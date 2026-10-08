"""SEC-10/WZ-03: explicit host settings with separately bound native secrets."""

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from backend.core.config import Settings, load_settings
from backend.core.errors import ConfigurationError
from backend.security.secrets import SecretStore, assert_secret_sources


def load_host_settings(project: Path, env_file: Path | None, store: SecretStore) -> Settings:
    """Read a dotenv only when named; presence never certifies credentials."""
    if env_file is not None and (not env_file.is_file() or env_file.stat().st_size > 1_048_576):
        raise ConfigurationError("The explicitly selected environment file is missing or too large")
    file_values = (
        {}
        if env_file is None
        else {
            name.upper(): value
            for name, value in dotenv_values(env_file, interpolate=False).items()
        }
    )
    mode = os.environ.get("EXECUTION_MODE", file_values.get("EXECUTION_MODE") or "MANUAL")
    assert_secret_sources(mode, dotenv_keys=tuple(file_values))
    paper = os.environ.get("PAPER_TRADING", file_values.get("PAPER_TRADING") or "true")
    if paper.casefold() not in {"true", "false"}:
        raise ConfigurationError("PAPER_TRADING must be true or false")
    prefix = "ALPACA_PAPER_" if paper.casefold() == "true" else "ALPACA_LIVE_"
    empty = SecretStr("")
    key, secret = store.get(prefix + "KEY_ID"), store.get(prefix + "SECRET")
    database = store.get("DB_URL")
    settings = load_settings(
        env_file=env_file,
        broker_api_key=key or empty,
        broker_secret_key=secret or empty,
        telegram_bot_token=store.get("TELEGRAM_BOT_TOKEN") or empty,
        telegram_callback_secret=store.get("TELEGRAM_CALLBACK_SECRET") or empty,
        plaid_secret=store.get("PLAID_SECRET") or empty,
        llm_api_key=store.get("LLM_API_KEY") or empty,
        newsapi_key=store.get("NEWSAPI_KEY") or empty,
        healthcheck_ping_url=store.get("HEALTHCHECK_PING_URL") or empty,
        **({"db_url": database} if database is not None else {}),
    )
    if store.get(prefix + "KEY_ID") != key or store.get(prefix + "SECRET") != secret:
        raise ConfigurationError(
            "Broker pair changed during configuration loading; retry after rotation"
        )
    url = make_url(settings.db_url.get_secret_value())
    if url.get_backend_name() == "sqlite" and url.database not in {None, "", ":memory:"}:
        path = Path(str(url.database))
        if not path.is_absolute():
            value = SecretStr(
                url.set(database=str((project / path).absolute())).render_as_string(
                    hide_password=False
                )
            )
            settings = Settings.validated_copy(settings.model_copy(update={"db_url": value}))
    return settings
