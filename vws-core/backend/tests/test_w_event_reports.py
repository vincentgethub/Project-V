"""ER-04/RT-12: event cohorts remain separate, masked and never double-counted."""

import pytest
from pydantic import ValidationError

from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.edge import EdgeKey
from backend.evaluation.outcomes import Outcome, OutcomeSetup
from backend.evaluation.weekly import render_weekly, report_csv
from backend.tests.test_edge import outcomes as edge_outcomes  # noqa: F401 - pytest fixture alias
from backend.tests.test_weekly_equity import calendar as calendar
from backend.tests.test_weekly_equity import history as history
from backend.tests.test_weekly_equity import results as results
from backend.tests.test_weekly_equity import weekly


def test_RT_event_cohorts_are_complete_subsets_and_keep_overall_counts(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar
) -> None:
    initial = weekly(results, history, calendar)
    changed = tuple(
        Outcome.model_validate(
            row.model_copy(
                update={
                    "setup": OutcomeSetup.model_validate(
                        row.setup.model_copy(update={"context_tags": ("fomc_day",)})
                    )
                }
            )
        )
        for row in results
    )
    report = weekly(changed, history, calendar)
    overall = tuple(card for card in report.cards if card.key.context_tag is None)
    tagged = tuple(card for card in report.cards if card.key.context_tag is not None)
    assert overall == initial.cards and tagged
    assert sum(card.n for card in overall) == sum(card.n for card in initial.cards)
    assert "event fomc_day" in render_weekly(report, mask_amounts=True)
    assert b"context_tag" in report_csv(report) and b"fomc_day" in report_csv(report)


@pytest.mark.parametrize("tags", [("INVENTED",), ("fomc_day", "fomc_day")])
def test_RT_outcome_context_has_a_closed_unique_taxonomy(
    results: tuple[Outcome, ...], tags: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError, match="taxonomy"):
        OutcomeSetup.model_validate(results[0].setup.model_copy(update={"context_tags": tags}))
    with pytest.raises(ValidationError):
        EdgeKey.model_validate(
            {
                "playbook": results[0].setup.playbook,
                "variant": "baseline",
                "cohort": "PAPER",
                "disposition": "APPROVED",
                "context_tag": "INVENTED",
            }
        )
