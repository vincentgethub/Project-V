"""EV/DQ hand-built goldens, independently recomputed exact P&L and hashes."""

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.agents.fundamentals import FrameworkStatus
from backend.core.config import EvaluationConfig
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.fee_schedule import load_fee_schedule
from backend.data.history import (
    FrozenHistory,
    HistoryBundle,
    HistoryManifest,
    HistorySeries,
    KnownSplit,
    ManifestEntry,
    canonical_bytes,
    load_history,
    seal_history,
    validate_history,
)
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import Playbook
from backend.evaluation.costs import CostContext, FeeSchedule
from backend.evaluation.outcomes import Outcome, OutcomeSetup, simulate_outcome

D = Decimal
START = date(2026, 9, 15)
ID = UUID("967af8df-6b23-4014-9860-843b8a8fe9e9")


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2026, 9, 1), end=date(2026, 11, 30))


@pytest.fixture(scope="module")
def schedule() -> FeeSchedule:
    return load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml")


def setup(**values: Any) -> OutcomeSetup:
    return OutcomeSetup.model_validate(
        {
            "alert_id": ID,
            "symbol": "AAPL",
            "playbook": Playbook.BASE_BREAKOUT,
            "cohort": "PAPER",
            "disposition": "APPROVED",
            "fundamentals_status": FrameworkStatus.PASS,
            "score": D(8),
            "qty": 100,
            "limit": D(101),
            "stop": D(95),
            "target": D(110),
            "decision_session": START,
            "valid_until_session": date(2026, 9, 17),
            **values,
        }
    )


def bar(
    day: int,
    *,
    opening: str = "100",
    high: str = "101",
    low: str = "99",
    closing: str = "100",
    volume: int = 20000,
) -> Bar:
    return Bar(
        timestamp=datetime(2026, 9, day, 4, tzinfo=UTC),
        open=D(opening),
        high=D(high),
        low=D(low),
        close=D(closing),
        volume=volume,
    )


def bundle(bars: tuple[Bar, ...], splits: tuple[KnownSplit, ...] = ()) -> HistoryBundle:
    factor = D(1)
    for action in splits:
        factor *= action.new_shares_per_old
    adjusted: list[Bar] = []
    actions = {action.effective_session: action.new_shares_per_old for action in splits}
    for item in bars:
        factor /= actions.get(item.session_date, D(1))
        adjusted.append(
            Bar(
                timestamp=item.timestamp,
                open=item.open / factor,
                high=item.high / factor,
                low=item.low / factor,
                close=item.close / factor,
                volume=item.volume,
            )
        )
    return HistoryBundle(
        series=(
            HistorySeries(symbol="AAPL", adjustment="RAW", bars=bars),
            HistorySeries(symbol="AAPL", adjustment="SPLIT", bars=tuple(adjusted)),
            HistorySeries(symbol="AAPL", adjustment="ALL", bars=tuple(adjusted)),
        ),
        splits=splits,
    )


def frozen(value: HistoryBundle) -> FrozenHistory:
    ordered = tuple(sorted(value.series, key=lambda item: (item.symbol, item.adjustment)))
    manifest = HistoryManifest(
        entries=tuple(
            ManifestEntry(
                symbol=item.symbol,
                adjustment=item.adjustment,
                sessions=item.sessions,
                sha256=hashlib.sha256(canonical_bytes(item)).hexdigest(),
                filename=f"{item.symbol}_{item.adjustment}.json",
            )
            for item in ordered
        ),
        splits=tuple(sorted(value.splits, key=lambda item: (item.symbol, item.effective_session))),
    )
    return FrozenHistory(manifest=manifest, bundle=value)


def run(
    intent: OutcomeSetup,
    value: HistoryBundle,
    calendar: MarketCalendar,
    schedule: FeeSchedule,
    **kwargs: Any,
) -> Outcome:
    return simulate_outcome(
        intent,
        frozen(value),
        CostContext(median_dollar_volume_20=D(500_000_000), atr14=D(2)),
        calendar,
        schedule,
        **kwargs,
    )


@pytest.mark.parametrize(
    "disposition",
    ["APPROVED", "REJECTED", "EXPIRED", "CRO_VETO", "RS_FILTER", "PR_FILTER", "SZ_FILTER"],
)
def test_EV_01_all_alerts_same_bar_stop_before_target(
    disposition: str, calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    observed = run(
        setup(disposition=disposition),
        bundle((bar(15), bar(16, high="111", low="94"))),
        calendar,
        schedule,
    )
    assert observed.status == "RESOLVED" and observed.reason == "STOP"
    assert observed.entry_session == observed.exit_session == date(2026, 9, 16)
    assert observed.entry_fill is not None and observed.entry_fill.price == D("100.02")
    assert observed.exit_fill is not None and observed.exit_fill.price == D("94.88")
    # Independent arithmetic: 100 shares, two cent-priced fills, fee ceilings.
    expected = D("9488") - D("10002") - D("0.01") - D("0.23")
    assert observed.net_money == expected and observed.r_multiple == (expected / D(600)).quantize(
        D("0.000001")
    )
    assert observed.mae_money == D(-602) and observed.mfe_money == D(1098)
    assert observed.sessions_held == 1 and "Dividends ignored" in observed.notes[1]


def test_EV_01_gap_below_stop_golden(calendar: MarketCalendar, schedule: FeeSchedule) -> None:
    observed = run(
        setup(),
        bundle((bar(15), bar(16), bar(17, opening="90", high="91", low="89", closing="90"))),
        calendar,
        schedule,
    )
    assert observed.reason == "GAP_STOP" and observed.sessions_held == 2
    assert observed.exit_fill is not None and observed.exit_fill.price == D("89.98")
    assert observed.net_money == D("-1004.23")
    assert observed.r_multiple == (D("-1004.23") / D(600)).quantize(D("0.000001"))
    # An opening exit must not claim the rest of that day's excursions.
    assert observed.mae_money == D(-1002) and observed.mfe_money == D(98)


def test_EV_01_target_requires_trade_through(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    touching = bundle((bar(15), bar(16, high="110")))
    assert run(setup(), touching, calendar, schedule).status == "OPEN"
    beyond = bundle((bar(15), bar(16, high="110.01")))
    result = run(setup(), beyond, calendar, schedule)
    assert result.reason == "TARGET" and result.net_money == D("997.73")


def test_EV_01_same_session_expiry_never_invents_a_later_fill(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    # Intraday proposals can expire at today's close. CM uses the next opening;
    # preserve that expiry and report no fill, even if tomorrow crosses the limit.
    result = run(
        setup(valid_until_session=START),
        bundle((bar(15), bar(16, high="111", low="94"))),
        calendar,
        schedule,
    )
    assert result.status == "NOT_FILLED" and result.entry_fill is None
    with pytest.raises(ValidationError):
        setup(valid_until_session=date(2026, 9, 14))


def test_EV_01_entry_halt_cancels_pending_but_preserves_held_exit(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    value = bundle((bar(15), bar(16), bar(17, opening="90", high="91", low="89", closing="90")))
    canceled = run(setup(), value, calendar, schedule, cancel_entry_at=START)
    assert canceled.status == "NOT_FILLED" and canceled.reason == "ENTRY_HALTED"
    assert canceled.entry_fill is None and canceled.net_money is None
    held = run(setup(), value, calendar, schedule, cancel_entry_at=date(2026, 9, 16))
    assert held.status == "RESOLVED" and held.reason == "GAP_STOP"
    assert held.exit_session == date(2026, 9, 17)
    with pytest.raises(DataIntegrityError):
        run(setup(), value, calendar, schedule, cancel_entry_at=date(2026, 9, 14))


def test_EV_01_never_filled_is_not_fake_loss(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    bars = tuple(
        bar(day, opening="102", high="103", low="101", closing="102") for day in (15, 16, 17)
    )
    result = run(setup(), bundle(bars), calendar, schedule)
    assert result.status == "NOT_FILLED" and result.reason == "ALERT_UNFILLED"
    assert result.r_multiple is None and result.net_money is None and result.sessions_held == 0
    pending = run(setup(), bundle(bars[:2]), calendar, schedule)
    assert pending.status == "INCOMPLETE" and pending.reason == "HISTORY_PENDING"


def test_EV_01_first_partial_fill_does_not_top_up(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    result = run(
        setup(qty=200),
        bundle((bar(15), bar(16, volume=10000), bar(17, high="110.01"))),
        calendar,
        schedule,
    )
    assert result.entry_fill is not None and result.entry_fill.status == "PARTIAL"
    assert result.entry_fill.qty == result.exit_fill.qty == 100  # type: ignore[union-attr]
    assert result.initial_risk_money == D(600) and result.net_money == D("997.73")


@pytest.mark.parametrize("signal,reason", [(None, "TIME"), (date(2026, 9, 17), "SIGNAL")])
def test_CM_03_time_and_signal_exit_next_open(
    signal: date | None, reason: str, calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    bars = bundle(
        (bar(15), bar(16), bar(17), bar(18, opening="105", high="120", low="90", closing="100"))
    )
    result = run(
        setup(),
        bars,
        calendar,
        schedule,
        policy=EvaluationConfig(max_hold_sessions=2),
        signal_exit_session=signal,
    )
    assert result.reason == reason and result.exit_session == date(2026, 9, 18)
    assert result.sessions_held == 2
    assert result.exit_fill is not None and result.exit_fill.price == D("104.97")
    assert result.net_money == D("494.74")
    # The new opening exit precedes later intraday stop and target touches.
    assert result.mae_money == D(-102) and result.mfe_money == D(498)


def test_EV_01_time_exit_gap_stop_still_has_priority(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    result = run(
        setup(),
        bundle((bar(15), bar(16), bar(17, opening="90", high="120", low="89", closing="100"))),
        calendar,
        schedule,
        policy=EvaluationConfig(max_hold_sessions=1),
    )
    assert result.reason == "GAP_STOP"


@pytest.mark.parametrize("split_day,qty", [(17, 100), (16, 200)])
def test_EV_01_split_during_hold_and_before_fill(
    split_day: int, qty: int, calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    action = KnownSplit(
        symbol="AAPL", effective_session=date(2026, 9, split_day), new_shares_per_old=D(2)
    )
    middle = (
        bar(16)
        if split_day == 17
        else bar(16, opening="50", high="50.50", low="49.50", closing="50")
    )
    value = bundle(
        (bar(15), middle, bar(17, opening="50", high="55.01", low="49", closing="50")), (action,)
    )
    result = run(setup(), value, calendar, schedule)
    assert result.status == "RESOLVED" and result.reason == "TARGET"
    assert result.entry_fill is not None and result.entry_fill.qty == qty
    assert (
        result.exit_fill is not None
        and result.exit_fill.qty == 200
        and result.exit_fill.price == D(55)
    )
    assert result.net_money == D("997.71") and result.initial_risk_money == D(600)
    assert result.setup.stop == D(95)  # recorded levels remain immutable


def test_EV_01_fractional_split_is_incomplete(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    action = KnownSplit(
        symbol="AAPL", effective_session=date(2026, 9, 17), new_shares_per_old=D("1.5")
    )
    bars = (
        bar(15, opening="99", high="100.50", low="97.50", closing="99"),
        bar(16, opening="99", high="100.50", low="97.50", closing="99"),
        bar(17, opening="66", high="67", low="65", closing="66"),
    )
    result = run(
        setup(qty=3, limit=D("100.50"), stop=D(96), target=D(111)),
        bundle(bars, (action,)),
        calendar,
        schedule,
    )
    assert (
        result.status == "INCOMPLETE"
        and result.reason == "FRACTIONAL_SPLIT"
        and result.net_money is None
    )


def test_EV_01_subcent_split_levels_are_incomplete(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    action = KnownSplit(symbol="AAPL", effective_session=date(2026, 9, 17), new_shares_per_old=D(2))
    result = run(
        setup(stop=D("95.01")),
        bundle(
            (bar(15), bar(16), bar(17, opening="50", high="51", low="49", closing="50")), (action,)
        ),
        calendar,
        schedule,
    )
    assert result.status == "INCOMPLETE" and result.reason == "SUBCENT_SPLIT"


def test_DQ_04_frozen_roundtrip_hashes_and_write_once(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    value = bundle((bar(15), bar(16)))
    written = seal_history(tmp_path, value, calendar)
    loaded = load_history(tmp_path, calendar)
    assert written == loaded
    assert (
        written.manifest.sha256
        == hashlib.sha256((tmp_path / "manifest.json").read_bytes()).hexdigest()
    )
    with pytest.raises(DataIntegrityError, match="overwritten"):
        seal_history(tmp_path, value, calendar)
    path = tmp_path / "AAPL_RAW.json"
    path.write_bytes(path.read_bytes().replace(b'"volume":20000', b'"volume":20001'))
    with pytest.raises(DataIntegrityError, match="hash differs"):
        load_history(tmp_path, calendar)


@pytest.mark.parametrize(
    "case", ["missing", "holiday", "duplicates", "zero", "unknown_split", "missing_adjustment"]
)
def test_DQ_03_bad_history_refused(case: str, calendar: MarketCalendar) -> None:
    with pytest.raises((ValidationError, DataIntegrityError)):
        if case == "missing":
            validate_history(bundle((bar(15), bar(17))), calendar)
        elif case == "holiday":
            validate_history(bundle((bar(19),)), calendar)
        elif case == "duplicates":
            bundle((bar(15), bar(15)))
        elif case == "zero":
            bundle((bar(15, volume=0),))
        elif case == "unknown_split":
            good = bundle((bar(15), bar(16)))
            altered = good.series[1].model_copy(
                update={"bars": (bar(15), bar(16, opening="50", high="51", low="49", closing="50"))}
            )
            HistoryBundle.model_validate(
                good.model_copy(update={"series": (good.series[0], altered, good.series[2])})
            )
        else:
            good = bundle((bar(15),))
            HistoryBundle.model_validate(
                good.model_copy(update={"series": (good.series[0], good.series[0], good.series[0])})
            )


@pytest.mark.parametrize(
    "case", ["setup", "history", "context", "policy", "future_signal", "no_decision"]
)
def test_EV_invalid_ingress_is_typed(
    case: str, calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    intent = setup()
    value = frozen(bundle((bar(15), bar(16))))
    context = CostContext(median_dollar_volume_20=D(500_000_000), atr14=D(2))
    kwargs: dict[str, Any] = {}
    if case == "setup":
        intent = intent.model_copy(update={"qty": True})
    elif case == "history":
        value = value.model_copy(
            update={"manifest": value.manifest.model_copy(update={"format_version": 2})}
        )
    elif case == "context":
        context = context.model_copy(update={"atr14": 1.1})
    elif case == "policy":
        kwargs["policy"] = EvaluationConfig().model_copy(update={"max_hold_sessions": 0})
    elif case == "future_signal":
        kwargs["signal_exit_session"] = datetime(2026, 9, 16, tzinfo=UTC)
    else:
        intent = setup(decision_session=date(2026, 9, 14))
    with pytest.raises(DataIntegrityError):
        simulate_outcome(intent, value, context, calendar, schedule, **kwargs)


def test_EV_results_reject_forged_profit_and_missing_disclosure(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    resolved = run(setup(), bundle((bar(15), bar(16, high="110.01"))), calendar, schedule)
    for changed in (
        {"net_money": D(9999)},
        {"r_multiple": D(10)},
        {"notes": ("profits guaranteed", "foo")},
        {"status": "OPEN"},
        {"entry_session": START},
        {"exit_fees": None},
    ):
        with pytest.raises(ValidationError):
            Outcome.model_validate(resolved.model_copy(update=changed))


def test_DQ_manifest_rejects_identity_and_frozen_byte_mismatch(calendar: MarketCalendar) -> None:
    value = frozen(bundle((bar(15), bar(16))))
    entry = value.manifest.entries[0]
    with pytest.raises(ValidationError):
        ManifestEntry.model_validate(entry.model_copy(update={"filename": "../escape.json"}))
    with pytest.raises(ValidationError):
        HistoryManifest.model_validate(
            value.manifest.model_copy(update={"entries": (*value.manifest.entries, entry)})
        )
    with pytest.raises(ValidationError):
        altered = value.manifest.model_copy(
            update={
                "entries": (
                    entry.model_copy(update={"sha256": "f" * 64}),
                    *value.manifest.entries[1:],
                )
            }
        )
        FrozenHistory.model_validate(value.model_copy(update={"manifest": altered}))


@pytest.mark.parametrize(
    "case",
    [
        "orphan_action",
        "missing_all",
        "session_mismatch",
        "anchor_action",
        "missing_symbol",
        "bound_name",
        "unsorted_dates",
        "split_proof",
        "series_count",
        "unchanged_split",
    ],
)
def test_DQ_rejects_incoherent_provenance(case: str) -> None:
    value = bundle((bar(15), bar(16)))
    sealed = frozen(value)
    entry = sealed.manifest.entries[0]
    action = KnownSplit(symbol="AAPL", effective_session=date(2026, 9, 16), new_shares_per_old=D(2))
    with pytest.raises((ValidationError, DataIntegrityError)):
        if case == "orphan_action":
            HistoryBundle.model_validate(
                value.model_copy(update={"splits": (action.model_copy(update={"symbol": "MSFT"}),)})
            )
        elif case == "missing_all":
            HistoryBundle.model_validate(
                value.model_copy(
                    update={
                        "series": (
                            *value.series[:2],
                            value.series[2].model_copy(update={"adjustment": "DIVIDEND"}),
                        )
                    }
                )
            )
        elif case == "session_mismatch":
            HistoryBundle.model_validate(
                value.model_copy(
                    update={
                        "series": (
                            *value.series[:2],
                            value.series[2].model_copy(update={"bars": (bar(15), bar(17))}),
                        )
                    }
                )
            )
        elif case == "anchor_action":
            HistoryBundle.model_validate(
                value.model_copy(
                    update={"splits": (action.model_copy(update={"effective_session": START}),)}
                )
            )
        elif case == "missing_symbol":
            value.for_symbol("MSFT", "SPLIT")
        elif case == "bound_name":
            ManifestEntry.model_validate(entry.model_copy(update={"filename": "MSFT_ALL.json"}))
        elif case == "unsorted_dates":
            ManifestEntry.model_validate(
                entry.model_copy(update={"sessions": (date(2026, 9, 16), START)})
            )
        elif case == "split_proof":
            FrozenHistory.model_validate(
                sealed.model_copy(
                    update={"manifest": sealed.manifest.model_copy(update={"splits": (action,)})}
                )
            )
        elif case == "series_count":
            extra = value.series[2].model_copy(update={"adjustment": "DIVIDEND"})
            expanded = HistoryBundle(series=(*value.series, extra))
            FrozenHistory.model_validate(sealed.model_copy(update={"bundle": expanded}))
        else:
            KnownSplit.model_validate(action.model_copy(update={"new_shares_per_old": D(1)}))


def test_DQ_split_manifest_roundtrip_and_single_session(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    action = KnownSplit(symbol="AAPL", effective_session=date(2026, 9, 16), new_shares_per_old=D(2))
    value = bundle(
        (bar(15), bar(16, opening="50", high="50.50", low="49.50", closing="50")), (action,)
    )
    assert seal_history(tmp_path, value, calendar) == load_history(tmp_path, calendar)
    assert validate_history(bundle((bar(15),)), calendar).series[0].sessions == (START,)


def test_DQ_local_file_failure_canonicality_and_size_bounds(
    tmp_path: Path, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.data.history as adapter

    with pytest.raises(DataIntegrityError, match="missing or malformed"):
        load_history(tmp_path, calendar)
    seal_history(tmp_path, bundle((bar(15),)), calendar)
    manifest_path = tmp_path / "manifest.json"
    original = manifest_path.read_bytes()
    manifest_path.write_bytes(b" " + original)
    with pytest.raises(DataIntegrityError, match="not canonical"):
        load_history(tmp_path, calendar)
    monkeypatch.setattr(adapter, "_LIMIT", 16)
    with pytest.raises(DataIntegrityError, match="exceeds"):
        load_history(tmp_path, calendar)


def test_DQ_data_canonicality_checked_after_digest(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    sealed = seal_history(tmp_path, bundle((bar(15),)), calendar)
    entry = sealed.manifest.entries[0]
    path = tmp_path / entry.filename
    changed = b" " + path.read_bytes()
    path.write_bytes(changed)
    changed_entry = entry.model_copy(update={"sha256": hashlib.sha256(changed).hexdigest()})
    manifest = sealed.manifest.model_copy(
        update={"entries": (changed_entry, *sealed.manifest.entries[1:])}
    )
    (tmp_path / "manifest.json").write_bytes(canonical_bytes(manifest))
    with pytest.raises(DataIntegrityError, match="data bytes are not canonical"):
        load_history(tmp_path, calendar)


def test_DQ_seal_io_failure_is_typed_and_has_no_manifest(
    tmp_path: Path, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise OSError("synthetic disk full")

    monkeypatch.setattr(Path, "open", failed_open)
    with pytest.raises(DataIntegrityError, match="sealing failed"):
        seal_history(tmp_path, bundle((bar(15),)), calendar)
    assert not (tmp_path / "manifest.json").exists()


def test_EV_no_fill_after_expiry_and_invalid_signal_date(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    value = bundle(
        tuple(
            bar(day, opening="102", high="103", low="101", closing="102")
            for day in (15, 16, 17, 18)
        )
    )
    assert run(setup(), value, calendar, schedule).reason == "ALERT_UNFILLED"
    with pytest.raises(DataIntegrityError):
        run(setup(), value, calendar, schedule, signal_exit_session=date(2026, 9, 14))
    with pytest.raises(ValidationError):
        setup(stop=D(102))


def test_EV_output_invariants_block_unavailable_or_partial_evidence(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    from backend.domain.models import Side
    from backend.evaluation.costs import FillResult, fees

    resolved = run(setup(), bundle((bar(15), bar(16, high="110.01"))), calendar, schedule)
    assert resolved.exit_fill is not None
    empty = FillResult(
        status="NOT_FILLED",
        requested_qty=100,
        qty=0,
        price=None,
        reason="NOT_TOUCHED",
        half_spread_bps=D(2),
    )
    partial = FillResult(
        status="PARTIAL",
        requested_qty=100,
        qty=50,
        price=D(110),
        reason="TARGET",
        half_spread_bps=D(2),
    )
    updates: tuple[dict[str, Any], ...] = (
        {"entry_session": None},
        {"entry_fill": empty},
        {"exit_session": START},
        {"exit_fill": None, "exit_fees": None, "exit_session": None},
        {"exit_fill": partial},
        {"reason": "STOP"},
        {
            "status": "NOT_FILLED",
            "reason": "ALERT_UNFILLED",
            "exit_fill": None,
            "exit_fees": None,
            "exit_session": None,
            "net_money": None,
            "r_multiple": None,
        },
        {
            "status": "OPEN",
            "reason": "STOP",
            "exit_fill": None,
            "exit_fees": None,
            "exit_session": None,
            "net_money": None,
            "r_multiple": None,
        },
        {
            "status": "INCOMPLETE",
            "reason": "TARGET",
            "exit_fill": None,
            "exit_fees": None,
            "exit_session": None,
            "net_money": None,
            "r_multiple": None,
        },
    )
    for changes in updates:
        with pytest.raises(ValidationError):
            Outcome.model_validate(resolved.model_copy(update=changes))
    # Exit dates without entry evidence also fail before any profit calculation.
    no_fill = run(
        setup(),
        bundle(
            tuple(
                bar(day, opening="102", high="103", low="101", closing="102")
                for day in (15, 16, 17)
            )
        ),
        calendar,
        schedule,
    )
    with pytest.raises(ValidationError):
        Outcome.model_validate(
            no_fill.model_copy(
                update={
                    "exit_session": date(2026, 9, 17),
                    "exit_fill": resolved.exit_fill,
                    "exit_fees": fees(Side.SELL, 100, D(110), date(2026, 9, 17), schedule=schedule),
                }
            )
        )
