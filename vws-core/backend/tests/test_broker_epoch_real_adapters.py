"""LP-43: the two-snapshot barrier (quiescence.check) on the real adapters, every platform."""

from pathlib import Path
from typing import Any

import pytest

from backend.tests import test_coordinated_intent as coordinated
from backend.tests import test_panic_dryrun_stop as dryrun
from backend.tests.broker_real_adapters import Adapters
from backend.tests.lp43_epoch_child import CASES
from backend.tests.platform_expect import fresh_flag_state as fresh_flag_state
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_broker_flag_os import child
from backend.tests.test_intent_resolution import case as ga_case
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness

case = ga_case
harness = make_research_harness

REFUSAL = "RAISED:Broker epoch changed during evidence collection"


def run_child(case_name: str, project: Path) -> str:
    code = f"from backend.tests.lp43_epoch_child import run; run({case_name!r})"
    process = child(code, project)
    output, errors = process.communicate(timeout=60)
    assert process.returncode == 0 and not errors, errors
    return output.strip()


def test_LP43_unchanged_snapshots_pass_so_each_refusal_below_is_caused_by_its_change(
    tmp_path: Path,
) -> None:
    assert run_child("unchanged", tmp_path) == "OK"


@pytest.mark.parametrize("change", CASES)
def test_LP43_each_change_between_snapshot_a_and_b_refuses_with_the_epoch_message(
    tmp_path: Path, change: str
) -> None:
    assert run_child(change, tmp_path) == REFUSAL


def test_LP43_the_eight_cases_are_the_eight_epoch_refusal_conditions() -> None:
    assert len(CASES) == 8 and len(set(CASES)) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
async def test_LP43_panic_after_final_get_refuses_the_resolver_on_real_adapters(
    case: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, strict: bool
) -> None:
    adapters = Adapters(tmp_path)
    monkeypatch.setattr(coordinated, "FakeSlots", adapters.slots)
    try:
        await coordinated.test_Q1_Q7_Q12_panic_after_final_get_before_proof_barrier(
            case, adapters.flag(), strict
        )
    finally:
        adapters.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_LP43_stop_change_between_snapshots_refuses_the_dry_run_on_real_adapters(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapters = Adapters(tmp_path)
    monkeypatch.setattr(dryrun, "FakeSlots", adapters.slots)
    monkeypatch.setattr(dryrun, "FakeFlagAdapter", adapters.flag)
    try:
        await dryrun.test_B2_dryrun_real_ensure_stop_change_refuses_at_existing_comparison(
            harness, tmp_path, monkeypatch
        )
    finally:
        adapters.finish()
