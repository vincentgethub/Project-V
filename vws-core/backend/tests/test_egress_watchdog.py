"""EGR: monthly outbound byte budget for the paper host.

Every reading comes from synthetic /proc/net/dev and /proc/net/route files under
tmp_path. No test reads the real /proc or opens a network connection.
"""

import json
import os
import stat
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.config import YamlConfig
from backend.core.database import SecurityEvent
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    EgressDeniedError,
    ExecutionDisabledError,
)
from backend.core.ledger import Ledger
from backend.net import egress
from backend.net.egress import EgressPolicy, build_allowlist
from backend.ops.egress_budget import (
    DEFAULT_BUDGET_BYTES,
    ESSENTIAL_PURPOSES,
    EgressLevel,
    EgressWatch,
    budget_from,
    default_interface,
    tx_bytes,
)
from backend.ops.macro_events import MacroCalendar
from backend.realtime.desk import RealtimeDesk
from backend.realtime.schedules import Schedules
from backend.realtime.storage import RealtimeStore
from backend.tests.test_w_core import CAL, SCOPE
from backend.tests.test_w_learning_feeds import baseline as baseline

NOV = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
ROUTE_HEADER = "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT"
DEV_HEADER = (
    "Inter-|   Receive                                                |  Transmit\n"
    " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs "
    "drop fifo colls carrier compressed\n"
)
NON_ESSENTIAL = (
    "llm",
    "rss",
    "newsapi",
    "alpaca-news-stream",
    "sec-edgar",
    "fred",
    "nasdaq-halts",
    "official-schedules",
    "unknown-purpose",
)
REDUCE_ONLY = ("alpaca", "alpaca-order", "alpaca_fills", "sdk", "telegram_api", "job_health")


def dev_line(iface: str, tx: int, rx: int = 7) -> str:
    return f"{iface:>6}: {rx} 1 0 0 0 0 0 0 {tx} 2 0 0 0 0 0 0\n"


def write_proc(
    root: Path,
    tx: int,
    *,
    iface: str = "ens4",
    route: str | None = None,
    extra: str = "",
) -> Path:
    net = root / "net"
    net.mkdir(parents=True, exist_ok=True)
    (net / "dev").write_text(
        DEV_HEADER + dev_line("lo", 999999999999) + dev_line(iface, tx) + extra
    )
    (net / "route").write_text(
        route
        if route is not None
        else (
            ROUTE_HEADER
            + "\n"
            + "lo\t00000000\t00000000\t0001\t0\t0\t0\t00000000\t0\t0\t0\n"
            + f"{iface}\t00000000\t0100800A\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
            + f"{iface}\t0000800A\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n"
        )
    )
    return root


def watch(
    tmp_path: Path, tx: int, *, at: datetime = NOV, budget: str | None = None
) -> tuple[EgressWatch, Path]:
    proc = write_proc(tmp_path / "proc", tx)
    state = tmp_path / "data" / "egress-counter.json"
    state.parent.mkdir(exist_ok=True)
    return EgressWatch(state, FrozenClock(at), proc=proc, budget=budget, platform="linux"), state


def seed(state: Path, *, month: str = "2026-11", used: int, last: int, iface: str = "ens4") -> None:
    state.write_text(
        json.dumps({"version": 1, "month": month, "iface": iface, "last": last, "used": used})
    )


def saved(state: Path) -> dict[str, object]:
    value = json.loads(state.read_text())
    assert isinstance(value, dict)
    return value


@pytest.fixture(autouse=True)
def no_global_budget() -> Iterator[None]:
    egress.configure_budget(None)
    yield
    egress.configure_budget(None)


def test_EGR_primary_interface_is_the_lowest_metric_default_route_never_lo() -> None:
    table = (
        ROUTE_HEADER
        + "\nlo\t00000000\t00000000\t0001\t0\t0\t0\t00000000\t0\t0\t0\n"
        + "wlan0\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
        + "eth0\t00000000\t0100A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
        + "eth1\t00000000\t0100A8C0\t0002\t0\t0\t1\t00000000\t0\t0\t0\n"
        + "eth2\t0000A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
    )
    assert default_interface(table) == "eth0"


@pytest.mark.parametrize(
    "table",
    [
        "",
        ROUTE_HEADER + "\n",
        ROUTE_HEADER + "\nlo\t00000000\t00000000\t0003\t0\t0\t0\t00000000\t0\t0\t0\n",
        "Iface\tGateway\n" + "eth0\t00000000\n",
        "Iface\tDestination\tGateway\tFlags\tRefCnt\n" + "eth0\t00000000\t0\t0003\t0\n",
        ROUTE_HEADER + "\neth0\t00000000\t0100A8C0\tzz\t0\t0\t100\t00000000\t0\t0\t0\n",
        ROUTE_HEADER + "\neth0\t00000000\n",
        ROUTE_HEADER + "\nbad/if\t00000000\t0100A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n",
    ],
)
def test_EGR_missing_or_malformed_default_route_is_refused(table: str) -> None:
    with pytest.raises(DataIntegrityError, match="EGR"):
        default_interface(table)


def test_EGR_tx_bytes_reads_the_transmit_column_of_the_named_interface() -> None:
    text = DEV_HEADER + dev_line("lo", 5) + dev_line("ens4", 123456, rx=999)
    assert tx_bytes(text, "ens4") == 123456


@pytest.mark.parametrize(
    "text",
    [
        DEV_HEADER + dev_line("lo", 5),
        DEV_HEADER + "  ens4: 1 2 3\n",
        DEV_HEADER + "  ens4: 1 2 3 4 5 6 7 8 -9 1 2 3 4 5 6 7\n",
        DEV_HEADER + "  ens4: 1 2 3 4 5 6 7 8 x 1 2 3 4 5 6 7\n",
        DEV_HEADER + "  ens4 1 2 3 4 5 6 7 8 9 1 2 3 4 5 6 7\n",
        DEV_HEADER + dev_line("ens4", 1) + dev_line("ens4", 2),
    ],
)
def test_EGR_unreadable_dev_counters_are_refused(text: str) -> None:
    with pytest.raises(DataIntegrityError, match="EGR"):
        tx_bytes(text, "ens4")


@pytest.mark.parametrize(
    ("raw", "budget", "refused"),
    [
        (None, DEFAULT_BUDGET_BYTES, False),
        ("", DEFAULT_BUDGET_BYTES, True),
        ("500000000", 500_000_000, False),
        (str(DEFAULT_BUDGET_BYTES), DEFAULT_BUDGET_BYTES, False),
        (str(DEFAULT_BUDGET_BYTES + 1), DEFAULT_BUDGET_BYTES, True),
        ("5000000000", DEFAULT_BUDGET_BYTES, True),
        ("0", DEFAULT_BUDGET_BYTES, True),
        ("-5", DEFAULT_BUDGET_BYTES, True),
        ("1e9", DEFAULT_BUDGET_BYTES, True),
        (" 500 ", DEFAULT_BUDGET_BYTES, True),
        ("1" * 40, DEFAULT_BUDGET_BYTES, True),
    ],
)
def test_EGR_budget_is_configurable_only_downward(
    raw: str | None, budget: int, refused: bool
) -> None:
    value, reason = budget_from(raw)
    assert value == budget and (reason is not None) == refused
    assert DEFAULT_BUDGET_BYTES == 1_000_000_000


def test_EGR_missing_counter_counts_as_over_budget_then_initializes_conservatively(
    tmp_path: Path,
) -> None:
    gauge, state = watch(tmp_path, 4000, budget="10000")
    first = gauge.sample()
    assert first.level == EgressLevel.BLOCKED and "missing" in first.reason
    # All bytes the kernel reports since boot are charged to this month.
    assert saved(state) == {
        "version": 1,
        "month": "2026-11",
        "iface": "ens4",
        "last": 4000,
        "used": 4000,
    }
    assert stat.S_IMODE(os.stat(state).st_mode) == 0o600
    assert not list(state.parent.glob("*.tmp"))
    write_proc(tmp_path / "proc", 4500)
    second = gauge.sample()
    assert second.level == EgressLevel.OK and second.used == 4500


@pytest.mark.parametrize(
    ("used", "level"),
    [
        (0, EgressLevel.OK),
        (7999, EgressLevel.OK),
        (8000, EgressLevel.PAUSED),
        (9499, EgressLevel.PAUSED),
        (9500, EgressLevel.BLOCKED),
        (10000, EgressLevel.BLOCKED),
        (25000, EgressLevel.BLOCKED),
    ],
)
def test_EGR_thresholds_pause_at_80_and_block_at_95_percent_inclusive(
    tmp_path: Path, used: int, level: EgressLevel
) -> None:
    gauge, state = watch(tmp_path, 100, budget="10000")
    seed(state, used=used, last=100)
    status = gauge.sample()
    assert status.level == level and status.used == used and status.budget == 10000
    assert gauge.allows("llm") == (level == EgressLevel.OK)
    assert gauge.entries_blocked() == (level == EgressLevel.BLOCKED)


def test_EGR_default_budget_edges_are_exact(tmp_path: Path) -> None:
    gauge, state = watch(tmp_path, 0)
    for used, level in (
        (799_999_999, EgressLevel.OK),
        (800_000_000, EgressLevel.PAUSED),
        (949_999_999, EgressLevel.PAUSED),
        (950_000_000, EgressLevel.BLOCKED),
    ):
        seed(state, used=used, last=0)
        assert gauge.sample().level == level


def test_EGR_counter_accumulates_deltas_within_the_month(tmp_path: Path) -> None:
    gauge, state = watch(tmp_path, 1500, budget="10000")
    seed(state, used=300, last=1000)
    assert gauge.sample().used == 800
    assert saved(state)["last"] == 1500


def test_EGR_utc_month_rollover_starts_a_new_count(tmp_path: Path) -> None:
    # 2026-12-01 00:30 UTC is still Nov 30 in Chicago; the counter uses the UTC calendar month.
    gauge, state = watch(
        tmp_path, 1200, budget="10000", at=datetime(2026, 12, 1, 0, 30, tzinfo=UTC)
    )
    seed(state, month="2026-11", used=9900, last=1000)
    status = gauge.sample()
    assert status.level == EgressLevel.OK and status.month == "2026-12" and status.used == 200
    assert saved(state)["month"] == "2026-12"


def test_EGR_reboot_counter_reset_never_lowers_the_count(tmp_path: Path) -> None:
    gauge, state = watch(tmp_path, 250, budget="10000")
    seed(state, used=7000, last=900000)
    status = gauge.sample()
    assert status.used == 7250 and saved(state)["last"] == 250


def test_EGR_kernel_counter_wrap_adds_the_new_reading_never_a_negative(tmp_path: Path) -> None:
    gauge, state = watch(tmp_path, 5, budget="10000")
    seed(state, used=7000, last=2**64 - 10)
    assert gauge.sample().used == 7005


def test_EGR_interface_change_charges_the_whole_new_reading(tmp_path: Path) -> None:
    gauge, state = watch(tmp_path, 900, budget="10000")
    seed(state, used=100, last=50, iface="eth9")
    assert gauge.sample().used == 1000 and saved(state)["iface"] == "ens4"


@pytest.mark.parametrize(
    "contents",
    [
        "not json",
        "[]",
        json.dumps({"version": 1, "month": "2026-11", "iface": "ens4", "last": 1}),
        json.dumps({"version": 2, "month": "2026-11", "iface": "ens4", "last": 1, "used": 1}),
        json.dumps({"version": 1, "month": "2026-13", "iface": "ens4", "last": 1, "used": 1}),
        json.dumps({"version": 1, "month": "2026-11", "iface": "e/s", "last": 1, "used": 1}),
        json.dumps({"version": 1, "month": "2026-11", "iface": "ens4", "last": -1, "used": 1}),
        json.dumps({"version": 1, "month": "2026-11", "iface": "ens4", "last": 1, "used": True}),
        json.dumps({"version": 1, "month": "2026-11", "iface": "ens4", "last": 1, "used": 1.5}),
        json.dumps(
            {"version": 1, "month": "2026-11", "iface": "ens4", "last": 1, "used": 1, "x": 1}
        ),
        json.dumps({"version": 1, "month": "2027-01", "iface": "ens4", "last": 1, "used": 1}),
        " " * 5000,
    ],
)
def test_EGR_corrupt_counter_is_over_budget_and_left_for_the_operator(
    tmp_path: Path, contents: str
) -> None:
    gauge, state = watch(tmp_path, 100, budget="10000")
    state.write_text(contents)
    status = gauge.sample()
    assert status.level == EgressLevel.BLOCKED and "counter" in status.reason
    assert state.read_text() == contents
    assert not gauge.allows("llm") and gauge.entries_blocked()


@pytest.mark.parametrize("broken", ["dev", "route", "proc", "unsupported", "state_dir"])
def test_EGR_unreadable_sources_count_as_over_budget(tmp_path: Path, broken: str) -> None:
    gauge, state = watch(tmp_path, 100, budget="10000")
    seed(state, used=0, last=100)
    before = state.read_text()
    if broken in {"dev", "route"}:
        (tmp_path / "proc" / "net" / broken).unlink()
    elif broken == "proc":
        (tmp_path / "proc" / "net" / "dev").write_text("x" * (1_048_576 + 1))
    elif broken == "unsupported":
        gauge = EgressWatch(state, FrozenClock(NOV), proc=tmp_path / "proc", platform="win32")
    else:
        state.unlink()
        state.parent.rmdir()
    status = gauge.sample()
    assert status.level == EgressLevel.BLOCKED
    assert gauge.entries_blocked() and not gauge.allows("rss")
    if broken != "state_dir":
        assert state.read_text() == before


def test_EGR_status_is_cached_briefly_then_resampled(tmp_path: Path) -> None:
    clock = FrozenClock(NOV)
    proc = write_proc(tmp_path / "proc", 100)
    state = tmp_path / "egress-counter.json"
    seed(state, used=0, last=100)
    gauge = EgressWatch(state, clock, proc=proc, budget="10000", platform="linux")
    assert gauge.status().level == EgressLevel.OK
    seed(state, used=9600, last=100)
    assert gauge.status().level == EgressLevel.OK
    object.__setattr__(clock, "current", datetime(2026, 11, 16, 12, 1, tzinfo=UTC))
    assert gauge.status().level == EgressLevel.BLOCKED
    with pytest.raises(ConfigurationError):
        EgressWatch(state, clock, proc=proc, max_age_seconds=0)


@pytest.mark.parametrize("condition", ["95", "unreadable"])
def test_EGR_reduce_only_broker_and_healthcheck_paths_stay_open(
    tmp_path: Path, condition: str
) -> None:
    gauge, state = watch(tmp_path, 100, budget="10000")
    if condition == "95":
        seed(state, used=9500, last=100)
    else:
        state.write_text("corrupt")
    assert gauge.sample().level == EgressLevel.BLOCKED
    assert set(REDUCE_ONLY) == ESSENTIAL_PURPOSES - {"telegram"}
    for purpose in (*REDUCE_ONLY, "telegram"):
        assert gauge.allows(purpose), purpose
    for purpose in NON_ESSENTIAL:
        assert not gauge.allows(purpose), purpose


def test_EGR_80_percent_pauses_only_non_essential_egress(tmp_path: Path) -> None:
    gauge, state = watch(tmp_path, 100, budget="10000")
    seed(state, used=8000, last=100)
    assert gauge.sample().level == EgressLevel.PAUSED
    assert all(gauge.allows(purpose) for purpose in ESSENTIAL_PURPOSES)
    assert not any(gauge.allows(purpose) for purpose in NON_ESSENTIAL)
    assert not gauge.entries_blocked()


def test_EGR_a_failing_gauge_allows_only_reduce_only_paths(tmp_path: Path) -> None:
    gauge, _ = watch(tmp_path, 100)

    def broken() -> object:
        raise RuntimeError("boom")

    object.__setattr__(gauge, "sample", broken)
    assert gauge.entries_blocked() and not gauge.allows("llm") and gauge.allows("alpaca-order")


@pytest.mark.parametrize("condition", ["80", "95", "unreadable"])
def test_EGR_policy_gate_denies_non_essential_with_an_audit_row_and_keeps_broker_open(
    engine: Engine, clock: FrozenClock, tmp_path: Path, condition: str
) -> None:
    gauge, state = watch(tmp_path, 100, budget="10000")
    if condition == "unreadable":
        (tmp_path / "proc" / "net" / "dev").unlink()
    else:
        seed(state, used=8000 if condition == "80" else 9500, last=100)
    ledger = Ledger(engine, clock)
    policy = EgressPolicy(
        build_allowlist(
            rss_urls=("https://feeds.example.org/rss",),
            healthcheck_url="https://hc-ping.com/abc",
        ),
        ledger,
    )
    assert policy.check_url("https://feeds.example.org/rss", purpose="rss") == "feeds.example.org"
    egress.configure_budget(gauge)
    with pytest.raises(EgressDeniedError, match="budget"):
        policy.check_url("https://feeds.example.org/rss", purpose="rss")
    for url, purpose in (
        ("https://paper-api.alpaca.markets/v2/orders", "alpaca-order"),
        ("https://paper-api.alpaca.markets/v2/positions", "alpaca"),
        ("https://paper-api.alpaca.markets/v2/account/activities", "alpaca_fills"),
        ("https://api.telegram.org/bot/sendMessage", "telegram_api"),
        ("https://hc-ping.com/abc", "job_health"),
    ):
        assert policy.check_url(url, purpose=purpose) == url.split("/")[2]
    with Session(engine) as session:
        denied = session.scalars(
            select(SecurityEvent).where(SecurityEvent.kind == "EGRESS_DENIED")
        ).all()
    assert [row.detail["purpose"] for row in denied] == ["rss"]
    egress.configure_budget(None)
    assert policy.check_url("https://feeds.example.org/rss", purpose="rss") == "feeds.example.org"
    not_a_gate: object = object()
    with pytest.raises(ConfigurationError):
        egress.configure_budget(not_a_gate)


@pytest.mark.parametrize("condition", ["OK", "80", "95", "unreadable"])
@pytest.mark.asyncio
async def test_EGR_95_percent_blocks_new_entries_and_never_exits(
    engine: Engine, clock: FrozenClock, baseline: YamlConfig, tmp_path: Path, condition: str
) -> None:
    gauge, state = watch(tmp_path, 100, budget="10000")
    if condition == "unreadable":
        state.write_text("{")
    else:
        seed(state, used={"OK": 0, "80": 8000, "95": 9500}[condition], last=100)
    store = RealtimeStore(Ledger(engine, clock), SCOPE, baseline.config_hash)
    schedules = Schedules(
        store.ledger, MacroCalendar(tmp_path / "missing.csv"), tmp_path / "events_policy.yaml"
    )
    desk = RealtimeDesk(store, baseline, CAL, schedules, lambda: True, egress=gauge)
    if condition in {"95", "unreadable"}:
        with pytest.raises(ExecutionDisabledError, match="EGR-95"):
            await desk.require_entry(uuid4())
        assert any("EGR" in line for line in desk.statuses())
    else:
        # Not blocked by egress: the ordinary opening-proposal binding check runs next.
        with pytest.raises(DataIntegrityError, match="RT-10"):
            await desk.require_entry(uuid4())
    # Held-position exits have no egress gate.
    assert desk.hard_exit("NVDA", clock.now()) is None


@pytest.mark.asyncio
async def test_EGR_alerts_once_per_month_and_level_and_retries_failed_delivery(
    tmp_path: Path,
) -> None:
    gauge, state = watch(tmp_path, 100, budget="10000")
    sent: list[str] = []
    fail = [True]

    async def notify(message: str) -> None:
        if fail[0]:
            fail[0] = False
            raise RuntimeError("telegram down")
        sent.append(message)

    seed(state, used=0, last=100)
    assert await gauge.alert(notify) is False and not sent
    seed(state, used=8000, last=100)
    gauge.sample()
    assert await gauge.alert(notify) is False and not sent  # delivery failed; not marked
    assert await gauge.alert(notify) is True and "80%" in sent[-1]
    assert await gauge.alert(notify) is False and len(sent) == 1
    seed(state, used=9500, last=100)
    gauge.sample()
    assert await gauge.alert(notify) is True and "95%" in sent[-1] and "blocked" in sent[-1]
    assert await gauge.alert(notify) is False and len(sent) == 2


@pytest.mark.asyncio
async def test_EGR_upward_budget_and_unreadable_counter_alert(tmp_path: Path) -> None:
    gauge, state = watch(tmp_path, 100, budget=str(DEFAULT_BUDGET_BYTES * 5))
    assert gauge.budget == DEFAULT_BUDGET_BYTES
    sent: list[str] = []

    async def notify(message: str) -> None:
        sent.append(message)

    seed(state, used=0, last=100)
    gauge.sample()
    assert await gauge.alert(notify) is True and "refused" in sent[0]
    state.write_text("corrupt")
    gauge.sample()
    assert await gauge.alert(notify) is True and "counter" in sent[1]
    assert await gauge.alert(notify) is False and len(sent) == 2


class Broken:
    def allows(self, purpose: str) -> bool:
        raise RuntimeError("gauge failed")

    def entries_blocked(self) -> bool:
        raise RuntimeError("gauge failed")

    def status_line(self) -> str | None:
        raise RuntimeError("gauge failed")


@pytest.mark.asyncio
async def test_EGR_a_raising_gate_fails_closed_for_entries_and_non_essential_egress(
    engine: Engine, clock: FrozenClock, baseline: YamlConfig, tmp_path: Path
) -> None:
    ledger = Ledger(engine, clock)
    policy = EgressPolicy(build_allowlist(), ledger)
    egress.configure_budget(Broken())
    with pytest.raises(EgressDeniedError, match="budget"):
        policy.check_url("https://www.sec.gov/x", purpose="sec-edgar")
    store = RealtimeStore(ledger, SCOPE, baseline.config_hash)
    schedules = Schedules(
        store.ledger, MacroCalendar(tmp_path / "missing.csv"), tmp_path / "events_policy.yaml"
    )
    desk = RealtimeDesk(store, baseline, CAL, schedules, lambda: True, egress=Broken())
    with pytest.raises(ExecutionDisabledError, match="EGR-95"):
        await desk.require_entry(uuid4())
    assert "EGR: egress budget UNVERIFIED; treated as 95%" in desk.statuses()
    ok, state = watch(tmp_path, 100, budget="10000")
    seed(state, used=0, last=100)
    plain = RealtimeDesk(store, baseline, CAL, schedules, lambda: True, egress=ok)
    assert not any(line.startswith("EGR") for line in plain.statuses())


INVALID_BUDGETS = {
    "zero": "0",
    "negative": "-5",
    "non-numeric": "lots",
    "empty": "",
    "too-high": str(DEFAULT_BUDGET_BYTES * 5),
}


@pytest.mark.parametrize("value_class", sorted(INVALID_BUDGETS))
@pytest.mark.asyncio
async def test_EGR_invalid_env_budget_keeps_the_default_and_every_live_gate_active(
    engine: Engine,
    clock: FrozenClock,
    baseline: YamlConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value_class: str,
) -> None:
    """EGR-02: an invalid cap never disables the gate; the default governs every live path."""
    monkeypatch.setenv("VWS_EGRESS_BUDGET_BYTES", INVALID_BUDGETS[value_class])
    proc = write_proc(tmp_path / "proc", 100)
    state = tmp_path / "data" / "egress-counter.json"
    state.parent.mkdir()
    # Built from the environment exactly as vws/runtime_cli.py execute() builds it.
    gauge = EgressWatch(
        state,
        FrozenClock(NOV),
        proc=proc,
        budget=os.environ.get("VWS_EGRESS_BUDGET_BYTES"),
        platform="linux",
    )
    assert gauge.budget == DEFAULT_BUDGET_BYTES == 1_000_000_000
    ledger = Ledger(engine, clock)
    policy = EgressPolicy(build_allowlist(rss_urls=("https://feeds.example.org/rss",)), ledger)
    egress.configure_budget(gauge)
    store = RealtimeStore(ledger, SCOPE, baseline.config_hash)
    schedules = Schedules(
        store.ledger, MacroCalendar(tmp_path / "missing.csv"), tmp_path / "events_policy.yaml"
    )
    desk = RealtimeDesk(store, baseline, CAL, schedules, lambda: True, egress=gauge)
    sent: list[str] = []

    async def notify(message: str) -> None:
        sent.append(message)

    for used, level in (
        (0, EgressLevel.OK),
        (800_000_000, EgressLevel.PAUSED),
        (950_000_000, EgressLevel.BLOCKED),
    ):
        seed(state, used=used, last=100)
        status = gauge.sample()
        assert status.level == level and status.used == used
        assert status.budget == DEFAULT_BUDGET_BYTES
        if level == EgressLevel.OK:
            # A zero or negative value was not applied as a budget (it would block at 0 bytes).
            assert (
                policy.check_url("https://feeds.example.org/rss", purpose="rss")
                == "feeds.example.org"
            )
        else:
            # A too-high value was not applied (it would leave 80% and 95% of the default open).
            with pytest.raises(EgressDeniedError, match="budget"):
                policy.check_url("https://feeds.example.org/rss", purpose="rss")
        assert (
            policy.check_url("https://paper-api.alpaca.markets/v2/orders", purpose="alpaca-order")
            == "paper-api.alpaca.markets"
        )
        if level == EgressLevel.BLOCKED:
            with pytest.raises(ExecutionDisabledError, match="EGR-95"):
                await desk.require_entry(uuid4())
        else:
            with pytest.raises(DataIntegrityError, match="RT-10"):
                await desk.require_entry(uuid4())
        assert desk.hard_exit("NVDA", clock.now()) is None
        assert await gauge.alert(notify) is True
    level_alerts = [message for message in sent if "refused" not in message]
    assert len(level_alerts) == 2
    assert "80% or more" in level_alerts[0] and "95% or more" in level_alerts[1]
    assert "800000000 of 1000000000 bytes" in level_alerts[0]
    assert "950000000 of 1000000000 bytes" in level_alerts[1]
    assert sent[0] == gauge.refusal and sum("refused" in message for message in sent) == 1
