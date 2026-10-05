"""R-07: credential redaction applies to structured and free-text logs."""

import io
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
import structlog
from pydantic import SecretStr

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import ProviderError
from backend.core.logging import (
    REDACTED,
    RedactingFormatter,
    configure_daily_log,
    configure_logging,
    redact,
    redact_processor,
)
from backend.core.notifier import ConsoleNotifier, DeduplicatingNotifier


def test_R_07_recursive_redaction_does_not_modify_input() -> None:
    payload = {
        "api_key": "hidden-key",
        "nested": [{"secret": "hidden-secret"}],
        "value": SecretStr("hidden-object"),
        "ok": "ordinary",
    }
    result = redact(payload)
    text = json.dumps(result)
    for secret in ("hidden-key", "hidden-secret", "hidden-object"):
        assert secret not in text
    assert "ordinary" in text
    assert payload["api_key"] == "hidden-key"
    assert redact_processor(None, "info", {"authorization": "Bearer secret"}) == {
        "authorization": REDACTED
    }


def test_R_07_plaintext_configured_secrets_and_urls_are_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(broker_api_key=SecretStr("test-only-log-api"))
    configure_logging(settings.broker_api_key)
    structlog.get_logger().error(
        "request failed with test-only-log-api",
        payload={"token": "unknown-token"},
        database="postgresql://alice:unregistered-password@localhost/vws",
    )
    output = capsys.readouterr().out
    for secret in ("test-only-log-api", "unknown-token", "unregistered-password"):
        assert secret not in output
    assert REDACTED in output


def test_R_07_exception_trace_and_halt_notification_redaction(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(SecretStr("test-only-exception-secret"))
    try:
        raise RuntimeError("provider rejected test-only-exception-secret")
    except RuntimeError:
        structlog.get_logger().exception("provider_failure")
    ConsoleNotifier().notify("HALTED", "test-only-exception-secret is unavailable")
    output = capsys.readouterr().out
    assert "test-only-exception-secret" not in output
    assert "HALTED" in output
    assert "provider_failure" in output


def test_R_07_database_password_and_query_credentials_are_registered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    Settings(
        db_url=SecretStr(
            "postgresql://user:isolated-db-password@localhost/vws?token=isolated-db-token"
        )
    )
    configure_logging()
    structlog.get_logger().error("isolated-db-password isolated-db-token")
    output = capsys.readouterr().out
    assert "isolated-db-password" not in output
    assert "isolated-db-token" not in output


def test_R_07_typed_error_str_repr_and_args_are_redacted() -> None:
    configure_logging(SecretStr("fixture-exception-credential"))
    error = ProviderError("request failed for fixture-exception-credential")
    for rendered in (str(error), repr(error), repr(error.args)):
        assert "fixture-exception-credential" not in rendered
        assert REDACTED in rendered


def test_R_07_standard_logger_redacts_interpolation_and_traceback() -> None:
    configure_logging(SecretStr("fixture-standard-log-credential"))
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.Logger("isolated-sdk-test")
    logger.addHandler(handler)
    try:
        raise RuntimeError("fixture-standard-log-credential")
    except RuntimeError:
        logger.exception("SDK request %s", "fixture-standard-log-credential")
    assert "fixture-standard-log-credential" not in output.getvalue()
    assert REDACTED in output.getvalue()


def test_R_02_notifier_deduplicates_and_resets_after_recovery() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def notify(self, state: str, reason: str) -> None:
            self.calls.append((state, reason))

    recorder = Recorder()
    notifier = DeduplicatingNotifier(recorder)
    notifier.notify("HALTED", "stale quote")
    notifier.notify("HALTED", "stale quote")
    notifier.notify("HALTED", "ledger failure")
    assert len(recorder.calls) == 2
    notifier.reset()
    notifier.notify("HALTED", "stale quote")
    assert len(recorder.calls) == 3


def test_R_02_failed_notification_is_retried() -> None:
    class Failing:
        def __init__(self) -> None:
            self.calls = 0

        def notify(self, state: str, reason: str) -> None:
            self.calls += 1
            raise ProviderError("fixture notification failure")

    recorder = Failing()
    notifier = DeduplicatingNotifier(recorder)
    for _attempt in range(2):
        with pytest.raises(ProviderError):
            notifier.notify("HALTED", "fault")
    assert recorder.calls == 2


def test_R_07_arbitrary_repr_cannot_leak_after_redaction(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class UnsafePayload:
        def __repr__(self) -> str:
            raise RuntimeError("untrusted repr must never run")

    configure_logging(SecretStr("fixture-arbitrary-object-secret"))
    structlog.get_logger().error("object_boundary", payload=UnsafePayload())
    output = capsys.readouterr().out
    assert "fixture-arbitrary-object-secret" not in output
    assert REDACTED in output
    assert redact(42) == 42
    assert redact(None) is None


def test_SEC_14_sdk_log_levels_and_unknown_token_traceback_redaction() -> None:
    configure_logging()
    for name in ("httpx", "httpcore", "urllib3", "telegram"):
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING
    bot_token = "bot123456789:" + "Z" * 35
    plaid_token = "access-sandbox-isolated-unregistered-credential"
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.Logger("isolated-telegram-error")
    logger.addHandler(handler)
    try:
        raise RuntimeError(
            f"https://api.telegram.org/{bot_token}/getMe access_token={plaid_token}\n"
            "APCA-API-KEY-ID: isolated-header-key\n"
            'APCA-API-SECRET-KEY="isolated-header-secret"\n'
            "Authorization: Bearer isolated-authorization-value"
        )
    except RuntimeError:
        logger.exception("telegram request failed")
    rendered = output.getvalue()
    for value in (
        bot_token,
        plaid_token,
        "isolated-header-key",
        "isolated-header-secret",
        "isolated-authorization-value",
    ):
        assert value not in rendered
    assert "telegram request failed" in rendered
    assert REDACTED in rendered
    assert "access-" not in str(ProviderError(f"transport failed {plaid_token}"))


def test_SEC_75_daily_log_retention_uses_injected_utc_clock(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "vws.log"
    path.parent.mkdir()
    expired = path.parent / "vws.log.2026-09-05"
    kept = path.parent / "vws.log.2026-09-06"
    malformed = path.parent / "vws.log.2026-13-01"
    unrelated = path.parent / "other.log.2026-09-01"
    for item in (expired, kept, malformed, unrelated):
        item.write_text("old", encoding="utf-8")
    handler = configure_daily_log(
        path, retention_days=30, clock=FrozenClock(datetime(2026, 10, 5, tzinfo=UTC))
    )
    try:
        assert not expired.exists()
        assert kept.exists() and malformed.exists() and unrelated.exists()
        record = logging.LogRecord(
            "telegram", logging.ERROR, __file__, 1, "access-sandbox-only-log-test", (), None
        )
        handler.emit(record)
        handler.flush()
        assert "access-sandbox-only-log-test" not in path.read_text(encoding="utf-8")
        assert REDACTED in path.read_text(encoding="utf-8")
    finally:
        handler.close()


@pytest.mark.parametrize("retention", [6, 366, True, 30.5])
def test_SEC_75_retention_range_refuses_before_creating_file(
    tmp_path: Path, retention: int
) -> None:
    path = tmp_path / "never-created" / "vws.log"
    with pytest.raises(ValueError, match="7 and 365"):
        configure_daily_log(path, retention_days=retention)
    assert not path.exists()
