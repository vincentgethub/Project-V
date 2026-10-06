"""GD-03/FA-09: one batched advisory call, after explicit code eligibility."""

from typing import Literal, Protocol, Self

from pydantic import model_validator

from backend.agents.llm_client import PublicHeadline, PublicResearchInput, Validated
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.data.news import NewsResult
from backend.domain.models import (
    FrozenModel,
    ProviderStatus,
    SentimentSignal,
    Symbol,
    validate_symbol,
)


class AdvisoryClient(Protocol):
    async def complete_json(
        self, prompt_name: str, input_data: PublicResearchInput, output_model: type[Validated]
    ) -> Validated | None: ...


class NewsAssessment(FrozenModel):
    symbol: Symbol
    news: NewsResult
    sentiment: SentimentSignal | None
    sentiment_status: Literal["OFF", "BLOCKED", "UNAVAILABLE", "OK"]

    @model_validator(mode="after")
    def evidence_bound(self) -> Self:
        if (self.sentiment_status == "OK") != (self.sentiment is not None):
            raise ValueError("summary status must match validated evidence")
        if self.sentiment is not None:
            allowed = {row.stable_id for row in self.news.headlines if row.summary_allowed}
            if not set(self.sentiment.evidence_headline_ids).issubset(allowed):
                raise ValueError("sentiment cites evidence outside supplied news")
        return self


class NewsReader:
    def __init__(self, settings: Settings, client: AdvisoryClient) -> None:
        self.settings, self.client = Settings.validated_copy(settings), client
        self._seen: dict[str, tuple[frozenset[str], SentimentSignal | None]] = {}

    async def read(
        self, symbol: str, news: NewsResult, *, eligible: bool = False
    ) -> NewsAssessment:
        """Caller must establish CRO #1, fundamentals mode and nonzero quantity.

        News with flagged instructions remains available for escaped display;
        only summary_allowed public headlines cross the separate LLM boundary.
        """
        validate_symbol(symbol)
        checked = NewsResult.model_validate(news)
        checked = NewsResult.model_validate(
            {
                **checked.model_dump(),
                "headlines": tuple(
                    row for row in checked.headlines if not row.symbols or symbol in row.symbols
                ),
            }
        )
        if type(eligible) is not bool:
            raise DataIntegrityError("GD-03: research eligibility must be explicit code boolean")
        rows = tuple(
            row
            for row in checked.headlines
            if row.summary_allowed and (not row.symbols or symbol in row.symbols)
        )
        ids = frozenset(row.stable_id for row in rows)
        result = None
        status: Literal["OFF", "BLOCKED", "UNAVAILABLE", "OK"] = "OFF"
        if self.settings.llm_enabled:
            status = "BLOCKED" if not eligible else "UNAVAILABLE"
            if eligible and checked.status == ProviderStatus.OK and rows:
                old_ids, previous = self._seen.get(symbol, (frozenset(), None))
                if ids.issubset(old_ids):
                    if previous is not None and set(previous.evidence_headline_ids).issubset(ids):
                        result = SentimentSignal.model_validate(previous)
                else:
                    new_rows = tuple(row for row in rows if row.stable_id not in old_ids)
                    evidence = PublicResearchInput(
                        ticker=symbol,
                        headlines=tuple(
                            PublicHeadline(stable_id=row.stable_id, headline=row.headline)
                            for row in new_rows
                        ),
                    )
                    candidate = await self.client.complete_json(
                        "news_sentiment", evidence, SentimentSignal
                    )
                    result = (
                        None if candidate is None else SentimentSignal.model_validate(candidate)
                    )
                    if result is not None and not set(result.evidence_headline_ids).issubset(
                        {row.stable_id for row in new_rows}
                    ):
                        raise DataIntegrityError("SEC-61: advisory client invented news citations")
                if len(self._seen) >= 512 and symbol not in self._seen:
                    self._seen.pop(next(iter(self._seen)))
                self._seen[symbol] = (ids, result)
                if result is not None:
                    status = "OK"
        return NewsAssessment(
            symbol=symbol, news=checked, sentiment=result, sentiment_status=status
        )
