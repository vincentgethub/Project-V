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
windows, manual CSV account evidence, indicators and a deterministic scanner.
Its final combined gate passed 2,901 tests, with one paper integration skipped;
risk/state/contracts retain 100% statement and branch coverage. The older core/gate.py is not a
certified human-approval boundary.
Stage E supplies deterministic fundamentals and optional public-only summaries.
Stage F supplies the swarm, private Telegram approval boundary, six scheduled
job bodies, manual tickets and read-only fill matching. Its offline gate passed
3,366 tests with 44 unverified checks skipped and complete required branch coverage;
connected host composition is Stage H work. The project is not
finished, and no broker order execution path currently exists. Stage I alone
may add the specified isolated order executor; money movement remains banned.

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

The guided first-run flow specified for Stage H will be install, then
`python -m vws setup`, `python -m vws start`, and review cards in your private
Telegram chat. Setup and start are not available yet. The bot component has
fake-HTTP tests; it has not been connected to your real private chat. Setup will save
secrets to the native keyring, start in MANUAL + paper, confirm your chat and
guide you through account-security attestations. It never enables auto mode.
For commands available at the current stage, see [RUNBOOK.md](RUNBOOK.md).

## Verify the audited core

Activate the virtual environment, then use the same commands as CI:

```text
python -m ruff check .
python -m ruff format --check .
python -m backend.core.check_stage_d
python -m backend.core.source_guard .
python -m bandit -r backend/core backend/domain backend/risk backend/data backend/agents backend/security backend/net backend/ops backend/telegram backend/notifications backend/tax scripts vws -c pyproject.toml
python -m pip_audit -r requirements.lock --no-deps --disable-pip --progress-spinner off --timeout 15
python -m pip_audit -r requirements-dev.lock --no-deps --disable-pip --progress-spinner off --timeout 15
python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]'
python -m pytest -q --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov-branch --cov-fail-under=100 --cov-report=term-missing
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
includes risk, state, compliance contracts, fundamentals, notifications and tax.
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
its startup and healthcheck CLI depend on Stage H and are not certified yet.

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

The owner-facing setup wizard is pending Stage H. Developers can deliberately
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
