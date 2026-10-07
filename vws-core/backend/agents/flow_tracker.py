"""GD-03: bounded public flow context, unavailable by default."""

import asyncio
from datetime import datetime

from backend.agents.providers import FlowProvider, NullFlowProvider
from backend.core.clock import ensure_utc
from backend.core.content import injection_suspect, sanitize_text
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    EgressDeniedError,
    ProviderError,
)
from backend.domain.models import FlowSignal, ProviderStatus, validate_symbol


class FlowTracker:
    def __init__(self, provider: FlowProvider | None = None, *, timeout_seconds: int = 30) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30:
            raise ConfigurationError("GD-03: flow deadline must be 1 through 30 seconds")
        self.provider = provider or NullFlowProvider()
        self.timeout_seconds = timeout_seconds

    async def read(self, symbol: str, as_of: datetime) -> FlowSignal:
        validate_symbol(symbol)
        instant = ensure_utc(as_of)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = FlowSignal.model_validate(await self.provider.get(symbol, instant))
            if result.summary is not None and (
                result.summary != sanitize_text(result.summary)
                or injection_suspect(result.summary, frozenset())
            ):
                raise DataIntegrityError("GD-03: flow context contains unsafe public text")
            if any(
                len(value) > 100
                or any(not (char.isascii() and (char.isalnum() or char in "_-")) for char in value)
                for value in result.evidence_ids
            ):
                raise DataIntegrityError("GD-03: flow evidence identifiers are invalid")
            return result
        except EgressDeniedError:
            raise
        except (TimeoutError, ProviderError):
            return FlowSignal(status=ProviderStatus.UNAVAILABLE)
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError("GD-03: flow evidence could not be validated") from None
