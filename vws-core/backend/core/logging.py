"""R-07: recursively redact credentials before structured log rendering."""

import logging
import re
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from pydantic import SecretStr

REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|credential|"
    r"fernet|db[_-]?url)",
    re.IGNORECASE,
)
_URL_PASSWORD = re.compile(r"(://[^\s:/@]+:)[^\s@]+(@)")
_KNOWN_SECRETS: tuple[str, ...] = ()


def register_secrets(*secrets: SecretStr | str) -> None:
    """R-07: register configured values for free-text redaction."""
    global _KNOWN_SECRETS
    values = set(_KNOWN_SECRETS)
    for secret in secrets:
        raw = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        if raw:
            values.add(raw)
    _KNOWN_SECRETS = tuple(sorted(values, key=len, reverse=True))


def _redact_text(value: str) -> str:
    """R-07: scrub configured secrets and credential-bearing URL passwords."""
    for secret in _KNOWN_SECRETS:
        value = value.replace(secret, REDACTED)
    return _URL_PASSWORD.sub(r"\1[REDACTED]\2", value)


def redact(value: object) -> object:
    """R-07: redact nested fields without mutating the caller's payload."""
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {
            _redact_text(str(key)): REDACTED if _SECRET_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item) for item in value]
    if isinstance(value, BaseException):
        return _redact_text(str(value))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    # Never let a renderer invoke arbitrary __repr__ after this redaction stage.
    return REDACTED


def redact_processor(
    logger: object, method_name: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """R-07: structlog processor applied after exception formatting."""
    return {
        _redact_text(str(key)): REDACTED if _SECRET_KEY.search(str(key)) else redact(item)
        for key, item in event_dict.items()
    }


def configure_logging(*secrets: SecretStr | str) -> None:
    """R-07: install redaction before JSON output and register known secrets."""
    register_secrets(*secrets)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for handler in logging.getLogger().handlers:
        handler.setFormatter(RedactingFormatter("%(message)s"))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


class RedactingFormatter(logging.Formatter):
    """R-07: scrub SDK standard-logging messages and rendered tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        """R-07: redact after interpolation and exception rendering."""
        return _redact_text(super().format(record))
