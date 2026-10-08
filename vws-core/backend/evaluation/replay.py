"""EV-03/PF-03: sealed daily replay with sequential CRO-sized cash accounting.

No provider, broker client, LLM or execution module is imported. Starting cash
and funding are explicit hypothetical assumptions. Pending limits reserve CRO
exposure; sale proceeds enter the entry budget only at T+1. Halts latch and stop
new admissions, while already-modeled exits remain available.
"""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from pathlib import Path
from typing import Any, Self, cast
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from backend.agents.expiry import proposal_expiry
from backend.agents.fundamentals import FrameworkStatus, framework_allows
from backend.agents.indicators import IndicatorMemo
from backend.agents.setup_hunter import SetupHunter
from backend.core.config import Settings, YamlConfig
from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.core.system_state import SystemState, financial_state
from backend.data.frozen_filings import FrozenFilings
from backend.data.history import (
    Digest,
    FrozenHistory,
    HistorySeries,
    KnownSplit,
    canonical_bytes,
    validate_history,
)
from backend.data.market_calendar import MarketCalendar
from backend.data.sec_edgar import SecPayload
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountType,
    Decision,
    DeployableCapital,
    FrozenModel,
    Instrument,
    Intent,
    MarketContext,
    MarketStatus,
    Money,
    OpenOrder,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    SessionDate,
    Side,
    Symbol,
    TradeProposal,
    Verdict,
)
from backend.evaluation.costs import CostContext, FeeBreakdown, FeeSchedule, FillResult, Note
from backend.evaluation.dividends import distribution_rates
from backend.evaluation.edge import EquityPoint
from backend.evaluation.fundamental_timeline import FundamentalTimeline, precompute_fundamentals
from backend.evaluation.outcomes import Outcome, OutcomeSetup, _simulate
from backend.evaluation.weekly import (
    DISCLAIMER,
    SURVIVORSHIP_NOTICE,
    ReportContext,
    WeeklyReport,
    build_weekly_report,
)
from backend.indicators.replay import SymbolGates, precompute_symbol
from backend.risk.risk_cro import STATE_RANK, ChiefRiskOfficer

MAX_REPLAY_DECISIONS = 100000
IDENTITY = UUID("14a44fba-f801-468d-b619-f3cbdc6af2bb")
NOTICE = "Hypothetical starting cash/funding; no deposits, withdrawals, leverage or broker execution. Sale proceeds excluded from entry cash until T+1."


class ReplayRequest(FrozenModel):
    start: SessionDate
    end: SessionDate
    symbols: tuple[Symbol, ...] = Field(min_length=1, max_length=100)
    initial_equity: Money = Field(gt=0, le=Decimal("1e12"))
    funding: DeployableCapital
    synthetic: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def bound(self) -> Self:
        with localcontext() as precision:
            precision.prec = 80
            if (
                self.start >= self.end
                or self.symbols != tuple(sorted(set(self.symbols)))
                or self.initial_equity != self.initial_equity.quantize(CENT)
            ):
                raise ValueError("EV-03: ordered dates/symbols and cent-valued seed required")
        return self


class ReplayDecision(FrozenModel):
    outcome: Outcome
    verdict: Verdict
    entry_canceled_on: SessionDate | None = None

    @model_validator(mode="after")
    def bound(self) -> Self:
        setup = self.outcome.setup
        if (
            setup.alert_id != self.verdict.proposal_id
            or setup.cohort != "REPLAY_IN_SAMPLE"
            or setup.disposition
            != ("APPROVED" if self.verdict.decision == Decision.APPROVED else "CRO_VETO")
        ):
            raise ValueError("EV-03: outcome differs from CRO proposal/cohort")
        if self.entry_canceled_on is not None and (
            self.verdict.decision != Decision.APPROVED
            or self.outcome.status != "NOT_FILLED"
            or self.outcome.reason != "ENTRY_HALTED"
            or not setup.decision_session <= self.entry_canceled_on < setup.valid_until_session
        ):
            raise ValueError("EV-03: cancellation must be an approved, unfilled, still-valid entry")
        return self


class ReplayRun(FrozenModel):
    request: ReplayRequest
    manifest_sha256: Digest
    filings_manifest_sha256: Digest
    config_sha256: Digest
    risk_config_sha256: Digest
    decisions: tuple[ReplayDecision, ...] = Field(max_length=100000)
    portfolio: tuple[EquityPoint, ...] = Field(min_length=2, max_length=20000)
    final_state: SystemState
    unavailable_fundamentals: int = Field(strict=True, ge=0)
    blocked_fundamentals: int = Field(strict=True, ge=0)
    warmup_or_unavailable_gates: int = Field(strict=True, ge=0)
    report: WeeklyReport
    notes: tuple[Note, ...] = (DISCLAIMER, SURVIVORSHIP_NOTICE, NOTICE)

    @model_validator(mode="after")
    def bound(self) -> Self:
        if self.notes != (DISCLAIMER, SURVIVORSHIP_NOTICE, NOTICE) or len(
            {item.outcome.setup.alert_id for item in self.decisions}
        ) != len(self.decisions):
            raise ValueError("EV-03: fixed notices and unique decisions required")
        if (
            any(
                item.outcome.manifest_sha256 != self.manifest_sha256
                or item.verdict.config_hash != self.risk_config_sha256
                for item in self.decisions
            )
            or self.report.context.cohort != "REPLAY_IN_SAMPLE"
            or self.report.manifest_sha256 != self.manifest_sha256
            or self.report.context.config_sha256 != self.config_sha256
            or self.report.context.synthetic != self.request.synthetic
        ):
            raise ValueError("EV-03: replay evidence/configuration binding differs")
        if any(
            a.session >= b.session for a, b in zip(self.portfolio, self.portfolio[1:], strict=False)
        ):
            raise ValueError("EV-03: portfolio marks must increase")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def _worker(
    raw: HistorySeries,
    splits: tuple[KnownSplit, ...],
    config: dict[str, Any],
    manifest: str,
    instrument: Instrument,
    payload: SecPayload | None,
    cache_root: Path | None,
) -> tuple[SymbolGates, FundamentalTimeline]:
    policy = YamlConfig.model_validate(config)
    calendar = MarketCalendar(
        start=raw.sessions[0] - timedelta(days=400), end=raw.sessions[-1] + timedelta(days=400)
    )
    return precompute_symbol(
        raw, splits, policy, manifest, cache_root=cache_root
    ), precompute_fundamentals(instrument, payload, policy.fundamentals, raw.sessions, calendar)


@dataclass
class _Held:
    outcome: Outcome
    qty: int
    entry_value: Decimal


def replay(
    request: ReplayRequest,
    history: FrozenHistory,
    filings: FrozenFilings,
    settings: Settings,
    config: YamlConfig,
    registry: InstrumentRegistry,
    calendar: MarketCalendar,
    schedule: FeeSchedule,
    *,
    workers: int | None = None,
    cache_root: Path | None = None,
) -> ReplayRun:
    """Fixed baseline only. Worker count affects speed, never sorting or decisions."""
    try:
        seed = ReplayRequest.model_validate(request)
        frozen = FrozenHistory.model_validate(history)
        validate_history(frozen.bundle, calendar)
        facts = FrozenFilings.model_validate(filings)
        policy = YamlConfig.model_validate(config)
        limits = Settings.validated_copy(settings)
        policy.assert_settings_consistent(limits)
        policy.assert_allowed_symbols(registry.symbols)
        fee_table = FeeSchedule.model_validate(schedule)
        if not set(seed.symbols).issubset(policy.watchlist):
            raise ValueError("replay symbols are outside the configured watchlist")
        if workers is not None and (type(workers) is not int or not 1 <= workers <= 256):
            raise ValueError("bounded worker count required")
        raw = {symbol: frozen.bundle.for_symbol(symbol, "RAW") for symbol in seed.symbols}
        days = tuple(day for day in raw[seed.symbols[0]].sessions if seed.start <= day <= seed.end)
        if len(days) < 2 or any(
            tuple(day for day in item.sessions if seed.start <= day <= seed.end) != days
            for item in raw.values()
        ):
            raise ValueError("replay needs a common completed multi-session window")
        manifest_hash = frozen.manifest.sha256
        scoped_splits = tuple(
            action for action in frozen.bundle.splits if action.effective_session <= days[-1]
        )
        arguments = tuple(
            (
                HistorySeries(
                    symbol=symbol,
                    adjustment="RAW",
                    bars=tuple(bar for bar in raw[symbol].bars if bar.session_date <= days[-1]),
                ),
                scoped_splits,
                policy.model_dump(mode="json"),
                manifest_hash,
                registry.get(symbol),
                facts.for_symbol(symbol),
                cache_root,
            )
            for symbol in seed.symbols
        )
        count = min(len(arguments), workers or max(1, (os.cpu_count() or 2) - 1))
        if count == 1:
            prepared = tuple(_worker(*args) for args in arguments)
        else:
            with ProcessPoolExecutor(max_workers=count) as pool:
                futures = tuple(pool.submit(_worker, *args) for args in arguments)
                prepared = tuple(future.result() for future in futures)
        # Results were submitted in sorted symbol order. No completion-order merge.
        gates = {item.symbol: {day.session: day for day in item.days} for item, _ in prepared}
        timelines = {item.symbol: table for item, table in prepared}
        if tuple(gates) != seed.symbols or any(
            item.manifest_sha256 != manifest_hash or item.config_sha256 != policy.config_hash
            for item, _ in prepared
        ):
            raise ValueError("precomputed provenance differs")
        prices = {
            symbol: {bar.session_date: bar for bar in item.bars} for symbol, item in raw.items()
        }
        distributions = {
            symbol: distribution_rates(frozen, symbol, days[-1]) for symbol in seed.symbols
        }
        splits = {
            (item.symbol, item.effective_session): item.new_shares_per_old
            for item in frozen.bundle.splits
        }
        cro = ChiefRiskOfficer(limits, registry, calendar)
        hunter = SetupHunter(cro, policy, IndicatorMemo())
        held: dict[UUID, _Held] = {}
        pending: dict[UUID, Outcome] = {}
        settling: dict[date, Decimal] = {}
        cash = seed.initial_equity
        accrued_income = Decimal(0)
        high_water = cash
        state = SystemState.RUNNING
        decisions: list[ReplayDecision] = []
        decision_indices: dict[UUID, int] = {}
        contexts: dict[UUID, CostContext] = {}
        points: list[EquityPoint] = []
        missing = blocked = unavailable = 0

        def valuation(day: date, opening: bool = False) -> Decimal:
            return (
                cash
                + accrued_income
                + sum(settling.values(), Decimal(0))
                + sum(
                    (
                        (
                            prices[item.outcome.setup.symbol][day].open
                            if opening
                            else prices[item.outcome.setup.symbol][day].close
                        )
                        * item.qty
                        for item in held.values()
                    ),
                    Decimal(0),
                )
            )

        def snapshot(day: date, baseline: Decimal) -> PortfolioSnapshot:
            positions: dict[str, Position] = {}
            for symbol in sorted({item.outcome.setup.symbol for item in held.values()}):
                rows = tuple(item for item in held.values() if item.outcome.setup.symbol == symbol)
                qty = sum(item.qty for item in rows)
                average = (sum((item.entry_value for item in rows), Decimal(0)) / qty).quantize(
                    CENT, rounding=ROUND_CEILING
                )
                positions[symbol] = Position(
                    qty=qty, avg_cost=average, last_price=prices[symbol][day].close
                )
            reservations: list[OpenOrder] = []
            for item in pending.values():
                intent = item.setup
                ratio = Decimal(1)
                for (symbol, effective), multiple in splits.items():
                    if symbol == intent.symbol and intent.decision_session < effective <= day:
                        ratio *= multiple
                shares = intent.qty * ratio
                if shares != shares.to_integral_value():
                    raise DataIntegrityError("EV-03: pending split requires fractional shares")
                reservations.append(
                    OpenOrder(
                        symbol=intent.symbol,
                        side=Side.BUY,
                        qty=int(shares),
                        limit_price=intent.limit / ratio,
                        stop_price=intent.stop / ratio,
                    )
                )
            now = calendar.session_close(day) + timedelta(minutes=30)
            return PortfolioSnapshot(
                account_id="replay-hypothetical",
                account_type=AccountType(limits.broker_account_type),
                as_of=now,
                equity=valuation(day),
                cash=cash,
                settled_cash=cash,
                positions=positions,
                open_orders=tuple(reservations),
                high_water_mark=high_water,
                day_start_equity=baseline,
            )

        with localcontext() as precision:
            precision.prec = 80
            for day in days:
                cash += settling.pop(day, Decimal(0))
                for item in held.values():
                    quantity = item.qty * splits.get((item.outcome.setup.symbol, day), Decimal(1))
                    if quantity != quantity.to_integral_value() or not 0 < quantity <= 10**9:
                        raise DataIntegrityError(
                            "EV-03: held split requires fractional/unbounded shares"
                        )
                    item.qty = int(quantity)
                baseline = valuation(day, opening=True)
                for item in held.values():
                    accrued_income += sum(
                        (
                            credit.amount
                            for credit in item.outcome.distributions
                            if credit.session == day
                        ),
                        Decimal(0),
                    )
                for identity, outcome in tuple(pending.items()):
                    if outcome.entry_session == day:
                        incoming = cast(FillResult, outcome.entry_fill)
                        value = cast(Decimal, incoming.price) * incoming.qty
                        debit = value + cast(FeeBreakdown, outcome.entry_fees).total
                        if debit > cash:
                            raise DataIntegrityError("EV-03: entry exceeds settled modeled cash")
                        cash -= debit
                        held[identity] = _Held(outcome, incoming.qty, value)
                        del pending[identity]
                    elif day >= outcome.setup.valid_until_session:
                        del pending[identity]
                for identity, item in tuple(held.items()):
                    if item.outcome.exit_session == day:
                        outgoing = cast(FillResult, item.outcome.exit_fill)
                        if outgoing.qty != item.qty:
                            raise DataIntegrityError("EV-03: exit exceeds modeled held shares")
                        proceeds = (
                            cast(Decimal, outgoing.price) * outgoing.qty
                            - cast(FeeBreakdown, item.outcome.exit_fees).total
                        )
                        settle = calendar.add_sessions(day, 1)
                        settling[settle] = settling.get(settle, Decimal(0)) + proceeds
                        del held[identity]
                equity = valuation(day)
                high_water = max(high_water, equity)
                tier = financial_state(equity, high_water, baseline, limits)
                if STATE_RANK[tier] > STATE_RANK[state]:
                    state = tier
                if equity <= 0:
                    raise DataIntegrityError("EV-03: portfolio equity is nonpositive")
                points.append(EquityPoint(session=day, equity=equity))
                now = calendar.session_close(day) + timedelta(minutes=30)
                for symbol in seed.symbols:
                    frame = gates[symbol][day]
                    if (
                        frame.adv20 is None
                        or frame.atr14 is None
                        or frame.evidence == (None, None, None)
                    ):
                        unavailable += 1
                        continue
                    fundamental = timelines[symbol].at(day)
                    if fundamental.framework_status == FrameworkStatus.INCOMPLETE:
                        missing += 1
                        continue
                    if not framework_allows(fundamental, policy.fundamentals):
                        blocked += 1
                        continue
                    market = MarketContext(
                        last_price=frame.close,
                        last_price_ts=now,
                        adv20_usd=frame.adv20,
                        status=MarketStatus.OK,
                    )
                    result = hunter.size_evidence(
                        symbol, frame.evidence, snapshot(day, baseline), market, now
                    )
                    for candidate in result.candidates:
                        identity = uuid5(
                            IDENTITY,
                            f"{symbol}/{day}/{candidate.playbook.value}/{policy.config_hash}",
                        )
                        expiry = proposal_expiry(now, limits.proposal_ttl_sessions, calendar)
                        proposal = TradeProposal(
                            proposal_id=identity,
                            signal_id=uuid5(IDENTITY, identity.hex),
                            account_id="replay-hypothetical",
                            symbol=symbol,
                            side=Side.BUY,
                            intent=Intent.ENTRY,
                            qty=candidate.qty,
                            limit_price=candidate.entry_price,
                            stop_price=candidate.stop_price,
                            target_price=candidate.target_price,
                            source=ProposalSource.SIGNAL,
                            created_at=now,
                            expires_at=expiry,
                        )
                        current = snapshot(day, baseline)
                        verdict = cro.evaluate(
                            proposal,
                            current,
                            market,
                            state,
                            now,
                            deployable=seed.funding,
                            daily_loss_blocked=baseline - equity
                            >= limits.daily_loss_limit * baseline,
                        )
                        if STATE_RANK[verdict.recommended_state] > STATE_RANK[state]:
                            state = verdict.recommended_state
                        setup = OutcomeSetup(
                            alert_id=identity,
                            symbol=symbol,
                            playbook=candidate.playbook,
                            cohort="REPLAY_IN_SAMPLE",
                            disposition="APPROVED"
                            if verdict.decision == Decision.APPROVED
                            else "CRO_VETO",
                            fundamentals_status=fundamental.framework_status,
                            score=candidate.score,
                            qty=candidate.qty,
                            limit=candidate.entry_price,
                            stop=candidate.stop_price,
                            target=candidate.target_price,
                            decision_session=day,
                            valid_until_session=expiry.astimezone(
                                ZoneInfo("America/New_York")
                            ).date(),
                        )
                        ctx = CostContext(
                            median_dollar_volume_20=frame.median_dollar_volume_20,
                            atr14=frame.atr14,
                            policy=policy.cm,
                        )
                        outcome = _simulate(
                            setup,
                            frozen,
                            ctx,
                            fee_table,
                            policy.evaluation,
                            None,
                            days[-1],
                            distribution_evidence=distributions[symbol],
                        )
                        decision_indices[identity] = len(decisions)
                        decisions.append(ReplayDecision(outcome=outcome, verdict=verdict))
                        contexts[identity] = ctx
                        if len(decisions) > MAX_REPLAY_DECISIONS:
                            raise DataIntegrityError("EV-03: replay decision bound exceeded")
                        if verdict.decision == Decision.APPROVED:
                            pending[identity] = outcome
                if state != SystemState.RUNNING:
                    for identity, outcome in pending.items():
                        index = decision_indices[identity]
                        canceled = _simulate(
                            outcome.setup,
                            frozen,
                            contexts[identity],
                            fee_table,
                            policy.evaluation,
                            None,
                            days[-1],
                            cancel_entry_at=day,
                            distribution_evidence=distributions[outcome.setup.symbol],
                        )
                        decisions[index] = ReplayDecision(
                            outcome=canceled,
                            verdict=decisions[index].verdict,
                            entry_canceled_on=day,
                        )
                    pending.clear()
        report = build_weekly_report(
            ReportContext(
                account_id="replay-hypothetical",
                cohort="REPLAY_IN_SAMPLE",
                start=days[0],
                end=days[-1],
                config_sha256=policy.config_hash,
                initial_equity=seed.initial_equity,
                synthetic=seed.synthetic,
            ),
            tuple(item.outcome for item in decisions),
            frozen,
            calendar,
            fee_table,
            policy.cm,
            limits.tax_profile,
        )
        return ReplayRun(
            request=seed,
            manifest_sha256=manifest_hash,
            filings_manifest_sha256=facts.manifest.sha256,
            config_sha256=policy.config_hash,
            risk_config_sha256=limits.config_hash,
            decisions=tuple(decisions),
            portfolio=tuple(points),
            final_state=state,
            unavailable_fundamentals=missing,
            blocked_fundamentals=blocked,
            warmup_or_unavailable_gates=unavailable,
            report=report,
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("EV-03: replay failed closed; no result inferred") from None
