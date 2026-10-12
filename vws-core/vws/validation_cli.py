"""QV: explicit host registration and sealed offline validation; no broker calls."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

from backend.core.config import load_yaml_config
from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError
from backend.data.fee_schedule import load_fee_schedule
from backend.data.frozen_filings import load_filings
from backend.data.history import load_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import CapitalStatus, DeployableCapital
from backend.evaluation.calibrated_costs import snapshot as cost_snapshot
from backend.evaluation.registry import Registrations, load_registry
from backend.evaluation.replay import ReplayRequest
from backend.evaluation.universe import load as load_universe
from backend.evaluation.validation_runner import ReplayEvaluator, context_hash, registration_context
from backend.evaluation.walkforward import final_holdout, publish, walkforward
from vws.replay_cli import _artifact_root
from vws.security_cli import SecurityContext


def execute(
    context: SecurityContext,
    project: Path,
    operation: str,
    *,
    history_root: Path,
    initial_equity: str,
    checking_balance: str,
    family: str | None = None,
    workers: int = 1,
    phrase: str = "",
) -> tuple[Path, ...]:
    if operation not in {"register", "walkforward", "final"}:
        raise ConfigurationError("QV: unknown host validation command")
    registry = InstrumentRegistry.from_csv(project / "config")
    config = load_yaml_config(project / "config/config.yaml", allowed_symbols=registry.symbols)
    config.assert_settings_consistent(context.settings)
    calendar = MarketCalendar(start=date(1990, 1, 1), end=date(2035, 12, 31))
    frozen, filings = load_history(history_root, calendar), load_filings(history_root)
    schedule = load_fee_schedule(project / "config/fees.yaml")
    path = project / "config/variants.yaml"
    fixed = load_registry(path, config)
    raw = tuple(row for row in frozen.manifest.entries if row.adjustment == "RAW")
    days = next((row.sessions for row in raw if row.symbol == "SPY"), raw[0].sessions)
    equity, checking = Decimal(initial_equity), Decimal(checking_balance)
    reserved = sum(context.settings.reserved_obligations_usd, Decimal(0))
    universe = load_universe(project / "config/universe_history.csv", registry.symbols)
    seed = ReplayRequest(
        start=days[0],
        end=days[-1],
        symbols=tuple(sorted(config.watchlist[:20])) if universe is None else universe.symbols,
        universe=universe,
        initial_equity=equity,
        funding=DeployableCapital(
            checking_used=checking,
            buffer=context.settings.checking_buffer_usd,
            reserved=reserved,
            deployable=max(Decimal(0), checking - context.settings.checking_buffer_usd - reserved),
            status=CapitalStatus.OK
            if checking >= context.settings.checking_buffer_usd
            else CapitalStatus.BUFFER_BREACH,
        ),
    )
    store = Registrations(context.ledger)
    calibration = cost_snapshot(
        context.ledger, "PAPER" if context.settings.paper_trading else "LIVE"
    )
    if operation == "register":
        proof = store.register(
            fixed,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            frozen,
            config.qv,
            calendar,
            context_sha256=context_hash(
                context.settings, config, filings, schedule, seed, registry, calibration
            ),
        )
        print(
            f"Registered {proof.sha256}; holdout {proof.holdout_start} through {proof.holdout_end} is locked."
        )
        return ()
    proof = store.latest()
    if (
        proof.registry != fixed
        or proof.file_sha256 != hashlib.sha256(path.read_bytes()).hexdigest()
    ):
        raise ConfigurationError("QV-01: current registry file differs; register before evaluation")
    if family is None:
        raise ConfigurationError("QV: name one registered family")
    runner = ReplayEvaluator(
        proof,
        seed,
        frozen,
        filings,
        context.settings,
        config,
        registry,
        calendar,
        schedule,
        workers=workers,
        cache_root=_artifact_root(project / "data/cache/ind"),
        final=operation == "final",
        calibration=calibration,
    )
    runner.preflight(family)
    result = (
        final_holdout(context.ledger, proof, family, config.qv, runner, phrase)
        if operation == "final"
        else walkforward(proof, family, days, config.qv, runner)
    )
    # Identical ordinary re-runs have the same bytes and do not multiply trial counts.
    outputs = publish(result, _artifact_root(project / "data/validation"))
    from backend.evaluation.availability import GradePublication

    publication = GradePublication(
        registration_sha256=proof.sha256,
        family=family,
        kind=result.kind,
        result_sha256=result.sha256,
        settings_sha256=context.settings.config_hash,
        baseline=config,
        result=result,
        inputs=registration_context(
            context.settings, config, filings, schedule, seed, registry, calibration
        ),
    )
    context.ledger.append(
        SecurityEvent,
        kind="VALIDATION_REPORT",
        detail=publication.model_dump(mode="json"),
    )
    print(outputs[1].read_text(encoding="utf-8"))
    return outputs
