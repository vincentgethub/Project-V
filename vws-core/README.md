# vws-core - defensive core and completion audit

The [master specification](docs/spec/MASTER_SPEC.md) and
[Amendments 01](docs/spec/AMENDMENT_01.md), [02](docs/spec/AMENDMENT_02.md),
[03](docs/spec/AMENDMENT_03.md), [04](docs/spec/AMENDMENT_04.md),
[05](docs/spec/AMENDMENT_05.md), [06](docs/spec/AMENDMENT_06.md), and the
[owner tax profile](docs/spec/TAX_PROFILE.md) govern the
project. Later amendments win over conflicting earlier specifications and
addenda. See [owner progress](docs/PROGRESS.md) and [technical status](docs/STATUS.md).

Work continues automatically through audit/fixes → S → D → E → F → G/G+ → H → J →
I → K → V → W after each green gate and local commit. It stops only for the specified
unresolved gate, required credential/decision, STOP-class finding, or safety
weakening. Nothing is pushed without the owner's instruction.

## Auto modes

> **Auto mode places real orders without asking you each time.** In AUTO_LIVE it trades your real money, and you can lose money, including more than a stop-loss suggests (gaps, halts, outages). Nothing in this software predicts or guarantees profits; paper results don't predict live results. Auto mode works only with Alpaca. Start with AUTO_PAPER, keep live limits small, and use `/halt` or `/manual` any time to stop new trades.

MANUAL with paper accounts remains the default. Stage I passed its offline
safety gates; no real broker order integration is certified. Setup saves native
keyring secrets and cannot enable AUTO. An explicitly configured AUTO_PAPER host
must pass the full doctor, watchdog, private Telegram, clock and encrypted-backup
checks before starting. Unverified checks block startup. The sole SDK order
module is `backend/execution/alpaca_executor.py`; MANUAL does not import it.

AUTO uses whole-share GTC bracket BUY LIMITs, verified broker stops and bounded
DAY LIMIT exits. FYI notices identify PAPER/LIVE, actual fills, protective levels
and CT times. Lower-scoring hybrid cards explicitly say Approve places the order.
Halts, `/pause` and `/manual` cancel unfilled entries and retain held protection.
Host `ops resume-auto --operator NAME` needs the exact `RESUME` phrase and doctor
checks; it cannot reset a HALT or acknowledge configuration drift.

Stage K's journal, private static reports, watch cards, reducing controls and
scratch emergency drill passed offline gates. Actual Telegram drill delivery
and broker integrations remain UNVERIFIED.

AUTO_LIVE remains locked pending V/W, paper history, reports, Stage J evidence,
the drill, security evidence, six explicit ceilings, and the host unlock phrase.
`ops disable-live --operator NAME` is a local downgrade requiring no broker
connection. During an incident, `ops panic` commits local HALT first, then makes
bounded cancellation/reporting attempts and prints every unavailable step.
Use the [runbook](RUNBOOK.md) for recovery; never place manual trades in the
dedicated AUTO account. Money movement is never available.

Read-only defensive infrastructure for long-only, whole-share research and human
trade tickets. Stage A supplies configuration guards, exact money/cent-price
helpers, UTC clocks, redacted logging, deduplicated notifications, XNYS sessions,
an immutable audit ledger, durable halt state, and an execution-code source guard.

Stage B adds frozen domain/research contracts, a validated instrument registry,
all thirteen deterministic CRO rules, sequential batch reservations, conservative
quantity suggestions, and RiskBoundary for persisted tiers and veto audit logs.
The historical Stage A/B delivery passed 1,167 offline tests. The CRO, boundary,
and state machine each had 100% statement and branch coverage at that delivery.

Stage C adds all seven pure compliance rules, exact wash-share allocation, tax
contracts, T+1 cash reconstruction, both day-trade regimes, reconciliation export,
and ComplianceBoundary for required HALTs and failed-finding audit logs.
The historical Stage A–C delivery passed 1,441 offline tests; all risk modules,
Stage C contracts and the persisted state machine had 100% statement and branch
coverage at that delivery.

The audit-fixes gate passed 2,167 offline tests; the risk modules, tax contracts
and persisted state have 100% statement and branch coverage. Stage D contains
read-only market/broker/liquidity providers, shared asynchronous request budgets,
incremental daily-bar caching, news and corporate-action evidence, earnings
windows, indicators and a deterministic scanner. Manual CSV is now owner-deferred.
Its final combined gate passed 2,901 tests, with one paper integration skipped;
risk/state/contracts retain 100% statement and branch coverage. The older core/gate.py is not a
certified human-approval boundary.
Stage E supplies deterministic fundamentals and optional public-only summaries.
Stage F supplies the swarm, private Telegram approval boundary, six scheduled
job bodies, manual tickets and read-only fill matching. Its offline gate passed
3,366 tests with 44 unverified checks skipped and complete required branch coverage;
connected host composition is supplied by Stage H. The project is not
finished. Stage I's isolated order executor passed its offline safety gates;
MANUAL remains the default, and money movement remains banned.

Stage G/G+ supplies recorded hypothetical outcomes, original cost evidence,
private weekly edge/security reports with individual proofs, sealed local
replay, split-aware cache invalidation and deterministic parallel indicators.
Its cumulative offline gate passed 3,709 cases with 44 unverified service checks
skipped; required safety branch coverage is 100%. The separate fixed 20-symbol,
seven-year replay passed in 88.411 seconds. Synthetic results never certify an
edge or live readiness.

Stage H supplies guided native-keyring setup, doctor, one-process host startup,
locks/heartbeat/watchdog, backed-up additive migration, encrypted maintenance,
private logging and pinned CI/deployment configuration. Its final offline gate
passed 4,080 tests, 46 service checks skipped, with complete required branch
coverage including evaluation. The current fixed replay passed in 97.666 seconds.
Actual account services, deployment and remote CI remain UNVERIFIED.

Stage J supplies account-history, cash-flow, daily P&L and tax reports, certified
GREEN OFFLINE: 4,266 tests passed, 52 service checks skipped, with complete
required branch coverage (5,244 statements / 1,684 branches). It shares the
original compliance wash-sale matcher. The fixed replay passed in 75.600s with
an unchanged proof hash. Exact amounts and append-only corrections remain.
BROKER_STATE_SOURCE stays ALPACA. Any MANUAL_CSV setting refuses startup with a
clear doctor fix; funding/state adapters cannot read `data/manual_*.csv`, even
when used directly. The host evidence file was declined. Amendment 02 §11.2
item 1's manual acceptance is DEFERRED (user decision, Oct 8 2026).
Real account/platform checks remain UNVERIFIED. Stage I follows J's local commit.

Stage S passed its offline gates on October 5, 2026. The encryption, anchor, drift and
panic service suite passed 137 offline tests with complete statement and branch
coverage; native-keyring/permissions/redaction services have separate fake tests.
The full collected suite passed 2,535 tests; the final CLI/progress gate passed
42 cases, including seven new cases. Risk/state coverage stays at 100%.
The final 60-runtime/121-dev hash locks installed into an isolated fresh Windows
environment, pip check passed, and all 121 dev pins audited clean.
Monitor-cycle, Telegram-handler and evening/weekly report wiring belong to the
specified later stages. A tested component does not certify a connected account.

Fundamentals use the amended deterministic five-point framework in Stage E.
Code evaluates exact Decimal ratios and free cash flow against strict thresholds:
gross margin >40%, operating margin >15%, ROIC >10%, FCF >0, and interest coverage
>3. Missing evidence cannot pass; inapplicable instruments have a separate status.
The earlier float/ModelAgnosticClient addendum is superseded. An optional LLM
may provide a one-line narrative and cannot set metrics, statuses or trade values.

## Install

Use Python 3.12. From this directory on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes --no-deps -r requirements.lock
.venv\Scripts\python.exe -m pip install --require-hashes --no-deps -r requirements-dev.lock
.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

On Linux use python3.12 and .venv/bin/python. Direct dependencies are pinned in
pyproject.toml; requirements.lock pins and hashes runtime packages, and
requirements-dev.lock covers development and build tools. The last command
installs only authored local source, without resolving external dependencies.
Fresh Windows installation of both lock closures is verified. Native Linux
operation and remote CI remain UNVERIFIED; requirements-lock.txt is retained
as historical audit evidence. No
credentials are needed for these tests. Unit tests block sockets and isolate
application environment variables. A real dotenv file is never auto-read.

After installing, run the guided setup and required checks from this folder:

```powershell
.venv\Scripts\python.exe -m vws setup
.venv\Scripts\python.exe -m vws doctor
.venv\Scripts\python.exe -m vws start
```

Setup saves secrets only in Windows Credential Manager or Linux Secret Service,
confirms your private Telegram chat and explains account security. Enter your
FRED key and SEC name/email only there. Cancel restores prior configuration and
secret entries; append-only audit records remain. Start currently accepts MANUAL
with paper keys, preserves saved halts, and refuses failed required doctor checks.
Optional unverified checks remain labeled. Review cards in your private chat;
approval creates a manual ticket. Read-only account history must reconcile with
the current bound account before tickets or tax exports are available; missing
history blocks them. No real connected operation is certified here.
The setup/start implementation passed the Stage H offline acceptance gate.
For commands available at the current stage, see [RUNBOOK.md](RUNBOOK.md).

## How to fund your account

Use the broker's own dashboard. vws never initiates deposits, withdrawals,
transfers or bank linking, and never requests bank routing/account details.
Plaid reads balances solely for the checking-buffer gate.

Paper uses virtual money. Review the [Alpaca paper-account instructions](https://docs.alpaca.markets/us/docs/paper-trading)
before resetting or choosing a virtual balance. The current dashboard's exact
reset steps and resulting credentials/account ID remain UNVERIFIED here. Rebind
and verify the resulting paper identity through setup; a changed account ID
starts a separate history and never inherits the old account's readiness.

For an eventual live account, the owner links a bank and initiates ACH deposits
in Alpaca's dashboard. This build has not enabled live mode. The read-only
accounting cycle detects recorded cash activity, deduplicates it and scales the
equity baselines; deposits are not trading gains. Withdrawals alert urgently.
Unknown activity is recorded and reported without guessing its effect.

## Tax records and account performance

Estimate and record-keeping aid, not tax advice. Your broker's 1099-B is the official record; consult a tax professional.

The guided setup starts with the owner's single/Texas profile: state rate zero,
NIIT zero, federal short-/long-term rates unset. Until both federal rates are
entered, tax replies show totals only. External IRA/Roth, Merrill and 401(k)
awareness comes from owner-entered/imported evidence; vws never logs into those
accounts. A recorded sale prompts review of the marked external lots.

After a successful read-only accounting cycle, use:

```powershell
.venv\Scripts\python.exe -m vws tax report --year 2026 --simulate
.venv\Scripts\python.exe -m vws tax report --year 2026 --account all
.venv\Scripts\python.exe -m vws tax reconcile --year 2026 --1099b PATH_TO_1099B.csv --mapping config/1099b_columns.yaml
.venv\Scripts\python.exe -m vws tax import-lots --file PATH_TO_MARKED_LOTS.csv
```

The first command uses PAPER evidence and labels every CSV header and row
`SIMULATED - NOT FOR FILING`. The second and reconciliation command require
separate LIVE evidence already captured and verified; they neither connect nor
enable trading. A missing checkpoint, unreconciled account, changed import or
wrong cohort refuses publication. Reports are write-once versions under
`data/tax/YEAR/ENV/ACCOUNT_HASH/REPORT_HASH/` containing `form8949.csv`,
`schedule_d_summary.csv`, `income.csv`, `lots_open.csv` and `README.txt`.
Corrections create new evidence and versions; they never replace ledger rows.

`config/accounts.yaml` lists owner-confirmed account IDs and tax status. CSV
accounts additionally specify `fills_csv`; their default lot method is FIFO.
Alpaca uses compressed FIFO. Whole-share fill CSV columns, in order, are
`id,account_id,env,symbol,side,qty,price,fees,ts,is_drip`; `env` is PAPER or LIVE
and `ts` is UTC. Marked-lot columns and operating steps are in RUNBOOK.md.
The one shared wash-sale engine applies configured identity groups across the
listed accounts, with tacking and permanent IRA/Roth loss flags.

`/pnl today|week|month|ytd` and private digests use a separate account/env series
and time-weighted returns that exclude external flows. SPY is labelled price
only and unavailable benchmark history stays UNVERIFIED. Historical cash and
market value reconstructed from account evidence are labelled COMPUTED.
`/tax` and weekly summaries show realized short-/long-term results, wash losses,
income and the rate-based estimated set-aside, with the disclaimer above.

Real per-fill fee attribution, corporate-action basis transformations, actual
1099-B columns/lot method and 2026 IRS form instructions remain UNVERIFIED.
The sample mapping is not an assertion about the broker's export. Ambiguous
fees or corporate actions block accounting rather than inventing tax basis.
The required [2026 form instructions are not yet verified](https://www.irs.gov/instructions/i8949);
unknown form boxes are explicitly marked UNVERIFIED. Open lots reflect the
supplied evidence date; future wash replacements can still change a loss.

## Run it 24/7

On Windows, use the same standard user who completed setup. In Task Scheduler,
create a task triggered **At log on**, running only when that user is logged on.
Leave **Run with highest privileges** off. Action: `powershell.exe`, arguments
`-NoProfile -WindowStyle Hidden -File "FULL_PATH\deploy\windows_start.ps1"`, and
Start in the vws-core folder. Use "Do not start a new instance" and a bounded
restart policy, for example three retries one minute apart. Do not impose a time
limit. The script invokes the installed venv and inherits no secret arguments.
Screen lock can remain enabled. Stopping a foreground process with Ctrl-C drains
workers and releases its OS lock; a forced Task Scheduler stop is a crash, not a
graceful shutdown. Startup re-verifies the ledger and never clears a halt.

On Linux, install under `/opt/vws-core` for a dedicated non-root `vws` user and
complete setup as that user first. Review `deploy/vws.service` before installing
it. Create its data/logs/backups directories, owned by that user with mode 0700;
the non-secret `.env` must be 0600. The user's unlocked Secret Service and private
D-Bus socket must remain available. Set `DBUS_SESSION_BUS_ADDRESS` to that user's
exact `/run/user/UID/bus` in the service environment; the security guard verifies
ownership and refuses TCP/alternate buses. A headless host without native secret
storage cannot start. Install the reviewed unit with `systemctl daemon-reload`
and `systemctl enable --now vws.service` only after successful setup/doctor.
SIGTERM drains jobs; the unit limits restarts, memory and tasks and opens no ports.
Home and runtime-user directories remain read-only so the owned Secret Service
socket stays visible; source/configuration files are also read-only to the unit.
These host changes are operator steps; none have been applied by this build.

Docker keeps non-root, read-only, capability-free execution and only the specified
data/logs/backups mounts. It does not mount a desktop secret-store socket. With
the current required keyring backend, that container therefore refuses connected
startup. Build and OS-lock health checks are provided; actual container operation
and native Linux secret storage remain UNVERIFIED. Use the documented host process
after setup. There is no plaintext secret fallback.

## Verify the audited core

Activate the virtual environment, then use the same commands as CI:

```text
python -m ruff check .
python -m ruff format --check .
python -m backend.core.check_stage_d
python -m backend.core.source_guard .
python -m bandit -r backend/core backend/domain backend/risk backend/data backend/agents backend/security backend/net backend/ops backend/telegram backend/notifications backend/tax backend/funding backend/pnl backend/evaluation backend/indicators scripts vws -c pyproject.toml
python -m pip_audit -r requirements.lock --no-deps --disable-pip --progress-spinner off --timeout 15
python -m pip_audit -r requirements-dev.lock --no-deps --disable-pip --progress-spinner off --timeout 15
python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]'
python -m pytest -q --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov=backend.evaluation --cov-branch --cov-fail-under=100 --cov-report=term-missing
python scripts/dry_run.py --dry-run NVDA --offline
```

On Windows `.venv\Scripts\python.exe -m` can replace python -m. Set
`$env:PYTHONIOENCODING = 'utf-8'` before the authored-source typing wrapper;
it runs strict mypy and checks the source guard. The secrets scan
emits JSON; an empty results object is required. Synthetic tests and the full
source delivery are excluded from that heuristic scan, not from the AST guard.
The guard checks all authored Python files, with only its banned-list constants
module exempt. The pre-commit configuration provides the same local source checks.

See [technical status](docs/STATUS.md) for actual counts and
[verification](VERIFY.md) for exact reproduction commands. The coverage gate
includes risk, state, compliance contracts, fundamentals, notifications, tax and
evaluation. Security scans also cover the funding and P&L packages.
Linux CI has separate mutation and disposable PostgreSQL jobs plus the container
build. Remote CI, PostgreSQL runtime, Docker, mutation testing and real paper
API integration remain UNVERIFIED until they run. No push is authorized here.

Run the Linux-only checks in an activated venv on an isolated Linux checkout:

```text
python -m mutmut run
python -m mutmut results --all > /tmp/vws-mutants.txt
python -m scripts.check_mutations /tmp/vws-mutants.txt
python -m pytest -q backend/tests/test_postgres.py --postgres-test-url 'postgresql+psycopg://vws_ci:CI_FIXTURE_ONLY@127.0.0.1:5432/vws_ci' # pragma: allowlist secret - public disposable CI fixture
```

The PostgreSQL command requires a disposable local PostgreSQL 16 database and
user both named `vws_ci`; the password shown is a public CI fixture. Tests never
discover an owner database or dotenv. All generated test schemas are isolated.
For the container build, copy `.env.example` to `.env` only in a disposable
checkout, then run `docker compose build`. The non-root package opens no ports;
its startup and healthcheck CLI passed fake host tests. Native secret storage
is unavailable under these restricted mounts, so connected startup refuses.

## Secure your accounts

Confirm each item yourself, then record it on the host with
`python -m vws --env-file .env ops attest ITEM --operator YOUR_NAME`. ITEM accepts
the number or the exact name below. The explicit `--env-file` option loads only
the file you chose. Doctor shows **ATTESTED (date)** or **WARN**; the app never
claims to have verified a third-party security setting.

| ITEM | Name | What to confirm |
| --- | --- | --- |
| 1 | ALPACA_MFA | Alpaca multi-factor authentication enabled |
| 2 | RECOVERY_EMAIL_2FA | Dedicated recovery email with a passkey or two-factor security |
| 3 | TELEGRAM_2STEP | Telegram two-step password set and Devices reviewed |
| 4 | PHONE_PASSCODE | Phone passcode enabled |
| 5 | GITHUB_PRIVATE_2FA | GitHub two-factor security enabled and repository private |
| 6 | CARRIER_PORT_PIN | Carrier port-out/SIM PIN enabled |
| 7 | PASSWORD_MANAGER | Every secret and the recovery backup key saved in a password manager |
| 8 | PLAID_2FA | Plaid dashboard two-factor security enabled |
| 9 | ALPACA_EMAIL_NOTICES | Alpaca email notifications enabled; exact setting remains VERIFY |
| 10 | ALPACA_CRYPTO_DISABLED | Unused crypto disabled in Alpaca; availability remains VERIFY |

Broker API scopes do not prove that Trading API keys have the same controls.
Trading API scope controls and IP allowlisting remain UNVERIFIED. If available,
MANUAL/data credentials must be read only; AUTO credentials get Trading + Data,
with Funding and Journaling set to No access. The app never tests funding
destructively. PK/AK key prefixes are only hints; endpoint/account binding is
authoritative. Crypto-wallet and whitelist mutations remain source-banned.

Native storage is Windows Credential Manager with local-machine persistence,
or Linux Secret Service. Plaid access tokens live there in every mode, with
no env/file fallback. Rotation asks for hidden input and validates a read-only
provider call before replacement. Failed validation keeps the old credential;
the ledger stores only a dated HMAC fingerprint. A credential age at 90 days
WARNs by default; unknown age never counts as verified.

Generate/store the backup recovery key and display it once with
`python -m vws --env-file .env ops show-backup-key`. Save it immediately in your
password manager. **Losing this key means encrypted backups cannot be restored.**
Do not paste it or any credential into chat, logs or command arguments.

See [RUNBOOK.md](RUNBOOK.md) for rotation, encrypted backups, host hardening,
anchor checks and drift acknowledgement, and [INCIDENT.md](docs/INCIDENT.md)
for a suspected compromise. Real keyring/provider/host checks are UNVERIFIED
until run on your configured machine; passing fake tests does not attest to them.

## Advanced: explicit manual configuration

The owner-facing setup wizard passed its H offline acceptance gate.
Developers can deliberately
load a private non-secret configuration with `--env-file .env`; tests never
read it implicitly. Verify the actual CASH or MARGIN account type rather than
copying the sample CASH value as an assumption. Keep strategy/schedules in
config/config.yaml and risk/mode settings in their single env home. Plaid tokens
cannot be placed in env or files, and AUTO_LIVE rejects the specified live,
Telegram and Plaid secrets from both dotenv and the process environment.
Manual configuration does not authorize mode upgrades or bypass live unlocks.

The app opens no inbound ports. HTTPS egress is allowlisted, TLS is verified,
redirects are rechecked, and the SDK socket hook provides an additional guard.
That Python guard is not an operating-system sandbox against a compromised host.
Private paths, disk encryption and an independent old ledger anchor still matter.

## Local API

```python
from pathlib import Path

from backend.core.clock import SystemClock
from backend.core.config import Settings
from backend.core.database import create_database, create_schema
from backend.core.notifier import ConsoleNotifier
from backend.core.source_guard import require_safe_sources
from backend.core.system_state import SystemStateStore

require_safe_sources(Path.cwd())
settings = Settings(broker_account_type="CASH")
engine = create_database(settings.db_url.get_secret_value())
create_schema(engine)
store = SystemStateStore(engine, SystemClock(), ConsoleNotifier())
print(store.current())
```

This scratch example explicitly supplies synthetic CASH and initializes a local
ledger. Connected startup requires an explicit BROKER_ACCOUNT_TYPE matching the
actual broker account; it has no default. The ledger verifies chains before
reading state. Existing
incompatible schemas fail without automatic migration. SystemStateStore.escalate
persists a halt; investigate its cause and verify the ledger before an attributed
operator_reset(operator_id, reason). Authentication for that administrative API
belongs to a future service boundary.

Use load_settings(env_file=...) only to deliberately read a private dotenv file.
load_yaml_config(path, allowed_symbols=..., settings=settings) validates YAML;
the symbol allowlist must come from the instrument source of truth.
Schedules, completed-bar lag and alert cooldown belong only to config/config.yaml.
Their former environment keys are rejected even when the values agree with YAML.
assert_research_ready(), assert_telegram_ready(), and assert_llm_call_budget_ready()
block missing connected configuration. with_yaml_hash() includes validated YAML
in the configuration identity used by future pipeline callers.

For risk evaluation, create ChiefRiskOfficer(settings, registry, calendar), with
an explicit verified InstrumentRegistry and bounded MarketCalendar. Inject that
CRO, the store, and a clock into RiskBoundary. Its evaluate(proposal, snapshot,
market, deployable=...) returns immutable rule evidence and persists required
state escalation. Direct CRO calls are pure and require caller-supplied state
and now; they cannot log or persist a halt. proposed expires_at is required.

Persist first-run equity baselines before calling risk. Zero marks recommend HALT.
The daily-loss limit blocks ENTRY/ADD for the current XNYS session and recovers at
the next session open. Drawdown tiers and fault HALTs latch until operator reset.
Unknown earnings produces a WARN; known nearby earnings blocks entries. Valid
held exits bypass entry gates. Pending BUY exposure/risk and pending SELL inventory
are reserved; max_allowed_qty never increases requested size. Sample CSVs require
operator verification before use with real account data. See ASSUMPTIONS.md for
the conservative calendar, sector, expiry, and inventory interpretations.

Ledger.record_trade_ticket() is a low-level atomic audit writer. Stage F's human
gate must authenticate callbacks and revalidate fresh data before invoking it.
It does not fetch market data or authenticate a Telegram user itself.

For compliance, create ComplianceEngine(settings, registry, calendar,
restricted_symbols=...). Its pure check(proposal, snapshot, lots, history,
external_accounts, now, flags=...) returns all CMP-01..07 findings. assess()
also stamps full input provenance and a typed state recommendation. Wrap it in
ComplianceBoundary(engine, store, clock) and call evaluate(..., flags=...) to
persist required broker/provider HALTs and log failed WARN/BLOCK findings.
An active current AccountFlags value is mandatory evidence; None requests HALT.

WashSaleMatcher shares replacement capacity across losses and excludes original
or disposed shares. TaxLot separates actual acquired_at from prior tacked holding
start; tacked lots require an explicit original acquisition ID. Realized losses
must already reflect earlier basis adjustments. Form 8949 rows cover matched
sale slices for reconciliation. See STAGE_C_SOURCE_NOTES.md for verified IRS,
SEC, FINRA and Alpaca contracts and the conservative software assumptions.

See ASSUMPTIONS.md and VERIFY.md. Historical full manifests and untruncated source
are in deliveries/Stage_A.md, deliveries/Stage_B.md, and deliveries/Stage_C.md.
The amended stages continue automatically after successful verification.

## Fixed historical replay

Stage G's offline CLI uses the same hunter gates, point-in-time fundamentals,
CRO sizing and pure cost/fill model. It runs no account, network or order code.
Try a labeled synthetic acceptance tape:

```powershell
.venv\Scripts\python.exe -m vws replay --start 2026-08-01 --end 2026-10-02 --symbols NVDA --offline-fixtures --workers 1
```

The JSON/CSV files are under `data/reports/`; synthetic caches have their own
namespace. Report hashes are deterministic, including across worker counts.
Real runs require explicitly supplied hypothetical starting/funding amounts and
sealed price/filing manifests. See RUNBOOK.md and docs/VALIDATION.md for the
commands, costs, source gaps, dividend estimates, rough taxes and survivorship.
The result is in-sample: no out-of-sample edge or live readiness is claimed.
Hypothetical/past results; not indicative of future returns.
