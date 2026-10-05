# Audit fixes verification - 2026-10-04

The complete offline suite passed **2,167 tests in 240.36 seconds**, with one
upstream websockets deprecation warning. All risk modules, tax contracts and
persisted state reached **100% statement and branch coverage**: 1,238 statements,
400 branches. Ruff check/format (78 files), strict mypy (70 authored sources),
the execution guard, production Bandit, pip check, pip-audit (109 unchanged
pins), corrected source secrets scan and all five actual Git-root hooks passed.
Full-history gitleaks 8.30.1: two commits, 2.19 MB, zero leaks.

See docs/STATUS.md for changes, requirement traceability, commands, assumptions
and UNVERIFIED checks. The results below are historical stage-delivery evidence.
No PostgreSQL, Docker, mutation or real-account integration pass is claimed.

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
