"""QV-01/02: explicit fixed variants, cumulative trials and immutable holdout."""

import calendar as civil
import hashlib
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

from pydantic import Field, field_serializer, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import ValidationConfig, YamlConfig, load_exact_yaml
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import Digest, FrozenHistory, canonical_bytes, validate_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, SessionDate

Name = str
ALLOWED_OVERRIDES = frozenset(
    {
        "evaluation.max_hold_sessions",
        "exits.variant",
        "sizing.confidence_mode",
        "rs.sector_filter",
        "rs.min_stock_percentile",
        "rs.use_breadth",
        "rs.top_n_sectors",
        "sizing.stop_atr_mult",
        "sizing.target_r",
        "sizing.swing_lookback",
        "playbooks.enabled",
    }
)


class Variant(FrozenModel):
    name: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    overrides: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("overrides", mode="after")
    @classmethod
    def explicit(cls, values: Mapping[str, Any]) -> Mapping[str, Any]:
        if not set(values).issubset(ALLOWED_OVERRIDES) or len(values) > 8:
            raise ValueError("QV-01: only explicit registered non-risk overrides are allowed")
        checked = dict(values)
        for name, value in checked.items():
            if name == "playbooks.enabled":
                if (
                    not isinstance(value, (list, tuple))
                    or not 1 <= len(value) <= 4
                    or any(
                        item
                        not in {
                            "TREND_50EMA",
                            "BASE_BREAKOUT",
                            "ANCHORED_VWAP_RECLAIM",
                            "EARNINGS_GAP",
                        }
                        for item in value
                    )
                    or len(set(value)) != len(value)
                ):
                    raise ValueError(
                        "EG-01: only one explicit set of specified enabled playbooks is allowed"
                    )
                checked[name] = tuple(value)
            elif isinstance(value, (Mapping, list, tuple, float)):
                raise ValueError("QV-01: combinations and inexact values are forbidden")
        return MappingProxyType(checked)

    @field_serializer("overrides")
    def serialized(self, values: Mapping[str, Any]) -> dict[str, Any]:
        from decimal import Decimal

        return {
            name: str(value) if isinstance(value, Decimal) else value
            for name, value in sorted(values.items())
        }


class VariantFamily(FrozenModel):
    name: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    variants: tuple[Variant, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def baseline(self) -> Self:
        names = tuple(row.name for row in self.variants)
        if len(set(names)) != len(names) or names[0] != "BASELINE" or self.variants[0].overrides:
            raise ValueError("QV-01: each family starts with one unmodified BASELINE")
        if any(not row.overrides for row in self.variants[1:]):
            raise ValueError("QV-01: a nonbaseline variant requires explicit overrides")
        return self


class VariantRegistry(FrozenModel):
    families: tuple[VariantFamily, ...] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if (
            len({row.name for row in self.families}) != len(self.families)
            or sum(len(row.variants) for row in self.families) > 24
        ):
            raise ValueError("QV-01: unique families and at most 24 explicit variants required")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    def family(self, name: str) -> VariantFamily:
        found = [row for row in self.families if row.name == name]
        if len(found) != 1:
            raise ConfigurationError("QV-01: unknown registered family")
        return found[0]


def apply_variant(baseline: YamlConfig, variant: Variant) -> YamlConfig:
    policy = YamlConfig.model_validate(baseline)
    fixed = Variant.model_validate(variant)
    payload = policy.model_dump(mode="python")
    for key, value in fixed.overrides.items():
        section, field = key.split(".")
        payload[section][field] = value
    try:
        result = YamlConfig.model_validate(payload)
        if result.evaluation.max_hold_sessions not in {10, 20, 30}:
            raise ValueError("EX-04: registered holding periods are 10, 20 or 30")
        return result
    except Exception:
        raise ConfigurationError("QV-01: fixed overrides violate the approved policy") from None


def load_registry(path: Path, baseline: YamlConfig) -> VariantRegistry:
    try:
        registry = VariantRegistry.model_validate(load_exact_yaml(path))
        for family in registry.families:
            for variant in family.variants:
                apply_variant(baseline, variant)
        return registry
    except Exception:
        raise ConfigurationError("QV-01: invalid explicit variant registry") from None


def add_months(day: date, count: int) -> date:
    if type(day) is not date or type(count) is not int or not -1200 <= count <= 1200:
        raise DataIntegrityError("QV-02/03: bounded calendar months required")
    month = day.year * 12 + day.month - 1 + count
    year, number = divmod(month, 12)
    return date(year, number + 1, min(day.day, civil.monthrange(year, number + 1)[1]))


class Registration(FrozenModel):
    registry: VariantRegistry
    file_sha256: Digest
    history_sha256: Digest
    training_start: SessionDate
    training_end: SessionDate
    holdout_start: SessionDate
    holdout_end: SessionDate
    cumulative_trials: tuple[tuple[str, int], ...] = Field(min_length=1, max_length=24)
    context_sha256: Digest | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        names = tuple(name for name, _ in self.cumulative_trials)
        if (
            not self.training_start < self.training_end < self.holdout_start <= self.holdout_end
            or names != tuple(sorted(row.name for row in self.registry.families))
            or any(
                type(count) is not int or not 1 <= count <= 1000000
                for _, count in self.cumulative_trials
            )
        ):
            raise ValueError("QV-01/02: invalid holdout or cumulative trials")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "Registration":
        values = dict(payload)
        values["holdout_start"] = date.fromisoformat(values["holdout_start"])
        values["holdout_end"] = date.fromisoformat(values["holdout_end"])
        values["training_start"] = date.fromisoformat(values["training_start"])
        values["training_end"] = date.fromisoformat(values["training_end"])
        return cls.model_validate(values)


class Registrations:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def latest(self) -> Registration:
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            row = session.scalar(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "VARIANTS_REGISTERED")
                .order_by(SecurityEvent.seq.desc())
                .limit(1)
            )
        if row is None or row.created_at > self.ledger.clock.now():
            raise ConfigurationError("QV-01: register fixed variants before any run")
        return Registration.recorded(row.detail)

    def register(
        self,
        registry: VariantRegistry,
        file_sha256: str,
        history: FrozenHistory,
        policy: ValidationConfig,
        calendar: MarketCalendar,
        *,
        context_sha256: str | None = None,
    ) -> Registration:
        fixed = VariantRegistry.model_validate(registry)
        frozen = FrozenHistory.model_validate(history)
        config = ValidationConfig.model_validate(policy)
        validate_history(frozen.bundle, calendar)
        if sum(len(row.variants) for row in fixed.families) > config.max_variants_total or any(
            len(row.variants) > config.max_variants_per_family for row in fixed.families
        ):
            raise ConfigurationError("QV-01: configured fixed-variant cap exceeded")
        self.ledger.verify_chain()
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            rows = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "VARIANTS_REGISTERED")
                    .order_by(SecurityEvent.seq)
                    .limit(1001)
                )
            )
            if len(rows) > 1000 or any(row.created_at > self.ledger.clock.now() for row in rows):
                raise DataIntegrityError("QV-01: registration history is unavailable")
            previous = tuple(Registration.recorded(row.detail) for row in rows)
            raw = tuple(row for row in frozen.manifest.entries if row.adjustment == "RAW")
            sessions = next((row.sessions for row in raw if row.symbol == "SPY"), raw[0].sessions)
            if len(sessions) <= 200:
                raise ConfigurationError("QV-02: history needs warm-up and a holdout")
            if previous:
                start, end = previous[0].holdout_start, previous[0].holdout_end
                if frozen.manifest.sha256 != previous[-1].history_sha256:
                    raise ConfigurationError("QV-02: registered frozen history cannot be replaced")
                if (
                    previous[-1].file_sha256 == file_sha256
                    and previous[-1].registry == fixed
                    and previous[-1].context_sha256 == context_sha256
                ):
                    return previous[-1]
            else:
                end = sessions[-1]
                cutoff = add_months(end, -config.holdout_months)
                possible = [day for day in sessions if day > cutoff]
                if not possible or possible[0] <= sessions[200]:
                    raise ConfigurationError("QV-02: insufficient non-holdout history")
                start = possible[0]
            trials: dict[str, int] = {}
            for old in previous:
                for family in old.registry.families:
                    trials[family.name] = trials.get(family.name, 0) + len(family.variants)
            for family in fixed.families:
                trials[family.name] = trials.get(family.name, 0) + len(family.variants)
            proof = Registration(
                registry=fixed,
                file_sha256=file_sha256,
                history_sha256=frozen.manifest.sha256,
                training_start=sessions[200],
                training_end=max(day for day in sessions if day < start),
                holdout_start=start,
                holdout_end=end,
                cumulative_trials=tuple(
                    (row.name, trials[row.name])
                    for row in sorted(fixed.families, key=lambda row: row.name)
                ),
                context_sha256=context_sha256,
            )
            self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="VARIANTS_REGISTERED",
                detail=proof.model_dump(mode="json"),
            )
            return proof

    def check_window(self, history_sha256: str, start: date, end: date) -> Registration:
        proof = self.latest()
        if (
            history_sha256 != proof.history_sha256
            or type(start) is not date
            or type(end) is not date
            or start >= end
            or not (end < proof.holdout_start or start > proof.holdout_end)
        ):
            raise ConfigurationError("QV-02: ordinary runs and reports refuse the frozen holdout")
        return proof


def refuse_registered_holdout(ledger: Ledger, start: date, end: date) -> None:
    """QV-02: ordinary hypothetical runs/reports cannot reveal registered dates."""
    if type(start) is not date or type(end) is not date or start >= end:
        raise ConfigurationError("QV-02: explicit ordered report dates required")
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        exists = session.scalar(
            select(SecurityEvent.id).where(SecurityEvent.kind == "VARIANTS_REGISTERED").limit(1)
        )
    if exists is None:
        return
    proof = Registrations(ledger).latest()
    if not (end < proof.holdout_start or start > proof.holdout_end):
        raise ConfigurationError(
            "QV-02: ordinary runs and reports refuse the frozen holdout; use the explicit one-use final command"
        )
