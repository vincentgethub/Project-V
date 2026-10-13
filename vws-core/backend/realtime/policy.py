"""RT-10/11, EVT: pure entry reductions. No execution capability lives here."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.config import EventsPolicy, RealtimeConfig
from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.ops.macro_events import MacroEvent
from backend.ops.trading_controls import ControlScope
from backend.realtime.models import (
    REQUIRED,
    ContextTag,
    Feed,
    FeedHealth,
    HealthStatus,
    RealtimeContext,
    RealtimeEvent,
)

NY = ZoneInfo("America/New_York")
ACTION = {"annotate": Decimal(1), "half_size": Decimal("0.5"), "no_new_entries": Decimal(0)}
EVENT_TAG = {
    "NEWS_NEG": ContextTag.NEWS_NEG,
    "HALT_NEWS": ContextTag.HALT,
    "HALT": ContextTag.HALT,
    "MWC1": ContextTag.MWC1,
    "MWC2": ContextTag.MWC2,
    "MWC3": ContextTag.MWC3,
    "ASSET_INACTIVE": ContextTag.ASSET_INACTIVE,
    "CA_PENDING": ContextTag.CA_PENDING,
    "DELIST": ContextTag.DELIST,
    "DILUTION": ContextTag.DILUTION,
}
MACRO_TAG = {
    "FOMC": (ContextTag.FOMC, "fomc"),
    "CPI": (ContextTag.CPI, "cpi"),
    "NFP": (ContextTag.JOBS, "jobs"),
    "GDP": (ContextTag.GDP, "gdp"),
    "PCE": (ContextTag.PCE, "pce"),
}


def clock_status(skew_ms: Decimal, config: RealtimeConfig) -> HealthStatus:
    checked = RealtimeConfig.model_validate(config)
    if not isinstance(skew_ms, Decimal) or not skew_ms.is_finite():
        raise DataIntegrityError("RT-01: clock skew requires an exact finite value")
    skew = abs(skew_ms)
    return (
        HealthStatus.UNAVAILABLE
        if skew > 2000
        else HealthStatus.DEGRADED
        if skew > checked.clock_skew_ms
        else HealthStatus.OK
    )


def expiry_session(day: date, calendar: MarketCalendar) -> tuple[ContextTag, ...]:
    if type(day) is not date:
        raise DataIntegrityError("RT-09: an explicit session date is required")
    first = day.replace(day=1)
    friday = first + timedelta(days=(4 - first.weekday()) % 7 + 14)
    effective = friday if calendar.is_session(friday) else calendar.previous_sessions(friday, 1)[0]
    if day != effective:
        return ()
    return (
        (ContextTag.OPEX, ContextTag.WITCHING) if day.month in {3, 6, 9, 12} else (ContextTag.OPEX,)
    )


def health_at(row: FeedHealth, now: datetime, config: RealtimeConfig) -> HealthStatus:
    checked, instant, policy = (
        FeedHealth.model_validate(row),
        ensure_utc(now),
        RealtimeConfig.model_validate(config),
    )
    age = instant - checked.observed_at
    if age < timedelta(0):
        raise DataIntegrityError("RT: feed health is in the future")
    ttl: dict[Feed, int] = {
        "clock": 60,
        "halts": policy.halt_poll_sec * 2,
        "news": policy.news_stale_sec,
        "assets": policy.asset_poll_sec,
        "ca": policy.ca_stale_hours * 3600,
        "edgar": 300,
        "fred": 36 * 3600,
        "macro": 90 * 86400,
    }
    return (
        HealthStatus.UNAVAILABLE if age > timedelta(seconds=ttl[checked.feed]) else checked.status
    )


def context(
    scope: ControlScope,
    symbol: str,
    now: datetime,
    policy_hash: str,
    config: RealtimeConfig,
    events_policy: EventsPolicy,
    health: tuple[FeedHealth, ...],
    events: tuple[RealtimeEvent, ...],
    macros: tuple[MacroEvent, ...],
    calendar: MarketCalendar,
    *,
    auto: bool,
    schedules_verified: bool,
) -> RealtimeContext:
    instant = ensure_utc(now)
    policy, table = (
        RealtimeConfig.model_validate(config),
        EventsPolicy.model_validate(events_policy),
    )
    if (
        type(auto) is not bool
        or type(schedules_verified) is not bool
        or max(len(health), len(events), len(macros)) > 10000
    ):
        raise DataIntegrityError("RT/EVT: bounded typed context inputs required")
    rows = tuple(FeedHealth.model_validate(row) for row in health)
    if len({row.feed for row in rows}) != len(rows):
        raise DataIntegrityError("RT: duplicate feed health snapshots")
    by_feed = {row.feed: row for row in rows}
    warnings, tags, actions = [], set(), []
    for name in REQUIRED:
        health_row = by_feed.get(name)
        if (
            health_row is None
            or health_at(health_row, instant, policy) != HealthStatus.OK
            or name == "assets"
            and symbol not in health_row.symbols
        ):
            warnings.append(f"RT-10: {name} is unhealthy, stale or lacks symbol coverage")
    if warnings:
        tags.add(ContextTag.UNAVAILABLE)
        if auto:
            actions.append(Decimal(0))
    clock = by_feed.get("clock")
    if clock is not None and clock.status == HealthStatus.DEGRADED:
        tags.add(ContextTag.CLOCK_SKEW)
    if not schedules_verified:
        warnings.append("EVT-01: confirmed quarterly macro schedule is UNAVAILABLE")
        tags.add(ContextTag.UNAVAILABLE)
        if auto:
            actions.append(Decimal(0))
    day = instant.astimezone(NY).date()
    hard_block = False
    latest_assets: dict[str, RealtimeEvent] = {}
    latest_halts: dict[str, RealtimeEvent] = {}
    mwc_actions = {
        "MWC1": policy.hard_events.mwc1,
        "MWC2": policy.hard_events.mwc2,
        "MWC3": policy.hard_events.mwc3,
    }
    macro_actions = {
        "fomc": table.fomc,
        "cpi": table.cpi,
        "jobs": table.jobs,
        "gdp": table.gdp,
        "pce": table.pce,
    }
    for item in events:
        row = RealtimeEvent.model_validate(item)
        if row.observed_at > instant:
            raise DataIntegrityError("RT: future event cannot affect a decision")
        if row.symbol not in {None, symbol} or row.expires_at <= instant:
            continue
        if row.kind in {"ASSET_INACTIVE", "ASSET_ACTIVE"}:
            previous = latest_assets.get(symbol)
            if previous is None or (row.occurred_at, row.observed_at, row.provider_id) > (
                previous.occurred_at,
                previous.observed_at,
                previous.provider_id,
            ):
                latest_assets[symbol] = row
            continue
        if row.kind in {"HALT", "RESUME"}:
            previous = latest_halts.get(symbol)
            if (
                previous is None
                or row.occurred_at > previous.occurred_at
                or row.occurred_at == previous.occurred_at
                and row.kind == "HALT"
            ):
                latest_halts[symbol] = row
            continue
        tag = EVENT_TAG.get(row.kind)
        if tag is not None:
            tags.add(tag)
        if row.kind in {"MWC1", "MWC2", "MWC3"}:
            if auto:
                actions.append(ACTION[mwc_actions[row.kind]])
        if row.kind == "VIX" and row.value is not None and row.value >= policy.vix_stress:
            tags.add(ContextTag.VIX_STRESS)
            if auto:
                actions.append(ACTION[table.vix_stress])
    for collection, blocked_kind, tag in (
        (latest_assets, "ASSET_INACTIVE", ContextTag.ASSET_INACTIVE),
        (latest_halts, "HALT", ContextTag.HALT),
    ):
        if symbol in collection and collection[symbol].kind == blocked_kind:
            tags.add(tag)
            hard_block = True
    fred = by_feed.get("fred")
    if table.vix_stress != "annotate" and (
        fred is None or health_at(fred, instant, policy) != HealthStatus.OK
    ):
        warnings.append("RT-07: VIX policy requires a verified FRED observation")
        tags.add(ContextTag.UNAVAILABLE)
        if auto:
            actions.append(Decimal(0))
    for macro in macros:
        macro_row = MacroEvent.model_validate(macro)
        if macro_row.date == day:
            tag, action_name = MACRO_TAG[macro_row.event]
            tags.add(tag)
            if auto:
                actions.append(ACTION[macro_actions[action_name]])
    expiration = expiry_session(day, calendar)
    tags.update(expiration)
    if expiration and auto:
        actions.append(ACTION[table.opex])
    if calendar.is_session(day) and calendar.session_close(day).astimezone(NY).time() < time(16):
        tags.add(ContextTag.EARLY_CLOSE)
    multiplier = Decimal(0) if hard_block else min(actions, default=Decimal(1))
    return RealtimeContext(
        scope=scope,
        symbol=symbol,
        as_of=instant,
        policy_sha256=policy_hash,
        tags=tuple(sorted(tags, key=lambda tag: tag.value)),
        entry_multiplier=multiplier,
        warnings=tuple(warnings),
        blocked=multiplier == 0,
    )


def exit_event(event: RealtimeEvent, config: RealtimeConfig, *, held: bool) -> bool:
    row, policy = RealtimeEvent.model_validate(event), RealtimeConfig.model_validate(config)
    if type(held) is not bool:
        raise DataIntegrityError("RT-11: held ownership must be explicit")
    return held and (
        (row.kind == "DELIST" and policy.hard_events.delisting)
        or row.kind == "DILUTION"
        and policy.hard_events.dilution == "exit"
    )
