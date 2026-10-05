# Stage B - full delivery

Stage B is complete under the newest master spec. Stage A remains delivered.
Stop here; the next command is Execute Stage C. No execution APIs exist.

1,167 offline tests passed in 77.13 seconds. Pure CRO coverage: 217 statements
and 56 branches, 100%. RiskBoundary: 80 statements and 32 branches, 100%.
Persisted state: 163 statements and 46 branches, 100%. Ruff, strict mypy,
AST source guard, Bandit, all five pre-commit hooks, pip check, secrets scan,
and audit of all 109 transitive pins passed. See the full VERIFY.md below.

Every file in the manifest is reproduced in full, including referenced sample
configuration and parent Git-root mirrors. Files are UTF-8; each byte count and
SHA-256 describes the original file bytes. Stage_A.md is retained as its original
historical delivery. Preserved Stage C/D drafts are outside this certification.

## ASSUMPTIONS

# ASSUMPTIONS

The newest master spec supersedes the earlier A–D blueprint and automatic
continuation request. The current command authorizes Stage B, with Stage A already
delivered. Stage C starts only after `Execute Stage C`. Order execution is permanently
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
25. Older C–D drafts and core/gate.py are preserved, not certified against the new master spec.
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
26. APScheduler 3.11.3 is the stable installed release with AsyncIOScheduler;
    actual scheduling is deferred to Stage F. Full source delivery uses a local
    Markdown artifact: assumptions, SHA-256 manifest, then every file in full.
27. SQLite recursive triggers are explicitly enabled to prevent REPLACE from
    deleting/replacing protected rows. State-control projections are verified
    against immutable events during live reads/transitions, not only at startup.


## FILE MANIFEST

| File | Scope | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| .env.example | Stage B and referenced configuration | 2606 | d4665b19a70c0d2d776e1e0be4c1351003f7d286c91b4f679983bcbf964a41fb |
| .gitignore | Stage B and referenced configuration | 371 | 9652788a7167eb59505640f6622c916b58e16004d0ea85b9ff6984bb10336de9 |
| .pre-commit-config.yaml | Stage B and referenced configuration | 906 | 8096372a7dd01ef88e42a191e0b2fa23f9c35d1da60055fffe68af0a275bf281 |
| pyproject.toml | Stage B and referenced configuration | 2240 | 2e1856235685591bd7d81652df03e12a9e7b437f1305cdd947c45f5233f64275 |
| requirements-lock.txt | Stage B and referenced configuration | 2123 | d465af53a4e8375afc2014db09889d14b4badfeb9a932fa5d3b344920273d5dc |
| .github/workflows/ci.yml | Stage B and referenced configuration | 2477 | 68e93ac1648819b1ae3f99965b03239494c7e0d21dc4387d71aaded0621c844d |
| README.md | Stage B and referenced configuration | 6412 | 2a2db9927633e5c895f14f253b4448d011c03576259788be5deff337b31a2912 |
| ASSUMPTIONS.md | Stage B and referenced configuration | 10362 | f88ea397e2bd52a765a3a5e23460a0d6f94fd909a5da2330cb6b359f1f5532e1 |
| VERIFY.md | Stage B and referenced configuration | 13582 | 1c973e27d148c019aba4c38c7f93b5eac5b5d6237119ef5b7ad94b2b45e7d913 |
| backend/core/check_stage_a.py | Stage B and referenced configuration | 1880 | 1fb4e8f146fc171bc40a071aa1f28d5cdb9dadd2e17e759a5b1fa41c113936ef |
| backend/core/check_stage_b.py | Stage B and referenced configuration | 1574 | 1cb98df34e1e402f67a9a599f3fcf54a14dc47d47d073d87eb2a3303d7acc6a9 |
| backend/domain/__init__.py | Stage B and referenced configuration | 82 | 75159c158cfe9b9ec1e4f7ec7eeb7b41d6666b253a09af5ac14f3288545edd7f |
| backend/domain/models.py | Stage B and referenced configuration | 19535 | df24b430981af747f3dd3a3a6be398043af3885fbeea9cc516d02ff932605824 |
| backend/domain/instruments.py | Stage B and referenced configuration | 12719 | df71caa90a340e8baeba32091f93ca858d6d286b109296c68968a32689c085aa |
| backend/risk/__init__.py | Stage B and referenced configuration | 68 | bed55df552c4aaba26164d22966cdfb9d8f2dca25ad9c293dc21147b55eb5220 |
| backend/risk/risk_cro.py | Stage B and referenced configuration | 24232 | f2ba629e627299bee5b0586b4c5d05dfe9bb1639920b0474170c5e3c8e88023e |
| backend/risk/boundary.py | Stage B and referenced configuration | 8495 | b8e8864c3c1c37a65b8e46854f90d0068f29b818047550a190703f48a4ddcf32 |
| backend/tests/test_domain.py | Stage B and referenced configuration | 34328 | 814aaba22e89c4f500fbf389a2066923da84c2fe7e798d2be7798d4b08bab6ad |
| backend/tests/test_risk_cro.py | Stage B and referenced configuration | 38631 | f17d6d13efff2b5ee143a69691bfd6e8de8e1eed411ce161451972309ed242bd |
| backend/tests/test_risk_boundary.py | Stage B and referenced configuration | 15633 | c173629ff9b90cc2e8ebffc36718a479b0548fa5e3f9347cabdd6cde56ca7048 |
| backend/tests/test_stage_b_adversarial.py | Stage B and referenced configuration | 14127 | c75c1503a6446c05fd0694f0d54232c565b623d365cf27bdd8654f13afd48d2c |
| config/config.yaml | Stage B and referenced configuration | 782 | 2714e63536baca5dd313596df9401ff5fa5e62a81358e35749a5f9e0a1ce3d0c |
| config/instruments.csv | Stage B and referenced configuration | 574 | 1d7f9d8750254079ead7e666ba4bbff5e6d270fa28c56511df361baaefb67e0f |
| config/etf_sector_weights.csv | Stage B and referenced configuration | 449 | 69f61d9c5cdb275b9fe4967acf38fe2688e0ad4f326e5ae7924bbc8a90ffe44e |
| config/substantially_identical.csv | Stage B and referenced configuration | 16 | c37995109bdb6b50a3cb83c024d1766379b2a41b7ceee5dea3084f6652afdfe2 |
| config/blackout_windows.csv | Stage B and referenced configuration | 24 | 56ea224a05617ca3033069d373ae86d2eeb1abdcb555abb4e91ff86fbe822143 |
| ../.github/workflows/ci.yml | Git-root mirror | 2477 | 68e93ac1648819b1ae3f99965b03239494c7e0d21dc4387d71aaded0621c844d |
| ../.pre-commit-config.yaml | Git-root mirror | 906 | 8096372a7dd01ef88e42a191e0b2fa23f9c35d1da60055fffe68af0a275bf281 |
| ../.gitignore | Git-root mirror | 371 | 9652788a7167eb59505640f6622c916b58e16004d0ea85b9ff6984bb10336de9 |

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
      - id: stage-ab-types
        name: Stage A and B strict types
        entry: python -m backend.core.check_stage_b
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
source = ["backend.core.system_state", "backend.risk.risk_cro", "backend.risk.boundary"]

[tool.bandit]
exclude_dirs = ["backend/tests", ".venv", "mutants"]

[tool.mutmut]
source_paths = ["backend/risk/"]
also_copy = ["backend/core", "backend/data", "backend/domain", "backend/tests", "config", "scripts"]
pytest_add_cli_args_test_selection = ["backend/tests/test_risk_cro.py", "backend/tests/test_compliance.py"]
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
name: Stage A and B defensive core
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
      - name: Strict Stage A and B typing
        run: python -m backend.core.check_stage_b
      - name: Execution source guard
        run: python -m backend.core.source_guard .
      - name: Security checks
        run: python -m bandit -r backend/core backend/domain backend/risk/risk_cro.py backend/risk/boundary.py backend/data/market_calendar.py -c pyproject.toml && python -m pip_audit -r requirements-lock.txt --no-deps --disable-pip --progress-spinner off --timeout 15 && python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]' > /tmp/vws-secrets.json && python -c "import json; from pathlib import Path; findings=json.loads(Path('/tmp/vws-secrets.json').read_text())['results']; print(findings); assert not findings"
      - name: Stage A and B tests, network blocked, state and CRO branch coverage 100%
        run: python -m pytest backend/tests/test_config_safety.py backend/tests/test_yaml_config.py backend/tests/test_money.py backend/tests/test_logging.py backend/tests/test_ledger.py backend/tests/test_research_ledger.py backend/tests/test_system_state.py backend/tests/test_market_calendar.py backend/tests/test_no_order_exec.py backend/tests/test_domain.py backend/tests/test_risk_cro.py backend/tests/test_risk_boundary.py backend/tests/test_stage_b_adversarial.py --cov=backend.core.system_state --cov=backend.risk.risk_cro --cov=backend.risk.boundary --cov-branch --cov-fail-under=100 --cov-report=term-missing
````````
<!-- END FILE .github/workflows/ci.yml -->

### README.md

<!-- BEGIN FILE README.md -->
````````markdown
# vws-core — Stages A and B

Read-only defensive infrastructure for long-only, whole-share research and human
trade tickets. Stage A supplies configuration guards, exact money/cent-price
helpers, UTC clocks, redacted logging, deduplicated notifications, XNYS sessions,
an immutable audit ledger, durable halt state, and an execution-code source guard.

Stage B adds frozen domain/research contracts, a validated instrument registry,
all thirteen deterministic CRO rules, sequential batch reservations, conservative
quantity suggestions, and RiskBoundary for persisted tiers and veto audit logs.
The combined offline suite passes 1,167 tests. The CRO, boundary, and state machine
each have 100% statement and branch coverage.

The research swarm and Telegram bot await later stages. Existing C–D drafts and
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

## Verify Stages A and B

Activate the virtual environment, then use the same commands as CI:

```text
python -m ruff check .
python -m ruff format --check .
python -m backend.core.check_stage_b
python -m backend.core.source_guard .
python -m bandit -r backend/core backend/domain backend/risk/risk_cro.py backend/risk/boundary.py backend/data/market_calendar.py -c pyproject.toml
python -m pip_audit -r requirements-lock.txt --no-deps --disable-pip --progress-spinner off --timeout 15
python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]'
python -m pytest backend/tests/test_config_safety.py backend/tests/test_yaml_config.py backend/tests/test_money.py backend/tests/test_logging.py backend/tests/test_ledger.py backend/tests/test_research_ledger.py backend/tests/test_system_state.py backend/tests/test_market_calendar.py backend/tests/test_no_order_exec.py backend/tests/test_domain.py backend/tests/test_risk_cro.py backend/tests/test_risk_boundary.py backend/tests/test_stage_b_adversarial.py --cov=backend.core.system_state --cov=backend.risk.risk_cro --cov=backend.risk.boundary --cov-branch --cov-fail-under=100 --cov-report=term-missing
```

On Windows `.venv\Scripts\python.exe -m` can replace python -m. The secrets scan
emits JSON; an empty results object is required. Synthetic tests and the full
source delivery are excluded from that heuristic scan, not from the AST guard.
The guard checks all authored Python files, with only its banned-list constants
module exempt. The pre-commit configuration provides the same local source checks.

The coverage gate applies to the completed state machine, CRO and boundary. The master
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

See ASSUMPTIONS.md and VERIFY.md. The full manifest and untruncated source are in
deliveries/Stage_A.md and deliveries/Stage_B.md. Continue with exactly Execute
Stage C for compliance rules and their tests.
````````
<!-- END FILE README.md -->

### ASSUMPTIONS.md

<!-- BEGIN FILE ASSUMPTIONS.md -->
````````markdown
# ASSUMPTIONS

The newest master spec supersedes the earlier A–D blueprint and automatic
continuation request. The current command authorizes Stage B, with Stage A already
delivered. Stage C starts only after `Execute Stage C`. Order execution is permanently
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
25. Older C–D drafts and core/gate.py are preserved, not certified against the new master spec.
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
# Stage A and B verification — 2026-10-04

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

Tags in older B–D drafts below are historical review references, not certification
of those drafts against the new master spec. Each location is collected verbatim.

| Location | Reference |
| --- | --- |
| .env.example:50 | https://docs.x.ai/developers/model-capabilities/text/generate-text |
| .env.example:52 | https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk |
| .env.example:54 | https://developers.openai.com/api/reference/overview |
| backend/core/check_stage_a.py:40 | https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application |
| backend/core/check_stage_b.py:31 | https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application |
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
| backend/risk/compliance.py:184 | https://www.sec.gov/resources-for-investors/investor-alerts-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor-bulletin |
| backend/risk/compliance.py:226 | https://www.irs.gov/publications/p550 |
| backend/risk/compliance.py:227 | https://www.irs.gov/pub/irs-drop/rr-08-05.pdf |
| backend/risk/compliance.py:299 | https://www.irs.gov/instructions/i8949 |
| backend/risk/compliance.py:624 | https://syndication.finra.org/content/understanding-new-intraday-margin-requirements |
| scripts/plaid_sandbox_token.py:62 | https://github.com/plaid/plaid-python#usage |
| scripts/plaid_sandbox_token.py:72 | https://plaid.com/docs/api/sandbox/#sandboxpublic_tokencreate |
| scripts/plaid_sandbox_token.py:73 | https://plaid.com/docs/balance/ |
| scripts/plaid_sandbox_token.py:83 | https://plaid.com/docs/api/items/#itempublic_tokenexchange |
````````
<!-- END FILE VERIFY.md -->

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

### backend/risk/__init__.py

<!-- BEGIN FILE backend/risk/__init__.py -->
````````python
"""R-02/R-03: deterministic read-only risk and compliance gates."""
````````
<!-- END FILE backend/risk/__init__.py -->

### backend/risk/risk_cro.py

<!-- BEGIN FILE backend/risk/risk_cro.py -->
````````python
"""CRO-01..13/R-01..05/R-09/R-13: pure, conservative, exact risk decisions.

The enclosing boundary logs vetoes and persists recommended state escalations.
Pending sells never release inventory/exposure before a fill. Pending same-name
buys reserve risk using protection evidence; an unknown stop reserves the whole
notional. Unconfigured known sectors use 35%; unconfigured themes use zero.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState, financial_state, state_allows
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import GICS_SECTORS, InstrumentRegistry
from backend.domain.models import (
    AssetClass,
    BlackoutWindow,
    CapitalStatus,
    Decision,
    DeployableCapital,
    Intent,
    MarketContext,
    MarketStatus,
    OpenOrder,
    PortfolioSnapshot,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
    Verdict,
    snapshot_hash,
)

ZERO = Decimal("0")
DEFAULT_SECTOR_CAP = Decimal("0.35")
SIZING_RULES = frozenset(f"CRO-{number:02d}" for number in range(2, 9))
EXCHANGE_TIMEZONE = ZoneInfo("America/New_York")
STATE_RANK = {SystemState.RUNNING: 0, SystemState.REDUCE_ONLY: 1, SystemState.HALTED: 2}


def _result(
    rule_id: str,
    passed: bool,
    observed: object,
    limit: object,
    message: str,
    severity: Severity = Severity.BLOCK,
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        passed=passed,
        severity=severity,
        observed=str(observed),
        limit=str(limit),
        message=message,
    )


def _entry(proposal: TradeProposal) -> bool:
    return proposal.intent in {Intent.ENTRY, Intent.ADD}


class ChiefRiskOfficer:
    """CRO-01..13: injected immutable policy and prebuilt calendar; no I/O."""

    def __init__(
        self,
        config: Settings,
        registry: InstrumentRegistry,
        calendar: MarketCalendar,
        *,
        blackout_windows: tuple[BlackoutWindow, ...] = (),
    ) -> None:
        try:
            # Reconstruct policy: model_copy/model_construct bypass validation.
            policy = config.model_dump(mode="python")
            if (
                not config.telegram_allowed_user_ids
                and "telegram_allowed_user_ids" not in config.model_fields_set
            ):
                del policy["telegram_allowed_user_ids"]
            self.config = Settings.model_validate(policy)
            if not isinstance(registry, InstrumentRegistry) or not isinstance(
                calendar, MarketCalendar
            ):
                raise DataIntegrityError("CRO-02: registry and bounded calendar are required")
            self.registry = InstrumentRegistry.validated_copy(registry)
            self.calendar = calendar
            self.blackout_windows = tuple(
                BlackoutWindow.model_validate(window)
                for window in (*self.registry.blackout_windows, *blackout_windows)
            )
            self._config_hash = self.config.config_hash
        except Exception as exc:
            raise ConfigurationError("CRO-01..13: cannot verify immutable risk policy") from exc

    def evaluate(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
        state: SystemState,
        now: datetime,
        *,
        deployable: DeployableCapital | None = None,
    ) -> Verdict:
        """CRO-01..13/R-02/R-03: all evidence; only CRO-01 short-circuits.

        R-09 valid reductions/exits use state and verifiable held inventory only.
        Financial tiers travel independently as recommended_state, including on
        exits, without effects or retroactively blocking that exit. Unknown
        earnings is a failed WARN and cannot veto an otherwise valid buy.
        """
        try:
            instant = ensure_utc(now)
            proposal = TradeProposal.model_validate(proposal)
            snapshot = PortfolioSnapshot.model_validate(snapshot)
            state_result = _result(
                "CRO-01",
                isinstance(state, SystemState)
                and state_allows(state, proposal.intent, proposal.source),
                state,
                "RUNNING, or permitted reduction/exit",
                "system operating state permits proposal",
            )
            recommended = financial_state(
                snapshot.equity, snapshot.high_water_mark, snapshot.day_start_equity, self.config
            )
            if not state_result.passed:
                return self._verdict(proposal, snapshot, instant, (state_result,), recommended)
            if not _entry(proposal):
                shape = self._shape(proposal, snapshot, None, instant)
                return self._verdict(
                    proposal, snapshot, instant, (state_result, shape), recommended
                )
            if market is None:
                raise DataIntegrityError("CRO-02: entry requires verified market context")
            market = MarketContext.model_validate(market)
            if deployable is not None:
                deployable = DeployableCapital.model_validate(deployable)
            limits = [self.config.__dict__[name] for name in self.config.DECIMAL_BOUNDS]
            limits.extend(self.config.sector_caps.values())
            limits.extend(self.config.theme_caps.values())
            with localcontext() as context:
                context.prec = max(
                    80,
                    len(str(proposal.qty)) + 40,
                    max(len(value.as_tuple().digits) for value in limits) + 40,
                )
                shape = self._shape(proposal, snapshot, market, instant)
                results = self._rules(proposal, snapshot, market, instant, deployable)
            return self._verdict(
                proposal, snapshot, instant, (state_result, shape, *results), recommended
            )
        except Exception as exc:
            try:
                instant = ensure_utc(now)
                if not isinstance(proposal.proposal_id, UUID):
                    raise DataIntegrityError("CRO-02: invalid proposal identity")
                failures = tuple(
                    _result(
                        f"CRO-{number:02d}",
                        False,
                        type(exc).__name__,
                        "verifiable inputs",
                        "input or policy evaluation failed closed",
                    )
                    for number in range(1, 14)
                )
                return Verdict(
                    proposal_id=proposal.proposal_id,
                    decision=Decision.VETOED,
                    results=failures,
                    config_hash=self._config_hash,
                    snapshot_hash="0" * 64,
                    evaluated_at=instant,
                    recommended_state=SystemState.HALTED,
                )
            except Exception as audit_error:
                raise DataIntegrityError(
                    "CRO-02: cannot construct an auditable veto"
                ) from audit_error

    def _verdict(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        now: datetime,
        results: tuple[RuleResult, ...],
        recommended: SystemState,
    ) -> Verdict:
        decision = (
            Decision.VETOED
            if any(not result.passed and result.severity == Severity.BLOCK for result in results)
            else Decision.APPROVED
        )
        return Verdict(
            proposal_id=proposal.proposal_id,
            decision=decision,
            results=results,
            config_hash=self._config_hash,
            snapshot_hash=snapshot_hash(snapshot),
            evaluated_at=now,
            recommended_state=recommended,
        )

    def _shape(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
        now: datetime,
    ) -> RuleResult:
        """CRO-02/R-01/R-09/R-13: account-bound fresh inventory and cent prices."""
        common = (
            proposal.account_id == snapshot.account_id
            and proposal.created_at <= now < proposal.expires_at
            and snapshot.as_of <= now
            and now - snapshot.as_of <= timedelta(seconds=self.config.stale_quote_seconds)
        )
        held = snapshot.positions.get(proposal.symbol)
        if not _entry(proposal):
            reserved = sum(
                order.qty
                for order in snapshot.open_orders
                if order.symbol == proposal.symbol and order.side == Side.SELL
            )
            available = 0 if held is None else max(0, held.qty - reserved)
            return _result(
                "CRO-02",
                common and proposal.qty <= available,
                proposal.qty,
                available,
                "reduction fits fresh held unreserved shares",
            )
        instrument = self.registry.get(proposal.symbol)
        # R-02: even zero holdings and pending sells must be identifiable for a buy.
        for symbol in snapshot.positions:
            self.registry.get(symbol)
        for order in snapshot.open_orders:
            self.registry.get(order.symbol)
        pending_qty = sum(
            order.qty
            for order in snapshot.open_orders
            if order.symbol == proposal.symbol and order.side == Side.BUY
        )
        already_held = (held is not None and held.qty > 0) or pending_qty > 0
        intent_matches = already_held if proposal.intent == Intent.ADD else not already_held
        valid = (
            common
            and intent_matches
            and snapshot.equity > 0
            and instrument.tradable
            and not instrument.is_leveraged
            and not instrument.is_inverse
            and market is not None
            and market.status == MarketStatus.OK
        )
        return _result(
            "CRO-02",
            valid,
            proposal.symbol,
            "valid long-only allowlisted instrument",
            "entry/add intent, stop, expiry, account, inventory and market are verified",
        )

    @staticmethod
    def _pending(snapshot: PortfolioSnapshot) -> dict[str, Decimal]:
        pending: dict[str, Decimal] = {}
        for order in snapshot.open_orders:
            if order.side == Side.BUY:
                pending[order.symbol] = (
                    pending.get(order.symbol, ZERO) + order.qty * order.limit_price
                )
        return pending

    def _risk(self, proposal: TradeProposal, snapshot: PortfolioSnapshot) -> RuleResult:
        """CRO-04: reserve new, existing ADD and same-name pending protection risk."""
        stop = proposal.stop_price
        if stop is None:
            raise DataIntegrityError("CRO-04: buy protection cannot be verified")
        risk = proposal.qty * (proposal.limit_price - stop)
        risk += proposal.qty * proposal.limit_price * self.config.stop_slippage_buffer
        position = snapshot.positions.get(proposal.symbol)
        if proposal.intent == Intent.ADD and position is not None:
            risk += position.qty * max(ZERO, position.last_price - stop)
            risk += position.value * self.config.stop_slippage_buffer
        for order in snapshot.open_orders:
            if order.symbol == proposal.symbol and order.side == Side.BUY:
                loss = (
                    order.limit_price
                    if order.stop_price is None
                    else max(ZERO, order.limit_price - min(stop, order.stop_price))
                )
                risk += (
                    order.qty * loss
                    + order.qty * order.limit_price * self.config.stop_slippage_buffer
                )
        limit = self.config.max_risk_per_trade * max(ZERO, snapshot.equity)
        return _result(
            "CRO-04", risk <= limit, risk, limit, "reserved stop risk plus slippage fits budget"
        )

    def _rules(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext,
        now: datetime,
        deployable: DeployableCapital | None,
    ) -> tuple[RuleResult, ...]:
        instrument = self.registry.get(proposal.symbol)
        pending = self._pending(snapshot)
        notional = proposal.qty * proposal.limit_price
        equity = max(ZERO, snapshot.equity)
        exposures = {
            symbol: position.value
            for symbol, position in snapshot.positions.items()
            if position.qty > 0
        }
        for symbol, value in pending.items():
            exposures[symbol] = exposures.get(symbol, ZERO) + value
        exposures[proposal.symbol] = exposures.get(proposal.symbol, ZERO) + notional
        cap = (
            self.config.max_single_stock_weight
            if instrument.asset_class == AssetClass.STOCK
            else self.config.max_single_etf_weight
        )
        name = _result(
            "CRO-03",
            exposures[proposal.symbol] <= cap * equity,
            exposures[proposal.symbol],
            cap * equity,
            "post-trade single-name value fits cap",
        )
        risk = self._risk(proposal, snapshot)
        allocation = self._allocation(exposures, equity)
        gross = sum(exposures.values(), ZERO)
        cash_after = snapshot.cash - sum(pending.values(), ZERO) - notional
        exposure = _result(
            "CRO-06",
            gross <= self.config.max_gross_exposure * equity
            and len(exposures) <= self.config.max_open_positions
            and cash_after >= self.config.min_cash_pct * equity,
            f"gross={gross}; positions={len(exposures)}; cash={cash_after}",
            f"gross<={self.config.max_gross_exposure * equity}; positions<={self.config.max_open_positions}; cash>={self.config.min_cash_pct * equity}",
            "gross exposure, number of names, and cash buffer all fit",
        )
        price = self._price(proposal, market, now)
        liquidity = _result(
            "CRO-08",
            notional <= self.config.max_pct_of_adv * market.adv20_usd,
            notional,
            self.config.max_pct_of_adv * market.adv20_usd,
            "notional fits average-volume cap",
        )
        baseline = snapshot.high_water_mark
        drawdown = ZERO if baseline <= 0 else max(ZERO, (baseline - equity) / baseline)
        drawdown_result = _result(
            "CRO-09",
            equity > 0
            and baseline > 0
            and max(ZERO, baseline - equity) < self.config.dd_reduce_only * baseline,
            drawdown,
            self.config.dd_reduce_only,
            "persisted drawdown below reduce-only tier",
        )
        day_start = snapshot.day_start_equity
        daily_loss = ZERO if day_start <= 0 else (day_start - equity) / day_start
        daily = _result(
            "CRO-10",
            equity > 0
            and day_start > 0
            and day_start - equity < self.config.daily_loss_limit * day_start,
            daily_loss,
            self.config.daily_loss_limit,
            "persisted daily loss below reduce-only tier",
        )
        blocked = any(
            window.start <= now <= window.end and window.symbol in {None, proposal.symbol}
            for window in self.blackout_windows
        )
        blackout = _result(
            "CRO-11",
            not blocked,
            "in blackout" if blocked else "clear",
            "outside all applicable UTC blackouts",
            "scheduled blackout includes both endpoint instants",
        )
        funding = _result(
            "CRO-12",
            deployable is not None and deployable.status == CapitalStatus.OK,
            "missing" if deployable is None else deployable.status,
            CapitalStatus.OK,
            "checking buffer and funding reading must be available",
        )
        earnings = self._earnings(market, now)
        return (
            name,
            risk,
            allocation,
            exposure,
            price,
            liquidity,
            drawdown_result,
            daily,
            blackout,
            funding,
            earnings,
        )

    def _allocation(self, exposures: dict[str, Decimal], equity: Decimal) -> RuleResult:
        """CRO-05: all holdings/pending buys participate in ETF look-through."""
        sectors: dict[str, Decimal] = {}
        themes: dict[str, Decimal] = {}
        known = True
        for symbol, value in exposures.items():
            instrument = self.registry.get(symbol)
            for sector, weight in self.registry.sector_weights(symbol).items():
                known = known and sector in GICS_SECTORS
                sectors[sector] = sectors.get(sector, ZERO) + value * weight
            for theme in instrument.themes:
                themes[theme] = themes.get(theme, ZERO) + value
        within_sectors = all(
            value <= self.config.sector_caps.get(sector, DEFAULT_SECTOR_CAP) * equity
            for sector, value in sectors.items()
        )
        within_themes = all(
            value <= self.config.theme_caps.get(theme, ZERO) * equity
            for theme, value in themes.items()
        )
        return _result(
            "CRO-05",
            known and within_sectors and within_themes,
            f"sectors={sorted(sectors.items())}; themes={sorted(themes.items())}",
            "configured sector/theme fractions",
            "sector look-through and theme caps fit",
        )

    def _price(self, proposal: TradeProposal, market: MarketContext, now: datetime) -> RuleResult:
        """CRO-07/DAT-01: regular-hour age; otherwise age from last close."""
        reference = (
            now
            if self.calendar.is_open(now)
            else self.calendar.session_close(self.calendar.last_completed_session(now))
        )
        age = max(timedelta(0), reference - market.last_price_ts)
        collar = (
            abs(proposal.limit_price - market.last_price)
            <= self.config.price_collar * market.last_price
        )
        valid = (
            market.last_price_ts <= now
            and age <= timedelta(seconds=self.config.stale_quote_seconds)
            and collar
            and proposal.limit_price >= self.config.min_price
        )
        return _result(
            "CRO-07",
            valid,
            f"price={proposal.limit_price}; reference={market.last_price}; age={age}",
            f"collar={self.config.price_collar}; min={self.config.min_price}; age<={self.config.stale_quote_seconds}s",
            "limit price and calendar-aware quote freshness are sane",
        )

    def _earnings(self, market: MarketContext, now: datetime) -> RuleResult:
        """CRO-13: inclusive XNYS proximity; unknown warns, never counts as neutral."""
        earnings = market.next_earnings_date
        if earnings is None:
            return _result(
                "CRO-13",
                False,
                "unknown",
                "verified earnings date",
                "earnings unavailable; operator must review unknown event risk",
                Severity.WARN,
            )
        today = now.astimezone(EXCHANGE_TIMEZONE).date()
        self.calendar.is_session(today)  # Enforce bounds even for a past event.
        on_session = self.calendar.is_session(earnings)
        if earnings <= today:
            blocked = True
        else:
            count = self.config.earnings_blackout_sessions + (0 if on_session else 1)
            earliest = (
                earnings if count == 0 else self.calendar.previous_sessions(earnings, count)[0]
            )
            blocked = today >= earliest
        return _result(
            "CRO-13",
            not blocked,
            earnings.isoformat(),
            f"outside {self.config.earnings_blackout_sessions} XNYS sessions",
            "known earnings within inclusive blackout or unresolved past date blocks",
        )

    def max_allowed_qty(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext,
        now: datetime,
    ) -> int:
        """CRO-03..08/R-04: largest eligible whole quantity, capped at requested qty.

        Advisory reduction only. Complete unique CRO-02..08 evidence is required,
        so an empty/failed evaluation cannot look eligible. Sizing is monotone.
        """
        try:
            proposal = TradeProposal.model_validate(proposal)
            snapshot = PortfolioSnapshot.model_validate(snapshot)
            market = MarketContext.model_validate(market)
            instant = ensure_utc(now)
            if not _entry(proposal):
                return 0
            with localcontext() as context:
                context.prec = 80
                upper = max(
                    0,
                    min(
                        proposal.qty,
                        int(min(snapshot.cash, snapshot.equity) / proposal.limit_price),
                    ),
                )
            lower = 0
            while lower < upper:
                midpoint = (lower + upper + 1) // 2
                candidate = proposal.model_copy(update={"qty": midpoint})
                verdict = self.evaluate(candidate, snapshot, market, SystemState.RUNNING, instant)
                evidence = tuple(
                    result for result in verdict.results if result.rule_id in SIZING_RULES
                )
                eligible = (
                    len(evidence) == len(SIZING_RULES)
                    and {result.rule_id for result in evidence} == SIZING_RULES
                    and all(
                        result.passed and result.severity == Severity.BLOCK for result in evidence
                    )
                )
                if eligible:
                    lower = midpoint
                else:
                    upper = midpoint - 1
            return lower
        except Exception as exc:
            raise DataIntegrityError("CRO-03..08: deterministic sizing failed closed") from exc

    def evaluate_batch(
        self,
        proposals: Iterable[TradeProposal],
        snapshot: PortfolioSnapshot,
        markets: dict[str, MarketContext],
        state: SystemState,
        now: datetime,
        *,
        deployable: DeployableCapital | None = None,
    ) -> tuple[Verdict, ...]:
        """CRO-03/CRO-04/CRO-06/R-09: sequential notional, protection/inventory reservations."""
        current = snapshot
        current_state = state
        verdicts: list[Verdict] = []
        try:
            for proposal in proposals:
                market = markets.get(proposal.symbol) if _entry(proposal) else None
                verdict = self.evaluate(
                    proposal, current, market, current_state, now, deployable=deployable
                )
                verdicts.append(verdict)
                if (
                    isinstance(current_state, SystemState)
                    and STATE_RANK[verdict.recommended_state] > STATE_RANK[current_state]
                ):
                    current_state = verdict.recommended_state
                if verdict.decision == Decision.APPROVED:
                    pending = OpenOrder(
                        symbol=proposal.symbol,
                        side=proposal.side,
                        qty=proposal.qty,
                        limit_price=proposal.limit_price,
                        stop_price=proposal.stop_price,
                    )
                    current = current.model_copy(
                        update={"open_orders": (*current.open_orders, pending)}
                    )
            return tuple(verdicts)
        except Exception as exc:
            raise DataIntegrityError("CRO-03/CRO-06: batch inputs cannot be verified") from exc
````````
<!-- END FILE backend/risk/risk_cro.py -->

### backend/risk/boundary.py

<!-- BEGIN FILE backend/risk/boundary.py -->
````````python
"""R-02/R-03/CRO-01..13: durable state and veto logs outside pure rules."""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from backend.core.clock import Clock, ensure_utc
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore, financial_state
from backend.domain.models import (
    Decision,
    DeployableCapital,
    Intent,
    MarketContext,
    PortfolioSnapshot,
    Severity,
    TradeProposal,
    Verdict,
    snapshot_hash,
)
from backend.risk.risk_cro import ChiefRiskOfficer


class VetoSink(Protocol):
    """R-07: an audit sink receives only the required nonsensitive identities."""

    def record(self, rule_id: str, proposal_id: UUID) -> None:
        """R-02: emit a veto record, raising if the audit sink is unavailable."""
        raise DataIntegrityError("R-02: veto audit sink has no implementation")


class LoggingVetoSink:
    """R-02/R-07: static log text plus rule and proposal identifiers."""

    def record(self, rule_id: str, proposal_id: UUID) -> None:
        logging.getLogger(__name__).warning(
            "risk_veto rule_id=%s proposal_id=%s", rule_id, proposal_id
        )


class RiskBoundary:
    """R-02/R-03: evaluate locally, latch tiers, and emit every blocking veto.

    This returns research evidence, never an execution authorization. Complete
    RuleResults travel in the immutable Verdict; the later service records them
    against its signal/proposal ledger rows. Fresh approval revalidation belongs
    at the later human approval boundary. A newly detected financial HALT does
    not retroactively trap an otherwise valid held exit (R-09); subsequent calls
    observe HALTED and require a MANUAL exit.
    """

    def __init__(
        self,
        cro: ChiefRiskOfficer,
        state: SystemStateStore,
        clock: Clock,
        *,
        veto_sink: VetoSink | None = None,
    ) -> None:
        self.cro = cro
        self.state = state
        self.clock = clock
        self.veto_sink = LoggingVetoSink() if veto_sink is None else veto_sink

    def _checked(
        self,
        verdict: Verdict,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
    ) -> Verdict:
        """R-02/R-03: an altered verdict cannot become passing audit evidence."""
        checked = Verdict.model_validate(verdict)
        identifiers = tuple(result.rule_id for result in checked.results)
        expected = tuple(f"CRO-{number:02d}" for number in range(1, 14))
        if (
            checked.proposal_id != proposal.proposal_id
            or checked.config_hash != self.cro.config.config_hash
            or not identifiers
            or len(identifiers) != len(set(identifiers))
            or any(identifier not in expected for identifier in identifiers)
        ):
            raise DataIntegrityError("R-02: risk verdict identity or rule evidence is invalid")
        if checked.decision == Decision.APPROVED:
            proposal = TradeProposal.model_validate(proposal)
            if (
                proposal.intent in {Intent.ENTRY, Intent.ADD}
                and checked.recommended_state != SystemState.RUNNING
            ):
                raise DataIntegrityError(
                    "CRO-01: approved entry cannot recommend a restricted state"
                )
            required = expected if proposal.intent in {Intent.ENTRY, Intent.ADD} else expected[:2]
            if identifiers != required or checked.snapshot_hash != snapshot_hash(snapshot):
                raise DataIntegrityError("R-02: approval lacks complete bound rule evidence")
            blocking = checked.results[:12] if len(required) == 13 else checked.results
            if any(not result.passed or result.severity != Severity.BLOCK for result in blocking):
                raise DataIntegrityError("R-02: approval has altered blocking-rule evidence")
            if len(required) == 13:
                earnings = checked.results[-1]
                unknown_warning = (
                    market is not None
                    and market.next_earnings_date is None
                    and not earnings.passed
                    and earnings.severity == Severity.WARN
                )
                if not unknown_warning and (
                    not earnings.passed or earnings.severity != Severity.BLOCK
                ):
                    raise DataIntegrityError("CRO-13: approval has invalid earnings evidence")
        elif not any(
            not result.passed and result.severity == Severity.BLOCK for result in checked.results
        ):
            raise DataIntegrityError("R-02: veto lacks a blocking reason")
        # An auditable fail-closed verdict may accompany deliberately invalid
        # snapshot input. HALTED is already maximally restrictive in that case.
        if checked.recommended_state != SystemState.HALTED:
            needed = financial_state(
                snapshot.equity,
                snapshot.high_water_mark,
                snapshot.day_start_equity,
                self.cro.config,
            )
            if needed == SystemState.HALTED or (
                needed == SystemState.REDUCE_ONLY
                and checked.recommended_state == SystemState.RUNNING
            ):
                raise DataIntegrityError(
                    "CRO-09/CRO-10: verdict concealed required state escalation"
                )
        return checked

    def evaluate(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
        *,
        deployable: DeployableCapital | None = None,
    ) -> Verdict:
        """R-02/CRO-01/CRO-09/CRO-10: faults halt, persist, and surface typed errors."""
        try:
            now = ensure_utc(self.clock.now())
            self.state.ledger.verify_chain()
            initial = self.state.current()
            verdict = self._checked(
                self.cro.evaluate(proposal, snapshot, market, initial, now, deployable=deployable),
                proposal,
                snapshot,
                market,
            )
            current = self.state.current()
            if current != initial:
                verdict = self._checked(
                    self.cro.evaluate(
                        proposal, snapshot, market, current, now, deployable=deployable
                    ),
                    proposal,
                    snapshot,
                    market,
                )
            if verdict.evaluated_at != now:
                raise DataIntegrityError("R-05: verdict time does not match injected clock")
            latched = self.state.escalate(
                verdict.recommended_state, "CRO-09/CRO-10 risk evaluation"
            )
            if latched != current and latched != verdict.recommended_state:
                verdict = self._checked(
                    self.cro.evaluate(
                        proposal, snapshot, market, latched, now, deployable=deployable
                    ),
                    proposal,
                    snapshot,
                    market,
                )
                if verdict.evaluated_at != now:
                    raise DataIntegrityError("R-05: rechecked verdict time differs from clock")
                self.state.escalate(
                    verdict.recommended_state, "CRO-09/CRO-10 concurrent state recheck"
                )
            for result in verdict.results:
                if not result.passed and result.severity == Severity.BLOCK:
                    self.veto_sink.record(result.rule_id, verdict.proposal_id)
            return verdict
        except Exception as exc:
            try:
                logging.getLogger(__name__).error(
                    "risk_boundary_fault error_type=%s", type(exc).__name__
                )
            except Exception as log_error:
                exc = DataIntegrityError(
                    f"R-02: risk fault audit unavailable ({type(log_error).__name__})"
                )
            try:
                self.state.halt_for_error(exc)
            except Exception as halt_error:
                raise DataIntegrityError(
                    "R-02: risk boundary failed; HALT persistence unavailable"
                ) from halt_error
            raise DataIntegrityError("R-02: risk boundary failed and latched HALTED") from exc
````````
<!-- END FILE backend/risk/boundary.py -->

### backend/tests/test_domain.py

<!-- BEGIN FILE backend/tests/test_domain.py -->
````````python
"""R-01/R-02/R-03/R-04/R-05/CRO-05/CRO-12 immutable-contract tests."""

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from shutil import copyfile
from typing import cast
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    AssetClass,
    BlackoutWindow,
    CapitalStatus,
    Decision,
    DeployableCapital,
    FlowSignal,
    Instrument,
    Intent,
    MarketContext,
    MarketStatus,
    OpenOrder,
    Playbook,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    ProviderResult,
    ProviderStatus,
    ResearchThesis,
    RuleResult,
    ScannerHit,
    SentimentClassification,
    SentimentSignal,
    SetupCandidate,
    SetupCriterion,
    Severity,
    Side,
    TradeProposal,
    Verdict,
    snapshot_hash,
)

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
PROPOSAL_ID = UUID("10000000-0000-0000-0000-000000000001")
SIGNAL_ID = UUID("10000000-0000-0000-0000-000000000002")


def proposal(**changes: object) -> TradeProposal:
    data: dict[str, object] = {
        "proposal_id": PROPOSAL_ID,
        "signal_id": SIGNAL_ID,
        "account_id": "paper",
        "symbol": "AAPL",
        "side": Side.BUY,
        "intent": Intent.ENTRY,
        "qty": 1,
        "limit_price": Decimal("100"),
        "stop_price": Decimal("95"),
        "source": ProposalSource.SIGNAL,
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=1),
    }
    data.update(changes)
    return TradeProposal.model_validate(data)


def instrument(symbol: str = "AAPL", **changes: object) -> Instrument:
    data: dict[str, object] = {
        "symbol": symbol,
        "asset_class": AssetClass.STOCK,
        "gics_sector": "Information Technology",
        "themes": ("TECH",),
        "is_leveraged": False,
        "is_inverse": False,
        "tradable": True,
    }
    data.update(changes)
    return Instrument.model_validate(data)


def snapshot(**changes: object) -> PortfolioSnapshot:
    data: dict[str, object] = {
        "account_id": "paper",
        "account_type": AccountType.CASH,
        "as_of": NOW,
        "equity": Decimal("10000"),
        "cash": Decimal("9900"),
        "settled_cash": Decimal("9900"),
        "positions": {"AAPL": Position(qty=1, avg_cost=Decimal("90"), last_price=Decimal("100"))},
        "open_orders": (),
        "high_water_mark": Decimal("10000"),
        "day_start_equity": Decimal("10000"),
    }
    data.update(changes)
    return PortfolioSnapshot.model_validate(data)


@pytest.mark.parametrize("bad", [True, 1.5, "1", 0, -1])
def test_R_01_whole_positive_shares_require_strict_integer(bad: object) -> None:
    with pytest.raises(ValidationError):
        proposal(qty=bad)


@pytest.mark.parametrize(
    "bad",
    [True, 100.0, 100, "100.00", Decimal("NaN"), "NaN", Decimal("Infinity"), Decimal("99.999999")],
)
def test_R_02_R_04_R_13_prices_never_coerce_non_decimal_nan_or_subcent_units(bad: object) -> None:
    with pytest.raises(ValidationError):
        proposal(limit_price=bad)


@pytest.mark.parametrize(
    "stop", [None, Decimal("100"), Decimal("100.01"), Decimal("0"), Decimal("-1")]
)
def test_R_01_entry_stop_must_be_positive_and_strictly_below_limit(stop: object) -> None:
    with pytest.raises(ValidationError):
        proposal(stop_price=stop)
    assert proposal(stop_price=Decimal("99.99")).stop_price == Decimal("99.99")


@pytest.mark.parametrize(
    "side,intent",
    [
        (Side.SELL, Intent.ENTRY),
        (Side.SELL, Intent.ADD),
        (Side.BUY, Intent.REDUCE),
        (Side.BUY, Intent.EXIT),
    ],
)
def test_R_01_side_and_intent_cannot_create_short_entry(side: Side, intent: Intent) -> None:
    with pytest.raises(ValidationError):
        proposal(side=side, intent=intent)


def test_R_01_R_09_valid_exit_does_not_require_stop() -> None:
    exit_proposal = proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None)
    assert exit_proposal.qty == 1
    assert exit_proposal.stop_price is None


def test_R_02_signal_is_required_and_unexpected_order_types_are_forbidden() -> None:
    data = proposal().model_dump()
    del data["signal_id"]
    with pytest.raises(ValidationError):
        TradeProposal.model_validate(data)
    with pytest.raises(ValidationError):
        proposal(order_type="MARKET")
    with pytest.raises(ValidationError):
        proposal(account_id=" ")


def test_R_03_snapshot_is_detached_and_deeply_immutable() -> None:
    positions = {"AAPL": Position(qty=1, avg_cost=Decimal("90"), last_price=Decimal("100"))}
    state = snapshot(positions=positions)
    positions.clear()
    assert state.positions["AAPL"].value == Decimal("100")
    with pytest.raises(TypeError):
        cast(dict[str, Position], state.positions)["AAPL"] = Position(
            qty=2, avg_cost=Decimal("90"), last_price=Decimal("100")
        )
    with pytest.raises(ValidationError):
        state.positions["AAPL"].qty = 99
    with pytest.raises(ValidationError):
        state.cash = Decimal("0")
    assert state.model_dump(mode="json")["positions"]["AAPL"]["qty"] == 1


def test_R_03_R_04_snapshot_hash_is_canonical_exact_and_change_sensitive() -> None:
    first = snapshot()
    scaled = snapshot(equity=Decimal("10000.00"), cash=Decimal("9900.000000"))
    assert snapshot_hash(first) == snapshot_hash(scaled)
    assert snapshot_hash(first) != snapshot_hash(snapshot(cash=Decimal("9899.99")))
    assert len(snapshot_hash(first)) == 64


def test_R_02_CRO_09_negative_equity_is_preserved_for_halt_evaluation() -> None:
    assert snapshot(equity=Decimal("-1")).equity == Decimal("-1")
    assert snapshot(equity=Decimal("0")).equity == Decimal("0")


def test_R_05_aware_instants_are_normalized_and_naive_instants_fail() -> None:
    chicago = timezone(timedelta(hours=-5))
    assert proposal(created_at=NOW.astimezone(chicago)).created_at == NOW
    assert proposal().created_at.tzinfo is UTC
    with pytest.raises(ValidationError):
        proposal(created_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        proposal(created_at="2026-10-02T16:00:00Z")


@pytest.mark.parametrize(
    "status", [CapitalStatus.BUFFER_BREACH, CapitalStatus.UNAVAILABLE, CapitalStatus.STALE]
)
def test_CRO_12_non_ok_funding_cannot_advertise_deployable_cash(status: CapitalStatus) -> None:
    with pytest.raises(ValidationError):
        DeployableCapital(
            checking_used=Decimal("2000"),
            buffer=Decimal("1500"),
            reserved=Decimal("0"),
            deployable=Decimal("500"),
            status=status,
        )
    assert (
        DeployableCapital(
            checking_used=Decimal("2000"),
            buffer=Decimal("1500"),
            reserved=Decimal("0"),
            deployable=Decimal("0"),
            status=status,
        ).deployable
        == 0
    )


def test_CRO_12_ok_funding_requires_exact_buffer_reserve_equation() -> None:
    assert (
        DeployableCapital(
            checking_used=Decimal("2000"),
            buffer=Decimal("1500"),
            reserved=Decimal("100"),
            deployable=Decimal("400"),
            status=CapitalStatus.OK,
        ).deployable
        == 400
    )
    with pytest.raises(ValidationError):
        DeployableCapital(
            checking_used=Decimal("2000"),
            buffer=Decimal("1500"),
            reserved=Decimal("100"),
            deployable=Decimal("400.01"),
            status=CapitalStatus.OK,
        )
    with pytest.raises(ValidationError):
        DeployableCapital(
            checking_used=Decimal("1499.99"),
            buffer=Decimal("1500"),
            reserved=Decimal("0"),
            deployable=Decimal("0"),
            status=CapitalStatus.OK,
        )


def test_R_02_CMP_06_all_current_account_flags_are_required() -> None:
    flags = AccountFlags(
        trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
    )
    assert not flags.blocked
    assert flags.model_copy(update={"account_blocked": True}).blocked
    assert flags.model_copy(update={"status": "ACCOUNT_UPDATED"}).blocked
    with pytest.raises(ValidationError):
        AccountFlags.model_validate({"status": "ACTIVE"})


def test_R_02_verdict_cannot_claim_approval_with_failed_block_or_no_evidence() -> None:
    data: dict[str, object] = {
        "proposal_id": PROPOSAL_ID,
        "decision": Decision.APPROVED,
        "results": (),
        "config_hash": "a" * 64,
        "snapshot_hash": "b" * 64,
        "evaluated_at": NOW,
    }
    with pytest.raises(ValidationError):
        Verdict.model_validate(data)
    failure = RuleResult(
        rule_id="CRO-01",
        passed=False,
        severity=Severity.BLOCK,
        observed="HALTED",
        limit="RUNNING",
        message="state blocks entry",
    )
    data["results"] = (failure,)
    with pytest.raises(ValidationError):
        Verdict.model_validate(data)
    data["decision"] = Decision.VETOED
    assert Verdict.model_validate(data).decision == Decision.VETOED


def test_R_02_DAT_02_market_missing_nan_and_zero_prices_fail_closed() -> None:
    for value in (None, Decimal("NaN"), Decimal("0"), Decimal("-1")):
        with pytest.raises(ValidationError):
            MarketContext.model_validate(
                {
                    "last_price": value,
                    "last_price_ts": NOW,
                    "adv20_usd": Decimal("10000"),
                    "status": MarketStatus.OK,
                }
            )


def test_CRO_05_registry_lookthrough_and_declared_sector_fallback() -> None:
    etf = instrument("XLK", asset_class=AssetClass.SECTOR_ETF)
    registry = InstrumentRegistry([instrument(), etf])
    assert registry.sector_weights("XLK") == {"Information Technology": Decimal("1")}
    supplied = {"XLK": {"Information Technology": Decimal("0.9"), "Financials": Decimal("0.1")}}
    weighted = InstrumentRegistry([instrument(), etf], supplied)
    supplied["XLK"].clear()
    assert weighted.sector_weights("XLK")["Financials"] == Decimal("0.1")
    with pytest.raises(TypeError):
        cast(dict[str, Decimal], weighted.sector_weights("XLK"))["Financials"] = Decimal("1")
    with pytest.raises(FrozenInstanceError):
        weighted.blackout_windows = ()  # type: ignore[misc]  # Intentional mutation attempt.


@pytest.mark.parametrize(
    "weight", [Decimal("0.99"), Decimal("1.01"), Decimal("0"), Decimal("-1"), Decimal("NaN"), 1.0]
)
def test_CRO_05_invalid_or_incomplete_etf_weights_fail_closed(weight: object) -> None:
    etf = instrument("XLK", asset_class=AssetClass.SECTOR_ETF)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([etf], {"XLK": {"Information Technology": cast(Decimal, weight)}})


def test_R_02_CMP_07_registry_unknown_duplicate_and_empty_names_fail_closed() -> None:
    registry = InstrumentRegistry([instrument()])
    with pytest.raises(DataIntegrityError):
        registry.get("UNKNOWN")
    with pytest.raises(DataIntegrityError):
        registry.identical_group("UNKNOWN")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([])
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument(), instrument()])
    with pytest.raises(ValidationError):
        instrument("aapl")
    with pytest.raises(ValidationError):
        instrument(themes=("TECH", "TECH"))
    with pytest.raises(ValidationError):
        instrument(themes=(" ",))


def test_CMP_01_identical_group_is_explicit_and_immutable() -> None:
    registry = InstrumentRegistry(
        [instrument(), instrument("MSFT"), instrument("NVDA")],
        identical_groups={"EXPLICIT_OPERATOR_GROUP": ["AAPL", "MSFT"]},
    )
    assert registry.identical_group("AAPL") == frozenset({"AAPL", "MSFT"})
    assert registry.identical_group("NVDA") == frozenset({"NVDA"})
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(
            [instrument(), instrument("MSFT")], identical_groups={"GROUP": ["AAPL", "UNKNOWN"]}
        )


def test_CRO_11_blackout_requires_aware_increasing_interval_and_known_symbol() -> None:
    window = BlackoutWindow(
        start=NOW, end=NOW + timedelta(hours=1), reason="operator event", symbol="AAPL"
    )
    assert InstrumentRegistry([instrument()], blackout_windows=[window]).blackout_windows == (
        window,
    )
    with pytest.raises(ValidationError):
        BlackoutWindow(start=NOW, end=NOW, reason="event")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(
            [instrument()], blackout_windows=[window.model_copy(update={"symbol": "UNKNOWN"})]
        )


def test_R_02_csv_sample_loads_exact_schema_and_leveraged_names_are_restricted() -> None:
    registry = InstrumentRegistry.from_csv(Path(__file__).resolve().parents[2] / "config")
    assert len(registry.symbols) == 10
    assert registry.get("TQQQ").is_leveraged and not registry.get("TQQQ").tradable
    assert registry.get("SH").is_inverse and not registry.get("SH").tradable
    assert sum(registry.sector_weights("SPY").values(), Decimal("0")) == Decimal("1")
    assert registry.blackout_windows == ()


def test_R_02_policy_csv_missing_file_or_surplus_column_fails_typed(tmp_path: Path) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.from_csv(tmp_path)
    (tmp_path / "instruments.csv").write_text("symbol,unexpected\nAAPL,true\n", encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.from_csv(tmp_path)


def test_R_03_snapshot_symbol_order_does_not_change_hash() -> None:
    aapl = Position(qty=1, avg_cost=Decimal("90"), last_price=Decimal("100"))
    msft = Position(qty=2, avg_cost=Decimal("190"), last_price=Decimal("200"))
    positions: Mapping[str, Position] = {"AAPL": aapl, "MSFT": msft}
    reverse = {"MSFT": msft, "AAPL": aapl}
    assert snapshot_hash(snapshot(positions=positions)) == snapshot_hash(
        snapshot(positions=reverse)
    )


@pytest.mark.parametrize("field", ["signal_id", "expires_at"])
def test_R_02_R_14_proposal_signal_and_expiry_are_required(field: str) -> None:
    data = proposal().model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        TradeProposal.model_validate(data)


@pytest.mark.parametrize("expiry", [NOW, NOW - timedelta(microseconds=1), NOW.replace(tzinfo=None)])
def test_R_05_R_14_expiry_must_be_aware_and_after_creation(expiry: datetime) -> None:
    with pytest.raises(ValidationError):
        proposal(expires_at=expiry)
    assert proposal(expires_at=NOW + timedelta(microseconds=1)).expires_at > NOW


@pytest.mark.parametrize(
    "target", [Decimal("0"), Decimal("100"), Decimal("99.99"), Decimal("100.001")]
)
def test_R_01_R_13_entry_target_is_optional_positive_cent_price_above_limit(
    target: Decimal,
) -> None:
    with pytest.raises(ValidationError):
        proposal(target_price=target)
    assert proposal(target_price=None).target_price is None
    assert proposal(target_price=Decimal("100.01")).target_price == Decimal("100.01")


@pytest.mark.parametrize("field", ["limit_price", "stop_price", "target_price"])
@pytest.mark.parametrize("bad", [Decimal("99.999999"), Decimal("99.999"), "99.99", 99, 99.99, True])
def test_R_13_every_proposal_price_boundary_rejects_non_cent_or_non_decimal(
    field: str, bad: object
) -> None:
    with pytest.raises(ValidationError):
        proposal(**{field: bad})


@pytest.mark.parametrize("field", ["avg_cost", "last_price"])
@pytest.mark.parametrize("bad", [Decimal("99.999"), "99.99", 99.99, 0, Decimal("0")])
def test_R_13_position_prices_are_exact_positive_decimal_cents(field: str, bad: object) -> None:
    data: dict[str, object] = {
        "qty": 1,
        "avg_cost": Decimal("99.99"),
        "last_price": Decimal("100.00"),
    }
    data[field] = bad
    with pytest.raises(ValidationError):
        Position.model_validate(data)


@pytest.mark.parametrize("bad", [Decimal("100.001"), "100.00", 100.0])
def test_R_13_market_and_pending_prices_enforce_same_boundary(bad: object) -> None:
    with pytest.raises(ValidationError):
        OpenOrder.model_validate({"symbol": "AAPL", "side": "BUY", "qty": 1, "limit_price": bad})
    with pytest.raises(ValidationError):
        MarketContext.model_validate(
            {"last_price": bad, "last_price_ts": NOW, "adv20_usd": Decimal("10000"), "status": "OK"}
        )


def test_CRO_04_open_order_optional_stop_preserves_conservative_batch_evidence() -> None:
    data = {"symbol": "AAPL", "side": "BUY", "qty": 1, "limit_price": Decimal("100.00")}
    assert OpenOrder.model_validate(data).stop_price is None
    assert OpenOrder.model_validate({**data, "stop_price": Decimal("99.99")}).stop_price == Decimal(
        "99.99"
    )
    for stop in (Decimal("100.00"), Decimal("100.01"), Decimal("99.999")):
        with pytest.raises(ValidationError):
            OpenOrder.model_validate({**data, "stop_price": stop})


def test_CRO_13_earnings_dates_are_explicit_dates_not_coerced_strings_or_timestamps() -> None:
    data = {
        "last_price": Decimal("100"),
        "last_price_ts": NOW,
        "adv20_usd": Decimal("10000"),
        "status": "OK",
    }
    assert MarketContext.model_validate(data).next_earnings_date is None
    assert MarketContext.model_validate(
        {**data, "next_earnings_date": date(2026, 10, 5)}
    ).next_earnings_date == date(2026, 10, 5)
    for earnings in (NOW, "2026-10-05", 123, True):
        with pytest.raises(ValidationError):
            MarketContext.model_validate({**data, "next_earnings_date": earnings})


@pytest.mark.parametrize(
    "change",
    [
        {"qty": True},
        {"limit_price": Decimal("100.001")},
        {"expires_at": NOW},
        {"target_price": Decimal("99")},
        {"side": Side.SELL},
    ],
)
def test_R_02_unvalidated_copy_proposals_fail_boundary_revalidation(
    change: dict[str, object],
) -> None:
    forged = proposal().model_copy(update=change)
    with pytest.raises(ValidationError):
        TradeProposal.model_validate(forged)


def test_R_02_constructed_and_nested_forged_models_are_revalidated() -> None:
    incomplete = TradeProposal.model_construct(proposal_id=PROPOSAL_ID)
    with pytest.raises(ValidationError):
        TradeProposal.model_validate(incomplete)
    bad_position = Position.model_construct(
        qty=True, avg_cost=Decimal("100"), last_price=Decimal("100")
    )
    forged = snapshot().model_copy(update={"positions": {"AAPL": bad_position}})
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate(forged)
    with pytest.raises(DataIntegrityError):
        snapshot_hash(forged)
    pending = OpenOrder.model_construct(
        symbol="AAPL", side=Side.BUY, qty=1.5, limit_price=Decimal("100")
    )
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate(snapshot().model_copy(update={"open_orders": (pending,)}))
    with pytest.raises(ValidationError):
        MarketContext.model_validate(
            MarketContext.model_construct(
                last_price=Decimal("100.001"),
                last_price_ts=NOW,
                adv20_usd=Decimal("10000"),
                status=MarketStatus.OK,
            )
        )


def test_R_03_revalidation_detaches_forged_mutable_positions() -> None:
    source = {"AAPL": Position(qty=1, avg_cost=Decimal("90"), last_price=Decimal("100"))}
    copied = snapshot().model_copy(update={"positions": source})
    checked = PortfolioSnapshot.model_validate(copied)
    source.clear()
    assert checked.positions["AAPL"].qty == 1
    with pytest.raises(TypeError):
        cast(dict[str, Position], checked.positions)["AAPL"] = Position(
            qty=2, avg_cost=Decimal("90"), last_price=Decimal("100")
        )


def test_R_04_position_notional_and_etf_sums_ignore_low_ambient_precision() -> None:
    with localcontext() as context:
        context.prec = 2
        position = Position(qty=12345, avg_cost=Decimal("123.45"), last_price=Decimal("123.45"))
        assert position.value == Decimal("1523990.25")
        registry = InstrumentRegistry(
            [instrument("XLK", asset_class=AssetClass.SECTOR_ETF)],
            {
                "XLK": {
                    "Information Technology": Decimal("0.999999"),
                    "Financials": Decimal("0.000001"),
                }
            },
        )
        assert registry.sector_weights("XLK")["Information Technology"] == Decimal("0.999999")
        with pytest.raises(DataIntegrityError):
            InstrumentRegistry(
                [instrument("XLK", asset_class=AssetClass.SECTOR_ETF)],
                {
                    "XLK": {
                        "Information Technology": Decimal("0.335"),
                        "Financials": Decimal("0.664"),
                    }
                },
            )
        funding = DeployableCapital(
            checking_used=Decimal("12345.67"),
            buffer=Decimal("1500.00"),
            reserved=Decimal("45.67"),
            deployable=Decimal("10800.00"),
            status=CapitalStatus.OK,
        )
        assert funding.deployable == Decimal("10800.00")


@pytest.mark.parametrize(
    "change",
    [
        {"is_leveraged": "false"},
        {"tradable": 1},
        {"asset_class": "UNKNOWN"},
        {"themes": (" ",)},
        {"symbol": "aapl"},
    ],
)
def test_R_02_registry_revalidates_forged_instrument_metadata(change: dict[str, object]) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument().model_copy(update=change)])


def test_R_02_CRO_11_registry_revalidates_forged_blackout_windows() -> None:
    window = BlackoutWindow(start=NOW, end=NOW + timedelta(hours=1), reason="event")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(
            [instrument()], blackout_windows=[window.model_copy(update={"end": NOW})]
        )


@given(st.integers(min_value=1, max_value=1_000_000))
def test_R_13_price_roundtrip_is_cent_quantized_and_exact(cents: int) -> None:
    value = Decimal(cents) / Decimal("100")
    validated = Position(qty=1, avg_cost=value, last_price=value)
    assert validated.last_price == value
    assert validated.last_price.as_tuple().exponent == -2


@pytest.mark.parametrize(
    "score,expected",
    [
        (Decimal("-5.01"), Decimal("-5")),
        (Decimal("-5"), Decimal("-5")),
        (Decimal("0"), Decimal("0")),
        (Decimal("5"), Decimal("5")),
        (Decimal("5.01"), Decimal("5")),
    ],
)
def test_R_11_sentiment_numeric_clamp_is_advisory_and_has_no_trade_fields(
    score: Decimal, expected: Decimal
) -> None:
    signal = SentimentSignal(
        score=score,
        classification=SentimentClassification.CONFIRMING,
        evidence_headline_ids=("headline-1",),
        summary="source context",
    )
    assert signal.score == expected
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate({**signal.model_dump(), "qty": 100})
    with pytest.raises(ValidationError):
        ResearchThesis.model_validate(
            {"narrative": "context", "evidence_headline_ids": (), "limit_price": Decimal("100")}
        )


@pytest.mark.parametrize("score", [Decimal("NaN"), Decimal("Infinity"), 4.0, True])
def test_R_11_sentiment_invalid_numerics_are_discardable_validation_errors(score: object) -> None:
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate(
            {
                "score": score,
                "classification": "CONFIRMING",
                "evidence_headline_ids": ("headline-1",),
                "summary": "context",
            }
        )


def test_R_11_cited_non_neutral_sentiment_requires_evidence_and_unique_ids() -> None:
    data = {
        "score": Decimal("0"),
        "classification": "NOISE",
        "evidence_headline_ids": (),
        "summary": "insufficient evidence",
    }
    assert SentimentSignal.model_validate(data).score == 0
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate({**data, "score": Decimal("1")})
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate({**data, "classification": "CONFIRMING"})
    with pytest.raises(ValidationError):
        SentimentSignal.model_validate({**data, "evidence_headline_ids": ("h-1", "h-1")})
    with pytest.raises(ValidationError):
        ResearchThesis(narrative="context", evidence_headline_ids=("h-1", "h-1"))


@pytest.mark.parametrize("status", [ProviderStatus.UNAVAILABLE, ProviderStatus.ERROR])
def test_R_02_unavailable_provider_and_flow_results_never_carry_positive_evidence(
    status: ProviderStatus,
) -> None:
    assert (
        ProviderResult[AccountFlags](status=status, payload=None, reason="not available").payload
        is None
    )
    assert FlowSignal(status=status).summary is None
    flags = AccountFlags(
        trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
    )
    with pytest.raises(ValidationError):
        ProviderResult[AccountFlags](status=status, payload=flags, reason="bad inferred data")
    with pytest.raises(ValidationError):
        FlowSignal(status=status, summary="buying signal", evidence_ids=("fake",))


def test_R_02_successful_provider_and_flow_results_require_explicit_evidence() -> None:
    flags = AccountFlags(
        trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
    )
    assert (
        ProviderResult[AccountFlags](
            status=ProviderStatus.OK, payload=flags, reason="recorded data"
        ).payload
        == flags
    )
    assert (
        FlowSignal(
            status=ProviderStatus.OK, summary="large print", evidence_ids=("print-1",)
        ).status
        == ProviderStatus.OK
    )
    with pytest.raises(ValidationError):
        ProviderResult[AccountFlags](status=ProviderStatus.OK, payload=None, reason="missing")
    with pytest.raises(ValidationError):
        FlowSignal(status=ProviderStatus.OK)
    with pytest.raises(ValidationError):
        FlowSignal(status=ProviderStatus.OK, summary="context", evidence_ids=("print-1", "print-1"))


def test_R_11_scanner_and_setup_outputs_keep_levels_and_scores_deterministic() -> None:
    hit = ScannerHit(
        symbol="AAPL",
        as_of=NOW,
        last_price=Decimal("100"),
        rvol=Decimal("1.5"),
        rsi=Decimal("50"),
        reason="completed bars",
    )
    assert hit.last_price == Decimal("100.00")
    criterion = SetupCriterion(name="breakout", points=Decimal("7"), reason="recorded trigger")
    data = {
        "symbol": "AAPL",
        "playbook": Playbook.BASE_BREAKOUT,
        "score": Decimal("7"),
        "criteria": (criterion,),
        "entry_price": Decimal("100"),
        "stop_price": Decimal("95"),
        "target_price": Decimal("110"),
        "qty": 1,
        "as_of": NOW,
    }
    assert SetupCandidate.model_validate(data).score == Decimal("7")
    for change in (
        {"score": Decimal("7.01")},
        {"criteria": (criterion, criterion)},
        {"stop_price": Decimal("100")},
        {"qty": True},
    ):
        with pytest.raises(ValidationError):
            SetupCandidate.model_validate({**data, **change})
    with pytest.raises(ValidationError):
        ScannerHit.model_validate({**hit.model_dump(), "rsi": Decimal("100.01")})


def test_CRO_09_CRO_10_verdict_state_recommendation_is_explicit_pure_data() -> None:
    result = RuleResult(
        rule_id="CRO-09",
        passed=False,
        severity=Severity.BLOCK,
        observed="drawdown",
        limit="halt",
        message="managed equity requires halt",
    )
    verdict = Verdict(
        proposal_id=PROPOSAL_ID,
        decision=Decision.VETOED,
        results=(result,),
        config_hash="a" * 64,
        snapshot_hash="b" * 64,
        evaluated_at=NOW,
        recommended_state=SystemState.HALTED,
    )
    assert verdict.recommended_state == SystemState.HALTED


@pytest.mark.parametrize("weights", [{"UNKNOWN": Decimal("1")}, {"Financials": Decimal("0")}, {}])
def test_CRO_05_etf_sector_map_rejects_unknown_zero_or_empty_exposure(
    weights: dict[str, Decimal],
) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument("XLK", asset_class=AssetClass.SECTOR_ETF)], {"XLK": weights})
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument()], {"UNKNOWN": {"Information Technology": Decimal("1")}})
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument()], {"AAPL": {"Information Technology": Decimal("1")}})


def test_CRO_05_unknown_declared_sector_is_preserved_as_full_exposure_to_block() -> None:
    registry = InstrumentRegistry(
        [instrument("SPY", asset_class=AssetClass.BROAD_ETF, gics_sector="UNKNOWN")]
    )
    assert registry.sector_weights("SPY") == {"UNKNOWN": Decimal("1")}


@pytest.mark.parametrize("group", [[], ["AAPL"], ["AAPL", "AAPL"], ["AAPL", "UNKNOWN"]])
def test_CMP_01_registry_identical_groups_need_known_unique_multiple_members(
    group: list[str],
) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument()], identical_groups={"GROUP": group})


def test_CMP_01_registry_identical_groups_cannot_overlap_or_use_blank_names() -> None:
    names = [instrument(), instrument("MSFT"), instrument("NVDA")]
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(
            names, identical_groups={"FIRST": ("AAPL", "MSFT"), "SECOND": ("MSFT", "NVDA")}
        )
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry(names, identical_groups={" ": ("AAPL", "MSFT")})


@pytest.mark.parametrize(
    "filename,content",
    [
        (
            "instruments.csv",
            "symbol,asset_class,gics_sector,themes,is_leveraged,is_inverse,tradable\nAAPL,STOCK,Information Technology,,false,false\n",
        ),
        (
            "instruments.csv",
            "symbol,asset_class,gics_sector,themes,is_leveraged,is_inverse,tradable\nAAPL,STOCK,Information Technology,,false,FALSE,true\n",
        ),
        (
            "instruments.csv",
            "symbol,asset_class,gics_sector,themes,is_leveraged,is_inverse,tradable\nAAPL,OPTIONS,Information Technology,,false,false,true\n",
        ),
        (
            "etf_sector_weights.csv",
            "symbol,gics_sector,weight\nSPY,Information Technology,0.5\nSPY,Information Technology,0.5\n",
        ),
        (
            "blackout_windows.csv",
            "symbol,start,end,reason\nAAPL,2026-10-02T16:00:00,2026-10-02T17:00:00,naive\n",
        ),
    ],
)
def test_R_02_CRO_05_policy_csv_corruption_is_typed_and_never_permissive(
    tmp_path: Path, filename: str, content: str
) -> None:
    source = Path(__file__).resolve().parents[2] / "config"
    for name in (
        "instruments.csv",
        "etf_sector_weights.csv",
        "substantially_identical.csv",
        "blackout_windows.csv",
    ):
        copyfile(source / name, tmp_path / name)
    (tmp_path / filename).write_text(content, encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.from_csv(tmp_path)


@pytest.mark.parametrize("bad", [None, True, "not an Instrument"])
def test_R_02_registry_non_model_inputs_raise_typed_integrity_error(bad: object) -> None:
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([cast(Instrument, bad)])
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry([instrument()], blackout_windows=[cast(BlackoutWindow, bad)])


def test_R_02_R_03_registry_validated_copy_detaches_mutable_internal_aliases() -> None:
    names = {"AAPL": instrument(), "MSFT": instrument("MSFT")}
    members = frozenset({"AAPL", "MSFT"})
    groups = {"AAPL": members, "MSFT": members}
    original = InstrumentRegistry(names.values())
    object.__setattr__(original, "_instruments", names)
    object.__setattr__(original, "_groups", groups)
    checked = InstrumentRegistry.validated_copy(original)
    names.clear()
    groups.clear()
    assert checked.symbols == frozenset({"AAPL", "MSFT"})
    assert checked.identical_group("AAPL") == members


@pytest.mark.parametrize(
    "bad",
    [
        {"AAPL": instrument().model_copy(update={"is_leveraged": "false"})},
        {"MSFT": instrument()},
        {},
    ],
)
def test_R_02_registry_validated_copy_rejects_forged_internal_instruments(
    bad: dict[str, Instrument],
) -> None:
    original = InstrumentRegistry([instrument()])
    object.__setattr__(original, "_instruments", bad)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(original)


@pytest.mark.parametrize(
    "groups",
    [
        {"AAPL": frozenset({"AAPL", "MSFT"})},
        {"AAPL": frozenset({"MSFT", "NVDA"})},
        {"AAPL": {"AAPL", "MSFT"}},
    ],
)
def test_R_02_CMP_01_registry_validated_copy_rejects_forged_asymmetric_groups(
    groups: object,
) -> None:
    original = InstrumentRegistry([instrument(), instrument("MSFT"), instrument("NVDA")])
    object.__setattr__(original, "_groups", groups)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(original)


def test_R_02_registry_validated_copy_revalidates_etf_weights_and_missing_storage() -> None:
    original = InstrumentRegistry([instrument("XLK", asset_class=AssetClass.SECTOR_ETF)])
    object.__setattr__(original, "_weights", {"XLK": {"Information Technology": Decimal("0.999")}})
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(original)
    empty = object.__new__(InstrumentRegistry)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(empty)
    object.__setattr__(original, "_weights", None)
    with pytest.raises(DataIntegrityError):
        InstrumentRegistry.validated_copy(original)
````````
<!-- END FILE backend/tests/test_domain.py -->

### backend/tests/test_risk_cro.py

<!-- BEGIN FILE backend/tests/test_risk_cro.py -->
````````python
"""CRO-01..13/R-01..05/R-09/R-13: exact boundaries, exits and sizing properties."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountType,
    AssetClass,
    BlackoutWindow,
    CapitalStatus,
    Decision,
    DeployableCapital,
    Instrument,
    Intent,
    MarketContext,
    MarketStatus,
    OpenOrder,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
)
from backend.risk.risk_cro import ChiefRiskOfficer


@pytest.fixture(scope="module")
def risk_calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


def _instrument(symbol: str, **changes: Any) -> Instrument:
    fields: dict[str, Any] = {
        "symbol": symbol,
        "asset_class": AssetClass.STOCK,
        "gics_sector": "Information Technology",
        "themes": (),
        "is_leveraged": False,
        "is_inverse": False,
        "tradable": True,
    }
    fields.update(changes)
    return Instrument(**fields)


def _registry(*additional: Instrument, **kwargs: Any) -> InstrumentRegistry:
    return InstrumentRegistry(
        (_instrument("AAPL"), _instrument("MSFT"), _instrument("IBM"), *additional), **kwargs
    )


def _proposal(clock: FrozenClock, **changes: Any) -> TradeProposal:
    fields: dict[str, Any] = {
        "proposal_id": UUID(int=1),
        "signal_id": UUID(int=2),
        "account_id": "paper-account",
        "symbol": "AAPL",
        "side": Side.BUY,
        "intent": Intent.ENTRY,
        "qty": 1,
        "limit_price": Decimal("100"),
        "stop_price": Decimal("95"),
        "source": ProposalSource.SIGNAL,
        "created_at": clock.now(),
        "expires_at": clock.now() + timedelta(days=1),
    }
    fields.update(changes)
    return TradeProposal(**fields)


def _snapshot(clock: FrozenClock, **changes: Any) -> PortfolioSnapshot:
    fields: dict[str, Any] = {
        "account_id": "paper-account",
        "account_type": AccountType.CASH,
        "as_of": clock.now(),
        "equity": Decimal("10000"),
        "cash": Decimal("10000"),
        "settled_cash": Decimal("10000"),
        "positions": {},
        "open_orders": (),
        "high_water_mark": Decimal("10000"),
        "day_start_equity": Decimal("10000"),
    }
    fields.update(changes)
    return PortfolioSnapshot(**fields)


def _market(clock: FrozenClock, **changes: Any) -> MarketContext:
    fields: dict[str, Any] = {
        "last_price": Decimal("100"),
        "last_price_ts": clock.now(),
        "adv20_usd": Decimal("1000000"),
        "status": MarketStatus.OK,
    }
    fields.update(changes)
    return MarketContext(**fields)


def _capital(status: CapitalStatus = CapitalStatus.OK) -> DeployableCapital:
    return DeployableCapital(
        checking_used=Decimal("5000"),
        buffer=Decimal("1500"),
        reserved=Decimal("100"),
        deployable=Decimal("3400") if status == CapitalStatus.OK else Decimal(0),
        status=status,
    )


def _position(qty: int, price: Decimal = Decimal("100")) -> Position:
    return Position(qty=qty, avg_cost=price, last_price=price)


def _rule(
    cro: ChiefRiskOfficer,
    clock: FrozenClock,
    rule_id: str,
    proposal: TradeProposal | None = None,
    snapshot: PortfolioSnapshot | None = None,
    market: MarketContext | None = None,
    **kwargs: Any,
) -> RuleResult:
    verdict = cro.evaluate(
        proposal or _proposal(clock),
        snapshot or _snapshot(clock),
        market or _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
        **kwargs,
    )
    assert len(verdict.results) == 13
    return next(result for result in verdict.results if result.rule_id == rule_id)


def test_CRO_01_to_12_R_03_approval_is_complete_exact_and_deterministic(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    proposal, snapshot, market = _proposal(clock), _snapshot(clock), _market(clock)
    first = cro.evaluate(
        proposal, snapshot, market, SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    assert first.decision == Decision.APPROVED
    assert first == cro.evaluate(
        proposal, snapshot, market, SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    assert [rule.rule_id for rule in first.results] == [
        f"CRO-{number:02d}" for number in range(1, 14)
    ]
    assert all(rule.passed for rule in first.results if rule.severity == Severity.BLOCK)
    assert first.results[-1].severity == Severity.WARN
    assert not first.results[-1].passed


@pytest.mark.parametrize(
    "state,source,intent,allowed",
    [
        (SystemState.RUNNING, ProposalSource.SIGNAL, Intent.ENTRY, True),
        (SystemState.REDUCE_ONLY, ProposalSource.SIGNAL, Intent.ENTRY, False),
        (SystemState.HALTED, ProposalSource.SIGNAL, Intent.ENTRY, False),
        (SystemState.REDUCE_ONLY, ProposalSource.SIGNAL, Intent.EXIT, True),
        (SystemState.HALTED, ProposalSource.SIGNAL, Intent.EXIT, False),
        (SystemState.HALTED, ProposalSource.MANUAL, Intent.REDUCE, True),
        (SystemState.HALTED, ProposalSource.MANUAL, Intent.EXIT, True),
    ],
)
def test_CRO_01_R_09_state_gate_and_manual_escape(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    state: SystemState,
    source: ProposalSource,
    intent: Intent,
    allowed: bool,
) -> None:
    changes: dict[str, Any] = {"intent": intent, "source": source}
    if intent in {Intent.EXIT, Intent.REDUCE}:
        changes.update(side=Side.SELL, stop_price=None)
    proposal = _proposal(clock, **changes)
    snapshot = _snapshot(
        clock, positions={"AAPL": _position(1)} if intent in {Intent.EXIT, Intent.REDUCE} else {}
    )
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    verdict = cro.evaluate(
        proposal, snapshot, _market(clock), state, clock.now(), deployable=_capital()
    )
    assert (verdict.decision == Decision.APPROVED) == allowed
    if not allowed:
        assert [rule.rule_id for rule in verdict.results] == ["CRO-01"]


def test_CRO_02_R_09_exit_ignores_missing_market_unknown_instrument_and_all_other_rules(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    proposal = _proposal(
        clock,
        symbol="UNKNOWN",
        side=Side.SELL,
        intent=Intent.EXIT,
        stop_price=None,
        limit_price=Decimal("1"),
    )
    snapshot = _snapshot(
        clock,
        equity=Decimal("1"),
        cash=Decimal(0),
        positions={"UNKNOWN": _position(1)},
        high_water_mark=Decimal("100000"),
        day_start_equity=Decimal("100000"),
    )
    verdict = cro.evaluate(proposal, snapshot, None, SystemState.RUNNING, clock.now())
    assert verdict.decision == Decision.APPROVED
    assert len(verdict.results) == 2


def test_CRO_02_R_02_entry_missing_market_vetoes(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        None,
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.VETOED
    assert len(verdict.results) == 13


@pytest.mark.parametrize(
    "qty,reserved,held,passed",
    [(2, 0, 2, True), (3, 0, 2, False), (1, 1, 2, True), (2, 1, 2, False), (1, 0, 0, False)],
)
def test_CRO_02_R_01_held_share_boundary_and_pending_sell_reservations(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    qty: int,
    reserved: int,
    held: int,
    passed: bool,
) -> None:
    pending = (
        ()
        if reserved == 0
        else (OpenOrder(symbol="AAPL", side=Side.SELL, qty=reserved, limit_price=Decimal("100")),)
    )
    snapshot = _snapshot(
        clock, positions={"AAPL": _position(held)} if held else {}, open_orders=pending
    )
    proposal = _proposal(clock, side=Side.SELL, intent=Intent.REDUCE, stop_price=None, qty=qty)
    verdict = ChiefRiskOfficer(Settings(), _registry(), risk_calendar).evaluate(
        proposal, snapshot, _market(clock), SystemState.RUNNING, clock.now()
    )
    assert verdict.results[1].passed == passed


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "other"},
        {"created_at": datetime(2099, 1, 1, tzinfo=UTC)},
        {"qty": True},
        {"qty": 0},
        {"limit_price": Decimal("NaN")},
        {"limit_price": Decimal(0)},
        {"stop_price": None},
        {"stop_price": Decimal("100")},
        {"side": Side.SELL},
    ],
)
def test_CRO_02_R_02_defensive_shape_veto_even_if_model_validation_bypassed(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    changes: dict[str, Any],
) -> None:
    proposal = _proposal(clock).model_copy(update=changes)
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    verdict = cro.evaluate(
        proposal,
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.VETOED
    assert not next(rule for rule in verdict.results if rule.rule_id == "CRO-02").passed


@pytest.mark.parametrize(
    "metadata", [{"tradable": False}, {"is_leveraged": True}, {"is_inverse": True}]
)
def test_CRO_02_R_01_instrument_safety(
    clock: FrozenClock, risk_calendar: MarketCalendar, metadata: dict[str, Any]
) -> None:
    registry = InstrumentRegistry((_instrument("AAPL", **metadata),))
    assert not _rule(ChiefRiskOfficer(Settings(), registry, risk_calendar), clock, "CRO-02").passed


def test_CRO_02_R_02_unknown_suspect_future_snapshot_nonpositive_equity(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    for proposal, snapshot, market in (
        (_proposal(clock, symbol="UNKNOWN"), _snapshot(clock), _market(clock)),
        (_proposal(clock), _snapshot(clock), _market(clock, status=MarketStatus.SUSPECT)),
        (
            _proposal(clock),
            _snapshot(clock, as_of=clock.now() + timedelta(seconds=1)),
            _market(clock),
        ),
        (_proposal(clock), _snapshot(clock, equity=Decimal(0)), _market(clock)),
        (_proposal(clock), _snapshot(clock, equity=Decimal("-1")), _market(clock)),
    ):
        verdict = cro.evaluate(
            proposal, snapshot, market, SystemState.RUNNING, clock.now(), deployable=_capital()
        )
        assert verdict.decision == Decision.VETOED
        assert not next(rule for rule in verdict.results if rule.rule_id == "CRO-02").passed


@pytest.mark.parametrize(
    "equity", [Decimal("2000"), Decimal("5000"), Decimal("25000"), Decimal("100000")]
)
@pytest.mark.parametrize("extra,passed", [(-1, True), (0, True), (1, False)])
def test_CRO_03_single_stock_exact_boundary_and_one_share(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    equity: Decimal,
    extra: int,
    passed: bool,
) -> None:
    snapshot = _snapshot(
        clock,
        equity=equity,
        cash=equity,
        settled_cash=equity,
        high_water_mark=equity,
        day_start_equity=equity,
    )
    qty = int(equity * Decimal("0.10") / Decimal("100")) + extra
    result = _rule(
        ChiefRiskOfficer(Settings(), _registry(), risk_calendar),
        clock,
        "CRO-03",
        proposal=_proposal(clock, qty=qty),
        snapshot=snapshot,
    )
    assert result.passed == passed


def test_CRO_03_pending_buy_counts_and_ETF_cap(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(
        Settings(), _registry(_instrument("SPY", asset_class=AssetClass.BROAD_ETF)), risk_calendar
    )
    assert _rule(cro, clock, "CRO-03", proposal=_proposal(clock, symbol="SPY", qty=40)).passed
    assert not _rule(cro, clock, "CRO-03", proposal=_proposal(clock, symbol="SPY", qty=41)).passed
    snapshot = _snapshot(
        clock,
        positions={"AAPL": _position(8)},
        open_orders=(
            OpenOrder(symbol="AAPL", side=Side.BUY, qty=1, limit_price=Decimal("100")),
            OpenOrder(symbol="AAPL", side=Side.SELL, qty=1, limit_price=Decimal("100")),
        ),
    )
    assert _rule(cro, clock, "CRO-03", snapshot=snapshot).passed
    assert not _rule(
        cro, clock, "CRO-03", proposal=_proposal(clock, qty=2), snapshot=snapshot
    ).passed


@pytest.mark.parametrize(
    "equity", [Decimal("2000"), Decimal("5000"), Decimal("25000"), Decimal("100000")]
)
def test_CRO_04_exact_risk_budget_and_one_cent_over(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    equity: Decimal,
) -> None:
    snapshot = _snapshot(
        clock, equity=equity, cash=equity, high_water_mark=equity, day_start_equity=equity
    )
    qty = int(equity / Decimal("1000"))
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert _rule(
        cro,
        clock,
        "CRO-04",
        proposal=_proposal(clock, qty=qty, stop_price=Decimal("90.2")),
        snapshot=snapshot,
    ).passed
    # R-13: the next representable stop is one cent lower at the module boundary.
    stop = Decimal("90.19")
    assert not _rule(
        cro, clock, "CRO-04", proposal=_proposal(clock, qty=qty, stop_price=stop), snapshot=snapshot
    ).passed


def test_CRO_04_ADD_includes_existing_last_to_new_stop(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    snapshot = _snapshot(clock, positions={"AAPL": _position(20)})
    assert not _rule(
        cro, clock, "CRO-04", proposal=_proposal(clock, intent=Intent.ADD), snapshot=snapshot
    ).passed
    below_stop = _snapshot(clock, positions={"AAPL": _position(20, Decimal("90"))})
    assert _rule(
        cro, clock, "CRO-04", proposal=_proposal(clock, intent=Intent.ADD), snapshot=below_stop
    ).passed
    assert _rule(cro, clock, "CRO-04", proposal=_proposal(clock, intent=Intent.ADD)).passed


@pytest.mark.parametrize("existing,passed", [(33, True), (34, True), (35, False)])
def test_CRO_05_sector_cap_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, existing: int, passed: bool
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert (
        _rule(
            cro, clock, "CRO-05", snapshot=_snapshot(clock, positions={"MSFT": _position(existing)})
        ).passed
        == passed
    )


def test_CRO_05_themes_unknown_sectors_and_ETF_lookthrough(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    themes = InstrumentRegistry(
        (_instrument("AAPL", themes=("AI_SEMIS",)), _instrument("MSFT", themes=("AI_SEMIS",)))
    )
    cro = ChiefRiskOfficer(Settings(), themes, risk_calendar)
    assert _rule(
        cro, clock, "CRO-05", snapshot=_snapshot(clock, positions={"MSFT": _position(24)})
    ).passed
    assert not _rule(
        cro, clock, "CRO-05", snapshot=_snapshot(clock, positions={"MSFT": _position(25)})
    ).passed
    unknown_theme = ChiefRiskOfficer(
        Settings(), InstrumentRegistry((_instrument("AAPL", themes=("UNLISTED",)),)), risk_calendar
    )
    assert not _rule(unknown_theme, clock, "CRO-05").passed
    unknown_sector = ChiefRiskOfficer(
        Settings(), InstrumentRegistry((_instrument("AAPL", gics_sector="UNKNOWN"),)), risk_calendar
    )
    assert not _rule(unknown_sector, clock, "CRO-05").passed
    financials = ChiefRiskOfficer(
        Settings(),
        InstrumentRegistry((_instrument("AAPL", gics_sector="Financials"),)),
        risk_calendar,
    )
    assert _rule(financials, clock, "CRO-05").passed
    registry = _registry(
        _instrument("SPY", asset_class=AssetClass.BROAD_ETF),
        etf_weights={
            "SPY": {"Information Technology": Decimal("0.5"), "Financials": Decimal("0.5")}
        },
    )
    lookthrough = ChiefRiskOfficer(Settings(), registry, risk_calendar)
    snapshot = _snapshot(clock, positions={"AAPL": _position(20)})
    assert _rule(
        lookthrough,
        clock,
        "CRO-05",
        proposal=_proposal(clock, symbol="SPY", qty=30),
        snapshot=snapshot,
    ).passed
    assert not _rule(
        lookthrough,
        clock,
        "CRO-05",
        proposal=_proposal(clock, symbol="SPY", qty=31),
        snapshot=snapshot,
    ).passed


@pytest.mark.parametrize("existing,passed", [(48, True), (49, True), (50, False)])
def test_CRO_06_gross_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, existing: int, passed: bool
) -> None:
    cro = ChiefRiskOfficer(Settings(max_gross_exposure=Decimal("0.50")), _registry(), risk_calendar)
    assert (
        _rule(
            cro, clock, "CRO-06", snapshot=_snapshot(clock, positions={"MSFT": _position(existing)})
        ).passed
        == passed
    )


@pytest.mark.parametrize(
    "cash,passed", [(Decimal("700.01"), True), (Decimal("700"), True), (Decimal("699.99"), False)]
)
def test_CRO_06_cash_buffer_pending_notional_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, cash: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    snapshot = _snapshot(
        clock,
        cash=cash,
        open_orders=(OpenOrder(symbol="MSFT", side=Side.BUY, qty=1, limit_price=Decimal("100")),),
    )
    assert _rule(cro, clock, "CRO-06", snapshot=snapshot).passed == passed


def test_CRO_06_position_count_boundary_and_zero_holdings(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(Settings(max_open_positions=2), _registry(), risk_calendar)
    assert _rule(
        cro,
        clock,
        "CRO-06",
        snapshot=_snapshot(clock, positions={"MSFT": _position(1), "IBM": _position(0)}),
    ).passed
    assert not _rule(
        cro,
        clock,
        "CRO-06",
        snapshot=_snapshot(clock, positions={"MSFT": _position(1), "IBM": _position(1)}),
    ).passed


@pytest.mark.parametrize(
    "limit,passed",
    [
        (Decimal("97"), True),
        (Decimal("103"), True),
        (Decimal("103.01"), False),
        (Decimal("96.99"), False),
    ],
)
def test_CRO_07_price_collar_exact_and_cent_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, limit: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert (
        _rule(cro, clock, "CRO-07", proposal=_proposal(clock, limit_price=limit)).passed == passed
    )


@pytest.mark.parametrize("seconds,passed", [(59, True), (60, True), (61, False), (-1, False)])
def test_CRO_07_quote_age_boundary_and_future(
    clock: FrozenClock, risk_calendar: MarketCalendar, seconds: int, passed: bool
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert (
        _rule(
            cro,
            clock,
            "CRO-07",
            market=_market(clock, last_price_ts=clock.now() - timedelta(seconds=seconds)),
        ).passed
        == passed
    )


@pytest.mark.parametrize(
    "price,passed", [(Decimal("5.01"), True), (Decimal("5"), True), (Decimal("4.99"), False)]
)
def test_CRO_07_minimum_price_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, price: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert (
        _rule(
            cro,
            clock,
            "CRO-07",
            proposal=_proposal(clock, limit_price=price, stop_price=Decimal("4")),
            market=_market(clock, last_price=price),
        ).passed
        == passed
    )


def test_CRO_07_DAT_01_weekend_quote_uses_last_close(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    weekend = FrozenClock(datetime(2026, 10, 4, 15, 0, tzinfo=UTC))
    close = risk_calendar.session_close(date(2026, 10, 2))
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert _rule(cro, weekend, "CRO-07", market=_market(weekend, last_price_ts=close)).passed
    assert not _rule(
        cro, weekend, "CRO-07", market=_market(weekend, last_price_ts=close - timedelta(seconds=61))
    ).passed


@pytest.mark.parametrize(
    "adv,passed",
    [
        (Decimal("10001"), True),
        (Decimal("10000"), True),
        (Decimal("9999"), False),
        (Decimal(0), False),
    ],
)
def test_CRO_08_ADV_exact_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, adv: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert _rule(cro, clock, "CRO-08", market=_market(clock, adv20_usd=adv)).passed == passed


@pytest.mark.parametrize(
    "equity,passed",
    [
        (Decimal("9200.01"), True),
        (Decimal("9200"), False),
        (Decimal("9199.99"), False),
        (Decimal("8800"), False),
    ],
)
def test_CRO_09_drawdown_inclusive_tiers(
    clock: FrozenClock, risk_calendar: MarketCalendar, equity: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert _rule(cro, clock, "CRO-09", snapshot=_snapshot(clock, equity=equity)).passed == passed


@pytest.mark.parametrize(
    "equity,passed",
    [(Decimal("9800.01"), True), (Decimal("9800"), False), (Decimal("9799.99"), False)],
)
def test_CRO_10_daily_loss_inclusive_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, equity: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert _rule(cro, clock, "CRO-10", snapshot=_snapshot(clock, equity=equity)).passed == passed


def test_CRO_09_CRO_10_first_baselines_zero_and_nonpositive_equity(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    fresh = _snapshot(clock, high_water_mark=Decimal(0), day_start_equity=Decimal(0))
    assert not _rule(cro, clock, "CRO-09", snapshot=fresh).passed
    assert not _rule(cro, clock, "CRO-10", snapshot=fresh).passed
    bad = _snapshot(
        clock, equity=Decimal(0), high_water_mark=Decimal(0), day_start_equity=Decimal(0)
    )
    assert not _rule(cro, clock, "CRO-09", snapshot=bad).passed
    assert not _rule(cro, clock, "CRO-10", snapshot=bad).passed


@pytest.mark.parametrize(
    "offset,symbol,passed",
    [
        (-1, "AAPL", False),
        (0, "AAPL", False),
        (1, "AAPL", True),
        (0, None, False),
        (0, "MSFT", True),
    ],
)
def test_CRO_11_blackout_start_end_and_symbol_boundaries(
    clock: FrozenClock, risk_calendar: MarketCalendar, offset: int, symbol: str | None, passed: bool
) -> None:
    window = BlackoutWindow(
        start=clock.now() + timedelta(seconds=offset),
        end=clock.now() + timedelta(seconds=offset + 1),
        symbol=symbol,
        reason="fixture",
    )
    registry = _registry(blackout_windows=(window,))
    cro = ChiefRiskOfficer(Settings(), registry, risk_calendar)
    assert _rule(cro, clock, "CRO-11").passed == passed
    if offset == -1:
        explicit = ChiefRiskOfficer(
            Settings(), _registry(), risk_calendar, blackout_windows=(window,)
        )
        assert not _rule(explicit, clock, "CRO-11").passed


@pytest.mark.parametrize("status", list(CapitalStatus))
def test_CRO_12_funding_all_statuses(
    clock: FrozenClock, risk_calendar: MarketCalendar, status: CapitalStatus
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(status),
    )
    assert next(rule for rule in verdict.results if rule.rule_id == "CRO-12").passed == (
        status == CapitalStatus.OK
    )
    missing = cro.evaluate(
        _proposal(clock), _snapshot(clock), _market(clock), SystemState.RUNNING, clock.now()
    )
    assert not next(rule for rule in missing.results if rule.rule_id == "CRO-12").passed


def test_CRO_02_R_02_faults_produce_veto_or_typed_error(
    clock: FrozenClock, risk_calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)

    def broken_calendar(now: datetime) -> bool:
        raise RuntimeError("injected calendar fault")

    monkeypatch.setattr(risk_calendar, "is_open", broken_calendar)
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.VETOED
    assert len(verdict.results) == 13
    with pytest.raises(DataIntegrityError):
        cro.evaluate(
            _proposal(clock).model_copy(update={"proposal_id": "bad"}),
            _snapshot(clock),
            _market(clock),
            SystemState.RUNNING,
            clock.now(),
        )
    with pytest.raises(DataIntegrityError):
        cro.evaluate(
            _proposal(clock),
            _snapshot(clock),
            _market(clock),
            SystemState.RUNNING,
            clock.now().replace(tzinfo=None),
        )


@pytest.mark.parametrize(
    "equity", [Decimal("2000"), Decimal("5000"), Decimal("25000"), Decimal("100000")]
)
def test_CRO_03_to_08_max_qty_is_largest_whole_share(
    clock: FrozenClock, risk_calendar: MarketCalendar, equity: Decimal
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    snapshot = _snapshot(
        clock, equity=equity, cash=equity, high_water_mark=equity, day_start_equity=equity
    )
    proposal = _proposal(clock, qty=10000, stop_price=Decimal("90.2"))
    largest = cro.max_allowed_qty(proposal, snapshot, _market(clock), clock.now())
    assert largest == int(equity * Decimal("0.10") / Decimal("100"))
    yes = cro.evaluate(
        proposal.model_copy(update={"qty": largest}),
        snapshot,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    no = cro.evaluate(
        proposal.model_copy(update={"qty": largest + 1}),
        snapshot,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert yes.decision == Decision.APPROVED
    assert no.decision == Decision.VETOED


def test_CRO_03_to_08_sizing_fail_closed_and_sell_zero(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    exit_proposal = _proposal(clock, side=Side.SELL, intent=Intent.EXIT, stop_price=None)
    assert cro.max_allowed_qty(exit_proposal, _snapshot(clock), _market(clock), clock.now()) == 0
    assert (
        cro.max_allowed_qty(
            _proposal(clock), _snapshot(clock, cash=Decimal(0)), _market(clock), clock.now()
        )
        == 0
    )
    assert (
        cro.max_allowed_qty(
            _proposal(clock, symbol="UNKNOWN"), _snapshot(clock), _market(clock), clock.now()
        )
        == 0
    )
    with pytest.raises(DataIntegrityError):
        cro.max_allowed_qty(
            _proposal(clock).model_copy(update={"limit_price": Decimal(0)}),
            _snapshot(clock),
            _market(clock),
            clock.now(),
        )
    with pytest.raises(DataIntegrityError):
        cro.max_allowed_qty(
            _proposal(clock), cast(PortfolioSnapshot, None), _market(clock), clock.now()
        )


def test_CRO_03_CRO_06_batch_reserves_approved_buys_and_sells(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    buy = _proposal(clock, qty=6, stop_price=Decimal("99"))
    verdicts = cro.evaluate_batch(
        (buy, buy),
        _snapshot(clock),
        {"AAPL": _market(clock)},
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert [verdict.decision for verdict in verdicts] == [Decision.APPROVED, Decision.VETOED]
    sell = _proposal(clock, side=Side.SELL, intent=Intent.EXIT, stop_price=None, qty=1)
    snapshot = _snapshot(clock, positions={"AAPL": _position(1)})
    exits = cro.evaluate_batch(
        (sell, sell), snapshot, {"AAPL": _market(clock)}, SystemState.RUNNING, clock.now()
    )
    assert [verdict.decision for verdict in exits] == [Decision.APPROVED, Decision.VETOED]
    missing = cro.evaluate_batch((buy,), _snapshot(clock), {}, SystemState.RUNNING, clock.now())
    assert missing[0].decision == Decision.VETOED


@hypothesis_settings(max_examples=75, deadline=None)
@given(
    equity=st.integers(min_value=2000, max_value=100000),
    qty=st.integers(min_value=1, max_value=1000),
)
def test_CRO_03_CRO_04_R_03_property_no_overweight_or_overrisk(equity: int, qty: int) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 15, 0, tzinfo=UTC))
    calendar = MarketCalendar(start=date(2026, 9, 1), end=date(2026, 10, 31))
    cro = ChiefRiskOfficer(Settings(), _registry(), calendar)
    capital = Decimal(equity)
    snapshot = _snapshot(
        clock, equity=capital, cash=capital, high_water_mark=capital, day_start_equity=capital
    )
    proposal = _proposal(clock, qty=qty, stop_price=Decimal("90.2"))
    verdict = cro.evaluate(
        proposal, snapshot, _market(clock), SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    assert verdict == cro.evaluate(
        proposal, snapshot, _market(clock), SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    if verdict.decision == Decision.APPROVED:
        assert qty * Decimal("100") <= capital * Decimal("0.10")
        assert qty * Decimal("10") <= capital * Decimal("0.01")


@hypothesis_settings(max_examples=50, deadline=None)
@given(
    held=st.integers(min_value=0, max_value=1000), extra=st.integers(min_value=1, max_value=1000)
)
def test_CRO_02_R_01_property_never_oversells(held: int, extra: int) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 15, 0, tzinfo=UTC))
    cro = ChiefRiskOfficer(
        Settings(), _registry(), MarketCalendar(start=date(2026, 9, 1), end=date(2026, 10, 31))
    )
    proposal = _proposal(
        clock, side=Side.SELL, intent=Intent.REDUCE, qty=held + extra, stop_price=None
    )
    snapshot = _snapshot(clock, positions={"AAPL": _position(held)})
    assert (
        cro.evaluate(proposal, snapshot, _market(clock), SystemState.RUNNING, clock.now()).decision
        == Decision.VETOED
    )


@hypothesis_settings(max_examples=25, deadline=None)
@given(
    qty=st.integers(min_value=1, max_value=1000),
    state=st.sampled_from([SystemState.REDUCE_ONLY, SystemState.HALTED]),
)
def test_CRO_01_property_never_enters_nonrunning(qty: int, state: SystemState) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 15, 0, tzinfo=UTC))
    cro = ChiefRiskOfficer(
        Settings(), _registry(), MarketCalendar(start=date(2026, 9, 1), end=date(2026, 10, 31))
    )
    assert (
        cro.evaluate(
            _proposal(clock, qty=qty),
            _snapshot(clock),
            _market(clock),
            state,
            clock.now(),
            deployable=_capital(),
        ).decision
        == Decision.VETOED
    )


@pytest.mark.parametrize("invalid_dependency", ["registry", "calendar"])
def test_CRO_02_R_02_constructor_requires_verified_dependencies(
    risk_calendar: MarketCalendar,
    invalid_dependency: str,
) -> None:
    registry = cast(InstrumentRegistry, None) if invalid_dependency == "registry" else _registry()
    calendar = cast(MarketCalendar, None) if invalid_dependency == "calendar" else risk_calendar
    with pytest.raises(ConfigurationError):
        ChiefRiskOfficer(Settings(), registry, calendar)


def test_CRO_02_R_07_explicit_telegram_allowlist_preserved(
    risk_calendar: MarketCalendar,
) -> None:
    config = Settings(telegram_allowed_user_ids=(123,))
    cro = ChiefRiskOfficer(config, _registry(), risk_calendar)
    assert cro.config.telegram_allowed_user_ids == (123,)
    assert cro.config.config_hash == config.config_hash


def test_CRO_04_R_02_protection_fault_never_becomes_zero_risk(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    forged = _proposal(clock).model_copy(update={"stop_price": None})
    with pytest.raises(DataIntegrityError):
        cro._risk(forged, _snapshot(clock))


@pytest.mark.parametrize(
    "earnings,passed",
    [(date(2026, 9, 28), False), (date(2026, 9, 29), False), (date(2026, 9, 30), True)],
)
def test_CRO_13_zero_sessions_blocks_same_day_and_unresolved_past(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    earnings: date,
    passed: bool,
) -> None:
    cro = ChiefRiskOfficer(Settings(earnings_blackout_sessions=0), _registry(), risk_calendar)
    rule = _rule(cro, clock, "CRO-13", market=_market(clock, next_earnings_date=earnings))
    assert rule.passed == passed
    assert rule.severity == Severity.BLOCK


def test_CRO_13_uses_exchange_date_after_UTC_midnight(
    risk_calendar: MarketCalendar,
) -> None:
    clock = FrozenClock(datetime(2026, 9, 30, 0, 30, tzinfo=UTC))
    close = risk_calendar.session_close(date(2026, 9, 29))
    cro = ChiefRiskOfficer(Settings(earnings_blackout_sessions=0), _registry(), risk_calendar)
    rule = _rule(
        cro,
        clock,
        "CRO-13",
        market=_market(clock, last_price_ts=close, next_earnings_date=date(2026, 9, 30)),
    )
    assert rule.passed


@pytest.mark.parametrize(
    "equity,expected",
    [
        (Decimal("10000"), SystemState.RUNNING),
        (Decimal("9800"), SystemState.REDUCE_ONLY),
        (Decimal("9200"), SystemState.REDUCE_ONLY),
        (Decimal("8800"), SystemState.HALTED),
        (Decimal("0"), SystemState.HALTED),
    ],
)
def test_CRO_09_CRO_10_recommendations_are_pure_and_do_not_trap_exits(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    equity: Decimal,
    expected: SystemState,
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    snapshot = _snapshot(clock, equity=equity, positions={"AAPL": _position(1)})
    exit_proposal = _proposal(clock, side=Side.SELL, intent=Intent.EXIT, stop_price=None)
    verdict = cro.evaluate(exit_proposal, snapshot, None, SystemState.RUNNING, clock.now())
    assert verdict.decision == Decision.APPROVED
    assert verdict.recommended_state == expected
    assert [result.rule_id for result in verdict.results] == ["CRO-01", "CRO-02"]


def test_CRO_03_to_08_advisory_sizing_never_increases_requested_qty(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    assert (
        cro.max_allowed_qty(_proposal(clock, qty=2), _snapshot(clock), _market(clock), clock.now())
        == 2
    )


def test_CRO_03_CRO_06_batch_iteration_fault_is_typed(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    class BrokenBatch:
        def __iter__(self) -> Any:
            raise RuntimeError("batch source unavailable")

    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    with pytest.raises(DataIntegrityError):
        cro.evaluate_batch(BrokenBatch(), _snapshot(clock), {}, SystemState.RUNNING, clock.now())


def test_CRO_01_R_02_batch_unverifiable_market_latches_local_halt(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    bad = _proposal(clock, symbol="MSFT")
    good = _proposal(clock)
    verdicts = cro.evaluate_batch(
        (bad, good),
        _snapshot(clock),
        {"AAPL": _market(clock)},
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdicts[0].recommended_state == SystemState.HALTED
    assert verdicts[1].decision == Decision.VETOED
    assert [result.rule_id for result in verdicts[1].results] == ["CRO-01"]


def test_CRO_04_batch_approved_but_unsubmitted_stop_risk_is_reserved(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), risk_calendar)
    first = _proposal(clock, qty=4, stop_price=Decimal("80"))
    second = _proposal(clock, proposal_id=UUID(int=3), intent=Intent.ADD, stop_price=Decimal("80"))
    verdicts = cro.evaluate_batch(
        (first, second),
        _snapshot(clock),
        {"AAPL": _market(clock)},
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdicts[0].decision == Decision.APPROVED
    assert verdicts[1].decision == Decision.VETOED
    assert next(result for result in verdicts[1].results if result.rule_id == "CRO-02").passed
    risk = next(result for result in verdicts[1].results if result.rule_id == "CRO-04")
    assert not risk.passed
    assert Decimal(risk.observed) == Decimal("101.00")


@pytest.mark.parametrize("unknown_inventory", ["zero_position", "pending_sell"])
def test_R_02_CRO_02_unknown_inventory_is_not_ignored_for_new_entries(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    unknown_inventory: str,
) -> None:
    changes: dict[str, Any] = (
        {"positions": {"UNKNOWN": _position(0)}}
        if unknown_inventory == "zero_position"
        else {
            "open_orders": (
                OpenOrder(symbol="UNKNOWN", side=Side.SELL, qty=1, limit_price=Decimal("100")),
            )
        }
    )
    verdict = ChiefRiskOfficer(Settings(), _registry(), risk_calendar).evaluate(
        _proposal(clock),
        _snapshot(clock, **changes),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.VETOED
    assert verdict.recommended_state == SystemState.HALTED
````````
<!-- END FILE backend/tests/test_risk_cro.py -->

### backend/tests/test_risk_boundary.py

<!-- BEGIN FILE backend/tests/test_risk_boundary.py -->
````````python
"""R-02/R-03/R-09: persisted CRO tiers, veto audit, and boundary faults."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import Clock, FrozenClock
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountType,
    AssetClass,
    CapitalStatus,
    Decision,
    DeployableCapital,
    Instrument,
    Intent,
    MarketContext,
    MarketStatus,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    Severity,
    Side,
    TradeProposal,
    Verdict,
)
from backend.risk.boundary import LoggingVetoSink, RiskBoundary, VetoSink
from backend.risk.risk_cro import ChiefRiskOfficer

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
TRADE_ID = UUID("50000000-0000-0000-0000-000000000001")
SIGNAL_ID = UUID("50000000-0000-0000-0000-000000000002")


class NoticeRecorder:
    """R-02: local observable notifications without external services."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def notify(self, state: str, reason: str) -> None:
        self.calls.append((state, reason))


class VetoRecorder:
    """R-02: injectable audit sink, including a reproducible sink failure."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, UUID]] = []
        self.fail = fail

    def record(self, rule_id: str, proposal_id: UUID) -> None:
        self.calls.append((rule_id, proposal_id))
        if self.fail:
            raise RuntimeError("audit unavailable")


class BrokenClock:
    """R-05/R-02: time failure is never converted into current time."""

    def now(self) -> datetime:
        raise RuntimeError("clock unavailable")


@pytest.fixture(scope="module")
def boundary_cro() -> ChiefRiskOfficer:
    """CRO-01..13: pure policy with explicitly bounded exchange sessions."""
    instrument = Instrument(
        symbol="AAPL",
        asset_class=AssetClass.STOCK,
        gics_sector="Information Technology",
        themes=(),
        is_leveraged=False,
        is_inverse=False,
        tradable=True,
    )
    return ChiefRiskOfficer(
        Settings(),
        InstrumentRegistry((instrument,)),
        MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31)),
    )


def trade(*, exit_: bool = False, manual: bool = False) -> TradeProposal:
    """R-01/R-05: exact local proposal with explicit lifetime."""
    return TradeProposal(
        proposal_id=TRADE_ID,
        signal_id=SIGNAL_ID,
        account_id="boundary-paper",
        symbol="AAPL",
        side=Side.SELL if exit_ else Side.BUY,
        intent=Intent.EXIT if exit_ else Intent.ENTRY,
        qty=1,
        limit_price=Decimal("100.00"),
        stop_price=None if exit_ else Decimal("95.00"),
        source=ProposalSource.MANUAL if manual else ProposalSource.SIGNAL,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def book(*, equity: str = "10000", held: bool = False) -> PortfolioSnapshot:
    """CRO-09/CRO-10: baselines represent previously persisted marks."""
    return PortfolioSnapshot(
        account_id="boundary-paper",
        account_type=AccountType.CASH,
        as_of=NOW,
        equity=Decimal(equity),
        cash=Decimal(equity),
        settled_cash=Decimal(equity),
        positions={"AAPL": Position(qty=1, avg_cost=Decimal("95.00"), last_price=Decimal("100.00"))}
        if held
        else {},
        open_orders=(),
        high_water_mark=Decimal("10000"),
        day_start_equity=Decimal(equity),
    )


def quote() -> MarketContext:
    """CRO-07/CRO-13: fresh quote and explicit unknown earnings."""
    return MarketContext(
        last_price=Decimal("100.00"),
        last_price_ts=NOW,
        adv20_usd=Decimal("1000000"),
        status=MarketStatus.OK,
    )


def capital() -> DeployableCapital:
    """CRO-12: no bank calls; exact advisory funds."""
    return DeployableCapital(
        checking_used=Decimal("5000"),
        buffer=Decimal("1500"),
        reserved=Decimal(0),
        deployable=Decimal("3500"),
        status=CapitalStatus.OK,
    )


def boundary(engine: Engine, cro: ChiefRiskOfficer, sink: VetoSink | None = None) -> RiskBoundary:
    """R-02/R-05: isolated SQLite state and injected fixed clock."""
    clock = FrozenClock(NOW)
    return RiskBoundary(
        cro, SystemStateStore(engine, clock, NoticeRecorder()), clock, veto_sink=sink
    )


def test_R_03_CRO_13_warn_approval_does_not_log_veto(
    engine: Engine, boundary_cro: ChiefRiskOfficer
) -> None:
    sink = VetoRecorder()
    gate = boundary(engine, boundary_cro, sink)
    result = gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert result.decision == Decision.APPROVED
    assert len(result.results) == 13
    assert not result.results[-1].passed and result.results[-1].severity == Severity.WARN
    assert sink.calls == []
    assert gate.state.current() == SystemState.RUNNING


@pytest.mark.parametrize(
    ("equity", "tier"), [("9200", SystemState.REDUCE_ONLY), ("8800", SystemState.HALTED)]
)
def test_CRO_09_tier_veto_persists_restart(
    engine: Engine, boundary_cro: ChiefRiskOfficer, equity: str, tier: SystemState
) -> None:
    sink = VetoRecorder()
    gate = boundary(engine, boundary_cro, sink)
    result = gate.evaluate(trade(), book(equity=equity), quote(), deployable=capital())
    assert result.decision == Decision.VETOED
    assert gate.state.current() == tier
    assert SystemStateStore(engine, FrozenClock(NOW), NoticeRecorder()).current() == tier
    assert sink.calls == [
        (row.rule_id, TRADE_ID)
        for row in result.results
        if not row.passed and row.severity == Severity.BLOCK
    ]


def test_R_09_exit_detects_halt_without_trapping_held_exit(
    engine: Engine, boundary_cro: ChiefRiskOfficer
) -> None:
    gate = boundary(engine, boundary_cro)
    snapshot = book(equity="8800", held=True)
    assert gate.evaluate(trade(exit_=True), snapshot, None).decision == Decision.APPROVED
    assert gate.state.current() == SystemState.HALTED
    assert gate.evaluate(trade(exit_=True), snapshot, None).decision == Decision.VETOED
    assert (
        gate.evaluate(trade(exit_=True, manual=True), snapshot, None).decision == Decision.APPROVED
    )


def test_CRO_01_concurrent_halt_rechecks_state(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, boundary_cro, VetoRecorder())
    original = gate.state.current
    calls = 0

    def changing_state() -> SystemState:
        nonlocal calls
        calls += 1
        if calls == 2:
            gate.state.escalate(SystemState.HALTED, "concurrent provider failure")
        return original()

    monkeypatch.setattr(gate.state, "current", changing_state)
    result = gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert result.decision == Decision.VETOED
    assert result.results[0].rule_id == "CRO-01"


@pytest.mark.parametrize("failure", ["clock", "cro", "database", "audit"])
def test_R_02_every_boundary_failure_halts(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    # Construct a private CRO so patched providers never contaminate other tests.
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro, VetoRecorder(fail=failure == "audit"))

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected boundary fault")

    if failure == "clock":
        gate.clock = cast(Clock, BrokenClock())
    elif failure == "cro":
        monkeypatch.setattr(cro, "evaluate", fail)
    elif failure == "database":
        monkeypatch.setattr(gate.state.ledger, "verify_chain", fail)
    else:
        gate.state.escalate(SystemState.REDUCE_ONLY, "test audit fault")
    with pytest.raises(DataIntegrityError, match="latched HALTED"):
        gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert gate.state.current() == SystemState.HALTED


def test_R_02_failed_halt_storage_surfaces_typed_error(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, boundary_cro)
    gate.clock = BrokenClock()

    def fail(error: Exception) -> SystemState:
        raise RuntimeError("halt storage unavailable")

    monkeypatch.setattr(gate.state, "halt_for_error", fail)
    with pytest.raises(DataIntegrityError, match="HALT persistence unavailable"):
        gate.evaluate(trade(), book(), quote())


@pytest.mark.parametrize(
    "alteration",
    ["id", "config", "empty", "duplicate", "unknown", "incomplete", "snapshot", "veto", "time"],
)
def test_R_02_forged_verdict_cannot_approve(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch, alteration: str
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    legitimate = cro.evaluate(
        trade(), book(), quote(), SystemState.RUNNING, NOW, deployable=capital()
    )
    updates: dict[str, object] = {}
    if alteration == "id":
        updates["proposal_id"] = SIGNAL_ID
    elif alteration == "config":
        updates["config_hash"] = "f" * 64
    elif alteration == "empty":
        updates["results"] = ()
    elif alteration == "duplicate":
        updates["results"] = (*legitimate.results, legitimate.results[0])
    elif alteration == "unknown":
        updates["results"] = (legitimate.results[0].model_copy(update={"rule_id": "FAKE"}),)
    elif alteration == "incomplete":
        updates["results"] = legitimate.results[:1]
    elif alteration == "snapshot":
        updates["snapshot_hash"] = "f" * 64
    elif alteration == "veto":
        updates["decision"] = Decision.VETOED
    else:
        updates["evaluated_at"] = NOW - timedelta(seconds=1)
    forged = legitimate.model_copy(update=updates)

    def returning(*args: object, **kwargs: object) -> Verdict:
        return forged

    monkeypatch.setattr(cro, "evaluate", returning)
    with pytest.raises(DataIntegrityError):
        gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert gate.state.current() == SystemState.HALTED


def test_R_02_veto_sink_contract_fails_closed() -> None:
    with pytest.raises(DataIntegrityError, match="no implementation"):
        VetoSink.record(cast(VetoSink, object()), "CRO-01", TRADE_ID)


def test_R_02_veto_log_contains_required_identities(caplog: pytest.LogCaptureFixture) -> None:
    LoggingVetoSink().record("CRO-01", TRADE_ID)
    assert "rule_id=CRO-01" in caplog.text
    assert f"proposal_id={TRADE_ID}" in caplog.text


def test_CRO_13_known_distant_earnings_pass(engine: Engine, boundary_cro: ChiefRiskOfficer) -> None:
    context = quote().model_copy(update={"next_earnings_date": date(2026, 10, 9)})
    result = boundary(engine, boundary_cro).evaluate(trade(), book(), context, deployable=capital())
    assert result.decision == Decision.APPROVED
    assert result.results[-1].passed and result.results[-1].severity == Severity.BLOCK


@pytest.mark.parametrize(
    "attack", ["warn_block", "earnings_warn", "halt", "reduce", "restricted_entry"]
)
def test_R_02_severity_and_financial_recommendation_attacks(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    snapshot = book(
        equity="8800" if attack == "halt" else "9200" if attack == "reduce" else "10000",
        held=attack in {"halt", "reduce"},
    )
    proposal = trade(exit_=attack in {"halt", "reduce"})
    result = cro.evaluate(
        proposal, snapshot, quote(), SystemState.RUNNING, NOW, deployable=capital()
    )
    if attack == "warn_block":
        result = result.model_copy(
            update={
                "results": (
                    result.results[0].model_copy(
                        update={"passed": False, "severity": Severity.WARN}
                    ),
                    *result.results[1:],
                )
            }
        )
    elif attack == "earnings_warn":
        # A known earnings date cannot borrow the unknown-date warning exception.
        result = result.model_copy(
            update={
                "results": (
                    *result.results[:-1],
                    result.results[-1].model_copy(
                        update={"passed": True, "severity": Severity.WARN}
                    ),
                )
            }
        )
    else:
        result = result.model_copy(
            update={
                "recommended_state": SystemState.HALTED
                if attack == "restricted_entry"
                else SystemState.RUNNING
            }
        )

    def returning(*args: object, **kwargs: object) -> Verdict:
        return result

    monkeypatch.setattr(cro, "evaluate", returning)
    with pytest.raises(DataIntegrityError):
        gate.evaluate(proposal, snapshot, quote(), deployable=capital())
    assert gate.state.current() == SystemState.HALTED


@pytest.mark.parametrize("bad_time", [False, True])
def test_CRO_01_halt_arriving_at_escalation_is_rechecked(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch, bad_time: bool
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    escalate = gate.state.escalate
    evaluate = cro.evaluate
    calls = 0

    def concurrent(target: SystemState, reason: str) -> SystemState:
        nonlocal calls
        calls += 1
        if calls == 1:
            escalate(SystemState.HALTED, "concurrent failure at commit")
        return escalate(target, reason)

    def injected(*args: object, **kwargs: object) -> Verdict:
        result = evaluate(*args, **kwargs)  # type: ignore[arg-type]
        if bad_time and args[3] == SystemState.HALTED:
            return result.model_copy(update={"evaluated_at": NOW - timedelta(seconds=1)})
        return result

    monkeypatch.setattr(gate.state, "escalate", concurrent)
    monkeypatch.setattr(cro, "evaluate", injected)
    if bad_time:
        with pytest.raises(DataIntegrityError):
            gate.evaluate(trade(), book(), quote(), deployable=capital())
    else:
        assert (
            gate.evaluate(trade(), book(), quote(), deployable=capital()).decision
            == Decision.VETOED
        )
    assert gate.state.current() == SystemState.HALTED


def test_R_02_fault_logger_failure_still_halts(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, boundary_cro)
    gate.clock = BrokenClock()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("logging unavailable")

    monkeypatch.setattr(logging.getLogger("backend.risk.boundary"), "error", fail)
    with pytest.raises(DataIntegrityError, match="latched HALTED"):
        gate.evaluate(trade(), book(), quote())
    assert gate.state.current() == SystemState.HALTED
````````
<!-- END FILE backend/tests/test_risk_boundary.py -->

### backend/tests/test_stage_b_adversarial.py

<!-- BEGIN FILE backend/tests/test_stage_b_adversarial.py -->
````````python
"""R-02/R-03/R-09/R-13: independent attacks on the Stage B risk boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import cast
from uuid import UUID

import pytest

from backend.core.config import Settings
from backend.core.errors import SafetyError
from backend.core.system_state import SystemState
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountType,
    AssetClass,
    CapitalStatus,
    Decision,
    DeployableCapital,
    Instrument,
    Intent,
    MarketContext,
    MarketStatus,
    OpenOrder,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    RuleResult,
    Side,
    TradeProposal,
    Verdict,
)
from backend.risk.risk_cro import ChiefRiskOfficer

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
PROPOSAL_ID = UUID("40000000-0000-0000-0000-000000000001")
SIGNAL_ID = UUID("40000000-0000-0000-0000-000000000002")


@pytest.fixture(scope="module")
def adversarial_calendar() -> MarketCalendar:
    """CRO-13: fixed exchange sessions, with no provider or wall-clock access."""
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


def registry() -> InstrumentRegistry:
    """CRO-02/CRO-05: minimal explicit metadata for independent fixtures."""
    return InstrumentRegistry(
        (
            Instrument(
                symbol="AAPL",
                asset_class=AssetClass.STOCK,
                gics_sector="Information Technology",
                themes=(),
                is_leveraged=False,
                is_inverse=False,
                tradable=True,
            ),
        )
    )


def proposal(now: datetime = NOW, **changes: object) -> TradeProposal:
    """R-01/R-05/R-13: an otherwise eligible cent-priced proposal."""
    fields: dict[str, object] = {
        "proposal_id": PROPOSAL_ID,
        "signal_id": SIGNAL_ID,
        "account_id": "adversarial-paper",
        "symbol": "AAPL",
        "side": Side.BUY,
        "intent": Intent.ENTRY,
        "qty": 1,
        "limit_price": Decimal("100.00"),
        "stop_price": Decimal("95.00"),
        "target_price": Decimal("110.00"),
        "source": ProposalSource.SIGNAL,
        "created_at": now,
        "expires_at": now + timedelta(hours=1),
    }
    fields.update(changes)
    return TradeProposal.model_validate(fields)


def position(qty: int = 1) -> Position:
    """CRO-02/CRO-04: whole-share, cent-priced held inventory."""
    return Position(qty=qty, avg_cost=Decimal("95.00"), last_price=Decimal("100.00"))


def snapshot(now: datetime = NOW, **changes: object) -> PortfolioSnapshot:
    """CRO-09/CRO-10: explicit positive persisted baselines."""
    fields: dict[str, object] = {
        "account_id": "adversarial-paper",
        "account_type": AccountType.CASH,
        "as_of": now,
        "equity": Decimal("10000"),
        "cash": Decimal("10000"),
        "settled_cash": Decimal("10000"),
        "positions": {},
        "open_orders": (),
        "high_water_mark": Decimal("10000"),
        "day_start_equity": Decimal("10000"),
    }
    fields.update(changes)
    return PortfolioSnapshot.model_validate(fields)


def market(now: datetime = NOW, **changes: object) -> MarketContext:
    """CRO-07/CRO-13: fresh quote; no guessed upcoming earnings date."""
    fields: dict[str, object] = {
        "last_price": Decimal("100.00"),
        "last_price_ts": now,
        "adv20_usd": Decimal("1000000"),
        "next_earnings_date": None,
        "status": MarketStatus.OK,
    }
    fields.update(changes)
    return MarketContext.model_validate(fields)


def funding() -> DeployableCapital:
    """CRO-12: exact independent buffer arithmetic, with no bank access."""
    return DeployableCapital(
        checking_used=Decimal("5000"),
        buffer=Decimal("1500"),
        reserved=Decimal("0"),
        deployable=Decimal("3500"),
        status=CapitalStatus.OK,
    )


def verdict(
    cro: ChiefRiskOfficer,
    trade: TradeProposal | None = None,
    book: PortfolioSnapshot | None = None,
    context: MarketContext | None = None,
    now: datetime = NOW,
) -> Verdict:
    """R-03: call the public pure gate with detached deterministic fixtures."""
    return cro.evaluate(
        trade or proposal(now),
        book or snapshot(now),
        context or market(now),
        SystemState.RUNNING,
        now,
        deployable=funding(),
    )


@pytest.mark.parametrize(
    "field,bad",
    [
        ("qty", True),
        ("qty", Decimal("1")),
        ("limit_price", Decimal("100.001")),
        ("limit_price", 100.0),
        ("stop_price", Decimal("100.00")),
        ("intent", "UNRECOGNIZED"),
        ("source", "UNRECOGNIZED"),
        ("signal_id", None),
    ],
)
def test_R_02_R_13_forged_frozen_proposal_is_revalidated(
    adversarial_calendar: MarketCalendar, field: str, bad: object
) -> None:
    """R-02: frozen is no substitute for validation at a risk boundary."""
    # Deliberately mutate instance storage without invoking Pydantic validation.
    forged = proposal()
    forged.__dict__[field] = bad
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert verdict(cro, trade=forged).decision == Decision.VETOED


@pytest.mark.parametrize("nested", ["position", "pending"])
def test_R_02_nested_instances_cannot_smuggle_invalid_inventory(
    adversarial_calendar: MarketCalendar, nested: str
) -> None:
    """R-02/CRO-02/CRO-06: revalidation reaches nested frozen instances."""
    if nested == "position":
        held = position()
        held.__dict__["qty"] = Decimal("1.5")
        book = snapshot()
        book.__dict__["positions"] = {"AAPL": held}
    else:
        pending = OpenOrder(symbol="AAPL", side=Side.BUY, qty=1, limit_price=Decimal("100.00"))
        pending.__dict__["qty"] = -1
        book = snapshot()
        book.__dict__["open_orders"] = (pending,)
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert verdict(cro, book=book).decision == Decision.VETOED


def test_R_02_hard_ceiling_cannot_be_bypassed_by_forged_settings(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-02: CRO construction rejects an unvalidated policy object."""
    config = Settings()
    config.__dict__["max_single_stock_weight"] = Decimal("1.00")
    with pytest.raises(SafetyError):
        ChiefRiskOfficer(config, registry(), adversarial_calendar)


def test_R_02_CRO_05_low_precision_cannot_accept_incomplete_etf_weights() -> None:
    """CRO-05: rounded weight sums cannot erase uncovered ETF exposure."""
    etf = Instrument(
        symbol="SPY",
        asset_class=AssetClass.BROAD_ETF,
        gics_sector="Information Technology",
        themes=(),
        is_leveraged=False,
        is_inverse=False,
        tradable=True,
    )
    with localcontext() as context:
        context.prec = 2
        with pytest.raises(SafetyError):
            InstrumentRegistry(
                (etf,),
                {
                    "SPY": {
                        "Information Technology": Decimal("0.335"),
                        "Financials": Decimal("0.664"),
                    }
                },
            )


@pytest.mark.parametrize("seconds", [0, 1])
def test_R_02_proposal_expiry_is_exclusive_at_exact_equality(
    adversarial_calendar: MarketCalendar, seconds: int
) -> None:
    """R-02/R-14: expiration equality never permits an approval."""
    trade = proposal(
        created_at=NOW - timedelta(hours=1), expires_at=NOW - timedelta(seconds=seconds)
    )
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert verdict(cro, trade=trade).decision == Decision.VETOED


def test_R_02_future_creation_and_inventory_cannot_be_approved(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-02/R-05: an aware UTC timestamp can still be unverifiable future data."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert (
        verdict(cro, trade=proposal(created_at=NOW + timedelta(seconds=1))).decision
        == Decision.VETOED
    )
    assert verdict(cro, book=snapshot(as_of=NOW + timedelta(seconds=1))).decision == Decision.VETOED


def test_R_02_R_09_stale_inventory_does_not_prove_a_valid_exit(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-09: only verified held inventory establishes the valid-exit exception."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    trade = proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None, target_price=None)
    book = snapshot(as_of=NOW - timedelta(seconds=61), positions={"AAPL": position()})
    assert verdict(cro, trade=trade, book=book).decision == Decision.VETOED


@pytest.mark.parametrize("field", ["high_water_mark", "day_start_equity"])
def test_R_02_CRO_09_CRO_10_zero_baseline_never_resets_risk(
    adversarial_calendar: MarketCalendar, field: str
) -> None:
    """CRO-09/CRO-10: first-run baselines must be initialized outside the rules."""
    book = snapshot()
    book.__dict__[field] = Decimal("0")
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert verdict(cro, book=book).decision == Decision.VETOED


def test_CRO_04_pending_same_symbol_buys_reserve_stop_risk(
    adversarial_calendar: MarketCalendar,
) -> None:
    """CRO-04: pending additions cannot spend the same stop-risk budget twice."""
    cro = ChiefRiskOfficer(
        Settings(max_single_stock_weight=Decimal("0.20")), registry(), adversarial_calendar
    )
    trade = proposal(intent=Intent.ADD, stop_price=Decimal("90.00"))
    clear = snapshot(positions={"AAPL": position()})
    clear_result = next(
        result
        for result in verdict(cro, trade=trade, book=clear).results
        if result.rule_id == "CRO-04"
    )
    assert clear_result.passed
    reserved = snapshot(
        positions={"AAPL": position()},
        open_orders=(
            OpenOrder(symbol="AAPL", side=Side.BUY, qty=8, limit_price=Decimal("100.00")),
        ),
    )
    result = verdict(cro, trade=trade, book=reserved)
    risk = next(item for item in result.results if item.rule_id == "CRO-04")
    assert not risk.passed
    assert result.decision == Decision.VETOED


def test_CRO_03_to_08_sizing_requires_complete_rule_evidence(
    adversarial_calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-02: all(empty) must never turn missing sizing evidence into capacity."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)

    def missing_rules(*args: object, **kwargs: object) -> tuple[RuleResult, ...]:
        return ()

    monkeypatch.setattr(cro, "_rules", missing_rules)
    assert cro.max_allowed_qty(proposal(), snapshot(), market(), NOW) == 0


@pytest.mark.parametrize(
    "earnings,blocked",
    [
        (date(2026, 11, 26), True),
        (date(2026, 11, 27), True),
        (date(2026, 11, 30), True),
        (date(2026, 12, 1), False),
    ],
)
def test_CRO_13_earnings_uses_sessions_across_holiday_and_early_close(
    adversarial_calendar: MarketCalendar, earnings: date, blocked: bool
) -> None:
    """CRO-13: Thanksgiving and the shortened Friday do not count as extra days."""
    now = datetime(2026, 11, 25, 16, tzinfo=UTC)
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    result = verdict(cro, context=market(now, next_earnings_date=earnings), now=now)
    earnings_result = next(item for item in result.results if item.rule_id == "CRO-13")
    assert earnings_result.passed == (not blocked)
    assert adversarial_calendar.session_close(date(2026, 11, 27)).hour == 18


def test_R_02_CRO_13_out_of_range_earnings_calendar_fails_closed(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-02/CRO-13: an unverifiable session distance is never favorable evidence."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert (
        verdict(cro, context=market(next_earnings_date=date(2035, 1, 2))).decision
        == Decision.VETOED
    )


def test_R_09_manual_exit_ignores_irrelevant_entry_provider_inputs(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-09: bad bank/market inputs cannot trap a verified manual liquidation."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    trade = proposal(
        symbol="UNKNOWN",
        side=Side.SELL,
        intent=Intent.EXIT,
        stop_price=None,
        target_price=None,
        source=ProposalSource.MANUAL,
    )
    book = snapshot(positions={"UNKNOWN": position()})
    result = cro.evaluate(
        trade,
        book,
        cast(MarketContext, object()),
        SystemState.HALTED,
        NOW,
        deployable=cast(DeployableCapital, object()),
    )
    assert result.decision == Decision.APPROVED
    assert tuple(item.rule_id for item in result.results) == ("CRO-01", "CRO-02")


def test_R_09_batch_exit_does_not_require_a_market_mapping(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-09: the batch helper preserves the same valid-exit contract."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    trade = proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None, target_price=None)
    results = cro.evaluate_batch(
        (trade,), snapshot(positions={"AAPL": position()}), {}, SystemState.RUNNING, NOW
    )
    assert results[0].decision == Decision.APPROVED


def test_R_03_R_04_ambient_decimal_precision_does_not_change_risk(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-03/R-04: unrelated caller math cannot round a boundary into approval."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    trade = proposal(qty=10, stop_price=Decimal("90.20"))
    exact = verdict(cro, trade=trade)
    with localcontext() as context:
        context.prec = 2
        limited = verdict(cro, trade=trade)
    assert limited == exact
    assert exact.decision == Decision.APPROVED
````````
<!-- END FILE backend/tests/test_stage_b_adversarial.py -->

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
name: Stage A and B defensive core
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
      - name: Strict Stage A and B typing
        run: python -m backend.core.check_stage_b
      - name: Execution source guard
        run: python -m backend.core.source_guard .
      - name: Security checks
        run: python -m bandit -r backend/core backend/domain backend/risk/risk_cro.py backend/risk/boundary.py backend/data/market_calendar.py -c pyproject.toml && python -m pip_audit -r requirements-lock.txt --no-deps --disable-pip --progress-spinner off --timeout 15 && python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]' > /tmp/vws-secrets.json && python -c "import json; from pathlib import Path; findings=json.loads(Path('/tmp/vws-secrets.json').read_text())['results']; print(findings); assert not findings"
      - name: Stage A and B tests, network blocked, state and CRO branch coverage 100%
        run: python -m pytest backend/tests/test_config_safety.py backend/tests/test_yaml_config.py backend/tests/test_money.py backend/tests/test_logging.py backend/tests/test_ledger.py backend/tests/test_research_ledger.py backend/tests/test_system_state.py backend/tests/test_market_calendar.py backend/tests/test_no_order_exec.py backend/tests/test_domain.py backend/tests/test_risk_cro.py backend/tests/test_risk_boundary.py backend/tests/test_stage_b_adversarial.py --cov=backend.core.system_state --cov=backend.risk.risk_cro --cov=backend.risk.boundary --cov-branch --cov-fail-under=100 --cov-report=term-missing
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
      - id: stage-ab-types
        name: Stage A and B strict types
        entry: python -m backend.core.check_stage_b
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
secrets-report.json
````````
<!-- END FILE ../.gitignore -->

