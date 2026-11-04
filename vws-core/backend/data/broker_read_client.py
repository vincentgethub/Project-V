"""Minimal read-only client contract; implementations retain the guarded factory."""

from typing import Protocol

import httpx


class BrokerReadClient(Protocol):
    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response: ...

    async def aclose(self) -> None: ...
