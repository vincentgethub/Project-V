# vws-core — defensive core and completion audit

The [master specification](docs/spec/MASTER_SPEC.md) and
[Amendments 01](docs/spec/AMENDMENT_01.md), [02](docs/spec/AMENDMENT_02.md),
[03](docs/spec/AMENDMENT_03.md), and [04](docs/spec/AMENDMENT_04.md) govern the
project. Later amendments win over conflicting earlier specifications and
addenda. See [owner progress](docs/PROGRESS.md) and [technical status](docs/STATUS.md).

Work continues automatically through audit/fixes → S → D → E → F → G → H → J →
I → K after each green gate and local commit. It stops only for the specified
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
and persisted state have 100% statement and branch coverage. Stage D already contains read-only
market/broker/liquidity providers, indicators and a deterministic scanner; its
amended batching, async, news, earnings and manual-account requirements remain
pending. The older core/gate.py is not a certified human-approval boundary.
The research swarm and Telegram bot are still pending. The project is not
finished, and no broker order execution path currently exists. Stage I alone
may add the specified isolated order executor; money movement remains banned.

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
.venv\Scripts\python.exe -m pip install --upgrade pip==26.2.1
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
```

On Linux use python3.12 and .venv/bin/python. Direct dependencies are pinned in
pyproject.toml; requirements-lock.txt pins the transitive environment. No
credentials are needed for these tests. Unit tests block sockets and isolate
application environment variables. A real dotenv file is never auto-read.

## Verify the audited core

Activate the virtual environment, then use the same commands as CI:

```text
python -m ruff check .
python -m ruff format --check .
python -m backend.core.check_stage_d
python -m backend.core.source_guard .
python -m bandit -r backend/core backend/domain backend/risk backend/data backend/agents scripts -c pyproject.toml
python -m pip_audit -r requirements-lock.txt --no-deps --disable-pip --progress-spinner off --timeout 15
python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]'
python -m pytest backend/tests --disable-socket --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov-branch --cov-fail-under=100 --cov-report=term-missing
```

On Windows `.venv\Scripts\python.exe -m` can replace python -m. The secrets scan
emits JSON; an empty results object is required. Synthetic tests and the full
source delivery are excluded from that heuristic scan, not from the AST guard.
The guard checks all authored Python files, with only its banned-list constants
module exempt. The pre-commit configuration provides the same local source checks.

See STATUS.md for the final combined audit-fixes results and exact commands for
checks marked UNVERIFIED. The coverage gate includes every risk module, the
state machine and Stage C tax contracts. Callback mutation tests, the
end-to-end dry run and Docker build belong to later stages. PostgreSQL runtime,
Docker, mutation testing and real paper API integration are not locally verified.

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
