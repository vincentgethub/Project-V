"""PG-01..05: bounded owner progress text for terminal and private chat."""

from __future__ import annotations

import re
from pathlib import Path

from backend.core.errors import DataIntegrityError

SECTIONS = (
    "Where things stand",
    "What works now",
    "What's being built next",
    "Waiting on you",
    "Not checked yet",
    "Try this next",
    "Safety status",
    "Suggestions",
)


def read_progress(path: Path | None = None) -> str:
    """PG-01/PG-03: fail visibly if the owner page is missing or malformed."""
    source = Path(__file__).resolve().parents[1] / "docs/PROGRESS.md" if path is None else path
    try:
        text = source.read_text(encoding="utf-8-sig")
        if not text.strip() or len(text.splitlines()) > 60 or len(text) > 12_000:
            raise DataIntegrityError("PG-01: progress page must be nonempty and at most 60 lines")
        headings = tuple(
            line.removeprefix("## ") for line in text.splitlines() if line.startswith("## ")
        )
        if headings != SECTIONS or "Last updated:" not in text:
            raise DataIntegrityError("PG-02/PG-04: progress page sections or date are missing")
        if re.search(r"\b(?:R|CRO|CMP|DAT|GD|FA|AX|SEC|PG|WZ)-\d+\b", text):
            raise DataIntegrityError("PG-03: owner progress page must use plain words")
        return text
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("PG-01: progress page could not be read") from None


def private_progress_text(path: Path | None = None) -> str:
    """Latest PG-05: full page; bot enforces allowlist/rate limits/masking.

    This static owner document contains no account state or secrets. Dynamic
    state must be rendered by the later bot through its masked presentation.
    """
    return read_progress(path)


def require_progress_update(changed_files: tuple[str, ...]) -> None:
    """PG-04: a stage code/config change requires the owner's page in that commit."""
    if not isinstance(changed_files, tuple) or any(
        not isinstance(name, str) for name in changed_files
    ):
        raise DataIntegrityError("PG-04: changed file inventory is invalid")
    names = tuple(name.replace("\\", "/") for name in changed_files)
    code_changed = any(name.endswith((".py", ".yaml", ".yml", ".toml")) for name in names)
    if code_changed and not any(name.endswith("docs/PROGRESS.md") for name in names):
        raise DataIntegrityError("PG-04: code changed without updating docs/PROGRESS.md")
