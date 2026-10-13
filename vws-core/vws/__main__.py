"""PG-05: print owner progress without loading secrets or constructing clients."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from backend.core.errors import SafetyError
from backend.core.logging import redact
from vws.progress import read_progress


def main(argv: Sequence[str] | None = None) -> int:
    """PG-05/SEC: host security actions require explicit named commands."""
    parser = argparse.ArgumentParser(prog="python -m vws")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--healthcheck", action="store_true")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("progress")
    commands.add_parser("doctor")
    commands.add_parser("start")
    setup_command = commands.add_parser("setup")
    setup_command.add_argument("--section", choices=("telegram", "alpaca", "watchlist", "risk"))
    replay_command = commands.add_parser("replay")
    replay_command.add_argument("--start", type=date.fromisoformat, required=True)
    replay_command.add_argument("--end", type=date.fromisoformat, required=True)
    replay_command.add_argument("--symbols", nargs="+")
    replay_command.add_argument("--offline-fixtures", action="store_true")
    replay_command.add_argument("--history", type=Path, default=Path("data/history"))
    replay_command.add_argument("--reports", type=Path, default=Path("data/reports"))
    replay_command.add_argument("--cache", type=Path, default=Path("data/cache/ind"))
    replay_command.add_argument("--initial-equity")
    replay_command.add_argument("--checking-balance")
    replay_command.add_argument("--workers", type=int)
    profiles = commands.add_parser("profile").add_subparsers(
        dest="profile_operation", required=True
    )
    for operation in ("scan", "replay"):
        profile = profiles.add_parser(operation)
        profile.add_argument("--end", type=date.fromisoformat, required=True)
        profile.add_argument("--symbols", nargs="+")
        profile.add_argument("--offline-fixtures", action="store_true")
        profile.add_argument("--history", type=Path, default=Path("data/history"))
        profile.add_argument("--output", type=Path, default=Path("data/profiles"))
        if operation == "replay":
            profile.add_argument("--start", type=date.fromisoformat, required=True)
            profile.add_argument("--initial-equity")
            profile.add_argument("--checking-balance")
            profile.add_argument("--workers", type=int)
    validation = commands.add_parser("validate").add_subparsers(
        dest="validation_operation", required=True
    )
    for name in ("register", "walkforward", "final"):
        command = validation.add_parser(name)
        command.add_argument("--history", type=Path, default=Path("data/history"))
        command.add_argument("--initial-equity", required=True)
        command.add_argument("--checking-balance", required=True)
        command.add_argument("--workers", type=int, default=1)
        if name != "register":
            command.add_argument("--family", required=True)
    tax = commands.add_parser("tax").add_subparsers(dest="tax_operation", required=True)
    tax_report = tax.add_parser("report")
    tax_report.add_argument("--year", type=int, required=True)
    tax_report.add_argument("--account", default="all")
    tax_report.add_argument("--simulate", action="store_true")
    tax_lots = tax.add_parser("import-lots")
    tax_lots.add_argument("--file", type=Path, required=True)
    tax_reconcile = tax.add_parser("reconcile")
    tax_reconcile.add_argument("--year", type=int, required=True)
    tax_reconcile.add_argument("--1099b", dest="official", type=Path, required=True)
    tax_reconcile.add_argument("--mapping", type=Path, default=Path("config/1099b_columns.yaml"))
    journal = commands.add_parser("journal").add_subparsers(dest="journal_operation", required=True)
    journal.add_parser("export")
    journal.add_parser("recent").add_argument("--count", type=int, default=10)
    journal.add_parser("regret").add_argument("proposal_id")
    commands.add_parser("lessons").add_subparsers(
        dest="lessons_operation", required=True
    ).add_parser("mine")
    commands.add_parser("events").add_subparsers(dest="events_operation", required=True).add_parser(
        "refresh-schedules"
    )
    report_parser = commands.add_parser("report").add_subparsers(
        dest="report_operation", required=True
    )
    report_parser.add_parser("monthly").add_argument("--month", required=True)
    ops = commands.add_parser("ops").add_subparsers(dest="operation", required=True)
    attest = ops.add_parser("attest")
    attest.add_argument("item")
    attest.add_argument("--operator", required=True)
    panic = ops.add_parser("panic")
    panic.add_argument("--operator", required=True)
    panic.add_argument("--reason", default="Operator emergency halt")
    for operation in ("apply-config", "ack-config"):
        ops.add_parser(operation).add_argument("--operator", required=True)
    for operation in ("resume-auto", "enable-live", "disable-live"):
        ops.add_parser(operation).add_argument("--operator", required=True)
    ops.add_parser("backup")
    ops.add_parser("migrate").add_argument("--operator", required=True)
    ops.add_parser("audit-dependencies").add_argument("--operator", required=True)
    ops.add_parser("drill").add_argument("--operator", required=True)
    restore = ops.add_parser("restore-test")
    restore.add_argument("--file", type=Path, required=True)
    ops.add_parser("show-backup-key")
    ops.add_parser("rotate-secret").add_argument("name")
    secrets = ops.add_parser("secrets").add_subparsers(dest="secret_operation", required=True)
    secrets.add_parser("set").add_argument("name")
    playbook = ops.add_parser("playbook").add_subparsers(dest="playbook_operation", required=True)
    enable = playbook.add_parser("enable")
    enable.add_argument("name")
    enable.add_argument("--operator", required=True)
    ledger = commands.add_parser("ledger").add_subparsers(dest="operation", required=True)
    verify = ledger.add_parser("verify-anchor")
    verify.add_argument("--seq", type=int)
    verify.add_argument("--hash")
    verify.add_argument("--file", type=Path)
    args = parser.parse_args(argv)
    if args.healthcheck and (args.command is not None or args.env_file is not None):
        parser.error("--healthcheck runs alone, without configuration or service access")
    if not args.healthcheck and args.command is None:
        parser.error("a command is required")
    try:
        if args.healthcheck:
            from backend.core.clock import SystemClock
            from backend.ops.process import heartbeat_is_fresh

            data = Path(__file__).resolve().parents[1] / "data"
            return int(
                not heartbeat_is_fresh(
                    data / "runtime-heartbeat.json", data / "runtime.lock", SystemClock()
                )
            )
        if args.command == "progress":
            sys.stdout.write(read_progress())
            return 0
        if args.command == "start":
            from vws.runtime_cli import execute as start_execute

            asyncio.run(start_execute(args.env_file))
            return 0
        if args.command == "setup":
            from vws.setup_cli import execute as setup_execute

            setup_result = asyncio.run(setup_execute(args.section, args.env_file))
            return 0 if setup_result.applied else 1
        if args.command == "replay":
            from vws.replay_cli import execute

            execute(
                args.start,
                args.end,
                None if args.symbols is None else tuple(args.symbols),
                project=Path(__file__).resolve().parents[1],
                history_root=args.history,
                report_root=args.reports,
                cache_root=args.cache,
                offline_fixtures=args.offline_fixtures,
                env_file=args.env_file,
                initial_equity=args.initial_equity,
                checking_balance=args.checking_balance,
                workers=args.workers,
            )
            return 0
        if args.command == "profile":
            from vws.profile_cli import execute as profile_execute

            profile_execute(
                args.profile_operation,
                end=args.end,
                project=Path(__file__).resolve().parents[1],
                output_root=args.output,
                history_root=args.history,
                offline_fixtures=args.offline_fixtures,
                symbols=None if args.symbols is None else tuple(args.symbols),
                env_file=args.env_file,
                start=getattr(args, "start", None),
                workers=getattr(args, "workers", None),
                initial_equity=getattr(args, "initial_equity", None),
                checking_balance=getattr(args, "checking_balance", None),
            )
            return 0
        # Progress never imports network/keyring service composition.
        from backend.security.secrets import KeyringSecretStore, SecretStore
        from vws import security_cli as security
        from vws.host_config import LocalLedgerLocator

        store: SecretStore
        try:
            store = KeyringSecretStore()
        except Exception:
            if args.command != "ops" or args.operation not in {"panic", "disable-live"}:
                raise
            store = LocalLedgerLocator()
        if args.command == "ops" and args.operation == "drill":
            from vws.drill_cli import execute as drill_execute

            print(asyncio.run(drill_execute(security.PROJECT, args.operator, args.env_file, store)))
            return 0
        if args.command == "ops" and args.operation == "migrate":
            from vws.migrate_cli import execute as migrate_execute

            migration = migrate_execute(args.operator, args.env_file, store)
            print(
                f"Schema {migration.source_version} -> {migration.target_version}; applied: {migration.applied}"
            )
            if migration.backup_path is not None:
                print(f"Verified encrypted backup: {migration.backup_path}")
            return 0
        selected_env = args.env_file
        if (
            selected_env is None
            and args.command == "ops"
            and args.operation == "panic"
            and (security.PROJECT / ".env").is_file()
        ):
            selected_env = security.PROJECT / ".env"
        if selected_env is None and (
            args.command in {"doctor", "tax", "journal", "report", "lessons", "events"}
            or (
                args.command == "ops"
                and args.operation
                in {"resume-auto", "enable-live", "disable-live", "playbook", "secrets"}
            )
        ):
            selected_env = security.PROJECT / ".env"
        context = security.open_context(
            selected_env,
            for_panic=args.command == "ops" and args.operation == "panic",
            for_downgrade=args.command == "ops" and args.operation == "disable-live",
            store=store,
        )
        try:
            if args.command == "validate":
                from vws.validation_cli import execute as validation_execute

                phrase = (
                    input("Type RUN HOLDOUT " + args.family + ": ")
                    if args.validation_operation == "final"
                    else ""
                )
                validation_execute(
                    context,
                    security.PROJECT,
                    args.validation_operation,
                    history_root=args.history,
                    initial_equity=args.initial_equity,
                    checking_balance=args.checking_balance,
                    family=getattr(args, "family", None),
                    workers=args.workers,
                    phrase=phrase,
                )
                return 0
            if args.command == "journal" and args.journal_operation != "export":
                from vws.realtime_cli import recent, regret

                print(
                    recent(context, security.PROJECT, args.count)
                    if args.journal_operation == "recent"
                    else regret(context, security.PROJECT, args.proposal_id)
                )
            elif args.command == "lessons":
                from vws.realtime_cli import service

                print(service(context, security.PROJECT).mine())
            elif args.command == "events":
                from vws.realtime_cli import refresh_schedules

                asyncio.run(refresh_schedules(context, security.PROJECT))
            elif args.command in {"journal", "report"}:
                from vws.extras_cli import export_journal, export_monthly

                path = (
                    export_journal(context, security.PROJECT)
                    if args.command == "journal"
                    else export_monthly(context, security.PROJECT, args.month)
                )
                print(f"Local {args.command} export: {path}")
            elif args.command == "tax":
                from vws.tax_cli import reconcile_broker, report

                if args.tax_operation == "import-lots":
                    from backend.tax.imports import import_marked_lots
                    from backend.tax.models import NOTICE

                    lots = import_marked_lots(
                        context.ledger,
                        args.file,
                        "PAPER" if context.settings.paper_trading else "LIVE",
                    )
                    print(f"Recorded {len(lots)} owner-marked external lots for sale review.")
                    print(NOTICE)
                elif args.tax_operation == "report":
                    totals, directory = report(
                        context, security.PROJECT, args.year, args.account, args.simulate
                    )
                    print(totals.notice)
                    print(
                        f"{'SIMULATED - NOT FOR FILING' if args.simulate else 'LIVE - ESTIMATE'}: {directory}"
                    )
                else:
                    directory, text = reconcile_broker(
                        context, security.PROJECT, args.year, args.official, args.mapping
                    )
                    print(text)
                    print(f"1099-B reconciliation: {directory}")
            elif args.command == "doctor":
                result = asyncio.run(security.doctor_result(context, store))
                for line in result.lines():
                    print(line)
                return result.exit_code
            elif args.command == "ledger":
                if args.file is not None:
                    if args.seq is not None or args.hash is not None:
                        raise SafetyError("Choose an anchor file or seq/hash together")
                    anchors = context.anchors.verify_file(args.file)
                    print(f"Verified {len(anchors)} ledger anchors.")
                elif args.seq is not None and args.hash is not None:
                    print(context.anchors.verify(args.seq, args.hash).message())
                else:
                    raise SafetyError("Anchor verification requires --file or --seq and --hash")
            elif args.operation in {"resume-auto", "enable-live", "disable-live"}:
                from vws.execution_cli import execute as mode_execute

                asyncio.run(mode_execute(context, store, args.operation, args.operator))
            elif args.operation == "playbook":
                from vws.extras_cli import enable_playbook

                enable_playbook(context, args.name, args.operator)
                print("Playbook enabled by the host operator; all entry checks still apply.")
            elif args.operation == "secrets":
                print(security.rotate_secret(context, args.name, store))
            elif args.operation == "attest":
                attestation = context.ops.attest(security.attest_item(args.item), args.operator)
                print(f"{attestation.status}: {attestation.item} {attestation.recorded_at}")
            elif args.operation == "panic":
                from vws.execution_cli import panic_cancel

                mode = context.emergency_mode or context.settings.execution_mode
                panic_result = context.ops.panic(
                    args.operator,
                    args.reason,
                    mode=mode,
                    cancel_unfilled=(lambda: asyncio.run(panic_cancel(context, store)))
                    if mode in {"AUTO_PAPER", "AUTO_LIVE"}
                    else None,
                    notify=lambda text: asyncio.run(security.panic_notify(context, store, text)),
                    read_activities=lambda since: asyncio.run(
                        security.panic_activities(context, store, since)
                    ),
                )
                print(f"Local state: {panic_result.state}")
                for activity in panic_result.recent_activity:
                    print(str(redact(activity)))
                if not panic_result.recent_activity:
                    print("UNVERIFIED: recent broker activities; inspect the broker dashboard.")
                for step in panic_result.revoke_checklist:
                    print(step)
                for failed in panic_result.failed_steps:
                    print("UNVERIFIED emergency step: " + failed)
            elif args.operation == "apply-config":
                context.drift.apply(context.config_hash(), args.operator)
                print("Effective configuration applied; audit event recorded.")
            elif args.operation == "ack-config":
                context.drift.ack(context.config_hash(), args.operator)
                print("Configuration drift acknowledged on the host.")
            elif args.operation == "rotate-secret":
                print(security.rotate_secret(context, args.name, store))
            elif args.operation == "audit-dependencies":
                from backend.ops.dependency_audit import audit

                counts = audit(security.PROJECT, context.ledger, args.operator)
                print("PASS: both current dependency locks audited; dated proof recorded.")
                for name, count in counts.items():
                    print(f"{name}: {count} active pins checked")
            else:
                backup = security.backups(context, store)
                if args.operation == "backup":
                    print(backup.create().path)
                elif args.operation == "restore-test":
                    restore_result = backup.restore_test(args.file)
                    print(
                        f"PASS: encrypted restore, ledger seq {restore_result.seq}, sha256 {restore_result.plaintext_sha256}"
                    )
                elif args.operation == "show-backup-key":
                    print(
                        "Save this recovery key in your password manager. Losing it prevents restores."
                    )
                    print(backup.show_key_once().get_secret_value())
        finally:
            context.engine.dispose()
        return 0
    except KeyboardInterrupt:
        print("Cancelled; setup restores prior configuration and keyring entries.", file=sys.stderr)
        return 130
    except SafetyError as exc:
        print(
            ("RED: " if args.command == "doctor" else "") + str(redact(str(exc))), file=sys.stderr
        )
        if args.command == "doctor":
            print(
                "Fix: Run setup, check the private configuration, and verify the ledger before retrying.",
                file=sys.stderr,
            )
        return 1
    except Exception as exc:
        print(
            f"Security command failed ({type(exc).__name__}); no secret details printed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
