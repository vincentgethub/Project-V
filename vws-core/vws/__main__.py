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
    ops = commands.add_parser("ops").add_subparsers(dest="operation", required=True)
    attest = ops.add_parser("attest")
    attest.add_argument("item")
    attest.add_argument("--operator", required=True)
    panic = ops.add_parser("panic")
    panic.add_argument("--operator", required=True)
    panic.add_argument("--reason", default="Operator emergency halt")
    for operation in ("apply-config", "ack-config"):
        ops.add_parser(operation).add_argument("--operator", required=True)
    ops.add_parser("backup")
    ops.add_parser("migrate").add_argument("--operator", required=True)
    ops.add_parser("audit-dependencies").add_argument("--operator", required=True)
    restore = ops.add_parser("restore-test")
    restore.add_argument("--file", type=Path, required=True)
    ops.add_parser("show-backup-key")
    ops.add_parser("rotate-secret").add_argument("name")
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
        # Progress never imports network/keyring service composition.
        from backend.security.secrets import KeyringSecretStore
        from vws import security_cli as security

        store = KeyringSecretStore()
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
        if args.command == "doctor" and selected_env is None:
            selected_env = security.PROJECT / ".env"
        context = security.open_context(
            selected_env,
            for_panic=args.command == "ops" and args.operation == "panic",
            store=store,
        )
        try:
            if args.command == "doctor":
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
            elif args.operation == "attest":
                attestation = context.ops.attest(security.attest_item(args.item), args.operator)
                print(f"{attestation.status}: {attestation.item} {attestation.recorded_at}")
            elif args.operation == "panic":
                panic_result = context.ops.panic(
                    args.operator, args.reason, mode=context.settings.execution_mode
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
