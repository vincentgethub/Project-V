"""QV/PF: registered windows use the real sealed, sequential CRO replay engine."""

import hashlib
import json
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from pydantic import Field

from backend.core.config import Settings, YamlConfig
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.data.frozen_filings import FrozenFilings
from backend.data.history import Digest, FrozenHistory, validate_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import AssetClass, DeployableCapital, FrozenModel, Instrument, Symbol
from backend.evaluation.calibrated_costs import CostCalibration
from backend.evaluation.costs import FeeSchedule
from backend.evaluation.registry import Registration, Variant, apply_variant
from backend.evaluation.replay import ReplayPreparation, ReplayRequest, prepare_replay, replay
from backend.evaluation.universe import HistoricalUniverse
from backend.evaluation.walkforward import Sample, ValidationTrade

MICRO = Decimal("0.000001")


class RegistrationContext(FrozenModel):
    """Exact preimage of the registration's nonsecret simulation input hash."""

    settings: Digest
    config: Digest
    filings: Digest
    fees: Digest
    symbols: tuple[Symbol, ...] = Field(min_length=1, max_length=100)
    initial_equity: str = Field(
        strict=True, min_length=1, max_length=64, pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$"
    )
    funding: DeployableCapital
    synthetic: bool = Field(strict=True)
    instruments: tuple[Instrument, ...] = Field(min_length=1, max_length=10000)
    calibration: CostCalibration = Field(
        default_factory=CostCalibration, exclude_if=lambda v: v.scope is None
    )
    universe: HistoricalUniverse | None = Field(default=None, exclude_if=lambda v: v is None)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def registration_context(
    settings: Settings,
    config: YamlConfig,
    filings: FrozenFilings,
    fees: FeeSchedule,
    seed: ReplayRequest,
    registry: InstrumentRegistry,
    calibration: CostCalibration | None = None,
) -> RegistrationContext:
    return RegistrationContext(
        settings=settings.config_hash,
        config=config.config_hash,
        filings=filings.manifest.sha256,
        fees=fees.sha256,
        symbols=seed.symbols,
        initial_equity=str(seed.initial_equity),
        funding=seed.funding,
        synthetic=seed.synthetic,
        instruments=tuple(registry.get(symbol) for symbol in sorted(registry.symbols)),
        calibration=CostCalibration() if calibration is None else calibration,
        universe=seed.universe,
    )


def context_hash(
    settings: Settings,
    config: YamlConfig,
    filings: FrozenFilings,
    fees: FeeSchedule,
    seed: ReplayRequest,
    registry: InstrumentRegistry,
    calibration: CostCalibration | None = None,
) -> str:
    return registration_context(settings, config, filings, fees, seed, registry, calibration).sha256


class ReplayEvaluator:
    """Only a registered explicit variant; windows restart with the fixed cash seed.

    Unresolved positions stay marked to market in daily returns but are excluded
    from resolved-trade counts. Arrays are causal; portfolio state is never reused.
    """

    @property
    def universe_sha256(self) -> str | None:
        return None if self.seed.universe is None else self.seed.universe.file_sha256

    def __init__(
        self,
        registration: Registration,
        seed: ReplayRequest,
        history: FrozenHistory,
        filings: FrozenFilings,
        settings: Settings,
        config: YamlConfig,
        registry: InstrumentRegistry,
        calendar: MarketCalendar,
        fees: FeeSchedule,
        *,
        workers: int = 1,
        cache_root: Path | None = None,
        final: bool = False,
        calibration: CostCalibration | None = None,
    ) -> None:
        self.proof, self.seed = (
            Registration.model_validate(registration),
            ReplayRequest.model_validate(seed),
        )
        self.history, self.filings = (
            FrozenHistory.model_validate(history),
            FrozenFilings.model_validate(filings),
        )
        self.settings, self.config, self.fees = (
            Settings.validated_copy(settings),
            YamlConfig.model_validate(config),
            FeeSchedule.model_validate(fees),
        )
        self.calibration = (
            CostCalibration()
            if calibration is None
            else CostCalibration.model_validate(calibration)
        )
        if self.calibration.scope is not None and self.calibration.scope.environment != (
            "PAPER" if self.settings.paper_trading else "LIVE"
        ):
            raise ConfigurationError("XA/QV: opposite-environment cost calibration refused")
        validate_history(self.history.bundle, calendar)
        self.config.assert_settings_consistent(self.settings)
        if type(final) is not bool or type(workers) is not int or not 1 <= workers <= 256:
            raise ConfigurationError(
                "QV/PF: bounded workers and explicit final capability required"
            )
        if (
            self.proof.history_sha256 != self.history.manifest.sha256
            or self.proof.context_sha256 is None
            or self.proof.context_sha256
            != context_hash(
                self.settings,
                self.config,
                self.filings,
                self.fees,
                self.seed,
                registry,
                self.calibration,
            )
        ):
            raise ConfigurationError(
                "QV-01/06: registration differs from the frozen run inputs; register on the host"
            )
        self.registry, self.calendar, self.workers, self.cache_root, self.final = (
            registry,
            calendar,
            workers,
            cache_root,
            final,
        )
        self._preparations: dict[str, ReplayPreparation] = {}
        self._shared_arrays: dict[str, ReplayPreparation] = {}
        self._samples: dict[tuple[str, date, date], Sample] = {}

    def preflight(self, family: str) -> None:
        """Refuse unavailable implementations before consuming a one-use holdout."""
        chosen = next((row for row in self.proof.registry.families if row.name == family), None)
        if chosen is None:
            raise ConfigurationError("QV-01: unregistered family refused")
        for row in chosen.variants:
            policy = apply_variant(self.config, row)
            if "EARNINGS_GAP" in policy.enabled_playbooks:
                for symbol in self.seed.symbols:
                    if self.registry.get(symbol).asset_class != AssetClass.STOCK:
                        continue
                    if self.filings.for_symbol(symbol, "SUBMISSIONS") is None:
                        raise ConfigurationError(
                            "EG-02: freeze bound submissions before validation"
                        )
                    self.history.bundle.for_symbol(symbol, "ALL")
                    self.history.bundle.for_symbol("SPY", "ALL")

    def __call__(self, variant: Variant, start: date, end: date) -> Sample:
        chosen = Variant.model_validate(variant)
        if chosen not in tuple(
            row for family in self.proof.registry.families for row in family.variants
        ):
            raise ConfigurationError("QV-01: unregistered variant refused")
        if (
            type(start) is not date
            or type(end) is not date
            or start >= end
            or (
                start < self.proof.training_start
                or end > (self.proof.holdout_end if self.final else self.proof.training_end)
            )
            or (not self.final and end >= self.proof.holdout_start)
        ):
            raise ConfigurationError(
                "QV-02/03: validation window is unavailable or consumes the holdout"
            )
        policy = apply_variant(self.config, chosen)
        key = (policy.config_hash, start, end)
        if key in self._samples:
            return Sample.model_validate(self._samples[key])
        prepared = self._preparations.get(policy.config_hash)
        required_end = (
            self.proof.holdout_end if end >= self.proof.holdout_start else self.proof.training_end
        )
        if prepared is None or prepared.end < end:
            dependencies = policy.model_dump(mode="json")
            sharing_key = hashlib.sha256(
                json.dumps(
                    {
                        "fundamentals": dependencies["fundamentals"],
                        "playbooks": dependencies["playbooks"],
                        "sizing": {
                            name: dependencies["sizing"][name]
                            for name in (
                                "stop_atr_mult",
                                "swing_lookback",
                                "target_r",
                                "max_stop_pct",
                            )
                        },
                        "end": str(required_end),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            shared = self._shared_arrays.get(sharing_key)
            if shared is None:
                prepared = prepare_replay(
                    self.seed.symbols,
                    required_end,
                    self.history,
                    self.filings,
                    policy,
                    self.registry,
                    workers=self.workers,
                    cache_root=self.cache_root,
                )
                self._shared_arrays[sharing_key] = prepared
            else:
                # Only dependencies explicitly proved above permit relabeling.
                # Cash, CRO verdicts and outcomes are recomputed for every window.
                prepared = ReplayPreparation.model_validate(
                    {
                        **shared.model_dump(),
                        "config_sha256": policy.config_hash,
                        "arrays": tuple(
                            (
                                type(gates).model_validate(
                                    {**gates.model_dump(), "config_sha256": policy.config_hash}
                                ),
                                timeline,
                            )
                            for gates, timeline in shared.arrays
                        ),
                    }
                )
            self._preparations[policy.config_hash] = prepared
        request = ReplayRequest.model_validate(
            {**self.seed.model_dump(), "start": start, "end": end}
        )
        run = replay(
            request,
            self.history,
            self.filings,
            self.settings,
            policy,
            self.registry,
            self.calendar,
            self.fees,
            workers=self.workers,
            cache_root=self.cache_root,
            preparation=prepared,
            calibration=self.calibration,
        )
        trades = []
        for item in run.decisions:
            row = item.outcome
            if row.setup.disposition == "APPROVED" and row.status == "RESOLVED":
                if (
                    row.entry_session is None
                    or row.exit_session is None
                    or row.r_multiple is None
                    or row.net_money is None
                ):
                    raise DataIntegrityError(
                        "QV-06: resolved replay outcome has no exact trade evidence"
                    )
                trades.append(
                    ValidationTrade(
                        identity=row.setup.alert_id,
                        decision=row.setup.decision_session,
                        entry=row.entry_session,
                        exit=row.exit_session,
                        r_multiple=row.r_multiple,
                        net_money=row.net_money,
                        playbook=row.setup.playbook,
                    )
                )
        daily = []
        prior = self.seed.initial_equity
        with localcontext() as precision:
            precision.prec = 80
            for point in run.portfolio:
                daily.append((point.session, (point.equity / prior - 1).quantize(MICRO)))
                prior = point.equity
        result = Sample(
            variant=chosen.name,
            start=start,
            end=end,
            history_sha256=self.history.manifest.sha256,
            trades=tuple(sorted(trades, key=lambda row: (row.exit, row.identity.hex))),
            daily=tuple(daily),
        )
        self._samples[key] = result
        return result
