# Stage A — full delivery

Implemented from the newest master spec after the exact command Execute Stage A.
Only Stage A is complete. Stop here; the next command is Execute Stage B.

845 offline tests passed. system_state coverage is 100% of 163 statements and
46 branches. Ruff, format, strict mypy (45 files), AST guard, Bandit, pip-audit,
secrets checks, and all five root pre-commit hooks passed. See VERIFY.md below.
PostgreSQL runtime checks and B–F master features remain pending.

Every listed file is reproduced in full; no code block is truncated. The last
appendix preserves earlier draft files that received minimal compatibility edits.
It does not certify their behavior against Stages B–D of the new master spec.
Original file bytes and SHA-256 values are recorded so the snapshot is reviewable.

## ASSUMPTIONS

# ASSUMPTIONS

The newest master spec supersedes the earlier A–D blueprint and automatic
continuation request. The current command authorizes only Stage A. Stage B starts
only after the exact command `Execute Stage B`. Order execution is permanently
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
25. Older B–D drafts are preserved, not certified against the new master spec.
    Minimal reflection/lint edits keep them compatible with the whole-source guard.
    The current Git root is Project V, so a root CI workflow mirrors the requested
    project workflow, pre-commit configuration, and .gitignore. These support
    nested or standalone project checkouts.
26. APScheduler 3.11.3 is the stable installed release with AsyncIOScheduler;
    actual scheduling is deferred to Stage F. Full source delivery uses a local
    Markdown artifact: assumptions, SHA-256 manifest, then every file in full.
27. SQLite recursive triggers are explicitly enabled to prevent REPLACE from
    deleting/replacing protected rows. State-control projections are verified
    against immutable events during live reads/transitions, not only at startup.

## FILE MANIFEST

| Path | Scope | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| .env.example | Stage A | 2606 | d4665b19a70c0d2d776e1e0be4c1351003f7d286c91b4f679983bcbf964a41fb |
| .gitignore | Stage A | 349 | 42411b3abf6b8a46f4faa2b060f1fd19d31cca57bb598c5a7b110f9501285637 |
| .dockerignore | Stage A | 339 | e5f749ef7bc885b3ac26490f985d6348f43f92d2a148d8ad1aa62fec7cbacaf8 |
| .pre-commit-config.yaml | Stage A | 899 | 5c1dc6c05e3976dfb8fdcbccf8ecebdc171e605ac9a4a69c84ad62e96fb83422 |
| pyproject.toml | Stage A | 2190 | 96e47254af904ebf47120aee7b75c539547d906e9614ef86c5b1b9b98cb335b9 |
| requirements-lock.txt | Stage A | 2123 | d465af53a4e8375afc2014db09889d14b4badfeb9a932fa5d3b344920273d5dc |
| .github/workflows/ci.yml | Stage A | 2132 | 978f9cf636050687194693b6ae35f363a365158032f63e835bc084580bd79f14 |
| README.md | Stage A | 4722 | f6b5fb76fbc3cebd41aaec0d129e2efe48f01b1583beba2138c6669346d3ed7f |
| ASSUMPTIONS.md | Stage A | 7020 | 7d25b1fb7713d157a8934e5b06a08827cc9e576c38aa2bf73e96464567995621 |
| VERIFY.md | Stage A | 9183 | 7ce890022eead819b900835cc6f4af3df07bce2e5736a81c85d3d694474331bf |
| config/config.yaml | Stage A | 782 | 2714e63536baca5dd313596df9401ff5fa5e62a81358e35749a5f9e0a1ce3d0c |
| backend/__init__.py | Stage A | 77 | 0d25e37c3c72b897beabf71ef1fdcfbaf73c3874f408fc3920e3d4b6c124a84e |
| backend/core/__init__.py | Stage A | 63 | 16172f1bfafe16fdd27a11fe2ffaed73525f04cf50c2bb9784c9d23ee8db4a8e |
| backend/core/config.py | Stage A | 35775 | 7427d4ee67178136522c4ffed0f67725d001c3b5e6ccbed64655d21acdf5b221 |
| backend/core/clock.py | Stage A | 1719 | 1903f9789454b57df2c6d5a9c85b3f7b1f8772da6edda0327386a85667446930 |
| backend/core/errors.py | Stage A | 1626 | 7b5e510980157cea2690298a5d7d19be33aeda257b8829822f5943bcb65675eb |
| backend/core/money.py | Stage A | 3427 | 491a267134a3d1ada08d05b5de0841b1f405406bcddfe08ab2cd7160f60e7add |
| backend/core/logging.py | Stage A | 3310 | 39a84aff1564ccdf7f3f48c521cf1af5ad680f9d75eb191e2eda64d13ebd6247 |
| backend/core/notifier.py | Stage A | 1827 | 4358bac1cb6ccc13c590b21772a710de9a9370bb7ab9d20286b28eacf8423f48 |
| backend/core/database.py | Stage A | 32566 | 87178a5ccdfaf97710ff729dc7af2b7c8422ac2d16ad46d3b68c50611c6e1fdb |
| backend/core/ledger.py | Stage A | 55148 | 5362851f86007316fdda720ca8cef26b6a2f7cb1e54a12d9d7fdc073aa683c09 |
| backend/core/system_state.py | Stage A | 11011 | dfeede8c2573d641cd12cbbd258244eb9caebb2763f5ea6961ba419fe2fe8b8a |
| backend/core/execution_policy.py | Stage A | 2238 | 826cb722b5dc19dc326ce75d0cbeac6c623b13a50a85313a1ac19d25913291f7 |
| backend/core/source_guard.py | Stage A | 22487 | ff10d3a3ab4a04c87ea9d463185b9f9b83f8e0bb9a9e2e6a12a9ecadff3b5d13 |
| backend/core/check_stage_a.py | Stage A | 1880 | 1fb4e8f146fc171bc40a071aa1f28d5cdb9dadd2e17e759a5b1fa41c113936ef |
| backend/data/__init__.py | Stage A | 38 | 92296c6545459927a1b354008b98911a38b58fd57c66dc852595388822e952af |
| backend/data/market_calendar.py | Stage A | 9589 | a3e136f65c416b13eb86fdec90f62dcd17353376d136da123257fa6a6a03600b |
| backend/tests/__init__.py | Stage A | 41 | c9481d0d1ecb3da2f37f02a1577a4eede80f71778168f2ce83a7abdff88a7cdb |
| backend/tests/conftest.py | Stage A | 1711 | a5d15a108cdc3d636d40f83772de0547a819b9d4e48c185f013c716e8f1e591e |
| backend/tests/test_config_safety.py | Stage A | 18843 | a11e64a90cea44e3af44f47a760126e7b01a38a27772512d105a713f00197a3e |
| backend/tests/test_yaml_config.py | Stage A | 11617 | 05ed93ce3064bc2035947ef71ef54e4390a08a950688cc55dd117c23f3ae6d03 |
| backend/tests/test_money.py | Stage A | 2899 | e14367be5710744d19d5cd8d08401162cafe13f78a2a61b6e1d9fd56f0362e96 |
| backend/tests/test_logging.py | Stage A | 5537 | 2b1e983a7b12b7890292d11190c9bb6a1de04298cfe0d2820375a994b17fb286 |
| backend/tests/test_ledger.py | Stage A | 22883 | 90a20247cfae41d8614882dcb8aea8bc447e803b2fe09b7381a93084df30d584 |
| backend/tests/test_research_ledger.py | Stage A | 19363 | c9ba8b65c1324c2b61c873c0db189d970871d12b83d12b593aa72ba7caa8bb6c |
| backend/tests/test_system_state.py | Stage A | 13152 | ec31578ab3ad549678d56c3e5d1bff04cc9a395b2ce64ecfa922d963a567bf3f |
| backend/tests/test_market_calendar.py | Stage A | 13276 | cbad00b260562f384c319ef008a168a1dd8993e04320a00b01d0656d6cf87a30 |
| backend/tests/test_no_order_exec.py | Stage A | 13661 | 85a9519dec13aa991154edad08c8c6867adafdf62839c2a148e65c9811b04915 |
| ../.github/workflows/ci.yml | Parent repository wiring | 2132 | 978f9cf636050687194693b6ae35f363a365158032f63e835bc084580bd79f14 |
| ../.pre-commit-config.yaml | Parent repository wiring | 899 | 5c1dc6c05e3976dfb8fdcbccf8ecebdc171e605ac9a4a69c84ad62e96fb83422 |
| ../.gitignore | Parent repository wiring | 349 | 42411b3abf6b8a46f4faa2b060f1fd19d31cca57bb598c5a7b110f9501285637 |
| backend/risk/risk_cro.py | Preserved draft compatibility edit | 19007 | 9089728132d5499c9c7a8e629fd410442b68488d6b409e32cb34a43b5ab1f94e |
| backend/tests/test_data_layer.py | Preserved draft compatibility edit | 24764 | 7c4eaccf0d58b70a13668b4a46b221cdb7e881cbcaea422d12b801432718a5e7 |
| scripts/plaid_sandbox_token.py | Preserved draft compatibility edit | 5717 | 31bfc1372340d595344750eae41cf51856f96f2322921be45dc88312d134b72b |

## EVERY FILE IN FULL

### .env.example

Scope: Stage A. SHA-256: d4665b19a70c0d2d776e1e0be4c1351003f7d286c91b4f679983bcbf964a41fb.

```text
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
```

### .gitignore

Scope: Stage A. SHA-256: 42411b3abf6b8a46f4faa2b060f1fd19d31cca57bb598c5a7b110f9501285637.

```text
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
secrets-report.json
```

### .dockerignore

Scope: Stage A. SHA-256: e5f749ef7bc885b3ac26490f985d6348f43f92d2a148d8ad1aa62fec7cbacaf8.

```text
.env
.env.*
!.env.example
.git
.venv
__pycache__
*.py[cod]
.pytest_cache
.mypy_cache
.ruff_cache
.hypothesis
.coverage*
coverage.xml
htmlcov
backend/tests
mutants
.mutmut-cache
.secrets
*.db
*.db-wal
*.db-shm
*.sqlite3*
*.pem
*.key
*.token
*.fernet
audit-report.json
bandit-report.json
secrets-report.json
build
dist
*.egg-info
deliveries
```

### .pre-commit-config.yaml

Scope: Stage A. SHA-256: 5c1dc6c05e3976dfb8fdcbccf8ecebdc171e605ac9a4a69c84ad62e96fb83422.

```yaml
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
      - id: stage-a-types
        name: Stage A strict types
        entry: python -m backend.core.check_stage_a
        language: system
        pass_filenames: false
        types: [python]
      - id: detect-secrets
        name: Secrets scan
        entry: detect-secrets-hook
        language: system
        exclude: (^|/)(backend/tests/|requirements-lock\.txt$|deliveries/)
```

### pyproject.toml

Scope: Stage A. SHA-256: 96e47254af904ebf47120aee7b75c539547d906e9614ef86c5b1b9b98cb335b9.

```toml
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
source = ["backend.core.system_state"]

[tool.bandit]
exclude_dirs = ["backend/tests", ".venv", "mutants"]

[tool.mutmut]
source_paths = ["backend/risk/"]
also_copy = ["backend/core", "backend/data", "backend/domain", "backend/tests", "config", "scripts"]
pytest_add_cli_args_test_selection = ["backend/tests/test_risk_cro.py", "backend/tests/test_compliance.py"]
pytest_add_cli_args = ["--disable-socket", "-q"]
```

### requirements-lock.txt

Scope: Stage A. SHA-256: d465af53a4e8375afc2014db09889d14b4badfeb9a932fa5d3b344920273d5dc.

```text
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
```

### .github/workflows/ci.yml

Scope: Stage A. SHA-256: 978f9cf636050687194693b6ae35f363a365158032f63e835bc084580bd79f14.

```yaml
name: Stage A defensive core
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
      - name: Strict Stage A typing
        run: python -m backend.core.check_stage_a
      - name: Execution source guard
        run: python -m backend.core.source_guard .
      - name: Security checks
        run: python -m bandit -r backend/core backend/data/market_calendar.py -c pyproject.toml && python -m pip_audit -r requirements-lock.txt && python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]' > /tmp/vws-secrets.json && python -c "import json; from pathlib import Path; findings=json.loads(Path('/tmp/vws-secrets.json').read_text())['results']; print(findings); assert not findings"
      - name: Stage A tests, network blocked, state branch coverage 100%
        run: python -m pytest backend/tests/test_config_safety.py backend/tests/test_yaml_config.py backend/tests/test_money.py backend/tests/test_logging.py backend/tests/test_ledger.py backend/tests/test_research_ledger.py backend/tests/test_system_state.py backend/tests/test_market_calendar.py backend/tests/test_no_order_exec.py --cov=backend.core.system_state --cov-branch --cov-fail-under=100 --cov-report=term-missing
```

### README.md

Scope: Stage A. SHA-256: f6b5fb76fbc3cebd41aaec0d129e2efe48f01b1583beba2138c6669346d3ed7f.

````markdown
# vws-core — Stage A

Read-only defensive infrastructure for long-only, whole-share research and human
trade tickets. Stage A supplies configuration guards, exact money/cent-price
helpers, UTC clocks, redacted logging, deduplicated notifications, XNYS sessions,
an immutable audit ledger, durable halt state, and an execution-code source guard.

Stage A does not run the research swarm or Telegram bot. Existing B–D drafts from
an older specification await their separate stage commands. The master project
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

## Verify Stage A

Activate the virtual environment, then use the same commands as CI:

```text
python -m ruff check .
python -m ruff format --check .
python -m backend.core.check_stage_a
python -m backend.core.source_guard .
python -m bandit -r backend/core backend/data/market_calendar.py -c pyproject.toml
python -m pip_audit -r requirements-lock.txt
python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]'
python -m pytest backend/tests/test_config_safety.py backend/tests/test_yaml_config.py backend/tests/test_money.py backend/tests/test_logging.py backend/tests/test_ledger.py backend/tests/test_research_ledger.py backend/tests/test_system_state.py backend/tests/test_market_calendar.py backend/tests/test_no_order_exec.py --cov=backend.core.system_state --cov-branch --cov-fail-under=100 --cov-report=term-missing
```

On Windows `.venv\Scripts\python.exe -m` can replace python -m. The secrets scan
emits JSON; an empty results object is required. Synthetic tests and the full
source delivery are excluded from that heuristic scan, not from the AST guard.
The guard checks all authored Python files, with only its banned-list constants
module exempt. The pre-commit configuration provides the same local source checks.

The Stage A coverage gate applies to the completed state machine. The master
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

Ledger.record_trade_ticket() is a low-level atomic audit writer. Stage F's human
gate must authenticate callbacks and revalidate fresh data before invoking it.
It does not fetch market data or authenticate a Telegram user itself.

See ASSUMPTIONS.md and VERIFY.md. The full manifest and untruncated source are in
deliveries/Stage_A.md. Continue with exactly Execute Stage B for domain contracts
and the deterministic Chief Risk Officer.
````

### ASSUMPTIONS.md

Scope: Stage A. SHA-256: 7d25b1fb7713d157a8934e5b06a08827cc9e576c38aa2bf73e96464567995621.

```markdown
# ASSUMPTIONS

The newest master spec supersedes the earlier A–D blueprint and automatic
continuation request. The current command authorizes only Stage A. Stage B starts
only after the exact command `Execute Stage B`. Order execution is permanently
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
25. Older B–D drafts are preserved, not certified against the new master spec.
    Minimal reflection/lint edits keep them compatible with the whole-source guard.
    The current Git root is Project V, so a root CI workflow mirrors the requested
    project workflow, pre-commit configuration, and .gitignore. These support
    nested or standalone project checkouts.
26. APScheduler 3.11.3 is the stable installed release with AsyncIOScheduler;
    actual scheduling is deferred to Stage F. Full source delivery uses a local
    Markdown artifact: assumptions, SHA-256 manifest, then every file in full.
27. SQLite recursive triggers are explicitly enabled to prevent REPLACE from
    deleting/replacing protected rows. State-control projections are verified
    against immutable events during live reads/transitions, not only at startup.
```

### VERIFY.md

Scope: Stage A. SHA-256: 7ce890022eead819b900835cc6f4af3df07bce2e5736a81c85d3d694474331bf.

```markdown
# Stage A verification — 2026-10-04

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
```

### config/config.yaml

Scope: Stage A. SHA-256: 2714e63536baca5dd313596df9401ff5fa5e62a81358e35749a5f9e0a1ce3d0c.

```yaml
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
```

### backend/__init__.py

Scope: Stage A. SHA-256: 0d25e37c3c72b897beabf71ef1fdcfbaf73c3874f408fc3920e3d4b6c124a84e.

```python
"""Scalp City Phase 1: deterministic, read-only defensive infrastructure."""
```

### backend/core/__init__.py

Scope: Stage A. SHA-256: 16172f1bfafe16fdd27a11fe2ffaed73525f04cf50c2bb9784c9d23ee8db4a8e.

```python
"""R-02/R-08 safety primitives and immutable audit storage."""
```

### backend/core/config.py

Scope: Stage A. SHA-256: 7427d4ee67178136522c4ffed0f67725d001c3b5e6ccbed64655d21acdf5b221.

```python
"""R-04/R-06/R-07: frozen settings, hard ceilings, and safe startup guards."""

import hashlib
import json
import re
from collections.abc import Collection, Mapping
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Literal, Self
from urllib.parse import parse_qsl, unquote, urlsplit

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from yaml.nodes import MappingNode, ScalarNode

from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.logging import register_secrets
from backend.core.money import decimal_money, validate_cent_price

PAPER_BROKER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_BROKER_ENDPOINT = "https://api.alpaca.markets"
LIVE_CONFIRMATION = "I_ACCEPT_REAL_MONEY_RISK"


def _exact_decimal(value: object) -> Decimal:
    """R-04: never convert a float or boolean into an exact setting."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise ValueError("use Decimal, decimal text, or integer; float is forbidden")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid decimal setting") from exc
    if not result.is_finite():
        raise ValueError("setting must be finite")
    return result


def _json_exact(value: object) -> object:
    """R-04: parse environment JSON numbers directly into Decimal."""
    if isinstance(value, str):
        try:
            return json.loads(value, parse_float=Decimal)
        except (ValueError, InvalidOperation) as exc:
            raise ValueError("setting requires valid JSON") from exc
    return value


class Settings(BaseSettings):
    """R-06: paper is default; unsafe overrides fail validation at startup.

    R-07: `.env` is never read implicitly. Use ``load_settings(env_file=...)``
    to deliberately load a development dotenv file. Secret fields stay masked.
    """

    model_config = SettingsConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        hide_input_in_errors=True,
        populate_by_name=True,
        case_sensitive=False,
        env_file=None,
        enable_decoding=False,
    )

    # Source constants cannot be raised by an environment variable.
    DECIMAL_BOUNDS: ClassVar[Mapping[str, tuple[Decimal, Decimal]]] = MappingProxyType(
        {
            "max_single_stock_weight": (Decimal("0"), Decimal("0.20")),
            "max_single_etf_weight": (Decimal("0"), Decimal("0.60")),
            "max_risk_per_trade": (Decimal("0"), Decimal("0.02")),
            "stop_slippage_buffer": (Decimal("0.002"), Decimal("0.01")),
            "max_gross_exposure": (Decimal("0"), Decimal("1.00")),
            "min_cash_pct": (Decimal("0.05"), Decimal("1.00")),
            "price_collar": (Decimal("0"), Decimal("0.10")),
            "min_price": (Decimal("5.00"), Decimal("1000000")),
            "max_pct_of_adv": (Decimal("0"), Decimal("0.05")),
            "daily_loss_limit": (Decimal("0"), Decimal("0.05")),
            "dd_reduce_only": (Decimal("0"), Decimal("0.15")),
            "dd_halt": (Decimal("0"), Decimal("0.25")),
            "gap_alert_pct": (Decimal("0"), Decimal("0.25")),
            "checking_buffer_usd": (Decimal("1500"), Decimal("1000000000")),
            "min_margin_equity": (Decimal("2000"), Decimal("1000000000")),
            "min_setup_score": (Decimal("6.0"), Decimal("10.0")),
            "llm_daily_budget_usd": (Decimal("0"), Decimal("1000")),
        }
    )
    INTEGER_BOUNDS: ClassVar[Mapping[str, tuple[int, int]]] = MappingProxyType(
        {
            "max_open_positions": (1, 30),
            "stale_quote_seconds": (1, 300),
            "max_clock_skew_seconds": (0, 10),
            "liquidity_ttl_seconds": (1, 3600),
            "request_timeout_seconds": (1, 60),
            "earnings_blackout_sessions": (0, 10),
            "max_alerts_per_day": (0, 20),
            "alert_cooldown_sessions": (1, 30),
            "proposal_ttl_sessions": (1, 3),
            "llm_timeout_seconds": (1, 60),
            "llm_max_tokens": (1, 8192),
            "scan_interval_minutes": (1, 1440),
            "offhours_interval_minutes": (1, 10080),
            "scheduler_misfire_grace_seconds": (1, 3600),
            "daily_bar_sip_lag_seconds": (900, 3600),
        }
    )
    SECRET_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "broker_api_key",
            "broker_secret_key",
            "plaid_client_id",
            "plaid_secret",
            "plaid_access_token",
            "fernet_key",
            "db_url",
            "llm_api_key",
            "telegram_bot_token",
            "telegram_callback_secret",
            "newsapi_key",
        }
    )

    max_single_stock_weight: Decimal = Decimal("0.10")
    max_single_etf_weight: Decimal = Decimal("0.40")
    max_risk_per_trade: Decimal = Decimal("0.01")
    stop_slippage_buffer: Decimal = Decimal("0.002")
    sector_caps: Mapping[str, Decimal] = Field(
        default_factory=lambda: {"Information Technology": Decimal("0.35")}
    )
    theme_caps: Mapping[str, Decimal] = Field(default_factory=lambda: {"AI_SEMIS": Decimal("0.25")})
    max_open_positions: int = 15
    max_gross_exposure: Decimal = Decimal("1.00")
    min_cash_pct: Decimal = Decimal("0.05")
    price_collar: Decimal = Decimal("0.03")
    min_price: Decimal = Decimal("5.00")
    max_pct_of_adv: Decimal = Decimal("0.01")
    daily_loss_limit: Decimal = Decimal("0.02")
    dd_reduce_only: Decimal = Decimal("0.08")
    dd_halt: Decimal = Decimal("0.12")
    stale_quote_seconds: int = 60
    max_clock_skew_seconds: int = 2
    gap_alert_pct: Decimal = Decimal("0.25")
    checking_buffer_usd: Decimal = Decimal("1500")
    reserved_obligations_usd: tuple[Decimal, ...] = ()
    liquidity_ttl_seconds: int = 900
    request_timeout_seconds: int = 30
    wash_sale_mode: Literal["BLOCK", "WARN"] = "BLOCK"
    day_trade_regime: Literal["INTRADAY_MARGIN", "LEGACY_PDT"] = "INTRADAY_MARGIN"
    min_margin_equity: Decimal = Decimal("2000")
    broker_account_type: Literal["CASH", "MARGIN"] = "CASH"
    paper_trading: bool = True
    live_trading_enabled: bool = False
    live_trading_confirm: str = ""
    broker_api_key: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        validation_alias=AliasChoices("BROKER_API_KEY", "ALPACA_API_KEY"),
    )
    broker_secret_key: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        validation_alias=AliasChoices("BROKER_SECRET_KEY", "ALPACA_SECRET_KEY"),
    )
    plaid_client_id: SecretStr = Field(default=SecretStr(""), repr=False)
    plaid_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    plaid_access_token: SecretStr = Field(default=SecretStr(""), repr=False)
    fernet_key: SecretStr = Field(default=SecretStr(""), repr=False)
    plaid_env: Literal["sandbox", "production"] = "sandbox"
    plaid_account_id: str = ""
    plaid_token_path: Path | None = None
    db_url: SecretStr = Field(default=SecretStr("sqlite:///vws-core.sqlite3"), repr=False)
    earnings_blackout_sessions: int = 2
    min_setup_score: Decimal = Decimal("7.0")
    max_alerts_per_day: int = 5
    alert_cooldown_sessions: int = 1
    proposal_ttl_sessions: int = 1
    enable_intraday_playbooks: bool = False
    # None is an offline-only sentinel; connected research requires explicit values.
    llm_base_url: str | None = None
    llm_model_name: str | None = None
    llm_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    llm_timeout_seconds: int = 30
    llm_max_tokens: int = 1500
    llm_daily_budget_usd: Decimal = Decimal("0")
    llm_input_cost_per_million_usd: Decimal | None = None
    llm_output_cost_per_million_usd: Decimal | None = None
    telegram_bot_token: SecretStr = Field(default=SecretStr(""), repr=False)
    telegram_allowed_user_ids: tuple[int, ...] = ()
    telegram_callback_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    newsapi_key: SecretStr = Field(default=SecretStr(""), repr=False)
    scan_interval_minutes: int = 15
    offhours_interval_minutes: int = 60
    scheduler_misfire_grace_seconds: int = 60
    daily_bar_sip_lag_seconds: int = 900

    @field_validator(*DECIMAL_BOUNDS.keys(), mode="before")
    @classmethod
    def validate_decimal_limit(cls, value: object, info: ValidationInfo) -> Decimal:
        """R-04/R-06: enforce finite exact limits and fixed safety bounds."""
        result = _exact_decimal(value)
        lower, upper = cls.DECIMAL_BOUNDS[str(info.field_name)]
        if not lower <= result <= upper:
            raise ValueError(f"{info.field_name} must be between {lower} and {upper}")
        if info.field_name in {
            "min_price",
            "checking_buffer_usd",
            "min_margin_equity",
            "llm_daily_budget_usd",
        }:
            try:
                decimal_money(result)
            except DataIntegrityError as exc:
                raise ValueError("monetary setting requires micro-unit precision") from exc
        if info.field_name == "min_price":
            try:
                validate_cent_price(result)
            except DataIntegrityError as exc:
                raise ValueError("minimum price requires cent precision") from exc
        return result

    @field_validator(
        "llm_input_cost_per_million_usd", "llm_output_cost_per_million_usd", mode="before"
    )
    @classmethod
    def validate_llm_rate(cls, value: object) -> Decimal | None:
        """GD-01/R-04: unknown prices stay unknown; supplied rates are exact."""
        if value is None:
            return None
        result = _exact_decimal(value)
        if not Decimal("0") <= result <= Decimal("1000"):
            raise ValueError("LLM cost rate must be between 0 and 1000 USD per million tokens")
        return result

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_url(cls, value: str | None) -> str | None:
        """GD-01/R-07: configurable HTTPS endpoints cannot hide credentials."""
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or any(char.isspace() for char in value)
            ):
                raise ValueError("unsafe LLM URL")
            _ = parsed.port
        except ValueError as exc:
            raise ValueError(
                "LLM_BASE_URL requires an HTTPS URL without credentials or query"
            ) from exc
        return value

    @field_validator("llm_model_name")
    @classmethod
    def validate_llm_model_name(cls, value: str | None) -> str | None:
        """GD-01: an explicit, nonempty model is mandatory for connected use."""
        if value is not None and (
            not value or value != value.strip() or len(value) > 200 or not value.isprintable()
        ):
            raise ValueError("LLM_MODEL_NAME must be a nonempty trimmed model name")
        return value

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def validate_telegram_allowlist(cls, value: object) -> tuple[int, ...]:
        """R-14/GD-05: allowlisted user IDs are unique, strict positive integers."""
        parsed = _json_exact(value)
        if not isinstance(parsed, (tuple, list)):
            raise ValueError("Telegram allowlist requires a JSON array")
        result: list[int] = []
        for user_id in parsed:
            if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
                raise ValueError("Telegram user IDs require positive integers")
            if user_id > 2**63 - 1 or user_id in result:
                raise ValueError("Telegram user IDs require unique 64-bit positive integers")
            result.append(user_id)
        return tuple(result)

    @field_validator(*INTEGER_BOUNDS.keys(), mode="before")
    @classmethod
    def validate_integer_limit(cls, value: object, info: ValidationInfo) -> int:
        """R-06: reject booleans, fractions, and values beyond source bounds."""
        if isinstance(value, str) and value.isdecimal():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("integer setting requires a whole integer")
        lower, upper = cls.INTEGER_BOUNDS[str(info.field_name)]
        if not lower <= value <= upper:
            raise ValueError(f"{info.field_name} must be between {lower} and {upper}")
        return value

    @field_validator("sector_caps", "theme_caps", mode="before")
    @classmethod
    def validate_cap_mapping(cls, value: object, info: ValidationInfo) -> object:
        """CRO-05/R-04: validate all cap values without float conversion."""
        parsed = _json_exact(value)
        if not isinstance(parsed, Mapping) or not parsed:
            raise ValueError("cap mapping must be a nonempty JSON object")
        ceiling = Decimal("0.50") if info.field_name == "sector_caps" else Decimal("0.40")
        result: dict[str, Decimal] = {}
        for key, raw in parsed.items():
            if not isinstance(key, str) or not key.strip() or key != key.strip():
                raise ValueError("cap keys must be nonempty trimmed names")
            cap = _exact_decimal(raw)
            if not Decimal("0") <= cap <= ceiling:
                raise ValueError(f"each {info.field_name} cap must be between 0 and {ceiling}")
            result[key] = cap
        return result

    @field_validator("sector_caps", "theme_caps", mode="after")
    @classmethod
    def freeze_cap_mapping(cls, value: Mapping[str, Decimal]) -> Mapping[str, Decimal]:
        """R-03: prevent nested settings mutation after startup."""
        return MappingProxyType(dict(value))

    @field_serializer("sector_caps", "theme_caps")
    def serialize_cap_mapping(self, value: Mapping[str, Decimal]) -> dict[str, str]:
        """R-04: preserve exact decimals in canonical JSON."""
        return {key: _canonical_decimal(cap) for key, cap in value.items()}

    @field_validator("reserved_obligations_usd", mode="before")
    @classmethod
    def validate_reserved_obligations(cls, value: object) -> tuple[Decimal, ...]:
        """CRO-12/R-04: reservations are immutable nonnegative exact amounts."""
        parsed = _json_exact(value)
        if not isinstance(parsed, (tuple, list)):
            raise ValueError("reservations require a JSON array")
        result: list[Decimal] = []
        for item in parsed:
            try:
                amount = decimal_money(_exact_decimal(item))
            except DataIntegrityError as exc:
                raise ValueError("reservation is not representable money") from exc
            if amount < 0:
                raise ValueError("reservations cannot be negative")
            result.append(amount)
        with localcontext() as context:
            context.prec = 40
            total = sum(result, Decimal("0"))
        if total > Decimal("1000000000"):
            raise ValueError("total reservations exceed the absolute ceiling")
        return tuple(result)

    @field_validator(
        "paper_trading", "live_trading_enabled", "enable_intraday_playbooks", mode="before"
    )
    @classmethod
    def validate_mode_flag(cls, value: object) -> bool:
        """R-06: accept explicit booleans only; reject truthy typos."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.casefold() in {"true", "false"}:
            return value.casefold() == "true"
        raise ValueError("mode flag must be true or false")

    @field_validator("db_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        """R-07: keep credential-bearing database URLs masked and validated."""
        raw = value.get_secret_value()
        try:
            parsed = urlsplit(raw)
            valid_scheme = parsed.scheme in {
                "sqlite",
                "sqlite+pysqlite",
                "postgresql",
                "postgresql+psycopg",
                "postgresql+psycopg2",
            }
            if not valid_scheme or not parsed.path or any(char.isspace() for char in raw):
                raise ValueError("unsupported or incomplete database URL")
            if parsed.scheme.startswith("postgresql") and not parsed.hostname:
                raise ValueError("PostgreSQL URL requires a host")
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("invalid database URL") from exc
        return value

    @model_validator(mode="after")
    def validate_startup(self) -> Self:
        """R-06: enforce live consent, keys, and drawdown-tier ordering."""
        if self.dd_reduce_only >= self.dd_halt:
            raise ValueError("DD_REDUCE_ONLY must be below DD_HALT")
        if (
            "telegram_allowed_user_ids" in self.model_fields_set
            and not self.telegram_allowed_user_ids
        ):
            raise ValueError("an explicitly configured Telegram allowlist cannot be empty")
        if not self.paper_trading:
            if not self.live_trading_enabled:
                raise ValueError("live mode requires LIVE_TRADING_ENABLED=true")
            if self.live_trading_confirm != LIVE_CONFIRMATION:
                raise ValueError("live mode requires exact LIVE_TRADING_CONFIRM")
            if not self.broker_api_key.get_secret_value().strip():
                raise ValueError("live mode requires a broker API key")
            if not self.broker_secret_key.get_secret_value().strip():
                raise ValueError("live mode requires a broker secret key")
        register_secrets(*(self.__dict__[name] for name in self.SECRET_FIELDS))
        database_url = urlsplit(self.db_url.get_secret_value())
        if database_url.password:
            register_secrets(unquote(database_url.password))
        for key, value in parse_qsl(database_url.query):
            if any(part in key.casefold() for part in ("password", "token", "secret", "key")):
                register_secrets(value)
        return self

    def assert_research_ready(self) -> None:
        """GD-01/R-02: connected research must supply endpoint, model, and key."""
        if (
            self.llm_base_url is None
            or self.llm_model_name is None
            or not self.llm_api_key.get_secret_value().strip()
        ):
            raise ConfigurationError("connected research requires LLM URL, model, and API key")

    def assert_llm_call_budget_ready(self) -> None:
        """GD-01: zero budgets and unknown cost rates prohibit budgeted calls."""
        self.assert_research_ready()
        if self.llm_daily_budget_usd <= 0:
            raise ConfigurationError("LLM calls are disabled by a zero daily budget")
        if (
            self.llm_input_cost_per_million_usd is None
            or self.llm_output_cost_per_million_usd is None
        ):
            raise ConfigurationError("LLM calls require explicit input and output token cost rates")

    def assert_telegram_ready(self) -> None:
        """R-14/GD-05: production callbacks cannot start without an allowlist."""
        if (
            not self.telegram_bot_token.get_secret_value().strip()
            or not self.telegram_allowed_user_ids
            or len(self.telegram_callback_secret.get_secret_value().encode("utf-8")) < 32
            or not self.telegram_callback_secret.get_secret_value().strip()
        ):
            raise ConfigurationError(
                "Telegram requires a bot token, nonempty user allowlist, and 32-byte callback secret"
            )

    @property
    def broker_endpoint(self) -> str:
        """R-06: derive the sole permissible trading endpoint from mode."""
        return PAPER_BROKER_ENDPOINT if self.paper_trading else LIVE_BROKER_ENDPOINT

    def nonsecret_snapshot(self) -> dict[str, object]:
        """R-07: canonical configuration without keys or database credentials."""
        result: dict[str, object] = {}
        for name in type(self).model_fields:
            if name not in self.SECRET_FIELDS:
                result[name] = _canonical_value(self.__dict__[name])
        url = urlsplit(self.db_url.get_secret_value())
        result["database_identity"] = {
            "driver": url.scheme,
            "host": url.hostname,
            "port": url.port,
            "database": url.path,
        }
        return result

    @property
    def config_hash(self) -> str:
        """R-03/R-07: stamp canonical nonsecret policy on every verdict."""
        encoded = json.dumps(
            self.nonsecret_snapshot(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def with_yaml_hash(self, yaml_config: "YamlConfig") -> str:
        """R-03/GD-02: combine nonsecret env policy and validated research YAML."""
        yaml_config.assert_settings_consistent(self)
        payload = {"settings": self.nonsecret_snapshot(), "yaml": yaml_config.nonsecret_snapshot()}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_decimal(value: Decimal) -> str:
    """R-04: use identical text for numerically identical finite decimals."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if value == 0 else text


def _canonical_value(value: object) -> object:
    """R-07: recursively encode exact immutable configuration values."""
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseModel):
        return {name: _canonical_value(value.__dict__[name]) for name in type(value).model_fields}
    return value


def assert_broker_endpoint(settings: Settings, resolved_endpoint: str) -> None:
    """R-06: assert the initialized SDK client's exact mode-specific endpoint.

    Accept one trailing slash only. Reject paths, query strings, alternate hosts,
    and endpoint switches. The read-only broker adapter must call this at startup.
    """
    if not isinstance(resolved_endpoint, str):
        raise ConfigurationError("broker endpoint must be a string")
    if resolved_endpoint.removesuffix("/") != settings.broker_endpoint:
        raise ConfigurationError("broker endpoint does not match configured trading mode")


def load_settings(env_file: str | Path | None = None, **overrides: Any) -> Settings:
    """R-06/R-07: explicitly load dotenv only when requested; fail typed."""
    try:
        values: dict[str, Any] = {"_env_file": env_file, **overrides}
        return Settings(**values)
    except (ValidationError, ValueError, TypeError, OSError) as exc:
        raise ConfigurationError("configuration validation failed") from exc


class _FrozenYamlModel(BaseModel):
    """R-03/GD-02: YAML policy objects are strict and recursively immutable."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        hide_input_in_errors=True,
    )


class ScheduleConfig(_FrozenYamlModel):
    """GD-04: bounded deterministic schedule, without risk controls."""

    scan_interval_minutes: int = 15
    offhours_interval_minutes: int = 60
    scheduler_misfire_grace_seconds: int = 60
    daily_bar_sip_lag_seconds: int = 900

    @field_validator(
        "scan_interval_minutes",
        "offhours_interval_minutes",
        "scheduler_misfire_grace_seconds",
        "daily_bar_sip_lag_seconds",
        mode="before",
    )
    @classmethod
    def validate_interval(cls, value: object, info: ValidationInfo) -> int:
        """GD-04/R-02: YAML intervals share source ceilings with env settings."""
        return Settings.validate_integer_limit(value, info)


class AlertConfig(_FrozenYamlModel):
    """GD-04: a session cooldown suppresses repeated setup cards."""

    alert_cooldown_sessions: int = 1

    @field_validator("alert_cooldown_sessions", mode="before")
    @classmethod
    def validate_cooldown(cls, value: object, info: ValidationInfo) -> int:
        """GD-04: require at least one session between repeated cards."""
        return Settings.validate_integer_limit(value, info)


class PlaybookConfig(_FrozenYamlModel):
    """GD-02/R-04: exact weights and reproducible ATR/target parameters."""

    criteria_weights: Mapping[str, Decimal]
    stop_atr_mult: Decimal = Decimal("2.0")
    target_r: Decimal = Decimal("2.0")

    @field_validator("criteria_weights", mode="before")
    @classmethod
    def validate_weights(cls, value: object) -> Mapping[str, Decimal]:
        """GD-02: criterion weights must be positive and sum to exactly one."""
        if not isinstance(value, Mapping) or not 1 <= len(value) <= 32:
            raise ValueError("criteria_weights requires 1 to 32 named criteria")
        _reject_yaml_risk_keys(value)
        result: dict[str, Decimal] = {}
        for name, raw in value.items():
            if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) is None:
                raise ValueError("criterion names require lowercase identifiers")
            weight = _exact_decimal(raw)
            if not Decimal("0") < weight <= Decimal("1"):
                raise ValueError("criterion weights must be in (0, 1]")
            try:
                decimal_money(weight)
            except DataIntegrityError as exc:
                raise ValueError("criterion weights require at most six decimal places") from exc
            result[name] = weight
        with localcontext() as context:
            context.prec = 40
            total = sum(result.values(), Decimal("0"))
        if total != Decimal("1"):
            raise ValueError("criterion weights must sum to exactly 1")
        return result

    @field_validator("criteria_weights", mode="after")
    @classmethod
    def freeze_weights(cls, value: Mapping[str, Decimal]) -> Mapping[str, Decimal]:
        """R-03: freeze weights after Pydantic has copied the mapping."""
        return MappingProxyType(dict(value))

    @field_validator("stop_atr_mult", "target_r", mode="before")
    @classmethod
    def validate_levels(cls, value: object, info: ValidationInfo) -> Decimal:
        """GD-02/R-04: reject invalid levels instead of repairing parameters."""
        result = _exact_decimal(value)
        lower = Decimal("0.5") if info.field_name == "stop_atr_mult" else Decimal("1.5")
        if not lower <= result <= Decimal("10"):
            raise ValueError(f"{info.field_name} must be between {lower} and 10")
        return result

    @field_serializer("criteria_weights")
    def serialize_weights(self, value: Mapping[str, Decimal]) -> dict[str, str]:
        """R-04: preserve exact weights in JSON snapshots."""
        return {name: _canonical_decimal(weight) for name, weight in value.items()}


class YamlConfig(_FrozenYamlModel):
    """GD-02/R-03: research configuration cannot modify env risk limits."""

    watchlist: tuple[str, ...]
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    playbooks: Mapping[str, PlaybookConfig]

    @model_validator(mode="before")
    @classmethod
    def reject_risk_limits(cls, value: object) -> object:
        """R-06: reject risk keys even when concealed in nested dictionaries."""
        _reject_yaml_risk_keys(value)
        return value

    @field_validator("watchlist", mode="before")
    @classmethod
    def validate_watchlist(cls, value: object) -> tuple[str, ...]:
        """R-02: keep explicit known symbol identities, without normalization."""
        if not isinstance(value, (tuple, list)) or not 1 <= len(value) <= 1000:
            raise ValueError("watchlist requires 1 to 1000 symbols")
        result: list[str] = []
        for symbol in value:
            if (
                not isinstance(symbol, str)
                or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) is None
            ):
                raise ValueError("watchlist symbols must be uppercase US instrument identifiers")
            if symbol in result:
                raise ValueError("watchlist symbols cannot be duplicated")
            result.append(symbol)
        return tuple(result)

    @field_validator("playbooks", mode="after")
    @classmethod
    def validate_playbooks(
        cls, value: Mapping[str, PlaybookConfig]
    ) -> Mapping[str, PlaybookConfig]:
        """GD-02: only the three specified daily playbooks are configurable."""
        expected = {"TREND_50EMA", "BASE_BREAKOUT", "ANCHORED_VWAP_RECLAIM"}
        if set(value) != expected:
            raise ValueError("playbooks must define exactly the three supported daily strategies")
        return MappingProxyType(dict(value))

    @field_serializer("playbooks")
    def serialize_playbooks(self, value: Mapping[str, PlaybookConfig]) -> dict[str, object]:
        """GD-02: canonicalize the immutable playbook map for audit snapshots."""
        return {name: _canonical_value(playbook) for name, playbook in value.items()}

    def assert_allowed_symbols(self, allowed_symbols: Collection[str]) -> None:
        """R-02: authoritative instrument symbols must cover the full watchlist."""
        if not allowed_symbols or not set(self.watchlist).issubset(set(allowed_symbols)):
            raise ConfigurationError("watchlist contains an unknown or unconfigured instrument")

    def assert_settings_consistent(self, settings: Settings) -> None:
        """R-02/GD-04: conflicting explicit env schedules/cooldowns fail startup."""
        policy = {
            **self.schedule.__dict__,
            "alert_cooldown_sessions": self.alerts.alert_cooldown_sessions,
        }
        for name, value in policy.items():
            if name in settings.model_fields_set and settings.__dict__[name] != value:
                raise ConfigurationError(
                    "environment and YAML schedule/cooldown definitions conflict"
                )

    def nonsecret_snapshot(self) -> dict[str, object]:
        """R-03/GD-02: deterministic exact-value snapshot suitable for hashing."""
        return {name: _canonical_value(self.__dict__[name]) for name in type(self).model_fields}

    @property
    def config_hash(self) -> str:
        """R-03: include all strategy parameters in research configuration identity."""
        encoded = json.dumps(
            self.nonsecret_snapshot(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


YAML_ALLOWED_SETTING_NAMES = frozenset(
    {
        "scan_interval_minutes",
        "offhours_interval_minutes",
        "scheduler_misfire_grace_seconds",
        "daily_bar_sip_lag_seconds",
        "alert_cooldown_sessions",
    }
)
YAML_FORBIDDEN_SETTING_NAMES = frozenset(Settings.model_fields) - YAML_ALLOWED_SETTING_NAMES


def _reject_yaml_risk_keys(value: object, depth: int = 0) -> None:
    """R-06/R-12: no secret/env risk keys, recursion, or deeply nested input."""
    if depth > 20:
        raise ValueError("YAML nesting exceeds the configuration limit")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("YAML mapping keys must be strings")
            normalized = key.strip().casefold().replace("-", "_")
            if normalized in YAML_FORBIDDEN_SETTING_NAMES:
                raise ValueError("YAML cannot contain env risk, credential, or runtime settings")
            _reject_yaml_risk_keys(item, depth + 1)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _reject_yaml_risk_keys(item, depth + 1)


class _ExactSafeLoader(yaml.SafeLoader):
    """R-04/R-12: safe YAML with exact decimals and no ambiguous duplicates."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[object, object]:
        """R-02: duplicate mapping keys cannot silently override prior policy."""
        keys: set[object] = set()
        for key_node, _value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                raise ValueError("YAML mapping keys must be scalars")
            key = self.construct_object(key_node, deep=deep)
            if key in keys:
                raise ValueError("duplicate YAML mapping key")
            keys.add(key)
        return dict(super().construct_mapping(node, deep=deep))


def _yaml_decimal(loader: _ExactSafeLoader, node: ScalarNode) -> Decimal:
    """R-04: YAML decimal scalars never pass through a binary float."""
    return _exact_decimal(loader.construct_scalar(node))


_ExactSafeLoader.add_constructor("tag:yaml.org,2002:float", _yaml_decimal)


def load_yaml_config(
    path: str | Path,
    *,
    allowed_symbols: Collection[str],
    settings: Settings | None = None,
) -> YamlConfig:
    """GD-02/R-02: safely load frozen YAML and enforce instrument/env identity."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        if len(raw.encode("utf-8")) > 1_048_576:
            raise ValueError("YAML configuration exceeds one MiB")
        depth = 0
        for token in yaml.scan(raw):
            if isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)):
                raise ValueError("YAML aliases and anchors are forbidden")
            if isinstance(
                token,
                (
                    yaml.tokens.BlockMappingStartToken,
                    yaml.tokens.BlockSequenceStartToken,
                    yaml.tokens.FlowMappingStartToken,
                    yaml.tokens.FlowSequenceStartToken,
                ),
            ):
                depth += 1
                if depth > 20:
                    raise ValueError("YAML nesting exceeds the configuration limit")
            elif isinstance(
                token,
                (
                    yaml.tokens.BlockEndToken,
                    yaml.tokens.FlowMappingEndToken,
                    yaml.tokens.FlowSequenceEndToken,
                ),
            ):
                depth -= 1
        # SafeLoader subclass: no arbitrary Python object constructors.
        parsed = yaml.load(raw, Loader=_ExactSafeLoader)  # nosec B506
        config = YamlConfig.model_validate(parsed)
        config.assert_allowed_symbols(allowed_symbols)
        if settings is not None:
            config.assert_settings_consistent(settings)
        return config
    except (yaml.YAMLError, ValidationError, ValueError, TypeError, OSError) as exc:
        raise ConfigurationError("YAML configuration validation failed") from exc
```

### backend/core/clock.py

Scope: Stage A. SHA-256: 1903f9789454b57df2c6d5a9c85b3f7b1f8772da6edda0327386a85667446930.

```python
"""R-05: injectable clocks and a single aware-UTC timestamp boundary."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from backend.core.errors import DataIntegrityError


def ensure_utc(value: datetime) -> datetime:
    """R-05/DAT-02: reject naive timestamps and normalize aware ones to UTC."""
    if not isinstance(value, datetime):
        raise DataIntegrityError("timestamp must be a datetime")
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            raise DataIntegrityError("timestamp must be timezone-aware")
        return value.astimezone(UTC)
    except DataIntegrityError:
        raise
    except Exception as exc:
        raise DataIntegrityError("timestamp could not be normalized to UTC") from exc


class Clock(Protocol):
    """R-05: rules receive time rather than reading the system clock."""

    def now(self) -> datetime:
        """Return a timezone-aware UTC timestamp."""
        raise NotImplementedError("Clock implementations must supply now")


class SystemClock:
    """R-05: the only core boundary permitted to read wall-clock time."""

    def now(self) -> datetime:
        """R-05: read wall-clock time in UTC."""
        return datetime.now(UTC)


@dataclass(frozen=True)
class FrozenClock:
    """R-05: an immutable deterministic clock for tests and replay."""

    current: datetime

    def __post_init__(self) -> None:
        """R-05: validate and normalize the supplied instant once."""
        object.__setattr__(self, "current", ensure_utc(self.current))

    def now(self) -> datetime:
        """R-05: return the injected instant without consulting the system."""
        return self.current
```

### backend/core/errors.py

Scope: Stage A. SHA-256: 7b5e510980157cea2690298a5d7d19be33aeda257b8829822f5943bcb65675eb.

```python
"""Typed failure vocabulary for R-02 fail-closed boundaries."""


class SafetyError(Exception):
    """R-02: a failure that callers must convert into a veto or halt."""

    def __init__(self, message: str) -> None:
        """R-07: never expose configured credentials in typed failures."""
        from backend.core.logging import redact

        super().__init__(str(redact(message)))


class ConfigurationError(SafetyError):
    """R-06/R-07: configuration cannot safely start the application."""


class DataIntegrityError(SafetyError):
    """R-02/DAT-02: a value is missing, malformed, or unverifiable."""


class StaleDataError(DataIntegrityError):
    """R-02/DAT-01: required data is too old for its trading session."""


class LedgerIntegrityError(SafetyError):
    """R-02: ledger references, invariants, or hash chains failed."""


class AppendOnlyError(LedgerIntegrityError):
    """R-02: an attempt was made to alter an immutable ledger row."""


class DatabaseError(SafetyError):
    """R-02: persistence failed and its outcome must not be assumed."""


class StateTransitionError(SafetyError):
    """R-02/R-09: a requested state transition is unauthorized."""


class ReconciliationError(LedgerIntegrityError):
    """R-02: observed broker holdings differ from ledger holdings."""


class CalendarError(SafetyError):
    """R-02/DAT-01: the exchange session cannot be verified."""


class LiquidityUnavailable(SafetyError):
    """R-02/CRO-12: required checking balance information is unavailable."""


class ProviderError(SafetyError):
    """R-02/DAT-04: an external read could not produce trusted data."""
```

### backend/core/money.py

Scope: Stage A. SHA-256: 491a267134a3d1ada08d05b5de0841b1f405406bcddfe08ab2cd7160f60e7add.

```python
"""R-04: exact Decimal money and signed-64-bit micro-unit storage."""

from decimal import Decimal, InvalidOperation, localcontext

from backend.core.errors import DataIntegrityError

MONEY_SCALE = 1_000_000
MIN_SCALED_MONEY = -(2**63)
MAX_SCALED_MONEY = 2**63 - 1
MoneyInput = Decimal | str | int
CENT = Decimal("0.01")


def validate_cent_price(value: Decimal) -> Decimal:
    """R-13/R-02: require a positive exact Decimal cent price at boundaries.

    Reject sub-cent input instead of silently rounding a proposed price. General
    account money and costs still use R-04 micro-units, independently of prices.
    """
    if not isinstance(value, Decimal):
        raise DataIntegrityError("R-13: price must be a Decimal")
    result = decimal_money(value)
    if result <= 0:
        raise DataIntegrityError("R-13: price must be positive")
    with localcontext() as context:
        context.prec = 40
        quantized = result.quantize(CENT)
    if result != quantized:
        raise DataIntegrityError("R-13: price has sub-cent precision")
    return quantized


def decimal_money(value: MoneyInput) -> Decimal:
    """R-04: accept exact values only, with finite micro-unit precision."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise DataIntegrityError("money requires Decimal, decimal text, or integer")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise DataIntegrityError("money is not valid decimal text") from exc
    if not result.is_finite():
        raise DataIntegrityError("money must be finite")
    _scaled(result)
    return result


def _scaled(value: Decimal) -> int:
    """R-04: scale exactly without ambient Decimal-context rounding."""
    if value == 0:
        return 0
    if value < Decimal("-9223372036854.775808") or value > Decimal("9223372036854.775807"):
        raise DataIntegrityError("money exceeds signed 64-bit storage")
    parts = value.as_tuple()
    trailing_zeros = 0
    for digit in reversed(parts.digits):
        if digit != 0:
            break
        trailing_zeros += 1
    if not isinstance(parts.exponent, int) or parts.exponent + trailing_zeros < -6:
        raise DataIntegrityError("money has precision below one micro-unit")
    with localcontext() as context:
        context.prec = max(40, len(value.as_tuple().digits) + 10)
        scaled = value * MONEY_SCALE
        if scaled != scaled.to_integral_value():
            raise DataIntegrityError("money has precision below one micro-unit")
        if scaled < MIN_SCALED_MONEY or scaled > MAX_SCALED_MONEY:
            raise DataIntegrityError("money exceeds signed 64-bit storage")
        return int(scaled)


def money_to_scaled(value: MoneyInput) -> int:
    """R-04: convert validated money into exact integer micro-units."""
    return _scaled(decimal_money(value))


def scaled_to_money(value: int) -> Decimal:
    """R-04: recover exact money; reject coercion and integer overflow."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataIntegrityError("scaled money must be an integer")
    if value < MIN_SCALED_MONEY or value > MAX_SCALED_MONEY:
        raise DataIntegrityError("scaled money exceeds signed 64-bit storage")
    with localcontext() as context:
        context.prec = 40
        return Decimal(value) / MONEY_SCALE
```

### backend/core/logging.py

Scope: Stage A. SHA-256: 39a84aff1564ccdf7f3f48c521cf1af5ad680f9d75eb191e2eda64d13ebd6247.

```python
"""R-07: recursively redact credentials before structured log rendering."""

import logging
import re
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from pydantic import SecretStr

REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|credential|"
    r"fernet|db[_-]?url)",
    re.IGNORECASE,
)
_URL_PASSWORD = re.compile(r"(://[^\s:/@]+:)[^\s@]+(@)")
_KNOWN_SECRETS: tuple[str, ...] = ()


def register_secrets(*secrets: SecretStr | str) -> None:
    """R-07: register configured values for free-text redaction."""
    global _KNOWN_SECRETS
    values = set(_KNOWN_SECRETS)
    for secret in secrets:
        raw = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        if raw:
            values.add(raw)
    _KNOWN_SECRETS = tuple(sorted(values, key=len, reverse=True))


def _redact_text(value: str) -> str:
    """R-07: scrub configured secrets and credential-bearing URL passwords."""
    for secret in _KNOWN_SECRETS:
        value = value.replace(secret, REDACTED)
    return _URL_PASSWORD.sub(r"\1[REDACTED]\2", value)


def redact(value: object) -> object:
    """R-07: redact nested fields without mutating the caller's payload."""
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {
            _redact_text(str(key)): REDACTED if _SECRET_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item) for item in value]
    if isinstance(value, BaseException):
        return _redact_text(str(value))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    # Never let a renderer invoke arbitrary __repr__ after this redaction stage.
    return REDACTED


def redact_processor(
    logger: object, method_name: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """R-07: structlog processor applied after exception formatting."""
    return {
        _redact_text(str(key)): REDACTED if _SECRET_KEY.search(str(key)) else redact(item)
        for key, item in event_dict.items()
    }


def configure_logging(*secrets: SecretStr | str) -> None:
    """R-07: install redaction before JSON output and register known secrets."""
    register_secrets(*secrets)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for handler in logging.getLogger().handlers:
        handler.setFormatter(RedactingFormatter("%(message)s"))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


class RedactingFormatter(logging.Formatter):
    """R-07: scrub SDK standard-logging messages and rendered tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        """R-07: redact after interpolation and exception rendering."""
        return _redact_text(super().format(record))
```

### backend/core/notifier.py

Scope: Stage A. SHA-256: 4358bac1cb6ccc13c590b21772a710de9a9370bb7ab9d20286b28eacf8423f48.

```python
"""R-02: injectable notifications for each persisted halt."""

from threading import Lock
from typing import Protocol

import structlog

from backend.core.logging import redact


class Notifier(Protocol):
    """R-02: notifications are boundary effects, never risk-rule decisions."""

    def notify(self, state: str, reason: str) -> None:
        """R-02: report a state escalation and its reason."""
        raise NotImplementedError("Notifier implementations must supply notify")


class ConsoleNotifier:
    """R-02/R-07: emit structured console notifications through redaction."""

    def notify(self, state: str, reason: str) -> None:
        """R-02: report an escalation to the configured structured logger."""
        structlog.get_logger("vws.safety").critical(
            "system_state_notification", state=redact(state), reason=redact(reason)
        )


class DeduplicatingNotifier:
    """R-02/R-07: deliver each redacted state/reason once per halt episode.

    Failed deliveries are retried, not marked delivered. Resetting the cache is
    explicit so an operator reset permits another notification for a new halt.
    """

    def __init__(self, delegate: Notifier) -> None:
        self.delegate = delegate
        self._delivered: set[tuple[str, str]] = set()
        self._lock = Lock()

    def notify(self, state: str, reason: str) -> None:
        """R-02: serialize deduplication and remember successful delivery only."""
        key = (str(redact(state)), str(redact(reason)))
        with self._lock:
            if key not in self._delivered:
                self.delegate.notify(*key)
                self._delivered.add(key)

    def reset(self) -> None:
        """R-02: begin a fresh notification episode after audited recovery."""
        with self._lock:
            self._delivered.clear()
```

### backend/core/database.py

Scope: Stage A. SHA-256: 87178a5ccdfaf97710ff729dc7af2b7c8422ac2d16ad46d3b68c50611c6e1fdb.

```python
"""R-02/R-04/R-05/R-08: typed, append-only SQLAlchemy ledger storage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
    event,
    inspect,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.types import TypeDecorator

from backend.core.clock import ensure_utc
from backend.core.errors import DatabaseError, LedgerIntegrityError, SafetyError
from backend.core.money import money_to_scaled, scaled_to_money, validate_cent_price

SCHEMA_VERSION = 2


class MoneyType(TypeDecorator[Decimal]):
    """R-04: store finite Decimal money as signed 64-bit millionths."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise DatabaseError("MoneyType requires Decimal values")
        return money_to_scaled(value)

    def process_result_value(self, value: int | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else scaled_to_money(value)


class PriceType(MoneyType):
    """R-04/R-13: cent prices at ORM boundaries, millionth-unit integer storage."""

    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> int | None:
        return None if value is None else money_to_scaled(validate_cent_price(value))

    def process_result_value(self, value: int | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else validate_cent_price(scaled_to_money(value))


class UTCDateTime(TypeDecorator[datetime]):
    """R-05: validate UTC input; restore timezone metadata lost by SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else ensure_utc(value)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            if dialect.name != "sqlite":
                raise DatabaseError("Database returned a timezone-naive timestamp")
            return value.replace(tzinfo=UTC)
        return ensure_utc(value)


class Base(DeclarativeBase):
    """SQLAlchemy registry for ledger and explicitly mutable control rows."""


class LedgerRecord(Base):
    """R-02/R-05: immutable identity, global sequence and per-table chain."""

    __abstract__ = True

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DataSnapshot(LedgerRecord):
    """DAT-03: reproducible vendor data provenance without look-ahead."""

    __tablename__ = "data_snapshots"
    __table_args__ = (
        CheckConstraint("bar_count >= 0", name="ck_snapshot_bar_count"),
        CheckConstraint("range_end >= range_start", name="ck_snapshot_range"),
        CheckConstraint("feed IN ('IEX', 'SIP', 'FAKE')", name="ck_snapshot_feed"),
        CheckConstraint(
            "adjustment IN ('RAW', 'SPLIT', 'DIVIDEND', 'ALL')",
            name="ck_snapshot_adjustment",
        ),
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    range_start: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    range_end: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    feed: Mapped[str] = mapped_column(String(16), nullable=False)
    adjustment: Mapped[str] = mapped_column(String(16), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    bar_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bars: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class Signal(LedgerRecord):
    """R-01/R-08: every proposed order has an auditable signal origin."""

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint("direction IN ('BUY', 'SELL', 'HOLD')", name="ck_signal_direction"),
        CheckConstraint("signal_type IN ('SIGNAL', 'SYSTEM', 'MANUAL')", name="ck_signal_type"),
        CheckConstraint("confidence >= 0 AND confidence <= 1000000", name="ck_signal_confidence"),
    )

    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    structured_thesis: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    invalidation: Mapped[str] = mapped_column(Text, nullable=False)
    data_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("data_snapshots.id"), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Order(LedgerRecord):
    """R-01/R-08: local LIMIT proposal record; never submits to a broker."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("qty > 0 AND qty = CAST(qty AS BIGINT)", name="ck_order_qty"),
        CheckConstraint("limit_price > 0", name="ck_order_limit"),
        CheckConstraint("limit_price % 10000 = 0", name="ck_order_limit_cents"),
        CheckConstraint(
            "stop_price IS NULL OR (stop_price > 0 AND stop_price % 10000 = 0)",
            name="ck_order_stop_cents",
        ),
        CheckConstraint(
            "target_price IS NULL OR (target_price > 0 AND target_price % 10000 = 0)",
            name="ck_order_target_cents",
        ),
        CheckConstraint(
            "side != 'BUY' OR target_price IS NULL OR target_price > limit_price",
            name="ck_order_long_target",
        ),
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_order_side"),
        CheckConstraint("intent IN ('ENTRY', 'ADD', 'REDUCE', 'EXIT')", name="ck_order_intent"),
        CheckConstraint("source IN ('SIGNAL', 'SYSTEM', 'MANUAL')", name="ck_order_source"),
        CheckConstraint("order_type = 'LIMIT'", name="ck_order_type"),
        CheckConstraint(
            "(side = 'BUY' AND intent IN ('ENTRY', 'ADD')) OR "
            "(side = 'SELL' AND intent IN ('REDUCE', 'EXIT'))",
            name="ck_order_side_intent",
        ),
        CheckConstraint(
            "intent NOT IN ('ENTRY', 'ADD') OR "
            "(stop_price IS NOT NULL AND stop_price > 0 AND stop_price < limit_price)",
            name="ck_order_entry_stop",
        ),
    )

    proposal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), unique=True, nullable=False)
    signal_id: Mapped[UUID] = mapped_column(ForeignKey("signals.id"), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    intent: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Decimal] = mapped_column(PriceType(), nullable=False)
    stop_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(8), nullable=False)


class OrderEvent(LedgerRecord):
    """R-02/R-08: append lifecycle transitions instead of changing orders."""

    __tablename__ = "order_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PROPOSED', 'APPROVED', 'SUBMITTED', 'PARTIALLY_FILLED', "
            "'FILLED', 'CANCELED', 'REJECTED')",
            name="ck_order_event_state",
        ),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Fill(LedgerRecord):
    """R-04/R-08: observed whole-share fills, never execution instructions."""

    __tablename__ = "fills"
    __table_args__ = (
        CheckConstraint("qty > 0 AND qty = CAST(qty AS BIGINT)", name="ck_fill_qty"),
        CheckConstraint("price > 0", name="ck_fill_price"),
        CheckConstraint("price % 10000 = 0", name="ck_fill_price_cents"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    broker_fill_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(PriceType(), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RiskDecision(LedgerRecord):
    """R-03: verdict provenance binds an existing proposal and config."""

    __tablename__ = "risk_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('APPROVED', 'VETOED')", name="ck_risk_decision"),
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("orders.proposal_id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(8), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RiskRuleResult(LedgerRecord):
    """R-03: one complete deterministic result for each evaluated rule."""

    __tablename__ = "risk_rule_results"
    __table_args__ = (
        CheckConstraint("severity IN ('BLOCK', 'WARN')", name="ck_risk_rule_severity"),
        CheckConstraint("passed IN (0, 1)", name="ck_risk_rule_passed"),
    )

    risk_decision_id: Mapped[UUID] = mapped_column(ForeignKey("risk_decisions.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    observed: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    limit: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class ComplianceCheck(LedgerRecord):
    """CMP-01..07: compliance findings remain separate audit records."""

    __tablename__ = "compliance_checks"
    __table_args__ = (
        CheckConstraint("severity IN ('BLOCK', 'WARN')", name="ck_compliance_severity"),
        CheckConstraint("passed IN (0, 1)", name="ck_compliance_passed"),
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("orders.proposal_id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    observed: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    limit: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class PortfolioState(LedgerRecord):
    """CRO-09/CRO-10: immutable managed-account baselines and positions."""

    __tablename__ = "portfolio_state"
    __table_args__ = (
        CheckConstraint("account_type IN ('CASH', 'MARGIN')", name="ck_portfolio_account_type"),
    )

    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    account_type: Mapped[str] = mapped_column(String(8), nullable=False)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    equity: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    cash: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    settled_cash: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    positions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    high_water_mark: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    day_start_equity: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    cash_flow_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    cash_flow_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class SystemEvent(LedgerRecord):
    """R-02/R-09: persistent escalation and identified operator resets."""

    __tablename__ = "system_events"
    __table_args__ = (
        CheckConstraint("state IN ('RUNNING', 'REDUCE_ONLY', 'HALTED')", name="ck_system_state"),
        CheckConstraint(
            "event_type IN ('ESCALATE', 'OPERATOR_RESET', 'INITIALIZED')",
            name="ck_system_event_type",
        ),
        CheckConstraint(
            "event_type != 'OPERATOR_RESET' OR "
            "(operator_id IS NOT NULL AND length(trim(operator_id)) > 0)",
            name="ck_system_operator",
        ),
    )

    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    operator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)


class ConfigSnapshot(LedgerRecord):
    """R-06/R-07: only nonsecret canonical settings belong in this ledger."""

    __tablename__ = "config_snapshots"

    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Alert(LedgerRecord):
    """GD-03/GD-05/R-14: immutable proposal card; lifecycle is AlertEvent history.

    The UUID primary key is the stable logical alert_id. Initial status is
    always PENDING; delivery and approval never mutate this row.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("status = 'PENDING'", name="ck_alert_initial_status"),
        CheckConstraint("score >= 1000000 AND score <= 10000000", name="ck_alert_score"),
        CheckConstraint("expires_at > created_at", name="ck_alert_expiry"),
        CheckConstraint(
            "telegram_message_id IS NULL OR telegram_chat_id IS NOT NULL",
            name="ck_alert_message_chat",
        ),
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("orders.proposal_id"), nullable=False)
    signal_id: Mapped[UUID] = mapped_column(ForeignKey("signals.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    playbook: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    card_text: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    @property
    def alert_id(self) -> UUID:
        """R-14: stable parent identity used by reports, events and tickets."""
        return self.id


class ResearchReport(LedgerRecord):
    """GD-03: every deterministic or advisory research outcome is attributable."""

    __tablename__ = "research_reports"
    __table_args__ = (
        CheckConstraint("status IN ('OK', 'UNAVAILABLE', 'ERROR')", name="ck_research_status"),
    )

    alert_id: Mapped[UUID] = mapped_column(ForeignKey("alerts.id"), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ApprovalEvent(LedgerRecord):
    """GD-05/R-14: single-use human decision or explicit expiry/failure evidence."""

    __tablename__ = "approval_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('MANUALLY_APPROVED', 'USER_VETOED', 'EXPIRED', 'REVALIDATION_FAILED')",
            name="ck_approval_action",
        ),
        CheckConstraint(
            "action NOT IN ('MANUALLY_APPROVED', 'USER_VETOED') OR "
            "(telegram_user_id IS NOT NULL AND telegram_user_id > 0)",
            name="ck_approval_user",
        ),
    )

    alert_id: Mapped[UUID] = mapped_column(
        ForeignKey("alerts.id"), nullable=False, unique=True, index=True
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    @property
    def event_id(self) -> UUID:
        """GD-05: event_id is its immutable UUID primary key."""
        return self.id


class AlertEvent(LedgerRecord):
    """GD-05/R-14: append-only delivery and actionable approval projections."""

    __tablename__ = "alert_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PENDING', 'SENT', 'APPROVED', 'REJECTED', 'EXPIRED', "
            "'REVALIDATION_FAILED')",
            name="ck_alert_event_state",
        ),
        CheckConstraint(
            "state NOT IN ('APPROVED', 'REJECTED', 'EXPIRED', 'REVALIDATION_FAILED') OR "
            "approval_event_id IS NOT NULL",
            name="ck_alert_event_evidence",
        ),
        CheckConstraint(
            "state != 'SENT' OR (telegram_chat_id IS NOT NULL AND "
            "telegram_message_id IS NOT NULL AND telegram_message_id > 0)",
            name="ck_alert_delivery_binding",
        ),
    )

    alert_id: Mapped[UUID] = mapped_column(ForeignKey("alerts.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    approval_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approval_events.id"), nullable=True, unique=True
    )
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class TradeTicket(LedgerRecord):
    """R-10/R-13/R-14: immutable manual broker ticket, never an execution request."""

    __tablename__ = "trade_tickets"
    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_ticket_side"),
        CheckConstraint("qty > 0 AND qty = CAST(qty AS BIGINT)", name="ck_ticket_qty"),
        CheckConstraint("limit_price > 0 AND limit_price % 10000 = 0", name="ck_ticket_limit"),
        CheckConstraint(
            "stop_price IS NULL OR (stop_price > 0 AND stop_price % 10000 = 0)",
            name="ck_ticket_stop",
        ),
        CheckConstraint(
            "target_price IS NULL OR (target_price > 0 AND target_price % 10000 = 0)",
            name="ck_ticket_target",
        ),
        CheckConstraint(
            "side != 'BUY' OR (stop_price IS NOT NULL AND stop_price < limit_price)",
            name="ck_ticket_long_stop",
        ),
        CheckConstraint(
            "side != 'BUY' OR target_price IS NULL OR target_price > limit_price",
            name="ck_ticket_long_target",
        ),
        CheckConstraint("valid_until > created_at", name="ck_ticket_expiry"),
    )

    alert_id: Mapped[UUID] = mapped_column(ForeignKey("alerts.id"), nullable=False, unique=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Decimal] = mapped_column(PriceType(), nullable=False)
    stop_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ticket_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    @property
    def ticket_id(self) -> UUID:
        """R-14: ticket_id is its immutable UUID primary key."""
        return self.id


class LLMCall(LedgerRecord):
    """GD-01: exact observed costs; missing transport usage is explicitly unknown."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('VALID', 'INVALID', 'TIMEOUT', 'BUDGET')", name="ck_llm_outcome"
        ),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_llm_input_tokens"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_llm_output_tokens"),
        CheckConstraint("est_cost_usd IS NULL OR est_cost_usd >= 0", name="ck_llm_cost"),
        CheckConstraint("latency_ms >= 0", name="ck_llm_latency"),
        CheckConstraint(
            "outcome != 'VALID' OR (input_tokens IS NOT NULL AND output_tokens IS NOT NULL "
            "AND est_cost_usd IS NOT NULL)",
            name="ck_llm_valid_usage",
        ),
        CheckConstraint(
            "outcome != 'BUDGET' OR (input_tokens IS NOT NULL AND output_tokens IS NOT NULL "
            "AND est_cost_usd IS NOT NULL AND input_tokens = 0 AND output_tokens = 0 AND "
            "est_cost_usd = 0)",
            name="ck_llm_budget_no_call",
        ),
    )

    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url_host: Mapped[str] = mapped_column(String(253), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    est_cost_usd: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)


class SecurityEvent(LedgerRecord):
    """GD-05/R-12/R-14: rejected authentication, signature and replay attempts."""

    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint("length(trim(kind)) > 0", name="ck_security_kind"),
        CheckConstraint(
            "telegram_user_id IS NULL OR telegram_user_id > 0", name="ck_security_user"
        ),
    )

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class SchemaMeta(Base):
    """R-02: refuse older schemas instead of silently mixing audit contracts."""

    __tablename__ = "schema_meta"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_schema_singleton"),
        CheckConstraint("version > 0", name="ck_schema_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class SystemControl(Base):
    """R-02: mutable singleton projection, checked against system events."""

    __tablename__ = "system_control"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_control_singleton"),
        CheckConstraint("state IN ('RUNNING', 'REDUCE_ONLY', 'HALTED')", name="ck_control_state"),
        CheckConstraint("version >= 0", name="ck_control_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class AppendControl(Base):
    """R-02: transaction-locked singleton allocates a global ledger sequence."""

    __tablename__ = "append_control"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_append_singleton"),
        CheckConstraint("next_seq > 0", name="ck_append_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


LEDGER_MODELS: tuple[type[LedgerRecord], ...] = (
    DataSnapshot,
    Signal,
    Order,
    OrderEvent,
    Fill,
    RiskDecision,
    RiskRuleResult,
    ComplianceCheck,
    PortfolioState,
    SystemEvent,
    ConfigSnapshot,
    Alert,
    ResearchReport,
    ApprovalEvent,
    AlertEvent,
    TradeTicket,
    LLMCall,
    SecurityEvent,
)


def _reject_mutation(mapper: Any, connection: Connection, target: LedgerRecord) -> None:
    """R-02: ORM mutation protection is independent of database triggers."""
    raise LedgerIntegrityError(f"Append-only ledger rejects mutation of {target.__tablename__}")


for _model in LEDGER_MODELS:
    for _column in _model.__table__.columns:
        if isinstance(_column.type, MoneyType):
            cast(Table, _model.__table__).append_constraint(
                CheckConstraint(
                    f"{_column.name} IS NULL OR {_column.name} = CAST({_column.name} AS BIGINT)",
                    name=f"ck_{_model.__tablename__}_{_column.name}_integer_storage",
                )
            )
    event.listen(_model, "before_update", _reject_mutation)
    event.listen(_model, "before_delete", _reject_mutation)


def _sqlite_foreign_keys(connection: Any, connection_record: Any) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA recursive_triggers=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
    finally:
        cursor.close()


def create_database(url: str) -> Engine:
    """R-02: create SQLite/PostgreSQL storage; SQLite FKs are always enabled."""
    try:
        engine = create_engine(url, pool_pre_ping=True)
        if engine.dialect.name not in {"sqlite", "postgresql"}:
            engine.dispose()
            raise DatabaseError("Only SQLite and PostgreSQL databases are supported")
        if engine.dialect.name == "sqlite":
            event.listen(engine, "connect", _sqlite_foreign_keys)
        return engine
    except SafetyError:
        raise
    except Exception as exc:
        raise DatabaseError("Database engine initialization failed") from exc


@contextmanager
def transaction(engine: Engine) -> Iterator[Session]:
    """R-02: serialize SQLite writers; lock the allocation row on PostgreSQL."""
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            with Session(bind=connection, expire_on_commit=False) as session:
                try:
                    if engine.dialect.name == "postgresql":
                        control = session.scalar(
                            select(AppendControl).where(AppendControl.id == 1).with_for_update()
                        )
                        if control is None:
                            raise LedgerIntegrityError("Ledger allocation control is missing")
                    yield session
                    session.flush()
                    connection.commit()
                except Exception:
                    session.rollback()
                    connection.rollback()
                    raise
    except SafetyError:
        raise
    except Exception as exc:
        raise DatabaseError("Database transaction failed") from exc


def create_schema(engine: Engine) -> None:
    """R-02: initialize a fresh schema or refuse any incompatible persisted one.

    Schema upgrades need an explicit audited migration; create_all is never
    used to conceal an old database missing new columns or ledger tables.
    """
    try:
        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        if existing:
            if "schema_meta" not in existing:
                raise DatabaseError("Existing ledger needs an explicit schema migration")
            with engine.connect() as connection:
                version = connection.scalar(select(SchemaMeta.version).where(SchemaMeta.id == 1))
            if version != SCHEMA_VERSION:
                raise DatabaseError("Persisted ledger schema version is incompatible")
            if existing != set(Base.metadata.tables):
                raise DatabaseError("Persisted ledger table inventory is incompatible")
            for table in Base.metadata.sorted_tables:
                persisted_columns = {column["name"] for column in inspector.get_columns(table.name)}
                if persisted_columns != {column.name for column in table.columns}:
                    raise DatabaseError("Persisted ledger columns require an explicit migration")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            if engine.dialect.name == "postgresql":
                connection.exec_driver_sql(
                    "CREATE OR REPLACE FUNCTION vws_reject_ledger_mutation() RETURNS trigger "
                    "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'append-only ledger'; END; $$"
                )
            for model in LEDGER_MODELS:
                table = model.__tablename__
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"vws_{table}_{operation.lower()}"
                    if engine.dialect.name == "sqlite":
                        connection.exec_driver_sql(
                            f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON {table} "
                            "BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END"
                        )
                    else:
                        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
                        connection.exec_driver_sql(
                            f"CREATE TRIGGER {trigger} BEFORE {operation} ON {table} "
                            "FOR EACH ROW EXECUTE FUNCTION vws_reject_ledger_mutation()"
                        )
        with engine.begin() as connection:
            insert = sqlite_insert if engine.dialect.name == "sqlite" else postgresql_insert
            connection.execute(
                insert(SchemaMeta)
                .values(id=1, version=SCHEMA_VERSION)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            connection.execute(
                insert(SystemControl)
                .values(id=1, state="RUNNING", version=0)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            connection.execute(
                insert(AppendControl)
                .values(id=1, next_seq=1)
                .on_conflict_do_nothing(index_elements=["id"])
            )
    except SafetyError:
        raise
    except Exception as exc:
        raise DatabaseError("Database schema initialization failed") from exc
```

### backend/core/ledger.py

Scope: Stage A. SHA-256: 5362851f86007316fdda720ca8cef26b6a2f7cb1e54a12d9d7fdc073aa683c09.

```python
"""R-02/R-04/R-05/R-08: local immutable audit ledger and reconciliation.

Hash chains detect accidental corruption and unauthorized row edits, not an
administrator capable of rewriting an entire database and all its hash chains.
Use database access controls and independent backups in production.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Any, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.core.clock import Clock, ensure_utc
from backend.core.database import (
    LEDGER_MODELS,
    Alert,
    AlertEvent,
    AppendControl,
    ApprovalEvent,
    ConfigSnapshot,
    Fill,
    LedgerRecord,
    LLMCall,
    MoneyType,
    Order,
    OrderEvent,
    PortfolioState,
    ResearchReport,
    SecurityEvent,
    Signal,
    SystemControl,
    SystemEvent,
    TradeTicket,
    UTCDateTime,
    transaction,
)
from backend.core.errors import (
    DataIntegrityError,
    LedgerIntegrityError,
    ReconciliationError,
    SafetyError,
)
from backend.core.money import money_to_scaled, scaled_to_money, validate_cent_price
from backend.core.notifier import ConsoleNotifier, DeduplicatingNotifier

RecordT = TypeVar("RecordT", bound=LedgerRecord)
GENESIS_HASH = "0" * 64
_ORDER_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"PROPOSED"}),
    "PROPOSED": frozenset({"APPROVED"}),
    "APPROVED": frozenset({"SUBMITTED"}),
    "SUBMITTED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED"}),
    "PARTIALLY_FILLED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED"}),
    "FILLED": frozenset(),
    "CANCELED": frozenset(),
    "REJECTED": frozenset(),
}
_STATE_RANK = {"RUNNING": 0, "REDUCE_ONLY": 1, "HALTED": 2}
_APPROVAL_STATES = {
    "MANUALLY_APPROVED": "APPROVED",
    "USER_VETOED": "REJECTED",
    "EXPIRED": "EXPIRED",
    "REVALIDATION_FAILED": "REVALIDATION_FAILED",
}
_ALERT_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"PENDING"}),
    "PENDING": frozenset({"SENT", "EXPIRED", "REVALIDATION_FAILED"}),
    "SENT": frozenset({"APPROVED", "REJECTED", "EXPIRED", "REVALIDATION_FAILED"}),
    "APPROVED": frozenset(),
    "REJECTED": frozenset(),
    "EXPIRED": frozenset(),
    "REVALIDATION_FAILED": frozenset(),
}


def _json_value(value: Any) -> Any:
    """R-04/R-05: make exact JSON; reject floats, secrets and unknown objects."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        return format(scaled_to_money(money_to_scaled(value)), "f")
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat(timespec="microseconds")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise DataIntegrityError("Ledger JSON keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise DataIntegrityError("Ledger JSON contains an unsupported or inexact value")


def canonical_json(record: LedgerRecord) -> str:
    """R-04/R-05: canonical row includes identity and sequence, excludes hashes."""
    values: dict[str, Any] = {}
    for column in record.__table__.columns:
        if column.name in {"row_hash", "prev_hash"}:
            continue
        value = record.__dict__[column.name]
        # Money hashes use stored micro-units so Decimal exponent is irrelevant.
        values[column.name] = (
            {"decimal_micro_units": money_to_scaled(value)}
            if isinstance(value, Decimal)
            else _json_value(value)
        )
    return json.dumps(
        values,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def row_digest(record: LedgerRecord) -> str:
    """R-02: bind each row to its predecessor and full canonical content."""
    return hashlib.sha256((record.prev_hash + canonical_json(record)).encode("utf-8")).hexdigest()


def ticket_digest(record: TradeTicket) -> str:
    """R-10/R-14: deterministic digest binds only immutable manual-ticket fields."""
    values = {
        "alert_id": record.alert_id,
        "symbol": record.symbol,
        "side": record.side,
        "qty": record.qty,
        "limit_price": record.limit_price,
        "stop_price": record.stop_price,
        "target_price": record.target_price,
        "valid_until": record.valid_until,
    }
    canonical = json.dumps(_json_value(values), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _valid_transition(previous: str | None, target: str) -> bool:
    return target in _ORDER_TRANSITIONS.get(previous, frozenset())


class Ledger:
    """R-02/R-08: serialize appends; no broker order or funding API exists."""

    def __init__(
        self,
        engine: Engine,
        clock: Clock,
        *,
        halt_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self._notifier = DeduplicatingNotifier(ConsoleNotifier())
        self.halt_callback = halt_callback or (
            lambda reason: self._notifier.notify("HALTED", reason)
        )

    def append(self, model_type: type[RecordT], **fields: Any) -> RecordT:
        """R-02: append one record and its automatic lifecycle evidence atomically."""
        with transaction(self.engine) as session:
            record = self.append_in_session(session, model_type, **fields)
        return record

    def append_in_session(
        self, session: Session, model_type: type[RecordT], **fields: Any
    ) -> RecordT:
        """R-02: share transaction(engine) with an atomic system-state transition.

        Callers own the transaction and must use the serialized transaction helper.
        Reserved identity/chain fields cannot be supplied by application code.
        """
        if model_type not in LEDGER_MODELS:
            raise LedgerIntegrityError("Unregistered append-only ledger record type")
        if {"id", "seq", "prev_hash", "row_hash"}.intersection(fields):
            raise LedgerIntegrityError("Ledger identity and hash fields are reserved")
        if not session.in_transaction():
            session.begin()
        try:
            control = session.scalar(
                select(AppendControl).where(AppendControl.id == 1).with_for_update()
            )
            if control is None:
                raise LedgerIntegrityError("Ledger allocation control is missing")
            normalized = dict(fields)
            if model_type is Signal:
                normalized.setdefault("signal_type", "SIGNAL")
            if model_type is Order:
                normalized.setdefault("order_type", "LIMIT")
                normalized.setdefault("target_price", None)
            if model_type.__tablename__ == "data_snapshots":
                normalized.setdefault("bars", [])
            if model_type is PortfolioState:
                normalized.setdefault("cash_flow_amount", Decimal(0))
                normalized.setdefault("cash_flow_at", None)
            if model_type is Alert:
                normalized.setdefault("status", "PENDING")
                normalized.setdefault("telegram_chat_id", None)
                normalized.setdefault("telegram_message_id", None)
            if model_type is AlertEvent:
                normalized.setdefault("approval_event_id", None)
                normalized.setdefault("telegram_chat_id", None)
                normalized.setdefault("telegram_message_id", None)
            if model_type is ResearchReport:
                normalized.setdefault("prompt_hash", None)
            if model_type is ApprovalEvent or model_type is SecurityEvent:
                normalized.setdefault("ts", self.clock.now())
                normalized.setdefault("telegram_user_id", None)
            for column in model_type.__table__.columns:
                if column.nullable:
                    normalized.setdefault(column.name, None)
                if column.name in normalized:
                    value = normalized[column.name]
                    if isinstance(value, float):
                        raise DataIntegrityError("Ledger fields reject float values")
                    if value is not None and column.name in {
                        "limit_price",
                        "stop_price",
                        "target_price",
                        "price",
                    }:
                        normalized[column.name] = validate_cent_price(value)
                    if column.type.__class__.__name__ == "JSON":
                        normalized[column.name] = _json_value(value)
                    elif isinstance(value, datetime):
                        normalized[column.name] = ensure_utc(value)
            record = model_type(**normalized)
            record.id = uuid4()
            record.seq = control.next_seq
            record.created_at = ensure_utc(normalized.get("created_at", self.clock.now()))
            previous = session.scalar(select(model_type).order_by(model_type.seq.desc()).limit(1))
            record.prev_hash = GENESIS_HASH if previous is None else previous.row_hash
            self._validate_record(session, record)
            if isinstance(record, TradeTicket):
                if "ticket_sha256" not in normalized:
                    record.ticket_sha256 = ticket_digest(record)
                elif record.ticket_sha256 != ticket_digest(record):
                    raise LedgerIntegrityError("Trade-ticket digest does not bind its exact fields")
            record.row_hash = row_digest(record)
            control.next_seq += 1
            session.add(record)
            session.flush()
            if isinstance(record, Order):
                self.append_in_session(
                    session,
                    OrderEvent,
                    order_id=record.id,
                    state="PROPOSED",
                    reason="local proposal recorded",
                    broker_order_id=None,
                )
            elif isinstance(record, Fill):
                order = session.get(Order, record.order_id)
                if order is None:
                    raise LedgerIntegrityError("Fill refers to a missing order")
                total = sum(
                    fill.qty
                    for fill in session.scalars(
                        select(Fill).where(Fill.order_id == record.order_id)
                    )
                )
                state = "FILLED" if total == order.qty else "PARTIALLY_FILLED"
                self.append_in_session(
                    session,
                    OrderEvent,
                    order_id=record.order_id,
                    state=state,
                    reason="observed fill recorded",
                    broker_order_id=None,
                )
            elif isinstance(record, Alert):
                self.append_in_session(
                    session,
                    AlertEvent,
                    alert_id=record.id,
                    state="PENDING",
                    reason="immutable alert candidate recorded",
                )
            elif isinstance(record, ApprovalEvent):
                self.append_in_session(
                    session,
                    AlertEvent,
                    alert_id=record.alert_id,
                    state=_APPROVAL_STATES[record.action],
                    approval_event_id=record.id,
                    reason="human decision or lifecycle failure recorded",
                )
            return record
        except SafetyError:
            raise
        except Exception as exc:
            raise LedgerIntegrityError("Ledger append failed; transaction must roll back") from exc

    def _validate_record(self, session: Session, record: LedgerRecord) -> None:
        self._validate_common(record)
        if isinstance(record, SystemEvent):
            prior = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()).limit(1))
            prior_state = "RUNNING" if prior is None else prior.state
            if record.state not in _STATE_RANK or prior_state not in _STATE_RANK:
                raise LedgerIntegrityError("System event requires a known operating state")
            if (
                _STATE_RANK[record.state] < _STATE_RANK[prior_state]
                and record.event_type != "OPERATOR_RESET"
            ):
                raise LedgerIntegrityError("Only an operator reset may lower the operating state")
            if record.event_type == "INITIALIZED" and (
                prior is not None or record.state != "RUNNING"
            ):
                raise LedgerIntegrityError("Initialization is allowed only once in RUNNING")
        if isinstance(record, Order):
            if isinstance(record.qty, bool) or not isinstance(record.qty, int):
                raise DataIntegrityError("Order quantity requires whole shares")
            if not isinstance(record.signal_id, UUID):
                raise LedgerIntegrityError("Order requires an explicit signal UUID")
            signal = session.get(Signal, record.signal_id)
            if signal is None or signal.symbol != record.symbol or signal.direction != record.side:
                raise LedgerIntegrityError("Order cannot be traced to a matching signal")
            if signal.signal_type != record.source:
                raise LedgerIntegrityError("Order source must match its explicit signal type")
        if isinstance(record, OrderEvent):
            previous = session.scalar(
                select(OrderEvent)
                .where(OrderEvent.order_id == record.order_id)
                .order_by(OrderEvent.seq.desc())
                .limit(1)
            )
            previous_state = None if previous is None else previous.state
            if not _valid_transition(previous_state, record.state):
                raise LedgerIntegrityError("Invalid appended order lifecycle transition")
            order = session.get(Order, record.order_id)
            if order is None:
                raise LedgerIntegrityError("Order event has no local order")
            total = sum(
                fill.qty
                for fill in session.scalars(select(Fill).where(Fill.order_id == record.order_id))
            )
            if record.state == "FILLED" and total != order.qty:
                raise LedgerIntegrityError(
                    "FILLED event requires the complete observed fill quantity"
                )
            if record.state == "PARTIALLY_FILLED" and not 0 < total < order.qty:
                raise LedgerIntegrityError("Partial event requires observed partial fills")
        if isinstance(record, Fill):
            self._validate_fill(session, record)
        if isinstance(record, ConfigSnapshot):
            self._reject_secret_fields(record.settings)
        if isinstance(record, Alert):
            order = session.scalar(select(Order).where(Order.proposal_id == record.proposal_id))
            if (
                order is None
                or order.signal_id != record.signal_id
                or order.symbol != record.symbol
                or record.status != "PENDING"
            ):
                raise LedgerIntegrityError("Alert requires the proposal's exact matching signal")
            if record.expires_at <= record.created_at or record.expires_at <= self.clock.now():
                raise LedgerIntegrityError("Alert must have a future expiry after creation")
            if record.telegram_message_id is not None:
                raise LedgerIntegrityError("Alert delivery binding belongs in a SENT event")
        if isinstance(record, ApprovalEvent):
            self._validate_approval(session, record)
        if isinstance(record, AlertEvent):
            self._validate_alert_event(session, record)
        if isinstance(record, TradeTicket):
            self._validate_ticket(session, record)

    def _validate_common(self, record: LedgerRecord, *, verifying: bool = False) -> None:
        """R-02/R-04/R-05/R-13: exact field boundaries also apply during verification."""
        for column in record.__table__.columns:
            if column.name in {"row_hash", "ticket_sha256"} and not verifying:
                continue
            value = record.__dict__.get(column.name)
            if value is None:
                if not column.nullable:
                    raise DataIntegrityError("A required ledger field is missing")
                continue
            if isinstance(value, float):
                raise DataIntegrityError("Ledger values must not contain floats")
            if isinstance(column.type, MoneyType):
                if not isinstance(value, Decimal):
                    raise DataIntegrityError("Ledger money requires Decimal")
                money_to_scaled(value)
            if isinstance(column.type, UTCDateTime):
                if not isinstance(value, datetime):
                    raise DataIntegrityError("Ledger timestamps require datetime values")
                ensure_utc(value)
            if column.type.__class__.__name__ == "JSON":
                if column.name in {"bars", "reasons"}:
                    if not isinstance(value, list):
                        raise DataIntegrityError("Ledger array fields require JSON arrays")
                elif not isinstance(value, dict):
                    raise DataIntegrityError("Ledger object fields require JSON objects")
                _json_value(value)
            if column.name in {"qty", "input_tokens", "output_tokens", "latency_ms"}:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise DataIntegrityError("Counts and whole shares require integers")
            if column.name in {"telegram_chat_id", "telegram_message_id", "telegram_user_id"}:
                if isinstance(value, bool) or not isinstance(value, int) or value == 0:
                    raise DataIntegrityError("Telegram identifiers require nonzero integers")
            if column.name in {"limit_price", "stop_price", "target_price", "price"}:
                if not isinstance(value, Decimal):
                    raise DataIntegrityError("Ledger prices require Decimal values")
                validate_cent_price(value)
            if column.name in {
                "config_hash",
                "snapshot_hash",
                "prompt_hash",
                "sha256",
                "ticket_sha256",
            }:
                if not isinstance(value, str) or len(value) != 64:
                    raise DataIntegrityError(
                        "Ledger provenance requires a SHA-256 hexadecimal digest"
                    )
                if any(character not in "0123456789abcdef" for character in value):
                    raise DataIntegrityError("Ledger provenance digest is malformed")
        if record.created_at > ensure_utc(self.clock.now()):
            raise DataIntegrityError("Ledger creation timestamp is in the future")
        if isinstance(record, LLMCall):
            self._validate_llm_call(record)
        if isinstance(record, ConfigSnapshot):
            self._reject_secret_fields(record.settings)

    @staticmethod
    def _validate_llm_call(record: LLMCall) -> None:
        """GD-01/R-02: unknown transport usage never implies a free successful call."""
        if record.outcome not in {"VALID", "INVALID", "TIMEOUT", "BUDGET"}:
            raise DataIntegrityError("LLM call requires a known outcome")
        if record.latency_ms < 0 or any(
            count is not None and count < 0 for count in (record.input_tokens, record.output_tokens)
        ):
            raise DataIntegrityError("LLM usage and latency cannot be negative")
        if record.est_cost_usd is not None and record.est_cost_usd < 0:
            raise DataIntegrityError("LLM estimated cost cannot be negative")
        if record.outcome == "VALID" and None in (
            record.input_tokens,
            record.output_tokens,
            record.est_cost_usd,
        ):
            raise DataIntegrityError("Valid LLM calls require accountable usage and cost")
        if record.outcome == "BUDGET" and (
            record.input_tokens != 0
            or record.output_tokens != 0
            or record.est_cost_usd != Decimal(0)
        ):
            raise DataIntegrityError("Budget veto is a zero-cost no-call outcome")
        if not record.provider.strip() or not record.model.strip():
            raise DataIntegrityError("LLM call requires an explicit provider and model")
        host = record.base_url_host
        if not host or any(character in host for character in "/:@?# "):
            raise DataIntegrityError("LLM audit stores only the base URL hostname")

    @staticmethod
    def _latest_alert_event(session: Session, alert_id: UUID) -> AlertEvent | None:
        return session.scalar(
            select(AlertEvent)
            .where(AlertEvent.alert_id == alert_id)
            .order_by(AlertEvent.seq.desc())
            .limit(1)
        )

    def _validate_approval(self, session: Session, record: ApprovalEvent) -> None:
        """GD-05/R-14: consume one delivered candidate or record its expiry/failure."""
        alert = session.get(Alert, record.alert_id)
        prior = self._latest_alert_event(session, record.alert_id)
        target = _APPROVAL_STATES.get(record.action)
        if alert is None or prior is None or target is None:
            raise LedgerIntegrityError("Approval event has no known alert or action")
        if target not in _ALERT_TRANSITIONS.get(prior.state, frozenset()):
            raise LedgerIntegrityError("Alert is already handled or not delivered")
        if (
            session.scalar(select(ApprovalEvent).where(ApprovalEvent.alert_id == alert.id))
            is not None
        ):
            raise LedgerIntegrityError("Alert approval is single-use")
        if (
            record.ts < alert.created_at
            or record.ts > record.created_at
            or record.ts > ensure_utc(self.clock.now())
        ):
            raise LedgerIntegrityError("Approval event timestamp is unverifiable")
        if record.action in {"MANUALLY_APPROVED", "USER_VETOED"}:
            if (
                isinstance(record.telegram_user_id, bool)
                or not isinstance(record.telegram_user_id, int)
                or record.telegram_user_id <= 0
            ):
                raise LedgerIntegrityError("Human approval events require explicit attribution")
            if record.ts >= alert.expires_at or self.clock.now() >= alert.expires_at:
                raise LedgerIntegrityError("Expired alert cannot receive a human decision")
        if record.action == "EXPIRED" and record.ts < alert.expires_at:
            raise LedgerIntegrityError("Expiry requires the expiry timestamp to have passed")
        if not isinstance(record.reasons, list):
            raise DataIntegrityError("Approval evidence requires a JSON array of findings")
        if record.action == "REVALIDATION_FAILED" and not record.reasons:
            raise LedgerIntegrityError("Revalidation failure requires explicit failure findings")

    def _validate_alert_event(self, session: Session, record: AlertEvent) -> None:
        """GD-05: delivery and terminal state are immutable auditable transitions."""
        alert = session.get(Alert, record.alert_id)
        prior = self._latest_alert_event(session, record.alert_id)
        previous = None if prior is None else prior.state
        if alert is None or record.state not in _ALERT_TRANSITIONS.get(previous, frozenset()):
            raise LedgerIntegrityError("Invalid appended alert lifecycle transition")
        if record.created_at < alert.created_at:
            raise LedgerIntegrityError("Alert event timestamp precedes its parent alert")
        if record.state == "SENT":
            if (
                isinstance(record.telegram_chat_id, bool)
                or not isinstance(record.telegram_chat_id, int)
                or record.telegram_chat_id == 0
                or isinstance(record.telegram_message_id, bool)
                or not isinstance(record.telegram_message_id, int)
                or record.telegram_message_id <= 0
            ):
                raise LedgerIntegrityError("SENT event requires a Telegram chat/message binding")
            if self.clock.now() >= alert.expires_at:
                raise LedgerIntegrityError("Expired candidate cannot become actionable")
            if (
                alert.telegram_chat_id is not None
                and record.telegram_chat_id != alert.telegram_chat_id
            ):
                raise LedgerIntegrityError("Delivery chat does not match its alert destination")
        if record.state in _APPROVAL_STATES.values():
            approval = session.get(ApprovalEvent, record.approval_event_id)
            if (
                approval is None
                or approval.alert_id != record.alert_id
                or _APPROVAL_STATES.get(approval.action) != record.state
            ):
                raise LedgerIntegrityError(
                    "Terminal alert state requires matching approval evidence"
                )
        elif record.approval_event_id is not None:
            raise LedgerIntegrityError("Delivery events cannot carry terminal approval evidence")

    @staticmethod
    def _ticket_matches_proposal(ticket: TradeTicket, order: Order, alert: Alert) -> bool:
        return (
            ticket.symbol == order.symbol
            and ticket.side == order.side
            and ticket.qty == order.qty
            and ticket.limit_price == order.limit_price
            and ticket.stop_price == order.stop_price
            and ticket.target_price == order.target_price
            and ticket.valid_until <= alert.expires_at
        )

    def _validate_ticket(self, session: Session, record: TradeTicket) -> None:
        """R-10/R-14: a single ticket exactly repeats an approved local proposal.

        Authentication and fresh external revalidation belong to the Stage F
        human gate. This writer is a local evidence API, not an authorization API.
        """
        alert = session.get(Alert, record.alert_id)
        if alert is None:
            raise LedgerIntegrityError("Manual ticket has no alert provenance")
        approval = session.scalar(select(ApprovalEvent).where(ApprovalEvent.alert_id == alert.id))
        state = self._latest_alert_event(session, alert.id)
        order = session.scalar(select(Order).where(Order.proposal_id == alert.proposal_id))
        if (
            approval is None
            or approval.action != "MANUALLY_APPROVED"
            or state is None
            or state.state != "APPROVED"
            or order is None
            or not self._ticket_matches_proposal(record, order, alert)
        ):
            raise LedgerIntegrityError("Ticket must exactly bind the manually approved proposal")
        if record.created_at < approval.ts or record.valid_until <= self.clock.now():
            raise LedgerIntegrityError("Manual ticket validity interval is unverifiable")
        if session.scalar(select(TradeTicket).where(TradeTicket.alert_id == alert.id)) is not None:
            raise LedgerIntegrityError("Alert already has its single-use trade ticket")

    def current_alert_status(self, alert_id: UUID) -> str:
        """GD-05: derive current status from history, leaving Alert.status PENDING."""
        self.verify_chain()
        try:
            with transaction(self.engine) as session:
                alert = session.get(Alert, alert_id)
                current = self._latest_alert_event(session, alert_id)
                if alert is None or current is None:
                    raise LedgerIntegrityError("Alert status cannot be resolved")
                return current.state
        except SafetyError:
            raise
        except Exception as exc:
            raise LedgerIntegrityError("Alert status read failed") from exc

    def alert_is_actionable(self, alert_id: UUID) -> bool:
        """GD-05/R-14: delivery success makes a pending candidate actionable."""
        self.verify_chain()
        with transaction(self.engine) as session:
            alert = session.get(Alert, alert_id)
            current = self._latest_alert_event(session, alert_id)
            if alert is None or current is None:
                raise LedgerIntegrityError("Alert actionability cannot be resolved")
            return current.state == "SENT" and ensure_utc(self.clock.now()) < alert.expires_at

    def record_trade_ticket(
        self,
        alert_id: UUID,
        *,
        telegram_user_id: int,
        reasons: list[dict[str, Any]],
        valid_until: datetime,
    ) -> TradeTicket:
        """R-10/R-14: atomically persist a revalidated human decision and its ticket.

        This local writer assumes the caller has authenticated the human and
        completed all fresh external checks. It cannot perform those checks or
        issue broker instructions. Concurrent replays fail without partial rows.
        """
        self.verify_chain()
        with transaction(self.engine) as session:
            alert = session.get(Alert, alert_id)
            if alert is None:
                raise LedgerIntegrityError("Manual ticket requires a known alert")
            order = session.scalar(select(Order).where(Order.proposal_id == alert.proposal_id))
            if order is None:
                raise LedgerIntegrityError("Manual ticket requires a local proposal")
            self.append_in_session(
                session,
                ApprovalEvent,
                alert_id=alert.id,
                action="MANUALLY_APPROVED",
                telegram_user_id=telegram_user_id,
                ts=self.clock.now(),
                reasons=reasons,
            )
            return self.append_in_session(
                session,
                TradeTicket,
                alert_id=alert.id,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
                target_price=order.target_price,
                valid_until=valid_until,
            )

    @staticmethod
    def _reject_secret_fields(settings: Any) -> None:
        secret_names = {
            "secret",
            "password",
            "token",
            "api_key",
            "access_token",
            "fernet_key",
            "db_url",
        }
        secret_suffixes = ("_secret", "_password", "_token", "_api_key", "_secret_key")
        if isinstance(settings, Mapping):
            for key, value in settings.items():
                lowered = key.lower()
                if lowered in secret_names or lowered.endswith(secret_suffixes):
                    raise DataIntegrityError("Config snapshots cannot contain secret fields")
                Ledger._reject_secret_fields(value)
        elif isinstance(settings, (tuple, list)):
            for value in settings:
                Ledger._reject_secret_fields(value)

    def _validate_fill(self, session: Session, fill: Fill) -> None:
        order = session.get(Order, fill.order_id)
        if order is None:
            raise LedgerIntegrityError("Observed fill has no local order")
        latest = session.scalar(
            select(OrderEvent)
            .where(OrderEvent.order_id == order.id)
            .order_by(OrderEvent.seq.desc())
            .limit(1)
        )
        if latest is None or latest.state not in {"SUBMITTED", "PARTIALLY_FILLED"}:
            raise LedgerIntegrityError("Observed fill requires an active submitted order")
        if isinstance(fill.qty, bool) or not isinstance(fill.qty, int) or fill.qty <= 0:
            raise DataIntegrityError("Observed fill requires a positive whole-share quantity")
        if not isinstance(fill.price, Decimal) or fill.price <= 0:
            raise DataIntegrityError("Observed fill requires a positive Decimal price")
        already_filled = sum(
            existing.qty
            for existing in session.scalars(select(Fill).where(Fill.order_id == order.id))
        )
        if already_filled + fill.qty > order.qty:
            raise LedgerIntegrityError("Observed fills exceed the order's whole-share quantity")
        if (order.side == "BUY" and fill.price > order.limit_price) or (
            order.side == "SELL" and fill.price < order.limit_price
        ):
            raise LedgerIntegrityError("Observed fill violates the recorded LIMIT price")
        if ensure_utc(fill.filled_at) > ensure_utc(self.clock.now()):
            raise LedgerIntegrityError("Observed fill timestamp is in the future")

    def _halt(self, reason: str) -> None:
        """R-02: persist a fail-closed control state even after chain corruption."""
        with transaction(self.engine) as session:
            control = session.scalar(
                select(SystemControl).where(SystemControl.id == 1).with_for_update()
            )
            if control is None:
                control = SystemControl(id=1, state="HALTED", version=0)
                session.add(control)
            count = len(list(session.scalars(select(SystemEvent))))
            control.state = "HALTED"
            control.version = count + 1
            self.append_in_session(
                session,
                SystemEvent,
                state="HALTED",
                reason=reason,
                operator_id=None,
                event_type="ESCALATE",
            )
        try:
            self.halt_callback(reason)
        except Exception as exc:
            raise LedgerIntegrityError("HALTED persisted; halt notification failed") from exc

    def verify_chain(self) -> None:
        """R-02: verify every hash, global sequence, FK and state projection.

        A failure persists HALTED before raising a typed error. Database failure
        can prevent persistence; the caller must also keep a process halt latch.
        """
        try:
            with transaction(self.engine) as session:
                self._verify_in_session(session)
        except Exception as exc:
            try:
                self._halt("ledger verification failed")
            except Exception as halt_error:
                raise LedgerIntegrityError(
                    "Ledger verification failed and durable halt could not be confirmed"
                ) from halt_error
            raise LedgerIntegrityError("Ledger verification failed; system is HALTED") from exc

    def _verify_in_session(self, session: Session) -> None:
        sequences: list[int] = []
        all_records: list[LedgerRecord] = []
        system_events: list[SystemEvent] = []
        for model_type in LEDGER_MODELS:
            previous = GENESIS_HASH
            for record in session.scalars(select(model_type).order_by(model_type.seq)):
                self._validate_common(record, verifying=True)
                if (
                    record.seq <= 0
                    or record.prev_hash != previous
                    or record.row_hash != row_digest(record)
                ):
                    raise LedgerIntegrityError(f"Broken hash chain in {model_type.__tablename__}")
                previous = record.row_hash
                sequences.append(record.seq)
                all_records.append(record)
                if isinstance(record, SystemEvent):
                    system_events.append(record)
        if sorted(sequences) != list(range(1, len(sequences) + 1)):
            raise LedgerIntegrityError("Global ledger sequences are missing or duplicated")
        allocation = session.get(AppendControl, 1)
        if allocation is None or allocation.next_seq != len(sequences) + 1:
            raise LedgerIntegrityError("Ledger sequence allocation disagrees with recorded rows")
        control = session.get(SystemControl, 1)
        expected_state = system_events[-1].state if system_events else "RUNNING"
        if (
            control is None
            or control.state != expected_state
            or control.version != len(system_events)
        ):
            raise LedgerIntegrityError(
                "Mutable state control disagrees with immutable system events"
            )
        self._verify_relationships(session, all_records)
        self._verify_lifecycle(all_records)
        self._verify_research_lifecycle(all_records)
        previous_state = "RUNNING"
        for event in system_events:
            if event.state not in _STATE_RANK:
                raise LedgerIntegrityError("Unknown system state in ledger")
            if (
                event.event_type != "OPERATOR_RESET"
                and _STATE_RANK[event.state] < _STATE_RANK[previous_state]
            ):
                raise LedgerIntegrityError("Unaudited system-state de-escalation")
            if event.event_type == "OPERATOR_RESET" and not (event.operator_id or "").strip():
                raise LedgerIntegrityError("Operator reset lacks attribution")
            if event.event_type == "INITIALIZED" and (
                event is not system_events[0] or event.state != "RUNNING"
            ):
                raise LedgerIntegrityError("Invalid repeated or nonrunning initialization event")
            previous_state = event.state

    @staticmethod
    def _verify_relationships(session: Session, records: list[LedgerRecord]) -> None:
        for record in records:
            for column in record.__table__.columns:
                value = record.__dict__[column.name]
                if value is None and not column.nullable:
                    raise LedgerIntegrityError("Nonnullable ledger field is missing")
                if value is None:
                    continue
                for foreign_key in column.foreign_keys:
                    target = foreign_key.column
                    parent_seq = session.scalar(select(target.table.c.seq).where(target == value))
                    if parent_seq is None or parent_seq >= record.seq:
                        raise LedgerIntegrityError("Ledger foreign key cannot be resolved")

    def _verify_lifecycle(self, records: list[LedgerRecord]) -> None:
        orders = {record.id: record for record in records if isinstance(record, Order)}
        signals = {record.id: record for record in records if isinstance(record, Signal)}
        for original_order in orders.values():
            signal = signals.get(original_order.signal_id)
            if (
                signal is None
                or signal.symbol != original_order.symbol
                or signal.direction != original_order.side
            ):
                raise LedgerIntegrityError("Order does not resolve to a matching signal")
            if signal.signal_type != original_order.source:
                raise LedgerIntegrityError("Order source and signal type disagree")
        states: dict[UUID, str] = {}
        totals: dict[UUID, int] = {}
        for record in sorted(records, key=lambda row: row.seq):
            if isinstance(record, Fill):
                order = orders.get(record.order_id)
                if order is None or states.get(record.order_id) not in {
                    "SUBMITTED",
                    "PARTIALLY_FILLED",
                }:
                    raise LedgerIntegrityError("Fill was recorded outside an active order")
                totals[record.order_id] = totals.get(record.order_id, 0) + record.qty
                if record.qty <= 0 or totals[record.order_id] > order.qty:
                    raise LedgerIntegrityError("Invalid cumulative fill quantity")
                if (
                    record.price <= 0
                    or (order.side == "BUY" and record.price > order.limit_price)
                    or (order.side == "SELL" and record.price < order.limit_price)
                ):
                    raise LedgerIntegrityError("Fill price violates the recorded LIMIT order")
                if ensure_utc(record.filled_at) > ensure_utc(self.clock.now()):
                    raise LedgerIntegrityError("Observed fill timestamp is in the future")
            if isinstance(record, OrderEvent):
                if not _valid_transition(states.get(record.order_id), record.state):
                    raise LedgerIntegrityError("Raw order-event lifecycle is invalid")
                order = orders.get(record.order_id)
                if order is None:
                    raise LedgerIntegrityError("Order event has no matching order")
                if record.state == "FILLED" and totals.get(record.order_id, 0) != order.qty:
                    raise LedgerIntegrityError(
                        "FILLED lifecycle does not match observed fill quantity"
                    )
                if (
                    record.state == "PARTIALLY_FILLED"
                    and not 0 < totals.get(record.order_id, 0) < order.qty
                ):
                    raise LedgerIntegrityError(
                        "Partial lifecycle does not match observed fill quantity"
                    )
                states[record.order_id] = record.state
        if set(orders) != set(states):
            raise LedgerIntegrityError("Every order requires its initial PROPOSED event")

    def _verify_research_lifecycle(self, records: list[LedgerRecord]) -> None:
        """GD-01/GD-03/GD-05/R-14: replay immutable evidence in global sequence order.

        Hash-valid raw SQL rows cannot bypass delivery, attribution, expiry,
        single use or exact proposal-to-ticket provenance.
        """
        orders = {record.proposal_id: record for record in records if isinstance(record, Order)}
        alerts = {record.id: record for record in records if isinstance(record, Alert)}
        approvals = {record.id: record for record in records if isinstance(record, ApprovalEvent)}
        states: dict[UUID, str] = {}
        decisions: dict[UUID, ApprovalEvent] = {}
        ticket_alerts: set[UUID] = set()
        event_approvals: set[UUID] = set()
        for record in sorted(records, key=lambda row: row.seq):
            if isinstance(record, Alert):
                order = orders.get(record.proposal_id)
                if (
                    order is None
                    or order.signal_id != record.signal_id
                    or order.symbol != record.symbol
                    or record.status != "PENDING"
                    or not Decimal(1) <= record.score <= Decimal(10)
                    or record.expires_at <= record.created_at
                    or record.telegram_message_id is not None
                ):
                    raise LedgerIntegrityError(
                        "Alert proposal provenance or immutable shape is invalid"
                    )
            if isinstance(record, ResearchReport):
                alert = alerts.get(record.alert_id)
                if (
                    alert is None
                    or record.created_at < alert.created_at
                    or record.status not in {"OK", "UNAVAILABLE", "ERROR"}
                ):
                    raise LedgerIntegrityError("Research outcome lacks valid alert provenance")
            if isinstance(record, ApprovalEvent):
                alert = alerts.get(record.alert_id)
                target = _APPROVAL_STATES.get(record.action)
                if (
                    alert is None
                    or target
                    not in _ALERT_TRANSITIONS.get(states.get(record.alert_id), frozenset())
                    or record.alert_id in decisions
                    or record.ts < alert.created_at
                    or record.ts > record.created_at
                    or not isinstance(record.reasons, list)
                ):
                    raise LedgerIntegrityError("Approval event is forged, replayed or unverifiable")
                if record.action in {"MANUALLY_APPROVED", "USER_VETOED"} and (
                    record.telegram_user_id is None
                    or record.telegram_user_id <= 0
                    or record.ts >= alert.expires_at
                ):
                    raise LedgerIntegrityError("Human decision is unattributed or expired")
                if record.action == "EXPIRED" and record.ts < alert.expires_at:
                    raise LedgerIntegrityError("Alert was expired before its validity ended")
                if record.action == "REVALIDATION_FAILED" and not record.reasons:
                    raise LedgerIntegrityError("Revalidation failure has no recorded findings")
                decisions[record.alert_id] = record
            if isinstance(record, AlertEvent):
                alert = alerts.get(record.alert_id)
                if (
                    alert is None
                    or record.state
                    not in _ALERT_TRANSITIONS.get(states.get(record.alert_id), frozenset())
                    or record.created_at < alert.created_at
                ):
                    raise LedgerIntegrityError("Raw alert lifecycle transition is invalid")
                if record.state == "SENT" and (
                    record.telegram_chat_id is None
                    or record.telegram_chat_id == 0
                    or record.telegram_message_id is None
                    or record.telegram_message_id <= 0
                    or record.created_at >= alert.expires_at
                    or (
                        alert.telegram_chat_id is not None
                        and record.telegram_chat_id != alert.telegram_chat_id
                    )
                ):
                    raise LedgerIntegrityError(
                        "Alert delivery binding or delivery expiry is invalid"
                    )
                if record.state in _APPROVAL_STATES.values():
                    approval = (
                        None
                        if record.approval_event_id is None
                        else approvals.get(record.approval_event_id)
                    )
                    if (
                        approval is None
                        or approval.alert_id != record.alert_id
                        or _APPROVAL_STATES.get(approval.action) != record.state
                        or approval.id in event_approvals
                        or approval.seq >= record.seq
                    ):
                        raise LedgerIntegrityError(
                            "Terminal alert state lacks exact approval evidence"
                        )
                    event_approvals.add(approval.id)
                elif record.approval_event_id is not None:
                    raise LedgerIntegrityError(
                        "Nonterminal delivery event carries approval evidence"
                    )
                states[record.alert_id] = record.state
            if isinstance(record, TradeTicket):
                alert = alerts.get(record.alert_id)
                approval = decisions.get(record.alert_id)
                order = None if alert is None else orders.get(alert.proposal_id)
                if (
                    alert is None
                    or approval is None
                    or approval.action != "MANUALLY_APPROVED"
                    or states.get(record.alert_id) != "APPROVED"
                    or record.alert_id in ticket_alerts
                    or order is None
                    or not self._ticket_matches_proposal(record, order, alert)
                    or record.valid_until <= record.created_at
                    or record.created_at < approval.ts
                    or record.ticket_sha256 != ticket_digest(record)
                ):
                    raise LedgerIntegrityError(
                        "Trade ticket is forged, replayed or loses provenance"
                    )
                ticket_alerts.add(record.alert_id)
        if set(alerts) != set(states):
            raise LedgerIntegrityError("Every alert requires its immutable PENDING lifecycle event")
        if set(approvals) != event_approvals:
            raise LedgerIntegrityError(
                "Every approval event requires exactly one terminal projection"
            )
        approved_alerts = {
            alert_id
            for alert_id, decision in decisions.items()
            if decision.action == "MANUALLY_APPROVED"
        }
        if approved_alerts != ticket_alerts:
            raise LedgerIntegrityError(
                "Every manual approval requires exactly one atomic trade ticket"
            )

    def record_fill(
        self,
        order_id: UUID,
        *,
        broker_fill_id: str,
        qty: int,
        price: Decimal,
        filled_at: datetime,
    ) -> Fill:
        """R-08: record a broker-observed fill locally; mismatch latches HALTED."""
        try:
            return self.append(
                Fill,
                order_id=order_id,
                broker_fill_id=broker_fill_id,
                qty=qty,
                price=price,
                filled_at=filled_at,
            )
        except Exception as exc:
            try:
                self._halt("observed fill could not be reconciled")
            except Exception as halt_error:
                raise ReconciliationError(
                    "Fill failed and durable halt is unconfirmed"
                ) from halt_error
            raise ReconciliationError("Observed fill rejected; system is HALTED") from exc

    def reconcile(
        self, broker_positions: Mapping[str, int], ledger_positions: Mapping[str, int]
    ) -> None:
        """R-01/R-02/R-08: compare complete long-only whole-share inventories."""
        try:
            for positions in (broker_positions, ledger_positions):
                for symbol, qty in positions.items():
                    if not symbol or isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
                        raise ReconciliationError("Unverifiable long-only position inventory")
            broker = {symbol: qty for symbol, qty in broker_positions.items() if qty != 0}
            local = {symbol: qty for symbol, qty in ledger_positions.items() if qty != 0}
            if broker != local:
                raise ReconciliationError("Broker and ledger positions disagree")
        except Exception as exc:
            try:
                self._halt("broker/ledger reconciliation failed")
            except Exception as halt_error:
                raise ReconciliationError(
                    "Reconciliation failed and durable halt is unconfirmed"
                ) from halt_error
            raise ReconciliationError("Reconciliation failed; system is HALTED") from exc

    def record_cash_flow(
        self, account_id: str, amount: Decimal, ts: datetime, equity_before: Decimal
    ) -> PortfolioState:
        """CRO-09/CRO-10/R-08: record observed external cash flow, never move money.

        Both drawdown baselines scale by equity_after/equity_before. Repeating
        decimal results round upward to a micro-unit, conservatively preserving
        loss sensitivity. Deposits never become settled cash until broker proof;
        withdrawals reduce settled cash, with a zero floor. Account attribution,
        an exact previous equity, and positive marked equity are mandatory.
        """
        try:
            if not isinstance(amount, Decimal) or not isinstance(equity_before, Decimal):
                raise DataIntegrityError("Cash flow requires exact Decimal inputs")
            money_to_scaled(amount)
            money_to_scaled(equity_before)
            instant = ensure_utc(ts)
            if instant > ensure_utc(self.clock.now()):
                raise ReconciliationError("Cash flow timestamp is in the future")
            with transaction(self.engine) as session:
                prior = session.scalar(
                    select(PortfolioState)
                    .where(PortfolioState.account_id == account_id)
                    .order_by(PortfolioState.seq.desc())
                    .limit(1)
                )
                if prior is None or equity_before <= 0 or prior.equity != equity_before:
                    raise ReconciliationError(
                        "Cash flow cannot resolve its prior managed-account equity"
                    )
                if (
                    instant < prior.as_of
                    or prior.high_water_mark <= 0
                    or prior.day_start_equity <= 0
                ):
                    raise ReconciliationError(
                        "Cash flow cannot verify its timestamp or loss baselines"
                    )
                with localcontext() as context:
                    context.prec = 80
                    equity_after = equity_before + amount
                    cash_after = prior.cash + amount
                    if equity_after <= 0 or cash_after < 0:
                        raise ReconciliationError(
                            "Cash flow would make equity nonpositive or require borrowing"
                        )
                    quantum = Decimal("0.000001")
                    high_water = (prior.high_water_mark * equity_after / equity_before).quantize(
                        quantum, rounding=ROUND_CEILING
                    )
                    day_start = (prior.day_start_equity * equity_after / equity_before).quantize(
                        quantum, rounding=ROUND_CEILING
                    )
                settled = max(Decimal(0), prior.settled_cash + min(Decimal(0), amount))
                return self.append_in_session(
                    session,
                    PortfolioState,
                    account_id=account_id,
                    account_type=prior.account_type,
                    as_of=instant,
                    equity=equity_after,
                    cash=cash_after,
                    settled_cash=settled,
                    positions=prior.positions,
                    high_water_mark=high_water,
                    day_start_equity=day_start,
                    cash_flow_amount=amount,
                    cash_flow_at=instant,
                )
        except Exception as exc:
            try:
                self._halt("observed external cash flow could not be reconciled")
            except Exception as halt_error:
                raise ReconciliationError(
                    "Cash flow failed and durable halt is unconfirmed"
                ) from halt_error
            raise ReconciliationError("Cash flow rejected; system is HALTED") from exc
```

### backend/core/system_state.py

Scope: Stage A. SHA-256: dfeede8c2573d641cd12cbbd258244eb9caebb2763f5ea6961ba419fe2fe8b8a.

```python
"""R-02/R-09: durable latching state; only audited operator reset can lower it."""

from __future__ import annotations

from decimal import Decimal, localcontext
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import Clock
from backend.core.config import Settings
from backend.core.database import SystemControl, SystemEvent, transaction
from backend.core.errors import (
    DataIntegrityError,
    LedgerIntegrityError,
    SafetyError,
    StateTransitionError,
)
from backend.core.ledger import Ledger
from backend.core.money import decimal_money
from backend.core.notifier import DeduplicatingNotifier, Notifier


class SystemState(StrEnum):
    """CRO-01 ordered operating modes; lowering a mode requires an operator."""

    RUNNING = "RUNNING"
    REDUCE_ONLY = "REDUCE_ONLY"
    HALTED = "HALTED"


_RANK = {SystemState.RUNNING: 0, SystemState.REDUCE_ONLY: 1, SystemState.HALTED: 2}


def state_allows(state: SystemState, intent: str, source: str) -> bool:
    """CRO-01/R-09: HALTED permits only explicitly manual reductions/exits."""
    if (
        not isinstance(state, SystemState)
        or not isinstance(intent, str)
        or not isinstance(source, str)
    ):
        return False
    if intent not in {"ENTRY", "ADD", "REDUCE", "EXIT"}:
        return False
    if source not in {"SIGNAL", "SYSTEM", "MANUAL"}:
        return False
    if state == SystemState.HALTED:
        return source == "MANUAL" and intent in {"REDUCE", "EXIT"}
    if state == SystemState.REDUCE_ONLY:
        return intent in {"REDUCE", "EXIT"}
    return state == SystemState.RUNNING


def financial_state(
    equity: Decimal,
    high_water_mark: Decimal,
    day_start_equity: Decimal,
    config: Settings,
) -> SystemState:
    """CRO-09/CRO-10 pure tier calculation; all thresholds include equality."""
    for value in (equity, high_water_mark, day_start_equity):
        if not isinstance(value, Decimal):
            raise DataIntegrityError("CRO-09/CRO-10: financial state requires exact Decimal values")
        decimal_money(value)
    if not isinstance(config, Settings):
        raise DataIntegrityError("CRO-09/CRO-10: financial state requires validated settings")
    if equity <= 0 or high_water_mark <= 0 or day_start_equity <= 0:
        return SystemState.HALTED
    values = (
        equity,
        high_water_mark,
        day_start_equity,
        config.dd_halt,
        config.dd_reduce_only,
        config.daily_loss_limit,
    )
    with localcontext() as context:
        context.prec = 80 + sum(len(value.as_tuple().digits) for value in values)
        loss_from_high = max(Decimal(0), high_water_mark - equity)
        if loss_from_high >= config.dd_halt * high_water_mark:
            return SystemState.HALTED
        loss_from_day_start = day_start_equity - equity
        if (
            loss_from_high >= config.dd_reduce_only * high_water_mark
            or loss_from_day_start >= config.daily_loss_limit * day_start_equity
        ):
            return SystemState.REDUCE_ONLY
    return SystemState.RUNNING


class SystemStateStore:
    """CRO-01/R-02: atomic control row plus append-only transition evidence.

    PostgreSQL locks the control row and append allocator in one transaction;
    SQLite takes BEGIN IMMEDIATE. A database failure also latches this process
    HALTED. Storage recovery never silently clears that process latch.
    """

    def __init__(
        self, engine: Engine, clock: Clock, notifier: Notifier, *, verify: bool = True
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.notifier = DeduplicatingNotifier(notifier)
        self._emergency_halt = False
        self.ledger = Ledger(engine, clock, halt_callback=self._notify)
        if verify:
            self.startup()

    def _notify(self, reason: str) -> None:
        try:
            self.notifier.notify(SystemState.HALTED.value, reason)
        except Exception as exc:
            self._emergency_halt = True
            raise StateTransitionError("R-02: halt notification failed") from exc

    def _verify_projection(self, session: Session, control: SystemControl) -> None:
        """R-02: a mutable projection cannot silently erase immutable halt evidence."""
        latest = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()).limit(1))
        expected = SystemState.RUNNING.value if latest is None else latest.state
        version = session.scalar(select(func.count()).select_from(SystemEvent))
        if control.state != expected or control.version != version:
            raise LedgerIntegrityError("R-02: operating state disagrees with immutable events")

    def startup(self) -> None:
        """R-02: chain verification is mandatory before accepting proposals."""
        try:
            self.ledger.verify_chain()
            self.current()
        except SafetyError as exc:
            self._emergency_halt = True
            self._notify("startup integrity or database verification failed")
            raise exc

    def current(self) -> SystemState:
        """CRO-01: read persisted state; a failed read cannot imply RUNNING."""
        if self._emergency_halt:
            return SystemState.HALTED
        try:
            with transaction(self.engine) as session:
                control = session.get(SystemControl, 1)
                if control is None:
                    raise StateTransitionError("R-02: missing state control row")
                try:
                    state = SystemState(control.state)
                except ValueError as exc:
                    raise StateTransitionError("R-02: invalid persisted state") from exc
                self._verify_projection(session, control)
                return state
        except SafetyError:
            self._emergency_halt = True
            self._notify("system state could not be verified")
            raise

    def escalate(self, target: SystemState, reason: str) -> SystemState:
        """CRO-01: an automatic request can only preserve or increase severity."""
        if not isinstance(target, SystemState) or not isinstance(reason, str) or not reason.strip():
            raise StateTransitionError("R-02: escalation needs valid state and reason")
        try:
            with transaction(self.engine) as session:
                control = session.scalar(
                    select(SystemControl).where(SystemControl.id == 1).with_for_update()
                )
                if control is None:
                    raise StateTransitionError("R-02: missing state control row")
                try:
                    current = SystemState(control.state)
                except ValueError as exc:
                    raise StateTransitionError("R-02: invalid persisted state") from exc
                self._verify_projection(session, control)
                if _RANK[target] > _RANK[current]:
                    control.state = target.value
                    control.version += 1
                    self.ledger.append_in_session(
                        session,
                        SystemEvent,
                        state=target.value,
                        reason=reason,
                        operator_id=None,
                        event_type="ESCALATE",
                    )
                    current = target
            if target == SystemState.HALTED:
                self._notify(reason)
            return SystemState.HALTED if self._emergency_halt else current
        except SafetyError:
            self._emergency_halt = True
            self._notify("state escalation failed; process latched HALTED")
            raise

    def operator_reset(
        self, operator_id: str, reason: str, target: SystemState = SystemState.RUNNING
    ) -> SystemState:
        """CRO-01: auditable reset; corrupted ledgers must be repaired first.

        Operator authentication belongs to a future service boundary. This local
        administrative API requires attribution and is never called by rules.
        """
        if (
            not isinstance(operator_id, str)
            or not isinstance(reason, str)
            or not operator_id.strip()
            or not reason.strip()
        ):
            raise StateTransitionError("R-02: reset requires operator ID and reason")
        if not isinstance(target, SystemState):
            raise StateTransitionError("R-02: invalid reset target")
        try:
            self.ledger.verify_chain()
            with transaction(self.engine) as session:
                control = session.scalar(
                    select(SystemControl).where(SystemControl.id == 1).with_for_update()
                )
                if control is None:
                    raise StateTransitionError("R-02: missing state control row")
                self._verify_projection(session, control)
                self.ledger.append_in_session(
                    session,
                    SystemEvent,
                    state=target.value,
                    reason=reason,
                    operator_id=operator_id,
                    event_type="OPERATOR_RESET",
                )
                control.state = target.value
                control.version += 1
            self._emergency_halt = False
            self.notifier.reset()
            if target == SystemState.HALTED:
                self._notify(reason)
            return target
        except SafetyError:
            self._emergency_halt = True
            self._notify("operator reset failed; process latched HALTED")
            raise

    def halt_for_error(self, error: Exception) -> SystemState:
        """R-02: stale data, integrity, reconciliation, clock and provider faults halt."""
        return self.escalate(SystemState.HALTED, f"fault: {type(error).__name__}")

    def apply_financial_limits(
        self,
        equity: Decimal,
        high_water_mark: Decimal,
        day_start_equity: Decimal,
        config: Settings,
    ) -> SystemState:
        """CRO-09/CRO-10: side effects stay outside pure risk rule evaluation."""
        try:
            target = financial_state(equity, high_water_mark, day_start_equity, config)
        except DataIntegrityError:
            self.escalate(SystemState.HALTED, "unverifiable financial state")
            raise
        except Exception as exc:
            self.escalate(SystemState.HALTED, "financial state evaluation failed")
            raise DataIntegrityError("CRO-09/CRO-10: financial state evaluation failed") from exc
        return self.escalate(target, "financial limits evaluated")


def require_integrity(store: SystemStateStore) -> None:
    """R-02: reverify on demand, persist and notify any chain failure."""
    try:
        store.ledger.verify_chain()
    except LedgerIntegrityError:
        store.halt_for_error(LedgerIntegrityError("ledger verification failed"))
        raise
```

### backend/core/execution_policy.py

Scope: Stage A. SHA-256: 826cb722b5dc19dc326ce75d0cbeac6c623b13a50a85313a1ac19d25913291f7.

```python
"""R-08/R-10/GD-07: sole source of prohibited execution and reflection names.

This declarative module alone is exempt from the authored-source AST scan.
It contains no SDK import, callable implementation, or execution capability.
"""

from typing import Final

BANNED_ORDER_REQUESTS: Final[frozenset[str]] = frozenset(
    {
        "OrderRequest",
        "MarketOrderRequest",
        "LimitOrderRequest",
        "StopOrderRequest",
        "StopLimitOrderRequest",
        "TrailingStopOrderRequest",
        "ReplaceOrderRequest",
        "ClosePositionRequest",
    }
)

BANNED_EXECUTION_METHODS: Final[frozenset[str]] = frozenset(
    {
        "submit_order",
        "replace_order_by_id",
        "replace_order",
        "cancel_order_by_id",
        "cancel_order",
        "cancel_orders",
        "cancel_all_orders",
        "close_position",
        "close_all_positions",
        "exercise_options_position",
        "create_transfer",
        "create_ach_transfer",
        "create_bank_transfer",
        "create_wire_transfer",
        "submit_transfer",
        "initiate_transfer",
        "transfer_create",
        "transfer",
    }
)

BANNED_DYNAMIC_BUILTINS: Final[frozenset[str]] = frozenset(
    {"eval", "exec", "compile", "__import__"}
)
RESTRICTED_REFLECTION: Final[frozenset[str]] = frozenset(
    {"getattr", "setattr", "__getattribute__", "__setattr__", "attrgetter", "methodcaller"}
)
BANNED_IMPORT_FUNCTIONS: Final[frozenset[str]] = frozenset({"importlib.import_module"})
MUTATING_HTTP_METHODS: Final[frozenset[str]] = frozenset({"POST", "DELETE", "PATCH"})
TRANSFER_CREATION_WORDS: Final[frozenset[str]] = frozenset(
    {"create", "submit", "initiate", "execute", "send", "withdraw", "deposit"}
)

# Generated dependencies and tool output are not project-authored source. No
# authored package, script, test, or root-level Python directory is excluded.
GENERATED_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".hypothesis",
        ".tox",
        ".nox",
        "build",
        "dist",
        "mutants",
        "node_modules",
    }
)
```

### backend/core/source_guard.py

Scope: Stage A. SHA-256: ff10d3a3ab4a04c87ea9d463185b9f9b83f8e0bb9a9e2e6a12a9ecadff3b5d13.

```python
"""R-08/R-10/GD-07: fail-closed AST guard for every authored Python source.

This scanner rejects prohibited SDK imports, execution member references,
reflection aliases, literal dictionary dispatch, and mutating HTTP endpoints.
Syntax/read failures and symbolic links are violations, never skipped evidence.
It is a source-control defense; OS-level network restrictions remain useful.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path

from backend.core.errors import ConfigurationError
from backend.core.execution_policy import (
    BANNED_DYNAMIC_BUILTINS,
    BANNED_EXECUTION_METHODS,
    BANNED_IMPORT_FUNCTIONS,
    BANNED_ORDER_REQUESTS,
    GENERATED_DIRECTORIES,
    MUTATING_HTTP_METHODS,
    RESTRICTED_REFLECTION,
    TRANSFER_CREATION_WORDS,
)

_ENDPOINT = re.compile(
    r"^(?:https?://[^/]+)?/(?:[^/?#]+/)*(?:orders|transfers?)(?:[/\?#]|$)", re.IGNORECASE
)
_EXEMPT_RELATIVE_PATH = Path("backend/core/execution_policy.py")


@dataclass(frozen=True, slots=True)
class Violation:
    """GD-07: stable source location and reason for a startup-blocking finding."""

    path: Path
    line: int
    column: int
    message: str
    rule_id: str = "GD-07"

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: {self.rule_id} {self.message}"


def _prohibited_member(name: str) -> bool:
    normalized = re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower()
    words = set(normalized.split("_"))
    creates_transfer = bool(words & {"transfer", "transfers"}) and bool(
        words & TRANSFER_CREATION_WORDS
    )
    return name in BANNED_EXECUTION_METHODS or name in BANNED_ORDER_REQUESTS or creates_transfer


def _references(node: ast.AST, aliases: dict[str, frozenset[str]]) -> frozenset[str]:
    if isinstance(node, ast.Name):
        unverified = f"__unverified__.{node.id}" if node.id == "re" else node.id
        return aliases.get(node.id, frozenset({unverified}))
    if isinstance(node, ast.Attribute):
        return frozenset(f"{base}.{node.attr}" for base in _references(node.value, aliases))
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return frozenset(ref for item in node.elts for ref in _references(item, aliases))
    if isinstance(node, ast.IfExp):
        return _references(node.body, aliases) | _references(node.orelse, aliases)
    if isinstance(node, ast.Call):
        callable_refs = _references(node.func, aliases)
        reflection = any(
            ref.rsplit(".", 1)[-1] in {"attrgetter", "methodcaller"} for ref in callable_refs
        )
        if reflection:
            attributes = (
                node.args
                if any(ref.rsplit(".", 1)[-1] == "attrgetter" for ref in callable_refs)
                else node.args[:1]
            )
            return frozenset(
                f"__reflected__.{attribute.value}"
                for attribute in attributes
                if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str)
            )
        return frozenset(ref for ref in callable_refs if ref.startswith("__reflected__."))
    return frozenset()


def _literal_strings(node: ast.AST, values: dict[str, frozenset[str]]) -> frozenset[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return frozenset({node.value})
    if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
        return frozenset({node.value.decode("utf-8")})
    if isinstance(node, ast.Name):
        return values.get(node.id, frozenset())
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_strings(node.left, values)
        right = _literal_strings(node.right, values)
        return frozenset(a + b for a in left for b in right)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        templates = _literal_strings(node.left, values)
        arguments = (
            [_literal_strings(item, values) for item in node.right.elts]
            if isinstance(node.right, ast.Tuple)
            else [_literal_strings(node.right, values)]
        )
        result = templates
        for combination in product(*arguments):
            for template in templates:
                try:
                    operand: str | tuple[str, ...] = (
                        combination[0] if not isinstance(node.right, ast.Tuple) else combination
                    )
                    result |= {template % operand}
                except (TypeError, ValueError):
                    result |= {template}
        return result
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return frozenset(value for item in node.elts for value in _literal_strings(item, values))
    if isinstance(node, ast.Dict):
        return frozenset(value for item in node.values for value in _literal_strings(item, values))
    if isinstance(node, ast.JoinedStr):
        return frozenset(value for item in node.values for value in _literal_strings(item, values))
    if isinstance(node, ast.Subscript):
        source = _literal_strings(node.value, values)
        if isinstance(node.slice, ast.Slice):
            parts = (node.slice.lower, node.slice.upper, node.slice.step)
            indices = tuple(_integer_literal(part) for part in parts)
            if any(
                part is not None and index is None
                for part, index in zip(parts, indices, strict=True)
            ):
                return frozenset()
            selection = slice(*indices)
            return frozenset(value[selection] for value in source)
        index = _integer_literal(node.slice)
        if index is not None:
            return frozenset(value[index] for value in source if -len(value) <= index < len(value))
    if isinstance(node, ast.IfExp):
        return _literal_strings(node.body, values) | _literal_strings(node.orelse, values)
    if isinstance(node, ast.Call):
        # Calls cannot hide constant endpoint evidence by wrapping a literal in
        # str(), a normalization helper, or a format operation.
        result = frozenset(
            value
            for item in (*node.args, *(keyword.value for keyword in node.keywords))
            for value in _literal_strings(item, values)
        )
        if isinstance(node.func, ast.Attribute):
            templates = _literal_strings(node.func.value, values)
            result |= templates
            if (
                node.func.attr == "join"
                and node.args
                and isinstance(node.args[0], (ast.Tuple, ast.List))
            ):
                choices = [_literal_strings(item, values) for item in node.args[0].elts]
                for combination in product(*choices):
                    result |= {separator.join(combination) for separator in templates}
            if node.func.attr == "format":
                args = [_literal_strings(item, values) for item in node.args]
                kwargs = {
                    item.arg: _literal_strings(item.value, values)
                    for item in node.keywords
                    if item.arg is not None
                }
                choices = [*args, *kwargs.values()]
                combinations = 1
                for choice in choices:
                    combinations *= len(choice)
                if combinations > 256:
                    raise ValueError("constant formatting exceeds verifiable complexity")
                for combination in product(*choices):
                    positional = combination[: len(args)]
                    named = dict(zip(kwargs, combination[len(args) :], strict=True))
                    for template in templates:
                        try:
                            result |= {template.format(*positional, **named)}
                        except (KeyError, IndexError, ValueError, AttributeError):
                            # Keep the unformatted text; malformed constants may
                            # never erase the endpoint evidence collected above.
                            result |= {template}
        return result
    return frozenset()


def _integer_literal(node: ast.AST | None) -> int | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        value = node.operand.value
        if isinstance(value, int) and not isinstance(value, bool):
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
    return None


def _assignment_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for item in node.elts for name in _assignment_names(item))
    return ()


def _symbol_tables(
    nodes: tuple[ast.AST, ...],
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """GD-07: conservatively retain every alias even across reassignment/scope."""
    aliases: dict[str, frozenset[str]] = {}
    values: dict[str, frozenset[str]] = {}
    assignments: list[tuple[tuple[str, ...], ast.AST]] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            for item in node.names:
                local = item.asname or item.name.split(".")[0]
                qualified = item.name if item.asname else item.name.split(".")[0]
                aliases[local] = aliases.get(local, frozenset()) | {qualified}
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                local = item.asname or item.name
                qualified = f"{node.module}.{item.name}" if node.module else item.name
                aliases[local] = aliases.get(local, frozenset()) | {qualified}
        elif isinstance(node, ast.Assign):
            targets = tuple(name for target in node.targets for name in _assignment_names(target))
            assignments.append((targets, node.value))
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            assignments.append((_assignment_names(node.target), node.value))
        elif isinstance(node, ast.arg):
            # Function parameters may shadow imported modules. Retain unknown
            # provenance so a parameter named re cannot impersonate the module.
            aliases[node.arg] = aliases.get(node.arg, frozenset()) | {f"__unverified__.{node.arg}"}
    # A dependency can pass through every assignment; bounded iterations avoid
    # malicious alias cycles expanding attribute paths without a termination.
    for _iteration in range(len(assignments) + 1):
        changed = False
        for targets, value in assignments:
            refs = _references(value, aliases)
            strings = _literal_strings(value, values)
            for name in targets:
                old_refs = aliases.get(name, frozenset())
                old_values = values.get(name, frozenset())
                new_refs = old_refs | refs
                new_values = old_values | strings
                if new_refs != old_refs or new_values != old_values:
                    aliases[name], values[name] = new_refs, new_values
                    changed = True
        if not changed:
            break
    return aliases, values


def _dynamic_reference(ref: str) -> bool:
    leaf = ref.rsplit(".", 1)[-1]
    if leaf == "compile":
        return ref != "re.compile"
    return (
        leaf in BANNED_DYNAMIC_BUILTINS or leaf == "import_module" or ref in BANNED_IMPORT_FUNCTIONS
    )


def _reflection_reference(ref: str) -> bool:
    return ref.rsplit(".", 1)[-1] in RESTRICTED_REFLECTION


def _node_messages(
    node: ast.AST,
    aliases: dict[str, frozenset[str]],
    values: dict[str, frozenset[str]],
) -> tuple[str, ...]:
    messages: list[str] = []
    if isinstance(node, ast.Import):
        for item in node.names:
            if _prohibited_member(item.name.rsplit(".", 1)[-1]):
                messages.append(f"prohibited import: {item.name}")
    if isinstance(node, ast.ImportFrom):
        for item in node.names:
            if item.name in BANNED_ORDER_REQUESTS or _prohibited_member(item.name):
                messages.append(f"prohibited import: {item.name}")
            qualified = f"{node.module}.{item.name}" if node.module else item.name
            if _dynamic_reference(qualified):
                messages.append(f"prohibited dynamic import: {qualified}")
        if any(item.name == "*" for item in node.names):
            messages.append("wildcard import prevents verification of execution aliases")
    if isinstance(node, ast.Attribute) and _prohibited_member(node.attr):
        messages.append(f"prohibited execution member: {node.attr}")
    if isinstance(node, (ast.Name, ast.Attribute)):
        for ref in sorted(_references(node, aliases)):
            if _dynamic_reference(ref):
                messages.append(f"prohibited dynamic code reference: {ref}")
            if isinstance(node, ast.Name) and _prohibited_member(ref.rsplit(".", 1)[-1]):
                messages.append(f"prohibited execution alias: {ref}")
    if isinstance(node, ast.Subscript):
        for key in sorted(_literal_strings(node.slice, values)):
            if (
                _prohibited_member(key)
                or key in BANNED_DYNAMIC_BUILTINS
                or key in RESTRICTED_REFLECTION
                or key == "import_module"
            ):
                messages.append(f"prohibited reflective dictionary key: {key}")
    if isinstance(node, ast.Call):
        refs = _references(node.func, aliases)
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "pop", "setdefault"}:
            bases = _references(node.func.value, aliases)
            vars_dictionary = (
                isinstance(node.func.value, ast.Call)
                and isinstance(node.func.value.func, ast.Name)
                and node.func.value.func.id == "vars"
            )
            if vars_dictionary or any(
                "__dict__" in ref or ref in {"builtins", "__builtins__"} for ref in bases
            ):
                for argument in node.args[:1]:
                    for name in _literal_strings(argument, values):
                        if (
                            _prohibited_member(name)
                            or name in BANNED_DYNAMIC_BUILTINS
                            or name in RESTRICTED_REFLECTION
                        ):
                            messages.append(f"prohibited reflective dictionary lookup: {name}")
        if isinstance(node.func, ast.Subscript):
            dictionary_refs = _references(node.func.value, aliases)
            if not _literal_strings(node.func.slice, values) and any(
                "__dict__" in ref or ref in {"__builtins__", "builtins"} for ref in dictionary_refs
            ):
                messages.append("dynamic reflective dictionary dispatch cannot be verified")
        if any(_reflection_reference(ref) for ref in refs):
            operator_reflection = any(
                ref.rsplit(".", 1)[-1] in {"attrgetter", "methodcaller"} for ref in refs
            )
            bound_dunder = any(
                ref.rsplit(".", 1)[-1] in {"__getattribute__", "__setattr__"}
                and not ref.startswith("object.")
                for ref in refs
            )
            name_index = 0 if bound_dunder or operator_reflection else 1
            name_node: ast.AST | None = (
                node.args[name_index] if len(node.args) > name_index else None
            )
            if name_node is None:
                name_node = next((item.value for item in node.keywords if item.arg == "name"), None)
            name_nodes = (
                node.args
                if any(ref.rsplit(".", 1)[-1] == "attrgetter" for ref in refs)
                else [name_node]
            )
            for attribute_node in name_nodes:
                if not isinstance(attribute_node, ast.Constant) or not isinstance(
                    attribute_node.value, str
                ):
                    messages.append("reflection attribute name must be a literal string")
                elif any(
                    _prohibited_member(part)
                    or part in BANNED_DYNAMIC_BUILTINS
                    or part in RESTRICTED_REFLECTION
                    or part == "import_module"
                    for part in attribute_node.value.split(".")
                ):
                    messages.append(f"prohibited reflection attribute: {attribute_node.value}")
        call_strings = frozenset(
            value
            for child in (*node.args, *(keyword.value for keyword in node.keywords))
            for value in _literal_strings(child, values)
        )
        endpoint_present = any(_ENDPOINT.match(value) for value in call_strings)
        method_present = any(
            value.upper() in MUTATING_HTTP_METHODS for value in call_strings
        ) or any(
            ref.rsplit(".", 1)[-1].lstrip("_").upper() in MUTATING_HTTP_METHODS for ref in refs
        )
        if endpoint_present and method_present:
            messages.append("mutating HTTP request targets an order or transfer endpoint")
    return tuple(dict.fromkeys(messages))


def _location(path: Path, node: ast.AST, message: str) -> Violation:
    if isinstance(node, (ast.expr, ast.stmt, ast.arg, ast.keyword)):
        return Violation(path, node.lineno, node.col_offset + 1, message)
    return Violation(path, 1, 1, message)


def scan_file(path: Path) -> tuple[Violation, ...]:
    """GD-07/R-02: parse one file, returning violations for unreadable/invalid source."""
    try:
        if path.is_symlink():
            return (
                Violation(path, 1, 1, "symbolic source link cannot establish authored provenance"),
            )
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        nodes = tuple(ast.walk(tree))
        aliases, values = _symbol_tables(nodes)
        findings = {
            _location(path, node, message)
            for node in nodes
            for message in _node_messages(node, aliases, values)
        }
        # Conservative file-wide evidence also catches mutation requests built
        # through separate assignments and transport.send(request). A file that
        # reads order history may not also contain a mutating method declaration.
        endpoint_nodes = tuple(
            node
            for node in nodes
            if isinstance(node, ast.expr)
            and any(_ENDPOINT.match(value) for value in _literal_strings(node, values))
        )
        mutation_present = any(
            isinstance(node, ast.expr)
            and any(
                value.upper() in MUTATING_HTTP_METHODS for value in _literal_strings(node, values)
            )
            or isinstance(node, ast.Attribute)
            and node.attr.lstrip("_").upper() in MUTATING_HTTP_METHODS
            for node in nodes
        )
        if endpoint_nodes and mutation_present:
            findings.add(
                _location(
                    path,
                    endpoint_nodes[0],
                    "order/transfer endpoint and mutating HTTP method coexist in authored source",
                )
            )
        return tuple(sorted(findings, key=lambda item: (item.line, item.column, item.message)))
    except Exception as error:
        return (Violation(path, 1, 1, f"source cannot be verified: {type(error).__name__}"),)


def scan_project(root: Path) -> tuple[Violation, ...]:
    """GD-07: scan all authored .py, rejecting links/escapes and unreadable paths.

    Only the exact constants module is exempt among authored Python files.
    Generated directory exclusions are explicit in execution_policy.py.
    """
    findings: list[Violation] = []
    try:
        if root.is_symlink() or not root.is_dir():
            return (Violation(root, 1, 1, "source root must be a real directory"),)
        source_root = root.resolve(strict=True)
        pending = [source_root]
        while pending:
            directory = pending.pop()
            for path in sorted(directory.iterdir()):
                if path.is_symlink():
                    findings.append(Violation(path, 1, 1, "symbolic project link is prohibited"))
                    continue
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(source_root):
                    findings.append(Violation(path, 1, 1, "source path escapes the project root"))
                elif path.is_dir():
                    if path.name not in GENERATED_DIRECTORIES and not path.name.endswith(
                        ".egg-info"
                    ):
                        pending.append(path)
                elif (
                    path.suffix == ".py" and path.relative_to(source_root) != _EXEMPT_RELATIVE_PATH
                ):
                    findings.extend(scan_file(path))
    except Exception as error:
        findings.append(
            Violation(root, 1, 1, f"project cannot be verified: {type(error).__name__}")
        )
    return tuple(
        sorted(findings, key=lambda item: (str(item.path), item.line, item.column, item.message))
    )


def require_safe_sources(root: Path) -> None:
    """GD-07/R-02: refuse startup when any authored source violates the policy."""
    findings = scan_project(root)
    if findings:
        raise ConfigurationError(
            "GD-07 authored-source safety check failed:\n" + "\n".join(map(str, findings))
        )


def main() -> int:
    """GD-07: command-line check for CI, pre-commit, and operator verification."""
    parser = argparse.ArgumentParser(description="Verify GD-07 read-only authored Python sources")
    parser.add_argument("root", type=Path, nargs="?", default=Path.cwd())
    arguments = parser.parse_args()
    findings = scan_project(arguments.root)
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    print("GD-07 authored-source scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### backend/core/check_stage_a.py

Scope: Stage A. SHA-256: 1fb4e8f146fc171bc40a071aa1f28d5cdb9dadd2e17e759a5b1fa41c113936ef.

```python
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
```

### backend/data/__init__.py

Scope: Stage A. SHA-256: 92296c6545459927a1b354008b98911a38b58fd57c66dc852595388822e952af.

```python
"""R-08 read-only data boundaries."""
```

### backend/data/market_calendar.py

Scope: Stage A. SHA-256: a3e136f65c416b13eb86fdec90f62dcd17353376d136da123257fa6a6a03600b.

```python
"""R-02/R-03/R-05, DAT-01 and CMP-03: deterministic, bounded XNYS sessions.

The official exchange_calendars schedule is compiled once to immutable Python
values. Queries perform no I/O and never consult the wall clock. A regular
session includes its open and excludes its close; at its exact close it is a
completed session. Session labels are dates, whereas all instants are UTC.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from datetime import date, datetime
from typing import Protocol, cast

import exchange_calendars
import pandas as pd
import structlog

from backend.core.clock import ensure_utc
from backend.core.errors import CalendarError

CalendarFactory = Callable[[str, date, date], object]


class _CalendarSource(Protocol):
    """R-02: narrow boundary for the verified, otherwise untyped SDK."""

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def sessions(self) -> pd.DatetimeIndex:
        raise NotImplementedError

    def session_open(self, session: pd.Timestamp) -> pd.Timestamp:
        raise NotImplementedError

    def session_close(self, session: pd.Timestamp) -> pd.Timestamp:
        raise NotImplementedError


def _official_calendar(name: str, start: date, end: date) -> object:
    # VERIFY: https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/calendar_utils.py
    return cast(
        object,
        exchange_calendars.get_calendar(
            name, start=start.isoformat(), end=end.isoformat(), side="left"
        ),
    )


def _calendar_instant(value: object) -> datetime:
    """R-02/R-05: reject missing, NaT or naive times at the SDK boundary."""
    if not isinstance(value, pd.Timestamp) or pd.isna(value):
        raise CalendarError("Calendar returned a missing or invalid session instant")
    return ensure_utc(value.to_pydatetime())


def _date_argument(value: date) -> date:
    """R-02: do not silently truncate an instant into a session label."""
    if not isinstance(value, date) or isinstance(value, datetime):
        raise CalendarError("Session arguments must be dates, not timestamps")
    return value


def _count_argument(value: int) -> int:
    """R-02/CMP-03: offsets are nonnegative whole session counts."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CalendarError("Session count must be a nonnegative integer")
    return value


class MarketCalendar:
    """R-02/R-03/R-05/DAT-01/CMP-03: bounded NYSE regular trading schedule.

    The default requested range is fixed at 1990-01-01 through 2030-12-31,
    rather than the SDK's wall-clock-dependent default. Only the resolved
    first through last session dates are supported. Beyond those dates every
    query raises CalendarError, including queries that would otherwise return
    an old close. Supply an explicit range for replay or a calendar update.

    add_sessions requires a genuine session date; it never guesses a trade
    date on a holiday. previous_sessions accepts holidays and weekends and
    returns strictly preceding session dates in chronological order.
    """

    def __init__(
        self,
        *,
        name: str = "XNYS",
        start: date = date(1990, 1, 1),
        end: date = date(2030, 12, 31),
        calendar_factory: CalendarFactory | None = None,
    ) -> None:
        try:
            if name != "XNYS":
                raise CalendarError("Only the XNYS calendar is supported")
            start = _date_argument(start)
            end = _date_argument(end)
            if start >= end:
                raise CalendarError("Calendar start must precede end")
            factory = calendar_factory or _official_calendar
            source = cast(_CalendarSource, factory(name, start, end))
            if source.name != "XNYS":
                raise CalendarError("Calendar provider resolved to an unexpected exchange")
            # VERIFY: https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/exchange_calendar.py
            labels = source.sessions
            if not isinstance(labels, pd.DatetimeIndex) or labels.empty:
                raise CalendarError("Calendar returned no valid sessions")
            dates: list[date] = []
            opens: list[datetime] = []
            closes: list[datetime] = []
            for label in labels:
                if not isinstance(label, pd.Timestamp) or pd.isna(label):
                    raise CalendarError("Calendar returned an invalid session label")
                if label.tzinfo is not None or label != label.normalize():
                    raise CalendarError("Session labels must be naive midnight dates")
                session = label.date()
                if not start <= session <= end:
                    raise CalendarError("Calendar session escaped the requested bounds")
                if dates and session <= dates[-1]:
                    raise CalendarError("Calendar sessions must increase strictly")
                # VERIFY: https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/exchange_calendar.py
                opened = _calendar_instant(source.session_open(label))
                closed = _calendar_instant(source.session_close(label))
                if opened >= closed or opened.date() != session or closed.date() != session:
                    raise CalendarError("XNYS session open/close interval is invalid")
                if closes and opened <= closes[-1]:
                    raise CalendarError("Calendar session intervals overlap")
                dates.append(session)
                opens.append(opened)
                closes.append(closed)
            self._sessions = tuple(dates)
            self._opens = tuple(opens)
            self._closes = tuple(closes)
        except CalendarError:
            raise
        except Exception as exc:
            structlog.get_logger(__name__).error(
                "calendar_build_failed", error_type=type(exc).__name__
            )
            raise CalendarError("Failed to construct a verified XNYS calendar") from exc

    @property
    def first_session(self) -> date:
        """R-02: first supported session label, inclusive."""
        return self._sessions[0]

    @property
    def last_session(self) -> date:
        """R-02: last supported session label, inclusive."""
        return self._sessions[-1]

    def _bounded_date(self, value: date) -> date:
        result = _date_argument(value)
        if not self.first_session <= result <= self.last_session:
            raise CalendarError("Date is outside the verified calendar range")
        return result

    def _session_index(self, value: date) -> int:
        result = self._bounded_date(value)
        index = bisect_left(self._sessions, result)
        if index == len(self._sessions) or self._sessions[index] != result:
            raise CalendarError("Date is not an XNYS trading session")
        return index

    def _instant(self, value: datetime) -> datetime:
        try:
            result = ensure_utc(value)
            self._bounded_date(result.date())
            return result
        except CalendarError:
            raise
        except Exception as exc:
            raise CalendarError("Calendar query requires a valid aware UTC instant") from exc

    def is_open(self, ts: datetime) -> bool:
        """DAT-01/R-05: regular hours are [open, close), including early closes."""
        instant = self._instant(ts)
        index = bisect_right(self._opens, instant) - 1
        return index >= 0 and instant < self._closes[index]

    def last_completed_session(self, now: datetime) -> date:
        """DAT-01/DAT-03: never expose today's in-progress daily session."""
        instant = self._instant(now)
        index = bisect_right(self._closes, instant) - 1
        if index < 0:
            raise CalendarError("No completed session exists in the verified range")
        return self._sessions[index]

    def add_sessions(self, day: date, n: int) -> date:
        """CMP-03: T+n from an actual trade date; holidays never count."""
        index = self._session_index(day) + _count_argument(n)
        if index >= len(self._sessions):
            raise CalendarError("Session offset exceeds the verified calendar range")
        return self._sessions[index]

    def previous_sessions(self, day: date, n: int) -> tuple[date, ...]:
        """CMP-05: n strictly preceding sessions, earliest first; d is excluded."""
        bounded = self._bounded_date(day)
        count = _count_argument(n)
        index = bisect_left(self._sessions, bounded)
        if count > index:
            raise CalendarError("Insufficient preceding sessions in verified range")
        return self._sessions[index - count : index]

    def session_open(self, day: date) -> datetime:
        """DAT-01/R-05: UTC regular-session open, with DST respected."""
        return self._opens[self._session_index(day)]

    def is_session(self, day: date) -> bool:
        """DAT-01/CMP-05: bounded session membership without assuming a holiday."""
        bounded = self._bounded_date(day)
        index = bisect_left(self._sessions, bounded)
        return index < len(self._sessions) and self._sessions[index] == bounded

    def session_close(self, day: date) -> datetime:
        """DAT-01/R-05: UTC regular-session close, with early close/DST respected."""
        return self._closes[self._session_index(day)]


XNYSCalendar = MarketCalendar
```

### backend/tests/__init__.py

Scope: Stage A. SHA-256: c9481d0d1ecb3da2f37f02a1577a4eede80f71778168f2ce83a7abdff88a7cdb.

```python
"""Offline requirement-focused tests."""
```

### backend/tests/conftest.py

Scope: Stage A. SHA-256: a5d15a108cdc3d636d40f83772de0547a819b9d4e48c185f013c716e8f1e591e.

```python
"""R-05/R-07: isolated clocks, databases and environment; no real dotenv."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import create_database, create_schema


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-07: settings tests are independent of broker/Plaid credentials."""
    import os

    prefixes = (
        "MAX_",
        "MIN_",
        "DD_",
        "DAILY_",
        "STOP_",
        "SECTOR_",
        "THEME_",
        "PRICE_",
        "STALE_",
        "GAP_",
        "CHECKING_",
        "RESERVED_",
        "LIQUIDITY_",
        "WASH_",
        "DAY_",
        "BROKER_",
        "ALPACA_",
        "PLAID_",
        "PAPER_",
        "LIVE_",
        "DB_",
        "FERNET_",
        "LLM_",
        "TELEGRAM_",
        "NEWSAPI_",
        "EARNINGS_",
        "ALERT_",
        "PROPOSAL_",
        "ENABLE_",
        "SCAN_",
        "OFFHOURS_",
        "SCHEDULER_",
    )
    for name in tuple(os.environ):
        if name.startswith(prefixes):
            monkeypatch.delenv(name)


@pytest.fixture
def clock() -> FrozenClock:
    """R-05: regular XNYS hours on a fixed ordinary session."""
    return FrozenClock(datetime(2026, 9, 29, 15, 0, tzinfo=UTC))


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """R-02: each test gets an independent on-disk SQLite ledger."""
    database = create_database(f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    create_schema(database)
    yield database
    database.dispose()
```

### backend/tests/test_config_safety.py

Scope: Stage A. SHA-256: a11e64a90cea44e3af44f47a760126e7b01a38a27772512d105a713f00197a3e.

```python
"""R-04/R-05/R-06/R-07: configuration safety and exact startup boundaries."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from backend.core.clock import FrozenClock, SystemClock, ensure_utc
from backend.core.config import (
    LIVE_BROKER_ENDPOINT,
    LIVE_CONFIRMATION,
    PAPER_BROKER_ENDPOINT,
    Settings,
    assert_broker_endpoint,
    load_settings,
)
from backend.core.errors import ConfigurationError, DataIntegrityError


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-07: test settings never depend on real credentials or environment."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)


def test_R_06_paper_defaults_and_exact_endpoint() -> None:
    settings = Settings()
    assert settings.paper_trading
    assert not settings.live_trading_enabled
    assert settings.broker_endpoint == PAPER_BROKER_ENDPOINT
    assert_broker_endpoint(settings, PAPER_BROKER_ENDPOINT)
    assert_broker_endpoint(settings, PAPER_BROKER_ENDPOINT + "/")


@pytest.mark.parametrize(
    "endpoint",
    [
        LIVE_BROKER_ENDPOINT,
        PAPER_BROKER_ENDPOINT + "/v2",
        PAPER_BROKER_ENDPOINT + "?paper=true",
        "http://paper-api.alpaca.markets",
        PAPER_BROKER_ENDPOINT + "//",
    ],
)
def test_R_06_endpoint_mismatch_fails_closed(endpoint: str) -> None:
    with pytest.raises(ConfigurationError):
        assert_broker_endpoint(Settings(), endpoint)


@pytest.mark.parametrize("missing", ["enabled", "confirm", "api_key", "secret_key"])
def test_R_06_each_missing_live_condition_raises(missing: str) -> None:
    values: dict[str, Any] = {
        "paper_trading": False,
        "live_trading_enabled": True,
        "live_trading_confirm": LIVE_CONFIRMATION,
        "broker_api_key": SecretStr("test-only-live-api"),
        "broker_secret_key": SecretStr("test-only-live-secret"),
    }
    fields = {
        "enabled": "live_trading_enabled",
        "confirm": "live_trading_confirm",
        "api_key": "broker_api_key",
        "secret_key": "broker_secret_key",
    }
    values.pop(fields[missing])
    with pytest.raises(ValidationError):
        Settings(**values)


def test_R_06_all_live_conditions_and_endpoint_assertion() -> None:
    settings = Settings(
        paper_trading=False,
        live_trading_enabled=True,
        live_trading_confirm=LIVE_CONFIRMATION,
        broker_api_key=SecretStr("test-only-complete-api"),
        broker_secret_key=SecretStr("test-only-complete-secret"),
    )
    assert settings.broker_endpoint == LIVE_BROKER_ENDPOINT
    assert_broker_endpoint(settings, LIVE_BROKER_ENDPOINT)
    with pytest.raises(ConfigurationError):
        assert_broker_endpoint(settings, PAPER_BROKER_ENDPOINT)


@pytest.mark.parametrize("field,bounds", list(Settings.DECIMAL_BOUNDS.items()))
def test_R_06_decimal_ceiling_boundary_and_oversized_rejection(
    field: str, bounds: tuple[Decimal, Decimal]
) -> None:
    upper = bounds[1]
    values: dict[str, Any] = {field: upper}
    if field == "dd_reduce_only":
        values["dd_halt"] = Decimal("0.25")
    assert Settings(**values).__dict__[field] == upper
    values[field] = upper + Decimal("0.01")
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("field,bounds", list(Settings.INTEGER_BOUNDS.items()))
def test_R_06_integer_ceiling_boundary_and_oversized_rejection(
    field: str, bounds: tuple[int, int]
) -> None:
    values: dict[str, Any] = {field: bounds[1]}
    assert Settings(**values).__dict__[field] == bounds[1]
    values[field] = bounds[1] + 1
    with pytest.raises(ValidationError):
        Settings(**values)
    values[field] = True
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("bad", [float("0.1"), True, "NaN", "Infinity", None])
def test_R_04_decimal_limits_reject_inexact_or_missing_values(bad: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(max_single_stock_weight=bad)


def test_R_06_conservative_security_floors_and_drawdown_ordering() -> None:
    for field, value in {
        "min_cash_pct": Decimal("0.049"),
        "min_price": Decimal("4.99"),
        "checking_buffer_usd": Decimal("1499.99"),
        "min_margin_equity": Decimal("1999.99"),
        "stop_slippage_buffer": Decimal("0.0019"),
    }.items():
        values: dict[str, Any] = {field: value}
        with pytest.raises(ValidationError):
            Settings(**values)
    with pytest.raises(ValidationError):
        Settings(dd_reduce_only=Decimal("0.12"), dd_halt=Decimal("0.12"))


def test_R_03_settings_and_nested_caps_are_immutable() -> None:
    original = {"Information Technology": Decimal("0.35")}
    settings = Settings(sector_caps=original)
    original["Information Technology"] = Decimal("0.99")
    assert settings.sector_caps["Information Technology"] == Decimal("0.35")
    with pytest.raises(ValidationError):
        settings.max_open_positions = 30
    with pytest.raises(TypeError):
        settings.sector_caps["Information Technology"] = Decimal("0.40")  # type: ignore[index]


def test_R_04_environment_json_uses_exact_decimal_and_caps_have_ceilings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECTOR_CAPS", '{"Information Technology": 0.35}')
    monkeypatch.setenv("RESERVED_OBLIGATIONS_USD", '[100.01, "250.25"]')
    settings = Settings()
    assert settings.sector_caps["Information Technology"] == Decimal("0.35")
    assert settings.reserved_obligations_usd == (Decimal("100.01"), Decimal("250.25"))
    monkeypatch.setenv("SECTOR_CAPS", '{"Information Technology": 0.500001}')
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "value",
    [[], {}, {"": Decimal("0.3")}, {"AI": Decimal("0.41")}, {"AI": float("0.2")}, "not-json"],
)
def test_CRO_05_bad_theme_caps_rejected(value: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(theme_caps=value)


def test_R_07_config_hash_is_canonical_nonsecret_and_policy_sensitive() -> None:
    first = Settings(
        sector_caps={"B": Decimal("0.20"), "A": Decimal("0.300")},
        broker_api_key=SecretStr("test-only-key-a"),
        db_url=SecretStr("postgresql://alice:private-a@localhost/vws?password=private-query"),
    )
    second = Settings(
        sector_caps={"A": Decimal("0.3"), "B": Decimal("0.2")},
        broker_api_key=SecretStr("test-only-key-b"),
        db_url=SecretStr("postgresql://bob:private-b@localhost/vws"),
    )
    assert first.config_hash == second.config_hash
    assert len(first.config_hash) == 64
    assert Settings(max_single_stock_weight=Decimal("0.09")).config_hash != Settings().config_hash
    text = repr(first) + str(first.nonsecret_snapshot()) + first.model_dump_json()
    for secret in ("test-only-key-a", "private-a", "private-query"):
        assert secret not in text


def test_R_07_dotenv_is_explicit_and_factory_errors_are_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MAX_SINGLE_STOCK_WEIGHT=0.09\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert Settings().max_single_stock_weight == Decimal("0.10")
    assert load_settings(env_file=env_file).max_single_stock_weight == Decimal("0.09")
    with pytest.raises(ConfigurationError):
        load_settings(max_single_stock_weight="10")


def test_R_06_env_flags_and_broker_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_TRADING", "false")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", LIVE_CONFIRMATION)
    monkeypatch.setenv("ALPACA_API_KEY", "test-only-env-api")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-only-env-secret")
    assert not Settings().paper_trading
    monkeypatch.setenv("PAPER_TRADING", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_R_05_clocks_are_aware_utc_and_frozen() -> None:
    instant = datetime(2026, 10, 4, 10, 0, tzinfo=timezone(timedelta(hours=-5)))
    clock = FrozenClock(instant)
    assert clock.now() == datetime(2026, 10, 4, 15, 0, tzinfo=UTC)
    assert clock.now() is clock.now()
    assert SystemClock().now().tzinfo is UTC
    with pytest.raises(DataIntegrityError):
        ensure_utc(datetime(2026, 10, 4))


def test_GD_01_offline_defaults_disable_llm_and_intraday_calls() -> None:
    settings = Settings()
    assert settings.llm_model_name is None
    assert settings.llm_base_url is None
    assert settings.llm_daily_budget_usd == Decimal("0")
    assert settings.llm_input_cost_per_million_usd is None
    assert settings.llm_output_cost_per_million_usd is None
    assert not settings.enable_intraday_playbooks
    assert settings.earnings_blackout_sessions == 2
    assert settings.min_setup_score == Decimal("7.0")
    assert settings.max_alerts_per_day == 5
    assert settings.proposal_ttl_sessions == 1
    with pytest.raises(ConfigurationError):
        settings.assert_research_ready()
    with pytest.raises(ConfigurationError):
        settings.assert_telegram_ready()


@pytest.mark.parametrize("missing", ["llm_base_url", "llm_model_name", "llm_api_key"])
def test_GD_01_connected_research_requires_explicit_provider_model_and_key(missing: str) -> None:
    values: dict[str, Any] = {
        "llm_base_url": "https://example.invalid/v1",
        "llm_model_name": "test-model-from-configuration",
        "llm_api_key": SecretStr("test-only-llm-key"),
    }
    values.pop(missing)
    with pytest.raises(ConfigurationError):
        Settings(**values).assert_research_ready()


def test_GD_01_zero_budget_and_unknown_costs_block_calls() -> None:
    values: dict[str, Any] = {
        "llm_base_url": "https://example.invalid/v1",
        "llm_model_name": "test-model-from-configuration",
        "llm_api_key": SecretStr("test-only-budget-key"),
    }
    connected = Settings(**values)
    connected.assert_research_ready()
    with pytest.raises(ConfigurationError, match="zero daily budget"):
        connected.assert_llm_call_budget_ready()
    values["llm_daily_budget_usd"] = Decimal("1")
    with pytest.raises(ConfigurationError, match="cost rates"):
        Settings(**values).assert_llm_call_budget_ready()
    values["llm_input_cost_per_million_usd"] = Decimal("2")
    with pytest.raises(ConfigurationError, match="cost rates"):
        Settings(**values).assert_llm_call_budget_ready()
    values["llm_output_cost_per_million_usd"] = Decimal("8")
    Settings(**values).assert_llm_call_budget_ready()


def test_R_04_GD_01_daily_budget_requires_representable_money() -> None:
    assert Settings(llm_daily_budget_usd=Decimal("0.000001")).llm_daily_budget_usd == Decimal(
        "0.000001"
    )
    with pytest.raises(ValidationError):
        Settings(llm_daily_budget_usd=Decimal("0.0000001"))


def test_R_04_validation_does_not_depend_on_ambient_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 1
        settings = Settings(
            min_price=Decimal("5.01"),
            reserved_obligations_usd=(Decimal("100000000"), Decimal("900000000")),
        )
        assert settings.min_price == Decimal("5.01")
        with pytest.raises(ValidationError):
            Settings(min_price=Decimal("5.001"))
        with pytest.raises(ValidationError):
            Settings(reserved_obligations_usd=(Decimal("1000000000"), Decimal("1")))


@pytest.mark.parametrize(
    "field",
    ["llm_input_cost_per_million_usd", "llm_output_cost_per_million_usd"],
)
@pytest.mark.parametrize("bad", [True, 0.1, "NaN", "Infinity", "-0.01", "1000.01"])
def test_GD_01_cost_rates_reject_inexact_nonfinite_and_out_of_bounds(field: str, bad: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: bad})


@pytest.mark.parametrize(
    "field",
    ["llm_input_cost_per_million_usd", "llm_output_cost_per_million_usd"],
)
@pytest.mark.parametrize("boundary", [Decimal("0"), Decimal("1000")])
def test_GD_01_cost_rate_exact_boundaries_pass(field: str, boundary: Decimal) -> None:
    values: dict[str, Any] = {field: boundary}
    assert Settings(**values).__dict__[field] == boundary


@pytest.mark.parametrize("score", ["6.0", "7.0", "10.0"])
def test_GD_02_setup_score_exact_boundaries_pass(score: str) -> None:
    values: dict[str, Any] = {"min_setup_score": score}
    assert Settings(**values).min_setup_score == Decimal(score)


@pytest.mark.parametrize("bad", ["5.99", "10.01", "NaN", "Infinity", 7.0, True])
def test_GD_02_setup_score_below_six_or_nonfinite_is_rejected(bad: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(min_setup_score=bad)


@pytest.mark.parametrize("field,bounds", list(Settings.INTEGER_BOUNDS.items()))
def test_R_06_integer_lower_boundary_and_below_rejection(
    field: str, bounds: tuple[int, int]
) -> None:
    values: dict[str, Any] = {field: bounds[0]}
    assert Settings(**values).__dict__[field] == bounds[0]
    values[field] = bounds[0] - 1
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("field", ["min_setup_score", "llm_daily_budget_usd"])
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_R_04_GD_01_nonfinite_environment_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, bad: str
) -> None:
    monkeypatch.setenv(field.upper(), bad)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid/v1",
        "https://user:private-key@example.invalid/v1",
        "https://example.invalid/v1?api_key=private-key",
        "https://example.invalid/v1#private-key",
        "https:///v1",
        "https://example.invalid:bad/v1",
        " https://example.invalid/v1",
    ],
)
def test_R_07_GD_01_llm_endpoint_rejects_secret_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(llm_base_url=url)
    assert "private-key" not in str(caught.value)


@pytest.mark.parametrize("model", ["", " ", " model", "model ", "line\nbreak", "x" * 201])
def test_GD_01_explicit_model_name_is_required_and_bounded(model: str) -> None:
    with pytest.raises(ValidationError):
        Settings(llm_model_name=model)


@pytest.mark.parametrize("missing", ["bot_token", "allowlist", "callback_secret"])
def test_R_14_GD_05_connected_telegram_requires_every_security_condition(missing: str) -> None:
    fields = {
        "bot_token": "telegram_bot_token",
        "allowlist": "telegram_allowed_user_ids",
        "callback_secret": "telegram_callback_secret",
    }
    values: dict[str, Any] = {
        "telegram_bot_token": SecretStr("test-only-telegram-token"),
        "telegram_allowed_user_ids": [10001],
        "telegram_callback_secret": SecretStr("test-only-callback-secret-32bytes-minimum"),
    }
    values.pop(fields[missing])
    with pytest.raises(ConfigurationError):
        Settings(**values).assert_telegram_ready()


def test_R_14_GD_05_allowlist_is_explicit_nonempty_immutable_and_strict() -> None:
    users = [10001, 10002]
    values: dict[str, Any] = {
        "telegram_bot_token": SecretStr("test-only-allowlist-token"),
        "telegram_allowed_user_ids": users,
        "telegram_callback_secret": SecretStr("test-only-callback-secret-32bytes-minimum"),
    }
    settings = Settings(**values)
    settings.assert_telegram_ready()
    users.append(99999)
    assert settings.telegram_allowed_user_ids == (10001, 10002)
    assert 99999 not in settings.telegram_allowed_user_ids
    values["telegram_allowed_user_ids"] = []
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize(
    "users",
    [[True], [0], [-1], [10001.0], ["10001"], [10001, 10001], [2**63], "10001"],
)
def test_R_14_GD_05_invalid_allowlist_never_starts(users: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(telegram_allowed_user_ids=users)


def test_R_14_GD_05_callback_secret_minimum_bytes_are_enforced() -> None:
    values: dict[str, Any] = {
        "telegram_bot_token": SecretStr("test-only-length-token"),
        "telegram_allowed_user_ids": [10001],
    }
    with pytest.raises(ConfigurationError):
        Settings(telegram_callback_secret=SecretStr("x" * 31), **values).assert_telegram_ready()
    Settings(telegram_callback_secret=SecretStr("x" * 32), **values).assert_telegram_ready()
    with pytest.raises(ConfigurationError):
        Settings(telegram_callback_secret=SecretStr(" " * 32), **values).assert_telegram_ready()


def test_R_07_GD_01_GD_05_new_secrets_are_masked_and_do_not_change_config_hash() -> None:
    values: dict[str, Any] = {
        "llm_api_key": SecretStr("test-only-private-llm-key"),
        "telegram_bot_token": SecretStr("987654321:test-only-private-token"),
        "telegram_callback_secret": SecretStr("test-only-private-callback-secret-32bytes"),
        "newsapi_key": SecretStr("test-only-private-news-key"),
    }
    settings = Settings(**values)
    assert settings.config_hash == Settings().config_hash
    rendered = repr(settings) + str(settings.nonsecret_snapshot()) + settings.model_dump_json()
    for secret in values.values():
        assert secret.get_secret_value() not in rendered
    invalid: dict[str, Any] = {"telegram_bot_token": 987654321}
    with pytest.raises(ValidationError) as caught:
        Settings(**invalid)
    assert "987654321" not in str(caught.value)


def test_GD_01_GD_05_environment_profiles_use_json_and_explicit_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL_NAME", "test-env-model")
    monkeypatch.setenv("LLM_API_KEY", "test-only-env-llm-key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[10001, 10002]")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-only-env-bot-token")
    monkeypatch.setenv("TELEGRAM_CALLBACK_SECRET", "test-only-env-callback-secret-32bytes")
    monkeypatch.setenv("ENABLE_INTRADAY_PLAYBOOKS", "true")
    settings = Settings()
    settings.assert_research_ready()
    settings.assert_telegram_ready()
    assert settings.llm_model_name == "test-env-model"
    assert settings.telegram_allowed_user_ids == (10001, 10002)
    assert settings.enable_intraday_playbooks
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[]")
    with pytest.raises(ValidationError):
        Settings()
```

### backend/tests/test_yaml_config.py

Scope: Stage A. SHA-256: 05ed93ce3064bc2035947ef71ef54e4390a08a950688cc55dd117c23f3ae6d03.

```python
"""GD-02/R-03/R-06: strict, exact, frozen research YAML cannot weaken risk."""

from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import SecretStr, ValidationError

from backend.core.config import (
    Settings,
    YamlConfig,
    load_yaml_config,
)
from backend.core.errors import ConfigurationError

REPOSITORY_CONFIG = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
ALLOWED_SYMBOLS = frozenset({"AAPL", "MSFT", "NVDA", "SPY", "QQQ", "XLK"})


@pytest.fixture(autouse=True)
def isolated_yaml_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-07: YAML tests cannot accidentally read connected credentials."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)


@pytest.fixture
def valid_payload() -> dict[str, Any]:
    """GD-02: a canonical exact-value copy of the shipped research policy."""
    return load_yaml_config(REPOSITORY_CONFIG, allowed_symbols=ALLOWED_SYMBOLS).nonsecret_snapshot()


def write_yaml(tmp_path: Path, payload: object) -> Path:
    """R-07: every mutable YAML fixture is local to its test."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_GD_02_shipped_yaml_uses_exact_frozen_weights_and_levels() -> None:
    config = load_yaml_config(
        REPOSITORY_CONFIG, allowed_symbols=ALLOWED_SYMBOLS, settings=Settings()
    )
    assert config.watchlist == ("AAPL", "MSFT", "NVDA", "SPY", "QQQ", "XLK")
    assert config.schedule.scan_interval_minutes == 15
    assert config.alerts.alert_cooldown_sessions == 1
    assert set(config.playbooks) == {"TREND_50EMA", "BASE_BREAKOUT", "ANCHORED_VWAP_RECLAIM"}
    for playbook in config.playbooks.values():
        assert sum(playbook.criteria_weights.values(), Decimal("0")) == Decimal("1")
        assert playbook.stop_atr_mult == Decimal("2")
        assert playbook.target_r == Decimal("2")
    with pytest.raises(ValidationError):
        config.watchlist = ("NVDA",)
    with pytest.raises(ValidationError):
        config.schedule.scan_interval_minutes = 30
    with pytest.raises(TypeError):
        config.playbooks["TREND_50EMA"] = config.playbooks["BASE_BREAKOUT"]  # type: ignore[index]
    with pytest.raises(TypeError):
        config.playbooks["TREND_50EMA"].criteria_weights["trend"] = Decimal("0.9")  # type: ignore[index]


def test_R_04_GD_02_weight_validation_uses_an_explicit_decimal_context(
    valid_payload: dict[str, Any],
) -> None:
    with localcontext() as context:
        context.prec = 1
        YamlConfig.model_validate(valid_payload)
        valid_payload["playbooks"]["TREND_50EMA"]["criteria_weights"] = {"trend": "0.99"}
        with pytest.raises(ValidationError, match="sum to exactly"):
            YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize("symbols", [frozenset(), frozenset({"NVDA"})])
def test_R_02_watchlist_requires_explicit_authoritative_instruments(
    symbols: frozenset[str],
) -> None:
    with pytest.raises(ConfigurationError, match="instrument"):
        load_yaml_config(REPOSITORY_CONFIG, allowed_symbols=symbols)


@pytest.mark.parametrize("watchlist", [[], ["nvda"], [" NVDA"], ["NVDA", "NVDA"], [None], [True]])
def test_R_02_watchlist_rejects_missing_malformed_or_duplicated_symbols(
    valid_payload: dict[str, Any], watchlist: Any
) -> None:
    valid_payload["watchlist"] = watchlist
    with pytest.raises(ValidationError):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize(
    "risk_key",
    [
        "MAX_RISK_PER_TRADE",
        "max-risk-per-trade",
        "max_single_stock_weight",
        "MIN_CASH_PCT",
        "sector_caps",
        "theme_caps",
        "reserved_obligations_usd",
        "earnings_blackout_sessions",
        "min_setup_score",
        "proposal_ttl_sessions",
        "max_alerts_per_day",
        "TELEGRAM_CALLBACK_SECRET",
    ],
)
@pytest.mark.parametrize("location", ["root", "schedule", "weights", "arbitrary_nested"])
def test_R_06_yaml_rejects_env_risk_and_secret_keys_at_every_depth(
    valid_payload: dict[str, Any], risk_key: str, location: str
) -> None:
    if location == "root":
        valid_payload[risk_key] = "0.5"
    elif location == "schedule":
        valid_payload["schedule"][risk_key] = "0.5"
    elif location == "weights":
        valid_payload["playbooks"]["BASE_BREAKOUT"]["criteria_weights"][risk_key] = "0.5"
    else:
        valid_payload["unrecognized"] = {"nested": [{risk_key: "0.5"}]}
    with pytest.raises(ValidationError, match="YAML cannot contain env"):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize("location", ["root", "schedule", "alerts", "playbook"])
def test_GD_02_yaml_rejects_unrecognized_fields(
    valid_payload: dict[str, Any], location: str
) -> None:
    containers = {
        "root": valid_payload,
        "schedule": valid_payload["schedule"],
        "alerts": valid_payload["alerts"],
        "playbook": valid_payload["playbooks"]["TREND_50EMA"],
    }
    containers[location]["unrecognized_field"] = "value"
    with pytest.raises(ValidationError, match="Extra inputs"):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize("strategy", ["INTRADAY_ORB", "UNKNOWN"])
def test_GD_02_yaml_requires_only_supported_daily_playbooks(
    valid_payload: dict[str, Any], strategy: str
) -> None:
    valid_payload["playbooks"][strategy] = valid_payload["playbooks"].pop("BASE_BREAKOUT")
    with pytest.raises(ValidationError, match="three supported"):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize(
    "weights",
    [
        {},
        {"trend": "0"},
        {"trend": "0.99"},
        {"trend": "1.01"},
        {"trend": "NaN"},
        {"trend": "0.999999999999999999999999999999999999"},
        {"trend": 1.0},
        {"bad name": "1"},
    ],
)
def test_GD_02_invalid_weight_totals_types_and_names_are_rejected(
    valid_payload: dict[str, Any], weights: Any
) -> None:
    valid_payload["playbooks"]["TREND_50EMA"]["criteria_weights"] = weights
    with pytest.raises(ValidationError):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize(
    "field,boundary",
    [
        ("stop_atr_mult", "0.5"),
        ("stop_atr_mult", "10"),
        ("target_r", "1.5"),
        ("target_r", "10"),
    ],
)
def test_GD_02_playbook_level_exact_boundaries_pass(
    valid_payload: dict[str, Any], field: str, boundary: str
) -> None:
    valid_payload["playbooks"]["TREND_50EMA"][field] = boundary
    config = YamlConfig.model_validate(valid_payload)
    assert config.playbooks["TREND_50EMA"].__dict__[field] == Decimal(boundary)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("stop_atr_mult", "0.49"),
        ("stop_atr_mult", "10.01"),
        ("target_r", "1.49"),
        ("target_r", "10.01"),
        ("target_r", "NaN"),
        ("target_r", "Infinity"),
        ("stop_atr_mult", 2.0),
    ],
)
def test_GD_02_playbook_invalid_levels_fail_closed(
    valid_payload: dict[str, Any], field: str, bad: Any
) -> None:
    valid_payload["playbooks"]["TREND_50EMA"][field] = bad
    with pytest.raises(ValidationError):
        YamlConfig.model_validate(valid_payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("scan_interval_minutes", 20),
        ("offhours_interval_minutes", 120),
        ("scheduler_misfire_grace_seconds", 120),
        ("daily_bar_sip_lag_seconds", 1200),
        ("alert_cooldown_sessions", 2),
    ],
)
def test_GD_04_explicit_env_and_yaml_conflicts_fail(
    monkeypatch: pytest.MonkeyPatch, field: str, value: int
) -> None:
    monkeypatch.setenv(field.upper(), str(value))
    with pytest.raises(ConfigurationError, match="conflict"):
        load_yaml_config(REPOSITORY_CONFIG, allowed_symbols=ALLOWED_SYMBOLS, settings=Settings())


def test_GD_04_consistent_explicit_env_values_and_yaml_only_overrides_pass(
    monkeypatch: pytest.MonkeyPatch, valid_payload: dict[str, Any], tmp_path: Path
) -> None:
    monkeypatch.setenv("SCAN_INTERVAL_MINUTES", "15")
    load_yaml_config(REPOSITORY_CONFIG, allowed_symbols=ALLOWED_SYMBOLS, settings=Settings())
    monkeypatch.delenv("SCAN_INTERVAL_MINUTES")
    valid_payload["schedule"]["scan_interval_minutes"] = 20
    config = load_yaml_config(
        write_yaml(tmp_path, valid_payload), allowed_symbols=ALLOWED_SYMBOLS, settings=Settings()
    )
    assert config.schedule.scan_interval_minutes == 20
    assert Settings().scan_interval_minutes == 15


def test_R_03_GD_02_combined_hash_tracks_yaml_and_ignores_credentials(
    valid_payload: dict[str, Any],
) -> None:
    first = YamlConfig.model_validate(valid_payload)
    original_hash = Settings().with_yaml_hash(first)
    assert len(first.config_hash) == 64
    assert len(original_hash) == 64
    assert original_hash != Settings().config_hash
    credentials = Settings(
        llm_api_key=SecretStr("test-only-yaml-private-key"),
        telegram_bot_token=SecretStr("test-only-yaml-bot-token"),
    )
    assert credentials.with_yaml_hash(first) == original_hash
    valid_payload["playbooks"]["BASE_BREAKOUT"]["target_r"] = "3"
    second = YamlConfig.model_validate(valid_payload)
    assert second.config_hash != first.config_hash
    assert Settings().with_yaml_hash(second) != original_hash
    reordered = {
        "playbooks": first.nonsecret_snapshot()["playbooks"],
        "alerts": first.nonsecret_snapshot()["alerts"],
        "schedule": first.nonsecret_snapshot()["schedule"],
        "watchlist": first.nonsecret_snapshot()["watchlist"],
    }
    assert YamlConfig.model_validate(reordered).config_hash == first.config_hash


@pytest.mark.parametrize(
    "unsafe",
    [
        "!!python/object/apply:os.system ['echo unsafe']",
        "watchlist: &symbols [NVDA]\nother: *symbols\n",
        "watchlist: [NVDA]\nwatchlist: [AAPL]\n",
        "watchlist: [NVDA]\nschedule: {scan_interval_minutes: 15, scan_interval_minutes: 20}\n",
        "watchlist: [NVDA]\nschedule: {scan_interval_minutes: .nan}\n",
        "[]",
        "",
        "watchlist: [",
        "nested: " + "[" * 2000 + "0" + "]" * 2000,
    ],
)
def test_R_12_GD_02_unsafe_ambiguous_or_malformed_yaml_is_typed(
    tmp_path: Path, unsafe: str
) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text(unsafe, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_yaml_config(path, allowed_symbols=ALLOWED_SYMBOLS)


def test_R_12_GD_02_oversized_or_missing_yaml_is_typed(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_yaml_config(tmp_path / "absent.yaml", allowed_symbols=ALLOWED_SYMBOLS)
    oversized = tmp_path / "large.yaml"
    oversized.write_text("#" * 1_048_577, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_yaml_config(oversized, allowed_symbols=ALLOWED_SYMBOLS)


def test_R_12_GD_02_excessive_depth_and_non_string_keys_are_rejected(
    valid_payload: dict[str, Any],
) -> None:
    nested: dict[str, Any] = {}
    valid_payload["unrecognized"] = nested
    for _ in range(22):
        child: dict[str, Any] = {}
        nested["nested"] = child
        nested = child
    with pytest.raises(ValidationError, match="nesting"):
        YamlConfig.model_validate(valid_payload)
    with pytest.raises(ValidationError, match="keys must be strings"):
        YamlConfig.model_validate({1: "NVDA"})
```

### backend/tests/test_money.py

Scope: Stage A. SHA-256: e14367be5710744d19d5cd8d08401162cafe13f78a2a61b6e1d9fd56f0362e96.

```python
"""R-04: storage boundaries and absence of accidental float coercion."""

from decimal import Decimal, localcontext
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.core.errors import DataIntegrityError
from backend.core.money import (
    MAX_SCALED_MONEY,
    MIN_SCALED_MONEY,
    decimal_money,
    money_to_scaled,
    scaled_to_money,
    validate_cent_price,
)


@pytest.mark.parametrize(
    "text,scaled",
    [
        ("0", 0),
        ("1.234567", 1_234_567),
        ("-1.234567", -1_234_567),
        ("1.2300000", 1_230_000),
        ("9223372036854.775807", MAX_SCALED_MONEY),
        ("-9223372036854.775808", MIN_SCALED_MONEY),
    ],
)
def test_R_04_exact_micro_unit_boundaries(text: str, scaled: int) -> None:
    assert money_to_scaled(text) == scaled
    assert scaled_to_money(scaled) == Decimal(text)


@pytest.mark.parametrize(
    "bad",
    [
        float("1.25"),
        True,
        None,
        "NaN",
        "Infinity",
        "junk",
        "0.0000001",
        "9223372036854.775808",
        "-9223372036854.775809",
        "1e999999999",
        "1e-999999999",
    ],
)
def test_R_04_bad_money_raises_typed_error(bad: Any) -> None:
    with pytest.raises(DataIntegrityError):
        decimal_money(bad)


@pytest.mark.parametrize("bad", [True, float("1"), "1", MAX_SCALED_MONEY + 1, MIN_SCALED_MONEY - 1])
def test_R_04_scaled_money_rejects_coercion_and_overflow(bad: Any) -> None:
    with pytest.raises(DataIntegrityError):
        scaled_to_money(bad)


@given(st.integers(min_value=MIN_SCALED_MONEY, max_value=MAX_SCALED_MONEY))
def test_R_04_property_signed_integer_round_trip(value: int) -> None:
    assert money_to_scaled(scaled_to_money(value)) == value


def test_R_04_conversion_is_independent_of_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 4
        assert money_to_scaled("9223372036854.775807") == MAX_SCALED_MONEY
        assert scaled_to_money(MAX_SCALED_MONEY) == Decimal("9223372036854.775807")


@pytest.mark.parametrize("value", ["1", "1.23", "1.230000", "9223372036854.77"])
def test_R_13_cent_price_is_quantized_without_changing_value(value: str) -> None:
    with localcontext() as context:
        context.prec = 4
        result = validate_cent_price(Decimal(value))
    assert result == Decimal(value)
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize("value", ["0", "-1", "0.001", "1.231", "NaN", "Infinity"])
def test_R_13_subcent_or_invalid_price_fails_closed(value: str) -> None:
    with pytest.raises(DataIntegrityError):
        validate_cent_price(Decimal(value))


@pytest.mark.parametrize("value", [1, "1.00", float("1"), True, None])
def test_R_13_price_boundary_rejects_non_decimal(value: Any) -> None:
    with pytest.raises(DataIntegrityError):
        validate_cent_price(value)
```

### backend/tests/test_logging.py

Scope: Stage A. SHA-256: 2b1e983a7b12b7890292d11190c9bb6a1de04298cfe0d2820375a994b17fb286.

```python
"""R-07: credential redaction applies to structured and free-text logs."""

import io
import json
import logging

import pytest
import structlog
from pydantic import SecretStr

from backend.core.config import Settings
from backend.core.errors import ProviderError
from backend.core.logging import (
    REDACTED,
    RedactingFormatter,
    configure_logging,
    redact,
    redact_processor,
)
from backend.core.notifier import ConsoleNotifier, DeduplicatingNotifier


def test_R_07_recursive_redaction_does_not_modify_input() -> None:
    payload = {
        "api_key": "hidden-key",
        "nested": [{"secret": "hidden-secret"}],
        "value": SecretStr("hidden-object"),
        "ok": "ordinary",
    }
    result = redact(payload)
    text = json.dumps(result)
    for secret in ("hidden-key", "hidden-secret", "hidden-object"):
        assert secret not in text
    assert "ordinary" in text
    assert payload["api_key"] == "hidden-key"
    assert redact_processor(None, "info", {"authorization": "Bearer secret"}) == {
        "authorization": REDACTED
    }


def test_R_07_plaintext_configured_secrets_and_urls_are_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(broker_api_key=SecretStr("test-only-log-api"))
    configure_logging(settings.broker_api_key)
    structlog.get_logger().error(
        "request failed with test-only-log-api",
        payload={"token": "unknown-token"},
        database="postgresql://alice:unregistered-password@localhost/vws",
    )
    output = capsys.readouterr().out
    for secret in ("test-only-log-api", "unknown-token", "unregistered-password"):
        assert secret not in output
    assert REDACTED in output


def test_R_07_exception_trace_and_halt_notification_redaction(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(SecretStr("test-only-exception-secret"))
    try:
        raise RuntimeError("provider rejected test-only-exception-secret")
    except RuntimeError:
        structlog.get_logger().exception("provider_failure")
    ConsoleNotifier().notify("HALTED", "test-only-exception-secret is unavailable")
    output = capsys.readouterr().out
    assert "test-only-exception-secret" not in output
    assert "HALTED" in output
    assert "provider_failure" in output


def test_R_07_database_password_and_query_credentials_are_registered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    Settings(
        db_url=SecretStr(
            "postgresql://user:isolated-db-password@localhost/vws?token=isolated-db-token"
        )
    )
    configure_logging()
    structlog.get_logger().error("isolated-db-password isolated-db-token")
    output = capsys.readouterr().out
    assert "isolated-db-password" not in output
    assert "isolated-db-token" not in output


def test_R_07_typed_error_str_repr_and_args_are_redacted() -> None:
    configure_logging(SecretStr("fixture-exception-credential"))
    error = ProviderError("request failed for fixture-exception-credential")
    for rendered in (str(error), repr(error), repr(error.args)):
        assert "fixture-exception-credential" not in rendered
        assert REDACTED in rendered


def test_R_07_standard_logger_redacts_interpolation_and_traceback() -> None:
    configure_logging(SecretStr("fixture-standard-log-credential"))
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.Logger("isolated-sdk-test")
    logger.addHandler(handler)
    try:
        raise RuntimeError("fixture-standard-log-credential")
    except RuntimeError:
        logger.exception("SDK request %s", "fixture-standard-log-credential")
    assert "fixture-standard-log-credential" not in output.getvalue()
    assert REDACTED in output.getvalue()


def test_R_02_notifier_deduplicates_and_resets_after_recovery() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def notify(self, state: str, reason: str) -> None:
            self.calls.append((state, reason))

    recorder = Recorder()
    notifier = DeduplicatingNotifier(recorder)
    notifier.notify("HALTED", "stale quote")
    notifier.notify("HALTED", "stale quote")
    notifier.notify("HALTED", "ledger failure")
    assert len(recorder.calls) == 2
    notifier.reset()
    notifier.notify("HALTED", "stale quote")
    assert len(recorder.calls) == 3


def test_R_02_failed_notification_is_retried() -> None:
    class Failing:
        def __init__(self) -> None:
            self.calls = 0

        def notify(self, state: str, reason: str) -> None:
            self.calls += 1
            raise ProviderError("fixture notification failure")

    recorder = Failing()
    notifier = DeduplicatingNotifier(recorder)
    for _attempt in range(2):
        with pytest.raises(ProviderError):
            notifier.notify("HALTED", "fault")
    assert recorder.calls == 2


def test_R_07_arbitrary_repr_cannot_leak_after_redaction(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class UnsafePayload:
        def __repr__(self) -> str:
            raise RuntimeError("untrusted repr must never run")

    configure_logging(SecretStr("fixture-arbitrary-object-secret"))
    structlog.get_logger().error("object_boundary", payload=UnsafePayload())
    output = capsys.readouterr().out
    assert "fixture-arbitrary-object-secret" not in output
    assert REDACTED in output
    assert redact(42) == 42
    assert redact(None) is None
```

### backend/tests/test_ledger.py

Scope: Stage A. SHA-256: 90a20247cfae41d8614882dcb8aea8bc447e803b2fe09b7381a93084df30d584.

```python
"""R-01/R-02/R-04/R-05/R-08: immutable ledger and fail-closed inventory tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import (
    LEDGER_MODELS,
    Alert,
    AlertEvent,
    AppendControl,
    ComplianceCheck,
    ConfigSnapshot,
    DataSnapshot,
    Fill,
    LedgerRecord,
    LLMCall,
    Order,
    OrderEvent,
    PortfolioState,
    ResearchReport,
    RiskDecision,
    RiskRuleResult,
    SecurityEvent,
    Signal,
    SystemControl,
    SystemEvent,
    create_schema,
    transaction,
)
from backend.core.errors import (
    DataIntegrityError,
    LedgerIntegrityError,
    ReconciliationError,
    SafetyError,
)
from backend.core.ledger import GENESIS_HASH, Ledger, row_digest


def _snapshot(ledger: Ledger, clock: FrozenClock) -> DataSnapshot:
    return ledger.append(
        DataSnapshot,
        symbol="AAPL",
        timeframe="1Day",
        range_start=clock.now() - timedelta(days=1),
        range_end=clock.now(),
        feed="SIP",
        adjustment="ALL",
        fetched_at=clock.now(),
        bar_count=1,
        sha256="a" * 64,
        bars=[{"close": "100"}],
    )


def _signal(ledger: Ledger, clock: FrozenClock) -> Signal:
    snapshot = _snapshot(ledger, clock)
    return ledger.append(
        Signal,
        agent_name="deterministic_fixture",
        symbol="AAPL",
        direction="BUY",
        confidence=Decimal("0.8"),
        structured_thesis={"reason": "fixture"},
        invalidation="under stop",
        data_snapshot_id=snapshot.id,
        prompt_hash=None,
    )


def _order(ledger: Ledger, clock: FrozenClock, **overrides: Any) -> Order:
    signal = _signal(ledger, clock)
    fields: dict[str, Any] = {
        "proposal_id": uuid4(),
        "signal_id": signal.id,
        "client_order_id": str(uuid4()),
        "account_id": "paper-fixture",
        "symbol": "AAPL",
        "side": "BUY",
        "intent": "ENTRY",
        "qty": 2,
        "limit_price": Decimal(100),
        "stop_price": Decimal(95),
        "source": "SIGNAL",
    }
    fields.update(overrides)
    return ledger.append(Order, **fields)


def _submitted(ledger: Ledger, clock: FrozenClock) -> Order:
    order = _order(ledger, clock)
    for state in ("APPROVED", "SUBMITTED"):
        ledger.append(
            OrderEvent,
            order_id=order.id,
            state=state,
            reason="fixture",
            broker_order_id=None,
        )
    return order


def _all_records(ledger: Ledger, clock: FrozenClock) -> dict[type[LedgerRecord], LedgerRecord]:
    order = _submitted(ledger, clock)
    fill = ledger.record_fill(
        order.id,
        broker_fill_id="observed-1",
        qty=1,
        price=Decimal(99),
        filled_at=clock.now(),
    )
    verdict = ledger.append(
        RiskDecision,
        proposal_id=order.proposal_id,
        decision="APPROVED",
        config_hash="b" * 64,
        snapshot_hash="c" * 64,
        evaluated_at=clock.now(),
    )
    ledger.append(
        RiskRuleResult,
        risk_decision_id=verdict.id,
        rule_id="CRO-01",
        passed=1,
        severity="BLOCK",
        observed={"state": "RUNNING"},
        limit={},
        message="allowed",
    )
    ledger.append(
        ComplianceCheck,
        proposal_id=order.proposal_id,
        rule_id="CMP-01",
        passed=1,
        severity="WARN",
        observed={},
        limit={},
        message="no loss sale",
        checked_at=clock.now(),
    )
    ledger.append(
        PortfolioState,
        account_id="paper-fixture",
        account_type="CASH",
        as_of=clock.now(),
        equity=Decimal(1000),
        cash=Decimal(901),
        settled_cash=Decimal(901),
        positions={"AAPL": {"qty": 1}},
        high_water_mark=Decimal(1000),
        day_start_equity=Decimal(1000),
    )
    with transaction(ledger.engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None
        control.state = "REDUCE_ONLY"
        control.version += 1
        ledger.append_in_session(
            session,
            SystemEvent,
            state="REDUCE_ONLY",
            reason="fixture",
            operator_id=None,
            event_type="ESCALATE",
        )
    ledger.append(ConfigSnapshot, config_hash="d" * 64, settings={"paper_trading": True})
    alert = ledger.append(
        Alert,
        proposal_id=order.proposal_id,
        signal_id=order.signal_id,
        symbol=order.symbol,
        playbook="BASE_BREAKOUT",
        score=Decimal("8.50"),
        card_text="audit fixture candidate",
        config_hash="d" * 64,
        expires_at=clock.now() + timedelta(hours=1),
    )
    ledger.append(
        ResearchReport,
        alert_id=alert.id,
        agent_name="flow",
        status="UNAVAILABLE",
        payload={"reason": "provider unavailable"},
    )
    ledger.append(
        AlertEvent,
        alert_id=alert.id,
        state="SENT",
        telegram_chat_id=123,
        telegram_message_id=456,
        reason="delivery fixture",
    )
    ledger.record_trade_ticket(
        alert.id,
        telegram_user_id=789,
        reasons=[{"rule_id": "CRO-01", "passed": True}],
        valid_until=alert.expires_at,
    )
    ledger.append(
        LLMCall,
        provider="fixture",
        base_url_host="example.invalid",
        model="test-model",
        prompt_hash="e" * 64,
        input_tokens=10,
        output_tokens=20,
        est_cost_usd=Decimal("0.000123"),
        latency_ms=15,
        outcome="VALID",
    )
    ledger.append(
        SecurityEvent,
        kind="BAD_HMAC",
        telegram_user_id=999,
        detail={"reason": "fixture signature rejected"},
    )
    assert fill.id is not None
    with Session(ledger.engine) as session:
        result: dict[type[LedgerRecord], LedgerRecord] = {}
        for model in LEDGER_MODELS:
            record = session.scalar(select(model).order_by(model.seq).limit(1))
            assert record is not None
            result[model] = record
        return result


def test_R_02_R_04_R_05_all_tables_roundtrip_and_global_chain(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    records = _all_records(ledger, clock)
    ledger.verify_chain()
    assert records[DataSnapshot].prev_hash == GENESIS_HASH
    with Session(engine) as session:
        order = session.scalar(select(Order))
        assert order is not None
        assert order.limit_price == Decimal(100)
        assert order.created_at == clock.now()
        assert order.created_at.tzinfo is not None
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT limit_price, typeof(limit_price) FROM orders")
        ).one()
        assert stored == (100_000_000, "integer")


@pytest.mark.parametrize("model", LEDGER_MODELS, ids=lambda model: model.__tablename__)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_R_02_raw_SQL_append_only_every_table(
    engine: Engine, clock: FrozenClock, model: type[LedgerRecord], operation: str
) -> None:
    ledger = Ledger(engine, clock)
    _all_records(ledger, clock)
    statement = (
        f"UPDATE {model.__tablename__} SET seq = seq"
        if operation == "UPDATE"
        else f"DELETE FROM {model.__tablename__}"
    )
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.exec_driver_sql(statement)
    ledger.verify_chain()


@pytest.mark.parametrize("model", LEDGER_MODELS, ids=lambda model: model.__tablename__)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_R_02_ORM_append_only_every_table(
    engine: Engine, clock: FrozenClock, model: type[LedgerRecord], operation: str
) -> None:
    ledger = Ledger(engine, clock)
    records = _all_records(ledger, clock)
    with pytest.raises(LedgerIntegrityError, match="Append-only"), transaction(engine) as session:
        record = session.get(model, records[model].id)
        assert record is not None
        if operation == "UPDATE":
            record.created_at = clock.now() - timedelta(seconds=1)
        else:
            session.delete(record)
    ledger.verify_chain()


@pytest.mark.parametrize("model", LEDGER_MODELS, ids=lambda model: model.__tablename__)
@pytest.mark.parametrize("conflict", ["id", "seq"])
def test_R_02_raw_SQL_replace_cannot_delete_immutable_rows(
    engine: Engine, clock: FrozenClock, model: type[LedgerRecord], conflict: str
) -> None:
    """R-02: SQLite REPLACE's implicit DELETE must invoke the append-only trigger."""
    ledger = Ledger(engine, clock)
    original = _all_records(ledger, clock)[model]
    values = {column.name: original.__dict__[column.name] for column in model.__table__.columns}
    if conflict == "id":
        values["seq"] = original.seq + 10_000
    else:
        values["id"] = uuid4()
    values["created_at"] = clock.now() - timedelta(seconds=1)
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(insert(model).prefix_with("OR REPLACE").values(**values))
    with Session(engine) as session:
        unchanged = session.get(model, original.id)
        assert unchanged is not None
        assert unchanged.seq == original.seq and unchanged.created_at == original.created_at
        assert unchanged.row_hash == original.row_hash
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA recursive_triggers").scalar_one() == 1
    ledger.verify_chain()


@pytest.mark.parametrize(
    "fields",
    [
        {"qty": 0},
        {"qty": -1},
        {"qty": Decimal("1.5")},
        {"qty": True},
        {"limit_price": Decimal(0)},
        {"side": "SHORT"},
        {"order_type": "MARKET"},
        {"stop_price": None},
        {"stop_price": Decimal(100)},
        {"signal_id": uuid4()},
        {"signal_id": None},
        {"source": "SYSTEM"},
    ],
)
def test_R_01_R_02_constraints_reject_bad_order(
    engine: Engine, clock: FrozenClock, fields: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(SafetyError):
        _order(ledger, clock, **fields)
    ledger.verify_chain()
    with Session(engine) as session:
        assert session.scalar(select(Order)) is None


def test_R_02_order_unique_client_id_and_proposal_FK(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    first = _order(ledger, clock)
    with pytest.raises(SafetyError):
        _order(ledger, clock, client_order_id=first.client_order_id)
    with pytest.raises(SafetyError):
        ledger.append(
            RiskDecision,
            proposal_id=uuid4(),
            decision="APPROVED",
            config_hash="a" * 64,
            snapshot_hash="b" * 64,
            evaluated_at=clock.now(),
        )
    ledger.verify_chain()


def test_R_02_corrupt_row_detected_and_halt_survives_restart(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    _snapshot(ledger, clock)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_data_snapshots_update")
        connection.exec_driver_sql("UPDATE data_snapshots SET symbol = 'CORRUPTED'")
    create_schema(engine)
    with pytest.raises(LedgerIntegrityError, match="HALTED"):
        ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"
    with pytest.raises(LedgerIntegrityError):
        Ledger(engine, clock).verify_chain()


def test_R_02_mutable_control_cannot_clear_halt(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    with transaction(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None
        control.state = "HALTED"
        control.version += 1
        ledger.append_in_session(
            session,
            SystemEvent,
            state="HALTED",
            reason="fixture",
            operator_id=None,
            event_type="ESCALATE",
        )
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE system_control SET state = 'RUNNING'")
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"
    ledger.verify_chain()


def test_R_02_lifecycle_and_readonly_fill_recording(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    order = _submitted(ledger, clock)
    for index in (1, 2):
        ledger.record_fill(
            order.id,
            broker_fill_id=f"fill-{index}",
            qty=1,
            price=Decimal(99),
            filled_at=clock.now(),
        )
    ledger.verify_chain()
    with Session(engine) as session:
        states = list(session.scalars(select(OrderEvent.state).order_by(OrderEvent.seq)))
    assert states == ["PROPOSED", "APPROVED", "SUBMITTED", "PARTIALLY_FILLED", "FILLED"]
    with pytest.raises(LedgerIntegrityError):
        ledger.append(
            OrderEvent,
            order_id=order.id,
            state="APPROVED",
            reason="bad",
            broker_order_id=None,
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"qty": 3},
        {"qty": 0},
        {"qty": True},
        {"price": Decimal(101)},
        {"price": Decimal("NaN")},
        {"filled_at": datetime(2099, 1, 1, tzinfo=UTC)},
        {"filled_at": datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)},
        {"order_id": uuid4()},
    ],
)
def test_R_02_bad_observed_fill_halts(
    engine: Engine, clock: FrozenClock, fields: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    order = _submitted(ledger, clock)
    values: dict[str, Any] = {
        "order_id": order.id,
        "broker_fill_id": "bad-fill",
        "qty": 1,
        "price": Decimal(99),
        "filled_at": clock.now(),
    }
    values.update(fields)
    with pytest.raises(ReconciliationError):
        ledger.record_fill(**values)
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"
        assert session.scalar(select(Fill)) is None
    ledger.verify_chain()


def test_R_02_raw_invalid_transition_detected_even_with_recomputed_hash(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    _order(ledger, clock)
    with Session(engine) as session:
        record = session.scalar(select(OrderEvent))
        assert record is not None
        session.expunge(record)
    record.state = "SUBMITTED"
    new_hash = row_digest(record)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_order_events_update")
        connection.execute(
            text("UPDATE order_events SET state = 'SUBMITTED', row_hash = :hash"),
            {"hash": new_hash},
        )
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()


@pytest.mark.parametrize(
    "broker,local",
    [
        ({"AAPL": 1}, {"AAPL": 2}),
        ({"AAPL": -1}, {}),
        ({"AAPL": True}, {}),
        ({"AAPL": Decimal("1.5")}, {}),
        ({"": 1}, {}),
    ],
)
def test_R_01_R_02_reconciliation_break_persists_halt(
    engine: Engine, clock: FrozenClock, broker: dict[str, Any], local: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(ReconciliationError):
        ledger.reconcile(broker, local)
    ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"


def test_R_01_R_02_matching_reconciliation_accepts_zero_absence(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    ledger.reconcile({"AAPL": 2, "MSFT": 0}, {"AAPL": 2})
    ledger.verify_chain()


def test_R_02_concurrent_appends_have_one_global_sequence(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)

    def append_one(index: int) -> UUID:
        record = ledger.append(
            ConfigSnapshot, config_hash=f"{index:064x}", settings={"index": index}
        )
        return record.id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(append_one, range(20)))
    assert len(set(ids)) == 20
    ledger.verify_chain()
    with Session(engine) as session:
        assert list(
            session.scalars(select(ConfigSnapshot.seq).order_by(ConfigSnapshot.seq))
        ) == list(range(1, 21))


@pytest.mark.parametrize("settings", [{"limit": 0.1}, {"broker_secret": "sensitive"}])
def test_R_04_R_07_ledger_rejects_float_and_secrets(
    engine: Engine, clock: FrozenClock, settings: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(DataIntegrityError):
        ledger.append(ConfigSnapshot, config_hash="a" * 64, settings=settings)
    ledger.verify_chain()


def test_R_02_allocation_corruption_halts(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    _snapshot(ledger, clock)
    with transaction(engine) as session:
        allocation = session.get(AppendControl, 1)
        assert allocation is not None
        allocation.next_seq = 10
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"


def _portfolio(ledger: Ledger, clock: FrozenClock, **changes: Any) -> PortfolioState:
    fields: dict[str, Any] = {
        "account_id": "paper-account",
        "account_type": "CASH",
        "as_of": clock.now(),
        "equity": Decimal("100"),
        "cash": Decimal("100"),
        "settled_cash": Decimal("60"),
        "positions": {},
        "high_water_mark": Decimal("120"),
        "day_start_equity": Decimal("110"),
    }
    fields.update(changes)
    return ledger.append(PortfolioState, **fields)


@pytest.mark.parametrize(
    "amount,high,day,settled",
    [
        (Decimal("50"), Decimal("180"), Decimal("165"), Decimal("60")),
        (Decimal("-30"), Decimal("84"), Decimal("77"), Decimal("30")),
        (Decimal("-80"), Decimal("24"), Decimal("22"), Decimal("0")),
    ],
)
def test_CRO_09_CRO_10_R_08_cash_flow_scales_both_marks_without_changing_loss(
    engine: Engine,
    clock: FrozenClock,
    amount: Decimal,
    high: Decimal,
    day: Decimal,
    settled: Decimal,
) -> None:
    ledger = Ledger(engine, clock)
    prior = _portfolio(ledger, clock)
    current = ledger.record_cash_flow("paper-account", amount, clock.now(), Decimal("100"))
    assert current.high_water_mark == high
    assert current.day_start_equity == day
    assert current.settled_cash == settled
    assert current.equity == current.cash == Decimal("100") + amount
    assert current.equity * prior.high_water_mark == prior.equity * current.high_water_mark
    assert current.equity * prior.day_start_equity == prior.equity * current.day_start_equity
    assert current.cash_flow_amount == amount and current.cash_flow_at == clock.now()
    ledger.verify_chain()


def test_CRO_09_CRO_10_cash_flow_rational_marks_round_conservatively_up(
    engine: Engine,
    clock: FrozenClock,
) -> None:
    ledger = Ledger(engine, clock)
    _portfolio(
        ledger,
        clock,
        equity=Decimal("3"),
        cash=Decimal("3"),
        settled_cash=Decimal("1"),
        high_water_mark=Decimal("10"),
        day_start_equity=Decimal("7"),
    )
    current = ledger.record_cash_flow("paper-account", Decimal("1"), clock.now(), Decimal("3"))
    assert current.high_water_mark == Decimal("13.333334")
    assert current.day_start_equity == Decimal("9.333334")
    ledger.verify_chain()


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "missing"},
        {"equity_before": Decimal("0")},
        {"equity_before": Decimal("99")},
        {"amount": Decimal("-100")},
        {"amount": Decimal("NaN")},
        {"amount": "1"},
        {"ts": datetime(2099, 1, 1, tzinfo=UTC)},
        {"ts": datetime(2020, 1, 1, tzinfo=UTC)},
    ],
)
def test_CRO_09_R_02_unverifiable_cash_flow_halts(
    engine: Engine,
    clock: FrozenClock,
    changes: dict[str, Any],
) -> None:
    ledger = Ledger(engine, clock)
    _portfolio(ledger, clock)
    fields: dict[str, Any] = {
        "account_id": "paper-account",
        "amount": Decimal("1"),
        "ts": clock.now(),
        "equity_before": Decimal("100"),
    }
    fields.update(changes)
    with pytest.raises(ReconciliationError):
        ledger.record_cash_flow(**fields)
    ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"


def test_R_07_snapshot_permits_token_path_metadata_but_rejects_nested_credentials(
    engine: Engine,
    clock: FrozenClock,
) -> None:
    ledger = Ledger(engine, clock)
    ledger.append(
        ConfigSnapshot,
        config_hash="a" * 64,
        settings={
            "plaid_token_path": "C:/private/token.enc",
            "database_identity": {"driver": "sqlite"},
        },
    )
    with pytest.raises(DataIntegrityError):
        ledger.append(
            ConfigSnapshot, config_hash="b" * 64, settings={"broker": {"password": "secret"}}
        )
    ledger.verify_chain()


def test_R_02_INITIALIZED_cannot_deescalate_or_repeat(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    with transaction(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None
        control.state = "HALTED"
        control.version = 1
        ledger.append_in_session(
            session,
            SystemEvent,
            state="HALTED",
            reason="fixture",
            event_type="ESCALATE",
            operator_id=None,
        )
    for state in ("RUNNING", "HALTED"):
        with pytest.raises(LedgerIntegrityError):
            ledger.append(
                SystemEvent,
                state=state,
                reason="invalid initializer",
                event_type="INITIALIZED",
                operator_id=None,
            )
    ledger.verify_chain()
```

### backend/tests/test_research_ledger.py

Scope: Stage A. SHA-256: c9ba8b65c1324c2b61c873c0db189d970871d12b83d12b593aa72ba7caa8bb6c.

```python
"""GD-01/GD-03/GD-05/R-10/R-14: immutable evidence, expiry and replay defenses."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import (
    Alert,
    AlertEvent,
    AppendControl,
    ApprovalEvent,
    ConfigSnapshot,
    DataSnapshot,
    LedgerRecord,
    LLMCall,
    Order,
    ResearchReport,
    SchemaMeta,
    Signal,
    SystemControl,
    TradeTicket,
    create_database,
    create_schema,
    transaction,
)
from backend.core.errors import DatabaseError, LedgerIntegrityError, SafetyError
from backend.core.ledger import GENESIS_HASH, Ledger, row_digest, ticket_digest

RecordT = TypeVar("RecordT", bound=LedgerRecord)


def _candidate(ledger: Ledger, clock: FrozenClock) -> Alert:
    snapshot = ledger.append(
        DataSnapshot,
        symbol="AAPL",
        timeframe="1Day",
        range_start=clock.now() - timedelta(days=1),
        range_end=clock.now(),
        feed="SIP",
        adjustment="ALL",
        fetched_at=clock.now(),
        bar_count=0,
        sha256="a" * 64,
    )
    signal = ledger.append(
        Signal,
        agent_name="deterministic-fixture",
        symbol="AAPL",
        direction="BUY",
        confidence=Decimal("0.85"),
        structured_thesis={"source": "fixture"},
        invalidation="close below structural stop",
        data_snapshot_id=snapshot.id,
    )
    proposal = ledger.append(
        Order,
        proposal_id=uuid4(),
        signal_id=signal.id,
        client_order_id=str(uuid4()),
        account_id="isolated-paper-account",
        symbol="AAPL",
        side="BUY",
        intent="ENTRY",
        qty=2,
        limit_price=Decimal("100.00"),
        stop_price=Decimal("95.00"),
        target_price=Decimal("110.00"),
        source="SIGNAL",
    )
    return ledger.append(
        Alert,
        proposal_id=proposal.proposal_id,
        signal_id=signal.id,
        symbol="AAPL",
        playbook="BASE_BREAKOUT",
        score=Decimal("8.50"),
        card_text="deterministic fixture card",
        config_hash="b" * 64,
        expires_at=clock.now() + timedelta(hours=1),
    )


def _deliver(ledger: Ledger, alert: Alert) -> AlertEvent:
    return ledger.append(
        AlertEvent,
        alert_id=alert.id,
        state="SENT",
        telegram_chat_id=-123,
        telegram_message_id=456,
        reason="observed delivery succeeded",
    )


def _ticket(ledger: Ledger, alert: Alert) -> TradeTicket:
    return ledger.record_trade_ticket(
        alert.id,
        telegram_user_id=789,
        reasons=[{"rule_id": "CRO-01", "passed": True}],
        valid_until=alert.expires_at,
    )


def _raw_append(ledger: Ledger, model: type[RecordT], **fields: Any) -> RecordT:
    """R-02: simulate hash-valid malicious INSERT that bypasses the local writer."""
    with transaction(ledger.engine) as session:
        control = session.get(AppendControl, 1)
        assert control is not None
        values = {column.name: None for column in model.__table__.columns if column.nullable}
        values.update(fields)
        record = model(**values)
        record.id = uuid4()
        record.seq = control.next_seq
        record.created_at = ledger.clock.now()
        previous = session.scalar(select(model).order_by(model.seq.desc()).limit(1))
        record.prev_hash = GENESIS_HASH if previous is None else previous.row_hash
        record.row_hash = row_digest(record)
        session.execute(
            insert(model),
            {column.name: record.__dict__[column.name] for column in model.__table__.columns},
        )
        control.next_seq += 1
    return record


def test_GD_05_R_14_delivery_is_an_appended_actionable_projection(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    assert alert.alert_id == alert.id
    assert ledger.current_alert_status(alert.id) == "PENDING"
    assert not ledger.alert_is_actionable(alert.id)
    _deliver(ledger, alert)
    assert ledger.current_alert_status(alert.id) == "SENT"
    assert ledger.alert_is_actionable(alert.id)
    with Session(engine) as session:
        original = session.get(Alert, alert.id)
        assert original is not None and original.status == "PENDING"
        assert original.telegram_message_id is None
        assert list(session.scalars(select(AlertEvent.state).order_by(AlertEvent.seq))) == [
            "PENDING",
            "SENT",
        ]
    ledger.verify_chain()


def test_GD_05_R_05_delivery_cannot_predate_its_parent_alert(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    with pytest.raises(LedgerIntegrityError, match="precedes"):
        ledger.append(
            AlertEvent,
            alert_id=alert.id,
            state="SENT",
            telegram_chat_id=-123,
            telegram_message_id=456,
            reason="invalid earlier delivery timestamp",
            created_at=clock.now() - timedelta(seconds=1),
        )
    assert ledger.current_alert_status(alert.id) == "PENDING"
    with Session(engine) as session:
        assert len(list(session.scalars(select(AlertEvent)))) == 1
    ledger.verify_chain()


def test_GD_05_R_05_approval_cannot_postdate_its_own_creation(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    later = Ledger(engine, FrozenClock(clock.now() + timedelta(seconds=2)))
    with pytest.raises(LedgerIntegrityError, match="timestamp"):
        later.append(
            ApprovalEvent,
            alert_id=alert.id,
            action="USER_VETOED",
            telegram_user_id=789,
            ts=later.clock.now(),
            created_at=clock.now() + timedelta(seconds=1),
            reasons=[],
        )
    assert later.current_alert_status(alert.id) == "SENT"
    with Session(engine) as session:
        assert session.scalar(select(ApprovalEvent)) is None
    later.verify_chain()


def test_GD_05_R_10_R_14_manual_ticket_binds_exact_local_proposal(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    ticket = _ticket(ledger, alert)
    assert ticket.ticket_id == ticket.id
    assert ticket.ticket_sha256 == ticket_digest(ticket)
    assert ticket.alert_id == alert.id
    assert ticket.qty == 2 and ticket.limit_price == Decimal("100.00")
    assert ticket.limit_price.as_tuple().exponent == -2
    assert ticket.stop_price == Decimal("95.00") and ticket.target_price == Decimal("110.00")
    assert ledger.current_alert_status(alert.id) == "APPROVED"
    assert not ledger.alert_is_actionable(alert.id)
    ledger.verify_chain()
    with Session(engine) as session:
        loaded_ticket = session.get(TradeTicket, ticket.id)
        assert loaded_ticket is not None and loaded_ticket.limit_price.as_tuple().exponent == -2
        decision = session.scalar(select(ApprovalEvent))
        assert decision is not None
        assert decision.event_id == decision.id
        assert decision.action == "MANUALLY_APPROVED" and decision.telegram_user_id == 789


def test_GD_05_R_14_replay_and_concurrent_tickets_are_single_use(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)

    def attempt(_: int) -> UUID | None:
        try:
            return _ticket(ledger, alert).id
        except LedgerIntegrityError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert sum(result is not None for result in results) == 1
    with pytest.raises(LedgerIntegrityError):
        _ticket(ledger, alert)
    with Session(engine) as session:
        assert len(list(session.scalars(select(ApprovalEvent)))) == 1
        assert len(list(session.scalars(select(TradeTicket)))) == 1
    ledger.verify_chain()


@pytest.mark.parametrize("seconds", [-1, 0, 3601])
def test_GD_05_R_14_invalid_ticket_interval_rolls_back_human_decision(
    engine: Engine, clock: FrozenClock, seconds: int
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    with pytest.raises(LedgerIntegrityError):
        ledger.record_trade_ticket(
            alert.id,
            telegram_user_id=789,
            reasons=[],
            valid_until=clock.now() + timedelta(seconds=seconds),
        )
    assert ledger.current_alert_status(alert.id) == "SENT"
    with Session(engine) as session:
        assert session.scalar(select(ApprovalEvent)) is None
        assert session.scalar(select(TradeTicket)) is None
    ledger.verify_chain()


def test_GD_05_R_14_expiry_at_exact_boundary_is_terminal(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    expired = Ledger(engine, FrozenClock(alert.expires_at))
    assert not expired.alert_is_actionable(alert.id)
    with pytest.raises(LedgerIntegrityError, match="Expired"):
        _ticket(expired, alert)
    expired.append(ApprovalEvent, alert_id=alert.id, action="EXPIRED", reasons=[])
    assert expired.current_alert_status(alert.id) == "EXPIRED"
    expired.verify_chain()


@pytest.mark.parametrize("action", ["USER_VETOED", "REVALIDATION_FAILED"])
def test_GD_05_R_14_terminal_decisions_cannot_later_create_tickets(
    engine: Engine, clock: FrozenClock, action: str
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    ledger.append(
        ApprovalEvent,
        alert_id=alert.id,
        action=action,
        telegram_user_id=789,
        reasons=[{"rule_id": "CRO-07", "passed": False}],
    )
    with pytest.raises(LedgerIntegrityError):
        _ticket(ledger, alert)
    assert ledger.current_alert_status(alert.id) in {"REJECTED", "REVALIDATION_FAILED"}
    ledger.verify_chain()


@pytest.mark.parametrize(
    "fields",
    [
        {"action": "MANUALLY_APPROVED", "telegram_user_id": None},
        {"action": "MANUALLY_APPROVED", "telegram_user_id": True},
        {"action": "MANUALLY_APPROVED", "telegram_user_id": -1},
        {"action": "EXPIRED"},
        {"action": "REVALIDATION_FAILED", "reasons": []},
        {"action": "UNRECOGNIZED"},
    ],
)
def test_GD_05_R_14_bad_approval_evidence_cannot_consume_alert(
    engine: Engine, clock: FrozenClock, fields: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    values: dict[str, Any] = {
        "alert_id": alert.id,
        "telegram_user_id": 789,
        "reasons": [{"rule_id": "CRO-01", "passed": True}],
    }
    values.update(fields)
    with pytest.raises(SafetyError):
        ledger.append(ApprovalEvent, **values)
    assert ledger.current_alert_status(alert.id) == "SENT"
    ledger.verify_chain()


@pytest.mark.parametrize("operation", ["verify", "status", "actionable", "ticket"])
def test_GD_05_R_14_hash_valid_raw_approval_without_delivery_halts(
    engine: Engine, clock: FrozenClock, operation: str
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    approval = _raw_append(
        ledger,
        ApprovalEvent,
        alert_id=alert.id,
        action="MANUALLY_APPROVED",
        telegram_user_id=789,
        ts=clock.now(),
        reasons=[],
    )
    _raw_append(
        ledger,
        AlertEvent,
        alert_id=alert.id,
        state="APPROVED",
        approval_event_id=approval.id,
        reason="forged event",
    )
    with pytest.raises(LedgerIntegrityError, match="HALTED"):
        if operation == "verify":
            ledger.verify_chain()
        elif operation == "status":
            ledger.current_alert_status(alert.id)
        elif operation == "actionable":
            ledger.alert_is_actionable(alert.id)
        else:
            _ticket(ledger, alert)
    with Session(engine) as session:
        state = session.get(SystemControl, 1)
        assert state is not None and state.state == "HALTED"


def test_GD_05_R_14_rehashed_ticket_tampering_cannot_change_qty(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    ticket = _ticket(ledger, alert)
    ticket.qty += 1
    ticket.ticket_sha256 = ticket_digest(ticket)
    digest = row_digest(ticket)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_trade_tickets_update")
        connection.execute(
            text("UPDATE trade_tickets SET qty = :qty, ticket_sha256 = :ticket, row_hash = :row"),
            {"qty": ticket.qty, "ticket": ticket.ticket_sha256, "row": digest},
        )
    with pytest.raises(LedgerIntegrityError, match="HALTED"):
        ledger.verify_chain()


def _llm_values() -> dict[str, Any]:
    return {
        "provider": "fixture-provider",
        "base_url_host": "example.invalid",
        "model": "explicit-fixture-model",
        "prompt_hash": "c" * 64,
        "input_tokens": 10,
        "output_tokens": 20,
        "est_cost_usd": Decimal("0.000001"),
        "latency_ms": 1,
        "outcome": "VALID",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"est_cost_usd": Decimal("-0.000001")},
        {"est_cost_usd": Decimal("NaN")},
        {"est_cost_usd": 0.01},
        {"est_cost_usd": None},
        {"input_tokens": None},
        {"input_tokens": -1},
        {"input_tokens": Decimal("1.5")},
        {"output_tokens": True},
        {"latency_ms": -1},
        {"outcome": "BUDGET"},
        {"outcome": "UNKNOWN"},
        {"base_url_host": "https://user:secret@example.invalid/v1"},
    ],
)
def test_GD_01_R_02_llm_usage_and_cost_fail_closed(
    engine: Engine, clock: FrozenClock, changes: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    fields = _llm_values()
    fields.update(changes)
    with pytest.raises(SafetyError):
        ledger.append(LLMCall, **fields)
    with Session(engine) as session:
        assert session.scalar(select(LLMCall)) is None
    ledger.verify_chain()


def test_GD_01_timeout_usage_is_unknown_and_budget_veto_is_zero_cost(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    fields = _llm_values()
    fields.update(outcome="TIMEOUT", input_tokens=None, output_tokens=None, est_cost_usd=None)
    transport_failure = ledger.append(LLMCall, **fields)
    assert transport_failure.est_cost_usd is None
    fields.update(outcome="BUDGET", input_tokens=0, output_tokens=0, est_cost_usd=Decimal(0))
    budget = ledger.append(LLMCall, **fields)
    assert budget.est_cost_usd == Decimal(0)
    ledger.verify_chain()


@pytest.mark.parametrize(
    "changes",
    [
        {"est_cost_usd": Decimal("-0.000001")},
        {"est_cost_usd": None},
        {"input_tokens": -1},
        {"outcome": "BUDGET", "input_tokens": None, "output_tokens": None, "est_cost_usd": None},
        {"outcome": "UNKNOWN"},
    ],
)
def test_GD_01_raw_SQL_llm_cost_and_usage_checks_cannot_be_bypassed(
    engine: Engine, clock: FrozenClock, changes: dict[str, Any]
) -> None:
    fields = _llm_values()
    fields.update(
        id=uuid4(),
        seq=1,
        created_at=clock.now(),
        prev_hash=GENESIS_HASH,
        row_hash=GENESIS_HASH,
    )
    fields.update(changes)
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(insert(LLMCall).values(**fields))
    Ledger(engine, clock).verify_chain()


@pytest.mark.parametrize(
    "settings",
    [
        {"providers": [{"password": "sensitive-fixture"}]},
        {"providers": [{"inner": [{"api_key": "sensitive-fixture"}]}]},
        [{"max_weight": "0.10"}],
    ],
)
def test_R_07_config_secret_fields_in_nested_arrays_and_bad_outer_shape_reject(
    engine: Engine, clock: FrozenClock, settings: Any
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(SafetyError):
        ledger.append(ConfigSnapshot, config_hash="d" * 64, settings=settings)
    ledger.verify_chain()


@pytest.mark.parametrize(
    "model,changes",
    [
        (Alert, {"signal_id": None}),
        (Alert, {"score": Decimal("10.01")}),
        (Alert, {"score": Decimal("0.99")}),
        (Alert, {"status": "APPROVED"}),
        (Alert, {"signal_id": uuid4()}),
        (Alert, {"proposal_id": uuid4()}),
        (AlertEvent, {"state": "SENT", "telegram_chat_id": None}),
        (AlertEvent, {"state": "SENT", "telegram_message_id": None}),
        (AlertEvent, {"state": "APPROVED", "approval_event_id": None}),
    ],
)
def test_GD_03_GD_05_raw_SQL_checks_and_foreign_keys_reject_bad_evidence(
    engine: Engine, clock: FrozenClock, model: type[LedgerRecord], changes: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    if model is Alert:
        values = {column.name: alert.__dict__[column.name] for column in model.__table__.columns}
    else:
        values = {
            "alert_id": alert.id,
            "state": "SENT",
            "telegram_chat_id": -123,
            "telegram_message_id": 456,
            "approval_event_id": None,
            "reason": "fixture",
            "created_at": clock.now(),
            "prev_hash": GENESIS_HASH,
            "row_hash": GENESIS_HASH,
        }
    values.update(id=uuid4(), seq=1000)
    values.update(changes)
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(insert(model).values(**values))
    ledger.verify_chain()


def test_R_02_schema_version_guard_does_not_silently_extend_an_old_ledger(tmp_path: Path) -> None:
    engine = create_database(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE signals (id TEXT PRIMARY KEY)")
        with pytest.raises(DatabaseError, match="migration"):
            create_schema(engine)
        assert inspect(engine).get_table_names() == ["signals"]
    finally:
        engine.dispose()


def test_R_02_schema_version_tampering_is_rejected(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(update(SchemaMeta).values(version=1))
    with pytest.raises(DatabaseError, match="incompatible"):
        create_schema(engine)


def test_GD_03_R_02_research_missing_alert_provenance_rejects(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(SafetyError):
        ledger.append(
            ResearchReport,
            alert_id=uuid4(),
            agent_name="fixture",
            status="UNAVAILABLE",
            payload={"reason": "provider unavailable"},
        )
    ledger.verify_chain()
```

### backend/tests/test_system_state.py

Scope: Stage A. SHA-256: ec31578ab3ad549678d56c3e5d1bff04cc9a395b2ce64ecfa922d963a567bf3f.

```python
"""CRO-01/CRO-09/CRO-10/R-09: persistent state, limits and fault branches."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any, cast

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import SystemControl, SystemEvent, transaction
from backend.core.errors import (
    DatabaseError,
    DataIntegrityError,
    LedgerIntegrityError,
    StateTransitionError,
)
from backend.core.system_state import (
    SystemState,
    SystemStateStore,
    financial_state,
    require_integrity,
    state_allows,
)


class RecordingNotifier:
    """R-02: observable notification boundary without external messages."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def notify(self, state: str, reason: str) -> None:
        self.calls.append((state, reason))
        if self.fail:
            raise RuntimeError("notification fault")


@pytest.mark.parametrize("state", list(SystemState))
@pytest.mark.parametrize("intent", ["ENTRY", "ADD", "REDUCE", "EXIT", "UNKNOWN"])
@pytest.mark.parametrize("source", ["SIGNAL", "SYSTEM", "MANUAL", "UNKNOWN"])
def test_CRO_01_R_09_state_gate(state: SystemState, intent: str, source: str) -> None:
    valid = intent != "UNKNOWN" and source != "UNKNOWN"
    expected = valid and (
        state == SystemState.RUNNING
        or (
            intent in {"REDUCE", "EXIT"}
            and (state == SystemState.REDUCE_ONLY or source == "MANUAL")
        )
    )
    assert state_allows(state, intent, source) == expected


@pytest.mark.parametrize(
    ("equity", "hwm", "start", "expected"),
    [
        ("100", "100", "100", SystemState.RUNNING),
        ("100.01", "100", "100", SystemState.RUNNING),
        ("92.01", "100", "92.01", SystemState.RUNNING),
        ("92", "100", "92", SystemState.REDUCE_ONLY),
        ("88.01", "100", "88.01", SystemState.REDUCE_ONLY),
        ("88", "100", "88", SystemState.HALTED),
        ("98.01", "100", "100", SystemState.RUNNING),
        ("98", "100", "100", SystemState.REDUCE_ONLY),
        ("0", "100", "100", SystemState.HALTED),
        ("100", "0", "100", SystemState.HALTED),
        ("100", "100", "0", SystemState.HALTED),
    ],
)
def test_CRO_09_CRO_10_exact_boundaries(
    equity: str, hwm: str, start: str, expected: SystemState
) -> None:
    assert financial_state(Decimal(equity), Decimal(hwm), Decimal(start), Settings()) == expected


def test_CRO_01_R_02_latch_restart_reset(engine: Engine, clock: FrozenClock) -> None:
    notifier = RecordingNotifier()
    store = SystemStateStore(engine, clock, notifier)
    assert store.current() == SystemState.RUNNING
    assert store.escalate(SystemState.REDUCE_ONLY, "drawdown") == SystemState.REDUCE_ONLY
    assert store.escalate(SystemState.RUNNING, "recovered") == SystemState.REDUCE_ONLY
    assert store.escalate(SystemState.HALTED, "stale data") == SystemState.HALTED
    restarted = SystemStateStore(engine, clock, notifier)
    assert restarted.current() == SystemState.HALTED
    assert restarted.escalate(SystemState.RUNNING, "recovered") == SystemState.HALTED
    assert restarted.operator_reset("local-operator", "verified fresh state") == SystemState.RUNNING
    with transaction(engine) as session:
        events = session.scalars(select(SystemEvent).order_by(SystemEvent.seq)).all()
        assert [event.event_type for event in events] == ["ESCALATE", "ESCALATE", "OPERATOR_RESET"]
        assert events[-1].operator_id == "local-operator"
    assert len(notifier.calls) == 1
    require_integrity(restarted)


@pytest.mark.parametrize(("operator", "reason"), [("", "why"), ("who", " ")])
def test_CRO_01_reset_needs_attribution(
    engine: Engine, clock: FrozenClock, operator: str, reason: str
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with pytest.raises(StateTransitionError):
        store.operator_reset(operator, reason)


def test_R_02_notifications_after_durable_halt(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(fail=True))
    with pytest.raises(StateTransitionError):
        store.halt_for_error(RuntimeError("provider"))
    assert store.current() == SystemState.HALTED
    assert SystemStateStore(engine, clock, RecordingNotifier()).current() == SystemState.HALTED


def test_CRO_09_CRO_10_apply_tiers(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    assert (
        store.apply_financial_limits(Decimal(98), Decimal(100), Decimal(100), Settings())
        == SystemState.REDUCE_ONLY
    )
    with pytest.raises(DataIntegrityError):
        store.apply_financial_limits(Decimal("NaN"), Decimal(100), Decimal(100), Settings())
    assert store.current() == SystemState.HALTED


def test_R_02_missing_control_halts(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with transaction(engine) as session:
        session.execute(delete(SystemControl))
    with pytest.raises(StateTransitionError):
        store.current()
    assert store.current() == SystemState.HALTED


def test_R_02_database_fault_latches(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.core.system_state as state_module

    store = SystemStateStore(engine, clock, RecordingNotifier())

    def broken_transaction(database: Engine) -> None:
        raise DatabaseError("injected storage failure")

    monkeypatch.setattr(state_module, "transaction", broken_transaction)
    with pytest.raises(DatabaseError):
        store.current()
    assert store.current() == SystemState.HALTED


def test_R_02_clock_is_injected(engine: Engine) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    store = SystemStateStore(engine, clock, RecordingNotifier())
    store.halt_for_error(RuntimeError("unknown fault"))
    with transaction(engine) as session:
        event = session.scalar(select(SystemEvent))
        assert event is not None
        assert event.created_at == clock.now()


def test_CRO_01_invalid_transition_arguments(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify=False)
    with pytest.raises(StateTransitionError):
        store.escalate(cast(SystemState, "BAD"), "reason")
    with pytest.raises(StateTransitionError):
        store.escalate(SystemState.HALTED, " ")
    with pytest.raises(StateTransitionError):
        store.operator_reset("operator", "reason", cast(SystemState, "BAD"))
    assert (
        store.operator_reset("operator", "remain halted", SystemState.HALTED) == SystemState.HALTED
    )


def test_R_02_startup_failure_notifies(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify=False)

    def broken_verify() -> None:
        raise LedgerIntegrityError("injected chain corruption")

    monkeypatch.setattr(store.ledger, "verify_chain", broken_verify)
    with pytest.raises(LedgerIntegrityError):
        store.startup()
    assert store.current() == SystemState.HALTED
    with pytest.raises(LedgerIntegrityError):
        store.operator_reset("operator", "cannot clear corrupt ledger")
    with pytest.raises(LedgerIntegrityError):
        require_integrity(store)


@pytest.mark.parametrize("action", ["current", "escalate", "reset"])
def test_R_02_unverifiable_control_branches(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify=False)
    with transaction(engine) as session:
        session.execute(delete(SystemControl))
    monkeypatch.setattr(store.ledger, "verify_chain", lambda: None)
    with pytest.raises(StateTransitionError):
        if action == "current":
            store.current()
        elif action == "escalate":
            store.escalate(SystemState.HALTED, "fault")
        else:
            store.operator_reset("operator", "reason")
    assert store.current() == SystemState.HALTED


@pytest.mark.parametrize("action", ["current", "escalate"])
def test_R_02_invalid_control_branches(engine: Engine, clock: FrozenClock, action: str) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify=False)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
        connection.execute(update(SystemControl).values(state="INVALID"))
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=OFF")
    with pytest.raises(StateTransitionError):
        if action == "current":
            store.current()
        else:
            store.escalate(SystemState.HALTED, "fault")


def test_R_02_emergency_latch_survives_successful_read(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify=False)

    def broken_verify() -> None:
        raise LedgerIntegrityError("fault")

    monkeypatch.setattr(store.ledger, "verify_chain", broken_verify)
    with pytest.raises(LedgerIntegrityError):
        store.startup()
    assert store.escalate(SystemState.RUNNING, "healthy storage now") == SystemState.HALTED


def test_CRO_09_R_04_low_precision_cannot_mask_boundaries() -> None:
    config = Settings()
    with localcontext() as context:
        context.prec = 2
        assert (
            financial_state(Decimal("8801"), Decimal("10000"), Decimal("8801"), config)
            == SystemState.REDUCE_ONLY
        )
        assert (
            financial_state(Decimal("9201"), Decimal("10000"), Decimal("9201"), config)
            == SystemState.RUNNING
        )


@pytest.mark.parametrize("bad", [100, "100", float("100"), True, None, Decimal("NaN")])
def test_R_02_R_04_financial_input_fault_halts(
    engine: Engine, clock: FrozenClock, bad: Any
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with pytest.raises(DataIntegrityError):
        store.apply_financial_limits(bad, Decimal("100"), Decimal("100"), Settings())
    assert store.current() == SystemState.HALTED


def test_R_02_unvalidated_financial_config_halts(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with pytest.raises(DataIntegrityError):
        store.apply_financial_limits(
            Decimal("100"), Decimal("100"), Decimal("100"), cast(Settings, None)
        )
    assert store.current() == SystemState.HALTED


def test_R_02_unexpected_financial_fault_is_typed_and_halts(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.core.system_state as state_module

    def broken(*args: object) -> SystemState:
        raise RuntimeError("unexpected evaluation fault")

    store = SystemStateStore(engine, clock, RecordingNotifier())
    monkeypatch.setattr(state_module, "financial_state", broken)
    with pytest.raises(DataIntegrityError):
        store.apply_financial_limits(Decimal("100"), Decimal("100"), Decimal("100"), Settings())
    assert store.current() == SystemState.HALTED


@pytest.mark.parametrize("bad", [None, 42, [], True])
def test_R_02_state_admin_arguments_raise_typed_errors(
    engine: Engine, clock: FrozenClock, bad: Any
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with pytest.raises(StateTransitionError):
        store.escalate(SystemState.HALTED, bad)
    with pytest.raises(StateTransitionError):
        store.operator_reset(bad, "reason")
    with pytest.raises(StateTransitionError):
        store.operator_reset("operator", bad)
    assert not state_allows(cast(SystemState, bad), "ENTRY", "SIGNAL")
    assert not state_allows(SystemState.RUNNING, bad, "SIGNAL")
    assert not state_allows(SystemState.RUNNING, "ENTRY", bad)


@pytest.mark.parametrize("action", ["current", "escalate", "reset"])
@pytest.mark.parametrize("field", ["state", "version"])
def test_R_02_mutable_projection_cannot_clear_immutable_halt(
    engine: Engine, clock: FrozenClock, action: str, field: str
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    store.escalate(SystemState.HALTED, "confirmed fault")
    values: dict[str, str | int] = {"state": "RUNNING"} if field == "state" else {"version": 0}
    with engine.begin() as connection:
        connection.execute(update(SystemControl).values(**values))
    with pytest.raises(LedgerIntegrityError):
        if action == "current":
            store.current()
        elif action == "escalate":
            store.escalate(SystemState.REDUCE_ONLY, "must not overwrite evidence")
        else:
            store.operator_reset("operator", "unverified recovery")
    assert store.current() == SystemState.HALTED
```

### backend/tests/test_market_calendar.py

Scope: Stage A. SHA-256: cbad00b260562f384c319ef008a168a1dd8993e04320a00b01d0656d6cf87a30.

```python
"""R-02/R-03/R-05, DAT-01/DAT-03 and CMP-03/CMP-05 calendar safety."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import cast

import pandas as pd
import pytest

from backend.core.errors import CalendarError
from backend.data.market_calendar import MarketCalendar


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2024, 1, 2), end=date(2026, 12, 31))


@pytest.mark.parametrize(
    "day,open_hour,close_hour",
    [
        (date(2024, 3, 8), 14, 21),
        (date(2024, 3, 11), 13, 20),
        (date(2024, 11, 1), 13, 20),
        (date(2024, 11, 4), 14, 21),
        (date(2025, 3, 7), 14, 21),
        (date(2025, 3, 10), 13, 20),
        (date(2025, 10, 31), 13, 20),
        (date(2025, 11, 3), 14, 21),
        (date(2026, 3, 6), 14, 21),
        (date(2026, 3, 9), 13, 20),
        (date(2026, 10, 30), 13, 20),
        (date(2026, 11, 2), 14, 21),
    ],
)
def test_DAT_01_R_05_dst_changes_exact_utc_regular_hours(
    calendar: MarketCalendar, day: date, open_hour: int, close_hour: int
) -> None:
    """DAT-01/R-05: real spring/fall dates retain 09:30-16:00 New York hours."""
    opened = datetime(day.year, day.month, day.day, open_hour, 30, tzinfo=UTC)
    closed = datetime(day.year, day.month, day.day, close_hour, tzinfo=UTC)
    assert calendar.session_open(day) == opened
    assert calendar.session_close(day) == closed
    assert not calendar.is_open(opened - timedelta(microseconds=1))
    assert calendar.is_open(opened)
    assert calendar.is_open(closed - timedelta(microseconds=1))
    assert not calendar.is_open(closed)


@pytest.mark.parametrize(
    "holiday",
    [
        date(2024, 7, 4),
        date(2024, 11, 28),
        date(2024, 12, 25),
        date(2025, 1, 9),
        date(2025, 7, 4),
        date(2025, 11, 27),
        date(2025, 12, 25),
        date(2026, 7, 3),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2026, 10, 3),
        date(2026, 10, 4),
    ],
)
def test_DAT_01_holidays_weekends_and_2025_national_mourning_are_closed(
    calendar: MarketCalendar, holiday: date
) -> None:
    """DAT-01: closed days cannot produce a trading-session close."""
    assert not calendar.is_open(datetime.combine(holiday, datetime.min.time(), UTC))
    assert not calendar.is_open(datetime(holiday.year, holiday.month, holiday.day, 16, tzinfo=UTC))
    with pytest.raises(CalendarError, match="not an XNYS"):
        calendar.session_close(holiday)


@pytest.mark.parametrize(
    "day,hour",
    [
        (date(2024, 7, 3), 17),
        (date(2024, 11, 29), 18),
        (date(2024, 12, 24), 18),
        (date(2025, 7, 3), 17),
        (date(2025, 11, 28), 18),
        (date(2025, 12, 24), 18),
        (date(2026, 11, 27), 18),
        (date(2026, 12, 24), 18),
    ],
)
def test_DAT_01_DAT_03_early_close_is_completed_at_exact_close(
    calendar: MarketCalendar, day: date, hour: int
) -> None:
    """DAT-01/DAT-03: daily completion follows actual early-close time."""
    closed = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
    assert calendar.session_close(day) == closed
    assert calendar.is_open(closed - timedelta(microseconds=1))
    assert not calendar.is_open(closed)
    assert calendar.last_completed_session(closed) == day
    assert calendar.last_completed_session(closed - timedelta(microseconds=1)) < day


def test_DAT_01_2026_july_second_has_normal_close(calendar: MarketCalendar) -> None:
    """DAT-01: an observed Friday holiday does not invent a Thursday early close."""
    assert calendar.session_close(date(2026, 7, 2)) == utc("2026-07-02T20:00:00")
    assert calendar.is_open(utc("2026-07-02T19:59:59.999999"))


@pytest.mark.parametrize(
    "now,expected",
    [
        ("2026-10-02T13:29:59.999999", date(2026, 10, 1)),
        ("2026-10-02T13:30:00", date(2026, 10, 1)),
        ("2026-10-02T19:59:59.999999", date(2026, 10, 1)),
        ("2026-10-02T20:00:00", date(2026, 10, 2)),
        ("2026-10-02T23:00:00", date(2026, 10, 2)),
        ("2026-10-03T16:00:00", date(2026, 10, 2)),
        ("2026-10-04T16:00:00", date(2026, 10, 2)),
        ("2026-11-26T16:00:00", date(2026, 11, 25)),
        ("2026-11-27T17:59:59.999999", date(2026, 11, 25)),
        ("2026-11-27T18:00:00", date(2026, 11, 27)),
    ],
)
def test_DAT_03_last_completed_session_excludes_in_progress_daily_bar(
    calendar: MarketCalendar, now: str, expected: date
) -> None:
    """DAT-03: pre-open, nights, weekends and holidays use the last completed bar."""
    assert calendar.last_completed_session(utc(now)) == expected


@pytest.mark.parametrize(
    "trade,settlement",
    [
        (date(2024, 7, 3), date(2024, 7, 5)),
        (date(2025, 7, 3), date(2025, 7, 7)),
        (date(2026, 7, 2), date(2026, 7, 6)),
        (date(2024, 11, 27), date(2024, 11, 29)),
        (date(2025, 11, 26), date(2025, 11, 28)),
        (date(2026, 11, 25), date(2026, 11, 27)),
        (date(2024, 11, 29), date(2024, 12, 2)),
        (date(2025, 11, 28), date(2025, 12, 1)),
        (date(2026, 11, 27), date(2026, 11, 30)),
        (date(2024, 12, 24), date(2024, 12, 26)),
        (date(2025, 12, 24), date(2025, 12, 26)),
        (date(2026, 12, 24), date(2026, 12, 28)),
        (date(2025, 1, 8), date(2025, 1, 10)),
    ],
)
def test_CMP_03_T_plus_one_uses_real_exchange_sessions(
    calendar: MarketCalendar, trade: date, settlement: date
) -> None:
    """CMP-03: an early close is a session; holiday/weekend dates never settle."""
    assert calendar.add_sessions(trade, 0) == trade
    assert calendar.add_sessions(trade, 1) == settlement


@pytest.mark.parametrize("day", [date(2026, 10, 5), date(2026, 10, 3), date(2026, 10, 4)])
def test_CMP_05_previous_sessions_excludes_anchor_and_is_chronological(
    calendar: MarketCalendar, day: date
) -> None:
    """CMP-05: legacy count windows consistently exclude the anchor day."""
    assert calendar.previous_sessions(day, 5) == (
        date(2026, 9, 28),
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 2),
    )
    assert calendar.previous_sessions(day, 0) == ()


def test_R_02_calendar_limits_reject_stale_fallback(calendar: MarketCalendar) -> None:
    """R-02: out-of-range instants cannot silently reuse an arbitrarily old close."""
    assert calendar.first_session == date(2024, 1, 2)
    assert calendar.last_session == date(2026, 12, 31)
    for instant in (utc("2024-01-01T16:00:00"), utc("2027-01-01T16:00:00")):
        with pytest.raises(CalendarError, match="outside"):
            calendar.is_open(instant)
        with pytest.raises(CalendarError, match="outside"):
            calendar.last_completed_session(instant)
    with pytest.raises(CalendarError, match="No completed"):
        calendar.last_completed_session(calendar.session_open(calendar.first_session))
    with pytest.raises(CalendarError, match="exceeds"):
        calendar.add_sessions(calendar.last_session, 1)
    with pytest.raises(CalendarError, match="Insufficient"):
        calendar.previous_sessions(calendar.first_session, 1)


@pytest.mark.parametrize("count", [-1, True, "1", None])
def test_R_02_CMP_03_invalid_session_counts_fail_closed(
    calendar: MarketCalendar, count: object
) -> None:
    """R-02/CMP-03: negative, boolean, text and missing offsets are invalid."""
    with pytest.raises(CalendarError, match="nonnegative"):
        calendar.add_sessions(date(2026, 10, 2), cast(int, count))
    with pytest.raises(CalendarError, match="nonnegative"):
        calendar.previous_sessions(date(2026, 10, 2), cast(int, count))


@pytest.mark.parametrize("day", [None, "2026-10-02", utc("2026-10-02T00:00:00")])
def test_R_02_session_label_cannot_be_missing_text_or_datetime(
    calendar: MarketCalendar, day: object
) -> None:
    """R-02: conversion of ambiguous labels is prohibited."""
    with pytest.raises(CalendarError, match="must be dates"):
        calendar.add_sessions(cast(date, day), 1)


def test_R_02_CMP_03_trade_date_must_be_actual_session(
    calendar: MarketCalendar,
) -> None:
    """R-02/CMP-03: settlement cannot guess a trade date on a holiday."""
    with pytest.raises(CalendarError, match="not an XNYS"):
        calendar.add_sessions(date(2026, 7, 3), 1)


@pytest.mark.parametrize(
    "instant",
    [None, "2026-10-02T16:00:00", utc("2026-10-02T16:00:00").replace(tzinfo=None)],
)
def test_R_02_R_05_invalid_instants_raise_typed_calendar_error(
    calendar: MarketCalendar, instant: object
) -> None:
    """R-02/R-05: naive and missing instants never yield open/completed state."""
    with pytest.raises(CalendarError):
        calendar.is_open(cast(datetime, instant))
    with pytest.raises(CalendarError):
        calendar.last_completed_session(cast(datetime, instant))


@pytest.mark.parametrize("name", ["UNKNOWN", "XNAS", "NYSE", ""])
def test_R_02_unknown_or_unapproved_exchange_fails_typed(name: str) -> None:
    """R-02: only an exact XNYS exchange name is accepted."""
    with pytest.raises(CalendarError, match="Only the XNYS"):
        MarketCalendar(name=name)


@pytest.mark.parametrize(
    "failure", [RuntimeError("offline"), ValueError("corrupt"), KeyError("missing")]
)
def test_R_02_injected_calendar_exception_is_typed(failure: Exception) -> None:
    """R-02: unexpected provider failures are never interpreted as valid state."""

    def broken(name: str, start: date, end: date) -> object:
        del name, start, end
        raise failure

    with pytest.raises(CalendarError, match="construct") as result:
        MarketCalendar(calendar_factory=broken)
    assert result.value.__cause__ is failure


class BrokenSchedule:
    """R-02: controllable malformed provider for SDK-boundary fault injection."""

    def __init__(self, fault: str) -> None:
        self.name = "XNAS" if fault == "exchange" else "XNYS"
        self.fault = fault
        if fault == "empty":
            self.sessions = pd.DatetimeIndex([])
        elif fault == "duplicate":
            self.sessions = pd.DatetimeIndex(["2026-10-01", "2026-10-01"])
        elif fault == "reversed":
            self.sessions = pd.DatetimeIndex(["2026-10-02", "2026-10-01"])
        elif fault == "label_timezone":
            self.sessions = pd.DatetimeIndex(["2026-10-01"], tz="UTC")
        elif fault == "label_time":
            self.sessions = pd.DatetimeIndex(["2026-10-01T12:00:00"])
        elif fault == "label_missing":
            self.sessions = pd.DatetimeIndex([pd.NaT])
        elif fault == "escaped":
            self.sessions = pd.DatetimeIndex(["2023-12-29"])
        else:
            self.sessions = pd.DatetimeIndex(["2026-10-01", "2026-10-02"])

    def session_open(self, session: pd.Timestamp) -> pd.Timestamp:
        if self.fault == "missing_instant":
            return cast(pd.Timestamp, pd.NaT)
        if self.fault == "naive_instant":
            return session + pd.Timedelta(hours=13, minutes=30)
        if self.fault == "wrong_day":
            return (session - pd.Timedelta(days=1)).tz_localize("UTC")
        if self.fault == "overlap" and session.day == 2:
            return pd.Timestamp("2026-10-01T19:00:00", tz="UTC")
        return session.tz_localize("UTC") + pd.Timedelta(hours=13, minutes=30)

    def session_close(self, session: pd.Timestamp) -> pd.Timestamp:
        if self.fault == "reversed_interval":
            return session.tz_localize("UTC") + pd.Timedelta(hours=13)
        return session.tz_localize("UTC") + pd.Timedelta(hours=20)


@pytest.mark.parametrize(
    "fault",
    [
        "exchange",
        "empty",
        "duplicate",
        "reversed",
        "label_timezone",
        "label_time",
        "label_missing",
        "escaped",
        "missing_instant",
        "naive_instant",
        "wrong_day",
        "reversed_interval",
        "overlap",
    ],
)
def test_R_02_R_05_malformed_calendar_schedule_fails_closed(fault: str) -> None:
    """R-02/R-05: unknown, missing, ambiguous or nonmonotonic schedules fail."""

    def broken(name: str, start: date, end: date) -> object:
        del name, start, end
        return BrokenSchedule(fault)

    with pytest.raises(CalendarError):
        MarketCalendar(start=date(2024, 1, 2), end=date(2026, 12, 31), calendar_factory=broken)


@pytest.mark.parametrize(
    "start,end",
    [(date(2026, 10, 2), date(2026, 10, 2)), (date(2026, 10, 2), date(2026, 10, 1))],
)
def test_R_02_invalid_calendar_range_is_typed(start: date, end: date) -> None:
    """R-02: an empty or reversed configured horizon cannot pass startup."""
    with pytest.raises(CalendarError, match="start must precede"):
        MarketCalendar(start=start, end=end)


def test_R_03_R_05_calendar_queries_are_deterministic(calendar: MarketCalendar) -> None:
    """R-03/R-05: the same injected instant has the same regular-session result."""
    instant = utc("2026-10-02T16:00:00")
    assert calendar.is_open(instant) == calendar.is_open(instant)
    assert calendar.last_completed_session(instant) == date(2026, 10, 1)
    assert calendar.last_completed_session(instant) == calendar.last_completed_session(instant)
```

### backend/tests/test_no_order_exec.py

Scope: Stage A. SHA-256: 85a9519dec13aa991154edad08c8c6867adafdf62839c2a148e65c9811b04915.

```python
"""R-08/R-10/GD-07: source safety, positive controls, and reflection bypasses."""

import ast
import sys
from pathlib import Path

import pytest

from backend.core.errors import ConfigurationError
from backend.core.execution_policy import BANNED_EXECUTION_METHODS, BANNED_ORDER_REQUESTS
from backend.core.source_guard import main as source_guard_main
from backend.core.source_guard import require_safe_sources, scan_file, scan_project


def _source(tmp_path: Path, source: str, name: str = "sample.py") -> Path:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source + "\n", encoding="utf-8")
    return target


def test_GD_07_every_authored_repository_file_is_read_only() -> None:
    root = Path(__file__).resolve().parents[2]
    violations = scan_project(root)
    assert not violations, "\n".join(map(str, violations))


@pytest.mark.parametrize("name", sorted(BANNED_ORDER_REQUESTS))
def test_GD_07_order_request_imports_and_aliases_are_rejected(tmp_path: Path, name: str) -> None:
    path = _source(tmp_path, f"from alpaca.trading.requests import {name} as Request\n")
    assert scan_file(path)


@pytest.mark.parametrize("name", sorted(BANNED_EXECUTION_METHODS))
def test_GD_07_execution_attributes_are_rejected_even_without_a_call(
    tmp_path: Path, name: str
) -> None:
    path = _source(tmp_path, f"operation = client.{name}\n")
    assert scan_file(path)


@pytest.mark.parametrize(
    "source",
    [
        "eval('untrusted')",
        "exec('untrusted')",
        "compile('untrusted', 'source', 'exec')",
        "__import__('untrusted')",
        "import builtins as b\nb.eval('untrusted')",
        "__builtins__.eval('untrusted')",
        "from builtins import eval as run\nrun('untrusted')",
        "run = eval\nnext_run = run\nnext_run('untrusted')",
        "import importlib\nimportlib.import_module('untrusted')",
        "import importlib as modules\nmodules.import_module('untrusted')",
        "from importlib import import_module as load\nload('untrusted')",
        "import importlib\nload = importlib.import_module\nload('untrusted')",
        "getattr(client, name)",
        "setattr(client, name, value)",
        "getattr(client, 'submit_order')",
        "setattr(client, 'submit_order', value)",
        "pick = getattr\npick(client, name)",
        "from builtins import getattr as getAttribute\ngetAttribute(client, name)",
        "from builtins import getattr as getAttribute\ngetAttribute(client, 'submit_order')",
        "import builtins as b\npick = b.getattr\npick(client, name)",
        "method = client.__dict__['submit_order']\nmethod(request)",
        "client.__dict__['submit_order'](request)",
        "name = 'submit_order'\nclient.__dict__[name](request)",
        "client.__dict__[name](request)",
        "__builtins__['eval']('untrusted')",
        "__builtins__['getattr'](client, name)",
        "client.__getattribute__('submit_order')(request)",
        "client.__getattribute__(name)(request)",
        "getattr(client, '__getattribute__')(name)(request)",
        "from alpaca.trading import requests as r\nr.MarketOrderRequest()",
        "import alpaca.trading.requests.OrderRequest as Request",
        "from alpaca.trading.requests import *",
        "client.create_internal_transfer(request)",
        "client.createTransfer(request)",
        "from operator import attrgetter\nattrgetter('submit_order')(client)(request)",
        "import operator\noperator.methodcaller('submit_order', request)(client)",
        "from operator import attrgetter as pick\npick('client.submit_order')(context)(request)",
        "from operator import attrgetter\npick = attrgetter\npick(name)(client)(request)",
        "from operator import attrgetter\nattrgetter('safe', 'submit_order')(client)",
        "from operator import methodcaller as call\ncall(name, request)(client)",
        "client.__dict__.get('submit_order')(request)",
        "vars(client).get('submit_order')(request)",
        "methods = client.__dict__\nmethods.get('submit_order')(request)",
        "import pandas as pd\npd.eval('untrusted')",
        "object.eval('untrusted')",
        "object.exec('untrusted')",
        "object.__import__('untrusted')",
        "object.import_module('untrusted')",
        "object.compile('untrusted')",
        "compiler = object.compile\ncompiler('untrusted')",
        "def execute(re):\n    re.compile('untrusted')",
        "import re\ndef execute(re):\n    re.compile('untrusted')",
        "import re as regex\ndef execute(regex):\n    regex.compile('untrusted')",
        "re.compile('untrusted')",
    ],
)
def test_GD_07_dynamic_code_reflection_and_import_bypasses_fail_closed(
    tmp_path: Path, source: str
) -> None:
    findings = scan_file(_source(tmp_path, source))
    assert findings, source
    assert all(item.rule_id == "GD-07" and item.line >= 1 and item.column >= 1 for item in findings)


@pytest.mark.parametrize(
    "source",
    [
        "client.post('/v2/orders', json=payload)",
        "client.delete('https://api.alpaca.markets/v2/orders/id')",
        "client.patch('/v2/orders/id', json=payload)",
        "client.request('POST', '/v1/accounts/account/transfers')",
        "client.request(method='DELETE', url='/v2/orders/id')",
        "verb = 'PATCH'\nurl = '/v2/orders/id'\nclient.request(method=verb, url=url)",
        "send = client.post\nurl = '/v2/orders'\nsend(url, json=payload)",
        "client.request(**{'method': 'POST', 'url': '/v2/orders'})",
        "client.post('/v2/' + 'orders')",
        "client.patch(f'/v2/orders/{identifier}')",
        "client.post('/v2/transfers', json=payload)",
        "client._post('/v2/orders', payload)",
        "client.request(method='POST', url='/v2/orders'.format())",
        "client.post('/v2/{endpoint}'.format(endpoint='orders'))",
        "endpoint = '/v2/orders'\nclient.request(method='POST', url=str(endpoint))",
        "client.post(normalize('/v2/orders'))",
        "from operator import attrgetter\nattrgetter('post')(client)('/v2/orders')",
        "from operator import attrgetter\npost = attrgetter('post')(client)\npost('/v2/orders')",
        "from operator import methodcaller\nmethodcaller('post', '/v2/orders')(client)",
        "from operator import attrgetter\nget, post = attrgetter('get', 'post')(client)\npost('/v2/orders')",
        "client.post('/v2/%s' % 'orders')",
        "client.post(''.join(['/v2/', 'orders']))",
        "client.post(b'/v2/orders'.decode())",
        "client.post('/sredro/2v/'[::-1])",
    ],
)
def test_GD_07_order_and_transfer_mutating_http_endpoints_are_rejected(
    tmp_path: Path, source: str
) -> None:
    findings = scan_file(_source(tmp_path, source))
    assert any("mutating HTTP" in item.message for item in findings), source


@pytest.mark.parametrize(
    "source",
    [
        "request.method = 'POST'\nrequest.url = '/v2/orders'\nsession.send(request)",
        "request.method = 'PATCH'\nrequest.url = b'/v2/orders'.decode()\nsession.send(request)",
        "request.method = 'DELETE'\nrequest.url = '/sredro/2v/'[::-1]\nsession.send(request)",
        "request.method = b'POST'.decode()\nrequest.url = '/v2/orders'\nsession.send(request)",
        "request.method = 'PO' + 'ST'\nrequest.url = '/v2/orders'\nsession.send(request)",
        "request.method = 'TSOP'[::-1]\nrequest.url = '/v2/orders'\nsession.send(request)",
    ],
)
def test_GD_07_separately_constructed_mutating_requests_fail_closed(
    tmp_path: Path, source: str
) -> None:
    assert scan_file(_source(tmp_path, source))


@pytest.mark.parametrize(
    "source",
    [
        "client.get_account()\nclient.get_all_positions()\nclient.get_orders(request)",
        "from alpaca.trading.requests import GetOrdersRequest\nquery = GetOrdersRequest()",
        "getattr(response, 'status_code', None)",
        "setattr(value, 'label', 'safe')",
        "import builtins as b\npick = b.getattr\npick(response, 'status_code', None)",
        "from builtins import getattr as getAttribute\ngetAttribute(response, 'cash')",
        "import re\npattern = re.compile('^[A-Z]+$')",
        "from re import compile as regex_compile\npattern = regex_compile('^[A-Z]+$')",
        "import re as regex\ncompile_pattern = regex.compile\ncompile_pattern('[A-Z]')",
        "import re as regex\nregex.compile('[A-Z]')",
        "client.get('/v2/orders')",
        "client.request('GET', '/v1/accounts/account/transfers')",
        "object.__setattr__(self, 'current', value)",
        "value.__getattribute__('cash')",
        "from operator import attrgetter\nattrgetter('cash')(account)",
        "from operator import methodcaller\nmethodcaller('get_account')(client)",
        "from operator import attrgetter\nattrgetter('get')(client)('/v2/orders')",
        "data = {'submit_order': 'untrusted text only'}",
        "sql = 'SELECT * FROM orders'",
    ],
)
def test_GD_07_safe_literal_reflection_regex_and_read_only_clients_are_allowed(
    tmp_path: Path, source: str
) -> None:
    findings = scan_file(_source(tmp_path, source))
    assert not findings, "\n".join(map(str, findings))


def test_GD_07_positive_control_scans_tests_scripts_and_other_authored_paths(
    tmp_path: Path,
) -> None:
    paths = (
        _source(tmp_path, "client.submit_order(request)", "backend/tests/planted.py"),
        _source(tmp_path, "client.close_position('AAPL')", "scripts/planted.py"),
        _source(tmp_path, "client.create_transfer(request)", "misc/planted.py"),
        _source(tmp_path, "client.cancel_orders()", "root_script.py"),
    )
    findings = scan_project(tmp_path)
    assert {item.path for item in findings} == set(paths)
    with pytest.raises(ConfigurationError, match="GD-07"):
        require_safe_sources(tmp_path)


def test_GD_07_only_canonical_constants_module_is_exempt(tmp_path: Path) -> None:
    canonical = _source(
        tmp_path, "client.submit_order(request)", "backend/core/execution_policy.py"
    )
    lookalike = _source(tmp_path, "client.submit_order(request)", "scripts/execution_policy.py")
    findings = scan_project(tmp_path)
    assert {item.path for item in findings} == {lookalike}
    assert all(item.path != canonical for item in findings)


def test_GD_07_generated_dependencies_are_explicitly_outside_authored_scan(tmp_path: Path) -> None:
    _source(tmp_path, "client.submit_order(request)", ".venv/Lib/site-packages/sdk.py")
    _source(tmp_path, "client.submit_order(request)", "__pycache__/generated.py")
    _source(tmp_path, "client.submit_order(request)", "build/generated.py")
    require_safe_sources(tmp_path)


@pytest.mark.parametrize("source", ["if (", "\x00", "not valid python source!"])
def test_GD_07_unparseable_source_fails_closed(tmp_path: Path, source: str) -> None:
    findings = scan_file(_source(tmp_path, source))
    assert len(findings) == 1
    assert "cannot be verified" in findings[0].message


def test_GD_07_unreadable_or_missing_source_fails_closed(tmp_path: Path) -> None:
    assert scan_file(tmp_path / "missing.py")
    assert scan_project(tmp_path / "missing")
    binary = tmp_path / "invalid_encoding.py"
    binary.write_bytes(bytes([0xFF, 0xFE, 0xFD]))
    assert scan_file(binary)


def test_GD_07_symbolic_links_fail_closed_without_following_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path, "client.get_account()")
    original = Path.is_symlink

    def observed_link(path: Path) -> bool:
        return path == source or original(path)

    monkeypatch.setattr(Path, "is_symlink", observed_link)
    assert "symbolic" in scan_file(source)[0].message
    assert "symbolic" in scan_project(tmp_path)[0].message


def test_GD_07_paths_that_resolve_outside_project_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path, "client.get_account()")
    original = Path.resolve
    outside = tmp_path.parent / "escaped.py"

    def observed_escape(path: Path, strict: bool = False) -> Path:
        return outside if path == source else original(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", observed_escape)
    findings = scan_project(tmp_path)
    assert len(findings) == 1
    assert "escapes" in findings[0].message


def test_GD_07_cli_reports_pass_and_nonzero_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["source_guard", str(tmp_path)])
    assert source_guard_main() == 0
    assert "passed" in capsys.readouterr().out
    _source(tmp_path, "client.submit_order(request)")
    assert source_guard_main() == 1
    assert "GD-07" in capsys.readouterr().err


def test_GD_07_unexpected_parser_or_directory_error_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path, "client.get_account()")

    def parser_failure(_source: str, filename: str) -> ast.AST:
        raise RuntimeError("sensitive source must not appear in diagnostics")

    monkeypatch.setattr(ast, "parse", parser_failure)
    findings = scan_file(source)
    assert "RuntimeError" in findings[0].message
    assert "sensitive" not in findings[0].message

    def directory_failure(_path: Path) -> list[Path]:
        raise RuntimeError("sensitive path must not appear in diagnostics")

    monkeypatch.setattr(Path, "iterdir", directory_failure)
    findings = scan_project(tmp_path)
    assert "RuntimeError" in findings[0].message
    assert "sensitive" not in findings[0].message
    with pytest.raises(ConfigurationError):
        require_safe_sources(tmp_path)
```

### ../.github/workflows/ci.yml

Scope: Parent repository wiring. SHA-256: 978f9cf636050687194693b6ae35f363a365158032f63e835bc084580bd79f14.

```yaml
name: Stage A defensive core
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
      - name: Strict Stage A typing
        run: python -m backend.core.check_stage_a
      - name: Execution source guard
        run: python -m backend.core.source_guard .
      - name: Security checks
        run: python -m bandit -r backend/core backend/data/market_calendar.py -c pyproject.toml && python -m pip_audit -r requirements-lock.txt && python -m detect_secrets scan --all-files --exclude-files '(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]' > /tmp/vws-secrets.json && python -c "import json; from pathlib import Path; findings=json.loads(Path('/tmp/vws-secrets.json').read_text())['results']; print(findings); assert not findings"
      - name: Stage A tests, network blocked, state branch coverage 100%
        run: python -m pytest backend/tests/test_config_safety.py backend/tests/test_yaml_config.py backend/tests/test_money.py backend/tests/test_logging.py backend/tests/test_ledger.py backend/tests/test_research_ledger.py backend/tests/test_system_state.py backend/tests/test_market_calendar.py backend/tests/test_no_order_exec.py --cov=backend.core.system_state --cov-branch --cov-fail-under=100 --cov-report=term-missing
```

### ../.pre-commit-config.yaml

Scope: Parent repository wiring. SHA-256: 5c1dc6c05e3976dfb8fdcbccf8ecebdc171e605ac9a4a69c84ad62e96fb83422.

```yaml
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
      - id: stage-a-types
        name: Stage A strict types
        entry: python -m backend.core.check_stage_a
        language: system
        pass_filenames: false
        types: [python]
      - id: detect-secrets
        name: Secrets scan
        entry: detect-secrets-hook
        language: system
        exclude: (^|/)(backend/tests/|requirements-lock\.txt$|deliveries/)
```

### ../.gitignore

Scope: Parent repository wiring. SHA-256: 42411b3abf6b8a46f4faa2b060f1fd19d31cca57bb598c5a7b110f9501285637.

```text
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
secrets-report.json
```

### backend/risk/risk_cro.py

Scope: Preserved draft compatibility edit. SHA-256: 9089728132d5499c9c7a8e629fd410442b68488d6b409e32cb34a43b5ab1f94e.

```python
"""CRO-01..12/R-01..05/R-09: pure, exact and conservative risk decisions.

The caller persists state escalations and logs vetoes outside this pure gate.
Unknown sector metadata blocks; unconfigured known sectors use a 35% cap and
unconfigured themes a zero cap. Pending sells never reduce exposure before a
fill. Pending buys, including earlier batch approvals, reserve notional.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, state_allows
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import GICS_SECTORS, InstrumentRegistry
from backend.domain.models import (
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
    RuleResult,
    Severity,
    Side,
    TradeProposal,
    Verdict,
    snapshot_hash,
)

ZERO = Decimal("0")
DEFAULT_SECTOR_CAP = Decimal("0.35")


def _result(
    rule_id: str, passed: bool, observed: object, limit: object, message: str
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        passed=passed,
        severity=Severity.BLOCK,
        observed=str(observed),
        limit=str(limit),
        message=message,
    )


def _entry(proposal: TradeProposal) -> bool:
    return proposal.intent in {Intent.ENTRY, Intent.ADD}


class ChiefRiskOfficer:
    """CRO-01..12: frozen-policy evaluation; no network, randomness or logging."""

    def __init__(
        self,
        config: Settings,
        registry: InstrumentRegistry,
        calendar: MarketCalendar,
        *,
        blackout_windows: tuple[BlackoutWindow, ...] = (),
    ) -> None:
        self.config = config
        self.registry = registry
        self.calendar = calendar
        self.blackout_windows = registry.blackout_windows + tuple(blackout_windows)

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
        """CRO-01..12/R-02/R-03: record all rules; only state rejection short-circuits.

        R-09 reductions/exits evaluate state and held-quantity shape only. Missing
        market metadata, funding flags, price collars and account losses cannot
        trap a valid exit. Malformed rule inputs veto; an invalid identity/time
        that cannot support an auditable verdict raises a typed integrity error.
        """
        try:
            instant = ensure_utc(now)
            if not isinstance(proposal.proposal_id, UUID):
                raise DataIntegrityError("CRO-02: proposal identity must be a UUID")
            state_result = _result(
                "CRO-01",
                isinstance(state, SystemState)
                and state_allows(state, proposal.intent, proposal.source),
                state,
                "RUNNING, or permitted reduction/exit",
                "system operating state permits proposal",
            )
            if not state_result.passed:
                return self._verdict(proposal, snapshot, instant, (state_result,))
            shape = self._shape(proposal, snapshot, market, instant)
            if not _entry(proposal):
                return self._verdict(proposal, snapshot, instant, (state_result, shape))
            if market is None:
                raise DataIntegrityError("CRO-02: entry requires verified market context")
            limits = [self.config.__dict__[name] for name in self.config.DECIMAL_BOUNDS]
            limits.extend(self.config.sector_caps.values())
            limits.extend(self.config.theme_caps.values())
            with localcontext() as context:
                context.prec = max(
                    80,
                    len(str(proposal.qty)) + 40,
                    max(len(value.as_tuple().digits) for value in limits) + 40,
                )
                results = self._rules(proposal, snapshot, market, instant, deployable)
            return self._verdict(proposal, snapshot, instant, (state_result, shape, *results))
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
                    for number in range(1, 13)
                )
                return Verdict(
                    proposal_id=proposal.proposal_id,
                    decision=Decision.VETOED,
                    results=failures,
                    config_hash=self.config.config_hash,
                    snapshot_hash="0" * 64,
                    evaluated_at=instant,
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
    ) -> Verdict:
        decision = (
            Decision.APPROVED if all(result.passed for result in results) else Decision.VETOED
        )
        return Verdict(
            proposal_id=proposal.proposal_id,
            decision=decision,
            results=results,
            config_hash=self.config.config_hash,
            snapshot_hash=snapshot_hash(snapshot),
            evaluated_at=now,
        )

    def _shape(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
        now: datetime,
    ) -> RuleResult:
        """CRO-02/R-01/R-09: account-bound long shape; exits need only inventory."""
        common = (
            proposal.account_id == snapshot.account_id
            and proposal.created_at <= now
            and snapshot.as_of <= now
            and isinstance(proposal.qty, int)
            and not isinstance(proposal.qty, bool)
            and proposal.qty > 0
            and isinstance(proposal.limit_price, Decimal)
            and proposal.limit_price.is_finite()
            and proposal.limit_price > 0
        )
        if not _entry(proposal):
            held = snapshot.positions.get(proposal.symbol)
            reserved = sum(
                order.qty
                for order in snapshot.open_orders
                if order.symbol == proposal.symbol and order.side == Side.SELL
            )
            available = 0 if held is None else max(0, held.qty - reserved)
            valid = common and proposal.side == Side.SELL and proposal.qty <= available
            return _result(
                "CRO-02", valid, proposal.qty, available, "reduction fits held unreserved shares"
            )
        instrument = self.registry.get(proposal.symbol)
        valid = (
            common
            and proposal.side == Side.BUY
            and proposal.stop_price is not None
            and proposal.stop_price.is_finite()
            and ZERO < proposal.stop_price < proposal.limit_price
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
            "entry has a stop, positive equity, and verified instrument/market",
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
        stop = proposal.stop_price
        risk = (
            ZERO
            if stop is None
            else proposal.qty * (proposal.limit_price - stop)
            + notional * self.config.stop_slippage_buffer
        )
        position = snapshot.positions.get(proposal.symbol)
        if proposal.intent == Intent.ADD and position is not None and stop is not None:
            risk += position.qty * max(ZERO, position.last_price - stop)
        risk_result = _result(
            "CRO-04",
            stop is not None and risk <= self.config.max_risk_per_trade * equity,
            risk,
            self.config.max_risk_per_trade * equity,
            "stop loss plus slippage fits risk budget",
        )
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
        baseline = snapshot.high_water_mark if snapshot.high_water_mark > 0 else equity
        drawdown = ZERO if baseline <= 0 else max(ZERO, (baseline - equity) / baseline)
        drawdown_result = _result(
            "CRO-09",
            equity > 0 and max(ZERO, baseline - equity) < self.config.dd_reduce_only * baseline,
            drawdown,
            self.config.dd_reduce_only,
            "drawdown below reduce-only tier; halt tier escalated by caller",
        )
        day_start = snapshot.day_start_equity if snapshot.day_start_equity > 0 else equity
        daily_loss = ZERO if day_start <= 0 else (day_start - equity) / day_start
        daily = _result(
            "CRO-10",
            equity > 0 and day_start - equity < self.config.daily_loss_limit * day_start,
            daily_loss,
            self.config.daily_loss_limit,
            "daily loss below reduce-only tier",
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
            "scheduled blackout gate",
        )
        funding = _result(
            "CRO-12",
            deployable is not None and deployable.status == CapitalStatus.OK,
            "missing" if deployable is None else deployable.status,
            CapitalStatus.OK,
            "checking buffer and funding reading must be available",
        )
        return (
            name,
            risk_result,
            allocation,
            exposure,
            price,
            liquidity,
            drawdown_result,
            daily,
            blackout,
            funding,
        )

    def _allocation(self, exposures: dict[str, Decimal], equity: Decimal) -> RuleResult:
        """CRO-05: all holdings and pending buys participate in ETF look-through."""
        sectors: dict[str, Decimal] = {}
        themes: dict[str, Decimal] = {}
        known = True
        for symbol, value in exposures.items():
            instrument: Instrument = self.registry.get(symbol)
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
        """CRO-07/DAT-01: regular-hour age; otherwise age from last session close."""
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

    def max_allowed_qty(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext,
        now: datetime,
    ) -> int:
        """CRO-03..08/R-04: largest whole-share quantity satisfying all sizing caps.

        This is an advisory cap, not an approval. State, compliance, blackout and
        funding gates still apply to the final proposal. Binary search is valid
        because all six caps are monotone with respect to a positive buy qty.
        """
        if not _entry(proposal):
            return 0
        try:
            if proposal.limit_price <= 0:
                return 0
            with localcontext() as context:
                context.prec = 80
                upper = max(0, int(min(snapshot.cash, snapshot.equity) / proposal.limit_price))
            lower = 0
            while lower < upper:
                midpoint = (lower + upper + 1) // 2
                candidate = proposal.model_copy(update={"qty": midpoint})
                verdict = self.evaluate(candidate, snapshot, market, SystemState.RUNNING, now)
                eligible = all(
                    result.passed
                    for result in verdict.results
                    if result.rule_id
                    in {"CRO-02", "CRO-03", "CRO-04", "CRO-05", "CRO-06", "CRO-07", "CRO-08"}
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
        """CRO-03/CRO-06: earlier approvals reserve shares/notional for later proposals."""
        current = snapshot
        verdicts: list[Verdict] = []
        try:
            for proposal in proposals:
                verdict = self.evaluate(
                    proposal, current, markets[proposal.symbol], state, now, deployable=deployable
                )
                verdicts.append(verdict)
                if verdict.decision == Decision.APPROVED:
                    pending = OpenOrder(
                        symbol=proposal.symbol,
                        side=proposal.side,
                        qty=proposal.qty,
                        limit_price=proposal.limit_price,
                    )
                    current = current.model_copy(
                        update={"open_orders": (*current.open_orders, pending)}
                    )
            return tuple(verdicts)
        except Exception as exc:
            raise DataIntegrityError("CRO-03/CRO-06: batch inputs cannot be verified") from exc
```

### backend/tests/test_data_layer.py

Scope: Preserved draft compatibility edit. SHA-256: 7c4eaccf0d58b70a13668b4a46b221cdb7e881cbcaea422d12b801432718a5e7.

```python
"""DAT-01..04/R-02/R-04: offline market-data safety and SDK-shape regressions."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import requests
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockLatestTradeRequest
from sqlalchemy import Engine, select

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import DataSnapshot, SystemEvent, transaction
from backend.core.errors import DataIntegrityError, ProviderError, SafetyError, StaleDataError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.broker_state import ExactJSONResponse, TimeoutSession
from backend.data.data_layer import (
    AlpacaMarketData,
    Bar,
    DataLayer,
    MarketDataProvider,
    ResilientReader,
    validate_clock_skew,
    validate_quote,
)
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import MarketContext, MarketStatus

NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def notify(self, state: str, reason: str) -> None:
        self.events.append((state, reason))


class RawProvider:
    def __init__(self, bars: tuple[Bar, ...], context: MarketContext) -> None:
        self.bars = bars
        self.context = context

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        return self.bars

    def latest_market(self, symbol: str, now: datetime) -> MarketContext:
        return self.context


def market(timestamp: datetime, **values: Any) -> MarketContext:
    return MarketContext(
        last_price=values.get("last_price", Decimal("100")),
        last_price_ts=timestamp,
        adv20_usd=values.get("adv20_usd", Decimal("1000000")),
        status=values.get("status", MarketStatus.OK),
    )


def daily_bar(day: date, **values: Any) -> Bar:
    fields: dict[str, Any] = {
        "timestamp": datetime(day.year, day.month, day.day, tzinfo=NEW_YORK),
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100"),
        "volume": 1000,
    }
    fields.update(values)
    return Bar(**fields)


def intraday_bar(timestamp: datetime) -> Bar:
    return daily_bar(timestamp.date(), timestamp=timestamp)


def make_layer(
    engine: Engine,
    calendar: MarketCalendar,
    *,
    now: datetime = NOW,
    bars: tuple[Bar, ...] = (),
    context: MarketContext | None = None,
    provider: MarketDataProvider | None = None,
    **values: Any,
) -> tuple[DataLayer, SystemStateStore, Ledger, RecordingNotifier]:
    clock = FrozenClock(now)
    notifier = RecordingNotifier()
    state = SystemStateStore(engine, clock, notifier)
    ledger = Ledger(engine, clock)
    layer = DataLayer(
        Settings(),
        provider or RawProvider(bars, context or market(now)),
        calendar,
        clock,
        state,
        ledger,
        **values,
    )
    return layer, state, ledger, notifier


@pytest.mark.parametrize("age,passes", [(0, True), (60, True), (61, False)])
def test_DAT_01_regular_quote_age_exact_boundary(
    calendar: MarketCalendar,
    age: int,
    passes: bool,
) -> None:
    context = market(NOW - timedelta(seconds=age))
    if passes:
        validate_quote(context, NOW, Settings(), calendar)
    else:
        with pytest.raises(StaleDataError):
            validate_quote(context, NOW, Settings(), calendar)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 9, 29, 23, 0, tzinfo=UTC),
        datetime(2026, 10, 3, 18, 0, tzinfo=UTC),
        datetime(2026, 10, 4, 18, 0, tzinfo=UTC),
        datetime(2026, 7, 3, 18, 0, tzinfo=UTC),
        datetime(2026, 11, 27, 18, 30, tzinfo=UTC),
        datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
    ],
)
def test_DAT_01_frozen_night_weekend_holiday_earlyclose_and_dst_do_not_halt(
    engine: Engine,
    calendar: MarketCalendar,
    now: datetime,
) -> None:
    close = calendar.session_close(calendar.last_completed_session(now))
    layer, state, _, notifier = make_layer(engine, calendar, now=now, context=market(close))
    assert layer.latest_market("AAPL").last_price_ts == close
    assert state.current() == SystemState.RUNNING
    assert notifier.events == []


def test_DAT_01_offhours_quote_age_measured_from_last_close(calendar: MarketCalendar) -> None:
    now = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)
    close = calendar.session_close(date(2026, 10, 2))
    validate_quote(market(close - timedelta(seconds=60)), now, Settings(), calendar)
    with pytest.raises(StaleDataError):
        validate_quote(market(close - timedelta(seconds=61)), now, Settings(), calendar)


@pytest.mark.parametrize(
    "timestamp", [NOW + timedelta(microseconds=1), NOW - timedelta(seconds=61)]
)
def test_DAT_01_DAT_02_invalid_quote_halts_with_typed_error(
    engine: Engine,
    calendar: MarketCalendar,
    timestamp: datetime,
) -> None:
    layer, state, _, notifier = make_layer(engine, calendar, context=market(timestamp))
    with pytest.raises(SafetyError):
        layer.latest_market("AAPL")
    assert state.current() == SystemState.HALTED
    assert notifier.events[-1][0] == "HALTED"


@pytest.mark.parametrize("seconds,passes", [(2, True), (-2, True), (3, False), (-3, False)])
def test_DAT_02_clock_skew_exact_boundary(seconds: int, passes: bool) -> None:
    if passes:
        validate_clock_skew(NOW + timedelta(seconds=seconds), NOW, Settings())
    else:
        with pytest.raises(DataIntegrityError):
            validate_clock_skew(NOW + timedelta(seconds=seconds), NOW, Settings())


def test_DAT_03_inprogress_daily_is_persisted_raw_and_not_returned(
    engine: Engine,
    calendar: MarketCalendar,
) -> None:
    previous = daily_bar(date(2026, 9, 28))
    current = daily_bar(date(2026, 9, 29))
    layer, state, ledger, _ = make_layer(engine, calendar, bars=(previous, current))
    assert layer.completed_daily_bars("AAPL", date(2026, 9, 28)) == (previous,)
    assert state.current() == SystemState.RUNNING
    with transaction(engine) as session:
        snapshots = tuple(session.scalars(select(DataSnapshot)))
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.bar_count == 2 and len(snapshot.bars) == 2
    assert snapshot.feed == "SIP" and snapshot.adjustment == "ALL"
    assert snapshot.fetched_at == NOW
    assert len(snapshot.sha256) == 64
    ledger.verify_chain()


@pytest.mark.parametrize("elapsed,passes", [(899, True), (900, False)])
def test_DAT_01_sip_daily_grace_exact_boundary(
    engine: Engine,
    calendar: MarketCalendar,
    elapsed: int,
    passes: bool,
) -> None:
    now = calendar.session_close(date(2026, 9, 29)) + timedelta(seconds=elapsed)
    previous = daily_bar(date(2026, 9, 28))
    layer, state, _, _ = make_layer(engine, calendar, now=now, bars=(previous,))
    if passes:
        assert layer.completed_daily_bars("AAPL", date(2026, 9, 28)) == (previous,)
        assert state.current() == SystemState.RUNNING
    else:
        with pytest.raises(StaleDataError):
            layer.completed_daily_bars("AAPL", date(2026, 9, 28))
        assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "unordered",
        "missing_middle",
        "missing_first",
        "stale",
        "empty",
        "future",
        "holiday",
    ],
)
def test_DAT_01_DAT_02_daily_sequence_failures_halt(
    engine: Engine,
    calendar: MarketCalendar,
    fault: str,
) -> None:
    now = datetime(2026, 9, 29, 21, 0, tzinfo=UTC)
    first, middle, last = (
        daily_bar(day) for day in (date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29))
    )
    choices: dict[str, tuple[Bar, ...]] = {
        "duplicate": (first, middle, middle, last),
        "unordered": (middle, first, last),
        "missing_middle": (first, last),
        "missing_first": (middle, last),
        "stale": (first, middle),
        "empty": (),
        "future": (
            first,
            middle,
            last.model_copy(update={"timestamp": now + timedelta(seconds=1)}),
        ),
        "holiday": (daily_bar(date(2026, 7, 3)), last),
    }
    layer, state, _, _ = make_layer(engine, calendar, now=now, bars=choices[fault])
    with pytest.raises(SafetyError):
        layer.completed_daily_bars("AAPL", date(2026, 9, 25))
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "updates",
    [
        {"open": Decimal("0")},
        {"close": Decimal("-1")},
        {"open": None},
        {"open": Decimal("NaN")},
        {"high": Decimal("99")},
        {"low": Decimal("101")},
        {"high": Decimal("98"), "low": Decimal("99")},
        {"volume": -1},
        {"volume": True},
        {"volume": Decimal("1")},
        {"timestamp": datetime(2026, 9, 28)},
    ],
)
def test_DAT_02_each_daily_integrity_violation_halts(
    engine: Engine,
    calendar: MarketCalendar,
    updates: dict[str, Any],
) -> None:
    broken = daily_bar(date(2026, 9, 28)).model_copy(update=updates)
    layer, state, _, _ = make_layer(engine, calendar, bars=(broken,))
    with pytest.raises(SafetyError):
        layer.completed_daily_bars("AAPL", date(2026, 9, 28))
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize("opening,suspect", [("125", False), ("125.01", True)])
def test_DAT_02_gap_exact_boundary_is_suspect_and_survives_restart(
    engine: Engine,
    calendar: MarketCalendar,
    opening: str,
    suspect: bool,
) -> None:
    left = daily_bar(date(2026, 9, 25))
    right = daily_bar(
        date(2026, 9, 28),
        open=Decimal(opening),
        high=Decimal("127"),
        low=Decimal("124"),
        close=Decimal("126"),
    )
    layer, state, ledger, _ = make_layer(engine, calendar, bars=(left, right))
    layer.completed_daily_bars("AAPL", date(2026, 9, 25))
    expected = MarketStatus.SUSPECT if suspect else MarketStatus.OK
    assert layer.latest_market("AAPL").status == expected
    restarted = DataLayer(Settings(), layer.provider, calendar, layer.clock, state, ledger)
    assert restarted.latest_market("AAPL").status == expected
    assert state.current() == SystemState.RUNNING
    if suspect:
        with pytest.raises(DataIntegrityError):
            restarted.acknowledge_gap("AAPL", "", "checked split")
        restarted.acknowledge_gap("AAPL", "operator-test", "verified corporate action")
        again = DataLayer(Settings(), layer.provider, calendar, layer.clock, state, ledger)
        assert again.latest_market("AAPL").status == MarketStatus.OK


def test_DAT_02_known_corporate_action_explains_gap(
    engine: Engine, calendar: MarketCalendar
) -> None:
    left = daily_bar(date(2026, 9, 25))
    right = daily_bar(
        date(2026, 9, 28),
        open=Decimal("150"),
        high=Decimal("151"),
        low=Decimal("149"),
        close=Decimal("150"),
    )
    layer, _, _, _ = make_layer(
        engine,
        calendar,
        bars=(left, right),
        corporate_actions=frozenset({("AAPL", date(2026, 9, 28))}),
    )
    layer.completed_daily_bars("AAPL", date(2026, 9, 25))
    assert layer.latest_market("AAPL").status == MarketStatus.OK


@pytest.mark.parametrize("end_age,passes", [(120, True), (121, False)])
def test_DAT_01_intraday_endtime_age_exact_boundary(
    engine: Engine,
    calendar: MarketCalendar,
    end_age: int,
    passes: bool,
) -> None:
    layer, state, _, _ = make_layer(engine, calendar)
    bar = intraday_bar(NOW - timedelta(seconds=end_age + 60))
    if passes:
        assert layer.validate_intraday((bar,), 60) == (bar,)
    else:
        with pytest.raises(StaleDataError):
            layer.validate_intraday((bar,), 60)
        assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "fault", ["inprogress", "future", "duplicate", "unordered", "missing_interval", "weekend"]
)
def test_DAT_02_DAT_03_invalid_intraday_sequences_halt(
    engine: Engine,
    calendar: MarketCalendar,
    fault: str,
) -> None:
    layer, state, _, _ = make_layer(engine, calendar)
    a, b = intraday_bar(NOW - timedelta(minutes=2)), intraday_bar(NOW - timedelta(minutes=1))
    choices = {
        "inprogress": (intraday_bar(NOW - timedelta(seconds=30)),),
        "future": (intraday_bar(NOW + timedelta(seconds=1)),),
        "duplicate": (b, b),
        "unordered": (b, a),
        "missing_interval": (intraday_bar(NOW - timedelta(minutes=5)), b),
        "weekend": (intraday_bar(datetime(2026, 9, 26, 15, 0, tzinfo=UTC)), b),
    }
    with pytest.raises(SafetyError):
        layer.validate_intraday(choices[fault], 60)
    assert state.current() == SystemState.HALTED


def test_DAT_01_intraday_weekend_uses_friday_session_close(
    engine: Engine,
    calendar: MarketCalendar,
) -> None:
    now = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)
    close = calendar.session_close(date(2026, 10, 2))
    layer, state, _, _ = make_layer(engine, calendar, now=now)
    bar = intraday_bar(close - timedelta(seconds=60))
    assert layer.validate_intraday((bar,), 60) == (bar,)
    assert state.current() == SystemState.RUNNING


class StatusError(Exception):
    def __init__(self, status: int) -> None:
        self.status_code = status


def reader_fixture(
    engine: Engine,
    *,
    attempts: int = 3,
    calls_per_minute: int = 200,
) -> tuple[ResilientReader, SystemStateStore, list[float]]:
    state = SystemStateStore(engine, FrozenClock(NOW), RecordingNotifier())
    sleeps: list[float] = []
    reader = ResilientReader(
        FrozenClock(NOW),
        state,
        attempts=attempts,
        calls_per_minute=calls_per_minute,
        sleep=sleeps.append,
    )
    return reader, state, sleeps


@pytest.mark.parametrize(
    "error",
    [
        StatusError(429),
        StatusError(500),
        StatusError(503),
        TimeoutError("timeout"),
        requests.Timeout("timeout"),
    ],
)
def test_DAT_04_transient_reads_retry_with_fake_sleep_and_recover(
    engine: Engine,
    error: Exception,
) -> None:
    reader, state, sleeps = reader_fixture(engine)
    count = 0

    def operation() -> str:
        nonlocal count
        count += 1
        if count < 3:
            raise error
        return "trusted-result"

    assert reader.run(operation) == "trusted-result"
    assert count == 3 and len(sleeps) == 2
    assert all(1 <= delay <= 8 for delay in sleeps)
    assert not reader.tripped and state.current() == SystemState.RUNNING


@pytest.mark.parametrize(
    "error", [StatusError(400), StatusError(401), RuntimeError("fault"), KeyError("field")]
)
def test_DAT_04_nontransient_reads_are_never_retried(engine: Engine, error: Exception) -> None:
    reader, state, sleeps = reader_fixture(engine)
    count = 0

    def operation() -> str:
        nonlocal count
        count += 1
        raise error

    with pytest.raises(ProviderError):
        reader.run(operation)
    assert count == 1 and sleeps == []
    assert reader.tripped and state.current() == SystemState.HALTED


def test_DAT_04_retry_exhaustion_latches_circuit_and_restart_state(engine: Engine) -> None:
    reader, state, sleeps = reader_fixture(engine)
    count = 0

    def operation() -> int:
        nonlocal count
        count += 1
        raise StatusError(429)

    with pytest.raises(ProviderError):
        reader.run(operation)
    assert count == 3 and len(sleeps) == 2
    with pytest.raises(ProviderError, match="latched"):
        reader.run(operation)
    assert count == 3
    assert (
        SystemStateStore(engine, FrozenClock(NOW), RecordingNotifier()).current()
        == SystemState.HALTED
    )
    assert state.current() == SystemState.HALTED


def test_DAT_04_request_budget_counts_retries_and_blocks_before_io(engine: Engine) -> None:
    reader, state, sleeps = reader_fixture(engine, calls_per_minute=2)
    count = 0

    def operation() -> str:
        nonlocal count
        count += 1
        return "result"

    reader.run(operation)
    reader.run(operation)
    with pytest.raises(ProviderError, match="budget"):
        reader.run(operation)
    assert count == 2 and sleeps == [] and state.current() == SystemState.HALTED


def test_DAT_04_budget_exact_minute_and_backward_clock_fail_closed(engine: Engine) -> None:
    reader, state, _ = reader_fixture(engine, calls_per_minute=1)
    reader.run(lambda: "first")
    reader.clock = FrozenClock(NOW + timedelta(seconds=60))
    assert reader.run(lambda: "second") == "second"
    reader.clock = FrozenClock(NOW + timedelta(seconds=59))
    with pytest.raises(DataIntegrityError, match="backward"):
        reader.run(lambda: "must-not-run")
    assert state.current() == SystemState.HALTED


def test_DAT_04_requests_http_status_429_is_transient(engine: Engine) -> None:
    reader, state, sleeps = reader_fixture(engine, attempts=2)
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError("rate limited", response=response)
    count = 0

    def operation() -> int:
        nonlocal count
        count += 1
        if count == 1:
            raise error
        return 5

    assert reader.run(operation) == 5
    assert len(sleeps) == 1 and state.current() == SystemState.RUNNING


def fault(*args: object, **kwargs: object) -> Any:
    raise RuntimeError("injected boundary fault")


@pytest.mark.parametrize("boundary", ["calendar", "provider", "database"])
def test_R_02_DAT_02_runtime_boundary_faults_are_typed_and_halt(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    layer, state, ledger, _ = make_layer(engine, calendar, bars=(daily_bar(date(2026, 9, 28)),))
    if boundary == "calendar":
        monkeypatch.setattr(calendar, "is_open", fault)
    elif boundary == "provider":
        monkeypatch.setattr(layer.provider, "latest_market", fault)
    else:
        monkeypatch.setattr(ledger, "append", fault)

    def operation() -> None:
        if boundary == "database":
            layer.completed_daily_bars("AAPL", date(2026, 9, 28))
        else:
            layer.latest_market("AAPL")

    with pytest.raises(SafetyError):
        operation()
    assert state.current() == SystemState.HALTED


def test_R_02_DAT_02_persisted_symbol_replay_fault_is_typed_and_halts(
    engine: Engine,
    calendar: MarketCalendar,
) -> None:
    layer, state, ledger, _ = make_layer(engine, calendar)
    ledger.append(
        SystemEvent,
        state="RUNNING",
        event_type="ESCALATE",
        operator_id=None,
        reason="DAT-02 symbol status: malformed-json",
    )
    with pytest.raises(SafetyError):
        DataLayer(Settings(), layer.provider, calendar, layer.clock, state, ledger)
    assert state.current() == SystemState.HALTED


def test_R_02_DAT_02_gap_acknowledgment_database_fault_is_typed_and_halts(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layer, state, ledger, _ = make_layer(engine, calendar)
    monkeypatch.setattr(ledger, "append_in_session", fault)
    with pytest.raises(SafetyError):
        layer.acknowledge_gap("AAPL", "operator-test", "checked")
    assert state.current() == SystemState.HALTED


def raw_bar(bar: Bar) -> dict[str, object]:
    return {
        "t": bar.timestamp.isoformat(),
        "o": bar.open,
        "h": bar.high,
        "l": bar.low,
        "c": bar.close,
        "v": bar.volume,
    }


class FakeSDK:
    """Return installed alpaca-py raw_data symbol maps, without HTTP envelopes."""

    def __init__(self, bars: tuple[Bar, ...]) -> None:
        self._session = requests.Session()
        self._retry = 3
        self.bars: dict[str, Any] = {"AAPL": [raw_bar(bar) for bar in bars]}
        self.quotes: dict[str, Any] = {
            "AAPL": {
                "bp": Decimal("99.99"),
                "ap": Decimal("100.01"),
                "t": (NOW - timedelta(seconds=10)).isoformat(),
            }
        }
        self.trades: dict[str, Any] = {
            "AAPL": {"p": Decimal("100"), "t": (NOW - timedelta(seconds=5)).isoformat()}
        }
        self.requests: list[object] = []

    def get_stock_bars(self, request: StockBarsRequest) -> object:
        self.requests.append(request)
        return self.bars

    def get_stock_latest_quote(self, request: StockLatestQuoteRequest) -> object:
        self.requests.append(request)
        return self.quotes

    def get_stock_latest_trade(self, request: StockLatestTradeRequest) -> object:
        self.requests.append(request)
        return self.trades


def sdk_fixture(
    engine: Engine, calendar: MarketCalendar
) -> tuple[AlpacaMarketData, FakeSDK, SystemStateStore]:
    bars = tuple(daily_bar(day) for day in calendar.previous_sessions(NOW.date(), 20))
    client = FakeSDK(bars)
    reader, state, _ = reader_fixture(engine)
    provider = AlpacaMarketData(Settings(), reader, client=client)
    return provider, client, state


def test_DAT_03_official_sdk_symbol_shapes_and_sip_iex_request_contracts(
    engine: Engine,
    calendar: MarketCalendar,
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    assert isinstance(client._session, TimeoutSession) and client._retry == 0
    bars = provider.daily_bars("AAPL", date(2026, 9, 1), NOW.date())
    assert len(bars) == 20
    request = client.requests[-1]
    assert isinstance(request, StockBarsRequest)
    assert request.feed == DataFeed.SIP and request.adjustment == Adjustment.ALL
    assert request.start is not None and request.start.tzinfo is not None
    context = provider.latest_market("AAPL", NOW)
    assert context.last_price == Decimal("100") and context.adv20_usd == Decimal("100000")
    assert context.last_price_ts == NOW - timedelta(seconds=10)
    quote_request = next(
        item for item in client.requests if isinstance(item, StockLatestQuoteRequest)
    )
    trade_request = next(
        item for item in client.requests if isinstance(item, StockLatestTradeRequest)
    )
    assert quote_request.feed == DataFeed.IEX and trade_request.feed == DataFeed.IEX
    assert state.current() == SystemState.RUNNING


@pytest.mark.parametrize("fault_kind", ["bad_ohlc", "missing_session", "stale_tail", "float_price"])
def test_DAT_02_adv_history_must_be_valid_complete_current_and_exact(
    engine: Engine,
    calendar: MarketCalendar,
    fault_kind: str,
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    if fault_kind == "bad_ohlc":
        client.bars["AAPL"][0]["h"] = Decimal("50")
    elif fault_kind == "float_price":
        client.bars["AAPL"][0]["o"] = float("100")
    elif fault_kind == "missing_session":
        all_sessions = calendar.previous_sessions(NOW.date(), 21)
        client.bars["AAPL"] = [
            raw_bar(daily_bar(day)) for index, day in enumerate(all_sessions) if index != 10
        ]
    else:
        old = calendar.previous_sessions(date(2026, 9, 14), 20)
        client.bars["AAPL"] = [raw_bar(daily_bar(day)) for day in old]
    layer = DataLayer(
        Settings(), provider, calendar, FrozenClock(NOW), state, Ledger(engine, FrozenClock(NOW))
    )
    with pytest.raises(SafetyError):
        layer.latest_market("AAPL")
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "field,value",
    [("bp", Decimal("0")), ("ap", Decimal("99")), ("t", (NOW + timedelta(seconds=1)).isoformat())],
)
def test_DAT_02_bad_sdk_quote_cannot_become_market_context(
    engine: Engine,
    calendar: MarketCalendar,
    field: str,
    value: object,
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    client.quotes["AAPL"][field] = value
    layer = DataLayer(
        Settings(), provider, calendar, FrozenClock(NOW), state, Ledger(engine, FrozenClock(NOW))
    )
    with pytest.raises(SafetyError):
        layer.latest_market("AAPL")
    assert state.current() == SystemState.HALTED


def test_R_04_DAT_03_transport_preserves_json_decimal_before_sdk_parsing() -> None:
    response = ExactJSONResponse()
    response._content = b'{"bars":{"AAPL":[{"c":100.123456,"v":1000}]}}'
    value = response.json()
    assert value["bars"]["AAPL"][0]["c"] == Decimal("100.123456")
    assert isinstance(value["bars"]["AAPL"][0]["c"], Decimal)
```

### scripts/plaid_sandbox_token.py

Scope: Preserved draft compatibility edit. SHA-256: 31bfc1372340d595344750eae41cf51856f96f2322921be45dc88312d134b72b.

```python
"""R-07/R-08: create a Sandbox-only token and store Fernet ciphertext.

Run ``python -m scripts.plaid_sandbox_token --output .secrets/plaid-token.fernet``.
FERNET_KEY, PLAID_CLIENT_ID and PLAID_SECRET must already be configured. No token
or key is printed. Balance requires another product entitlement; Auth is used
only for Sandbox bootstrap. Runtime liquidity calls remain balance reads only.
"""

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

import plaid
from cryptography.fernet import Fernet
from plaid.api.plaid_api import PlaidApi
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest

from backend.core.config import Settings, load_settings
from backend.core.errors import ConfigurationError, ProviderError
from backend.core.logging import configure_logging, register_secrets


class SandboxTokenClient(Protocol):
    """R-08: bootstrap exposes only Sandbox creation and token exchange."""

    def sandbox_public_token_create(self, request: object, **kwargs: object) -> object:
        """R-08: create a test Item, never an external money instruction."""
        raise NotImplementedError("client must supply Sandbox token creation")

    def item_public_token_exchange(self, request: object, **kwargs: object) -> object:
        """R-07: exchange a public token for the secret access token."""
        raise NotImplementedError("client must supply public token exchange")


def create_sandbox_token(
    settings: Settings,
    output: Path,
    institution_id: str = "ins_109508",
    *,
    client: SandboxTokenClient | None = None,
) -> Path:
    """R-07/R-08: write ciphertext once; never overwrite an existing token file."""
    if settings.plaid_env != "sandbox":
        raise ConfigurationError("token bootstrap is permitted only in Plaid Sandbox")
    if not institution_id.strip():
        raise ConfigurationError("Sandbox institution ID is required")
    try:
        cipher = Fernet(settings.fernet_key.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise ConfigurationError("a valid FERNET_KEY is required before bootstrap") from exc
    if output.exists():
        raise ConfigurationError("token output already exists; choose a new file")
    if client is None:
        if (
            not settings.plaid_client_id.get_secret_value()
            or not settings.plaid_secret.get_secret_value()
        ):
            raise ConfigurationError("Plaid Sandbox credentials are required")
        # VERIFY: https://github.com/plaid/plaid-python#usage
        configuration = plaid.Configuration(
            host=plaid.Environment.Sandbox,
            api_key={
                "clientId": settings.plaid_client_id.get_secret_value(),
                "secret": settings.plaid_secret.get_secret_value(),
            },
        )
        client = cast(SandboxTokenClient, PlaidApi(plaid.ApiClient(configuration)))
    try:
        # VERIFY: https://plaid.com/docs/api/sandbox/#sandboxpublic_tokencreate
        # VERIFY: https://plaid.com/docs/balance/ (Balance is not standalone.)
        public_response = client.sandbox_public_token_create(
            SandboxPublicTokenCreateRequest(
                institution_id=institution_id,
                initial_products=[Products("auth")],
            ),
            _request_timeout=settings.request_timeout_seconds,
        )
        public_token = _token_field(public_response, "public_token")
        register_secrets(public_token)
        # VERIFY: https://plaid.com/docs/api/items/#itempublic_tokenexchange
        exchange_response = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token),
            _request_timeout=settings.request_timeout_seconds,
        )
        access_token = _token_field(exchange_response, "access_token")
        register_secrets(access_token)
        ciphertext = cipher.encrypt(access_token.encode("utf-8"))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as handle:
            handle.write(ciphertext)
        return output.resolve()
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ProviderError("Sandbox token bootstrap failed; no secret was printed") from exc


def _token_field(response: object, name: str) -> str:
    """R-07: validate token fields without putting their values in errors."""
    if isinstance(response, Mapping):
        value = response.get(name)
    elif name == "public_token":
        value = getattr(response, "public_token", None)
    elif name == "access_token":
        value = getattr(response, "access_token", None)
    else:
        raise ConfigurationError("Unsupported Plaid token field")
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError("Plaid token response is incomplete")
    return value


def main() -> None:
    """R-07: CLI loads optional dotenv explicitly and prints only the file path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--institution", default="ins_109508")
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()
    settings = load_settings(env_file=args.env_file)
    configure_logging()
    result = create_sandbox_token(settings, args.output, args.institution)
    print(f"Encrypted Sandbox token saved to {result}")


if __name__ == "__main__":
    main()
```

END OF DELIVERY — 44 complete files. Nothing remains truncated.
