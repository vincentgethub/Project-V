"""CRO-01..13/R-01..05/R-09/R-13: pure, conservative, exact risk decisions.

The enclosing boundary logs vetoes and persists recommended state escalations.
Pending sells never release inventory/exposure before a fill. Pending same-name
buys reserve risk using protection evidence; an unknown stop reserves the whole
notional. Unconfigured known sectors use 35%; unconfigured themes use zero.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState, financial_state, state_allows
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import GICS_SECTORS, InstrumentRegistry
from backend.domain.models import (
    AssetClass,
    BlackoutWindow,
    CapitalStatus,
    Decision,
    DeployableCapital,
    Intent,
    MarketContext,
    MarketStatus,
    OpenOrder,
    PortfolioSnapshot,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
    Verdict,
    snapshot_hash,
)

ZERO = Decimal("0")
DEFAULT_SECTOR_CAP = Decimal("0.35")
SIZING_RULES = frozenset(f"CRO-{number:02d}" for number in range(2, 9))
EXCHANGE_TIMEZONE = ZoneInfo("America/New_York")
STATE_RANK = {SystemState.RUNNING: 0, SystemState.REDUCE_ONLY: 1, SystemState.HALTED: 2}


def _result(
    rule_id: str,
    passed: bool,
    observed: object,
    limit: object,
    message: str,
    severity: Severity = Severity.BLOCK,
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        passed=passed,
        severity=severity,
        observed=str(observed),
        limit=str(limit),
        message=message,
    )


def _entry(proposal: TradeProposal) -> bool:
    return proposal.intent in {Intent.ENTRY, Intent.ADD}


class ChiefRiskOfficer:
    """CRO-01..13: injected immutable policy and prebuilt calendar; no I/O."""

    def __init__(
        self,
        config: Settings,
        registry: InstrumentRegistry,
        calendar: MarketCalendar,
        *,
        blackout_windows: tuple[BlackoutWindow, ...] = (),
    ) -> None:
        try:
            # Reconstruct policy: model_copy/model_construct bypass validation.
            policy = config.model_dump(mode="python")
            if (
                not config.telegram_allowed_user_ids
                and "telegram_allowed_user_ids" not in config.model_fields_set
            ):
                del policy["telegram_allowed_user_ids"]
            self.config = Settings.model_validate(policy)
            if not isinstance(registry, InstrumentRegistry) or not isinstance(
                calendar, MarketCalendar
            ):
                raise DataIntegrityError("CRO-02: registry and bounded calendar are required")
            self.registry = InstrumentRegistry.validated_copy(registry)
            self.calendar = calendar
            self.blackout_windows = tuple(
                BlackoutWindow.model_validate(window)
                for window in (*self.registry.blackout_windows, *blackout_windows)
            )
            self._config_hash = self.config.config_hash
        except Exception as exc:
            raise ConfigurationError("CRO-01..13: cannot verify immutable risk policy") from exc

    def evaluate(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
        state: SystemState,
        now: datetime,
        *,
        deployable: DeployableCapital | None = None,
    ) -> Verdict:
        """CRO-01..13/R-02/R-03: all evidence; only CRO-01 short-circuits.

        R-09 valid reductions/exits use state and verifiable held inventory only.
        Drawdown tiers travel independently as recommended_state, including on
        exits, without effects or retroactively blocking that exit. Daily loss
        vetoes entries through CRO-10 without latching a system-state tier. Its
        attested baseline is rolled at the next XNYS open outside these rules.
        Unknown
        earnings is a failed WARN and cannot veto an otherwise valid buy.
        """
        try:
            instant = ensure_utc(now)
            proposal = TradeProposal.model_validate(proposal)
            snapshot = PortfolioSnapshot.model_validate(snapshot)
            state_result = _result(
                "CRO-01",
                isinstance(state, SystemState)
                and state_allows(state, proposal.intent, proposal.source),
                state,
                "RUNNING, or permitted reduction/exit",
                "system operating state permits proposal",
            )
            recommended = financial_state(
                snapshot.equity, snapshot.high_water_mark, snapshot.day_start_equity, self.config
            )
            if not state_result.passed:
                return self._verdict(proposal, snapshot, instant, (state_result,), recommended)
            if not _entry(proposal):
                shape = self._shape(proposal, snapshot, None, instant)
                return self._verdict(
                    proposal, snapshot, instant, (state_result, shape), recommended
                )
            if market is None:
                raise DataIntegrityError("CRO-02: entry requires verified market context")
            market = MarketContext.model_validate(market)
            if deployable is not None:
                deployable = DeployableCapital.model_validate(deployable)
            limits = [self.config.__dict__[name] for name in self.config.DECIMAL_BOUNDS]
            limits.extend(self.config.sector_caps.values())
            limits.extend(self.config.theme_caps.values())
            with localcontext() as context:
                context.prec = max(
                    80,
                    len(str(proposal.qty)) + 40,
                    max(len(value.as_tuple().digits) for value in limits) + 40,
                )
                shape = self._shape(proposal, snapshot, market, instant)
                results = self._rules(proposal, snapshot, market, instant, deployable)
            return self._verdict(
                proposal, snapshot, instant, (state_result, shape, *results), recommended
            )
        except Exception as exc:
            try:
                instant = ensure_utc(now)
                if not isinstance(proposal.proposal_id, UUID):
                    raise DataIntegrityError("CRO-02: invalid proposal identity")
                failures = tuple(
                    _result(
                        f"CRO-{number:02d}",
                        False,
                        type(exc).__name__,
                        "verifiable inputs",
                        "input or policy evaluation failed closed",
                    )
                    for number in range(1, 14)
                )
                return Verdict(
                    proposal_id=proposal.proposal_id,
                    decision=Decision.VETOED,
                    results=failures,
                    config_hash=self._config_hash,
                    snapshot_hash="0" * 64,
                    evaluated_at=instant,
                    recommended_state=SystemState.HALTED,
                )
            except Exception as audit_error:
                raise DataIntegrityError(
                    "CRO-02: cannot construct an auditable veto"
                ) from audit_error

    def _verdict(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        now: datetime,
        results: tuple[RuleResult, ...],
        recommended: SystemState,
    ) -> Verdict:
        decision = (
            Decision.VETOED
            if any(not result.passed and result.severity == Severity.BLOCK for result in results)
            else Decision.APPROVED
        )
        return Verdict(
            proposal_id=proposal.proposal_id,
            decision=decision,
            results=results,
            config_hash=self._config_hash,
            snapshot_hash=snapshot_hash(snapshot),
            evaluated_at=now,
            recommended_state=recommended,
        )

    def _shape(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
        now: datetime,
    ) -> RuleResult:
        """CRO-02/R-01/R-09/R-13: account-bound fresh inventory and cent prices."""
        common = (
            proposal.account_id == snapshot.account_id
            and proposal.created_at <= now < proposal.expires_at
            and snapshot.as_of <= now
            and now - snapshot.as_of <= timedelta(seconds=self.config.stale_quote_seconds)
        )
        held = snapshot.positions.get(proposal.symbol)
        if not _entry(proposal):
            reserved = sum(
                order.qty
                for order in snapshot.open_orders
                if order.symbol == proposal.symbol and order.side == Side.SELL
            )
            available = 0 if held is None else max(0, held.qty - reserved)
            return _result(
                "CRO-02",
                common and proposal.qty <= available,
                proposal.qty,
                available,
                "reduction fits fresh held unreserved shares",
            )
        instrument = self.registry.get(proposal.symbol)
        # R-02: even zero holdings and pending sells must be identifiable for a buy.
        for symbol in snapshot.positions:
            self.registry.get(symbol)
        for order in snapshot.open_orders:
            self.registry.get(order.symbol)
        pending_qty = sum(
            order.qty
            for order in snapshot.open_orders
            if order.symbol == proposal.symbol and order.side == Side.BUY
        )
        already_held = (held is not None and held.qty > 0) or pending_qty > 0
        intent_matches = already_held if proposal.intent == Intent.ADD else not already_held
        valid = (
            common
            and intent_matches
            and snapshot.equity > 0
            and instrument.tradable
            and not instrument.is_leveraged
            and not instrument.is_inverse
            and market is not None
            and market.status == MarketStatus.OK
        )
        return _result(
            "CRO-02",
            valid,
            proposal.symbol,
            "valid long-only allowlisted instrument",
            "entry/add intent, stop, expiry, account, inventory and market are verified",
        )

    @staticmethod
    def _pending(snapshot: PortfolioSnapshot) -> dict[str, Decimal]:
        pending: dict[str, Decimal] = {}
        for order in snapshot.open_orders:
            if order.side == Side.BUY:
                pending[order.symbol] = (
                    pending.get(order.symbol, ZERO) + order.qty * order.limit_price
                )
        return pending

    def _risk(self, proposal: TradeProposal, snapshot: PortfolioSnapshot) -> RuleResult:
        """CRO-04: reserve new, existing ADD and same-name pending protection risk."""
        stop = proposal.stop_price
        if stop is None:
            raise DataIntegrityError("CRO-04: buy protection cannot be verified")
        risk = proposal.qty * (proposal.limit_price - stop)
        risk += proposal.qty * proposal.limit_price * self.config.stop_slippage_buffer
        position = snapshot.positions.get(proposal.symbol)
        if proposal.intent == Intent.ADD and position is not None:
            risk += position.qty * max(ZERO, position.last_price - stop)
            risk += position.value * self.config.stop_slippage_buffer
        for order in snapshot.open_orders:
            if order.symbol == proposal.symbol and order.side == Side.BUY:
                loss = (
                    order.limit_price
                    if order.stop_price is None
                    else max(ZERO, order.limit_price - min(stop, order.stop_price))
                )
                risk += (
                    order.qty * loss
                    + order.qty * order.limit_price * self.config.stop_slippage_buffer
                )
        limit = self.config.max_risk_per_trade * max(ZERO, snapshot.equity)
        return _result(
            "CRO-04", risk <= limit, risk, limit, "reserved stop risk plus slippage fits budget"
        )

    def _rules(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext,
        now: datetime,
        deployable: DeployableCapital | None,
    ) -> tuple[RuleResult, ...]:
        instrument = self.registry.get(proposal.symbol)
        pending = self._pending(snapshot)
        notional = proposal.qty * proposal.limit_price
        equity = max(ZERO, snapshot.equity)
        exposures = {
            symbol: position.value
            for symbol, position in snapshot.positions.items()
            if position.qty > 0
        }
        for symbol, value in pending.items():
            exposures[symbol] = exposures.get(symbol, ZERO) + value
        exposures[proposal.symbol] = exposures.get(proposal.symbol, ZERO) + notional
        cap = (
            self.config.max_single_stock_weight
            if instrument.asset_class == AssetClass.STOCK
            else self.config.max_single_etf_weight
        )
        name = _result(
            "CRO-03",
            exposures[proposal.symbol] <= cap * equity,
            exposures[proposal.symbol],
            cap * equity,
            "post-trade single-name value fits cap",
        )
        risk = self._risk(proposal, snapshot)
        allocation = self._allocation(exposures, equity)
        gross = sum(exposures.values(), ZERO)
        cash_after = snapshot.cash - sum(pending.values(), ZERO) - notional
        exposure = _result(
            "CRO-06",
            gross <= self.config.max_gross_exposure * equity
            and len(exposures) <= self.config.max_open_positions
            and cash_after >= self.config.min_cash_pct * equity,
            f"gross={gross}; positions={len(exposures)}; cash={cash_after}",
            f"gross<={self.config.max_gross_exposure * equity}; positions<={self.config.max_open_positions}; cash>={self.config.min_cash_pct * equity}",
            "gross exposure, number of names, and cash buffer all fit",
        )
        price = self._price(proposal, market, now)
        liquidity = _result(
            "CRO-08",
            notional <= self.config.max_pct_of_adv * market.adv20_usd,
            notional,
            self.config.max_pct_of_adv * market.adv20_usd,
            "notional fits average-volume cap",
        )
        baseline = snapshot.high_water_mark
        drawdown = ZERO if baseline <= 0 else max(ZERO, (baseline - equity) / baseline)
        drawdown_result = _result(
            "CRO-09",
            equity > 0
            and baseline > 0
            and max(ZERO, baseline - equity) < self.config.dd_reduce_only * baseline,
            drawdown,
            self.config.dd_reduce_only,
            "persisted drawdown below reduce-only tier",
        )
        day_start = snapshot.day_start_equity
        daily_loss = ZERO if day_start <= 0 else (day_start - equity) / day_start
        daily = _result(
            "CRO-10",
            equity > 0
            and day_start > 0
            and day_start - equity < self.config.daily_loss_limit * day_start,
            daily_loss,
            self.config.daily_loss_limit,
            "loss below session entry limit; baseline rolls at next XNYS open",
        )
        blocked = any(
            window.start <= now <= window.end and window.symbol in {None, proposal.symbol}
            for window in self.blackout_windows
        )
        blackout = _result(
            "CRO-11",
            not blocked,
            "in blackout" if blocked else "clear",
            "outside all applicable UTC blackouts",
            "scheduled blackout includes both endpoint instants",
        )
        funding = _result(
            "CRO-12",
            deployable is not None and deployable.status == CapitalStatus.OK,
            "missing" if deployable is None else deployable.status,
            CapitalStatus.OK,
            "checking buffer and funding reading must be available",
        )
        earnings = self._earnings(market, now)
        return (
            name,
            risk,
            allocation,
            exposure,
            price,
            liquidity,
            drawdown_result,
            daily,
            blackout,
            funding,
            earnings,
        )

    def _allocation(self, exposures: dict[str, Decimal], equity: Decimal) -> RuleResult:
        """CRO-05: all holdings/pending buys participate in ETF look-through."""
        sectors: dict[str, Decimal] = {}
        themes: dict[str, Decimal] = {}
        known = True
        for symbol, value in exposures.items():
            instrument = self.registry.get(symbol)
            for sector, weight in self.registry.sector_weights(symbol).items():
                known = known and sector in GICS_SECTORS
                sectors[sector] = sectors.get(sector, ZERO) + value * weight
            for theme in instrument.themes:
                themes[theme] = themes.get(theme, ZERO) + value
        within_sectors = all(
            value <= self.config.sector_caps.get(sector, DEFAULT_SECTOR_CAP) * equity
            for sector, value in sectors.items()
        )
        within_themes = all(
            value <= self.config.theme_caps.get(theme, ZERO) * equity
            for theme, value in themes.items()
        )
        return _result(
            "CRO-05",
            known and within_sectors and within_themes,
            f"sectors={sorted(sectors.items())}; themes={sorted(themes.items())}",
            "configured sector/theme fractions",
            "sector look-through and theme caps fit",
        )

    def _price(self, proposal: TradeProposal, market: MarketContext, now: datetime) -> RuleResult:
        """CRO-07/DAT-01: regular-hour age; otherwise age from last close."""
        reference = (
            now
            if self.calendar.is_open(now)
            else self.calendar.session_close(self.calendar.last_completed_session(now))
        )
        age = max(timedelta(0), reference - market.last_price_ts)
        collar = (
            abs(proposal.limit_price - market.last_price)
            <= self.config.price_collar * market.last_price
        )
        valid = (
            market.last_price_ts <= now
            and age <= timedelta(seconds=self.config.stale_quote_seconds)
            and collar
            and proposal.limit_price >= self.config.min_price
        )
        return _result(
            "CRO-07",
            valid,
            f"price={proposal.limit_price}; reference={market.last_price}; age={age}",
            f"collar={self.config.price_collar}; min={self.config.min_price}; age<={self.config.stale_quote_seconds}s",
            "limit price and calendar-aware quote freshness are sane",
        )

    def _earnings(self, market: MarketContext, now: datetime) -> RuleResult:
        """CRO-13: inclusive XNYS proximity; unknown warns, never counts as neutral."""
        earnings = market.next_earnings_date
        if earnings is None:
            return _result(
                "CRO-13",
                False,
                "unknown",
                "verified earnings date",
                "earnings unavailable; operator must review unknown event risk",
                Severity.WARN,
            )
        today = now.astimezone(EXCHANGE_TIMEZONE).date()
        self.calendar.is_session(today)  # Enforce bounds even for a past event.
        on_session = self.calendar.is_session(earnings)
        if earnings <= today:
            blocked = True
        else:
            count = self.config.earnings_blackout_sessions + (0 if on_session else 1)
            earliest = (
                earnings if count == 0 else self.calendar.previous_sessions(earnings, count)[0]
            )
            blocked = today >= earliest
        return _result(
            "CRO-13",
            not blocked,
            earnings.isoformat(),
            f"outside {self.config.earnings_blackout_sessions} XNYS sessions",
            "known earnings within inclusive blackout or unresolved past date blocks",
        )

    def max_allowed_qty(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext,
        now: datetime,
    ) -> int:
        """CRO-03..08/R-04: largest eligible whole quantity, capped at requested qty.

        Advisory reduction only. Complete unique CRO-02..08 evidence is required,
        so an empty/failed evaluation cannot look eligible. Sizing is monotone.
        """
        try:
            proposal = TradeProposal.model_validate(proposal)
            snapshot = PortfolioSnapshot.model_validate(snapshot)
            market = MarketContext.model_validate(market)
            instant = ensure_utc(now)
            if not _entry(proposal):
                return 0
            with localcontext() as context:
                context.prec = 80
                upper = max(
                    0,
                    min(
                        proposal.qty,
                        int(min(snapshot.cash, snapshot.equity) / proposal.limit_price),
                    ),
                )
            lower = 0
            while lower < upper:
                midpoint = (lower + upper + 1) // 2
                candidate = proposal.model_copy(update={"qty": midpoint})
                verdict = self.evaluate(candidate, snapshot, market, SystemState.RUNNING, instant)
                evidence = tuple(
                    result for result in verdict.results if result.rule_id in SIZING_RULES
                )
                eligible = (
                    len(evidence) == len(SIZING_RULES)
                    and {result.rule_id for result in evidence} == SIZING_RULES
                    and all(
                        result.passed and result.severity == Severity.BLOCK for result in evidence
                    )
                )
                if eligible:
                    lower = midpoint
                else:
                    upper = midpoint - 1
            return lower
        except Exception as exc:
            raise DataIntegrityError("CRO-03..08: deterministic sizing failed closed") from exc

    def evaluate_batch(
        self,
        proposals: Iterable[TradeProposal],
        snapshot: PortfolioSnapshot,
        markets: dict[str, MarketContext],
        state: SystemState,
        now: datetime,
        *,
        deployable: DeployableCapital | None = None,
    ) -> tuple[Verdict, ...]:
        """CRO-03/CRO-04/CRO-06/R-09: sequential notional, protection/inventory reservations."""
        current = snapshot
        current_state = state
        verdicts: list[Verdict] = []
        try:
            for proposal in proposals:
                market = markets.get(proposal.symbol) if _entry(proposal) else None
                verdict = self.evaluate(
                    proposal, current, market, current_state, now, deployable=deployable
                )
                verdicts.append(verdict)
                if (
                    isinstance(current_state, SystemState)
                    and STATE_RANK[verdict.recommended_state] > STATE_RANK[current_state]
                ):
                    current_state = verdict.recommended_state
                if verdict.decision == Decision.APPROVED:
                    pending = OpenOrder(
                        symbol=proposal.symbol,
                        side=proposal.side,
                        qty=proposal.qty,
                        limit_price=proposal.limit_price,
                        stop_price=proposal.stop_price,
                    )
                    current = current.model_copy(
                        update={"open_orders": (*current.open_orders, pending)}
                    )
            return tuple(verdicts)
        except Exception as exc:
            raise DataIntegrityError("CRO-03/CRO-06: batch inputs cannot be verified") from exc
