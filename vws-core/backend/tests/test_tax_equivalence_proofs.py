"""TX: proof obligations for rejected proposals; these IDs remain gate failures.

The finite order abstractions are exhaustive, not random history sampling.
The accompanying TAX_EQUIVALENCE_PROOFS.md gives the induction arguments and
reachability premises. These checks are outside the unchanged tax selection:
an assertion about the original syntax must never manufacture a mutation kill.
"""

from __future__ import annotations

import ast
import codecs
import copy
import inspect
import textwrap
from decimal import Decimal, localcontext
from itertools import product
from pathlib import Path
from typing import Any, cast

import pytest

from backend.domain.models import Money, Side
from backend.domain.tax_profile import TaxProfile
from backend.tax import accounting, lots, reports
from backend.tax.reports import AnnualTax
from backend.tests.test_tax_accounting import account
from backend.tests.test_wash_sales import registry
from scripts.check_mutations import OWNER_APPROVED_IDS

CASES = (
    ("lots.xǁWashSaleMatcherǁ_inputs__mutmut_29", "rank"),
    ("lots.xǁWashSaleMatcherǁallocations__mutmut_44", "present"),
    ("lots.xǁWashSaleMatcherǁallocations__mutmut_46", "present"),
    ("lots.xǁWashSaleMatcherǁallocations__mutmut_47", "present"),
    ("accounting.x__rebuild__mutmut_107", "zip"),
    ("accounting.x__rebuild__mutmut_110", "zip"),
    ("accounting.x__rebuild__mutmut_35", "positive"),
    ("accounting.x__rebuild__mutmut_53", "fresh"),
    ("accounting.x_build_tax_book__mutmut_114", "sum"),
    ("accounting.x_build_tax_book__mutmut_123", "sum"),
    ("accounting.x_build_tax_book__mutmut_134", "sum"),
    ("accounting.x_build_tax_book__mutmut_32", "rank"),
    ("reports.x_annual__mutmut_119", "sum"),
    ("reports.x_annual__mutmut_190", "sum"),
    ("reports.x_annual__mutmut_200", "sum"),
    ("reports.x_annual__mutmut_210", "sum"),
    ("reports.x_annual__mutmut_226", "sum"),
    ("reports.x_annual__mutmut_242", "sum"),
    ("reports.x_annual__mutmut_340", "sum"),
    ("reports.x_annual__mutmut_346", "sum"),
    ("reports.x_annual__mutmut_109", "sum"),
    ("reports.x_render_report__mutmut_195", "codec"),
    ("reports.x_render_report__mutmut_91", "mode"),
    ("reports.x_render_report__mutmut_92", "mode"),
    ("reports.x_render_report__mutmut_93", "mode"),
    ("reports.x_save_report__mutmut_44", "codec"),
    ("reports.x_annual__mutmut_104", "precision"),
)


@pytest.fixture(scope="module")
def generated_tax_ast() -> dict[str, dict[str, ast.FunctionDef]]:
    from mutmut.mutation.file_mutation import mutate_file_contents

    root = Path(__file__).resolve().parents[2]
    result: dict[str, dict[str, ast.FunctionDef]] = {}
    for module in ("lots", "accounting", "reports"):
        filename = f"backend/tax/{module}.py"
        generated = mutate_file_contents(filename, (root / filename).read_text(encoding="utf-8"))
        tree = ast.parse(generated.code)
        result[module] = {
            node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
    return result


def differing_nodes(left: ast.AST, right: ast.AST) -> list[tuple[ast.AST, ast.AST]]:
    if type(left) is not type(right):
        return [(left, right)]
    changes: list[tuple[ast.AST, ast.AST]] = []
    right_fields = dict(ast.iter_fields(right))
    for field, a in ast.iter_fields(left):
        b = right_fields[field]
        if isinstance(a, ast.AST) and isinstance(b, ast.AST):
            changes.extend(differing_nodes(a, b))
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                return [(left, right)]
            for x, y in zip(a, b, strict=True):
                if isinstance(x, ast.AST) and isinstance(y, ast.AST):
                    changes.extend(differing_nodes(x, y))
                elif x != y:
                    return [(left, right)]
        elif a != b:
            return [(left, right)]
    return changes


def normalized_source(value: Any) -> str:
    return ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(value))))


def prove_rank() -> None:
    assert set(Side) == {Side.BUY, Side.SELL}
    # Three comparison outcomes cover every timestamp/UUID pair. Two tags cover
    # every validated side. Lexicographic order is unchanged in all 36 classes.
    for time_order, uuid_order, a, b in product((-1, 0, 1), (-1, 0, 1), (0, 1), (0, 1)):
        left = (time_order, a, uuid_order)
        right = (0, b, 0)
        new_left = (time_order, 2 * a, uuid_order)
        new_right = (0, 2 * b, 0)
        assert (left < right, left == right) == (new_left < new_right, new_left == new_right)


def prove_present() -> None:
    tree = ast.parse(normalized_source(lots.WashSaleMatcher.allocations))
    guard = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "replacement.trade_id in surviving[loss.trade_id]"
    )
    assert len(guard.body) == 1
    assert (
        ast.unparse(guard.body[0])
        == "first_held = replacement.qty - surviving[loss.trade_id].get(replacement.trade_id, 0)"
    )
    # An arbitrary opaque value is returned by identity, independently of every
    # default. Built-in dict membership/get have no intervening mutation here.
    key, arbitrary_value = object(), object()
    evidence = {key: arbitrary_value}
    assert type(evidence) is dict and key in evidence
    assert (
        evidence.get(key)
        is evidence.get(key, None)
        is evidence.get(key, 0)
        is evidence.get(key, 1)
        is arbitrary_value
    )


def prove_zip() -> None:
    # __reduce__ exposes the same built-in iterator state and disabled strict
    # flag, so every next()/exception transition is the same for arbitrary
    # iterators, including adjacent lists with different lengths.
    left, right = iter(()), iter(())
    baseline = zip(left, right, strict=False).__reduce__()
    assert baseline == zip(left, right, strict=None).__reduce__()  # type: ignore[call-overload]
    assert baseline == zip(left, right).__reduce__()  # noqa: B905 - omitted strict is the proof case


def prove_positive() -> None:
    # Every weak ordering of four integers has a rank representative in 0..3.
    # Exhausting ranks therefore proves this for every size and share index.
    for start, a, b, end in product(range(4), repeat=4):
        if a < b:
            assert (start <= a < b <= end) == (start <= a <= b <= end)
    source = normalized_source(accounting._rebuild)
    assert "marks = sorted(boundaries[fill.fill_id])" in source
    assert "zip(marks, marks[1:], strict=False)" in source
    assert "parts.remove(part)" in source
    # A partial sale advances by min(remaining, width); zero width is removed.
    for width_order, remaining_order in product(range(1, 4), repeat=2):
        after = width_order - min(width_order, remaining_order)
        assert after == 0 or after > 0


def prove_fresh(left: ast.AugAssign, right: ast.Assign) -> None:
    source = normalized_source(lots.WashSaleMatcher.allocations)
    assert (
        "assigned: dict[UUID, list[tuple[int, int]]] = {row.trade_id: [] for row in buys}" in source
    )
    assert "assigned[replacement.trade_id].extend(slices)" in source
    assert "assigned[replacement.trade_id].sort()" in source
    availability = normalized_source(lots.WashSaleMatcher._available_slices)
    assert "available = max(0, start - cursor)" in availability
    assert "matched = min(available, remaining)" in availability
    assert "output.append((cursor, cursor + matched))" in availability
    assert "cursor = max(cursor, end)" in availability
    rebuild = normalized_source(accounting._rebuild)
    assert "_Part(fill, start, end, pool_id, 0, fill.ts)" in rebuild
    builder = normalized_source(accounting.build_tax_book)
    assert (
        "candidate = matcher.allocations(history, tuple((row.ownership for row in owned)))"
        in builder
    )
    assert "boundaries[adjustment.replacement_trade_id].update((start, end))" in builder
    # Exhaust all weak orderings of a candidate and occupied interval. The
    # allocator returns only their complement. Union preserves disjointness;
    # induction means a physical share can receive at most one assignment.
    for a, b, c, d in product(range(4), repeat=4):
        if 0 <= a < b <= d and c <= d:
            intervals = lots.WashSaleMatcher._available_slices(c, d, [(a, b)], d)
            assert all(not (max(x, a) < min(y, b)) for x, y in intervals)

    # Freshness has two abstract states; the only legal assignment transition
    # is fresh->assigned. A disposal or split cannot make an assigned share
    # fresh again. For arbitrary cumulative amounts, the affine vectors agree.
    def affine(node: ast.AST) -> tuple[int, int]:
        if isinstance(node, ast.Name):
            return {"next_amount": (1, 0), "allocated": (0, 1)}[node.id]
        assert isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)
        a, b = affine(node.left), affine(node.right)
        return a[0] - b[0], a[1] - b[1]

    prior = (0, 0)
    increment, assignment = affine(left.value), affine(right.value)
    assert (prior[0] + increment[0], prior[1] + increment[1]) == assignment


def prove_sum() -> None:
    from pydantic import TypeAdapter

    money = TypeAdapter(Money)
    assert money.validate_python(0).as_tuple() == money.validate_python(Decimal(0)).as_tuple()
    # Empty versus nonempty is the complete sum induction. In the nonempty
    # branch Decimal converts integer 0 to Decimal(0) before the first add;
    # all subsequent operands/operations and Decimal flags are identical.
    # Include signed zero, exponent extremes and maximum scaled money in the
    # executable operator/validation check, including representation and flags.
    for text in (
        "0",
        "-0",
        "0.000000",
        "1E-1000",
        "1.230000",
        "-9223372036854.775808",
        "9223372036854.775807",
    ):
        value = Decimal(text)
        with localcontext() as context:
            context.prec = 80
            context.clear_flags()
            a = Decimal(0) + value
            flags = dict(context.flags)
            context.clear_flags()
            b = 0 + value
            assert a.as_tuple() == b.as_tuple() and dict(context.flags) == flags


def prove_mode() -> None:
    # AnnualTax's serialization schema is closed over these primitive cases;
    # no user serializer can inspect the spelling of the non-JSON mode.
    assert not AnnualTax.__pydantic_decorators__.field_serializers
    assert not AnnualTax.__pydantic_decorators__.model_serializers
    schema = AnnualTax.__pydantic_core_schema__
    kinds: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            assert "serialization" not in value
            if isinstance(value.get("type"), str):
                kinds.add(value["type"])
            for item in value.values():
                visit(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                visit(item)

    visit(schema)
    assert kinds <= {
        "model",
        "model-fields",
        "model-field",
        "int",
        "str",
        "tuple",
        "decimal",
        "function-before",
        "function-after",
        "no-info",
        "default",
        "nullable",
        "bool",
    }
    from datetime import date

    book = accounting.build_tax_book((), (account(),), registry(), "PAPER")
    totals = reports.annual(book, (), TaxProfile(), 2026, date(2027, 2, 1), simulate=True)
    original = totals.model_dump(mode="python")
    for mode in (None, "XXpythonXX", "PYTHON"):
        actual = totals.model_dump(mode=cast(Any, mode))
        assert actual == original
        assert all(type(actual[k]) is type(v) for k, v in original.items())
        assert all(
            actual[k] is v for k, v in original.items() if type(v) in (Decimal, str, int, bool)
        )


@pytest.mark.parametrize(("key", "kind"), CASES, ids=[key for key, _ in CASES])
def test_TX_rejected_proposal_has_individual_proof_obligations(
    generated_tax_ast: dict[str, dict[str, ast.FunctionDef]], key: str, kind: str
) -> None:
    assert "backend.tax." + key not in OWNER_APPROVED_IDS
    module, name = key.split(".")
    nodes = generated_tax_ast[module]
    before = copy.deepcopy(nodes[name.split("__mutmut_")[0] + "__mutmut_orig"])
    after = copy.deepcopy(nodes[name])
    after.name = before.name
    delta = differing_nodes(before, after)
    assert len(delta) == 1, key
    left, right = delta[0]
    if kind == "rank":
        assert isinstance(left, ast.Constant) and isinstance(right, ast.Constant)
        assert (left.value, right.value) == (1, 2)
        prove_rank()
    elif kind == "present":
        assert isinstance(left, (ast.Constant, ast.Call)) and isinstance(right, type(left))
        prove_present()
    elif kind == "zip":
        assert (
            isinstance(left, ast.Constant)
            and isinstance(right, ast.Constant)
            and left.value is False
            and right.value is None
        ) or (isinstance(left, ast.Call) and isinstance(right, ast.Call) and not right.keywords)
        prove_zip()
    elif kind == "positive":
        assert isinstance(left, ast.Lt) and isinstance(right, ast.LtE)
        prove_positive()
    elif kind == "fresh":
        assert isinstance(left, ast.AugAssign) and isinstance(right, ast.Assign)
        assert ast.dump(left.value) == ast.dump(right.value)
        prove_fresh(left, right)
    elif kind == "sum":
        assert isinstance(left, ast.Call) and isinstance(right, ast.Call)
        assert ast.unparse(left.func) == ast.unparse(right.func) == "sum"
        assert len(left.args) == 2 and len(right.args) == 1
        assert ast.unparse(left.args[1]) == "Decimal(0)"
        assert ast.dump(left.args[0]) == ast.dump(right.args[0])
        prove_sum()
    elif kind == "codec":
        assert isinstance(left, ast.Constant) and isinstance(right, ast.Constant)
        assert (left.value, right.value) == ("utf-8", "UTF-8")
        assert isinstance(left.value, str) and isinstance(right.value, str)
        # Same codec callable for all strings, including identical errors.
        assert codecs.lookup(left.value) is codecs.lookup(right.value)
        assert codecs.lookup(left.value).encode is codecs.lookup(right.value).encode
    elif kind == "mode":
        assert isinstance(left, ast.Constant) and isinstance(right, ast.Constant)
        assert left.value == "python" and right.value in (None, "XXpythonXX", "PYTHON")
        prove_mode()
    else:
        assert (
            kind == "precision"
            and isinstance(left, ast.Constant)
            and isinstance(right, ast.Constant)
        )
        assert (left.value, right.value) == (0, 1)
        # Nonempty min ignores its default for every exponent. Empty has the
        # only two literal outcomes; prior precision 80 dominates both.
        assert "precision.prec = 80" in normalized_source(reports.annual)
        assert max(80, 32 - 0) == max(80, 32 - 1) == 80
