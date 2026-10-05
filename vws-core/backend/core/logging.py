"""R-07: recursively redact credentials before structured log rendering."""

import logging
import re
from collections.abc import Mapping, MutableMapping
from datetime import date, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import structlog
from pydantic import SecretStr

from backend.core.clock import Clock, SystemClock, ensure_utc

REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|credential|"
    r"fernet|db[_-]?url)",
    re.IGNORECASE,
)
_URL_PASSWORD = re.compile(r"(://[^\s:/@]+:)[^\s@]+(@)")
_TELEGRAM_TOKEN = re.compile(r"bot\d+:[A-Za-z0-9_-]{30,}")
_PLAID_TOKEN = re.compile(r"access-[A-Za-z0-9_-]+")
_HEADER_VALUE = re.compile(
    r"((?:APCA-API-[A-Za-z0-9_-]+|Authorization)[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n,;}]+)",
    re.IGNORECASE,
)
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
    value = _URL_PASSWORD.sub(r"\1[REDACTED]\2", value)
    value = _TELEGRAM_TOKEN.sub(REDACTED, value)
    value = _PLAID_TOKEN.sub(REDACTED, value)
    return _HEADER_VALUE.sub(r"\1[REDACTED]", value)


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


def configure_logging(
    *secrets: SecretStr | str,
    log_path: Path | None = None,
    retention_days: int = 30,
    clock: Clock | None = None,
) -> None:
    """R-07: install redaction before JSON output and register known secrets."""
    register_secrets(*secrets)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for handler in logging.getLogger().handlers:
        handler.setFormatter(RedactingFormatter("%(message)s"))
    for name in ("httpx", "httpcore", "urllib3", "telegram"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if log_path is not None:
        root = logging.getLogger()
        for handler in tuple(root.handlers):
            if isinstance(handler, DailyRedactingHandler):
                root.removeHandler(handler)
                handler.close()
        root.addHandler(configure_daily_log(log_path, retention_days=retention_days, clock=clock))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory()
        if log_path is None
        else structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


class RedactingFormatter(logging.Formatter):
    """R-07: scrub SDK standard-logging messages and rendered tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        """R-07: redact after interpolation and exception rendering."""
        return _redact_text(super().format(record))


class DailyRedactingHandler(TimedRotatingFileHandler):
    """SEC-14/SEC-75: UTC daily rotation, with age-based permanent expiry."""

    def __init__(self, path: Path, retention_days: int, clock: Clock) -> None:
        """SEC-75: enforce the documented retention range before opening logs."""
        if (
            isinstance(retention_days, bool)
            or not isinstance(retention_days, int)
            or not 7 <= retention_days <= 365
        ):
            raise ValueError("log retention must be between 7 and 365 days")
        self.retention_days = retention_days
        self.clock = clock
        super().__init__(
            path,
            when="midnight",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
            utc=True,
        )
        self.setFormatter(RedactingFormatter("%(message)s"))

    def getFilesToDelete(self) -> list[str]:
        """SEC-75: sparse logging still expires archives by age, not file count."""
        path = Path(self.baseFilename)
        parent = path.parent.resolve(strict=True)
        cutoff = ensure_utc(self.clock.now()).date() - timedelta(days=self.retention_days)
        result: list[str] = []
        prefix = path.name + "."
        for archive in parent.glob(prefix + "????-??-??"):
            if archive.is_symlink() or not archive.resolve(strict=True).is_relative_to(parent):
                raise ValueError("log archive provenance cannot be verified")
            try:
                archive_day = date.fromisoformat(archive.name[len(prefix) :])
            except ValueError:
                continue
            if archive_day <= cutoff and archive.is_file():
                result.append(str(archive))
        return sorted(result)


def configure_daily_log(
    path: Path,
    *,
    retention_days: int = 30,
    clock: Clock | None = None,
) -> DailyRedactingHandler:
    """SEC-14/SEC-75: a caller explicitly chooses a private daily log path."""
    if (
        isinstance(retention_days, bool)
        or not isinstance(retention_days, int)
        or not 7 <= retention_days <= 365
    ):
        raise ValueError("log retention must be between 7 and 365 days")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("log path must not be a symbolic link")
    handler = DailyRedactingHandler(path, retention_days, SystemClock() if clock is None else clock)
    for expired in handler.getFilesToDelete():
        Path(expired).unlink()
    return handler
