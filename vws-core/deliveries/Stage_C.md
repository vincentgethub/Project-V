# Stage C - full delivery

Stage C is complete under the newest master spec, following Execute Stage C.
Stages A and B remain delivered. Stop here; next command: Execute Stage D.
No order-execution, broker/bank request, transfer, LLM or Telegram action occurred.

1,441 offline tests passed in 118.28 seconds. Completed risk modules, compliance
contracts and persisted state achieved 100% of 1,108 statements and 360 branches.
Ruff, strict mypy, AST guard, Bandit, all five root pre-commit hooks, pip check,
secrets scan, and audit of all 109 transitive pins passed. VERIFY.md below records
the evidence and limits. STAGE_C_SOURCE_NOTES.md records authoritative references.

Every manifest file appears in full, including referenced configuration and
parent Git-root mirrors. UTF-8 bytes and SHA-256 hashes identify each original
file exactly. Historical Stage_A.md and Stage_B.md remain unchanged. Preserved
Stage D drafts and core/gate.py are outside this stage's certification.

## ASSUMPTIONS

# ASSUMPTIONS

The newest master spec supersedes the earlier A–D blueprint and automatic
continuation request. The current command authorizes Stage C, with Stages A and B
already delivered. Stage D starts only after `Execute Stage D`. Order execution is permanently
absent; orders in the ledger are local proposal/audit records.

1. Financial inputs are exact decimal text, integers or Decimal. R-13 price
   boundaries specifically require positive Decimal cent prices; quantities are
   whole integers. Indicator math alone may use float64 in later stages.
2. Sub-cent proposed prices are rejected rather than silently rounded. General
   money, costs and balances retain millionths in signed 64-bit storage.
3. Settings never load a real `.env` implicitly. Secret-bearing database URLs are
   SecretStr. Their non-secret identity participates in configuration hashing.
4. Protective minima cannot be reduced below the blueprint defaults: the checking
   buffer, cash reserve, minimum price, slippage allowance and margin equity floor.
   Unspecified absolute bounds are documented in config source.
5. SQLite is the local default. PostgreSQL-compatible SQL, row locks and triggers
   are supplied; PostgreSQL runtime verification is separately reported.
6. Audit tables are append-only. Two deliberately mutable singleton rows allocate
   sequence numbers and project current operating state. Verification reconciles
   the projection with immutable transition events.
7. A database or notifier fault also latches the current process HALTED. Persisting
   a halt cannot be guaranteed while storage itself is unavailable; failure is
   surfaced and no approval can rely on that process state.
8. Only an attributed operator reset lowers a latched operating state. A recovered
   quote, restart or new session alone never clears a halt.
9. XNYS sessions are bounded by an explicit calendar range. Dates outside that
   range fail closed; timestamps at the exact close belong to a completed session.
   T+1 starts from a verified trading session, with holidays and early closes honored.
10. Supplied CSVs are sample configuration, not an authoritative production
    instrument universe or current ETF weights. Unknown instruments fail closed.
11. The checking-buffer gate caps new funding only. It never moves bank money and
    does not treat checking funds as already settled brokerage cash.
12. Valid held-position reductions bypass entry-specific market, funding and
    concentration checks. The HALTED/manual exception remains explicit.
13. A pure CRO returns decisions and evidence. Persistence, state escalation,
    notifications and veto logging happen in the enclosing gate.
14. Alpaca does not provide a settled-cash field in the required account contract.
    Cash-account purchases need an injected settlement ledger; absent proof means
    zero settled cash.
15. In the preserved Stage D draft, Plaid Balance is not a standalone Link/Sandbox initialization product. Sandbox
    setup uses the supported Auth entitlement to obtain an Item token; application
    runtime calls only the balance endpoint. No Auth data retrieval or funding exists.
16. The account-schema test fixture is synthetic and follows verified current
    fields. It is not misrepresented as a captured live account response. A genuine
    sanitized recording requires credentials and remains an integration check.

Stage-specific additions and unresolved verification items are recorded with each
delivery and in VERIFY.md.

17. Settings() permits isolated offline core tests without credentials. Connected
    startup must call assert_research_ready() and/or assert_telegram_ready(). The
    model, credentials, nonempty user allowlist, and >=32-byte callback secret
    have no usable offline defaults. No model name is hard-coded.
18. Zero LLM daily budget disables calls. Explicit verified input/output token
    rates plus assert_llm_call_budget_ready() are also required. Stage E implements
    actual calls and budget accounting; no cost is guessed.
19. Additional source bounds resolve unspecified ceilings conservatively: setup
    score 6..10, cooldown 1..30 sessions, LLM budget 0..1,000 USD/day, timeout 1..60
    seconds, max tokens 1..8,192. YAML is separate, frozen, exact Decimal, rejects
    risk keys/duplicates/anchors/aliases/oversize/depth >20, and requires an explicit
    instrument allowlist. Criterion weights support at most six decimal places.
    with_yaml_hash() combines the validated YAML with nonsecret environment policy.
20. Alert.id is the stable alert ID. PENDING means not yet delivered; an append-only
    AlertEvent SENT makes the awaiting-human alert actionable. This resolves the
    spec's ambiguous requirement that a delivered alert still be called PENDING.
    Terminal statuses are new events. Chat/message IDs belong to delivery evidence.
21. Manual approval and its ticket commit atomically; a unique alert FK makes
    tickets single-use. Exact ticket values come from the linked local proposal.
    Ledger.record_trade_ticket() is a low-level persistence primitive: Stage F
    must authenticate the human and revalidate fresh data before calling it.
22. Schema version 2 rejects old/incompatible databases; no silent migration is
    performed. Use a new development database or an explicitly reviewed migration.
    PostgreSQL is schema-compatible but no server runtime test is claimed.
    Administrators can disable triggers/rewrite evidence; this is not a claim of
    protection from a privileged database owner.
23. Every halt invokes a notifier. Repeated successful redacted state/reason
    messages are deduplicated for a local halt episode; failed delivery is retried.
    Daily-loss reduction remains latched until an explicit operator reset, a
    stricter interpretation of the spec's next-session recovery ambiguity.
24. The AST guard scans every authored Python file including tests/scripts/drafts;
    only execution_policy.py's banned-list constants are exempt. Generated virtual
    environments/caches/vendor dependencies are not authored repository sources.
    Builtin compile is banned; re.compile is permitted regex construction.
25. The older Stage D draft and core/gate.py are preserved, not certified against the new master spec.
    Minimal reflection/lint edits keep them compatible with the whole-source guard.
    The current Git root is Project V, so a root CI workflow mirrors the requested
    project workflow, pre-commit configuration, and .gitignore. These support
    nested or standalone project checkouts.

26. Stage B adds required proposal expires_at and optional target_price. An ENTRY
    or ADD target, when supplied, must exceed the limit. Prices require Decimal
    cents even in model validation; JSON/API adapters must decode exact Decimal
    values before entering these contracts. Float prices and sub-cent prices fail.
27. Existing Pydantic instances, including nested positions/orders, are revalidated
    at risk ingress. Policy and registry mappings are detached/revalidated at CRO
    construction. The service objects and compiled calendar are trusted injected
    dependencies; callers must not reassign their policy references during use.
28. High-water and daily-start marks must already be persisted and positive. Zero
    is missing evidence and recommends HALTED. First-run initialization belongs
    outside the pure CRO and must explicitly persist actual equity as the baseline.
29. Unconfigured known sectors use a 35% cap; unconfigured themes use zero. Unknown
    sectors block. An ETF with complete verified look-through to known sectors may
    have UNKNOWN declared sector; without weights its declared sector is 100%.
30. Pending BUY notional reserves concentration, gross exposure and cash. Pending
    SELL quantities reserve inventory and never release exposure before a fill.
    Same-name pending BUY stop risk uses its supplied stop; an absent stop reserves
    the full notional as loss. ADD also covers existing shares at the proposed stop.
31. max_allowed_qty is advisory and never exceeds requested qty. It finds the
    largest whole quantity satisfying complete CRO-02..08 evidence; it does not
    certify earnings, funding, operating state, or later compliance approval.
32. Unknown earnings is an explicit failed WARN. A known past date blocks as
    unresolved. A non-session earnings date includes the preceding exchange session
    plus the configured prior sessions. UTC blackout windows include both endpoints.
33. Verifiable exits bypass entry gates but still require matching accounts,
    live proposal lifetime, fresh inventory, and held minus pending SELL quantity.
    Snapshot freshness uses the quote TTL; stale holdings cannot prove held qty.
34. recommended_state is a typed Verdict extension carrying a pure CRO tier to
    RiskBoundary for persistence. A new financial HALT does not retroactively trap
    a valid held exit from a permitted starting state. Later HALTED calls require
    MANUAL source. A fatal batch result also gates subsequent entries in that batch.
35. RiskBoundary checks current state before and after evaluation, consumes the
    persisted escalation result, logs each blocking veto, and halts on any fault.
    Its Verdict is research evidence. The Stage F human gate still needs fresh
    revalidation and atomic state checks when writing alert/ticket evidence.
36. MarketContext carries no symbol field in the specified contract. Stage D's
    per-symbol provider must bind its returned market data to the requested symbol.
    Stage B never fetches data or substitutes default quote/funding evidence.
37. ProviderResult and research output contracts are present; actual providers,
    deterministic scanners, LLM clients, scheduler and Telegram await their stages.
    LLM contracts cannot set trade levels/qty or a CRO decision.

38. Stage C's account taxonomy attests accounts belonging to the same taxpayer.
    The supplied history must include relevant-window purchases/dispositions,
    DRIP, other accounts, and the original BUY for explicitly referenced lots.
    The software cannot discover omitted spouse/entity accounts or future trades.
    Substantially identical groups remain explicit operator-reviewed metadata.
39. TradeRecord.price remains strict Decimal cents; TaxLot.cost_basis, realized
    losses and adjusted tax basis retain micro-unit money. Prior adjustments can
    create fractional-cent basis, so basis is not silently rounded to a price.
    Fractional-share DRIP evidence is unverifiable under this whole-share contract.
40. A loss sale represents one original acquisition lot and attests its realized
    loss after previous basis adjustments. Aggregate multi-lot losses must be split.
    acquired_at is the actual purchase timestamp. An earlier holding_period_start
    represents prior tacking and requires acquisition_trade_id. Untacked origins
    absent from a relevant window can be attested older acquisitions; ambiguous
    missing lineage or simultaneous trades with unresolved disposal order fail.
41. Wash matching uses disjoint replacement-share intervals shared across loss
    sales. Already disposed shares and the sold lot's original purchase are not
    replacements. Proportional micro allocations reconcile cumulatively; an amount
    below supported precision raises rather than erasing a wash flag. Prior basis
    and tacking must already be reflected in the caller's executed loss evidence.
42. IRA/Roth replacement losses are permanent and do not increase retirement basis.
    Form 8949 exports matched sale slices with code W and positive adjustments.
    Column (b) uses actual acquisition date, separate from tacked holding duration.
    Unmatched shares remain separate broker reconciliation rows; these exports do
    not constitute a complete tax return or replace cross-account verification.
43. Settlement and wash dates use New York calendar dates; T+1 uses bounded XNYS
    sessions. Reconstructed sale proceeds and date-only funding evidence become
    usable at settlement-session close. Confirmed broker settled cash may establish
    earlier availability. Missing funding evidence WARNs a verifiable exit; a
    non-session or out-of-range settlement date is unverifiable and requests HALT.
44. INTRADAY_MARGIN is default. LEGACY_PDT remains an explicit broker-transition
    policy. The conservative counter maximizes distinct same-day opening orders
    touched by available closing shares, counting an opening order only once
    across partial sales. This upper bound can exceed a broker's actual method.
    Partial fills must first be consolidated into one executed-order TradeRecord.
    The legacy entry guard is inclusive at three completed day trades and applies
    below $25,000 in a margin account; exits retain WARN findings.
45. ComplianceEngine.check() preserves the specified list-of-RuleResult API.
    assess() adds frozen provenance, input_hash, and recommended_state. The full
    input hash binds proposal values, snapshot, lots, history, account taxonomy,
    flags, instruments, identical groups and restricted symbols. Settings retain
    the master settings-only config_hash. A malformed input can carry a zero
    digest only as restrictive HALTED failure evidence.
46. ComplianceBoundary persists broker/input/provider HALTs and logs every failed
    WARN or BLOCK outside pure rules. Ordinary cash/wash/restriction failures do
    not themselves halt. Valid, fresh held exits receive WARNs even on unknown
    tax/funding context; invalid or oversized sells do not get that exception.
    The later human gate must combine CRO/state and compliance evidence before
    authenticated fresh approval. No standalone compliance result authorizes a ticket.
26. APScheduler 3.11.3 is the stable installed release with AsyncIOScheduler;
    actual scheduling is deferred to Stage F. Full source delivery uses a local
    Markdown artifact: assumptions, SHA-256 manifest, then every file in full.
27. SQLite recursive triggers are explicitly enabled to prevent REPLACE from
    deleting/replacing protected rows. State-control projections are verified
    against immutable events during live reads/transitions, not only at startup.


## FILE MANIFEST

| File | Scope | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| .env.example | Stage C and referenced configuration | 2606 | d4665b19a70c0d2d776e1e0be4c1351003f7d286c91b4f679983bcbf964a41fb |
| .gitignore | Stage C and referenced configuration | 393 | a05c6036b9d2d5b14805ae732d49945770021b6974b04e310ab9077c1c1f3cb9 |
| .pre-commit-config.yaml | Stage C and referenced configuration | 911 | 6a3f557da9182d950e1cec0a18f24f69eb1a01825032e5c6c8087eaceab2820d |
| pyproject.toml | Stage C and referenced configuration | 2368 | 04a92c293bf601f525536463c20e5cb63b467604643b544da320421dca8e2be7 |
| requirements-lock.txt | Stage C and referenced configuration | 2123 | d465af53a4e8375afc2014db09889d14b4badfeb9a932fa5d3b344920273d5dc |
| .github/workflows/ci.yml | Stage C and referenced configuration | 2605 | 5d52f41da371a5331fdadd0ebc55f461352715a9aae1b78e5c536648bdd2b412 |
| README.md | Stage C and referenced configuration | 8011 | 8a8e61db3bf7dbe8218f059b1580ef24314c16ce6d9f997935071dc7c8079f0e |
| ASSUMPTIONS.md | Stage C and referenced configuration | 14297 | cd5fe10daaaa3008b2ec2ef5fda740ff0b0749203b78dc2abc081cd89b9d295d |
| VERIFY.md | Stage C and referenced configuration | 19167 | 441af347bf2a68ace65a50771cd1008109231554d36a729025781692a2fc29e2 |
| STAGE_C_SOURCE_NOTES.md | Stage C and referenced configuration | 4644 | ab524d7e59398618a9dca75b02410ed7e0c62ad642468ff7482118afe9dfcf0f |
| backend/core/check_stage_a.py | Stage C and referenced configuration | 1880 | 1fb4e8f146fc171bc40a071aa1f28d5cdb9dadd2e17e759a5b1fa41c113936ef |
| backend/core/check_stage_b.py | Stage C and referenced configuration | 1574 | 1cb98df34e1e402f67a9a599f3fcf54a14dc47d47d073d87eb2a3303d7acc6a9 |
| backend/core/check_stage_c.py | Stage C and referenced configuration | 1536 | f74fc2d08311d69981232b719935e09315e9e27f14c72a184adb8cb23c1ad308 |
| backend/domain/__init__.py | Stage C and referenced configuration | 82 | 75159c158cfe9b9ec1e4f7ec7eeb7b41d6666b253a09af5ac14f3288545edd7f |
| backend/domain/models.py | Stage C and referenced configuration | 19535 | df24b430981af747f3dd3a3a6be398043af3885fbeea9cc516d02ff932605824 |
| backend/domain/instruments.py | Stage C and referenced configuration | 12719 | df71caa90a340e8baeba32091f93ca858d6d286b109296c68968a32689c085aa |
| backend/domain/compliance_models.py | Stage C and referenced configuration | 6804 | 1268b2bbf88075e8b7679bd99187b27b1a7cad30c6cc25e09726e6bd596e354e |
| backend/risk/__init__.py | Stage C and referenced configuration | 68 | bed55df552c4aaba26164d22966cdfb9d8f2dca25ad9c293dc21147b55eb5220 |
| backend/risk/compliance.py | Stage C and referenced configuration | 32651 | bbd854922de0a78bc26c41c83fbb5b192a63ba0144ade73092ece79e04873352 |
| backend/risk/wash_sales.py | Stage C and referenced configuration | 14305 | 2dda3a48413732cf15c279acf95df2fe96179209d97bc7f618de48d306ce1faa |
| backend/risk/compliance_boundary.py | Stage C and referenced configuration | 8623 | 4a831a22612bfa40efd7048e66e53b0af02830c3e87064ac2ece6418fbd243e4 |
| backend/tests/test_compliance.py | Stage C and referenced configuration | 40301 | ce348476832c16f2eddac533e869d88d8da6e03c48c6524a6ad2c6fdafd2be2f |
| backend/tests/test_wash_sales.py | Stage C and referenced configuration | 20037 | ad6c63b160441b04f6573bd30bec16863d625e89746a7891abf6895f769e29e3 |
| backend/tests/test_compliance_boundary.py | Stage C and referenced configuration | 15156 | c4d7b7d6c9a10fb5d540f49283f11b763fbcdb55e92c1a3f94035d6cfe921e08 |
| backend/tests/test_stage_c_adversarial.py | Stage C and referenced configuration | 22995 | 8d72a33ba4eb96a190755fec64cb6fa1fccfc58cc3572fd3c0396b17a41a98b2 |
| config/config.yaml | Stage C and referenced configuration | 782 | 2714e63536baca5dd313596df9401ff5fa5e62a81358e35749a5f9e0a1ce3d0c |
| config/instruments.csv | Stage C and referenced configuration | 574 | 1d7f9d8750254079ead7e666ba4bbff5e6d270fa28c56511df361baaefb67e0f |
| config/etf_sector_weights.csv | Stage C and referenced configuration | 449 | 69f61d9c5cdb275b9fe4967acf38fe2688e0ad4f326e5ae7924bbc8a90ffe44e |
| config/substantially_identical.csv | Stage C and referenced configuration | 16 | c37995109bdb6b50a3cb83c024d1766379b2a41b7ceee5dea3084f6652afdfe2 |
| config/blackout_windows.csv | Stage C and referenced configuration | 24 | 56ea224a05617ca3033069d373ae86d2eeb1abdcb555abb4e91ff86fbe822143 |
| ../.github/workflows/ci.yml | Git-root mirror | 2605 | 5d52f41da371a5331fdadd0ebc55f461352715a9aae1b78e5c536648bdd2b412 |
| ../.pre-commit-config.yaml | Git-root mirror | 911 | 6a3f557da9182d950e1cec0a18f24f69eb1a01825032e5c6c8087eaceab2820d |
| ../.gitignore | Git-root mirror | 393 | a05c6036b9d2d5b14805ae732d49945770021b6974b04e310ab9077c1c1f3cb9 |

## FULL FILES

### .env.example

<!-- BEGIN FILE .env.example -->
````````text
# Development sample only. Loading this file is explicit; never commit a real .env.
PAPER_TRADING=true
LIVE_TRADING_ENABLED=false
LIVE_TRADING_CONFIRM=
BROKER_ACCOUNT_TYPE=CASH
BROKER_API_KEY=
BROKER_SECRET_KEY=
PLAID_ENV=sandbox
PLAID_CLIENT_ID=
PLAID_SECRET=
PLAID_ACCESS_TOKEN=
PLAID_ACCOUNT_ID=
FERNET_KEY=
# Optional encrypted Plaid token file; no token is printed or committed.
# PLAID_TOKEN_PATH=.secrets/plaid.token
DB_URL=sqlite:///vws-core.sqlite3
MAX_SINGLE_STOCK_WEIGHT=0.10
MAX_SINGLE_ETF_WEIGHT=0.40
MAX_RISK_PER_TRADE=0.01
STOP_SLIPPAGE_BUFFER=0.002
SECTOR_CAPS={"Information Technology":"0.35"}
THEME_CAPS={"AI_SEMIS":"0.25"}
MAX_OPEN_POSITIONS=15
MAX_GROSS_EXPOSURE=1.00
MIN_CASH_PCT=0.05
PRICE_COLLAR=0.03
MIN_PRICE=5.00
MAX_PCT_OF_ADV=0.01
DAILY_LOSS_LIMIT=0.02
DD_REDUCE_ONLY=0.08
DD_HALT=0.12
STALE_QUOTE_SECONDS=60
MAX_CLOCK_SKEW_SECONDS=2
GAP_ALERT_PCT=0.25
CHECKING_BUFFER_USD=1500
RESERVED_OBLIGATIONS_USD=[]
LIQUIDITY_TTL_SECONDS=900
WASH_SALE_MODE=BLOCK
DAY_TRADE_REGIME=INTRADAY_MARGIN
MIN_MARGIN_EQUITY=2000
REQUEST_TIMEOUT_SECONDS=30
EARNINGS_BLACKOUT_SESSIONS=2
MIN_SETUP_SCORE=7.0
MAX_ALERTS_PER_DAY=5
ALERT_COOLDOWN_SESSIONS=1
PROPOSAL_TTL_SESSIONS=1
ENABLE_INTRADAY_PLAYBOOKS=false

# Select one explicit HTTPS provider URL and set its matching credentials.
# VERIFY: https://docs.x.ai/developers/model-capabilities/text/generate-text
# LLM_BASE_URL=https://api.x.ai/v1
# VERIFY: https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk
# LLM_BASE_URL=https://api.anthropic.com/v1/
# VERIFY: https://developers.openai.com/api/reference/overview
# LLM_BASE_URL=https://api.openai.com/v1
# There is no default model. Choose an available model in your provider account.
# LLM_MODEL_NAME=
LLM_API_KEY=
LLM_TIMEOUT_SECONDS=30
LLM_MAX_TOKENS=1500
# Zero budget disables paid calls. Explicit verified cost rates are also required.
LLM_DAILY_BUDGET_USD=0
# LLM_INPUT_COST_PER_MILLION_USD=
# LLM_OUTPUT_COST_PER_MILLION_USD=
# JSON-mode capabilities differ; Stage E requests JSON in the prompt and validates it.

TELEGRAM_BOT_TOKEN=
# Keep unset for isolated Stage A. Connected Telegram requires a nonempty list.
# TELEGRAM_ALLOWED_USER_IDS=[]
# Connected mode requires a separate random secret of at least 32 UTF-8 bytes.
TELEGRAM_CALLBACK_SECRET=
NEWSAPI_KEY=
SCAN_INTERVAL_MINUTES=15
OFFHOURS_INTERVAL_MINUTES=60
SCHEDULER_MISFIRE_GRACE_SECONDS=60
# Completed daily SIP bars must be at least 15 minutes old.
DAILY_BAR_SIP_LAG_SECONDS=900

# Supported aliases (use canonical names above; do not set conflicting aliases):
# ALPACA_API_KEY=
# ALPACA_SECRET_KEY=
````````
<!-- END FILE .env.example -->

### .gitignore

<!-- BEGIN FILE .gitignore -->
````````text
.env
.env.*
!.env.example
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage*
htmlcov/
*.db
*.db-wal
*.db-shm
*.sqlite3
*.sqlite3-wal
*.sqlite3-shm
*.egg-info/
build/
dist/
.mutmut-cache/
mutants/
*.pem
*.key
*.token
*.fernet
.secrets/
audit-report.json
bandit-report.json
.hypothesis/
coverage.xml
coverage-stage-b.json
coverage-stage-c.json
secrets-report.json
````````
<!-- END FILE .gitignore -->

### .pre-commit-config.yaml

<!-- BEGIN FILE .pre-commit-config.yaml -->
````````yaml
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: Ruff lint
        entry: python -m ruff check
        language: system
        types: [python]
      - id: ruff-format
        name: Ruff format check
        entry: python -m ruff format --check
        language: system
        types: [python]
      - id: no-order-execution
        name: R-10 GD-07 source guard
        entry: python -m backend.core.source_guard .
        language: system
        pass_filenames: false
        always_run: true
      - id: stage-abc-types
        name: Stage A through C strict types
        entry: python -m backend.core.check_stage_c
        language: system
        pass_filenames: false
        types: [python]
      - id: detect-secrets
        name: Secrets scan
        entry: detect-secrets-hook
        language: system
        exclude: (^|/)(backend/tests/|requirements-lock\.txt$|deliveries/)
````````
<!-- END FILE .pre-commit-config.yaml -->

### pyproject.toml

<!-- BEGIN FILE pyproject.toml -->
````````toml
[build-system]
requires = ["setuptools==83.0.0"]
build-backend = "setuptools.build_meta"

[project]
name = "scalp-city-vws-core"
version = "0.1.0"
description = "Deterministic read-only trading defense and immutable audit ledger"
requires-python = ">=3.11"
dependencies = [
  "pydantic==2.13.5", "pydantic-settings==2.15.0", "SQLAlchemy==2.0.54",
  "alpaca-py==0.44.0", "plaid-python==45.0.0", "pandas==3.0.6",
  "exchange-calendars==4.13.2", "tenacity==9.1.4", "structlog==26.1.0",
  "cryptography==50.0.2", "requests==2.34.2", "tzdata==2026.5",
  "openai==3.24.0", "python-telegram-bot==22.8", "APScheduler==3.11.3",
  "httpx==0.28.1", "feedparser==6.0.14", "numpy==2.5.3", "PyYAML==6.0.3",
]

[project.optional-dependencies]
dev = [
  "pytest==9.1.1", "pytest-cov==7.1.0", "pytest-socket==0.8.1",
  "hypothesis==6.168.3", "mutmut==3.8.0", "ruff==0.16.10", "mypy==2.4.0",
  "pandas-stubs==3.0.5.260914", "bandit==1.9.4", "pip-audit==2.10.1",
  "detect-secrets==1.5.0", "pre-commit==4.6.2", "types-requests==2.32.4.20250913",
  "pytest-asyncio==1.4.0", "types-PyYAML==6.0.12.20260906",
]

[tool.setuptools.packages.find]
include = ["backend*"]

[tool.pytest.ini_options]
testpaths = ["backend/tests"]
addopts = "--disable-socket --strict-markers"
asyncio_mode = "strict"
asyncio_default_fixture_loop_scope = "function"
markers = ["integration: explicit paper-key integration checks (not run by default)"]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["backend", "scripts"]

[[tool.mypy.overrides]]
module = ["exchange_calendars.*", "alpaca.*", "plaid.*", "tenacity.*"]
ignore_missing_imports = true

[tool.coverage.run]
branch = true
source = ["backend.core.system_state", "backend.risk", "backend.domain.compliance_models"]

[tool.bandit]
exclude_dirs = ["backend/tests", ".venv", "mutants"]

[tool.mutmut]
source_paths = ["backend/risk/"]
also_copy = ["backend/core", "backend/data", "backend/domain", "backend/tests", "config", "scripts"]
pytest_add_cli_args_test_selection = ["backend/tests/test_risk_cro.py", "backend/tests/test_compliance.py", "backend/tests/test_wash_sales.py", "backend/tests/test_compliance_boundary.py", "backend/tests/test_stage_c_adversarial.py"]
pytest_add_cli_args = ["--disable-socket", "-q"]
````````
<!-- END FILE pyproject.toml -->

### requirements-lock.txt

<!-- BEGIN FILE requirements-lock.txt -->
````````text
alpaca-py==0.44.0
annotated-types==0.8.0
anyio==4.15.1
APScheduler==3.11.3
ast_serialize==0.12.1
bandit==1.9.4
boolean.py==5.0
CacheControl==0.14.4
certifi==2026.7.22
cffi==2.1.1
cfgv==3.5.0
charset-normalizer==3.5.2
click==8.5.0
colorama==0.4.6
coverage==7.16.2
cryptography==50.0.2
cyclonedx-python-lib==11.12.0
defusedxml==0.7.1
detect-secrets==1.5.0
distlib==0.4.3
exchange_calendars==4.13.2
feedparser==6.0.14
feedparser-sgmllib==2.1.0
filelock==4.0.10
greenlet==3.5.6
h11==0.16.0
httpcore==1.0.9
httpcore2==2.13.1
httpx==0.28.1
httpx2==2.13.1
hypothesis==6.168.3
identify==2.6.20
idna==3.20
iniconfig==2.3.0
jiter==0.17.0
korean_lunar_calendar==0.4.0
libcst==1.9.0
librt==0.16.0
license-expression==30.4.4
linkify-it-py==2.2.0
markdown-it-py==4.2.0
mdit-py-plugins==0.6.1
mdurl==0.1.2
msgpack==1.2.3
mutmut==3.8.0
mypy==2.4.0
mypy_extensions==1.1.0
nodeenv==1.11.0
nulltype==2.3.1
numpy==2.5.3
openai==3.24.0
packageurl-python==0.17.6
packaging==26.3
pandas==3.0.6
pandas-stubs==3.0.5.260914
pathspec==1.1.1
pip==26.2.1
pip-requirements-parser==32.0.1
pip_api==0.0.35
pip_audit==2.10.1
plaid-python==45.0.0
platformdirs==4.12.3
pluggy==1.6.0
pre_commit==4.6.2
py-serializable==2.1.0
pycparser==3.0
pydantic==2.13.5
pydantic-settings==2.15.0
pydantic_core==2.46.5
Pygments==2.21.0
pyluach==2.3.0
pyparsing==3.3.3
pytest==9.1.1
pytest-asyncio==1.4.0
pytest-cov==7.1.0
pytest-socket==0.8.1
python-dateutil==2.9.0.post0
python-discovery==1.6.1
python-dotenv==1.2.4
python-telegram-bot==22.8
pytz==2026.5
PyYAML==6.0.3
requests==2.34.2
rich==15.0.0
ruff==0.16.10
setproctitle==1.3.8
setuptools==83.0.0
six==1.17.0
sniffio==1.3.1
sortedcontainers==2.4.0
SQLAlchemy==2.0.54
sseclient-py==1.9.0
stevedore==5.9.1
structlog==26.1.0
tenacity==9.1.4
textual==8.2.8
tomli==2.4.1
tomli_w==1.2.0
toolz==1.1.0
truststore==0.10.4
types-PyYAML==6.0.12.20260906
types-requests==2.32.4.20250913
typing-inspection==0.4.4
typing_extensions==4.16.0
tzdata==2026.5
tzlocal==5.4.4
urllib3==2.8.0
virtualenv==21.14.5
websockets==17.2
````````
<!-- END FILE requirements-lock.txt -->

### .github/workflows/ci.yml

<!-- BEGIN FILE .github/workflows/ci.yml -->
````````yaml
name: Stage A through C defensive core
on: [push, pull_request]
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ${{ env.VWS_PROJECT_DIR || '.' }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Locate project
        working-directory: .
        run: |
          if [ -f pyproject.toml ]; then
            echo 'VWS_PROJECT_DIR=.' >> "$GITHUB_ENV"
          else
            echo 'VWS_PROJECT_DIR=vws-core' >> "$GITHUB_ENV"
          fi
      - name: Install exact dependencies
        run: python -m pip install --upgrade pip==26.2.1 && python -m pip install -r requirements-lock.txt && python -m pip install --no-deps -e .
      - name: Lint and format
        run: python -m ruff check . && python -m ruff format --check .
      - name: Strict Stage A through C typing
        run: python -m backend.core.check_stage_c
      - name: Execution source guard
        run: python -m backend.core.source_guard .
      - name: Security checks
        run: python -m bandit -r backend/core backend/domain backend/risk backend/data/market_calendar.py -c pyproject.toml && python -m pip_audit -r requirements-lock.txt --no-deps --disable-pip --progress-spinner off --timeout 15 && python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]' > /tmp/vws-secrets.json && python -c "import json; from pathlib import Path; findings=json.loads(Path('/tmp/vws-secrets.json').read_text())['results']; print(findings); assert not findings"
      - name: Stage A through C tests, network blocked, risk and state branch coverage 100%
        run: python -m pytest backend/tests/test_config_safety.py backend/tests/test_yaml_config.py backend/tests/test_money.py backend/tests/test_logging.py backend/tests/test_ledger.py backend/tests/test_research_ledger.py backend/tests/test_system_state.py backend/tests/test_market_calendar.py backend/tests/test_no_order_exec.py backend/tests/test_domain.py backend/tests/test_risk_cro.py backend/tests/test_risk_boundary.py backend/tests/test_stage_b_adversarial.py backend/tests/test_compliance.py backend/tests/test_wash_sales.py backend/tests/test_compliance_boundary.py backend/tests/test_stage_c_adversarial.py --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov-branch --cov-fail-under=100 --cov-report=term-missing
````````
<!-- END FILE .github/workflows/ci.yml -->

### README.md

<!-- BEGIN FILE README.md -->
````````markdown
# vws-core — Stages A through C

Read-only defensive infrastructure for long-only, whole-share research and human
trade tickets. Stage A supplies configuration guards, exact money/cent-price
helpers, UTC clocks, redacted logging, deduplicated notifications, XNYS sessions,
an immutable audit ledger, durable halt state, and an execution-code source guard.

Stage B adds frozen domain/research contracts, a validated instrument registry,
all thirteen deterministic CRO rules, sequential batch reservations, conservative
quantity suggestions, and RiskBoundary for persisted tiers and veto audit logs.
The Stage A/B offline suite passes 1,167 tests. The CRO, boundary, and state machine
each have 100% statement and branch coverage.

Stage C adds all seven pure compliance rules, exact wash-share allocation, tax
contracts, T+1 cash reconstruction, both day-trade regimes, reconciliation export,
and ComplianceBoundary for required HALTs and failed-finding audit logs.
The combined Stage A–C offline suite passes 1,441 tests; all risk modules, Stage C
contracts and the persisted state machine have 100% statement and branch coverage.

The research swarm and Telegram bot await later stages. Existing Stage D drafts and
core/gate.py from an older specification await their separate stage commands. The master project
is not finished. There is no broker order execution path.

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

## Verify Stages A through C

Activate the virtual environment, then use the same commands as CI:

```text
python -m ruff check .
python -m ruff format --check .
python -m backend.core.check_stage_c
python -m backend.core.source_guard .
python -m bandit -r backend/core backend/domain backend/risk backend/data/market_calendar.py -c pyproject.toml
python -m pip_audit -r requirements-lock.txt --no-deps --disable-pip --progress-spinner off --timeout 15
python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]'
python -m pytest backend/tests/test_config_safety.py backend/tests/test_yaml_config.py backend/tests/test_money.py backend/tests/test_logging.py backend/tests/test_ledger.py backend/tests/test_research_ledger.py backend/tests/test_system_state.py backend/tests/test_market_calendar.py backend/tests/test_no_order_exec.py backend/tests/test_domain.py backend/tests/test_risk_cro.py backend/tests/test_risk_boundary.py backend/tests/test_stage_b_adversarial.py backend/tests/test_compliance.py backend/tests/test_wash_sales.py backend/tests/test_compliance_boundary.py backend/tests/test_stage_c_adversarial.py --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov-branch --cov-fail-under=100 --cov-report=term-missing
```

On Windows `.venv\Scripts\python.exe -m` can replace python -m. The secrets scan
emits JSON; an empty results object is required. Synthetic tests and the full
source delivery are excluded from that heuristic scan, not from the AST guard.
The guard checks all authored Python files, with only its banned-list constants
module exempt. The pre-commit configuration provides the same local source checks.

The coverage gate applies to the completed state machine, all risk modules and
Stage C tax contracts. The master
coverage gate, callback mutation tests, offline end-to-end dry run, and Docker
build belong to later stages. PostgreSQL needs a driver/server for runtime checks;
this delivery exercises SQLite and does not claim a PostgreSQL server test.

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
settings = Settings()
engine = create_database(settings.db_url.get_secret_value())
create_schema(engine)
store = SystemStateStore(engine, SystemClock(), ConsoleNotifier())
print(store.current())
```

This initializes a local ledger and verifies chains before reading state. Existing
incompatible schemas fail without automatic migration. SystemStateStore.escalate
persists a halt; investigate its cause and verify the ledger before an attributed
operator_reset(operator_id, reason). Authentication for that administrative API
belongs to a future service boundary.

Use load_settings(env_file=...) only to deliberately read a private dotenv file.
load_yaml_config(path, allowed_symbols=..., settings=settings) validates YAML;
the symbol allowlist must come from the instrument source of truth.
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

See ASSUMPTIONS.md and VERIFY.md. The full manifest and untruncated source are in
deliveries/Stage_A.md, deliveries/Stage_B.md, and deliveries/Stage_C.md. Continue
with exactly Execute Stage D for data providers, indicators, and the scanner.
````````
<!-- END FILE README.md -->

### ASSUMPTIONS.md

<!-- BEGIN FILE ASSUMPTIONS.md -->
````````markdown
# ASSUMPTIONS

The newest master spec supersedes the earlier A–D blueprint and automatic
continuation request. The current command authorizes Stage C, with Stages A and B
already delivered. Stage D starts only after `Execute Stage D`. Order execution is permanently
absent; orders in the ledger are local proposal/audit records.

1. Financial inputs are exact decimal text, integers or Decimal. R-13 price
   boundaries specifically require positive Decimal cent prices; quantities are
   whole integers. Indicator math alone may use float64 in later stages.
2. Sub-cent proposed prices are rejected rather than silently rounded. General
   money, costs and balances retain millionths in signed 64-bit storage.
3. Settings never load a real `.env` implicitly. Secret-bearing database URLs are
   SecretStr. Their non-secret identity participates in configuration hashing.
4. Protective minima cannot be reduced below the blueprint defaults: the checking
   buffer, cash reserve, minimum price, slippage allowance and margin equity floor.
   Unspecified absolute bounds are documented in config source.
5. SQLite is the local default. PostgreSQL-compatible SQL, row locks and triggers
   are supplied; PostgreSQL runtime verification is separately reported.
6. Audit tables are append-only. Two deliberately mutable singleton rows allocate
   sequence numbers and project current operating state. Verification reconciles
   the projection with immutable transition events.
7. A database or notifier fault also latches the current process HALTED. Persisting
   a halt cannot be guaranteed while storage itself is unavailable; failure is
   surfaced and no approval can rely on that process state.
8. Only an attributed operator reset lowers a latched operating state. A recovered
   quote, restart or new session alone never clears a halt.
9. XNYS sessions are bounded by an explicit calendar range. Dates outside that
   range fail closed; timestamps at the exact close belong to a completed session.
   T+1 starts from a verified trading session, with holidays and early closes honored.
10. Supplied CSVs are sample configuration, not an authoritative production
    instrument universe or current ETF weights. Unknown instruments fail closed.
11. The checking-buffer gate caps new funding only. It never moves bank money and
    does not treat checking funds as already settled brokerage cash.
12. Valid held-position reductions bypass entry-specific market, funding and
    concentration checks. The HALTED/manual exception remains explicit.
13. A pure CRO returns decisions and evidence. Persistence, state escalation,
    notifications and veto logging happen in the enclosing gate.
14. Alpaca does not provide a settled-cash field in the required account contract.
    Cash-account purchases need an injected settlement ledger; absent proof means
    zero settled cash.
15. In the preserved Stage D draft, Plaid Balance is not a standalone Link/Sandbox initialization product. Sandbox
    setup uses the supported Auth entitlement to obtain an Item token; application
    runtime calls only the balance endpoint. No Auth data retrieval or funding exists.
16. The account-schema test fixture is synthetic and follows verified current
    fields. It is not misrepresented as a captured live account response. A genuine
    sanitized recording requires credentials and remains an integration check.

Stage-specific additions and unresolved verification items are recorded with each
delivery and in VERIFY.md.

17. Settings() permits isolated offline core tests without credentials. Connected
    startup must call assert_research_ready() and/or assert_telegram_ready(). The
    model, credentials, nonempty user allowlist, and >=32-byte callback secret
    have no usable offline defaults. No model name is hard-coded.
18. Zero LLM daily budget disables calls. Explicit verified input/output token
    rates plus assert_llm_call_budget_ready() are also required. Stage E implements
    actual calls and budget accounting; no cost is guessed.
19. Additional source bounds resolve unspecified ceilings conservatively: setup
    score 6..10, cooldown 1..30 sessions, LLM budget 0..1,000 USD/day, timeout 1..60
    seconds, max tokens 1..8,192. YAML is separate, frozen, exact Decimal, rejects
    risk keys/duplicates/anchors/aliases/oversize/depth >20, and requires an explicit
    instrument allowlist. Criterion weights support at most six decimal places.
    with_yaml_hash() combines the validated YAML with nonsecret environment policy.
20. Alert.id is the stable alert ID. PENDING means not yet delivered; an append-only
    AlertEvent SENT makes the awaiting-human alert actionable. This resolves the
    spec's ambiguous requirement that a delivered alert still be called PENDING.
    Terminal statuses are new events. Chat/message IDs belong to delivery evidence.
21. Manual approval and its ticket commit atomically; a unique alert FK makes
    tickets single-use. Exact ticket values come from the linked local proposal.
    Ledger.record_trade_ticket() is a low-level persistence primitive: Stage F
    must authenticate the human and revalidate fresh data before calling it.
22. Schema version 2 rejects old/incompatible databases; no silent migration is
    performed. Use a new development database or an explicitly reviewed migration.
    PostgreSQL is schema-compatible but no server runtime test is claimed.
    Administrators can disable triggers/rewrite evidence; this is not a claim of
    protection from a privileged database owner.
23. Every halt invokes a notifier. Repeated successful redacted state/reason
    messages are deduplicated for a local halt episode; failed delivery is retried.
    Daily-loss reduction remains latched until an explicit operator reset, a
    stricter interpretation of the spec's next-session recovery ambiguity.
24. The AST guard scans every authored Python file including tests/scripts/drafts;
    only execution_policy.py's banned-list constants are exempt. Generated virtual
    environments/caches/vendor dependencies are not authored repository sources.
    Builtin compile is banned; re.compile is permitted regex construction.
25. The older Stage D draft and core/gate.py are preserved, not certified against the new master spec.
    Minimal reflection/lint edits keep them compatible with the whole-source guard.
    The current Git root is Project V, so a root CI workflow mirrors the requested
    project workflow, pre-commit configuration, and .gitignore. These support
    nested or standalone project checkouts.

26. Stage B adds required proposal expires_at and optional target_price. An ENTRY
    or ADD target, when supplied, must exceed the limit. Prices require Decimal
    cents even in model validation; JSON/API adapters must decode exact Decimal
    values before entering these contracts. Float prices and sub-cent prices fail.
27. Existing Pydantic instances, including nested positions/orders, are revalidated
    at risk ingress. Policy and registry mappings are detached/revalidated at CRO
    construction. The service objects and compiled calendar are trusted injected
    dependencies; callers must not reassign their policy references during use.
28. High-water and daily-start marks must already be persisted and positive. Zero
    is missing evidence and recommends HALTED. First-run initialization belongs
    outside the pure CRO and must explicitly persist actual equity as the baseline.
29. Unconfigured known sectors use a 35% cap; unconfigured themes use zero. Unknown
    sectors block. An ETF with complete verified look-through to known sectors may
    have UNKNOWN declared sector; without weights its declared sector is 100%.
30. Pending BUY notional reserves concentration, gross exposure and cash. Pending
    SELL quantities reserve inventory and never release exposure before a fill.
    Same-name pending BUY stop risk uses its supplied stop; an absent stop reserves
    the full notional as loss. ADD also covers existing shares at the proposed stop.
31. max_allowed_qty is advisory and never exceeds requested qty. It finds the
    largest whole quantity satisfying complete CRO-02..08 evidence; it does not
    certify earnings, funding, operating state, or later compliance approval.
32. Unknown earnings is an explicit failed WARN. A known past date blocks as
    unresolved. A non-session earnings date includes the preceding exchange session
    plus the configured prior sessions. UTC blackout windows include both endpoints.
33. Verifiable exits bypass entry gates but still require matching accounts,
    live proposal lifetime, fresh inventory, and held minus pending SELL quantity.
    Snapshot freshness uses the quote TTL; stale holdings cannot prove held qty.
34. recommended_state is a typed Verdict extension carrying a pure CRO tier to
    RiskBoundary for persistence. A new financial HALT does not retroactively trap
    a valid held exit from a permitted starting state. Later HALTED calls require
    MANUAL source. A fatal batch result also gates subsequent entries in that batch.
35. RiskBoundary checks current state before and after evaluation, consumes the
    persisted escalation result, logs each blocking veto, and halts on any fault.
    Its Verdict is research evidence. The Stage F human gate still needs fresh
    revalidation and atomic state checks when writing alert/ticket evidence.
36. MarketContext carries no symbol field in the specified contract. Stage D's
    per-symbol provider must bind its returned market data to the requested symbol.
    Stage B never fetches data or substitutes default quote/funding evidence.
37. ProviderResult and research output contracts are present; actual providers,
    deterministic scanners, LLM clients, scheduler and Telegram await their stages.
    LLM contracts cannot set trade levels/qty or a CRO decision.

38. Stage C's account taxonomy attests accounts belonging to the same taxpayer.
    The supplied history must include relevant-window purchases/dispositions,
    DRIP, other accounts, and the original BUY for explicitly referenced lots.
    The software cannot discover omitted spouse/entity accounts or future trades.
    Substantially identical groups remain explicit operator-reviewed metadata.
39. TradeRecord.price remains strict Decimal cents; TaxLot.cost_basis, realized
    losses and adjusted tax basis retain micro-unit money. Prior adjustments can
    create fractional-cent basis, so basis is not silently rounded to a price.
    Fractional-share DRIP evidence is unverifiable under this whole-share contract.
40. A loss sale represents one original acquisition lot and attests its realized
    loss after previous basis adjustments. Aggregate multi-lot losses must be split.
    acquired_at is the actual purchase timestamp. An earlier holding_period_start
    represents prior tacking and requires acquisition_trade_id. Untacked origins
    absent from a relevant window can be attested older acquisitions; ambiguous
    missing lineage or simultaneous trades with unresolved disposal order fail.
41. Wash matching uses disjoint replacement-share intervals shared across loss
    sales. Already disposed shares and the sold lot's original purchase are not
    replacements. Proportional micro allocations reconcile cumulatively; an amount
    below supported precision raises rather than erasing a wash flag. Prior basis
    and tacking must already be reflected in the caller's executed loss evidence.
42. IRA/Roth replacement losses are permanent and do not increase retirement basis.
    Form 8949 exports matched sale slices with code W and positive adjustments.
    Column (b) uses actual acquisition date, separate from tacked holding duration.
    Unmatched shares remain separate broker reconciliation rows; these exports do
    not constitute a complete tax return or replace cross-account verification.
43. Settlement and wash dates use New York calendar dates; T+1 uses bounded XNYS
    sessions. Reconstructed sale proceeds and date-only funding evidence become
    usable at settlement-session close. Confirmed broker settled cash may establish
    earlier availability. Missing funding evidence WARNs a verifiable exit; a
    non-session or out-of-range settlement date is unverifiable and requests HALT.
44. INTRADAY_MARGIN is default. LEGACY_PDT remains an explicit broker-transition
    policy. The conservative counter maximizes distinct same-day opening orders
    touched by available closing shares, counting an opening order only once
    across partial sales. This upper bound can exceed a broker's actual method.
    Partial fills must first be consolidated into one executed-order TradeRecord.
    The legacy entry guard is inclusive at three completed day trades and applies
    below $25,000 in a margin account; exits retain WARN findings.
45. ComplianceEngine.check() preserves the specified list-of-RuleResult API.
    assess() adds frozen provenance, input_hash, and recommended_state. The full
    input hash binds proposal values, snapshot, lots, history, account taxonomy,
    flags, instruments, identical groups and restricted symbols. Settings retain
    the master settings-only config_hash. A malformed input can carry a zero
    digest only as restrictive HALTED failure evidence.
46. ComplianceBoundary persists broker/input/provider HALTs and logs every failed
    WARN or BLOCK outside pure rules. Ordinary cash/wash/restriction failures do
    not themselves halt. Valid, fresh held exits receive WARNs even on unknown
    tax/funding context; invalid or oversized sells do not get that exception.
    The later human gate must combine CRO/state and compliance evidence before
    authenticated fresh approval. No standalone compliance result authorizes a ticket.
26. APScheduler 3.11.3 is the stable installed release with AsyncIOScheduler;
    actual scheduling is deferred to Stage F. Full source delivery uses a local
    Markdown artifact: assumptions, SHA-256 manifest, then every file in full.
27. SQLite recursive triggers are explicitly enabled to prevent REPLACE from
    deleting/replacing protected rows. State-control projections are verified
    against immutable events during live reads/transitions, not only at startup.
````````
<!-- END FILE ASSUMPTIONS.md -->

### VERIFY.md

<!-- BEGIN FILE VERIFY.md -->
````````markdown
# Stage A through C verification — 2026-10-04

## Stage C result

The final combined selected Stage A–C suite passed **1,441 tests in 118.28 seconds**
on Windows and Python 3.12.14, with sockets blocked. Stage C adds 274 cases:
131 compliance-engine cases, 60 contract/matcher cases, 53 independent adversarial
cases, and 30 durable-boundary cases. Hypothesis exercises exact proportional
allocation and input faults in addition to the explicit boundary fixtures.

| Check | Observed result |
| --- | --- |
| Combined selected Stage A–C tests | 1,441 passed |
| Pure compliance engine | 100%; 300 statements, 106 branches |
| Wash-sale matcher | 100%; 164 statements, 66 branches |
| Compliance contracts | 100%; 104 statements, 28 branches |
| ComplianceBoundary | 100%; 80 statements, 26 branches |
| All risk modules, tax contracts and persisted state | 100%; 1,108 statements, 360 branches |
| Ruff lint/format | passed; 62 authored Python files formatted |
| Strict mypy | 56 source files passed; fixed Stage A–C gate passes 42 files |
| Whole authored-source execution guard | passed |
| Bandit completed core/domain/risk/calendar modules | zero findings |
| pip-audit all 109 exact transitive pins | no known vulnerabilities |
| pip check | no broken requirements |
| detect-secrets authored production files | zero findings |
| Actual parent Git-root pre-commit | all five hooks passed |

All seven CMP rules retain complete evidence. Existing instances and nested tax
history are revalidated; malformed inputs, calendar faults and missing/blocked
current broker flags request HALTED. Pure check() retains the specified list API;
assess() adds a frozen state recommendation and full input fingerprint. The
boundary checks proposal/snapshot/config/time/input binding and rule severities,
persists HALTs and logs every failed WARN or BLOCK with rule/proposal IDs.
Cached same-ID evidence cannot be reused after changing quantity, price, history,
accounts, flags or policy. Ordinary cash/wash/restriction failures do not halt.

Wash matching allocates disjoint replacement-share intervals, excludes original
and disposed shares, and reconciles partial losses exactly at micro precision.
Tests include the IRS partial-share example, inclusive day-30/day-31 endpoints,
overlapping loss sales, retirement-account permanent losses, basis adjustments,
DST holding-period tacking, original-acquisition lineage and actual Form 8949
acquisition dates. Prior adjusted basis/loss evidence is caller-attested; exports
cover matched sale slices and require separate unmatched-share reconciliation.

T+1 and five-session windows honor New York trade dates, XNYS holidays and early
closes. Date-only funding evidence is conservative through session close; missing
funding evidence WARNs a verifiable exit. Legacy counting uses a documented upper
bound on distinct opening orders touched by closing shares, with one count per
order across partial fills/sales. It is an operator transition guard rather than
a claim to reproduce every broker's method. Valid held exits receive WARNs;
invalid, stale or oversized sells do not qualify for that exception.

| Requirement | Implementation | Tests |
| --- | --- | --- |
| CMP-01/02, R-04/05/13 | validated tax contracts; disjoint proportional wash matching | test_compliance; test_wash_sales; test_stage_c_adversarial |
| CMP-02 basis/tacking/export | original BUY lineage; separate actual/tacked dates; positive code W | IRS golden, partial/DST/tacked-lot/export regressions |
| CMP-03 | settled cash reconstruction, pending reserves, conservative T+1 funding | exact-cent, close/holiday/early-close, unknown funding cases |
| CMP-04 | cash reservation and inclusive margin-equity floor | $2k/$5k/$25k/$100k and one-cent boundaries |
| CMP-05 | INTRADAY_MARGIN default and explicit legacy guard | five sessions, equity/count boundaries, independent/partial/equal-time orders |
| CMP-06 | explicit current AccountFlags; pure HALT recommendation; durable boundary | each flag/missing flag, restart, provider/clock/DB/audit faults |
| CMP-07 | detached allowlist/identical groups/restricted symbols | unknown/leveraged/inverse/restricted metadata and forged registry |
| R-02/03/09 | full input fingerprint, immutable assessment, exit WARN policy | forged/replayed assessment, expired/stale/oversized exit, deterministic checks |
| R-08/10, GD-07 | no external execution path; all-source guard | CLI, full safety suite, pre-commit |

[STAGE_C_SOURCE_NOTES.md](STAGE_C_SOURCE_NOTES.md) records the verified IRS,
SEC, FINRA and Alpaca links and distinguishes source requirements from software
assumptions. No broker/bank request, transfer, LLM call or Telegram message was
sent. There are no new dependencies. PostgreSQL runtime, Docker, full pipeline,
mutation score and later D–F features remain outside this certification. The
historical Stage A/B delivery artifacts are retained unchanged.

## Stage B result

Stage B completed locally on Windows, Python 3.12.14. The combined selected
Stage A/B suite passed **1,167 tests in 77.13 seconds**, with sockets blocked.
This adds 322 Stage B cases, including Hypothesis-generated boundary inputs,
forged Pydantic instances, provider/DB/calendar/audit faults, and independent
regressions. It does not certify the preserved C–D drafts or later services.

| Check | Observed result |
| --- | --- |
| Combined Stage A/B tests | 1,167 passed |
| Pure CRO coverage | 100%; 217 statements, 56 branches |
| RiskBoundary coverage | 100%; 80 statements, 32 branches |
| Persisted state coverage | 100%; 163 statements, 46 branches |
| Ruff lint and format | passed; 53 authored Python files formatted |
| Strict mypy | 49 source files passed; fixed Stage A/B gate passes 33 files |
| Whole authored-source execution guard | passed |
| Bandit completed A/B modules | zero findings |
| pip-audit exact transitive lock | no known vulnerabilities; all 109 pinned entries audited |
| pip check | no broken requirements |
| detect-secrets authored production files | zero findings |
| Parent Git-root pre-commit | all five hooks passed |

The immutable domain requires cent-priced Decimal values and explicit proposal
expiry. Revalidation rejects model_construct/model_copy bypasses in proposals,
holdings, pending orders, and policy/registry metadata. Risk rules return complete
unique evidence, honor WARN versus BLOCK, reserve pending notional and same-name
stop risk, and return monotone batch state recommendations. Quantity advice is
bounded at requested size and requires complete sizing evidence.

RiskBoundary verifies the ledger and state, binds approval evidence to proposal,
snapshot, policy and time, persists financial tiers, and logs every blocking veto
using rule/proposal IDs. Faults log a static error type, halt, and raise typed
DataIntegrityError. An audit logger fault still triggers HALT. Financial HALT
detection does not retroactively trap a permitted held exit; subsequent calls
use the persisted HALTED/manual gate. The later human approval service still
requires fresh data and atomic state checks at alert/ticket writes.

| Requirement | Implementation | Tests |
| --- | --- | --- |
| R-01..05, R-13 | frozen/revalidated models, cent-price ingress, canonical hashes | test_domain; test_stage_b_adversarial |
| CRO-01/02, R-09 | state/shape/account/lifetime/inventory rules; exit bypass | test_risk_cro; test_risk_boundary; test_stage_b_adversarial |
| CRO-03/04 | name caps, slippage/stop risk, ADD and pending BUY risk | test_risk_cro property/boundary cases; independent regressions |
| CRO-05 | frozen registry, ETF look-through, sector/theme caps | test_domain; test_risk_cro; independent unknown-sector case |
| CRO-06 | pending gross/name/cash caps; sequential batches | test_risk_cro batch/property cases |
| CRO-07/08 | exact collar, min price, calendar freshness, ADV cap | test_risk_cro; independent precision/freshness cases |
| CRO-09/10 | pure recommended_state; persistence/logging outside CRO | test_risk_cro; test_risk_boundary; test_system_state |
| CRO-11/13 | inclusive UTC windows and exchange-session earnings | test_risk_cro; independent holiday/early-close/date faults |
| CRO-12 | explicit available funding; exits bypass unavailable funding | test_risk_cro; independent exit faults |
| R-02, GD-07 | audited fail-closed boundary; all-source guard | test_risk_boundary; test_no_order_exec |
| R-11/12, GD-03 contracts | typed provider/research outputs without LLM trade authority | test_domain; implementations await D/E/F |

The Stage B runner reuses the already verified mypy API contract and Stage A
source list. No dependencies changed. Sample CSVs remain demonstration metadata.
The transitive lock is audited with --no-deps --disable-pip; every entry is exactly
pinned and pip check independently verifies the installed dependency relationships.
PostgreSQL, Docker, real providers and end-to-end Telegram remain unverified.
The final project's mutation score gate awaits its completion stage; no mutation
score is claimed for this native Windows run. The historical Stage A full-source
delivery is retained unchanged.

## Historical Stage A result

Stage A completed locally on Windows, Python 3.12.14, with network sockets blocked
for unit tests. The larger master project and later-stage drafts are not certified
by this delivery. CI is configured; no remote GitHub run is claimed.

| Check | Observed result |
| --- | --- |
| Selected Stage A pytest suite | 845 passed in 66.41 seconds |
| system_state statement and branch coverage | 100%; 163 statements, 46 branches |
| Whole authored-source execution guard | passed; 141 positive/control scanner cases |
| Ruff lint and formatting | passed |
| Strict mypy | all 45 source files passed; portable Stage A gate passes 22 files including its runner |
| Bandit Stage A scan | zero findings |
| pip-audit exact transitive lock | no known vulnerabilities |
| pip check | no broken requirements |
| detect-secrets authored production files | zero findings; generated caches and synthetic fixtures excluded |
| pre-commit hooks from actual parent Git root | all five hooks passed |
| Example configuration smoke check | .env.example loads in paper mode; YAML watchlist is a subset of instruments.csv |

Commands are recorded in README.md and .github/workflows/ci.yml. The type runner
uses the documented mypy API with fixed source paths and no subprocess shell.
A single Bandit B506 annotation applies to a SafeLoader subclass, which rejects
unsafe tags, aliases, duplicate keys, oversized content, and excessive depth.

The security review found and fixed malformed financial inputs failing to halt,
unsafe object repr logging, state projection tampering, SQLite REPLACE bypasses,
invalid alert/approval chronology, and several AST reflection/endpoint wrappers.
The ledger suites exercise ORM and raw SQL barriers across 18 immutable tables,
foreign keys and enums, hash/provenance replay, atomic ticket rollback/replay,
expiry boundaries, and concurrent single-use tickets.

PostgreSQL DDL/locks have not run against a server. Real broker, bank, LLM, or
Telegram connectivity has not been exercised. No real secrets were used. Stage F
must authenticate/HMAC-bind callbacks and revalidate fresh data before calling the
trusted local ticket persistence API. The AST guard is a source policy, not an OS
sandbox; privileged database administrators remain outside its trust boundary.

## Stage A traceability

| Requirement | Implementation | Tests |
| --- | --- | --- |
| R-01, R-13 | money.validate_cent_price; database.PriceType; ledger proposal/fill/ticket shape | test_money, test_ledger, test_research_ledger |
| R-02 | typed errors; durable state/latch; database transactions; schema version; integrity replay | test_system_state, test_ledger, test_research_ledger, test_market_calendar |
| R-03 | frozen policy and canonical config/YAML hashes; financial_state pure helper | test_config_safety, test_yaml_config, test_system_state |
| R-04 | Decimal helpers and MoneyType integer millionths | test_money, test_ledger, test_research_ledger |
| R-05 | injected Clock, ensure_utc, UTCDateTime, bounded XNYS schedule | test_ledger, test_system_state, test_market_calendar |
| R-06 | paper defaults, four-condition live guard, resolved broker endpoint checks | test_config_safety |
| R-07 | SecretStr, redacted typed errors/logs, no implicit dotenv, ignore files | test_config_safety, test_logging; secrets hook/scan |
| R-08, R-10, GD-07 | source_guard; no execution APIs in authored code | test_no_order_exec; CLI and pre-commit source guard |
| R-09, CRO-01 | persisted state gate including manual halt exits | test_system_state; held-quantity rules deferred to Stage B |
| R-14 storage foundation | immutable alert delivery/approval events; unique atomic tickets | test_research_ledger; callback auth deferred to Stage F |
| CRO-09, CRO-10 foundation | exact financial tiers, HWM cash-flow scaling, audited reset | test_system_state, test_ledger |
| DAT-01, CMP-03 foundation | XNYS UTC session/holiday/DST/early-close semantics | test_market_calendar |
| GD-01/GD-02 configuration foundation | connected readiness, budget/rate guards, strict YAML | test_config_safety, test_yaml_config; clients deferred to Stage E |

## External contract references

| Contract | Primary reference | Evidence scope |
| --- | --- | --- |
| pydantic-settings v2 | https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ | official docs and installed isolated tests |
| SQLAlchemy typed custom storage | https://docs.sqlalchemy.org/en/20/core/custom_types.html | installed ORM/bind/read tests |
| SQLAlchemy mapper guards | https://docs.sqlalchemy.org/en/20/orm/events.html | installed ORM mutation tests |
| SQLite recursive triggers and REPLACE | https://www.sqlite.org/lang_conflict.html and https://www.sqlite.org/pragma.html#pragma_recursive_triggers | official docs; all-table REPLACE regressions |
| XNYS calendar | https://github.com/gerrymanoim/exchange_calendars | pinned package; session/DST/holiday tests |
| OpenAI base URL | https://developers.openai.com/api/reference/overview | example configuration only; no API call |
| xAI OpenAI-compatible base URL | https://docs.x.ai/developers/model-capabilities/text/generate-text | example configuration only; no API call |
| Anthropic compatibility/base URL | https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk | supports compatibility layer with differences; no API call |
| AsyncIOScheduler 3.x | https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/asyncio.html | stable 3.11.3 pin; scheduler deferred to F |
| mypy programmatic gate | https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application | installed API and root-hook verification |

Provider response-format support differs. The future client requests JSON in the
prompt and validates it with Pydantic; no response_format assumption is baked in.
No provider-specific model or token price is supplied by default.

## Complete VERIFY tag inventory

Tags in the preserved Stage D draft are historical references, not certification
of that draft. The completed A–C tags and earlier references are collected from
current source locations below. External source scope is described above and in
STAGE_C_SOURCE_NOTES.md.

| Location | Reference |
| --- | --- |
| .env.example:50 | https://docs.x.ai/developers/model-capabilities/text/generate-text |
| .env.example:52 | https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk |
| .env.example:54 | https://developers.openai.com/api/reference/overview |
| backend/core/check_stage_a.py:40 | https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application |
| backend/core/check_stage_b.py:31 | https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application |
| backend/core/check_stage_c.py:29 | https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application |
| backend/data/broker_state.py:87 | https://github.com/alpacahq/alpaca-py/blob/master/alpaca/common/rest.py |
| backend/data/broker_state.py:104 | https://github.com/alpacahq/alpaca-py/blob/master/alpaca/common/rest.py |
| backend/data/broker_state.py:141 | https://alpaca.markets/sdks/python/api_reference/trading_api.html |
| backend/data/broker_state.py:167 | https://alpaca.markets/sdks/python/api_reference/trading/account.html |
| backend/data/broker_state.py:170 | https://alpaca.markets/sdks/python/api_reference/trading/orders.html |
| backend/data/broker_state.py:174 | https://alpaca.markets/sdks/python/api_reference/trading/clock.html |
| backend/data/data_layer.py:436 | https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html |
| backend/data/data_layer.py:449 | https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html |
| backend/data/data_layer.py:492 | https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html |
| backend/data/liquidity.py:105 | https://github.com/plaid/plaid-python#usage |
| backend/data/liquidity.py:125 | https://plaid.com/docs/api/accounts/#accountsbalanceget |
| backend/data/liquidity.py:132 | https://github.com/plaid/plaid-python/blob/master/plaid/api_client.py |
| backend/data/market_calendar.py:45 | https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/calendar_utils.py |
| backend/data/market_calendar.py:108 | https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/exchange_calendar.py |
| backend/data/market_calendar.py:125 | https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/exchange_calendar.py |
| backend/risk/compliance.py:147 | https://www.sec.gov/resources-for-investors/investor-alerts-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor-bulletin |
| backend/risk/compliance.py:251 | https://www.irs.gov/publications/p550 |
| backend/risk/compliance.py:252 | https://www.irs.gov/pub/irs-drop/rr-08-05.pdf |
| backend/risk/compliance.py:258 | https://www.irs.gov/instructions/i8949 |
| backend/risk/compliance.py:701 | https://syndication.finra.org/content/understanding-new-intraday-margin-requirements |
| backend/risk/compliance.py:702 | https://www.finra.org/rules-guidance/guidance/interps-4210 |
| backend/risk/compliance.py:781 | https://docs.alpaca.markets/us/reference/getaccount-1 |
| backend/risk/wash_sales.py:67 | https://www.irs.gov/publications/p550 |
| backend/risk/wash_sales.py:68 | https://www.irs.gov/pub/irs-drop/rr-08-05.pdf |
| backend/risk/wash_sales.py:283 | https://www.irs.gov/instructions/i8949 |
| scripts/plaid_sandbox_token.py:62 | https://github.com/plaid/plaid-python#usage |
| scripts/plaid_sandbox_token.py:72 | https://plaid.com/docs/api/sandbox/#sandboxpublic_tokencreate |
| scripts/plaid_sandbox_token.py:73 | https://plaid.com/docs/balance/ (Balance is not standalone.) |
| scripts/plaid_sandbox_token.py:83 | https://plaid.com/docs/api/items/#itempublic_tokenexchange |
````````
<!-- END FILE VERIFY.md -->

### STAGE_C_SOURCE_NOTES.md

<!-- BEGIN FILE STAGE_C_SOURCE_NOTES.md -->
````````markdown
# Stage C primary-source verification

Verified on October 4, 2026. These notes describe source scope and the software's conservative policies; they are not a filing determination.

- **CMP-01/CMP-02:** [IRS Publication 550](https://www.irs.gov/publications/p550), currently the 2025 edition, describes the inclusive 30-calendar-day window on either side of a loss sale, acquisition-order proportional share matching, replacement basis adjustment, and holding-period tacking. The implementation uses explicit operator-supplied substantially identical groups and account classifications. It cannot discover omitted accounts, spouse transactions, corporate actions, or future purchases. Example 1 under “More or less stock bought than sold” supplies the independent $750 partial-match golden fixture. Disposed original shares cannot serve as their own replacement. Previously tacked lots require an acquisition ID and its purchase record; untacked holding-start metadata without an ID attests the actual purchase timestamp.
- **CMP-01/CMP-02:** [Revenue Ruling 2008-5](https://www.irs.gov/pub/irs-drop/rr-08-05.pdf) addresses a taxable loss followed by substantially identical purchases in the individual's IRA or Roth IRA. It disallows the loss without increasing retirement-account basis. The ruling expressly confines its scope and does not determine prohibited-transaction issues.
- **CMP-02:** [2025 Form 8949 instructions](https://www.irs.gov/instructions/i8949) require code W and a positive nondeductible loss adjustment in column (g). Column (b) uses the actual acquisition trade date, independently of a tacked holding-period start. The implementation exports matched sale slices for reconciliation. A complete tax return requires all transactions, including unmatched shares and applicable broker records; a 1099-B can omit cross-account wash sales.
- **CMP-03:** The [SEC T+1 investor bulletin](https://www.sec.gov/resources-for-investors/investor-alerts-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor-bulletin) states that applicable transactions from May 28, 2024 settle one business day after the trade date. The software uses bounded XNYS sessions and New York trade dates. In reconstructed cash history, proceeds become usable at the settlement session close unless a reconciled broker snapshot confirms them sooner. That close-time convention is a conservative software assumption, not an SEC-mandated intraday settlement hour.
- **CMP-03/CMP-05:** [FINRA's current intraday-trading explanation](https://syndication.finra.org/content/frequent-intraday-trading-understanding-basics) distinguishes freeriding from selling securities funded by proceeds that have not settled. Missing funding evidence produces an exit warning; it never silently proves settlement.
- **CMP-05:** [FINRA Notice 26-10](https://www.finra.org/rules-guidance/notices/26-10), published April 20, 2026, sets June 4, 2026 as the new intraday-margin effective date and permits firm phase-in until October 20, 2027. INTRADAY_MARGIN is the default. LEGACY_PDT is an explicit operator-selected transition guard; it is not inferred from deleted broker fields. The [historical Rule 4210 interpretations](https://www.finra.org/rules-guidance/guidance/interps-4210) describe multiple counting methods. The software counts the maximum plausibly touched independent opening purchase orders, allocating at least one sold share to each previously uncounted available order before extra shares. One opening order is counted once across partial sells; tied times conservatively place purchases first. Callers must consolidate partial fills belonging to the same executed order. This is a conservative operator guard, and can exceed a broker's authoritative count.
- **CMP-06:** Alpaca's [current account documentation](https://docs.alpaca.markets/us/docs/account-plans) supplies the trading, account, and user-suspension flags and account status. Its [June 3, 2026 changelog](https://docs.alpaca.markets/us/changelog/2026-06-03-pdt-f3c04da) and [intraday-margin migration notice](https://alpaca.markets/blog/finra-retires-the-pdt-rule-introducing-alpacas-new-intraday-margin-framework/) confirm July 6, 2026 field removal. Some Python SDK reference pages still show optional historical fields; current REST documentation and the migration notices control the adapter contract. Stage C performs no broker request.

No source discrepancy requires changing the user's October 2026 regime defaults. Broker transition choice, unknown funding evidence, reconstructed settlement timing, and incomplete tax history remain explicit conservative policies.
````````
<!-- END FILE STAGE_C_SOURCE_NOTES.md -->

### backend/core/check_stage_a.py

<!-- BEGIN FILE backend/core/check_stage_a.py -->
````````python
"""R-02/R-10: portable Stage A strict-type gate for CI and Git-root hooks."""

import sys
from pathlib import Path

from mypy import api

from backend.core.errors import ConfigurationError

TYPE_FILES = (
    "backend/core/check_stage_a.py",
    "backend/core/config.py",
    "backend/core/clock.py",
    "backend/core/errors.py",
    "backend/core/money.py",
    "backend/core/logging.py",
    "backend/core/notifier.py",
    "backend/core/database.py",
    "backend/core/ledger.py",
    "backend/core/system_state.py",
    "backend/core/source_guard.py",
    "backend/core/execution_policy.py",
    "backend/data/market_calendar.py",
    "backend/tests/test_config_safety.py",
    "backend/tests/test_yaml_config.py",
    "backend/tests/test_money.py",
    "backend/tests/test_logging.py",
    "backend/tests/test_ledger.py",
    "backend/tests/test_research_ledger.py",
    "backend/tests/test_system_state.py",
    "backend/tests/test_market_calendar.py",
    "backend/tests/test_no_order_exec.py",
)


def main() -> int:
    """R-02: run the fixed check in its project, even from the parent Git root."""
    project = Path(__file__).resolve().parents[2]
    try:
        # VERIFY: https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application
        stdout, stderr, status = api.run(
            [
                "--strict",
                "--config-file",
                str(project / "pyproject.toml"),
                "--cache-dir",
                str(project / ".mypy_cache"),
                *(str(project / path) for path in TYPE_FILES),
            ]
        )
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        return status
    except Exception as exc:
        raise ConfigurationError("Stage A type checker could not start") from exc


if __name__ == "__main__":
    raise SystemExit(main())
````````
<!-- END FILE backend/core/check_stage_a.py -->

### backend/core/check_stage_b.py

<!-- BEGIN FILE backend/core/check_stage_b.py -->
````````python
"""R-02/R-10: portable strict typing for completed Stages A and B."""

import sys
from pathlib import Path

from mypy import api

from backend.core.check_stage_a import TYPE_FILES as STAGE_A_TYPE_FILES
from backend.core.errors import ConfigurationError

TYPE_FILES = (
    *STAGE_A_TYPE_FILES,
    "backend/core/check_stage_b.py",
    "backend/domain/__init__.py",
    "backend/domain/models.py",
    "backend/domain/instruments.py",
    "backend/risk/__init__.py",
    "backend/risk/risk_cro.py",
    "backend/risk/boundary.py",
    "backend/tests/test_domain.py",
    "backend/tests/test_risk_cro.py",
    "backend/tests/test_risk_boundary.py",
    "backend/tests/test_stage_b_adversarial.py",
)


def main() -> int:
    """R-02: fixed source paths work from a nested or standalone Git checkout."""
    project = Path(__file__).resolve().parents[2]
    try:
        # VERIFY: https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application
        stdout, stderr, status = api.run(
            [
                "--strict",
                "--config-file",
                str(project / "pyproject.toml"),
                "--cache-dir",
                str(project / ".mypy_cache"),
                *(str(project / path) for path in TYPE_FILES),
            ]
        )
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        return status
    except Exception as exc:
        raise ConfigurationError("Stage A/B type checker could not start") from exc


if __name__ == "__main__":
    raise SystemExit(main())
````````
<!-- END FILE backend/core/check_stage_b.py -->

### backend/core/check_stage_c.py

<!-- BEGIN FILE backend/core/check_stage_c.py -->
````````python
"""R-02/R-10: portable strict typing for completed Stages A through C."""

import sys
from pathlib import Path

from mypy import api

from backend.core.check_stage_b import TYPE_FILES as STAGE_B_TYPE_FILES
from backend.core.errors import ConfigurationError

TYPE_FILES = (
    *STAGE_B_TYPE_FILES,
    "backend/core/check_stage_c.py",
    "backend/domain/compliance_models.py",
    "backend/risk/compliance.py",
    "backend/risk/wash_sales.py",
    "backend/risk/compliance_boundary.py",
    "backend/tests/test_compliance.py",
    "backend/tests/test_wash_sales.py",
    "backend/tests/test_compliance_boundary.py",
    "backend/tests/test_stage_c_adversarial.py",
)


def main() -> int:
    """R-02: fixed verified source paths work from either Git layout."""
    project = Path(__file__).resolve().parents[2]
    try:
        # VERIFY: https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application
        stdout, stderr, status = api.run(
            [
                "--strict",
                "--config-file",
                str(project / "pyproject.toml"),
                "--cache-dir",
                str(project / ".mypy_cache"),
                *(str(project / path) for path in TYPE_FILES),
            ]
        )
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        return status
    except Exception as exc:
        raise ConfigurationError("Stage A-C type checker could not start") from exc


if __name__ == "__main__":
    raise SystemExit(main())
````````
<!-- END FILE backend/core/check_stage_c.py -->

### backend/domain/__init__.py

<!-- BEGIN FILE backend/domain/__init__.py -->
````````python
"""R-01/R-02/R-03/R-04/R-05/R-11/R-13: immutable defensive/research contracts."""
````````
<!-- END FILE backend/domain/__init__.py -->

### backend/domain/models.py

<!-- BEGIN FILE backend/domain/models.py -->
````````python
"""R-01/R-02/R-04/R-05/R-11/R-13: frozen contracts for trading and research."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Generic, Self, TypeVar, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.core.money import MoneyInput, decimal_money, validate_cent_price
from backend.core.system_state import SystemState

_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,14}$")


def _exact_money(value: object) -> Decimal:
    """R-04: reject float, bool, NaN and sub-micro-unit money at ingress."""
    try:
        return decimal_money(cast(MoneyInput, value))
    except DataIntegrityError as exc:
        raise ValueError(str(exc)) from exc


def _aware_utc(value: object) -> datetime:
    """R-05: the boundary requires an aware datetime and normalizes to UTC."""
    try:
        return ensure_utc(cast(datetime, value))
    except DataIntegrityError as exc:
        raise ValueError(str(exc)) from exc


def _cent_price(value: object) -> Decimal:
    """R-13: only exact positive Decimal cent prices cross module boundaries."""
    try:
        return validate_cent_price(cast(Decimal, value))
    except DataIntegrityError as exc:
        raise ValueError(str(exc)) from exc


def _session_date(value: object) -> date:
    """R-05/CRO-13: earnings are calendar dates, never guessed timestamps."""
    if type(value) is not date:
        raise ValueError("earnings date must be an explicit calendar date")
    return value


def _sentiment_score(value: object) -> Decimal:
    """R-11: finite exact sentiment is clamped to the stated advisory range."""
    amount = _exact_money(value)
    return max(Decimal("-5"), min(Decimal("5"), amount))


def validate_symbol(value: str) -> str:
    """R-02: symbols must already be unambiguous uppercase US ticker labels."""
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError("symbol must be an uppercase US ticker label")
    return value


Money = Annotated[Decimal, BeforeValidator(_exact_money)]
Price = Annotated[Decimal, BeforeValidator(_cent_price)]
UTCDateTime = Annotated[datetime, BeforeValidator(_aware_utc)]
SessionDate = Annotated[date, BeforeValidator(_session_date)]
PositiveQty = Annotated[int, Field(strict=True, gt=0)]
NonnegativeQty = Annotated[int, Field(strict=True, ge=0)]
Symbol = Annotated[str, BeforeValidator(validate_symbol)]
Identifier = Annotated[str, Field(strict=True, min_length=1)]


class AssetClass(StrEnum):
    STOCK = "STOCK"
    BROAD_ETF = "BROAD_ETF"
    SECTOR_ETF = "SECTOR_ETF"
    COMMODITY_ETF = "COMMODITY_ETF"
    CASH_EQUIV = "CASH_EQUIV"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Intent(StrEnum):
    ENTRY = "ENTRY"
    ADD = "ADD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


class ProposalSource(StrEnum):
    SIGNAL = "SIGNAL"
    SYSTEM = "SYSTEM"
    MANUAL = "MANUAL"


class AccountType(StrEnum):
    CASH = "CASH"
    MARGIN = "MARGIN"


class MarketStatus(StrEnum):
    OK = "OK"
    SUSPECT = "SUSPECT"


class CapitalStatus(StrEnum):
    OK = "OK"
    BUFFER_BREACH = "BUFFER_BREACH"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


class Severity(StrEnum):
    BLOCK = "BLOCK"
    WARN = "WARN"


class Decision(StrEnum):
    APPROVED = "APPROVED"
    VETOED = "VETOED"


class DayTradeRegime(StrEnum):
    INTRADAY_MARGIN = "INTRADAY_MARGIN"
    LEGACY_PDT = "LEGACY_PDT"


class ProviderStatus(StrEnum):
    """R-02/R-11: unavailable research cannot be inferred to be positive."""

    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class Playbook(StrEnum):
    """R-11/GD-03: code chooses the setup playbook."""

    TREND_50EMA = "TREND_50EMA"
    BASE_BREAKOUT = "BASE_BREAKOUT"
    ANCHORED_VWAP_RECLAIM = "ANCHORED_VWAP_RECLAIM"
    INTRADAY_ORB = "INTRADAY_ORB"
    INTRADAY_VWAP_RECLAIM = "INTRADAY_VWAP_RECLAIM"


class SentimentClassification(StrEnum):
    """R-11: sentiment context does not decide a proposal or risk verdict."""

    THESIS_CHANGING = "THESIS_CHANGING"
    CONFIRMING = "CONFIRMING"
    NOISE = "NOISE"


class FrozenModel(BaseModel):
    """R-02/R-03: unexpected fields and mutation cannot silently change rules."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        revalidate_instances="always",
    )

    @field_validator("*", mode="after")
    @classmethod
    def nonblank_strings(cls, value: object) -> object:
        """R-02: whitespace-only identifiers are unverifiable state."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("text fields cannot be blank")
        return value


class Instrument(FrozenModel):
    """R-01/CRO-02/CRO-05: explicit, allowlisted instrument metadata."""

    symbol: Symbol
    asset_class: AssetClass
    gics_sector: Identifier
    themes: tuple[Identifier, ...] = ()
    is_leveraged: bool = Field(strict=True)
    is_inverse: bool = Field(strict=True)
    tradable: bool = Field(strict=True)

    @field_validator("themes")
    @classmethod
    def unique_themes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """CRO-05: duplicate theme labels must not distort exposure aggregation."""
        if len(value) != len(set(value)):
            raise ValueError("instrument themes must be unique")
        if any(not theme.strip() for theme in value):
            raise ValueError("instrument themes cannot be blank")
        return value


class TradeProposal(FrozenModel):
    """R-01/R-04/R-05: whole-share long-only LIMIT proposal linked to a signal."""

    proposal_id: UUID
    signal_id: UUID
    account_id: Identifier
    symbol: Symbol
    side: Side
    intent: Intent
    qty: PositiveQty
    limit_price: Price
    stop_price: Price | None = None
    target_price: Price | None = None
    source: ProposalSource
    created_at: UTCDateTime
    expires_at: UTCDateTime

    @model_validator(mode="after")
    def validate_long_only_shape(self) -> Self:
        """R-01: additions are buys with a stop, reductions are sells."""
        if self.intent in (Intent.ENTRY, Intent.ADD):
            if self.side != Side.BUY:
                raise ValueError("ENTRY/ADD must be BUY")
            if self.stop_price is None or self.stop_price >= self.limit_price:
                raise ValueError("ENTRY/ADD requires a stop strictly below the limit")
            if self.target_price is not None and self.target_price <= self.limit_price:
                raise ValueError("ENTRY/ADD target must exceed the limit")
        elif self.side != Side.SELL:
            raise ValueError("REDUCE/EXIT must be SELL")
        if self.expires_at <= self.created_at:
            raise ValueError("proposal expiry must follow its creation")
        return self


class Position(FrozenModel):
    """R-01/R-04: a long position with exact cost and current valuation."""

    qty: NonnegativeQty
    avg_cost: Price
    last_price: Price

    @property
    def value(self) -> Decimal:
        """CRO-03/CRO-06: whole-share notional without float conversion."""
        with localcontext() as context:
            context.prec = max(80, len(str(self.qty)) + 40)
            return self.qty * self.last_price


class OpenOrder(FrozenModel):
    """CRO-03/CRO-06: read-only pending LIMIT notional."""

    symbol: Symbol
    side: Side
    qty: PositiveQty
    limit_price: Price
    stop_price: Price | None = None

    @model_validator(mode="after")
    def validate_stop(self) -> Self:
        """R-01/CRO-04: an optional pending BUY stop must precede its limit."""
        if (
            self.side == Side.BUY
            and self.stop_price is not None
            and self.stop_price >= self.limit_price
        ):
            raise ValueError("pending BUY stop must be below its limit")
        return self


class PortfolioSnapshot(FrozenModel):
    """R-03/R-04/R-05/CRO-09: immutable managed-account state.

    Signed balances are retained so a negative broker balance can trigger a
    veto/halt rather than be lost through coercion. Position quantities remain
    nonnegative. Funding values must be present even when they are zero.
    """

    account_id: Identifier
    account_type: AccountType
    as_of: UTCDateTime
    equity: Money
    cash: Money
    settled_cash: Money
    positions: Mapping[str, Position]
    open_orders: tuple[OpenOrder, ...]
    high_water_mark: Money = Field(ge=Decimal(0))
    day_start_equity: Money = Field(ge=Decimal(0))

    @field_validator("positions", mode="after")
    @classmethod
    def immutable_positions(cls, value: Mapping[str, Position]) -> Mapping[str, Position]:
        """R-03: detach mutable input dictionaries and validate every symbol."""
        for symbol in value:
            validate_symbol(symbol)
        return MappingProxyType(dict(value))

    @field_serializer("positions")
    def serialize_positions(self, value: Mapping[str, Position]) -> dict[str, Position]:
        """R-03: expose sorted JSON data without weakening stored immutability."""
        return {symbol: value[symbol] for symbol in sorted(value)}


class MarketContext(FrozenModel):
    """DAT-01/DAT-02/CRO-07/CRO-08: validated per-symbol pricing state."""

    last_price: Price
    last_price_ts: UTCDateTime
    adv20_usd: Money = Field(ge=Decimal(0))
    next_earnings_date: SessionDate | None = None
    status: MarketStatus


class DeployableCapital(FrozenModel):
    """CRO-12: advisory NEW funding capacity; never a transfer instruction."""

    checking_used: Money = Field(ge=Decimal(0))
    buffer: Money = Field(ge=Decimal(0))
    reserved: Money = Field(ge=Decimal(0))
    deployable: Money = Field(ge=Decimal(0))
    status: CapitalStatus

    @model_validator(mode="after")
    def validate_deployable(self) -> Self:
        """CRO-12: unavailable balances cannot accidentally advertise funding."""
        if self.status != CapitalStatus.OK and self.deployable != 0:
            raise ValueError("non-OK funding state must have zero deployable capital")
        if self.status == CapitalStatus.OK:
            with localcontext() as context:
                context.prec = 80
                expected = max(Decimal(0), self.checking_used - self.buffer - self.reserved)
                if self.deployable != expected:
                    raise ValueError("deployable does not equal checking less buffer and reserves")
            if self.checking_used < self.buffer:
                raise ValueError("checking below its buffer cannot have OK status")
        return self


class AccountFlags(FrozenModel):
    """R-02/CMP-06: exact current broker account-status flags, explicitly required."""

    trading_blocked: bool = Field(strict=True)
    account_blocked: bool = Field(strict=True)
    trade_suspended_by_user: bool = Field(strict=True)
    status: Identifier

    @property
    def blocked(self) -> bool:
        """CMP-06: any broker restriction requires the caller to latch HALTED."""
        return (
            self.status != "ACTIVE"
            or self.trading_blocked
            or self.account_blocked
            or self.trade_suspended_by_user
        )


class BlackoutWindow(FrozenModel):
    """CRO-11/R-05: UTC interval; CRO blocks both endpoints conservatively."""

    start: UTCDateTime
    end: UTCDateTime
    symbol: Symbol | None = None
    reason: Identifier

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """CRO-11: a missing/reversed interval cannot silently disable a blackout."""
        if self.start >= self.end:
            raise ValueError("blackout start must precede end")
        return self


class RuleResult(FrozenModel):
    """R-02/CRO-01..13/CMP-01..07: complete, reviewable rule evidence."""

    rule_id: Identifier
    passed: bool = Field(strict=True)
    severity: Severity
    observed: str
    limit: str
    message: Identifier


class Verdict(FrozenModel):
    """R-02/R-03/R-05: reproducible verdict with configuration/snapshot hashes."""

    proposal_id: UUID
    decision: Decision
    results: tuple[RuleResult, ...]
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluated_at: UTCDateTime
    recommended_state: SystemState = SystemState.RUNNING

    @model_validator(mode="after")
    def validate_approval(self) -> Self:
        """R-02: an APPROVED verdict requires evidence and no blocking failure."""
        if self.decision == Decision.APPROVED and (
            not self.results
            or any(
                not result.passed and result.severity == Severity.BLOCK for result in self.results
            )
        ):
            raise ValueError("APPROVED verdict requires passing blocking-rule evidence")
        return self


Payload = TypeVar("Payload", bound=FrozenModel)


class ProviderResult(FrozenModel, Generic[Payload]):
    """R-02/R-11: typed evidence is present only when a provider succeeds."""

    status: ProviderStatus
    payload: Payload | None
    reason: str = Field(max_length=2000)

    @model_validator(mode="after")
    def validate_available_evidence(self) -> Self:
        """R-02: an unavailable/error result never carries inferred evidence."""
        if (self.status == ProviderStatus.OK) != (self.payload is not None):
            raise ValueError("provider OK requires payload; non-OK requires no payload")
        return self


class ScannerHit(FrozenModel):
    """R-11/R-13/GD-03: deterministic scanner facts from completed bars."""

    symbol: Symbol
    as_of: UTCDateTime
    last_price: Price
    rvol: Money = Field(ge=Decimal(0))
    rsi: Money = Field(ge=Decimal(0), le=Decimal(100))
    reason: str = Field(min_length=1, max_length=2000)


class SetupCriterion(FrozenModel):
    """R-11/GD-03: code supplies each graded playbook criterion."""

    name: Identifier
    points: Money = Field(ge=Decimal(0), le=Decimal(10))
    reason: str = Field(min_length=1, max_length=2000)


class SetupCandidate(FrozenModel):
    """R-11/R-13/GD-03: code supplies score, levels, size, and criteria."""

    symbol: Symbol
    playbook: Playbook
    score: Money = Field(ge=Decimal(1), le=Decimal(10))
    criteria: tuple[SetupCriterion, ...] = Field(min_length=1)
    entry_price: Price
    stop_price: Price
    target_price: Price
    qty: PositiveQty
    as_of: UTCDateTime

    @model_validator(mode="after")
    def validate_deterministic_levels(self) -> Self:
        """R-01/R-11: criteria reconcile to score and long levels are ordered."""
        names = tuple(criterion.name for criterion in self.criteria)
        if len(names) != len(set(names)):
            raise ValueError("setup criteria names must be unique")
        with localcontext() as context:
            context.prec = 80
            if sum((criterion.points for criterion in self.criteria), Decimal(0)) != self.score:
                raise ValueError("setup score must equal deterministic criterion points")
        if not self.stop_price < self.entry_price < self.target_price:
            raise ValueError("setup levels require stop < entry < target")
        return self


class SentimentSignal(FrozenModel):
    """R-11/R-12: bounded advisory LLM output without executable trade fields."""

    score: Annotated[Decimal, BeforeValidator(_sentiment_score)]
    classification: SentimentClassification
    evidence_headline_ids: tuple[Identifier, ...] = Field(max_length=100)
    summary: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_cited_claim(self) -> Self:
        """R-11/R-12: non-noise sentiment requires explicit evidence ids."""
        if len(self.evidence_headline_ids) != len(set(self.evidence_headline_ids)):
            raise ValueError("headline evidence ids must be unique")
        if (
            self.score != 0 or self.classification != SentimentClassification.NOISE
        ) and not self.evidence_headline_ids:
            raise ValueError("non-neutral sentiment requires cited headline ids")
        return self


class FlowSignal(FrozenModel):
    """R-02/R-11: unavailable flow remains explicit and has no positive claim."""

    status: ProviderStatus
    summary: str | None = Field(default=None, max_length=2000)
    evidence_ids: tuple[Identifier, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_flow_evidence(self) -> Self:
        """R-02: unavailable/error flow never masquerades as evidence."""
        if self.status != ProviderStatus.OK and (self.summary is not None or self.evidence_ids):
            raise ValueError("non-OK flow cannot carry claims or evidence")
        if self.status == ProviderStatus.OK and (self.summary is None or not self.evidence_ids):
            raise ValueError("OK flow requires a summary and evidence ids")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("flow evidence ids must be unique")
        return self


class ResearchThesis(FrozenModel):
    """R-11/R-12: advisory narrative cannot set score, levels, or quantity."""

    narrative: str = Field(min_length=1, max_length=4000)
    evidence_headline_ids: tuple[Identifier, ...] = Field(max_length=100)

    @field_validator("evidence_headline_ids")
    @classmethod
    def unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """R-12: duplicate citations cannot inflate evidence counts."""
        if len(value) != len(set(value)):
            raise ValueError("headline evidence ids must be unique")
        return value


def _canonical(value: object) -> object:
    """R-03/R-04: stable exact JSON data independent of Decimal display scale."""
    if isinstance(value, Decimal):
        text = format(value, "f")
        return "0" if value == 0 else text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise DataIntegrityError("snapshot contains a value that cannot be hashed exactly")


def snapshot_hash(snapshot: PortfolioSnapshot) -> str:
    """R-03/R-04: SHA256 of canonical non-secret portfolio JSON."""
    try:
        checked = PortfolioSnapshot.model_validate(snapshot)
        payload = json.dumps(
            _canonical(checked), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    except DataIntegrityError:
        raise
    except Exception as exc:
        raise DataIntegrityError("R-02: invalid snapshot cannot be hashed") from exc
````````
<!-- END FILE backend/domain/models.py -->

### backend/domain/instruments.py

<!-- BEGIN FILE backend/domain/instruments.py -->
````````python
"""R-02/CRO-02/CRO-05/CMP-01/CMP-07: explicit frozen instrument allowlist.

Bundled CSV data are demonstration inputs, not verified investable metadata or
current fund holdings. A production operator must replace and verify them.
An empty blackout/group file expresses only the supplied operator policy;
this registry makes no claim to discover all events or tax-equivalent funds.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path
from types import MappingProxyType

import structlog
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.core.money import decimal_money
from backend.domain.models import (
    AssetClass,
    BlackoutWindow,
    Instrument,
    validate_symbol,
)

GICS_SECTORS = frozenset(
    {
        "Communication Services",
        "Consumer Discretionary",
        "Consumer Staples",
        "Energy",
        "Financials",
        "Health Care",
        "Industrials",
        "Information Technology",
        "Materials",
        "Real Estate",
        "Utilities",
    }
)


def _rows(path: Path, columns: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    """R-02: load exact CSV columns; duplicate headers/missing fields are errors."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or (
                len(reader.fieldnames) != len(columns) or set(reader.fieldnames) != set(columns)
            ):
                raise DataIntegrityError(f"CSV columns do not match policy schema: {path.name}")
            result: list[dict[str, str]] = []
            for row in reader:
                if set(row) != set(columns) or any(
                    not isinstance(row[key], str) for key in columns
                ):
                    raise DataIntegrityError(f"CSV row has missing or surplus fields: {path.name}")
                result.append({key: row[key].strip() for key in columns})
            return tuple(result)
    except DataIntegrityError:
        raise
    except Exception as exc:
        structlog.get_logger(__name__).error(
            "policy_csv_read_failed", file=path.name, error_type=type(exc).__name__
        )
        raise DataIntegrityError(f"Cannot verify policy CSV: {path.name}") from exc


def _boolean(value: str) -> bool:
    """R-02: typoed boolean metadata cannot become a truthy permissive value."""
    if value not in {"true", "false"}:
        raise DataIntegrityError("CSV boolean must be exactly true or false")
    return value == "true"


@dataclass(frozen=True, init=False)
class InstrumentRegistry:
    """R-02/CRO-02/CRO-05/CMP-01: detached, immutable metadata snapshot."""

    _instruments: Mapping[str, Instrument]
    _weights: Mapping[str, Mapping[str, Decimal]]
    _groups: Mapping[str, frozenset[str]]
    blackout_windows: tuple[BlackoutWindow, ...]

    def __init__(
        self,
        instruments: Iterable[Instrument],
        etf_weights: Mapping[str, Mapping[str, Decimal]] | None = None,
        identical_groups: Mapping[str, Iterable[str]] | None = None,
        blackout_windows: Iterable[BlackoutWindow] = (),
    ) -> None:
        try:
            names: dict[str, Instrument] = {}
            for instrument in instruments:
                if not isinstance(instrument, Instrument):
                    raise DataIntegrityError("Registry instruments must be valid and unique")
                instrument = Instrument.model_validate(instrument)
                if instrument.symbol in names:
                    raise DataIntegrityError("Registry instruments must be valid and unique")
                names[instrument.symbol] = instrument
            if not names:
                raise DataIntegrityError("An empty instrument allowlist cannot authorize trading")
            weights: dict[str, Mapping[str, Decimal]] = {}
            for symbol, sectors in (etf_weights or {}).items():
                if symbol not in names or names[symbol].asset_class == AssetClass.STOCK:
                    raise DataIntegrityError(
                        "ETF weights reference an unknown or non-ETF instrument"
                    )
                parsed: dict[str, Decimal] = {}
                for sector, weight in sectors.items():
                    amount = decimal_money(weight)
                    if sector not in GICS_SECTORS or not Decimal(0) < amount <= Decimal(1):
                        raise DataIntegrityError(
                            "ETF sectors/weights must be known positive fractions"
                        )
                    parsed[sector] = amount
                with localcontext() as context:
                    context.prec = 80
                    if not parsed or sum(parsed.values(), Decimal(0)) != Decimal(1):
                        raise DataIntegrityError("ETF look-through weights must total exactly one")
                weights[symbol] = MappingProxyType(parsed)
            groups: dict[str, frozenset[str]] = {}
            for group_id, group in (identical_groups or {}).items():
                members = tuple(group)
                if not group_id.strip() or len(members) < 2 or len(members) != len(set(members)):
                    raise DataIntegrityError(
                        "Identical group requires a name and at least two unique symbols"
                    )
                for symbol in members:
                    validate_symbol(symbol)
                    if symbol not in names or symbol in groups:
                        raise DataIntegrityError(
                            "Identical groups must use known, disjoint symbols"
                        )
                    groups[symbol] = frozenset(members)
            windows_list: list[BlackoutWindow] = []
            for window in blackout_windows:
                if not isinstance(window, BlackoutWindow):
                    raise DataIntegrityError("Blackout window must reference a known symbol")
                window = BlackoutWindow.model_validate(window)
                if window.symbol is not None and window.symbol not in names:
                    raise DataIntegrityError("Blackout window must reference a known symbol")
                windows_list.append(window)
            windows = tuple(windows_list)
            object.__setattr__(self, "_instruments", MappingProxyType(names))
            object.__setattr__(self, "_weights", MappingProxyType(weights))
            object.__setattr__(self, "_groups", MappingProxyType(groups))
            object.__setattr__(self, "blackout_windows", windows)
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot verify instrument registry") from exc

    @property
    def symbols(self) -> frozenset[str]:
        """CMP-07: the complete explicit allowlist, detached from caller input."""
        return frozenset(self._instruments)

    def get(self, symbol: str) -> Instrument:
        """R-02/CRO-02/CMP-07: an unknown name never acquires inferred metadata."""
        try:
            validate_symbol(symbol)
            return self._instruments[symbol]
        except Exception as exc:
            raise DataIntegrityError("Symbol is absent from the instrument allowlist") from exc

    def sector_weights(self, symbol: str) -> Mapping[str, Decimal]:
        """CRO-05: absent look-through means 100% of the declared sector.

        An UNKNOWN declared sector remains UNKNOWN here and must block at the
        CRO; it must never be silently treated as zero sector exposure.
        """
        instrument = self.get(symbol)
        return self._weights.get(symbol, MappingProxyType({instrument.gics_sector: Decimal(1)}))

    def identical_group(self, symbol: str) -> frozenset[str]:
        """CMP-01/CMP-02: an ungrouped known name is identical only to itself."""
        self.get(symbol)
        return self._groups.get(symbol, frozenset({symbol}))

    def validated_copy(self) -> InstrumentRegistry:
        """R-02/R-03: detach and revalidate even a forged registry instance.

        Invoke this on the class at policy ingress so a subclass cannot replace
        the validation routine. Stored symbol keys must agree with instruments;
        stored identical-group relationships must be complete and symmetric.
        """
        try:
            if not all(
                isinstance(value, Mapping)
                for value in (self._instruments, self._weights, self._groups)
            ):
                raise DataIntegrityError("Registry storage must contain verifiable mappings")
            names: list[Instrument] = []
            for symbol, instrument in self._instruments.items():
                validated = Instrument.model_validate(instrument)
                if symbol != validated.symbol:
                    raise DataIntegrityError("Registry symbol key disagrees with metadata")
                names.append(validated)
            groups: dict[str, tuple[str, ...]] = {}
            seen: set[frozenset[str]] = set()
            for symbol, members in self._groups.items():
                if not isinstance(members, frozenset) or symbol not in members:
                    raise DataIntegrityError("Registry identical-group relationship is malformed")
                if any(self._groups.get(member) != members for member in members):
                    raise DataIntegrityError(
                        "Registry identical-group relationships must be symmetric"
                    )
                if members not in seen:
                    groups[f"VALIDATED_GROUP_{len(groups)}"] = tuple(sorted(members))
                    seen.add(members)
            return InstrumentRegistry(names, self._weights, groups, self.blackout_windows)
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot revalidate instrument registry") from exc

    @classmethod
    def from_csv(cls, directory: Path) -> InstrumentRegistry:
        """R-02/CRO-05/CMP-07: explicit I/O boundary; all four policy files required."""
        try:
            names = tuple(
                Instrument(
                    symbol=row["symbol"],
                    asset_class=AssetClass(row["asset_class"]),
                    gics_sector=row["gics_sector"],
                    themes=tuple(row["themes"].split(";")) if row["themes"] else (),
                    is_leveraged=_boolean(row["is_leveraged"]),
                    is_inverse=_boolean(row["is_inverse"]),
                    tradable=_boolean(row["tradable"]),
                )
                for row in _rows(
                    directory / "instruments.csv",
                    (
                        "symbol",
                        "asset_class",
                        "gics_sector",
                        "themes",
                        "is_leveraged",
                        "is_inverse",
                        "tradable",
                    ),
                )
            )
            weights: dict[str, dict[str, Decimal]] = {}
            for row in _rows(
                directory / "etf_sector_weights.csv",
                ("symbol", "gics_sector", "weight"),
            ):
                sector_weights = weights.setdefault(row["symbol"], {})
                if row["gics_sector"] in sector_weights:
                    raise DataIntegrityError("Duplicate ETF sector weight")
                sector_weights[row["gics_sector"]] = decimal_money(row["weight"])
            groups: dict[str, list[str]] = {}
            for row in _rows(directory / "substantially_identical.csv", ("group_id", "symbol")):
                groups.setdefault(row["group_id"], []).append(row["symbol"])
            windows = tuple(
                BlackoutWindow(
                    start=datetime.fromisoformat(row["start"]),
                    end=datetime.fromisoformat(row["end"]),
                    symbol=row["symbol"] or None,
                    reason=row["reason"],
                )
                for row in _rows(
                    directory / "blackout_windows.csv",
                    ("symbol", "start", "end", "reason"),
                )
            )
            return cls(names, weights, groups, windows)
        except DataIntegrityError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise DataIntegrityError("Policy CSV contains invalid instrument metadata") from exc
````````
<!-- END FILE backend/domain/instruments.py -->

### backend/domain/compliance_models.py

<!-- BEGIN FILE backend/domain/compliance_models.py -->
````````python
"""R-02/R-04/R-05/R-13, CMP-01..05: immutable tax-accounting evidence.

Execution prices are exact Decimal cents. Tax basis and realized loss are
micro-unit money because wash adjustments can create fractional-cent basis.
All accounts are caller-attested accounts of the same taxpayer; spouse and
controlled-entity classification remains an operator verification duty.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from backend.domain.models import (
    FrozenModel,
    Identifier,
    Money,
    PositiveQty,
    Price,
    SessionDate,
    Side,
    Symbol,
    UTCDateTime,
)


class TaxStatus(StrEnum):
    """CMP-01/CMP-02: a taxable deduction cannot arise inside an IRA/Roth."""

    TAXABLE = "TAXABLE"
    IRA = "IRA"
    ROTH = "ROTH"


class ExternalAccount(FrozenModel):
    """CMP-01/CMP-02: explicit same-taxpayer account ownership and tax status."""

    account_id: Identifier
    tax_status: TaxStatus


class TaxLot(FrozenModel):
    """CMP-02/CMP-03: available whole shares and attested per-share tax basis.

    acquisition_trade_id, when known, identifies the original executed BUY.
    acquired_at is the actual purchase timestamp; a separately tacked holding
    start requires that original BUY ID and its record in supplied history.
    funding_settlement_date=None means settlement evidence is unavailable.
    """

    lot_id: UUID
    account_id: Identifier
    symbol: Symbol
    qty: PositiveQty
    acquired_at: UTCDateTime
    cost_basis: Money = Field(gt=Decimal(0))
    funding_settlement_date: SessionDate | None = None
    acquisition_trade_id: UUID | None = None
    holding_period_start: UTCDateTime | None = None

    @model_validator(mode="after")
    def validate_holding_period(self) -> Self:
        """R-02/CMP-02: tacking cannot guess or overwrite an acquisition date."""
        if self.holding_period_start is not None:
            if self.holding_period_start > self.acquired_at:
                raise ValueError("lot holding period cannot begin after actual acquisition")
            if self.holding_period_start < self.acquired_at and self.acquisition_trade_id is None:
                raise ValueError("previously tacked lot requires its original acquisition ID")
        return self


class TradeRecord(FrozenModel):
    """CMP-01..05: an executed whole-share trade, including DRIP purchases.

    realized_loss is attested total positive loss, including earlier basis
    adjustments. Each loss SELL represents one acquisition lot and supplies
    its holding-period start. An explicit acquisition ID disambiguates fills.
    Without that ID, holding_period_start attests the actual untacked purchase
    timestamp; previously tacked lots require the original acquisition ID.
    Aggregate multi-lot losses must be split by the caller before evaluation.
    """

    trade_id: UUID
    account_id: Identifier
    symbol: Symbol
    side: Side
    qty: PositiveQty
    price: Price
    ts: UTCDateTime
    realized_loss: Money = Field(default=Decimal(0), ge=Decimal(0))
    holding_period_start: UTCDateTime | None = None
    is_drip: bool = Field(default=False, strict=True)
    acquisition_trade_id: UUID | None = None

    @model_validator(mode="after")
    def validate_loss(self) -> Self:
        """R-02/CMP-02: loss and disposal evidence cannot contradict execution."""
        if self.realized_loss > 0 and (self.side != Side.SELL or self.holding_period_start is None):
            raise ValueError("realized loss requires a SELL and holding-period start")
        if self.holding_period_start is not None and self.holding_period_start > self.ts:
            raise ValueError("holding period cannot start after the executed trade")
        if self.acquisition_trade_id is not None and self.side != Side.SELL:
            raise ValueError("an acquisition reference belongs only to a SELL")
        if self.is_drip and self.side != Side.BUY:
            raise ValueError("a DRIP record must be a BUY")
        return self


class WashAdjustment(FrozenModel):
    """CMP-01/CMP-02: one disjoint loss-share/replacement-share allocation.

    acquired_date is the sold lot's original acquisition date, for Form 8949.
    adjusted_basis is the total basis of the matched replacement slice;
    holding_period_start is its tacked start. IRA/Roth basis stays unchanged.
    """

    loss_trade_id: UUID
    replacement_trade_id: UUID
    loss_account_id: Identifier
    replacement_account_id: Identifier
    symbol: Symbol
    qty: PositiveQty
    sale_date: SessionDate
    acquired_date: SessionDate
    proceeds: Money = Field(ge=Decimal(0))
    cost_basis: Money = Field(gt=Decimal(0))
    disallowed_loss: Money = Field(gt=Decimal(0))
    adjusted_basis: Money | None = None
    holding_period_start: UTCDateTime
    permanent_loss: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_allocation(self) -> Self:
        """R-02/CMP-02: every exported sale slice must reconcile exactly."""
        with localcontext() as context:
            context.prec = 80
            if self.cost_basis - self.proceeds != self.disallowed_loss:
                raise ValueError("matched sale basis must reconcile to its disallowed loss")
        if self.acquired_date > self.sale_date:
            raise ValueError("sold lot acquisition cannot follow its sale")
        if self.permanent_loss:
            if self.adjusted_basis is not None:
                raise ValueError("IRA/Roth permanent loss cannot increase replacement basis")
        elif self.adjusted_basis is None or self.adjusted_basis <= self.disallowed_loss:
            raise ValueError("taxable replacement requires its positive adjusted basis")
        return self


class Form8949Row(FrozenModel):
    """CMP-02: disjoint matched sale slice with positive code-W adjustment."""

    account_id: Identifier
    loss_trade_id: UUID
    description: Identifier
    date_acquired: SessionDate
    date_sold: SessionDate
    proceeds: Money
    cost_basis: Money
    code: Literal["W"] = "W"
    adjustment: Money = Field(gt=Decimal(0))
    gain_or_loss: Money

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        """R-02/CMP-02: adjustment changes gain/loss without reducing basis."""
        with localcontext() as context:
            context.prec = 80
            if self.proceeds - self.cost_basis + self.adjustment != self.gain_or_loss:
                raise ValueError("Form 8949 proceeds, basis and adjustment must reconcile")
        if self.date_acquired > self.date_sold:
            raise ValueError("Form 8949 acquisition cannot follow sale")
        return self
````````
<!-- END FILE backend/domain/compliance_models.py -->

### backend/risk/__init__.py

<!-- BEGIN FILE backend/risk/__init__.py -->
````````python
"""R-02/R-03: deterministic read-only risk and compliance gates."""
````````
<!-- END FILE backend/risk/__init__.py -->

### backend/risk/compliance.py

<!-- BEGIN FILE backend/risk/compliance.py -->
````````python
"""R-02/R-03/R-04/R-05/R-09, CMP-01..07: pure pre-trade compliance.

These flags and Form 8949 rows aid reconciliation; the broker's 1099-B remains
the filing record. Account taxonomy, complete trade history and current lots
are injected by the caller. Unknown account ownership/tax status fails closed.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.money import decimal_money
from backend.core.system_state import SystemState
from backend.data.market_calendar import MarketCalendar
from backend.domain.compliance_models import (
    ExternalAccount as ExternalAccount,
)
from backend.domain.compliance_models import (
    Form8949Row as Form8949Row,
)
from backend.domain.compliance_models import (
    TaxLot as TaxLot,
)
from backend.domain.compliance_models import (
    TaxStatus as TaxStatus,
)
from backend.domain.compliance_models import (
    TradeRecord as TradeRecord,
)
from backend.domain.compliance_models import (
    WashAdjustment as WashAdjustment,
)
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    DayTradeRegime,
    FrozenModel,
    Intent,
    PortfolioSnapshot,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
    UTCDateTime,
    _canonical,
    snapshot_hash,
)
from backend.risk.wash_sales import WashSaleMatcher

_NEW_YORK = ZoneInfo("America/New_York")


class ComplianceAssessment(FrozenModel):
    """CMP-01..07/R-02/R-03: immutable evidence and an effect-free halt request."""

    proposal_id: UUID | None
    results: tuple[RuleResult, ...]
    config_hash: str
    snapshot_hash: str
    input_hash: str
    evaluated_at: UTCDateTime
    recommended_state: SystemState


def _day(value: datetime) -> date:
    """R-05/CMP-03/CMP-05: exchange dates use New York even near UTC midnight."""
    return ensure_utc(value).astimezone(_NEW_YORK).date()


def _compliance_canonical(value: object) -> object:
    """R-03/R-04/R-05: exact B-stage JSON normalization with tax date support."""
    if isinstance(value, FrozenModel):
        return _compliance_canonical(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _compliance_canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_compliance_canonical(item) for item in value]
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return _canonical(value)


def _result(
    rule: str, passed: bool, severity: Severity, observed: object, limit: object, message: str
) -> RuleResult:
    return RuleResult(
        rule_id=rule,
        passed=passed,
        severity=severity,
        observed=str(observed),
        limit=str(limit),
        message=message,
    )


class ComplianceEngine:
    """CMP-01..07/R-03/R-09: evaluate all rules without changing any position.

    FIFO chooses proposed sale lots. Identical groups are operator-supplied,
    not inferred from overlapping holdings. An exit gets warnings for every
    compliance failure, including provider faults. The orchestration layer
    must persist a HALT on failed CMP-06 before running the state gate.
    """

    def __init__(
        self,
        config: Settings,
        registry: InstrumentRegistry,
        calendar: MarketCalendar,
        *,
        restricted_symbols: frozenset[str] = frozenset(),
    ) -> None:
        try:
            policy = config.model_dump(mode="python")
            if (
                not config.telegram_allowed_user_ids
                and "telegram_allowed_user_ids" not in config.model_fields_set
            ):
                del policy["telegram_allowed_user_ids"]
            self.config = Settings.model_validate(policy)
            if not isinstance(calendar, MarketCalendar):
                raise DataIntegrityError("CMP-03: bounded exchange calendar is required")
            self.registry = InstrumentRegistry.validated_copy(registry)
            self.calendar = calendar
            self.restricted_symbols = frozenset(restricted_symbols)
            for symbol in self.restricted_symbols:
                self.registry.get(symbol)
            self._config_hash = self.config.config_hash
        except Exception as exc:
            raise ConfigurationError(
                "CMP-01..07: cannot verify immutable compliance policy"
            ) from exc

    def settlement_date(self, ts: datetime) -> date:
        """CMP-03: T+1 uses the actual exchange trade date, not the UTC date."""
        # VERIFY: https://www.sec.gov/resources-for-investors/investor-alerts-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor-bulletin
        try:
            return self.calendar.add_sessions(_day(ts), 1)
        except Exception as exc:
            raise DataIntegrityError("CMP-03: cannot verify T+1 settlement date") from exc

    def input_hash(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
        flags: AccountFlags | None,
    ) -> str:
        """R-02/R-03: bind full evidence and detached tax/restriction policy.

        Tuple ordering is retained as part of the supplied evidence. Decimal
        trailing zeros are normalized; all timestamps are normalized to UTC.
        The settings-only config_hash remains the master contract's hash.
        """
        try:
            if not all(isinstance(rows, tuple) for rows in (lots, history, accounts)):
                raise DataIntegrityError("CMP-01..07: evidence must be immutable tuples")
            payload = {
                "proposal": TradeProposal.model_validate(proposal),
                "snapshot": PortfolioSnapshot.model_validate(snapshot),
                "lots": tuple(TaxLot.model_validate(row) for row in lots),
                "history": tuple(TradeRecord.model_validate(row) for row in history),
                "accounts": tuple(ExternalAccount.model_validate(row) for row in accounts),
                "flags": AccountFlags.model_validate(flags) if flags is not None else None,
                "restricted_symbols": sorted(self.restricted_symbols),
                "instruments": tuple(
                    self.registry.get(symbol) for symbol in sorted(self.registry.symbols)
                ),
                "identical_groups": {
                    symbol: sorted(self.registry.identical_group(symbol))
                    for symbol in sorted(self.registry.symbols)
                },
            }
            encoded = json.dumps(
                _compliance_canonical(payload),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        except Exception as exc:
            raise DataIntegrityError(
                "CMP-01..07: cannot hash verified compliance evidence"
            ) from exc

    def settled_cash_as_of(
        self,
        initial_cash: Decimal,
        history: tuple[TradeRecord, ...],
        now: datetime,
        *,
        account_id: str,
    ) -> Decimal:
        """CMP-03: exact reconstructed cash with conservative T+1 credit timing.

        BUY costs debit immediately. Without an attested settlement timestamp,
        SELL proceeds credit only at the T+1 session close. A broker-reconciled
        settled_cash snapshot can provide confirmed funds sooner that day.
        """
        try:
            instant = ensure_utc(now)
            if not isinstance(initial_cash, Decimal) or not account_id.strip():
                raise DataIntegrityError("CMP-03: Decimal baseline and account are required")
            cash = decimal_money(initial_cash)
            rows = tuple(TradeRecord.model_validate(row) for row in history)
            if len({row.trade_id for row in rows}) != len(rows):
                raise DataIntegrityError("CMP-03: duplicate trade identifier")
            with localcontext() as context:
                context.prec = 80
                for trade in sorted(rows, key=lambda row: (row.ts, str(row.trade_id))):
                    self.registry.get(trade.symbol)
                    if trade.ts > instant:
                        raise DataIntegrityError("CMP-03: future executed trade")
                    if trade.account_id != account_id:
                        continue
                    notional = trade.qty * trade.price
                    if trade.side == Side.BUY:
                        cash -= notional
                    elif self.calendar.session_close(self.settlement_date(trade.ts)) <= instant:
                        cash += notional
            return decimal_money(cash)
        except Exception as exc:
            raise DataIntegrityError("CMP-03: cannot reconstruct verified settled cash") from exc

    def wash_adjustments(
        self,
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
    ) -> tuple[WashAdjustment, ...]:
        """CMP-01/CMP-02: 61-day matching, proportional loss, basis and tacking.

        Each replacement share has one shared capacity across all loss sales.
        Match loss sales chronologically, then replacement purchases in their
        acquisition order; both day-30 endpoints are included. IRA/Roth
        replacements permanently disallow the taxable loss with no IRA basis
        increase. Zero-rounded micro-unit estimates raise rather than disappear.
        """
        # VERIFY: https://www.irs.gov/publications/p550
        # VERIFY: https://www.irs.gov/pub/irs-drop/rr-08-05.pdf
        return WashSaleMatcher(self.registry).adjustments(history, external_accounts)

    @staticmethod
    def form_8949_rows(adjustments: tuple[WashAdjustment, ...]) -> tuple[Form8949Row, ...]:
        """CMP-02: one code-W reconciliation row per disjoint matched sale slice."""
        # VERIFY: https://www.irs.gov/instructions/i8949
        return WashSaleMatcher.form_8949_rows(adjustments)

    @staticmethod
    def _accounts(rows: tuple[ExternalAccount, ...]) -> dict[str, TaxStatus]:
        accounts = {row.account_id: row.tax_status for row in rows}
        if len(accounts) != len(rows):
            raise DataIntegrityError("Tax account identifiers must be unique")
        return accounts

    def check(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
        now: datetime,
        *,
        flags: AccountFlags | None = None,
    ) -> list[RuleResult]:
        """CMP-01..07: mandated evidence API; effects remain in the boundary."""
        return list(
            self.assess(
                proposal, snapshot, lots, history, external_accounts, now, flags=flags
            ).results
        )

    def assess(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
        now: datetime,
        *,
        flags: AccountFlags | None = None,
    ) -> ComplianceAssessment:
        """CMP-01..07/R-02/R-09: all evidence plus explicit fault provenance.

        Ordinary rule failures retain RUNNING; unverifiable input, a provider
        fault or failed current broker flags recommends a durable HALT. Only
        independently verifiable exits receive warnings for those failures.
        """
        try:
            instant = ensure_utc(now)
        except Exception as exc:
            raise DataIntegrityError("R-05/CMP-01..07: evaluation time is unverifiable") from exc
        severity = (
            Severity.WARN if self._verified_exit(proposal, snapshot, instant) else Severity.BLOCK
        )
        identity = (
            proposal.__dict__.get("proposal_id") if isinstance(proposal, TradeProposal) else None
        )
        proposal_id = identity if isinstance(identity, UUID) else None
        digest = "0" * 64
        input_digest = "0" * 64
        try:
            snapshot = PortfolioSnapshot.model_validate(snapshot)
            digest = snapshot_hash(snapshot)
            proposal = TradeProposal.model_validate(proposal)
            proposal_id = proposal.proposal_id
            if not all(isinstance(rows, tuple) for rows in (lots, history, external_accounts)):
                raise DataIntegrityError("CMP-01..07: evidence must be immutable tuples")
            lots = tuple(TaxLot.model_validate(row) for row in lots)
            history = tuple(TradeRecord.model_validate(row) for row in history)
            external_accounts = tuple(
                ExternalAccount.model_validate(row) for row in external_accounts
            )
            input_digest = self.input_hash(
                proposal, snapshot, lots, history, external_accounts, flags
            )
            self._validate_inputs(proposal, snapshot, lots, history, external_accounts, instant)
        except Exception as exc:
            failures = tuple(
                _result(
                    f"CMP-{number:02d}",
                    False,
                    severity,
                    type(exc).__name__,
                    "verified state",
                    "Unverifiable compliance input; HALTED required",
                )
                for number in range(1, 8)
            )
            return ComplianceAssessment(
                proposal_id=proposal_id,
                results=failures,
                config_hash=self._config_hash,
                snapshot_hash=digest,
                input_hash=input_digest,
                evaluated_at=instant,
                recommended_state=SystemState.HALTED,
            )
        operations: tuple[tuple[str, Callable[[], RuleResult]], ...] = (
            (
                "CMP-01",
                lambda: self._forward(proposal, history, external_accounts, instant, severity),
            ),
            (
                "CMP-02",
                lambda: self._backward(
                    proposal, snapshot, lots, history, external_accounts, instant
                ),
            ),
            ("CMP-03", lambda: self._settlement(proposal, snapshot, lots, instant, severity)),
            ("CMP-04", lambda: self._borrowing(proposal, snapshot, severity)),
            ("CMP-05", lambda: self._day_trade(proposal, snapshot, history, instant, severity)),
            ("CMP-06", lambda: self._broker(flags, severity)),
            ("CMP-07", lambda: self._restricted(proposal, severity)),
        )
        results: list[RuleResult] = []
        recommended = SystemState.RUNNING
        for rule, operation in operations:
            try:
                with localcontext() as context:
                    context.prec = 80
                    results.append(operation())
            except Exception as exc:
                recommended = SystemState.HALTED
                results.append(
                    _result(
                        rule,
                        False,
                        severity,
                        type(exc).__name__,
                        "verified state",
                        "Unverifiable compliance rule; HALTED required",
                    )
                )
        if not results[5].passed:
            recommended = SystemState.HALTED
        return ComplianceAssessment(
            proposal_id=proposal_id,
            results=tuple(results),
            config_hash=self._config_hash,
            snapshot_hash=digest,
            input_hash=input_digest,
            evaluated_at=instant,
            recommended_state=recommended,
        )

    def _validate_common(
        self, proposal: TradeProposal, snapshot: PortfolioSnapshot, instant: datetime
    ) -> None:
        """R-02/R-05/R-09: bind a live proposal to fresh account inventory."""
        if (
            proposal.account_id != snapshot.account_id
            or not proposal.created_at <= instant < proposal.expires_at
            or snapshot.as_of > instant
            or instant - snapshot.as_of > timedelta(seconds=self.config.stale_quote_seconds)
        ):
            raise DataIntegrityError("Account binding, expiry or portfolio freshness is invalid")
        if proposal.side == Side.SELL:
            held = snapshot.positions.get(proposal.symbol)
            pending = sum(
                order.qty
                for order in snapshot.open_orders
                if order.side == Side.SELL and order.symbol == proposal.symbol
            )
            if held is None or proposal.qty > held.qty - pending:
                raise DataIntegrityError("R-09: sell quantity exceeds unreserved held shares")

    def _verified_exit(
        self, proposal: TradeProposal, snapshot: PortfolioSnapshot, instant: datetime
    ) -> bool:
        """R-09: warning-only compliance is available to verifiable held exits."""
        try:
            checked = TradeProposal.model_validate(proposal)
            state = PortfolioSnapshot.model_validate(snapshot)
            self._validate_common(checked, state, instant)
            return checked.intent in (Intent.REDUCE, Intent.EXIT)
        except Exception:
            return False

    def _validate_inputs(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
        now: datetime,
    ) -> None:
        instant = ensure_utc(now)
        self._validate_common(proposal, snapshot, instant)
        if snapshot.equity <= 0:
            raise DataIntegrityError("R-02/CMP-04: account equity requires HALTED")
        known = self._accounts(accounts)
        if proposal.account_id not in known:
            raise DataIntegrityError("Managed account tax status is unknown")
        if len({row.trade_id for row in history}) != len(history) or len(
            {row.lot_id for row in lots}
        ) != len(lots):
            raise DataIntegrityError("Trade or lot identifiers must be unique")
        if proposal.proposal_id in {row.trade_id for row in history}:
            raise DataIntegrityError("Proposal already exists in executed history")
        for trade in history:
            if trade.ts > instant or trade.account_id not in known:
                raise DataIntegrityError("Trade history is future or account ownership is unknown")
            self.registry.get(trade.symbol)
        executed = {row.trade_id: row for row in history}
        lot_inventory: dict[UUID, int] = {}
        for lot in lots:
            if lot.acquired_at > instant or lot.account_id not in known:
                raise DataIntegrityError("Tax lot is future or account ownership is unknown")
            self.registry.get(lot.symbol)
            if lot.acquisition_trade_id is not None:
                original = executed.get(lot.acquisition_trade_id)
                lot_inventory[lot.acquisition_trade_id] = (
                    lot_inventory.get(lot.acquisition_trade_id, 0) + lot.qty
                )
                if (
                    original is None
                    or original.side != Side.BUY
                    or original.account_id != lot.account_id
                    or original.symbol != lot.symbol
                    or original.ts != lot.acquired_at
                    or lot_inventory[lot.acquisition_trade_id] > original.qty
                ):
                    raise DataIntegrityError(
                        "CMP-02: tax lot acquisition lineage does not reconcile"
                    )

    def _forward(
        self,
        proposal: TradeProposal,
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
        now: datetime,
        severity: Severity,
    ) -> RuleResult:
        if proposal.side != Side.BUY:
            return _result(
                "CMP-01",
                True,
                Severity.WARN,
                "exit",
                "buy only",
                "Forward wash-sale rule is not applicable",
            )
        candidate = TradeRecord(
            trade_id=proposal.proposal_id,
            account_id=proposal.account_id,
            symbol=proposal.symbol,
            side=Side.BUY,
            qty=proposal.qty,
            price=proposal.limit_price,
            ts=ensure_utc(now),
        )
        matches = tuple(
            row
            for row in self.wash_adjustments((*history, candidate), accounts)
            if row.replacement_trade_id == proposal.proposal_id
        )
        loss = sum((row.disallowed_loss for row in matches), Decimal(0))
        blocked = loss > 0
        policy = Severity(self.config.wash_sale_mode) if blocked else severity
        permanent = any(row.permanent_loss for row in matches)
        return _result(
            "CMP-01",
            not blocked,
            policy,
            loss,
            0,
            "IRA/Roth replacement creates permanent loss"
            if permanent
            else "Forward wash-sale matched loss shares"
            if blocked
            else "No forward wash-sale replacement",
        )

    def _sale_lots(
        self, proposal: TradeProposal, snapshot: PortfolioSnapshot, lots: tuple[TaxLot, ...]
    ) -> tuple[tuple[TaxLot, int], ...]:
        selected = sorted(
            (
                lot
                for lot in lots
                if lot.account_id == proposal.account_id and lot.symbol == proposal.symbol
            ),
            key=lambda lot: (lot.acquired_at, str(lot.lot_id)),
        )
        held = snapshot.positions.get(proposal.symbol)
        if held is None or proposal.qty > held.qty or sum(lot.qty for lot in selected) != held.qty:
            raise DataIntegrityError("Sale lots do not reconcile to held whole shares")
        remaining = proposal.qty
        output: list[tuple[TaxLot, int]] = []
        for lot in selected:
            if remaining == 0:
                break
            shares = min(remaining, lot.qty)
            output.append((lot, shares))
            remaining -= shares
        return tuple(output)

    def _backward(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
        now: datetime,
    ) -> RuleResult:
        if proposal.side != Side.SELL:
            return _result(
                "CMP-02",
                True,
                Severity.WARN,
                "buy",
                "loss sale only",
                "Backward wash-sale rule is not applicable",
            )
        candidates = tuple(
            TradeRecord(
                trade_id=uuid5(proposal.proposal_id, str(lot.lot_id)),
                account_id=proposal.account_id,
                symbol=proposal.symbol,
                side=Side.SELL,
                qty=shares,
                price=proposal.limit_price,
                ts=ensure_utc(now),
                realized_loss=max(Decimal(0), (lot.cost_basis - proposal.limit_price) * shares),
                holding_period_start=lot.holding_period_start or lot.acquired_at,
                acquisition_trade_id=lot.acquisition_trade_id,
            )
            for lot, shares in self._sale_lots(proposal, snapshot, lots)
        )
        ids = {row.trade_id for row in candidates}
        matches = tuple(
            row
            for row in self.wash_adjustments((*history, *candidates), accounts)
            if row.loss_trade_id in ids
        )
        loss = sum((row.disallowed_loss for row in matches), Decimal(0))
        permanent = any(row.permanent_loss for row in matches)
        return _result(
            "CMP-02",
            loss == 0,
            Severity.WARN,
            loss,
            0,
            "Backward wash-sale estimated disallowed loss; permanent IRA/Roth loss"
            if permanent
            else "Backward wash-sale estimated disallowed loss"
            if loss
            else "No backward wash-sale loss",
        )

    @staticmethod
    def _pending(snapshot: PortfolioSnapshot) -> Decimal:
        return sum(
            (
                order.qty * order.limit_price
                for order in snapshot.open_orders
                if order.side == Side.BUY
            ),
            Decimal(0),
        )

    def _settlement(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        now: datetime,
        severity: Severity,
    ) -> RuleResult:
        if snapshot.account_type != AccountType.CASH:
            return _result(
                "CMP-03",
                True,
                severity,
                "margin",
                "cash accounts",
                "Cash settlement rule is not applicable",
            )
        if proposal.side == Side.BUY:
            required = proposal.qty * proposal.limit_price + self._pending(snapshot)
            return _result(
                "CMP-03",
                required <= snapshot.settled_cash,
                severity,
                required,
                snapshot.settled_cash,
                "BUY plus pending buys requires confirmed settled cash",
            )
        unsafe = 0
        for lot, shares in self._sale_lots(proposal, snapshot, lots):
            funding_date = lot.funding_settlement_date
            if funding_date is None or now < self.calendar.session_close(funding_date):
                unsafe += shares
        return _result(
            "CMP-03",
            unsafe == 0,
            Severity.WARN,
            unsafe,
            0,
            "Sale funding is unknown or may create a good-faith/freeriding violation"
            if unsafe
            else "Sale funding is settled",
        )

    def _borrowing(
        self, proposal: TradeProposal, snapshot: PortfolioSnapshot, severity: Severity
    ) -> RuleResult:
        if proposal.side == Side.SELL:
            return _result(
                "CMP-04", True, Severity.WARN, "exit", "buys only", "Exit does not borrow"
            )
        required = proposal.qty * proposal.limit_price + self._pending(snapshot)
        enough_equity = (
            snapshot.account_type != AccountType.MARGIN
            or snapshot.equity >= self.config.min_margin_equity
        )
        passed = required <= snapshot.cash and enough_equity
        return _result(
            "CMP-04",
            passed,
            severity,
            f"cash_required={required};equity={snapshot.equity}",
            f"cash={snapshot.cash};minimum_margin_equity={self.config.min_margin_equity}",
            "No borrowing; managed margin-account minimum equity is an operator guard",
        )

    def _day_trade(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        history: tuple[TradeRecord, ...],
        now: datetime,
        severity: Severity,
    ) -> RuleResult:
        """CMP-05: conservative opening-order count across five XNYS sessions.

        Each distinct same-day BUY order plausibly touched by a later SELL
        counts once. One sold share is allocated to each untouched opening order
        before extra shares, providing a conservative upper bound when broker
        allocation is unknown. Split fills must be consolidated by the caller;
        the broker's permitted counting method may produce fewer trades.
        """
        # VERIFY: https://syndication.finra.org/content/understanding-new-intraday-margin-requirements
        # VERIFY: https://www.finra.org/rules-guidance/guidance/interps-4210
        today = _day(now)
        window = frozenset(
            (*self.calendar.previous_sessions(today, 4), today)
            if self.calendar.is_session(today)
            else self.calendar.previous_sessions(today, 5)
        )
        pending: dict[tuple[date, str], deque[tuple[UUID, int]]] = {}
        completed_ids: set[UUID] = set()
        same_day = False
        # Equal timestamps lack fill ordering: BUY-before-SELL maximizes the
        # conservative count instead of letting arbitrary UUID order reduce it.
        for trade in sorted(
            history, key=lambda row: (row.ts, row.side != Side.BUY, str(row.trade_id))
        ):
            if trade.account_id != proposal.account_id:
                continue
            trade_day = _day(trade.ts)
            if (
                trade_day == today
                and trade.symbol == proposal.symbol
                and trade.side != proposal.side
            ):
                same_day = True
            if trade_day not in window:
                continue
            key = (trade_day, trade.symbol)
            queue = pending.setdefault(key, deque())
            if trade.side == Side.BUY:
                queue.append((trade.trade_id, trade.qty))
            else:
                remaining = trade.qty
                available_orders = list(queue)
                queue.clear()
                for index, (buy_id, available) in enumerate(available_orders):
                    if remaining == 0:
                        break
                    if buy_id not in completed_ids:
                        available_orders[index] = (buy_id, available - 1)
                        completed_ids.add(buy_id)
                        remaining -= 1
                for buy_id, available in available_orders:
                    matched = min(remaining, available)
                    remaining -= matched
                    if matched < available:
                        queue.append((buy_id, available - matched))
        completed = len(completed_ids)
        legacy_block = (
            self.config.day_trade_regime == DayTradeRegime.LEGACY_PDT
            and snapshot.account_type == AccountType.MARGIN
            and same_day
            and completed >= 3
            and snapshot.equity < Decimal("25000")
        )
        result_severity = severity if legacy_block else Severity.WARN
        return _result(
            "CMP-05",
            not same_day,
            result_severity,
            f"same_day={same_day};completed={completed};equity={snapshot.equity}",
            "legacy>=3 and equity<25000; default same-day WARN",
            "Legacy same-day guard would block an addition"
            if legacy_block
            else "Same-day round-trip warning"
            if same_day
            else "No same-day round trip",
        )

    @staticmethod
    def _broker(flags: AccountFlags | None, severity: Severity) -> RuleResult:
        if flags is None:
            return _result(
                "CMP-06",
                False,
                severity,
                "missing",
                "explicit current account flags",
                "Unverifiable broker flags; HALTED required",
            )
        # VERIFY: https://docs.alpaca.markets/us/reference/getaccount-1
        checked = AccountFlags.model_validate(flags)
        return _result(
            "CMP-06",
            not checked.blocked,
            severity,
            checked.model_dump_json(),
            "ACTIVE and all flags false",
            "Broker account blocked; HALTED required"
            if checked.blocked
            else "Broker account is active and unrestricted",
        )

    def _restricted(self, proposal: TradeProposal, severity: Severity) -> RuleResult:
        instrument = self.registry.get(proposal.symbol)
        passed = (
            proposal.symbol not in self.restricted_symbols
            and instrument.tradable
            and not instrument.is_leveraged
            and not instrument.is_inverse
        )
        return _result(
            "CMP-07",
            passed,
            severity,
            proposal.symbol,
            "tradable allowlist minus restricted names",
            "Explicit instrument allowlist and restricted-list policy",
        )
````````
<!-- END FILE backend/risk/compliance.py -->

### backend/risk/wash_sales.py

<!-- BEGIN FILE backend/risk/wash_sales.py -->
````````python
"""R-02/R-03/R-04/R-05, CMP-01/CMP-02: pure chronological wash-sale matching.

This is a pre-trade/reconciliation estimate, not a complete tax return. Supplied
history must include all acquisitions and dispositions relevant to matching.
Loss records attest any tax basis and holding-period adjustments from earlier
wash sales; tacked holding periods require an explicit acquisition trade ID.
Without that ID the holding start attests the actual untacked acquisition.
FIFO identifies non-loss dispositions without an acquisition ID;
ambiguous or insufficient supplied inventory fails closed. Sold shares cannot
replace themselves; retained shares of a partly sold acquisition can qualify.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.core.money import money_to_scaled, scaled_to_money
from backend.domain.compliance_models import (
    ExternalAccount,
    Form8949Row,
    TaxStatus,
    TradeRecord,
    WashAdjustment,
)
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import Side

_NEW_YORK = ZoneInfo("America/New_York")


def trade_day(value: datetime) -> date:
    """R-05/CMP-01/CMP-02: calendar-day windows use the US exchange date."""
    return ensure_utc(value).astimezone(_NEW_YORK).date()


class WashSaleMatcher:
    """CMP-01/CMP-02/R-03: detached metadata and no I/O or mutable tax ledger."""

    def __init__(self, registry: InstrumentRegistry) -> None:
        try:
            if not isinstance(registry, InstrumentRegistry):
                raise DataIntegrityError("Wash matcher requires an explicit instrument registry")
            self.registry = InstrumentRegistry.validated_copy(registry)
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot verify wash-sale registry") from exc

    def adjustments(
        self,
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
    ) -> tuple[WashAdjustment, ...]:
        """CMP-01/CMP-02: inclusive 61-day matching and shared share capacity.

        Acquisitions match in chronological order. Before-sale shares must still
        be held after the loss disposition. A later sale does not erase an
        already valid replacement match. Each purchase share is assigned once
        across all losses. Proportional loss uses cumulative integer micro-unit
        allocation, so partial matches never absorb unmatched-share losses.
        """
        # VERIFY: https://www.irs.gov/publications/p550
        # VERIFY: https://www.irs.gov/pub/irs-drop/rr-08-05.pdf
        try:
            ordered, statuses = self._inputs(history, accounts)
            surviving = self._survivors(ordered)
            buys = tuple(row for row in ordered if row.side == Side.BUY)
            acquisitions = {row.trade_id: row.ts for row in buys}
            assigned: dict[UUID, list[tuple[int, int]]] = {row.trade_id: [] for row in buys}
            output: list[WashAdjustment] = []
            for loss in ordered:
                if loss.realized_loss <= 0 or statuses[loss.account_id] != TaxStatus.TAXABLE:
                    continue
                group = self.registry.identical_group(loss.symbol)
                used = 0
                allocated_micro = 0
                loss_micro = money_to_scaled(loss.realized_loss)
                for replacement in buys:
                    if used == loss.qty:
                        break
                    if (
                        replacement.symbol not in group
                        or abs((trade_day(replacement.ts) - trade_day(loss.ts)).days) > 30
                    ):
                        continue
                    first_held = 0
                    if replacement.trade_id in surviving[loss.trade_id]:
                        first_held = replacement.qty - surviving[loss.trade_id].get(
                            replacement.trade_id, 0
                        )
                    slices = self._available_slices(
                        first_held, replacement.qty, assigned[replacement.trade_id], loss.qty - used
                    )
                    matched = sum(end - start for start, end in slices)
                    if matched == 0:
                        continue
                    new_used = used + matched
                    new_allocated = loss_micro * new_used // loss.qty
                    disallowed = scaled_to_money(new_allocated - allocated_micro)
                    if disallowed <= 0:
                        raise DataIntegrityError(
                            "Wash loss allocation is below supported micro-unit precision"
                        )
                    output.append(
                        self._adjustment(
                            loss,
                            replacement,
                            matched,
                            disallowed,
                            statuses,
                            acquisitions[loss.acquisition_trade_id]
                            if loss.acquisition_trade_id is not None
                            else None,
                        )
                    )
                    assigned[replacement.trade_id].extend(slices)
                    assigned[replacement.trade_id].sort()
                    used = new_used
                    allocated_micro = new_allocated
            return tuple(output)
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot verify wash-sale matching evidence") from exc

    @staticmethod
    def _available_slices(
        first_held: int, total: int, assigned: list[tuple[int, int]], requested: int
    ) -> tuple[tuple[int, int], ...]:
        """CMP-02: FIFO share intervals prevent retained matched shares being reused."""
        cursor = first_held
        remaining = requested
        output: list[tuple[int, int]] = []
        for start, end in (*assigned, (total, total)):
            if end <= cursor:
                continue
            available = max(0, start - cursor)
            matched = min(available, remaining)
            if matched:
                output.append((cursor, cursor + matched))
                remaining -= matched
            cursor = max(cursor, end)
            if remaining == 0:
                break
        return tuple(output)

    def _inputs(
        self, history: tuple[TradeRecord, ...], accounts: tuple[ExternalAccount, ...]
    ) -> tuple[tuple[TradeRecord, ...], dict[str, TaxStatus]]:
        """R-02/CMP-01/CMP-02: revalidate forged models and every ownership link."""
        if not isinstance(history, tuple) or not isinstance(accounts, tuple):
            raise DataIntegrityError("Wash-sale evidence must be immutable tuples")
        checked_accounts = tuple(ExternalAccount.model_validate(row) for row in accounts)
        statuses = {row.account_id: row.tax_status for row in checked_accounts}
        if len(statuses) != len(checked_accounts):
            raise DataIntegrityError("Tax account identifiers must be unique")
        ordered = tuple(
            sorted(
                (TradeRecord.model_validate(row) for row in history),
                key=lambda row: (row.ts, 0 if row.side == Side.BUY else 1, str(row.trade_id)),
            )
        )
        if len({row.trade_id for row in ordered}) != len(ordered):
            raise DataIntegrityError("Executed trade identifiers must be unique")
        for trade in ordered:
            if trade.account_id not in statuses:
                raise DataIntegrityError("Executed trade ownership/tax status is unknown")
            self.registry.get(trade.symbol)
            if (
                trade.side == Side.SELL
                and trade.holding_period_start is None
                and trade.acquisition_trade_id is None
                and any(
                    row.side == Side.BUY
                    and row.account_id == trade.account_id
                    and row.symbol == trade.symbol
                    and row.ts == trade.ts
                    for row in ordered
                )
            ):
                raise DataIntegrityError("Tied BUY/SELL execution requires original-lot metadata")
        return ordered, statuses

    @staticmethod
    def _survivors(ordered: tuple[TradeRecord, ...]) -> dict[UUID, dict[UUID, int]]:
        """CMP-02: replay lot disposals before checking replacement availability."""
        inventory: dict[UUID, int] = {}
        purchases: dict[UUID, TradeRecord] = {}
        result: dict[UUID, dict[UUID, int]] = {}
        for trade in ordered:
            if trade.side == Side.BUY:
                purchases[trade.trade_id] = trade
                inventory[trade.trade_id] = trade.qty
                continue
            candidates = tuple(
                buy
                for buy in purchases.values()
                if buy.account_id == trade.account_id and buy.symbol == trade.symbol
            )
            selected: tuple[TradeRecord, ...]
            if trade.acquisition_trade_id is not None:
                origin = purchases.get(trade.acquisition_trade_id)
                if origin is None or origin not in candidates:
                    raise DataIntegrityError("SELL references an unavailable original purchase")
                if (
                    trade.holding_period_start is not None
                    and trade.holding_period_start > origin.ts
                ):
                    raise DataIntegrityError("SELL holding-period evidence disagrees with purchase")
                selected = (origin,)
            elif trade.holding_period_start is not None:
                selected = tuple(buy for buy in candidates if buy.ts == trade.holding_period_start)
                if len(selected) > 1:
                    raise DataIntegrityError("SELL original purchase is ambiguous; supply its ID")
            else:
                selected = candidates
            remaining = trade.qty
            for buy in selected:
                disposed = min(remaining, inventory[buy.trade_id])
                inventory[buy.trade_id] -= disposed
                remaining -= disposed
                if remaining == 0:
                    break
            if selected and remaining:
                raise DataIntegrityError("SELL exceeds verified original-purchase inventory")
            if trade.realized_loss > 0:
                result[trade.trade_id] = inventory.copy()
        return result

    @staticmethod
    def _adjustment(
        loss: TradeRecord,
        replacement: TradeRecord,
        matched: int,
        disallowed: Decimal,
        statuses: dict[str, TaxStatus],
        acquired_at: datetime | None = None,
    ) -> WashAdjustment:
        """CMP-01/CMP-02: preserve exact basis and tack the old holding duration."""
        if loss.holding_period_start is None:
            raise DataIntegrityError("Loss sale lacks holding-period metadata")
        permanent = statuses[replacement.account_id] in (TaxStatus.IRA, TaxStatus.ROTH)
        with localcontext() as context:
            context.prec = 80
            proceeds = loss.price * matched
            cost_basis = proceeds + disallowed
            adjusted = None if permanent else replacement.price * matched + disallowed
        held_days = (trade_day(loss.ts) - trade_day(loss.holding_period_start)).days
        tacked_start = (
            replacement.ts.astimezone(_NEW_YORK) - timedelta(days=held_days)
        ).astimezone(UTC)
        return WashAdjustment(
            loss_trade_id=loss.trade_id,
            replacement_trade_id=replacement.trade_id,
            loss_account_id=loss.account_id,
            replacement_account_id=replacement.account_id,
            symbol=loss.symbol,
            qty=matched,
            sale_date=trade_day(loss.ts),
            acquired_date=trade_day(
                loss.holding_period_start if acquired_at is None else acquired_at
            ),
            proceeds=proceeds,
            cost_basis=cost_basis,
            disallowed_loss=disallowed,
            adjusted_basis=adjusted,
            holding_period_start=tacked_start,
            permanent_loss=permanent,
        )

    @staticmethod
    def form_8949_rows(adjustments: tuple[WashAdjustment, ...]) -> tuple[Form8949Row, ...]:
        """CMP-02: export disjoint matched slices, never duplicate a whole sale.

        Unmatched loss shares require their separate broker-1099-B rows. These
        reconciliation estimates do not replace the broker filing record.
        """
        # VERIFY: https://www.irs.gov/instructions/i8949
        try:
            if not isinstance(adjustments, tuple):
                raise DataIntegrityError("Form 8949 evidence must be an immutable tuple")
            checked = tuple(WashAdjustment.model_validate(row) for row in adjustments)
            pairs = {(row.loss_trade_id, row.replacement_trade_id) for row in checked}
            if len(pairs) != len(checked):
                raise DataIntegrityError("Form 8949 evidence repeats a loss/replacement slice")
            with localcontext() as context:
                context.prec = 80
                return tuple(
                    Form8949Row(
                        account_id=row.loss_account_id,
                        loss_trade_id=row.loss_trade_id,
                        description=f"{row.qty} {row.symbol}",
                        date_acquired=row.acquired_date,
                        date_sold=row.sale_date,
                        proceeds=row.proceeds,
                        cost_basis=row.cost_basis,
                        adjustment=row.disallowed_loss,
                        gain_or_loss=row.proceeds - row.cost_basis + row.disallowed_loss,
                    )
                    for row in checked
                )
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot verify Form 8949 wash-sale evidence") from exc
````````
<!-- END FILE backend/risk/wash_sales.py -->

### backend/risk/compliance_boundary.py

<!-- BEGIN FILE backend/risk/compliance_boundary.py -->
````````python
"""R-02/R-03/CMP-01..07: compliance audit and HALT effects outside pure rules."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from backend.core.clock import Clock, ensure_utc
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.domain.models import (
    AccountFlags,
    Intent,
    PortfolioSnapshot,
    Severity,
    TradeProposal,
    snapshot_hash,
)
from backend.risk.compliance import (
    ComplianceAssessment,
    ComplianceEngine,
    ExternalAccount,
    TaxLot,
    TradeRecord,
)


class ComplianceFindingSink(Protocol):
    """R-07: audit only nonsensitive rule/proposal/severity identities."""

    def record(self, rule_id: str, proposal_id: UUID, severity: Severity) -> None:
        """R-02: an unavailable sink raises rather than silently dropping evidence."""
        raise DataIntegrityError("R-02: compliance audit sink has no implementation")


class LoggingComplianceFindingSink:
    """CMP-01..07/R-07: static text; no external account/history payload in logs."""

    def record(self, rule_id: str, proposal_id: UUID, severity: Severity) -> None:
        logging.getLogger(__name__).warning(
            "compliance_finding rule_id=%s proposal_id=%s severity=%s",
            rule_id,
            proposal_id,
            severity,
        )


class ComplianceBoundary:
    """R-02/R-03/CMP-06: pure evidence plus durable fault escalation.

    This assessment does not authorize an alert or a trade ticket. The later
    service combines it with CRO evidence and fresh authenticated human approval.
    Current broker restrictions and unexpected provider/input faults persist a
    HALT. A valid held exit still receives WARN findings (R-09); subsequent CRO
    calls observe the persisted HALTED state and require the manual exception.
    """

    def __init__(
        self,
        engine: ComplianceEngine,
        state: SystemStateStore,
        clock: Clock,
        *,
        finding_sink: ComplianceFindingSink | None = None,
    ) -> None:
        self.engine = engine
        self.state = state
        self.clock = clock
        self.finding_sink = LoggingComplianceFindingSink() if finding_sink is None else finding_sink

    def _checked(
        self,
        assessment: ComplianceAssessment,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        now: datetime,
        flags: AccountFlags | None,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
    ) -> ComplianceAssessment:
        """R-02/R-03/R-09: complete bound evidence cannot silently change severity."""
        checked = ComplianceAssessment.model_validate(assessment)
        proposal = TradeProposal.model_validate(proposal)
        try:
            identity = self.engine.input_hash(
                proposal, snapshot, lots, history, external_accounts, flags
            )
        except DataIntegrityError:
            identity = "0" * 64
        if checked.input_hash != identity or (
            identity == "0" * 64
            and (
                checked.recommended_state != SystemState.HALTED
                or all(row.passed for row in checked.results)
            )
        ):
            raise DataIntegrityError("R-03: compliance assessment inputs do not match")
        if (
            checked.proposal_id != proposal.proposal_id
            or checked.config_hash != self.engine.config.config_hash
            or checked.evaluated_at != now
            or tuple(row.rule_id for row in checked.results)
            != tuple(f"CMP-{number:02d}" for number in range(1, 8))
        ):
            raise DataIntegrityError(
                "R-02: compliance assessment provenance or evidence is invalid"
            )
        if checked.snapshot_hash != snapshot_hash(snapshot):
            # Invalid input can produce a maximally restrictive auditable report.
            # The ordinary snapshot_hash path still validates every valid input.
            if (
                checked.snapshot_hash != "0" * 64
                or checked.recommended_state != SystemState.HALTED
                or any(row.passed for row in checked.results)
            ):
                raise DataIntegrityError("R-03: compliance assessment snapshot does not match")
        exit_trade = proposal.intent in {Intent.REDUCE, Intent.EXIT}
        if exit_trade:
            held = snapshot.positions.get(proposal.symbol)
            pending = sum(
                order.qty
                for order in snapshot.open_orders
                if order.symbol == proposal.symbol and order.side.value == "SELL"
            )
            verifiable = (
                held is not None
                and proposal.qty <= held.qty - pending
                and proposal.account_id == snapshot.account_id
                and proposal.created_at <= checked.evaluated_at < proposal.expires_at
                and timedelta(0)
                <= now - snapshot.as_of
                <= timedelta(seconds=self.engine.config.stale_quote_seconds)
            )
            if verifiable and any(row.severity != Severity.WARN for row in checked.results):
                raise DataIntegrityError("R-09: compliance evidence would trap a verifiable exit")
        else:
            for row in checked.results:
                if (
                    row.rule_id in {"CMP-03", "CMP-04", "CMP-06", "CMP-07"}
                    and row.severity != Severity.BLOCK
                ):
                    raise DataIntegrityError("R-02: compliance blocking-rule severity was altered")
            forward = checked.results[0]
            if self.engine.config.wash_sale_mode == "BLOCK" and forward.severity != Severity.BLOCK:
                raise DataIntegrityError("CMP-01: configured BLOCK policy was downgraded")
        broker = checked.results[5]
        try:
            expected_blocked = flags is None or AccountFlags.model_validate(flags).blocked
        except (ValueError, TypeError):
            expected_blocked = True
        if expected_blocked and broker.passed:
            raise DataIntegrityError("CMP-06: assessment concealed missing or blocked broker flags")
        if not broker.passed and checked.recommended_state != SystemState.HALTED:
            raise DataIntegrityError("CMP-06: broker restriction must recommend HALTED")
        return checked

    def evaluate(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
        *,
        flags: AccountFlags | None = None,
    ) -> ComplianceAssessment:
        """R-02/CMP-06: any boundary failure logs, halts, and raises a typed error."""
        try:
            now = ensure_utc(self.clock.now())
            self.state.ledger.verify_chain()
            self.state.current()
            assessment = self._checked(
                self.engine.assess(
                    proposal, snapshot, lots, history, external_accounts, now, flags=flags
                ),
                proposal,
                snapshot,
                now,
                flags,
                lots,
                history,
                external_accounts,
            )
            self.state.escalate(assessment.recommended_state, "CMP-06 compliance assessment")
            for row in assessment.results:
                if not row.passed:
                    # Identity has been checked above; no invalid None can reach the sink.
                    self.finding_sink.record(row.rule_id, proposal.proposal_id, row.severity)
            return assessment
        except Exception as exc:
            try:
                logging.getLogger(__name__).error(
                    "compliance_boundary_fault error_type=%s", type(exc).__name__
                )
            except Exception as log_error:
                exc = DataIntegrityError(
                    f"R-02: compliance fault audit unavailable ({type(log_error).__name__})"
                )
            try:
                self.state.halt_for_error(exc)
            except Exception as halt_error:
                raise DataIntegrityError(
                    "R-02: compliance boundary failed; HALT persistence unavailable"
                ) from halt_error
            raise DataIntegrityError("R-02: compliance boundary failed and latched HALTED") from exc
````````
<!-- END FILE backend/risk/compliance_boundary.py -->

### backend/tests/test_compliance.py

<!-- BEGIN FILE backend/tests/test_compliance.py -->
````````python
"""CMP-01..07/R-02/R-09: exact boundaries, cross-account matching and faults."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    Intent,
    OpenOrder,
    Position,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
    snapshot_hash,
)
from backend.risk.compliance import (
    ComplianceEngine,
    ExternalAccount,
    TaxLot,
    TaxStatus,
    TradeRecord,
)
from backend.tests.test_domain import NOW, instrument, proposal, snapshot

ACCOUNTS = (
    ExternalAccount(account_id="paper", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="other", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="ira", tax_status=TaxStatus.IRA),
    ExternalAccount(account_id="roth", tax_status=TaxStatus.ROTH),
)
FLAGS = AccountFlags(
    trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
)


def uid(value: int) -> UUID:
    return UUID(int=value)


def trade(
    value: int,
    *,
    side: Side = Side.BUY,
    days: int = -1,
    qty: int = 10,
    loss: str = "0",
    account: str = "paper",
    symbol: str = "AAPL",
    ts: datetime | None = None,
    price: str = "100",
) -> TradeRecord:
    return TradeRecord(
        trade_id=uid(value),
        account_id=account,
        symbol=symbol,
        side=side,
        qty=qty,
        price=Decimal(price),
        ts=ts if ts is not None else NOW + timedelta(days=days),
        realized_loss=Decimal(loss),
        holding_period_start=NOW - timedelta(days=100) if Decimal(loss) > 0 else None,
    )


def lot(
    value: int = 1,
    *,
    qty: int = 1,
    basis: str = "110",
    days: int = -100,
    funding: date | None = None,
) -> TaxLot:
    return TaxLot(
        lot_id=uid(value),
        account_id="paper",
        symbol="AAPL",
        qty=qty,
        acquired_at=NOW + timedelta(days=days),
        cost_basis=Decimal(basis),
        funding_settlement_date=funding,
    )


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2024, 1, 2), end=date(2027, 12, 31))


@pytest.fixture
def engine(calendar: MarketCalendar) -> ComplianceEngine:
    registry = InstrumentRegistry(
        [instrument(), instrument("MSFT")],
        identical_groups={"TEST_OPERATOR_GROUP": ("AAPL", "MSFT")},
    )
    return ComplianceEngine(Settings(), registry, calendar)


def check(
    engine: ComplianceEngine,
    *,
    selling: bool = False,
    history: tuple[TradeRecord, ...] = (),
    lots: tuple[TaxLot, ...] = (),
    state_changes: dict[str, object] | None = None,
    proposal_changes: dict[str, object] | None = None,
    flags: AccountFlags | None = FLAGS,
    accounts: tuple[ExternalAccount, ...] = ACCOUNTS,
) -> dict[str, RuleResult]:
    changes: dict[str, object] = (
        {"side": Side.SELL, "intent": Intent.EXIT, "stop_price": None} if selling else {}
    )
    changes.update(proposal_changes or {})
    return {
        row.rule_id: row
        for row in engine.check(
            proposal(**changes),
            snapshot(**(state_changes or {})),
            lots,
            history,
            accounts,
            NOW,
            flags=flags,
        )
    }


@pytest.mark.parametrize("days,expected", [(-30, False), (-31, True), (-1, False), (0, False)])
def test_CMP_01_forward_day30_inclusive_day31_excluded(
    engine: ComplianceEngine, days: int, expected: bool
) -> None:
    result = check(engine, history=(trade(1, side=Side.SELL, days=days, loss="100"),))["CMP-01"]
    assert result.passed is expected
    assert result.severity == Severity.BLOCK
    assert Decimal(result.observed) == (Decimal(0) if expected else Decimal("10"))


def test_CMP_01_warn_mode_and_forward_ira_permanent_loss(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    warning = ComplianceEngine(Settings(wash_sale_mode="WARN"), engine.registry, calendar)
    result = check(warning, history=(trade(1, side=Side.SELL, account="other", loss="100"),))[
        "CMP-01"
    ]
    assert not result.passed and result.severity == Severity.WARN
    candidate = proposal(account_id="ira")
    state = snapshot(account_id="ira")
    results = engine.check(
        candidate, state, (), (trade(2, side=Side.SELL, loss="100"),), ACCOUNTS, NOW, flags=FLAGS
    )
    forward = next(row for row in results if row.rule_id == "CMP-01")
    assert "permanent loss" in forward.message and not forward.passed


@pytest.mark.parametrize("days,expected", [(-30, False), (-31, True), (-1, False), (0, False)])
def test_CMP_02_backward_cross_account_substantially_identical_day_boundary(
    engine: ComplianceEngine, days: int, expected: bool
) -> None:
    result = check(
        engine,
        selling=True,
        lots=(lot(),),
        history=(trade(1, days=days, symbol="MSFT", account="other", qty=1),),
    )["CMP-02"]
    assert result.passed is expected and result.severity == Severity.WARN
    assert Decimal(result.observed) == (Decimal(0) if expected else Decimal("10"))


def test_CMP_02_backward_sale_profit_and_ira_loss_are_warn_only(engine: ComplianceEngine) -> None:
    profitable = check(engine, selling=True, lots=(lot(basis="90"),), history=(trade(1),))["CMP-02"]
    assert profitable.passed
    permanent = check(engine, selling=True, lots=(lot(),), history=(trade(1, account="ira"),))[
        "CMP-02"
    ]
    assert not permanent.passed and "permanent" in permanent.message
    assert all(
        row.severity == Severity.WARN
        for row in check(
            engine, selling=True, lots=(lot(),), history=(trade(1, account="ira"),)
        ).values()
    )


def test_CMP_01_CMP_02_share_capacity_is_shared_across_multiple_loss_sales(
    engine: ComplianceEngine,
) -> None:
    losses = (
        trade(1, side=Side.SELL, days=-2, qty=5, loss="50"),
        trade(2, side=Side.SELL, days=-1, qty=5, loss="100"),
    )
    replacement = trade(3, days=0, qty=6, account="other")
    rows = engine.wash_adjustments((*losses, replacement), ACCOUNTS)
    assert [row.qty for row in rows] == [5, 1]
    assert [row.disallowed_loss for row in rows] == [Decimal("50"), Decimal("20")]
    assert sum(row.qty for row in rows) == replacement.qty
    assert sum((row.disallowed_loss for row in rows), Decimal(0)) == Decimal("70")


def test_CMP_02_61_day_window_partial_lots_basis_tacking_and_8949(engine: ComplianceEngine) -> None:
    sale = trade(1, side=Side.SELL, days=0, qty=10, loss="100", price="90")
    records = (
        trade(2, days=-30, qty=2, price="95"),
        sale,
        trade(3, days=30, qty=3, price="80"),
        trade(4, days=31, qty=10),
    )
    rows = engine.wash_adjustments(records, ACCOUNTS)
    assert [row.qty for row in rows] == [2, 3]
    assert [row.disallowed_loss for row in rows] == [Decimal("20"), Decimal("30")]
    assert [row.adjusted_basis for row in rows] == [Decimal("210"), Decimal("270")]
    assert rows[0].holding_period_start == records[0].ts - timedelta(days=100)
    # Holding periods count exchange-local calendar days across November DST.
    assert rows[1].holding_period_start == datetime(2026, 7, 24, 15, tzinfo=UTC)
    assert rows[1].holding_period_start.astimezone(ZoneInfo("America/New_York")).date() == date(
        2026, 7, 24
    )
    exported = engine.form_8949_rows(rows)
    assert [row.code for row in exported] == ["W", "W"]
    assert [row.adjustment for row in exported] == [Decimal("20"), Decimal("30")]
    assert [row.proceeds for row in exported] == [Decimal("180"), Decimal("270")]
    assert all(row.gain_or_loss == 0 for row in exported)


@pytest.mark.parametrize("account", ["ira", "roth"])
def test_CMP_01_ira_roth_replacement_does_not_adjust_retirement_basis(
    engine: ComplianceEngine, account: str
) -> None:
    rows = engine.wash_adjustments(
        (trade(1, side=Side.SELL, loss="100"), trade(2, days=0, qty=2, account=account)), ACCOUNTS
    )
    assert rows[0].permanent_loss and rows[0].adjusted_basis is None
    assert rows[0].disallowed_loss == Decimal("20")


def test_CMP_02_fractional_loss_allocation_reconciles_exact_total(engine: ComplianceEngine) -> None:
    rows = engine.wash_adjustments(
        (
            trade(1, side=Side.SELL, qty=3, loss="1"),
            trade(2, days=0, qty=1),
            trade(3, days=0, qty=2),
        ),
        ACCOUNTS,
    )
    assert [row.disallowed_loss for row in rows] == [Decimal("0.333333"), Decimal("0.666667")]
    assert sum((row.disallowed_loss for row in rows), Decimal(0)) == Decimal(1)


@pytest.mark.parametrize("cash,expected", [("100", True), ("99.99", False), ("100.01", True)])
def test_CMP_03_settled_cash_exact_notional_boundary(
    engine: ComplianceEngine, cash: str, expected: bool
) -> None:
    assert check(engine, state_changes={"settled_cash": Decimal(cash)})["CMP-03"].passed is expected


def test_CMP_03_pending_buys_reserve_settled_cash_and_margin_is_exempt(
    engine: ComplianceEngine,
) -> None:
    pending = OpenOrder(symbol="AAPL", side=Side.BUY, qty=1, limit_price=Decimal("100"))
    assert not check(
        engine, state_changes={"settled_cash": Decimal("199.99"), "open_orders": (pending,)}
    )["CMP-03"].passed
    assert check(
        engine, state_changes={"account_type": AccountType.MARGIN, "settled_cash": Decimal(0)}
    )["CMP-03"].passed


@pytest.mark.parametrize(
    "funding,expected",
    [
        (date(2026, 10, 1), True),
        (date(2026, 10, 2), False),
        (date(2026, 10, 5), False),
        (None, False),
    ],
)
def test_CMP_03_good_faith_sale_only_warns_at_settlement_boundary(
    engine: ComplianceEngine, funding: date | None, expected: bool
) -> None:
    row = check(engine, selling=True, lots=(lot(funding=funding),))["CMP-03"]
    assert row.passed is expected and row.severity == Severity.WARN


@pytest.mark.parametrize(
    "ts,expected",
    [
        (datetime(2026, 7, 3, 0, 30, tzinfo=UTC), date(2026, 7, 6)),
        (datetime(2025, 11, 27, 0, 30, tzinfo=UTC), date(2025, 11, 28)),
        (datetime(2026, 12, 24, 17, tzinfo=UTC), date(2026, 12, 28)),
    ],
)
def test_CMP_03_T_plus_one_uses_new_york_trade_date_with_holidays(
    engine: ComplianceEngine, ts: datetime, expected: date
) -> None:
    assert engine.settlement_date(ts) == expected


def test_CMP_03_settled_cash_reconstruction_does_not_credit_unsettled_sales(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    executed = datetime(2026, 7, 2, 16, tzinfo=UTC)
    rows = (
        trade(1, side=Side.SELL, ts=executed, qty=2),
        trade(2, side=Side.BUY, ts=executed, qty=1),
        trade(3, side=Side.SELL, ts=executed, account="other"),
    )
    closed = calendar.session_close(date(2026, 7, 6))
    assert engine.settled_cash_as_of(
        Decimal("500"), rows, closed - timedelta(microseconds=1), account_id="paper"
    ) == Decimal("400")
    assert engine.settled_cash_as_of(Decimal("500"), rows, closed, account_id="paper") == Decimal(
        "600"
    )


@pytest.mark.parametrize("cash,expected", [("100", True), ("99.99", False), ("100.01", True)])
def test_CMP_04_no_borrowing_exact_cash_boundary(
    engine: ComplianceEngine, cash: str, expected: bool
) -> None:
    assert check(engine, state_changes={"cash": Decimal(cash)})["CMP-04"].passed is expected


@pytest.mark.parametrize("equity,expected", [("2000", True), ("1999.99", False), ("2000.01", True)])
def test_CMP_04_margin_minimum_equity_operator_guard_boundary(
    engine: ComplianceEngine, equity: str, expected: bool
) -> None:
    assert (
        check(
            engine, state_changes={"account_type": AccountType.MARGIN, "equity": Decimal(equity)}
        )["CMP-04"].passed
        is expected
    )


def legacy_history() -> tuple[TradeRecord, ...]:
    rows: list[TradeRecord] = []
    for index, day in enumerate((28, 29, 30)):
        opened = datetime(2026, 9, day, 14, tzinfo=UTC)
        rows.extend(
            (
                trade(index * 2 + 1, ts=opened),
                trade(index * 2 + 2, side=Side.SELL, ts=opened + timedelta(hours=1)),
            )
        )
    rows.append(trade(20, side=Side.SELL, ts=NOW - timedelta(hours=1)))
    return tuple(rows)


@pytest.mark.parametrize(
    "regime,equity,severity",
    [
        ("INTRADAY_MARGIN", "24999.99", Severity.WARN),
        ("LEGACY_PDT", "24999.99", Severity.BLOCK),
        ("LEGACY_PDT", "25000", Severity.WARN),
        ("LEGACY_PDT", "25000.01", Severity.WARN),
    ],
)
def test_CMP_05_both_regimes_and_25000_exact_legacy_boundary(
    engine: ComplianceEngine, calendar: MarketCalendar, regime: str, equity: str, severity: Severity
) -> None:
    guarded = ComplianceEngine(
        Settings.model_validate({"day_trade_regime": regime}), engine.registry, calendar
    )
    row = check(
        guarded,
        history=legacy_history(),
        state_changes={"account_type": AccountType.MARGIN, "equity": Decimal(equity)},
    )["CMP-05"]
    assert not row.passed and row.severity == severity
    assert "completed=3" in row.observed


def test_CMP_05_legacy_three_count_and_cash_account_boundary(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    guarded = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), engine.registry, calendar)
    for history in (legacy_history()[2:], legacy_history()):
        row = check(guarded, history=history)["CMP-05"]
        assert row.severity == Severity.WARN
    assert check(guarded)["CMP-05"].passed
    exit_result = check(
        guarded, selling=True, lots=(lot(),), history=(*legacy_history()[:-1], trade(30, days=0))
    )["CMP-05"]
    assert not exit_result.passed and exit_result.severity == Severity.WARN


@pytest.mark.parametrize(
    "field", ["trading_blocked", "account_blocked", "trade_suspended_by_user", "status", "missing"]
)
def test_CMP_06_each_exact_current_broker_flag_requires_halt(
    engine: ComplianceEngine, field: str
) -> None:
    flags = (
        None
        if field == "missing"
        else FLAGS.model_copy(update={field: "ACCOUNT_UPDATED" if field == "status" else True})
    )
    row = check(engine, flags=flags)["CMP-06"]
    assert not row.passed and row.severity == Severity.BLOCK and "HALTED required" in row.message
    assert (
        check(engine, selling=True, lots=(lot(),), flags=flags)["CMP-06"].severity == Severity.WARN
    )


def test_CMP_07_allowlist_restricted_leveraged_inverse_and_unknown_names(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    assert check(engine)["CMP-07"].passed
    restricted = ComplianceEngine(
        Settings(), engine.registry, calendar, restricted_symbols=frozenset({"AAPL"})
    )
    assert not check(restricted)["CMP-07"].passed
    registry = InstrumentRegistry.from_csv(Path(__file__).resolve().parents[2] / "config")
    sample = ComplianceEngine(Settings(), registry, calendar)
    for symbol in ("TQQQ", "SH", "UNKNOWN"):
        row = check(sample, proposal_changes={"symbol": symbol})["CMP-07"]
        assert not row.passed and row.severity == Severity.BLOCK


@pytest.mark.parametrize(
    "fault",
    [
        "account",
        "future_snapshot",
        "future_proposal",
        "missing_account",
        "future_trade",
        "unknown_trade_account",
        "future_lot",
        "unknown_lot_account",
        "duplicate_trade",
        "duplicate_lot",
        "duplicate_account",
        "executed_proposal",
    ],
)
def test_R_02_compliance_corrupt_state_warns_only_verifiable_exits(
    engine: ComplianceEngine, fault: str
) -> None:
    states: dict[str, object] = {}
    proposed: dict[str, object] = {}
    rows: tuple[TradeRecord, ...] = ()
    lots: tuple[TaxLot, ...] = (lot(),)
    accounts: tuple[ExternalAccount, ...] = ACCOUNTS
    if fault == "account":
        states["account_id"] = "mismatch"
    elif fault == "future_snapshot":
        states["as_of"] = NOW + timedelta(seconds=1)
    elif fault == "future_proposal":
        proposed["created_at"] = NOW + timedelta(seconds=1)
    elif fault == "missing_account":
        accounts = ACCOUNTS[1:]
    elif fault == "future_trade":
        rows = (trade(1, days=1),)
    elif fault == "unknown_trade_account":
        rows = (trade(1, account="unknown"),)
    elif fault == "future_lot":
        lots = (lot(days=1),)
    elif fault == "unknown_lot_account":
        lots = (lot().model_copy(update={"account_id": "unknown"}),)
    elif fault == "duplicate_trade":
        rows = (trade(1), trade(1))
    elif fault == "duplicate_lot":
        lots = (lot(), lot())
    elif fault == "duplicate_account":
        accounts = (*ACCOUNTS, ACCOUNTS[0])
    else:
        rows = (trade(1).model_copy(update={"trade_id": proposal().proposal_id}),)
    for selling in (False, True):
        results = check(
            engine,
            selling=selling,
            state_changes=states,
            proposal_changes=proposed,
            history=rows,
            lots=lots,
            accounts=accounts,
        )
        assert len(results) == 7
        assert all(not row.passed for row in results.values())
        valid_exit = selling and fault not in {"account", "future_snapshot", "future_proposal"}
        assert all(
            row.severity == (Severity.WARN if valid_exit else Severity.BLOCK)
            for row in results.values()
        )


def test_R_02_calendar_provider_fault_is_block_for_entry_warning_for_exit(
    engine: ComplianceEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(day: date) -> bool:
        del day
        raise RuntimeError("calendar failed")

    monkeypatch.setattr(engine.calendar, "is_session", broken)
    assert not check(engine)["CMP-05"].passed
    assert check(engine)["CMP-05"].severity == Severity.BLOCK
    assert check(engine, selling=True, lots=(lot(),))["CMP-05"].severity == Severity.WARN


def test_R_02_wash_helper_duplicate_unknown_and_missing_holding_period_fail_typed(
    engine: ComplianceEngine,
) -> None:
    bad = trade(1, side=Side.SELL, loss="100").model_copy(update={"holding_period_start": None})
    for rows in ((trade(1), trade(1)), (trade(1, account="unknown"),), (bad,)):
        with pytest.raises(DataIntegrityError):
            engine.wash_adjustments(rows, ACCOUNTS)
    with pytest.raises(DataIntegrityError):
        engine.wash_adjustments(
            (trade(1, side=Side.SELL, qty=3, loss="0.000001"), trade(2, days=0, qty=1)), ACCOUNTS
        )


def test_CMP_02_loss_sale_requires_holding_metadata_and_no_future_start() -> None:
    with pytest.raises(ValidationError):
        trade(1, side=Side.BUY, loss="100")
    with pytest.raises(ValidationError):
        TradeRecord.model_validate(
            {**trade(1, side=Side.SELL, loss="100").model_dump(), "holding_period_start": None}
        )
    with pytest.raises(ValidationError):
        trade(1).model_copy(
            update={"holding_period_start": NOW + timedelta(days=1)}
        ).model_validate({**trade(1).model_dump(), "holding_period_start": NOW + timedelta(days=1)})


def test_R_02_none_proposal_is_never_success(engine: ComplianceEngine) -> None:
    results = engine.check(cast(object, None), snapshot(), (), (), ACCOUNTS, NOW, flags=FLAGS)  # type: ignore[arg-type]
    assert len(results) == 7 and all(
        not row.passed and row.severity == Severity.BLOCK for row in results
    )


def test_R_03_compliance_is_deterministic(engine: ComplianceEngine) -> None:
    rows = (trade(1, side=Side.SELL, loss="100"),)
    first = engine.check(proposal(), snapshot(), (), rows, ACCOUNTS, NOW, flags=FLAGS)
    second = engine.check(proposal(), snapshot(), (), rows, ACCOUNTS, NOW, flags=FLAGS)
    assert first == second and len(first) == 7


def test_CMP_02_exhausted_replacement_shares_are_not_reused(engine: ComplianceEngine) -> None:
    rows = engine.wash_adjustments(
        (
            trade(1, side=Side.SELL, days=-2, qty=5, loss="50"),
            trade(2, side=Side.SELL, days=-1, qty=5, loss="100"),
            trade(3, days=0, qty=5),
            trade(4, days=0, qty=1),
        ),
        ACCOUNTS,
    )
    assert [(row.loss_trade_id, row.replacement_trade_id, row.qty) for row in rows] == [
        (uid(1), uid(3), 5),
        (uid(2), uid(4), 1),
    ]


@pytest.mark.parametrize("fault", ["missing_lots", "oversell", "no_position"])
def test_R_09_CMP_02_only_held_exit_with_incomplete_lots_is_warning_only(
    engine: ComplianceEngine, fault: str
) -> None:
    changes: dict[str, object] = {"qty": 2} if fault == "oversell" else {}
    states: dict[str, object] = {"positions": {}} if fault == "no_position" else {}
    lots = () if fault == "missing_lots" else (lot(),)
    results = check(engine, selling=True, lots=lots, state_changes=states, proposal_changes=changes)
    assert not results["CMP-02"].passed
    expected = Severity.WARN if fault == "missing_lots" else Severity.BLOCK
    assert all(row.severity == expected for row in results.values())


def test_CMP_02_fifo_sale_stops_before_unselected_lot(engine: ComplianceEngine) -> None:
    held = Position(qty=2, avg_cost=Decimal("110"), last_price=Decimal("100"))
    results = check(
        engine,
        selling=True,
        lots=(lot(1), lot(2, basis="999", days=-90)),
        state_changes={"positions": {"AAPL": held}},
        history=(trade(3, days=-1, qty=1),),
    )
    assert results["CMP-02"].observed == "10"


@pytest.mark.parametrize("equity", ["2000", "5000", "25000", "100000"])
@pytest.mark.parametrize("cash", ["99.99", "100.00", "100.01"])
def test_CMP_03_CMP_04_cash_cent_boundary_at_each_equity(
    engine: ComplianceEngine, equity: str, cash: str
) -> None:
    rows = check(
        engine,
        state_changes={
            "equity": Decimal(equity),
            "cash": Decimal(cash),
            "settled_cash": Decimal(cash),
        },
    )
    expected = Decimal(cash) >= Decimal(100)
    assert rows["CMP-03"].passed is expected
    assert rows["CMP-04"].passed is expected


@pytest.mark.parametrize("fault", ["config", "calendar", "registry", "restricted", "telegram"])
def test_R_02_compliance_constructor_revalidates_detached_policy(
    engine: ComplianceEngine, calendar: MarketCalendar, fault: str
) -> None:
    policy = Settings()
    registry = engine.registry
    clock_calendar = calendar
    restricted = frozenset[str]()
    if fault == "config":
        policy = policy.model_copy(update={"max_risk_per_trade": Decimal("0.03")})
    elif fault == "calendar":
        clock_calendar = cast(MarketCalendar, None)
    elif fault == "registry":
        registry = cast(InstrumentRegistry, None)
    elif fault == "restricted":
        restricted = frozenset({"UNKNOWN"})
    else:
        policy = policy.model_copy(update={"telegram_allowed_user_ids": ()})
    with pytest.raises(ConfigurationError):
        ComplianceEngine(policy, registry, clock_calendar, restricted_symbols=restricted)


def test_R_02_compliance_constructor_accepts_configured_telegram_and_copies_restrictions(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    blocked = {"AAPL"}
    copied = ComplianceEngine(
        Settings(telegram_allowed_user_ids=(42,)),
        engine.registry,
        calendar,
        restricted_symbols=cast(frozenset[str], blocked),
    )
    blocked.clear()
    assert copied.config.telegram_allowed_user_ids == (42,)
    assert not check(copied)["CMP-07"].passed


def test_CMP_01_CMP_07_normal_failures_do_not_request_halt(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    restricted = ComplianceEngine(
        Settings(), engine.registry, calendar, restricted_symbols=frozenset({"AAPL"})
    )
    assessment = restricted.assess(
        proposal(),
        snapshot(cash=Decimal("99.99"), settled_cash=Decimal("99.99")),
        (),
        (trade(1, side=Side.SELL, loss="100"),),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert assessment.recommended_state == SystemState.RUNNING
    assert {row.rule_id for row in assessment.results if not row.passed} == {
        "CMP-01",
        "CMP-03",
        "CMP-04",
        "CMP-07",
    }
    assert assessment.proposal_id == proposal().proposal_id
    assert assessment.config_hash == restricted.config.config_hash
    assert assessment.snapshot_hash == snapshot_hash(
        snapshot(cash=Decimal("99.99"), settled_cash=Decimal("99.99"))
    )
    assert assessment.evaluated_at == NOW


def test_CMP_06_failed_flags_and_calendar_fault_request_halt(
    engine: ComplianceEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = engine.assess(proposal(), snapshot(), (), (), ACCOUNTS, NOW)
    assert blocked.recommended_state == SystemState.HALTED
    assert blocked.snapshot_hash == snapshot_hash(snapshot())

    def fail(day: date) -> bool:
        del day
        raise RuntimeError("untrusted failure detail")

    monkeypatch.setattr(engine.calendar, "is_session", fail)
    failed = engine.assess(proposal(), snapshot(), (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert failed.recommended_state == SystemState.HALTED
    assert failed.results[4].rule_id == "CMP-05" and not failed.results[4].passed
    assert "untrusted failure detail" not in str(failed)


@pytest.mark.parametrize("seconds,expected", [(60, True), (60.000001, False), (-0.000001, False)])
def test_R_05_snapshot_freshness_exact_inclusive_boundary(
    engine: ComplianceEngine, seconds: float, expected: bool
) -> None:
    assessment = engine.assess(
        proposal(),
        snapshot(as_of=NOW - timedelta(seconds=seconds)),
        (),
        (),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert all(row.passed for row in assessment.results) is expected
    assert assessment.recommended_state == (SystemState.RUNNING if expected else SystemState.HALTED)


@pytest.mark.parametrize("offset,expected", [(-1, False), (0, False), (1, True)])
def test_R_05_proposal_expiry_is_exclusive_at_exact_timestamp(
    engine: ComplianceEngine, offset: int, expected: bool
) -> None:
    candidate = proposal(
        created_at=NOW - timedelta(seconds=2), expires_at=NOW + timedelta(seconds=offset)
    )
    results = engine.check(candidate, snapshot(), (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert all(row.passed for row in results) is expected


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "missing_id",
        "subcent",
        "fractional_qty",
        "position",
        "order",
        "lot",
        "trade",
        "account",
        "list",
        "unknown_history",
        "unknown_lot",
        "zero_equity",
    ],
)
def test_R_02_forged_or_unverifiable_inputs_have_seven_failed_rules_and_halt(
    engine: ComplianceEngine, fault: str
) -> None:
    candidate = proposal()
    state = snapshot()
    lots: tuple[TaxLot, ...] = ()
    history: tuple[TradeRecord, ...] = ()
    accounts: tuple[ExternalAccount, ...] = ACCOUNTS
    if fault == "none":
        candidate = cast(TradeProposal, None)
    elif fault == "missing_id":
        candidate = TradeProposal.model_construct()
    elif fault == "subcent":
        candidate = candidate.model_copy(update={"limit_price": Decimal("100.001")})
    elif fault == "fractional_qty":
        candidate = candidate.model_copy(update={"qty": 1.0})
    elif fault == "position":
        state = state.model_copy(update={"positions": {"AAPL": Position.model_construct(qty=1.1)}})
    elif fault == "order":
        state = state.model_copy(update={"open_orders": (OpenOrder.model_construct(qty=1.0),)})
    elif fault == "lot":
        lots = (lot().model_copy(update={"qty": 1.0}),)
    elif fault == "trade":
        history = (trade(1).model_copy(update={"price": 100.0}),)
    elif fault == "account":
        accounts = (ACCOUNTS[0].model_copy(update={"tax_status": "UNKNOWN"}),)
    elif fault == "list":
        history = cast(tuple[TradeRecord, ...], [])
    elif fault == "unknown_history":
        history = (trade(1, symbol="UNKNOWN"),)
    elif fault == "unknown_lot":
        lots = (lot().model_copy(update={"symbol": "UNKNOWN"}),)
    else:
        state = snapshot(equity=Decimal(0))
    assessment = engine.assess(candidate, state, lots, history, accounts, NOW, flags=FLAGS)
    assert [row.rule_id for row in assessment.results] == [f"CMP-{n:02d}" for n in range(1, 8)]
    assert all(not row.passed and row.severity == Severity.BLOCK for row in assessment.results)
    assert assessment.recommended_state == SystemState.HALTED
    if fault in {"position", "order"}:
        assert assessment.snapshot_hash == "0" * 64
    if fault in {"none", "missing_id"}:
        assert assessment.proposal_id is None


def test_R_05_invalid_evaluation_time_is_a_typed_error(engine: ComplianceEngine) -> None:
    with pytest.raises(DataIntegrityError):
        engine.check(
            proposal(), snapshot(), (), (), ACCOUNTS, NOW.replace(tzinfo=None), flags=FLAGS
        )


@pytest.mark.parametrize(
    "fault", ["float_baseline", "blank_account", "duplicate", "future", "unknown", "forged"]
)
def test_CMP_03_cash_reconstruction_invalid_evidence_raises_typed_error(
    engine: ComplianceEngine, fault: str
) -> None:
    initial = Decimal(500)
    account = "paper"
    records: tuple[TradeRecord, ...] = (trade(1),)
    if fault == "float_baseline":
        initial = cast(Decimal, 500.0)
    elif fault == "blank_account":
        account = " "
    elif fault == "duplicate":
        records = (trade(1), trade(1))
    elif fault == "future":
        records = (trade(1, days=1),)
    elif fault == "unknown":
        records = (trade(1, symbol="UNKNOWN"),)
    else:
        records = (trade(1).model_copy(update={"qty": 1.5}),)
    with pytest.raises(DataIntegrityError):
        engine.settled_cash_as_of(initial, records, NOW, account_id=account)


def test_CMP_03_settlement_calendar_fault_is_typed(
    engine: ComplianceEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(day: date, count: int) -> date:
        del day, count
        raise RuntimeError("calendar failure")

    monkeypatch.setattr(engine.calendar, "add_sessions", broken)
    with pytest.raises(DataIntegrityError):
        engine.settlement_date(NOW)


def test_CMP_05_multiple_opening_orders_and_partial_closes_are_counted_conservatively(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    configured = ComplianceEngine(
        Settings(day_trade_regime="LEGACY_PDT"), engine.registry, calendar
    )
    started = NOW - timedelta(hours=2)
    records = tuple(trade(i + 1, ts=started + timedelta(minutes=i), qty=1) for i in range(3))
    records += (trade(5, side=Side.SELL, ts=NOW - timedelta(minutes=1), qty=3),)
    row = check(
        configured,
        history=records,
        state_changes={"account_type": AccountType.MARGIN, "equity": Decimal("24999.99")},
    )["CMP-05"]
    assert not row.passed and row.severity == Severity.BLOCK
    assert "completed=3" in row.observed
    partial = (
        trade(10, ts=started, qty=10),
        trade(11, side=Side.SELL, ts=started + timedelta(minutes=1), qty=1),
        trade(12, side=Side.SELL, ts=started + timedelta(minutes=2), qty=9),
    )
    assert "completed=1" in check(configured, history=partial)["CMP-05"].observed


def test_R_09_pending_sells_reserve_held_inventory(engine: ComplianceEngine) -> None:
    pending = OpenOrder(symbol="AAPL", side=Side.SELL, qty=1, limit_price=Decimal(100))
    assessment = engine.assess(
        proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None),
        snapshot(open_orders=(pending,)),
        (lot(),),
        (),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert assessment.recommended_state == SystemState.HALTED
    assert all(not row.passed and row.severity == Severity.BLOCK for row in assessment.results)


@given(
    qty=st.integers(min_value=1, max_value=100),
    cash_cents=st.integers(min_value=0, max_value=1_100_000),
)
@settings(max_examples=70, deadline=None)
def test_CMP_03_CMP_04_property_never_pass_when_proposed_cash_exceeds_available(
    calendar: MarketCalendar, qty: int, cash_cents: int
) -> None:
    guarded = ComplianceEngine(Settings(), InstrumentRegistry([instrument()]), calendar)
    cash = Decimal(cash_cents) / 100
    state = snapshot(cash=cash, settled_cash=cash)
    candidate = proposal(qty=qty)
    one = guarded.assess(candidate, state, (), (), ACCOUNTS, NOW, flags=FLAGS)
    two = guarded.assess(candidate, state, (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert one == two
    for number in (2, 3):
        assert one.results[number].passed is (qty * Decimal(100) <= cash)


def test_R_04_low_decimal_context_does_not_change_rule_decision(engine: ComplianceEngine) -> None:
    state = snapshot(
        cash=Decimal("199.99"),
        settled_cash=Decimal("199.99"),
        open_orders=(OpenOrder(symbol="AAPL", side=Side.BUY, qty=1, limit_price=Decimal(100)),),
    )
    normal = engine.assess(proposal(), state, (), (), ACCOUNTS, NOW, flags=FLAGS)
    with localcontext() as context:
        context.prec = 2
        reduced = engine.assess(proposal(), state, (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert reduced == normal


def test_R_03_compliance_input_hash_binds_all_evidence_and_policy(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    original = engine.input_hash(
        proposal(), snapshot(), (lot(funding=date(2026, 10, 1)),), (trade(1),), ACCOUNTS, FLAGS
    )
    changes = (
        engine.input_hash(
            proposal(qty=2),
            snapshot(),
            (lot(funding=date(2026, 10, 1)),),
            (trade(1),),
            ACCOUNTS,
            FLAGS,
        ),
        engine.input_hash(
            proposal(),
            snapshot(),
            (lot(basis="111", funding=date(2026, 10, 1)),),
            (trade(1),),
            ACCOUNTS,
            FLAGS,
        ),
        engine.input_hash(
            proposal(),
            snapshot(),
            (lot(funding=date(2026, 10, 1)),),
            (trade(1, qty=11),),
            ACCOUNTS,
            FLAGS,
        ),
        engine.input_hash(
            proposal(),
            snapshot(),
            (lot(funding=date(2026, 10, 1)),),
            (trade(1),),
            (ACCOUNTS[0],),
            FLAGS,
        ),
        engine.input_hash(
            proposal(),
            snapshot(),
            (lot(funding=date(2026, 10, 1)),),
            (trade(1),),
            ACCOUNTS,
            FLAGS.model_copy(update={"trading_blocked": True}),
        ),
    )
    assert all(value != original and len(value) == 64 for value in changes)
    restricted = ComplianceEngine(
        Settings(), engine.registry, calendar, restricted_symbols=frozenset({"AAPL"})
    )
    assert (
        restricted.input_hash(
            proposal(), snapshot(), (lot(funding=date(2026, 10, 1)),), (trade(1),), ACCOUNTS, FLAGS
        )
        != original
    )
    different_groups = ComplianceEngine(
        Settings(), InstrumentRegistry([instrument(), instrument("MSFT")]), calendar
    )
    assert (
        different_groups.input_hash(
            proposal(), snapshot(), (lot(funding=date(2026, 10, 1)),), (trade(1),), ACCOUNTS, FLAGS
        )
        != original
    )


def test_R_02_compliance_input_hash_malformed_tuples_raises_typed(engine: ComplianceEngine) -> None:
    with pytest.raises(DataIntegrityError):
        engine.input_hash(proposal(), snapshot(), cast(tuple[TaxLot, ...], []), (), ACCOUNTS, FLAGS)


def test_CMP_03_good_faith_funding_on_today_requires_session_close_confirmation(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    closed = calendar.session_close(date(2026, 10, 2))
    for offset, expected in ((-1, False), (0, True), (1, True)):
        instant = closed + timedelta(microseconds=offset)
        rows = engine.check(
            proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None),
            snapshot(as_of=instant),
            (lot(funding=date(2026, 10, 2)),),
            (),
            ACCOUNTS,
            instant,
            flags=FLAGS,
        )
        assert rows[2].passed is expected and rows[2].severity == Severity.WARN


def test_CMP_03_invalid_funding_session_requests_halt_with_exit_warnings(
    engine: ComplianceEngine,
) -> None:
    assessed = engine.assess(
        proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None),
        snapshot(),
        (lot(funding=date(2026, 10, 3)),),
        (),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert not assessed.results[2].passed and assessed.results[2].severity == Severity.WARN
    assert assessed.recommended_state == SystemState.HALTED


def test_CMP_05_equal_execution_times_are_conservatively_ordered(engine: ComplianceEngine) -> None:
    records = (
        trade(1, side=Side.SELL, ts=NOW, qty=3),
        trade(2, ts=NOW, qty=1),
        trade(3, ts=NOW, qty=1),
        trade(4, ts=NOW, qty=1),
    )
    assert "completed=3" in check(engine, history=records)["CMP-05"].observed


def test_CMP_05_unknown_broker_share_allocation_counts_max_plausible_opening_orders(
    engine: ComplianceEngine,
) -> None:
    started = NOW - timedelta(hours=1)
    records = (
        trade(1, qty=10, ts=started),
        trade(2, qty=10, ts=started + timedelta(minutes=1)),
        trade(3, side=Side.SELL, qty=2, ts=started + timedelta(minutes=2)),
    )
    assert "completed=2" in check(engine, history=records)["CMP-05"].observed
    limited = (*records[:2], records[2].model_copy(update={"qty": 1}))
    assert "completed=1" in check(engine, history=limited)["CMP-05"].observed


def test_CMP_02_prior_tacked_lot_preserves_holding_period_and_actual_acquisition(
    engine: ComplianceEngine,
) -> None:
    purchase = trade(1, days=-10, qty=1)
    replacement = trade(2, days=-1, qty=1, account="other")
    held_lot = lot(days=-10, funding=date(2026, 10, 1)).model_copy(
        update={"holding_period_start": NOW - timedelta(days=100), "acquisition_trade_id": uid(1)}
    )
    assessed = engine.assess(
        proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None),
        snapshot(),
        (held_lot,),
        (purchase, replacement),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert assessed.recommended_state == SystemState.RUNNING
    assert assessed.results[1].observed == "10" and assessed.results[1].severity == Severity.WARN


@pytest.mark.parametrize(
    "fault", ["missing", "sell", "account", "symbol", "timestamp", "qty", "aggregate_qty"]
)
def test_CMP_02_tax_lot_acquisition_lineage_requires_matching_original_buy(
    engine: ComplianceEngine, fault: str
) -> None:
    original = trade(1, days=-10, qty=1)
    held_lot = lot(days=-10).model_copy(update={"acquisition_trade_id": uid(1)})
    history: tuple[TradeRecord, ...] = (original,)
    lots: tuple[TaxLot, ...] = (held_lot,)
    if fault == "missing":
        history = ()
    elif fault == "sell":
        history = (original.model_copy(update={"side": Side.SELL}),)
    elif fault == "account":
        history = (original.model_copy(update={"account_id": "other"}),)
    elif fault == "symbol":
        history = (original.model_copy(update={"symbol": "MSFT"}),)
    elif fault == "timestamp":
        history = (original.model_copy(update={"ts": NOW - timedelta(days=11)}),)
    elif fault == "qty":
        lots = (held_lot.model_copy(update={"qty": 2}),)
    else:
        lots = (held_lot, held_lot.model_copy(update={"lot_id": uid(2)}))
    assessed = engine.assess(proposal(), snapshot(), lots, history, ACCOUNTS, NOW, flags=FLAGS)
    assert assessed.recommended_state == SystemState.HALTED
    assert all(not row.passed and row.severity == Severity.BLOCK for row in assessed.results)
````````
<!-- END FILE backend/tests/test_compliance.py -->

### backend/tests/test_wash_sales.py

<!-- BEGIN FILE backend/tests/test_wash_sales.py -->
````````python
"""R-02/R-03/R-04/R-05/R-13, CMP-01/CMP-02: tax matching boundaries and faults."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.domain.compliance_models import (
    ExternalAccount,
    Form8949Row,
    TaxLot,
    TaxStatus,
    TradeRecord,
    WashAdjustment,
)
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import AssetClass, Instrument, Side
from backend.risk.wash_sales import WashSaleMatcher, trade_day

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
OLD = NOW - timedelta(days=100)
ACCOUNTS = (
    ExternalAccount(account_id="tax", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="other", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="ira", tax_status=TaxStatus.IRA),
    ExternalAccount(account_id="roth", tax_status=TaxStatus.ROTH),
)


def registry(*, grouped: bool = False) -> InstrumentRegistry:
    """CMP-01/CMP-02: fixture identities are explicit, never inferred."""
    names = tuple(
        Instrument(
            symbol=name,
            asset_class=AssetClass.STOCK,
            gics_sector="Information Technology",
            is_leveraged=False,
            is_inverse=False,
            tradable=True,
        )
        for name in ("AAA", "BBB", "CCC")
    )
    return InstrumentRegistry(names, identical_groups={"paired": ("AAA", "BBB")} if grouped else {})


def buy(
    identifier: int,
    *,
    qty: int = 100,
    ts: datetime = NOW,
    price: Decimal = Decimal("10.00"),
    account: str = "other",
    symbol: str = "AAA",
    drip: bool = False,
) -> TradeRecord:
    """CMP-01/CMP-02: executed replacement fixture."""
    return TradeRecord(
        trade_id=UUID(int=identifier),
        account_id=account,
        symbol=symbol,
        side=Side.BUY,
        qty=qty,
        price=price,
        ts=ts,
        is_drip=drip,
    )


def sale(
    identifier: int,
    *,
    qty: int = 100,
    ts: datetime = NOW,
    loss: Decimal = Decimal("100.00"),
    price: Decimal = Decimal("9.00"),
    account: str = "tax",
    symbol: str = "AAA",
    held_from: datetime | None = OLD,
    origin: UUID | None = None,
) -> TradeRecord:
    """CMP-02: one attested acquisition-lot disposal."""
    return TradeRecord(
        trade_id=UUID(int=identifier),
        account_id=account,
        symbol=symbol,
        side=Side.SELL,
        qty=qty,
        price=price,
        ts=ts,
        realized_loss=loss,
        holding_period_start=held_from,
        acquisition_trade_id=origin,
    )


def adjustment() -> WashAdjustment:
    """CMP-02: valid matched evidence for standalone exporter fault tests."""
    return WashSaleMatcher(registry()).adjustments((sale(1), buy(2)), ACCOUNTS)[0]


@pytest.mark.parametrize("offset,expected", [(-31, 0), (-30, 100), (0, 100), (30, 100), (31, 0)])
def test_cmp_01_cmp_02_inclusive_day_30_and_31(offset: int, expected: int) -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (buy(2, ts=NOW + timedelta(days=offset)), sale(1)), ACCOUNTS
    )
    assert sum(row.qty for row in rows) == expected


def test_cmp_02_partial_loss_does_not_absorb_unmatched_loss() -> None:
    rows = WashSaleMatcher(registry()).adjustments((sale(1), buy(2, qty=10)), ACCOUNTS)
    assert len(rows) == 1
    assert rows[0].disallowed_loss == Decimal("10.00")
    assert rows[0].cost_basis == Decimal("100.00")
    assert rows[0].adjusted_basis == Decimal("110.00")
    exported = WashSaleMatcher.form_8949_rows(rows)
    assert exported[0].proceeds == Decimal("90.00")
    assert exported[0].adjustment == Decimal("10.00")
    assert exported[0].gain_or_loss == 0
    assert exported[0].code == "W"


def test_cmp_02_irs_publication_550_example_chronological_matching() -> None:
    acquired = datetime(2024, 9, 20, 16, tzinfo=UTC)
    sold = datetime(2025, 1, 3, 16, tzinfo=UTC)
    rows = WashSaleMatcher(registry()).adjustments(
        (
            buy(1, ts=acquired, price=Decimal("50.00"), account="tax"),
            buy(2, qty=50, ts=datetime(2024, 12, 13, 16, tzinfo=UTC), price=Decimal("55.00")),
            buy(3, qty=25, ts=datetime(2024, 12, 20, 16, tzinfo=UTC), price=Decimal("45.00")),
            sale(4, ts=sold, price=Decimal("40.00"), loss=Decimal("1000.00"), held_from=acquired),
        ),
        ACCOUNTS,
    )
    assert [row.qty for row in rows] == [50, 25]
    assert [row.disallowed_loss for row in rows] == [Decimal("500"), Decimal("250")]
    assert [row.adjusted_basis for row in rows] == [Decimal("3250"), Decimal("1375")]
    exported = WashSaleMatcher.form_8949_rows(rows)
    assert sum(row.adjustment for row in exported) == Decimal("750")
    assert sum(row.proceeds for row in exported) == Decimal("3000")
    assert sum(row.cost_basis for row in exported) == Decimal("3750")


@pytest.mark.parametrize("account", ["ira", "roth"])
def test_cmp_01_ira_roth_permanent_loss_no_basis_increase(account: str) -> None:
    row = WashSaleMatcher(registry()).adjustments((sale(1), buy(2, account=account)), ACCOUNTS)[0]
    assert row.permanent_loss
    assert row.adjusted_basis is None
    assert row.disallowed_loss == Decimal("100")


@pytest.mark.parametrize("account", ["ira", "roth"])
def test_cmp_02_ira_roth_loss_sales_have_no_taxable_loss_deduction(account: str) -> None:
    assert (
        WashSaleMatcher(registry()).adjustments((sale(1, account=account), buy(2)), ACCOUNTS) == ()
    )


def test_cmp_01_identical_group_and_drip_other_accounts() -> None:
    rows = WashSaleMatcher(registry(grouped=True)).adjustments(
        (sale(1), buy(2, qty=25, symbol="BBB", drip=True), buy(3, symbol="CCC")), ACCOUNTS
    )
    assert len(rows) == 1
    assert rows[0].replacement_trade_id == UUID(int=2)
    assert rows[0].qty == 25


def test_cmp_02_loss_lot_cannot_replace_its_own_disposed_shares() -> None:
    acquired = NOW - timedelta(days=10)
    original = buy(1, account="tax", ts=acquired)
    loss = sale(2, held_from=acquired, origin=original.trade_id)
    assert WashSaleMatcher(registry()).adjustments((loss, original), ACCOUNTS) == ()


def test_cmp_02_retained_shares_of_original_purchase_can_replace_sold_slice() -> None:
    acquired = NOW - timedelta(days=10)
    rows = WashSaleMatcher(registry()).adjustments(
        (
            buy(1, account="tax", ts=acquired),
            sale(2, qty=50, loss=Decimal("50"), held_from=acquired),
        ),
        ACCOUNTS,
    )
    assert len(rows) == 1
    assert rows[0].qty == 50


def test_cmp_02_disposed_before_loss_purchase_is_not_available() -> None:
    acquired = NOW - timedelta(days=10)
    rows = WashSaleMatcher(registry()).adjustments(
        (
            buy(1, ts=acquired),
            sale(
                2, account="other", loss=Decimal(0), ts=NOW - timedelta(days=5), held_from=acquired
            ),
            sale(3),
        ),
        ACCOUNTS,
    )
    assert rows == ()


def test_cmp_02_later_disposal_does_not_erase_prior_valid_match() -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (
            sale(1),
            buy(2, ts=NOW + timedelta(days=1)),
            sale(3, account="other", loss=Decimal(0), ts=NOW + timedelta(days=2), held_from=None),
        ),
        ACCOUNTS,
    )
    assert len(rows) == 1
    assert rows[0].replacement_trade_id == UUID(int=2)


def test_cmp_02_shared_capacity_does_not_reuse_retained_previously_matched_shares() -> None:
    acquired = NOW - timedelta(days=1)
    rows = WashSaleMatcher(registry()).adjustments(
        (
            buy(1, ts=acquired),
            sale(2, qty=75, loss=Decimal("75")),
            sale(
                3,
                qty=25,
                account="other",
                loss=Decimal(0),
                ts=NOW + timedelta(days=1),
                held_from=acquired,
            ),
            sale(4, ts=NOW + timedelta(days=2)),
        ),
        ACCOUNTS,
    )
    assert [row.qty for row in rows] == [75, 25]
    assert sum(row.qty for row in rows) == 100
    assert sum(row.disallowed_loss for row in rows) == 100


def test_cmp_02_multiple_loss_sales_exhaust_replacement_capacity() -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (sale(1), sale(2, ts=NOW + timedelta(days=1)), buy(3, qty=150, ts=NOW + timedelta(days=2))),
        ACCOUNTS,
    )
    assert [row.qty for row in rows] == [100, 50]
    assert [row.disallowed_loss for row in rows] == [Decimal("100"), Decimal("50")]


def test_cmp_02_micro_loss_proportions_and_full_residual_are_exact() -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (
            sale(1, qty=3, loss=Decimal("1.000001")),
            buy(2, qty=1),
            buy(3, qty=1),
            buy(4, qty=1),
            buy(5),
        ),
        ACCOUNTS,
    )
    assert [row.disallowed_loss for row in rows] == [
        Decimal("0.333333"),
        Decimal("0.333334"),
        Decimal("0.333334"),
    ]
    assert sum(row.disallowed_loss for row in rows) == Decimal("1.000001")


def test_r_02_cmp_02_loss_smaller_than_micro_allocation_fails_typed() -> None:
    with pytest.raises(DataIntegrityError, match="micro-unit"):
        WashSaleMatcher(registry()).adjustments(
            (sale(1, qty=100, loss=Decimal("0.000001")), buy(2, qty=1)), ACCOUNTS
        )


def test_r_04_cmp_02_ambient_decimal_precision_cannot_change_matching() -> None:
    matcher = WashSaleMatcher(registry())
    history = (sale(1, qty=3, loss=Decimal("1.000001")), buy(2, qty=2))
    expected = matcher.adjustments(history, ACCOUNTS)
    with localcontext() as context:
        context.prec = 2
        assert matcher.adjustments(history, ACCOUNTS) == expected
        assert matcher.form_8949_rows(expected)[0].gain_or_loss == 0


def test_r_05_cmp_02_holding_period_tacking_uses_calendar_days_across_dst() -> None:
    ny = ZoneInfo("America/New_York")
    acquired = datetime(2026, 10, 15, 0, 30, tzinfo=ny).astimezone(UTC)
    sold = datetime(2026, 11, 4, 0, 30, tzinfo=ny).astimezone(UTC)
    replacement = datetime(2026, 11, 5, 0, 30, tzinfo=ny).astimezone(UTC)
    row = WashSaleMatcher(registry()).adjustments(
        (sale(1, ts=sold, held_from=acquired), buy(2, ts=replacement)), ACCOUNTS
    )[0]
    assert trade_day(row.holding_period_start) == date(2026, 10, 16)
    assert row.holding_period_start.astimezone(ny).hour == 0


def test_r_05_cmp_02_utc_midnight_window_uses_new_york_trade_date() -> None:
    assert trade_day(datetime(2026, 10, 2, 1, tzinfo=UTC)) == date(2026, 10, 1)


@given(
    qty=st.integers(1, 10000),
    replacement_qty=st.integers(1, 10000),
    loss_micro=st.integers(10000, 10000000),
)
def test_r_03_r_04_cmp_02_property_partial_matches_are_proportional_and_deterministic(
    qty: int, replacement_qty: int, loss_micro: int
) -> None:
    matcher = WashSaleMatcher(registry())
    loss = Decimal(loss_micro) / 1000000
    history = (sale(1, qty=qty, loss=loss), buy(2, qty=replacement_qty))
    rows = matcher.adjustments(history, ACCOUNTS)
    assert rows == matcher.adjustments(tuple(reversed(history)), ACCOUNTS)
    assert sum(row.qty for row in rows) == min(qty, replacement_qty)
    expected_micro = loss_micro * min(qty, replacement_qty) // qty
    assert sum(row.disallowed_loss for row in rows) == Decimal(expected_micro) / 1000000
    assert sum(row.disallowed_loss for row in rows) <= loss


@pytest.mark.parametrize("bad_price", [Decimal("9.001"), Decimal("NaN"), Decimal(0), 9.0, "9.00"])
def test_r_13_cmp_02_execution_price_requires_decimal_cents(bad_price: object) -> None:
    with pytest.raises(ValidationError):
        TradeRecord.model_validate({**buy(1).model_dump(), "price": bad_price})


@pytest.mark.parametrize("bad_qty", [True, 1.0, "1", 0, -1])
def test_r_01_cmp_02_quantity_is_strict_positive_integer(bad_qty: object) -> None:
    with pytest.raises(ValidationError):
        TradeRecord.model_validate({**buy(1).model_dump(), "qty": bad_qty})


def test_r_04_cmp_02_fractional_cent_tax_basis_is_preserved() -> None:
    lot = TaxLot(
        lot_id=UUID(int=1),
        account_id="tax",
        symbol="AAA",
        qty=3,
        acquired_at=OLD,
        cost_basis=Decimal("10.333333"),
        funding_settlement_date=date(2026, 7, 1),
    )
    assert lot.cost_basis == Decimal("10.333333")


def test_r_02_cmp_02_tax_lot_preserves_actual_date_and_explicit_tacked_start() -> None:
    lot = TaxLot(
        lot_id=UUID(int=1),
        account_id="tax",
        symbol="AAA",
        qty=3,
        acquired_at=NOW - timedelta(days=10),
        cost_basis=Decimal("10.333333"),
        acquisition_trade_id=UUID(int=2),
        holding_period_start=OLD,
    )
    assert lot.acquired_at == NOW - timedelta(days=10)
    assert lot.holding_period_start == OLD
    assert TaxLot.model_validate(lot) == lot
    same_start = lot.model_copy(
        update={"holding_period_start": lot.acquired_at, "acquisition_trade_id": None}
    )
    assert TaxLot.model_validate(same_start).holding_period_start == lot.acquired_at


@pytest.mark.parametrize(
    "changes",
    [
        {"holding_period_start": NOW + timedelta(days=1)},
        {"holding_period_start": OLD, "acquisition_trade_id": None},
        {"holding_period_start": datetime(2026, 7, 1)},
    ],
)
def test_r_02_r_05_cmp_02_tax_lot_rejects_future_unidentified_or_naive_tacking(
    changes: dict[str, object],
) -> None:
    lot = TaxLot(
        lot_id=UUID(int=1),
        account_id="tax",
        symbol="AAA",
        qty=1,
        acquired_at=NOW,
        cost_basis=Decimal("10.00"),
    )
    with pytest.raises(ValidationError):
        TaxLot.model_validate(lot.model_copy(update=changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"side": Side.BUY},
        {"holding_period_start": None},
        {"holding_period_start": NOW + timedelta(days=1)},
    ],
)
def test_r_02_cmp_02_loss_sale_requires_consistent_holding_evidence(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TradeRecord.model_validate({**sale(1).model_dump(), **changes})


def test_r_02_cmp_02_buy_cannot_reference_disposal_and_drip_is_buy_only() -> None:
    with pytest.raises(ValidationError, match="acquisition reference"):
        TradeRecord.model_validate({**buy(1).model_dump(), "acquisition_trade_id": UUID(int=2)})
    with pytest.raises(ValidationError, match="DRIP"):
        TradeRecord.model_validate({**sale(1).model_dump(), "is_drip": True})


@pytest.mark.parametrize("changes", [{"qty": True}, {"price": Decimal("9.001")}, {"side": "FAKE"}])
def test_r_02_cmp_02_forged_trade_models_fail_typed(changes: dict[str, object]) -> None:
    forged = buy(1).model_copy(update=changes)
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(registry()).adjustments((forged,), ACCOUNTS)


def test_r_02_cmp_02_invalid_history_ownership_ids_and_symbol_fail_typed() -> None:
    matcher = WashSaleMatcher(registry())
    for history, accounts in (
        ((buy(1), buy(1)), ACCOUNTS),
        ((buy(1, account="unknown"),), ACCOUNTS),
        ((buy(1, symbol="ZZZ"),), ACCOUNTS),
        ((buy(1),), (*ACCOUNTS, ACCOUNTS[0])),
        ((buy(1),), (ACCOUNTS[0].model_copy(update={"tax_status": "FAKE"}),)),
    ):
        with pytest.raises(DataIntegrityError):
            matcher.adjustments(history, accounts)
    with pytest.raises(DataIntegrityError):
        matcher.adjustments(cast(tuple[TradeRecord, ...], [buy(1)]), ACCOUNTS)
    with pytest.raises(DataIntegrityError):
        matcher.adjustments((), cast(tuple[ExternalAccount, ...], list(ACCOUNTS)))


def test_r_02_cmp_02_disposal_origin_wrong_account_missing_and_oversized_fail_typed() -> None:
    acquired = NOW - timedelta(days=5)
    original = buy(1, account="tax", ts=acquired)
    matcher = WashSaleMatcher(registry())
    for history in (
        (sale(2, origin=UUID(int=99)),),
        (original, sale(2, account="other", origin=original.trade_id)),
        (original, sale(2, origin=original.trade_id, held_from=NOW - timedelta(days=1))),
        (original, sale(2, qty=101, origin=original.trade_id, held_from=acquired)),
        (original, buy(3, account="tax", ts=acquired), sale(2, held_from=acquired)),
    ):
        with pytest.raises(DataIntegrityError):
            matcher.adjustments(history, ACCOUNTS)


def test_cmp_02_explicit_origin_can_supply_tacked_earlier_holding_start() -> None:
    acquired = NOW - timedelta(days=5)
    original = buy(1, account="tax", ts=acquired)
    rows = WashSaleMatcher(registry()).adjustments(
        (original, sale(2, held_from=OLD, origin=original.trade_id), buy(3)), ACCOUNTS
    )
    assert rows[0].acquired_date == trade_day(acquired)
    assert trade_day(rows[0].holding_period_start) == trade_day(OLD)


def test_r_02_cmp_02_registry_ingress_forgery_and_unexpected_fault_are_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(cast(InstrumentRegistry, None))

    def fault(_: InstrumentRegistry) -> InstrumentRegistry:
        raise RuntimeError("registry failure")

    monkeypatch.setattr(InstrumentRegistry, "validated_copy", fault)
    with pytest.raises(DataIntegrityError, match="registry"):
        WashSaleMatcher(registry())


def test_r_02_cmp_02_matching_unexpected_fault_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    matcher = WashSaleMatcher(registry())

    def fault(_: tuple[TradeRecord, ...]) -> dict[UUID, dict[UUID, int]]:
        raise RuntimeError("inventory failure")

    monkeypatch.setattr(matcher, "_survivors", fault)
    with pytest.raises(DataIntegrityError, match="matching"):
        matcher.adjustments((sale(1), buy(2)), ACCOUNTS)


def test_r_02_cmp_02_tied_disposal_without_original_metadata_is_unverifiable() -> None:
    with pytest.raises(DataIntegrityError, match="Tied"):
        WashSaleMatcher(registry()).adjustments(
            (buy(1, account="tax"), sale(2, loss=Decimal(0), held_from=None)), ACCOUNTS
        )


def test_r_02_cmp_02_adjustment_helper_cannot_guess_missing_holding_period() -> None:
    forged = sale(1).model_copy(update={"holding_period_start": None})
    with pytest.raises(DataIntegrityError, match="holding-period"):
        WashSaleMatcher._adjustment(forged, buy(2), 1, Decimal("1"), {"other": TaxStatus.TAXABLE})


def test_r_02_cmp_02_exporter_revalidates_and_rejects_duplicate_slices() -> None:
    row = adjustment()
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher.form_8949_rows((row, row))
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher.form_8949_rows(cast(tuple[WashAdjustment, ...], [row]))
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher.form_8949_rows(
            (row.model_copy(update={"disallowed_loss": Decimal("999")}),)
        )
    assert WashSaleMatcher.form_8949_rows(()) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"cost_basis": Decimal("1")},
        {"acquired_date": date(2030, 1, 1)},
        {"permanent_loss": True},
        {"adjusted_basis": None},
        {"adjusted_basis": Decimal("100")},
    ],
)
def test_r_02_cmp_02_wash_adjustment_internal_totals_are_checked(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        WashAdjustment.model_validate({**adjustment().model_dump(), **changes})


def test_r_02_cmp_02_form_8949_model_checks_totals_and_dates() -> None:
    row = WashSaleMatcher.form_8949_rows((adjustment(),))[0]
    with pytest.raises(ValidationError):
        Form8949Row.model_validate({**row.model_dump(), "gain_or_loss": Decimal("1")})
    with pytest.raises(ValidationError):
        Form8949Row.model_validate({**row.model_dump(), "date_acquired": date(2030, 1, 1)})
````````
<!-- END FILE backend/tests/test_wash_sales.py -->

### backend/tests/test_compliance_boundary.py

<!-- BEGIN FILE backend/tests/test_compliance_boundary.py -->
````````python
"""R-02/R-03/R-09/CMP-06: durable compliance audit and provider faults."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    AssetClass,
    Instrument,
    Intent,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    Severity,
    Side,
    TradeProposal,
)
from backend.risk.compliance import (
    ComplianceAssessment,
    ComplianceEngine,
    ExternalAccount,
    TaxLot,
    TaxStatus,
)
from backend.risk.compliance_boundary import (
    ComplianceBoundary,
    ComplianceFindingSink,
    LoggingComplianceFindingSink,
)

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
PROPOSAL_ID = UUID("60000000-0000-0000-0000-000000000001")
SIGNAL_ID = UUID("60000000-0000-0000-0000-000000000002")
LOT_ID = UUID("60000000-0000-0000-0000-000000000003")
ACCOUNTS = (ExternalAccount(account_id="boundary-paper", tax_status=TaxStatus.TAXABLE),)
FLAGS = AccountFlags(
    trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
)


class LocalNotifier:
    """R-02: observable notifications without an external service."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def notify(self, state: str, reason: str) -> None:
        self.calls.append((state, reason))


class FindingRecorder:
    """R-02: deterministic audit failure injection."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, UUID, Severity]] = []

    def record(self, rule_id: str, proposal_id: UUID, severity: Severity) -> None:
        self.calls.append((rule_id, proposal_id, severity))
        if self.fail:
            raise RuntimeError("compliance audit unavailable")


class FailedClock:
    """R-05: time failure cannot become a guessed timestamp."""

    def now(self) -> datetime:
        raise RuntimeError("clock failure")


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


def policy(calendar: MarketCalendar) -> ComplianceEngine:
    instrument = Instrument(
        symbol="AAPL",
        asset_class=AssetClass.STOCK,
        gics_sector="Information Technology",
        themes=(),
        is_leveraged=False,
        is_inverse=False,
        tradable=True,
    )
    return ComplianceEngine(Settings(), InstrumentRegistry((instrument,)), calendar)


def proposal(*, selling: bool = False) -> TradeProposal:
    return TradeProposal(
        proposal_id=PROPOSAL_ID,
        signal_id=SIGNAL_ID,
        account_id="boundary-paper",
        symbol="AAPL",
        side=Side.SELL if selling else Side.BUY,
        intent=Intent.EXIT if selling else Intent.ENTRY,
        qty=1,
        limit_price=Decimal("100.00"),
        stop_price=None if selling else Decimal("95.00"),
        source=ProposalSource.SIGNAL,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def snapshot(*, selling: bool = False, settled: str = "10000") -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="boundary-paper",
        account_type=AccountType.CASH,
        as_of=NOW,
        equity=Decimal("10000"),
        cash=Decimal("10000"),
        settled_cash=Decimal(settled),
        positions={
            "AAPL": Position(qty=1, avg_cost=Decimal("110.00"), last_price=Decimal("100.00"))
        }
        if selling
        else {},
        open_orders=(),
        high_water_mark=Decimal("10000"),
        day_start_equity=Decimal("10000"),
    )


def lots() -> tuple[TaxLot, ...]:
    return (
        TaxLot(
            lot_id=LOT_ID,
            account_id="boundary-paper",
            symbol="AAPL",
            qty=1,
            acquired_at=NOW - timedelta(days=100),
            cost_basis=Decimal("110.00"),
            funding_settlement_date=date(2026, 10, 1),
        ),
    )


def boundary(
    engine: Engine, calendar: MarketCalendar, sink: ComplianceFindingSink | None = None
) -> ComplianceBoundary:
    clock = FrozenClock(NOW)
    return ComplianceBoundary(
        policy(calendar), SystemStateStore(engine, clock, LocalNotifier()), clock, finding_sink=sink
    )


def test_R_03_CMP_01_07_complete_pure_evidence(engine: Engine, calendar: MarketCalendar) -> None:
    recorder = FindingRecorder()
    gate = boundary(engine, calendar, recorder)
    result = gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=FLAGS)
    assert len(result.results) == 7 and all(row.passed for row in result.results)
    assert result.proposal_id == PROPOSAL_ID and result.evaluated_at == NOW
    assert gate.state.current() == SystemState.RUNNING and recorder.calls == []


def test_CMP_03_ordinary_cash_failure_logs_without_halt(
    engine: Engine, calendar: MarketCalendar
) -> None:
    recorder = FindingRecorder()
    gate = boundary(engine, calendar, recorder)
    result = gate.evaluate(proposal(), snapshot(settled="99.99"), (), (), ACCOUNTS, flags=FLAGS)
    assert not result.results[2].passed and result.results[2].severity == Severity.BLOCK
    assert recorder.calls == [("CMP-03", PROPOSAL_ID, Severity.BLOCK)]
    assert gate.state.current() == SystemState.RUNNING


@pytest.mark.parametrize("missing", [False, True])
def test_CMP_06_broker_flags_halt_and_survive_restart(
    engine: Engine, calendar: MarketCalendar, missing: bool
) -> None:
    gate = boundary(engine, calendar)
    flags = None if missing else FLAGS.model_copy(update={"account_blocked": True})
    result = gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=flags)
    assert not result.results[5].passed and result.recommended_state == SystemState.HALTED
    assert (
        SystemStateStore(engine, FrozenClock(NOW), LocalNotifier()).current() == SystemState.HALTED
    )


def test_R_09_CMP_06_valid_exit_warns_while_persisting_halt(
    engine: Engine, calendar: MarketCalendar
) -> None:
    recorder = FindingRecorder()
    gate = boundary(engine, calendar, recorder)
    result = gate.evaluate(
        proposal(selling=True), snapshot(selling=True), lots(), (), ACCOUNTS, flags=None
    )
    assert all(row.severity == Severity.WARN for row in result.results)
    assert not result.results[5].passed and gate.state.current() == SystemState.HALTED
    assert ("CMP-06", PROPOSAL_ID, Severity.WARN) in recorder.calls


@pytest.mark.parametrize("fault", ["clock", "database", "engine", "audit"])
def test_R_02_boundary_provider_faults_halt(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    gate = boundary(engine, calendar, FindingRecorder(fail=fault == "audit"))

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected failure")

    if fault == "clock":
        gate.clock = FailedClock()
    elif fault == "database":
        monkeypatch.setattr(gate.state.ledger, "verify_chain", fail)
    elif fault == "engine":
        monkeypatch.setattr(gate.engine, "assess", fail)
    with pytest.raises(DataIntegrityError, match="latched HALTED"):
        gate.evaluate(proposal(), snapshot(settled="99.99"), (), (), ACCOUNTS, flags=FLAGS)
    assert gate.state.current() == SystemState.HALTED


def test_R_02_failed_halt_persistence_remains_typed(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, calendar)
    gate.clock = FailedClock()

    def fail(error: Exception) -> SystemState:
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(gate.state, "halt_for_error", fail)
    with pytest.raises(DataIntegrityError, match="HALT persistence unavailable"):
        gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=FLAGS)


@pytest.mark.parametrize(
    "attack",
    [
        "id",
        "config",
        "time",
        "missing",
        "duplicate",
        "snapshot",
        "severity",
        "broker_halt",
        "concealed_flags",
        "exit_block",
        "input_hash",
        "wash_severity",
    ],
)
def test_R_02_forged_compliance_assessment_fails_closed(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    gate = boundary(engine, calendar)
    selling = attack == "exit_block"
    trade = proposal(selling=selling)
    book = snapshot(selling=selling)
    inventory = lots() if selling else ()
    legitimate = gate.engine.assess(trade, book, inventory, (), ACCOUNTS, NOW, flags=FLAGS)
    actual_flags = (
        FLAGS.model_copy(update={"trading_blocked": True}) if attack == "concealed_flags" else FLAGS
    )
    fields: dict[str, object] = {}
    if attack == "id":
        fields["proposal_id"] = SIGNAL_ID
    elif attack == "config":
        fields["config_hash"] = "f" * 64
    elif attack == "time":
        fields["evaluated_at"] = NOW - timedelta(seconds=1)
    elif attack == "missing":
        fields["results"] = legitimate.results[:-1]
    elif attack == "duplicate":
        fields["results"] = (*legitimate.results[:-1], legitimate.results[0])
    elif attack == "snapshot":
        fields["snapshot_hash"] = "f" * 64
    elif attack == "input_hash":
        fields["input_hash"] = "f" * 64
    elif attack == "wash_severity":
        fields["results"] = (
            legitimate.results[0].model_copy(update={"passed": False, "severity": Severity.WARN}),
            *legitimate.results[1:],
        )
    elif attack in {"severity", "exit_block"}:
        replacement = legitimate.results[2].model_copy(
            update={"severity": Severity.BLOCK if selling else Severity.WARN}
        )
        fields["results"] = (*legitimate.results[:2], replacement, *legitimate.results[3:])
    elif attack == "broker_halt":
        fields["results"] = (
            *legitimate.results[:5],
            legitimate.results[5].model_copy(update={"passed": False}),
            legitimate.results[6],
        )
        fields["recommended_state"] = SystemState.RUNNING
    elif attack == "concealed_flags":
        fields["input_hash"] = gate.engine.input_hash(
            trade, book, inventory, (), ACCOUNTS, actual_flags
        )
    forged = legitimate.model_copy(update=fields)

    def returning(*args: object, **kwargs: object) -> ComplianceAssessment:
        return forged

    monkeypatch.setattr(gate.engine, "assess", returning)
    with pytest.raises(DataIntegrityError):
        gate.evaluate(trade, book, inventory, (), ACCOUNTS, flags=actual_flags)
    assert gate.state.current() == SystemState.HALTED


def test_R_02_audit_sink_contract_and_log_ids(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(DataIntegrityError, match="no implementation"):
        ComplianceFindingSink.record(
            cast(ComplianceFindingSink, object()), "CMP-06", PROPOSAL_ID, Severity.BLOCK
        )
    LoggingComplianceFindingSink().record("CMP-06", PROPOSAL_ID, Severity.WARN)
    assert f"proposal_id={PROPOSAL_ID}" in caplog.text and "rule_id=CMP-06" in caplog.text


def test_R_02_logging_failure_does_not_skip_halt(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, calendar)
    gate.clock = FailedClock()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("logging failure")

    monkeypatch.setattr(logging.getLogger("backend.risk.compliance_boundary"), "error", fail)
    with pytest.raises(DataIntegrityError, match="latched HALTED"):
        gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=FLAGS)
    assert gate.state.current() == SystemState.HALTED


def test_R_09_corrupt_tax_context_warns_and_halts_for_valid_exit(
    engine: Engine, calendar: MarketCalendar
) -> None:
    gate = boundary(engine, calendar)
    invalid_flags = FLAGS.model_copy(update={"account_blocked": "unknown"})
    result = gate.evaluate(
        proposal(selling=True), snapshot(selling=True), lots(), (), ACCOUNTS, flags=invalid_flags
    )
    assert result.input_hash == "0" * 64
    assert all(not row.passed and row.severity == Severity.WARN for row in result.results)
    assert gate.state.current() == SystemState.HALTED


@pytest.mark.parametrize("fault", ["oversell", "stale", "no_holding"])
def test_R_09_unverifiable_exit_is_not_a_valid_exit_exception(
    engine: Engine, calendar: MarketCalendar, fault: str
) -> None:
    gate = boundary(engine, calendar)
    trade = proposal(selling=True)
    book = snapshot(selling=True)
    if fault == "oversell":
        trade = trade.model_copy(update={"qty": 2})
    elif fault == "stale":
        book = book.model_copy(update={"as_of": NOW - timedelta(seconds=61)})
    else:
        book = book.model_copy(update={"positions": {}})
    result = gate.evaluate(trade, book, lots(), (), ACCOUNTS, flags=FLAGS)
    assert all(not row.passed and row.severity == Severity.BLOCK for row in result.results)
    assert gate.state.current() == SystemState.HALTED


def test_R_03_cached_assessment_cannot_authorize_changed_quantity(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, calendar)
    book = snapshot(settled="100")
    previous = gate.engine.assess(proposal(), book, (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert all(row.passed for row in previous.results)

    def cached(*args: object, **kwargs: object) -> ComplianceAssessment:
        return previous

    monkeypatch.setattr(gate.engine, "assess", cached)
    with pytest.raises(DataIntegrityError):
        gate.evaluate(proposal().model_copy(update={"qty": 2}), book, (), (), ACCOUNTS, flags=FLAGS)
    assert gate.state.current() == SystemState.HALTED


def test_R_02_unhashed_maximal_failure_can_only_halt(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, calendar)
    result = gate.engine.assess(proposal(), snapshot(), (), (), ACCOUNTS, NOW, flags=FLAGS)
    failed = result.model_copy(
        update={
            "snapshot_hash": "0" * 64,
            "recommended_state": SystemState.HALTED,
            "results": tuple(
                row.model_copy(update={"passed": False, "severity": Severity.BLOCK})
                for row in result.results
            ),
        }
    )

    def returning(*args: object, **kwargs: object) -> ComplianceAssessment:
        return failed

    monkeypatch.setattr(gate.engine, "assess", returning)
    assessment = gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=FLAGS)
    assert all(not row.passed for row in assessment.results)
    assert gate.state.current() == SystemState.HALTED
````````
<!-- END FILE backend/tests/test_compliance_boundary.py -->

### backend/tests/test_stage_c_adversarial.py

<!-- BEGIN FILE backend/tests/test_stage_c_adversarial.py -->
````````python
"""R-02/R-03/R-04/R-09/R-13/CMP-01..07: independent adversarial evidence.

Fixtures are authored here, independently of implementation test helpers. Tax
goldens use the public IRS Publication 550 partial-replacement example.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.core.config import Settings
from backend.core.errors import DataIntegrityError, SafetyError
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    AssetClass,
    Instrument,
    Intent,
    OpenOrder,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
)
from backend.risk.compliance import (
    ComplianceEngine,
    ExternalAccount,
    TaxLot,
    TaxStatus,
    TradeRecord,
)
from backend.risk.wash_sales import WashSaleMatcher

NOW = datetime(2026, 10, 2, 16, 0, tzinfo=UTC)
ACCOUNTS = (
    ExternalAccount(account_id="managed", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="other", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="ira", tax_status=TaxStatus.IRA),
    ExternalAccount(account_id="roth", tax_status=TaxStatus.ROTH),
)
FLAGS = AccountFlags(
    trading_blocked=False,
    account_blocked=False,
    trade_suspended_by_user=False,
    status="ACTIVE",
)


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _instant(day: date, *, hour: int = 16) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)


def _registry() -> InstrumentRegistry:
    return InstrumentRegistry(
        (
            Instrument(
                symbol=symbol,
                asset_class=AssetClass.STOCK,
                gics_sector="Information Technology",
                is_leveraged=False,
                is_inverse=False,
                tradable=True,
            )
            for symbol in ("AAPL", "MSFT", "JNJ")
        ),
        identical_groups={"OPERATOR_ATTESTED": ("AAPL", "MSFT")},
    )


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2024, 1, 2), end=date(2027, 12, 31))


@pytest.fixture
def engine(calendar: MarketCalendar) -> ComplianceEngine:
    return ComplianceEngine(Settings(), _registry(), calendar)


def _proposal(**changes: object) -> TradeProposal:
    values: dict[str, object] = {
        "proposal_id": _uuid(900),
        "signal_id": _uuid(901),
        "account_id": "managed",
        "symbol": "AAPL",
        "side": Side.BUY,
        "intent": Intent.ENTRY,
        "qty": 1,
        "limit_price": Decimal("10.00"),
        "stop_price": Decimal("9.00"),
        "source": ProposalSource.SIGNAL,
        "created_at": NOW - timedelta(seconds=1),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return TradeProposal.model_validate(values)


def _snapshot(**changes: object) -> PortfolioSnapshot:
    values: dict[str, object] = {
        "account_id": "managed",
        "account_type": AccountType.CASH,
        "as_of": NOW,
        "equity": Decimal("25000"),
        "cash": Decimal("25000"),
        "settled_cash": Decimal("25000"),
        "positions": {},
        "open_orders": (),
        "high_water_mark": Decimal("25000"),
        "day_start_equity": Decimal("25000"),
    }
    values.update(changes)
    return PortfolioSnapshot.model_validate(values)


def _trade(
    identifier: int,
    day: date,
    *,
    side: Side = Side.BUY,
    qty: int = 10,
    price: str = "100.00",
    account: str = "managed",
    symbol: str = "AAPL",
    loss: str = "0",
    acquired_at: datetime | None = None,
    acquisition_id: UUID | None = None,
    minute: int = 0,
) -> TradeRecord:
    return TradeRecord(
        trade_id=_uuid(identifier),
        account_id=account,
        symbol=symbol,
        side=side,
        qty=qty,
        price=Decimal(price),
        ts=_instant(day) + timedelta(minutes=minute),
        realized_loss=Decimal(loss),
        holding_period_start=(
            acquired_at
            if acquired_at is not None
            else _instant(day - timedelta(days=100))
            if Decimal(loss) > 0
            else None
        ),
        acquisition_trade_id=acquisition_id,
    )


def _check(
    engine: ComplianceEngine,
    *,
    proposal: TradeProposal | None = None,
    snapshot: PortfolioSnapshot | None = None,
    history: tuple[TradeRecord, ...] = (),
    lots: tuple[TaxLot, ...] = (),
    accounts: tuple[ExternalAccount, ...] = ACCOUNTS,
    flags: AccountFlags | None = FLAGS,
    now: datetime = NOW,
) -> dict[str, RuleResult]:
    results = engine.check(
        proposal or _proposal(),
        snapshot or _snapshot(),
        lots,
        history,
        accounts,
        now,
        flags=flags,
    )
    assert [row.rule_id for row in results] == [f"CMP-0{number}" for number in range(1, 8)]
    return {row.rule_id: row for row in results}


@pytest.mark.parametrize(
    "field,value",
    [
        ("price", Decimal("100.001")),
        ("price", 100.0),
        ("qty", 1.0),
        ("qty", True),
        ("side", "UNRECOGNIZED"),
        ("ts", datetime(2026, 10, 1, 16)),
    ],
)
def test_R_02_R_13_CMP_forged_history_cannot_produce_approval(
    engine: ComplianceEngine, field: str, value: object
) -> None:
    forged = _trade(1, date(2026, 10, 1)).model_copy(update={field: value})
    evidence = _check(engine, history=(forged,))
    assert any(not row.passed and row.severity == Severity.BLOCK for row in evidence.values())


@pytest.mark.parametrize("offset", [0, -1])
def test_R_02_CMP_expiry_exact_endpoint_is_invalid(engine: ComplianceEngine, offset: int) -> None:
    expired = _proposal(
        created_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(seconds=offset)
    )
    evidence = _check(engine, proposal=expired)
    assert all(not row.passed for row in evidence.values())
    assert any(row.severity == Severity.BLOCK for row in evidence.values())


@pytest.mark.parametrize("offset", [61, 3600, 86400])
def test_R_02_CMP_stale_snapshot_is_unverifiable(engine: ComplianceEngine, offset: int) -> None:
    evidence = _check(engine, snapshot=_snapshot(as_of=NOW - timedelta(seconds=offset)))
    assert any(not row.passed and row.severity == Severity.BLOCK for row in evidence.values())


@pytest.mark.parametrize("unknown", ["account", "history_symbol", "lot_symbol", "proposal_symbol"])
def test_R_02_CMP_unknown_identity_is_fail_closed(engine: ComplianceEngine, unknown: str) -> None:
    history = (_trade(1, date(2026, 10, 1), symbol="ZZZZ"),) if unknown == "history_symbol" else ()
    lots = (
        (
            TaxLot(
                lot_id=_uuid(1),
                account_id="managed",
                symbol="ZZZZ",
                qty=1,
                acquired_at=NOW - timedelta(days=5),
                cost_basis=Decimal("100"),
            ),
        )
        if unknown == "lot_symbol"
        else ()
    )
    results = _check(
        engine,
        proposal=_proposal(symbol="ZZZZ") if unknown == "proposal_symbol" else None,
        history=history,
        lots=lots,
        accounts=() if unknown == "account" else ACCOUNTS,
    )
    assert any(not row.passed and row.severity == Severity.BLOCK for row in results.values())


def test_R_02_CMP_forged_nested_holdings_and_settings_are_revalidated(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    forged_position = Position(qty=1, avg_cost=Decimal("100"), last_price=Decimal("100"))
    forged = _snapshot().model_copy(
        update={"positions": {"AAPL": forged_position.model_copy(update={"qty": 1.5})}}
    )
    assert any(not row.passed for row in _check(engine, snapshot=forged).values())
    policy = Settings().model_copy(update={"max_single_stock_weight": Decimal("0.99")})
    with pytest.raises(SafetyError):
        ComplianceEngine(policy, engine.registry, calendar)


@pytest.mark.parametrize("unknown_symbol", [False, True])
def test_R_09_CMP_valid_held_exit_only_warns_unverifiable_tax_context(
    engine: ComplianceEngine, unknown_symbol: bool
) -> None:
    symbol = "ZZZZ" if unknown_symbol else "AAPL"
    proposal = _proposal(symbol=symbol, side=Side.SELL, intent=Intent.EXIT, stop_price=None, qty=10)
    snapshot = _snapshot(
        positions={symbol: Position(qty=10, avg_cost=Decimal("100"), last_price=Decimal("100"))}
    )
    results = _check(engine, proposal=proposal, snapshot=snapshot, accounts=(), flags=None)
    assert all(row.severity == Severity.WARN for row in results.values())
    assert any(not row.passed for row in results.values())


def test_R_09_CMP_pending_sell_reservation_prevents_oversized_exit(
    engine: ComplianceEngine,
) -> None:
    proposal = _proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None, qty=10)
    snapshot = _snapshot(
        positions={"AAPL": Position(qty=10, avg_cost=Decimal("100"), last_price=Decimal("100"))},
        open_orders=(OpenOrder(symbol="AAPL", side=Side.SELL, qty=1, limit_price=Decimal("100")),),
    )
    results = _check(engine, proposal=proposal, snapshot=snapshot)
    assert any(not row.passed and row.severity == Severity.BLOCK for row in results.values())


@pytest.mark.parametrize("equity", ["2000", "5000", "25000", "100000"])
@pytest.mark.parametrize("cash,passed", [("100", True), ("99.99", False)])
def test_CMP_03_CMP_04_pending_cash_exact_cent_boundaries(
    engine: ComplianceEngine, equity: str, cash: str, passed: bool
) -> None:
    snapshot = _snapshot(
        equity=Decimal(equity),
        cash=Decimal(cash),
        settled_cash=Decimal(cash),
        open_orders=(OpenOrder(symbol="MSFT", side=Side.BUY, qty=3, limit_price=Decimal("30")),),
    )
    evidence = _check(engine, snapshot=snapshot)
    assert evidence["CMP-03"].passed is passed
    assert evidence["CMP-04"].passed is passed


@pytest.mark.parametrize(
    "trade_day,settled_day,closing_hour",
    [
        (date(2026, 3, 6), date(2026, 3, 9), 20),
        (date(2026, 11, 25), date(2026, 11, 27), 18),
        (date(2026, 11, 27), date(2026, 11, 30), 21),
    ],
)
def test_CMP_03_T1_DST_holiday_early_close_exact_credit_time(
    engine: ComplianceEngine, trade_day: date, settled_day: date, closing_hour: int
) -> None:
    sale = _trade(1, trade_day, side=Side.SELL, qty=1)
    close = _instant(settled_day, hour=closing_hour)
    assert engine.settlement_date(sale.ts) == settled_day
    assert engine.settled_cash_as_of(
        Decimal("10"), (sale,), close - timedelta(microseconds=1), account_id="managed"
    ) == Decimal("10")
    assert engine.settled_cash_as_of(
        Decimal("10"), (sale,), close, account_id="managed"
    ) == Decimal("110")


def test_CMP_02_IRS_partial_replacement_golden(engine: ComplianceEngine) -> None:
    original = _trade(1, date(2024, 9, 20), qty=100, price="50")
    first = _trade(2, date(2024, 12, 13), qty=50, price="55")
    second = _trade(3, date(2024, 12, 20), qty=25, price="45")
    sale = _trade(
        4,
        date(2025, 1, 3),
        side=Side.SELL,
        qty=100,
        price="40",
        loss="1000",
        acquired_at=original.ts,
        acquisition_id=original.trade_id,
    )
    matcher = WashSaleMatcher(engine.registry)
    matches = matcher.adjustments((original, first, second, sale), ACCOUNTS)
    assert [(row.qty, row.disallowed_loss, row.adjusted_basis) for row in matches] == [
        (50, Decimal("500"), Decimal("3250")),
        (25, Decimal("250"), Decimal("1375")),
    ]
    exported = matcher.form_8949_rows(matches)
    assert all(row.code == "W" and row.adjustment > 0 for row in exported)
    assert sum((row.proceeds for row in exported), Decimal(0)) == Decimal("3000")
    assert sum((row.cost_basis for row in exported), Decimal(0)) == Decimal("3750")
    assert sum((row.adjustment for row in exported), Decimal(0)) == Decimal("750")
    assert sum((row.gain_or_loss for row in exported), Decimal(0)) == 0
    # 105 New York calendar days tack to the December purchase. August is
    # daylight time, so its 11:00 local effective start is 15:00 UTC.
    assert matches[0].holding_period_start == datetime(2024, 8, 30, 15, 0, tzinfo=UTC)


def test_CMP_02_original_shares_sold_cannot_replace_themselves(engine: ComplianceEngine) -> None:
    buy = _trade(1, date(2026, 9, 20), qty=10)
    sale = _trade(
        2,
        date(2026, 9, 21),
        side=Side.SELL,
        qty=10,
        price="90",
        loss="100",
        acquired_at=buy.ts,
        acquisition_id=buy.trade_id,
    )
    assert WashSaleMatcher(engine.registry).adjustments((buy, sale), ACCOUNTS) == ()


def test_CMP_02_Form_8949_actual_acquisition_is_separate_from_prior_tacking(
    engine: ComplianceEngine,
) -> None:
    original = _trade(1, date(2026, 9, 20), qty=10)
    sale = _trade(
        2,
        date(2026, 9, 21),
        side=Side.SELL,
        qty=10,
        price="90",
        loss="100",
        acquired_at=_instant(date(2026, 1, 1)),
        acquisition_id=original.trade_id,
    )
    replacement = _trade(3, date(2026, 9, 22), qty=10, account="other")
    matcher = WashSaleMatcher(engine.registry)
    matches = matcher.adjustments((original, sale, replacement), ACCOUNTS)
    assert len(matches) == 1
    assert matches[0].holding_period_start == datetime(2026, 1, 2, 17, 0, tzinfo=UTC)
    assert matches[0].acquired_date == date(2026, 9, 20)
    assert matcher.form_8949_rows(matches)[0].date_acquired == date(2026, 9, 20)


def test_R_02_CMP_02_equal_timestamps_do_not_make_uuid_order_tax_evidence(
    engine: ComplianceEngine,
) -> None:
    buy = _trade(20, date(2026, 9, 20), qty=10)
    sale = _trade(
        1,
        date(2026, 9, 20),
        side=Side.SELL,
        qty=10,
        price="90",
        loss="100",
        acquired_at=buy.ts,
        acquisition_id=buy.trade_id,
    )
    assert WashSaleMatcher(engine.registry).adjustments((sale, buy), ACCOUNTS) == ()


def test_R_02_CMP_02_equal_timestamps_without_origin_fail_closed(
    engine: ComplianceEngine,
) -> None:
    buy = _trade(20, date(2026, 9, 20), qty=10)
    sale = _trade(1, date(2026, 9, 20), side=Side.SELL, qty=10, price="110")
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(engine.registry).adjustments((sale, buy), ACCOUNTS)


def test_CMP_02_disposed_cross_account_replacement_has_no_capacity(
    engine: ComplianceEngine,
) -> None:
    buy = _trade(1, date(2026, 9, 5), qty=10, symbol="MSFT", account="other")
    sold = _trade(
        2,
        date(2026, 9, 6),
        qty=10,
        symbol="MSFT",
        account="other",
        side=Side.SELL,
        price="110",
        acquired_at=buy.ts,
        acquisition_id=buy.trade_id,
    )
    loss = _trade(3, date(2026, 9, 20), side=Side.SELL, loss="100")
    assert WashSaleMatcher(engine.registry).adjustments((buy, sold, loss), ACCOUNTS) == ()


def test_CMP_01_CMP_02_overlapping_losses_share_capacity_and_exact_money(
    engine: ComplianceEngine,
) -> None:
    first = _trade(1, date(2026, 9, 10), side=Side.SELL, qty=100, loss="200")
    second = _trade(2, date(2026, 9, 11), side=Side.SELL, qty=100, loss="200")
    replacement = _trade(3, date(2026, 9, 12), qty=150, price="90", account="other")
    matcher = WashSaleMatcher(engine.registry)
    matches = matcher.adjustments((first, second, replacement), ACCOUNTS)
    assert [(row.qty, row.disallowed_loss) for row in matches] == [
        (100, Decimal("200")),
        (50, Decimal("100")),
    ]
    assert sum(row.qty for row in matches) == replacement.qty
    with localcontext() as context:
        context.prec = 2
        assert matcher.adjustments((replacement, second, first), ACCOUNTS) == matches


@pytest.mark.parametrize("account", ["ira", "roth"])
def test_CMP_01_IRA_disallowed_loss_never_increases_retirement_basis(
    engine: ComplianceEngine, account: str
) -> None:
    loss = _trade(1, date(2026, 9, 10), side=Side.SELL, loss="100")
    replacement = _trade(2, date(2026, 9, 11), qty=5, account=account)
    matches = WashSaleMatcher(engine.registry).adjustments((loss, replacement), ACCOUNTS)
    assert len(matches) == 1
    assert matches[0].disallowed_loss == Decimal("50")
    assert matches[0].permanent_loss
    assert matches[0].adjusted_basis is None


@settings(max_examples=50, deadline=None)
@given(loss_shares=st.integers(min_value=2, max_value=200), replacement_shares=st.integers(1, 200))
def test_CMP_01_CMP_02_partial_share_allocation_never_disallows_unmatched_loss(
    loss_shares: int, replacement_shares: int
) -> None:
    loss = _trade(1, date(2026, 9, 10), side=Side.SELL, qty=loss_shares, loss=str(loss_shares))
    replacement = _trade(2, date(2026, 9, 11), qty=replacement_shares, account="other")
    matches = WashSaleMatcher(_registry()).adjustments((loss, replacement), ACCOUNTS)
    expected = min(loss_shares, replacement_shares)
    assert sum(row.qty for row in matches) == expected
    assert sum((row.disallowed_loss for row in matches), Decimal(0)) == Decimal(expected)


def test_CMP_02_forged_wash_models_cannot_bypass_public_matcher(engine: ComplianceEngine) -> None:
    forged = _trade(1, date(2026, 9, 10), side=Side.SELL, loss="100").model_copy(
        update={"price": Decimal("100.001")}
    )
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(engine.registry).adjustments((forged,), ACCOUNTS)


@pytest.mark.parametrize("equity,blocked", [("24999.99", True), ("25000", False)])
def test_CMP_05_legacy_independent_opening_orders_are_counted_before_single_close(
    calendar: MarketCalendar, equity: str, blocked: bool
) -> None:
    engine = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), _registry(), calendar)
    history = (
        _trade(1, date(2026, 10, 1), qty=1, minute=0),
        _trade(2, date(2026, 10, 1), qty=1, minute=1),
        _trade(3, date(2026, 10, 1), qty=1, minute=2),
        _trade(4, date(2026, 10, 1), side=Side.SELL, qty=3, price="110", minute=3),
        _trade(5, NOW.date(), side=Side.SELL, qty=1, minute=-1),
    )
    result = _check(
        engine,
        snapshot=_snapshot(account_type=AccountType.MARGIN, equity=Decimal(equity)),
        history=history,
    )["CMP-05"]
    assert not result.passed
    assert result.severity == (Severity.BLOCK if blocked else Severity.WARN)
    assert "completed=3" in result.observed


def test_CMP_05_one_opening_order_is_counted_once_across_partial_exits(
    calendar: MarketCalendar,
) -> None:
    engine = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), _registry(), calendar)
    history = (
        _trade(1, date(2026, 10, 1), qty=3),
        _trade(2, date(2026, 10, 1), side=Side.SELL, qty=1, price="110", minute=1),
        _trade(3, date(2026, 10, 1), side=Side.SELL, qty=1, price="110", minute=2),
        _trade(4, date(2026, 10, 1), side=Side.SELL, qty=1, price="110", minute=3),
        _trade(5, NOW.date(), side=Side.SELL, qty=1, minute=-1),
    )
    result = _check(engine, snapshot=_snapshot(account_type=AccountType.MARGIN), history=history)[
        "CMP-05"
    ]
    assert not result.passed and result.severity == Severity.WARN
    assert "completed=1" in result.observed


def test_CMP_05_partial_close_uses_conservative_possible_distinct_openings(
    calendar: MarketCalendar,
) -> None:
    engine = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), _registry(), calendar)
    history = (
        _trade(1, date(2026, 10, 1), qty=10),
        _trade(2, date(2026, 10, 1), qty=10, minute=1),
        _trade(3, date(2026, 10, 1), side=Side.SELL, qty=2, price="110", minute=2),
        _trade(4, NOW.date(), side=Side.SELL, qty=1, minute=-1),
    )
    result = _check(
        engine,
        snapshot=_snapshot(account_type=AccountType.MARGIN),
        history=history,
    )["CMP-05"]
    assert not result.passed and result.severity == Severity.WARN
    assert "completed=2" in result.observed


def test_CMP_05_five_sessions_include_oldest_session_but_exclude_sixth(
    calendar: MarketCalendar,
) -> None:
    engine = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), _registry(), calendar)
    history: list[TradeRecord] = []
    for index, day in enumerate(
        (date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30))
    ):
        history.append(_trade(index * 2 + 1, day, qty=1))
        history.append(_trade(index * 2 + 2, day, side=Side.SELL, qty=1, price="110", minute=1))
    history.append(_trade(100, NOW.date(), side=Side.SELL, qty=1, minute=-1))
    result = _check(
        engine,
        snapshot=_snapshot(account_type=AccountType.MARGIN, equity=Decimal("5000")),
        history=tuple(history),
    )["CMP-05"]
    assert not result.passed and result.severity == Severity.BLOCK
    assert "completed=3" in result.observed


def test_R_03_CMP_repeated_evaluation_does_not_mutate_input(engine: ComplianceEngine) -> None:
    proposal = _proposal()
    snapshot = _snapshot()
    before = snapshot.model_dump_json()
    first = _check(engine, proposal=proposal, snapshot=snapshot)
    second = _check(engine, proposal=proposal, snapshot=snapshot)
    assert first == second
    assert snapshot.model_dump_json() == before
    assert proposal.qty == 1


@pytest.mark.parametrize(
    "changed", ["qty", "limit", "history", "account_tax", "flags", "restriction"]
)
def test_R_03_CMP_full_input_hash_binds_proposal_tax_history_flags_and_policy(
    engine: ComplianceEngine, calendar: MarketCalendar, changed: str
) -> None:
    proposal = _proposal()
    snapshot = _snapshot()
    baseline = engine.assess(proposal, snapshot, (), (), ACCOUNTS, NOW, flags=FLAGS)
    history = (
        (_trade(1, date(2026, 9, 20), side=Side.SELL, loss="100"),) if changed == "history" else ()
    )
    accounts = (
        (ExternalAccount(account_id="managed", tax_status=TaxStatus.IRA), *ACCOUNTS[1:])
        if changed == "account_tax"
        else ACCOUNTS
    )
    if changed == "qty":
        proposal = _proposal(qty=2)
    elif changed == "limit":
        proposal = _proposal(limit_price=Decimal("11"))
    active_engine = (
        ComplianceEngine(
            Settings(), engine.registry, calendar, restricted_symbols=frozenset({"AAPL"})
        )
        if changed == "restriction"
        else engine
    )
    flags = FLAGS.model_copy(update={"trading_blocked": True}) if changed == "flags" else FLAGS
    evidence = active_engine.assess(proposal, snapshot, (), history, accounts, NOW, flags=flags)
    assert evidence.proposal_id == baseline.proposal_id
    assert evidence.config_hash == baseline.config_hash
    assert evidence.snapshot_hash == baseline.snapshot_hash
    assert evidence.evaluated_at == baseline.evaluated_at
    assert evidence.input_hash != baseline.input_hash
````````
<!-- END FILE backend/tests/test_stage_c_adversarial.py -->

### config/config.yaml

<!-- BEGIN FILE config/config.yaml -->
````````yaml
# GD-02: research parameters only. Risk ceilings and secrets live in env settings.
watchlist:
  - AAPL
  - MSFT
  - NVDA
  - SPY
  - QQQ
  - XLK
schedule:
  scan_interval_minutes: 15
  offhours_interval_minutes: 60
  scheduler_misfire_grace_seconds: 60
  daily_bar_sip_lag_seconds: 900
alerts:
  alert_cooldown_sessions: 1
playbooks:
  TREND_50EMA:
    criteria_weights:
      trend: 0.40
      reclaim: 0.35
      relative_volume: 0.25
    stop_atr_mult: 2.0
    target_r: 2.0
  BASE_BREAKOUT:
    criteria_weights:
      breakout: 0.45
      relative_volume: 0.35
      trend: 0.20
    stop_atr_mult: 2.0
    target_r: 2.0
  ANCHORED_VWAP_RECLAIM:
    criteria_weights:
      reclaim: 0.45
      momentum: 0.30
      relative_volume: 0.25
    stop_atr_mult: 2.0
    target_r: 2.0
````````
<!-- END FILE config/config.yaml -->

### config/instruments.csv

<!-- BEGIN FILE config/instruments.csv -->
````````csv
symbol,asset_class,gics_sector,themes,is_leveraged,is_inverse,tradable
AAPL,STOCK,Information Technology,CONSUMER_TECH,false,false,true
MSFT,STOCK,Information Technology,CLOUD,false,false,true
NVDA,STOCK,Information Technology,AI_SEMIS,false,false,true
JNJ,STOCK,Health Care,,false,false,true
JPM,STOCK,Financials,,false,false,true
SPY,BROAD_ETF,UNKNOWN,,false,false,true
QQQ,BROAD_ETF,UNKNOWN,MEGA_CAP_TECH,false,false,true
XLK,SECTOR_ETF,Information Technology,,false,false,true
TQQQ,BROAD_ETF,UNKNOWN,MEGA_CAP_TECH,true,false,false
SH,BROAD_ETF,UNKNOWN,,false,true,false
````````
<!-- END FILE config/instruments.csv -->

### config/etf_sector_weights.csv

<!-- BEGIN FILE config/etf_sector_weights.csv -->
````````csv
symbol,gics_sector,weight
SPY,Information Technology,0.30
SPY,Financials,0.15
SPY,Health Care,0.12
SPY,Consumer Discretionary,0.10
SPY,Communication Services,0.09
SPY,Industrials,0.08
SPY,Consumer Staples,0.05
SPY,Energy,0.04
SPY,Utilities,0.03
SPY,Real Estate,0.02
SPY,Materials,0.02
QQQ,Information Technology,0.50
QQQ,Communication Services,0.15
QQQ,Consumer Discretionary,0.15
QQQ,Health Care,0.08
QQQ,Consumer Staples,0.07
QQQ,Industrials,0.05
````````
<!-- END FILE config/etf_sector_weights.csv -->

### config/substantially_identical.csv

<!-- BEGIN FILE config/substantially_identical.csv -->
````````csv
group_id,symbol
````````
<!-- END FILE config/substantially_identical.csv -->

### config/blackout_windows.csv

<!-- BEGIN FILE config/blackout_windows.csv -->
````````csv
symbol,start,end,reason
````````
<!-- END FILE config/blackout_windows.csv -->

### ../.github/workflows/ci.yml

<!-- BEGIN FILE ../.github/workflows/ci.yml -->
````````yaml
name: Stage A through C defensive core
on: [push, pull_request]
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ${{ env.VWS_PROJECT_DIR || '.' }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Locate project
        working-directory: .
        run: |
          if [ -f pyproject.toml ]; then
            echo 'VWS_PROJECT_DIR=.' >> "$GITHUB_ENV"
          else
            echo 'VWS_PROJECT_DIR=vws-core' >> "$GITHUB_ENV"
          fi
      - name: Install exact dependencies
        run: python -m pip install --upgrade pip==26.2.1 && python -m pip install -r requirements-lock.txt && python -m pip install --no-deps -e .
      - name: Lint and format
        run: python -m ruff check . && python -m ruff format --check .
      - name: Strict Stage A through C typing
        run: python -m backend.core.check_stage_c
      - name: Execution source guard
        run: python -m backend.core.source_guard .
      - name: Security checks
        run: python -m bandit -r backend/core backend/domain backend/risk backend/data/market_calendar.py -c pyproject.toml && python -m pip_audit -r requirements-lock.txt --no-deps --disable-pip --progress-spinner off --timeout 15 && python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]' > /tmp/vws-secrets.json && python -c "import json; from pathlib import Path; findings=json.loads(Path('/tmp/vws-secrets.json').read_text())['results']; print(findings); assert not findings"
      - name: Stage A through C tests, network blocked, risk and state branch coverage 100%
        run: python -m pytest backend/tests/test_config_safety.py backend/tests/test_yaml_config.py backend/tests/test_money.py backend/tests/test_logging.py backend/tests/test_ledger.py backend/tests/test_research_ledger.py backend/tests/test_system_state.py backend/tests/test_market_calendar.py backend/tests/test_no_order_exec.py backend/tests/test_domain.py backend/tests/test_risk_cro.py backend/tests/test_risk_boundary.py backend/tests/test_stage_b_adversarial.py backend/tests/test_compliance.py backend/tests/test_wash_sales.py backend/tests/test_compliance_boundary.py backend/tests/test_stage_c_adversarial.py --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov-branch --cov-fail-under=100 --cov-report=term-missing
````````
<!-- END FILE ../.github/workflows/ci.yml -->

### ../.pre-commit-config.yaml

<!-- BEGIN FILE ../.pre-commit-config.yaml -->
````````yaml
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: Ruff lint
        entry: python -m ruff check
        language: system
        types: [python]
      - id: ruff-format
        name: Ruff format check
        entry: python -m ruff format --check
        language: system
        types: [python]
      - id: no-order-execution
        name: R-10 GD-07 source guard
        entry: python -m backend.core.source_guard .
        language: system
        pass_filenames: false
        always_run: true
      - id: stage-abc-types
        name: Stage A through C strict types
        entry: python -m backend.core.check_stage_c
        language: system
        pass_filenames: false
        types: [python]
      - id: detect-secrets
        name: Secrets scan
        entry: detect-secrets-hook
        language: system
        exclude: (^|/)(backend/tests/|requirements-lock\.txt$|deliveries/)
````````
<!-- END FILE ../.pre-commit-config.yaml -->

### ../.gitignore

<!-- BEGIN FILE ../.gitignore -->
````````text
.env
.env.*
!.env.example
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage*
htmlcov/
*.db
*.db-wal
*.db-shm
*.sqlite3
*.sqlite3-wal
*.sqlite3-shm
*.egg-info/
build/
dist/
.mutmut-cache/
mutants/
*.pem
*.key
*.token
*.fernet
.secrets/
audit-report.json
bandit-report.json
.hypothesis/
coverage.xml
coverage-stage-b.json
coverage-stage-c.json
secrets-report.json
````````
<!-- END FILE ../.gitignore -->

