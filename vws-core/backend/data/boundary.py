"""R-02/R-08/CMP-06/CRO-12/DAT-01: durable safety around read-only providers.

Market-data validation and its HALTs live in DataLayer. This companion boundary
binds account identity, current flags, exact funding policy and injected time.
Reading data never authorizes a trade; later CRO/compliance/human gates remain
required. A halted system can still read holdings needed for a manual held exit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal, localcontext
from typing import Protocol, TypeVar

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError, StaleDataError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.broker_state import BrokerStateProvider
from backend.data.liquidity import LiquidityGate, validated_liquidity_settings
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import AccountFlags, DeployableCapital, FrozenModel, PortfolioSnapshot
from backend.risk.portfolio_marks import PersistedPortfolioMarks

ReadT = TypeVar("ReadT")


class AsyncReadExecutor(Protocol):
    """DAT-08: share the bounded worker admission boundary across read providers."""

    async def run(self, operation: Callable[[], ReadT], *, budget_request: bool = False) -> ReadT:
        """DAT-08: admit a worker, discard late results and retain its slot until completion."""
        raise NotImplementedError("async read executor must supply run")

    def bind_policy(self, settings: Settings, ledger: Ledger) -> None:
        """DAT-06/R-06: share only the same bound account policy and ledger."""
        raise NotImplementedError("async read executor must supply bind_policy")

    def ensure_active(self) -> None:
        """DAT-08: refuse publication by an expired admitted worker."""
        raise NotImplementedError("async read executor must supply ensure_active")


class BrokerReading(FrozenModel):
    """CMP-06/R-02: account balances and restriction flags travel together."""

    snapshot: PortfolioSnapshot
    flags: AccountFlags


class ReadBoundary:
    """R-02/R-08: faults persist HALTED and notify; unavailable funding stays zero."""

    def __init__(
        self,
        config: Settings,
        state: SystemStateStore,
        clock: Clock,
        broker: BrokerStateProvider,
        liquidity: LiquidityGate,
        *,
        account_id: str,
        marks: PersistedPortfolioMarks | None = None,
    ) -> None:
        """R-02: pin the operator's managed account rather than accepting any ID."""
        if (
            not isinstance(account_id, str)
            or not account_id.strip()
            or account_id != account_id.strip()
        ):
            raise ConfigurationError("R-02: a pinned managed account ID is required")
        self.config = validated_liquidity_settings(config)
        self.state = state
        self.clock = clock
        self.broker = broker
        self.liquidity = liquidity
        self.account_id = account_id
        self.marks = (
            PersistedPortfolioMarks(state.ledger, account_id, MarketCalendar(), self.config)
            if marks is None
            else marks
        )
        if (
            not isinstance(self.marks, PersistedPortfolioMarks)
            or self.marks.ledger.engine is not state.engine
            or self.marks.account_id != account_id
            or self.marks.config.config_hash != self.config.config_hash
        ):
            raise ConfigurationError("CRO-09/CRO-10: broker marks differ from account policy")

    def _fail(self, error: Exception) -> None:
        """R-02/R-07: static fault audit and typed failure even if storage is down."""
        try:
            logging.getLogger(__name__).error(
                "read_boundary_fault error_type=%s", type(error).__name__
            )
        except Exception as audit_error:
            error = DataIntegrityError(
                f"R-02: read fault audit failed ({type(audit_error).__name__})"
            )
        try:
            self.state.halt_for_error(error)
        except Exception as halt_error:
            raise DataIntegrityError(
                "R-02: read failed; HALT persistence unavailable"
            ) from halt_error

    def portfolio(self) -> BrokerReading:
        """CMP-06/DAT-01: synchronous read boundary for host commands and tests."""
        return self._portfolio()

    def _portfolio(self, active: Callable[[], None] | None = None) -> BrokerReading:
        """CMP-06/DAT-01/DAT-02: fresh, bound account reads or a durable HALT.

        Freshness uses wall-clock age even off-hours because account holdings can
        change independently of the exchange session. Quote freshness alone is
        anchored to the last completed close by DAT-01. A valid restricted
        account reading is returned after latching its restriction for manual
        exit analysis; it never authorizes a new entry.
        """
        try:
            started = ensure_utc(self.clock.now())
            self.state.ledger.verify_chain()
            if active is not None:
                active()
            snapshot = PortfolioSnapshot.model_validate(self.broker.snapshot(started))
            flags = AccountFlags.model_validate(self.broker.last_flags)
            finished = ensure_utc(self.clock.now())
            if finished < started or snapshot.as_of != started:
                raise DataIntegrityError("DAT-02: broker snapshot time is not bound to this read")
            if finished - started > timedelta(seconds=self.config.stale_quote_seconds):
                raise StaleDataError("DAT-01: broker read took longer than the freshness budget")
            if (
                snapshot.account_id != self.account_id
                or snapshot.account_type != self.config.broker_account_type
            ):
                raise DataIntegrityError(
                    "R-02: broker snapshot account identity differs from policy"
                )
            if active is not None:
                active()
            snapshot = self.marks.observe(snapshot)
            reading = BrokerReading(snapshot=snapshot, flags=flags)
            if flags.blocked:
                self.state.escalate(SystemState.HALTED, "CMP-06 broker account restricted")
            self.state.apply_financial_limits(
                snapshot.equity, snapshot.high_water_mark, snapshot.day_start_equity, self.config
            )
            return reading
        except Exception as exc:
            self._fail(exc)
            if isinstance(exc, DataIntegrityError):
                raise
            raise DataIntegrityError("R-02: broker read failed and latched HALTED") from exc

    def funding(self, *, refresh: bool = False) -> DeployableCapital:
        """CRO-12/R-02: exact configured advisory funding or fault HALT.

        Expected UNAVAILABLE/STALE/BUFFER_BREACH readings have zero deployable
        capacity and veto entries downstream. Unexpected bank, clock, parsing,
        audit and database errors escalate HALTED here.
        """
        try:
            ensure_utc(self.clock.now())
            self.state.ledger.verify_chain()
            result = DeployableCapital.model_validate(self.liquidity.evaluate(refresh=refresh))
            with localcontext() as context:
                context.prec = 80
                reserved = sum(self.config.reserved_obligations_usd, Decimal(0))
            if result.buffer != self.config.checking_buffer_usd or result.reserved != reserved:
                raise DataIntegrityError("CRO-12: funding result differs from configured policy")
            return result
        except Exception as exc:
            self._fail(exc)
            if isinstance(exc, DataIntegrityError):
                raise
            raise DataIntegrityError("R-02: funding read failed and latched HALTED") from exc

    async def portfolio_async(self, reader: AsyncReadExecutor) -> BrokerReading:
        """DAT-08: account SDK calls and database checks leave the event loop free."""
        reader.bind_policy(self.config, self.state.ledger)
        return await reader.run(lambda: self._portfolio(reader.ensure_active))

    async def funding_async(
        self, reader: AsyncReadExecutor, *, refresh: bool = False
    ) -> DeployableCapital:
        """DAT-08: bank SDK calls share bounded workers and discard late results."""
        reader.bind_policy(self.config, self.state.ledger)
        return await reader.run(lambda: self.funding(refresh=refresh))
