"""Amendment06: planted self-modification and lesson auto-apply must fail."""

from pathlib import Path

import pytest

from backend.core.source_guard import scan_file, scan_project


@pytest.mark.parametrize(
    "source",
    [
        "from backend.ops.apply_config import setup_application as save\nsave(proposal)",
        "import backend.ops.apply_config as writer\nwriter.setup_application(proposal)",
        "drift.apply(operator='automatic', config_hash=proposal['hash'])",
        "registrations.register(proposal['variant'])",
        "modes.enable_live(proposal)",
    ],
)
def test_LP_07_indirect_auto_apply_and_registration_forbidden(tmp_path: Path, source: str) -> None:
    directory = tmp_path / "learning"
    directory.mkdir()
    target = directory / "proposals.py"
    target.write_text(source, encoding="utf-8")
    assert any(row.rule_id == "SELF-WRITE" for row in scan_file(target))


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path\nPath(__file__).write_text('new code')",
        "from pathlib import Path\np=Path(__file__).parent/'other.py'\np.write_bytes(b'code')",
        "from pathlib import Path\np=Path('config/config.yaml')\nq=p\nq.write_text(proposal)",
        "open('config/variants.yaml','w').write(proposal)",
        "open('.env','a').write(proposal)",
        "Path('config/fees.yaml').open(mode='r+')",
        "Path('backend/agents/scanner.py').unlink()",
        "Path('data/tmp').replace('config/config.yaml')",
        "import shutil\nshutil.copyfile('data/proposals/1.json','config/config.yaml')",
        "import os\nos.open('config/variants.yaml',os.O_WRONLY)",
        "open('.env',mode='w')",
        "p=Path('data')\np=p/'another'\np.write_text('unbounded alias')",
        "Path('operator-risk.yaml').write_text('weakened risk')",
        "Path('deploy/windows_start.ps1').write_text('code')",
    ],
)
def test_planted_runtime_self_write_or_lesson_apply_fails(tmp_path: Path, source: str) -> None:
    path = tmp_path / "planted.py"
    path.write_text(source, encoding="utf-8")
    assert any(item.rule_id == "SELF-WRITE" for item in scan_file(path))


@pytest.mark.parametrize(
    "source",
    [
        "Path('config/config.yaml').read_text()",
        "open('.env','r')",
        "Path('data/proposals/1.json').write_text('proposal only')",
        "Path('docs/PROGRESS.md').write_text('suggestion only')",
    ],
)
def test_public_reads_and_specified_artifact_writes_are_allowed(
    tmp_path: Path, source: str
) -> None:
    path = tmp_path / "ordinary.py"
    path.write_text(source, encoding="utf-8")
    assert not scan_file(path)


def test_config_writer_exception_requires_trusted_full_project_path(tmp_path: Path) -> None:
    source = "Path('config/config.yaml').write_text('validated settings')"
    path = tmp_path / "setup.py"
    path.write_text(source, encoding="utf-8")
    assert scan_file(path) and scan_project(tmp_path)
    path.unlink()
    trusted = tmp_path / "vws" / "setup.py"
    trusted.parent.mkdir()
    trusted.write_text(source, encoding="utf-8")
    assert not scan_project(tmp_path)


@pytest.mark.parametrize(
    "source",
    [
        "Path(__file__).write_text('code')",
        "Path('backend/agents/scanner.py').write_text('code')",
        "Path('prompts/news_sentiment.md').write_text('instructions')",
    ],
)
def test_trusted_setup_can_never_change_source_or_prompts(tmp_path: Path, source: str) -> None:
    path = tmp_path / "vws" / "setup.py"
    path.parent.mkdir()
    path.write_text(source, encoding="utf-8")
    assert any(item.rule_id == "SELF-WRITE" for item in scan_project(tmp_path))


def test_test_basename_does_not_exempt_production_self_modification(tmp_path: Path) -> None:
    path = tmp_path / "test_malicious.py"
    path.write_text("Path(__file__).write_text('code')", encoding="utf-8")
    assert any(item.rule_id == "SELF-WRITE" for item in scan_file(path))


def test_build_compiler_allowed_only_two_lock_outputs_and_never_runtime_import(
    tmp_path: Path,
) -> None:
    compiler = tmp_path / "scripts" / "compile_locks.py"
    compiler.parent.mkdir()
    compiler.write_text(
        "from pathlib import Path\np=Path(__file__).resolve().parents[1]/'requirements.lock'\np.write_text('compiled hashes')",
        encoding="utf-8",
    )
    assert scan_file(compiler) and not scan_project(tmp_path)
    compiler.write_text("Path(__file__).write_text('code')", encoding="utf-8")
    assert scan_project(tmp_path)
    runtime = tmp_path / "runtime.py"
    runtime.write_text("from scripts.compile_locks import main\nmain()", encoding="utf-8")
    assert scan_file(runtime)
