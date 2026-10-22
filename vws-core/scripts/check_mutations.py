"""OPS-06: certify only complete killed/type-caught mutmut results."""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from backend.core.errors import DataIntegrityError
from scripts.mutation_fingerprints import read_map

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


OWNER_APPROVED_FINGERPRINTS = {
    "backend.tax.lots.xǁWashSaleMatcherǁ_available_slices__mutmut_4": "sha256:03e878af83b1107da991aca8e46b60d1830e5450e51a9907658fcadd51115d2a",
    "backend.tax.reports.x__csv__mutmut_18": "sha256:e664601cf42744f626fdc8b979b3d519be756d417acf3529a6d9546f920c8716",
    "backend.tax.reports.x__cell__mutmut_6": "sha256:ccfcf6730c6edb7a496ea5a2e836d1e48cf456276237409523b0cd992aeb9540",
    "backend.tax.accounting.x_build_tax_book__mutmut_104": "sha256:fad23f41101190ab63612c04b4a6767a1679e10567aa31cbfb9a3a70802ddb19",
    "backend.tax.reports.x_save_report__mutmut_74": "sha256:27e17fe1411517ea3620bd0e048fde90f48ff8d4c4ecdf797056268cf518fe85",
    "backend.tax.accounting.x_build_tax_book__mutmut_78": "sha256:024ffda5a541aa5ac88d875d0655268261646e7bd418115eb6e954ef3c5a4fdd",
}


def approved_equivalents(path: Path | None = None) -> frozenset[str]:
    """OPS-06: only the owner's six individually approved fingerprints may survive."""
    source = path or Path(__file__).resolve().parents[1] / "config/tax-equivalent-mutants.json"
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        entries = data["entries"]
        ids = [row["id"] for row in entries]
        if (
            data["schema_version"] != 2
            or len(ids) != len(set(ids))
            or len(ids) != 6
            or frozenset(ids) != OWNER_APPROVED_IDS
            or any(
                OWNER_APPROVED_FINGERPRINTS.get(row["id"]) != row["fingerprint"] for row in entries
            )
            or any(
                row["approved_by"] != "owner" or row["approved_on"] != "2026-10-16"
                for row in entries
            )
        ):
            raise ValueError("unapproved entry")
        rows = read_map(Path(__file__).resolve().parents[1])
        current = {row["new_id"]: row["fingerprint"] for row in rows if row["new_id"]}
        multiplicity = Counter(current.values())
        if any(
            current.get(row["id"]) != row["fingerprint"] or multiplicity[row["fingerprint"]] != 1
            for row in entries
        ):
            raise ValueError("approved fingerprint moved or changed")
        return frozenset(
            key
            for key, fingerprint in current.items()
            if fingerprint in set(OWNER_APPROVED_FINGERPRINTS.values())
        )
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
