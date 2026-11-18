"""EGR-01..05: monthly outbound byte budget for the paper host.

Outbound bytes are read from the default-route interface in /proc/net/dev and
charged to a counter for the UTC calendar month, persisted atomically in the
runtime data directory. The cap defaults to 1 GB and can only be lowered. A
reboot, a kernel counter reset or a wrap never lowers the count: a reading
below the last one is charged in full as the new delta.

At 80% non-essential egress (research, news, LLM, optional feeds) is paused.
At 95% new entries are also blocked. A missing, corrupt or unreadable counter
or /proc source counts as 95%. Reduce-only broker traffic (order status,
cancel, reconcile, flatten), Telegram alerts and the healthcheck are never
gated. Linux only; any other platform reports unsupported and fails closed.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from backend.core.clock import Clock, ensure_utc
from backend.core.errors import ConfigurationError, DataIntegrityError

DEFAULT_BUDGET_BYTES = 1_000_000_000
PAUSE_PERCENT = 80
BLOCK_PERCENT = 95
# Reduce-only broker traffic, owner alerts and the healthcheck are never paused.
# Any other purpose, including an unknown one, is non-essential (fail closed).
ESSENTIAL_PURPOSES = frozenset(
    {"alpaca", "alpaca-order", "alpaca_fills", "sdk", "telegram", "telegram_api", "job_health"}
)
_PROC_LIMIT = 1_048_576
_STATE_LIMIT = 4096
_IFACE = re.compile(r"^[A-Za-z0-9_.:@-]{1,15}$")
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_KEYS = frozenset({"version", "month", "iface", "last", "used"})

Notify = Callable[[str], Awaitable[None]]


class EgressLevel(StrEnum):
    OK = "OK"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class EgressStatus:
    level: EgressLevel
    month: str
    used: int | None
    budget: int
    reason: str

    def message(self) -> str:
        if self.used is None:
            return (
                f"EGR: outbound byte counter UNAVAILABLE ({self.reason}); treated as 95%: "
                "new entries blocked and non-essential egress paused. Broker exits, "
                "alerts and the healthcheck stay open."
            )
        share = f"{self.used} of {self.budget} bytes for {self.month} UTC"
        if self.level == EgressLevel.BLOCKED:
            return (
                f"EGR: outbound bytes at 95% or more of the budget ({share}): new entries "
                "blocked and non-essential egress paused. Broker exits stay open."
            )
        return (
            f"EGR: outbound bytes at 80% or more of the budget ({share}): research, news, "
            "LLM and optional feeds paused."
        )


def budget_from(raw: str | None) -> tuple[int, str | None]:
    """EGR-02: a budget can only be lowered; anything else uses the default."""
    if raw is None:
        return DEFAULT_BUDGET_BYTES, None
    if not re.fullmatch(r"[0-9]{1,13}", raw) or not 1 <= int(raw) <= DEFAULT_BUDGET_BYTES:
        return DEFAULT_BUDGET_BYTES, (
            "EGR: configured egress budget refused (it must be a whole number of bytes "
            f"from 1 to the {DEFAULT_BUDGET_BYTES} default); using the default."
        )
    return int(raw), None


def _bounded(path: Path) -> str:
    with path.open("rb") as stream:
        data = stream.read(_PROC_LIMIT + 1)
    if len(data) > _PROC_LIMIT:
        raise DataIntegrityError("EGR: kernel network table exceeds its bound")
    return data.decode("ascii")


def default_interface(route: str) -> str:
    """EGR-01: the lowest-metric up default route in /proc/net/route, never lo."""
    lines = route.splitlines()
    if not lines or lines[0].split()[:4] != ["Iface", "Destination", "Gateway", "Flags"]:
        raise DataIntegrityError("EGR: /proc/net/route header is unreadable")
    header = lines[0].split()
    if "Metric" not in header or "Mask" not in header:
        raise DataIntegrityError("EGR: /proc/net/route header is unreadable")
    metric, mask = header.index("Metric"), header.index("Mask")
    best: tuple[int, str] | None = None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != len(header):
            raise DataIntegrityError("EGR: /proc/net/route row is unreadable")
        try:
            flags, cost = int(fields[3], 16), int(fields[metric])
        except ValueError:
            raise DataIntegrityError("EGR: /proc/net/route row is unreadable") from None
        name = fields[0]
        if not _IFACE.fullmatch(name):
            raise DataIntegrityError("EGR: /proc/net/route interface name is unreadable")
        if name == "lo" or fields[1] != "00000000" or fields[mask] != "00000000":
            continue
        if flags & 0x1 and (best is None or (cost, name) < best):
            best = (cost, name)
    if best is None:
        raise DataIntegrityError("EGR: no default-route interface")
    return best[1]


def tx_bytes(dev: str, iface: str) -> int:
    """EGR-01: transmit bytes (the ninth counter) of one /proc/net/dev interface."""
    found: list[int] = []
    for line in dev.splitlines()[2:]:
        name, separator, rest = line.partition(":")
        if not separator:
            raise DataIntegrityError("EGR: /proc/net/dev row is unreadable")
        if name.strip() != iface:
            continue
        fields = rest.split()
        if len(fields) != 16 or not all(field.isdigit() for field in fields):
            raise DataIntegrityError("EGR: /proc/net/dev counters are unreadable")
        found.append(int(fields[8]))
    if len(found) != 1:
        raise DataIntegrityError("EGR: primary interface counters are missing or duplicated")
    return found[0]


def _month(clock: Clock) -> str:
    return f"{ensure_utc(clock.now()):%Y-%m}"


@dataclass(frozen=True, slots=True)
class _Counter:
    month: str
    iface: str
    last: int
    used: int


def _read_state(path: Path, month: str) -> _Counter:
    with path.open("rb") as stream:
        data = stream.read(_STATE_LIMIT + 1)
    if len(data) > _STATE_LIMIT:
        raise DataIntegrityError("EGR: counter file exceeds its bound")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict) or set(value) != _KEYS or value["version"] != 1:
        raise DataIntegrityError("EGR: counter file has an unknown shape")
    stamp, iface, last, used = value["month"], value["iface"], value["last"], value["used"]
    if (
        not isinstance(stamp, str)
        or not _MONTH.fullmatch(stamp)
        or stamp > month
        or not isinstance(iface, str)
        or not _IFACE.fullmatch(iface)
        or type(last) is not int
        or type(used) is not int
        or last < 0
        or used < 0
    ):
        raise DataIntegrityError("EGR: counter file values are invalid")
    return _Counter(stamp, iface, last, used)


def _write_state(path: Path, state: _Counter) -> None:
    """EGR-01: write-then-rename, so a crash leaves the old or the new counter."""
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(
        {
            "version": 1,
            "month": state.month,
            "iface": state.iface,
            "last": state.last,
            "used": state.used,
        },
        sort_keys=True,
    ).encode("ascii")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class EgressWatch:
    """EGR: sample, persist and gate the monthly outbound byte budget."""

    def __init__(
        self,
        state_path: Path,
        clock: Clock,
        *,
        proc: Path = Path("/proc"),
        budget: str | None = None,
        platform: str = "",
        max_age_seconds: int = 60,
    ) -> None:
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
            raise ConfigurationError("EGR: sample age must be 1-3600 seconds")
        self.state_path, self.clock, self.proc = state_path, clock, proc
        self.platform = platform or sys.platform
        self.budget, self.refusal = budget_from(budget)
        self.max_age_seconds = max_age_seconds
        self._cached: tuple[float, EgressStatus] | None = None
        self._alerted: set[tuple[str, ...]] = set()

    def _over(self, month: str, reason: str) -> EgressStatus:
        return EgressStatus(EgressLevel.BLOCKED, month, None, self.budget, reason)

    def sample(self) -> EgressStatus:
        month = _month(self.clock)
        status = self._measure(month)
        self._cached = (ensure_utc(self.clock.now()).timestamp(), status)
        return status

    def _measure(self, month: str) -> EgressStatus:
        if self.platform != "linux":
            return self._over(month, "unsupported platform; Linux only")
        try:
            iface = default_interface(_bounded(self.proc / "net" / "route"))
            reading = tx_bytes(_bounded(self.proc / "net" / "dev"), iface)
        except (OSError, UnicodeError, DataIntegrityError):
            return self._over(month, "kernel interface counters unreadable")
        try:
            previous = _read_state(self.state_path, month)
        except FileNotFoundError:
            previous = None
        except (OSError, UnicodeError, ValueError, DataIntegrityError):
            return self._over(month, "counter file corrupt or unreadable; operator review")
        if previous is None:
            used = reading
        else:
            same = previous.iface == iface and reading >= previous.last
            delta = reading - previous.last if same else reading
            used = delta if previous.month != month else previous.used + delta
        try:
            _write_state(self.state_path, _Counter(month, iface, reading, used))
        except OSError:
            return self._over(month, "counter file cannot be written")
        if previous is None:
            return self._over(month, "counter missing; initialized from the kernel total")
        if used * 100 >= self.budget * BLOCK_PERCENT:
            level = EgressLevel.BLOCKED
        elif used * 100 >= self.budget * PAUSE_PERCENT:
            level = EgressLevel.PAUSED
        else:
            level = EgressLevel.OK
        return EgressStatus(level, month, used, self.budget, "measured")

    def status(self) -> EgressStatus:
        now = ensure_utc(self.clock.now()).timestamp()
        if self._cached is not None and now - self._cached[0] < self.max_age_seconds:
            return self._cached[1]
        return self.sample()

    def _level(self) -> EgressLevel:
        try:
            return self.status().level
        except Exception:
            return EgressLevel.BLOCKED

    def allows(self, purpose: str) -> bool:
        """EGR-03/05: essential purposes always pass; others only below 80%."""
        return purpose in ESSENTIAL_PURPOSES or self._level() == EgressLevel.OK

    def entries_blocked(self) -> bool:
        """EGR-04: new entries stop at 95% or an unreadable counter."""
        return self._level() == EgressLevel.BLOCKED

    def status_line(self) -> str | None:
        """EGR: /status line while the budget is paused, blocked or unreadable."""
        status = self.status()
        return None if status.level == EgressLevel.OK else status.message()

    async def alert(self, notify: Notify) -> bool:
        """EGR: one owner alert per month and level; failed deliveries retry."""
        status = self.status()
        pending: list[tuple[tuple[str, ...], str]] = []
        if self.refusal is not None:
            pending.append((("config",), self.refusal))
        if status.level != EgressLevel.OK:
            kind = "counter" if status.used is None else "measured"
            pending.append(((status.month, status.level.value, kind), status.message()))
        delivered = False
        for episode, message in pending:
            if episode in self._alerted:
                continue
            try:
                await notify(message)
            except Exception:
                # Not marked as sent: the next sample retries this episode.
                retry = True
            else:
                retry = False
            if not retry:
                self._alerted.add(episode)
                delivered = True
        return delivered
