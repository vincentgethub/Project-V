"""OPS-06: certify only complete killed/type-caught mutmut results."""

import re
import sys
from pathlib import Path

from backend.core.errors import DataIntegrityError

_LINE = re.compile(r"\s*([A-Za-z0-9_.$]+): (.+)\Z")


def require_complete_results(text: str) -> int:
    if not isinstance(text, str) or not text.strip() or len(text) > 20_000_000:
        raise DataIntegrityError("OPS-06: mutation results unavailable")
    seen: set[str] = set()
    for line in text.splitlines():
        item = _LINE.fullmatch(line)
        if item is None or item[1] in seen or item[2] not in {"killed", "caught by type check"}:
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
        print(f"Verified killed/type-caught mutants: {count}")
        return 0
    except Exception:
        print("Mutation gate FAIL: missing, surviving, malformed or unverified results.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
