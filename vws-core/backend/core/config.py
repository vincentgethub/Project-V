"""R-04/R-06/R-07: frozen settings, hard ceilings, and safe startup guards."""

import hashlib
import json
import os
import re
from collections.abc import Collection, Mapping
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Literal, Self
from urllib.parse import parse_qsl, unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from yaml.nodes import MappingNode, ScalarNode

from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.logging import register_secrets
from backend.core.money import decimal_money, validate_cent_price
from backend.domain.tax_profile import (
    DEFAULT_FILING_STATUS,
    DEFAULT_NIIT_RATE,
    DEFAULT_STATE,
    DEFAULT_STATE_RATE,
    FilingStatus,
    TaxProfile,
)

PAPER_BROKER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_BROKER_ENDPOINT = "https://api.alpaca.markets"
LIVE_CONFIRMATION = "I_ACCEPT_REAL_MONEY_RISK"
MANUAL_CSV_DISABLED_MESSAGE = (
    "MANUAL_CSV is disabled by owner decision (Oct 8 2026); "
    "set BROKER_STATE_SOURCE=ALPACA. Manual funding/state CSV files are not read."
)
YAML_INTEGER_BOUNDS: Mapping[str, tuple[int, int]] = MappingProxyType(
    {
        "monitor_interval_minutes": (1, 1440),
        "offhours_news_interval_minutes": (1, 10080),
        "scheduler_misfire_grace_seconds": (1, 3600),
        "daily_bar_sip_lag_seconds": (960, 3600),
        "daily_scan_delay_minutes": (30, 1440),
        "alert_cooldown_sessions": (1, 30),
    }
)
YAML_ALLOWED_SETTING_NAMES = frozenset(YAML_INTEGER_BOUNDS) | frozenset(
    {"scan_interval_minutes", "offhours_interval_minutes"}
)
KEYRING_ONLY_ENV_NAMES = frozenset(
    {"plaid_access_token", "plaid_token_path", "fernet_key", "fred_api_key"}
)


def _reject_yaml_environment_keys() -> None:
    """R-06/R-07: every strategy/schedule key has exactly one YAML home."""
    if any(name.casefold() in YAML_ALLOWED_SETTING_NAMES for name in os.environ):
        raise ValueError("YAML-only schedule/cooldown settings cannot appear in environment")


def _bounded_integer(value: object, name: str, bounds: tuple[int, int]) -> int:
    """R-06/GD-04: whole integer bounds share logic but keep distinct homes."""
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("integer setting requires a whole integer")
    lower, upper = bounds
    if not lower <= value <= upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return value


def _exact_decimal(value: object) -> Decimal:
    """R-04: never convert a float or boolean into an exact setting."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise ValueError("use Decimal, decimal text, or integer; float is forbidden")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid decimal setting") from exc
    if not result.is_finite():
        raise ValueError("setting must be finite")
    return result


def _bounded_exact_decimal(value: object) -> Decimal:
    """CM/DQ: finite evidence numbers have bounded coefficients and exponents."""
    result = _exact_decimal(value)
    if len(result.as_tuple().digits) > 128 or abs(result.adjusted()) > 128:
        raise ValueError("exact evidence number exceeds supported precision or exponent")
    return result


def _json_exact(value: object) -> object:
    """R-04: parse environment JSON numbers directly into Decimal."""
    if isinstance(value, str):
        try:
            return json.loads(value, parse_float=Decimal)
        except (ValueError, InvalidOperation) as exc:
            raise ValueError("setting requires valid JSON") from exc
    return value


class Settings(BaseSettings):
    """R-06: paper is default; unsafe overrides fail validation at startup.

    R-07: `.env` is never read implicitly. Use ``load_settings(env_file=...)``
    to deliberately load a development dotenv file. Secret fields stay masked.
    """

    model_config = SettingsConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        hide_input_in_errors=True,
        populate_by_name=True,
        case_sensitive=False,
        env_file=None,
        enable_decoding=False,
    )

    def __init__(self, **values: Any) -> None:
        """R-06/R-07: validate required fields from explicit values or env.

        An env-backed required field need not be a Python keyword argument.
        BaseSettings still rejects an absent source or an unknown field.
        """
        super().__init__(**values)

    @classmethod
    def validated_copy(cls, value: "Settings") -> "Settings":
        """R-02/R-07: validate a complete snapshot without rerunning env sources.

        Pydantic's self_instance validation is the same boundary used by
        BaseModel.__init__. It avoids BaseSettings reading later environment
        values while preserving the intentionally unset offline allowlist.
        """
        if not isinstance(value, cls):
            raise ConfigurationError("settings snapshot requires typed Settings")
        values = value.model_dump(mode="python")
        if (
            not value.telegram_allowed_user_ids
            and "telegram_allowed_user_ids" not in value.model_fields_set
        ):
            values.pop("telegram_allowed_user_ids")
        if value.tax_state != DEFAULT_STATE and "tax_state_rate" not in value.model_fields_set:
            raise ConfigurationError("a changed state requires an explicit TAX_STATE_RATE")
        checked = cls.__new__(cls)
        cls.__pydantic_validator__.validate_python(values, self_instance=checked)
        return checked

    # Source constants cannot be raised by an environment variable.
    DECIMAL_BOUNDS: ClassVar[Mapping[str, tuple[Decimal, Decimal]]] = MappingProxyType(
        {
            "max_single_stock_weight": (Decimal("0"), Decimal("0.20")),
            "max_single_etf_weight": (Decimal("0"), Decimal("0.60")),
            "max_risk_per_trade": (Decimal("0"), Decimal("0.02")),
            "stop_slippage_buffer": (Decimal("0.002"), Decimal("0.01")),
            "max_gross_exposure": (Decimal("0"), Decimal("1.00")),
            "min_cash_pct": (Decimal("0.05"), Decimal("1.00")),
            "price_collar": (Decimal("0"), Decimal("0.10")),
            "min_price": (Decimal("5.00"), Decimal("1000000")),
            "max_pct_of_adv": (Decimal("0"), Decimal("0.05")),
            "daily_loss_limit": (Decimal("0"), Decimal("0.05")),
            "dd_reduce_only": (Decimal("0"), Decimal("0.15")),
            "dd_halt": (Decimal("0"), Decimal("0.25")),
            "gap_alert_pct": (Decimal("0"), Decimal("0.25")),
            "checking_buffer_usd": (Decimal("1500"), Decimal("1000000000")),
            "min_margin_equity": (Decimal("2000"), Decimal("1000000000")),
            "min_setup_score": (Decimal("6.0"), Decimal("10.0")),
            "llm_daily_budget_usd": (Decimal("0"), Decimal("20")),
            "auto_min_score": (Decimal("6.0"), Decimal("10.0")),
            "auto_exit_limit_offset": (Decimal("0"), Decimal("0.01")),
        }
    )
    INTEGER_BOUNDS: ClassVar[Mapping[str, tuple[int, int]]] = MappingProxyType(
        {
            "max_open_positions": (1, 30),
            "stale_quote_seconds": (1, 300),
            "max_clock_skew_seconds": (0, 10),
            "liquidity_ttl_seconds": (1, 3600),
            "request_timeout_seconds": (1, 60),
            "earnings_blackout_sessions": (0, 10),
            "max_alerts_per_day": (0, 20),
            "proposal_ttl_sessions": (1, 3),
            "llm_timeout_seconds": (1, 30),
            "llm_max_tokens": (1, 8192),
            "secret_max_age_days": (30, 365),
            "log_retention_days": (7, 365),
            "tg_rate_per_min": (1, 20),
            "tg_heavy_rate_per_min": (1, 5),
            "backup_retention_days": (1, 365),
            "auto_no_trade_open_minutes": (5, 60),
            "auto_no_trade_close_minutes": (10, 60),
            "auto_max_entries_per_day": (1, 10),
            "auto_max_consecutive_order_failures": (1, 3),
            "auto_live_min_paper_sessions": (20, 10000),
        }
    )
    SECRET_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "broker_api_key",
            "broker_secret_key",
            "plaid_client_id",
            "plaid_secret",
            "db_url",
            "llm_api_key",
            "telegram_bot_token",
            "telegram_callback_secret",
            "newsapi_key",
            "healthcheck_ping_url",
        }
    )

    max_single_stock_weight: Decimal = Decimal("0.10")
    max_single_etf_weight: Decimal = Decimal("0.40")
    max_risk_per_trade: Decimal = Decimal("0.01")
    stop_slippage_buffer: Decimal = Decimal("0.002")
    sector_caps: Mapping[str, Decimal] = Field(
        default_factory=lambda: {"Information Technology": Decimal("0.35")}
    )
    theme_caps: Mapping[str, Decimal] = Field(default_factory=lambda: {"AI_SEMIS": Decimal("0.25")})
    max_open_positions: int = 15
    max_gross_exposure: Decimal = Decimal("1.00")
    min_cash_pct: Decimal = Decimal("0.05")
    price_collar: Decimal = Decimal("0.03")
    min_price: Decimal = Decimal("5.00")
    max_pct_of_adv: Decimal = Decimal("0.01")
    daily_loss_limit: Decimal = Decimal("0.02")
    dd_reduce_only: Decimal = Decimal("0.08")
    dd_halt: Decimal = Decimal("0.12")
    stale_quote_seconds: int = 60
    max_clock_skew_seconds: int = 2
    gap_alert_pct: Decimal = Decimal("0.25")
    checking_buffer_usd: Decimal = Decimal("1500")
    reserved_obligations_usd: tuple[Decimal, ...] = ()
    liquidity_ttl_seconds: int = 900
    request_timeout_seconds: int = 30
    wash_sale_mode: Literal["BLOCK", "WARN"] = "BLOCK"
    day_trade_regime: Literal["INTRADAY_MARGIN", "LEGACY_PDT"] = "INTRADAY_MARGIN"
    min_margin_equity: Decimal = Decimal("2000")
    broker_account_type: Literal["CASH", "MARGIN"]
    broker_state_source: Literal["ALPACA", "MANUAL_CSV"] = "ALPACA"
    alpaca_data_plan: Literal["BASIC", "ALGO_TRADER_PLUS"] = "BASIC"
    news_provider: Literal["ALPACA", "RSS", "NEWSAPI"] = "ALPACA"
    sec_user_agent: str | None = Field(default=None, repr=False, max_length=280)
    paper_trading: bool = True
    live_trading_enabled: bool = False
    live_trading_confirm: str = ""
    execution_mode: Literal["MANUAL", "AUTO_PAPER", "AUTO_LIVE"] = "MANUAL"
    auto_min_score: Decimal = Decimal("8.5")
    auto_no_trade_open_minutes: int = 15
    auto_no_trade_close_minutes: int = 15
    auto_max_entries_per_day: int = 5
    auto_max_consecutive_order_failures: int = 3
    auto_live_min_paper_sessions: int = 20
    auto_exits: bool = True
    auto_exit_before_earnings: bool = True
    auto_exit_limit_offset: Decimal = Decimal("0.01")
    live_max_order_notional: Decimal | None = None
    live_max_daily_orders: int | None = None
    live_max_open_positions: int | None = None
    live_max_gross_exposure_pct: Decimal | None = None
    live_max_risk_per_trade: Decimal | None = None
    live_daily_loss_limit: Decimal | None = None
    broker_api_key: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        validation_alias=AliasChoices("BROKER_API_KEY", "ALPACA_API_KEY"),
    )
    broker_secret_key: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        validation_alias=AliasChoices("BROKER_SECRET_KEY", "ALPACA_SECRET_KEY"),
    )
    plaid_client_id: SecretStr = Field(default=SecretStr(""), repr=False)
    plaid_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    plaid_env: Literal["sandbox", "production"] = "sandbox"
    plaid_account_id: str = ""
    db_url: SecretStr = Field(default=SecretStr("sqlite:///vws-core.sqlite3"), repr=False)
    earnings_blackout_sessions: int = 2
    min_setup_score: Decimal = Decimal("7.0")
    max_alerts_per_day: int = 5
    proposal_ttl_sessions: int = 1
    display_tz: str = "America/Chicago"
    enable_intraday_playbooks: bool = False
    # None is an offline-only sentinel; connected research requires explicit values.
    llm_enabled: bool = Field(default=False, strict=True)
    llm_base_url: str | None = None
    llm_model_name: str | None = None
    llm_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    llm_timeout_seconds: int = 30
    llm_max_tokens: int = 1500
    llm_daily_budget_usd: Decimal = Decimal("1.00")
    llm_input_cost_per_million_usd: Decimal | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_PRICE_INPUT_PER_MTOK", "llm_input_cost_per_million_usd"),
    )
    llm_output_cost_per_million_usd: Decimal | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LLM_PRICE_OUTPUT_PER_MTOK", "llm_output_cost_per_million_usd"
        ),
    )
    telegram_bot_token: SecretStr = Field(default=SecretStr(""), repr=False)
    telegram_allowed_user_ids: tuple[int, ...] = ()
    telegram_chat_id: int | None = Field(default=None, strict=True, gt=0, le=2**63 - 1)
    telegram_callback_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    newsapi_key: SecretStr = Field(default=SecretStr(""), repr=False)
    anchor_file_path: Path | None = None
    telegram_mask_amounts: bool = False
    secret_max_age_days: int = 90
    log_retention_days: int = 30
    log_file_path: Path | None = None
    backup_dir: Path = Path("data/backups")
    backup_retention_days: int = 30
    tg_rate_per_min: int = 20
    tg_heavy_rate_per_min: int = 5
    healthcheck_ping_url: SecretStr = Field(default=SecretStr(""), repr=False)
    tax_filing_status: FilingStatus = DEFAULT_FILING_STATUS
    tax_state: str = Field(default=DEFAULT_STATE, min_length=1, max_length=64)
    tax_fed_st_rate: Decimal | None = None
    tax_fed_lt_rate: Decimal | None = None
    tax_state_rate: Decimal | None = DEFAULT_STATE_RATE
    tax_niit_rate: Decimal | None = DEFAULT_NIIT_RATE

    @field_validator(
        "tax_fed_st_rate", "tax_fed_lt_rate", "tax_state_rate", "tax_niit_rate", mode="before"
    )
    @classmethod
    def validate_tax_rate(cls, value: object) -> Decimal | None:
        return TaxProfile.exact_rate(value)

    @field_validator(
        "live_max_order_notional",
        "live_max_gross_exposure_pct",
        "live_max_risk_per_trade",
        "live_daily_loss_limit",
        mode="before",
    )
    @classmethod
    def validate_live_decimal(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        result = _exact_decimal(value)
        decimal_money(result)
        if result <= 0:
            raise ValueError("live limits must be positive exact values")
        if result > Decimal("1000000000"):
            raise ValueError("live limit exceeds the absolute money ceiling")
        return result

    @field_validator("live_max_daily_orders", "live_max_open_positions", mode="before")
    @classmethod
    def validate_live_integer(cls, value: object, info: ValidationInfo) -> int | None:
        if value is None:
            return None
        ceiling = 5 if info.field_name == "live_max_daily_orders" else 30
        return _bounded_integer(value, str(info.field_name), (1, ceiling))

    @property
    def tax_profile(self) -> TaxProfile:
        """TX-08: one profile boundary for setup and future Stage J reports."""
        return TaxProfile(
            filing_status=self.tax_filing_status,
            state=self.tax_state,
            federal_st_rate=self.tax_fed_st_rate,
            federal_lt_rate=self.tax_fed_lt_rate,
            state_rate=self.tax_state_rate,
            niit_rate=self.tax_niit_rate,
        )

    @field_validator("sec_user_agent")
    @classmethod
    def validate_sec_contact(cls, value: str | None) -> str | None:
        """DAT-11/FA-02: public SEC reads require descriptive ASCII contact headers."""
        if value is None:
            return None
        contact = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)
        if (
            not value.strip()
            or any(not 32 <= ord(character) <= 126 for character in value)
            or contact is None
            or len((value[: contact.start()] + value[contact.end() :]).strip()) < 3
        ):
            raise ValueError("SEC_USER_AGENT requires an application/name and contact email")
        return value

    @field_validator("llm_enabled", mode="before")
    @classmethod
    def validate_llm_enabled(cls, value: object) -> bool:
        if type(value) is bool:
            return value
        if isinstance(value, str) and value.casefold() in {"true", "false"}:
            return value.casefold() == "true"
        raise ValueError("LLM_ENABLED requires true or false")

    @model_validator(mode="before")
    @classmethod
    def reject_wrong_configuration_home(cls, value: object) -> object:
        """R-06: process env cannot silently override YAML-only settings."""
        _reject_yaml_environment_keys()
        if any(name.casefold() in KEYRING_ONLY_ENV_NAMES for name in os.environ):
            raise ValueError("Keyring-only credentials cannot appear in environment settings")
        return value

    @field_validator("execution_mode", mode="before")
    @classmethod
    def validate_execution_mode(cls, value: object) -> str:
        """AX-02/SEC-10: an unknown mode cannot enable automatic behavior."""
        return (
            value
            if isinstance(value, str) and value in {"MANUAL", "AUTO_PAPER", "AUTO_LIVE"}
            else "MANUAL"
        )

    @field_validator("display_tz")
    @classmethod
    def validate_display_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("DISPLAY_TZ requires an installed IANA timezone") from None
        return value

    @field_validator("healthcheck_ping_url")
    @classmethod
    def validate_healthcheck_url(cls, value: SecretStr) -> SecretStr:
        """SEC-31: healthcheck URLs remain secret and use authenticated TLS."""
        raw = value.get_secret_value()
        if raw:
            parsed = urlsplit(raw)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
            ):
                raise ValueError("healthcheck URL requires HTTPS without user credentials")
            if parsed.port not in {None, 443}:
                raise ValueError("healthcheck URL requires the standard HTTPS port")
        return value

    @field_validator(*DECIMAL_BOUNDS.keys(), mode="before")
    @classmethod
    def validate_decimal_limit(cls, value: object, info: ValidationInfo) -> Decimal:
        """R-04/R-06: enforce finite exact limits and fixed safety bounds."""
        result = _exact_decimal(value)
        lower, upper = cls.DECIMAL_BOUNDS[str(info.field_name)]
        if not lower <= result <= upper:
            raise ValueError(f"{info.field_name} must be between {lower} and {upper}")
        if info.field_name in {
            "min_price",
            "checking_buffer_usd",
            "min_margin_equity",
            "llm_daily_budget_usd",
        }:
            try:
                decimal_money(result)
            except DataIntegrityError as exc:
                raise ValueError("monetary setting requires micro-unit precision") from exc
        if info.field_name == "min_price":
            try:
                validate_cent_price(result)
            except DataIntegrityError as exc:
                raise ValueError("minimum price requires cent precision") from exc
        return result

    @field_validator(
        "llm_input_cost_per_million_usd", "llm_output_cost_per_million_usd", mode="before"
    )
    @classmethod
    def validate_llm_rate(cls, value: object) -> Decimal | None:
        """GD-01/R-04: unknown prices stay unknown; supplied rates are exact."""
        if value is None:
            return None
        result = _exact_decimal(value)
        if not Decimal("0") <= result <= Decimal("1000"):
            raise ValueError("LLM cost rate must be between 0 and 1000 USD per million tokens")
        try:
            decimal_money(result)
        except DataIntegrityError as exc:
            raise ValueError("LLM cost rate requires supported exact micro-unit precision") from exc
        return result

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_url(cls, value: str | None) -> str | None:
        """GD-01/R-07: configurable HTTPS endpoints cannot hide credentials."""
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or any(char.isspace() for char in value)
            ):
                raise ValueError("unsafe LLM URL")
            _ = parsed.port
        except ValueError as exc:
            raise ValueError(
                "LLM_BASE_URL requires an HTTPS URL without credentials or query"
            ) from exc
        return value

    @field_validator("llm_model_name")
    @classmethod
    def validate_llm_model_name(cls, value: str | None) -> str | None:
        """GD-01: an explicit, nonempty model is mandatory for connected use."""
        if value is not None and (
            not value or value != value.strip() or len(value) > 128 or not value.isprintable()
        ):
            raise ValueError("LLM_MODEL_NAME must be a nonempty trimmed model name")
        return value

    @field_validator("telegram_chat_id", mode="before")
    @classmethod
    def validate_private_chat_id(cls, value: object) -> int | None:
        if value is None:
            return None
        return _bounded_integer(value, "telegram_chat_id", (1, 2**63 - 1))

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def validate_telegram_allowlist(cls, value: object) -> tuple[int, ...]:
        """R-14/GD-05: allowlisted user IDs are unique, strict positive integers."""
        parsed = _json_exact(value)
        if not isinstance(parsed, (tuple, list)):
            raise ValueError("Telegram allowlist requires a JSON array")
        result: list[int] = []
        for user_id in parsed:
            if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
                raise ValueError("Telegram user IDs require positive integers")
            if user_id > 2**63 - 1 or user_id in result:
                raise ValueError("Telegram user IDs require unique 64-bit positive integers")
            result.append(user_id)
        return tuple(result)

    @field_validator(*INTEGER_BOUNDS.keys(), mode="before")
    @classmethod
    def validate_integer_limit(cls, value: object, info: ValidationInfo) -> int:
        """R-06: reject booleans, fractions, and values beyond source bounds."""
        name = str(info.field_name)
        return _bounded_integer(value, name, cls.INTEGER_BOUNDS[name])

    @field_validator("sector_caps", "theme_caps", mode="before")
    @classmethod
    def validate_cap_mapping(cls, value: object, info: ValidationInfo) -> object:
        """CRO-05/R-04: validate all cap values without float conversion."""
        parsed = _json_exact(value)
        if not isinstance(parsed, Mapping) or not parsed:
            raise ValueError("cap mapping must be a nonempty JSON object")
        ceiling = Decimal("0.50") if info.field_name == "sector_caps" else Decimal("0.40")
        result: dict[str, Decimal] = {}
        for key, raw in parsed.items():
            if not isinstance(key, str) or not key.strip() or key != key.strip():
                raise ValueError("cap keys must be nonempty trimmed names")
            cap = _exact_decimal(raw)
            if not Decimal("0") <= cap <= ceiling:
                raise ValueError(f"each {info.field_name} cap must be between 0 and {ceiling}")
            result[key] = cap
        return result

    @field_validator("sector_caps", "theme_caps", mode="after")
    @classmethod
    def freeze_cap_mapping(cls, value: Mapping[str, Decimal]) -> Mapping[str, Decimal]:
        """R-03: prevent nested settings mutation after startup."""
        return MappingProxyType(dict(value))

    @field_serializer("sector_caps", "theme_caps")
    def serialize_cap_mapping(self, value: Mapping[str, Decimal]) -> dict[str, str]:
        """R-04: preserve exact decimals in canonical JSON."""
        return {key: _canonical_decimal(cap) for key, cap in value.items()}

    @field_validator("reserved_obligations_usd", mode="before")
    @classmethod
    def validate_reserved_obligations(cls, value: object) -> tuple[Decimal, ...]:
        """CRO-12/R-04: reservations are immutable nonnegative exact amounts."""
        parsed = _json_exact(value)
        if not isinstance(parsed, (tuple, list)):
            raise ValueError("reservations require a JSON array")
        result: list[Decimal] = []
        for item in parsed:
            try:
                amount = decimal_money(_exact_decimal(item))
            except DataIntegrityError as exc:
                raise ValueError("reservation is not representable money") from exc
            if amount < 0:
                raise ValueError("reservations cannot be negative")
            result.append(amount)
        with localcontext() as context:
            context.prec = 40
            total = sum(result, Decimal("0"))
        if total > Decimal("1000000000"):
            raise ValueError("total reservations exceed the absolute ceiling")
        return tuple(result)

    @field_validator(
        "paper_trading",
        "live_trading_enabled",
        "enable_intraday_playbooks",
        "telegram_mask_amounts",
        "auto_exits",
        "auto_exit_before_earnings",
        mode="before",
    )
    @classmethod
    def validate_mode_flag(cls, value: object) -> bool:
        """R-06: accept explicit booleans only; reject truthy typos."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.casefold() in {"true", "false"}:
            return value.casefold() == "true"
        raise ValueError("mode flag must be true or false")

    @field_validator("db_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        """R-07: keep credential-bearing database URLs masked and validated."""
        raw = value.get_secret_value()
        try:
            parsed = urlsplit(raw)
            valid_scheme = parsed.scheme in {
                "sqlite",
                "sqlite+pysqlite",
                "postgresql",
                "postgresql+psycopg",
                "postgresql+psycopg2",
            }
            if not valid_scheme or not parsed.path or any(char.isspace() for char in raw):
                raise ValueError("unsupported or incomplete database URL")
            if parsed.scheme.startswith("postgresql") and not parsed.hostname:
                raise ValueError("PostgreSQL URL requires a host")
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("invalid database URL") from exc
        return value

    @model_validator(mode="after")
    def validate_startup(self) -> Self:
        """R-06: enforce live consent, keys, and drawdown-tier ordering."""
        if self.dd_reduce_only >= self.dd_halt:
            raise ValueError("DD_REDUCE_ONLY must be below DD_HALT")
        if self.execution_mode != "MANUAL" and self.auto_min_score < self.min_setup_score:
            raise ValueError("AUTO_MIN_SCORE must be at least MIN_SETUP_SCORE")
        for name, live_limit_value, ceiling in (
            (
                "LIVE_MAX_GROSS_EXPOSURE_PCT",
                self.live_max_gross_exposure_pct,
                self.max_gross_exposure,
            ),
            ("LIVE_MAX_RISK_PER_TRADE", self.live_max_risk_per_trade, self.max_risk_per_trade),
            ("LIVE_DAILY_LOSS_LIMIT", self.live_daily_loss_limit, self.daily_loss_limit),
            ("LIVE_MAX_OPEN_POSITIONS", self.live_max_open_positions, self.max_open_positions),
        ):
            if live_limit_value is not None and live_limit_value > ceiling:
                raise ValueError(f"{name} exceeds its CRO ceiling")
        if self.tax_state != DEFAULT_STATE and "tax_state_rate" not in self.model_fields_set:
            raise ValueError("a changed state requires an explicit TAX_STATE_RATE")
        _ = self.tax_profile
        if self.llm_enabled:
            try:
                self.assert_llm_call_budget_ready()
            except ConfigurationError as exc:
                raise ValueError(str(exc)) from exc
        if (
            "telegram_allowed_user_ids" in self.model_fields_set
            and not self.telegram_allowed_user_ids
        ):
            raise ValueError("an explicitly configured Telegram allowlist cannot be empty")
        if not self.paper_trading:
            if not self.live_trading_enabled:
                raise ValueError("live mode requires LIVE_TRADING_ENABLED=true")
            if self.live_trading_confirm != LIVE_CONFIRMATION:
                raise ValueError("live mode requires exact LIVE_TRADING_CONFIRM")
            if not self.broker_api_key.get_secret_value().strip():
                raise ValueError("live mode requires a broker API key")
            if not self.broker_secret_key.get_secret_value().strip():
                raise ValueError("live mode requires a broker secret key")
        register_secrets(*(self.__dict__[name] for name in self.SECRET_FIELDS))
        database_url = urlsplit(self.db_url.get_secret_value())
        if database_url.password:
            register_secrets(unquote(database_url.password))
        for key, value in parse_qsl(database_url.query):
            if any(part in key.casefold() for part in ("password", "token", "secret", "key")):
                register_secrets(value)
        return self

    def assert_research_ready(self) -> None:
        """GD-01/R-02: connected research must supply endpoint, model, and key."""
        if (
            self.llm_base_url is None
            or self.llm_model_name is None
            or not self.llm_api_key.get_secret_value().strip()
        ):
            raise ConfigurationError("connected research requires LLM URL, model, and API key")

    def assert_llm_call_budget_ready(self) -> None:
        """GD-01: zero budgets and unknown cost rates prohibit budgeted calls."""
        self.assert_research_ready()
        if self.llm_daily_budget_usd <= 0:
            raise ConfigurationError("LLM calls are disabled by a zero daily budget")
        if (
            self.llm_input_cost_per_million_usd is None
            or self.llm_output_cost_per_million_usd is None
        ):
            raise ConfigurationError("LLM calls require explicit input and output token cost rates")

    def assert_telegram_ready(self) -> None:
        """R-14/GD-05: production callbacks cannot start without an allowlist."""
        if (
            not self.telegram_bot_token.get_secret_value().strip()
            or not self.telegram_allowed_user_ids
            or len(self.telegram_callback_secret.get_secret_value().encode("utf-8")) < 32
            or not self.telegram_callback_secret.get_secret_value().strip()
        ):
            raise ConfigurationError(
                "Telegram requires a bot token, nonempty user allowlist, and 32-byte callback secret"
            )

    @property
    def broker_endpoint(self) -> str:
        """R-06: derive the sole permissible trading endpoint from mode."""
        return PAPER_BROKER_ENDPOINT if self.paper_trading else LIVE_BROKER_ENDPOINT

    def nonsecret_snapshot(self) -> dict[str, object]:
        """R-07: canonical configuration without keys or database credentials."""
        result: dict[str, object] = {}
        for name in type(self).model_fields:
            if name not in self.SECRET_FIELDS:
                result[name] = _canonical_value(self.__dict__[name])
        url = urlsplit(self.db_url.get_secret_value())
        result["database_identity"] = {
            "driver": url.scheme,
            "host": url.hostname,
            "port": url.port,
            "database": url.path,
        }
        return result

    @property
    def config_hash(self) -> str:
        """R-03/R-07: stamp canonical nonsecret policy on every verdict."""
        encoded = json.dumps(
            self.nonsecret_snapshot(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def with_yaml_hash(self, yaml_config: "YamlConfig") -> str:
        """R-03/GD-02: combine nonsecret env policy and validated research YAML."""
        yaml_config.assert_settings_consistent(self)
        payload = {"settings": self.nonsecret_snapshot(), "yaml": yaml_config.nonsecret_snapshot()}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_decimal(value: Decimal) -> str:
    """R-04: use identical text for numerically identical finite decimals."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if value == 0 else text


def _canonical_value(value: object) -> object:
    """R-07: recursively encode exact immutable configuration values."""
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseModel):
        return {name: _canonical_value(value.__dict__[name]) for name in type(value).model_fields}
    return value


def assert_broker_endpoint(settings: Settings, resolved_endpoint: str) -> None:
    """R-06: assert the initialized SDK client's exact mode-specific endpoint.

    Accept one trailing slash only. Reject paths, query strings, alternate hosts,
    and endpoint switches. The read-only broker adapter must call this at startup.
    """
    if not isinstance(resolved_endpoint, str):
        raise ConfigurationError("broker endpoint must be a string")
    if resolved_endpoint.removesuffix("/") != settings.broker_endpoint:
        raise ConfigurationError("broker endpoint does not match configured trading mode")


def load_settings(env_file: str | Path | None = None, **overrides: Any) -> Settings:
    """R-06/R-07: explicitly load dotenv only when requested; fail typed."""
    try:
        values: dict[str, Any] = {"_env_file": env_file, **overrides}
        return Settings(**values)
    except (ValidationError, ValueError, TypeError, OSError) as exc:
        raise ConfigurationError("configuration validation failed") from exc


class _FrozenYamlModel(BaseModel):
    """R-03/GD-02: YAML policy objects are strict and recursively immutable."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ScheduleConfig(_FrozenYamlModel):
    """GD-04: bounded deterministic schedule, without risk controls."""

    scheduler_misfire_grace_seconds: int = 60
    daily_bar_sip_lag_seconds: int = 960
    daily_scan_delay_minutes: int = 30
    monitor_interval_minutes: int = 15
    offhours_news_interval_minutes: int = 60

    @field_validator(
        "scheduler_misfire_grace_seconds",
        "daily_bar_sip_lag_seconds",
        "daily_scan_delay_minutes",
        "monitor_interval_minutes",
        "offhours_news_interval_minutes",
        mode="before",
    )
    @classmethod
    def validate_interval(cls, value: object, info: ValidationInfo) -> int:
        """GD-04/R-02: schedule bounds belong exclusively to YAML."""
        name = str(info.field_name)
        return _bounded_integer(value, name, YAML_INTEGER_BOUNDS[name])


class AlertConfig(_FrozenYamlModel):
    """GD-04: a session cooldown suppresses repeated setup cards."""

    alert_cooldown_sessions: int = 1

    @field_validator("alert_cooldown_sessions", mode="before")
    @classmethod
    def validate_cooldown(cls, value: object, info: ValidationInfo) -> int:
        """GD-04: require at least one session between repeated cards."""
        name = str(info.field_name)
        return _bounded_integer(value, name, YAML_INTEGER_BOUNDS[name])


class EgressHost(_FrozenYamlModel):
    """SEC-31: every extra DNS host requires a visible operator comment."""

    host: str
    comment: str = Field(min_length=1, max_length=280)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        """SEC-31: exact DNS identities, no URLs, literals, ports or wildcards."""
        import ipaddress

        try:
            ipaddress.ip_address(value)
        except ValueError:
            if (
                not value.isascii()
                or len(value) > 253
                or "." not in value
                or any(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                    for label in value.split(".")
                )
            ):
                raise ValueError("extra egress host requires a lowercase DNS name") from None
            return value
        raise ValueError("extra egress host cannot be an IP literal")

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str) -> str:
        """SEC-31: a comment cannot consist of whitespace or control characters."""
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("extra egress host requires a readable justification")
        return value


class EgressConfig(_FrozenYamlModel):
    """SEC-31: explicit immutable additional public egress identities."""

    extra_hosts: tuple[EgressHost, ...] = Field(default=(), max_length=100)

    @field_validator("extra_hosts")
    @classmethod
    def validate_unique_hosts(cls, value: tuple[EgressHost, ...]) -> tuple[EgressHost, ...]:
        """SEC-31: duplicate grants fail rather than hiding a conflicting comment."""
        if len({entry.host for entry in value}) != len(value):
            raise ValueError("extra egress hosts cannot be duplicated")
        return value


class NewsConfig(_FrozenYamlModel):
    """DAT-09/SEC-31: explicitly configured, bounded public RSS feeds."""

    rss_urls: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("rss_urls")
    @classmethod
    def validate_rss_urls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """SEC-30/31: RSS grants require HTTPS DNS identities without credentials."""
        if len(set(value)) != len(value):
            raise ValueError("RSS URLs cannot be duplicated")
        for url in value:
            if len(url) > 2048 or not url.isascii() or any(ord(char) <= 32 for char in url):
                raise ValueError("RSS URL is malformed or exceeds its boundary")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 443}
                or parsed.fragment
            ):
                raise ValueError("RSS URL requires an ordinary HTTPS destination")
            EgressHost.validate_host(parsed.hostname)
        return value


class FundamentalsConfig(_FrozenYamlModel):
    """FA-01..09: exact mandated thresholds, distinct from portfolio risk limits."""

    enabled: bool = True
    mode: Literal["annotate", "require"] = "annotate"
    gross_margin_min: Decimal = Decimal("0.40")
    operating_margin_min: Decimal = Decimal("0.15")
    roic_min: Decimal = Decimal("0.10")
    fcf_min: Decimal = Decimal("0")
    interest_coverage_min: Decimal = Decimal("3.0")
    exempt_sectors: tuple[str, ...] = ("Financials", "Real Estate")
    max_filing_age_days: int = Field(default=200, strict=True, ge=1, le=200)
    cache_hours: int = Field(default=24, strict=True, ge=1, le=24)

    @field_validator(
        "gross_margin_min",
        "operating_margin_min",
        "roic_min",
        "fcf_min",
        "interest_coverage_min",
        mode="before",
    )
    @classmethod
    def exact_framework_thresholds(cls, value: object, info: ValidationInfo) -> Decimal:
        thresholds = {
            "gross_margin_min": Decimal("0.40"),
            "operating_margin_min": Decimal("0.15"),
            "roic_min": Decimal("0.10"),
            "fcf_min": Decimal("0"),
            "interest_coverage_min": Decimal("3.0"),
        }
        number = _exact_decimal(value)
        if number != thresholds[info.field_name or ""]:
            raise ValueError("fundamental thresholds must match the mandated strict framework")
        return number

    @field_validator("exempt_sectors")
    @classmethod
    def valid_exempt_sectors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        from backend.domain.instruments import GICS_SECTORS

        if (
            len(value) > 11
            or len(set(value)) != len(value)
            or not set(value).issubset(GICS_SECTORS)
        ):
            raise ValueError("fundamental exemptions require unique known GICS sectors")
        return value

    @model_validator(mode="after")
    def required_framework_is_enabled(self) -> Self:
        if self.mode == "require" and not self.enabled:
            raise ValueError("required fundamentals cannot be disabled")
        return self


class SizingConfig(_FrozenYamlModel):
    """GD-03: deterministic target sizing, capped again by the CRO."""

    target_risk_per_trade: Decimal = Decimal("0.005")
    max_stop_pct: Decimal = Decimal("0.12")
    stop_atr_mult: Decimal = Decimal("2.0")
    target_r: Decimal = Decimal("2.0")
    swing_lookback: int = Field(default=10, strict=True, ge=1, le=60)

    @field_validator(
        "target_risk_per_trade", "max_stop_pct", "stop_atr_mult", "target_r", mode="before"
    )
    @classmethod
    def exact_sizing_bounds(cls, value: object, info: ValidationInfo) -> Decimal:
        bounds = {
            "target_risk_per_trade": (Decimal("0.000001"), Decimal("0.01")),
            "max_stop_pct": (Decimal("0.000001"), Decimal("0.12")),
            "stop_atr_mult": (Decimal("0.5"), Decimal("10")),
            "target_r": (Decimal("1.5"), Decimal("10")),
        }
        number = _exact_decimal(value)
        lower, upper = bounds[info.field_name or ""]
        if not lower <= number <= upper:
            raise ValueError("sizing parameter exceeds its specified bounds")
        decimal_money(number)
        return number


class SpreadFloorsConfig(_FrozenYamlModel):
    """CM-01: liquidity floors may be raised, never silently weakened."""

    high: Decimal = Decimal(2)
    mid: Decimal = Decimal(5)
    low: Decimal = Decimal(15)

    @field_validator("high", "mid", "low", mode="before")
    @classmethod
    def exact_floors(cls, value: object, info: ValidationInfo) -> Decimal:
        number = _exact_decimal(value)
        minimum = {"high": Decimal(2), "mid": Decimal(5), "low": Decimal(15)}
        if not minimum[info.field_name or ""] <= number <= 1000:
            raise ValueError("CM-01: spread floors cannot be reduced or exceed 1000 bps")
        decimal_money(number)
        return number

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.high <= self.mid <= self.low:
            raise ValueError("CM-01: liquidity floors must be ordered")
        return self


class CostModelConfig(_FrozenYamlModel):
    """CM-01..03: fixed conservative simulation parameters, never an optimizer."""

    spread_floor_bps: SpreadFloorsConfig = Field(default_factory=SpreadFloorsConfig)
    stop_slip_atr_frac: Decimal = Decimal("0.05")
    max_participation: Decimal = Decimal("0.01")

    @field_validator("stop_slip_atr_frac", "max_participation", mode="before")
    @classmethod
    def exact_bounds(cls, value: object, info: ValidationInfo) -> Decimal:
        number = _exact_decimal(value)
        lower, upper = (
            (Decimal("0.05"), Decimal(1))
            if info.field_name == "stop_slip_atr_frac"
            else (Decimal("0.000001"), Decimal("0.01"))
        )
        if not lower <= number <= upper:
            raise ValueError("CM-02/03: cost/participation parameter weakens the baseline")
        decimal_money(number)
        return number


class EvaluationConfig(_FrozenYamlModel):
    """EV-01: the fixed baseline holding period; registered variants follow V."""

    max_hold_sessions: int = Field(default=20, strict=True, ge=1, le=30)


class PlaybookConfig(_FrozenYamlModel):
    """GD-02/R-04: exact weights; level parameters have one home in sizing."""

    criteria_weights: Mapping[str, Decimal]

    @field_validator("criteria_weights", mode="before")
    @classmethod
    def validate_weights(cls, value: object) -> Mapping[str, Decimal]:
        """GD-02: criterion weights must be positive and sum to exactly one."""
        if not isinstance(value, Mapping) or not 1 <= len(value) <= 32:
            raise ValueError("criteria_weights requires 1 to 32 named criteria")
        _reject_yaml_risk_keys(value)
        result: dict[str, Decimal] = {}
        for name, raw in value.items():
            if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) is None:
                raise ValueError("criterion names require lowercase identifiers")
            weight = _exact_decimal(raw)
            if not Decimal("0") < weight <= Decimal("1"):
                raise ValueError("criterion weights must be in (0, 1]")
            try:
                decimal_money(weight)
            except DataIntegrityError as exc:
                raise ValueError("criterion weights require at most six decimal places") from exc
            result[name] = weight
        with localcontext() as context:
            context.prec = 40
            total = sum(result.values(), Decimal("0"))
        if total != Decimal("1"):
            raise ValueError("criterion weights must sum to exactly 1")
        return result

    @field_validator("criteria_weights", mode="after")
    @classmethod
    def freeze_weights(cls, value: Mapping[str, Decimal]) -> Mapping[str, Decimal]:
        """R-03: freeze weights after Pydantic has copied the mapping."""
        return MappingProxyType(dict(value))

    @field_serializer("criteria_weights")
    def serialize_weights(self, value: Mapping[str, Decimal]) -> dict[str, str]:
        """R-04: preserve exact weights in JSON snapshots."""
        return {name: _canonical_decimal(weight) for name, weight in value.items()}


class YamlConfig(_FrozenYamlModel):
    """GD-02/R-03: research configuration cannot modify env risk limits."""

    watchlist: tuple[str, ...]
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    egress: EgressConfig = Field(default_factory=EgressConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    fundamentals: FundamentalsConfig = Field(default_factory=FundamentalsConfig)
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    cm: CostModelConfig = Field(default_factory=CostModelConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    playbooks: Mapping[str, PlaybookConfig]

    @model_validator(mode="before")
    @classmethod
    def reject_risk_limits(cls, value: object) -> object:
        """R-06: reject risk keys even when concealed in nested dictionaries."""
        _reject_yaml_risk_keys(value)
        return value

    @field_validator("watchlist", mode="before")
    @classmethod
    def validate_watchlist(cls, value: object) -> tuple[str, ...]:
        """R-02: keep explicit known symbol identities, without normalization."""
        if not isinstance(value, (tuple, list)) or not 1 <= len(value) <= 1000:
            raise ValueError("watchlist requires 1 to 1000 symbols")
        result: list[str] = []
        for symbol in value:
            if (
                not isinstance(symbol, str)
                or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) is None
            ):
                raise ValueError("watchlist symbols must be uppercase US instrument identifiers")
            if symbol in result:
                raise ValueError("watchlist symbols cannot be duplicated")
            result.append(symbol)
        return tuple(result)

    @field_validator("playbooks", mode="after")
    @classmethod
    def validate_playbooks(
        cls, value: Mapping[str, PlaybookConfig]
    ) -> Mapping[str, PlaybookConfig]:
        """GD-02: only the three specified daily playbooks are configurable."""
        expected = {"TREND_50EMA", "BASE_BREAKOUT", "ANCHORED_VWAP_RECLAIM"}
        if set(value) != expected:
            raise ValueError("playbooks must define exactly the three supported daily strategies")
        criteria = {
            "TREND_50EMA": {
                "trend",
                "slope",
                "pullback",
                "range_position",
                "relative_volume",
                "rsi",
            },
            "BASE_BREAKOUT": {
                "breakout",
                "relative_volume",
                "base_range",
                "trend",
                "rsi",
                "range_position",
            },
            "ANCHORED_VWAP_RECLAIM": {
                "reclaim",
                "relative_volume",
                "slope",
                "atr_risk",
                "rsi",
                "range_position",
            },
        }
        if any(set(config.criteria_weights) != criteria[name] for name, config in value.items()):
            raise ValueError("each daily playbook must use its six specified criteria")
        return MappingProxyType(dict(value))

    @field_serializer("playbooks")
    def serialize_playbooks(self, value: Mapping[str, PlaybookConfig]) -> dict[str, object]:
        """GD-02: canonicalize the immutable playbook map for audit snapshots."""
        return {name: _canonical_value(playbook) for name, playbook in value.items()}

    def assert_allowed_symbols(self, allowed_symbols: Collection[str]) -> None:
        """R-02: authoritative instrument symbols must cover the full watchlist."""
        if not allowed_symbols or not set(self.watchlist).issubset(set(allowed_symbols)):
            raise ConfigurationError("watchlist contains an unknown or unconfigured instrument")

    def assert_settings_consistent(self, settings: Settings) -> None:
        """R-02/GD-04: wrong-home keys fail even when their values agree."""
        try:
            _reject_yaml_environment_keys()
            if YAML_ALLOWED_SETTING_NAMES.intersection(settings.__dict__) or (
                YAML_ALLOWED_SETTING_NAMES.intersection(settings.model_fields_set)
            ):
                raise ValueError("YAML-only schedule/cooldown settings cannot appear in Settings")
            if self.sizing.target_risk_per_trade > settings.max_risk_per_trade:
                raise ValueError("target sizing risk cannot exceed the CRO risk limit")
        except ValueError as exc:
            raise ConfigurationError("YAML-only settings are configured in the wrong home") from exc

    def nonsecret_snapshot(self) -> dict[str, object]:
        """R-03/GD-02: deterministic exact-value snapshot suitable for hashing."""
        return {name: _canonical_value(self.__dict__[name]) for name in type(self).model_fields}

    @property
    def config_hash(self) -> str:
        """R-03: include all strategy parameters in research configuration identity."""
        encoded = json.dumps(
            self.nonsecret_snapshot(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


YAML_FORBIDDEN_SETTING_NAMES = frozenset(Settings.model_fields)


def _reject_yaml_risk_keys(value: object, depth: int = 0) -> None:
    """R-06/R-12: no secret/env risk keys, recursion, or deeply nested input."""
    if depth > 20:
        raise ValueError("YAML nesting exceeds the configuration limit")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("YAML mapping keys must be strings")
            normalized = key.strip().casefold().replace("-", "_")
            if normalized in YAML_FORBIDDEN_SETTING_NAMES:
                raise ValueError("YAML cannot contain env risk, credential, or runtime settings")
            _reject_yaml_risk_keys(item, depth + 1)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _reject_yaml_risk_keys(item, depth + 1)


class _ExactSafeLoader(yaml.SafeLoader):
    """R-04/R-12: safe YAML with exact decimals and no ambiguous duplicates."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[object, object]:
        """R-02: duplicate mapping keys cannot silently override prior policy."""
        keys: set[object] = set()
        for key_node, _value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                raise ValueError("YAML mapping keys must be scalars")
            key = self.construct_object(key_node, deep=deep)
            if key in keys:
                raise ValueError("duplicate YAML mapping key")
            keys.add(key)
        return dict(super().construct_mapping(node, deep=deep))


def _yaml_decimal(loader: _ExactSafeLoader, node: ScalarNode) -> Decimal:
    """R-04: YAML decimal scalars never pass through a binary float."""
    return _exact_decimal(loader.construct_scalar(node))


_ExactSafeLoader.add_constructor("tag:yaml.org,2002:float", _yaml_decimal)


def load_exact_yaml(path: str | Path) -> object:
    """R-04/R-12: shared bounded, duplicate-free, exact-decimal YAML read."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        if len(raw.encode("utf-8")) > 1_048_576:
            raise ValueError("YAML configuration exceeds one MiB")
        depth = 0
        for token in yaml.scan(raw):
            if isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)):
                raise ValueError("YAML aliases and anchors are forbidden")
            if isinstance(
                token,
                (
                    yaml.tokens.BlockMappingStartToken,
                    yaml.tokens.BlockSequenceStartToken,
                    yaml.tokens.FlowMappingStartToken,
                    yaml.tokens.FlowSequenceStartToken,
                ),
            ):
                depth += 1
                if depth > 20:
                    raise ValueError("YAML nesting exceeds the configuration limit")
            elif isinstance(
                token,
                (
                    yaml.tokens.BlockEndToken,
                    yaml.tokens.FlowMappingEndToken,
                    yaml.tokens.FlowSequenceEndToken,
                ),
            ):
                depth -= 1
        # SafeLoader subclass: no arbitrary Python object constructors.
        return yaml.load(raw, Loader=_ExactSafeLoader)  # nosec B506
    except (yaml.YAMLError, ValueError, TypeError, OSError) as exc:
        raise ConfigurationError("YAML configuration validation failed") from exc


def load_yaml_config(
    path: str | Path,
    *,
    allowed_symbols: Collection[str],
    settings: Settings | None = None,
) -> YamlConfig:
    """GD-02/R-02: load frozen policy and enforce instrument/env identity."""
    try:
        config = YamlConfig.model_validate(load_exact_yaml(path))
        config.assert_allowed_symbols(allowed_symbols)
        if settings is not None:
            config.assert_settings_consistent(settings)
        return config
    except (yaml.YAMLError, ValidationError, ValueError, TypeError, OSError) as exc:
        raise ConfigurationError("YAML configuration validation failed") from exc
