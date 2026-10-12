"""PF-04: host diagnostics of sealed public scan/replay; no broker execution."""

import cProfile
import io
import pstats
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import uuid4

from backend.agents.indicators import IndicatorMemo
from backend.agents.scanner import scan
from backend.core.config import load_yaml_config
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.data.history import load_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import CapitalStatus, DeployableCapital, MarketStatus, ProviderStatus
from backend.evaluation.fixtures import SYNTHETIC, seal_offline_fixtures
from backend.evaluation.registry import refuse_registered_holdout
from backend.evaluation.replay import ReplayRequest
from vws.replay_cli import _artifact_root


def _scan(
    end: date,
    symbols: tuple[str, ...] | None,
    *,
    project: Path,
    history_root: Path,
    offline_fixtures: bool,
    env_file: Path | None,
) -> None:
    if offline_fixtures and env_file is not None:
        raise ConfigurationError("PF-04: offline profiling never reads dotenv or accounts")
    registry = InstrumentRegistry.from_csv(project / "config")
    config = load_yaml_config(project / "config/config.yaml", allowed_symbols=registry.symbols)
    selected = tuple(sorted(symbols or config.watchlist))
    if len(set(selected)) != len(selected) or not set(selected).issubset(config.watchlist):
        raise ConfigurationError("PF-04: unique configured scan symbols required")
    calendar = MarketCalendar(start=date(1990, 1, 1), end=date(2035, 12, 31))
    calendar.session_close(end)
    with TemporaryDirectory(prefix="vws-profile-fakes-") as temporary:
        if offline_fixtures:
            seed = ReplayRequest(
                start=calendar.previous_sessions(end, 1)[0],
                end=end,
                symbols=selected,
                initial_equity=Decimal(10000),
                synthetic=True,
                funding=DeployableCapital(
                    checking_used=Decimal(11500),
                    buffer=Decimal(1500),
                    reserved=Decimal(0),
                    deployable=Decimal(10000),
                    status=CapitalStatus.OK,
                ),
            )
            frozen, _ = seal_offline_fixtures(Path(temporary), seed, calendar)
            print(SYNTHETIC)
        else:
            frozen = load_history(history_root, calendar)
            from vws.security_cli import open_context

            context = open_context(env_file)
            try:
                refuse_registered_holdout(
                    context.ledger,
                    min(frozen.bundle.for_symbol(name, "SPLIT").sessions[0] for name in selected),
                    end,
                )
            finally:
                context.ledger.engine.dispose()
        memo = IndicatorMemo()
        for name in selected:
            bars = tuple(
                bar
                for bar in frozen.bundle.for_symbol(name, "SPLIT").bars
                if bar.session_date <= end
            )
            if not bars:
                raise DataIntegrityError("PF-04: completed scan history unavailable")
            result = scan(
                name,
                bars,
                now=calendar.session_close(end) + timedelta(minutes=30),
                calendar=calendar,
                data_snapshot_hash=frozen.manifest.sha256,
                market_status=MarketStatus.OK,
                memo=memo,
            )
            if result.status != ProviderStatus.OK:
                raise DataIntegrityError(
                    "PF-04: scan inputs unavailable; no successful profile inferred"
                )
        print(f"Scanned {len(selected)} frozen public symbols through {end}; no trade approval.")


def execute(
    operation: str,
    *,
    end: date,
    project: Path,
    output_root: Path,
    history_root: Path,
    offline_fixtures: bool,
    symbols: tuple[str, ...] | None = None,
    start: date | None = None,
    env_file: Path | None = None,
    initial_equity: str | None = None,
    checking_balance: str | None = None,
    workers: int | None = None,
) -> tuple[Path, Path]:
    if operation not in {"scan", "replay"} or type(offline_fixtures) is not bool:
        raise ConfigurationError("PF-04: explicit scan/replay diagnostics required")
    if operation == "replay" and start is None:
        raise ConfigurationError("PF-04: replay profiling requires a start date")
    if offline_fixtures and env_file is not None:
        raise ConfigurationError("PF-04: offline profiling never reads dotenv or accounts")
    root = _artifact_root(output_root)
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        if operation == "scan":
            _scan(
                end,
                symbols,
                project=project,
                history_root=history_root,
                offline_fixtures=offline_fixtures,
                env_file=env_file,
            )
        else:
            from vws.replay_cli import execute as run_replay

            run_replay(
                cast(date, start),
                end,
                symbols,
                project=project,
                history_root=history_root,
                report_root=root / "reports",
                cache_root=root / "ind",
                offline_fixtures=offline_fixtures,
                env_file=env_file,
                initial_equity=initial_equity,
                checking_balance=checking_balance,
                workers=workers,
            )
    finally:
        profiler.disable()
    identity = uuid4().hex
    binary, text = root / f"{operation}_{identity}.pstats", root / f"{operation}_{identity}.txt"
    profiler.dump_stats(str(binary))
    buffer = io.StringIO()
    buffer.write(
        "Diagnostic parent-process profile; worker CPU is not included. This is not a performance gate.\n"
    )
    pstats.Stats(profiler, stream=buffer).strip_dirs().sort_stats("cumulative").print_stats(20)
    with text.open("x", encoding="utf-8") as stream:
        stream.write(buffer.getvalue())
    print(f"Profile top 20: {text}")
    return binary, text
