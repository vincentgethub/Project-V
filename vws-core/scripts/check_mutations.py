"""OPS-06: certify only complete killed/type-caught mutmut results."""

import json
import re
import sys
from pathlib import Path

from backend.core.errors import DataIntegrityError

_LINE = re.compile(r"\s*([A-Za-z0-9_.$]+): (.+)\Z")
OWNER_APPROVED_IDS = frozenset(
    {
        "backend.tax.lots.xǁWashSaleMatcherǁ_available_slices__mutmut_4",
        "backend.tax.reports.x__csv__mutmut_18",
        "backend.tax.reports.x__cell__mutmut_6",
        "backend.tax.accounting.x_build_tax_book__mutmut_104",
        "backend.tax.reports.x_save_report__mutmut_74",
        "backend.tax.accounting.x_build_tax_book__mutmut_78",
    }
)


def approved_equivalents(path: Path | None = None) -> frozenset[str]:
    """OPS-06: only the owner's six individually approved IDs may survive."""
    source = path or Path(__file__).resolve().parents[1] / "config/tax-equivalent-mutants.json"
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        entries = data["entries"]
        ids = [row["id"] for row in entries]
        if (
            data["schema_version"] != 1
            or len(ids) != len(set(ids))
            or len(ids) != 6
            or frozenset(ids) != OWNER_APPROVED_IDS
            or any(
                row["approved_by"] != "owner" or row["approved_on"] != "2026-10-16"
                for row in entries
            )
        ):
            raise ValueError("unapproved entry")
        return frozenset(ids)
    except Exception:
        raise DataIntegrityError(
            "OPS-06: individual mutation approvals cannot be verified"
        ) from None


def require_complete_results(text: str) -> int:
    if not isinstance(text, str) or not text.strip() or len(text) > 20_000_000:
        raise DataIntegrityError("OPS-06: mutation results unavailable")
    seen: set[str] = set()
    approved = {"m_" + key.encode("utf-8").hex() for key in approved_equivalents()}
    for line in text.splitlines():
        item = _LINE.fullmatch(line)
        if (
            item is None
            or item[1] in seen
            or (
                item[2] not in {"killed", "caught by type check"}
                and not (item[2] == "survived" and item[1] in approved)
            )
        ):
            raise DataIntegrityError(
                "OPS-06: mutation results contain surviving or unverified cases"
            )
        seen.add(item[1])
    return len(seen)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.check_mutations MUTMUT_RESULTS_FILE")
        return 2
    try:
        count = require_complete_results(Path(sys.argv[1]).read_text(encoding="utf-8"))
        print(f"Verified processed mutants (individual owner approvals only): {count}")
        return 0
    except Exception:
        print("Mutation gate FAIL: missing, surviving, malformed or unverified results.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
