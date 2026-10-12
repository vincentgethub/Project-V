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
    ALLOWED_EXECUTOR_NAMES,
    BANNED_ALPACA_FIELDS,
    BANNED_DYNAMIC_BUILTINS,
    BANNED_EXECUTION_METHODS,
    BANNED_IMPORT_FUNCTIONS,
    BANNED_LLM_TOOL_FIELDS,
    BANNED_ORDER_REQUESTS,
    BANNED_TLS_MEMBERS,
    DIRECT_HTTP_CALLS,
    EXECUTOR_RELATIVE_PATH,
    GENERATED_DIRECTORIES,
    HTTP_CLIENT_TYPES,
    HTTP_URL_PATTERN,
    INBOUND_NETWORK_CALLS,
    ISOLATED_ORDER_CLASSES,
    MONEY_ENDPOINT_WORDS,
    MUTATING_HTTP_METHODS,
    ORDER_HTTP_FACTORY_NAMES,
    PRIVATE_LLM_FIELDS,
    PRIVATE_LLM_MODELS,
    RESTRICTED_REFLECTION,
    TRANSFER_CREATION_WORDS,
)
from backend.security.write_guard import runtime_write_nodes

_ENDPOINT = re.compile(
    r"^(?:https?://[^/]+)?/(?:[^/?#]+/)*"
    r"(?:orders|transfers?|wallets?|whitelists?|journals?|ach_relationships|"
    r"bank_accounts?|funding|deposits?|withdrawals?)(?:[/\?#]|$)",
    re.IGNORECASE,
)
_EXEMPT_RELATIVE_PATH = Path("backend/core/execution_policy.py")
_HTTP_FACTORY_PATH = Path("backend/net/http.py")
_CONFIG_SUFFIXES = frozenset({".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".env"})
_HTTP_LITERAL = re.compile(HTTP_URL_PATTERN, re.IGNORECASE)


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
    return (
        name in BANNED_EXECUTION_METHODS
        or name in BANNED_ORDER_REQUESTS
        or name in ISOLATED_ORDER_CLASSES
        or mutates_money
    )


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


def _scoped_tables(
    tree: ast.Module,
) -> dict[
    ast.AST,
    tuple[
        dict[str, frozenset[str]],
        dict[str, frozenset[str]],
        dict[str, ast.AST],
        set[str],
    ],
]:
    """GD-07: propagate aliases within lexical scopes and their ancestors.

    Separate functions cannot share local bindings. Treating them as one scope
    can fabricate recursive strings from unrelated cryptographic operations.
    Ancestor bindings remain conservative across local reassignments/shadowing.
    """
    scope_nodes: dict[ast.AST, list[ast.AST]] = {tree: []}
    parents: dict[ast.AST, ast.AST] = {}
    scopes: dict[ast.AST, ast.AST] = {}

    def visit(node: ast.AST, scope: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            parents[node] = scope
            scope = node
            scope_nodes[scope] = []
        scopes[node] = scope
        scope_nodes[scope].append(node)
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, tree)
    scoped_nodes: dict[ast.AST, tuple[ast.AST, ...]] = {}
    tables = {}
    for scope, own_nodes in scope_nodes.items():
        ancestors = scoped_nodes[parents[scope]] if scope in parents else ()
        combined = (*ancestors, *own_nodes)
        scoped_nodes[scope] = combined
        aliases, values = _symbol_tables(combined)
        assignments, private_names = _security_tables(combined)
        tables[scope] = (aliases, values, assignments, private_names)
    return {node: tables[scope] for node, scope in scopes.items()}


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
    *,
    executor: bool = False,
) -> tuple[str, ...]:
    messages: list[str] = []

    def prohibited(name: str) -> bool:
        return _prohibited_member(name) and not (executor and name in ALLOWED_EXECUTOR_NAMES)

    if isinstance(node, ast.Import):
        for item in node.names:
            if prohibited(item.name.rsplit(".", 1)[-1]):
                messages.append(f"prohibited import: {item.name}")
    if isinstance(node, ast.ImportFrom):
        for item in node.names:
            if item.name in BANNED_ALPACA_FIELDS:
                messages.append(f"removed Alpaca field import: {item.name}")
            if prohibited(item.name):
                messages.append(f"prohibited import: {item.name}")
            qualified = f"{node.module}.{item.name}" if node.module else item.name
            if _dynamic_reference(qualified):
                messages.append(f"prohibited dynamic import: {qualified}")
        if any(item.name == "*" for item in node.names):
            messages.append("wildcard import prevents verification of execution aliases")
    if isinstance(node, ast.Attribute) and prohibited(node.attr):
        messages.append(f"prohibited execution member: {node.attr}")
    if isinstance(node, ast.Attribute) and node.attr in BANNED_ALPACA_FIELDS:
        messages.append(f"removed Alpaca field read: {node.attr}")
    if isinstance(node, (ast.Name, ast.Attribute)):
        for ref in sorted(_references(node, aliases)):
            if _dynamic_reference(ref):
                messages.append(f"prohibited dynamic code reference: {ref}")
            if isinstance(node, ast.Name) and prohibited(ref.rsplit(".", 1)[-1]):
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


def _location(path: Path, node: ast.AST, message: str, rule_id: str = "GD-07") -> Violation:
    if isinstance(node, (ast.expr, ast.stmt, ast.arg, ast.keyword)):
        return Violation(path, node.lineno, node.col_offset + 1, message, rule_id)
    return Violation(path, 1, 1, message, rule_id)


def _security_tables(nodes: tuple[ast.AST, ...]) -> tuple[dict[str, ast.AST], set[str]]:
    """SEC-33/61: track literal option aliases and private payload provenance."""
    assignments: dict[str, ast.AST] = {}
    private_names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _assignment_names(target):
                    assignments[name] = node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            for name in _assignment_names(node.target):
                assignments[name] = node.value
        if isinstance(node, ast.arg) and node.annotation is not None:
            if any(
                isinstance(child, (ast.Name, ast.Attribute))
                and (child.id if isinstance(child, ast.Name) else child.attr) in PRIVATE_LLM_MODELS
                for child in ast.walk(node.annotation)
            ):
                private_names.add(node.arg)
    return assignments, private_names


def _resolve_node(node: ast.AST, assignments: dict[str, ast.AST]) -> ast.AST:
    visited: set[str] = set()
    while isinstance(node, ast.Name) and node.id in assignments and node.id not in visited:
        visited.add(node.id)
        node = assignments[node.id]
    return node


def _private_payload(
    node: ast.AST,
    assignments: dict[str, ast.AST],
    private_names: set[str],
    visited: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(node, ast.Name):
        if node.id in private_names or node.id.lower() in PRIVATE_LLM_FIELDS:
            return True
        if node.id in assignments and node.id not in visited:
            return _private_payload(
                assignments[node.id], assignments, private_names, visited | {node.id}
            )
    if isinstance(node, ast.Attribute) and node.attr.lower() in PRIVATE_LLM_FIELDS:
        return True
    if isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                if key.value.lower() in PRIVATE_LLM_FIELDS:
                    return True
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in PRIVATE_LLM_MODELS:
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr in PRIVATE_LLM_MODELS:
            return True
    return any(
        _private_payload(child, assignments, private_names, visited)
        for child in ast.iter_child_nodes(node)
    )


def _security_messages(
    node: ast.AST,
    aliases: dict[str, frozenset[str]],
    values: dict[str, frozenset[str]],
    assignments: dict[str, ast.AST],
    private_names: set[str],
    *,
    factory: bool,
    test_file: bool,
) -> tuple[tuple[str, str], ...]:
    messages: list[tuple[str, str]] = []
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.Return)):
        assigned = node.value
        if assigned is not None and not factory:
            if any(ref in DIRECT_HTTP_CALLS for ref in _references(assigned, aliases)):
                messages.append(("SEC-30", "direct HTTP aliases bypass the central factory"))
    if isinstance(node, ast.Attribute) and node.attr in BANNED_TLS_MEMBERS:
        messages.append(("SEC-33", "TLS verification bypass is prohibited"))
    if isinstance(node, ast.Name) and any(
        ref.rsplit(".", 1)[-1] in BANNED_TLS_MEMBERS for ref in _references(node, aliases)
    ):
        messages.append(("SEC-33", "TLS verification bypass alias is prohibited"))
    if (
        isinstance(node, ast.ClassDef)
        and not factory
        and any(
            ref in HTTP_CLIENT_TYPES for base in node.bases for ref in _references(base, aliases)
        )
    ):
        messages.append(("SEC-30", "HTTP client subclasses belong in the central HTTP factory"))
    if isinstance(node, ast.Call):
        refs = _references(node.func, aliases)
        if any(ref in DIRECT_HTTP_CALLS for ref in refs) and not factory:
            messages.append(("SEC-30", "direct HTTP creation or requests bypasses make_client"))
        if any(ref in INBOUND_NETWORK_CALLS for ref in refs):
            messages.append(("SEC-34", "inbound network server or bind is prohibited"))
        # Socket variables lose constructor provenance in the general alias
        # table; an explicit socket-style bind/listen call remains prohibited.
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"bind", "listen"}:
            if not any(ref.startswith("sqlalchemy.") for ref in refs):
                messages.append(("SEC-34", "inbound socket bind/listen is prohibited"))
        options = [(item.arg, item.value) for item in node.keywords if item.arg is not None]
        for item in node.keywords:
            if item.arg is None:
                expanded = _resolve_node(item.value, assignments)
                if isinstance(expanded, ast.Dict):
                    options.extend(
                        (key.value, value)
                        for key, value in zip(expanded.keys, expanded.values, strict=True)
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    )
        if any(ref in DIRECT_HTTP_CALLS for ref in refs):
            request_refs = refs - {
                "requests.Session",
                "requests.sessions.Session",
                "requests.session",
            }
            if request_refs and not any(key == "timeout" for key, _value in options):
                messages.append(("SEC-30", "HTTP calls require an explicit bounded timeout"))
        for key, value in options:
            resolved = _resolve_node(value, assignments)
            if (
                key in {"verify", "check_hostname"}
                and isinstance(resolved, ast.Constant)
                and resolved.value is False
            ):
                messages.append(("SEC-33", "TLS verification must never be disabled"))
            if key in BANNED_LLM_TOOL_FIELDS:
                messages.append(("SEC-61", "LLM tool/function execution fields are prohibited"))
            if key in {"messages", "prompt", "input"} and _private_payload(
                value, assignments, private_names
            ):
                messages.append(("SEC-61", "private account data cannot enter an LLM payload"))
        llm_call = any("completions.create" in ref or "responses.create" in ref for ref in refs)
        if llm_call and not any(key == "max_tokens" for key, _value in options):
            messages.append(("SEC-60", "every LLM request requires explicit max_tokens"))
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        assigned_value = node.value
        if assigned_value is not None:
            resolved = _resolve_node(assigned_value, assignments)
            if isinstance(resolved, ast.Constant) and resolved.value is False:
                for target in targets:
                    if isinstance(target, ast.Attribute) and target.attr == "check_hostname":
                        messages.append(
                            ("SEC-33", "TLS hostname verification must never be disabled")
                        )
                    if isinstance(target, ast.Subscript) and "verify" in _literal_strings(
                        target.slice, values
                    ):
                        messages.append(("SEC-33", "TLS verification must never be disabled"))
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        for match in _HTTP_LITERAL.finditer(node.value):
            host = match.group(1).split(":", 1)[0].lower()
            if not test_file or host not in {"localhost", "127.0.0.1", "["}:
                messages.append(
                    ("SEC-33", "unencrypted HTTP URL in code/configuration is prohibited")
                )
    return tuple(dict.fromkeys(messages))


def scan_file(
    path: Path,
    *,
    factory_path: Path | None = None,
    executor_path: Path | None = None,
    config_writer_path: Path | None = None,
    build_metadata_paths: frozenset[str] = frozenset(),
) -> tuple[Violation, ...]:
    """GD-07/R-02: parse one file, returning violations for unreadable/invalid source."""
    try:
        if path.is_symlink():
            return (
                Violation(path, 1, 1, "symbolic source link cannot establish authored provenance"),
            )
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        nodes = tuple(ast.walk(tree))
        tables = _scoped_tables(tree)
        factory = factory_path is not None and path.resolve() == factory_path.resolve()
        executor = executor_path is not None and path.resolve() == executor_path.resolve()
        test_file = path.name.startswith("test_") or path.name == "conftest.py"
        findings = {
            _location(path, node, message)
            for node in nodes
            for message in _node_messages(node, tables[node][0], tables[node][1], executor=executor)
        }
        findings.update(
            _location(path, node, message, rule_id)
            for node in nodes
            for rule_id, message in _security_messages(
                node,
                *tables[node],
                factory=factory,
                test_file=test_file,
            )
        )
        if not factory and not executor:
            for node in nodes:
                imported = (
                    tuple(item.name for item in node.names)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    else ()
                )
                referenced = tuple(
                    ref.rsplit(".", 1)[-1] for ref in _references(node, tables[node][0])
                )
                if any(name in ORDER_HTTP_FACTORY_NAMES for name in (*imported, *referenced)):
                    findings.add(
                        _location(
                            path,
                            node,
                            "order transport capability exists outside the isolated executor",
                            "AX-10",
                        )
                    )
        config_writer = (
            config_writer_path is not None and path.resolve() == config_writer_path.resolve()
        )
        self_write_test = (
            test_file and path.parent.name == "tests" and path.parent.parent.name == "backend"
        )
        if not self_write_test:
            findings.update(
                _location(
                    path, node, "runtime source/config modification is prohibited", "SELF-WRITE"
                )
                for node in runtime_write_nodes(
                    tree,
                    path,
                    allow_config_writes=config_writer,
                    build_metadata_paths=build_metadata_paths,
                )
            )
            for node in nodes:
                imports = (
                    tuple(alias.name for alias in node.names)
                    if isinstance(node, ast.Import)
                    else tuple((node.module or "") + "." + alias.name for alias in node.names)
                    if isinstance(node, ast.ImportFrom)
                    else ()
                )
                if any(
                    name == "scripts.compile_locks" or name.startswith("scripts.compile_locks.")
                    for name in imports
                ):
                    findings.add(
                        _location(
                            path,
                            node,
                            "hash-lock authoring compiler cannot be imported by runtime code",
                            "SELF-WRITE",
                        )
                    )
        # Conservative file-wide evidence also catches mutation requests built
        # through separate assignments and transport.send(request). A file that
        # reads order history may not also contain a mutating method declaration.
        endpoint_nodes = tuple(
            node
            for node in nodes
            if isinstance(node, ast.expr)
            and any(_ENDPOINT.match(value) for value in _literal_strings(node, tables[node][1]))
        )
        mutation_present = any(
            isinstance(node, ast.expr)
            and any(
                value.upper() in MUTATING_HTTP_METHODS
                for value in _literal_strings(node, tables[node][1])
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
                    relative = path.relative_to(source_root)
                    authorized_writer = relative in {
                        Path("vws/setup.py"),
                        Path("backend/ops/apply_config.py"),
                    }
                    findings.extend(
                        scan_file(
                            path,
                            factory_path=source_root / _HTTP_FACTORY_PATH,
                            executor_path=source_root / EXECUTOR_RELATIVE_PATH,
                            config_writer_path=path if authorized_writer else None,
                            build_metadata_paths=frozenset(
                                (source_root / name).resolve().as_posix()
                                for name in ("requirements.lock", "requirements-dev.lock")
                            )
                            if relative == Path("scripts/compile_locks.py")
                            else frozenset(),
                        )
                    )
                elif path.suffix in _CONFIG_SUFFIXES or path.name.startswith(".env"):
                    for number, line in enumerate(
                        path.read_text(encoding="utf-8-sig").splitlines(), 1
                    ):
                        if _HTTP_LITERAL.search(line):
                            findings.append(
                                Violation(
                                    path,
                                    number,
                                    1,
                                    "unencrypted HTTP URL in configuration is prohibited",
                                    "SEC-33",
                                )
                            )
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
