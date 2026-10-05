"""PG-05: print owner progress without loading secrets or constructing clients."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from backend.core.errors import SafetyError
from vws.progress import read_progress


def main(argv: Sequence[str] | None = None) -> int:
    """PG-05/R-07: available host commands are explicit and network-free."""
    parser = argparse.ArgumentParser(prog="python -m vws")
    parser.add_argument("command", choices=("progress",))
    parser.parse_args(argv)
    try:
        sys.stdout.write(read_progress())
        return 0
    except SafetyError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
