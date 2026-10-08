"""WZ-01..09: explicit host setup; no automatic execution or live key collection."""

import asyncio
import base64
import getpass
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from io import StringIO
from pathlib import Path
from typing import Literal, Protocol, TypeVar

from dotenv import dotenv_values
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import make_url

from backend.core.clock import Clock
from backend.core.config import Settings, YamlConfig, load_exact_yaml
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.logging import register_secrets
from backend.domain.instruments import InstrumentRegistry
from backend.domain.tax_profile import EXTERNAL_LOT_REMINDERS, TAX_ESTIMATE_NOTICE, TaxProfile
from backend.ops.apply_config import setup_application, setup_path
from backend.ops.doctor import DoctorResult
from backend.ops.read_checks import PaperAccountCheck, PrivateChatCheck
from backend.security.secrets import SecretStore

Section = Literal["telegram", "alpaca", "watchlist", "risk"]
ResultT = TypeVar("ResultT")
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_CREDENTIAL_NAMES = frozenset(
    {
        "BROKER_API_KEY",
        "BROKER_SECRET_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_PAPER_KEY_ID",
        "ALPACA_PAPER_SECRET",
        "ALPACA_LIVE_KEY_ID",
        "ALPACA_LIVE_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CALLBACK_SECRET",
        "FRED_API_KEY",
        "FERNET_KEY",
        "PLAID_ACCESS_TOKEN",
        "PLAID_SECRET",
        "LLM_API_KEY",
        "NEWSAPI_KEY",
        "HEALTHCHECK_PING_URL",
    }
)


class Prompts(Protocol):
    def ask(self, question: str, default: str = "") -> str: ...
    def hidden(self, question: str, saved: bool) -> str: ...
    def show(self, message: str) -> None: ...


class TerminalPrompts:
    def ask(self, question: str, default: str = "") -> str:
        answer = input(question + (f" [{default}]" if default else "") + ": ").strip()
        return answer or default

    def hidden(self, question: str, saved: bool) -> str:
        # ASCII works in the default Windows console; no prefix or secret echo.
        return getpass.getpass(question + (" [saved; Enter keeps it]" if saved else "") + ": ")

    def show(self, message: str) -> None:
        print(message)


class SetupReads(Protocol):
    async def telegram(
        self,
        token: SecretStr,
        method: Literal["getMe", "getWebhookInfo", "getUpdates", "getChat"],
        *,
        chat_id: int | None = None,
    ) -> object: ...
    async def paper_account(self, key: SecretStr, secret: SecretStr) -> PaperAccountCheck: ...
    async def asset(self, symbol: str, key: SecretStr, secret: SecretStr) -> None: ...
    async def fred(self, key: SecretStr) -> None: ...


@dataclass(frozen=True)
class SetupResult:
    applied: bool
    changed_names: tuple[str, ...]
    waiting: tuple[str, ...]
    backups: tuple[Path, ...] = ()
    doctor: DoctorResult | None = None


def read_environment(path: Path) -> tuple[str, dict[str, str]]:
    """WZ-03: explicit bounded input, duplicate refusal, no interpolation."""
    raw = path.read_bytes().decode("utf-8-sig") if path.exists() else ""
    if len(raw.encode("utf-8")) > 1_048_576:
        raise ConfigurationError("Environment file exceeds the setup size bound")
    names: list[str] = []
    for line in raw.splitlines():
        match = _ENV_LINE.match(line)
        if match:
            names.append(match[1].upper())
        elif line.strip() and not line.lstrip().startswith("#"):
            raise ConfigurationError("Setup requires one complete environment setting per line")
    if len(names) != len(set(names)):
        raise ConfigurationError("Duplicate environment settings must be resolved before setup")
    parsed = dotenv_values(stream=StringIO(raw), interpolate=False)
    values = {key.upper(): value for key, value in parsed.items() if value is not None}
    if len(values) != len(names) or any(
        "\n" in value or "\r" in value for value in values.values()
    ):
        raise ConfigurationError("Setup cannot safely preserve this environment format")
    if any(values.get(name) for name in _CREDENTIAL_NAMES):
        raise ConfigurationError(
            "A plaintext credential exists; migrate it to the keyring before setup"
        )
    if values.get("DB_URL"):
        try:
            if make_url(values["DB_URL"]).password is not None:
                raise ValueError("credential-bearing database URL")
        except Exception:
            raise ConfigurationError(
                "Setup cannot preserve a database password in its environment file"
            ) from None
    return raw, values


def environment_bytes(raw: str, changes: dict[str, str | None]) -> bytes:
    """WZ-07: preserve all other lines and never serialize credential values."""
    if any(name in _CREDENTIAL_NAMES and value is not None for name, value in changes.items()):
        raise ConfigurationError("Setup cannot write a credential to its environment file")
    remaining = dict(changes)
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines: list[str] = []
    for line in raw.splitlines(keepends=True):
        match = _ENV_LINE.match(line)
        if match is None or match[1].upper() not in remaining:
            lines.append(line)
            continue
        name = match[1].upper()
        value = remaining.pop(name)
        if value is not None:
            lines.append(name + "=" + json.dumps(value, ensure_ascii=True) + newline)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += newline
    for name, value in remaining.items():
        if value is not None:
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name) is None:
                raise ConfigurationError("Setup environment name is invalid")
            lines.append(name + "=" + json.dumps(value, ensure_ascii=True) + newline)
    return "".join(lines).encode("utf-8")


def watchlist_bytes(raw: str, symbols: tuple[str, ...]) -> bytes:
    """WZ-07: replace just the top-level watchlist; preserve other YAML bytes."""
    lines = raw.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if re.match(r"^watchlist\s*:", line)]
    if len(starts) != 1:
        raise ConfigurationError("Setup needs one explicit top-level watchlist")
    start = starts[0]
    end = start + 1
    while end < len(lines) and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:", lines[end]):
        end += 1
    newline = "\r\n" if "\r\n" in raw else "\n"
    block = "watchlist:" + newline + "".join("  - " + symbol + newline for symbol in symbols)
    return ("".join(lines[:start]) + block + "".join(lines[end:])).encode("utf-8")


class SetupWizard:
    def __init__(
        self,
        project: Path,
        store: SecretStore,
        reads: SetupReads,
        prompts: Prompts,
        clock: Clock,
        *,
        record: Callable[[tuple[str, ...], dict[str, str]], None],
        doctor: Callable[[], Awaitable[DoctorResult]],
        rolled_back: Callable[[tuple[str, ...]], None] | None = None,
        section: Section | None = None,
    ) -> None:
        self.project, self.store, self.reads, self.io, self.clock = (
            project,
            store,
            reads,
            prompts,
            clock,
        )
        self.record, self.doctor, self.section = record, doctor, section
        self.rolled_back = rolled_back
        self.env_path = setup_path(project, ".env")
        self.yaml_path = setup_path(project, "config/config.yaml")
        self.original_env, self.values = read_environment(self.env_path)
        self.original_yaml = self.yaml_path.read_bytes().decode("utf-8")
        self.registry = InstrumentRegistry.from_csv(project / "config")
        self.config = YamlConfig.model_validate(load_exact_yaml(self.yaml_path))
        self.config.assert_allowed_symbols(self.registry.symbols)
        self.env_changes: dict[str, str | None] = {}
        self.secret_changes: dict[str, SecretStr | None] = {}
        self.waiting: list[str] = []
        self.symbols = self.config.watchlist
        self.watch_changed = False

    def _selected(self, section: Section) -> bool:
        return self.section is None or self.section == section

    def _value(self, name: str) -> str | None:
        return self.env_changes.get(name, self.values.get(name))

    def _secret(self, name: str) -> SecretStr | None:
        return (
            self.secret_changes.get(name) if name in self.secret_changes else self.store.get(name)
        )

    def _hidden(self, name: str, question: str) -> SecretStr | None:
        current = self._secret(name)
        raw = self.io.hidden(question, current is not None)
        value = SecretStr(raw) if raw else current
        if value is not None:
            register_secrets(value)
        return value

    def _yes(self, question: str, default: str = "no") -> bool:
        while True:
            answer = self.io.ask(question + " (yes/no)", default).casefold()
            if answer in {"yes", "no"}:
                return answer == "yes"
            self.io.show("Please type yes or no.")

    async def _check(
        self, label: str, action: Callable[[], Awaitable[ResultT]]
    ) -> tuple[bool, ResultT | None]:
        while True:
            try:
                async with asyncio.timeout(60):
                    return True, await action()
            except (ProviderError, DataIntegrityError, OSError, TimeoutError, ValidationError):
                self.io.show(label + " is UNVERIFIED; the read-only check failed.")
                answer = self.io.ask("Retry this check or skip it?", "retry").casefold()
                if answer == "skip":
                    self.waiting.append(label + ": rerun setup to finish verification.")
                    return False, None
                if answer != "retry":
                    self.io.show("Please type retry or skip.")

    async def _telegram(self) -> None:
        while True:
            token = self._hidden("TELEGRAM_BOT_TOKEN", "Telegram bot token (hidden)")
            if token is None:
                self.secret_changes["TELEGRAM_BOT_TOKEN"] = None
                self.env_changes.update(TELEGRAM_CHAT_ID=None, TELEGRAM_ALLOWED_USER_IDS=None)
                self.waiting.append("Telegram: enter a bot token and confirm your private chat.")
                return
            try:
                ok, me = await self._check(
                    "Telegram bot", partial(self.reads.telegram, token, "getMe")
                )
            except ConfigurationError:
                self.io.show("That token format is invalid. Enter it again.")
                continue
            if not ok:
                self.secret_changes["TELEGRAM_BOT_TOKEN"] = None
                self.env_changes.update(TELEGRAM_CHAT_ID=None, TELEGRAM_ALLOWED_USER_IDS=None)
                return
            if not isinstance(me, dict) or me.get("is_bot") is not True:
                self.io.show("That credential did not identify a bot. Enter it again.")
                continue
            self.secret_changes["TELEGRAM_BOT_TOKEN"] = token
            if (
                me.get("can_join_groups") is not False
                or me.get("can_read_all_group_messages") is not False
            ):
                self.waiting.append(
                    "Telegram: disable group joining and enable privacy in BotFather."
                )
            break
        self.io.show("Send /start to your bot from your phone. Group chats are ignored.")
        while True:
            self.io.ask("Press Enter after sending /start")
            ok, updates = await self._check(
                "Private Telegram chat", lambda: self.reads.telegram(token, "getUpdates")
            )
            if not ok:
                self.env_changes.update(TELEGRAM_CHAT_ID=None, TELEGRAM_ALLOWED_USER_IDS=None)
                return
            candidates: dict[int, PrivateChatCheck] = {}
            if isinstance(updates, list) and len(updates) <= 100:
                for update in updates:
                    if not isinstance(update, dict) or not isinstance(update.get("message"), dict):
                        continue
                    message = update["message"]
                    chat, user = message.get("chat"), message.get("from")
                    text = message.get("text")
                    if (
                        not isinstance(chat, dict)
                        or not isinstance(user, dict)
                        or chat.get("type") != "private"
                        or text != "/start"
                        or user.get("is_bot") is not False
                    ):
                        continue
                    try:
                        display = " ".join(
                            str(user.get(name, "")) for name in ("first_name", "last_name")
                        ).strip()
                        candidate = PrivateChatCheck.model_validate(
                            {
                                "user_id": user.get("id"),
                                "chat_id": chat.get("id"),
                                "display_name": display,
                            }
                        )
                        candidates[candidate.chat_id] = candidate
                    except (ValueError, TypeError):
                        continue
            # Require a single unambiguous identity; do not select a stranger's
            # latest update when multiple private accounts have contacted a bot.
            if len(candidates) != 1:
                self.io.show("One confirmed private /start is needed; no chat was selected.")
                if self.io.ask("Retry or skip private chat?", "retry").casefold() == "skip":
                    self.env_changes.update(TELEGRAM_CHAT_ID=None, TELEGRAM_ALLOWED_USER_IDS=None)
                    self.waiting.append("Telegram: confirm one private account in setup.")
                    return
                continue
            candidate = next(iter(candidates.values()))
            self.io.show(
                "Telegram account: "
                + candidate.display_name.encode("ascii", "backslashreplace").decode("ascii")
            )
            if not self._yes("Is this your account?"):
                self.io.show("No chat was saved.")
                continue
            self.env_changes["TELEGRAM_CHAT_ID"] = str(candidate.chat_id)
            self.env_changes["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([candidate.user_id])
            callback = self._secret("TELEGRAM_CALLBACK_SECRET")
            if callback is None or len(callback.get_secret_value().encode("utf-8")) < 32:
                self.secret_changes["TELEGRAM_CALLBACK_SECRET"] = SecretStr(
                    secrets.token_urlsafe(48)
                )
            return

    async def _alpaca(self) -> None:
        while True:
            key = self._hidden("ALPACA_PAPER_KEY_ID", "Alpaca PAPER key (hidden)")
            secret = self._hidden("ALPACA_PAPER_SECRET", "Alpaca PAPER secret (hidden)")
            if key is None or secret is None:
                self.secret_changes.update(ALPACA_PAPER_KEY_ID=None, ALPACA_PAPER_SECRET=None)
                self.waiting.append("Alpaca paper: enter both matching paper credentials.")
                return
            try:
                ok, account = await self._check(
                    "Alpaca paper account", partial(self.reads.paper_account, key, secret)
                )
            except ConfigurationError:
                self.io.show(
                    "A hidden credential is empty or malformed. Enter the paper pair again."
                )
                continue
            if not ok:
                self.secret_changes.update(ALPACA_PAPER_KEY_ID=None, ALPACA_PAPER_SECRET=None)
                return
            checked = PaperAccountCheck.model_validate(account)
            if (
                checked.status.value != "ACTIVE"
                or checked.account_blocked
                or checked.trading_blocked
                or checked.trade_suspended_by_user
            ):
                self.io.show(
                    "This paper account is not active and unrestricted. Resolve the restriction first."
                )
                if self.io.ask("Retry or skip Alpaca paper?", "retry").casefold() == "skip":
                    self.secret_changes.update(ALPACA_PAPER_KEY_ID=None, ALPACA_PAPER_SECRET=None)
                    self.waiting.append(
                        "Alpaca paper: resolve account restrictions and rerun setup."
                    )
                    return
                continue
            self.secret_changes.update(ALPACA_PAPER_KEY_ID=key, ALPACA_PAPER_SECRET=secret)
            self.io.show(
                f"Paper account status: {checked.status.value}; buying power: ${checked.buying_power:,.2f}."
            )
            # The removed broker fields cannot infer account type. Ask explicitly.
            while True:
                kind = self.io.ask(
                    "Account type shown by Alpaca (CASH/MARGIN)",
                    self._value("BROKER_ACCOUNT_TYPE") or "CASH",
                ).upper()
                if kind in {"CASH", "MARGIN"}:
                    self.env_changes["BROKER_ACCOUNT_TYPE"] = kind
                    return
                self.io.show("Use CASH or MARGIN from your broker account information.")

    async def _watchlist(self) -> None:
        while True:
            answer = self.io.ask(
                "Watchlist tickers, separated by commas", ",".join(self.symbols)
            ).upper()
            symbols = tuple(part.strip() for part in answer.split(","))
            if (
                not symbols
                or len(symbols) > 100
                or len(symbols) != len(set(symbols))
                or not set(symbols) <= set(self.registry.symbols)
            ):
                self.io.show("Use unique tickers from the approved stock and ETF registry.")
                continue
            key, secret = self._secret("ALPACA_PAPER_KEY_ID"), self._secret("ALPACA_PAPER_SECRET")
            if key is None or secret is None:
                self.waiting.append(
                    "Watchlist: paper credentials are required to verify tradable assets."
                )
                return
            valid = True
            for symbol in symbols:
                ok, _ = await self._check(
                    "Watchlist " + symbol,
                    partial(self.reads.asset, symbol, key, secret),
                )
                if not ok:
                    return
            if valid:
                self.symbols, self.watch_changed = symbols, symbols != self.config.watchlist
                return

    def _snapshot(self, changes: dict[str, str | None] | None = None) -> Settings:
        # Validate setup values using a MANUAL paper projection. Existing AUTO
        # flags are preserved byte-for-byte and never entered through setup.
        raw: dict[str, str | None] = dict(self.values)
        raw.update(self.env_changes)
        if changes:
            raw.update(changes)
        values: dict[str, object] = {
            key.lower(): value
            for key, value in raw.items()
            if value is not None and key not in _CREDENTIAL_NAMES
        }
        values.update(
            execution_mode="MANUAL",
            paper_trading=True,
            live_trading_enabled=False,
            live_trading_confirm="",
            llm_enabled=False,
        )
        values.setdefault("broker_account_type", "CASH")
        for old, new in (
            ("llm_price_input_per_mtok", "llm_input_cost_per_million_usd"),
            ("llm_price_output_per_mtok", "llm_output_cost_per_million_usd"),
        ):
            if old in values:
                values[new] = values.pop(old)
        checked = Settings.__new__(Settings)
        Settings.__pydantic_validator__.validate_python(values, self_instance=checked)
        return checked

    def _bounded(self, name: str, question: str) -> None:
        current = self._snapshot()
        default = str(current.model_dump(mode="python")[name.lower()])
        while True:
            answer = self.io.ask(question, default)
            try:
                candidate = self._snapshot({name: answer})
                self.config.assert_settings_consistent(candidate)
            except (ValidationError, ConfigurationError, DataIntegrityError):
                self.io.show(
                    "That value is outside the allowed limits or conflicts with another safety setting."
                )
                continue
            self.env_changes[name] = answer
            return

    async def _risk(self) -> None:
        for name, question in (
            (
                "LLM_DAILY_BUDGET_USD",
                "Daily AI summary budget in dollars (AI stays off unless enabled separately)",
            ),
            ("MAX_RISK_PER_TRADE", "Maximum risk per trade as a fraction (0.01 means 1%)"),
            ("DAILY_LOSS_LIMIT", "Daily loss entry limit as a fraction"),
            ("DD_REDUCE_ONLY", "Drawdown fraction that permits held exits only"),
            ("DD_HALT", "Drawdown fraction that latches a halt"),
            ("CHECKING_BUFFER_USD", "Checking-account safety buffer in dollars"),
            ("MAX_OPEN_POSITIONS", "Maximum number of open positions"),
        ):
            self._bounded(name, question)
        self.io.show(
            "Tax defaults: single, Texas, state rate 0. Federal rates are unknown until entered; estimates are unavailable without them."
        )
        for name, default, question in (
            ("TAX_FILING_STATUS", "single", "Tax filing status"),
            ("TAX_STATE", "Texas", "Tax state"),
            ("TAX_STATE_RATE", "0", "State tax fraction"),
            ("TAX_NIIT_RATE", "0", "NIIT fraction"),
            ("TAX_FED_ST_RATE", "", "Federal short-term fraction; leave blank if unknown"),
            ("TAX_FED_LT_RATE", "", "Federal long-term fraction; leave blank if unknown"),
        ):
            while True:
                answer = self.io.ask(question, self._value(name) or default)
                try:
                    if name == "TAX_STATE":
                        TaxProfile.bounded_state(answer)
                    else:
                        self._snapshot({name: answer or None})
                except (ValidationError, ConfigurationError):
                    self.io.show(
                        "Use a supported status, plain state name, or a tax fraction between 0 and 1."
                    )
                    continue
                self.env_changes[name] = answer or None
                break
        self.io.show(TAX_ESTIMATE_NOTICE)
        for reminder in EXTERNAL_LOT_REMINDERS:
            self.io.show(reminder + "; the app never logs into these accounts.")
        # Owner status note: these are collected in the wizard only. A FRED
        # credential check is not a certification of Stage W feed health.
        while True:
            contact = self.io.ask(
                "SEC filing contact: your name and email; blank keeps it unverified",
                self._value("SEC_USER_AGENT") or "",
            )
            try:
                self._snapshot({"SEC_USER_AGENT": contact or None})
            except (ValidationError, ConfigurationError):
                self.io.show("Enter a name and a valid contact email on one line.")
                continue
            self.env_changes["SEC_USER_AGENT"] = contact or None
            if not contact:
                self.waiting.append("SEC: enter your filing name and email in setup.")
            break
        while True:
            key = self._hidden("FRED_API_KEY", "FRED API key (hidden; blank keeps it unverified)")
            if key is None:
                self.secret_changes["FRED_API_KEY"] = None
                self.waiting.append(
                    "FRED: enter the key in setup; realtime feed health remains unverified until checked."
                )
                break
            try:
                ok, _ = await self._check("FRED credential", partial(self.reads.fred, key))
            except ConfigurationError:
                self.io.show("That hidden credential is malformed. Enter it again.")
                continue
            self.secret_changes["FRED_API_KEY"] = key if ok else None
            self.waiting.append("FRED: realtime feed health still requires Stage W verification.")
            break

    async def run(self) -> SetupResult:
        self.io.show(
            "Setup collects paper settings and stores credentials in the OS keyring. It never turns on auto mode or collects live keys."
        )
        mode = self.values.get("EXECUTION_MODE", "MANUAL")
        if mode.startswith("AUTO_"):
            self.io.show(
                "Existing "
                + mode
                + " is preserved. Host mode command: python -m vws ops resume-auto --operator YOUR_NAME (requires the explicit phrase and Stage I checks). Live setup: python -m vws ops enable-live."
            )
        if self.section is None:
            # Remove empty legacy credential placeholders, never their values.
            self.env_changes.update(
                {name: None for name in _CREDENTIAL_NAMES if name in self.values}
            )
            if not mode.startswith("AUTO_"):
                self.env_changes.update(
                    EXECUTION_MODE="MANUAL",
                    PAPER_TRADING="true",
                    LIVE_TRADING_ENABLED="false",
                    LIVE_TRADING_CONFIRM="",
                )
            self.env_changes.setdefault(
                "BROKER_ACCOUNT_TYPE", self.values.get("BROKER_ACCOUNT_TYPE", "CASH")
            )
            self.env_changes.setdefault(
                "DB_URL", self.values.get("DB_URL", "sqlite:///data/vws-core.sqlite3")
            )
        if self._selected("telegram"):
            await self._telegram()
        if self._selected("alpaca"):
            await self._alpaca()
        if self._selected("watchlist"):
            await self._watchlist()
        if self._selected("risk"):
            await self._risk()
        if self.section is None:
            while not self._yes("Use Central Time for display, with UTC storage?", "yes"):
                self.io.show(
                    "The specified display timezone is Central Time. Cancel with Ctrl-C to leave files unchanged."
                )
            self.env_changes["DISPLAY_TZ"] = "America/Chicago"
        candidate = self._snapshot()
        self.config.assert_settings_consistent(candidate)
        self.io.show("Review settings to save:")
        for name, value in sorted(self.env_changes.items()):
            if name in _CREDENTIAL_NAMES:
                continue
            # SEC contact is private identification and is not printed back.
            self.io.show(
                name
                + ": "
                + ("configured" if name == "SEC_USER_AGENT" and value else value or "unset")
            )
        for name, secret_value in sorted(self.secret_changes.items()):
            self.io.show(
                name
                + ": "
                + (
                    "saved in keyring after confirmation"
                    if secret_value is not None
                    else "unset / UNVERIFIED"
                )
            )
        if self.watch_changed:
            self.io.show("Watchlist: " + ", ".join(self.symbols))
        if not self._yes("Save these settings?"):
            self.io.show("Cancelled. Existing files and keyring entries are unchanged.")
            return SetupResult(False, (), tuple(self.waiting))
        files: dict[str, bytes] = {}
        if self.env_changes:
            files[".env"] = environment_bytes(self.original_env, self.env_changes)
        if self.watch_changed:
            files["config/config.yaml"] = watchlist_bytes(self.original_yaml, self.symbols)
        # Verify the original bytes again before overwriting a concurrent host edit.
        if (
            self.env_path.read_bytes().decode("utf-8-sig") if self.env_path.exists() else ""
        ) != self.original_env or self.yaml_path.read_bytes().decode("utf-8") != self.original_yaml:
            raise DataIntegrityError(
                "Configuration changed during setup; rerun without overwriting it"
            )
        salt = self.store.get("VWS_FINGERPRINT_SALT")
        if salt is None and any(value is not None for value in self.secret_changes.values()):
            salt = SecretStr(base64.b64encode(secrets.token_bytes(32)).decode("ascii"))
            self.secret_changes["VWS_FINGERPRINT_SALT"] = salt
        fingerprints: dict[str, str] = {}
        if salt is not None:
            try:
                salt_bytes = base64.b64decode(salt.get_secret_value(), validate=True)
                if len(salt_bytes) != 32:
                    raise ValueError("invalid salt")
            except ValueError:
                raise ConfigurationError("Existing keyring fingerprint salt is invalid") from None
            for name, secret_value in self.secret_changes.items():
                if secret_value is not None and name != "VWS_FINGERPRINT_SALT":
                    fingerprints[name] = hmac.new(
                        salt_bytes,
                        (name + "\0" + secret_value.get_secret_value()).encode(),
                        hashlib.sha256,
                    ).hexdigest()
        names = tuple(
            sorted(
                {name for name, value in self.env_changes.items() if value != self.values.get(name)}
                | {
                    name
                    for name, value in self.secret_changes.items()
                    if name != "VWS_FINGERPRINT_SALT" and value != self.store.get(name)
                }
                | ({"WATCHLIST"} if self.watch_changed else set())
            )
        )
        with setup_application(
            self.project,
            files,
            self.secret_changes,
            self.store,
            self.clock,
            names,
            lambda changed: self.record(changed, fingerprints),
            self.rolled_back,
        ) as backups:
            try:
                result = await self.doctor()
            except Exception:
                result = None
                self.waiting.append(
                    "Doctor: rerun the read-only checklist; its result is UNVERIFIED."
                )
            if result is not None:
                for line in result.lines():
                    self.io.show(line)
                self.waiting.extend(
                    row.message + " " + row.fix
                    for row in result.checks
                    if row.status not in {"PASS", "NOT_REQUIRED"}
                )
            self.io.show("Waiting on you:")
            for item in self.waiting or ["Nothing right now."]:
                self.io.show(item)
            self.io.show("Saved. Credentials are in the OS keyring; auto mode was not enabled.")
        return SetupResult(True, names, tuple(self.waiting), backups, result)
