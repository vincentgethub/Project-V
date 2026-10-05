"""SEC-01..75: explicit host security commands; no broker order imports."""

from __future__ import annotations

import asyncio
import getpass
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from sqlalchemy.engine import Engine, make_url

from backend.core.clock import SystemClock
from backend.core.config import Settings, load_settings, load_yaml_config
from backend.core.database import create_database, create_schema
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.core.logging import configure_logging
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.net.egress import EgressPolicy, SDKSocketGuard, build_allowlist
from backend.net.http import configure_network, make_client
from backend.ops.anchors import LedgerAnchors
from backend.ops.backups import BackupService
from backend.ops.security import ACCOUNT_ITEMS, ConfigDriftGuard, SecurityOps, effective_config_hash
from backend.security.permissions import check_permissions
from backend.security.secrets import (
    RotationService,
    SecretStore,
    assert_secret_sources,
)
from backend.telegram.security import bot_security_findings

PROJECT = Path(__file__).resolve().parents[1]


@dataclass
class SecurityContext:
    """Security services share the bound local ledger and injected clock."""

    settings: Settings
    engine: Engine
    ledger: Ledger
    state: SystemStateStore
    ops: SecurityOps
    drift: ConfigDriftGuard
    anchors: LedgerAnchors
    env_file: Path | None

    def config_hash(self) -> str:
        return effective_config_hash(
            self.settings,
            {
                name: PROJECT / "config" / name
                for name in ("config.yaml", "instruments.csv", "macro_events.csv", "accounts.yaml")
            },
        )


def open_context(env_file: Path | None = None, *, for_panic: bool = False) -> SecurityContext:
    """SEC-10: private dotenv is read only on an explicit command option."""
    engine: Engine | None = None
    try:
        settings = load_settings(env_file=env_file)
        keys: tuple[str, ...] = ()
        if env_file is not None:
            text = env_file.read_text(encoding="utf-8-sig")
            keys = tuple(re.findall(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", text))
        assert_secret_sources(settings.execution_mode, dotenv_keys=keys)
        # Refuse a positively world-writable database before opening it. Panic
        # bypasses AUTO startup prerequisites so a local halt remains reachable.
        db_path = local_database_path(settings)
        check_permissions(
            env_file=env_file,
            data_dir=PROJECT / "data",
            logs_dir=PROJECT / "logs",
            backups_dir=PROJECT / "backups",
            db_path=db_path if db_path is not None and db_path.exists() else None,
            mode="MANUAL" if for_panic else settings.execution_mode,
        )
        configure_logging()
        engine = create_database(settings.db_url.get_secret_value())
        create_schema(engine)
        clock = SystemClock()
        state = SystemStateStore(engine, clock, ConsoleNotifier(), verify_ledger=not for_panic)
        ledger = state.ledger
        ops = SecurityOps(ledger, state, clock)
        return SecurityContext(
            settings,
            engine,
            ledger,
            state,
            ops,
            ConfigDriftGuard(ledger, clock),
            LedgerAnchors(ledger, clock, settings.anchor_file_path),
            env_file,
        )
    except Exception:
        if engine is not None:
            engine.dispose()
        raise ConfigurationError(
            "Security command could not load its explicit configuration or verified ledger"
        ) from None


def local_database_path(settings: Settings) -> Path | None:
    """SEC-12: resolve only a local SQLite file; memory/remote DBs have no ACL."""
    url = make_url(settings.db_url.get_secret_value())
    if url.get_backend_name() != "sqlite" or url.database in {None, "", ":memory:"}:
        return None
    return Path(str(url.database)).resolve()


def configure_egress(context: SecurityContext) -> SDKSocketGuard:
    """SEC-31/32: explicit network startup verifies YAML grants first."""
    settings = context.settings
    import csv

    with (PROJECT / "config/instruments.csv").open(encoding="utf-8", newline="") as handle:
        symbols = {row["symbol"] for row in csv.DictReader(handle)}
    yaml = load_yaml_config(
        PROJECT / "config/config.yaml", allowed_symbols=symbols, settings=settings
    )
    policy = EgressPolicy(
        build_allowlist(
            mode=settings.execution_mode,
            plaid_env=settings.plaid_env,
            llm_enabled=settings.llm_daily_budget_usd > 0,
            llm_base_url=settings.llm_base_url,
            healthcheck_url=settings.healthcheck_ping_url.get_secret_value() or None,
            extra_hosts={entry.host: entry.comment for entry in yaml.egress.extra_hosts},
        ),
        context.ledger,
    )
    configure_network(policy)
    guard = SDKSocketGuard(policy)
    guard.install()
    return guard


async def read_json(
    purpose: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, str] | None = None,
) -> dict[str, Any]:
    """SEC-13: read-only credential validation shares the guarded factory."""
    async with make_client(purpose) as client:
        response = (
            await client.get(url, headers=headers)
            if payload is None
            else await client.post(url, json=payload)
        )
        if response.status_code != 200:
            raise ProviderError("Credential read validation was rejected by the provider")
        try:
            result = response.json()
        except Exception:
            raise ProviderError("Credential read validation returned malformed JSON") from None
        if not isinstance(result, dict):
            raise ProviderError("Credential validation response has the wrong shape")
        return result


def _stored_or_configured(store: SecretStore, name: str, configured: SecretStr) -> SecretStr:
    value = store.get(name)
    selected = value if value is not None else configured
    if not selected.get_secret_value():
        raise ConfigurationError("Matching credential is required for live read validation")
    return selected


def rotate_secret(context: SecurityContext, name: str, store: SecretStore) -> str:
    """SEC-13: hidden input is validated before the native keyring changes."""
    allowed = {
        "BROKER_API_KEY",
        "BROKER_SECRET_KEY",
        "ALPACA_PAPER_KEY_ID",
        "ALPACA_PAPER_SECRET",
        "ALPACA_LIVE_KEY_ID",
        "ALPACA_LIVE_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "PLAID_SECRET",
        "PLAID_ACCESS_TOKEN",
    }
    if name not in allowed:
        raise ConfigurationError("This credential has no supported read validator")
    value = SecretStr(getpass.getpass("New credential (hidden): "))
    configure_egress(context)
    settings = context.settings

    def validate(candidate: SecretStr) -> None:
        raw = candidate.get_secret_value()
        if name == "TELEGRAM_BOT_TOKEN":
            result = asyncio.run(
                read_json("telegram", "https://api.telegram.org/bot" + raw + "/getMe")
            )
            user = result.get("result")
            if (
                result.get("ok") is not True
                or not isinstance(user, dict)
                or user.get("is_bot") is not True
            ):
                raise DataIntegrityError("Telegram credential did not identify a bot")
        elif name.startswith("PLAID_"):
            secret = (
                raw
                if name == "PLAID_SECRET"
                else _stored_or_configured(
                    store, "PLAID_SECRET", settings.plaid_secret
                ).get_secret_value()
            )
            token = (
                raw
                if name == "PLAID_ACCESS_TOKEN"
                else _stored_or_configured(
                    store, "PLAID_ACCESS_TOKEN", SecretStr("")
                ).get_secret_value()
            )
            result = asyncio.run(
                read_json(
                    "plaid",
                    "https://" + settings.plaid_env + ".plaid.com/item/get",
                    payload={
                        "client_id": settings.plaid_client_id.get_secret_value(),
                        "secret": secret,
                        "access_token": token,
                    },
                )
            )
            if not isinstance(result.get("item"), dict) or not result["item"].get("item_id"):
                raise DataIntegrityError("Plaid credential did not identify an item")
        else:
            is_secret = name.endswith("SECRET") or name == "BROKER_SECRET_KEY"
            prefix = (
                "ALPACA_LIVE"
                if name.startswith("ALPACA_LIVE")
                else "ALPACA_PAPER"
                if name.startswith("ALPACA_PAPER")
                else "BROKER"
            )
            key_name = prefix + "_KEY_ID" if prefix != "BROKER" else "BROKER_API_KEY"
            secret_name = prefix + "_SECRET" if prefix != "BROKER" else "BROKER_SECRET_KEY"
            # Named pairs never borrow a credential from another environment.
            # The configured legacy pair may only supply its matching mode.
            configured_pair_matches = prefix == "BROKER" or (
                prefix == "ALPACA_PAPER" and settings.paper_trading
            )
            configured_key = settings.broker_api_key if configured_pair_matches else SecretStr("")
            configured_secret = (
                settings.broker_secret_key if configured_pair_matches else SecretStr("")
            )
            key = (
                _stored_or_configured(store, key_name, configured_key).get_secret_value()
                if is_secret
                else raw
            )
            secret = (
                raw
                if is_secret
                else _stored_or_configured(store, secret_name, configured_secret).get_secret_value()
            )
            host = (
                "api.alpaca.markets"
                if prefix == "ALPACA_LIVE"
                else "paper-api.alpaca.markets"
                if prefix == "ALPACA_PAPER"
                else settings.broker_endpoint.removeprefix("https://")
            )
            result = asyncio.run(
                read_json(
                    "alpaca",
                    "https://" + host + "/v2/account",
                    headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                )
            )
            account_id = result.get("id")
            if (
                not isinstance(account_id, str)
                or not account_id.strip()
                or result.get("status") != "ACTIVE"
                or any(
                    result.get(flag) is not False
                    for flag in ("trading_blocked", "account_blocked", "trade_suspended_by_user")
                )
            ):
                raise DataIntegrityError(
                    "Broker credential did not identify an active unrestricted account"
                )

    record = RotationService(store, context.ledger.clock, context.ledger, {name: validate}).rotate(
        name, value
    )
    return f"Credential rotated: {record.name}; dated HMAC fingerprint recorded."


def doctor(context: SecurityContext, store: SecretStore) -> tuple[str, ...]:
    """SEC checks report observations and explicitly leave absent evidence unverified."""
    settings = context.settings
    messages = [
        f"Mode: {settings.execution_mode}; real-money order path unavailable before Stage I."
    ]
    for item in context.ops.attestations():
        date = "" if item.recorded_at is None else " " + item.recorded_at.isoformat()
        messages.append(item.status + ": " + item.item + date)
    for finding in check_permissions(
        env_file=context.env_file,
        data_dir=PROJECT / "data",
        logs_dir=PROJECT / "logs",
        backups_dir=PROJECT / "backups",
        db_path=local_database_path(settings),
        mode=settings.execution_mode,
    ):
        messages.append(finding.status + ": " + finding.reason)
    for key in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "PYTHONHTTPSVERIFY"):
        if key in os.environ:
            messages.append("WARN: TLS environment override is set: " + key)
    pair_key = "ALPACA_PAPER_KEY_ID" if settings.paper_trading else "ALPACA_LIVE_KEY_ID"
    broker_key = (
        store.get(pair_key) or store.get("BROKER_API_KEY") or settings.broker_api_key
    ).get_secret_value()
    if broker_key and not broker_key.startswith("PK" if settings.paper_trading else "AK"):
        messages.append("WARN: broker key prefix is unexpected; prefix is only a hint.")
    rotation = RotationService(store, context.ledger.clock, context.ledger, {})
    for name in (
        pair_key,
        "ALPACA_PAPER_SECRET" if settings.paper_trading else "ALPACA_LIVE_SECRET",
        "BROKER_API_KEY",
        "BROKER_SECRET_KEY",
        "TELEGRAM_BOT_TOKEN",
        "PLAID_SECRET",
        "PLAID_ACCESS_TOKEN",
    ):
        age = rotation.age(name, settings.secret_max_age_days)
        messages.append(f"{age.status}: credential age {name}")
    token = store.get("TELEGRAM_BOT_TOKEN") or settings.telegram_bot_token
    if token.get_secret_value():
        configure_egress(context)
        base = "https://api.telegram.org/bot" + token.get_secret_value()
        me = asyncio.run(read_json("telegram", base + "/getMe"))
        webhook = asyncio.run(read_json("telegram", base + "/getWebhookInfo"))
        if (
            me.get("ok") is not True
            or webhook.get("ok") is not True
            or not isinstance(me.get("result"), dict)
            or not isinstance(webhook.get("result"), dict)
        ):
            raise ProviderError("Telegram security checks could not be verified")
        findings = bot_security_findings(
            me["result"], webhook["result"], mode=settings.execution_mode, ledger=context.ledger
        )
        messages.extend(findings)
        if not findings:
            messages.append("PASS: Telegram webhook and BotFather fields checked.")
    else:
        messages.append("UNVERIFIED: Telegram security requires a configured bot credential.")
    messages.append("UNVERIFIED: Trading API key scopes and IP allowlisting availability.")
    return tuple(messages)


def backups(context: SecurityContext, store: SecretStore) -> BackupService:
    return BackupService(context.ledger, context.ledger.clock, store, PROJECT / "backups")


def attest_item(value: str) -> str:
    if value.isdecimal() and 1 <= int(value) <= len(ACCOUNT_ITEMS):
        return ACCOUNT_ITEMS[int(value) - 1]
    return value
