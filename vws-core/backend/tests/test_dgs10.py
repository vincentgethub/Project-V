"""Item 6: FRED DGS10 yield spikes can only reduce or block new entries."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import EventsPolicy, RealtimeConfig
from backend.core.errors import DataIntegrityError, ProviderError
from backend.realtime import parsers
from backend.realtime.models import ContextTag, RealtimeEvent
from backend.realtime.policy import context
from backend.realtime.reader import RealtimeReader
from backend.tests.test_read_checks import client
from backend.tests.test_w_core import CAL, HASH, SCOPE, health

NOW = datetime(2026, 9, 29, 21, tzinfo=UTC)
DAY = date(2026, 9, 29)


def payload(*rows: tuple[str, str]) -> dict[str, object]:
    return {"observations": [{"date": day, "value": value} for day, value in rows]}


def rates(clock: FrozenClock, rise_bps: str) -> RealtimeEvent:
    return RealtimeEvent(
        feed="fred",
        provider_id="fred:DGS10:fixture",
        kind="DGS10",
        occurred_at=clock.now(),
        observed_at=clock.now(),
        expires_at=clock.now().replace(year=2027),
        value=Decimal(rise_bps),
    )


def decide(
    clock: FrozenClock,
    events: tuple[RealtimeEvent, ...],
    *,
    auto: bool = True,
    action: str = "half_size",
    vix: str = "half_size",
    fred_ok: bool = True,
) -> Any:
    rows = tuple(row for row in health(clock.now()) if fred_ok or row.feed != "fred")
    return context(
        SCOPE,
        "NVDA",
        clock.now(),
        HASH,
        RealtimeConfig(),
        EventsPolicy.model_validate({"dgs10_spike": action, "vix_stress": vix}),
        rows,
        events,
        (),
        CAL,
        auto=auto,
        schedules_verified=True,
    )


def test_DGS10_parser_reports_only_the_rise_in_basis_points() -> None:
    up = parsers.dgs10(payload(("2026-09-29", "4.60"), ("2026-09-28", "4.40")), NOW, DAY)
    assert up.kind == "DGS10" and up.value == 20 and up.symbol is None
    assert "4.60" in up.text and "4.40" in up.text
    skipped = parsers.dgs10(
        payload(("2026-09-29", "4.41"), ("2026-09-28", "."), ("2026-09-25", "4.40")), NOW, DAY
    )
    assert skipped.value == 1
    down = parsers.dgs10(payload(("2026-09-29", "4.20"), ("2026-09-28", "4.40")), NOW, DAY)
    assert down.value == 0


@pytest.mark.parametrize(
    "body",
    [
        payload(("2026-09-29", "."), ("2026-09-28", "4.40"), ("2026-09-25", "4.30")),
        payload(("2026-09-28", "4.60"), ("2026-09-25", "4.40")),
        payload(("2026-09-29", "4.60")),
        payload(("2026-09-29", "4.60"), ("2026-09-28", "NaN")),
        payload(("2026-09-29", "-1"), ("2026-09-28", "4.40")),
        payload(("2026-09-28", "4.40"), ("2026-09-29", "4.60")),
        payload(*((f"2026-09-{29 - n:02d}", "4.40") for n in range(11))),
        {"observations": "4.60"},
        {},
    ],
)
def test_DGS10_missing_stale_or_malformed_data_fails_closed(body: dict[str, object]) -> None:
    with pytest.raises(DataIntegrityError):
        parsers.dgs10(body, NOW, DAY)


def test_DGS10_event_is_global_and_valued(clock: FrozenClock) -> None:
    with pytest.raises(ValidationError):
        RealtimeEvent.model_validate({**rates(clock, "1").model_dump(), "value": None})
    with pytest.raises(ValidationError):
        RealtimeEvent.model_validate({**rates(clock, "1").model_dump(), "symbol": "NVDA"})


def test_DGS10_policy_has_no_neutral_action_and_threshold_only_tightens() -> None:
    assert EventsPolicy().dgs10_spike == "half_size"
    assert RealtimeConfig().dgs10_spike_bps == 15
    with pytest.raises(ValidationError):
        EventsPolicy.model_validate({"dgs10_spike": "annotate"})
    for bound in (0, 16, "15.5x"):
        with pytest.raises(ValidationError):
            RealtimeConfig.model_validate({"dgs10_spike_bps": bound})
    assert RealtimeConfig.model_validate({"dgs10_spike_bps": 5}).dgs10_spike_bps == 5


@pytest.mark.parametrize(
    ("rise", "action", "expected"),
    [
        ("15", "half_size", Decimal("0.5")),
        ("40", "no_new_entries", Decimal(0)),
        ("14.99", "half_size", Decimal(1)),
        ("0", "no_new_entries", Decimal(1)),
    ],
)
def test_DGS10_spike_only_reduces_auto_entries(
    clock: FrozenClock, rise: str, action: str, expected: Decimal
) -> None:
    row = decide(clock, (rates(clock, rise),), action=action)
    assert row.entry_multiplier == expected
    assert (ContextTag.RATES_SPIKE in row.tags) == (Decimal(rise) >= 15)
    manual = decide(clock, (rates(clock, rise),), action=action, auto=False)
    assert manual.entry_multiplier == 1
    assert (ContextTag.RATES_SPIKE in manual.tags) == (Decimal(rise) >= 15)


@pytest.mark.parametrize("vix", ["annotate", "half_size"])
def test_DGS10_unverified_fred_blocks_auto_even_when_vix_only_annotates(
    clock: FrozenClock, vix: str
) -> None:
    row = decide(clock, (), vix=vix, fred_ok=False)
    assert row.blocked and ContextTag.UNAVAILABLE in row.tags
    assert any("DGS10" in line for line in row.warnings)
    manual = decide(clock, (), vix=vix, fred_ok=False, auto=False)
    assert not manual.blocked and manual.warnings


def fred_reader(clock: FrozenClock, key: SecretStr | None, dgs10: Any) -> Any:
    expected = CAL.last_completed_session(clock.now())

    async def vix(token: object) -> dict[str, object]:
        return payload((expected.isoformat(), "20"))

    reader: Any = RealtimeReader.__new__(RealtimeReader)
    reader.clock, reader.calendar = clock, CAL
    reader.fred_key = key
    reader.reads = SimpleNamespace(fred_observations=vix, fred_dgs10=dgs10)
    reader._fred_day, reader._cache = None, {}
    return reader, expected


@pytest.mark.asyncio
async def test_DGS10_reader_polls_both_series_and_fails_closed_without_either(
    clock: FrozenClock,
) -> None:
    calls: list[object] = []

    async def good(token: object) -> dict[str, object]:
        calls.append(token)
        return payload((expected.isoformat(), "4.60"), ("2026-09-25", "4.40"))

    key = SecretStr("PUBLIC_SYNTHETIC_FRED_FIXTURE")
    reader, expected = fred_reader(clock, key, good)
    health_row, events = await reader.poll("fred")
    assert health_row.feed == "fred" and [row.kind for row in events] == ["VIX", "DGS10"]
    assert events[1].value == 20 and calls == [key]

    async def broken(token: object) -> dict[str, object]:
        raise ProviderError("FRED DGS10 unavailable")

    reader, _ = fred_reader(clock, key, broken)
    with pytest.raises(ProviderError):
        await reader.poll("fred")
    reader, _ = fred_reader(clock, None, good)
    with pytest.raises(ProviderError, match="setup"):
        await reader.poll("fred")


@pytest.mark.asyncio
async def test_DGS10_read_is_bounded_official_and_masked(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload(("2026-10-06", "4.60"), ("2026-10-05", "4.40")))

    source = client(engine, clock, monkeypatch, handler)
    result = await source.fred_dgs10(SecretStr("TEST_ONLY_NOT_A_CREDENTIAL"))
    (request,) = seen
    assert request.url.host == "api.stlouisfed.org" and request.method == "GET"
    assert request.url.params["series_id"] == "DGS10"
    assert request.url.params["limit"] == "10" and request.url.params["sort_order"] == "desc"
    observations = result["observations"]
    assert isinstance(observations, list) and len(observations) == 2
