# Host operations

Stage S offline and host-command gates passed October 5, 2026, using synthetic
data and fake services. Connected commands need your explicit account
type and saved credentials. Examples below use `python` from the vws-core venv;
on Windows you can use `.venv\Scripts\python.exe`. Never paste secrets into chat.

## Current paper workflow

1. Read `python -m vws progress`; preview `python scripts/dry_run.py --dry-run NVDA --offline`.
   The preview uses RAM and synthetic data and sends nothing.
2. Run `python -m vws setup`, then `python -m vws doctor`, then `python -m vws start`.
   Required unverified checks refuse startup. Check `/status`, read the
   full card and Details, then Approve or Reject. Approval first rechecks fresh
   evidence and creates manual instructions; it places no order.
3. Place a paper LIMIT entry yourself in the broker dashboard. After filling,
   verify the correct whole-share STOP coverage and optional target/OCO there.
   Tap I placed it or Skip. That records your attribution only.
4. Read-only polling matches observed fills to tickets. Unmatched manual fills
   remain observed records. Inspect reconciliation warnings; never guess a stop.
5. Use `/halt REASON` for urgent entry shutdown once the bot is connected.
   Valid held exits and stop protection remain your responsibility in MANUAL.
   Ctrl-C stops the host service; reset requires host investigation and RESET.
6. Rotate suspected secrets with the commands below, retain encrypted backups
   and compare ledger anchors. No current paper result authorizes live mode.

## Start, stop and current mode

The owner declined manual CSV on October 8 2026. BROKER_STATE_SOURCE must stay
ALPACA. MANUAL_CSV refuses startup and doctor explains how to correct it.
Manual funding/state components refuse direct use before any file access.
The host evidence file was declined and not built. Amendment 02's manual-path
acceptance is DEFERRED by this owner decision; final guard checks are underway.

Read `python -m vws progress`. The implemented `setup`, `doctor` and `start`
commands passed the H offline acceptance gate; real services are unverified.
Your bot is not connected or running here. Current behavior is MANUAL, paper by
default. Stage I's isolated AUTO executor is under final offline verification.
Ordinary stop uses Ctrl-C; the host drains
admitted work and audits cleanup. To stop entries during an incident, use panic below.

Host AUTO resumes use `ops resume-auto --operator NAME` and the exact phrase
`RESUME`; live unlock uses `ops enable-live --operator NAME` and
`I UNDERSTAND THIS TRADES REAL MONEY`. Live remains locked until all K/V/W
prerequisites and recorded evidence pass. Setup never upgrades modes. Telegram can only downgrade:
`/manual`, `/pause`, `/halt`; it never resets a halt or enables auto/live.

## Halt, panic and recovery

Run `python -m vws --env-file .env ops panic --operator NAME --reason "suspected compromise"`.
HALTED is saved locally before external callbacks. Panic works with the network
down and prints the revoke checklist. MANUAL has no cancellation or executor
import. AUTO panic cancels only verified unfilled entries, keeps stop/target legs,
and attempts a private notice and 30-day non-FILL/unrecognized-order report.
Unavailable keyring, configuration or network steps are printed as UNVERIFIED;
the persisted local HALT remains. Unknown same-symbol orders or uncaptured fills
prevent overlapping sells. Inspect protection urgently in the broker dashboard.
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
Manual CSV broker state/funding is disabled by the latest owner decision,
including MANUAL mode and direct component use. No manual file is read.
Confirmed earnings near a proposal block entries; estimated or unknown dates
show warnings. The account-type check halts on a reported CASH/MARGIN mismatch.

The current fresh schema is version 6. Normal startup refuses older layouts;
never delete the database or change its version number by hand. Stage H/J supply
the explicit backup-first additive migration. Host `python -m vws ops panic --operator NAME --reason REASON` remains available for the exact compatible
version-2 through version-5 schemas and persists HALTED without upgrading them. It does not certify
old or damaged ledger chains. An incompatible control schema is refused.

The real paper check is UNVERIFIED. After paper credentials exist, use
`python -m pytest -m integration --paper-integration-env-file PRIVATE_PAPER_CONFIG`.
This explicitly selected private file must bind MANUAL, paper keys and account
type. Default tests read neither real dotenv files nor native keyring secrets.
The integration reads an account and delayed SIP bars; it never submits orders.

## Independent ledger anchors and configuration drift

Evening maintenance sends `Ledger anchor · seq N · HASH` and optionally appends
the full digest to ANCHOR_FILE_PATH on another device. Host wiring is tested
offline; real private delivery remains UNVERIFIED. Anchors bind the ordered
prefix across every immutable table.
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
Stage H supplies monitor composition; an unexplained broker identity change
has a tested persistent HALT service. Real connections remain UNVERIFIED. Legitimate rotation needs matching
SECRET_ROTATED evidence. Telegram cannot acknowledge config or upgrade a mode.

## Secure the host

Windows: dedicated standard user, BitLocker, Defender, automatic updates,
firewall enabled, and screen lock at five minutes or less. Keep Credential
Manager local-machine storage available. Doctor currently reads ACLs; broad
Everyone/Users/Authenticated Users read rights WARN. A world-writable DB refuses.
Doctor probes disk encryption, admin status, Defender and firewall without
changing them. Unknown results never count as a pass. Account settings are
dated owner attestations; they cannot be inferred from a successful API read.

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
guard. Stage I wires these named checks; actual owner/service evidence is still
UNVERIFIED. Stage V must also supply a recent READY verdict and W must supply at
least five healthy required-feed sessions. No CLI can silently waive a check.

Monthly `ops drill` remains pending K. The weekly report now has event counts,
new numeric IDs, secret ages and the last drill, anchor verify, pip-audit and
restore test; missing evidence stays UNVERIFIED and the latest failure is kept. FYI auto
messages later describe actions rather than request approval. Read `/pnl` with
cash-flow-adjusted paper/live series kept separate; year end export, compare
with authoritative 1099-B, then give both to your preparer. Reports are unfinished.
Logs use UTC daily dates, 10 MiB chunks and at most five archived chunks per day,
plus the active file; retention defaults to 30 days (7-365 allowed). This combines
OPS-08's size bound with later SEC-75's daily age retention. Ledger, tax
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

## Host startup, health and schema upgrades

Run setup, doctor, then start from the project folder. Startup reads the selected
private `.env` explicitly, uses the native secret store, binds paper identity,
verifies the ledger and sets SQLite WAL with a ten-second busy timeout. It holds
an OS file lock for its entire life. A second process refuses. Saved HALTED and
REDUCE_ONLY states persist; monitoring and held-exit warnings remain available.

`python -m vws --healthcheck` reads only the bounded UTC heartbeat and tests that
the OS lock is held. It never reads dotenv, keyring or the DB. Exit zero means a
recent runtime loop with scheduler/ledger/clock checks and verified notification
delivery, not a trading-readiness verdict. No inbound health server exists.
Failed urgent delivery stays pending, latches HALTED and stops heartbeat renewal.
An optional HTTPS dead-man URL is contacted only after successful jobs, through
the guarded HTTP factory. Three job failures or a missed daily scan alert privately.

For a known older SQLite schema, stop the runtime first and run:

```powershell
.venv\Scripts\python.exe -m vws ops migrate --operator "YOUR NAME"
.venv\Scripts\python.exe -m vws doctor
```

The current Stage J layout is version 6, adding cash-flow, daily-P&L and tax
evidence tables. The migration authenticates an encrypted online backup and its
scratch restore before additive DDL. Existing ledger rows and hashes are retained. Unknown layouts
or corrupt chains refuse. Do not manually alter `schema_meta` or delete rows.
If migration is refused, preserve the DB and report the precise failure.
Nightly backups restore into an isolated temporary directory to verify the chain;
retention prunes only authenticated owned archives. Save the recovery key when
setup displays it; a key lost with the machine prevents restores.

After installing the development tools from their hash lock, run
`python -m vws ops audit-dependencies --operator "YOUR NAME"` on the host. It
audits both current lock files, refuses skipped/incomplete/vulnerable results and
records only dated hashes, counts and the operator. Doctor compares those hashes
to the current files; an old result or changed lock stays unverified for live
prerequisites. This command is explicit maintenance, never a scheduler job.
CI also audits both locks weekly and publishes public CycloneDX inventories.
Dependabot proposes reviewed updates only; it never applies them to the host.

PostgreSQL remains optional. Automated legacy PostgreSQL migration is refused;
the CI trigger/concurrency suite uses only a disposable DB. Stop writers before
a production schema change. `pg_dump --format=custom --no-password --dbname=service=vws`
streams a consistent database dump to stdout. Route that stream directly into
your verified encrypted backup tool, never a plaintext file; private libpq service
configuration is an operator prerequisite, with no password in command arguments.
Restore using `pg_restore --exit-on-error --no-owner --dbname=service=vws_restore`
against an isolated empty restore database, then run the ledger verification smoke
command in VERIFY.md with that explicit restore URL. Record dump/restore success
only after the actual commands and chain verification pass. Neither production
PostgreSQL backup nor migration has been certified on this machine.

## Account history and cash activity

At startup and each monitor cycle, the Stage J service reads the selected bound
account's activity history. Initial capture requires complete paginated history;
later cycles resume from their checkpoint. Duplicate activity IDs are ignored
only when their contents agree. External deposits/withdrawals/journals scale
saved equity baselines atomically with their immutable activity evidence.
Missing opening history or ambiguous prior scaling halts rather than assuming
the current cash balance proves the past.

An urgent withdrawal warning is attempted even when later reconciliation fails.
Investigate any withdrawal you did not make through the broker's own support
and account-security controls. vws detects funding; it cannot initiate it.
Manual cash-flow files are not read. Do not use `data/manual_*.csv` to feed
state or funding; that path is deliberately deferred. Separate explicit
other-account tax imports remain supported and never initiate funding.

If accounting fails, new entries remain blocked and the durable HALT stays
latched. Existing held-position monitoring still attempts fresh quotes and
capped exit warnings. In MANUAL, confirm actual broker stops and make valid
held exits yourself. Do not clear a fault solely to obtain another ticket.

## Tax evidence and exports

Estimate and record-keeping aid, not tax advice. Your broker's 1099-B is the official record; consult a tax professional.

Register only your own confirmed account IDs in `config/accounts.yaml`.
Each entry has `id`, `name`, `tax_status` (TAXABLE, IRA or ROTH) and `source`
(ALPACA or CSV). CSV entries require `fills_csv` and default to FIFO; Alpaca
defaults to ALPACA_COMPRESSED_FIFO. Paths are direct, bounded owner files;
symlinks or unresolved parent traversal are refused. No external account login
is performed. A 401(k) lot can be marked for awareness without inventing its
tax treatment.

Fill CSV headers are `id,account_id,env,symbol,side,qty,price,fees,ts,is_drip`.
Use stable fill IDs, PAPER or LIVE, BUY or SELL, positive whole shares, exact
cent prices, nonnegative exact fees, UTC timestamps and `true` or `false`.
Keep the complete corrected fill history: a new import manifest supersedes
the projection without deleting old ledger evidence. Rerun a verified read-only
accounting cycle before exporting after any fill correction.

For owner-marked external lots, use exact CSV headers:

```text
lot_id,account_id,symbol,qty,cost_basis,acquired_at,funding_settlement_date,acquisition_trade_id,holding_period_start
```

`lot_id` is a stable UUID; `cost_basis` is per share, not total lot value.
`acquired_at` and an optional tacked `holding_period_start` are UTC. Optional
settlement date uses YYYY-MM-DD and acquisition ID uses a UUID. Keep unknown
optional fields blank; do not guess them. Quantity must be positive whole
shares. Import with `python -m vws tax import-lots --file PATH.csv` under the
selected account environment. Same-ID corrections append new versions.
The current marked-lot input has no removal/tombstone interface; omitting an
earlier marked lot does not retire it. This limitation can overstate awareness
and must be reviewed before treating a sale warning as complete evidence.

Once successful bound reconciliation has been recorded:

```text
python -m vws tax report --year 2026 --simulate
python -m vws tax report --year 2026 --account all
python -m vws tax reconcile --year 2026 --1099b PATH.csv --mapping config/1099b_columns.yaml
```

Simulation selects PAPER only and labels every CSV header/row NOT FOR FILING.
Without simulation, reporting and reconciliation require separate existing LIVE
evidence; neither command starts a service or enables trading. Missing or
changed checkpoints, account identity or book hashes refuse exports. The five
tax files are immutable versions below `data/tax/YEAR/ENV/ACCOUNT_HASH/REPORT_HASH`.
Unknown form boxes are UNVERIFIED. Future replacement buys within the wash
window can change the current estimate; open lots use the evidence date.

Map the broker's actual 1099-B export yourself. The sample mapping is only an
example. It requires seven distinct columns for symbol, sale date, quantity,
proceeds, basis, wash adjustment and term, plus explicit date/term labels.
Differences over one cent, term differences and unmatched rows are listed with
likely causes. The 1099-B wins; vws never alters it or files a return.
Federal ST/LT rates remain unset until supplied in setup; Texas state and NIIT
start at zero. `/tax` shows totals only until the rates are complete.

`/pnl today|week|month|ytd` is account performance, not a tax total. Its TWR
excludes external flows, keeps PAPER/LIVE separate and labels SPY price only.
Daily records/corrections retain source evidence. Reconstructed historical
cash and market value are COMPUTED; unknown sessions/fees refuse accounting.
Actual fee attribution, corporate-action basis, the broker's real tax export
and 2026 IRS form instructions remain UNVERIFIED on this machine.

## Extras and the emergency drill

After setup, run `python -m vws ops drill --operator "Vincent La Rocca"` on the host.
It uses a new scratch ledger and fake positions/orders; it opens no owner database
and places no broker order. It sends a marked DRILL to your private Telegram chat
and checks its receipt within 60 seconds. It needs setup's native backup key and
Telegram token/private chat. A failed or offline-only drill cannot qualify for
live unlock. The authenticated proof is stored at `data/drills/latest.enc`;
verify again within 31 days. No real drill was run here. This proof belongs to
the specified safety drill; the declined manual-CSV evidence file is not built.
AUTO_LIVE still needs the verdict, feed history and all separate unlock checks.

Reply to a bound trade card or trade FYI with a note of at most 1,000 characters.
Notes are escaped, private and append-only; they never enter trading decisions.
`python -m vws journal export` writes the complete bound journal CSV. A physical
sale outside a Project V proposal is UNASSIGNED/UNAVAILABLE and gets no invented
setup or CRO evidence. The digest lists at most five vetoes.

`/watch TICKER` accepts instruments.csv names and allows ten requests per ET day.
Watch cards are approvable in MANUAL and read-only in AUTO; they never auto-trade.
SPY below EMA200 defaults to annotation in MANUAL and half size in AUTO. Macro
release windows reuse CRO-11. The calendar ships empty; maintain official dates
in `config/macro_events.csv`. Status warns after 90 days.

A negative mean R after 30 resolved tracker trades pauses that playbook's auto
entries. Only `python -m vws ops playbook enable BASE_BREAKOUT --operator NAME`
can re-enable it. PAPER/LIVE samples stay separate. New losing evidence can pause
it again. Existing valid exits and stop protection continue.

`/report` and weekly delivery attach generated `latest.html` privately. It uses
inline SVG and no scripts or external resources; printing it is enough.
`python -m vws report monthly --month 2026-10` exports those sections to CSV.
The month filters daily accounting, SPY and the report's last 20 trades; current
positions, tax YTD and health show their snapshot date. It is not a full trade
statement or reconstructed historical month-end holdings/tax report.

`python -m vws ops secrets set NAME` uses the existing audited native keyring
rotation path and prompts without echo. Enter FRED only in `vws setup`.

## Reading the edge report and the verdict

Stage V remains in progress. See docs/VALIDATION.md for the registered test
procedure and its assumptions. No actual WORKING strategy or READY verdict has
been established. Hypothetical/past results; not indicative of future returns.

Read the cohort first: physical paper fills, the hypothetical alert tracker,
in-sample replay and out-of-sample replay are different evidence. Read the number
of resolved trades, after-cost average R, its confidence range and drawdown
together. UNPROVEN or INSUFFICIENT is not a positive result. WORKING needs the
specified minimum sample, positive lower bound, profit factor and, for OOS,
deflated Sharpe. Missing observations never count as passes.

Registration requires sealed history and financial filings plus explicit starting
cash assumptions. From vws-core, after setup and ledger verification:

```powershell
python -m vws validate register --history data/history --initial-equity 10000 --checking-balance 11500
python -m vws validate walkforward --family CONFIDENCE --history data/history --initial-equity 10000 --checking-balance 11500 --workers 3
```

Those cash figures are hypothetical examples; supply your intended assumptions.
Do not run a final holdout just to preview the tool. It consumes a one-use test
after the exact host phrase. EXITS includes baseline, split-at-1R, split with an
upward trail, EMA20 signal exit, and the fixed 10/20/30-session time stops.
Registration hashes bind reports and prevent changing inputs during a run.

For diagnostics without owner configuration:

```powershell
python -m vws profile scan --end 2026-10-02 --symbols NVDA --offline-fixtures
python -m vws profile replay --start 2026-09-01 --end 2026-10-02 --symbols NVDA --offline-fixtures --workers 1
```

These write cProfile top-20 text and .pstats files under data/profiles. Parent
profiles exclude worker CPU; their timings are diagnostics, not performance
acceptance. Fake inputs cannot establish an edge. The full performance gate
remains `python -m pytest backend/tests/test_replay_cli.py -m perf --no-cov -q -s`.

READY requires every sample, drawdown, benchmark, incident, security and drill
condition. STOP conditions take precedence. The verdict never enables a mode;
the independent live unlock and feed-history requirements remain mandatory.

`/verdict` recomputes the informational PAPER verdict in the private chat. The
first-session monthly check waits for the completed daily-bar delay. In paper
mode the live-only security conditions remain UNVERIFIED. The existing explicit
host `ops enable-live` preflight can recompute against qualified PAPER history
using the prepared live host's current security observations. It still requires
every separate AX prerequisite and the exact phrase before recording an unlock.
Do not run that command during this build; AUTO_LIVE stays locked.

For the paper cancel-semantics check, first configure a disposable AUTO_PAPER
account through setup and use already canceled OTO and OCO roots from your paper
drill. The following integration test performs authenticated GETs only; it sends
no orders or cancels. Missing evidence is UNVERIFIED.

```powershell
python -m pytest -m integration backend/tests/test_v_paper_cancel_integration.py --paper-integration-env-file C:\PRIVATE\paper.env --paper-cancel-order-ids EXISTING_OTO_ROOT_UUID,EXISTING_OCO_ROOT_UUID
```

AUTO_LIVE trail stops additionally need 30 successful paper raises, zero failures
and no unprotected window over 30 seconds, under the current variant/policy.
When a cancel is ambiguous, an overlapping sell is unsafe: halt, notify urgently
and look up the existing broker identity before any repair. Held exits and valid
stop protection remain available during entry halts.
