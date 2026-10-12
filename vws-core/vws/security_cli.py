"""SEC-01..75: explicit host security commands; no broker order imports."""

from __future__ import annotations

import asyncio
import getpass
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from sqlalchemy.engine import Engine, make_url

from backend.core.clock import SystemClock
from backend.core.config import Settings, YamlConfig, load_settings, load_yaml_config
from backend.core.database import (
    SecurityEvent,
    create_database,
    create_schema,
    prepare_panic_schema,
)
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.core.logging import configure_logging
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.domain.instruments import InstrumentRegistry
from backend.execution.stop_readiness import live_raise_reasons
from backend.net.egress import EgressPolicy, SDKSocketGuard, build_allowlist
from backend.net.http import configure_network, make_client
from backend.ops.anchors import LedgerAnchors
from backend.ops.backups import BackupService
from backend.ops.doctor import DoctorResult
from backend.ops.security import ACCOUNT_ITEMS, ConfigDriftGuard, SecurityOps, effective_config_hash
from backend.security.permissions import check_permissions
from backend.security.secrets import (
    RotationService,
    SecretStore,
    assert_secret_sources,
)
from backend.telegram.security import bot_security_findings
from vws.host_config import (
    LocalLedgerLocator,
    emergency_mode,
    load_downgrade_settings,
    load_host_settings,
)

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
    settings_source: Callable[[], Settings] | None = None
    egress_guard: SDKSocketGuard | None = None
    doctor_observations: tuple[datetime, DoctorResult] | None = None
    emergency_mode: str | None = None

    def config_hash(self) -> str:
        return effective_config_hash(
            self.settings if self.settings_source is None else self.settings_source(),
            {
                name: PROJECT / "config" / name
                for name in ("config.yaml", "instruments.csv", "macro_events.csv", "accounts.yaml")
            },
        )


def _panic_bound_context(context: SecurityContext, store: SecretStore) -> SecurityContext:
    """SEC-73: external callbacks cannot run before the durable local HALT."""
    from backend.core.system_state import SystemState

    if context.state.current() != SystemState.HALTED:
        raise ConfigurationError("Panic external reporting requires local HALT first")
    settings = load_host_settings(PROJECT, context.env_file, store)
    if settings.db_url != context.settings.db_url:
        raise ConfigurationError("Panic settings changed the local ledger binding")
    return replace(context, settings=settings, settings_source=None)


async def panic_notify(context: SecurityContext, store: SecretStore, text: str) -> None:
    """SEC-73: private, urgent notification; failure never undoes local HALT."""
    from telegram import Bot

    from backend.net.http import TelegramRequest
    from backend.ops.read_checks import ReadChecksClient

    bound = _panic_bound_context(context, store)
    settings = bound.settings
    settings.assert_telegram_ready()
    configure_egress(bound)
    config = load_yaml_config(
        PROJECT / "config/config.yaml",
        allowed_symbols=InstrumentRegistry.from_csv(PROJECT / "config").symbols,
        settings=settings,
    )
    policy = _require_network_policy(bound, config)
    reads = ReadChecksClient(policy, bound.ledger.clock)
    async with asyncio.timeout(60):
        me = await reads.telegram(settings.telegram_bot_token, "getMe")
        webhook = await reads.telegram(settings.telegram_bot_token, "getWebhookInfo")
        if (
            not isinstance(me, dict)
            or not isinstance(webhook, dict)
            or bot_security_findings(me, webhook, mode=settings.execution_mode)
        ):
            raise ConfigurationError("Panic notification requires verified private bot settings")
        for chat_id in settings.telegram_allowed_user_ids:
            chat = await reads.telegram(settings.telegram_bot_token, "getChat", chat_id=chat_id)
            if (
                not isinstance(chat, dict)
                or chat.get("id") != chat_id
                or chat.get("type") != "private"
            ):
                raise ConfigurationError("Panic notification requires verified private bot/chat")
        async with Bot(
            settings.telegram_bot_token.get_secret_value(),
            request=TelegramRequest(settings.telegram_bot_token.get_secret_value(), policy),
        ) as bot:
            for chat_id in settings.telegram_allowed_user_ids:
                await bot.send_message(chat_id, text)


async def panic_activities(
    context: SecurityContext, store: SecretStore, since: datetime
) -> tuple[str, ...]:
    """SEC-73: bounded read-only activity and unrecognized-order report."""
    from sqlalchemy.orm import Session

    from backend.data.async_reader import AsyncAlpacaReader
    from backend.data.fee_schedule import load_fee_schedule
    from backend.execution.storage import bindings
    from backend.funding.activities import AlpacaActivitiesSource
    from backend.ops.read_checks import ReadChecksClient

    bound = _panic_bound_context(context, store)
    settings = bound.settings
    # Refuse before activating sockets if the matching native pair is absent.
    ReadChecksClient.broker_headers(settings.broker_api_key, settings.broker_secret_key)
    configure_egress(bound)
    config = load_yaml_config(
        PROJECT / "config/config.yaml",
        allowed_symbols=InstrumentRegistry.from_csv(PROJECT / "config").symbols,
        settings=settings,
    )
    policy = _require_network_policy(bound, config)
    reader = AsyncAlpacaReader(bound.ledger.clock, bound.state, plan=settings.alpaca_data_plan)
    reader.bind_policy(settings, bound.ledger)
    source = None
    try:
        async with asyncio.timeout(60):
            reads = ReadChecksClient(
                policy, bound.ledger.clock, alpaca_request_hook=reader.bucket.acquire
            )
            account = await reads.account(
                settings, settings.broker_api_key, settings.broker_secret_key
            )
            source = AlpacaActivitiesSource(
                settings, str(account.account_id), bound.state, bound.ledger.clock, reader, policy
            )
            batch = await source.read_activities(
                since, bound.ledger.clock.now(), load_fee_schedule(PROJECT / "config/fees.yaml")
            )
            orders = await reads.open_orders(settings)
            if not isinstance(orders, list) or len(orders) >= 500:
                raise DataIntegrityError("Panic open-order report cannot prove completeness")
            with Session(bound.engine) as session:
                known = {str(row.order_id) for row in bindings(session).values()}
            output = []
            for activity in batch.activities:
                if activity.type != "FILL":
                    amount = (
                        "$•••" if settings.telegram_mask_amounts else f"${activity.amount:,.2f}"
                    )
                    output.append(f"{batch.env} · {activity.date} {activity.type} {amount}")
            for order in orders:
                if not isinstance(order, dict) or not isinstance(order.get("client_order_id"), str):
                    raise DataIntegrityError("Panic order identity is unavailable")
                if (
                    not order["client_order_id"].startswith("vws-")
                    and str(order.get("id")) not in known
                ):
                    output.append(
                        f"{batch.env} · Unrecognized open order; inspect broker dashboard"
                    )
            if len(output) > 10000:
                raise DataIntegrityError("Panic report exceeds its bounded activity count")
            return tuple(output) or (
                f"{batch.env} · Verified: no non-FILL activity in 30 days or unrecognized open order.",
            )
    finally:
        if source is not None:
            await source.client.aclose()
        await reader.aclose()


def open_context(
    env_file: Path | None = None,
    *,
    for_panic: bool = False,
    for_downgrade: bool = False,
    store: SecretStore | None = None,
) -> SecurityContext:
    """SEC-10: private dotenv is read only on an explicit command option."""
    engine: Engine | None = None
    try:
        if for_downgrade or for_panic:
            settings = load_downgrade_settings(PROJECT, env_file, store or LocalLedgerLocator())
        else:
            settings = (
                load_settings(env_file=env_file)
                if store is None
                else load_host_settings(PROJECT, env_file, store)
            )
        keys: tuple[str, ...] = ()
        if env_file is not None:
            text = env_file.read_text(encoding="utf-8-sig")
            keys = tuple(re.findall(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", text))
        if not (for_downgrade or for_panic):
            assert_secret_sources(settings.execution_mode, dotenv_keys=keys)
        # Refuse a positively world-writable database before opening it. Panic
        # bypasses AUTO startup prerequisites so a local halt remains reachable.
        db_path = local_database_path(settings)
        check_permissions(
            env_file=env_file,
            data_dir=PROJECT / "data",
            logs_dir=PROJECT / "logs",
            backups_dir=backup_directory(settings),
            db_path=db_path if db_path is not None and db_path.exists() else None,
            mode="MANUAL" if for_panic else settings.execution_mode,
        )
        configure_logging()
        engine = create_database(settings.db_url.get_secret_value())
        if for_panic:
            prepare_panic_schema(engine)
        else:
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
            emergency_mode=emergency_mode(env_file) if for_panic else None,
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


def backup_directory(settings: Settings) -> Path:
    """OPS-04: bind relative BACKUP_DIR to the project, never the caller's cwd."""
    selected = settings.backup_dir
    return selected if selected.is_absolute() else PROJECT / selected


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
            llm_enabled=settings.llm_enabled,
            llm_base_url=settings.llm_base_url,
            healthcheck_url=settings.healthcheck_ping_url.get_secret_value() or None,
            rss_urls=yaml.news.rss_urls,
            news_provider=settings.news_provider,
            extra_hosts={entry.host: entry.comment for entry in yaml.egress.extra_hosts},
        ),
        context.ledger,
    )
    configure_network(policy)
    guard = SDKSocketGuard(policy)
    guard.install()
    context.egress_guard = guard
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
        backups_dir=backup_directory(context.settings),
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


def live_security_guard(
    context: SecurityContext, store: SecretStore
) -> Callable[[], tuple[str, ...]]:
    """Amendment 03 section 10: inspect current local proof and recent doctor observations."""
    from backend.execution.live_security import LiveSecurityGuard

    def permissions() -> bool:
        findings = check_permissions(
            env_file=context.env_file,
            data_dir=PROJECT / "data",
            logs_dir=PROJECT / "logs",
            backups_dir=backup_directory(context.settings),
            db_path=local_database_path(context.settings),
            mode=context.settings.execution_mode,
        )
        return len(findings) >= 4 and all(row.status == "PASS" for row in findings)

    def observations() -> tuple[datetime, DoctorResult]:
        if context.doctor_observations is None:
            raise ConfigurationError("Current live security observations are unavailable")
        return context.doctor_observations

    return LiveSecurityGuard(
        context.settings,
        context.state,
        store,
        PROJECT,
        permissions_pass=permissions,
        observations=observations,
        egress_active=lambda: context.egress_guard is not None and context.egress_guard.installed,
    ).reasons


async def doctor_result(context: SecurityContext, store: SecretStore) -> DoctorResult:
    """OPS-01: actual checklist; optional observations remain explicitly unverified."""
    from backend.data.market_calendar import MarketCalendar
    from backend.domain.instruments import InstrumentRegistry
    from backend.ops.doctor import Doctor
    from backend.ops.host import inspect_host
    from backend.ops.read_checks import ReadChecksClient
    from vws.drill_cli import verified_drill

    config = load_yaml_config(
        PROJECT / "config/config.yaml",
        allowed_symbols=InstrumentRegistry.from_csv(PROJECT / "config").symbols,
        settings=context.settings,
    )
    configure_egress(context)
    host = await asyncio.to_thread(inspect_host, PROJECT / "data")
    doctor = Doctor(
        context.settings,
        config,
        context.state,
        MarketCalendar(),
        context.ledger.clock,
        store,
        ReadChecksClient(_require_network_policy(context, config), context.ledger.clock),
        project=PROJECT,
        host_findings=host,
    )
    result = await doctor.run()
    context.doctor_observations = (context.ledger.clock.now(), result)
    if context.settings.execution_mode == "MANUAL":
        return result
    from backend.execution.live_guard import LiveGuard
    from backend.execution.readiness import verified_backup
    from backend.ops.doctor import Check

    checks = list(result.checks)
    backup_ok = False
    try:
        await asyncio.to_thread(verified_backup, backups(context, store))
        backup_ok = True
    except Exception as error:
        backup_ok = False
        context.ledger.append(
            SecurityEvent,
            kind="AUTO_BACKUP_UNVERIFIED",
            detail={"error_type": type(error).__name__},
        )
    checks.append(
        Check(
            name="auto_backup",
            status="PASS" if backup_ok else "RED",
            required=True,
            message="Authenticated backup is verified and younger than 26 hours."
            if backup_ok
            else "AUTO backup is missing, stale or unverified.",
            fix="Run python -m vws ops backup, then ops restore-test --file PATH; retain the OS keyring backup key.",
        )
    )
    health_ok = bool(context.settings.healthcheck_ping_url.get_secret_value().strip())
    checks.append(
        Check(
            name="auto_watchdog",
            status="PASS" if health_ok else "RED",
            required=True,
            message="Watchdog and healthcheck endpoint are configured."
            if health_ok
            else "AUTO needs the watchdog and an HTTPS healthcheck endpoint.",
            fix="Enter HEALTHCHECK_PING_URL only through setup; verify the watchdog and external checker.",
        )
    )
    if context.settings.execution_mode == "AUTO_LIVE":
        security_reasons = live_security_guard(context, store)
        security_findings = security_reasons()
        checks.extend(
            Check(
                name="live_security_" + chr(ord("a") + index),
                status="RED",
                required=True,
                message=finding,
                fix="Complete this named security prerequisite on the host; unavailable evidence cannot pass.",
            )
            for index, finding in enumerate(security_findings)
        )
        if not security_findings:
            checks.append(
                Check(
                    name="live_security",
                    status="PASS",
                    required=True,
                    message="Every Amendment 03 section 10 live security prerequisite is verified.",
                    fix="Keep key rotation, attestations, backup, anchor, audit and host protections current.",
                )
            )
        findings: tuple[str, ...] = ("AX-15: live account identity remains unverified",)
        if doctor.account_id is not None:
            try:
                findings = LiveGuard(
                    context.settings,
                    context.state,
                    MarketCalendar(),
                    doctor.account_id,
                    context.config_hash,
                    security_reasons=security_reasons,
                    exit_reasons=lambda: live_raise_reasons(context.ledger, config),
                    verdict_hash=lambda: config.config_hash,
                    drill_ready=lambda: verified_drill(
                        PROJECT, context.settings, store, context.ledger.clock.now(), 45
                    ),
                ).reasons()
            except Exception:
                findings = ("AUTO_LIVE readiness evidence is invalid or unavailable",)
        checks.append(
            Check(
                name="live_unlock",
                status="RED" if findings else "PASS",
                required=True,
                message="AUTO_LIVE locked: " + "; ".join(findings)[:250]
                if findings
                else "AUTO_LIVE prerequisites verified.",
                fix="Complete AX-40/41, Stage K drill, Stage V READY and five Stage W healthy sessions; use host enable-live only after review.",
            )
        )
    green = DoctorResult(checks=tuple(checks)).fully_green
    checks.append(
        Check(
            name="auto_fully_green",
            status="PASS" if green else "RED",
            required=True,
            message="Every AUTO doctor observation is green."
            if green
            else "AUTO refuses any RED, WARN or UNVERIFIED doctor observation.",
            fix="Resolve each listed check; unavailable credentials or services never count as PASS.",
        )
    )
    return DoctorResult(checks=tuple(checks))


def _require_network_policy(context: SecurityContext, config: YamlConfig) -> EgressPolicy:
    """SEC-31: construct the same validated grants for explicit read clients."""
    settings = context.settings
    return EgressPolicy(
        build_allowlist(
            mode=settings.execution_mode,
            plaid_env=settings.plaid_env,
            llm_enabled=settings.llm_enabled,
            llm_base_url=settings.llm_base_url,
            healthcheck_url=settings.healthcheck_ping_url.get_secret_value() or None,
            rss_urls=config.news.rss_urls,
            news_provider=settings.news_provider,
            extra_hosts={entry.host: entry.comment for entry in config.egress.extra_hosts},
        ),
        context.ledger,
    )


def backups(context: SecurityContext, store: SecretStore) -> BackupService:
    return BackupService(
        context.ledger, context.ledger.clock, store, backup_directory(context.settings)
    )


def attest_item(value: str) -> str:
    if value.isdecimal() and 1 <= int(value) <= len(ACCOUNT_ITEMS):
        return ACCOUNT_ITEMS[int(value) - 1]
    return value
