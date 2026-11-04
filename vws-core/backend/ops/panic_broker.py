"""Panic-only async adapters; the actor's admission is the single choke point."""

import httpx

from backend.core.errors import ConfigurationError
from backend.data.broker_read_client import BrokerReadClient
from backend.ops.quiescence import BrokerActor, current_actor
from backend.ops.read_checks import ReadChecksClient


class PanicReadChecksClient(ReadChecksClient):
    async def _get(
        self,
        purpose: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> object:
        actor = current_actor()
        if actor is None:
            raise ConfigurationError("Panic broker read requires an actor scope")

        async def operation() -> object:
            return await super(PanicReadChecksClient, self)._get(
                purpose,
                url,
                headers=headers,
                params=params,
            )

        return await actor.async_call(operation)


class PanicReadClient:
    def __init__(self, client: BrokerReadClient, actor: BrokerActor) -> None:
        self.client, self.actor = client, actor

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.actor.async_call(
            lambda: self.client.get(url, headers=headers, params=params)
        )

    async def aclose(self) -> None:
        await self.client.aclose()
