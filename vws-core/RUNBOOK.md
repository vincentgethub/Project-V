# Host operations

Stage S offline and host-command gates passed October 5, 2026, using synthetic
data and fake services. Connected commands need your explicit account
type and saved credentials. Examples below use `python` from the vws-core venv;
on Windows you can use `.venv\Scripts\python.exe`. Never paste secrets into chat.

## Start, stop and current mode

Read `python -m vws progress`. The service `setup` and `start` commands arrive in
Stage H; private Telegram cards arrive in Stage F. Current behavior is MANUAL,
paper by default, with no order executor. Ordinary stop uses Ctrl-C once the
service exists. To stop entries during an incident, use panic below.

Future host upgrades use `ops resume-auto --operator NAME` and the exact phrase
`RESUME`; live unlock uses `ops enable-live --operator NAME` and
`I UNDERSTAND THIS TRADES REAL MONEY`. These commands are Stage I work and are
not available now. Setup never upgrades modes. Telegram can only downgrade:
`/manual`, `/pause`, `/halt`; it never resets a halt or enables auto/live.

## Halt, panic and recovery

Run `python -m vws --env-file .env ops panic --operator NAME --reason "suspected compromise"`.
HALTED is saved locally before external callbacks. Panic works with the network
down and prints the revoke checklist. MANUAL has no cancellation or executor
import. Future AUTO wiring cancels only unfilled entries, keeps stop/target legs,
and lists 30 days of non-FILL activity and orders without a `vws-` client ID.
Panic never flattens holdings; inspect and decide that in the broker dashboard.

Explain the cause and verify current data, the ledger and old anchors before
resuming. The specified future host reset is `ops reset --operator NAME --reason
"..."`, with the exact phrase `RESET`; it is not available before its stage.
Daily-loss entry blocks expire at the next XNYS open. Drawdown/fault halts latch.
Use [docs/INCIDENT.md](docs/INCIDENT.md) for key leaks, a lost laptop or takeover.

## Secret rotation

Use `python -m vws --env-file .env ops rotate-secret NAME`; hidden input is
validated with a read-only Alpaca account, Telegram getMe or Plaid item/get
request before replacement. The old value survives failed validation. The
ledger stores a dated salted HMAC fingerprint, never the credential.
Run `python -m vws --env-file .env doctor` afterward. Unknown ages stay UNKNOWN;
the configured maximum age WARNs at 90 days by default (allowed range 30-365).

Telegram token: BotFather `/revoke` invalidates the old token immediately, then
rotate `TELEGRAM_BOT_TOKEN`, then doctor. BotFather `/setjoingroups` -> Disable
and `/setprivacy` -> Enable. A configured webhook is urgent, suggests a leaked
token, and refuses AUTO. Keep the bot in a confirmed private chat only.

Alpaca: dashboard -> API Keys -> Regenerate the affected pair; revoke from your
phone if the host is lost. Rotate the matching saved key and secret. Trading API
key scope controls and IP allowlisting remain UNVERIFIED; never probe funding.
Rotate Plaid credentials or remove the affected item, GitHub tokens and recovery
email credentials as appropriate. A Plaid access token uses native keyring only.

## Encrypted backup and verified restore

Use `ops show-backup-key` once and save the key immediately in a password manager.
Losing it means no restore is possible. The key lives in the native keyring;
the intentional one-time display is for you, never for logs or Telegram.
Run `python -m vws --env-file .env ops backup`; it creates only encrypted
`.vwsbak` output. The authenticated header binds version, UTC time and plaintext
SHA-256. SQLite uses a consistent in-memory image; above 256 MiB it refuses.
PostgreSQL backup tooling and scheduled backups arrive in Stage H.

Run `python -m vws --env-file .env ops restore-test --file PATH.vwsbak`.
It decrypts into private temporary storage, checks the plaintext SHA-256 and all
ledger chains, then removes the scratch copy and records dated success.
Changed bytes, a wrong key or an inconsistent digest refuse. The command tests
a restore; it does not replace your current ledger. Full recovery belongs on a
clean host, with a verified backup and key. Do not overwrite a suspect ledger.
You may keep encrypted copies off-box; never copy a plaintext database as backup.

## Independent ledger anchors and configuration drift

The evening digest will send `Ledger anchor · seq N · HASH` and optionally append
the full digest to ANCHOR_FILE_PATH on another device. Digest/weekly wiring is
pending its stage. Anchors bind the ordered prefix across every immutable table.
Each month compare an older saved Telegram/off-box anchor using
`python -m vws --env-file .env ledger verify-anchor --seq N --hash HASH`,
or `ledger verify-anchor --file PATH`. A mismatch is urgent; keep entries halted.
Successful verification records dated evidence. Keep old off-box anchors.

Before a monitor observes an intentional config change, run
`python -m vws --env-file .env ops apply-config --operator NAME`.
The effective non-secret config includes env policy and config.yaml,
instruments.csv, macro_events.csv and accounts.yaml. Unacknowledged drift alerts
urgently and pauses AUTO entries. A revert alone does not clear the pause.
Investigate first, then use `ops ack-config --operator NAME` on the host.
Monitor composition is pending Stage F; an unexplained broker identity change
already has a tested persistent HALT service. Legitimate rotation needs matching
SECRET_ROTATED evidence. Telegram cannot acknowledge config or upgrade a mode.

## Secure the host

Windows: dedicated standard user, BitLocker, Defender, automatic updates,
firewall enabled, and screen lock at five minutes or less. Keep Credential
Manager local-machine storage available. Doctor currently reads ACLs; broad
Everyone/Users/Authenticated Users read rights WARN. A world-writable DB refuses.
Disk-encryption, admin, Defender and firewall probes arrive in Stage H; unknown
results never count as a pass. Account settings are dated owner attestations.

VPS: dedicated vws user; SSH keys only; `PasswordAuthentication no` and
`PermitRootLogin no`; deny inbound except SSH with ufw; unattended-upgrades and
fail2ban. Private `.env` is 0600, data/logs/backups 0700, all owned by the run user.
Unsafe or unknown POSIX permissions refuse AUTO. No application inbound port,
webhook server, Docker ports, privileged container or Docker socket mount exists.

## Paper checklist, reports and later live unlock

Across four weeks, confirm paper/account binding, review data freshness and
WARNs, compare manual tickets with the paper dashboard, then review hypothetical
evaluation and paper reports. This is a checklist, not permission to enable AUTO.
Auto eligibility later needs at least 20 successful paper XNYS sessions with the
specified job evidence, its report, funding/tax stage, a recent drill, explicit
unlock, security prerequisites, ceilings and capital ramp. None is bypassed here.

Live security requires keyring-only secrets; live key age within the maximum;
items 1-7 attested within 365 days; private permissions; restore success within
30 days; anchor verify within 31 days; clean pip-audit within 7 days; empty
webhook and safe getMe group flags; a non-admin/non-root user; and active egress
guard. These unlock checks are future Stage I composition, not certified now.

Monthly `ops drill` and weekly security reporting are pending their stages. The
report must show counts/new numeric IDs, secret ages and last drill, anchor
verify, pip-audit and restore test; missing evidence stays UNVERIFIED. FYI auto
messages later describe actions rather than request approval. Read `/pnl` with
cash-flow-adjusted paper/live series kept separate; year end export, compare
with authoritative 1099-B, then give both to your preparer. Reports are unfinished.
Logs rotate daily with 30-day retention by default (7-365 allowed). Ledger, tax
and security evidence stay permanently, local plus encrypted backups. No telemetry.
