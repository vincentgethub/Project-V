"""EV-02/ER-01: exact daily cash plus raw mark-to-market for CRO-sized outcomes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import model_validator

from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.data.history import FrozenHistory, validate_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel
from backend.evaluation.costs import FeeBreakdown, FillResult, Note
from backend.evaluation.dividends import (
    NOTICE as DISTRIBUTION_NOTICE,
)
from backend.evaluation.dividends import (
    distribution_credit,
    distribution_rates,
)
from backend.evaluation.edge import EdgeKey, EquityCurve, EquityPoint
from backend.evaluation.outcomes import Outcome

MAX_EQUITY_SESSIONS = 20000


class EquityBuild(FrozenModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    curve: EquityCurve | None
    reason: Note

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.status == "AVAILABLE") != (self.curve is not None):
            raise ValueError("EV-02: unavailable equity cannot invent a curve")
        return self


def _selected(key: EdgeKey, item: Outcome) -> bool:
    setup = item.setup
    return (
        (setup.playbook, setup.variant, setup.cohort, setup.disposition)
        == (
            key.playbook,
            key.variant,
            key.cohort,
            key.disposition,
        )
        and (
            key.fundamentals_status is None or key.fundamentals_status == setup.fundamentals_status
        )
        and (key.context_tag is None or key.context_tag in setup.context_tags)
    )


def build_equity_curve(
    key: EdgeKey,
    outcomes: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    *,
    initial_equity: Decimal,
    start: date,
    end: date,
    portfolio: bool = False,
) -> EquityBuild:
    """No new sizing/fill model. Cash, dated fees and whole-share splits follow EV/CM.

    The supplied baseline is explicit. Hypothetical cohorts are independent;
    concurrent fills requiring borrowed cash make equity unavailable. Exposure
    counts a session with any held shares, including an exit at its opening.
    """
    try:
        bound = EdgeKey.model_validate(key)
        frozen = FrozenHistory.model_validate(history)
        validate_history(frozen.bundle, calendar)
        if not isinstance(outcomes, tuple) or len(outcomes) > 100000:
            raise ValueError("bounded immutable outcomes required")
        checked = tuple(Outcome.model_validate(item) for item in outcomes)
        if len({item.setup.alert_id for item in checked}) != len(checked) or any(
            (
                not _selected(bound, item)
                if not portfolio
                else (item.setup.variant, item.setup.cohort, item.setup.disposition)
                != (bound.variant, bound.cohort, bound.disposition)
            )
            or item.manifest_sha256 != frozen.manifest.sha256
            for item in checked
        ):
            raise ValueError("outcomes differ from curve cohort or history")
        if (
            not isinstance(initial_equity, Decimal)
            or not initial_equity.is_finite()
            or initial_equity <= 0
        ):
            raise ValueError("positive exact initial equity required")
        if type(start) is not date or type(end) is not date or start >= end:
            raise ValueError("ordered explicit session window required")
        if not calendar.is_session(start) or not calendar.is_session(end):
            raise ValueError("XNYS session endpoints required")
        days: list[date] = [start]
        while days[-1] < end:
            if len(days) >= MAX_EQUITY_SESSIONS:
                raise ValueError("equity window exceeds its bound")
            days.append(calendar.add_sessions(days[-1], 1))
        if any(
            item.setup.decision_session < start
            or item.setup.decision_session > end
            or (item.exit_session is not None and item.exit_session > end)
            for item in checked
        ):
            raise ValueError("curve window does not cover the outcomes")
        if any(item.status == "INCOMPLETE" for item in checked):
            return EquityBuild(
                status="UNAVAILABLE",
                curve=None,
                reason="Incomplete outcome or split evidence; equity is unavailable",
            )
        prices = {
            symbol: {
                bar.session_date: bar.close for bar in frozen.bundle.for_symbol(symbol, "RAW").bars
            }
            for symbol in {item.setup.symbol for item in checked}
        }
        if any(any(day not in marks for day in days) for marks in prices.values()):
            raise ValueError("raw marks do not cover every equity session")
        entries: dict[date, list[Outcome]] = {}
        exits: dict[date, list[Outcome]] = {}
        partials: dict[date, list[Outcome]] = {}
        for item in checked:
            if item.entry_session is not None:
                entries.setdefault(item.entry_session, []).append(item)
            if item.exit_session is not None:
                exits.setdefault(item.exit_session, []).append(item)
            for row in item.partial_exits:
                partials.setdefault(row.session, []).append(item)
        actions = {
            (action.symbol, action.effective_session): action.new_shares_per_old
            for action in frozen.bundle.splits
        }
        holdings: dict[UUID, tuple[str, int]] = {}
        cash = initial_equity
        accrued_income = Decimal(0)
        rates = (
            {symbol: distribution_rates(frozen, symbol, end) for symbol in prices}
            if bound.cohort.startswith("REPLAY")
            else {}
        )
        by_identity = {item.setup.alert_id: item for item in checked}
        points: list[EquityPoint] = []
        exposed = 0
        with localcontext() as precision:
            precision.prec = 256
            if cash != cash.quantize(CENT):
                raise ValueError("initial equity requires cents")
            for day in days:
                had_shares = bool(holdings)
                for identity, (symbol, qty) in tuple(holdings.items()):
                    adjusted = qty * actions.get((symbol, day), Decimal(1))
                    if adjusted != adjusted.to_integral_value() or not 0 < adjusted <= 10**9:
                        return EquityBuild(
                            status="UNAVAILABLE",
                            curve=None,
                            reason="Split requires fractional or unbounded shares; equity is unavailable",
                        )
                    holdings[identity] = (symbol, int(adjusted))
                    expected = distribution_credit(
                        day, int(adjusted), rates.get(symbol, {}).get(day)
                    )
                    recorded = tuple(
                        credit
                        for credit in by_identity[identity].distributions
                        if credit.session == day
                    )
                    if recorded != (() if expected is None else (expected,)):
                        raise ValueError(
                            "distribution proof differs from frozen prices or held shares"
                        )
                    if expected is not None:
                        accrued_income += expected.amount
                for item in sorted(
                    partials.get(day, []), key=lambda value: value.setup.alert_id.hex
                ):
                    if item.entry_session == day:
                        continue
                    partial = next(row for row in item.partial_exits if row.session == day)
                    symbol, qty = holdings[item.setup.alert_id]
                    if not 0 < partial.fill.qty < qty:
                        raise ValueError("EX-01: partial exit exceeds held shares")
                    holdings[item.setup.alert_id] = (symbol, qty - partial.fill.qty)
                    cash += (
                        cast(Decimal, partial.fill.price) * partial.fill.qty - partial.fees.total
                    )
                for item in sorted(exits.get(day, []), key=lambda value: value.setup.alert_id.hex):
                    if item.entry_session == day:
                        continue
                    fill = cast(FillResult, item.exit_fill)
                    held = holdings.pop(item.setup.alert_id, None)
                    if held != (item.setup.symbol, fill.qty):
                        raise ValueError("exit shares differ from split-adjusted holdings")
                    cash += (
                        cast(Decimal, fill.price) * fill.qty
                        - cast(FeeBreakdown, item.exit_fees).total
                    )
                for item in sorted(
                    entries.get(day, []), key=lambda value: value.setup.alert_id.hex
                ):
                    fill = cast(FillResult, item.entry_fill)
                    debit = (
                        cast(Decimal, fill.price) * fill.qty
                        + cast(FeeBreakdown, item.entry_fees).total
                    )
                    if debit > cash:
                        return EquityBuild(
                            status="UNAVAILABLE",
                            curve=None,
                            reason="Concurrent hypothetical fills exceed available cash; no leverage is modeled",
                        )
                    cash -= debit
                    had_shares = True
                    remaining = fill.qty
                    for partial in item.partial_exits:
                        if partial.session == day:
                            remaining -= partial.fill.qty
                            cash += (
                                cast(Decimal, partial.fill.price) * partial.fill.qty
                                - partial.fees.total
                            )
                    if remaining <= 0:
                        raise ValueError("EX-01: partial exit must leave the B leg")
                    if item.exit_session == day:
                        outgoing = cast(FillResult, item.exit_fill)
                        if outgoing.qty != remaining:
                            raise ValueError("same-session exit shares differ from the entry")
                        cash += (
                            cast(Decimal, outgoing.price) * outgoing.qty
                            - cast(FeeBreakdown, item.exit_fees).total
                        )
                    else:
                        holdings[item.setup.alert_id] = (item.setup.symbol, remaining)
                equity = (
                    cash
                    + accrued_income
                    + sum(
                        (prices[symbol][day] * qty for symbol, qty in holdings.values()), Decimal(0)
                    )
                )
                if equity <= 0:
                    return EquityBuild(
                        status="UNAVAILABLE",
                        curve=None,
                        reason="Nonpositive hypothetical equity; portfolio metrics are unavailable",
                    )
                if day != start and had_shares:
                    exposed += 1
                points.append(EquityPoint(session=day, equity=equity))
        curve = EquityCurve(
            key=bound,
            manifest_sha256=frozen.manifest.sha256,
            alert_ids=tuple(
                sorted((item.setup.alert_id for item in checked), key=lambda value: value.hex)
            ),
            points=tuple(points),
            exposed_sessions=exposed,
        )
        return EquityBuild(
            status="AVAILABLE",
            curve=curve,
            reason="Daily cash plus RAW marks; recorded CRO shares, shared costs and split evidence; "
            + (DISTRIBUTION_NOTICE if bound.cohort.startswith("REPLAY") else "dividends ignored"),
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("EV-02: daily equity evidence is unverifiable") from None
