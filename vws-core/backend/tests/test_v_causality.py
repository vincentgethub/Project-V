"""QV-06: actual CRO/portfolio decisions ignore poisoned future tape."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from backend.data.frozen_filings import FrozenFilings
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries, seal_history
from backend.data.market_calendar import MarketCalendar
from backend.tests import test_replay as golden

calendar, inputs = golden.calendar, golden.inputs


def test_QV_future_prices_never_change_earlier_portfolio_decisions(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    tmp_path: Path,
) -> None:
    cutoff = date(2026, 9, 30)
    seed = golden.request(end=cutoff)
    original = golden.run(seed, inputs, calendar)
    assert original.decisions
    root = tmp_path / "poisoned"
    root.mkdir()
    changed = seal_history(
        root,
        HistoryBundle(
            series=tuple(
                HistorySeries(
                    symbol=series.symbol,
                    adjustment=series.adjustment,
                    bars=tuple(
                        bar.model_copy(
                            update={
                                "open": bar.open * Decimal(100),
                                "high": bar.high * Decimal(100),
                                "low": bar.low * Decimal(100),
                                "close": bar.close * Decimal(100),
                                "volume": bar.volume * 3,
                            }
                        )
                        if bar.session_date > cutoff
                        else bar
                        for bar in series.bars
                    ),
                )
                for series in inputs[0].bundle.series
            ),
            splits=inputs[0].bundle.splits,
        ),
        calendar,
    )
    poisoned = golden.run(seed, (changed, inputs[1]), calendar)
    assert original.manifest_sha256 != poisoned.manifest_sha256
    assert original.portfolio == poisoned.portfolio
    assert tuple(row.verdict for row in original.decisions) == tuple(
        row.verdict for row in poisoned.decisions
    )
    assert tuple(
        row.outcome.model_dump(exclude={"manifest_sha256"}) for row in original.decisions
    ) == tuple(row.outcome.model_dump(exclude={"manifest_sha256"}) for row in poisoned.decisions)
