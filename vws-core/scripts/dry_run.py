"""GD-08: single-symbol offline acceptance CLI with no real ledger writes."""

import argparse
import asyncio

from backend.agents.offline_run import offline_run
from backend.core.errors import SafetyError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", required=True, metavar="SYMBOL")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if not args.offline:
        print("UNVERIFIED: connected dry run awaits Stage F provider composition; use --offline.")
        return 2
    try:
        result = asyncio.run(offline_run(args.dry_run))
    except SafetyError as exc:
        print(f"Offline gate failed: {type(exc).__name__}")
        return 1
    print("SYNTHETIC OFFLINE ACCEPTANCE - RAM ledger; MANUAL; paper; sentiment off.")
    for card, preview in zip(result.cards, result.previews, strict=True):
        print(card)
        print(preview)
    for rule in result.veto_ids:
        print(f"VETO: {rule}")
    print(
        f"Cards: {len(result.cards)}; LLM calls: {result.llm_calls}; ledger verified: {result.ledger_verified}"
    )
    return 0 if result.cards and not result.veto_ids else 1


if __name__ == "__main__":
    raise SystemExit(main())
