"""R-02/CRO-02/CRO-05/CMP-01/CMP-07: explicit frozen instrument allowlist.

Bundled CSV data are demonstration inputs, not verified investable metadata or
current fund holdings. A production operator must replace and verify them.
An empty blackout/group file expresses only the supplied operator policy;
this registry makes no claim to discover all events or tax-equivalent funds.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path
from types import MappingProxyType

import structlog
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.core.money import decimal_money
from backend.domain.models import (
    AssetClass,
    BlackoutWindow,
    Instrument,
    validate_symbol,
)

GICS_SECTORS = frozenset(
    {
        "Communication Services",
        "Consumer Discretionary",
        "Consumer Staples",
        "Energy",
        "Financials",
        "Health Care",
        "Industrials",
        "Information Technology",
        "Materials",
        "Real Estate",
        "Utilities",
    }
)


def _rows(path: Path, columns: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    """R-02: load exact CSV columns; duplicate headers/missing fields are errors."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or (
                len(reader.fieldnames) != len(columns) or set(reader.fieldnames) != set(columns)
            ):
                raise DataIntegrityError(f"CSV columns do not match policy schema: {path.name}")
            result: list[dict[str, str]] = []
            for row in reader:
                if set(row) != set(columns) or any(
                    not isinstance(row[key], str) for key in columns
                ):
                    raise DataIntegrityError(f"CSV row has missing or surplus fields: {path.name}")
                result.append({key: row[key].strip() for key in columns})
            return tuple(result)
    except DataIntegrityError:
        raise
    except Exception as exc:
        structlog.get_logger(__name__).error(
            "policy_csv_read_failed", file=path.name, error_type=type(exc).__name__
        )
        raise DataIntegrityError(f"Cannot verify policy CSV: {path.name}") from exc


def _boolean(value: str) -> bool:
    """R-02: typoed boolean metadata cannot become a truthy permissive value."""
    if value not in {"true", "false"}:
        raise DataIntegrityError("CSV boolean must be exactly true or false")
    return value == "true"


@dataclass(frozen=True, init=False)
class InstrumentRegistry:
    """R-02/CRO-02/CRO-05/CMP-01: detached, immutable metadata snapshot."""

    _instruments: Mapping[str, Instrument]
    _weights: Mapping[str, Mapping[str, Decimal]]
    _groups: Mapping[str, frozenset[str]]
    blackout_windows: tuple[BlackoutWindow, ...]

    def __init__(
        self,
        instruments: Iterable[Instrument],
        etf_weights: Mapping[str, Mapping[str, Decimal]] | None = None,
        identical_groups: Mapping[str, Iterable[str]] | None = None,
        blackout_windows: Iterable[BlackoutWindow] = (),
    ) -> None:
        try:
            names: dict[str, Instrument] = {}
            for instrument in instruments:
                if not isinstance(instrument, Instrument):
                    raise DataIntegrityError("Registry instruments must be valid and unique")
                instrument = Instrument.model_validate(instrument)
                if instrument.symbol in names:
                    raise DataIntegrityError("Registry instruments must be valid and unique")
                names[instrument.symbol] = instrument
            if not names:
                raise DataIntegrityError("An empty instrument allowlist cannot authorize trading")
            weights: dict[str, Mapping[str, Decimal]] = {}
            for symbol, sectors in (etf_weights or {}).items():
                if symbol not in names or names[symbol].asset_class == AssetClass.STOCK:
                    raise DataIntegrityError(
                        "ETF weights reference an unknown or non-ETF instrument"
                    )
                parsed: dict[str, Decimal] = {}
                for sector, weight in sectors.items():
                    amount = decimal_money(weight)
                    if sector not in GICS_SECTORS or not Decimal(0) < amount <= Decimal(1):
                        raise DataIntegrityError(
                            "ETF sectors/weights must be known positive fractions"
                        )
                    parsed[sector] = amount
                with localcontext() as context:
                    context.prec = 80
                    if not parsed or sum(parsed.values(), Decimal(0)) != Decimal(1):
                        raise DataIntegrityError("ETF look-through weights must total exactly one")
                weights[symbol] = MappingProxyType(parsed)
            groups: dict[str, frozenset[str]] = {}
            for group_id, group in (identical_groups or {}).items():
                members = tuple(group)
                if not group_id.strip() or len(members) < 2 or len(members) != len(set(members)):
                    raise DataIntegrityError(
                        "Identical group requires a name and at least two unique symbols"
                    )
                for symbol in members:
                    validate_symbol(symbol)
                    if symbol not in names or symbol in groups:
                        raise DataIntegrityError(
                            "Identical groups must use known, disjoint symbols"
                        )
                    groups[symbol] = frozenset(members)
            windows_list: list[BlackoutWindow] = []
            for window in blackout_windows:
                if not isinstance(window, BlackoutWindow):
                    raise DataIntegrityError("Blackout window must reference a known symbol")
                window = BlackoutWindow.model_validate(window)
                if window.symbol is not None and window.symbol not in names:
                    raise DataIntegrityError("Blackout window must reference a known symbol")
                windows_list.append(window)
            windows = tuple(windows_list)
            object.__setattr__(self, "_instruments", MappingProxyType(names))
            object.__setattr__(self, "_weights", MappingProxyType(weights))
            object.__setattr__(self, "_groups", MappingProxyType(groups))
            object.__setattr__(self, "blackout_windows", windows)
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot verify instrument registry") from exc

    @property
    def symbols(self) -> frozenset[str]:
        """CMP-07: the complete explicit allowlist, detached from caller input."""
        return frozenset(self._instruments)

    def get(self, symbol: str) -> Instrument:
        """R-02/CRO-02/CMP-07: an unknown name never acquires inferred metadata."""
        try:
            validate_symbol(symbol)
            return self._instruments[symbol]
        except Exception as exc:
            raise DataIntegrityError("Symbol is absent from the instrument allowlist") from exc

    def sector_weights(self, symbol: str) -> Mapping[str, Decimal]:
        """CRO-05: absent look-through means 100% of the declared sector.

        An UNKNOWN declared sector remains UNKNOWN here and must block at the
        CRO; it must never be silently treated as zero sector exposure.
        """
        instrument = self.get(symbol)
        return self._weights.get(symbol, MappingProxyType({instrument.gics_sector: Decimal(1)}))

    def identical_group(self, symbol: str) -> frozenset[str]:
        """CMP-01/CMP-02: an ungrouped known name is identical only to itself."""
        self.get(symbol)
        return self._groups.get(symbol, frozenset({symbol}))

    def validated_copy(self) -> InstrumentRegistry:
        """R-02/R-03: detach and revalidate even a forged registry instance.

        Invoke this on the class at policy ingress so a subclass cannot replace
        the validation routine. Stored symbol keys must agree with instruments;
        stored identical-group relationships must be complete and symmetric.
        """
        try:
            if not all(
                isinstance(value, Mapping)
                for value in (self._instruments, self._weights, self._groups)
            ):
                raise DataIntegrityError("Registry storage must contain verifiable mappings")
            names: list[Instrument] = []
            for symbol, instrument in self._instruments.items():
                validated = Instrument.model_validate(instrument)
                if symbol != validated.symbol:
                    raise DataIntegrityError("Registry symbol key disagrees with metadata")
                names.append(validated)
            groups: dict[str, tuple[str, ...]] = {}
            seen: set[frozenset[str]] = set()
            for symbol, members in self._groups.items():
                if not isinstance(members, frozenset) or symbol not in members:
                    raise DataIntegrityError("Registry identical-group relationship is malformed")
                if any(self._groups.get(member) != members for member in members):
                    raise DataIntegrityError(
                        "Registry identical-group relationships must be symmetric"
                    )
                if members not in seen:
                    groups[f"VALIDATED_GROUP_{len(groups)}"] = tuple(sorted(members))
                    seen.add(members)
            return InstrumentRegistry(names, self._weights, groups, self.blackout_windows)
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot revalidate instrument registry") from exc

    @classmethod
    def from_csv(cls, directory: Path) -> InstrumentRegistry:
        """R-02/CRO-05/CMP-07: explicit I/O boundary; all four policy files required."""
        try:
            names = tuple(
                Instrument(
                    symbol=row["symbol"],
                    asset_class=AssetClass(row["asset_class"]),
                    gics_sector=row["gics_sector"],
                    themes=tuple(row["themes"].split(";")) if row["themes"] else (),
                    is_leveraged=_boolean(row["is_leveraged"]),
                    is_inverse=_boolean(row["is_inverse"]),
                    tradable=_boolean(row["tradable"]),
                )
                for row in _rows(
                    directory / "instruments.csv",
                    (
                        "symbol",
                        "asset_class",
                        "gics_sector",
                        "themes",
                        "is_leveraged",
                        "is_inverse",
                        "tradable",
                    ),
                )
            )
            weights: dict[str, dict[str, Decimal]] = {}
            for row in _rows(
                directory / "etf_sector_weights.csv",
                ("symbol", "gics_sector", "weight"),
            ):
                sector_weights = weights.setdefault(row["symbol"], {})
                if row["gics_sector"] in sector_weights:
                    raise DataIntegrityError("Duplicate ETF sector weight")
                sector_weights[row["gics_sector"]] = decimal_money(row["weight"])
            groups: dict[str, list[str]] = {}
            for row in _rows(directory / "substantially_identical.csv", ("group_id", "symbol")):
                groups.setdefault(row["group_id"], []).append(row["symbol"])
            windows = tuple(
                BlackoutWindow(
                    start=datetime.fromisoformat(row["start"]),
                    end=datetime.fromisoformat(row["end"]),
                    symbol=row["symbol"] or None,
                    reason=row["reason"],
                )
                for row in _rows(
                    directory / "blackout_windows.csv",
                    ("symbol", "start", "end", "reason"),
                )
            )
            return cls(names, weights, groups, windows)
        except DataIntegrityError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise DataIntegrityError("Policy CSV contains invalid instrument metadata") from exc
