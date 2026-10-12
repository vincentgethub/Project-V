"""EG integration: sealed submissions, causal cached arrays and isolated grades."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.agents.earnings_gap import evaluate_earnings_gap
from backend.agents.indicators import IndicatorMemo, IndicatorSeries
from backend.core.config import YamlConfig, load_yaml_config
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.earnings_reports import EarningsReport
from backend.data.frozen_filings import FilingEvidence, FrozenFilings, load_filings, seal_filings
from backend.data.history import HistorySeries
from backend.data.market_calendar import MarketCalendar
from backend.data.sec_edgar import SecPayload
from backend.domain.instruments import InstrumentRegistry
from backend.indicators.replay import precompute_symbol
from backend.tests.test_v_connections import calendar as source_calendar
from backend.tests.test_v_connections import earnings as source_earnings
from backend.tests.test_v_connections import registry as source_registry

calendar, earnings, registry = source_calendar, source_earnings, source_registry
EarningsFixture = tuple[tuple[Bar, ...], IndicatorSeries, tuple[Bar, ...], EarningsReport]

PROJECT = Path(__file__).resolve().parents[2]


def policy(registry: InstrumentRegistry) -> YamlConfig:
    values = load_yaml_config(
        PROJECT / "config/config.yaml", allowed_symbols=registry.symbols
    ).model_dump()
    values["playbooks"]["enabled"] = ["EARNINGS_GAP"]
    return YamlConfig.model_validate(values)


def test_EG_precomputed_arrays_equal_native_causal_hunter(
    calendar: MarketCalendar,
    registry: InstrumentRegistry,
    earnings: EarningsFixture,
) -> None:
    bars, _, spy, report = earnings
    config = policy(registry)
    arrays = precompute_symbol(
        HistorySeries(symbol="NVDA", adjustment="RAW", bars=bars),
        (),
        config,
        "a" * 64,
        instrument=registry.get("NVDA"),
        earnings_reports=(report,),
        spy_returns=HistorySeries(symbol="SPY", adjustment="ALL", bars=spy),
        stock_returns=HistorySeries(symbol="NVDA", adjustment="ALL", bars=bars),
        calendar=calendar,
    )
    for index in (208, 209):
        prefix, benchmark = bars[: index + 1], spy[: index + 1]
        found = evaluate_earnings_gap(
            registry.get("NVDA"),
            prefix,
            IndicatorMemo().calculate("NVDA", prefix, 0),
            benchmark,
            (report,),
            config.sizing,
            calendar.session_close(prefix[-1].session_date) + timedelta(minutes=16),
            calendar,
            stock_return_bars=prefix,
        )
        assert found is not None and arrays.days[index].evidence == (found,)
    assert arrays.days[207].evidence == (None,)


@pytest.mark.parametrize("missing", ["reports", "spy", "stock", "issuer"])
def test_EG_enabled_replay_refuses_missing_evidence(
    calendar: MarketCalendar,
    registry: InstrumentRegistry,
    earnings: EarningsFixture,
    missing: str,
) -> None:
    bars, _, spy, report = earnings
    with pytest.raises(DataIntegrityError):
        precompute_symbol(
            HistorySeries(symbol="NVDA", adjustment="RAW", bars=bars),
            (),
            policy(registry),
            "a" * 64,
            instrument=None if missing == "issuer" else registry.get("NVDA"),
            earnings_reports=None if missing == "reports" else (report,),
            spy_returns=None
            if missing == "spy"
            else HistorySeries(symbol="SPY", adjustment="ALL", bars=spy),
            stock_returns=None
            if missing == "stock"
            else HistorySeries(symbol="NVDA", adjustment="ALL", bars=bars),
            calendar=calendar,
        )


def test_EG_known_later_report_cannot_change_an_earlier_gate(
    calendar: MarketCalendar,
    registry: InstrumentRegistry,
    earnings: EarningsFixture,
) -> None:
    bars, _, spy, original = earnings
    later = EarningsReport.model_validate(
        {
            **original.model_dump(),
            "known_at": calendar.session_close(bars[-1].session_date) + timedelta(days=1),
        }
    )
    config = policy(registry)
    arrays = precompute_symbol(
        HistorySeries(symbol="NVDA", adjustment="RAW", bars=bars),
        (),
        config,
        "a" * 64,
        instrument=registry.get("NVDA"),
        earnings_reports=(later,),
        calendar=calendar,
        spy_returns=HistorySeries(symbol="SPY", adjustment="ALL", bars=spy),
        stock_returns=HistorySeries(symbol="NVDA", adjustment="ALL", bars=bars),
    )
    assert all(day.evidence == (None,) for day in arrays.days)


def submission(report: EarningsReport, cik: str = "0001045810") -> SecPayload:
    raw = json.dumps(
        {
            "cik": int(cik),
            "filings": {
                "recent": {
                    "form": ["8-K"],
                    "items": ["2.02,9.01"],
                    "acceptanceDateTime": [report.known_at.isoformat()],
                    "accessionNumber": [report.accession],
                }
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return SecPayload(
        kind="SUBMISSIONS",
        cik=cik,
        raw=raw,
        fetched_at=report.known_at + timedelta(days=7),
        data_sha256=hashlib.sha256(raw).hexdigest(),
    )


def test_EG_frozen_submissions_manifest_roundtrip_and_tamper(
    tmp_path: Path,
    earnings: EarningsFixture,
) -> None:
    report = earnings[-1]
    frozen = seal_filings(tmp_path, (FilingEvidence(symbol="NVDA", payload=submission(report)),))
    restored = load_filings(tmp_path)
    assert restored == frozen and restored.manifest.sha256 == frozen.manifest.sha256
    assert restored.for_symbol("NVDA") is None
    assert restored.for_symbol("NVDA", "SUBMISSIONS") == submission(report)
    (tmp_path / "NVDA_submissions.json").write_bytes(b"{}")
    with pytest.raises(DataIntegrityError):
        load_filings(tmp_path)


def test_EG_companyfacts_and_submissions_cannot_bind_different_issuers(
    tmp_path: Path,
    earnings: EarningsFixture,
) -> None:
    report = earnings[-1]
    raw = b'{"cik":1,"facts":{"us-gaap":{}}}'
    company = FilingEvidence(
        symbol="NVDA",
        payload=SecPayload(
            kind="COMPANYFACTS",
            cik="0000000001",
            fetched_at=report.known_at,
            raw=raw,
            data_sha256=hashlib.sha256(raw).hexdigest(),
        ),
    )
    sub = FilingEvidence(symbol="NVDA", payload=submission(report))
    assert sub.payload.cik is not None
    first = seal_filings(tmp_path, (company,))
    from backend.data.frozen_filings import FilingEntry, FilingsManifest

    entry = FilingEntry(
        symbol="NVDA",
        cik=sub.payload.cik,
        fetched_at=sub.payload.fetched_at,
        data_sha256=sub.payload.data_sha256,
        bytes=len(sub.payload.raw),
        filename="NVDA_submissions.json",
    )
    with pytest.raises(ValidationError, match="CIK"):
        FrozenFilings(
            manifest=FilingsManifest(entries=(*first.manifest.entries, entry)),
            evidence=(company, sub),
        )
