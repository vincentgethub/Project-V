"""PF-03: causal split-aware arrays and the hunter's fixed gate windows.

Only already-effective splits enter the economic price/volume series. Historical
EMA comparisons are converted to today's basis before cent quantization. Final
vendor adjustment factors therefore cannot alter earlier decisions. Float64 is
confined to indicator math; exact native prices, costs and sizing leave here.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Self, cast

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from backend.agents.indicators import MICRO, Array, _export
from backend.agents.setup_hunter import PlaybookEvidence, PlaybookWindow, evaluate_window
from backend.core.config import YamlConfig
from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.data.data_layer import Bar, _bars_digest
from backend.data.history import Digest, HistorySeries, KnownSplit
from backend.domain.models import FrozenModel, Money, Playbook, Price, SessionDate, Symbol
from backend.evaluation.costs import Note
from backend.indicators.causal_cache import load_or_compute
from backend.indicators.vectorized import average


class GateDay(FrozenModel):
    session: SessionDate
    close: Price
    adv20: Money | None = Field(ge=0)
    median_dollar_volume_20: Money | None = Field(ge=0)
    atr14: Money | None = Field(ge=0)
    evidence: tuple[PlaybookEvidence | None, ...] = Field(min_length=3, max_length=3)
    reason: Note


class SymbolGates(FrozenModel):
    symbol: Symbol
    manifest_sha256: Digest
    config_sha256: Digest
    days: tuple[GateDay, ...] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if any(a.session >= b.session for a, b in zip(self.days, self.days[1:], strict=False)):
            raise ValueError("PF-03: precomputed gate dates must increase")
        return self


def _rsi(values: Array) -> Array:
    change = np.diff(values)
    gains = average(np.maximum(change, 0), 14, np.float64(1) / 14)
    losses = average(np.maximum(-change, 0), 14, np.float64(1) / 14)
    result = np.full(gains.shape, np.nan, dtype=np.float64)
    positive = losses > 0
    result[positive] = 100 - 100 / (1 + gains[positive] / losses[positive])
    result[(losses == 0) & (gains > 0)] = 100
    return np.concatenate((np.asarray([np.nan], dtype=np.float64), result))


def precompute_symbol(
    raw: HistorySeries,
    splits: tuple[KnownSplit, ...],
    config: YamlConfig,
    manifest_sha256: str,
    *,
    cache_root: Path | None = None,
) -> SymbolGates:
    """One full indicator pass, one bounded gate pass, no portfolio or future lookup."""
    try:
        audit = HistorySeries.model_validate(raw)
        policy = YamlConfig.model_validate(config)
        if audit.adjustment != "RAW" or audit.symbol not in policy.watchlist:
            raise ValueError("configured native audit series required")
        if not isinstance(splits, tuple) or len(splits) > 10000:
            raise ValueError("bounded split tuple required")
        actions = tuple(KnownSplit.model_validate(item) for item in splits)
        keys = tuple((item.symbol, item.effective_session) for item in actions)
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate split action")
        selected = {
            item.effective_session: item.new_shares_per_old
            for item in actions
            if item.symbol == audit.symbol
        }
        if any(day not in audit.sessions[1:] for day in selected):
            raise ValueError("split lacks native history anchor")
        factors: list[Decimal] = []
        with localcontext() as precision:
            precision.prec = 256
            factor = Decimal(1)
            for bar in audit.bars:
                factor *= selected.get(bar.session_date, Decimal(1))
                if not Decimal("1e-100") <= factor <= Decimal("1e100"):
                    raise ValueError("split basis exceeds indicator precision bound")
                factors.append(factor)
            scaled = np.asarray(
                [
                    (
                        bar.open * f,
                        bar.high * f,
                        bar.low * f,
                        bar.close * f,
                        Decimal(bar.volume) / f,
                    )
                    for bar, f in zip(audit.bars, factors, strict=True)
                ],
                dtype=np.float64,
            )
        if not np.isfinite(scaled).all() or not (scaled > 0).all():
            raise ValueError("nonfinite economic indicator input")
        opening, high, low, close, volume = (scaled[:, column] for column in range(5))

        def calculate() -> dict[str, Array]:
            emas = {
                period: average(close, period, np.float64(2) / (period + 1))
                for period in (20, 50, 200)
            }
            ranges = high - low
            ranges[1:] = np.maximum(
                np.maximum(ranges[1:], np.abs(high[1:] - close[:-1])), np.abs(low[1:] - close[:-1])
            )
            atr = average(ranges, 14, np.float64(1) / 14)
            rsi = _rsi(close)
            mean_volume = (
                pd.Series(volume)
                .shift(1)
                .rolling(20, min_periods=20)
                .mean()
                .to_numpy(dtype=np.float64)
            )
            rvol = np.full(volume.shape, np.nan, dtype=np.float64)
            np.divide(volume, mean_volume, out=rvol, where=mean_volume > 0)
            typical = (high + low + close) / 3
            return {
                "ema20": emas[20],
                "ema50": emas[50],
                "ema200": emas[200],
                "atr14": atr,
                "rsi14": rsi,
                "rvol20": rvol,
                "typical": typical,
                "volume": volume,
            }

        actions_hash = hashlib.sha256(
            json.dumps(
                [
                    action.model_dump(mode="json")
                    for action in sorted(
                        actions, key=lambda action: (action.symbol, action.effective_session)
                    )
                    if action.symbol == audit.symbol
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        arrays = load_or_compute(
            cache_root,
            audit.symbol,
            audit.sessions[-1],
            len(audit.bars),
            _bars_digest(audit.bars)[0],
            actions_hash,
            calculate,
        )
        emas = {period: arrays[f"ema{period}"] for period in (20, 50, 200)}
        atr, rsi, rvol, typical, volume = (
            arrays[name] for name in ("atr14", "rsi14", "rvol20", "typical", "volume")
        )
        days: list[GateDay] = []
        with localcontext() as precision:
            precision.prec = 256
            for i, latest in enumerate(audit.bars):
                evidence: tuple[PlaybookEvidence | None, ...] = (None, None, None)
                reason = "200-session warm-up or indicator evidence unavailable"
                atr_value = _export(atr[i : i + 1] / np.float64(factors[i]), CENT)[0]
                dollars = sorted(
                    bar.close * bar.volume for bar in audit.bars[max(0, i - 19) : i + 1]
                )
                adv = sum(dollars, Decimal(0)) / 20 if len(dollars) == 20 else None
                median = (dollars[9] + dollars[10]) / 2 if len(dollars) == 20 else None
                if i >= 199:

                    def price(index: int, field: str, current: int = i) -> Decimal:
                        # All field names are fixed local literals, never provider input.
                        bar = audit.bars[index]
                        value = {
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                        }[field]
                        return value * factors[index] / factors[current]

                    first = i - 59
                    anchor = min(range(first, i + 1), key=lambda j: (price(j, "low"), -j))
                    for j in range(i, max(anchor, 19), -1):
                        prior_vol = sum(
                            (Decimal(audit.bars[k].volume) / factors[k] for k in range(j - 20, j)),
                            Decimal(0),
                        )
                        if Decimal(audit.bars[j].volume) / factors[j] * 20 >= 2 * prior_vol and abs(
                            price(j, "open") / price(j - 1, "close") - 1
                        ) >= Decimal(".04"):
                            anchor = j
                            break
                    vwap = np.cumsum(
                        typical[anchor : i + 1] * volume[anchor : i + 1], dtype=np.float64
                    ) / np.cumsum(volume[anchor : i + 1], dtype=np.float64)
                    output = _export(
                        np.asarray(
                            [
                                emas[20][i],
                                emas[50][i],
                                emas[200][i],
                                emas[50][i - 10],
                                atr[i],
                                vwap[-1],
                                np.nan if anchor == i else vwap[-2],
                            ],
                            dtype=np.float64,
                        )
                        / np.float64(factors[i]),
                        CENT,
                    )
                    dimensions = _export(np.asarray([rsi[i], rvol[i]], dtype=np.float64), MICRO)
                    previous = audit.bars[i - 1]
                    prior_prices = tuple(
                        price(i - 1, name) for name in ("open", "high", "low", "close")
                    )
                    minima = (
                        min(
                            price(j, "low")
                            for j in range(i - policy.sizing.swing_lookback + 1, i + 1)
                        ),
                        min(price(j, "low") for j in range(i - 4, i + 1)),
                        max(price(j, "high") for j in range(i - 20, i)),
                        min(price(j, "low") for j in range(i - 20, i)),
                    )
                    if any(value != value.quantize(CENT) for value in (*prior_prices, *minima)):
                        reason = "Split-adjusted gate prices require subcents; no setup inferred"
                    elif any(value is None for value in (*output[:5], *dimensions)) or any(
                        value is not None and value <= 0 for value in output[:4]
                    ):
                        reason = "Finite positive price indicators unavailable; no setup inferred"
                    else:
                        prior = Bar(
                            timestamp=previous.timestamp,
                            open=prior_prices[0],
                            high=prior_prices[1],
                            low=prior_prices[2],
                            close=prior_prices[3],
                            volume=previous.volume,
                        )
                        frame = PlaybookWindow(
                            latest=latest,
                            prior=prior,
                            ema20=cast(Decimal, output[0]),
                            ema50=cast(Decimal, output[1]),
                            ema200=cast(Decimal, output[2]),
                            old_ema50=cast(Decimal, output[3]),
                            rsi14=cast(Decimal, dimensions[0]),
                            atr14=cast(Decimal, output[4]),
                            rvol20=cast(Decimal, dimensions[1]),
                            anchored_vwap=output[5],
                            prior_anchored_vwap=output[6],
                            swing_low=minima[0],
                            pullback_low=minima[1],
                            base_high=minima[2],
                            base_low=minima[3],
                        )
                        evidence = tuple(
                            evaluate_window(Playbook(name), frame, weights, policy.sizing)
                            for name, weights in policy.playbooks.items()
                        )
                        reason = "Shared hunter gates evaluated on causal completed-session inputs"
                days.append(
                    GateDay(
                        session=latest.session_date,
                        close=latest.close,
                        adv20=adv,
                        median_dollar_volume_20=median,
                        atr14=atr_value,
                        evidence=evidence,
                        reason=reason,
                    )
                )
        return SymbolGates(
            symbol=audit.symbol,
            manifest_sha256=manifest_sha256,
            config_sha256=policy.config_hash,
            days=tuple(days),
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("PF-03: causal replay inputs are unverifiable") from None
