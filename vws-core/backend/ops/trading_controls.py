"""XK-03/05/06: exact reduction-only overlays and serialized persistent controls."""

from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import Literal, Self

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import RegimeFilterConfig
from backend.core.database import SecurityEvent, SystemControl, SystemEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import FrozenModel, Money, Playbook
from backend.ops.playbook_kill import playbook_kill_condition

STEPS = (Decimal("0.25"), Decimal("0.50"), Decimal(1))


class ControlScope(FrozenModel):
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Literal["PAPER", "LIVE"]


class RampState(FrozenModel):
    scope: ControlScope
    step: int = Field(strict=True, ge=0, le=2)
    resolved_baseline: int = Field(strict=True, ge=0, le=100000)
    last_fault_seq: int = Field(strict=True, ge=0)
    drawdown_latched: bool = Field(default=False, strict=True)

    @property
    def multiplier(self) -> Decimal:
        return STEPS[self.step]


class RampObservation(FrozenModel):
    scope: ControlScope
    resolved: int = Field(strict=True, ge=0, le=100000)
    drawdown: Money = Field(ge=0, le=1)
    fault_seq: int = Field(strict=True, ge=0)
    faults: int = Field(default=0, strict=True, ge=0, le=100000)
    restricted: bool = Field(default=False, strict=True)


class PlaybookState(FrozenModel):
    scope: ControlScope
    playbook: Playbook
    paused: bool = Field(strict=True)
    evaluated_count: int = Field(strict=True, ge=0, le=100000)
    enabled_through: int = Field(strict=True, ge=0, le=100000)
    operator: str | None = Field(default=None, strict=True, min_length=1, max_length=128)

    @model_validator(mode="after")
    def owner_enable(self) -> Self:
        if not self.paused and self.enabled_through and self.operator is None:
            raise ValueError("XK-05: re-enable needs a named host operator")
        return self


def regime_multiplier(
    close: Decimal | None, ema200: Decimal | None, config: RegimeFilterConfig, *, auto: bool
) -> Decimal:
    policy = RegimeFilterConfig.model_validate(config)
    if type(auto) is not bool:
        raise DataIntegrityError("XK-03: explicit automatic-mode identity required")
    if close is None or ema200 is None:
        if auto:
            raise DataIntegrityError("XK-03: SPY regime evidence is unavailable")
        return Decimal(1)
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or value <= 0
        for value in (close, ema200)
    ):
        raise DataIntegrityError("XK-03: exact positive SPY prices required")
    if not auto or close >= ema200 or policy.auto == "annotate":
        return Decimal(1)
    return Decimal("0.5") if policy.auto == "half_size" else Decimal(0)


def reduced_quantity(quantity: int, multipliers: tuple[Decimal, ...]) -> int:
    if (
        type(quantity) is not int
        or not 1 <= quantity <= 10**9
        or not isinstance(multipliers, tuple)
        or len(multipliers) > 10
    ):
        raise DataIntegrityError("XK-03/06: bounded whole shares and immutable overlays required")
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or not 0 <= value <= 1
        for value in multipliers
    ):
        raise DataIntegrityError("XK-03/06: overlays may only reduce size")
    with localcontext() as precision:
        precision.prec = 80
        result = Decimal(quantity)
        for value in multipliers:
            result *= value
        return int(result.to_integral_value(rounding=ROUND_FLOOR))


def advance_ramp(previous: RampState, observation: RampObservation) -> RampState:
    old, seen = RampState.model_validate(previous), RampObservation.model_validate(observation)
    if (
        seen.scope != old.scope
        or seen.scope.environment != "LIVE"
        or seen.resolved < old.resolved_baseline
        or seen.fault_seq < old.last_fault_seq
    ):
        raise DataIntegrityError("XK-06: ramp observation is unbound or goes backwards")
    step, baseline = old.step, old.resolved_baseline
    # Consume each latched state event once. Repeated monitor polls cannot
    # repeatedly lower or raise a step from the same historical evidence.
    breached = seen.drawdown >= Decimal("0.05")
    if seen.fault_seq > old.last_fault_seq or (breached and not old.drawdown_latched):
        step, baseline = max(0, step - max(1, seen.faults)), seen.resolved
    elif breached or seen.restricted:
        baseline = seen.resolved
    elif seen.resolved - baseline >= (10 if step == 0 else 20) and step < 2:
        step, baseline = step + 1, seen.resolved
    return RampState(
        scope=old.scope,
        step=step,
        resolved_baseline=baseline,
        last_fault_seq=seen.fault_seq,
        drawdown_latched=breached,
    )


class TradingControls:
    def __init__(self, ledger: Ledger, scope: ControlScope) -> None:
        self.ledger, self.scope = ledger, ControlScope.model_validate(scope)

    def _rows(self, session: Session, kind: str) -> tuple[SecurityEvent, ...]:
        rows = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == kind)
                .order_by(SecurityEvent.seq)
                .limit(100001)
            )
        )
        if len(rows) > 100000 or any(row.ts > self.ledger.clock.now() for row in rows):
            raise DataIntegrityError("XK-05/06: control evidence is future or unbounded")
        return rows

    def _ramp(self, session: Session) -> RampState:
        states = tuple(
            RampState.model_validate(row.detail) for row in self._rows(session, "CAPITAL_RAMP")
        )
        return next(
            (row for row in reversed(states) if row.scope == self.scope),
            RampState(scope=self.scope, step=0, resolved_baseline=0, last_fault_seq=0),
        )

    def ramp(self) -> RampState:
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            return self._ramp(session)

    def observe_ramp(self, resolved: int, drawdown: Decimal) -> tuple[RampState, bool]:
        self.ledger.verify_chain()
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            previous = self._ramp(session)
            faults = tuple(
                session.scalars(
                    select(SystemEvent)
                    .where(
                        SystemEvent.state.in_(("REDUCE_ONLY", "HALTED")),
                        SystemEvent.seq > previous.last_fault_seq,
                    )
                    .order_by(SystemEvent.seq)
                    .limit(100001)
                )
            )
            operating = session.scalar(select(SystemControl.state).where(SystemControl.id == 1))
            if (
                len(faults) > 100000
                or any(row.created_at > self.ledger.clock.now() for row in faults)
                or operating not in {"RUNNING", "REDUCE_ONLY", "HALTED"}
            ):
                raise DataIntegrityError("XK-06: state history is unavailable, future or unbounded")
            fault = faults[-1].seq if faults else previous.last_fault_seq
            result = advance_ramp(
                previous,
                RampObservation(
                    scope=self.scope,
                    resolved=resolved,
                    drawdown=drawdown,
                    fault_seq=fault,
                    faults=len(faults),
                    restricted=operating != "RUNNING",
                ),
            )
            changed = result != previous
            if changed:
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="CAPITAL_RAMP",
                    detail=result.model_dump(mode="json"),
                )
            return result, result.step != previous.step

    def _playbook(self, session: Session, playbook: Playbook) -> PlaybookState:
        states = tuple(
            PlaybookState.model_validate(row.detail)
            for row in self._rows(session, "PLAYBOOK_CONTROL")
        )
        return next(
            (
                row
                for row in reversed(states)
                if row.scope == self.scope and row.playbook == playbook
            ),
            PlaybookState(
                scope=self.scope,
                playbook=playbook,
                paused=False,
                evaluated_count=0,
                enabled_through=0,
            ),
        )

    def paused(self, playbook: Playbook) -> bool:
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            return self._playbook(session, Playbook(playbook)).paused

    def evaluate_playbook(self, playbook: Playbook, sample: tuple[Decimal, ...]) -> bool:
        losing = playbook_kill_condition(sample)
        self.ledger.verify_chain()
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            previous = self._playbook(session, Playbook(playbook))
            if len(sample) < previous.evaluated_count:
                raise DataIntegrityError("XK-05: resolved sample cannot go backwards")
            if losing and len(sample) > previous.enabled_through and not previous.paused:
                result = PlaybookState(
                    scope=self.scope,
                    playbook=playbook,
                    paused=True,
                    evaluated_count=len(sample),
                    enabled_through=previous.enabled_through,
                )
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="PLAYBOOK_CONTROL",
                    detail=result.model_dump(mode="json"),
                )
                return True
            return previous.paused

    def enable_playbook(self, playbook: Playbook, operator: str) -> None:
        from backend.ops.security import _operator

        actor = _operator(operator)
        self.ledger.verify_chain()
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            previous = self._playbook(session, Playbook(playbook))
            if not previous.paused:
                raise DataIntegrityError("XK-05: playbook is already enabled")
            result = PlaybookState(
                scope=self.scope,
                playbook=playbook,
                paused=False,
                evaluated_count=previous.evaluated_count,
                enabled_through=previous.evaluated_count,
                operator=actor,
            )
            self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="PLAYBOOK_CONTROL",
                detail=result.model_dump(mode="json"),
            )
