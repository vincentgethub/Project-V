"""EV-03: read sealed local data, print reproducible evidence, write local reports."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.core.config import load_settings, load_yaml_config
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.money import decimal_money
from backend.data.fee_schedule import load_fee_schedule
from backend.data.frozen_filings import load_filings
from backend.data.history import canonical_bytes, load_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import CapitalStatus, DeployableCapital
from backend.evaluation.fixtures import SYNTHETIC, offline_settings, seal_offline_fixtures
from backend.evaluation.replay import ReplayRequest, ReplayRun, replay
from backend.evaluation.weekly import render_weekly, save_report
from backend.ops.anchors import controlled_path
from backend.security.write_guard import protected_output_path


def _artifact_root(path: Path) -> Path:
    """Validate destinations before creating even an empty artifact directory."""
    try:
        target = path.absolute()
        if protected_output_path(target.as_posix()):
            raise ValueError("protected output namespace")
        existing = target
        while not existing.exists():
            if existing.is_symlink() or existing == existing.parent:
                raise ValueError("indirect artifact path")
            existing = existing.parent
        if (
            not existing.is_dir()
            or existing.is_symlink()
            or existing.resolve(strict=True) != existing
        ):
            raise ValueError("artifact ancestry is indirect")
        target.mkdir(parents=True, exist_ok=True)
        controlled_path(target / "probe.json")
        return target
    except Exception:
        raise DataIntegrityError(
            "EV-03: artifact directory must use a direct unprotected path"
        ) from None


def _write(root: Path, result: ReplayRun) -> tuple[Path, Path, Path]:
    json_path, csv_path = save_report(root, result.report)
    proof = controlled_path(root / f"replay_{result.sha256}.json")
    contents = canonical_bytes(result)
    if len(contents) > 32 * 1024 * 1024:
        raise DataIntegrityError("EV-03: replay proof exceeds its report bound")
    if proof.exists():
        with proof.open("rb") as stream:
            previous = stream.read(len(contents) + 1)
        if previous != contents:
            raise DataIntegrityError("EV-03: existing replay proof differs; overwrite refused")
    else:
        with proof.open("xb") as stream:
            stream.write(contents)
    return proof, json_path, csv_path


def execute(
    start: date,
    end: date,
    symbols: tuple[str, ...] | None,
    *,
    project: Path,
    history_root: Path,
    report_root: Path,
    cache_root: Path,
    offline_fixtures: bool,
    env_file: Path | None = None,
    initial_equity: str | None = None,
    checking_balance: str | None = None,
    workers: int | None = None,
) -> ReplayRun:
    registry = InstrumentRegistry.from_csv(project / "config")
    config = load_yaml_config(project / "config/config.yaml", allowed_symbols=registry.symbols)
    if offline_fixtures and env_file is not None:
        raise ConfigurationError(
            "EV-03: offline fixtures do not read dotenv or account configuration"
        )
    settings = offline_settings() if offline_fixtures else load_settings(env_file=env_file)
    if not offline_fixtures and (initial_equity is None or checking_balance is None):
        raise ConfigurationError(
            "EV-03: supply --initial-equity and --checking-balance as explicit hypothetical assumptions"
        )
    equity = decimal_money(initial_equity or "10000")
    checking = (
        decimal_money(checking_balance)
        if checking_balance is not None
        else equity + settings.checking_buffer_usd
    )
    reserved = sum(settings.reserved_obligations_usd, Decimal(0))
    seed = ReplayRequest(
        start=start,
        end=end,
        symbols=tuple(sorted(symbols or config.watchlist[:20])),
        initial_equity=equity,
        synthetic=offline_fixtures,
        funding=DeployableCapital(
            checking_used=checking,
            buffer=settings.checking_buffer_usd,
            reserved=reserved,
            deployable=max(Decimal(0), checking - settings.checking_buffer_usd - reserved),
            status=CapitalStatus.OK
            if checking >= settings.checking_buffer_usd
            else CapitalStatus.BUFFER_BREACH,
        ),
    )
    if not set(seed.symbols).issubset(config.watchlist):
        raise ConfigurationError("EV-03: requested symbols are outside the configured watchlist")
    calendar = MarketCalendar(
        start=min(date(1990, 1, 1), start - timedelta(days=450)),
        end=max(date(2030, 12, 31), end + timedelta(days=450)),
    )
    fees = load_fee_schedule(project / "config/fees.yaml")
    # Create only explicit artifact roots after validating every existing parent.
    report_root = _artifact_root(report_root)
    cache_root = _artifact_root(cache_root / "synthetic" if offline_fixtures else cache_root)
    if offline_fixtures:
        print(SYNTHETIC)
        with TemporaryDirectory(prefix="vws-replay-fakes-") as temporary:
            root = Path(temporary)
            seal_offline_fixtures(root, seed, calendar)
            result = replay(
                seed,
                load_history(root, calendar),
                load_filings(root),
                settings,
                config,
                registry,
                calendar,
                fees,
                workers=workers,
                cache_root=cache_root,
            )
    else:
        result = replay(
            seed,
            load_history(history_root, calendar),
            load_filings(history_root),
            settings,
            config,
            registry,
            calendar,
            fees,
            workers=workers,
            cache_root=cache_root,
        )
    proof, json_path, csv_path = _write(report_root, result)
    print(render_weekly(result.report, mask_amounts=settings.telegram_mask_amounts))
    print(
        f"Replay SHA-256: {result.sha256}\nFilings manifest SHA-256: {result.filings_manifest_sha256}"
    )
    print(
        f"Modeled portfolio state: {result.final_state}; unavailable fundamentals: {result.unavailable_fundamentals}; blocked fundamentals: {result.blocked_fundamentals}"
    )
    print(f"Explicit hypothetical seed: {equity}; no broker execution or money movement")
    print(f"Saved {proof}\nSaved {json_path}\nSaved {csv_path}")
    return result
