"""GD-01/SEC-60..62: optional, public-only, bounded advisory JSON client."""

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, TypeVar, cast
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, model_validator
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.agents.fundamentals import FundamentalReport
from backend.agents.llm_budget import LLMBudget
from backend.agents.prompts import Prompt, load_prompt
from backend.core.clock import Clock
from backend.core.config import Settings
from backend.core.content import injection_suspect, sanitize_text
from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier, Notifier
from backend.domain.models import FrozenModel, Identifier, SentimentSignal, Symbol
from backend.net.egress import EgressPolicy
from backend.net.http import make_llm_sdk_client


class PublicHeadline(FrozenModel):
    stable_id: str = Field(strict=True, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    headline: str = Field(strict=True, min_length=1, max_length=280)


class PublicResearchInput(FrozenModel):
    """Finite whitelist: no tools, portfolio, balances, quantities or secrets."""

    ticker: Symbol
    headlines: tuple[PublicHeadline, ...] = Field(default=(), max_length=50)
    public_fundamentals: FundamentalReport | None = None
    public_filing_ids: tuple[str, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def provenance(self) -> "PublicResearchInput":
        if len({row.stable_id for row in self.headlines}) != len(self.headlines):
            raise ValueError("duplicate public headline identifiers")
        if len(set(self.public_filing_ids)) != len(self.public_filing_ids):
            raise ValueError("duplicate public filing identifiers")
        if any(
            not identifier
            or len(identifier) > 100
            or any(not (char.isascii() and (char.isalnum() or char in "_-")) for char in identifier)
            for identifier in self.public_filing_ids
        ):
            raise ValueError("filing identifiers require bounded plain public identifiers")
        if self.public_fundamentals is not None and self.public_fundamentals.symbol != self.ticker:
            raise ValueError("public fundamental report belongs to another ticker")
        return self


class Narrative(FrozenModel):
    summary: str = Field(strict=True, min_length=1, max_length=280)
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=50)


Validated = TypeVar("Validated", SentimentSignal, Narrative)


@dataclass(frozen=True, slots=True)
class RawCompletion:
    content: str | None
    usage: tuple[int, int] | None = None


class TransientLLMError(ProviderError):
    """Only transient transport errors qualify for bounded application retries."""


class CompletionTransport(Protocol):
    async def complete(self, prompt: Prompt, data: str) -> RawCompletion: ...
    async def aclose(self) -> None: ...


class SDKTransport:
    """One compatible SDK path for every configured provider, no hidden retries."""

    def __init__(self, settings: Settings, policy: EgressPolicy) -> None:
        settings.assert_llm_call_budget_ready()
        if any(name.startswith("OPENAI_") and value for name, value in os.environ.items()):
            raise ConfigurationError(
                "GD-01: ambient OPENAI_* settings must be removed; configure only LLM_* values"
            )
        if settings.llm_base_url is None:
            raise ConfigurationError("GD-01: missing configured LLM URL")
        # VERIFY: installed openai3.24 _base_client accepts legacy httpx.AsyncClient.
        # VERIFY: https://developers.openai.com/api/reference/python
        from openai import AsyncOpenAI

        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            organization="",
            project="",
            admin_api_key="",
            webhook_secret="",  # nosec B106
            max_retries=0,
            timeout=float(settings.llm_timeout_seconds),
            http_client=cast(
                Any,
                make_llm_sdk_client(
                    settings.llm_base_url, settings.llm_timeout_seconds, policy=policy
                ),
            ),
        )

    async def complete(self, prompt: Prompt, data: str) -> RawCompletion:
        from openai import APIConnectionError, APIStatusError

        if self.settings.llm_model_name is None:
            raise ConfigurationError("GD-01: missing configured model")
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.llm_model_name,
                temperature=0,
                max_tokens=self.settings.llm_max_tokens,
                stream=False,
                messages=[
                    {"role": "system", "content": prompt.text},
                    {"role": "user", "content": data},
                ],
            )
        except APIConnectionError as exc:
            if isinstance(exc.__cause__, ProviderError):
                raise ProviderError("LLM HTTP safety boundary refused request") from None
            raise TransientLLMError("LLM transport unavailable") from None
        except APIStatusError as exc:
            if exc.status_code == 429 or 500 <= exc.status_code <= 599:
                raise TransientLLMError("LLM service temporarily unavailable") from None
            raise ProviderError("LLM service refused request") from None
        content = response.choices[0].message.content if len(response.choices) == 1 else None
        usage = (
            None
            if response.usage is None
            else (response.usage.prompt_tokens, response.usage.completion_tokens)
        )
        return RawCompletion(content, usage)

    async def aclose(self) -> None:
        await self.client.close()


def _json_object(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > 32_768:
        raise ValueError("unbounded LLM JSON")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in items:
            if name in result:
                raise ValueError("duplicate JSON keys")
            result[name] = value
        return result

    def nonfinite(_: str) -> None:
        raise ValueError("nonfinite JSON")

    value = json.loads(text, parse_float=Decimal, parse_constant=nonfinite, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


class LLMClient:
    """Reservations cover each physical attempt; validated results are cached.

    Identical concurrent inputs share one flight. One invalid-JSON retry is
    permitted; transient failures have at most three physical attempts total.
    No additional instructions are constructed in application source.
    """

    def __init__(
        self,
        settings: Settings,
        ledger: Ledger,
        clock: Clock,
        *,
        policy: EgressPolicy | None = None,
        transport: CompletionTransport | None = None,
        notifier: Notifier | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        self.ledger, self.clock = ledger, clock
        self.policy, self._transport = policy, transport
        self.budget = LLMBudget(ledger, clock, self.settings, notifier or ConsoleNotifier())
        self.sleep = sleep
        self._cache: dict[str, SentimentSignal | Narrative | None] = {}
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}

    async def aclose(self) -> None:
        if self._transport is not None:
            await self._transport.aclose()

    async def complete_json(
        self, prompt_name: str, input_data: PublicResearchInput, output_model: type[Validated]
    ) -> Validated | None:
        expected: type[SentimentSignal] | type[Narrative] = (
            SentimentSignal if prompt_name == "news_sentiment" else Narrative
        )
        if output_model is not expected or not isinstance(input_data, PublicResearchInput):
            raise DataIntegrityError(
                "SEC-61: only typed public input and advisory output are allowed"
            )
        evidence = PublicResearchInput.model_validate(input_data)
        prompt = load_prompt(prompt_name)
        if not self.settings.llm_enabled or (
            not evidence.headlines and evidence.public_fundamentals is None
        ):
            return None
        if prompt_name == "fundamental_analyst" and evidence.public_fundamentals is None:
            return None
        # Reject every string that is flagged or would change on sanitization.
        texts = tuple(row.headline for row in evidence.headlines)
        if evidence.public_fundamentals is not None:
            texts += (
                tuple(metric.note for metric in evidence.public_fundamentals.metrics)
                + evidence.public_fundamentals.failure_reasons
            )
        if any(
            injection_suspect(text, frozenset()) or sanitize_text(text) != text for text in texts
        ):
            digest = hashlib.sha256(evidence.model_dump_json().encode("utf-8")).hexdigest()
            await asyncio.to_thread(
                self.ledger.append,
                SecurityEvent,
                kind="PROMPT_INJECTION_SUSPECT",
                detail={"public_input_sha256": digest},
            )
            return None
        canonical = json.dumps(
            evidence.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        if len(canonical) > 65_536:
            raise DataIntegrityError("SEC-61: public evidence exceeds bounded input")
        key = hashlib.sha256((prompt.prompt_hash + canonical).encode("utf-8")).hexdigest()
        lock, users = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, users + 1)
        try:
            async with lock:
                if key in self._cache:
                    cached = self._cache[key]
                    return None if cached is None else output_model.model_validate(cached)
                result = await self._call(prompt, canonical, evidence, output_model)
                if len(self._cache) >= 1024:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = result
                return result
        finally:
            active = self._locks[key][1] - 1
            if active:
                self._locks[key] = (lock, active)
            else:
                self._locks.pop(key)

    async def _call(
        self,
        prompt: Prompt,
        canonical: str,
        evidence: PublicResearchInput,
        output_model: type[Validated],
    ) -> Validated | None:
        if self._transport is None:
            if self.policy is None:
                raise ConfigurationError("SEC-31: optional LLM requires explicit egress policy")
            self._transport = SDKTransport(self.settings, self.policy)
        host = urlsplit(self.settings.llm_base_url or "").hostname
        if host is None:
            raise ConfigurationError("GD-01: missing configured hostname")
        # Conservative upper estimate includes UTF-8 bytes, message framing and
        # data delimiters. No tokenizer/model-specific dependency is required.
        data = "<untrusted_data>\n" + canonical + "\n</untrusted_data>"
        estimate = 4 * len((prompt.text + data).encode("utf-8")) + 4096
        transport = self._transport
        invalid_attempts, physical_attempts = 0, 0

        async def attempt_group() -> Validated | None:
            nonlocal invalid_attempts, physical_attempts
            while physical_attempts < 3:
                physical_attempts += 1
                reservation = await asyncio.to_thread(
                    self.budget.reserve, estimate, prompt.prompt_hash, host
                )
                if reservation is None:
                    return None
                started = asyncio.get_running_loop().time()
                outcome, usage = "TIMEOUT", None
                result: Validated | None = None
                transient, cancelled, unexpected = False, False, False
                try:
                    async with asyncio.timeout(self.settings.llm_timeout_seconds):
                        raw = await transport.complete(prompt, data)
                    outcome = "INVALID"
                    if not isinstance(raw, RawCompletion):
                        raise ValueError("untyped completion response")
                    if raw.usage is not None and (
                        not isinstance(raw.usage, tuple)
                        or len(raw.usage) != 2
                        or any(
                            type(count) is not int or not 0 <= count <= 10_000_000
                            for count in raw.usage
                        )
                    ):
                        await asyncio.to_thread(
                            self.ledger.append,
                            SecurityEvent,
                            kind="LLM_BAD_USAGE",
                            detail={"prompt_hash": prompt.prompt_hash},
                        )
                        raise ValueError("invalid token usage; retaining reserved estimate")
                    usage = raw.usage
                    if raw.content is not None:
                        value = _json_object(raw.content)
                        candidate = output_model.model_validate(value)
                        ids = (
                            candidate.evidence_headline_ids
                            if isinstance(candidate, SentimentSignal)
                            else candidate.evidence_ids
                        )
                        allowed = {row.stable_id for row in evidence.headlines}
                        if isinstance(candidate, Narrative):
                            allowed.update(evidence.public_filing_ids)
                        if not ids or len(ids) != len(set(ids)) or not set(ids).issubset(allowed):
                            raise ValueError("invented or absent evidence identifiers")
                        if candidate.summary != sanitize_text(
                            candidate.summary
                        ) or injection_suspect(candidate.summary, frozenset()):
                            await asyncio.to_thread(
                                self.ledger.append,
                                SecurityEvent,
                                kind="LLM_OUTPUT_INJECTION",
                                detail={
                                    "response_sha256": hashlib.sha256(
                                        raw.content.encode("utf-8")
                                    ).hexdigest()
                                },
                            )
                            raise ValueError("unsafe advisory summary")
                        result, outcome = candidate, "VALID"
                except asyncio.CancelledError:
                    cancelled = True
                except (TimeoutError, TransientLLMError):
                    transient = True
                except (ValueError, ValidationError, ProviderError, TypeError, ArithmeticError):
                    pass
                except Exception:
                    unexpected, outcome = True, "INVALID"
                latency_ms = max(0, int((asyncio.get_running_loop().time() - started) * 1000))
                accountable = await asyncio.shield(
                    asyncio.to_thread(
                        self.budget.settle,
                        reservation,
                        usage=usage,
                        latency_ms=latency_ms,
                        outcome=outcome,
                    )
                )
                if cancelled:
                    raise asyncio.CancelledError
                if unexpected:
                    raise DataIntegrityError(
                        "GD-01: unexpected completion failure; reservation settled"
                    )
                if result is not None and accountable:
                    return result
                if not accountable:
                    return None
                if transient:
                    raise TransientLLMError("LLM transport temporarily unavailable")
                invalid_attempts += 1
                if invalid_attempts >= 2 or outcome == "TIMEOUT":
                    return None
            return None

        try:
            return await AsyncRetrying(
                retry=retry_if_exception_type(TransientLLMError),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.1, max=0.2),
                sleep=self.sleep,
                reraise=True,
            )(attempt_group)
        except TransientLLMError:
            return None


class FakeLLMClient:
    """GD-08: offline public-only fixture client, never constructs an SDK."""

    async def complete_json(
        self, prompt_name: str, input_data: PublicResearchInput, output_model: type[Validated]
    ) -> Validated | None:
        load_prompt(prompt_name)
        evidence = PublicResearchInput.model_validate(input_data)
        expected: type[SentimentSignal] | type[Narrative] = (
            SentimentSignal if prompt_name == "news_sentiment" else Narrative
        )
        if output_model is not expected:
            raise DataIntegrityError("SEC-61: fake accepts the prompt's advisory output only")
        if any(
            injection_suspect(row.headline, frozenset())
            or row.headline != sanitize_text(row.headline)
            for row in evidence.headlines
        ):
            return None
        if not evidence.headlines:
            return None
        ids = (evidence.headlines[0].stable_id,)
        values: dict[str, object] = {"summary": evidence.headlines[0].headline}
        if output_model is SentimentSignal:
            values.update(score=Decimal(0), classification="NOISE", evidence_headline_ids=ids)
        elif output_model is Narrative:
            values["evidence_ids"] = ids
        else:
            raise DataIntegrityError("SEC-61: fake accepts advisory outputs only")
        return output_model.model_validate(values)
