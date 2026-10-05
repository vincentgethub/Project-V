"""R-07/R-08: create a Sandbox-only token and store Fernet ciphertext.

Run ``python -m scripts.plaid_sandbox_token --output .secrets/plaid-token.fernet``.
FERNET_KEY, PLAID_CLIENT_ID and PLAID_SECRET must already be configured. No token
or key is printed. Balance requires another product entitlement; Auth is used
only for Sandbox bootstrap. Runtime liquidity calls remain balance reads only.
"""

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

import plaid
from cryptography.fernet import Fernet
from plaid.api.plaid_api import PlaidApi
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest

from backend.core.config import Settings, load_settings
from backend.core.errors import ConfigurationError, ProviderError, SafetyError
from backend.core.logging import configure_logging, register_secrets
from backend.data.liquidity import prepare_plaid_client, validated_liquidity_settings


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
    output: Path,
    institution_id: str = "ins_109508",
    *,
    client: SandboxTokenClient | None = None,
) -> Path:
    """R-07/R-08: write ciphertext once; never overwrite an existing token file."""
    settings = validated_liquidity_settings(settings)
    if settings.plaid_env != "sandbox":
        raise ConfigurationError("token bootstrap is permitted only in Plaid Sandbox")
    if not institution_id.strip():
        raise ConfigurationError("Sandbox institution ID is required")
    try:
        cipher = Fernet(settings.fernet_key.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise ConfigurationError("a valid FERNET_KEY is required before bootstrap") from exc
    if output.exists():
        raise ConfigurationError("token output already exists; choose a new file")
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
                institution_id=institution_id,
                initial_products=[Products("auth")],
            ),
            _request_timeout=settings.request_timeout_seconds,
        )
        public_token = _token_field(public_response, "public_token")
        register_secrets(public_token)
        # VERIFY: https://plaid.com/docs/api/items/#itempublic_tokenexchange
        exchange_response = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token),
            _request_timeout=settings.request_timeout_seconds,
        )
        access_token = _token_field(exchange_response, "access_token")
        register_secrets(access_token)
        ciphertext = cipher.encrypt(access_token.encode("utf-8"))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as handle:
            handle.write(ciphertext)
        return output.resolve()
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
    """R-07: CLI loads optional dotenv explicitly and prints only the file path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--institution", default="ins_109508")
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()
    try:
        settings = load_settings(env_file=args.env_file)
        configure_logging()
        result = create_sandbox_token(settings, args.output, args.institution)
    except SafetyError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Encrypted Sandbox token saved to {result}")


if __name__ == "__main__":
    main()
