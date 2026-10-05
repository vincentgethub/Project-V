"""R-02: injectable notifications for each persisted halt."""

from threading import Lock
from typing import Protocol

import structlog

from backend.core.logging import redact


class Notifier(Protocol):
    """R-02: notifications are boundary effects, never risk-rule decisions."""

    def notify(self, state: str, reason: str) -> None:
        """R-02: report a state escalation and its reason."""
        raise NotImplementedError("Notifier implementations must supply notify")


class ConsoleNotifier:
    """R-02/R-07: emit structured console notifications through redaction."""

    def notify(self, state: str, reason: str) -> None:
        """R-02: report an escalation to the configured structured logger."""
        structlog.get_logger("vws.safety").critical(
            "system_state_notification", state=redact(state), reason=redact(reason)
        )


class DeduplicatingNotifier:
    """R-02/R-07: deliver each redacted state/reason once per halt episode.

    Failed deliveries are retried, not marked delivered. Resetting the cache is
    explicit so an operator reset permits another notification for a new halt.
    """

    def __init__(self, delegate: Notifier) -> None:
        self.delegate = delegate
        self._delivered: set[tuple[str, str]] = set()
        self._lock = Lock()

    def notify(self, state: str, reason: str) -> None:
        """R-02: serialize deduplication and remember successful delivery only."""
        key = (str(redact(state)), str(redact(reason)))
        with self._lock:
            if key not in self._delivered:
                self.delegate.notify(*key)
                self._delivered.add(key)

    def reset(self) -> None:
        """R-02: begin a fresh notification episode after audited recovery."""
        with self._lock:
            self._delivered.clear()
