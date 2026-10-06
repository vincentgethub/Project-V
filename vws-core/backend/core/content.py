"""SEC-60..62: deterministic treatment of untrusted public text."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger

_URL = re.compile(r"(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>]+", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")
_INSTRUCTIONS = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior)|system\s+prompt|"
    r"(?:^|\n)\s*(?:system|assistant|developer|user)\s*:",
    re.IGNORECASE,
)


def sanitize_text(value: str, *, limit: int = 280) -> str:
    """SEC-60: strip display markup/links/control characters, then bound text."""
    if not isinstance(value, str) or type(limit) is not int or not 1 <= limit <= 280:
        raise DataIntegrityError("SEC-60: public display text or cap is invalid")
    if len(value) > 100_000:
        raise DataIntegrityError("SEC-60: untrusted text exceeds the input boundary")
    text = html.unescape(value)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = _URL.sub("", _TAG.sub("", text))
    text = "".join(
        " " if character.isspace() else character
        for character in text
        if unicodedata.category(character) not in {"Cf", "Cs"}
        and (unicodedata.category(character) != "Cc" or character.isspace())
    )
    text = re.sub(r"[`*_~\[\]{}#>|]", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    return " ".join(text.split())[:limit].rstrip()


def headline_digest(value: str) -> str:
    """DAT-09: one normalized public-headline identity across all providers."""
    normalized = " ".join(unicodedata.normalize("NFKC", sanitize_text(value)).casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def headline_stable_id(provider: str, provider_id: str | None, digest: str) -> str:
    """DAT-09: bind a stable citation to its provider ID or headline digest."""
    identity = provider + (
        "\0id\0" + provider_id if provider_id is not None else "\0headline\0" + digest
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def injection_suspect(value: str, allowed_hosts: frozenset[str]) -> bool:
    """SEC-62: public facts never grant authority to embedded instructions."""
    if not isinstance(value, str) or not isinstance(allowed_hosts, frozenset):
        raise DataIntegrityError("SEC-62: untrusted input or host inventory is invalid")
    if len(value) > 100_000 or any(not isinstance(host, str) for host in allowed_hosts):
        raise DataIntegrityError("SEC-62: input or host inventory exceeds its boundary")
    decoded = html.unescape(value)
    if _INSTRUCTIONS.search(decoded) or _TAG.search(decoded):
        return True
    for match in _URL.finditer(decoded):
        link = match.group()
        if link.casefold().startswith("www."):
            link = "https://" + link
        try:
            parsed = urlsplit(link)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in allowed_hosts
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 443}
            ):
                return True
        except ValueError:
            return True
    return False


@dataclass(frozen=True)
class PreparedHeadline:
    """SEC-62: a flagged headline can be displayed but never sent for summary."""

    headline: str
    summary_allowed: bool


def prepare_headline(value: str, allowed_hosts: frozenset[str], ledger: Ledger) -> PreparedHeadline:
    """SEC-62: retain bounded bare headlines and permanent injection evidence."""
    flagged = injection_suspect(value, allowed_hosts)
    if flagged:
        ledger.append(
            SecurityEvent,
            kind="PROMPT_INJECTION_SUSPECT",
            detail={"headline_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()},
        )
    return PreparedHeadline(sanitize_text(value), not flagged)


def public_llm_payload(
    *, ticker: str, headlines: tuple[str, ...], public_fundamentals: dict[str, str] | None = None
) -> dict[str, object]:
    """SEC-61: only named public evidence crosses the LLM input boundary."""
    if not isinstance(ticker, str) or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker) is None:
        raise DataIntegrityError("SEC-61: public ticker is invalid")
    if not isinstance(headlines, tuple) or len(headlines) > 50:
        raise DataIntegrityError("SEC-61: public headlines require a bounded immutable inventory")
    facts = {} if public_fundamentals is None else public_fundamentals
    allowed = {
        "gross_margin",
        "operating_margin",
        "roic",
        "free_cash_flow",
        "interest_coverage",
        "period_end",
        "filed",
        "basis",
        "source",
        "framework_status",
    }
    if not isinstance(facts, dict) or not set(facts).issubset(allowed):
        raise DataIntegrityError("SEC-61: only public fundamental fields are permitted")
    return {
        "ticker": ticker,
        "untrusted_news": tuple(
            f"<untrusted_news>{sanitize_text(item)}</untrusted_news>" for item in headlines
        ),
        "public_fundamentals": {key: sanitize_text(value) for key, value in facts.items()},
    }
