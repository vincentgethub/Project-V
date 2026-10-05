"""R-02/R-04/R-08/CRO-12: read-only checking balances and funding capacity."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, Any, Protocol, cast

import plaid
import structlog
from plaid.api.plaid_api import PlaidApi
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.accounts_balance_get_request_options import AccountsBalanceGetRequestOptions
from pydantic import Field, field_validator

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    LiquidityUnavailable,
    ProviderError,
    SafetyError,
)
from backend.core.logging import register_secrets
from backend.core.money import MoneyInput, decimal_money
from backend.domain.models import CapitalStatus, DeployableCapital, FrozenModel
from backend.security.secrets import SecretStore, assert_secret_sources, plaid_access_token

if TYPE_CHECKING:
    from backend.data.data_layer import ResilientReader


class BalanceReading(FrozenModel):
    """R-04/R-05/CRO-12: exact source balances; missing values are explicit."""

    available: Decimal | None
    current: Decimal | None
    currency: str = Field(strict=True, min_length=1)
    as_of: datetime

    @field_validator("available", "current", mode="before")
    @classmethod
    def validate_balance(cls, value: object) -> Decimal | None:
        """R-04: no floats, nonfinite money, or implicit precision loss."""
        if value is None:
            return None
        try:
            return decimal_money(cast(MoneyInput, value))
        except DataIntegrityError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_timestamp(cls, value: object) -> datetime:
        """R-05: require an aware timestamp and normalize it to UTC."""
        try:
            return ensure_utc(cast(datetime, value))
        except DataIntegrityError as exc:
            raise ValueError(str(exc)) from exc


class LiquiditySource(Protocol):
    """R-08: a source can read a balance and cannot move money."""

    def read(self) -> BalanceReading:
        """CRO-12: return a balance reading or a typed unavailable error."""
        raise NotImplementedError("LiquiditySource implementations must supply read")


class PlaidBalanceClient(Protocol):
    """R-08: deliberately expose only Plaid's balance read endpoint."""

    def accounts_balance_get(self, request: object, **kwargs: object) -> object:
        """R-08: fetch balances without an SDK financial-value conversion."""
        raise NotImplementedError("balance client must supply accounts_balance_get")


class PlaidLiquiditySource:
    """R-08/CRO-12: query one pinned checking account using official plaid-python.

    Raw HTTP JSON is decoded with Decimal, avoiding the generated SDK's float
    financial fields. Balance entitlement is established separately; Balance is
    not a valid standalone Link/Sandbox initial product. Runtime calls only read
    balances. The clock stamps completion of the fresh institution balance read.
    """

    def __init__(
        self,
        config: Settings,
        clock: Clock,
        client: PlaidBalanceClient | None = None,
        *,
        reader: ResilientReader | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        """SEC-11/R-08: only native keyring storage supplies the access token."""
        assert_secret_sources("MANUAL")
        self._config = validated_liquidity_settings(config)
        config = self._config
        self._clock = clock
        self._reader = reader
        if not config.plaid_account_id.strip():
            raise ConfigurationError("Plaid requires a pinned account ID")
        if client is None and reader is None:
            raise ConfigurationError("DAT-04: live Plaid reads require a resilient reader")
        self._token = plaid_access_token(secret_store).get_secret_value()
        register_secrets(self._token)
        if client is None:
            if reader is None:
                raise ConfigurationError("DAT-04: live Plaid reads require a resilient reader")
            if (
                not config.plaid_client_id.get_secret_value()
                or not config.plaid_secret.get_secret_value()
            ):
                raise ConfigurationError("Plaid client credentials are required")
            try:
                # VERIFY: https://github.com/plaid/plaid-python#usage
                configuration = plaid.Configuration(
                    host=plaid.Environment.Sandbox
                    if config.plaid_env == "sandbox"
                    else plaid.Environment.Production,
                    api_key={
                        "clientId": config.plaid_client_id.get_secret_value(),
                        "secret": config.plaid_secret.get_secret_value(),
                    },
                )
                configuration.retries = 0
                sdk = PlaidApi(plaid.ApiClient(configuration))
                prepare_plaid_client(sdk, config.plaid_env)
                self._client = cast(PlaidBalanceClient, sdk)
            except Exception:
                raise ConfigurationError("Plaid SDK could not be safely initialized") from None
        else:
            if isinstance(client, PlaidApi):
                if reader is None:
                    raise ConfigurationError(
                        "DAT-04: real Plaid SDK reads require a resilient reader"
                    )
                prepare_plaid_client(client, config.plaid_env)
            self._client = client

    def read(self) -> BalanceReading:
        """CRO-12/DAT-04: fresh read with timeout and exact pinned-account match."""
        try:
            if isinstance(self._client, PlaidApi):
                prepare_plaid_client(self._client, self._config.plaid_env)
            # VERIFY: https://plaid.com/docs/api/products/signal/#accountsbalanceget
            request = AccountsBalanceGetRequest(
                access_token=self._token,
                options=AccountsBalanceGetRequestOptions(
                    account_ids=[self._config.plaid_account_id]
                ),
            )

            # VERIFY: https://github.com/plaid/plaid-python/blob/master/plaid/api_client.py
            def operation() -> object:
                try:
                    return self._client.accounts_balance_get(
                        request,
                        _request_timeout=self._config.request_timeout_seconds,
                        _preload_content=False,
                        _return_http_data_only=True,
                    )
                except plaid.ApiException as error:
                    if _login_required(error):
                        raise LiquidityUnavailable("Plaid item requires reauthentication") from None
                    raise

            response = operation() if self._reader is None else self._reader.run(operation)
            payload = _raw_balance_payload(response)
            accounts = payload.get("accounts")
            if not isinstance(accounts, list):
                raise DataIntegrityError("Plaid response requires accounts")
            if len(accounts) != 1 or not isinstance(accounts[0], Mapping):
                raise DataIntegrityError("Plaid pinned account must match exactly once")
            account = accounts[0]
            if account.get("account_id") != self._config.plaid_account_id:
                raise DataIntegrityError("Plaid returned an unrequested account")
            if account.get("type") != "depository" or account.get("subtype") != "checking":
                raise DataIntegrityError("Plaid pinned account must be a checking account")
            balances = account.get("balances")
            if not isinstance(balances, Mapping):
                raise DataIntegrityError("Plaid account requires balances")
            return BalanceReading.model_validate(
                {
                    "available": balances.get("available"),
                    "current": balances.get("current"),
                    "currency": balances.get("iso_currency_code"),
                    "as_of": self._clock.now(),
                }
            )
        except SafetyError as exc:
            raise exc from None
        except plaid.ApiException as exc:
            _log_fault("liquidity_read_failed", exc)
            raise LiquidityUnavailable("Plaid balance read failed") from None
        except Exception as exc:
            _log_fault("liquidity_read_failed", exc)
            raise DataIntegrityError("Plaid balance response cannot be verified") from None


def prepare_plaid_client(client: PlaidApi, environment: str) -> None:
    """R-07/R-08/DAT-04: verify mode and disable SDK redirects/inner retries.

    The pinned SDK passes Configuration.retries to its urllib3 pool. A zero retry
    budget also refuses redirects, preventing reposting secret token JSON to a
    redirected host. Existing injected pools are cleared before the override.
    """
    try:
        # VERIFY: https://github.com/plaid/plaid-python/blob/master/plaid/rest.py
        expected = (
            plaid.Environment.Sandbox if environment == "sandbox" else plaid.Environment.Production
        )
        configuration = client.api_client.configuration
        pool = client.api_client.rest_client.pool_manager
        if environment not in {"sandbox", "production"} or configuration.host != expected:
            raise ConfigurationError("Plaid resolved endpoint differs from configured mode")
        configuration.debug = False
        configuration.retries = 0
        if pool.connection_pool_kw.get("retries") != 0:
            pool.clear()
            pool.connection_pool_kw["retries"] = 0
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("Plaid SDK transport contract cannot be verified") from None


def _login_required(error: plaid.ApiException) -> bool:
    """R-02/R-07: classify exact error codes without logging untrusted bodies."""
    body = getattr(error, "body", None)
    if not isinstance(body, (str, bytes, bytearray)):
        return False
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        return False
    return isinstance(payload, Mapping) and payload.get("error_code") == "ITEM_LOGIN_REQUIRED"


def _log_fault(event: str, error: Exception) -> None:
    """R-02/R-07: record only static event names and types; audit faults are typed."""
    try:
        structlog.get_logger().error(event, error_type=type(error).__name__)
    except Exception:
        raise DataIntegrityError("liquidity fault audit failed") from None


def validated_liquidity_settings(config: Settings) -> Settings:
    """R-02/CRO-12: reject settings forged through unchecked Pydantic copies."""
    try:
        if not isinstance(config, Settings):
            raise DataIntegrityError("liquidity settings are missing")
        values = config.model_dump()
        if (
            not config.telegram_allowed_user_ids
            and "telegram_allowed_user_ids" not in config.model_fields_set
        ):
            values.pop("telegram_allowed_user_ids")
        return Settings.model_validate(values)
    except Exception as exc:
        raise ConfigurationError("liquidity settings cannot be verified") from exc


def _raw_balance_payload(response: object) -> Mapping[str, Any]:
    """R-04: parse original financial JSON with no intermediate float value."""
    if isinstance(response, Mapping):
        return response
    raw = getattr(response, "data", None)
    if not isinstance(raw, (str, bytes, bytearray)):
        raise DataIntegrityError("Plaid raw response body is unavailable")
    try:
        decoded = json.loads(raw, parse_float=Decimal)
    except (ValueError, UnicodeError) as exc:
        raise DataIntegrityError("Plaid response is not valid JSON") from exc
    finally:
        release = getattr(response, "release_conn", None)
        if callable(release):
            release()
    if not isinstance(decoded, Mapping):
        raise DataIntegrityError("Plaid response must be a JSON object")
    return decoded


class ManualLiquiditySource:
    """R-08/CRO-12: explicit manual balance assertion, subject to the same TTL."""

    def __init__(self, value: MoneyInput, clock: Clock) -> None:
        """R-04/R-05: stamp this assertion once rather than renewing it on reads."""
        amount = decimal_money(value)
        self._reading = BalanceReading(
            available=amount,
            current=amount,
            currency="USD",
            as_of=clock.now(),
        )

    def read(self) -> BalanceReading:
        """CRO-12: read the existing assertion without pretending it is refreshed."""
        return BalanceReading.model_validate(self._reading)


class FakeLiquiditySource:
    """R-08: deterministic, network-free balance source for tests."""

    def __init__(self, reading: BalanceReading) -> None:
        """R-03: retain an immutable supplied reading."""
        self.reading = BalanceReading.model_validate(reading)

    def read(self) -> BalanceReading:
        """R-03: return exactly the injected reading."""
        return BalanceReading.model_validate(self.reading)


class LiquidityGate:
    """CRO-12: cached advisory funding capacity; no money movement exists."""

    def __init__(self, config: Settings, source: LiquiditySource, clock: Clock) -> None:
        """R-03/R-05: inject all policy, data, and time dependencies."""
        self._config = validated_liquidity_settings(config)
        self._source = source
        self._clock = clock
        self._cached: BalanceReading | None = None

    def refresh(self) -> BalanceReading:
        """CRO-12: explicitly obtain a fresh reading; failures invalidate cache."""
        try:
            reading = self._source.read()
            if not isinstance(reading, BalanceReading):
                raise DataIntegrityError("liquidity source returned no valid reading")
            self._cached = BalanceReading.model_validate(reading)
            return self._cached
        except SafetyError:
            self._cached = None
            raise
        except Exception as exc:
            self._cached = None
            _log_fault("liquidity_provider_failed", exc)
            raise ProviderError("liquidity provider failed") from exc

    def evaluate(self, *, refresh: bool = False) -> DeployableCapital:
        """CRO-12: stale/unavailable/non-USD/missing readings advertise zero funds.

        Expiry never silently renews a cached assertion. The host must explicitly
        call refresh or request evaluate(refresh=True) before opening new funding.
        """
        try:
            return self._evaluate(refresh=refresh)
        except SafetyError:
            raise
        except Exception as exc:
            self._cached = None
            _log_fault("liquidity_evaluation_failed", exc)
            raise DataIntegrityError("liquidity capacity cannot be verified") from exc

    def _evaluate(self, *, refresh: bool) -> DeployableCapital:
        """CRO-12/R-05: exact advisory arithmetic using the injected clock."""
        try:
            reading = self.refresh() if refresh or self._cached is None else self._cached
        except LiquidityUnavailable:
            return self._result(CapitalStatus.UNAVAILABLE)
        reading = BalanceReading.model_validate(reading)
        now = ensure_utc(self._clock.now())
        age = (now - reading.as_of).total_seconds()
        if age < 0:
            raise DataIntegrityError("liquidity reading is in the future")
        if age > self._config.liquidity_ttl_seconds:
            return self._result(CapitalStatus.STALE)
        if reading.currency != "USD" or reading.available is None or reading.current is None:
            return self._result(CapitalStatus.UNAVAILABLE)
        checking = min(reading.available, reading.current)
        if checking < self._config.checking_buffer_usd:
            return self._result(CapitalStatus.BUFFER_BREACH, max(Decimal("0"), checking))
        return self._result(CapitalStatus.OK, checking)

    def _result(
        self,
        status: CapitalStatus,
        checking: Decimal = Decimal("0"),
    ) -> DeployableCapital:
        """CRO-12/R-04: derive exact capacity without an execution capability."""
        with localcontext() as context:
            context.prec = 80
            reserved = decimal_money(sum(self._config.reserved_obligations_usd, Decimal("0")))
            deployable = decimal_money(
                max(Decimal("0"), checking - self._config.checking_buffer_usd - reserved)
            )
        return DeployableCapital(
            checking_used=checking,
            buffer=self._config.checking_buffer_usd,
            reserved=reserved,
            deployable=deployable if status == CapitalStatus.OK else Decimal("0"),
            status=status,
        )
