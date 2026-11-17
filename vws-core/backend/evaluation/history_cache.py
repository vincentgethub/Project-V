"""PF-04: validate one immutable frozen history once per evaluator.

The cache belongs to one evaluator instance (never module-global). It is keyed
by the SHA-256 of the history's full canonical content, never by object
identity, and it stores only a history that passed full validation. A miss,
a different calendar, a non-FrozenHistory input or an unhashable input is
fully validated, exactly as before. A hit returns the object that itself
passed validation and whose content still hashes to the key, so unvalidated
or altered content is never used downstream.
"""

from __future__ import annotations

import hashlib

from backend.data.history import FrozenHistory, canonical_bytes, validate_history
from backend.data.market_calendar import MarketCalendar

MAX_ENTRIES = 8


class ValidatedHistories:
    """Content-hash cache of successful FrozenHistory + DQ-03 validations."""

    def __init__(self, calendar: MarketCalendar) -> None:
        self.calendar = calendar
        self._passed: dict[str, FrozenHistory] = {}

    def __len__(self) -> int:
        return len(self._passed)

    def validated(self, history: FrozenHistory, calendar: MarketCalendar) -> FrozenHistory:
        key = None
        # A different calendar only disables the cache; it never selects an entry.
        if calendar is self.calendar and type(history) is FrozenHistory:
            try:
                key = hashlib.sha256(canonical_bytes(history)).hexdigest()
            except Exception:
                key = None
            cached = None if key is None else self._passed.get(key)
            if key is not None and cached is not None:
                # The served object must still have the content that passed.
                if hashlib.sha256(canonical_bytes(cached)).hexdigest() == key:
                    return cached
                del self._passed[key]
        frozen = FrozenHistory.model_validate(history)
        validate_history(frozen.bundle, calendar)
        if key is not None and len(self._passed) < MAX_ENTRIES:
            self._passed[key] = frozen
        return frozen
