"""SEC-01/SEC-43/SEC-72/SEC-73: durable host-only security evidence and offline panic."""

from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import SecurityEvent, SystemEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.ops.security import ACCOUNT_ITEMS, ConfigDriftGuard, SecurityOps, effective_config_hash


def _ops(engine: Engine, clock: FrozenClock) -> SecurityOps:
    return SecurityOps(
        Ledger(engine, clock), SystemStateStore(engine, clock, ConsoleNotifier()), clock
    )


def _rows(engine: Engine, kind: str) -> list[SecurityEvent]:
    with transaction(engine) as session:
        return list(
            session.scalars(
                select(SecurityEvent).where(SecurityEvent.kind == kind).order_by(SecurityEvent.seq)
            )
        )


def _files(tmp_path: Path) -> dict[str, Path]:
    files = {
        name: tmp_path / name
        for name in ("config.yaml", "instruments.csv", "macro_events.csv", "accounts.yaml")
    }
    files["config.yaml"].write_text("policy: fixed\n", encoding="utf-8")
    files["instruments.csv"].write_text("symbol\nSPY\n", encoding="utf-8")
    return files


def test_SEC_43_hash_is_stable_excludes_secrets_and_binds_effective_values(tmp_path: Path) -> None:
    files = _files(tmp_path)
    settings = Settings(_env_file=None, broker_account_type="CASH")
    original = effective_config_hash(settings, files)
    assert original == effective_config_hash(settings, dict(reversed(tuple(files.items()))))
    secret_changed = Settings(
        _env_file=None,
        broker_account_type="CASH",
        alpaca_api_key="synthetic-one",
        alpaca_secret_key="synthetic-two",
    )
    assert original == effective_config_hash(secret_changed, files)
    amount_changed = Settings(_env_file=None, broker_account_type="CASH", max_open_positions=2)
    assert original != effective_config_hash(amount_changed, files)


@pytest.mark.parametrize(
    "name", ["config.yaml", "instruments.csv", "macro_events.csv", "accounts.yaml"]
)
def test_SEC_43_each_policy_file_is_bound_in_hash(tmp_path: Path, name: str) -> None:
    files = _files(tmp_path)
    settings = Settings(_env_file=None, broker_account_type="CASH")
    before = effective_config_hash(settings, files)
    files[name].write_bytes(b"changed policy bytes")
    assert effective_config_hash(settings, files) != before


@pytest.mark.parametrize("fault", ["inventory", "required_missing", "directory", "oversized"])
def test_SEC_43_bad_config_inventory_is_typed(tmp_path: Path, fault: str) -> None:
    files = _files(tmp_path)
    if fault == "inventory":
        files.pop("accounts.yaml")
    elif fault == "required_missing":
        files["config.yaml"].unlink()
    elif fault == "directory":
        files["config.yaml"] = tmp_path
    else:
        with files["config.yaml"].open("wb") as handle:
            handle.truncate(10 * 1024 * 1024 + 1)
    with pytest.raises(DataIntegrityError, match="fingerprinted"):
        effective_config_hash(Settings(_env_file=None, broker_account_type="CASH"), files)


@pytest.mark.parametrize("mode", ["MANUAL", "AUTO_PAPER", "AUTO_LIVE"])
def test_SEC_43_applied_config_is_quiet_and_unapproved_change_alerts_once(
    engine: Engine, clock: FrozenClock, mode: str
) -> None:
    messages: list[str] = []
    guard = ConfigDriftGuard(Ledger(engine, clock), clock, messages.append)
    guard.apply("a" * 64, "Owner")
    assert not guard.check("a" * 64, mode).changed
    result = guard.check("b" * 64, mode)
    assert result.changed and result.newly_detected
    assert result.entries_paused == (mode != "MANUAL")
    assert guard.entries_paused() == result.entries_paused
    assert not guard.check("b" * 64, mode).newly_detected
    assert len(messages) == 1 and messages[0].startswith("Urgent:")
    assert len(_rows(engine, "CONFIG_DRIFT")) == 1
    assert len(_rows(engine, "CONFIG_DRIFT_PAUSED")) == (mode != "MANUAL")


def test_SEC_43_pause_latches_through_config_revert_until_host_ack(
    engine: Engine, clock: FrozenClock
) -> None:
    guard = ConfigDriftGuard(Ledger(engine, clock), clock)
    guard.apply("a" * 64, "Owner")
    guard.check("b" * 64, "AUTO_PAPER")
    reverted = guard.check("a" * 64, "AUTO_PAPER")
    assert not reverted.changed and reverted.entries_paused
    guard.ack("a" * 64, "Owner")
    assert not guard.entries_paused()
    assert not guard.check("a" * 64, "AUTO_PAPER").entries_paused
    assert _rows(engine, "CONFIG_ACKNOWLEDGED")[-1].detail["operator"] == "Owner"


def test_SEC_43_manual_drift_becoming_auto_pauses_before_entries(
    engine: Engine, clock: FrozenClock
) -> None:
    guard = ConfigDriftGuard(Ledger(engine, clock), clock)
    result = guard.check("a" * 64)
    assert result.baseline_hash is None and not result.entries_paused
    result = guard.check("a" * 64, "AUTO_PAPER")
    assert result.entries_paused and not result.newly_detected


def test_SEC_43_notification_failure_does_not_erase_auto_pause(
    engine: Engine, clock: FrozenClock
) -> None:
    def fail(message: str) -> None:
        raise OSError("offline")

    guard = ConfigDriftGuard(Ledger(engine, clock), clock, fail)
    with pytest.raises(DataIntegrityError):
        guard.check("a" * 64, "AUTO_PAPER")
    assert guard.entries_paused()
    assert len(_rows(engine, "CONFIG_DRIFT")) == 1


@pytest.mark.parametrize("value", ["", "a" * 63, "A" * 64, "g" * 64, 123, None])
def test_SEC_43_malformed_config_hash_refuses(
    engine: Engine, clock: FrozenClock, value: object
) -> None:
    guard = ConfigDriftGuard(Ledger(engine, clock), clock)
    with pytest.raises(DataIntegrityError):
        guard.check(cast(Any, value))
    with pytest.raises(DataIntegrityError):
        guard.apply(cast(Any, value), "Owner")


@pytest.mark.parametrize("mode", ["AUTO", "manual", "", 123, None])
def test_SEC_43_unknown_mode_never_bypasses_pause(
    engine: Engine, clock: FrozenClock, mode: object
) -> None:
    with pytest.raises(DataIntegrityError):
        ConfigDriftGuard(Ledger(engine, clock), clock).check("a" * 64, cast(Any, mode))


@pytest.mark.parametrize("item", ACCOUNT_ITEMS)
def test_SEC_01_ten_account_items_are_dated_attestations_not_remote_verifications(
    engine: Engine, clock: FrozenClock, item: str
) -> None:
    ops = _ops(engine, clock)
    initial = ops.attestations()
    assert len(initial) == 10 and all(row.status == "WARN" for row in initial)
    attested = ops.attest(item, "Owner")
    assert attested.status == "ATTESTED" and attested.recorded_at == clock.now()
    observed = {row.item: row for row in ops.attestations()}
    assert observed[item] == attested
    assert all(row.status == "WARN" for name, row in observed.items() if name != item)
    assert _rows(engine, "ACCOUNT_ATTESTED")[0].detail == {"item": item, "operator": "Owner"}


def test_SEC_01_latest_attestation_date_wins(engine: Engine, clock: FrozenClock) -> None:
    ops = _ops(engine, clock)
    ops.attest("ALPACA_MFA", "Owner")
    later = FrozenClock(clock.now() + timedelta(days=1))
    ops = _ops(engine, later)
    ops.attest("ALPACA_MFA", "Owner")
    assert ops.attestations()[0].recorded_at == later.now()


@pytest.mark.parametrize("operator", ["", " ", "<owner>", "x" * 129, None])
def test_SEC_01_bad_attribution_is_typed(
    engine: Engine, clock: FrozenClock, operator: object
) -> None:
    with pytest.raises(DataIntegrityError):
        _ops(engine, clock).attest("ALPACA_MFA", cast(Any, operator))


def test_SEC_01_unknown_attestation_refuses(engine: Engine, clock: FrozenClock) -> None:
    with pytest.raises(DataIntegrityError):
        _ops(engine, clock).attest("REMOTE_VERIFIED", "Owner")


def test_SEC_72_counts_use_injected_report_window(engine: Engine, clock: FrozenClock) -> None:
    ops = _ops(engine, clock)
    ops.attest("ALPACA_MFA", "Owner")
    ops.attest("PASSWORD_MANAGER", "Owner")
    assert ops.counts(clock.now() - timedelta(days=7)) == {"ACCOUNT_ATTESTED": 2}
    assert ops.counts(clock.now()) == {"ACCOUNT_ATTESTED": 2}
    with pytest.raises(DataIntegrityError):
        ops.counts(clock.now() + timedelta(seconds=1))


def test_SEC_72_first_identity_bootstraps_unchanged_is_quiet_change_halts_and_alerts(
    engine: Engine, clock: FrozenClock
) -> None:
    messages: list[str] = []
    ops = _ops(engine, clock)
    ops.notify = messages.append
    assert not ops.observe_identity("ALPACA_PAPER_API_KEY", "a" * 64)
    assert not ops.observe_identity("ALPACA_PAPER_API_KEY", "a" * 64)
    assert ops.state.current() == SystemState.RUNNING
    assert ops.observe_identity("ALPACA_PAPER_API_KEY", "b" * 64)
    assert ops.state.current() == SystemState.HALTED
    assert len(messages) == 1 and messages[0].startswith("Urgent:")
    assert len(_rows(engine, "BROKER_IDENTITY_CHANGED")) == 1
    assert len(_rows(engine, "BROKER_IDENTITY_OBSERVED")) == 2
    restarted = _ops(engine, clock)
    assert restarted.state.current() == SystemState.HALTED


@pytest.mark.parametrize("proof", ["matching", "wrong_name", "wrong_fingerprint", "stale"])
def test_SEC_72_only_later_matching_rotation_proof_accepts_key_change(
    engine: Engine, clock: FrozenClock, proof: str
) -> None:
    ops = _ops(engine, clock)
    if proof == "stale":
        ops.ledger.append(
            SecurityEvent,
            kind="SECRET_ROTATED",
            detail={"name": "ALPACA_PAPER_API_KEY", "fingerprint": "b" * 64},
        )
    ops.observe_identity("ALPACA_PAPER_API_KEY", "a" * 64)
    if proof != "stale":
        ops.ledger.append(
            SecurityEvent,
            kind="SECRET_ROTATED",
            detail={
                "name": "OTHER_KEY" if proof == "wrong_name" else "ALPACA_PAPER_API_KEY",
                "fingerprint": "c" * 64 if proof == "wrong_fingerprint" else "b" * 64,
            },
        )
    halted = ops.observe_identity("ALPACA_PAPER_API_KEY", "b" * 64)
    assert halted == (proof != "matching")
    assert ops.state.current() == (
        SystemState.RUNNING if proof == "matching" else SystemState.HALTED
    )


@pytest.mark.parametrize(
    "name,fingerprint",
    [
        ("bad label", "a" * 64),
        ("x" * 65, "a" * 64),
        ("ALPACA_KEY", "bad"),
        ("ALPACA_KEY", "A" * 64),
    ],
)
def test_SEC_72_unverifiable_identity_fails_closed_and_halts(
    engine: Engine, clock: FrozenClock, name: str, fingerprint: str
) -> None:
    ops = _ops(engine, clock)
    with pytest.raises(DataIntegrityError):
        ops.observe_identity(name, fingerprint)
    assert ops.state.current() == SystemState.HALTED


@pytest.mark.parametrize("mode", ["MANUAL", "AUTO_PAPER", "AUTO_LIVE"])
def test_SEC_73_panic_persists_halt_before_every_callback_and_only_auto_cancels(
    engine: Engine, clock: FrozenClock, mode: str
) -> None:
    ops = _ops(engine, clock)
    called: list[str] = []
    since_values: list[object] = []

    def observe(label: str) -> None:
        assert _ops(engine, clock).state.current() == SystemState.HALTED
        called.append(label)

    def stop() -> None:
        observe("stop entries")

    def cancel() -> None:
        observe("cancel unfilled only")

    def notify(message: str) -> None:
        observe("notify")
        assert _rows(engine, "PANIC")

    def read(since: object) -> tuple[str, ...]:
        observe("read activity")
        since_values.append(since)
        return ("non-FILL: cash activity", "unknown client order id: external-order")

    result = ops.panic(
        "Owner",
        "suspected compromise",
        mode=mode,
        stop_entries=stop,
        cancel_unfilled=cancel,
        notify=notify,
        read_activities=read,
    )
    assert result.state == SystemState.HALTED and not result.failed_steps
    assert called == (
        ["stop entries", "cancel unfilled only", "notify", "read activity"]
        if mode != "MANUAL"
        else ["stop entries", "notify", "read activity"]
    )
    assert since_values == [clock.now() - timedelta(days=30)]
    assert len(result.recent_activity) == 2
    assert any("Regenerate" in line for line in result.revoke_checklist)
    assert any("/revoke" in line for line in result.revoke_checklist)
    with transaction(engine) as session:
        halt_event = session.scalar(select(SystemEvent))
        panic_event = session.scalar(select(SecurityEvent).where(SecurityEvent.kind == "PANIC"))
        assert (
            halt_event is not None and panic_event is not None and halt_event.seq < panic_event.seq
        )


def test_SEC_73_panic_completes_with_network_and_all_optional_steps_down(
    engine: Engine, clock: FrozenClock
) -> None:
    ops = _ops(engine, clock)

    def fail() -> None:
        raise OSError("offline")

    def notify(message: str) -> None:
        raise OSError("offline")

    def read(since: object) -> tuple[str, ...]:
        raise OSError("offline")

    result = ops.panic(
        "Owner",
        "offline",
        mode="AUTO_PAPER",
        stop_entries=fail,
        cancel_unfilled=fail,
        notify=notify,
        read_activities=read,
    )
    assert result.failed_steps == (
        "stop entry jobs",
        "cancel unfilled entries",
        "notify Telegram",
        "read recent activity",
    )
    assert result.state == SystemState.HALTED and result.recent_activity == ()
    assert result.revoke_checklist
    assert _ops(engine, clock).state.current() == SystemState.HALTED


def test_SEC_73_missing_auto_cancellation_is_explicit_unavailable(
    engine: Engine, clock: FrozenClock
) -> None:
    result = _ops(engine, clock).panic("Owner", "offline", mode="AUTO_PAPER")
    assert result.failed_steps == ("cancel unfilled entries unavailable",)


@pytest.mark.parametrize("value", [["not tuple"], ("x" * 281,), (123,)])
def test_SEC_73_invalid_activity_is_unavailable_without_losing_halt(
    engine: Engine, clock: FrozenClock, value: object
) -> None:
    def read(since: object) -> tuple[str, ...]:
        return cast(tuple[str, ...], value)

    result = _ops(engine, clock).panic("Owner", "offline", read_activities=read)
    assert result.recent_activity == () and result.failed_steps == ("read recent activity",)


@pytest.mark.parametrize("reason", ["", " ", "x" * 281, None])
def test_SEC_73_invalid_panic_reason_is_typed(
    engine: Engine, clock: FrozenClock, reason: object
) -> None:
    with pytest.raises(DataIntegrityError):
        _ops(engine, clock).panic("Owner", cast(Any, reason))


@pytest.mark.parametrize("mode", ["AUTO", "manual", 123])
def test_SEC_73_unknown_panic_mode_is_typed(
    engine: Engine, clock: FrozenClock, mode: object
) -> None:
    with pytest.raises(DataIntegrityError):
        _ops(engine, clock).panic("Owner", "test", mode=cast(Any, mode))


def test_SEC_73_security_ops_refuse_a_different_active_ledger(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    from backend.core.database import create_database, create_schema

    other = create_database(f"sqlite:///{(tmp_path / 'other.db').as_posix()}")
    create_schema(other)
    try:
        with pytest.raises(DataIntegrityError):
            SecurityOps(
                Ledger(other, clock), SystemStateStore(engine, clock, ConsoleNotifier()), clock
            )
    finally:
        other.dispose()


def test_SEC_43_explicit_nonempty_telegram_allowlist_is_valid_in_hash(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None, broker_account_type="CASH", telegram_allowed_user_ids=(123,)
    )
    assert len(effective_config_hash(settings, _files(tmp_path))) == 64


def test_SEC_01_SEC_43_ledger_read_faults_are_typed(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _ops(engine, clock)
    guard = ConfigDriftGuard(ops.ledger, clock)

    def fail() -> None:
        raise OSError("unavailable storage")

    monkeypatch.setattr(ops.ledger, "verify_chain", fail)
    with pytest.raises(DataIntegrityError):
        guard.entries_paused()
    with pytest.raises(DataIntegrityError):
        ops.attestations()


def test_SEC_72_failed_identity_halt_is_explicitly_unverified(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _ops(engine, clock)

    def fail(target: SystemState, reason: str) -> SystemState:
        raise OSError("unavailable storage")

    monkeypatch.setattr(ops.state, "escalate", fail)
    with pytest.raises(DataIntegrityError, match="durable halt is unverified"):
        ops.observe_identity("BAD LABEL", "a" * 64)


def test_SEC_73_halt_storage_fault_never_calls_network_and_prints_revoke_instruction(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _ops(engine, clock)
    messages: list[str] = []

    def fail(self: SystemStateStore, target: SystemState, reason: str) -> SystemState:
        raise OSError("unavailable storage")

    monkeypatch.setattr(SystemStateStore, "escalate", fail)
    with pytest.raises(DataIntegrityError, match="revoke keys now"):
        ops.panic("Owner", "storage fault", notify=messages.append)
    assert messages == []


def test_SEC_73_panic_audit_failure_keeps_durable_halt_and_offline_checklist(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _ops(engine, clock)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("unavailable audit storage")

    monkeypatch.setattr(ops.ledger, "append", fail)
    result = ops.panic("Owner", "audit fault")
    assert result.failed_steps == ("write panic audit",)
    assert ops.state.current() == SystemState.HALTED and result.revoke_checklist
