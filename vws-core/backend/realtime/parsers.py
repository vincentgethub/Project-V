"""RT-02..07: public data, fixed classifications, bounded untrusted text."""

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import wraps
from html.parser import HTMLParser
from typing import Any, Literal, ParamSpec, TypeVar
from uuid import UUID

# XML is bounded UTF-8 and declarations/entities are rejected before parsing.
from xml.etree import ElementTree  # nosec B405
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.domain.models import validate_symbol
from backend.realtime.models import RealtimeEvent

NY = ZoneInfo("America/New_York")
PERSISTENT = datetime(9999, 12, 31, tzinfo=UTC)
NEGATIVE = re.compile(
    r"\b(offering|dilution|fraud|going[ -]concern|fda.{0,20}reject\w*|downgrade cluster)\b", re.I
)
HALT = re.compile(r"\b(trading halt\w*|halted|luld|market[ -]wide circuit breaker)\b", re.I)
WATCH_FORMS = frozenset(
    {
        "8-K",
        "8-K/A",
        "4",
        "4/A",
        "SC 13D",
        "SC 13D/A",
        "SC 13G",
        "SC 13G/A",
        "13D",
        "13G",
        "S-3",
        "S-3/A",
    }
)

Arguments = ParamSpec("Arguments")
Result = TypeVar("Result")


def _public_parse(function: Callable[Arguments, Result]) -> Callable[Arguments, Result]:
    @wraps(function)
    def checked(*args: Arguments.args, **kwargs: Arguments.kwargs) -> Result:
        try:
            return function(*args, **kwargs)
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError("RT: public observation is malformed or unbound") from None

    return checked


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _plain_text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 50000:
        raise DataIntegrityError("RT-02: bounded public news text required")
    parser = _Text()
    parser.feed(value)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", " ".join(parser.parts))
    return re.sub(r"\s+", " ", text).strip() or "No public headline supplied"


def strip_html(value: object) -> str:
    return _plain_text(value)[:1000]


def timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        raise DataIntegrityError("RT: bounded explicit provider timestamp required")
    try:
        return ensure_utc(datetime.fromisoformat(value))
    except Exception:
        raise DataIntegrityError("RT: malformed provider timestamp") from None


@_public_parse
def news(payload: Mapping[str, Any], now: datetime) -> tuple[RealtimeEvent, ...]:
    instant = ensure_utc(now)
    if not isinstance(payload, Mapping):
        raise DataIntegrityError("RT-02: news article object required")
    identity, symbols = payload.get("id"), payload.get("symbols")
    if (
        isinstance(identity, bool)
        or not isinstance(identity, (int, str))
        or not 1 <= len(str(identity)) <= 100
        or not isinstance(symbols, (list, tuple))
        or len(symbols) > 1000
    ):
        raise DataIntegrityError("RT-02: bounded article identity and symbols required")
    headline, summary = payload.get("headline", ""), payload.get("summary", "")
    if not isinstance(headline, str) or not isinstance(summary, str):
        raise DataIntegrityError("RT-02: headline and summary must be text")
    complete = _plain_text(headline + " " + summary)
    kind = (
        "HALT_NEWS"
        if HALT.search(complete)
        else "NEWS_NEG"
        if NEGATIVE.search(complete)
        else "OTHER"
    )
    text = complete[:1000]
    occurred = timestamp(payload.get("created_at"))
    return tuple(
        RealtimeEvent.model_validate(
            {
                "feed": "news",
                "provider_id": f"news:{identity}",
                "kind": kind,
                "symbol": validate_symbol(symbol),
                "occurred_at": occurred,
                "observed_at": instant,
                "expires_at": occurred + timedelta(days=1),
                "text": text,
            }
        )
        for symbol in sorted(set(symbols))
    )


@_public_parse
def halt_rss(raw: bytes, now: datetime) -> tuple[RealtimeEvent, ...]:
    instant = ensure_utc(now)
    if type(raw) is not bytes or not 0 < len(raw) <= 1048576:
        raise DataIntegrityError("RT-03: bounded RSS without DTD or entities required")
    try:
        # Decode first so UTF-16/other encodings cannot hide a DTD from the
        # byte-level filter. Nasdaq publishes UTF-8 RSS; other encodings refuse.
        text = raw.decode("utf-8-sig")
        if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
            raise ValueError("DTD and entity declarations forbidden")
        root = ElementTree.fromstring(text)  # nosec B314
        if root.tag != "rss" or root.find("channel") is None:
            raise ValueError("RSS channel required")
        items = root.findall("channel/item")
        if len(items) > 10000:
            raise ValueError("RSS item bound")
        result = []
        for item in items:

            def field(name: str, item: ElementTree.Element = item) -> str:
                # XML namespace identifiers are document data, never egress
                # destinations. Match qualified local fields and reject aliases
                # or duplicate fields; the RSS source is fixed verified HTTPS.
                matches = [
                    child
                    for child in item
                    if child.tag.startswith("{") and child.tag.endswith("}" + name)
                ]
                if len(matches) > 1:
                    raise ValueError("duplicate qualified halt field")
                return ((matches[0].text or "") if matches else "").strip()

            def local(day: str, clock: str) -> datetime:
                naive = datetime.strptime(day + " " + clock.split(".")[0], "%m/%d/%Y %H:%M:%S")
                value = naive.replace(tzinfo=NY)
                if (
                    value.replace(fold=1).utcoffset() != value.utcoffset()
                    or value.astimezone(UTC).astimezone(NY) != value
                ):
                    raise ValueError("ambiguous RSS local time")
                return value.astimezone(UTC)

            symbol, code = field("IssueSymbol"), field("ReasonCode")
            if not code or len(code) > 20:
                raise ValueError("halt reason required")
            occurred = local(field("HaltDate"), field("HaltTime"))
            global_event = code in {"MWC1", "MWC2", "MWC3"}
            normalized = None if global_event else validate_symbol(symbol)
            identifier = f"rss:{symbol}:{code}:{occurred.isoformat()}"
            result.append(
                RealtimeEvent.model_validate(
                    {
                        "feed": "halts",
                        "provider_id": identifier,
                        "kind": code if global_event else "HALT",
                        "symbol": normalized,
                        "occurred_at": occurred,
                        "observed_at": instant,
                        "expires_at": datetime.combine(
                            occurred.astimezone(NY).date() + timedelta(days=1),
                            datetime.min.time(),
                            NY,
                        ).astimezone(UTC)
                        if global_event
                        else PERSISTENT,
                        "text": f"Nasdaq halt reason {code}",
                    }
                )
            )
            resumed = field("ResumptionTradeTime")
            if resumed and not global_event:
                resumed_at = local(field("ResumptionDate"), resumed)
                if resumed_at < occurred:
                    raise ValueError("resume precedes halt")
                result.append(
                    RealtimeEvent(
                        feed="halts",
                        provider_id=identifier + ":resume",
                        kind="RESUME",
                        symbol=normalized,
                        occurred_at=resumed_at,
                        observed_at=instant,
                        expires_at=PERSISTENT,
                        text=f"Nasdaq resumed after {code}",
                    )
                )
        return tuple(result)
    except Exception:
        raise DataIntegrityError("RT-03: halt RSS is malformed or unbound") from None


@_public_parse
def asset(payload: Mapping[str, Any], symbol: str, now: datetime) -> RealtimeEvent:
    validate_symbol(symbol)
    if (
        payload.get("symbol") != symbol
        or type(payload.get("tradable")) is not bool
        or payload.get("status") not in {"active", "inactive"}
    ):
        raise DataIntegrityError("RT-04: exact requested asset identity and status required")
    active = payload["tradable"] and payload["status"] == "active"
    return RealtimeEvent(
        feed="assets",
        provider_id=f"asset:{symbol}:{now.isoformat()}",
        kind="ASSET_ACTIVE" if active else "ASSET_INACTIVE",
        symbol=symbol,
        occurred_at=now,
        observed_at=now,
        expires_at=PERSISTENT,
        text="Asset active and tradable" if active else "Asset inactive or non-tradable",
    )


def submissions(
    payload: Mapping[str, Any], symbol: str, now: datetime, *, since: datetime
) -> tuple[RealtimeEvent, ...]:
    validate_symbol(symbol)
    try:
        recent = payload["filings"]["recent"]
        forms, accessions, accepted = (
            recent["form"],
            recent["accessionNumber"],
            recent["acceptanceDateTime"],
        )
        if not all(
            isinstance(values, list) and len(values) <= 10000
            for values in (forms, accessions, accepted)
        ) or not len(forms) == len(accessions) == len(accepted):
            raise ValueError("SEC aligned bounded arrays required")
        rows = []
        for form, accession, at in zip(forms, accessions, accepted, strict=True):
            if (
                not isinstance(form, str)
                or not isinstance(accession, str)
                or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession)
            ):
                raise ValueError("SEC form and accession required")
            occurred = timestamp(at)
            if occurred > now:
                raise ValueError("future filing")
            if occurred < since or form not in WATCH_FORMS and not form.startswith("424B"):
                continue
            rows.append(
                RealtimeEvent(
                    feed="edgar",
                    provider_id=f"sec:{accession}",
                    kind="DILUTION"
                    if form in {"S-3", "S-3/A"} or form.startswith("424B")
                    else "FILING",
                    symbol=symbol,
                    occurred_at=occurred,
                    observed_at=now,
                    expires_at=occurred + timedelta(days=1),
                    text=f"SEC form {form}; accession {accession}",
                )
            )
        return tuple(rows)
    except Exception:
        raise DataIntegrityError("RT-06: SEC recent submissions are malformed") from None


def fred(payload: Mapping[str, Any], now: datetime, expected_date: date) -> RealtimeEvent:
    try:
        observations = payload["observations"]
        if not isinstance(observations, list) or len(observations) != 1:
            raise ValueError("one latest FRED observation required")
        row = observations[0]
        observed_date = date.fromisoformat(row["date"])
        if observed_date != expected_date or not isinstance(row["value"], str):
            raise ValueError("FRED observation date differs from latest completed session")
        value = Decimal(row["value"])
        occurred = datetime.combine(
            observed_date, datetime.min.time().replace(hour=16), NY
        ).astimezone(UTC)
        return RealtimeEvent(
            feed="fred",
            provider_id=f"fred:VIXCLS:{observed_date}",
            kind="VIX",
            occurred_at=occurred,
            observed_at=now,
            expires_at=occurred + timedelta(days=7),
            value=value,
            text=f"FRED VIXCLS daily close {observed_date}",
        )
    except Exception:
        raise DataIntegrityError("RT-07: latest VIX daily close is missing or malformed") from None


def corporate_actions(
    payload: Mapping[str, Any], now: datetime, symbols: tuple[str, ...]
) -> tuple[RealtimeEvent, ...]:
    """RT-05: early incomplete records annotate; only confirmed removals exit."""
    try:
        groups = payload["corporate_actions"]
        if not isinstance(groups, Mapping) or len(groups) > 30:
            raise ValueError("bounded corporate-action groups required")
        result = []
        count = 0
        for group, records in groups.items():
            if not isinstance(group, str) or len(group) > 64 or not isinstance(records, list):
                raise ValueError("typed corporate-action list required")
            count += len(records)
            if count > 1000:
                raise ValueError("corporate-action count exceeds requested bound")
            for record in records:
                if not isinstance(record, Mapping) or len(record) > 100:
                    raise ValueError("bounded corporate-action record required")
                identity = str(UUID(record["id"]))
                symbol = record.get(
                    "symbol",
                    record.get(
                        "old_symbol", record.get("acquiree_symbol", record.get("source_symbol"))
                    ),
                )
                validate_symbol(symbol)
                if symbol not in symbols:
                    raise ValueError("corporate-action symbol was not requested")
                raw_date = record.get("process_date")
                process = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
                confirmed = process is not None and process <= now.astimezone(NY).date()
                occurred = (
                    datetime.combine(process, datetime.min.time(), NY).astimezone(UTC)
                    if confirmed and process is not None
                    else now
                )
                kind: Literal["DELIST", "CA_PENDING"] = (
                    "DELIST" if group == "worthless_removals" and confirmed else "CA_PENDING"
                )
                digest = hashlib.sha256(
                    json.dumps(
                        dict(record), sort_keys=True, separators=(",", ":"), default=str
                    ).encode("utf-8")
                ).hexdigest()[:16]
                result.append(
                    RealtimeEvent(
                        feed="ca",
                        provider_id=f"ca:{identity}:{digest}",
                        kind=kind,
                        symbol=symbol,
                        occurred_at=occurred,
                        observed_at=now,
                        expires_at=PERSISTENT,
                        text=f"Corporate action {group}; {'confirmed process date' if confirmed else 'early/incomplete confirmation'}; delayed provider data",
                    )
                )
        return tuple(result)
    except Exception:
        raise DataIntegrityError("RT-05: corporate-action confirmation is malformed") from None
