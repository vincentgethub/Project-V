"""S1 composition around the unchanged, independently testable G-a resolver."""

import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from backend.execution.intent_resolution import IntentRefusal
from backend.execution.models import IntentDryRun
from backend.ops.quiescence import BrokerCoordination, QuiescenceError


@dataclass
class CoordinationWindow:
    coordination: BrokerCoordination
    strict: bool
    verified: bool = False
    acquired: bool = False

    def require(self) -> None:
        if self.strict and not self.verified:
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")

    def check(self) -> None:
        if self.verified:
            try:
                self.coordination.check()
            except (OSError, QuiescenceError):
                self.verified = False
        self.require()


class CoordinatedResolver:
    def __init__(self, coordination: BrokerCoordination) -> None:
        self.coordination = coordination

    async def run(
        self, operation: Callable[[], Awaitable[IntentDryRun]], *, strict: bool = False
    ) -> IntentDryRun:
        with self.window(strict=strict) as proof:
            value = await operation()
        return value.model_copy(update={"quiescence_verified": proof.verified})

    @contextmanager
    def window(self, *, strict: bool) -> Iterator[CoordinationWindow]:
        proof = CoordinationWindow(self.coordination, strict)
        try:
            self.coordination.acquire_proof()
        except (OSError, QuiescenceError):
            proof.verified = False
        else:
            proof.acquired = proof.verified = True
        try:
            proof.require()
            yield proof
        finally:
            primary = sys.exception()
            try:
                if primary is None:
                    proof.check()
            finally:
                if proof.acquired:
                    try:
                        self.coordination.release_proof()
                    except (OSError, QuiescenceError) as error:
                        proof.verified = False
                        if primary is not None:
                            primary.add_note("Broker proof cleanup failed: " + type(error).__name__)
                        else:
                            proof.require()
