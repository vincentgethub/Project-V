"""Additional M9 boundary proof: extra-round data always fails with a typed refusal."""

import pytest

from backend.execution.coordinated_intent import InventoryClient
from backend.execution.intent_resolution import IntentRefusal
from backend.execution.models import IntentDryRun, IntentOrderView
from backend.ops.read_checks import IntentReadClient
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_intent_apply_barrier import Review
from backend.tests.test_intent_apply_barrier import review as review
from backend.tests.test_swarm_and_callbacks import make_research_harness


class PositionFeed(IntentReadClient):
    def __init__(self, quantity: object) -> None:
        self.quantity = quantity

    async def open_orders(self) -> tuple[IntentOrderView, ...]:
        return ()

    async def _fetch(
        self, path: str, *, params: dict[str, str] | None = None, absence: bool = False
    ) -> object:
        return [{"symbol": "SPY", "side": "long", "qty": self.quantity}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quantity",
    [
        pytest.param("UNTRUSTED_BROKER_QUANTITY", id="text"),
        pytest.param("NaN", id="nonfinite"),
        pytest.param("1.5", id="fraction"),
        pytest.param(-1, id="negative"),
        pytest.param(False, id="boolean"),
        pytest.param(None, id="missing"),
    ],
)
async def test_extra_round_bad_quantity_is_a_typed_refusal(quantity: object) -> None:
    with pytest.raises(IntentRefusal, match="FIX_G_LOOKUP_UNVERIFIED"):
        await InventoryClient(PositionFeed(quantity)).inventory()


@pytest.mark.asyncio
async def test_extra_round_whole_quantity_guard() -> None:
    result = await InventoryClient(PositionFeed("2")).inventory()
    assert result.positions == (("SPY", 2),)
    assert len(result.digest()) == 64


harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_apply_rechecks_proof_before_summary_and_confirmation(review: Review) -> None:
    announced: list[str] = []
    prompts: list[str] = []

    async def interrupted() -> IntentDryRun:
        value = await review.operation()
        review.flag.signal_if_present()
        return value

    def confirm(prompt: str) -> str:
        prompts.append(prompt)
        return f"CLEAR INTENT {review.request.intent_id} PAPER {review.request.account}"

    with pytest.raises(IntentRefusal) as refusal:
        await review.resolver.apply(
            interrupted,
            reader=review.reader,
            broker=review.inventory,
            ledger=review.harness.state.ledger,
            state=review.harness.state,
            request=review.request,
            confirm=confirm,
            announce=announced.append,
        )
    assert refusal.value.code == "FIX_G_QUIESCENCE_UNVERIFIED"
    assert announced == [] and prompts == []
    assert review.inventory.calls == 0 and review.audits() == []
