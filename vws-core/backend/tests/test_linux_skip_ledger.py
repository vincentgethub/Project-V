"""LP-50: every skip site is pinned with a written reason; no Windows-only skip remains."""

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

PINNED = {
    (
        "test_paper_integration.py",
        "UNVERIFIED: explicit paper integration credentials not supplied",
    ),
    (
        "test_paper_integration.py",
        "UNVERIFIED: paper keys absent from the native keyring for this explicit configuration",
    ),
    ("test_postgres.py", "UNVERIFIED: explicit disposable PostgreSQL URL not supplied"),
    ("test_tax_reports.py", "POSIX permission bits require a POSIX filesystem"),
    (
        "test_v_paper_cancel_integration.py",
        "UNVERIFIED: explicit paper config and existing canceled OTO/OCO broker UUIDs required",
    ),
    ("test_wash_sales.py", "Changing process local timezone requires POSIX tzset"),
}


def literal(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def skip_sites() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted(TESTS.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in {"skip", "skipif", "importorskip"}:
                continue
            reasons = [literal(arg) for arg in node.args] + [
                literal(keyword.value) for keyword in node.keywords if keyword.arg == "reason"
            ]
            found.add((path.name, next((r for r in reasons if r), "<NO REASON>")))
    return found


def test_LP50_every_remaining_skip_has_a_written_reason_and_none_is_windows_only() -> None:
    sites = skip_sites()
    assert not any("<NO REASON>" in reason for _file, reason in sites)
    assert not any("windows" in reason.lower() for _file, reason in sites)
    assert sites == PINNED
