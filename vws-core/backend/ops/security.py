"""SEC-01/SEC-43/SEC-72/SEC-73: local attestations, drift and panic controls."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.domain.models import FrozenModel, UTCDateTime

ACCOUNT_ITEMS = (
    "ALPACA_MFA",
    "RECOVERY_EMAIL_2FA",
    "TELEGRAM_2STEP",
    "PHONE_PASSCODE",
    "GITHUB_PRIVATE_2FA",
    "CARRIER_PORT_PIN",
    "PASSWORD_MANAGER",
    "PLAID_2FA",
    "ALPACA_EMAIL_NOTICES",
    "ALPACA_CRYPTO_DISABLED",
)
REVOKE_CHECKLIST = (
    "Alpaca dashboard > API Keys > Regenerate the affected key pair.",
    "Telegram BotFather: /revoke, then rotate TELEGRAM_BOT_TOKEN.",
    "Rotate the Plaid secret or remove the affected item.",
    "Revoke affected GitHub tokens; secure the recovery email and password.",
    "Run vws ops rotate-secret for each affected credential, then doctor.",
    "Check withdrawals and unknown orders in the broker dashboard.",
)


def _hash(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise DataIntegrityError("SEC-43: a complete hexadecimal fingerprint is required")
    return value


def _operator(value: str) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9 ._-]{1,128}", value) is None
        or not value.strip()
    ):
        raise DataIntegrityError("SEC-01: a local operator name is required")
    return value.strip()


def effective_config_hash(settings: Settings, files: Mapping[str, Path]) -> str:
    """SEC-43/RT/LP: bind nonsecret settings and exact supplied policy bytes.

    Not-yet-created optional macro/accounts files contribute an explicit missing
    marker. Required config/instruments files may never be silently absent.
    Only file hashes are retained; file contents never enter security events.
    """
    try:
        legacy = {"config.yaml", "instruments.csv", "macro_events.csv", "accounts.yaml"}
        current = legacy | {"events_policy.yaml", "fees.yaml", "variants.yaml"}
        expected = set(files)
        if expected not in (legacy, current):
            raise ValueError("effective config file inventory differs")
        payload = settings.model_dump()
        if (
            "telegram_allowed_user_ids" not in settings.model_fields_set
            and not settings.telegram_allowed_user_ids
        ):
            payload.pop("telegram_allowed_user_ids")
        validated = Settings.model_validate(payload)
        snapshot = validated.nonsecret_snapshot()
        hashes: dict[str, str] = {}
        for name in sorted(expected):
            path = files[name]
            if not path.exists() and name in {"macro_events.csv", "accounts.yaml"}:
                hashes[name] = "MISSING"
            else:
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or path.stat().st_size > 10 * 1024 * 1024
                ):
                    raise ValueError("policy file is unavailable or oversized")
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        encoded = json.dumps(
            {"settings": snapshot, "files": hashes}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    except Exception:
        raise DataIntegrityError(
            "SEC-43: effective configuration could not be fingerprinted"
        ) from None


class DriftResult(FrozenModel):
    """SEC-43: drift annotates MANUAL and persistently pauses AUTO entries."""

    current_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_hash: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    changed: bool = Field(strict=True)
    entries_paused: bool = Field(strict=True)
    newly_detected: bool = Field(strict=True)


class ConfigDriftGuard:
    """SEC-43: apply/ack are host-only service APIs, never Telegram upgrades."""

    def __init__(
        self, ledger: Ledger, clock: Clock, notify: Callable[[str], None] | None = None
    ) -> None:
        self.ledger = ledger
        self.clock = clock
        self.notify = notify

    def _events(self, session: Session) -> tuple[SecurityEvent, ...]:
        return tuple(
            session.scalars(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind.in_(
                        (
                            "CONFIG_APPLIED",
                            "CONFIG_ACKNOWLEDGED",
                            "CONFIG_DRIFT",
                            "CONFIG_DRIFT_PAUSED",
                        )
                    )
                )
                .order_by(SecurityEvent.seq)
            )
        )

    def _accept(self, current_hash: str, operator: str, kind: str) -> None:
        try:
            self.ledger.verify_chain()
            self.ledger.append(
                SecurityEvent,
                kind=kind,
                telegram_user_id=None,
                detail={"config_hash": _hash(current_hash), "operator": _operator(operator)},
                ts=ensure_utc(self.clock.now()),
            )
        except Exception:
            raise DataIntegrityError("SEC-43: configuration acknowledgement failed") from None

    def apply(self, current_hash: str, operator: str) -> None:
        self._accept(current_hash, operator, "CONFIG_APPLIED")

    def ack(self, current_hash: str, operator: str) -> None:
        self._accept(current_hash, operator, "CONFIG_ACKNOWLEDGED")

    def entries_paused(self) -> bool:
        try:
            self.ledger.verify_chain()
            with transaction(self.ledger.engine) as session:
                events = self._events(session)
                accepted = max(
                    (
                        event.seq
                        for event in events
                        if event.kind in {"CONFIG_APPLIED", "CONFIG_ACKNOWLEDGED"}
                    ),
                    default=0,
                )
                return any(
                    event.kind == "CONFIG_DRIFT_PAUSED" and event.seq > accepted for event in events
                )
        except Exception:
            raise DataIntegrityError("SEC-43: entry-pause evidence unavailable") from None

    def check(self, current_hash: str, mode: str = "MANUAL") -> DriftResult:
        try:
            current_hash = _hash(current_hash)
            if mode not in {"MANUAL", "AUTO_PAPER", "AUTO_LIVE"}:
                raise ValueError("mode must be a known label")
            auto = mode in {"AUTO_PAPER", "AUTO_LIVE"}
            self.ledger.verify_chain()
            with transaction(self.ledger.engine) as session:
                events = self._events(session)
                accepted = tuple(
                    event
                    for event in events
                    if event.kind in {"CONFIG_APPLIED", "CONFIG_ACKNOWLEDGED"}
                )
                baseline = accepted[-1] if accepted else None
                baseline_hash = None if baseline is None else _hash(baseline.detail["config_hash"])
                baseline_seq = 0 if baseline is None else baseline.seq
                changed = current_hash != baseline_hash
                paused = any(
                    event.kind == "CONFIG_DRIFT_PAUSED" and event.seq > baseline_seq
                    for event in events
                )
                seen = any(
                    event.kind == "CONFIG_DRIFT"
                    and event.seq > baseline_seq
                    and event.detail.get("config_hash") == current_hash
                    for event in events
                )
                newly_detected = changed and not seen
                if newly_detected:
                    self.ledger.append_in_session(
                        session,
                        SecurityEvent,
                        kind="CONFIG_DRIFT",
                        telegram_user_id=None,
                        detail={"config_hash": current_hash, "baseline_hash": baseline_hash},
                        ts=ensure_utc(self.clock.now()),
                    )
                if changed and auto and not paused:
                    self.ledger.append_in_session(
                        session,
                        SecurityEvent,
                        kind="CONFIG_DRIFT_PAUSED",
                        telegram_user_id=None,
                        detail={"config_hash": current_hash},
                        ts=ensure_utc(self.clock.now()),
                    )
                    paused = True
            if newly_detected and self.notify is not None:
                self.notify(
                    "Urgent: effective configuration changed without a host acknowledgement."
                )
            return DriftResult(
                current_hash=current_hash,
                baseline_hash=baseline_hash,
                changed=changed,
                entries_paused=paused,
                newly_detected=newly_detected,
            )
        except Exception:
            raise DataIntegrityError("SEC-43: configuration drift verification failed") from None


class AccountAttestation(FrozenModel):
    """SEC-01: owner-attested evidence never claims remote verification."""

    item: str
    status: Literal["ATTESTED", "WARN"]
    recorded_at: UTCDateTime | None


class PanicResult(FrozenModel):
    """SEC-73: local halt survives callback failures and the checklist is usable offline."""

    state: SystemState
    failed_steps: tuple[str, ...]
    recent_activity: tuple[str, ...]
    revoke_checklist: tuple[str, ...]


class SecurityOps:
    """SEC-01/SEC-72/SEC-73: explicit host actions over the immutable ledger."""

    def __init__(
        self,
        ledger: Ledger,
        state: SystemStateStore,
        clock: Clock,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self.ledger = ledger
        self.state = state
        self.clock = clock
        self.notify = notify
        if ledger.engine is not state.engine:
            raise DataIntegrityError("SEC-73: security operations require the active local ledger")

    def attest(self, item: str, operator: str) -> AccountAttestation:
        try:
            if item not in ACCOUNT_ITEMS:
                raise ValueError("unknown account security item")
            instant = ensure_utc(self.clock.now())
            self.ledger.append(
                SecurityEvent,
                kind="ACCOUNT_ATTESTED",
                telegram_user_id=None,
                detail={"item": item, "operator": _operator(operator)},
                ts=instant,
            )
            return AccountAttestation(item=item, status="ATTESTED", recorded_at=instant)
        except Exception:
            raise DataIntegrityError("SEC-01: account attestation could not be recorded") from None

    def attestations(self) -> tuple[AccountAttestation, ...]:
        try:
            self.ledger.verify_chain()
            with transaction(self.ledger.engine) as session:
                events = session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "ACCOUNT_ATTESTED")
                    .order_by(SecurityEvent.seq)
                )
                latest = {
                    event.detail["item"]: event.ts
                    for event in events
                    if event.detail.get("item") in ACCOUNT_ITEMS
                }
            return tuple(
                AccountAttestation(
                    item=item,
                    status="ATTESTED" if item in latest else "WARN",
                    recorded_at=latest.get(item),
                )
                for item in ACCOUNT_ITEMS
            )
        except Exception:
            raise DataIntegrityError("SEC-01: account attestations could not be read") from None

    def counts(self, since: datetime) -> dict[str, int]:
        try:
            instant = ensure_utc(since)
            now = ensure_utc(self.clock.now())
            if instant > now:
                raise ValueError("future report window")
            self.ledger.verify_chain()
            with transaction(self.ledger.engine) as session:
                events = session.scalars(
                    select(SecurityEvent).where(
                        SecurityEvent.ts >= instant, SecurityEvent.ts <= now
                    )
                )
                result: dict[str, int] = {}
                for event in events:
                    result[event.kind] = result.get(event.kind, 0) + 1
                return result
        except Exception:
            raise DataIntegrityError("SEC-72: security event counts could not be read") from None

    def observe_identity(self, name: str, fingerprint: str) -> bool:
        """SEC-72: unexplained key/account identity drift halts entries."""
        try:
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", name) is None:
                raise ValueError("identity label invalid")
            fingerprint = _hash(fingerprint)
            self.ledger.verify_chain()
            with transaction(self.ledger.engine) as session:
                events = tuple(
                    session.scalars(
                        select(SecurityEvent)
                        .where(
                            SecurityEvent.kind.in_(("BROKER_IDENTITY_OBSERVED", "SECRET_ROTATED"))
                        )
                        .order_by(SecurityEvent.seq)
                    )
                )
                previous = tuple(
                    event
                    for event in events
                    if event.kind == "BROKER_IDENTITY_OBSERVED" and event.detail.get("name") == name
                )
                prior = previous[-1] if previous else None
                changed = prior is not None and prior.detail.get("fingerprint") != fingerprint
                rotated = any(
                    event.kind == "SECRET_ROTATED"
                    and event.seq > (0 if prior is None else prior.seq)
                    and event.detail.get("name") == name
                    and event.detail.get("fingerprint") == fingerprint
                    for event in events
                )
            if changed and not rotated:
                self.state.escalate(SystemState.HALTED, "SEC-72 unexplained broker identity change")
                self.ledger.append(
                    SecurityEvent,
                    kind="BROKER_IDENTITY_CHANGED",
                    detail={"name": name, "fingerprint": fingerprint},
                    ts=ensure_utc(self.clock.now()),
                )
            if prior is None or changed:
                self.ledger.append(
                    SecurityEvent,
                    kind="BROKER_IDENTITY_OBSERVED",
                    telegram_user_id=None,
                    detail={"name": name, "fingerprint": fingerprint},
                    ts=ensure_utc(self.clock.now()),
                )
            if changed and not rotated and self.notify is not None:
                self.notify(
                    "Urgent: broker account or key identity changed without verified rotation; entries are halted."
                )
            return changed and not rotated
        except Exception:
            try:
                self.state.escalate(
                    SystemState.HALTED, "SEC-72 broker identity could not be verified"
                )
            except Exception:
                raise DataIntegrityError(
                    "SEC-72: identity verification failed and durable halt is unverified"
                ) from None
            raise DataIntegrityError(
                "SEC-72: broker identity evidence could not be verified"
            ) from None

    def panic(
        self,
        operator: str,
        reason: str,
        *,
        mode: str = "MANUAL",
        stop_entries: Callable[[], None] | None = None,
        cancel_unfilled: Callable[[], None] | None = None,
        notify: Callable[[str], None] | None = None,
        read_activities: Callable[[datetime], tuple[str, ...]] | None = None,
    ) -> PanicResult:
        """SEC-73: console-only local HALT commits before all external callbacks.

        The future AUTO composition injects cancellation of unfilled entries;
        MANUAL never invokes that callback and never imports an executor.
        """
        operator = _operator(operator)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 280:
            raise DataIntegrityError("SEC-73: panic requires a short local reason")
        if mode not in {"MANUAL", "AUTO_PAPER", "AUTO_LIVE"}:
            raise DataIntegrityError("SEC-73: panic requires a valid mode label")
        local_state = SystemStateStore(
            self.ledger.engine, self.clock, ConsoleNotifier(), verify_ledger=False
        )
        try:
            local_state.escalate(SystemState.HALTED, "SEC-73 local panic")
        except Exception:
            raise DataIntegrityError(
                "SEC-73: panic local HALT persistence failed; revoke keys now"
            ) from None
        failures: list[str] = []
        if mode in {"AUTO_PAPER", "AUTO_LIVE"} and cancel_unfilled is None:
            failures.append("cancel unfilled entries unavailable")
        for label, action in (
            ("stop entry jobs", stop_entries),
            (
                "cancel unfilled entries",
                cancel_unfilled if mode in {"AUTO_PAPER", "AUTO_LIVE"} else None,
            ),
        ):
            if action is not None:
                try:
                    action()
                except Exception:
                    failures.append(label)
        try:
            self.ledger.append(
                SecurityEvent,
                kind="PANIC",
                telegram_user_id=None,
                detail={"operator": operator, "failed_steps": list(failures)},
                ts=ensure_utc(self.clock.now()),
            )
        except Exception:
            failures.append("write panic audit")
        if notify is not None:
            try:
                notify(
                    "HALTED locally. Revoke affected broker and Telegram keys; inspect withdrawals and unknown orders."
                )
            except Exception:
                failures.append("notify Telegram")
        activity: tuple[str, ...] = ()
        if read_activities is not None:
            try:
                activity = read_activities(ensure_utc(self.clock.now()) - timedelta(days=30))
                if type(activity) is not tuple or any(
                    not isinstance(line, str) or len(line) > 280 for line in activity
                ):
                    raise ValueError("activity report must be bounded text")
            except Exception:
                activity = ()
                failures.append("read recent activity")
        return PanicResult(
            state=SystemState.HALTED,
            failed_steps=tuple(failures),
            recent_activity=activity,
            revoke_checklist=REVOKE_CHECKLIST,
        )
