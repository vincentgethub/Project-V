"""OPS-03: success-only optional outbound ping and bound watchdog hook."""

from pydantic import SecretStr

from backend.core.database import JobRun
from backend.core.errors import ConfigurationError, ProviderError
from backend.core.logging import register_secrets
from backend.net.egress import EgressPolicy
from backend.net.http import make_client
from backend.ops.watchdog import Watchdog


class JobHealth:
    def __init__(self, watchdog: Watchdog, policy: EgressPolicy, ping_url: SecretStr) -> None:
        if policy.ledger.engine is not watchdog.state.engine:
            raise ConfigurationError("Job health must share the verified desk ledger")
        self.watchdog, self.policy = watchdog, policy
        self.url = ping_url.get_secret_value()
        if self.url:
            register_secrets(ping_url)
            policy.check_url(self.url, purpose="job_health")

    async def __call__(self, run: JobRun) -> None:
        if run.outcome == "PASS" and self.url:
            async with make_client(
                "job_health", policy=self.policy, allow_redirects=False, max_response_bytes=4096
            ) as client:
                response = await client.get(self.url)
                if not 200 <= response.status_code < 300:
                    raise ProviderError("The optional healthcheck ping did not succeed")
        await self.watchdog.check()
