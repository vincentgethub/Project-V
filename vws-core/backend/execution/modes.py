"""AX-01/02/30: persisted downgrades, host-only resume, no SDK imports."""

import asyncio
from typing import Literal
from weakref import WeakKeyDictionary

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import MANUAL_CSV_DISABLED_MESSAGE, Settings
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError, ExecutionDisabledError
from backend.core.system_state import SystemState, SystemStateStore
from backend.execution.models import Environment, ExecutionMode, ModeOverride
from backend.security.secrets import SecretStore

_RANK = {"MANUAL": 0, "AUTO_PAPER": 1, "AUTO_LIVE": 2}
_ACCOUNT_LOCKS: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[str, str], asyncio.Lock]
] = WeakKeyDictionary()


def account_lock(account_id: str, environment: str) -> asyncio.Lock:
    """AX-25: all executor instances share one lock for this account and cohort."""
    locks = _ACCOUNT_LOCKS.setdefault(asyncio.get_running_loop(), {})
    return locks.setdefault((account_id, environment), asyncio.Lock())


def assert_auto_binding(settings: Settings, store: SecretStore) -> None:
    """AX-15: verify separately named native key pairs without exposing values."""
    settings = Settings.validated_copy(settings)
    if settings.broker_state_source != "ALPACA":
        raise ConfigurationError(MANUAL_CSV_DISABLED_MESSAGE)
    if settings.execution_mode == "MANUAL":
        return
    paper = settings.execution_mode == "AUTO_PAPER"
    if settings.paper_trading != paper:
        raise ConfigurationError("Execution mode and PAPER_TRADING disagree")
    selected = "ALPACA_PAPER_" if paper else "ALPACA_LIVE_"
    opposite = "ALPACA_LIVE_" if paper else "ALPACA_PAPER_"
    if any(
        value is not None and value.get_secret_value().strip()
        for value in (store.get(opposite + "KEY_ID"), store.get(opposite + "SECRET"))
    ):
        raise ConfigurationError("AUTO mode refuses an opposite-environment Alpaca key")
    key, secret = store.get(selected + "KEY_ID"), store.get(selected + "SECRET")
    if (
        key is None
        or secret is None
        or not key.get_secret_value().strip()
        or not secret.get_secret_value().strip()
        or key != settings.broker_api_key
        or secret != settings.broker_secret_key
    ):
        raise ConfigurationError("AUTO mode requires the matching Alpaca keyring pair")
    if not paper and (
        not settings.live_trading_enabled
        or settings.live_trading_confirm != "I_ACCEPT_REAL_MONEY_RISK"
    ):
        raise ConfigurationError("AUTO_LIVE requires the complete R-06 triple gate")


class ModeStore:
    def __init__(self, settings: Settings, state: SystemStateStore, account_id: str) -> None:
        self.settings = Settings.validated_copy(settings)
        if not account_id or len(account_id) > 128:
            raise ConfigurationError("Mode store requires a bounded account identity")
        self.state, self.account_id = state, account_id
        self.environment: Environment = "PAPER" if settings.paper_trading else "LIVE"

    def _latest(self, session: Session) -> ModeOverride | None:
        if self.settings.execution_mode == "AUTO_LIVE":
            live = session.scalar(
                select(SecurityEvent)
                .where(SecurityEvent.kind.in_(("LIVE_DISABLED", "LIVE_ENABLED")))
                .order_by(SecurityEvent.seq.desc())
                .limit(1)
            )
            if live is not None and live.kind == "LIVE_DISABLED":
                # A local emergency disable applies to every live account, even
                # when the caller cannot retrieve credentials or broker state.
                return ModeOverride(
                    account_id=self.account_id,
                    environment=self.environment,
                    mode="MANUAL",
                    paused=True,
                    action="DISABLE_LIVE",
                    actor=live.detail["operator"],
                    config_hash=self.settings.config_hash,
                )
        rows = session.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.kind == "EXECUTION_MODE_OVERRIDE")
            .order_by(SecurityEvent.seq.desc())
        )
        for row in rows:
            checked = ModeOverride.model_validate(row.detail)
            if checked.account_id == self.account_id and checked.environment == self.environment:
                return checked
        return None

    def _read(self) -> ModeOverride | None:
        try:
            self.state.ledger.verify_chain()
            with Session(self.state.engine) as session:
                return self._latest(session)
        except Exception as error:
            self.state.halt_for_error(error)
            raise DataIntegrityError("Persisted execution mode cannot be verified") from None

    @property
    def effective(self) -> ExecutionMode:
        override = self._read()
        configured = self.settings.execution_mode
        if override is None:
            return configured
        return override.mode if _RANK[override.mode] <= _RANK[configured] else configured

    def in_session(self, session: Session) -> tuple[ExecutionMode, bool]:
        """AX-02: inspect an override inside the caller's serialized transaction."""
        override = self._latest(session)
        configured = self.settings.execution_mode
        mode = (
            configured
            if override is None or _RANK[override.mode] > _RANK[configured]
            else override.mode
        )
        return mode, (override is not None and override.paused) or self._drift_paused(session)

    @staticmethod
    def _drift_paused(session: Session) -> bool:
        """SEC-43: entry admission shares the durable host acknowledgement gate."""
        accepted = session.scalar(
            select(SecurityEvent.seq)
            .where(SecurityEvent.kind.in_(("CONFIG_APPLIED", "CONFIG_ACKNOWLEDGED")))
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
        return (
            session.scalar(
                select(SecurityEvent.seq)
                .where(
                    SecurityEvent.kind == "CONFIG_DRIFT_PAUSED",
                    SecurityEvent.seq > (accepted or 0),
                )
                .limit(1)
            )
            is not None
        )

    @property
    def entries_enabled(self) -> bool:
        override = self._read()
        with Session(self.state.engine) as session:
            drift_paused = self._drift_paused(session)
        return (
            self.effective != "MANUAL"
            and (override is None or not override.paused)
            and self.state.current() == SystemState.RUNNING
            and not drift_paused
        )

    def downgrade(
        self,
        action: Literal["MANUAL", "PAUSE", "HALT", "DISABLE_LIVE"],
        *,
        actor: str,
    ) -> None:
        try:
            with transaction(self.state.engine) as session:
                previous = self._latest(session)
                mode = self.settings.execution_mode if previous is None else previous.mode
                if _RANK[mode] > _RANK[self.settings.execution_mode]:
                    mode = self.settings.execution_mode
                checked = ModeOverride(
                    account_id=self.account_id,
                    environment=self.environment,
                    mode=mode if action == "PAUSE" else "MANUAL",
                    paused=True,
                    action=action,
                    actor=actor,
                    config_hash=self.settings.config_hash,
                )
                self.state.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="EXECUTION_MODE_OVERRIDE",
                    detail=checked.model_dump(mode="json"),
                )
            if action == "HALT":
                self.state.escalate(SystemState.HALTED, "Automatic entries halted by operator")
        except Exception as error:
            self.state.halt_for_error(error)
            raise DataIntegrityError("Execution downgrade could not be durably saved") from None

    def resume(self, *, operator: str, phrase: str) -> None:
        if phrase != "RESUME" or not operator.strip() or len(operator) > 128:
            raise ConfigurationError("Host resume requires an operator and exact RESUME phrase")
        if self.settings.execution_mode == "MANUAL":
            raise ExecutionDisabledError("Configured MANUAL cannot be upgraded by resume-auto")
        if self.state.current() != SystemState.RUNNING:
            raise ExecutionDisabledError("Audited host reset is required before resuming entries")
        checked = ModeOverride(
            account_id=self.account_id,
            environment=self.environment,
            mode=self.settings.execution_mode,
            paused=False,
            action="RESUME",
            actor=operator,
            config_hash=self.settings.config_hash,
        )
        self.state.ledger.append(
            SecurityEvent,
            kind="EXECUTION_MODE_OVERRIDE",
            detail=checked.model_dump(mode="json"),
        )
