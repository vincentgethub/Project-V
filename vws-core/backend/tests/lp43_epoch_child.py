"""Child process for LP-43: one real two-snapshot proof, one change between snapshot A and B.

Runs in a fresh process so the platform flag starts unsignaled (the Windows event is
process-wide and sticky). Prints ``RAISED:<message>`` or ``OK``.
"""

import json
import sys
from pathlib import Path
from uuid import uuid4

from backend.ops.quiescence import BrokerActor, BrokerCoordination, QuiescenceError

CASES = (
    "lease-dropped",
    "lease-released",
    "epoch-missing",
    "generation-rewritten",
    "invocation-added",
    "begin-record-changed",
    "end-record-changed",
    "record-removed",
)


def panic_invocation(project: Path) -> None:
    actor = BrokerActor(BrokerCoordination(project), "panic")
    actor.start()
    actor.finish()


def change_record(coordination: BrokerCoordination, phase: str) -> None:
    path = next(coordination.directory.glob(f"*.{phase}"))
    payload = json.loads(path.read_text(encoding="ascii"))
    payload["slot"] = not payload["slot"]
    path.write_text(json.dumps(payload, sort_keys=True), encoding="ascii")


def run(case: str) -> None:
    project = Path(sys.argv[1])
    coordination = BrokerCoordination(project)
    coordination.initialize()
    if case in {"begin-record-changed", "end-record-changed", "record-removed"}:
        panic_invocation(project)
    coordination.acquire_proof()
    released = None
    try:
        if case == "lease-dropped":
            coordination._leases.pop().release()
        elif case == "lease-released":
            released = coordination._leases[0]
            released.release()
        elif case == "epoch-missing":
            coordination._epoch = None
        elif case == "generation-rewritten":
            (coordination.directory / "generation").write_text(uuid4().hex)
        elif case == "invocation-added":
            panic_invocation(project)
        elif case == "begin-record-changed":
            change_record(coordination, "BEGIN")
        elif case == "end-record-changed":
            change_record(coordination, "END")
        elif case == "record-removed":
            for path in coordination.directory.glob("*.BEGIN"):
                path.unlink()
            for path in coordination.directory.glob("*.END"):
                path.unlink()
        elif case != "unchanged":
            raise SystemExit("unknown case " + case)
        try:
            coordination.check()
        except QuiescenceError as error:
            print("RAISED:" + str(error), flush=True)
        else:
            print("OK", flush=True)
    finally:
        if released is not None:
            coordination._leases.remove(released)
        coordination.release_proof()
