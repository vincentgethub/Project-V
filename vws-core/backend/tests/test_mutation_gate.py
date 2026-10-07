"""OPS-06: unavailable mutation evidence cannot become a pass."""

import pytest

from backend.core.errors import DataIntegrityError
from scripts.check_mutations import require_complete_results


def test_OPS_06_complete_mutation_evidence_counts_exactly() -> None:
    assert (
        require_complete_results(
            "  backend.risk.mutant_1: killed\n  backend.notifications.mutant_2: caught by type check\n"
        )
        == 2
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "x: survived",
        "x: timeout",
        "x: no tests",
        "x: skipped",
        "x: not checked",
        "x: suspicious",
        "x: killed\nx: killed",
        "malformed",
    ],
)
def test_OPS_06_missing_or_unverified_mutants_cannot_pass(text: str) -> None:
    with pytest.raises(DataIntegrityError):
        require_complete_results(text)
