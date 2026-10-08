"""FN/PL/TX: complete-history host composition, exact ingress and restart evidence."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import CashFlow, PortfolioState, SecurityEvent, TaxEvent
from backend.core.errors import DataIntegrityError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader
from backend.data.fee_schedule import load_fee_schedule
from backend.data.fill_polling import ObservedFill
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import AccountType, PortfolioSnapshot, Position
from backend.evaluation.costs import FeeSchedule
from backend.funding.activities import ActivityBatch, AlpacaActivitiesSource, parse_activity
from backend.funding.models import Activity
from backend.net.egress import EgressPolicy, build_allowlist
from backend.pnl.history import EquityClose, EquityHistory, read_history
from backend.pnl.service import AccountingReports
from backend.pnl.storage import read_days
from backend.tax.imports import import_marked_lots
from backend.tax.models import NOTICE, SIMULATED
from backend.tax.service import TaxService, managed_accounts
from backend.tests.test_funding_and_pnl import baseline
from backend.tests.test_wash_sales import registry

PROJECT = Path(__file__).resolve().parents[2]


def fee_schedule() -> FeeSchedule:
    return load_fee_schedule(PROJECT / "config/fees.yaml")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition", ["before_opening", "missing_scaling", "proven_scaling", "no_flow", "non_flow"]
)
async def test_FN_03_existing_baselines_cannot_be_silently_reset(
    engine: Engine, clock: FrozenClock, tmp_path: Path, condition: str
) -> None:
    when = clock.now() - timedelta(days=2) if condition == "before_opening" else clock.now()
    event = Activity(
        account_id="tax",
        env="PAPER",
        activity_id="legacy",
        type="CSW",
        amount=Decimal(-100),
        date=when.date(),
        occurred_at=when,
        observed_at=clock.now(),
        source="BROKER",
        payload_sha256="a" * 64,
    )
    rows = () if condition == "no_flow" else (event,)
    if condition == "non_flow":
        rows = (parse_activity(raw("DIV"), "tax", "PAPER", clock.now(), fee_schedule()),)
    tax, _, notices = fixture(engine, clock, tmp_path, rows)
    baseline(tax.state.ledger)
    if condition == "proven_scaling":
        tax.state.ledger.record_cash_flow("tax", Decimal(-100), clock.now(), Decimal(1000))
    if condition == "missing_scaling":
        with pytest.raises(DataIntegrityError):
            await tax.sync()
        assert tax.state.current() == SystemState.HALTED
        assert notices[0][1] and "secure your broker" in notices[0][0]
    else:
        await tax.sync()
    tax.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_TX_open_managed_buy_matches_holdings_without_ticket_callback(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    purchase = parse_activity(
        {
            "id": "buy",
            "activity_type": "FILL",
            "symbol": "AAA",
            "side": "buy",
            "qty": "10",
            "price": "10.00",
            "transaction_time": "2026-09-28T15:00:00Z",
            "order_id": str(UUID(int=1)),
        },
        "tax",
        "PAPER",
        clock.now(),
        fee_schedule(),
    )
    tax, _, _ = fixture(engine, clock, tmp_path, (purchase,), qty=10)
    await tax.sync()
    assert tax.book().lots[0].qty == 10
    snapshot = await tax.snapshot()
    tax._publish(tax.book(), snapshot, clock.now())
    tax.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_TX_empty_prepare_and_direct_wrong_account_batch_refuse(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    tax, source, _ = fixture(engine, clock, tmp_path)
    called: list[tuple[str, ...]] = []

    async def prepare(symbols: tuple[str, ...]) -> None:
        called.append(symbols)

    tax.prepare_fills = prepare
    await tax.sync()
    assert called == []
    batch = await source.read_activities(None, clock.now(), fee_schedule())
    with pytest.raises(DataIntegrityError):
        tax._record(batch.model_copy(update={"account_id": "other"}), False)


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
async def test_FN_TX_disabled_manual_source_cannot_read_or_use_cached_history(
    engine: Engine,
    clock: FrozenClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cached: bool,
) -> None:
    tax, source, _ = fixture(engine, clock, tmp_path)
    if cached:
        await tax.sync()
    tax.settings = Settings.validated_copy(
        tax.settings.model_copy(update={"broker_state_source": "MANUAL_CSV"})
    )

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Disabled source must not read owner CSV or account providers")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(source, "read_activities", forbidden)
    with pytest.raises(DataIntegrityError, match="entries halted"):
        await tax.sync()
    assert tax.state.current() == SystemState.HALTED
    with pytest.raises(DataIntegrityError, match="disabled by owner decision"):
        tax._record(
            ActivityBatch(
                account_id="tax",
                env="PAPER",
                as_of=clock.now(),
                complete_history=True,
                activities=(),
            ),
            False,
        )
    with pytest.raises(DataIntegrityError, match="disabled by owner decision"):
        TaxService(
            tax.project,
            tax.state,
            tax.settings,
            tax.account_id,
            tax.registry,
            tax.activities,
            tax.snapshot,
            tax.notify,
            tax.schedule,
        )
    tax.state.ledger.verify_chain()


@pytest.mark.parametrize("source", ["MANUAL_CSV", "unknown", "foreign_api"])
def test_TX_primary_manual_source_must_be_explicit_owner_csv(
    engine: Engine, clock: FrozenClock, tmp_path: Path, source: str
) -> None:
    fixture(engine, clock, tmp_path)
    if source == "foreign_api":
        (tmp_path / "config/accounts.yaml").write_text(
            "accounts:\n  - id: tax\n    name: Manual\n    tax_status: TAXABLE\n    source: CSV\n    fills_csv: fills.csv\n"
            "  - id: other\n    name: Unverified API account\n    tax_status: IRA\n    source: ALPACA\n",
            encoding="utf-8",
        )
        source = "MANUAL_CSV"
    with pytest.raises(DataIntegrityError):
        managed_accounts(tmp_path, "tax", source)


@pytest.mark.asyncio
async def test_TX_external_csv_owner_import_and_incremental_checkpoint(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    tax, source, _ = fixture(engine, clock, tmp_path)
    file = tmp_path / "external.csv"
    file.write_text(
        "id,account_id,env,symbol,side,qty,price,fees,ts,is_drip\none,ira,PAPER,AAA,BUY,1,10.00,0,2026-09-28T15:00:00Z,true\n",
        encoding="utf-8",
    )
    (tmp_path / "config/accounts.yaml").write_text(
        "accounts:\n  - id: tax\n    name: tax\n    tax_status: TAXABLE\n    source: ALPACA\n"
        "  - id: ira\n    name: IRA\n    tax_status: IRA\n    source: CSV\n    fills_csv: external.csv\n",
        encoding="utf-8",
    )
    await tax.sync()
    assert len(tax.book().lots) == 1 and tax.book().lots[0].account_id == "ira"
    source.complete = False
    tax.state.ledger.clock = FrozenClock(clock.now() + timedelta(seconds=1))
    tax.state.clock = tax.state.ledger.clock
    await tax.sync(force=True)
    with Session(engine) as session:
        assert (
            len(
                tuple(
                    session.scalars(
                        select(SecurityEvent).where(
                            SecurityEvent.kind == "TAX_FULL_HISTORY_CAPTURED"
                        )
                    )
                )
            )
            == 1
        )
    tax.state.ledger.verify_chain()


def state(engine: Engine, clock: FrozenClock) -> SystemStateStore:
    return SystemStateStore(engine, clock, ConsoleNotifier())


def settings() -> Settings:
    return Settings(
        _env_file=None,
        broker_account_type="CASH",
        broker_api_key=SecretStr("fake-paper-key"),
        broker_secret_key=SecretStr("fake-paper-secret"),
    )


def raw(kind: str = "DIV", identifier: str = "one", **changes: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "activity_type": kind,
        "date": "2026-09-23",
        "net_amount": "1.00",
        **changes,
    }


@pytest.mark.parametrize(
    "change", [None, {"date": "2026-09-23T14:00:00Z"}, {"symbol": "AAA"}, {"qty": "1.5"}]
)
def test_FΝ_02_documented_decimal_strings(change: dict[str, Any] | None) -> None:
    row = parse_activity(
        raw(**(change or {})), "tax", "PAPER", datetime(2026, 10, 6, tzinfo=UTC), fee_schedule()
    )
    assert row.amount == Decimal(1) and len(row.payload_sha256) == 64
    assert Activity.from_payload(row.model_dump(mode="json")) == row


@pytest.mark.parametrize(
    "changes",
    [
        {"net_amount": 1.0},
        {"net_amount": "NaN"},
        {"net_amount": "0.0000001"},
        {"date": "bad"},
        {"date": "2027-01-01"},
        {"activity_type": "CSW"},
        {"id": 1},
        {"id": "bad id"},
        {"activity_type": 1},
        {"symbol": "BAD / SYMBOL"},
        {"activity_type": "FILL"},
        {"net_amount": None},
        {"unknown": float("inf")},
    ],
)
def test_FN_02_invalid_ingress_never_becomes_money(changes: dict[str, Any]) -> None:
    with pytest.raises(DataIntegrityError):
        parse_activity(
            raw(**changes), "tax", "PAPER", datetime(2026, 10, 6, tzinfo=UTC), fee_schedule()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", [None, "account", "duplicate", "429", "status", "object", "range", "cancel"]
)
async def test_FN_02_full_history_paging_and_source_faults(
    engine: Engine, clock: FrozenClock, fault: str | None
) -> None:
    st = state(engine, clock)
    requests: list[httpx.Request] = []

    async def http(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET" and request.url.host == "paper-api.alpaca.markets"
        if request.url.path == "/v2/account":
            return httpx.Response(200, json={"id": "wrong" if fault == "account" else "tax"})
        assert request.url.params["page_size"] == "100" and "after" not in request.url.params
        if fault == "cancel":
            raise asyncio.CancelledError()
        if fault in {"429", "status"}:
            return httpx.Response(429 if fault == "429" else 500)
        if fault == "object":
            return httpx.Response(200, json={})
        first = "page_token" not in request.url.params
        rows = (
            [raw(identifier=f"old-{number}", date="2025-09-01") for number in range(100)]
            if first
            else [raw(identifier="latest")]
        )
        if fault == "duplicate":
            rows[1] = rows[0]
        if fault == "range":
            rows[0]["date"] = "2027-01-01"
        return httpx.Response(200, json=rows)

    reader = AsyncAlpacaReader(clock, st)
    source = AlpacaActivitiesSource(
        settings(),
        "tax",
        st,
        clock,
        reader,
        EgressPolicy(build_allowlist(), st.ledger),
        transport=httpx.MockTransport(http),
    )
    try:
        if fault is None:
            batch = await source.read_activities(None, clock.now(), fee_schedule())
            assert batch.complete_history and len(batch.activities) == 101
            assert len(requests) == 3 and requests[-1].url.params["page_token"] == "old-99"
            assert min(row.date for row in batch.activities).year == 2025
        else:
            with pytest.raises(asyncio.CancelledError if fault == "cancel" else DataIntegrityError):
                await source.read_activities(None, clock.now(), fee_schedule())
            assert st.current() == SystemState.HALTED
    finally:
        await source.close()


class Activities:
    def __init__(self, st: SystemStateStore, rows: tuple[Activity, ...] = ()) -> None:
        self.state, self.rows = st, rows
        self.complete = True
        self.starts: list[datetime | None] = []

    async def read_activities(
        self, after: datetime | None, until: datetime, schedule: Any
    ) -> ActivityBatch:
        self.starts.append(after)
        return ActivityBatch(
            account_id="tax",
            env="PAPER",
            as_of=until,
            complete_history=self.complete,
            activities=tuple(
                Activity.model_validate(row.model_copy(update={"observed_at": until}))
                for row in self.rows
            ),
        )


def fixture(
    engine: Engine,
    clock: FrozenClock,
    project: Path,
    rows: tuple[Activity, ...] = (),
    *,
    equity: str = "1000",
    qty: int = 0,
) -> tuple[TaxService, Activities, list[tuple[str, bool]]]:
    (project / "config").mkdir(exist_ok=True)
    (project / "config/accounts.yaml").write_text("accounts: []\n", encoding="utf-8")
    st = state(engine, clock)
    source, notices = Activities(st, rows), []

    async def snapshot() -> PortfolioSnapshot:
        positions = (
            {}
            if not qty
            else {"AAA": Position(qty=qty, avg_cost=Decimal(10), last_price=Decimal(10))}
        )
        cash = Decimal(equity) - qty * Decimal(10)
        st.ledger.append(
            PortfolioState,
            account_id="tax",
            account_type=AccountType.CASH,
            as_of=clock.now(),
            equity=Decimal(equity),
            cash=cash,
            settled_cash=cash,
            positions={name: pos.model_dump(mode="json") for name, pos in positions.items()},
            high_water_mark=Decimal(equity),
            day_start_equity=Decimal(equity),
        )
        return PortfolioSnapshot(
            account_id="tax",
            as_of=clock.now(),
            account_type=AccountType.CASH,
            equity=Decimal(equity),
            cash=cash,
            settled_cash=cash,
            positions=positions,
            open_orders=(),
            high_water_mark=Decimal(equity),
            day_start_equity=Decimal(equity),
        )

    async def notify(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    return (
        TaxService(
            project, st, settings(), "tax", registry(), source, snapshot, notify, fee_schedule()
        ),
        source,
        notices,
    )


@pytest.mark.asyncio
async def test_TX_H_complete_capture_restart_context_and_dividend(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    dividend = parse_activity(raw(), "tax", "PAPER", clock.now(), fee_schedule())
    tax, source, notices = fixture(engine, clock, tmp_path, (dividend,))
    assert (await tax.sync()).counts["cash_activities_recorded"] == 1
    assert (await tax.sync()).counts == {"account_context_cached": 1}
    assert tax.incomes()[0].dividend_class == "unclassified"
    tax._fresh = None
    assert (await tax.sync()).counts["cash_activities_recorded"] == 0
    assert source.starts[0] is None and source.starts[1] == clock.now() - timedelta(seconds=1)
    assert len(notices) == 1
    with Session(engine) as session:
        assert len(tuple(session.scalars(select(CashFlow)))) == 1
        assert len(tuple(session.scalars(select(TaxEvent)))) == 1
    tax.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["incomplete", "holdings", "account", "withdrawal_and_missing_buy"]
)
async def test_TX_H_missing_history_halts_but_verified_withdrawal_alerts(
    engine: Engine, clock: FrozenClock, tmp_path: Path, fault: str
) -> None:
    rows: tuple[Activity, ...] = ()
    if fault == "withdrawal_and_missing_buy":
        rows = (
            parse_activity(
                raw("CSW", net_amount="-1.00"), "tax", "PAPER", clock.now(), fee_schedule()
            ),
        )
    tax, source, notices = fixture(
        engine,
        clock,
        tmp_path,
        rows,
        qty=1 if fault in {"holdings", "withdrawal_and_missing_buy"} else 0,
    )
    source.complete = fault != "incomplete"
    if fault == "account":
        tax.account_id = "wrong"
    with pytest.raises(DataIntegrityError):
        await tax.sync()
    assert tax.state.current() == SystemState.HALTED
    if fault == "withdrawal_and_missing_buy":
        assert notices[0][1] and "secure your broker account" in notices[0][0]
    tax.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_PL_01_portfolio_history_exact_json_get(engine: Engine, clock: FrozenClock) -> None:
    clock = FrozenClock(datetime(2026, 10, 6, 21, tzinfo=UTC))
    st = state(engine, clock)

    async def http(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/account":
            return httpx.Response(200, json={"id": "tax"})
        assert request.method == "GET" and request.url.params["timeframe"] == "1D"
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "timeframe": "1D",
                    "timestamp": [int(datetime(2026, 10, 6, 20, tzinfo=UTC).timestamp())],
                    "equity": [1234.56],
                }
            ).encode(),
        )

    source = AlpacaActivitiesSource(
        settings(),
        "tax",
        st,
        clock,
        AsyncAlpacaReader(clock, st),
        EgressPolicy(build_allowlist(), st.ledger),
        transport=httpx.MockTransport(http),
    )
    try:
        result = await read_history(source, date(2026, 10, 6), date(2026, 10, 6), MarketCalendar())
        assert result.closes[0].equity == Decimal("1234.56")
    finally:
        await source.close()


@pytest.mark.asyncio
async def test_PL_TX_runtime_capture_backfills_flow_math_and_private_commands(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    flow = tuple(
        parse_activity(
            raw(kind, str(number), date=day, net_amount=amount),
            "tax",
            "PAPER",
            clock.now(),
            fee_schedule(),
        )
        for number, (kind, day, amount) in enumerate(
            [
                ("CSD", "2026-09-23", "1000"),
                ("CSD", "2026-09-24", "1000"),
                ("CSW", "2026-09-25", "-500"),
            ]
        )
    )
    tax, _, notices = fixture(engine, clock, tmp_path, flow, equity="1500")

    async def history(start: date, end: date) -> EquityHistory:
        return EquityHistory(
            account_id="tax",
            env="PAPER",
            as_of=clock.now(),
            sha256="b" * 64,
            closes=tuple(
                EquityClose(session=day, equity=Decimal(amount))
                for day, amount in [
                    (date(2026, 9, 23), "1000"),
                    (date(2026, 9, 24), "2000"),
                    (date(2026, 9, 25), "1500"),
                    (date(2026, 9, 28), "1500"),
                    (date(2026, 9, 29), "1500"),
                ]
            ),
        )

    async def spy(start: date, end: date) -> tuple[tuple[date, Decimal], ...]:
        return tuple(
            (date(2026, 9, day), Decimal(100 + index))
            for index, day in enumerate([22, 23, 24, 25, 28, 29])
        )

    reports = AccountingReports(tax, MarketCalendar(), 10, history, spy)
    assert "UNVERIFIED" in (await reports.pnl("today"))[0]
    assert NOTICE in (await reports.tax_summary())[0]
    result = await reports.capture()
    assert result.counts["pnl_sessions_recorded"] == 5
    series = read_days(tax.state.ledger, "tax", "PAPER")
    assert len(series) == 5 and all(row.day_pnl == 0 and row.day_ret == 0 for row in series)
    assert all(row.source == "COMPUTED" for row in series)
    assert "SPY 5.00% (price only)" in "".join(await reports.pnl("week"))
    assert "7-day avg $+0.00/day" in await reports.digest_line()
    text = "".join(await reports.tax_summary())
    assert SIMULATED in text and "Rates unset: totals only" in text and NOTICE in text
    assert any(urgent and "Withdrawal" in text for text, urgent in notices)
    assert "Use /pnl" in (await reports.pnl("garbage"))[0]
    assert "Use /tax" in (await reports.tax_summary("bad"))[0]
    tax.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("fee_evidence", ["broker", "modeled", "contradictory", "refund"])
async def test_CM_04_actual_fee_cash_is_never_counted_twice_or_guessed(
    engine: Engine, tmp_path: Path, fee_evidence: str
) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    cash = parse_activity(
        raw("CSD", "deposit", date="2026-09-23", net_amount="1000"),
        "tax",
        "PAPER",
        clock.now(),
        fee_schedule(),
    )
    charge = parse_activity(
        raw(
            "FEE",
            "fee",
            date="2026-09-25",
            net_amount="0.25" if fee_evidence == "refund" else "-0.25",
        ),
        "tax",
        "PAPER",
        clock.now(),
        fee_schedule(),
    )
    fills = tuple(
        parse_activity(
            {
                "id": identity,
                "activity_type": "FILL",
                "symbol": "AAA",
                "side": side,
                "qty": "10",
                "price": "10.00",
                "transaction_time": stamp,
                "order_id": str(UUID(int=number)),
            },
            "tax",
            "PAPER",
            clock.now(),
            fee_schedule(),
        )
        for number, identity, side, stamp in [
            (1, "buy", "buy", "2026-09-24T15:00:00Z"),
            (2, "sell", "sell", "2026-09-25T15:00:00Z"),
        ]
    )
    if fee_evidence != "modeled":
        replaced: list[Activity] = []
        for row in fills:
            assert row.fill is not None
            amount = (
                Decimal(0)
                if row.fill.side.value == "BUY"
                else Decimal("0.50" if fee_evidence == "contradictory" else "0.25")
            )
            replaced.append(
                Activity.model_validate(
                    row.model_copy(
                        update={
                            "fill": row.fill.model_copy(
                                update={"fees": amount, "fee_source": "BROKER"}
                            )
                        }
                    )
                )
            )
        fills = tuple(replaced)
    tax, _, _ = fixture(engine, clock, tmp_path, (cash, *fills, charge), equity="999.75")

    async def history(start: date, end: date) -> EquityHistory:
        return EquityHistory(
            account_id="tax",
            env="PAPER",
            as_of=clock.now(),
            sha256="b" * 64,
            closes=tuple(
                EquityClose(
                    session=date(2026, 9, day), equity=Decimal("1000" if day < 25 else "999.75")
                )
                for day in (23, 24, 25, 28, 29)
            ),
        )

    async def spy(start: date, end: date) -> tuple[tuple[date, Decimal], ...]:
        return ()

    reports = AccountingReports(tax, MarketCalendar(), 10, history, spy)
    if fee_evidence != "broker":
        with pytest.raises(DataIntegrityError):
            await reports.capture()
        assert tax.state.current() == SystemState.HALTED
    else:
        await reports.capture()
        rows = read_days(tax.state.ledger, "tax", "PAPER")
        charged = next(row for row in rows if row.observation.session == date(2026, 9, 25))
        assert charged.observation.fees == Decimal("0.25")
        assert charged.day_pnl == Decimal("-0.25") and charged.observation.cash == Decimal("999.75")
    tax.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("older_funding", [False, True])
async def test_PL_unavailable_history_uses_verified_close_but_never_invents_gaps(
    engine: Engine, tmp_path: Path, older_funding: bool
) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    deposit = parse_activity(
        raw(
            "CSD",
            "deposit",
            date="2026-09-23" if older_funding else "2026-09-29",
            net_amount="1000",
        ),
        "tax",
        "PAPER",
        clock.now(),
        fee_schedule(),
    )
    tax, _, _ = fixture(engine, clock, tmp_path, (deposit,))

    async def missing(start: date, end: date) -> EquityHistory:
        raise DataIntegrityError("Synthetic missing history")

    async def spy(start: date, end: date) -> tuple[tuple[date, Decimal], ...]:
        return ()

    reports = AccountingReports(tax, MarketCalendar(), 10, missing, spy)
    if older_funding:
        with pytest.raises(DataIntegrityError):
            await reports.capture()
        assert not read_days(tax.state.ledger, "tax", "PAPER")
        assert tax.state.current() == SystemState.HALTED
    else:
        result = await reports.capture()
        assert result.counts["pnl_sessions_recorded"] == 1
        daily = read_days(tax.state.ledger, "tax", "PAPER")[0]
        assert daily.day_pnl == 0 and daily.source == "COMPUTED"
    tax.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_TX_real_fills_prepare_public_provenance_and_review_marked_401k(
    engine: Engine,
    tmp_path: Path,
) -> None:
    clock = FrozenClock(datetime(2026, 10, 6, 21, tzinfo=UTC))
    rows = tuple(
        parse_activity(
            {
                "id": f"trade-{identifier}",
                "activity_type": "FILL",
                "symbol": "AAA",
                "side": side,
                "qty": "10",
                "price": price,
                "transaction_time": stamp,
                "order_id": str(UUID(int=identifier)),
            },
            "tax",
            "PAPER",
            clock.now(),
            fee_schedule(),
        )
        for identifier, side, price, stamp in [
            (1, "buy", "10.00", "2026-06-24T15:00:00Z"),
            (2, "sell", "9.00", "2026-10-02T15:00:00Z"),
        ]
    )
    tax, _, notices = fixture(engine, clock, tmp_path, rows)
    seen: list[ObservedFill] = []
    prepared: list[tuple[str, ...]] = []
    tax.observe_fill = seen.append

    async def prepare(symbols: tuple[str, ...]) -> None:
        prepared.append(symbols)

    tax.prepare_fills = prepare
    file = tmp_path / "marks.csv"
    file.write_text(
        "lot_id,account_id,symbol,qty,cost_basis,acquired_at,funding_settlement_date,acquisition_trade_id,holding_period_start\n"
        + f"{UUID(int=55)},owner-401k,AAA,2,10.00,2026-10-01T15:00:00Z,2026-10-02,{UUID(int=56)},2026-09-01T15:00:00Z\n",
        encoding="utf-8",
    )
    import_marked_lots(tax.state.ledger, file, "PAPER")
    result = await tax.sync()
    assert result.counts["fills_observed"] == 2 and len(seen) == 2 and prepared == [("AAA",)]
    assert any("overlapping external lots" in text and "401(k)" in text for text, _ in notices)
    before = len(notices)
    await tax.sync(force=True)
    assert len(notices) == before
    tax.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["account_config", "checkpoint", "context_env", "stale_snapshot"])
async def test_TX_service_binding_cannot_publish_unverified_context(
    engine: Engine, clock: FrozenClock, tmp_path: Path, fault: str
) -> None:
    tax, _, _ = fixture(engine, clock, tmp_path)
    if fault == "account_config":
        (tmp_path / "config/accounts.yaml").write_text(
            "accounts:\n  - id: wrong\n    name: wrong\n    tax_status: TAXABLE\n    source: ALPACA\n",
            encoding="utf-8",
        )
        with pytest.raises(DataIntegrityError):
            managed_accounts(tmp_path, "tax")
    elif fault == "checkpoint":
        tax.state.ledger.append(
            SecurityEvent,
            kind="ACCOUNT_ACTIVITIES_CAPTURED",
            detail={
                "account_id": "tax",
                "cohort": "PAPER",
                "until": (clock.now() + timedelta(seconds=1)).isoformat(),
            },
        )
        with pytest.raises(DataIntegrityError):
            tax._checkpoint()
    else:
        snapshot = await tax.snapshot()
        if fault == "context_env":
            tax.env = "LIVE"
        else:
            snapshot = snapshot.model_copy(update={"as_of": clock.now() - timedelta(seconds=31)})
        with pytest.raises(DataIntegrityError):
            tax._publish(tax.book(), snapshot, clock.now())
