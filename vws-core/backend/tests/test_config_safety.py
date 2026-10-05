"""R-04/R-05/R-06/R-07: configuration safety and exact startup boundaries."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from backend.core.clock import FrozenClock, SystemClock, ensure_utc
from backend.core.config import (
    LIVE_BROKER_ENDPOINT,
    LIVE_CONFIRMATION,
    PAPER_BROKER_ENDPOINT,
    Settings,
    assert_broker_endpoint,
    load_settings,
)
from backend.core.errors import ConfigurationError, DataIntegrityError


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-07: test settings never depend on real credentials or environment."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setenv("BROKER_ACCOUNT_TYPE", "CASH")


def test_R_06_broker_account_type_is_required_without_an_implicit_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-06/CMP-03: only the owner/provider supplies the account-type choice."""
    assert Settings.model_fields["broker_account_type"].is_required()
    monkeypatch.delenv("BROKER_ACCOUNT_TYPE")
    with pytest.raises(ValidationError, match="broker_account_type"):
        Settings()
    with pytest.raises(ConfigurationError, match="configuration validation"):
        load_settings()
    assert Settings(broker_account_type="CASH").broker_account_type == "CASH"
    assert Settings(broker_account_type="MARGIN").broker_account_type == "MARGIN"


def test_R_06_paper_defaults_and_exact_endpoint() -> None:
    settings = Settings()
    assert settings.paper_trading
    assert not settings.live_trading_enabled
    assert settings.broker_endpoint == PAPER_BROKER_ENDPOINT
    assert_broker_endpoint(settings, PAPER_BROKER_ENDPOINT)
    assert_broker_endpoint(settings, PAPER_BROKER_ENDPOINT + "/")


@pytest.mark.parametrize(
    "endpoint",
    [
        LIVE_BROKER_ENDPOINT,
        PAPER_BROKER_ENDPOINT + "/v2",
        PAPER_BROKER_ENDPOINT + "?paper=true",
        f"{'http'}://paper-api.alpaca.markets",
        PAPER_BROKER_ENDPOINT + "//",
    ],
)
def test_R_06_endpoint_mismatch_fails_closed(endpoint: str) -> None:
    with pytest.raises(ConfigurationError):
        assert_broker_endpoint(Settings(), endpoint)


@pytest.mark.parametrize("missing", ["enabled", "confirm", "api_key", "secret_key"])
def test_R_06_each_missing_live_condition_raises(missing: str) -> None:
    values: dict[str, Any] = {
        "paper_trading": False,
        "live_trading_enabled": True,
        "live_trading_confirm": LIVE_CONFIRMATION,
        "broker_api_key": SecretStr("test-only-live-api"),
        "broker_secret_key": SecretStr("test-only-live-secret"),
    }
    fields = {
        "enabled": "live_trading_enabled",
        "confirm": "live_trading_confirm",
        "api_key": "broker_api_key",
        "secret_key": "broker_secret_key",
    }
    values.pop(fields[missing])
    with pytest.raises(ValidationError):
        Settings(**values)


def test_R_06_all_live_conditions_and_endpoint_assertion() -> None:
    settings = Settings(
        paper_trading=False,
        live_trading_enabled=True,
        live_trading_confirm=LIVE_CONFIRMATION,
        broker_api_key=SecretStr("test-only-complete-api"),
        broker_secret_key=SecretStr("test-only-complete-secret"),
    )
    assert settings.broker_endpoint == LIVE_BROKER_ENDPOINT
    assert_broker_endpoint(settings, LIVE_BROKER_ENDPOINT)
    with pytest.raises(ConfigurationError):
        assert_broker_endpoint(settings, PAPER_BROKER_ENDPOINT)


@pytest.mark.parametrize("field,bounds", list(Settings.DECIMAL_BOUNDS.items()))
def test_R_06_decimal_ceiling_boundary_and_oversized_rejection(
    field: str, bounds: tuple[Decimal, Decimal]
) -> None:
    upper = bounds[1]
    values: dict[str, Any] = {field: upper}
    if field == "dd_reduce_only":
        values["dd_halt"] = Decimal("0.25")
    assert Settings(**values).__dict__[field] == upper
    values[field] = upper + Decimal("0.01")
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("field,bounds", list(Settings.INTEGER_BOUNDS.items()))
def test_R_06_integer_ceiling_boundary_and_oversized_rejection(
    field: str, bounds: tuple[int, int]
) -> None:
    values: dict[str, Any] = {field: bounds[1]}
    assert Settings(**values).__dict__[field] == bounds[1]
    values[field] = bounds[1] + 1
    with pytest.raises(ValidationError):
        Settings(**values)
    values[field] = True
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("bad", [float("0.1"), True, "NaN", "Infinity", None])
def test_R_04_decimal_limits_reject_inexact_or_missing_values(bad: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(max_single_stock_weight=bad)


def test_R_06_conservative_security_floors_and_drawdown_ordering() -> None:
    for field, value in {
        "min_cash_pct": Decimal("0.049"),
        "min_price": Decimal("4.99"),
        "checking_buffer_usd": Decimal("1499.99"),
        "min_margin_equity": Decimal("1999.99"),
        "stop_slippage_buffer": Decimal("0.0019"),
    }.items():
        values: dict[str, Any] = {field: value}
        with pytest.raises(ValidationError):
            Settings(**values)
    with pytest.raises(ValidationError):
        Settings(dd_reduce_only=Decimal("0.12"), dd_halt=Decimal("0.12"))


def test_R_03_settings_and_nested_caps_are_immutable() -> None:
    original = {"Information Technology": Decimal("0.35")}
    settings = Settings(sector_caps=original)
    original["Information Technology"] = Decimal("0.99")
    assert settings.sector_caps["Information Technology"] == Decimal("0.35")
    with pytest.raises(ValidationError):
        settings.max_open_positions = 30
    with pytest.raises(TypeError):
        settings.sector_caps["Information Technology"] = Decimal("0.40")  # type: ignore[index]


def test_R_04_environment_json_uses_exact_decimal_and_caps_have_ceilings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECTOR_CAPS", '{"Information Technology": 0.35}')
    monkeypatch.setenv("RESERVED_OBLIGATIONS_USD", '[100.01, "250.25"]')
    settings = Settings()
    assert settings.sector_caps["Information Technology"] == Decimal("0.35")
    assert settings.reserved_obligations_usd == (Decimal("100.01"), Decimal("250.25"))
    monkeypatch.setenv("SECTOR_CAPS", '{"Information Technology": 0.500001}')
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "value",
    [[], {}, {"": Decimal("0.3")}, {"AI": Decimal("0.41")}, {"AI": float("0.2")}, "not-json"],
)
def test_CRO_05_bad_theme_caps_rejected(value: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(theme_caps=value)


def test_R_07_config_hash_is_canonical_nonsecret_and_policy_sensitive() -> None:
    first = Settings(
        sector_caps={"B": Decimal("0.20"), "A": Decimal("0.300")},
        broker_api_key=SecretStr("test-only-key-a"),
        db_url=SecretStr("postgresql://alice:private-a@localhost/vws?password=private-query"),
    )
    second = Settings(
        sector_caps={"A": Decimal("0.3"), "B": Decimal("0.2")},
        broker_api_key=SecretStr("test-only-key-b"),
        db_url=SecretStr("postgresql://bob:private-b@localhost/vws"),
    )
    assert first.config_hash == second.config_hash
    assert len(first.config_hash) == 64
    assert Settings(max_single_stock_weight=Decimal("0.09")).config_hash != Settings().config_hash
    text = repr(first) + str(first.nonsecret_snapshot()) + first.model_dump_json()
    for secret in ("test-only-key-a", "private-a", "private-query"):
        assert secret not in text


def test_R_07_dotenv_is_explicit_and_factory_errors_are_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MAX_SINGLE_STOCK_WEIGHT=0.09\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert Settings().max_single_stock_weight == Decimal("0.10")
    assert load_settings(env_file=env_file).max_single_stock_weight == Decimal("0.09")
    with pytest.raises(ConfigurationError):
        load_settings(max_single_stock_weight="10")


def test_R_06_env_flags_and_broker_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_TRADING", "false")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", LIVE_CONFIRMATION)
    monkeypatch.setenv("ALPACA_API_KEY", "test-only-env-api")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-only-env-secret")
    assert not Settings().paper_trading
    monkeypatch.setenv("PAPER_TRADING", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_R_05_clocks_are_aware_utc_and_frozen() -> None:
    instant = datetime(2026, 10, 4, 10, 0, tzinfo=timezone(timedelta(hours=-5)))
    clock = FrozenClock(instant)
    assert clock.now() == datetime(2026, 10, 4, 15, 0, tzinfo=UTC)
    assert clock.now() is clock.now()
    assert SystemClock().now().tzinfo is UTC
    with pytest.raises(DataIntegrityError):
        ensure_utc(datetime(2026, 10, 4))


def test_GD_01_offline_defaults_disable_llm_and_intraday_calls() -> None:
    settings = Settings()
    assert settings.llm_model_name is None
    assert settings.llm_base_url is None
    assert settings.llm_daily_budget_usd == Decimal("0")
    assert settings.llm_input_cost_per_million_usd is None
    assert settings.llm_output_cost_per_million_usd is None
    assert not settings.enable_intraday_playbooks
    assert settings.earnings_blackout_sessions == 2
    assert settings.min_setup_score == Decimal("7.0")
    assert settings.max_alerts_per_day == 5
    assert settings.proposal_ttl_sessions == 1
    with pytest.raises(ConfigurationError):
        settings.assert_research_ready()
    with pytest.raises(ConfigurationError):
        settings.assert_telegram_ready()


@pytest.mark.parametrize("missing", ["llm_base_url", "llm_model_name", "llm_api_key"])
def test_GD_01_connected_research_requires_explicit_provider_model_and_key(missing: str) -> None:
    values: dict[str, Any] = {
        "llm_base_url": "https://example.invalid/v1",
        "llm_model_name": "test-model-from-configuration",
        "llm_api_key": SecretStr("test-only-llm-key"),
    }
    values.pop(missing)
    with pytest.raises(ConfigurationError):
        Settings(**values).assert_research_ready()


def test_GD_01_zero_budget_and_unknown_costs_block_calls() -> None:
    values: dict[str, Any] = {
        "llm_base_url": "https://example.invalid/v1",
        "llm_model_name": "test-model-from-configuration",
        "llm_api_key": SecretStr("test-only-budget-key"),
    }
    connected = Settings(**values)
    connected.assert_research_ready()
    with pytest.raises(ConfigurationError, match="zero daily budget"):
        connected.assert_llm_call_budget_ready()
    values["llm_daily_budget_usd"] = Decimal("1")
    with pytest.raises(ConfigurationError, match="cost rates"):
        Settings(**values).assert_llm_call_budget_ready()
    values["llm_input_cost_per_million_usd"] = Decimal("2")
    with pytest.raises(ConfigurationError, match="cost rates"):
        Settings(**values).assert_llm_call_budget_ready()
    values["llm_output_cost_per_million_usd"] = Decimal("8")
    Settings(**values).assert_llm_call_budget_ready()


def test_R_04_GD_01_daily_budget_requires_representable_money() -> None:
    assert Settings(llm_daily_budget_usd=Decimal("0.000001")).llm_daily_budget_usd == Decimal(
        "0.000001"
    )
    with pytest.raises(ValidationError):
        Settings(llm_daily_budget_usd=Decimal("0.0000001"))


def test_R_04_validation_does_not_depend_on_ambient_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 1
        settings = Settings(
            min_price=Decimal("5.01"),
            reserved_obligations_usd=(Decimal("100000000"), Decimal("900000000")),
        )
        assert settings.min_price == Decimal("5.01")
        with pytest.raises(ValidationError):
            Settings(min_price=Decimal("5.001"))
        with pytest.raises(ValidationError):
            Settings(reserved_obligations_usd=(Decimal("1000000000"), Decimal("1")))


@pytest.mark.parametrize(
    "field",
    ["llm_input_cost_per_million_usd", "llm_output_cost_per_million_usd"],
)
@pytest.mark.parametrize("bad", [True, 0.1, "NaN", "Infinity", "-0.01", "1000.01"])
def test_GD_01_cost_rates_reject_inexact_nonfinite_and_out_of_bounds(field: str, bad: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: bad})


@pytest.mark.parametrize(
    "field",
    ["llm_input_cost_per_million_usd", "llm_output_cost_per_million_usd"],
)
@pytest.mark.parametrize("boundary", [Decimal("0"), Decimal("1000")])
def test_GD_01_cost_rate_exact_boundaries_pass(field: str, boundary: Decimal) -> None:
    values: dict[str, Any] = {field: boundary}
    assert Settings(**values).__dict__[field] == boundary


@pytest.mark.parametrize("score", ["6.0", "7.0", "10.0"])
def test_GD_02_setup_score_exact_boundaries_pass(score: str) -> None:
    values: dict[str, Any] = {"min_setup_score": score}
    assert Settings(**values).min_setup_score == Decimal(score)


@pytest.mark.parametrize("bad", ["5.99", "10.01", "NaN", "Infinity", 7.0, True])
def test_GD_02_setup_score_below_six_or_nonfinite_is_rejected(bad: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(min_setup_score=bad)


@pytest.mark.parametrize("field,bounds", list(Settings.INTEGER_BOUNDS.items()))
def test_R_06_integer_lower_boundary_and_below_rejection(
    field: str, bounds: tuple[int, int]
) -> None:
    values: dict[str, Any] = {field: bounds[0]}
    assert Settings(**values).__dict__[field] == bounds[0]
    values[field] = bounds[0] - 1
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("field", ["min_setup_score", "llm_daily_budget_usd"])
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_R_04_GD_01_nonfinite_environment_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, bad: str
) -> None:
    monkeypatch.setenv(field.upper(), bad)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "url",
    [
        f"{'http'}://example.invalid/v1",
        "https://user:private-key@example.invalid/v1",
        "https://example.invalid/v1?api_key=private-key",
        "https://example.invalid/v1#private-key",
        "https:///v1",
        "https://example.invalid:bad/v1",
        " https://example.invalid/v1",
    ],
)
def test_R_07_GD_01_llm_endpoint_rejects_secret_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(llm_base_url=url)
    assert "private-key" not in str(caught.value)


@pytest.mark.parametrize("model", ["", " ", " model", "model ", "line\nbreak", "x" * 201])
def test_GD_01_explicit_model_name_is_required_and_bounded(model: str) -> None:
    with pytest.raises(ValidationError):
        Settings(llm_model_name=model)


@pytest.mark.parametrize("missing", ["bot_token", "allowlist", "callback_secret"])
def test_R_14_GD_05_connected_telegram_requires_every_security_condition(missing: str) -> None:
    fields = {
        "bot_token": "telegram_bot_token",
        "allowlist": "telegram_allowed_user_ids",
        "callback_secret": "telegram_callback_secret",
    }
    values: dict[str, Any] = {
        "telegram_bot_token": SecretStr("test-only-telegram-token"),
        "telegram_allowed_user_ids": [10001],
        "telegram_callback_secret": SecretStr("test-only-callback-secret-32bytes-minimum"),
    }
    values.pop(fields[missing])
    with pytest.raises(ConfigurationError):
        Settings(**values).assert_telegram_ready()


def test_R_14_GD_05_allowlist_is_explicit_nonempty_immutable_and_strict() -> None:
    users = [10001, 10002]
    values: dict[str, Any] = {
        "telegram_bot_token": SecretStr("test-only-allowlist-token"),
        "telegram_allowed_user_ids": users,
        "telegram_callback_secret": SecretStr("test-only-callback-secret-32bytes-minimum"),
    }
    settings = Settings(**values)
    settings.assert_telegram_ready()
    users.append(99999)
    assert settings.telegram_allowed_user_ids == (10001, 10002)
    assert 99999 not in settings.telegram_allowed_user_ids
    values["telegram_allowed_user_ids"] = []
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize(
    "users",
    [[True], [0], [-1], [10001.0], ["10001"], [10001, 10001], [2**63], "10001"],
)
def test_R_14_GD_05_invalid_allowlist_never_starts(users: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(telegram_allowed_user_ids=users)


def test_R_14_GD_05_callback_secret_minimum_bytes_are_enforced() -> None:
    values: dict[str, Any] = {
        "telegram_bot_token": SecretStr("test-only-length-token"),
        "telegram_allowed_user_ids": [10001],
    }
    with pytest.raises(ConfigurationError):
        Settings(telegram_callback_secret=SecretStr("x" * 31), **values).assert_telegram_ready()
    Settings(telegram_callback_secret=SecretStr("x" * 32), **values).assert_telegram_ready()
    with pytest.raises(ConfigurationError):
        Settings(telegram_callback_secret=SecretStr(" " * 32), **values).assert_telegram_ready()


def test_R_07_GD_01_GD_05_new_secrets_are_masked_and_do_not_change_config_hash() -> None:
    values: dict[str, Any] = {
        "llm_api_key": SecretStr("test-only-private-llm-key"),
        "telegram_bot_token": SecretStr("987654321:test-only-private-token"),
        "telegram_callback_secret": SecretStr("test-only-private-callback-secret-32bytes"),
        "newsapi_key": SecretStr("test-only-private-news-key"),
    }
    settings = Settings(**values)
    assert settings.config_hash == Settings().config_hash
    rendered = repr(settings) + str(settings.nonsecret_snapshot()) + settings.model_dump_json()
    for secret in values.values():
        assert secret.get_secret_value() not in rendered
    invalid: dict[str, Any] = {"telegram_bot_token": 987654321}
    with pytest.raises(ValidationError) as caught:
        Settings(**invalid)
    assert "987654321" not in str(caught.value)


def test_GD_01_GD_05_environment_profiles_use_json_and_explicit_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL_NAME", "test-env-model")
    monkeypatch.setenv("LLM_API_KEY", "test-only-env-llm-key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[10001, 10002]")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-only-env-bot-token")
    monkeypatch.setenv("TELEGRAM_CALLBACK_SECRET", "test-only-env-callback-secret-32bytes")
    monkeypatch.setenv("ENABLE_INTRADAY_PLAYBOOKS", "true")
    settings = Settings()
    settings.assert_research_ready()
    settings.assert_telegram_ready()
    assert settings.llm_model_name == "test-env-model"
    assert settings.telegram_allowed_user_ids == (10001, 10002)
    assert settings.enable_intraday_playbooks
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[]")
    with pytest.raises(ValidationError):
        Settings()
