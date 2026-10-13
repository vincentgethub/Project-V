"""GD-02/R-03/R-06: strict, exact, frozen research YAML cannot weaken risk."""

from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import SecretStr, ValidationError

from backend.core.config import (
    YAML_INTEGER_BOUNDS,
    Settings,
    YamlConfig,
    load_settings,
    load_yaml_config,
)
from backend.core.errors import ConfigurationError
from backend.domain.instruments import InstrumentRegistry

REPOSITORY_CONFIG = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
ALLOWED_SYMBOLS = InstrumentRegistry.from_csv(REPOSITORY_CONFIG.parent).symbols


@pytest.fixture(autouse=True)
def isolated_yaml_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-07: YAML tests cannot accidentally read connected credentials."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setenv("BROKER_ACCOUNT_TYPE", "CASH")


@pytest.fixture
def valid_payload() -> dict[str, Any]:
    """GD-02: a canonical exact-value copy of the shipped research policy."""
    return load_yaml_config(REPOSITORY_CONFIG, allowed_symbols=ALLOWED_SYMBOLS).nonsecret_snapshot()


def write_yaml(tmp_path: Path, payload: object) -> Path:
    """R-07: every mutable YAML fixture is local to its test."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_GD_02_shipped_yaml_uses_exact_frozen_weights_and_levels() -> None:
    config = load_yaml_config(
        REPOSITORY_CONFIG, allowed_symbols=ALLOWED_SYMBOLS, settings=Settings()
    )
    assert len(config.watchlist) == 32
    assert set(config.watchlist).issubset(ALLOWED_SYMBOLS)
    assert config.schedule.monitor_interval_minutes == 15
    assert config.alerts.alert_cooldown_sessions == 1
    assert set(config.playbooks) == {"TREND_50EMA", "BASE_BREAKOUT", "ANCHORED_VWAP_RECLAIM"}
    for playbook in config.playbooks.values():
        assert sum(playbook.criteria_weights.values(), Decimal("0")) == Decimal("1")
        assert config.sizing.stop_atr_mult == Decimal("2")
        assert config.sizing.target_r == Decimal("2")
    with pytest.raises(ValidationError):
        config.watchlist = ("NVDA",)
    with pytest.raises(ValidationError):
        config.schedule.monitor_interval_minutes = 30
    with pytest.raises(TypeError):
        config.playbooks["TREND_50EMA"] = config.playbooks["BASE_BREAKOUT"]  # type: ignore[index]
    with pytest.raises(TypeError):
        config.playbooks["TREND_50EMA"].criteria_weights["trend"] = Decimal("0.9")  # type: ignore[index]


def test_R_04_GD_02_weight_validation_uses_an_explicit_decimal_context(
    valid_payload: dict[str, Any],
) -> None:
    with localcontext() as context:
        context.prec = 1
        YamlConfig.model_validate(valid_payload)
        valid_payload["playbooks"]["TREND_50EMA"]["criteria_weights"] = {"trend": "0.99"}
        with pytest.raises(ValidationError, match="sum to exactly"):
            YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize("symbols", [frozenset(), frozenset({"NVDA"})])
def test_R_02_watchlist_requires_explicit_authoritative_instruments(
    symbols: frozenset[str],
) -> None:
    with pytest.raises(ConfigurationError, match="instrument"):
        load_yaml_config(REPOSITORY_CONFIG, allowed_symbols=symbols)


@pytest.mark.parametrize("watchlist", [[], ["nvda"], [" NVDA"], ["NVDA", "NVDA"], [None], [True]])
def test_R_02_watchlist_rejects_missing_malformed_or_duplicated_symbols(
    valid_payload: dict[str, Any], watchlist: Any
) -> None:
    valid_payload["watchlist"] = watchlist
    with pytest.raises(ValidationError):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize(
    "risk_key",
    [
        "MAX_RISK_PER_TRADE",
        "max-risk-per-trade",
        "max_single_stock_weight",
        "MIN_CASH_PCT",
        "sector_caps",
        "theme_caps",
        "reserved_obligations_usd",
        "earnings_blackout_sessions",
        "min_setup_score",
        "proposal_ttl_sessions",
        "max_alerts_per_day",
        "TELEGRAM_CALLBACK_SECRET",
    ],
)
@pytest.mark.parametrize("location", ["root", "schedule", "weights", "arbitrary_nested"])
def test_R_06_yaml_rejects_env_risk_and_secret_keys_at_every_depth(
    valid_payload: dict[str, Any], risk_key: str, location: str
) -> None:
    if location == "root":
        valid_payload[risk_key] = "0.5"
    elif location == "schedule":
        valid_payload["schedule"][risk_key] = "0.5"
    elif location == "weights":
        valid_payload["playbooks"]["BASE_BREAKOUT"]["criteria_weights"][risk_key] = "0.5"
    else:
        valid_payload["unrecognized"] = {"nested": [{risk_key: "0.5"}]}
    with pytest.raises(ValidationError, match="YAML cannot contain env"):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize("location", ["root", "schedule", "alerts", "playbook"])
def test_GD_02_yaml_rejects_unrecognized_fields(
    valid_payload: dict[str, Any], location: str
) -> None:
    containers = {
        "root": valid_payload,
        "schedule": valid_payload["schedule"],
        "alerts": valid_payload["alerts"],
        "playbook": valid_payload["playbooks"]["TREND_50EMA"],
    }
    containers[location]["unrecognized_field"] = "value"
    with pytest.raises(ValidationError, match="Extra inputs"):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize("strategy", ["INTRADAY_ORB", "UNKNOWN"])
def test_GD_02_yaml_requires_only_supported_daily_playbooks(
    valid_payload: dict[str, Any], strategy: str
) -> None:
    valid_payload["playbooks"][strategy] = valid_payload["playbooks"].pop("BASE_BREAKOUT")
    with pytest.raises(ValidationError, match="three supported"):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize(
    "weights",
    [
        {},
        {"trend": "0"},
        {"trend": "0.99"},
        {"trend": "1.01"},
        {"trend": "NaN"},
        {"trend": "0.999999999999999999999999999999999999"},
        {"trend": 1.0},
        {"bad name": "1"},
    ],
)
def test_GD_02_invalid_weight_totals_types_and_names_are_rejected(
    valid_payload: dict[str, Any], weights: Any
) -> None:
    valid_payload["playbooks"]["TREND_50EMA"]["criteria_weights"] = weights
    with pytest.raises(ValidationError):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize(
    "field,boundary",
    [
        ("stop_atr_mult", "0.5"),
        ("stop_atr_mult", "10"),
        ("target_r", "1.5"),
        ("target_r", "10"),
    ],
)
def test_GD_02_playbook_level_exact_boundaries_pass(
    valid_payload: dict[str, Any], field: str, boundary: str
) -> None:
    valid_payload["sizing"][field] = boundary
    config = YamlConfig.model_validate(valid_payload)
    assert config.sizing.__dict__[field] == Decimal(boundary)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("stop_atr_mult", "0.49"),
        ("stop_atr_mult", "10.01"),
        ("target_r", "1.49"),
        ("target_r", "10.01"),
        ("target_r", "NaN"),
        ("target_r", "Infinity"),
        ("stop_atr_mult", 2.0),
    ],
)
def test_GD_02_playbook_invalid_levels_fail_closed(
    valid_payload: dict[str, Any], field: str, bad: Any
) -> None:
    valid_payload["sizing"][field] = bad
    with pytest.raises(ValidationError):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("monitor_interval_minutes", 20),
        ("offhours_news_interval_minutes", 120),
        ("scheduler_misfire_grace_seconds", 120),
        ("daily_bar_sip_lag_seconds", 1200),
        ("alert_cooldown_sessions", 2),
    ],
)
@pytest.mark.parametrize("use_yaml_value", [False, True])
def test_GD_04_yaml_only_keys_in_process_env_fail_even_when_values_agree(
    monkeypatch: pytest.MonkeyPatch, field: str, value: int, use_yaml_value: bool
) -> None:
    """R-06/GD-04: equal values do not excuse a second configuration home."""
    config = load_yaml_config(REPOSITORY_CONFIG, allowed_symbols=ALLOWED_SYMBOLS)
    settings = Settings()
    if use_yaml_value:
        model = config.alerts if field == "alert_cooldown_sessions" else config.schedule
        value = model.__dict__[field]
    monkeypatch.setenv(field.upper(), str(value))
    with pytest.raises(ValidationError, match="YAML-only"):
        Settings()
    with pytest.raises(ConfigurationError, match="wrong home"):
        config.assert_settings_consistent(settings)


@pytest.mark.parametrize("field", sorted(YAML_INTEGER_BOUNDS))
@pytest.mark.parametrize("spelling", ["upper", "lower"])
def test_GD_04_yaml_only_keys_in_dotenv_are_rejected(
    tmp_path: Path, field: str, spelling: str
) -> None:
    """R-06/R-07: explicitly loaded dotenv cannot hold YAML-only parameters."""
    key = field.upper() if spelling == "upper" else field
    env_file = tmp_path / ".env"
    env_file.write_text(f"{key}={YAML_INTEGER_BOUNDS[field][0]}\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_settings(env_file=env_file)


@pytest.mark.parametrize("field", sorted(YAML_INTEGER_BOUNDS))
@pytest.mark.parametrize("value", ["", "unparseable"])
def test_GD_04_wrong_home_process_values_cannot_be_silently_ignored(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    """R-06: even empty removed env values must fail startup."""
    monkeypatch.setenv(field, value)
    with pytest.raises(ValidationError, match="YAML-only"):
        Settings()


@pytest.mark.parametrize("field", sorted(YAML_INTEGER_BOUNDS))
def test_GD_04_wrong_home_constructor_and_forged_settings_are_rejected(
    field: str,
) -> None:
    """R-02/R-06: model_copy cannot smuggle duplicate schedule definitions."""
    value = YAML_INTEGER_BOUNDS[field][0]
    with pytest.raises(ValidationError, match="Extra inputs"):
        Settings(**{field: value})
    forged = Settings().model_copy(update={field: value})
    with pytest.raises(ConfigurationError, match="wrong home"):
        load_yaml_config(REPOSITORY_CONFIG, allowed_symbols=ALLOWED_SYMBOLS, settings=forged)


@pytest.mark.parametrize("field,bounds", list(YAML_INTEGER_BOUNDS.items()))
@pytest.mark.parametrize("boundary_index", [0, 1])
def test_GD_04_yaml_integer_bounds_are_separate_and_preserved(
    valid_payload: dict[str, Any], field: str, bounds: tuple[int, int], boundary_index: int
) -> None:
    """R-06/GD-04: every YAML bound is tested independently of env settings."""
    assert not set(YAML_INTEGER_BOUNDS).intersection(Settings.INTEGER_BOUNDS)
    container = valid_payload["alerts" if field == "alert_cooldown_sessions" else "schedule"]
    container[field] = bounds[boundary_index]
    config = YamlConfig.model_validate(valid_payload)
    model = config.alerts if field == "alert_cooldown_sessions" else config.schedule
    assert model.__dict__[field] == bounds[boundary_index]
    container[field] += -1 if boundary_index == 0 else 1
    with pytest.raises(ValidationError, match="must be between"):
        YamlConfig.model_validate(valid_payload)
    container[field] = True
    with pytest.raises(ValidationError, match="whole integer"):
        YamlConfig.model_validate(valid_payload)


def test_GD_04_yaml_only_overrides_pass_and_do_not_enter_env_settings(
    valid_payload: dict[str, Any], tmp_path: Path
) -> None:
    valid_payload["schedule"]["monitor_interval_minutes"] = 20
    config = load_yaml_config(
        write_yaml(tmp_path, valid_payload), allowed_symbols=ALLOWED_SYMBOLS, settings=Settings()
    )
    assert config.schedule.monitor_interval_minutes == 20
    assert "monitor_interval_minutes" not in Settings.model_fields
    assert "alert_cooldown_sessions" not in Settings.model_fields


def test_R_03_GD_02_combined_hash_tracks_yaml_and_ignores_credentials(
    valid_payload: dict[str, Any],
) -> None:
    first = YamlConfig.model_validate(valid_payload)
    original_hash = Settings().with_yaml_hash(first)
    assert len(first.config_hash) == 64
    assert len(original_hash) == 64
    assert original_hash != Settings().config_hash
    credentials = Settings(
        llm_api_key=SecretStr("test-only-yaml-private-key"),
        telegram_bot_token=SecretStr("test-only-yaml-bot-token"),
    )
    assert credentials.with_yaml_hash(first) == original_hash
    valid_payload["sizing"]["target_r"] = "3"
    second = YamlConfig.model_validate(valid_payload)
    assert second.config_hash != first.config_hash
    assert Settings().with_yaml_hash(second) != original_hash
    reordered = dict(reversed(tuple(first.nonsecret_snapshot().items())))
    assert YamlConfig.model_validate(reordered).config_hash == first.config_hash


@pytest.mark.parametrize(
    "unsafe",
    [
        "!!python/object/apply:os.system ['echo unsafe']",
        "watchlist: &symbols [NVDA]\nother: *symbols\n",
        "watchlist: [NVDA]\nwatchlist: [AAPL]\n",
        "watchlist: [NVDA]\nschedule: {monitor_interval_minutes: 15, monitor_interval_minutes: 20}\n",
        "watchlist: [NVDA]\nschedule: {monitor_interval_minutes: .nan}\n",
        "[]",
        "",
        "watchlist: [",
        "nested: " + "[" * 2000 + "0" + "]" * 2000,
    ],
)
def test_R_12_GD_02_unsafe_ambiguous_or_malformed_yaml_is_typed(
    tmp_path: Path, unsafe: str
) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text(unsafe, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_yaml_config(path, allowed_symbols=ALLOWED_SYMBOLS)


def test_R_12_GD_02_oversized_or_missing_yaml_is_typed(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_yaml_config(tmp_path / "absent.yaml", allowed_symbols=ALLOWED_SYMBOLS)
    oversized = tmp_path / "large.yaml"
    oversized.write_text("#" * 1_048_577, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_yaml_config(oversized, allowed_symbols=ALLOWED_SYMBOLS)


def test_R_12_GD_02_excessive_depth_and_non_string_keys_are_rejected(
    valid_payload: dict[str, Any],
) -> None:
    nested: dict[str, Any] = {}
    valid_payload["unrecognized"] = nested
    for _ in range(22):
        child: dict[str, Any] = {}
        nested["nested"] = child
        nested = child
    with pytest.raises(ValidationError, match="nesting"):
        YamlConfig.model_validate(valid_payload)
    with pytest.raises(ValidationError, match="keys must be strings"):
        YamlConfig.model_validate({1: "NVDA"})
