"""EX/PF: real partial-leg replay accounting and prepared-input scope checks."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.agents.setup_hunter import HuntDrop, SetupHunter
from backend.core.config import Settings, YamlConfig, load_yaml_config
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.fee_schedule import load_fee_schedule
from backend.data.frozen_filings import FilingEvidence, FrozenFilings, seal_filings
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries, seal_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import SetupCandidate, SizeEvidence
from backend.evaluation import replay as replay_module
from backend.evaluation.calibrated_costs import CostCalibration
from backend.evaluation.replay import ReplayRun, prepare_replay, replay
from backend.ops.trading_controls import ControlScope
from backend.risk.risk_cro import ChiefRiskOfficer
from backend.tests import test_replay as golden
from backend.tests.test_fundamentals import evidence, set_value

calendar, inputs = golden.calendar, golden.inputs
ROOT = Path(__file__).resolve().parents[2]
D = Decimal


def test_PF_preparation_process_pool_has_the_same_public_arrays(
    inputs: tuple[FrozenHistory, FrozenFilings],
) -> None:
    history, filings = inputs
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    config = load_yaml_config(ROOT / "config/config.yaml", allowed_symbols=registry.symbols)
    seed = golden.request(symbols=("NVDA",))
    serial = prepare_replay(seed.symbols, seed.end, history, filings, config, registry, workers=1)
    parallel = prepare_replay(seed.symbols, seed.end, history, filings, config, registry, workers=2)
    assert parallel == serial


def test_PR_size_callback_requires_a_completed_market_frame(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def assigned(self: SetupHunter, provider: Any) -> None:
        if provider is not None:
            provider("NVDA", D(8), 1, None, calendar.session_close(golden.request().start))

    monkeypatch.setattr(
        SetupHunter, "size_provider", property(lambda self: None, assigned), raising=False
    )
    with pytest.raises(DataIntegrityError, match="benchmark data is unavailable"):
        golden.run(golden.request(), inputs, calendar)


def test_FA_required_failed_framework_is_blocked_before_any_replay_candidate(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    tmp_path: Path,
) -> None:
    history, filings = inputs
    facts = []
    for row in filings.evidence:
        payload = row.payload.parsed()
        set_value(payload, "GrossProfit", 400)
        facts.append(FilingEvidence(symbol=row.symbol, payload=evidence(payload)))
    root = tmp_path / "failed-framework"
    root.mkdir()
    sealed = seal_filings(root, tuple(facts))
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    values = load_yaml_config(
        ROOT / "config/config.yaml", allowed_symbols=registry.symbols
    ).model_dump()
    values["fundamentals"]["mode"] = "require"
    result = replay(
        golden.request(),
        history,
        sealed,
        Settings(),
        YamlConfig.model_validate(values),
        registry,
        calendar,
        load_fee_schedule(ROOT / "config/fees.yaml"),
        workers=1,
    )
    assert result.blocked_fundamentals > 0 and not result.decisions
    assert all(point.equity == result.request.initial_equity for point in result.portfolio)


def test_RS_future_only_sector_history_is_never_used_early(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    tmp_path: Path,
) -> None:
    history, filings = inputs
    last = history.bundle.for_symbol("NVDA", "RAW").bars[-1]
    series = history.bundle.series + tuple(
        HistorySeries(symbol="XLK", adjustment=kind, bars=(last,))
        for kind in ("ALL", "RAW", "SPLIT")
    )
    root = tmp_path / "late-sector"
    root.mkdir()
    frozen = seal_history(root, HistoryBundle(series=series), calendar)
    result = golden.run(golden.request(), (frozen, filings), calendar)
    assert result.decisions and all(row.outcome.setup.symbol != "XLK" for row in result.decisions)


def test_ER_replay_full_CRO_veto_retains_the_same_unsized_base_as_other_filters(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_hunt, original_cro = SetupHunter.size_evidence, ChiefRiskOfficer.evaluate
    candidates: list[SetupCandidate] = []
    hunting = False

    def hunt(self: SetupHunter, *args: Any, **kwargs: Any) -> Any:
        nonlocal hunting
        hunting = True
        try:
            result = original_hunt(self, *args, **kwargs)
        finally:
            hunting = False
        candidates.extend(result.candidates)
        return result

    def veto(
        self: ChiefRiskOfficer,
        proposal: Any,
        portfolio: Any,
        market: Any,
        state: Any,
        now: Any,
        **kwargs: Any,
    ) -> Any:
        return original_cro(
            self,
            proposal,
            portfolio,
            market,
            state if hunting else SystemState.HALTED,
            now,
            **kwargs,
        )

    monkeypatch.setattr(SetupHunter, "size_evidence", hunt)
    monkeypatch.setattr(ChiefRiskOfficer, "evaluate", veto)
    result = golden.run(golden.request(symbols=("NVDA",)), inputs, calendar)
    candidate = candidates[0]
    factors = candidate.size_evidence
    assert factors is not None and factors.base_qty > candidate.qty
    assert result.decisions[0].outcome.setup.disposition == "CRO_VETO"
    assert result.decisions[0].outcome.setup.qty == factors.base_qty
    assert not any(
        row.setup.playbook == candidate.playbook
        and row.setup.decision_session == result.decisions[0].outcome.setup.decision_session
        and row.setup.disposition == "CRO_VETO"
        for row in result.filtered_outcomes
    )
    assert result.portfolio[-1].equity == result.request.initial_equity


@pytest.mark.parametrize(
    "variant,damage", [("SPLIT_1R", False), ("SPLIT_1R_TRAIL", False), ("SPLIT_1R", True)]
)
def test_EX_replay_cash_and_stop_protection_follow_real_partial_legs(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    tmp_path: Path,
    variant: str,
    damage: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history, filings = inputs
    seed = golden.request(symbols=("NVDA",))
    prices: dict[date, tuple[int | str, int | str, int | str, int | str]] = {
        date(2026, 9, 30): (100, "106.01", 100, "104.50"),
        date(2026, 10, 1): (101, "107.10", "100.50", 102),
        date(2026, 10, 2): (101, "107.10", "100.50", 102),
        date(2026, 10, 5): (100, 103, 99, 101),
    }
    root = tmp_path / "partial-history"
    root.mkdir()
    history = seal_history(
        root,
        HistoryBundle(
            series=tuple(
                HistorySeries(
                    symbol=row.symbol,
                    adjustment=row.adjustment,
                    bars=tuple(
                        bar.model_copy(
                            update=dict(
                                zip(
                                    ("open", "high", "low", "close"),
                                    (D(x) for x in prices[bar.session_date]),
                                    strict=True,
                                )
                            )
                        )
                        if bar.session_date in prices
                        else bar
                        for bar in row.bars
                    ),
                )
                for row in history.bundle.series
            )
        ),
        calendar,
    )
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    values = load_yaml_config(
        ROOT / "config/config.yaml", allowed_symbols=registry.symbols
    ).model_dump()
    values["exits"]["variant"] = variant
    config = YamlConfig.model_validate(values)
    if damage:
        held = replay_module._Held

        def too_few(*args: Any) -> Any:
            row = held(*args)
            if row.outcome.partial_exits:
                row.qty = row.outcome.partial_exits[0].fill.qty
            return row

        monkeypatch.setattr(replay_module, "_Held", too_few)
        with pytest.raises(DataIntegrityError, match="partial exit exceeds modeled held"):
            replay(
                seed,
                history,
                filings,
                Settings(),
                config,
                registry,
                calendar,
                load_fee_schedule(ROOT / "config/fees.yaml"),
                workers=1,
            )
        return
    result = replay(
        seed,
        history,
        filings,
        Settings(),
        config,
        registry,
        calendar,
        load_fee_schedule(ROOT / "config/fees.yaml"),
        workers=1,
    )
    trades = tuple(row.outcome for row in result.decisions if row.outcome.partial_exits)
    assert trades and all(row.status == "RESOLVED" for row in trades), tuple(
        (
            r.verdict.decision,
            r.outcome.setup.qty,
            r.outcome.setup.limit,
            r.outcome.setup.stop,
            r.outcome.setup.target,
            r.outcome.status,
            r.outcome.reason,
        )
        for r in result.decisions
    )
    executed = tuple(
        row.outcome
        for row in result.decisions
        if row.outcome.setup.disposition == "APPROVED" and row.outcome.entry_fill is not None
    )
    assert all(row.status == "RESOLVED" for row in executed)
    assert result.portfolio[-1].equity == seed.initial_equity + sum(
        (row.net_money for row in executed if row.net_money is not None), D(0)
    )
    if variant == "SPLIT_1R_TRAIL":
        assert any(row.stop_moves for row in trades)
        assert all(point.equity > 0 for point in result.portfolio[2:-1])
    # Altered portfolio evidence cannot masquerade as a deterministic run.
    with pytest.raises(ValidationError, match="marks"):
        ReplayRun.model_validate(
            result.model_copy(update={"portfolio": tuple(reversed(result.portfolio))})
        )
    with pytest.raises(ValidationError, match="binding differs"):
        ReplayRun.model_validate(result.model_copy(update={"risk_config_sha256": "b" * 64}))


@pytest.mark.parametrize("shadow", [False, True])
def test_EX_one_share_split_candidate_or_filter_never_creates_a_leg(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    shadow: bool,
) -> None:
    original = SetupHunter.size_evidence
    observed: list[SetupCandidate] = []

    def one_share(self: SetupHunter, *args: Any, **kwargs: Any) -> Any:
        found = original(self, *args, **kwargs)
        if not found.candidates:
            return found
        changed = tuple(
            SetupCandidate.model_validate(row.model_copy(update={"qty": 1, "size_evidence": None}))
            for row in found.candidates
        )
        observed.extend(changed)
        if shadow:
            return type(found).model_validate(
                found.model_copy(
                    update={
                        "candidates": (),
                        "drops": found.drops
                        + tuple(
                            HuntDrop(
                                playbook=row.playbook,
                                reason="one-share boundary fixture",
                                filtered_candidate=row,
                                reductions=SizeEvidence(base_qty=1, relative_strength=D(0)),
                            )
                            for row in changed
                        ),
                    }
                )
            )
        return type(found).model_validate(found.model_copy(update={"candidates": changed}))

    monkeypatch.setattr(SetupHunter, "size_evidence", one_share)
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    values = load_yaml_config(
        ROOT / "config/config.yaml", allowed_symbols=registry.symbols
    ).model_dump()
    values["exits"]["variant"] = "SPLIT_1R"
    result = replay(
        golden.request(),
        *inputs,
        Settings(),
        YamlConfig.model_validate(values),
        registry,
        calendar,
        load_fee_schedule(ROOT / "config/fees.yaml"),
        workers=1,
    )
    assert observed and result.decisions == ()
    assert not any(row.setup.qty == 1 for row in result.filtered_outcomes)


@pytest.mark.parametrize("case", ["workers", "unordered", "scope", "cost_mode", "counterfactual"])
def test_PF_prepared_replay_and_counterfactuals_cannot_cross_scope(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    case: str,
) -> None:
    history, filings = inputs
    seed = golden.request(symbols=("NVDA",))
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    config = load_yaml_config(ROOT / "config/config.yaml", allowed_symbols=registry.symbols)
    fees = load_fee_schedule(ROOT / "config/fees.yaml")
    if case in {"workers", "unordered"}:
        with pytest.raises(DataIntegrityError, match="ordered symbols"):
            prepare_replay(
                ("NVDA", "NVDA") if case == "unordered" else seed.symbols,
                seed.end,
                history,
                filings,
                config,
                registry,
                workers=True if case == "workers" else 1,
            )
        return
    prepared = prepare_replay(seed.symbols, seed.end, history, filings, config, registry)
    kwargs: dict[str, Any] = {"preparation": prepared}
    if case == "scope":
        kwargs["preparation"] = prepared.model_copy(update={"filings_manifest_sha256": "0" * 64})
    elif case == "cost_mode":
        from datetime import UTC, datetime
        from uuid import UUID

        kwargs["calibration"] = CostCalibration(
            scope=ControlScope(account_id="other", environment="LIVE"),
            source_ids=(UUID(int=1),),
            high=D(2),
            observed_at=datetime(2026, 10, 8, tzinfo=UTC),
        )
    if case == "counterfactual":
        result = replay(
            seed,
            history,
            filings,
            Settings(),
            config,
            registry,
            calendar,
            fees,
            workers=1,
            **kwargs,
        )
        with pytest.raises(ValidationError, match="counterfactuals"):
            ReplayRun.model_validate(
                result.model_copy(update={"filtered_outcomes": (result.decisions[0].outcome,)})
            )
    else:
        with pytest.raises(DataIntegrityError):
            replay(
                seed,
                history,
                filings,
                Settings(),
                config,
                registry,
                calendar,
                fees,
                workers=1,
                **kwargs,
            )


@pytest.mark.parametrize(
    "fault", ["date", "filter_bound", "decision_bound", "held_bound", "exit_quantity"]
)
def test_EV_replay_refuses_stale_sizing_and_corrupt_share_books(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    original_hunt = SetupHunter.size_evidence
    if fault in {"filter_bound", "decision_bound"}:
        monkeypatch.setattr(replay_module, "MAX_REPLAY_DECISIONS", 0)

    def hunt(self: SetupHunter, *args: Any, **kwargs: Any) -> Any:
        result = original_hunt(self, *args, **kwargs)
        if fault == "date" and result.candidates:
            candidate = result.candidates[0]
            provider = self.size_provider
            assert provider is not None
            provider(
                candidate.symbol,
                candidate.score,
                candidate.qty,
                args[2],
                args[4] + timedelta(days=1),
            )
        if fault == "decision_bound":
            result = type(result).model_validate(
                result.model_copy(
                    update={
                        "candidates": tuple(
                            type(row).model_validate(row.model_copy(update={"size_evidence": None}))
                            for row in result.candidates
                        ),
                        "drops": tuple(
                            type(row).model_validate(
                                row.model_copy(
                                    update={
                                        "filtered_candidate": None,
                                        "reductions": None,
                                        "filtered_cro_cap": None,
                                    }
                                )
                            )
                            for row in result.drops
                        ),
                    }
                )
            )
        return result

    monkeypatch.setattr(SetupHunter, "size_evidence", hunt)
    original_held = replay_module._Held

    def damaged(*args: Any) -> Any:
        value = original_held(*args)
        value.qty = 10**9 + 1 if fault == "held_bound" else value.qty + 1
        return value

    if fault in {"held_bound", "exit_quantity"}:
        monkeypatch.setattr(replay_module, "_Held", damaged)
    with pytest.raises(
        DataIntegrityError,
        match="another completed session|inventory exceeded|decision bound|held split|held shares",
    ):
        golden.run(golden.request(), inputs, calendar)
