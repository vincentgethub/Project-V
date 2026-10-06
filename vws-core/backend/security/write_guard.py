"""Amendment06: static positive controls against runtime source/config writes.

This complements controlled output destinations. Tests may create fixtures;
only the trusted setup/apply-config modules may intentionally change settings.
"""

import ast
import posixpath
from pathlib import Path, PurePosixPath

_WRITERS = frozenset(
    {
        "write_text",
        "write_bytes",
        "unlink",
        "remove",
        "rmdir",
        "rmtree",
        "rename",
        "replace",
        "touch",
    }
)


def protected_output_path(value: str, *, allow_config_writes: bool = False) -> bool:
    normalized = value.replace("\\", "/").lower()
    parts = PurePosixPath(normalized).parts
    name = PurePosixPath(normalized).name
    source = (
        any(part in {"backend", "vws", "scripts", "prompts", "deploy", ".github"} for part in parts)
        or normalized.endswith(
            (".py", ".pyw", ".ps1", ".sh", ".bat", ".cmd", ".js", ".ts", ".tsx", ".jsx")
        )
        or name
        in {
            "agents.md",
            "pyproject.toml",
            "dockerfile",
            "docker-compose.yml",
            ".pre-commit-config.yaml",
            ".gitignore",
            ".dockerignore",
        }
        or name.startswith("requirements")
    )
    config = (
        "config" in parts
        or any(part.startswith(".env") for part in parts)
        or normalized.endswith((".yaml", ".yml", ".toml", ".cfg", ".ini"))
    )
    return source or (config and not allow_config_writes)


_protected = protected_output_path


def runtime_write_nodes(
    tree: ast.AST,
    source_path: Path,
    *,
    allow_config_writes: bool = False,
    build_metadata_paths: frozenset[str] = frozenset(),
) -> tuple[ast.AST, ...]:
    """Resolve known paths/aliases; unknown artifact paths need runtime checks.

    Resolve __file__ and ancestors so build metadata outside packages is not
    confused with protected source. No eval or execution is used.
    """
    nodes = tuple(ast.walk(tree))
    paths: dict[str, frozenset[str]] = {"__file__": frozenset({source_path.resolve().as_posix()})}

    def values(node: ast.AST) -> frozenset[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return frozenset({node.value})
        if isinstance(node, ast.Name):
            return paths.get(node.id, frozenset())
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
            left, right = values(node.left), values(node.right)
            if left and right:
                return frozenset(
                    posixpath.normpath(a + "/" + b) if isinstance(node.op, ast.Div) else a + b
                    for a in left
                    for b in right
                )
            return frozenset(a for a in left if _protected(a))
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            return frozenset(str(PurePosixPath(value).parent) for value in values(node.value))
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "parents"
            and isinstance(node.slice, ast.Constant)
            and type(node.slice.value) is int
            and 0 <= node.slice.value < 64
        ):
            result: set[str] = set()
            for value in values(node.value.value):
                parent = PurePosixPath(value)
                for _ in range(node.slice.value + 1):
                    parent = parent.parent
                result.add(str(parent))
            return frozenset(result)
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else ""
            )
            if name in {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "str"}:
                return values(node.args[0]) if node.args else frozenset()
            if isinstance(func, ast.Attribute) and name in {
                "resolve",
                "absolute",
                "as_posix",
                "joinpath",
            }:
                base = values(func.value)
                for arg in node.args:
                    tail = values(arg)
                    base = (
                        frozenset(posixpath.normpath(a + "/" + b) for a in base for b in tail)
                        if tail
                        else frozenset(a for a in base if _protected(a))
                    )
                return base
        return frozenset()

    def protected(node: ast.AST) -> bool:
        return any(
            value not in build_metadata_paths
            and _protected(value, allow_config_writes=allow_config_writes)
            for value in values(node)
        )

    for _pass in range(64):
        previous = dict(paths)
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                resolved = values(node.value)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and resolved:
                        paths[target.id] = paths.get(target.id, frozenset()) | resolved
        if paths == previous:
            break
        if sum(len(items) for items in paths.values()) > 4096:
            return (tree,)
    else:
        return (tree,)  # cyclic/unbounded path aliases cannot establish safety
    findings: list[ast.AST] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id
            if isinstance(func, ast.Name)
            else ""
        )
        write_target = func.value if isinstance(func, ast.Attribute) else None
        if name in _WRITERS and (
            (write_target is not None and protected(write_target))
            or any(protected(arg) for arg in node.args)
        ):
            findings.append(node)
        elif name in {"open", "fdopen"}:
            modes = [
                arg.value
                for arg in node.args[1:]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
            modes.extend(
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "mode"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            )
            flags = any(
                isinstance(child, ast.Attribute)
                and child.attr in {"O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"}
                for child in ast.walk(node)
            )
            writes = flags or any(any(char in mode for char in "wax+") for mode in modes)
            if writes and (
                (write_target is not None and protected(write_target))
                or (node.args and protected(node.args[0]))
            ):
                findings.append(node)
        elif (
            name in {"copy", "copy2", "copyfile", "copytree", "move"}
            and len(node.args) > 1
            and protected(node.args[1])
        ):
            findings.append(node)
    return tuple(findings)
