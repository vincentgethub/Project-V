"""R-04/R-08/CRO-12/SEC-11: exact balances and keyring-only Plaid tokens."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import plaid
import pytest
from pydantic import SecretStr, ValidationError

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    LiquidityUnavailable,
    ProviderError,
)
from backend.data.liquidity import (
    BalanceReading,
    FakeLiquiditySource,
    LiquidityGate,
    ManualLiquiditySource,
    PlaidLiquiditySource,
)
from backend.domain.models import CapitalStatus
from backend.security import secrets as secret_module
from scripts import plaid_sandbox_token as sandbox_module
from scripts.plaid_sandbox_token import create_sandbox_token

NOW = datetime(2026, 10, 4, 15, 0, tzinfo=UTC)


class FakeSecrets:
    """SEC-11: explicit isolated keyring substitute, with no native access."""

    def __init__(self, token: str | None = None) -> None:
        self.values: dict[str, SecretStr] = {}
        if token is not None:
            self.values["PLAID_ACCESS_TOKEN"] = SecretStr(token)

    def get(self, name: str) -> SecretStr | None:
        return self.values.get(name)

    def set(self, name: str, value: SecretStr) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


@pytest.fixture(autouse=True)
def isolated_plaid_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-11/R-07: no test may discover or read the owner's native keyring."""
    monkeypatch.setattr(
        secret_module, "KeyringSecretStore", lambda: FakeSecrets("test-only-access-token")
    )
    monkeypatch.setattr(sandbox_module, "KeyringSecretStore", FakeSecrets)


def reading(available: Any = "3000", current: Any = "4000", **values: Any) -> BalanceReading:
    return BalanceReading(
        available=available,
        current=current,
        currency=values.get("currency", "USD"),
        as_of=values.get("as_of", NOW),
    )


@pytest.mark.parametrize(
    "available,current,expected,status",
    [
        ("3000", "4000", "1500", CapitalStatus.OK),
        ("4000", "3000", "1500", CapitalStatus.OK),
        ("1500", "1500", "0", CapitalStatus.OK),
        ("1499.99", "4000", "0", CapitalStatus.BUFFER_BREACH),
        ("-100", "4000", "0", CapitalStatus.BUFFER_BREACH),
    ],
)
def test_CRO_12_min_balance_buffer_and_exact_boundary(
    available: str,
    current: str,
    expected: str,
    status: CapitalStatus,
) -> None:
    result = LiquidityGate(
        Settings(), FakeLiquiditySource(reading(available, current)), FrozenClock(NOW)
    ).evaluate()
    assert result.deployable == Decimal(expected)
    assert result.status == status


def test_CRO_12_reservations_reduce_only_advisory_capacity() -> None:
    settings = Settings(reserved_obligations_usd=(Decimal("500.25"), Decimal("100.50")))
    gate = LiquidityGate(settings, FakeLiquiditySource(reading()), FrozenClock(NOW))
    assert gate.evaluate().deployable == Decimal("899.25")


@pytest.mark.parametrize(
    "available,current,currency",
    [(None, "3000", "USD"), ("3000", None, "USD"), ("3000", "3000", "EUR")],
)
def test_CRO_12_missing_and_nonusd_balances_are_unavailable(
    available: Any,
    current: Any,
    currency: str,
) -> None:
    result = LiquidityGate(
        Settings(),
        FakeLiquiditySource(reading(available, current, currency=currency)),
        FrozenClock(NOW),
    ).evaluate()
    assert result.status == CapitalStatus.UNAVAILABLE
    assert result.deployable == 0


@pytest.mark.parametrize("age,status", [(900, CapitalStatus.OK), (901, CapitalStatus.STALE)])
def test_CRO_12_ttl_exact_boundary(age: int, status: CapitalStatus) -> None:
    gate = LiquidityGate(
        Settings(),
        FakeLiquiditySource(reading(as_of=NOW - timedelta(seconds=age))),
        FrozenClock(NOW),
    )
    assert gate.evaluate().status == status


def test_R_05_future_liquidity_time_fails_closed() -> None:
    gate = LiquidityGate(
        Settings(), FakeLiquiditySource(reading(as_of=NOW + timedelta(seconds=1))), FrozenClock(NOW)
    )
    with pytest.raises(DataIntegrityError):
        gate.evaluate()


@pytest.mark.parametrize("bad", [float("3.2"), True, "NaN", "0.0000001"])
def test_R_04_balance_readings_reject_inexact_money(bad: Any) -> None:
    with pytest.raises(ValidationError):
        reading(bad)


def test_CRO_12_manual_value_does_not_refresh_itself() -> None:
    source = ManualLiquiditySource("3000", FrozenClock(NOW))
    gate = LiquidityGate(Settings(), source, FrozenClock(NOW + timedelta(seconds=901)))
    assert gate.evaluate(refresh=True).status == CapitalStatus.STALE
    assert source.read().as_of == NOW


class FailingSource:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def read(self) -> BalanceReading:
        raise self.error


def test_R_02_provider_fault_is_typed_and_unavailable_is_zero() -> None:
    gate = LiquidityGate(Settings(), FailingSource(RuntimeError("fault")), FrozenClock(NOW))
    with pytest.raises(ProviderError):
        gate.evaluate()
    gate = LiquidityGate(Settings(), FailingSource(LiquidityUnavailable("fault")), FrozenClock(NOW))
    result = gate.evaluate()
    assert result.status == CapitalStatus.UNAVAILABLE and result.deployable == 0


@dataclass
class RawResponse:
    data: bytes
    released: bool = False

    def release_conn(self) -> None:
        self.released = True


class FakePlaid:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[tuple[object, dict[str, object]]] = []

    def accounts_balance_get(self, request: object, **kwargs: object) -> object:
        self.requests.append((request, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def plaid_settings(**values: Any) -> Settings:
    return Settings(
        plaid_account_id="checking-test",
        **values,
    )


def test_R_08_plaid_pinned_balance_read_timeout_and_exact_raw_json() -> None:
    response = RawResponse(
        b'{"accounts":[{"account_id":"checking-test","type":"depository",'
        b'"subtype":"checking","balances":{"available":3000.01,"current":4000.02,'
        b'"iso_currency_code":"USD"}}]}'
    )
    client = FakePlaid(response)
    source = PlaidLiquiditySource(plaid_settings(), FrozenClock(NOW), client)
    balance = source.read()
    assert balance.available == Decimal("3000.01")
    assert balance.current == Decimal("4000.02")
    assert response.released
    request, kwargs = client.requests[0]
    assert getattr(getattr(request, "options", None), "account_ids", None) == ["checking-test"]
    assert kwargs["_request_timeout"] == 30 and kwargs["_preload_content"] is False


def test_CRO_12_plaid_login_required_and_bad_pin_fail_closed() -> None:
    error = plaid.ApiException(status=400)
    error.body = '{"error_code":"ITEM_LOGIN_REQUIRED"}'
    with pytest.raises(LiquidityUnavailable, match="reauthentication"):
        PlaidLiquiditySource(plaid_settings(), FrozenClock(NOW), FakePlaid(error)).read()
    with pytest.raises(DataIntegrityError):
        PlaidLiquiditySource(plaid_settings(), FrozenClock(NOW), FakePlaid({"accounts": []})).read()


class FakeSandbox:
    def __init__(self) -> None:
        self.products: object = None

    def sandbox_public_token_create(self, request: object, **kwargs: object) -> object:
        self.products = getattr(request, "initial_products", None)
        assert kwargs["_request_timeout"] == 30
        return {"public_token": "test-only-public-token"}

    def item_public_token_exchange(self, request: object, **kwargs: object) -> object:
        assert getattr(request, "public_token", None) == "test-only-public-token"
        assert kwargs["_request_timeout"] == 30
        return {"access_token": "test-only-encrypted-access-token"}


def test_SEC_11_sandbox_token_is_keyring_only_and_runtime_reads_same_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings()
    store = FakeSecrets()
    client = FakeSandbox()
    existing_paths = set(tmp_path.iterdir())
    create_sandbox_token(settings, client=client, secret_store=store)
    token = store.get("PLAID_ACCESS_TOKEN")
    assert token is not None
    assert token.get_secret_value() == "test-only-encrypted-access-token"
    assert set(tmp_path.iterdir()) == existing_paths
    assert "test-only-encrypted-access-token" not in capsys.readouterr().out
    assert isinstance(client.products, list)
    assert len(client.products) == 1 and str(client.products[0]) == "auth"
    with pytest.raises(ConfigurationError, match="already exists"):
        create_sandbox_token(settings, client=client, secret_store=store)
    source = PlaidLiquiditySource(
        Settings(plaid_account_id="checking-test"),
        FrozenClock(NOW),
        FakePlaid({"accounts": []}),
        secret_store=store,
    )
    with pytest.raises(DataIntegrityError):
        source.read()


def test_SEC_11_R_08_sandbox_script_rejects_production_and_unavailable_keyring() -> None:
    with pytest.raises(ConfigurationError, match="Sandbox"):
        create_sandbox_token(Settings(plaid_env="production"), client=FakeSandbox())

    class BrokenStore(FakeSecrets):
        def get(self, name: str) -> SecretStr | None:
            raise RuntimeError("native unavailable")

    with pytest.raises(ConfigurationError, match="keyring"):
        create_sandbox_token(Settings(), client=FakeSandbox(), secret_store=BrokenStore())


def plaid_account(**updates: object) -> dict[str, object]:
    """R-08: synthetic pinned checking response with exact decimal money."""
    account: dict[str, object] = {
        "account_id": "checking-test",
        "type": "depository",
        "subtype": "checking",
        "balances": {
            "available": Decimal("3000.01"),
            "current": Decimal("4000.02"),
            "iso_currency_code": "USD",
        },
    }
    account.update(updates)
    return account


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"accounts": None},
        {"accounts": {}},
        {"accounts": [None]},
        {"accounts": [plaid_account(), plaid_account()]},
        {"accounts": [plaid_account(), {"account_id": "other"}]},
        {"accounts": [plaid_account(account_id="other")]},
        {"accounts": [plaid_account(type="credit")]},
        {"accounts": [plaid_account(subtype="savings")]},
        {"accounts": [plaid_account(balances=None)]},
        {
            "accounts": [
                plaid_account(
                    balances={"available": 3000.01, "current": 4000, "iso_currency_code": "USD"}
                )
            ]
        },
        {
            "accounts": [
                plaid_account(
                    balances={"available": "NaN", "current": 4000, "iso_currency_code": "USD"}
                )
            ]
        },
    ],
)
def test_R_02_R_08_plaid_malformed_unrequested_or_ambiguous_accounts_fail_closed(
    payload: object,
) -> None:
    with pytest.raises(DataIntegrityError):
        PlaidLiquiditySource(plaid_settings(), FrozenClock(NOW), FakePlaid(payload)).read()


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"null", bytes((255,))])
def test_R_04_plaid_invalid_raw_json_releases_connection_and_fails(body: bytes) -> None:
    response = RawResponse(body)
    with pytest.raises(DataIntegrityError):
        PlaidLiquiditySource(plaid_settings(), FrozenClock(NOW), FakePlaid(response)).read()
    assert response.released


@pytest.mark.parametrize("payload", [None, object(), RuntimeError("bad transport")])
def test_R_02_plaid_missing_raw_body_and_unexpected_faults_are_integrity_errors(
    payload: object,
) -> None:
    with pytest.raises(DataIntegrityError):
        PlaidLiquiditySource(plaid_settings(), FrozenClock(NOW), FakePlaid(payload)).read()


@pytest.mark.parametrize(
    "body", [None, "malformed", '{"message":"ITEM_LOGIN_REQUIRED"}', '{"error_code":"OTHER"}', "[]"]
)
def test_CRO_12_plaid_errors_do_not_guess_login_state_from_arbitrary_text(body: object) -> None:
    error = plaid.ApiException(status=400)
    error.body = body
    with pytest.raises(LiquidityUnavailable, match="balance read failed"):
        PlaidLiquiditySource(plaid_settings(), FrozenClock(NOW), FakePlaid(error)).read()


def test_R_02_balance_instances_and_cached_readings_are_revalidated() -> None:
    forged = reading().model_copy(update={"available": Decimal("NaN")})
    with pytest.raises(ValidationError):
        FakeLiquiditySource(forged)
    gate = LiquidityGate(Settings(), FakeLiquiditySource(reading()), FrozenClock(NOW))
    assert gate.evaluate().status == CapitalStatus.OK
    gate._cached = forged
    with pytest.raises(DataIntegrityError):
        gate.evaluate()
    assert gate._cached is None


def test_R_02_reading_models_are_frozen_and_extra_fields_forbidden() -> None:
    original = reading()
    with pytest.raises(ValidationError):
        original.available = Decimal("100000")
    with pytest.raises(ValidationError):
        BalanceReading.model_validate({**original.model_dump(), "guessed": True})
    with pytest.raises(ValidationError):
        reading(as_of=NOW.replace(tzinfo=None))


def test_R_02_liquidity_settings_are_revalidated_before_capacity_or_bootstrap(
    tmp_path: Path,
) -> None:
    invalid = Settings().model_copy(update={"checking_buffer_usd": Decimal("-1")})
    with pytest.raises(ConfigurationError):
        LiquidityGate(invalid, FakeLiquiditySource(reading()), FrozenClock(NOW))
    with pytest.raises(ConfigurationError):
        create_sandbox_token(invalid, client=FakeSandbox())


def test_DAT_04_real_plaid_requires_resilience_before_any_network_call() -> None:
    with pytest.raises(ConfigurationError, match="resilient"):
        PlaidLiquiditySource(plaid_settings(), FrozenClock(NOW))


@pytest.mark.parametrize(
    "settings",
    [
        Settings(broker_account_type="CASH"),
        Settings(broker_account_type="CASH", plaid_account_id="checking-test"),
    ],
)
def test_R_07_R_08_plaid_rejects_missing_pin_or_access_token(settings: Settings) -> None:
    with pytest.raises(ConfigurationError):
        PlaidLiquiditySource(
            settings, FrozenClock(NOW), FakePlaid({"accounts": []}), secret_store=FakeSecrets()
        )


@pytest.mark.parametrize("name", ["PLAID_ACCESS_TOKEN", "PLAID_TOKEN_PATH", "FERNET_KEY"])
def test_SEC_11_legacy_sources_never_fall_back_to_the_keyring_token(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    config = plaid_settings()
    monkeypatch.setenv(name, "")
    with pytest.raises(ConfigurationError, match="keyring"):
        PlaidLiquiditySource(config, FrozenClock(NOW), FakePlaid({"accounts": []}))


def test_R_02_provider_failed_refresh_invalidates_a_previously_good_cache() -> None:
    source = FakeLiquiditySource(reading())
    gate = LiquidityGate(Settings(), source, FrozenClock(NOW))
    assert gate.evaluate().status == CapitalStatus.OK
    source.reading = reading().model_copy(update={"current": True})
    with pytest.raises(ProviderError):
        gate.evaluate(refresh=True)
    assert gate._cached is None


def test_R_04_funding_calculation_ignores_global_decimal_precision() -> None:
    from decimal import localcontext

    settings = Settings(reserved_obligations_usd=(Decimal("123.123456"), Decimal("456.654321")))
    gate = LiquidityGate(
        settings, FakeLiquiditySource(reading("8765.123456", "9876.987654")), FrozenClock(NOW)
    )
    with localcontext() as context:
        context.prec = 2
        assert gate.evaluate().deployable == Decimal("6685.345679")


@pytest.mark.parametrize(
    "response", [{}, {"public_token": ""}, {"public_token": 1}, RuntimeError("sdk failed")]
)
def test_R_07_sandbox_invalid_response_never_writes_token(tmp_path: Path, response: object) -> None:
    class BadSandbox(FakeSandbox):
        def sandbox_public_token_create(self, request: object, **kwargs: object) -> object:
            if isinstance(response, Exception):
                raise response
            return response

    settings = Settings()
    store = FakeSecrets()
    existing_paths = set(tmp_path.iterdir())
    with pytest.raises((ConfigurationError, ProviderError)):
        create_sandbox_token(settings, client=BadSandbox(), secret_store=store)
    assert store.get("PLAID_ACCESS_TOKEN") is None
    assert set(tmp_path.iterdir()) == existing_paths
