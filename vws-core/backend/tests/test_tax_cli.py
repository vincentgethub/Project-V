"""TX-07/09/10: actual CLI, synthetic account history and write-once exports."""

from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path
from shutil import copyfile

import pytest

from backend.core.config import Settings
from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import Side
from backend.ops.doctor import Check, DoctorResult
from backend.tax.accounting import build_tax_book
from backend.tax.models import NOTICE, SIMULATED, Environment
from backend.tax.service import managed_accounts
from backend.tax.storage import append_evidence, read_fills
from backend.tests.test_doctor import Store
from backend.tests.test_security_cli import (  # noqa: F401
    make_security_context,
    no_native_keyring,
)
from backend.tests.test_tax_accounting import fill
from vws import security_cli, tax_cli
from vws.__main__ import main
from vws.runtime_cli import compose


def install(ctx: security_cli.SecurityContext, project: Path, env: Environment = "PAPER") -> None:
    config = project / "config"
    config.mkdir(exist_ok=True)
    original = Path(__file__).resolve().parents[2] / "config"
    for name in (
        "instruments.csv",
        "etf_sector_weights.csv",
        "etf_theme_weights.csv",
        "substantially_identical.csv",
        "blackout_windows.csv",
    ):
        if (original / name).exists():
            copyfile(original / name, config / name)
    config.joinpath("accounts.yaml").write_text("accounts: []\n", encoding="utf-8")
    for number, side, days in [(1, Side.BUY, -100), (2, Side.SELL, 0)]:
        row = fill(number, side=side).model_copy(
            update={
                "symbol": "NVDA",
                "env": env,
                "ts": ctx.ledger.clock.now() + timedelta(days=days),
            }
        )
        append_evidence(
            ctx.ledger,
            "tax",
            env,
            "FILL",
            row.activity_id,
            row.payload_sha256,
            row.model_dump(mode="json"),
        )
    for kind in ("TAX_FULL_HISTORY_CAPTURED", "ACCOUNT_ACTIVITIES_CAPTURED"):
        ctx.ledger.append(
            SecurityEvent,
            kind=kind,
            detail={
                "account_id": "tax",
                "cohort": env,
                "until": ctx.ledger.clock.now().isoformat(),
            },
        )
    book = build_tax_book(
        read_fills(ctx.ledger, "tax", env, csv=False),
        managed_accounts(project, "tax"),
        InstrumentRegistry.from_csv(config),
        env,
    )
    ctx.ledger.append(
        SecurityEvent,
        kind="J_ACCOUNTING_VERIFIED",
        detail={
            "account_id": "tax",
            "cohort": env,
            "as_of": ctx.ledger.clock.now().isoformat(),
            "book_sha256": book.sha256,
        },
    )


def test_TX_07_actual_host_cli_exports_simulated_and_disposes(
    context: security_cli.SecurityContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install(context, tmp_path)
    monkeypatch.setattr(security_cli, "open_context", lambda *args, **kwargs: context)
    assert main(["tax", "report", "--year", "2026", "--simulate"]) == 0
    text = capsys.readouterr().out
    assert NOTICE in text and SIMULATED in text
    files = tuple((tmp_path / "data/tax/2026/PAPER").rglob("form8949.csv"))
    assert len(files) == 1 and SIMULATED in files[0].read_text(encoding="utf-8")
    assert main(["tax", "report", "--year", "2026"]) == 1
    assert "UNVERIFIED" in capsys.readouterr().err


def test_TX_09_live_authoritative_reconcile_output(
    context: security_cli.SecurityContext, tmp_path: Path
) -> None:
    install(context, tmp_path, "LIVE")
    mapping = Path(__file__).resolve().parents[2] / "config/1099b_columns.yaml"
    official = tmp_path / "1099b.csv"
    official.write_text(
        "symbol,date_sold,qty,proceeds,basis,wash_adjustment,term\nNVDA,2026-09-29,10,100,100,0,ST\n",
        encoding="utf-8",
    )
    destination, text = tax_cli.reconcile_broker(context, tmp_path, 2026, official, mapping)
    assert "LIVE" in destination.parts and NOTICE in text
    assert tax_cli.reconcile_broker(context, tmp_path, 2026, official, mapping)[0] == destination
    destination.write_text("corrupt", encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        tax_cli.reconcile_broker(context, tmp_path, 2026, official, mapping)


@pytest.mark.parametrize(
    "kind", ["none", "checkpoint", "future", "unreconciled", "stale_proof", "wrong_hash"]
)
def test_TX_cli_missing_history_does_not_export_empty_pass(
    context: security_cli.SecurityContext, tmp_path: Path, kind: str
) -> None:
    if kind != "none":
        context.ledger.append(
            SecurityEvent,
            kind="TAX_FULL_HISTORY_CAPTURED",
            detail={
                "account_id": "tax",
                "cohort": "PAPER",
                "until": context.ledger.clock.now().isoformat(),
            },
        )
    if kind == "future":
        context.ledger.append(
            SecurityEvent,
            kind="ACCOUNT_ACTIVITIES_CAPTURED",
            detail={
                "account_id": "tax",
                "cohort": "PAPER",
                "until": (context.ledger.clock.now() + timedelta(seconds=1)).isoformat(),
            },
        )
    if kind in {"unreconciled", "stale_proof", "wrong_hash"}:
        install(context, tmp_path)
        context.ledger.append(
            SecurityEvent,
            kind="ACCOUNT_ACTIVITIES_CAPTURED",
            detail={
                "account_id": "tax",
                "cohort": "PAPER",
                "until": context.ledger.clock.now().isoformat(),
            },
        )
        if kind != "unreconciled":
            context.ledger.append(
                SecurityEvent,
                kind="J_ACCOUNTING_VERIFIED",
                detail={
                    "account_id": "tax",
                    "cohort": "PAPER",
                    "as_of": (context.ledger.clock.now() - timedelta(seconds=31)).isoformat()
                    if kind == "stale_proof"
                    else context.ledger.clock.now().isoformat(),
                    "book_sha256": "f" * 64,
                },
            )
    with pytest.raises(DataIntegrityError):
        tax_cli.evidence(context, tmp_path, "PAPER")


@pytest.mark.asyncio
async def test_DAT_12_host_refuses_wrong_broker_fallback(
    context: security_cli.SecurityContext,
) -> None:
    context.settings = Settings.validated_copy(
        context.settings.model_copy(update={"broker_state_source": "MANUAL_CSV"})
    )
    doctor = DoctorResult(
        checks=(
            Check(
                name="fake",
                status="PASS",
                required=True,
                message="Synthetic only",
                fix="Synthetic only",
            ),
        )
    )
    async with AsyncExitStack() as resources:
        with pytest.raises(ConfigurationError, match="disabled by owner decision"):
            await compose(context, Store(), doctor, resources=resources)
