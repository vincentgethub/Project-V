"""PG-01..05: owner page is bounded, truthful, accessible and stage-updated."""

from pathlib import Path

import pytest

from backend.core.errors import DataIntegrityError
from vws.__main__ import main
from vws.progress import private_progress_text, read_progress, require_progress_update


def test_PG_01_PG_05_actual_page_is_plain_and_cli_prints_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = read_progress()
    assert len(text.splitlines()) <= 60
    assert main(("progress",)) == 0
    captured = capsys.readouterr()
    assert captured.out == text and captured.err == ""
    assert "Suggestions" in text


def test_PG_05_private_display_contains_only_specified_sections() -> None:
    text = private_progress_text()
    for heading in ("Where things stand", "Waiting on you", "Safety status"):
        assert heading in text
    for heading in ("What works now", "What's being built next", "Not checked yet", "Suggestions"):
        assert heading not in text


@pytest.mark.parametrize(
    "change",
    ["empty", "too_long", "missing_section", "wrong_order", "requirement_id", "missing_date"],
)
def test_PG_01_PG_03_malformed_owner_page_is_rejected(tmp_path: Path, change: str) -> None:
    text = read_progress()
    if change == "empty":
        text = ""
    elif change == "too_long":
        text += "\n" * 61
    elif change == "missing_section":
        text = text.replace("## Suggestions", "Ideas")
    elif change == "wrong_order":
        text = text.replace("## Waiting on you", "## Safety status")
    elif change == "requirement_id":
        text += "\nSEC-01\n"
    else:
        text = text.replace("Last updated:", "Updated")
    path = tmp_path / "progress.md"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        read_progress(path)


def test_PG_01_missing_page_is_a_typed_error(tmp_path: Path) -> None:
    with pytest.raises(DataIntegrityError):
        read_progress(tmp_path / "missing.md")


def test_PG_04_stage_commit_with_code_requires_progress_change() -> None:
    with pytest.raises(DataIntegrityError):
        require_progress_update(("backend/risk/risk_cro.py",))
    require_progress_update(("backend/risk/risk_cro.py", "docs/PROGRESS.md"))
    require_progress_update(("README.md",))
    require_progress_update(("vws-core\\backend\\data\\news.py", "vws-core\\docs\\PROGRESS.md"))


def test_PG_05_bad_page_cli_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import vws.__main__ as cli

    def failed() -> str:
        raise DataIntegrityError("progress page is unavailable")

    monkeypatch.setattr(cli, "read_progress", failed)
    assert main(("progress",)) == 1
    assert "progress page is unavailable" in capsys.readouterr().err
