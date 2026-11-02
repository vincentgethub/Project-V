"""Host-only dry-run dispatch; avoids writable host/state composition."""

import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine

from backend.core.clock import SystemClock
from backend.core.ledger import Ledger
from backend.execution.intent_resolution import (
    IntentRefusal,
    SnapshotReader,
    dry_run,
    validate_request,
)
from backend.net.egress import EgressPolicy, build_allowlist
from backend.ops.read_checks import IntentReadClient
from backend.security.secrets import KeyringSecretStore
from vws.host_config import load_host_settings


class RealSnapshotWaiter:
    """The host waits outside DB transactions while retaining the runtime lock."""

    async def wait(self) -> None:
        await asyncio.sleep(60)


def execute(
    *,
    intent: str,
    account: str,
    environment: str,
    operator: str,
    reason: str,
    env_file: Path | None = None,
) -> int:
    engine = None
    try:
        host = (
            sys.stdin.isatty()
            and not any(
                os.environ.get(name) for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")
            )
            and not os.environ.get("SESSIONNAME", "").upper().startswith("RDP")
        )
        validate_request(environment, operator, reason, host)
        try:
            identity = UUID(intent)
        except ValueError:
            raise IntentRefusal("FIX_G_UNKNOWN_INTENT") from None
        project = Path(__file__).resolve().parents[1]
        settings = load_host_settings(project, env_file, KeyringSecretStore())
        if not settings.paper_trading:
            raise IntentRefusal("FIX_G_PAPER_ONLY")
        reader = SnapshotReader(settings, project)
        clock = SystemClock()
        # Only unchanged EgressPolicy.deny may append through this engine.
        # No schema initialization, startup verification or state store is called.
        engine = create_engine(settings.db_url.get_secret_value())
        policy = EgressPolicy(build_allowlist(), Ledger(engine, clock))
        broker = IntentReadClient(settings, account, policy, clock)
        result = asyncio.run(
            dry_run(
                reader,
                broker,
                clock,
                intent_id=identity,
                account=account,
                environment=environment,
                operator=operator,
                reason=reason,
                host=host,
                waiter=RealSnapshotWaiter(),
            )
        )
        for line in result.lines():
            print(line)
        return 0
    except IntentRefusal as error:
        print(str(error), file=sys.stderr)
        logging.getLogger(__name__).warning("%s", error)
        return 1
    except Exception:
        failure = IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
        print(str(failure), file=sys.stderr)
        logging.getLogger(__name__).warning("%s", failure)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
