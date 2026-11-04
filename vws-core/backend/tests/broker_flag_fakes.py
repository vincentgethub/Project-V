"""Explicit shared flag fake for new coordination tests."""

from backend.ops.panic_flag import PanicFlagError


class FakeFlagHandle:
    def __init__(self, adapter: "FakeFlagAdapter") -> None:
        self.adapter = adapter

    def signaled(self) -> bool:
        self.adapter.reads += 1
        if self.adapter.fail_at == "read-start" or (
            self.adapter.fail_at == "read-end" and self.adapter.reads > 1
        ):
            raise PanicFlagError("Panic flag read failed")
        return self.adapter.signaled

    def close(self) -> None:
        self.adapter.windows -= 1
        if self.adapter.fail_at == "close":
            raise PanicFlagError("Panic flag close failed")


class FakeFlagAdapter:
    def __init__(self) -> None:
        self.windows = 0
        self.reads = 0
        self.signaled = False
        self.retained = False
        self.fail_at: str | None = None
        self.signals = 0
        self.waits = 0
        self.trace: list[str] = []

    def open_window(self) -> FakeFlagHandle:
        if self.fail_at == "open":
            raise PanicFlagError("Panic flag open failed")
        self.windows += 1
        return FakeFlagHandle(self)

    def signal_if_present(self) -> bool:
        self.signals += 1
        self.trace.append("flag")
        if self.fail_at == "signal":
            raise PanicFlagError("Panic flag signal failed")
        self.retained = self.signaled = True
        return True
