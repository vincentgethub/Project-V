"""R-01/R-02/R-03/R-04/R-05/CRO-05/CRO-12 immutable-contract tests."""

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from shutil import copyfile
from typing import cast
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    AssetClass,
    BlackoutWindow,
    CapitalStatus,
    Decision,
    DeployableCapital,
    FlowSignal,
    Instrument,
    Intent,
    MarketContext,
    MarketStatus,
    OpenOrder,
    Playbook,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    ProviderResult,
    ProviderStatus,
    ResearchThesis,
    RuleResult,
    ScannerHit,
    SentimentClassification,
    SentimentSignal,
    SetupCandidate,
    SetupCriterion,
    Severity,
    Side,
    TradeProposal,
    Verdict,
    snapshot_hash,
)

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
PROPOSAL_ID = UUID("10000000-0000-0000-0000-000000000001")
SIGNAL_ID = UUID("10000000-0000-0000-0000-000000000002")


def proposal(**changes: object) -> TradeProposal:
    data: dict[str, object] = {
        "proposal_id": PROPOSAL_ID,
        "signal_id": SIGNAL_ID,
        "account_id": "paper",
        "symbol": "AAPL",
        "side": Side.BUY,
        "intent": Intent.ENTRY,
        "qty": 1,
        "limit_price": Decimal("100"),
        "stop_price": Decimal("95"),
        "source": ProposalSource.SIGNAL,
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=1),
    }
    data.update(changes)
    return TradeProposal.model_validate(data)


def instrument(symbol: str = "AAPL", **changes: object) -> Instrument:
    data: dict[str, object] = {
        "symbol": symbol,
        "asset_class": AssetClass.STOCK,
        "gics_sector": "Information Technology",
        "themes": ("TECH",),
        "is_leveraged": False,
        "is_inverse": False,
        "tradable": True,
    }
    data.update(changes)
    return Instrument.model_validate(data)


def snapshot(**changes: object) -> PortfolioSnapshot:
    data: dict[str, object] = {
        "account_id": "paper",
        "account_type": AccountType.CASH,
        "as_of": NOW,
        "equity": Decimal("10000"),
        "cash": Decimal("9900"),
        "settled_cash": Decimal("9900"),
        "positions": {"AAPL": Position(qty=1, avg_cost=Decimal("90"), last_price=Decimal("100"))},
        "open_orders": (),
        "high_water_mark": Decimal("10000"),
        "day_start_equity": Decimal("10000"),
    }
    data.update(changes)
    return PortfolioSnapshot.model_validate(data)


@pytest.mark.parametrize("bad", [True, 1.5, "1", 0, -1])
def test_R_01_whole_positive_shares_require_strict_integer(bad: object) -> None:
    with pytest.raises(ValidationError):
        proposal(qty=bad)


@pytest.mark.parametrize(
    "bad",
    [True, 100.0, 100, "100.00", Decimal("NaN"), "NaN", Decimal("Infinity"), Decimal("99.999999")],
)
def test_R_02_R_04_R_13_prices_never_coerce_non_decimal_nan_or_subcent_units(bad: object) -> None:
    with pytest.raises(ValidationError):
        proposal(limit_price=bad)


@pytest.mark.parametrize(
    "stop", [None, Decimal("100"), Decimal("100.01"), Decimal("0"), Decimal("-1")]
)
def test_R_01_entry_stop_must_be_positive_and_strictly_below_limit(stop: object) -> None:
    with pytest.raises(ValidationError):
        proposal(stop_price=stop)
    assert proposal(stop_price=Decimal("99.99")).stop_price == Decimal("99.99")


@pytest.mark.parametrize(
    "side,intent",
    [
        (Side.SELL, Intent.ENTRY),
        (Side.SELL, Intent.ADD),
        (Side.BUY, Intent.REDUCE),
        (Side.BUY, Intent.EXIT),
    ],
)
def test_R_01_side_and_intent_cannot_create_short_entry(side: Side, intent: Intent) -> None:
    with pytest.raises(ValidationError):
        proposal(side=side, intent=intent)


def test_R_01_R_09_valid_exit_does_not_require_stop() -> None:
    exit_proposal = proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None)
    assert exit_proposal.qty == 1
    assert exit_proposal.stop_price is None


def test_R_02_signal_is_required_and_unexpected_order_types_are_forbidden() -> None:
    data = proposal().model_dump()
    del data["signal_id"]
    with pytest.raises(ValidationError):
        TradeProposal.model_validate(data)
    with pytest.raises(ValidationError):
        proposal(order_type="MARKET")
    with pytest.raises(ValidationError):
        proposal(account_id=" ")


def test_R_03_snapshot_is_detached_and_deeply_immutable() -> None:
    positions = {"AAPL": Position(qty=1, avg_cost=Decimal("90"), last_price=Decimal("100"))}
    state = snapshot(positions=positions)
    positions.clear()
    assert state.positions["AAPL"].value == Decimal("100")
    with pytest.raises(TypeError):
        cast(dict[str, Position], state.positions)["AAPL"] = Position(
            qty=2, avg_cost=Decimal("90"), last_price=Decimal("100")
        )
    with pytest.raises(ValidationError):
        state.positions["AAPL"].qty = 99
    with pytest.raises(ValidationError):
        state.cash = Decimal("0")
    assert state.model_dump(mode="json")["positions"]["AAPL"]["qty"] == 1


def test_R_03_R_04_snapshot_hash_is_canonical_exact_and_change_sensitive() -> None:
    first = snapshot()
    scaled = snapshot(equity=Decimal("10000.00"), cash=Decimal("9900.000000"))
    assert snapshot_hash(first) == snapshot_hash(scaled)
    assert snapshot_hash(first) != snapshot_hash(snapshot(cash=Decimal("9899.99")))
    assert len(snapshot_hash(first)) == 64


def test_R_02_CRO_09_negative_equity_is_preserved_for_halt_evaluation() -> None:
    assert snapshot(equity=Decimal("-1")).equity == Decimal("-1")
    assert snapshot(equity=Decimal("0")).equity == Decimal("0")


def test_R_05_aware_instants_are_normalized_and_naive_instants_fail() -> None:
    chicago = timezone(timedelta(hours=-5))
    assert proposal(created_at=NOW.astimezone(chicago)).created_at == NOW
    assert proposal().created_at.tzinfo is UTC
    with pytest.raises(ValidationError):
        proposal(created_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        proposal(created_at="2026-10-02T16:00:00Z")


@pytest.mark.parametrize(
    "status", [CapitalStatus.BUFFER_BREACH, CapitalStatus.UNAVAILABLE, CapitalStatus.STALE]
)
def test_CRO_12_non_ok_funding_cannot_advertise_deployable_cash(status: CapitalStatus) -> None:
    with pytest.raises(ValidationError):
        DeployableCapital(
            checking_used=Decimal("2000"),
            buffer=Decimal("1500"),
            reserved=Decimal("0"),
            deployable=Decimal("500"),
            status=status,
        )
    assert (
        DeployableCapital(
            checking_used=Decimal("2000"),
            buffer=Decimal("1500"),
            reserved=Decimal("0"),
            deployable=Decimal("0"),
            status=status,
        ).deployable
        == 0
    )


def test_CRO_12_ok_funding_requires_exact_buffer_reserve_equation() -> None:
    assert (
        DeployableCapital(
            checking_used=Decimal("2000"),
            buffer=Decimal("1500"),
            reserved=Decimal("100"),
            deployable=Decimal("400"),
            status=CapitalStatus.OK,
        ).deployable
        == 400
    )
    with pytest.raises(ValidationError):
        DeployableCapital(
            checking_used=Decimal("2000"),
            buffer=Decimal("1500"),
            reserved=Decimal("100"),
            deployable=Decimal("400.01"),
            status=CapitalStatus.OK,
        )
    with pytest.raises(ValidationError):
        DeployableCapital(
            checking_used=Decimal("1499.99"),
            buffer=Decimal("1500"),
            reserved=Decimal("0"),
            deployable=Decimal("0"),
            status=CapitalStatus.OK,
        )


def test_R_02_CMP_06_all_current_account_flags_are_required() -> None:
    flags = AccountFlags(
        trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
    )
    assert not flags.blocked
    assert flags.model_copy(update={"account_blocked": True}).blocked
    assert flags.model_copy(update={"status": "ACCOUNT_UPDATED"}).blocked
    with pytest.raises(ValidationError):
        AccountFlags.model_validate({"status": "ACTIVE"})


def test_R_02_verdict_cannot_claim_approval_with_failed_block_or_no_evidence() -> None:
    data: dict[str, object] = {
        "proposal_id": PROPOSAL_ID,
        "decision": Decision.APPROVED,
        "results": (),
        "config_hash": "a" * 64,
        "snapshot_hash": "b" * 64,
        "evaluated_at": NOW,
    }
    with pytest.raises(ValidationError):
        Verdict.model_validate(data)
    failure = RuleResult(
        rule_id="CRO-01",
        passed=False,
        severity=Severity.BLOCK,
        observed="HALTED",
        limit="RUNNING",
        message="state blocks entry",
    )
    data["results"] = (failure,)
    with pytest.raises(ValidationError):
        Verdict.model_validate(data)
    data["decision"] = Decision.VETOED
    assert Verdict.model_validate(data).decision == Decision.VETOED


def test_R_02_DAT_02_market_missing_nan_and_zero_prices_fail_closed() -> None:
    for value in (None, Decimal("NaN"), Decimal("0"), Decimal("-1")):
        with pytest.raises(ValidationError):
            MarketContext.model_validate(
                {
                    "last_price": value,
                    "last_price_ts": NOW,
                    "adv20_usd": Decimal("10000"),
                    "status": MarketStatus.OK,
                }
            )


def test_CRO_05_registry_lookthrough_and_declared_sector_fallback() -> None:
    etf = instrument("XLK", asset_class=AssetClass.SECTOR_ETF)
    registry = InstrumentRegistry([instrument(), etf])
    assert registry.sector_weights("XLK") == {"Information Technology": Decimal("1")}
    supplied = {"XLK": {"Information Technology": Decimal("0.9"), "Financials": Decimal("0.1")}}
    weighted = InstrumentRegistry([instrument(), etf], supplied)
    supplied["XLK"].clear()
    assert weighted.sector_weights("XLK")["Financials"] == Decimal("0.1")
    with pytest.raises(TypeError):
        cast(dict[str, Decimal], weighted.sector_weights("XLK"))["Financials"] = Decimal("1")
    with pytest.raises(FrozenInstanceError):
        weighted.blackout_windows = ()  # type: ignore[misc]  # Intentional mutation attempt.


@pytest.mark.parametrize(
    "weight", [Decimal("0.99"), Decimal("1.01"), Decimal("0"), Decimal("-1"), Decimal("NaN"), 1.0]
)
def test_CRO_05_invalid_or_incomplete_etf_weights_fail_closed(weight: object) -> None:
    etf = instrument("XLK", asset_class=AssetClass.SECTOR_ETF)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([etf], {"XLK": {"Information Technology": cast(Decimal, weight)}})


def test_R_02_CMP_07_registry_unknown_duplicate_and_empty_names_fail_closed() -> None:
    registry = InstrumentRegistry([instrument()])
    with pytest.raises(DataIntegrityError):
        registry.get("UNKNOWN")
    with pytest.raises(DataIntegrityError):
        registry.identical_group("UNKNOWN")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([])
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument(), instrument()])
    with pytest.raises(ValidationError):
        instrument("aapl")
    with pytest.raises(ValidationError):
        instrument(themes=("TECH", "TECH"))
    with pytest.raises(ValidationError):
        instrument(themes=(" ",))


def test_CMP_01_identical_group_is_explicit_and_immutable() -> None:
    registry = InstrumentRegistry(
        [instrument(), instrument("MSFT"), instrument("NVDA")],
        identical_groups={"EXPLICIT_OPERATOR_GROUP": ["AAPL", "MSFT"]},
    )
    assert registry.identical_group("AAPL") == frozenset({"AAPL", "MSFT"})
    assert registry.identical_group("NVDA") == frozenset({"NVDA"})
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(
            [instrument(), instrument("MSFT")], identical_groups={"GROUP": ["AAPL", "UNKNOWN"]}
        )


def test_CRO_11_blackout_requires_aware_increasing_interval_and_known_symbol() -> None:
    window = BlackoutWindow(
        start=NOW, end=NOW + timedelta(hours=1), reason="operator event", symbol="AAPL"
    )
    assert InstrumentRegistry([instrument()], blackout_windows=[window]).blackout_windows == (
        window,
    )
    with pytest.raises(ValidationError):
        BlackoutWindow(start=NOW, end=NOW, reason="event")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(
            [instrument()], blackout_windows=[window.model_copy(update={"symbol": "UNKNOWN"})]
        )


def test_R_02_csv_sample_loads_exact_schema_and_leveraged_names_are_restricted() -> None:
    registry = InstrumentRegistry.from_csv(Path(__file__).resolve().parents[2] / "config")
    assert len(registry.symbols) == 10
    assert registry.get("TQQQ").is_leveraged and not registry.get("TQQQ").tradable
    assert registry.get("SH").is_inverse and not registry.get("SH").tradable
    assert sum(registry.sector_weights("SPY").values(), Decimal("0")) == Decimal("1")
    assert registry.blackout_windows == ()


def test_R_02_policy_csv_missing_file_or_surplus_column_fails_typed(tmp_path: Path) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.from_csv(tmp_path)
    (tmp_path / "instruments.csv").write_text("symbol,unexpected\nAAPL,true\n", encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.from_csv(tmp_path)


def test_R_03_snapshot_symbol_order_does_not_change_hash() -> None:
    aapl = Position(qty=1, avg_cost=Decimal("90"), last_price=Decimal("100"))
    msft = Position(qty=2, avg_cost=Decimal("190"), last_price=Decimal("200"))
    positions: Mapping[str, Position] = {"AAPL": aapl, "MSFT": msft}
    reverse = {"MSFT": msft, "AAPL": aapl}
    assert snapshot_hash(snapshot(positions=positions)) == snapshot_hash(
        snapshot(positions=reverse)
    )


@pytest.mark.parametrize("field", ["signal_id", "expires_at"])
def test_R_02_R_14_proposal_signal_and_expiry_are_required(field: str) -> None:
    data = proposal().model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        TradeProposal.model_validate(data)


@pytest.mark.parametrize("expiry", [NOW, NOW - timedelta(microseconds=1), NOW.replace(tzinfo=None)])
def test_R_05_R_14_expiry_must_be_aware_and_after_creation(expiry: datetime) -> None:
    with pytest.raises(ValidationError):
        proposal(expires_at=expiry)
    assert proposal(expires_at=NOW + timedelta(microseconds=1)).expires_at > NOW


@pytest.mark.parametrize(
    "target", [Decimal("0"), Decimal("100"), Decimal("99.99"), Decimal("100.001")]
)
def test_R_01_R_13_entry_target_is_optional_positive_cent_price_above_limit(
    target: Decimal,
) -> None:
    with pytest.raises(ValidationError):
        proposal(target_price=target)
    assert proposal(target_price=None).target_price is None
    assert proposal(target_price=Decimal("100.01")).target_price == Decimal("100.01")


@pytest.mark.parametrize("field", ["limit_price", "stop_price", "target_price"])
@pytest.mark.parametrize("bad", [Decimal("99.999999"), Decimal("99.999"), "99.99", 99, 99.99, True])
def test_R_13_every_proposal_price_boundary_rejects_non_cent_or_non_decimal(
    field: str, bad: object
) -> None:
    with pytest.raises(ValidationError):
        proposal(**{field: bad})


@pytest.mark.parametrize("field", ["avg_cost", "last_price"])
@pytest.mark.parametrize("bad", [Decimal("99.999"), "99.99", 99.99, 0, Decimal("0")])
def test_R_13_position_prices_are_exact_positive_decimal_cents(field: str, bad: object) -> None:
    data: dict[str, object] = {
        "qty": 1,
        "avg_cost": Decimal("99.99"),
        "last_price": Decimal("100.00"),
    }
    data[field] = bad
    with pytest.raises(ValidationError):
        Position.model_validate(data)


@pytest.mark.parametrize("bad", [Decimal("100.001"), "100.00", 100.0])
def test_R_13_market_and_pending_prices_enforce_same_boundary(bad: object) -> None:
    with pytest.raises(ValidationError):
        OpenOrder.model_validate({"symbol": "AAPL", "side": "BUY", "qty": 1, "limit_price": bad})
    with pytest.raises(ValidationError):
        MarketContext.model_validate(
            {"last_price": bad, "last_price_ts": NOW, "adv20_usd": Decimal("10000"), "status": "OK"}
        )


def test_CRO_04_open_order_optional_stop_preserves_conservative_batch_evidence() -> None:
    data = {"symbol": "AAPL", "side": "BUY", "qty": 1, "limit_price": Decimal("100.00")}
    assert OpenOrder.model_validate(data).stop_price is None
    assert OpenOrder.model_validate({**data, "stop_price": Decimal("99.99")}).stop_price == Decimal(
        "99.99"
    )
    for stop in (Decimal("100.00"), Decimal("100.01"), Decimal("99.999")):
        with pytest.raises(ValidationError):
            OpenOrder.model_validate({**data, "stop_price": stop})


def test_CRO_13_earnings_dates_are_explicit_dates_not_coerced_strings_or_timestamps() -> None:
    data = {
        "last_price": Decimal("100"),
        "last_price_ts": NOW,
        "adv20_usd": Decimal("10000"),
        "status": "OK",
    }
    assert MarketContext.model_validate(data).next_earnings_date is None
    assert MarketContext.model_validate(
        {**data, "next_earnings_date": date(2026, 10, 5)}
    ).next_earnings_date == date(2026, 10, 5)
    for earnings in (NOW, "2026-10-05", 123, True):
        with pytest.raises(ValidationError):
            MarketContext.model_validate({**data, "next_earnings_date": earnings})


@pytest.mark.parametrize(
    "change",
    [
        {"qty": True},
        {"limit_price": Decimal("100.001")},
        {"expires_at": NOW},
        {"target_price": Decimal("99")},
        {"side": Side.SELL},
    ],
)
def test_R_02_unvalidated_copy_proposals_fail_boundary_revalidation(
    change: dict[str, object],
) -> None:
    forged = proposal().model_copy(update=change)
    with pytest.raises(ValidationError):
        TradeProposal.model_validate(forged)


def test_R_02_constructed_and_nested_forged_models_are_revalidated() -> None:
    incomplete = TradeProposal.model_construct(proposal_id=PROPOSAL_ID)
    with pytest.raises(ValidationError):
        TradeProposal.model_validate(incomplete)
    bad_position = Position.model_construct(
        qty=True, avg_cost=Decimal("100"), last_price=Decimal("100")
    )
    forged = snapshot().model_copy(update={"positions": {"AAPL": bad_position}})
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate(forged)
    with pytest.raises(DataIntegrityError):
        snapshot_hash(forged)
    pending = OpenOrder.model_construct(
        symbol="AAPL", side=Side.BUY, qty=1.5, limit_price=Decimal("100")
    )
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate(snapshot().model_copy(update={"open_orders": (pending,)}))
    with pytest.raises(ValidationError):
        MarketContext.model_validate(
            MarketContext.model_construct(
                last_price=Decimal("100.001"),
                last_price_ts=NOW,
                adv20_usd=Decimal("10000"),
                status=MarketStatus.OK,
            )
        )


def test_R_03_revalidation_detaches_forged_mutable_positions() -> None:
    source = {"AAPL": Position(qty=1, avg_cost=Decimal("90"), last_price=Decimal("100"))}
    copied = snapshot().model_copy(update={"positions": source})
    checked = PortfolioSnapshot.model_validate(copied)
    source.clear()
    assert checked.positions["AAPL"].qty == 1
    with pytest.raises(TypeError):
        cast(dict[str, Position], checked.positions)["AAPL"] = Position(
            qty=2, avg_cost=Decimal("90"), last_price=Decimal("100")
        )


def test_R_04_position_notional_and_etf_sums_ignore_low_ambient_precision() -> None:
    with localcontext() as context:
        context.prec = 2
        position = Position(qty=12345, avg_cost=Decimal("123.45"), last_price=Decimal("123.45"))
        assert position.value == Decimal("1523990.25")
        registry = InstrumentRegistry(
            [instrument("XLK", asset_class=AssetClass.SECTOR_ETF)],
            {
                "XLK": {
                    "Information Technology": Decimal("0.999999"),
                    "Financials": Decimal("0.000001"),
                }
            },
        )
        assert registry.sector_weights("XLK")["Information Technology"] == Decimal("0.999999")
        with pytest.raises(DataIntegrityError):
            InstrumentRegistry(
                [instrument("XLK", asset_class=AssetClass.SECTOR_ETF)],
                {
                    "XLK": {
                        "Information Technology": Decimal("0.335"),
                        "Financials": Decimal("0.664"),
                    }
                },
            )
        funding = DeployableCapital(
            checking_used=Decimal("12345.67"),
            buffer=Decimal("1500.00"),
            reserved=Decimal("45.67"),
            deployable=Decimal("10800.00"),
            status=CapitalStatus.OK,
        )
        assert funding.deployable == Decimal("10800.00")


@pytest.mark.parametrize(
    "change",
    [
        {"is_leveraged": "false"},
        {"tradable": 1},
        {"asset_class": "UNKNOWN"},
        {"themes": (" ",)},
        {"symbol": "aapl"},
    ],
)
def test_R_02_registry_revalidates_forged_instrument_metadata(change: dict[str, object]) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument().model_copy(update=change)])


def test_R_02_CRO_11_registry_revalidates_forged_blackout_windows() -> None:
    window = BlackoutWindow(start=NOW, end=NOW + timedelta(hours=1), reason="event")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(
            [instrument()], blackout_windows=[window.model_copy(update={"end": NOW})]
        )


@given(st.integers(min_value=1, max_value=1_000_000))
def test_R_13_price_roundtrip_is_cent_quantized_and_exact(cents: int) -> None:
    value = Decimal(cents) / Decimal("100")
    validated = Position(qty=1, avg_cost=value, last_price=value)
    assert validated.last_price == value
    assert validated.last_price.as_tuple().exponent == -2


@pytest.mark.parametrize(
    "score,expected",
    [
        (Decimal("-5.01"), Decimal("-5")),
        (Decimal("-5"), Decimal("-5")),
        (Decimal("0"), Decimal("0")),
        (Decimal("5"), Decimal("5")),
        (Decimal("5.01"), Decimal("5")),
    ],
)
def test_R_11_sentiment_numeric_clamp_is_advisory_and_has_no_trade_fields(
    score: Decimal, expected: Decimal
) -> None:
    signal = SentimentSignal(
        score=score,
        classification=SentimentClassification.CONFIRMING,
        evidence_headline_ids=("headline-1",),
        summary="source context",
    )
    assert signal.score == expected
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate({**signal.model_dump(), "qty": 100})
    with pytest.raises(ValidationError):
        ResearchThesis.model_validate(
            {"narrative": "context", "evidence_headline_ids": (), "limit_price": Decimal("100")}
        )


@pytest.mark.parametrize("score", [Decimal("NaN"), Decimal("Infinity"), 4.0, True])
def test_R_11_sentiment_invalid_numerics_are_discardable_validation_errors(score: object) -> None:
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate(
            {
                "score": score,
                "classification": "CONFIRMING",
                "evidence_headline_ids": ("headline-1",),
                "summary": "context",
            }
        )


def test_R_11_cited_non_neutral_sentiment_requires_evidence_and_unique_ids() -> None:
    data = {
        "score": Decimal("0"),
        "classification": "NOISE",
        "evidence_headline_ids": (),
        "summary": "insufficient evidence",
    }
    assert SentimentSignal.model_validate(data).score == 0
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate({**data, "score": Decimal("1")})
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate({**data, "classification": "CONFIRMING"})
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate({**data, "evidence_headline_ids": ("h-1", "h-1")})
    with pytest.raises(ValidationError):
        ResearchThesis(narrative="context", evidence_headline_ids=("h-1", "h-1"))


@pytest.mark.parametrize("status", [ProviderStatus.UNAVAILABLE, ProviderStatus.ERROR])
def test_R_02_unavailable_provider_and_flow_results_never_carry_positive_evidence(
    status: ProviderStatus,
) -> None:
    assert (
        ProviderResult[AccountFlags](status=status, payload=None, reason="not available").payload
        is None
    )
    assert FlowSignal(status=status).summary is None
    flags = AccountFlags(
        trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
    )
    with pytest.raises(ValidationError):
        ProviderResult[AccountFlags](status=status, payload=flags, reason="bad inferred data")
    with pytest.raises(ValidationError):
        FlowSignal(status=status, summary="buying signal", evidence_ids=("fake",))


def test_R_02_successful_provider_and_flow_results_require_explicit_evidence() -> None:
    flags = AccountFlags(
        trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
    )
    assert (
        ProviderResult[AccountFlags](
            status=ProviderStatus.OK, payload=flags, reason="recorded data"
        ).payload
        == flags
    )
    assert (
        FlowSignal(
            status=ProviderStatus.OK, summary="large print", evidence_ids=("print-1",)
        ).status
        == ProviderStatus.OK
    )
    with pytest.raises(ValidationError):
        ProviderResult[AccountFlags](status=ProviderStatus.OK, payload=None, reason="missing")
    with pytest.raises(ValidationError):
        FlowSignal(status=ProviderStatus.OK)
    with pytest.raises(ValidationError):
        FlowSignal(status=ProviderStatus.OK, summary="context", evidence_ids=("print-1", "print-1"))


def test_R_11_scanner_and_setup_outputs_keep_levels_and_scores_deterministic() -> None:
    hit = ScannerHit(
        symbol="AAPL",
        as_of=NOW,
        last_price=Decimal("100"),
        rvol=Decimal("1.5"),
        rsi=Decimal("50"),
        reason="completed bars",
    )
    assert hit.last_price == Decimal("100.00")
    criterion = SetupCriterion(name="breakout", points=Decimal("7"), reason="recorded trigger")
    data = {
        "symbol": "AAPL",
        "playbook": Playbook.BASE_BREAKOUT,
        "score": Decimal("7"),
        "criteria": (criterion,),
        "entry_price": Decimal("100"),
        "stop_price": Decimal("95"),
        "target_price": Decimal("110"),
        "qty": 1,
        "as_of": NOW,
    }
    assert SetupCandidate.model_validate(data).score == Decimal("7")
    for change in (
        {"score": Decimal("7.01")},
        {"criteria": (criterion, criterion)},
        {"stop_price": Decimal("100")},
        {"qty": True},
    ):
        with pytest.raises(ValidationError):
            SetupCandidate.model_validate({**data, **change})
    with pytest.raises(ValidationError):
        ScannerHit.model_validate({**hit.model_dump(), "rsi": Decimal("100.01")})


def test_CRO_09_CRO_10_verdict_state_recommendation_is_explicit_pure_data() -> None:
    result = RuleResult(
        rule_id="CRO-09",
        passed=False,
        severity=Severity.BLOCK,
        observed="drawdown",
        limit="halt",
        message="managed equity requires halt",
    )
    verdict = Verdict(
        proposal_id=PROPOSAL_ID,
        decision=Decision.VETOED,
        results=(result,),
        config_hash="a" * 64,
        snapshot_hash="b" * 64,
        evaluated_at=NOW,
        recommended_state=SystemState.HALTED,
    )
    assert verdict.recommended_state == SystemState.HALTED


@pytest.mark.parametrize("weights", [{"UNKNOWN": Decimal("1")}, {"Financials": Decimal("0")}, {}])
def test_CRO_05_etf_sector_map_rejects_unknown_zero_or_empty_exposure(
    weights: dict[str, Decimal],
) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument("XLK", asset_class=AssetClass.SECTOR_ETF)], {"XLK": weights})
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument()], {"UNKNOWN": {"Information Technology": Decimal("1")}})
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument()], {"AAPL": {"Information Technology": Decimal("1")}})


def test_CRO_05_unknown_declared_sector_is_preserved_as_full_exposure_to_block() -> None:
    registry = InstrumentRegistry(
        [instrument("SPY", asset_class=AssetClass.BROAD_ETF, gics_sector="UNKNOWN")]
    )
    assert registry.sector_weights("SPY") == {"UNKNOWN": Decimal("1")}


@pytest.mark.parametrize("group", [[], ["AAPL"], ["AAPL", "AAPL"], ["AAPL", "UNKNOWN"]])
def test_CMP_01_registry_identical_groups_need_known_unique_multiple_members(
    group: list[str],
) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument()], identical_groups={"GROUP": group})


def test_CMP_01_registry_identical_groups_cannot_overlap_or_use_blank_names() -> None:
    names = [instrument(), instrument("MSFT"), instrument("NVDA")]
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(
            names, identical_groups={"FIRST": ("AAPL", "MSFT"), "SECOND": ("MSFT", "NVDA")}
        )
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(names, identical_groups={" ": ("AAPL", "MSFT")})


@pytest.mark.parametrize(
    "filename,content",
    [
        (
            "instruments.csv",
            "symbol,asset_class,gics_sector,themes,is_leveraged,is_inverse,tradable\nAAPL,STOCK,Information Technology,,false,false\n",
        ),
        (
            "instruments.csv",
            "symbol,asset_class,gics_sector,themes,is_leveraged,is_inverse,tradable\nAAPL,STOCK,Information Technology,,false,FALSE,true\n",
        ),
        (
            "instruments.csv",
            "symbol,asset_class,gics_sector,themes,is_leveraged,is_inverse,tradable\nAAPL,OPTIONS,Information Technology,,false,false,true\n",
        ),
        (
            "etf_sector_weights.csv",
            "symbol,gics_sector,weight\nSPY,Information Technology,0.5\nSPY,Information Technology,0.5\n",
        ),
        (
            "blackout_windows.csv",
            "symbol,start,end,reason\nAAPL,2026-10-02T16:00:00,2026-10-02T17:00:00,naive\n",
        ),
    ],
)
def test_R_02_CRO_05_policy_csv_corruption_is_typed_and_never_permissive(
    tmp_path: Path, filename: str, content: str
) -> None:
    source = Path(__file__).resolve().parents[2] / "config"
    for name in (
        "instruments.csv",
        "etf_sector_weights.csv",
        "substantially_identical.csv",
        "blackout_windows.csv",
    ):
        copyfile(source / name, tmp_path / name)
    (tmp_path / filename).write_text(content, encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.from_csv(tmp_path)


@pytest.mark.parametrize("bad", [None, True, "not an Instrument"])
def test_R_02_registry_non_model_inputs_raise_typed_integrity_error(bad: object) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([cast(Instrument, bad)])
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument()], blackout_windows=[cast(BlackoutWindow, bad)])


def test_R_02_R_03_registry_validated_copy_detaches_mutable_internal_aliases() -> None:
    names = {"AAPL": instrument(), "MSFT": instrument("MSFT")}
    members = frozenset({"AAPL", "MSFT"})
    groups = {"AAPL": members, "MSFT": members}
    original = InstrumentRegistry(names.values())
    object.__setattr__(original, "_instruments", names)
    object.__setattr__(original, "_groups", groups)
    checked = InstrumentRegistry.validated_copy(original)
    names.clear()
    groups.clear()
    assert checked.symbols == frozenset({"AAPL", "MSFT"})
    assert checked.identical_group("AAPL") == members


@pytest.mark.parametrize(
    "bad",
    [
        {"AAPL": instrument().model_copy(update={"is_leveraged": "false"})},
        {"MSFT": instrument()},
        {},
    ],
)
def test_R_02_registry_validated_copy_rejects_forged_internal_instruments(
    bad: dict[str, Instrument],
) -> None:
    original = InstrumentRegistry([instrument()])
    object.__setattr__(original, "_instruments", bad)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(original)


@pytest.mark.parametrize(
    "groups",
    [
        {"AAPL": frozenset({"AAPL", "MSFT"})},
        {"AAPL": frozenset({"MSFT", "NVDA"})},
        {"AAPL": {"AAPL", "MSFT"}},
    ],
)
def test_R_02_CMP_01_registry_validated_copy_rejects_forged_asymmetric_groups(
    groups: object,
) -> None:
    original = InstrumentRegistry([instrument(), instrument("MSFT"), instrument("NVDA")])
    object.__setattr__(original, "_groups", groups)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(original)


def test_R_02_registry_validated_copy_revalidates_etf_weights_and_missing_storage() -> None:
    original = InstrumentRegistry([instrument("XLK", asset_class=AssetClass.SECTOR_ETF)])
    object.__setattr__(original, "_weights", {"XLK": {"Information Technology": Decimal("0.999")}})
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(original)
    empty = object.__new__(InstrumentRegistry)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(empty)
    object.__setattr__(original, "_weights", None)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(original)
