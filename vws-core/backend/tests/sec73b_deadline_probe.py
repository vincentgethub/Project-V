"""SEC-73b diagnostics: log loop.time at test entry, first _read_bound, and deadline.

External pytest plugin. It does not monkeypatch loop.time, change assertions,
budgets, timeouts, or production code. Activated only for the two production
panic-read tests that failed in CI run 44306742137. Lines start with
SEC73B_PROBE so they can be grepped from hosted job logs.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.core.database import ExecutionOrderRecord
from backend.execution.alpaca_executor import AlpacaExecutor
from backend.execution.models import BrokerOrder

_TARGETS = frozenset(
    {
        "test_SEC_73_production_timeout_cuts_off_a_read_that_never_returns",
        "test_SEC_73_production_deadline_abandons_a_blocked_broker_read",
    }
)

_original_init: Callable[..., None] | None = None
_original_read_bound: Callable[..., Awaitable[BrokerOrder | None]] | None = None
_patch: pytest.MonkeyPatch | None = None
_read_seq = 0
_timeout_seq = 0
_last_deadline: float | None = None
_nodeid = ""
_log_path: Path | None = None


def _is_target(item: pytest.Item) -> bool:
    original = getattr(item, "originalname", item.name)
    return original.split("[")[0] in _TARGETS or item.name.split("[")[0] in _TARGETS


def _probe_log_path() -> Path | None:
    explicit = os.environ.get("VWS_SEC73B_PROBE_LOG", "").strip()
    if explicit:
        return Path(explicit)
    audit = os.environ.get("VWS_MUTATION_AUDIT_DIR", "").strip()
    if audit:
        return Path(audit) / "sec73b-probe.jsonl"
    return None


def _emit(event: str, **fields: object) -> None:
    payload: dict[str, object] = {
        "event": event,
        "nodeid": _nodeid,
        "ts": datetime.now(UTC).isoformat(),
        "mono": time.monotonic(),
        "wall": time.time(),
    }
    try:
        payload["loop_time"] = asyncio.get_running_loop().time()
    except RuntimeError:
        payload["loop_time"] = None
    if _last_deadline is not None:
        payload["deadline"] = _last_deadline
        loop_time = payload["loop_time"]
        if isinstance(loop_time, float):
            payload["remaining"] = _last_deadline - loop_time
    payload.update(fields)
    line = "SEC73B_PROBE " + json.dumps(payload, default=str, separators=(",", ":"))
    stream = getattr(sys, "__stderr__", None) or sys.stderr
    stream.write(line + "\n")
    stream.flush()
    if _log_path is not None:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        with _log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _install() -> None:
    global _original_init, _original_read_bound, _read_seq, _timeout_seq, _last_deadline
    if _original_init is not None:
        return
    _read_seq = 0
    _timeout_seq = 0
    _last_deadline = None
    _original_init = AlpacaExecutor.__init__
    _original_read_bound = AlpacaExecutor._read_bound

    def probed_init(self: AlpacaExecutor, *args: object, **kwargs: object) -> None:
        assert _original_init is not None
        saved_init: Callable[..., None] = _original_init
        saved_init(self, *args, **kwargs)
        # pytest_runtest_setup runs before the asyncio loop exists; this is the
        # first loop.time() once the test is inside the running loop.
        _emit("test_entry_loop")
        inner = self._panic_timeout

        @asynccontextmanager
        async def probed_timeout(deadline: float) -> AsyncIterator[object]:
            global _timeout_seq, _last_deadline
            _timeout_seq += 1
            _last_deadline = deadline
            loop_time = asyncio.get_running_loop().time()
            _emit(
                "timeout_enter",
                timeout_seq=_timeout_seq,
                deadline=deadline,
                already_expired=loop_time >= deadline,
            )
            try:
                async with inner(deadline) as value:
                    yield value
            except TimeoutError:
                _emit(
                    "deadline_fired",
                    timeout_seq=_timeout_seq,
                    deadline=deadline,
                )
                raise
            else:
                _emit("timeout_exit", timeout_seq=_timeout_seq, deadline=deadline)

        self._panic_timeout = probed_timeout

    async def probed_read_bound(
        self: AlpacaExecutor, instruction: ExecutionOrderRecord
    ) -> BrokerOrder | None:
        global _read_seq
        assert _original_read_bound is not None
        saved_read: Callable[..., Awaitable[BrokerOrder | None]] = _original_read_bound
        _read_seq += 1
        first = _read_seq == 1
        _emit(
            "first_read_bound_enter" if first else "read_bound_enter",
            read_seq=_read_seq,
            instruction_id=str(instruction.id),
        )
        try:
            return await saved_read(self, instruction)
        finally:
            _emit(
                "first_read_bound_exit" if first else "read_bound_exit",
                read_seq=_read_seq,
                instruction_id=str(getattr(instruction, "id", "?")),
            )

    global _patch
    _patch = pytest.MonkeyPatch()
    _patch.setattr(AlpacaExecutor, "__init__", probed_init)
    _patch.setattr(AlpacaExecutor, "_read_bound", probed_read_bound)


def _uninstall() -> None:
    global _original_init, _original_read_bound, _last_deadline, _patch
    if _patch is not None:
        _patch.undo()
        _patch = None
    _original_init = None
    _original_read_bound = None
    _last_deadline = None


def pytest_runtest_setup(item: pytest.Item) -> None:
    global _nodeid, _log_path
    if not _is_target(item):
        return
    _nodeid = item.nodeid
    _log_path = _probe_log_path()
    _install()
    _emit("test_entry", name=item.name)


def pytest_runtest_teardown(item: pytest.Item) -> None:
    global _nodeid
    if not _is_target(item):
        return
    try:
        _emit("test_exit", name=item.name)
    finally:
        _uninstall()
        _nodeid = ""
