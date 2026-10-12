"""QV: sealed run admission and exact resolved-trade projection boundaries."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine

from backend.agents.fundamentals import FrameworkStatus
from backend.core.clock import FrozenClock
from backend.core.config import load_yaml_config
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.earnings_reports import EarningsReport
from backend.data.fee_schedule import load_fee_schedule
from backend.data.frozen_filings import FilingEvidence, FilingsManifest, FrozenFilings, seal_filings
from backend.data.history import Adjustment, FrozenHistory, HistoryBundle
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import AssetClass, Playbook
from backend.evaluation import validation_runner
from backend.evaluation.calibrated_costs import CostCalibration
from backend.evaluation.costs import CostContext
from backend.evaluation.outcomes import OutcomeSetup, simulate_outcome
from backend.evaluation.registry import Registrations, Variant, VariantFamily, VariantRegistry
from backend.evaluation.replay import prepare_replay
from backend.evaluation.validation_runner import ReplayEvaluator, context_hash
from backend.ops.trading_controls import ControlScope
from backend.tests.test_replay import request
from backend.tests.test_v_earnings_wiring import submission
from backend.tests.test_v_validation import calendar as source_calendar
from backend.tests.test_v_validation import history as source_history

calendar, history = source_calendar, source_history
ROOT = Path(__file__).resolve().parents[2]
D = Decimal


@pytest.fixture
def runner_args(
    engine: Engine, clock: FrozenClock, calendar: MarketCalendar, history: FrozenHistory
) -> tuple[Any, ...]:
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    config = load_yaml_config(ROOT / "config/config.yaml", allowed_symbols=registry.symbols)
    from backend.evaluation.fixtures import offline_settings

    settings = offline_settings()
    seed = request(
        start=date(2019, 1, 1), end=date(2025, 12, 31), symbols=("NVDA",), synthetic=True
    )
    filings = FrozenFilings(manifest=FilingsManifest(entries=()), evidence=())
    fees = load_fee_schedule(ROOT / "config/fees.yaml")
    registry_set = VariantRegistry(
        families=(
            VariantFamily(
                name="PLAYBOOK",
                variants=(
                    Variant(name="BASELINE"),
                    Variant(
                        name="EARNINGS_GAP", overrides={"playbooks.enabled": ("EARNINGS_GAP",)}
                    ),
                ),
            ),
            VariantFamily(
                name="EXITS",
                variants=(
                    Variant(name="BASELINE"),
                    Variant(name="TIME_10", overrides={"evaluation.max_hold_sessions": 10}),
                ),
            ),
        )
    )
    proof = Registrations(Ledger(engine, clock)).register(
        registry_set,
        "a" * 64,
        history,
        config.qv,
        calendar,
        context_sha256=context_hash(settings, config, filings, fees, seed, registry),
    )
    return proof, seed, history, filings, settings, config, registry, calendar, fees


@pytest.mark.parametrize(
    "case", ["workers_bool", "workers_zero", "final_int", "context", "cost_mode", "universe"]
)
def test_QV_runner_validates_explicit_capability_and_frozen_scope(
    runner_args: tuple[Any, ...], case: str
) -> None:
    values = list(runner_args)
    kwargs: dict[str, Any] = {}
    if case == "workers_bool":
        kwargs["workers"] = True
    elif case == "workers_zero":
        kwargs["workers"] = 0
    elif case == "final_int":
        kwargs["final"] = 1
    elif case == "context":
        values[0] = values[0].model_copy(update={"context_sha256": None})
    elif case == "cost_mode":
        kwargs["calibration"] = CostCalibration(
            scope=ControlScope(account_id="other", environment="LIVE"),
            source_ids=(UUID(int=1),),
            high=D(2),
            observed_at=datetime(2026, 10, 8, tzinfo=UTC),
        )
    if case == "universe":
        assert ReplayEvaluator(*values).universe_sha256 is None
    else:
        with pytest.raises(ConfigurationError):
            ReplayEvaluator(*values, **kwargs)


@pytest.mark.parametrize("case", ["missing_submissions", "missing_all", "ETF"])
def test_EG_preflight_requires_causal_stock_evidence(
    runner_args: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    runner = ReplayEvaluator(*runner_args)
    if case == "ETF":
        asset = runner.registry.get("NVDA").model_copy(update={"asset_class": AssetClass.BROAD_ETF})
        monkeypatch.setattr(InstrumentRegistry, "get", lambda self, symbol: asset)
        runner.preflight("PLAYBOOK")
    elif case == "missing_submissions":
        with pytest.raises(ConfigurationError, match="submissions"):
            runner.preflight("PLAYBOOK")
    else:
        monkeypatch.setattr(FrozenFilings, "for_symbol", lambda *a, **k: SimpleNamespace())
        original = HistoryBundle.for_symbol

        def unavailable(self: HistoryBundle, symbol: str, adjustment: Adjustment) -> Any:
            if adjustment == "ALL":
                raise DataIntegrityError("EG missing ALL")
            return original(self, symbol, adjustment)

        monkeypatch.setattr(HistoryBundle, "for_symbol", unavailable)
        with pytest.raises(DataIntegrityError, match="missing ALL"):
            runner.preflight("PLAYBOOK")


@pytest.mark.parametrize("missing", [False, True])
def test_QV_sample_uses_exact_resolved_receipt_or_refuses_missing_evidence(
    runner_args: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    runner = ReplayEvaluator(*runner_args)
    start = runner.proof.training_start
    end = runner.calendar.add_sessions(start, 4)
    bar = runner.history.bundle.for_symbol("NVDA", "RAW").bars[201]
    setup = OutcomeSetup(
        alert_id=UUID(int=1),
        symbol="NVDA",
        playbook=Playbook.TREND_50EMA,
        cohort="REPLAY_IN_SAMPLE",
        disposition="APPROVED",
        fundamentals_status=FrameworkStatus.PASS,
        score=D(8),
        qty=2,
        limit=bar.open,
        stop=bar.open - D("0.01"),
        target=bar.open + D(1),
        decision_session=start,
        valid_until_session=end,
    )
    outcome = simulate_outcome(
        setup,
        runner.history,
        CostContext(atr14=D(1)),
        runner.calendar,
        runner.fees,
        policy=runner.config.evaluation,
    )
    assert outcome.status == "RESOLVED"
    if missing:
        outcome = outcome.model_copy(update={"net_money": None})
    prepared = prepare_replay(
        runner.seed.symbols, end, runner.history, runner.filings, runner.config, runner.registry
    )
    runner._preparations[runner.config.config_hash] = prepared
    monkeypatch.setattr(
        validation_runner,
        "replay",
        lambda *a, **k: SimpleNamespace(
            decisions=(SimpleNamespace(outcome=outcome),), portfolio=()
        ),
    )
    if missing:
        with pytest.raises(DataIntegrityError, match="exact trade"):
            runner(Variant(name="BASELINE"), start, end)
    else:
        result = runner(Variant(name="BASELINE"), start, end)
        assert len(result.trades) == 1 and result.trades[0].net_money == outcome.net_money


def test_PF_fixed_exit_variants_share_only_arrays_and_restart_the_cash_seed(
    runner_args: tuple[Any, ...],
) -> None:
    runner = ReplayEvaluator(*runner_args)
    start = runner.proof.training_start
    end = runner.calendar.add_sessions(start, 2)
    base = runner(Variant(name="BASELINE"), start, end)
    other = runner(
        Variant(name="TIME_10", overrides={"evaluation.max_hold_sessions": 10}), start, end
    )
    assert base.daily == other.daily and base.trades == other.trades == ()
    assert len(runner._shared_arrays) == 1 and len(runner._preparations) == 2


def test_EG_preflight_accepts_sealed_submissions_and_both_all_adjusted_series(
    runner_args: tuple[Any, ...], tmp_path: Path
) -> None:
    report = EarningsReport(
        symbol="NVDA",
        report_date=date(2020, 1, 2),
        known_at=datetime(2020, 1, 2, 21, tzinfo=UTC),
        accepted_at=datetime(2020, 1, 2, 21, tzinfo=UTC),
        accession="0001045810-20-000001",
        source="SEC_8K_ITEM_202",
    )
    filings = seal_filings(tmp_path, (FilingEvidence(symbol="NVDA", payload=submission(report)),))
    values = list(runner_args)
    values[3] = filings
    values[0] = values[0].model_copy(
        update={
            "context_sha256": context_hash(
                values[4], values[5], filings, values[8], values[1], values[6]
            )
        }
    )
    runner = ReplayEvaluator(*values)
    runner.preflight("PLAYBOOK")
