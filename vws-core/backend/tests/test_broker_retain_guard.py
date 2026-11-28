"""physical_call is fail-closed: the caller must retain() first; the counter never goes negative."""

from pathlib import Path

import pytest

from backend.ops.quiescence import BrokerActor, BrokerCoordination, QuiescenceError

REFUSAL = r"^physical_call requires retain\(\) before dispatch$"


def started(project: Path) -> BrokerActor:
    actor = BrokerActor(BrokerCoordination(project), "runtime")
    actor.start()
    return actor


def test_unretained_physical_call_is_refused_without_running_and_records_a_failure(
    tmp_path: Path,
) -> None:
    actor = started(tmp_path)
    ran: list[str] = []
    with pytest.raises(QuiescenceError, match=REFUSAL):
        actor.physical_call(lambda: ran.append("broker"))
    assert ran == [] and actor._pending == 0
    assert actor.failure_types == {"QuiescenceError"} and actor._healthy is False
    actor.finish()
    assert not list(actor.coordination.directory.glob("*.END")), "no END after a refused call"


def test_retained_physical_call_runs_and_returns_the_counter_to_zero(tmp_path: Path) -> None:
    actor = started(tmp_path)
    actor.retain()
    assert actor.physical_call(lambda: "result") == "result"
    assert actor._pending == 0 and actor.failure_types == set()
    actor.finish()
    assert len(list(actor.coordination.directory.glob("*.END"))) == 1


def test_a_second_call_after_the_retain_was_consumed_is_refused(tmp_path: Path) -> None:
    actor = started(tmp_path)
    actor.retain()
    actor.physical_call(lambda: None)
    with pytest.raises(QuiescenceError, match=REFUSAL):
        actor.physical_call(lambda: None)
    assert actor._pending == 0
    actor.finish()


def test_call_finished_never_drives_the_counter_negative(tmp_path: Path) -> None:
    actor = started(tmp_path)
    actor._call_finished(None)
    assert actor._pending == 0
    assert actor.failure_types == {"QuiescenceError"} and actor._healthy is False
    actor.finish()
