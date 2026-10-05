"""R-08/R-10/GD-07: fail-closed AST guard for every authored Python source.

This scanner rejects prohibited SDK imports, execution member references,
reflection aliases, literal dictionary dispatch, and mutating HTTP endpoints.
Syntax/read failures and symbolic links are violations, never skipped evidence.
It is a source-control defense; OS-level network restrictions remain useful.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path

from backend.core.errors import ConfigurationError
from backend.core.execution_policy import (
    BANNED_ALPACA_FIELDS,
    BANNED_DYNAMIC_BUILTINS,
    BANNED_EXECUTION_METHODS,
    BANNED_IMPORT_FUNCTIONS,
    BANNED_ORDER_REQUESTS,
    GENERATED_DIRECTORIES,
    MONEY_ENDPOINT_WORDS,
    MUTATING_HTTP_METHODS,
    RESTRICTED_REFLECTION,
    TRANSFER_CREATION_WORDS,
)

_ENDPOINT = re.compile(
    r"^(?:https?://[^/]+)?/(?:[^/?#]+/)*"
    r"(?:orders|transfers?|wallets?|whitelists?|journals?|ach_relationships|"
    r"bank_accounts?|funding|deposits?|withdrawals?)(?:[/\?#]|$)",
    re.IGNORECASE,
)
_EXEMPT_RELATIVE_PATH = Path("backend/core/execution_policy.py")


@dataclass(frozen=True, slots=True)
class Violation:
    """GD-07: stable source location and reason for a startup-blocking finding."""

    path: Path
    line: int
    column: int
    message: str
    rule_id: str = "GD-07"

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: {self.rule_id} {self.message}"


def _prohibited_member(name: str) -> bool:
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    normalized = re.sub(r"([a-z])([A-Z])", r"\1_\2", normalized).lower()
    words = set(normalized.split("_"))
    mutates_money = bool(words & MONEY_ENDPOINT_WORDS) and bool(words & TRANSFER_CREATION_WORDS)
    return name in BANNED_EXECUTION_METHODS or name in BANNED_ORDER_REQUESTS or mutates_money


def _references(node: ast.AST, aliases: dict[str, frozenset[str]]) -> frozenset[str]:
    if isinstance(node, ast.Name):
        unverified = f"__unverified__.{node.id}" if node.id == "re" else node.id
        return aliases.get(node.id, frozenset({unverified}))
    if isinstance(node, ast.Attribute):
        return frozenset(f"{base}.{node.attr}" for base in _references(node.value, aliases))
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return frozenset(ref for item in node.elts for ref in _references(item, aliases))
    if isinstance(node, ast.IfExp):
        return _references(node.body, aliases) | _references(node.orelse, aliases)
    if isinstance(node, ast.Call):
        callable_refs = _references(node.func, aliases)
        reflection = any(
            ref.rsplit(".", 1)[-1] in {"attrgetter", "methodcaller"} for ref in callable_refs
        )
        if reflection:
            attributes = (
                node.args
                if any(ref.rsplit(".", 1)[-1] == "attrgetter" for ref in callable_refs)
                else node.args[:1]
            )
            return frozenset(
                f"__reflected__.{attribute.value}"
                for attribute in attributes
                if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str)
            )
        return frozenset(ref for ref in callable_refs if ref.startswith("__reflected__."))
    return frozenset()


def _literal_strings(node: ast.AST, values: dict[str, frozenset[str]]) -> frozenset[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return frozenset({node.value})
    if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
        return frozenset({node.value.decode("utf-8")})
    if isinstance(node, ast.Name):
        return values.get(node.id, frozenset())
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_strings(node.left, values)
        right = _literal_strings(node.right, values)
        return frozenset(a + b for a in left for b in right)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        templates = _literal_strings(node.left, values)
        arguments = (
            [_literal_strings(item, values) for item in node.right.elts]
            if isinstance(node.right, ast.Tuple)
            else [_literal_strings(node.right, values)]
        )
        result = templates
        for combination in product(*arguments):
            for template in templates:
                try:
                    operand: str | tuple[str, ...] = (
                        combination[0] if not isinstance(node.right, ast.Tuple) else combination
                    )
                    result |= {template % operand}
                except (TypeError, ValueError):
                    result |= {template}
        return result
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return frozenset(value for item in node.elts for value in _literal_strings(item, values))
    if isinstance(node, ast.Dict):
        return frozenset(value for item in node.values for value in _literal_strings(item, values))
    if isinstance(node, ast.JoinedStr):
        return frozenset(value for item in node.values for value in _literal_strings(item, values))
    if isinstance(node, ast.Subscript):
        source = _literal_strings(node.value, values)
        if isinstance(node.slice, ast.Slice):
            parts = (node.slice.lower, node.slice.upper, node.slice.step)
            indices = tuple(_integer_literal(part) for part in parts)
            if any(
                part is not None and index is None
                for part, index in zip(parts, indices, strict=True)
            ):
                return frozenset()
            selection = slice(*indices)
            return frozenset(value[selection] for value in source)
        index = _integer_literal(node.slice)
        if index is not None:
            return frozenset(value[index] for value in source if -len(value) <= index < len(value))
    if isinstance(node, ast.IfExp):
        return _literal_strings(node.body, values) | _literal_strings(node.orelse, values)
    if isinstance(node, ast.Call):
        # Calls cannot hide constant endpoint evidence by wrapping a literal in
        # str(), a normalization helper, or a format operation.
        result = frozenset(
            value
            for item in (*node.args, *(keyword.value for keyword in node.keywords))
            for value in _literal_strings(item, values)
        )
        if isinstance(node.func, ast.Attribute):
            templates = _literal_strings(node.func.value, values)
            result |= templates
            if (
                node.func.attr == "join"
                and node.args
                and isinstance(node.args[0], (ast.Tuple, ast.List))
            ):
                choices = [_literal_strings(item, values) for item in node.args[0].elts]
                for combination in product(*choices):
                    result |= {separator.join(combination) for separator in templates}
            if node.func.attr == "format":
                args = [_literal_strings(item, values) for item in node.args]
                kwargs = {
                    item.arg: _literal_strings(item.value, values)
                    for item in node.keywords
                    if item.arg is not None
                }
                choices = [*args, *kwargs.values()]
                combinations = 1
                for choice in choices:
                    combinations *= len(choice)
                if combinations > 256:
                    raise ValueError("constant formatting exceeds verifiable complexity")
                for combination in product(*choices):
                    positional = combination[: len(args)]
                    named = dict(zip(kwargs, combination[len(args) :], strict=True))
                    for template in templates:
                        try:
                            result |= {template.format(*positional, **named)}
                        except (KeyError, IndexError, ValueError, AttributeError):
                            # Keep the unformatted text; malformed constants may
                            # never erase the endpoint evidence collected above.
                            result |= {template}
        return result
    return frozenset()


def _integer_literal(node: ast.AST | None) -> int | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        value = node.operand.value
        if isinstance(value, int) and not isinstance(value, bool):
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
    return None


def _assignment_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for item in node.elts for name in _assignment_names(item))
    return ()


def _symbol_tables(
    nodes: tuple[ast.AST, ...],
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """GD-07: conservatively retain every alias even across reassignment/scope."""
    aliases: dict[str, frozenset[str]] = {}
    values: dict[str, frozenset[str]] = {}
    assignments: list[tuple[tuple[str, ...], ast.AST]] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            for item in node.names:
                local = item.asname or item.name.split(".")[0]
                qualified = item.name if item.asname else item.name.split(".")[0]
                aliases[local] = aliases.get(local, frozenset()) | {qualified}
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                local = item.asname or item.name
                qualified = f"{node.module}.{item.name}" if node.module else item.name
                aliases[local] = aliases.get(local, frozenset()) | {qualified}
        elif isinstance(node, ast.Assign):
            targets = tuple(name for target in node.targets for name in _assignment_names(target))
            assignments.append((targets, node.value))
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            assignments.append((_assignment_names(node.target), node.value))
        elif isinstance(node, ast.arg):
            # Function parameters may shadow imported modules. Retain unknown
            # provenance so a parameter named re cannot impersonate the module.
            aliases[node.arg] = aliases.get(node.arg, frozenset()) | {f"__unverified__.{node.arg}"}
    # A dependency can pass through every assignment; bounded iterations avoid
    # malicious alias cycles expanding attribute paths without a termination.
    for _iteration in range(len(assignments) + 1):
        changed = False
        for targets, value in assignments:
            refs = _references(value, aliases)
            strings = _literal_strings(value, values)
            for name in targets:
                old_refs = aliases.get(name, frozenset())
                old_values = values.get(name, frozenset())
                new_refs = old_refs | refs
                new_values = old_values | strings
                if new_refs != old_refs or new_values != old_values:
                    aliases[name], values[name] = new_refs, new_values
                    changed = True
        if not changed:
            break
    return aliases, values


def _dynamic_reference(ref: str) -> bool:
    leaf = ref.rsplit(".", 1)[-1]
    if leaf == "compile":
        return ref != "re.compile"
    return (
        leaf in BANNED_DYNAMIC_BUILTINS or leaf == "import_module" or ref in BANNED_IMPORT_FUNCTIONS
    )


def _reflection_reference(ref: str) -> bool:
    return ref.rsplit(".", 1)[-1] in RESTRICTED_REFLECTION


def _node_messages(
    node: ast.AST,
    aliases: dict[str, frozenset[str]],
    values: dict[str, frozenset[str]],
) -> tuple[str, ...]:
    messages: list[str] = []
    if isinstance(node, ast.Import):
        for item in node.names:
            if _prohibited_member(item.name.rsplit(".", 1)[-1]):
                messages.append(f"prohibited import: {item.name}")
    if isinstance(node, ast.ImportFrom):
        for item in node.names:
            if item.name in BANNED_ALPACA_FIELDS:
                messages.append(f"removed Alpaca field import: {item.name}")
            if item.name in BANNED_ORDER_REQUESTS or _prohibited_member(item.name):
                messages.append(f"prohibited import: {item.name}")
            qualified = f"{node.module}.{item.name}" if node.module else item.name
            if _dynamic_reference(qualified):
                messages.append(f"prohibited dynamic import: {qualified}")
        if any(item.name == "*" for item in node.names):
            messages.append("wildcard import prevents verification of execution aliases")
    if isinstance(node, ast.Attribute) and _prohibited_member(node.attr):
        messages.append(f"prohibited execution member: {node.attr}")
    if isinstance(node, ast.Attribute) and node.attr in BANNED_ALPACA_FIELDS:
        messages.append(f"removed Alpaca field read: {node.attr}")
    if isinstance(node, (ast.Name, ast.Attribute)):
        for ref in sorted(_references(node, aliases)):
            if _dynamic_reference(ref):
                messages.append(f"prohibited dynamic code reference: {ref}")
            if isinstance(node, ast.Name) and _prohibited_member(ref.rsplit(".", 1)[-1]):
                messages.append(f"prohibited execution alias: {ref}")
    if isinstance(node, ast.Subscript):
        for key in sorted(_literal_strings(node.slice, values)):
            if key in BANNED_ALPACA_FIELDS:
                messages.append(f"removed Alpaca field dictionary read: {key}")
            if (
                _prohibited_member(key)
                or key in BANNED_DYNAMIC_BUILTINS
                or key in RESTRICTED_REFLECTION
                or key == "import_module"
            ):
                messages.append(f"prohibited reflective dictionary key: {key}")
    if isinstance(node, ast.Call):
        refs = _references(node.func, aliases)
        if any(ref.rsplit(".", 1)[-1] in {"get", "pop", "setdefault"} for ref in refs):
            keys = (*node.args[:1], *(item.value for item in node.keywords if item.arg == "key"))
            for argument in keys:
                for name in _literal_strings(argument, values):
                    if name in BANNED_ALPACA_FIELDS:
                        messages.append(f"removed Alpaca field dictionary lookup: {name}")
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "pop", "setdefault"}:
            bases = _references(node.func.value, aliases)
            vars_dictionary = (
                isinstance(node.func.value, ast.Call)
                and isinstance(node.func.value.func, ast.Name)
                and node.func.value.func.id == "vars"
            )
            if vars_dictionary or any(
                "__dict__" in ref or ref in {"builtins", "__builtins__"} for ref in bases
            ):
                for argument in node.args[:1]:
                    for name in _literal_strings(argument, values):
                        if (
                            _prohibited_member(name)
                            or name in BANNED_DYNAMIC_BUILTINS
                            or name in RESTRICTED_REFLECTION
                        ):
                            messages.append(f"prohibited reflective dictionary lookup: {name}")
        if isinstance(node.func, ast.Subscript):
            dictionary_refs = _references(node.func.value, aliases)
            if not _literal_strings(node.func.slice, values) and any(
                "__dict__" in ref or ref in {"__builtins__", "builtins"} for ref in dictionary_refs
            ):
                messages.append("dynamic reflective dictionary dispatch cannot be verified")
        if any(_reflection_reference(ref) for ref in refs):
            operator_reflection = any(
                ref.rsplit(".", 1)[-1] in {"attrgetter", "methodcaller"} for ref in refs
            )
            bound_dunder = any(
                ref.rsplit(".", 1)[-1] in {"__getattribute__", "__setattr__"}
                and not ref.startswith("object.")
                for ref in refs
            )
            name_index = 0 if bound_dunder or operator_reflection else 1
            name_node: ast.AST | None = (
                node.args[name_index] if len(node.args) > name_index else None
            )
            if name_node is None:
                name_node = next((item.value for item in node.keywords if item.arg == "name"), None)
            name_nodes = (
                node.args
                if any(ref.rsplit(".", 1)[-1] == "attrgetter" for ref in refs)
                else [name_node]
            )
            for attribute_node in name_nodes:
                if not isinstance(attribute_node, ast.Constant) or not isinstance(
                    attribute_node.value, str
                ):
                    messages.append("reflection attribute name must be a literal string")
                elif any(
                    _prohibited_member(part)
                    or part in BANNED_ALPACA_FIELDS
                    or part in BANNED_DYNAMIC_BUILTINS
                    or part in RESTRICTED_REFLECTION
                    or part == "import_module"
                    for part in attribute_node.value.split(".")
                ):
                    messages.append(f"prohibited reflection attribute: {attribute_node.value}")
        call_strings = frozenset(
            value
            for child in (*node.args, *(keyword.value for keyword in node.keywords))
            for value in _literal_strings(child, values)
        )
        endpoint_present = any(_ENDPOINT.match(value) for value in call_strings)
        method_present = any(
            value.upper() in MUTATING_HTTP_METHODS for value in call_strings
        ) or any(
            ref.rsplit(".", 1)[-1].lstrip("_").upper() in MUTATING_HTTP_METHODS for ref in refs
        )
        if endpoint_present and method_present:
            messages.append("mutating HTTP request targets an order or money-movement endpoint")
    return tuple(dict.fromkeys(messages))


def _location(path: Path, node: ast.AST, message: str) -> Violation:
    if isinstance(node, (ast.expr, ast.stmt, ast.arg, ast.keyword)):
        return Violation(path, node.lineno, node.col_offset + 1, message)
    return Violation(path, 1, 1, message)


def scan_file(path: Path) -> tuple[Violation, ...]:
    """GD-07/R-02: parse one file, returning violations for unreadable/invalid source."""
    try:
        if path.is_symlink():
            return (
                Violation(path, 1, 1, "symbolic source link cannot establish authored provenance"),
            )
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        nodes = tuple(ast.walk(tree))
        aliases, values = _symbol_tables(nodes)
        findings = {
            _location(path, node, message)
            for node in nodes
            for message in _node_messages(node, aliases, values)
        }
        # Conservative file-wide evidence also catches mutation requests built
        # through separate assignments and transport.send(request). A file that
        # reads order history may not also contain a mutating method declaration.
        endpoint_nodes = tuple(
            node
            for node in nodes
            if isinstance(node, ast.expr)
            and any(_ENDPOINT.match(value) for value in _literal_strings(node, values))
        )
        mutation_present = any(
            isinstance(node, ast.expr)
            and any(
                value.upper() in MUTATING_HTTP_METHODS for value in _literal_strings(node, values)
            )
            or isinstance(node, ast.Attribute)
            and node.attr.lstrip("_").upper() in MUTATING_HTTP_METHODS
            for node in nodes
        )
        if endpoint_nodes and mutation_present:
            findings.add(
                _location(
                    path,
                    endpoint_nodes[0],
                    "order/money endpoint and mutating HTTP method coexist in authored source",
                )
            )
        return tuple(sorted(findings, key=lambda item: (item.line, item.column, item.message)))
    except Exception as error:
        return (Violation(path, 1, 1, f"source cannot be verified: {type(error).__name__}"),)


def scan_project(root: Path) -> tuple[Violation, ...]:
    """GD-07: scan all authored .py, rejecting links/escapes and unreadable paths.

    Only the exact constants module is exempt among authored Python files.
    Generated directory exclusions are explicit in execution_policy.py.
    """
    findings: list[Violation] = []
    try:
        if root.is_symlink() or not root.is_dir():
            return (Violation(root, 1, 1, "source root must be a real directory"),)
        source_root = root.resolve(strict=True)
        pending = [source_root]
        while pending:
            directory = pending.pop()
            for path in sorted(directory.iterdir()):
                if path.is_symlink():
                    findings.append(Violation(path, 1, 1, "symbolic project link is prohibited"))
                    continue
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(source_root):
                    findings.append(Violation(path, 1, 1, "source path escapes the project root"))
                elif path.is_dir():
                    if path.name not in GENERATED_DIRECTORIES and not path.name.endswith(
                        ".egg-info"
                    ):
                        pending.append(path)
                elif (
                    path.suffix == ".py" and path.relative_to(source_root) != _EXEMPT_RELATIVE_PATH
                ):
                    findings.extend(scan_file(path))
    except Exception as error:
        findings.append(
            Violation(root, 1, 1, f"project cannot be verified: {type(error).__name__}")
        )
    return tuple(
        sorted(findings, key=lambda item: (str(item.path), item.line, item.column, item.message))
    )


def require_safe_sources(root: Path) -> None:
    """GD-07/R-02: refuse startup when any authored source violates the policy."""
    findings = scan_project(root)
    if findings:
        raise ConfigurationError(
            "GD-07 authored-source safety check failed:\n" + "\n".join(map(str, findings))
        )


def main() -> int:
    """GD-07: command-line check for CI, pre-commit, and operator verification."""
    parser = argparse.ArgumentParser(description="Verify GD-07 read-only authored Python sources")
    parser.add_argument("root", type=Path, nargs="?", default=Path.cwd())
    arguments = parser.parse_args()
    findings = scan_project(arguments.root)
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    print("GD-07 authored-source scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
