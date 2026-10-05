"""SEC-11/R-08: bootstrap a Sandbox item and save its token only to the keyring.

Run ``python -m scripts.plaid_sandbox_token --env-file .env`` after configuring
Sandbox credentials. No token, key or credential path is printed. Auth is used
only for Sandbox bootstrap; runtime liquidity calls remain balance reads only.
"""

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

import plaid
from plaid.api.plaid_api import PlaidApi
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from pydantic import SecretStr

from backend.core.config import Settings, load_settings
from backend.core.errors import ConfigurationError, ProviderError, SafetyError
from backend.core.logging import configure_logging, register_secrets
from backend.data.liquidity import prepare_plaid_client, validated_liquidity_settings
from backend.security.secrets import KeyringSecretStore, SecretStore, assert_secret_sources


class SandboxTokenClient(Protocol):
    """R-08: bootstrap exposes only Sandbox creation and token exchange."""

    def sandbox_public_token_create(self, request: object, **kwargs: object) -> object:
        """R-08: create a test Item, never an external money instruction."""
        raise NotImplementedError("client must supply Sandbox token creation")

    def item_public_token_exchange(self, request: object, **kwargs: object) -> object:
        """R-07: exchange a public token for the secret access token."""
        raise NotImplementedError("client must supply public token exchange")


def create_sandbox_token(
    settings: Settings,
    institution_id: str = "ins_109508",
    *,
    client: SandboxTokenClient | None = None,
    secret_store: SecretStore | None = None,
) -> None:
    """SEC-11: keyring only; refuse an existing token before any provider call."""
    settings = validated_liquidity_settings(settings)
    assert_secret_sources("MANUAL")
    if settings.plaid_env != "sandbox":
        raise ConfigurationError("token bootstrap is permitted only in Plaid Sandbox")
    if not isinstance(institution_id, str) or not institution_id.strip():
        raise ConfigurationError("Sandbox institution ID is required")
    source = KeyringSecretStore() if secret_store is None else secret_store
    try:
        if source.get("PLAID_ACCESS_TOKEN") is not None:
            raise ConfigurationError("Plaid keyring token already exists; use validated rotation")
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("native keyring is unavailable before bootstrap") from None
    if client is None:
        if (
            not settings.plaid_client_id.get_secret_value()
            or not settings.plaid_secret.get_secret_value()
        ):
            raise ConfigurationError("Plaid Sandbox credentials are required")
        try:
            # VERIFY: https://github.com/plaid/plaid-python#usage
            configuration = plaid.Configuration(
                host=plaid.Environment.Sandbox,
                api_key={
                    "clientId": settings.plaid_client_id.get_secret_value(),
                    "secret": settings.plaid_secret.get_secret_value(),
                },
            )
            configuration.retries = 0
            sdk = PlaidApi(plaid.ApiClient(configuration))
            prepare_plaid_client(sdk, "sandbox")
            client = cast(SandboxTokenClient, sdk)
        except Exception:
            raise ConfigurationError("Plaid SDK could not be safely initialized") from None
    elif isinstance(client, PlaidApi):
        prepare_plaid_client(client, "sandbox")
    try:
        # VERIFY: https://plaid.com/docs/api/sandbox/#sandboxpublic_tokencreate
        # VERIFY: https://plaid.com/docs/balance/ (Balance is not standalone.)
        public_response = client.sandbox_public_token_create(
            SandboxPublicTokenCreateRequest(
                institution_id=institution_id, initial_products=[Products("auth")]
            ),
            _request_timeout=settings.request_timeout_seconds,
        )
        public_token = _token_field(public_response, "public_token")
        register_secrets(public_token)
        # VERIFY: https://plaid.com/docs/api/items/#itempublic_tokenexchange
        response = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token),
            _request_timeout=settings.request_timeout_seconds,
        )
        token = SecretStr(_token_field(response, "access_token"))
        register_secrets(token)
        try:
            source.set("PLAID_ACCESS_TOKEN", token)
            observed = source.get("PLAID_ACCESS_TOKEN")
            if observed is None or observed.get_secret_value() != token.get_secret_value():
                raise ConfigurationError("Sandbox keyring write could not be verified")
        except Exception:
            source.delete("PLAID_ACCESS_TOKEN")
            raise
    except ConfigurationError:
        raise
    except Exception:
        raise ProviderError("Sandbox token bootstrap failed; no secret was printed") from None


def _token_field(response: object, name: str) -> str:
    """R-07: validate token fields without putting their values in errors."""
    if isinstance(response, Mapping):
        value = response.get(name)
    elif name == "public_token":
        value = getattr(response, "public_token", None)
    elif name == "access_token":
        value = getattr(response, "access_token", None)
    else:
        raise ConfigurationError("Unsupported Plaid token field")
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError("Plaid token response is incomplete")
    return value


def main() -> None:
    """SEC-11/R-07: optional dotenv is explicit; token values are never printed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default="ins_109508")
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()
    try:
        settings = load_settings(env_file=args.env_file)
        configure_logging()
        create_sandbox_token(settings, args.institution)
    except SafetyError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    print("Sandbox access token saved to the native keyring")


if __name__ == "__main__":
    main()
