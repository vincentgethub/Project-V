"""GD-03: pure amended playbooks, exact levels and CRO-capped whole shares.

No LLM, provider, ledger, clock read or order execution occurs in this module.
The caller audits typed drops and applies the complete CRO check before research.
"""

from collections.abc import Callable
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from backend.agents.anchors import select_anchor
from backend.agents.expiry import proposal_expiry
from backend.agents.indicators import IndicatorMemo, IndicatorSeries
from backend.agents.scanner import ScannerConfig, _checked_bars
from backend.core.clock import ensure_utc
from backend.core.config import PlaybookConfig, SizingConfig, YamlConfig
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.money import CENT
from backend.data.data_layer import Bar
from backend.data.earnings_reports import EarningsReport
from backend.domain.models import (
    FrozenModel,
    Intent,
    MarketContext,
    MarketStatus,
    Money,
    Playbook,
    PortfolioSnapshot,
    Price,
    ProposalSource,
    SetupCandidate,
    SetupCriterion,
    Side,
    SizeEvidence,
    Symbol,
    TradeProposal,
    UTCDateTime,
    validate_symbol,
)
from backend.risk.overlays import fit_open_risk
from backend.risk.risk_cro import ChiefRiskOfficer

_IDENTITY = UUID("cadf65d8-1569-44ee-a074-d6f658393603")
_ZERO = Decimal(0)


class PlaybookEvidence(FrozenModel):
    """Code-produced grades and levels before minimum score and size gates."""

    playbook: Playbook
    score: Money = Field(ge=0, le=10)
    criteria: tuple[SetupCriterion, ...] = Field(min_length=6, max_length=6)
    entry: Price
    stop: Price
    target: Price

    @model_validator(mode="after")
    def consistent(self) -> Self:
        with localcontext() as context:
            context.prec = 80
            if sum((item.points for item in self.criteria), _ZERO) != self.score:
                raise ValueError("GD-03: score must equal criterion points")
            if not self.stop < self.entry < self.target:
                raise ValueError("GD-03: invalid long setup levels")
            if (self.target - self.entry) / (self.entry - self.stop) < Decimal("1.5"):
                raise ValueError("GD-03: target reward/risk is below 1.5")
        if len({item.name for item in self.criteria}) != 6:
            raise ValueError("GD-03: six unique criterion names required")
        return self


class HuntDrop(FrozenModel):
    playbook: Playbook
    reason: str = Field(max_length=280)
    filtered_candidate: SetupCandidate | None = Field(default=None, exclude_if=lambda v: v is None)
    reductions: SizeEvidence | None = Field(default=None, exclude_if=lambda v: v is None)
    filtered_cro_cap: int | None = Field(
        default=None, strict=True, ge=0, le=0, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def shadow_bound(self) -> Self:
        if (self.filtered_candidate is None) != (self.reductions is None):
            raise ValueError("ER-04: filter shadow needs its exact reduction evidence")
        if self.filtered_cro_cap is not None and self.filtered_candidate is None:
            raise ValueError("ER-04: CRO shadow requires its candidate")
        if (
            self.filtered_candidate is not None
            and self.reductions is not None
            and (
                self.filtered_candidate.playbook != self.playbook
                or self.filtered_candidate.qty != self.reductions.base_qty
                or self.filtered_candidate.size_evidence is not None
                or self.reductions.product >= 1
                and self.filtered_cro_cap is None
            )
        ):
            raise ValueError("ER-04: shadow must retain the unsized candidate")
        return self


class PlaybookWindow(FrozenModel):
    """PF-03: sufficient completed-bar facts for the shared daily gate logic.

    Replay computes these once. Prices retain the current session's split basis;
    neither a future bar nor portfolio state is needed to grade a playbook.
    """

    latest: Bar
    prior: Bar
    ema20: Price
    ema50: Price
    ema200: Price
    old_ema50: Price
    rsi14: Money = Field(ge=0, le=100)
    atr14: Money = Field(ge=0)
    rvol20: Money = Field(ge=0)
    anchored_vwap: Price | None
    prior_anchored_vwap: Price | None
    swing_low: Price
    pullback_low: Price
    base_high: Price
    base_low: Price

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.prior.session_date >= self.latest.session_date or self.base_low > self.base_high:
            raise ValueError("PF-03: gate window is unordered")
        with localcontext() as precision:
            precision.prec = 80
            if self.atr14 != self.atr14.quantize(CENT):
                raise ValueError("PF-03: ATR must retain the cent-valued indicator boundary")
        return self


class HuntResult(FrozenModel):
    symbol: Symbol
    as_of: UTCDateTime
    candidates: tuple[SetupCandidate, ...] = Field(max_length=4)
    drops: tuple[HuntDrop, ...] = Field(max_length=4)
    active_playbooks: tuple[Playbook, ...] = Field(
        default=(Playbook.TREND_50EMA, Playbook.BASE_BREAKOUT, Playbook.ANCHORED_VWAP_RECLAIM),
        min_length=1,
        max_length=4,
        exclude_if=lambda value: (
            value == (Playbook.TREND_50EMA, Playbook.BASE_BREAKOUT, Playbook.ANCHORED_VWAP_RECLAIM)
        ),
    )

    @model_validator(mode="after")
    def consistent(self) -> Self:
        names = (
            *tuple(item.playbook for item in self.candidates),
            *tuple(item.playbook for item in self.drops),
        )
        if (
            len(names) != len(self.active_playbooks)
            or set(names) != set(self.active_playbooks)
            or len(set(self.active_playbooks)) != len(self.active_playbooks)
        ):
            raise ValueError("GD-03: exactly one result per daily playbook required")
        if any(item.symbol != self.symbol or item.as_of != self.as_of for item in self.candidates):
            raise ValueError("GD-03: candidate provenance differs from hunt")
        return self


def score_eligible(score: Decimal, minimum: Decimal) -> bool:
    """Never round the score up across its gate."""
    if not isinstance(score, Decimal) or not isinstance(minimum, Decimal):
        raise DataIntegrityError("GD-03: setup score requires exact Decimal")
    if (
        not score.is_finite()
        or not minimum.is_finite()
        or not 0 <= score <= 10
        or not 6 <= minimum <= 10
    ):
        raise DataIntegrityError("GD-03: setup score or minimum is out of bounds")
    return score >= minimum


def evaluate_playbook(
    playbook: Playbook,
    bars: tuple[Bar, ...],
    series: IndicatorSeries,
    weights: PlaybookConfig,
    sizing: SizingConfig,
) -> PlaybookEvidence | None:
    """Exact hard gates and default point table from Amendment01 section4.3.

    The hunter validates calendar/bar provenance and shares the memo with the
    scanner. Undefined indicators and failed hard/level gates return no setup.
    Stops round down and targets up, preserving conservative risk and reward.
    """
    from backend.agents.indicators import _bars

    try:
        bars = _bars(bars)
        series = IndicatorSeries.model_validate(series)
        weights = PlaybookConfig.model_validate(weights)
        sizing = SizingConfig.model_validate(sizing)
        if len(bars) != len(series.ema20):
            raise DataIntegrityError("GD-03: indicator and bar lengths differ")
        if len(bars) < 200:
            return None
        values = (
            series.ema20[-1],
            series.ema50[-1],
            series.ema200[-1],
            series.ema50[-11],
            series.rsi14[-1],
            series.atr14[-1],
            series.rvol20[-1],
        )
        if any(value is None for value in values):
            return None
        e20, e50, e200, old50, rsi, atr, rvol = (value for value in values if value is not None)
        window = PlaybookWindow(
            latest=bars[-1],
            prior=bars[-2],
            ema20=e20,
            ema50=e50,
            ema200=e200,
            old_ema50=old50,
            rsi14=rsi,
            atr14=atr,
            rvol20=rvol,
            anchored_vwap=series.anchored_vwap[-1],
            prior_anchored_vwap=series.anchored_vwap[-2],
            swing_low=min(bar.low for bar in bars[-sizing.swing_lookback :]),
            pullback_low=min(bar.low for bar in bars[-5:]),
            base_high=max(bar.high for bar in bars[-21:-1]),
            base_low=min(bar.low for bar in bars[-21:-1]),
        )
        return evaluate_window(playbook, window, weights, sizing)

    except (DataIntegrityError, ConfigurationError):
        raise
    except Exception:
        raise DataIntegrityError(
            "GD-03: deterministic playbook evidence cannot be verified"
        ) from None


def evaluate_window(
    playbook: Playbook,
    window: PlaybookWindow,
    weights: PlaybookConfig,
    sizing: SizingConfig,
) -> PlaybookEvidence | None:
    """GD-03/PF-03: the same fixed hard gates, grades and levels for live/replay."""
    try:
        window = PlaybookWindow.model_validate(window)
        weights = PlaybookConfig.model_validate(weights)
        sizing = SizingConfig.model_validate(sizing)
        e20, e50, e200, old50 = window.ema20, window.ema50, window.ema200, window.old_ema50
        rsi, atr, rvol = window.rsi14, window.atr14, window.rvol20
        with localcontext() as context:
            context.prec = 80
            t, prior = window.latest, window.prior
            entry = t.high + CENT
            stop = min(
                entry - sizing.stop_atr_mult * atr,
                window.swing_low - CENT,
            ).quantize(CENT, rounding=ROUND_FLOOR)
            if stop <= 0 or atr <= 0 or (entry - stop) / entry > sizing.max_stop_pct:
                return None
            target = (entry + sizing.target_r * (entry - stop)).quantize(
                CENT, rounding=ROUND_CEILING
            )
            range_pos = _ZERO if t.high == t.low else (t.close - t.low) / (t.high - t.low)
            slope = (e50 / old50 - 1) if old50 > 0 else _ZERO
            pullback = window.pullback_low
            grades: dict[str, tuple[Decimal, str]]
            if playbook == Playbook.TREND_50EMA:
                if not (
                    t.close > e200
                    and e50 > old50
                    and pullback <= e50 * Decimal("1.01")
                    and t.close > e50
                    and t.close > prior.high
                ):
                    return None
                grades = {
                    "trend": (
                        Decimal(e20 > e50 > e200),
                        f"EMA20={e20}; EMA50={e50}; EMA200={e200}",
                    ),
                    "slope": (
                        Decimal(1)
                        if slope >= Decimal("0.02")
                        else Decimal("0.5")
                        if slope >= Decimal("0.01")
                        else _ZERO,
                        f"EMA50 10-session slope={slope}",
                    ),
                    "pullback": (
                        Decimal(abs(pullback / e50 - 1) <= Decimal("0.01")),
                        f"last5 low={pullback}; EMA50={e50}",
                    ),
                    "range_position": (
                        Decimal(range_pos >= Decimal("0.7")),
                        f"range position={range_pos}",
                    ),
                    "relative_volume": (Decimal(rvol >= Decimal("1.2")), f"RVOL={rvol}"),
                    "rsi": (Decimal(45 <= rsi <= 65), f"RSI14={rsi}"),
                }
            elif playbook == Playbook.BASE_BREAKOUT:
                ceiling = window.base_high
                base_range = (ceiling - window.base_low) / t.close
                margin = t.close / ceiling - 1
                if not (
                    t.close > ceiling and rvol >= Decimal("1.5") and base_range <= Decimal("0.15")
                ):
                    return None
                grades = {
                    "breakout": (
                        Decimal(1)
                        if Decimal("0.005") <= margin <= Decimal("0.03")
                        else Decimal("0.5")
                        if margin > Decimal("0.03")
                        else _ZERO,
                        f"breakout margin={margin}",
                    ),
                    "relative_volume": (
                        Decimal(1) if rvol >= 2 else Decimal("0.5"),
                        f"RVOL={rvol}",
                    ),
                    "base_range": (
                        Decimal(1) if base_range <= Decimal("0.10") else Decimal("0.5"),
                        f"prior20 range/close={base_range}",
                    ),
                    "trend": (
                        Decimal(t.close > e50 > e200),
                        f"close={t.close}; EMA50={e50}; EMA200={e200}",
                    ),
                    "rsi": (Decimal(55 <= rsi <= 75), f"RSI14={rsi}"),
                    "range_position": (
                        Decimal(range_pos >= Decimal("0.75")),
                        f"range position={range_pos}",
                    ),
                }
            elif playbook == Playbook.ANCHORED_VWAP_RECLAIM:
                avwap, old_vwap = window.anchored_vwap, window.prior_anchored_vwap
                if (
                    avwap is None
                    or old_vwap is None
                    or not (prior.close < old_vwap and t.close > avwap and rvol >= Decimal("1.2"))
                ):
                    return None
                margin = t.close / avwap - 1
                grades = {
                    "reclaim": (
                        Decimal(Decimal("0.005") <= margin <= Decimal("0.03")),
                        f"reclaim margin={margin}",
                    ),
                    "relative_volume": (
                        Decimal(1) if rvol >= Decimal("1.5") else Decimal("0.5"),
                        f"RVOL={rvol}",
                    ),
                    "slope": (Decimal(e50 > old50), f"EMA50={e50}; ten sessions ago={old50}"),
                    "atr_risk": (
                        Decimal(entry - stop <= 2 * atr),
                        f"entry-stop={entry - stop}; ATR14={atr}",
                    ),
                    "rsi": (Decimal(45 <= rsi <= 65), f"RSI14={rsi}"),
                    "range_position": (
                        Decimal(range_pos >= Decimal("0.7")),
                        f"range position={range_pos}",
                    ),
                }
            else:
                raise DataIntegrityError("GD-03: unsupported daily playbook")
            if set(weights.criteria_weights) != set(grades):
                raise ConfigurationError(
                    "GD-03: playbook criterion weights do not match its defined criteria"
                )
            criteria = tuple(
                SetupCriterion(
                    name=name, points=10 * weights.criteria_weights[name] * grade, reason=reason
                )
                for name, (grade, reason) in grades.items()
            )
            return PlaybookEvidence(
                playbook=playbook,
                score=sum((item.points for item in criteria), _ZERO),
                criteria=criteria,
                entry=entry,
                stop=stop,
                target=target,
            )
    except (DataIntegrityError, ConfigurationError):
        raise
    except Exception:
        raise DataIntegrityError(
            "GD-03: deterministic playbook evidence cannot be verified"
        ) from None


class SetupHunter:
    """Each whole-share size uses exactly the risk buffer charged by CRO-04."""

    def __init__(self, cro: ChiefRiskOfficer, config: YamlConfig, memo: IndicatorMemo) -> None:
        if not isinstance(cro, ChiefRiskOfficer) or not isinstance(memo, IndicatorMemo):
            raise ConfigurationError("GD-03: hunter requires the CRO and shared indicator memo")
        self.cro = cro
        self.config = YamlConfig.model_validate(config)
        self.config.assert_settings_consistent(cro.config)
        self.config.assert_allowed_symbols(cro.registry.symbols)
        self.memo = memo
        self.size_provider: (
            Callable[[str, Decimal, int, PortfolioSnapshot, datetime], SizeEvidence] | None
        ) = None

    def hunt(
        self,
        symbol: str,
        bars: tuple[Bar, ...],
        snapshot: PortfolioSnapshot,
        market: MarketContext,
        now: datetime,
        *,
        earnings_reports: tuple[EarningsReport, ...] = (),
        spy_bars: tuple[Bar, ...] = (),
        stock_return_bars: tuple[Bar, ...] | None = None,
    ) -> HuntResult:
        try:
            validate_symbol(symbol)
            instant = ensure_utc(now)
            snapshot = PortfolioSnapshot.model_validate(snapshot)
            market = MarketContext.model_validate(market)
            checked = _checked_bars(
                bars,
                instant,
                self.cro.calendar,
                ScannerConfig(),
            )
            if symbol not in self.config.watchlist:
                raise DataIntegrityError("GD-03: hunter symbol is outside configured watchlist")
            series = (
                self.memo.calculate(symbol, checked, select_anchor(checked)[0])
                if len(checked) >= 200 and market.status == MarketStatus.OK
                else None
            )
            evidence: list[PlaybookEvidence | None] = []
            for name in self.config.enabled_playbooks:
                if series is None:
                    evidence.append(None)
                elif name == "EARNINGS_GAP":
                    from backend.agents.earnings_gap import evaluate_earnings_gap

                    evidence.append(
                        evaluate_earnings_gap(
                            self.cro.registry.get(symbol),
                            checked,
                            series,
                            spy_bars,
                            earnings_reports,
                            self.config.sizing,
                            instant,
                            self.cro.calendar,
                            stock_return_bars=stock_return_bars,
                        )
                        if earnings_reports and spy_bars
                        else None
                    )
                else:
                    evidence.append(
                        evaluate_playbook(
                            Playbook(name),
                            checked,
                            series,
                            self.config.playbooks[name],
                            self.config.sizing,
                        )
                    )
            return self.size_evidence(symbol, tuple(evidence), snapshot, market, instant)

        except (DataIntegrityError, ConfigurationError):
            raise
        except Exception:
            raise DataIntegrityError("GD-03: hunter failed closed") from None

    def size_evidence(
        self,
        symbol: str,
        evidence: tuple[PlaybookEvidence | None, ...],
        snapshot: PortfolioSnapshot,
        market: MarketContext,
        now: datetime,
    ) -> HuntResult:
        """PF-03: sequential portfolio sizing of precomputed, revalidated grades."""
        try:
            validate_symbol(symbol)
            instant = ensure_utc(now)
            snapshot = PortfolioSnapshot.model_validate(snapshot)
            market = MarketContext.model_validate(market)
            if (
                symbol not in self.config.watchlist
                or not isinstance(evidence, tuple)
                or len(evidence) != len(self.config.enabled_playbooks)
            ):
                raise DataIntegrityError("PF-03: bounded configured daily evidence required")
            results: list[SetupCandidate] = []
            drops: list[HuntDrop] = []
            for name, item in zip(self.config.enabled_playbooks, evidence, strict=True):
                filtered_candidate = None
                reductions = None
                filtered_cro_cap = None
                playbook = Playbook(name)
                found = PlaybookEvidence.model_validate(item) if item is not None else None
                if found is not None and found.playbook != playbook:
                    raise DataIntegrityError("PF-03: precomputed playbook ordering differs")
                if market.status != MarketStatus.OK:
                    found = None
                reason = "hard gate, indicator or level evidence unavailable"
                if found is not None and score_eligible(
                    found.score, self.cro.config.min_setup_score
                ):
                    with localcontext() as context:
                        context.prec = 80
                        per_share = (
                            found.entry
                            - found.stop
                            + found.entry * self.cro.config.stop_slippage_buffer
                        )
                        qty = max(
                            0,
                            int(
                                self.config.sizing.target_risk_per_trade
                                * snapshot.equity
                                / per_share
                            ),
                        )
                    factors = SizeEvidence(base_qty=qty, minimum=self.config.sizing.min_multiplier)
                    if qty and self.size_provider is not None:
                        factors = SizeEvidence.model_validate(
                            self.size_provider(symbol, found.score, qty, snapshot, instant)
                        )
                        if (
                            factors.base_qty != qty
                            or factors.minimum != self.config.sizing.min_multiplier
                        ):
                            raise DataIntegrityError(
                                "PR-04: reduction evidence has another base size or policy"
                            )
                        qty = factors.qty
                    reason = "quantity zero; no alert or LLM call"
                    if not qty and factors is not None and factors.product < 1:
                        reductions = factors
                        filtered_candidate = SetupCandidate(
                            symbol=symbol,
                            playbook=playbook,
                            score=found.score,
                            criteria=found.criteria,
                            entry_price=found.entry,
                            stop_price=found.stop,
                            target_price=found.target,
                            qty=factors.base_qty,
                            as_of=instant,
                        )
                    if qty:
                        identity = f"{snapshot.account_id}/{symbol}/{playbook.value}/{instant.isoformat()}/{self.config.config_hash}"
                        proposal = TradeProposal(
                            proposal_id=uuid5(_IDENTITY, identity),
                            signal_id=uuid5(_IDENTITY, identity + "/signal"),
                            account_id=snapshot.account_id,
                            symbol=symbol,
                            side=Side.BUY,
                            intent=Intent.ENTRY,
                            qty=qty,
                            limit_price=found.entry,
                            stop_price=found.stop,
                            target_price=found.target,
                            source=ProposalSource.SIGNAL,
                            created_at=instant,
                            expires_at=proposal_expiry(
                                instant, self.cro.config.proposal_ttl_sessions, self.cro.calendar
                            ),
                            size_evidence=factors,
                        )
                        qty = min(
                            fit_open_risk(
                                qty, proposal, snapshot, self.cro.config.portfolio_max_open_risk
                            ),
                            self.cro.max_allowed_qty(proposal, snapshot, market, instant),
                        )
                        if not qty:
                            filtered_cro_cap = 0
                            reductions = factors
                            filtered_candidate = SetupCandidate(
                                symbol=symbol,
                                playbook=playbook,
                                score=found.score,
                                criteria=found.criteria,
                                entry_price=found.entry,
                                stop_price=found.stop,
                                target_price=found.target,
                                qty=factors.base_qty,
                                as_of=instant,
                            )
                        if qty:
                            results.append(
                                SetupCandidate(
                                    symbol=symbol,
                                    playbook=playbook,
                                    score=found.score,
                                    criteria=found.criteria,
                                    entry_price=found.entry,
                                    stop_price=found.stop,
                                    target_price=found.target,
                                    qty=qty,
                                    as_of=instant,
                                    size_evidence=factors,
                                )
                            )
                            continue
                elif found is not None:
                    reason = "setup score below configured minimum"
                drops.append(
                    HuntDrop(
                        playbook=playbook,
                        reason=reason,
                        filtered_candidate=filtered_candidate,
                        reductions=reductions,
                        filtered_cro_cap=filtered_cro_cap,
                    )
                )
            return HuntResult(
                symbol=symbol,
                as_of=instant,
                candidates=tuple(results),
                drops=tuple(drops),
                active_playbooks=tuple(Playbook(name) for name in self.config.enabled_playbooks),
            )
        except (DataIntegrityError, ConfigurationError):
            raise
        except Exception:
            raise DataIntegrityError("PF-03: replay sizing failed closed") from None
