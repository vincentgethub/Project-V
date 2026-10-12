"""EX-06/EG-01: entry availability from current registered OOS evidence only."""

from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import Settings, YamlConfig
from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import Digest
from backend.domain.models import FrozenModel, Playbook
from backend.evaluation.registry import Registrations, apply_variant
from backend.evaluation.validation_runner import RegistrationContext
from backend.evaluation.walkforward import ValidationRun, ValidationTrade, _results


class GradePublication(FrozenModel):
    registration_sha256: Digest
    family: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    kind: Literal["WALKFORWARD", "HOLDOUT"]
    result_sha256: Digest
    settings_sha256: Digest
    baseline: YamlConfig
    result: ValidationRun
    inputs: RegistrationContext

    @model_validator(mode="after")
    def bound(self) -> Self:
        if (
            self.result.sha256 != self.result_sha256
            or self.result.registration_sha256 != self.registration_sha256
            or self.result.family != self.family
            or self.result.kind != self.kind
            or self.settings_sha256 != self.inputs.settings
            or self.baseline.config_hash != self.inputs.config
            or self.result.universe_sha256
            != (None if self.inputs.universe is None else self.inputs.universe.file_sha256)
        ):
            raise ValueError("QV-07: grade publication differs from its registered result")
        return self

    @classmethod
    def recorded(cls, values: dict[str, Any]) -> "GradePublication":
        try:
            payload = dict(values)
            payload["result"] = ValidationRun.recorded(payload["result"])
            if "universe" in payload["inputs"]:
                from backend.evaluation.universe import HistoricalUniverse

                payload["inputs"] = {
                    **payload["inputs"],
                    "universe": HistoricalUniverse.recorded(payload["inputs"]["universe"]),
                }
            if "calibration" in payload["inputs"]:
                from backend.evaluation.calibrated_costs import CostCalibration

                payload["inputs"] = {
                    **payload["inputs"],
                    "calibration": CostCalibration.recorded(payload["inputs"]["calibration"]),
                }
            return cls.model_validate(payload)
        except Exception:
            raise DataIntegrityError("EX-06: recorded validation proof is unverifiable") from None


class GradeStore:
    def __init__(self, ledger: Ledger, settings: Settings, config: YamlConfig) -> None:
        self.ledger, self.settings, self.config = (
            ledger,
            Settings.validated_copy(settings),
            YamlConfig.model_validate(config),
        )
        self._verified: dict[str, GradePublication] = {}

    def oos_by_playbook(self) -> dict[Playbook, tuple[Decimal, ...]]:
        """XA-02: current registered variant, honest OOS only, unique trades.

        Old samples without a recorded playbook are unavailable for this check.
        Neither pooled performance nor selected variants certify another policy.
        """
        try:
            publications = self._publications()
        except ConfigurationError:
            return {}
        proof = Registrations(self.ledger).latest()
        trades: dict[UUID, ValidationTrade] = {}
        for publication in publications:
            results = {row.variant: row for row in publication.result.results}
            for variant in proof.registry.family(publication.family).variants:
                if (
                    apply_variant(publication.baseline, variant).config_hash
                    != self.config.config_hash
                ):
                    continue
                for trade in results[variant.name].sample.trades:
                    if trade.playbook is None:
                        continue
                    prior = trades.get(trade.identity)
                    if prior is not None and prior != trade:
                        raise DataIntegrityError("XA-02: duplicate OOS trade evidence differs")
                    trades[trade.identity] = trade
        ordered = tuple(sorted(trades.values(), key=lambda row: (row.exit, row.identity.hex)))
        return {
            name: tuple(row.r_multiple for row in ordered if row.playbook == name)
            for name in Playbook
            if any(row.playbook == name for row in ordered)
        }

    def _publications(self) -> tuple[GradePublication, ...]:
        proof = Registrations(self.ledger).latest()
        from backend.evaluation.calibrated_costs import snapshot as cost_snapshot

        current_costs = cost_snapshot(
            self.ledger, "PAPER" if self.settings.paper_trading else "LIVE"
        )
        with Session(self.ledger.engine) as session:
            rows = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "VALIDATION_REPORT")
                    .order_by(SecurityEvent.seq.desc())
                    .limit(1001)
                )
            )
        if len(rows) > 1000:
            raise DataIntegrityError("EX-06: grade publication inventory exceeds its bound")
        checked = []
        seen: set[str] = set()
        for row in rows:
            if row.created_at > self.ledger.clock.now():
                raise DataIntegrityError("EX-06: future validation publication")
            if row.detail.get("registration_sha256") != proof.sha256:
                continue
            # Older hash-only publications are never admission evidence.
            if "result" not in row.detail:
                continue
            publication = GradePublication.recorded(row.detail)
            if publication.family in seen or publication.kind != "WALKFORWARD":
                continue
            seen.add(publication.family)
            if publication.settings_sha256 != self.settings.config_hash:
                continue
            if publication.inputs.sha256 != proof.context_sha256:
                raise DataIntegrityError("EX-06: grade inputs differ from registered input hash")
            if publication.inputs.synthetic:
                continue
            if publication.inputs.calibration != current_costs:
                continue  # Changed actual costs require a new registered evaluation.
            family = proof.registry.family(publication.family)
            if publication.result.history_sha256 != proof.history_sha256 or tuple(
                item.variant for item in publication.result.results
            ) != ("SELECTED", *(item.name for item in family.variants)):
                raise DataIntegrityError(
                    "EX-06: grades differ from the registered family or history"
                )
            if any(
                not proof.training_start
                <= item.sample.start
                < item.sample.end
                < proof.holdout_start
                for item in publication.result.results
            ) or any(
                row.fold.train_start != proof.training_start
                or row.fold.test_end >= proof.holdout_start
                for row in publication.result.selections
            ):
                raise DataIntegrityError(
                    "EX-06: ordinary grades cannot consume holdout or pre-warmup dates"
                )
            cached = self._verified.get(publication.result_sha256)
            if cached is None:
                # Recompute statistics; a stored WORKING string is not authority.
                expected = _results(
                    tuple(item.sample for item in publication.result.results),
                    dict(proof.cumulative_trials)[family.name],
                    publication.baseline.qv,
                )
                if expected != publication.result.results:
                    raise DataIntegrityError(
                        "EX-06: stored grades differ from registered statistics"
                    )
                self._verified[publication.result_sha256] = publication
            elif cached != publication:
                raise DataIntegrityError("EX-06: immutable grade binding changed")
            checked.append(publication)
        return tuple(checked)

    def exit_working(self) -> bool:
        try:
            publications = self._publications()
        except ConfigurationError:
            return False
        proof = Registrations(self.ledger).latest()
        for publication in publications:
            if publication.family != "EXITS":
                continue
            family = proof.registry.family(publication.family)
            results = {item.variant: item for item in publication.result.results}
            for variant in family.variants:
                if (
                    apply_variant(publication.baseline, variant).config_hash
                    == self.config.config_hash
                    and results[variant.name].grade == "WORKING"
                ):
                    return True
        return False

    def earnings_working(self) -> bool:
        if "EARNINGS_GAP" not in self.config.enabled_playbooks:
            return False
        try:
            publications = self._publications()
        except ConfigurationError:
            return False
        proof = Registrations(self.ledger).latest()
        for publication in publications:
            if publication.family != "PLAYBOOK":
                continue
            family = proof.registry.family("PLAYBOOK")
            results = {row.variant: row for row in publication.result.results}
            for variant in family.variants:
                policy = apply_variant(publication.baseline, variant)
                isolated = self.config.model_dump(mode="json")
                isolated["playbooks"]["enabled"] = ["EARNINGS_GAP"]
                if (
                    policy.enabled_playbooks == ("EARNINGS_GAP",)
                    and policy.config_hash == YamlConfig.model_validate(isolated).config_hash
                    and results[variant.name].grade == "WORKING"
                ):
                    return True
        return False
