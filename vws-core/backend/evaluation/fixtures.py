"""EV-03 acceptance: fixed synthetic history/filings; never owner account evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.frozen_filings import FilingEvidence, FrozenFilings, seal_filings
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries, seal_history
from backend.data.market_calendar import MarketCalendar
from backend.data.sec_edgar import SecPayload
from backend.evaluation.replay import ReplayRequest
from backend.evaluation.weekly import SYNTHETIC_NOTICE

SYNTHETIC = SYNTHETIC_NOTICE
MAX_FIXTURE_SESSIONS = 20000


def offline_settings() -> Settings:
    # Construct defaults without environment sources, then fully revalidate.
    # No unvalidated instance reaches an indicator, risk rule or replay boundary.
    return Settings.validated_copy(Settings.model_construct(broker_account_type="CASH"))


def _filings(first_year: int, last_year: int, fetched: date) -> SecPayload:
    amounts = {
        "Revenues": 1000,
        "GrossProfit": 500,
        "OperatingIncomeLoss": 200,
        "NetCashProvidedByUsedInOperatingActivities": 300,
        "PaymentsToAcquirePropertyPlantAndEquipment": 100,
        "InterestExpense": 20,
        "IncomeTaxExpenseBenefit": 40,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 200,
        "StockholdersEquity": 900,
        "LongTermDebt": 200,
        "CashAndCashEquivalentsAtCarryingValue": 100,
    }
    balances = {"StockholdersEquity", "LongTermDebt", "CashAndCashEquivalentsAtCarryingValue"}
    facts: dict[str, object] = {}
    for tag, amount in amounts.items():
        rows: list[dict[str, object]] = []
        for year in range(first_year, last_year + 1):
            for quarter, (month, day) in enumerate(((3, 31), (6, 30), (9, 30), (12, 31)), 1):
                end = date(year, month, day)
                row: dict[str, object] = {
                    "val": amount if tag in balances else amount * quarter // 4,
                    "end": end.isoformat(),
                    "filed": (end + timedelta(days=30)).isoformat(),
                    "form": "10-K" if quarter == 4 else "10-Q",
                }
                if tag not in balances:
                    row["start"] = date(year, 1, 1).isoformat()
                rows.append(row)
        facts[tag] = {"units": {"USD": rows}}
    raw = json.dumps(
        {"cik": 1, "facts": {"us-gaap": facts}}, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    from datetime import UTC, datetime

    return SecPayload(
        kind="COMPANYFACTS",
        cik="0000000001",
        fetched_at=datetime.combine(fetched, datetime.min.time(), UTC),
        raw=raw,
        data_sha256=hashlib.sha256(raw).hexdigest(),
    )


def seal_offline_fixtures(
    root: Path, request: ReplayRequest, calendar: MarketCalendar
) -> tuple[FrozenHistory, FrozenFilings]:
    """One prescribed tape pattern, not generated parameter combinations."""
    try:
        seed = ReplayRequest.model_validate(request)
        first = seed.start
        while not calendar.is_session(first):
            first += timedelta(days=1)
        last = seed.end
        while not calendar.is_session(last):
            last -= timedelta(days=1)
        if first >= last:
            raise ValueError("synthetic replay needs multiple sessions")
        dates = list(calendar.previous_sessions(first, 200))
        dates.append(first)
        while dates[-1] < last:
            if len(dates) >= MAX_FIXTURE_SESSIONS:
                raise ValueError("synthetic tape exceeds its bound")
            dates.append(calendar.add_sessions(dates[-1], 1))
        bars: list[Bar] = []
        for index, day in enumerate(dates):
            base = Decimal(50) + Decimal(index) * Decimal(".01")
            close = base + (Decimal(".75") if index % 40 == 39 else Decimal(0))
            bars.append(
                Bar(
                    timestamp=calendar.session_open(day) - timedelta(hours=5, minutes=30),
                    open=close - Decimal(".05"),
                    high=close + Decimal(".01"),
                    low=close - Decimal(".25"),
                    close=close,
                    volume=2000000 if index % 40 == 39 else 1000000,
                )
            )
        bundle = HistoryBundle(
            series=tuple(
                HistorySeries(symbol=symbol, adjustment=adj, bars=tuple(bars))
                for symbol in tuple(sorted({*seed.symbols, "SPY"}))
                for adj in ("ALL", "RAW", "SPLIT")
            )
        )
        history = seal_history(root, bundle, calendar)
        payload = _filings(dates[0].year - 2, last.year, last + timedelta(days=60))
        raw_submissions = json.dumps(
            {
                "cik": 1,
                "filings": {
                    "recent": {
                        "form": [],
                        "items": [],
                        "acceptanceDateTime": [],
                        "accessionNumber": [],
                    }
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        submissions = SecPayload(
            kind="SUBMISSIONS",
            cik=payload.cik,
            fetched_at=payload.fetched_at,
            raw=raw_submissions,
            data_sha256=hashlib.sha256(raw_submissions).hexdigest(),
        )
        filings = seal_filings(
            root,
            tuple(
                FilingEvidence(symbol=symbol, payload=evidence)
                for symbol in seed.symbols
                for evidence in (payload, submissions)
            ),
        )
        return history, filings
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("EV-03: synthetic fixture preparation failed") from None
