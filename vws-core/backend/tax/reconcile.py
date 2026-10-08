"""TX-09: owner-supplied column mapping; broker 1099-B is authoritative."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Self

import yaml
from pydantic import Field, model_validator

from backend.core.config import _ExactSafeLoader
from backend.core.errors import DataIntegrityError
from backend.domain.models import FrozenModel, Money, PositiveQty, SessionDate, Symbol
from backend.tax.accounting import TaxBook
from backend.tax.imports import read_bytes
from backend.tax.lots import trade_day
from backend.tax.models import NOTICE, SIMULATED, TaxSale
from backend.tax.reports import _csv


class ColumnMapping(FrozenModel):
    symbol: str = Field(min_length=1, max_length=128)
    date_sold: str = Field(min_length=1, max_length=128)
    qty: str = Field(min_length=1, max_length=128)
    proceeds: str = Field(min_length=1, max_length=128)
    basis: str = Field(min_length=1, max_length=128)
    wash: str = Field(min_length=1, max_length=128)
    term: str = Field(min_length=1, max_length=128)
    date_format: str = Field(default="%Y-%m-%d", min_length=1, max_length=32)
    short_term_label: str = Field(default="ST", min_length=1, max_length=32)
    long_term_label: str = Field(default="LT", min_length=1, max_length=32)

    @model_validator(mode="after")
    def distinct(self) -> Self:
        names = (
            self.symbol,
            self.date_sold,
            self.qty,
            self.proceeds,
            self.basis,
            self.wash,
            self.term,
        )
        if len(set(names)) != len(names) or self.short_term_label == self.long_term_label:
            raise ValueError("TX-09: mapping columns and term labels must be distinct")
        return self


class Broker1099(FrozenModel):
    symbol: Symbol
    date_sold: SessionDate
    qty: PositiveQty
    proceeds: Money
    basis: Money = Field(ge=0)
    wash: Money = Field(ge=0)
    term: str = Field(pattern=r"^(ST|LT)$")


class Difference(FrozenModel):
    symbol: Symbol
    date_sold: SessionDate
    qty: PositiveQty
    status: str = Field(pattern=r"^(MATCH|DIFFERENT|UNMATCHED_BROKER|UNMATCHED_LEDGER|AMBIGUOUS)$")
    detail: str = Field(min_length=1, max_length=512)
    likely_cause: str = Field(min_length=1, max_length=512)
    proceeds_difference: Money | None = None
    basis_difference: Money | None = None
    wash_difference: Money | None = None


def load_mapping(path: Path) -> ColumnMapping:
    try:
        payload = read_bytes(path, 65536)
        depth = 0
        for token in yaml.scan(payload):
            if isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)):
                raise ValueError("TX-09: YAML aliases and anchors are forbidden")
            if isinstance(
                token,
                (
                    yaml.tokens.BlockMappingStartToken,
                    yaml.tokens.BlockSequenceStartToken,
                    yaml.tokens.FlowMappingStartToken,
                    yaml.tokens.FlowSequenceStartToken,
                ),
            ):
                depth += 1
                if depth > 20:
                    raise ValueError("TX-09: mapping nesting exceeds its bound")
            elif isinstance(
                token,
                (
                    yaml.tokens.BlockEndToken,
                    yaml.tokens.FlowMappingEndToken,
                    yaml.tokens.FlowSequenceEndToken,
                ),
            ):
                depth -= 1
        # ExactSafeLoader inherits SafeLoader; anchors/depth are rejected above.
        return ColumnMapping.model_validate(yaml.load(payload, Loader=_ExactSafeLoader))  # nosec B506
    except Exception:
        raise DataIntegrityError("TX-09: owner 1099-B column mapping is unavailable") from None


def read_1099(path: Path, mapping: ColumnMapping) -> tuple[Broker1099, ...]:
    try:
        from datetime import datetime

        bound = ColumnMapping.model_validate(mapping)
        data = read_bytes(path, 16 * 1024 * 1024)
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
        names = (
            bound.symbol,
            bound.date_sold,
            bound.qty,
            bound.proceeds,
            bound.basis,
            bound.wash,
            bound.term,
        )
        if (
            reader.fieldnames is None
            or len(set(reader.fieldnames)) != len(reader.fieldnames)
            or not set(names) <= set(reader.fieldnames)
        ):
            raise ValueError("TX-09: CSV columns differ from explicit mapping")
        rows: list[Broker1099] = []
        for raw in reader:
            if (
                len(rows) >= 100000
                or any(not isinstance(value, str) or len(value) > 512 for value in raw.values())
                or set(raw) != set(reader.fieldnames)
            ):
                raise ValueError("TX-09: malformed/bounded CSV row required")
            qty = Decimal(raw[bound.qty])
            if not qty.is_finite() or qty != qty.to_integral_value() or not 0 < qty <= 10**9:
                raise ValueError("TX-09: whole-share quantity required")
            label = raw[bound.term]
            if label not in {bound.short_term_label, bound.long_term_label}:
                raise ValueError("TX-09: explicit term label required")
            rows.append(
                Broker1099(
                    symbol=raw[bound.symbol],
                    date_sold=datetime.strptime(raw[bound.date_sold], bound.date_format).date(),
                    qty=int(qty),
                    proceeds=Decimal(raw[bound.proceeds]),
                    basis=Decimal(raw[bound.basis]),
                    wash=Decimal(raw[bound.wash]),
                    term="ST" if label == bound.short_term_label else "LT",
                )
            )
        return tuple(rows)
    except Exception:
        raise DataIntegrityError("TX-09: broker 1099-B rows cannot be verified") from None


def reconcile(
    book: TaxBook, rows: tuple[Broker1099, ...], year: int, account_id: str
) -> tuple[Difference, ...]:
    try:
        checked = TaxBook.model_validate(book)
        if (
            type(year) is not int
            or not 1900 <= year <= 9998
            or not isinstance(rows, tuple)
            or len(rows) > 100000
            or account_id not in {row.id for row in checked.accounts}
        ):
            raise ValueError("TX-09: bound account/year/1099-B required")
        official = tuple(Broker1099.model_validate(row) for row in rows)
        if any(row.date_sold.year != year for row in official):
            raise ValueError("TX-09: 1099-B tax year differs")
        grouped: dict[tuple[str, date, int], list[tuple[TaxSale, ...]]] = defaultdict(list)
        executions: dict[str, list[TaxSale]] = defaultdict(list)
        for sale in checked.sales:
            if sale.account_id == account_id and trade_day(sale.sold_at).year == year:
                executions[str(sale.fill_id)].append(sale)
        for execution in executions.values():
            first = execution[0]
            grouped[
                (first.symbol, trade_day(first.sold_at), sum(row.qty for row in execution))
            ].append(tuple(execution))
        broker_counts: dict[tuple[str, date, int], int] = defaultdict(int)
        for row in official:
            broker_counts[(row.symbol, row.date_sold, row.qty)] += 1
        output: list[Difference] = []
        consumed: set[tuple[str, date, int]] = set()
        with localcontext() as precision:
            precision.prec = 80
            for row in official:
                key = (row.symbol, row.date_sold, row.qty)
                possible = grouped.get(key, [])
                if not possible:
                    output.append(
                        Difference(
                            symbol=row.symbol,
                            date_sold=row.date_sold,
                            qty=row.qty,
                            status="UNMATCHED_BROKER",
                            detail="1099-B row has no unambiguous executed match",
                            likely_cause="Missing import, lot aggregation, account selection or corporate action",
                        )
                    )
                    continue
                if len(possible) != 1 or broker_counts[key] != 1:
                    consumed.add(key)
                    output.append(
                        Difference(
                            symbol=row.symbol,
                            date_sold=row.date_sold,
                            qty=row.qty,
                            status="AMBIGUOUS",
                            detail="Multiple symbol/date/quantity matches require broker review",
                            likely_cause="Multiple executions or broker lot aggregation; no arbitrary match was chosen",
                        )
                    )
                    continue
                consumed.add(key)
                ours = possible[0]
                proceeds = sum((sale.proceeds for sale in ours), Decimal(0)) - row.proceeds
                basis = sum((sale.basis for sale in ours), Decimal(0)) - row.basis
                wash = sum((sale.wash_disallowed for sale in ours), Decimal(0)) - row.wash
                terms = {sale.term for sale in ours}
                flags = tuple(
                    label
                    for label, difference in (
                        ("proceeds", proceeds),
                        ("basis", basis),
                        ("wash", wash),
                    )
                    if abs(difference) > Decimal("0.01")
                ) + (() if terms == {row.term} else ("term",))
                output.append(
                    Difference(
                        symbol=row.symbol,
                        date_sold=row.date_sold,
                        qty=row.qty,
                        status="DIFFERENT" if flags else "MATCH",
                        detail="Differences: " + ", ".join(flags)
                        if flags
                        else "Within one cent; term agrees",
                        likely_cause="Cross-account wash not visible to broker, lot method, fees or corporate action"
                        if flags
                        else "1099-B remains authoritative",
                        proceeds_difference=proceeds,
                        basis_difference=basis,
                        wash_difference=wash,
                    )
                )
            for key, executions_for_key in grouped.items():
                if key not in consumed:
                    for _execution in executions_for_key:
                        output.append(
                            Difference(
                                symbol=key[0],
                                date_sold=key[1],
                                qty=key[2],
                                status="UNMATCHED_LEDGER",
                                detail="Executed ledger sale has no 1099-B match",
                                likely_cause="Broker aggregation, missing broker row, account selection or corporate action",
                            )
                        )
        return tuple(output)
    except Exception:
        raise DataIntegrityError("TX-09: 1099-B reconciliation could not be verified") from None


def reconciliation_csv(rows: tuple[Difference, ...], *, simulate: bool = False) -> bytes:
    checked = tuple(Difference.model_validate(row) for row in rows)
    columns = tuple(Difference.model_fields)
    return _csv(
        columns,
        tuple(tuple(row.model_dump(mode="python")[name] for name in columns) for row in checked),
        SIMULATED if simulate else "LIVE - 1099-B AUTHORITATIVE",
    )


def summary(rows: tuple[Difference, ...]) -> str:
    checked = tuple(Difference.model_validate(row) for row in rows)
    return f"1099-B authoritative: {sum(row.status == 'MATCH' for row in checked)} matched, {sum(row.status != 'MATCH' for row in checked)} need review.\n{NOTICE}"
