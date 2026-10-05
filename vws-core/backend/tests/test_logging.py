"""R-07: credential redaction applies to structured and free-text logs."""

import io
import json
import logging

import pytest
import structlog
from pydantic import SecretStr

from backend.core.config import Settings
from backend.core.errors import ProviderError
from backend.core.logging import (
    REDACTED,
    RedactingFormatter,
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
