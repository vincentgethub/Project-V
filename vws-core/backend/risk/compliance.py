"""R-02/R-03/R-04/R-05/R-09, CMP-01..07: pure pre-trade compliance.

These flags and Form 8949 rows aid reconciliation; the broker's 1099-B remains
the filing record. Account taxonomy, complete trade history and current lots
are injected by the caller. Unknown account ownership/tax status fails closed.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.money import decimal_money
from backend.core.system_state import SystemState
from backend.data.market_calendar import MarketCalendar
from backend.domain.compliance_models import (
    ExternalAccount as ExternalAccount,
)
from backend.domain.compliance_models import (
    Form8949Row as Form8949Row,
)
from backend.domain.compliance_models import (
    TaxLot as TaxLot,
)
from backend.domain.compliance_models import (
    TaxStatus as TaxStatus,
)
from backend.domain.compliance_models import (
    TradeRecord as TradeRecord,
)
from backend.domain.compliance_models import (
    WashAdjustment as WashAdjustment,
)
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    DayTradeRegime,
    FrozenModel,
    Intent,
    PortfolioSnapshot,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
    UTCDateTime,
    _canonical,
    snapshot_hash,
)
from backend.tax.lots import WashSaleMatcher

_NEW_YORK = ZoneInfo("America/New_York")


class ComplianceAssessment(FrozenModel):
    """CMP-01..07/R-02/R-03: immutable evidence and an effect-free halt request."""

    proposal_id: UUID | None
    results: tuple[RuleResult, ...]
    config_hash: str
    snapshot_hash: str
    input_hash: str
    evaluated_at: UTCDateTime
    recommended_state: SystemState


def _day(value: datetime) -> date:
    """R-05/CMP-03/CMP-05: exchange dates use New York even near UTC midnight."""
    return ensure_utc(value).astimezone(_NEW_YORK).date()


def day_trade_activity(
    calendar: MarketCalendar,
    account_id: str,
    symbol: str,
    side: Side,
    history: tuple[TradeRecord, ...],
    now: datetime,
) -> tuple[bool, int]:
    """CMP-05/AX-25: one pure, conservative count shared by both entry gates."""
    today = _day(now)
    window = frozenset(
        (*calendar.previous_sessions(today, 4), today)
        if calendar.is_session(today)
        else calendar.previous_sessions(today, 5)
    )
    pending: dict[tuple[date, str], deque[tuple[UUID, int]]] = {}
    completed_ids: set[UUID] = set()
    same_day = False
    # BUY-before-SELL at an equal timestamp maximizes the conservative count.
    for trade in sorted(history, key=lambda row: (row.ts, row.side != Side.BUY, str(row.trade_id))):
        if trade.account_id != account_id:
            continue
        trade_day = _day(trade.ts)
        if trade_day == today and trade.symbol == symbol and trade.side != side:
            same_day = True
        if trade_day not in window:
            continue
        queue = pending.setdefault((trade_day, trade.symbol), deque())
        if trade.side == Side.BUY:
            queue.append((trade.trade_id, trade.qty))
        else:
            remaining = trade.qty
            available_orders = list(queue)
            queue.clear()
            for index, (buy_id, available) in enumerate(available_orders):
                if remaining == 0:
                    break
                if buy_id not in completed_ids:
                    available_orders[index] = (buy_id, available - 1)
                    completed_ids.add(buy_id)
                    remaining -= 1
            for buy_id, available in available_orders:
                matched = min(remaining, available)
                remaining -= matched
                if matched < available:
                    queue.append((buy_id, available - matched))
    return same_day, len(completed_ids)


def _compliance_canonical(value: object) -> object:
    """R-03/R-04/R-05: exact B-stage JSON normalization with tax date support."""
    if isinstance(value, FrozenModel):
        return _compliance_canonical(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _compliance_canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_compliance_canonical(item) for item in value]
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return _canonical(value)


def _result(
    rule: str, passed: bool, severity: Severity, observed: object, limit: object, message: str
) -> RuleResult:
    return RuleResult(
        rule_id=rule,
        passed=passed,
        severity=severity,
        observed=str(observed),
        limit=str(limit),
        message=message,
    )


class ComplianceEngine:
    """CMP-01..07/R-03/R-09: evaluate all rules without changing any position.

    FIFO chooses proposed sale lots. Identical groups are operator-supplied,
    not inferred from overlapping holdings. An exit gets warnings for every
    compliance failure, including provider faults. The orchestration layer
    must persist a HALT on failed CMP-06 before running the state gate.
    """

    def __init__(
        self,
        config: Settings,
        registry: InstrumentRegistry,
        calendar: MarketCalendar,
        *,
        restricted_symbols: frozenset[str] = frozenset(),
    ) -> None:
        try:
            policy = config.model_dump(mode="python")
            if (
                not config.telegram_allowed_user_ids
                and "telegram_allowed_user_ids" not in config.model_fields_set
            ):
                del policy["telegram_allowed_user_ids"]
            self.config = Settings.model_validate(policy)
            if not isinstance(calendar, MarketCalendar):
                raise DataIntegrityError("CMP-03: bounded exchange calendar is required")
            self.registry = InstrumentRegistry.validated_copy(registry)
            self.calendar = calendar
            self.restricted_symbols = frozenset(restricted_symbols)
            for symbol in self.restricted_symbols:
                self.registry.get(symbol)
            self._config_hash = self.config.config_hash
        except Exception as exc:
            raise ConfigurationError(
                "CMP-01..07: cannot verify immutable compliance policy"
            ) from exc

    def settlement_date(self, ts: datetime) -> date:
        """CMP-03: T+1 uses the actual exchange trade date, not the UTC date."""
        # VERIFY: https://www.sec.gov/resources-for-investors/investor-alerts-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor-bulletin
        try:
            return self.calendar.add_sessions(_day(ts), 1)
        except Exception as exc:
            raise DataIntegrityError("CMP-03: cannot verify T+1 settlement date") from exc

    def input_hash(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
        flags: AccountFlags | None,
    ) -> str:
        """R-02/R-03: bind full evidence and detached tax/restriction policy.

        Tuple ordering is retained as part of the supplied evidence. Decimal
        trailing zeros are normalized; all timestamps are normalized to UTC.
        The settings-only config_hash remains the master contract's hash.
        """
        try:
            if not all(isinstance(rows, tuple) for rows in (lots, history, accounts)):
                raise DataIntegrityError("CMP-01..07: evidence must be immutable tuples")
            payload = {
                "proposal": TradeProposal.model_validate(proposal),
                "snapshot": PortfolioSnapshot.model_validate(snapshot),
                "lots": tuple(TaxLot.model_validate(row) for row in lots),
                "history": tuple(TradeRecord.model_validate(row) for row in history),
                "accounts": tuple(ExternalAccount.model_validate(row) for row in accounts),
                "flags": AccountFlags.model_validate(flags) if flags is not None else None,
                "restricted_symbols": sorted(self.restricted_symbols),
                "instruments": tuple(
                    self.registry.get(symbol) for symbol in sorted(self.registry.symbols)
                ),
                "identical_groups": {
                    symbol: sorted(self.registry.identical_group(symbol))
                    for symbol in sorted(self.registry.symbols)
                },
            }
            encoded = json.dumps(
                _compliance_canonical(payload),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        except Exception as exc:
            raise DataIntegrityError(
                "CMP-01..07: cannot hash verified compliance evidence"
            ) from exc

    def settled_cash_as_of(
        self,
        initial_cash: Decimal,
        history: tuple[TradeRecord, ...],
        now: datetime,
        *,
        account_id: str,
    ) -> Decimal:
        """CMP-03: exact reconstructed cash with conservative T+1 credit timing.

        BUY costs debit immediately. Without an attested settlement timestamp,
        SELL proceeds credit only at the T+1 session close. A broker-reconciled
        settled_cash snapshot can provide confirmed funds sooner that day.
        """
        try:
            instant = ensure_utc(now)
            if not isinstance(initial_cash, Decimal) or not account_id.strip():
                raise DataIntegrityError("CMP-03: Decimal baseline and account are required")
            cash = decimal_money(initial_cash)
            rows = tuple(TradeRecord.model_validate(row) for row in history)
            if len({row.trade_id for row in rows}) != len(rows):
                raise DataIntegrityError("CMP-03: duplicate trade identifier")
            with localcontext() as context:
                context.prec = 80
                for trade in sorted(rows, key=lambda row: (row.ts, str(row.trade_id))):
                    self.registry.get(trade.symbol)
                    if trade.ts > instant:
                        raise DataIntegrityError("CMP-03: future executed trade")
                    if trade.account_id != account_id:
                        continue
                    notional = trade.qty * trade.price
                    if trade.side == Side.BUY:
                        cash -= notional
                    elif self.calendar.session_close(self.settlement_date(trade.ts)) <= instant:
                        cash += notional
            return decimal_money(cash)
        except Exception as exc:
            raise DataIntegrityError("CMP-03: cannot reconstruct verified settled cash") from exc

    def wash_adjustments(
        self,
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
    ) -> tuple[WashAdjustment, ...]:
        """CMP-01/CMP-02: 61-day matching, proportional loss, basis and tacking.

        Each replacement share has one shared capacity across all loss sales.
        Match loss sales chronologically, then replacement purchases in their
        acquisition order; both day-30 endpoints are included. IRA/Roth
        replacements permanently disallow the taxable loss with no IRA basis
        increase. Zero-rounded micro-unit estimates raise rather than disappear.
        """
        # VERIFY: https://www.irs.gov/publications/p550
        # VERIFY: https://www.irs.gov/pub/irs-drop/rr-08-05.pdf
        return WashSaleMatcher(self.registry).adjustments(history, external_accounts)

    @staticmethod
    def form_8949_rows(adjustments: tuple[WashAdjustment, ...]) -> tuple[Form8949Row, ...]:
        """CMP-02: one code-W reconciliation row per disjoint matched sale slice."""
        # VERIFY: https://www.irs.gov/instructions/i8949
        return WashSaleMatcher.form_8949_rows(adjustments)

    @staticmethod
    def _accounts(rows: tuple[ExternalAccount, ...]) -> dict[str, TaxStatus]:
        accounts = {row.account_id: row.tax_status for row in rows}
        if len(accounts) != len(rows):
            raise DataIntegrityError("Tax account identifiers must be unique")
        return accounts

    def check(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
        now: datetime,
        *,
        flags: AccountFlags | None = None,
    ) -> list[RuleResult]:
        """CMP-01..07: mandated evidence API; effects remain in the boundary."""
        return list(
            self.assess(
                proposal, snapshot, lots, history, external_accounts, now, flags=flags
            ).results
        )

    def assess(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
        now: datetime,
        *,
        flags: AccountFlags | None = None,
    ) -> ComplianceAssessment:
        """CMP-01..07/R-02/R-09: all evidence plus explicit fault provenance.

        Ordinary rule failures retain RUNNING; unverifiable input, a provider
        fault or failed current broker flags recommends a durable HALT. Only
        independently verifiable exits receive warnings for those failures.
        """
        try:
            instant = ensure_utc(now)
        except Exception as exc:
            raise DataIntegrityError("R-05/CMP-01..07: evaluation time is unverifiable") from exc
        severity = (
            Severity.WARN if self._verified_exit(proposal, snapshot, instant) else Severity.BLOCK
        )
        identity = (
            proposal.__dict__.get("proposal_id") if isinstance(proposal, TradeProposal) else None
        )
        proposal_id = identity if isinstance(identity, UUID) else None
        digest = "0" * 64
        input_digest = "0" * 64
        try:
            snapshot = PortfolioSnapshot.model_validate(snapshot)
            digest = snapshot_hash(snapshot)
            proposal = TradeProposal.model_validate(proposal)
            proposal_id = proposal.proposal_id
            if not all(isinstance(rows, tuple) for rows in (lots, history, external_accounts)):
                raise DataIntegrityError("CMP-01..07: evidence must be immutable tuples")
            lots = tuple(TaxLot.model_validate(row) for row in lots)
            history = tuple(TradeRecord.model_validate(row) for row in history)
            external_accounts = tuple(
                ExternalAccount.model_validate(row) for row in external_accounts
            )
            input_digest = self.input_hash(
                proposal, snapshot, lots, history, external_accounts, flags
            )
            self._validate_inputs(proposal, snapshot, lots, history, external_accounts, instant)
        except Exception as exc:
            failures = tuple(
                _result(
                    f"CMP-{number:02d}",
                    False,
                    severity,
                    type(exc).__name__,
                    "verified state",
                    "Unverifiable compliance input; HALTED required",
                )
                for number in range(1, 8)
            )
            return ComplianceAssessment(
                proposal_id=proposal_id,
                results=failures,
                config_hash=self._config_hash,
                snapshot_hash=digest,
                input_hash=input_digest,
                evaluated_at=instant,
                recommended_state=SystemState.HALTED,
            )
        operations: tuple[tuple[str, Callable[[], RuleResult]], ...] = (
            (
                "CMP-01",
                lambda: self._forward(proposal, history, external_accounts, instant, severity),
            ),
            (
                "CMP-02",
                lambda: self._backward(
                    proposal, snapshot, lots, history, external_accounts, instant
                ),
            ),
            ("CMP-03", lambda: self._settlement(proposal, snapshot, lots, instant, severity)),
            ("CMP-04", lambda: self._borrowing(proposal, snapshot, severity)),
            ("CMP-05", lambda: self._day_trade(proposal, snapshot, history, instant, severity)),
            ("CMP-06", lambda: self._broker(flags, severity)),
            ("CMP-07", lambda: self._restricted(proposal, severity)),
        )
        results: list[RuleResult] = []
        recommended = SystemState.RUNNING
        for rule, operation in operations:
            try:
                with localcontext() as context:
                    context.prec = 80
                    results.append(operation())
            except Exception as exc:
                recommended = SystemState.HALTED
                results.append(
                    _result(
                        rule,
                        False,
                        severity,
                        type(exc).__name__,
                        "verified state",
                        "Unverifiable compliance rule; HALTED required",
                    )
                )
        if not results[5].passed:
            recommended = SystemState.HALTED
        return ComplianceAssessment(
            proposal_id=proposal_id,
            results=tuple(results),
            config_hash=self._config_hash,
            snapshot_hash=digest,
            input_hash=input_digest,
            evaluated_at=instant,
            recommended_state=recommended,
        )

    def _validate_common(
        self, proposal: TradeProposal, snapshot: PortfolioSnapshot, instant: datetime
    ) -> None:
        """R-02/R-05/R-09: bind a live proposal to fresh account inventory."""
        if (
            proposal.account_id != snapshot.account_id
            or not proposal.created_at <= instant < proposal.expires_at
            or snapshot.as_of > instant
            or instant - snapshot.as_of > timedelta(seconds=self.config.stale_quote_seconds)
        ):
            raise DataIntegrityError("Account binding, expiry or portfolio freshness is invalid")
        if proposal.side == Side.SELL:
            held = snapshot.positions.get(proposal.symbol)
            pending = snapshot.reserved_sell_shares(proposal.symbol)
            if held is None or proposal.qty > held.qty - pending:
                raise DataIntegrityError("R-09: sell quantity exceeds unreserved held shares")

    def _verified_exit(
        self, proposal: TradeProposal, snapshot: PortfolioSnapshot, instant: datetime
    ) -> bool:
        """R-09: warning-only compliance is available to verifiable held exits."""
        try:
            checked = TradeProposal.model_validate(proposal)
            state = PortfolioSnapshot.model_validate(snapshot)
            self._validate_common(checked, state, instant)
            return checked.intent in (Intent.REDUCE, Intent.EXIT)
        except Exception:
            return False

    def _validate_inputs(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
        now: datetime,
    ) -> None:
        instant = ensure_utc(now)
        self._validate_common(proposal, snapshot, instant)
        if snapshot.equity <= 0:
            raise DataIntegrityError("R-02/CMP-04: account equity requires HALTED")
        known = self._accounts(accounts)
        if proposal.account_id not in known:
            raise DataIntegrityError("Managed account tax status is unknown")
        if len({row.trade_id for row in history}) != len(history) or len(
            {row.lot_id for row in lots}
        ) != len(lots):
            raise DataIntegrityError("Trade or lot identifiers must be unique")
        if proposal.proposal_id in {row.trade_id for row in history}:
            raise DataIntegrityError("Proposal already exists in executed history")
        for trade in history:
            if trade.ts > instant or trade.account_id not in known:
                raise DataIntegrityError("Trade history is future or account ownership is unknown")
            self.registry.get(trade.symbol)
        executed = {row.trade_id: row for row in history}
        lot_inventory: dict[UUID, int] = {}
        for lot in lots:
            if lot.acquired_at > instant or lot.account_id not in known:
                raise DataIntegrityError("Tax lot is future or account ownership is unknown")
            self.registry.get(lot.symbol)
            if lot.acquisition_trade_id is not None:
                original = executed.get(lot.acquisition_trade_id)
                lot_inventory[lot.acquisition_trade_id] = (
                    lot_inventory.get(lot.acquisition_trade_id, 0) + lot.qty
                )
                if (
                    original is None
                    or original.side != Side.BUY
                    or original.account_id != lot.account_id
                    or original.symbol != lot.symbol
                    or original.ts != lot.acquired_at
                    or lot_inventory[lot.acquisition_trade_id] > original.qty
                ):
                    raise DataIntegrityError(
                        "CMP-02: tax lot acquisition lineage does not reconcile"
                    )

    def _forward(
        self,
        proposal: TradeProposal,
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
        now: datetime,
        severity: Severity,
    ) -> RuleResult:
        if proposal.side != Side.BUY:
            return _result(
                "CMP-01",
                True,
                Severity.WARN,
                "exit",
                "buy only",
                "Forward wash-sale rule is not applicable",
            )
        candidate = TradeRecord(
            trade_id=proposal.proposal_id,
            account_id=proposal.account_id,
            symbol=proposal.symbol,
            side=Side.BUY,
            qty=proposal.qty,
            price=proposal.limit_price,
            ts=ensure_utc(now),
        )
        matches = tuple(
            row
            for row in self.wash_adjustments((*history, candidate), accounts)
            if row.replacement_trade_id == proposal.proposal_id
        )
        loss = sum((row.disallowed_loss for row in matches), Decimal(0))
        blocked = loss > 0
        policy = Severity(self.config.wash_sale_mode) if blocked else severity
        permanent = any(row.permanent_loss for row in matches)
        return _result(
            "CMP-01",
            not blocked,
            policy,
            loss,
            0,
            "IRA/Roth replacement creates permanent loss"
            if permanent
            else "Forward wash-sale matched loss shares"
            if blocked
            else "No forward wash-sale replacement",
        )

    def _sale_lots(
        self, proposal: TradeProposal, snapshot: PortfolioSnapshot, lots: tuple[TaxLot, ...]
    ) -> tuple[tuple[TaxLot, int], ...]:
        selected = sorted(
            (
                lot
                for lot in lots
                if lot.account_id == proposal.account_id and lot.symbol == proposal.symbol
            ),
            key=lambda lot: (lot.acquired_at, str(lot.lot_id)),
        )
        held = snapshot.positions.get(proposal.symbol)
        if held is None or proposal.qty > held.qty or sum(lot.qty for lot in selected) != held.qty:
            raise DataIntegrityError("Sale lots do not reconcile to held whole shares")
        remaining = proposal.qty
        output: list[tuple[TaxLot, int]] = []
        for lot in selected:
            if remaining == 0:
                break
            shares = min(remaining, lot.qty)
            output.append((lot, shares))
            remaining -= shares
        return tuple(output)

    def _backward(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
        now: datetime,
    ) -> RuleResult:
        if proposal.side != Side.SELL:
            return _result(
                "CMP-02",
                True,
                Severity.WARN,
                "buy",
                "loss sale only",
                "Backward wash-sale rule is not applicable",
            )
        candidates = tuple(
            TradeRecord(
                trade_id=uuid5(proposal.proposal_id, str(lot.lot_id)),
                account_id=proposal.account_id,
                symbol=proposal.symbol,
                side=Side.SELL,
                qty=shares,
                price=proposal.limit_price,
                ts=ensure_utc(now),
                realized_loss=max(Decimal(0), (lot.cost_basis - proposal.limit_price) * shares),
                holding_period_start=lot.holding_period_start or lot.acquired_at,
                acquisition_trade_id=lot.acquisition_trade_id,
            )
            for lot, shares in self._sale_lots(proposal, snapshot, lots)
        )
        ids = {row.trade_id for row in candidates}
        matches = tuple(
            row
            for row in self.wash_adjustments((*history, *candidates), accounts)
            if row.loss_trade_id in ids
        )
        loss = sum((row.disallowed_loss for row in matches), Decimal(0))
        permanent = any(row.permanent_loss for row in matches)
        return _result(
            "CMP-02",
            loss == 0,
            Severity.WARN,
            loss,
            0,
            "Backward wash-sale estimated disallowed loss; permanent IRA/Roth loss"
            if permanent
            else "Backward wash-sale estimated disallowed loss"
            if loss
            else "No backward wash-sale loss",
        )

    @staticmethod
    def _pending(snapshot: PortfolioSnapshot) -> Decimal:
        return sum(
            (
                order.qty * order.limit_price
                for order in snapshot.open_orders
                if order.side == Side.BUY
            ),
            Decimal(0),
        )

    def _settlement(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        now: datetime,
        severity: Severity,
    ) -> RuleResult:
        if snapshot.account_type != AccountType.CASH:
            return _result(
                "CMP-03",
                True,
                severity,
                "margin",
                "cash accounts",
                "Cash settlement rule is not applicable",
            )
        if proposal.side == Side.BUY:
            required = proposal.qty * proposal.limit_price + self._pending(snapshot)
            return _result(
                "CMP-03",
                required <= snapshot.settled_cash,
                severity,
                required,
                snapshot.settled_cash,
                "BUY plus pending buys requires confirmed settled cash",
            )
        unsafe = 0
        for lot, shares in self._sale_lots(proposal, snapshot, lots):
            funding_date = lot.funding_settlement_date
            if funding_date is None or now < self.calendar.session_close(funding_date):
                unsafe += shares
        return _result(
            "CMP-03",
            unsafe == 0,
            Severity.WARN,
            unsafe,
            0,
            "Sale funding is unknown or may create a good-faith/freeriding violation"
            if unsafe
            else "Sale funding is settled",
        )

    def _borrowing(
        self, proposal: TradeProposal, snapshot: PortfolioSnapshot, severity: Severity
    ) -> RuleResult:
        if proposal.side == Side.SELL:
            return _result(
                "CMP-04", True, Severity.WARN, "exit", "buys only", "Exit does not borrow"
            )
        required = proposal.qty * proposal.limit_price + self._pending(snapshot)
        enough_equity = (
            snapshot.account_type != AccountType.MARGIN
            or snapshot.equity >= self.config.min_margin_equity
        )
        passed = required <= snapshot.cash and enough_equity
        return _result(
            "CMP-04",
            passed,
            severity,
            f"cash_required={required};equity={snapshot.equity}",
            f"cash={snapshot.cash};minimum_margin_equity={self.config.min_margin_equity}",
            "No borrowing; managed margin-account minimum equity is an operator guard",
        )

    def _day_trade(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        history: tuple[TradeRecord, ...],
        now: datetime,
        severity: Severity,
    ) -> RuleResult:
        """CMP-05: conservative opening-order count across five XNYS sessions.

        Each distinct same-day BUY order plausibly touched by a later SELL
        counts once. One sold share is allocated to each untouched opening order
        before extra shares, providing a conservative upper bound when broker
        allocation is unknown. Split fills must be consolidated by the caller;
        the broker's permitted counting method may produce fewer trades.
        """
        # VERIFY: https://syndication.finra.org/content/understanding-new-intraday-margin-requirements
        # VERIFY: https://www.finra.org/rules-guidance/guidance/interps-4210
        same_day, completed = day_trade_activity(
            self.calendar, proposal.account_id, proposal.symbol, proposal.side, history, now
        )
        legacy_block = (
            self.config.day_trade_regime == DayTradeRegime.LEGACY_PDT
            and snapshot.account_type == AccountType.MARGIN
            and same_day
            and completed >= 3
            and snapshot.equity < Decimal("25000")
        )
        result_severity = severity if legacy_block else Severity.WARN
        return _result(
            "CMP-05",
            not same_day,
            result_severity,
            f"same_day={same_day};completed={completed};equity={snapshot.equity}",
            "legacy>=3 and equity<25000; default same-day WARN",
            "Legacy same-day guard would block an addition"
            if legacy_block
            else "Same-day round-trip warning"
            if same_day
            else "No same-day round trip",
        )

    @staticmethod
    def _broker(flags: AccountFlags | None, severity: Severity) -> RuleResult:
        if flags is None:
            return _result(
                "CMP-06",
                False,
                severity,
                "missing",
                "explicit current account flags",
                "Unverifiable broker flags; HALTED required",
            )
        # VERIFY: https://docs.alpaca.markets/us/reference/getaccount-1
        checked = AccountFlags.model_validate(flags)
        return _result(
            "CMP-06",
            not checked.blocked,
            severity,
            checked.model_dump_json(),
            "ACTIVE and all flags false",
            "Broker account blocked; HALTED required"
            if checked.blocked
            else "Broker account is active and unrestricted",
        )

    def _restricted(self, proposal: TradeProposal, severity: Severity) -> RuleResult:
        instrument = self.registry.get(proposal.symbol)
        passed = (
            proposal.symbol not in self.restricted_symbols
            and instrument.tradable
            and not instrument.is_leveraged
            and not instrument.is_inverse
        )
        return _result(
            "CMP-07",
            passed,
            severity,
            proposal.symbol,
            "tradable allowlist minus restricted names",
            "Explicit instrument allowlist and restricted-list policy",
        )
