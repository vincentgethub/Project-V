"""GD-01: atomic, append-only daily reservations and actual-usage settlement."""

from datetime import date
from decimal import ROUND_CEILING, Decimal, localcontext
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import LLMCall, SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.notifier import Notifier
from backend.domain.models import FrozenModel, Money

_NY = ZoneInfo("America/New_York")
_MICRO = Decimal("0.000001")
_MILLION = Decimal(1_000_000)
_KINDS = ("LLM_RESERVED", "LLM_SETTLED", "LLM_BUDGET_EXHAUSTED")


def token_cost(
    input_tokens: int, output_tokens: int, input_rate: Decimal, output_rate: Decimal
) -> Decimal:
    if any(
        type(count) is not int or not 0 <= count <= 10_000_000
        for count in (input_tokens, output_tokens)
    ):
        raise DataIntegrityError("GD-01: token usage must be bounded nonnegative integers")
    if any(
        not isinstance(rate, Decimal) or not rate.is_finite() or not 0 <= rate <= 1000
        for rate in (input_rate, output_rate)
    ):
        raise DataIntegrityError("GD-01: unknown or invalid token prices")
    with localcontext() as context:
        context.prec = 80
        return ((input_tokens * input_rate + output_tokens * output_rate) / _MILLION).quantize(
            _MICRO, rounding=ROUND_CEILING
        )


class Reservation(FrozenModel):
    reservation_id: UUID
    day: date
    amount: Money = Field(ge=0)
    input_estimate: int = Field(strict=True, ge=0, le=10_000_000)
    output_estimate: int = Field(strict=True, ge=0, le=8192)
    input_rate: Money = Field(ge=0, le=1000)
    output_rate: Money = Field(ge=0, le=1000)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=253)

    @model_validator(mode="after")
    def exact_reservation(self) -> "Reservation":
        if self.amount != token_cost(
            self.input_estimate, self.output_estimate, self.input_rate, self.output_rate
        ):
            raise ValueError("reserved amount must match its token bounds and exact prices")
        return self


class Settlement(FrozenModel):
    reservation_id: UUID
    day: date
    amount: Money = Field(ge=0)
    usage_estimated: bool = Field(strict=True)
    input_tokens: int = Field(strict=True, ge=0, le=10_000_000)
    output_tokens: int = Field(strict=True, ge=0, le=10_000_000)


class LLMBudget:
    """A crashed call retains its reservation; no refund or ledger mutation."""

    def __init__(
        self, ledger: Ledger, clock: Clock, settings: Settings, notifier: Notifier
    ) -> None:
        self.ledger, self.clock, self.settings, self.notifier = (
            ledger,
            clock,
            Settings.validated_copy(settings),
            notifier,
        )

    def _rows(
        self, session: Session, day: date
    ) -> tuple[dict[UUID, Reservation], dict[UUID, Settlement], bool]:
        reservations: dict[UUID, Reservation] = {}
        settlements: dict[UUID, Settlement] = {}
        exhausted = False
        for row in session.scalars(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind.in_(_KINDS),
                SecurityEvent.detail["day"].as_string() == day.isoformat(),
            )
            .order_by(SecurityEvent.seq)
        ):
            if row.kind == "LLM_RESERVED":
                reservation = Reservation.model_validate(row.detail)
                if reservation.reservation_id in reservations:
                    raise DataIntegrityError("GD-01: duplicated budget reservation")
                reservations[reservation.reservation_id] = reservation
            elif row.kind == "LLM_SETTLED":
                settlement = Settlement.model_validate(row.detail)
                if (
                    settlement.reservation_id not in reservations
                    or settlement.reservation_id in settlements
                ):
                    raise DataIntegrityError("GD-01: settlement lacks a unique reservation")
                original = reservations[settlement.reservation_id]
                if settlement.amount != token_cost(
                    settlement.input_tokens,
                    settlement.output_tokens,
                    original.input_rate,
                    original.output_rate,
                ):
                    raise DataIntegrityError("GD-01: settlement does not match token costs")
                if settlement.usage_estimated and (
                    settlement.input_tokens,
                    settlement.output_tokens,
                ) != (original.input_estimate, original.output_estimate):
                    raise DataIntegrityError(
                        "GD-01: estimated settlement differs from reservation bounds"
                    )
                settlements[settlement.reservation_id] = settlement
            else:
                exhausted = True
        return reservations, settlements, exhausted

    def reserve(self, input_estimate: int, prompt_hash: str, host: str) -> Reservation | None:
        self.settings.assert_llm_call_budget_ready()
        if (
            self.settings.llm_model_name is None
            or self.settings.llm_input_cost_per_million_usd is None
            or self.settings.llm_output_cost_per_million_usd is None
        ):
            raise DataIntegrityError("GD-01: incomplete configured prices/model")
        day = ensure_utc(self.clock.now()).astimezone(_NY).date()
        candidate = Reservation(
            reservation_id=uuid4(),
            day=day,
            input_estimate=input_estimate,
            output_estimate=self.settings.llm_max_tokens,
            input_rate=self.settings.llm_input_cost_per_million_usd,
            output_rate=self.settings.llm_output_cost_per_million_usd,
            amount=token_cost(
                input_estimate,
                self.settings.llm_max_tokens,
                self.settings.llm_input_cost_per_million_usd,
                self.settings.llm_output_cost_per_million_usd,
            ),
            prompt_hash=prompt_hash,
            model=self.settings.llm_model_name,
            host=host,
        )
        notify = False
        with transaction(self.ledger.engine) as session:
            reservations, settlements, exhausted = self._rows(session, day)
            with localcontext() as context:
                context.prec = 80
                committed = sum(
                    (
                        settlements[item].amount if item in settlements else row.amount
                        for item, row in reservations.items()
                    ),
                    Decimal(0),
                )
                refused = (
                    exhausted or committed + candidate.amount > self.settings.llm_daily_budget_usd
                )
            if refused:
                if not exhausted:
                    self.ledger.append_in_session(
                        session,
                        SecurityEvent,
                        kind="LLM_BUDGET_EXHAUSTED",
                        detail={"day": day.isoformat()},
                    )
                    notify = True
                self.ledger.append_in_session(
                    session,
                    LLMCall,
                    provider="openai-compatible",
                    base_url_host=host,
                    model=candidate.model,
                    prompt_hash=prompt_hash,
                    input_tokens=0,
                    output_tokens=0,
                    est_cost_usd=Decimal(0),
                    latency_ms=0,
                    outcome="BUDGET",
                )
            else:
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="LLM_RESERVED",
                    detail=candidate.model_dump(mode="json"),
                )
        if notify:
            self.notifier.notify(
                "LLM_DISABLED", "Daily LLM budget exhausted; public summaries unavailable"
            )
        return None if refused else candidate

    def settle(
        self,
        reservation: Reservation,
        *,
        usage: tuple[int, int] | None,
        latency_ms: int,
        outcome: str,
    ) -> bool:
        """Retain estimated cost if usage is absent; settlement is single-use.

        Usage outside the requested bounds is still charged as reported, marked
        anomalous, and blocks subsequent calls for the day. It never earns a pass.
        """
        reservation = Reservation.model_validate(reservation)
        counts = (
            (reservation.input_estimate, reservation.output_estimate) if usage is None else usage
        )
        amount = token_cost(*counts, reservation.input_rate, reservation.output_rate)
        anomalous = amount > reservation.amount or counts[1] > reservation.output_estimate
        notify = False
        with transaction(self.ledger.engine) as session:
            reservations, settlements, exhausted = self._rows(session, reservation.day)
            if (
                reservations.get(reservation.reservation_id) != reservation
                or reservation.reservation_id in settlements
            ):
                raise DataIntegrityError("GD-01: reservation mismatch or replayed settlement")
            self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="LLM_SETTLED",
                detail=Settlement(
                    reservation_id=reservation.reservation_id,
                    day=reservation.day,
                    amount=amount,
                    usage_estimated=usage is None,
                    input_tokens=counts[0],
                    output_tokens=counts[1],
                ).model_dump(mode="json"),
            )
            self.ledger.append_in_session(
                session,
                LLMCall,
                provider="openai-compatible",
                base_url_host=reservation.host,
                model=reservation.model,
                prompt_hash=reservation.prompt_hash,
                input_tokens=counts[0],
                output_tokens=counts[1],
                est_cost_usd=amount,
                latency_ms=latency_ms,
                outcome="INVALID" if anomalous else outcome,
            )
            if anomalous and not exhausted:
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="LLM_BUDGET_EXHAUSTED",
                    detail={
                        "day": reservation.day.isoformat(),
                        "reason": "provider_usage_exceeded_reservation",
                    },
                )
                notify = True
        if notify:
            self.notifier.notify(
                "LLM_DISABLED",
                "Provider usage exceeded reservation; public summaries disabled for the day",
            )
        return not anomalous
