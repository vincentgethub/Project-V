# Host operations

Stage S offline and host-command gates passed October 5, 2026, using synthetic
data and fake services. Connected commands need your explicit account
type and saved credentials. Examples below use `python` from the vws-core venv;
on Windows you can use `.venv\Scripts\python.exe`. Never paste secrets into chat.

## Current paper workflow

1. Read `python -m vws progress`; preview `python scripts/dry_run.py --dry-run NVDA --offline`.
   The preview uses RAM and synthetic data and sends nothing.
2. Connected startup awaits Stage H. Once configured, check `/status`, read the
   full card and Details, then Approve or Reject. Approval first rechecks fresh
   evidence and creates manual instructions; it places no order.
3. Place a paper LIMIT entry yourself in the broker dashboard. After filling,
   verify the correct whole-share STOP coverage and optional target/OCO there.
   Tap I placed it or Skip. That records your attribution only.
4. Read-only polling matches observed fills to tickets. Unmatched manual fills
   remain observed records. Inspect reconciliation warnings; never guess a stop.
5. Use `/halt REASON` for urgent entry shutdown once the bot is connected.
   Valid held exits and stop protection remain your responsibility in MANUAL.
   Ctrl-C stops the later host service; reset requires host investigation and RESET.
6. Rotate suspected secrets with the commands below, retain encrypted backups
   and compare ledger anchors. No current paper result authorizes live mode.

## Start, stop and current mode

Read `python -m vws progress`. The service `setup` and `start` commands arrive in
Stage H; private Telegram components are implemented in Stage F and tested
against fake HTTP. Your bot is not connected or running here. Current behavior is MANUAL,
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
token, and refuses polling in every mode without deleting the webhook.
Keep the bot in a confirmed private chat only.

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

## Data checks and existing database versions

Stage D adds shared read budgets, completed daily-bar caching, public headlines,
corporate-action evidence, earnings windows and manual CSV account reads.
Manual CSV is available only in MANUAL; it also needs fresh prices and explicit
account-restriction and pending-order evidence. Missing evidence refuses entries.
Confirmed earnings near a proposal block entries; estimated or unknown dates
show warnings. The account-type check halts on a reported CASH/MARGIN mismatch.

The current fresh schema is version 4. Normal startup refuses a version-2 or
version-3 database; never delete it or change its version number by hand. Stage H supplies
the explicit backup-first additive migration. Host `python -m vws ops panic --operator NAME --reason REASON` remains available for the exact compatible
version-2/version-3 schemas and persists HALTED without upgrading them. It does not certify
old or damaged ledger chains. An incompatible control schema is refused.

The real paper check is UNVERIFIED. After paper credentials exist, use
`python -m pytest -m integration --paper-integration-env-file PRIVATE_PAPER_CONFIG`.
This explicitly selected private file must bind MANUAL, paper keys and account
type. Default tests read neither real dotenv files nor native keyring secrets.
The integration reads an account and delayed SIP bars; it never submits orders.

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
Connected monitor composition is pending Stage H; an unexplained broker identity change
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

Monthly `ops drill` remains pending K. The weekly report now has event counts,
new numeric IDs, secret ages and the last drill, anchor verify, pip-audit and
restore test; missing evidence stays UNVERIFIED and the latest failure is kept. FYI auto
messages later describe actions rather than request approval. Read `/pnl` with
cash-flow-adjusted paper/live series kept separate; year end export, compare
with authoritative 1099-B, then give both to your preparer. Reports are unfinished.
Logs rotate daily with 30-day retention by default (7-365 allowed). Ledger, tax
and security evidence stay permanently, local plus encrypted backups. No telemetry.

## Reading the edge report and the verdict

`/edge` and `/report` are private, allowlisted and rate-limited. Their connected
startup arrives in H. They show the same saved proof, using the current amount
masking setting. Each weekly publication keeps JSON/CSV and an `outcomes_*.json`
proof with every recorded alert's fills, costs, R, daily price-bound MAE/MFE,
holding time and exit reason. Files are content-addressed and never overwritten.
The ledger binds their hashes to the account and paper/live cohort.

Approved, rejected, expired, pending and failed fresh checks are separate views.
CRO vetoes with positive shares have a shadow view. Fundamental subgroups overlap
the overall rows, so do not add those rows together. Unfilled limits are not
losses. Fewer than 30 resolved trades says "too few trades to judge". Missing
portfolio evidence is n/a. The CSV and plain-language report disclose costs,
source limitations, dividend handling and rough taxes. See docs/VALIDATION.md.

WORKING needs the specified sample, positive lower uncertainty bound and profit
factor. Replay also needs an out-of-sample, trial-adjusted validation result;
G's in-sample replay cannot supply that. Neither a grade nor the later readiness
verdict changes settings or unlocks live. The verdict, walk-forward/holdout,
portfolio overlays and exit variants arrive in V after K. Five healthy realtime
feed sessions from W are an additional prerequisite. No edge is established by
synthetic fixtures. Hypothetical/past results; not indicative of future returns.

Offline acceptance, without credentials, an owner database or network:

```powershell
.venv\Scripts\python.exe -m vws replay --start 2026-08-01 --end 2026-10-02 --symbols NVDA --offline-fixtures --workers 1
```

That command saves explicitly synthetic proof/report files and uses a separate
synthetic indicator cache. For observed history, supply a sealed `manifest.json`
with RAW/SPLIT/ALL data and a `filings_manifest.json` from the documented
`backend.data.history.seal_history` / `backend.data.frozen_filings.seal_filings`
host APIs. Both refuse overwrites. An empty filing manifest means unavailable,
not fundamentally sound. Do not regenerate missing files inside replay.
Example with explicit hypothetical cash/funding and a separately selected cache:

```powershell
.venv\Scripts\python.exe -m vws replay --start 2019-01-01 --end 2025-12-31 --symbols NVDA --history data/history/SEALED_SNAPSHOT --initial-equity 10000 --checking-balance 11500 --cache data/cache/ind/SEALED_SNAPSHOT
```

The amounts above are example assumptions, not your account balance. It reads
existing environment settings and only a dotenv file explicitly supplied with
the global `--env-file` option. It opens no owner database and makes no provider
or broker calls. A changed source under an existing indicator key is refused;
use the selected snapshot's separate cache. Keep backups before host migrations.
Use a cumulative report window from the first tracked alert when assembling the
weekly history source, so alerts still open after their first week are included.
