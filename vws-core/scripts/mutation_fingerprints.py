"""OPS-06: deterministic native mutation identities; no historical test results."""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import io
import json
import re
import tomllib
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from mutmut.mutation import file_mutation
from mutmut.mutation.mutators import mutation_operators
from mutmut.mutation.trampoline_templates import mangle_function_name
from mutmut.utils.format_utils import get_mutant_name

from backend.core.errors import DataIntegrityError
from scripts.mutation_inventory import EXPECTED_TOTAL

BASE_COMMIT_URL = (
    "https://github.com/vincentgethub/Project-V/commit/5dc9af896d3fec6bc8e1b38eb2159641a740b27a"
)
BASE_COMMIT = BASE_COMMIT_URL.rsplit("/", 1)[1]
MAP_PATH = "build/pass7/inventory-fingerprint-map.csv"
FIELDS = ("old_id", "new_id", "fingerprint", "old_line", "new_line")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DataIntegrityError("OPS-06 fingerprint: " + message)


def mutation_rows(filename: str, source: str) -> list[dict[str, Any]]:
    """Keep the native generator's outputs and ordering; tag the emitting operator."""
    operators: dict[tuple[int, int], str] = {}

    def tagged(operator: Any) -> Any:
        def wrapped(node: Any) -> Iterator[Any]:
            for candidate in operator(node):
                operators[id(node), id(candidate)] = operator.__name__
                yield candidate

        return wrapped

    with patch.object(
        file_mutation,
        "mutation_operators",
        [(kind, tagged(operator)) for kind, operator in mutation_operators],
    ):
        module, mutations, _, _ = file_mutation.create_mutations(filename, source)
    positions = MetadataWrapper(module, unsafe_skip_copy=True).resolve(PositionProvider)
    grouped: dict[Any, list[Any]] = defaultdict(list)
    for mutation in mutations:
        grouped[mutation.contained_by_top_level_function].append(mutation)
    functions: list[tuple[cst.FunctionDef, str | None]] = []
    for statement in module.body:
        if isinstance(statement, cst.FunctionDef):
            functions.append((statement, None))
        elif isinstance(statement, cst.ClassDef) and isinstance(statement.body, cst.IndentedBlock):
            functions.extend(
                (method, statement.name.value)
                for method in statement.body.body
                if isinstance(method, cst.FunctionDef)
            )
    rows: list[dict[str, Any]] = []
    lines = source.splitlines()
    for function, class_name in functions:
        name = function.name.value if class_name is None else class_name + "." + function.name.value
        for number, mutation in enumerate(grouped.get(function, ()), 1):
            position = positions[mutation.original_node]
            operator = operators[id(mutation.original_node), id(mutation.mutated_node)]
            mutated = module.code_for_node(mutation.mutated_node)
            payload = [
                filename,
                name,
                " ".join(lines[position.start.line - 1].split()),
                operator,
                mutated,
            ]
            canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            fingerprint = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            native_name = mangle_function_name(name=function.name.value, class_name=class_name)
            rows.append(
                {
                    "id": get_mutant_name(Path(filename), native_name + "__mutmut_" + str(number)),
                    "fingerprint": fingerprint,
                    "file": filename,
                    "function": name,
                    "line": position.start.line,
                    "end_line": position.end.line,
                    "operator": operator,
                    "payload": payload,
                    "original_node": module.code_for_node(mutation.original_node),
                    "mutated_text": mutated,
                }
            )
    require(len(rows) == len({row["id"] for row in rows}), "duplicate generated ID")
    return rows


def read_map(root: Path) -> list[dict[str, str]]:
    with (root / MAP_PATH).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(tuple(reader.fieldnames or ()) == FIELDS, "map columns")
        rows = list(reader)
    old = [row["old_id"] for row in rows if row["old_id"]]
    new = [row["new_id"] for row in rows if row["new_id"]]
    require(len(old) == len(set(old)) == 15457, "old map inventory")
    require(len(new) == len(set(new)) == EXPECTED_TOTAL, "new map inventory")
    require(
        all(re.fullmatch(r"sha256:[a-f0-9]{64}", row["fingerprint"]) is not None for row in rows),
        "fingerprint format",
    )
    return rows


def generate_map(root: Path, baseline: Path) -> tuple[bytes, dict[str, Any]]:
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mutmut"]
    old_config = tomllib.loads((baseline / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "mutmut"
    ]
    require(config == old_config, "mutation configuration changed")
    files: set[str] = set()
    for source in config["source_paths"]:
        path = root / source
        files.update(
            p.relative_to(root).as_posix()
            for p in (path.rglob("*.py") if path.is_dir() else (path,))
        )
    require(len(files) == 18, "configured file count")
    old_rows: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    changed_old: dict[str, set[int]] = {}
    changed_new: dict[str, set[int]] = {}
    hunks: dict[str, str] = {}
    for filename in sorted(files):
        before = (baseline / filename).read_text(encoding="utf-8")
        after = (root / filename).read_text(encoding="utf-8")
        old_rows.extend(mutation_rows(filename, before))
        new_rows.extend(mutation_rows(filename, after))
        old_changed: set[int] = set()
        new_changed: set[int] = set()
        for tag, a, b, c, d in difflib.SequenceMatcher(
            a=before.splitlines(), b=after.splitlines(), autojunk=False
        ).get_opcodes():
            if tag != "equal":
                old_changed.update(range(a + 1, b + 1))
                new_changed.update(range(c + 1, d + 1))
        changed_old[filename], changed_new[filename] = old_changed, new_changed
        hunks[filename] = "".join(
            difflib.unified_diff(
                before.splitlines(True),
                after.splitlines(True),
                fromfile="old/" + filename,
                tofile="new/" + filename,
            )
        )
    old_partition = json.loads(
        (baseline / "config/mutation-shards.json").read_text(encoding="utf-8")
    )
    require(
        {row["id"] for row in old_rows}
        == {key for job in old_partition["shards"] for key in job["ids"]},
        "baseline ID names",
    )
    require(len(old_rows) == 15457 and len(new_rows) == EXPECTED_TOTAL, "inventory totals")
    old_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    new_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in old_rows:
        old_groups[row["fingerprint"]].append(row)
    for row in new_rows:
        new_groups[row["fingerprint"]].append(row)
    mapped: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for fingerprint in sorted(old_groups.keys() | new_groups.keys()):
        before_group, after_group = old_groups[fingerprint], new_groups[fingerprint]
        if len(before_group) > 1 or len(after_group) > 1:
            duplicates.append({"fingerprint": fingerprint, "old": before_group, "new": after_group})
        for index in range(max(len(before_group), len(after_group))):
            old = before_group[index] if index < len(before_group) else None
            new = after_group[index] if index < len(after_group) else None
            mapped.append(
                {
                    "old_id": old["id"] if old else "",
                    "new_id": new["id"] if new else "",
                    "fingerprint": fingerprint,
                    "old_line": old["line"] if old else "",
                    "new_line": new["line"] if new else "",
                }
            )
            if old is None or new is None:
                record = dict(new or old or {})
                record["bucket"] = "NEW" if new else "GONE"
                changed = changed_new if new else changed_old
                require(
                    record["line"] in changed[record["file"]],
                    "NEW/GONE mutation on unchanged line: " + record["id"],
                )
                record["diff_hunk"] = hunks[record["file"]]
                unmatched.append(record)
    counts = {
        "MATCHED": sum(bool(row["old_id"] and row["new_id"]) for row in mapped),
        "NEW": sum(row["bucket"] == "NEW" for row in unmatched),
        "GONE": sum(row["bucket"] == "GONE" for row in unmatched),
    }
    require(
        counts["MATCHED"] + counts["NEW"] == EXPECTED_TOTAL
        and counts["MATCHED"] + counts["GONE"] == 15457,
        "bucket totals",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(mapped)
    return stream.getvalue().encode("utf-8"), {
        "base_commit": BASE_COMMIT,
        "counts": counts,
        "unmatched": unmatched,
        "duplicates": duplicates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    try:
        content, proof = generate_map(root, args.baseline)
        destination = root / MAP_PATH
        if args.check:
            require(destination.read_bytes() == content, "committed fingerprint map differs")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        print(
            "Fingerprint map PASS:",
            json.dumps(proof["counts"], sort_keys=True),
            "unchanged-line NEW/GONE: 0",
        )
        print("Fingerprint map SHA256:", hashlib.sha256(content).hexdigest())
        return 0
    except Exception:
        print(
            "Fingerprint map FAIL: changed identities, invalid inventory or unchanged-line NEW/GONE."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
