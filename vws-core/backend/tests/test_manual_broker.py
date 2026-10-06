"""DAT-12: exact manual CSVs, session freshness and explicit missing evidence."""

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    ProviderError,
    StaleDataError,
)
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.boundary import ReadBoundary
from backend.data.liquidity import BalanceReading, FakeLiquiditySource, LiquidityGate
from backend.data.manual_broker import (
    AccountFlagsProvider,
    ManualCSVBrokerState,
    MarketContextProvider,
    PendingOrdersProvider,
)
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import AccountFlags, MarketContext, MarketStatus, OpenOrder, Side
from backend.risk.portfolio_marks import PersistedPortfolioMarks

NOW = datetime(2026, 10, 6, 15, tzinfo=UTC)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2024, 1, 2), end=date(2026, 12, 31))


def write(path: Path, content: str, modified: datetime) -> None:
    """DAT-12: host wall-clock and floating timestamps cannot affect fixtures."""
    path.write_text(content, encoding="utf-8")
    elapsed = modified - EPOCH
    ns = ((elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds) * 1000
    os.utime(path, ns=(ns, ns))


def clean_flags(now: datetime) -> AccountFlags:
    return AccountFlags(
        status="ACTIVE", trading_blocked=False, account_blocked=False, trade_suspended_by_user=False
    )


def no_orders(now: datetime) -> tuple[OpenOrder, ...]:
    return ()


def quote(symbol: str, now: datetime) -> MarketContext:
    assert symbol in {"AAPL", "MSFT"}
    return MarketContext(
        last_price=Decimal("100.00"),
        last_price_ts=now,
        adv20_usd=Decimal("10000000"),
        status=MarketStatus.OK,
    )


def provider(
    tmp_path: Path,
    calendar: MarketCalendar,
    *,
    now: datetime = NOW,
    modified: datetime = NOW,
    positions: str = "symbol,qty,avg_cost\nAAPL,10,90.01\n",
    cash: str = "cash,settled_cash\n1000.00,900.00\n",
    flags: AccountFlagsProvider | None = clean_flags,
    pending: PendingOrdersProvider | None = no_orders,
    market: MarketContextProvider = quote,
    config: Settings | None = None,
) -> ManualCSVBrokerState:
    positions_path, cash_path = tmp_path / "manual_positions.csv", tmp_path / "manual_cash.csv"
    write(positions_path, positions, modified)
    write(cash_path, cash, modified)
    settings = (
        Settings(_env_file=None, broker_account_type="CASH", broker_state_source="MANUAL_CSV")
        if config is None
        else config
    )
    return ManualCSVBrokerState(
        settings,
        FrozenClock(now),
        calendar,
        lambda equity, instant: (equity, equity),
        positions_path,
        cash_path,
        account_id="manual-test-account",
        known_symbols=frozenset({"AAPL", "MSFT"}),
        market_context_provider=market,
        flags_provider=flags,
        pending_orders_provider=pending,
    )


def test_DAT_12_exact_projection_uses_current_market_not_average_cost(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    calls: list[datetime] = []

    def pending(now: datetime) -> tuple[OpenOrder, ...]:
        calls.append(now)
        return (OpenOrder(symbol="MSFT", side=Side.BUY, qty=2, limit_price=Decimal("95.50")),)

    source = provider(tmp_path, calendar, pending=pending)
    snapshot = source.snapshot(NOW)
    assert snapshot.account_id == "manual-test-account" and snapshot.account_type == "CASH"
    assert snapshot.as_of == NOW
    assert snapshot.cash == Decimal("1000.00") and snapshot.settled_cash == Decimal("900.00")
    assert snapshot.positions["AAPL"].qty == 10 and snapshot.positions["AAPL"].avg_cost == Decimal(
        "90.01"
    )
    assert snapshot.positions["AAPL"].last_price == Decimal("100.00")
    assert snapshot.equity == Decimal("2000.00")
    assert snapshot.high_water_mark == snapshot.day_start_equity == snapshot.equity
    assert snapshot.open_orders[0].qty == 2 and calls == [NOW]
    assert source.last_flags is not None and not source.last_flags.blocked


def test_DAT_12_empty_positions_need_no_market_price_lookup(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    def never(symbol: str, now: datetime) -> MarketContext:
        raise AssertionError("no holdings need a quote")

    result = provider(tmp_path, calendar, positions="symbol,qty,avg_cost\n", market=never).snapshot(
        NOW
    )
    assert not result.positions and result.equity == Decimal("1000.00")


@pytest.mark.parametrize(
    "modified,now",
    [
        (datetime(2026, 10, 5, 15, tzinfo=UTC), NOW),
        (datetime(2026, 10, 2, 20, tzinfo=UTC), datetime(2026, 10, 5, 13, 29, tzinfo=UTC)),
        (datetime(2026, 10, 2, 20, tzinfo=UTC), datetime(2026, 10, 5, 13, 30, tzinfo=UTC)),
        (datetime(2026, 9, 3, 15, tzinfo=UTC), datetime(2026, 9, 7, 20, tzinfo=UTC)),
        (datetime(2026, 3, 6, 20, tzinfo=UTC), datetime(2026, 3, 9, 13, 30, tzinfo=UTC)),
    ],
)
def test_DAT_12_one_session_or_less_is_fresh_across_weekend_holiday_and_dst(
    tmp_path: Path, calendar: MarketCalendar, modified: datetime, now: datetime
) -> None:
    assert provider(tmp_path, calendar, now=now, modified=modified).snapshot(now).as_of == now


@pytest.mark.parametrize(
    "modified,now",
    [
        (datetime(2026, 10, 2, 20, tzinfo=UTC), NOW),
        (datetime(2026, 9, 3, 15, tzinfo=UTC), datetime(2026, 9, 8, 13, 30, tzinfo=UTC)),
        (datetime(2026, 3, 6, 20, tzinfo=UTC), datetime(2026, 3, 10, 13, 30, tzinfo=UTC)),
        (datetime(2026, 11, 25, 20, tzinfo=UTC), datetime(2026, 11, 30, 14, 30, tzinfo=UTC)),
    ],
)
def test_DAT_12_more_than_one_session_is_stale_at_the_actual_open(
    tmp_path: Path, calendar: MarketCalendar, modified: datetime, now: datetime
) -> None:
    source = provider(tmp_path, calendar, now=now, modified=modified)
    with pytest.raises(StaleDataError, match="older than one"):
        source.snapshot(now)
    assert source.last_flags is None


@pytest.mark.parametrize("which", ["manual_cash.csv", "manual_positions.csv"])
def test_DAT_12_either_stale_file_refuses_the_whole_snapshot(
    tmp_path: Path, calendar: MarketCalendar, which: str
) -> None:
    source = provider(tmp_path, calendar)
    path = tmp_path / which
    write(path, path.read_text(encoding="utf-8"), datetime(2026, 10, 2, 20, tzinfo=UTC))
    with pytest.raises(StaleDataError):
        source.snapshot(NOW)


def test_DAT_12_future_file_or_wrong_read_clock_cannot_appear_fresh(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    source = provider(tmp_path, calendar, modified=NOW + timedelta(microseconds=1))
    with pytest.raises(DataIntegrityError, match="future"):
        source.snapshot(NOW)
    source = provider(tmp_path, calendar)
    with pytest.raises(DataIntegrityError, match="clock"):
        source.snapshot(NOW + timedelta(seconds=3))
    with pytest.raises(DataIntegrityError):
        source.snapshot(NOW.replace(tzinfo=None))


@pytest.mark.parametrize(
    "row",
    [
        "AAPL,1.0,90.00",
        "AAPL,-1,90.00",
        "AAPL,+1,90.00",
        "AAPL,01,90.00",
        "AAPL,9999999999999,90.00",
        "AAPL,True,90.00",
        "AAPL,10,90.001",
        "AAPL,10,0",
        "AAPL,10,-90",
        "AAPL,10,NaN",
        "AAPL,10,inf",
        "AAPL,10,1e2",
        "aapl,10,90",
        "UNKNOWN,10,90",
        "AAPL,10",
        "AAPL,10,90,extra",
    ],
)
def test_DAT_12_invalid_position_rows_fail_closed(
    tmp_path: Path, calendar: MarketCalendar, row: str
) -> None:
    with pytest.raises(DataIntegrityError):
        provider(tmp_path, calendar, positions="symbol,qty,avg_cost\n" + row + "\n").snapshot(NOW)


@pytest.mark.parametrize(
    "positions",
    [
        "",
        "symbol,quantity,avg_cost\nAAPL,10,90\n",
        "symbol,qty,qty\nAAPL,10,90\n",
        "symbol,qty,avg_cost\nAAPL,10,90\nAAPL,20,90\n",
    ],
)
def test_DAT_12_invalid_position_headers_and_duplicates_fail_closed(
    tmp_path: Path, calendar: MarketCalendar, positions: str
) -> None:
    with pytest.raises(DataIntegrityError):
        provider(tmp_path, calendar, positions=positions).snapshot(NOW)


@pytest.mark.parametrize(
    "cash",
    [
        "",
        "cash,balance\n1000,900\n",
        "cash,settled_cash\n",
        "cash,settled_cash\n1000,900\n1000,900\n",
        "cash,settled_cash\n1000\n",
        "cash,settled_cash\n1000,900,extra\n",
        "cash,settled_cash\nNaN,900\n",
        "cash,settled_cash\n1e3,900\n",
        "cash,settled_cash\n1000,1000.01\n",
        "cash,settled_cash\n1000.0000001,900\n",
    ],
)
def test_DAT_12_invalid_cash_shape_or_money_is_unavailable(
    tmp_path: Path, calendar: MarketCalendar, cash: str
) -> None:
    with pytest.raises(DataIntegrityError):
        provider(tmp_path, calendar, cash=cash).snapshot(NOW)


def test_DAT_12_missing_pending_order_proof_is_never_an_empty_order_list(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    source = provider(tmp_path, calendar, pending=None)
    with pytest.raises(DataIntegrityError, match="pending orders are unavailable"):
        source.snapshot(NOW)
    assert source.last_flags is None


def test_DAT_12_missing_restriction_flags_stay_unknown(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    source = provider(tmp_path, calendar, flags=None)
    assert source.snapshot(NOW).positions["AAPL"].qty == 10
    assert source.last_flags is None


@pytest.mark.parametrize("missing", ["flags", "pending"])
def test_DAT_12_read_boundary_latches_halt_on_missing_account_evidence(
    tmp_path: Path, calendar: MarketCalendar, engine: Engine, missing: str
) -> None:
    settings = Settings(
        _env_file=None, broker_account_type="CASH", broker_state_source="MANUAL_CSV"
    )
    source = provider(
        tmp_path,
        calendar,
        flags=None if missing == "flags" else clean_flags,
        pending=None if missing == "pending" else no_orders,
        config=settings,
    )
    clock = FrozenClock(NOW)
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    bank = LiquidityGate(
        settings,
        FakeLiquiditySource(
            BalanceReading(
                available=Decimal("5000"), current=Decimal("5000"), currency="USD", as_of=NOW
            )
        ),
        clock,
    )
    marks = PersistedPortfolioMarks(state.ledger, "manual-test-account", calendar, settings)
    boundary = ReadBoundary(
        settings, state, clock, source, bank, account_id="manual-test-account", marks=marks
    )
    with pytest.raises(DataIntegrityError):
        boundary.portfolio()
    assert state.current() == SystemState.HALTED


def test_DAT_12_failed_refresh_clears_previous_clean_flags(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    source = provider(tmp_path, calendar)
    source.snapshot(NOW)
    assert source.last_flags is not None
    (tmp_path / "manual_cash.csv").unlink()
    with pytest.raises(DataIntegrityError):
        source.snapshot(NOW)
    assert source.last_flags is None


@pytest.mark.parametrize("kind", ["stale", "future", "suspect", "forged"])
def test_DAT_12_current_valuation_cannot_be_invented_from_cost(
    tmp_path: Path, calendar: MarketCalendar, kind: str
) -> None:
    def invalid(symbol: str, now: datetime) -> MarketContext:
        context = quote(symbol, now)
        if kind == "stale":
            return context.model_copy(update={"last_price_ts": now - timedelta(seconds=61)})
        if kind == "future":
            return context.model_copy(update={"last_price_ts": now + timedelta(seconds=1)})
        if kind == "suspect":
            return context.model_copy(update={"status": MarketStatus.SUSPECT})
        return context.model_copy(update={"last_price": Decimal("NaN")})

    with pytest.raises(DataIntegrityError):
        provider(tmp_path, calendar, market=invalid).snapshot(NOW)


@pytest.mark.parametrize(
    "kind", ["pending_mutable", "pending_unknown", "pending_forged", "flags_forged"]
)
def test_DAT_12_injected_attestations_are_revalidated(
    tmp_path: Path, calendar: MarketCalendar, kind: str
) -> None:
    order = OpenOrder(symbol="AAPL", side=Side.BUY, qty=1, limit_price=Decimal("100"))

    def pending(now: datetime) -> tuple[OpenOrder, ...]:
        if kind == "pending_mutable":
            return cast(tuple[OpenOrder, ...], [order])
        if kind == "pending_unknown":
            return (order.model_copy(update={"symbol": "UNKNOWN"}),)
        if kind == "pending_forged":
            return (order.model_copy(update={"qty": True}),)
        return ()

    def flags(now: datetime) -> AccountFlags:
        return clean_flags(now).model_copy(update={"trading_blocked": "false"})

    with pytest.raises(DataIntegrityError):
        provider(
            tmp_path,
            calendar,
            pending=pending,
            flags=flags if kind == "flags_forged" else clean_flags,
        ).snapshot(NOW)


def test_DAT_12_equity_arithmetic_is_exact_despite_global_precision(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    def fractional_cent(symbol: str, now: datetime) -> MarketContext:
        return quote(symbol, now).model_copy(update={"last_price": Decimal("123.45")})

    with localcontext() as context:
        context.prec = 2
        result = provider(
            tmp_path,
            calendar,
            positions="symbol,qty,avg_cost\nAAPL,123456789,90.01\n",
            cash="cash,settled_cash\n1000.123456,900\n",
            market=fractional_cent,
        ).snapshot(NOW)
    assert result.equity == Decimal("15240741602.173456")


@pytest.mark.parametrize("mode", ["AUTO_PAPER", "AUTO_LIVE"])
def test_AX_15_manual_source_never_composes_an_automatic_mode(
    tmp_path: Path, calendar: MarketCalendar, mode: str
) -> None:
    config = Settings(
        _env_file=None,
        broker_account_type="CASH",
        broker_state_source="MANUAL_CSV",
        execution_mode=cast(Any, mode),
    )
    with pytest.raises(ConfigurationError):
        provider(tmp_path, calendar, config=config)


def test_DAT_12_wrong_source_selection_or_forged_policy_refuses(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    with pytest.raises(ConfigurationError):
        provider(tmp_path, calendar, config=Settings(_env_file=None, broker_account_type="CASH"))
    invalid = Settings(
        _env_file=None, broker_account_type="CASH", broker_state_source="MANUAL_CSV"
    ).model_copy(update={"broker_account_type": "GUESSED"})
    with pytest.raises(ConfigurationError):
        provider(tmp_path, calendar, config=invalid)


def test_DAT_12_unexpected_provider_error_is_typed_and_has_no_secret_context(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    def fail(symbol: str, now: datetime) -> MarketContext:
        raise RuntimeError("access-sandbox-unregistered-error-token")

    with pytest.raises(ProviderError) as caught:
        provider(tmp_path, calendar, market=fail).snapshot(NOW)
    assert "access-sandbox-unregistered-error-token" not in str(caught.value)
    assert caught.value.__suppress_context__ is True


def test_DAT_12_oversized_manual_file_is_rejected_before_parsing(
    tmp_path: Path, calendar: MarketCalendar
) -> None:
    source = provider(tmp_path, calendar, positions="symbol,qty,avg_cost\n" + "x" * 1_048_576)
    with pytest.raises(DataIntegrityError, match="oversized"):
        source.snapshot(NOW)


def test_DAT_12_manual_symlink_path_is_never_a_trusted_csv(
    tmp_path: Path,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = provider(tmp_path, calendar)
    path = tmp_path / "manual_positions.csv"
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda candidate: candidate == path or original(candidate)
    )
    with pytest.raises(DataIntegrityError, match="symbolic link"):
        source.snapshot(NOW)
