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
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.execution.coordinated_intent import (
    ApplyRequest,
    CoordinatedResolver,
    InventoryClient,
)
from backend.execution.coordinated_intent import (
    CoordinatedSnapshotReader as SnapshotReader,
)
from backend.execution.intent_resolution import (
    IntentRefusal,
    dry_run,
    validate_request,
)
from backend.execution.models import IntentDryRun
from backend.net.egress import EgressPolicy, build_allowlist
from backend.ops.quiescence import BrokerCoordination
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
    apply: bool = False,
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
        coordination = BrokerCoordination(project)
        reader = SnapshotReader(settings, project)
        reader.coordination = coordination
        clock = SystemClock()
        # Only unchanged EgressPolicy.deny may append through this engine.
        # No schema initialization, startup verification or state store is called.
        engine = create_engine(settings.db_url.get_secret_value())
        policy = EgressPolicy(build_allowlist(), Ledger(engine, clock))
        broker = IntentReadClient(settings, account, policy, clock)

        async def operation() -> IntentDryRun:
            return await dry_run(
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

        resolver = CoordinatedResolver(coordination)
        if apply:
            state = SystemStateStore(engine, clock, ConsoleNotifier(), verify_ledger=False)
            asyncio.run(
                resolver.apply(
                    operation,
                    reader=reader,
                    broker=InventoryClient(broker),
                    ledger=state.ledger,
                    state=state,
                    request=ApplyRequest(
                        intent_id=identity,
                        account=account,
                        environment=environment,
                        operator=operator,
                        reason=reason,
                        host=host,
                    ),
                    confirm=input,
                )
            )
        result = asyncio.run(resolver.run(operation))
        for line in result.lines():
            print(line)
        return 0
    except IntentRefusal as error:
        print(str(error), file=sys.stderr)
        logging.getLogger(__name__).warning("%s", error)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
