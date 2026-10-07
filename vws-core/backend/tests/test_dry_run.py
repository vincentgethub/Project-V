"""E/GD-08: actual indicators through card/preview, socket-blocked and isolated."""

from decimal import Decimal
from pathlib import Path

import pytest

from backend.agents import offline_run as module
from backend.agents.llm_client import SDKTransport
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.domain.models import (
    FlowSignal,
    ProviderStatus,
    SentimentClassification,
    SentimentSignal,
)
from backend.notifications.card_formatter import display_time, format_card, manual_instructions


@pytest.mark.asyncio
async def test_GD_08_disabled_end_to_end_never_constructs_sdk_or_opens_real_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("offline run attempted to construct a paid client")

    monkeypatch.setattr(SDKTransport, "__init__", forbidden)
    real_file = tmp_path / "real-ledger.db"
    real_file.write_bytes(b"real ledger must remain untouched")
    monkeypatch.setenv("DB_URL", "sqlite:///" + real_file.as_posix())
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("EXECUTION_MODE", "AUTO_LIVE")
    result = await module.offline_run("NVDA")
    assert result.ledger_verified and result.llm_calls == 0
    assert len(result.cards) == len(result.previews) == 1 and not result.veto_ids
    assert real_file.read_bytes() == b"real ledger must remain untouched"
    text = result.cards[0]
    # Independent hand arithmetic from the recorded synthetic bars' final high.
    assert "BASE_BREAKOUT (score 9.00/10)" in text
    assert "Buy limit $101.76 · Stop $99.12 · Target $107.04" in text
    assert "Size 9 sh = $915.84 (9.16% of account)" in text
    assert "-$25.59 (0.26%) · Reward:risk 1.86" in text
    assert "3 headlines (sentiment off)" in text
    assert "Fundamentals 0/5 INCOMPLETE" in text and "Flow: n/a" in text
    assert "earnings unavailable" in text and "CT" in text
    assert "BUY 9 NVDA, LIMIT $101.76, DAY" in result.previews[0]
    assert "After it fills: SELL STOP 9 NVDA at $99.12, GTC" in result.previews[0]


@pytest.mark.asyncio
async def test_FA_08_require_drops_missing_fundamentals_before_news_or_llm() -> None:
    result = await module.offline_run("NVDA", require_fundamentals=True)
    assert not result.cards and not result.previews and result.llm_calls == 0
    assert "FA-08: required fundamentals unavailable/failed" in result.dropped
    assert result.ledger_verified


@pytest.mark.asyncio
async def test_GD_08_unknown_symbol_fails_typed() -> None:
    with pytest.raises(ConfigurationError):
        await module.offline_run("AAPL")


@pytest.mark.asyncio
async def test_GD_08_corrupted_fixture_fails_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "read_bytes", lambda path: b"{broken")
    with pytest.raises(DataIntegrityError):
        await module.offline_run("NVDA")


@pytest.mark.asyncio
async def test_GD_05_card_rejects_mismatched_bound_evidence_and_escapes_text() -> None:
    result = await module.offline_run("NVDA")
    context = result.contexts[0]
    settings = Settings(broker_account_type="CASH")
    for field, value in (
        ("candidate", context.candidate.model_copy(update={"qty": context.candidate.qty + 1})),
        ("verdict", context.verdict.model_copy(update={"results": context.verdict.results[:1]})),
        (
            "compliance",
            context.compliance.model_copy(update={"results": context.compliance.results[:1]}),
        ),
    ):
        with pytest.raises(DataIntegrityError):
            format_card(context.model_copy(update={field: value}), settings)
    assert "&lt;b&gt;" in format_card(
        context.model_copy(update={"market_context": "<b>unavailable</b>"}), settings
    )
    assert display_time(context.proposal.expires_at, settings).endswith("CT")
    assert display_time(
        context.proposal.expires_at,
        Settings(broker_account_type="CASH", display_tz="America/New_York"),
    ).endswith("EDT")


@pytest.mark.asyncio
async def test_GD_05_changed_price_cannot_appear_in_an_approved_card() -> None:
    result = await module.offline_run("NVDA")
    context = result.contexts[0]
    changed = context.proposal.model_copy(update={"limit_price": Decimal("102.00")})
    with pytest.raises(DataIntegrityError):
        format_card(
            context.model_copy(update={"proposal": changed}), Settings(broker_account_type="CASH")
        )
    with pytest.raises(DataIntegrityError):
        manual_instructions(
            context.proposal.model_copy(update={"target_price": None}),
            Settings(broker_account_type="CASH"),
        )


def test_GD_05_display_timezone_must_be_real() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(broker_account_type="CASH", display_tz="Invented/Nowhere")


@pytest.mark.asyncio
async def test_GD_05_oversize_card_fails_without_silently_truncating_evidence() -> None:
    result = await module.offline_run("NVDA")
    flow = FlowSignal(status=ProviderStatus.OK, summary="&" * 1000, evidence_ids=("f1",))
    with pytest.raises(DataIntegrityError, match="message boundary"):
        format_card(
            result.contexts[0].model_copy(update={"flow": flow}),
            Settings(broker_account_type="CASH"),
        )


@pytest.mark.asyncio
async def test_GD_05_valid_public_sentiment_displays_citations_without_changing_trade_numbers() -> (
    None
):
    result = await module.offline_run("NVDA")
    context = result.contexts[0]
    sentiment = SentimentSignal(
        score=Decimal(4),
        classification=SentimentClassification.CONFIRMING,
        evidence_headline_ids=(context.news.news.headlines[0].stable_id,),
        summary="Public fixture headline confirms the stated catalyst.",
    )
    news = context.news.model_copy(update={"sentiment": sentiment, "sentiment_status": "OK"})
    text = format_card(
        context.model_copy(update={"news": news}), Settings(broker_account_type="CASH")
    )
    assert "News: +4 CONFIRMING [" in text
    assert "Buy limit $101.76 · Stop $99.12 · Target $107.04" in text
