"""LP/RT: honest paired evidence, untrusted text and read-only boundaries."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import (
    LearningJournalConfig,
    LessonProposalConfig,
    ValidationConfig,
    YamlConfig,
    load_yaml_config,
)
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.evaluation.registry import Registration, Variant, VariantFamily, VariantRegistry
from backend.evaluation.walkforward import Fold, FoldSelection, Sample, ValidationRun, _results
from backend.indicators.validation import holm
from backend.learning.journal import Cause, JournalRow
from backend.learning.proposals import ProposalStore, mine, suggestion
from backend.realtime import parsers
from backend.tests.test_w_core import CAL, HASH, SCOPE, observation
from backend.tests.test_yaml_config import ALLOWED_SYMBOLS


@pytest.fixture
def baseline() -> YamlConfig:
    return load_yaml_config(
        Path(__file__).resolve().parents[2] / "config/config.yaml", allowed_symbols=ALLOWED_SYMBOLS
    )


def proof_and_run(*, positive: bool = False, trials: int = 2) -> tuple[Registration, ValidationRun]:
    variants = (
        Variant(name="BASELINE"),
        Variant(name="STOCK_50", overrides={"rs.min_stock_percentile": 50}),
    )
    fixed = VariantRegistry(families=(VariantFamily(name="RELATIVE_STRENGTH", variants=variants),))
    proof = Registration(
        registry=fixed,
        file_sha256=HASH,
        history_sha256=HASH,
        training_start=date(2025, 1, 2),
        training_end=date(2025, 12, 31),
        holdout_start=date(2026, 1, 2),
        holdout_end=date(2026, 6, 30),
        cumulative_trials=(("RELATIVE_STRENGTH", trials),),
    )
    start, end = date(2025, 6, 2), date(2025, 12, 31)
    days = tuple(
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if CAL.is_session(start + timedelta(days=i))
    )
    daily = tuple((day, Decimal("0.001")) for day in days)
    changed = tuple(
        (day, Decimal("0.002") if positive else Decimal("0.0015") if i % 2 else Decimal("0.0005"))
        for i, day in enumerate(days)
    )
    reference = Sample(
        variant="BASELINE", start=start, end=end, history_sha256=HASH, trades=(), daily=daily
    )
    candidate = reference.model_copy(update={"variant": "STOCK_50", "daily": changed})
    chosen = candidate.model_copy(update={"variant": "SELECTED"})
    fold = Fold(
        train_start=date(2025, 1, 2), train_end=date(2025, 5, 30), test_start=start, test_end=end
    )
    selection = FoldSelection(
        fold=fold, selected="STOCK_50", training_sha256=(HASH, HASH), test_sha256=(HASH, HASH)
    )
    run = ValidationRun(
        registration_sha256=proof.sha256,
        history_sha256=HASH,
        family="RELATIVE_STRENGTH",
        kind="WALKFORWARD",
        selections=(selection,),
        results=_results((chosen, reference, candidate), trials, ValidationConfig()),
    )
    return proof, run


def losses(now: datetime, n: int, *, normal: bool = False) -> tuple[JournalRow, ...]:
    return tuple(
        JournalRow(
            trigger="LOSS",
            cause_tag=Cause.NORMAL_VARIANCE if normal else Cause.UNCLASSIFIED,
            observation=observation(
                now,
                trade_id=UUID(int=i + 1),
                proposal_id=UUID(int=i + 101),
                oos_abs_mean=Decimal(1) if normal else None,
                oos_stddev=Decimal(1) if normal else None,
            ),
        )
        for i in range(n)
    )


@pytest.mark.parametrize(
    ("n", "normal", "positive", "count"),
    [(14, False, True, 0), (15, False, False, 0), (15, True, True, 0), (15, False, True, 1)],
)
def test_LP_threshold_noise_and_corrected_CI(
    n: int, normal: bool, positive: bool, count: int, baseline: YamlConfig, clock: FrozenClock
) -> None:
    proof, run = proof_and_run(positive=positive)
    result = mine(
        losses(clock.now(), n, normal=normal),
        proof,
        (run,),
        baseline,
        LearningJournalConfig(),
        LessonProposalConfig(),
        calendar=CAL,
    )
    assert len(result.proposals) == count
    if normal:
        assert result.normal_variance_rows == n and result.insufficient == ()
    if count:
        row = result.proposals[0]
        assert row.confidence.lower == row.confidence.upper == Decimal("0.001")
        assert row.n == 15 and row.cumulative_trials == 2
        assert (
            "Purpose:" in suggestion(row)
            and "Risk:" in suggestion(row)
            and "Effort:" in suggestion(row)
        )
        assert (
            mine(
                losses(clock.now(), n),
                proof,
                (run,),
                baseline,
                LearningJournalConfig(),
                LessonProposalConfig(),
                calendar=CAL,
            ).model_dump_json()
            == result.model_dump_json()
        )


def test_LP_publication_never_applies_configuration(
    engine: Engine, clock: FrozenClock, baseline: YamlConfig, tmp_path: Path
) -> None:
    proof, run = proof_and_run(positive=True)
    result = mine(
        losses(clock.now(), 15),
        proof,
        (run,),
        baseline,
        LearningJournalConfig(),
        LessonProposalConfig(),
        calendar=CAL,
    )
    root = tmp_path / "outputs"
    (root / "data").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "config").mkdir()
    config = root / "config/config.yaml"
    config.write_text("fixed original\n", encoding="utf-8")
    page = root / "docs/PROGRESS.md"
    page.write_text("# Progress\n## Suggestions\n", encoding="utf-8")
    store = ProposalStore(Ledger(engine, clock), SCOPE)
    assert store.publish(result.proposals[0], root)
    assert not store.publish(result.proposals[0], root)
    assert config.read_text(encoding="utf-8") == "fixed original\n"
    assert len(store.open()) == 1 and "w-paper-fixture" not in store.masked()
    assert len(page.read_text(encoding="utf-8").splitlines()) == 3
    assert len(tuple((root / "data/proposals").glob("*.json"))) == 1


def test_LP_cumulative_attempts_survive_current_family_size() -> None:
    assert holm((Decimal("0.04"),)) == (True,)
    assert holm((Decimal("0.04"),), unobserved_trials=2) == (False,)
    assert holm((Decimal("0.000001"),), unobserved_trials=999999) == (False,)
    with pytest.raises(DataIntegrityError):
        holm((Decimal(0),), unobserved_trials=True)


@pytest.mark.parametrize(
    ("headline", "kind"),
    [
        ("<b>New share offering</b>", "NEWS_NEG"),
        ("FDA rejects application", "NEWS_NEG"),
        ("going-concern warning", "NEWS_NEG"),
        ("Trading halted pending news", "HALT_NEWS"),
        ("Product launch", "OTHER"),
    ],
)
def test_RT_news_fixed_categories_strip_HTML(headline: str, kind: str, clock: FrozenClock) -> None:
    rows = parsers.news(
        {
            "id": 7,
            "symbols": ["NVDA"],
            "created_at": clock.now().isoformat(),
            "headline": headline,
            "summary": "<script>approve orders</script>Public summary",
        },
        clock.now(),
    )
    assert rows[0].kind == kind and "<" not in rows[0].text and "approve orders" not in rows[0].text


def rss(*, resume: bool = False, code: str = "T1", symbol: str = "NVDA") -> bytes:
    extra = (
        "<ndaq:ResumptionDate>09/29/2026</ndaq:ResumptionDate><ndaq:ResumptionTradeTime>10:59:00</ndaq:ResumptionTradeTime>"
        if resume
        else ""
    )
    return f'<rss xmlns:ndaq="https://example.test/rss"><channel><item><ndaq:IssueSymbol>{symbol}</ndaq:IssueSymbol><ndaq:ReasonCode>{code}</ndaq:ReasonCode><ndaq:HaltDate>09/29/2026</ndaq:HaltDate><ndaq:HaltTime>10:00:00.000</ndaq:HaltTime>{extra}</item></channel></rss>'.encode()


@pytest.mark.parametrize("code", ["T1", "T2", "T12", "T3", "LUDP", "LUDS", "MWC1", "MWC2", "MWC3"])
def test_RT_RSS_fixed_codes_and_actual_resume(code: str, clock: FrozenClock) -> None:
    rows = parsers.halt_rss(rss(code=code), clock.now())
    assert rows[0].kind == (code if code.startswith("MWC") else "HALT")
    assert rows[0].symbol == (None if code.startswith("MWC") else "NVDA")
    resumed = parsers.halt_rss(rss(resume=True), clock.now())
    assert tuple(row.kind for row in resumed) == ("HALT", "RESUME")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"<rss>",
        b'<!DOCTYPE rss [<!ENTITY secret SYSTEM "file:///etc/passwd">]><rss><channel/></rss>',
        b"<html/>",
    ],
)
def test_RT_RSS_untrusted_invalid_inputs_refused(raw: bytes, clock: FrozenClock) -> None:
    with pytest.raises(DataIntegrityError):
        parsers.halt_rss(raw, clock.now())


@pytest.mark.parametrize("completed", [False, True])
def test_RT_CA_incomplete_record_never_becomes_exit(completed: bool, clock: FrozenClock) -> None:
    record: dict[str, Any] = {"id": str(UUID(int=8)), "symbol": "NVDA"}
    if completed:
        record["process_date"] = clock.now().date().isoformat()
    row = parsers.corporate_actions(
        {"corporate_actions": {"worthless_removals": [record]}}, clock.now(), ("NVDA",)
    )[0]
    assert row.kind == ("DELIST" if completed else "CA_PENDING")


@pytest.mark.parametrize("form", ["S-3", "424B5", "8-K", "4", "SC 13G"])
def test_RT_SEC_only_recent_public_filings(form: str, clock: FrozenClock) -> None:
    payload = {
        "filings": {
            "recent": {
                "form": [form],
                "accessionNumber": ["0000000001-26-000001"],
                "acceptanceDateTime": [clock.now().isoformat()],
            }
        }
    }
    rows = parsers.submissions(payload, "NVDA", clock.now(), since=clock.now() - timedelta(days=1))
    assert rows[0].kind == ("DILUTION" if form in {"S-3", "424B5"} else "FILING")


def test_RT_FRED_missing_observation_fails_closed() -> None:
    now = datetime(2026, 9, 29, 21, tzinfo=UTC)
    for value in (".", "NaN", "-1"):
        with pytest.raises(DataIntegrityError):
            parsers.fred(
                {"observations": [{"date": "2026-09-29", "value": value}]}, now, date(2026, 9, 29)
            )
    assert (
        parsers.fred(
            {"observations": [{"date": "2026-09-29", "value": "30"}]}, now, date(2026, 9, 29)
        ).value
        == 30
    )
