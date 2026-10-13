"""EV-03: actual CLI, sealed reads, fixed performance target and no keyring/DB."""

import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter

import pytest

from backend.core.config import load_yaml_config
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.data.fee_schedule import load_fee_schedule
from backend.data.frozen_filings import load_filings
from backend.data.history import load_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import CapitalStatus, DeployableCapital
from backend.evaluation.fixtures import SYNTHETIC, offline_settings, seal_offline_fixtures
from backend.evaluation.replay import ReplayRequest, replay
from vws.__main__ import main
from vws.replay_cli import _artifact_root, execute

PROJECT = Path(__file__).resolve().parents[2]
D = Decimal


def test_EV_03_cli_offline_fixtures_uses_no_dotenv_secrets_or_account_db(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("PAPER_TRADING", "false")
    args = [
        "replay",
        "--start",
        "2026-08-01",
        "--end",
        "2026-10-02",
        "--symbols",
        "NVDA",
        "AVGO",
        "--offline-fixtures",
        "--reports",
        str(tmp_path / "reports"),
        "--cache",
        str(tmp_path / "cache"),
        "--workers",
        "1",
    ]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert SYNTHETIC in first and "Survivorship-bias warning" in first
    assert "Replay SHA-256:" in first and "Hypothetical/past results" in first
    assert tuple((tmp_path / "reports").glob("*.csv"))
    assert tuple((tmp_path / "cache/synthetic").glob("*.npz"))
    assert not tuple((tmp_path / "cache").glob("*.npz"))
    import json

    proof = json.loads(next((tmp_path / "reports").glob("replay_*.json")).read_bytes())
    assert proof["request"]["synthetic"] and proof["report"]["context"]["synthetic"]
    assert SYNTHETIC in proof["report"]["notes"]
    assert not tuple(tmp_path.glob("*.db"))
    files = tuple(sorted(path.name for path in (tmp_path / "reports").iterdir()))
    assert main(args) == 0
    assert tuple(sorted(path.name for path in (tmp_path / "reports").iterdir())) == files


def test_EV_03_offline_cli_refuses_explicit_real_dotenv_and_real_requires_seed(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError):
        execute(
            date(2026, 8, 1),
            date(2026, 10, 2),
            ("NVDA",),
            project=PROJECT,
            history_root=tmp_path,
            report_root=tmp_path,
            cache_root=tmp_path,
            offline_fixtures=True,
            env_file=tmp_path / "must-not-read.env",
        )
    with pytest.raises(ConfigurationError):
        execute(
            date(2026, 8, 1),
            date(2026, 10, 2),
            ("NVDA",),
            project=PROJECT,
            history_root=tmp_path,
            report_root=tmp_path,
            cache_root=tmp_path,
            offline_fixtures=False,
        )


def test_EV_03_protected_artifact_directory_is_refused_before_creation(tmp_path: Path) -> None:
    target = tmp_path / "config" / "unexpected"
    with pytest.raises(DataIntegrityError):
        _artifact_root(target)
    assert not target.exists() and not target.parent.exists()
    ordinary = _artifact_root(tmp_path / "safe" / "reports")
    assert ordinary.is_dir()


def test_PF_06_four_worker_replay_has_identical_proof(tmp_path: Path) -> None:
    registry = InstrumentRegistry.from_csv(PROJECT / "config")
    config = load_yaml_config(PROJECT / "config/config.yaml", allowed_symbols=registry.symbols)
    cal = MarketCalendar(start=date(2025, 1, 1), end=date(2027, 1, 1))
    seed = ReplayRequest(
        start=date(2026, 8, 3),
        end=date(2026, 10, 2),
        symbols=("AAPL", "AMZN", "AVGO", "NVDA"),
        initial_equity=D(10000),
        funding=DeployableCapital(
            checking_used=D(11500),
            buffer=D(1500),
            reserved=D(0),
            deployable=D(10000),
            status=CapitalStatus.OK,
        ),
        synthetic=True,
    )
    seal_offline_fixtures(tmp_path, seed, cal)
    history, filings = load_history(tmp_path, cal), load_filings(tmp_path)
    fees = load_fee_schedule(PROJECT / "config/fees.yaml")
    settings = offline_settings()
    first = replay(seed, history, filings, settings, config, registry, cal, fees, workers=1)
    second = replay(seed, history, filings, settings, config, registry, cal, fees, workers=4)
    assert first.decisions and first.sha256 == second.sha256


@pytest.mark.perf
def test_EV_03_twenty_symbols_seven_years_under_three_minutes(tmp_path: Path) -> None:
    registry = InstrumentRegistry.from_csv(PROJECT / "config")
    config = load_yaml_config(PROJECT / "config/config.yaml", allowed_symbols=registry.symbols)
    settings = offline_settings()
    calendar = MarketCalendar(start=date(2017, 1, 1), end=date(2027, 1, 1))
    seed = ReplayRequest(
        start=date(2019, 1, 1),
        end=date(2025, 12, 31),
        symbols=tuple(sorted(config.watchlist[:20])),
        initial_equity=D(10000),
        funding=DeployableCapital(
            checking_used=D(11500),
            buffer=D(1500),
            reserved=D(0),
            deployable=D(10000),
            status=CapitalStatus.OK,
        ),
    )
    seed = ReplayRequest.model_validate({**seed.model_dump(), "synthetic": True})
    seal_offline_fixtures(tmp_path, seed, calendar)
    frozen, filings = load_history(tmp_path, calendar), load_filings(tmp_path)
    fees = load_fee_schedule(PROJECT / "config/fees.yaml")
    cache = tmp_path / "ind"
    cache.mkdir()
    started = perf_counter()
    # Three compute workers plus the sequential parent; fixed baseline only.
    result = replay(
        seed,
        frozen,
        filings,
        settings,
        config,
        registry,
        calendar,
        fees,
        workers=3,
        cache_root=cache,
    )
    elapsed = perf_counter() - started
    print(
        f"EV-03 actual 20-symbol x 7-year replay: {elapsed:.3f}s; decisions={len(result.decisions)}; hash={result.sha256}"
    )
    assert len(seed.symbols) == 20 and len(result.portfolio) >= 1700
    assert result.decisions and any(item.outcome.status == "RESOLVED" for item in result.decisions)
    budget = float(os.environ.get("VWS_PERF_BUDGET_SECONDS", "180"))
    assert elapsed < budget, f"EV-03 runtime budget failed: {elapsed:.3f}s >= {budget:g}s"
