"""LJ-04/LP-05: optional public-evidence wording; code keeps all authority."""

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.llm_client import Narrative, PublicHeadline, PublicResearchInput
from backend.core.content import injection_suspect, sanitize_text
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.learning.journal import MistakeJournal
from backend.realtime.storage import RealtimeStore


class PublicWriter(Protocol):
    async def complete_json(
        self, prompt_name: str, input_data: PublicResearchInput, output_model: type[Narrative]
    ) -> Narrative | None: ...


async def enrich(journal: MistakeJournal, realtime: RealtimeStore, client: PublicWriter) -> int:
    if realtime.scope != journal.scope or realtime.ledger.engine is not journal.ledger.engine:
        raise DataIntegrityError("LJ-04: narrative evidence must share the bound journal")
    journal.ledger.verify_chain()
    with Session(journal.ledger.engine) as session:
        prior = set(
            session.scalars(
                select(SecurityEvent.detail["key"].as_string()).where(
                    SecurityEvent.kind == "LEARNING_NARRATIVE"
                )
            )
        )
    events = realtime.events()
    added = 0
    for row in journal.rows():
        if row.key in prior:
            continue
        # Only public feed text enters the prompt. No trading results, scope,
        # balance, order, quantity, private note or account identity enters it.
        public = tuple(
            PublicHeadline(stable_id=realtime.key(event), headline=event.text[:280])
            for event in events
            if event.symbol == row.observation.symbol
            and event.feed in {"news", "edgar"}
            and event.observed_at <= row.observation.at
            and row.observation.at < event.expires_at
        )[:50]
        public = tuple(
            item
            for item in public
            if sanitize_text(item.headline) == item.headline
            and not injection_suspect(item.headline, frozenset())
        )
        draft = None
        if public:
            try:
                draft = await client.complete_json(
                    "research_synthesis",
                    PublicResearchInput(ticker=row.observation.symbol, headlines=public),
                    Narrative,
                )
            except Exception:
                draft = None  # Wording failure cannot change a tag or block protection.
        text = f"Code recorded {row.cause_tag}. " + (
            "Public evidence unavailable; review the structured journal."
            if draft is None
            else Narrative.model_validate(draft).summary
        )
        if len(text) > 1000 or sanitize_text(text) != text or injection_suspect(text, frozenset()):
            text = f"Code recorded {row.cause_tag}. Review the structured journal."
        with transaction(journal.ledger.engine) as session:
            journal.ledger._verify_in_session(session)
            existing = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "LEARNING_NARRATIVE",
                    SecurityEvent.detail["key"].as_string() == row.key,
                )
                .limit(1)
            )
            if existing is not None:
                continue
            journal.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="LEARNING_NARRATIVE",
                detail={
                    "scope": journal.scope.model_dump(mode="json"),
                    "key": row.key,
                    "summary": text,
                    "public_evidence_ids": [item.stable_id for item in public],
                },
            )
            added += 1
    return added
