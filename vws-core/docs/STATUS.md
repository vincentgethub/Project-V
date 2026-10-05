# Technical status

Audit date: 2026-10-04 America/Chicago. The initial audit results below describe the pre-fix working
tree. The audit-fixes gate below certifies the current implementation. Amendments 01â€“04 supersede conflicts in the master and
earlier addenda. Execution order: audit/fixes â†’ S â†’ D â†’ E â†’ F â†’ G â†’ H â†’ J â†’ I â†’ K.
Optional ideas require plain-words approval and live only in PROGRESS Suggestions.

## Stage inventory

| Stage | Existing deliverable | Current amended status |
| --- | --- | --- |
| A | core config/money/clock/logging/database/ledger/state/guard; XNYS calendar; Stage_A.md | Original stage certified; configuration/guard corrections certified |
| B | frozen contracts, registry, CRO, risk boundary; Stage_B.md | Original certified; session daily-loss correction certified |
| C | compliance, wash matching, tax models, compliance boundary; Stage_C.md | Original certified; shared tax-core move reserved for J |
| D | data_layer/broker_state/liquidity/read boundary; indicators/scanner; Sandbox helper; six test modules | Original source tests pass; no final D delivery; DAT-05..12 missing |
| S | SecretStr, redaction, append-only chains and source bans are foundations | New security stage not implemented |
| Eâ€“K | Configuration/storage foundations only | Agents/swarm/bot/evaluation/ops/funding/P&L/tax/auto/extras not implemented |

64 authored Python files: 39 production/script files and 25 test-package files.
588 test function declarations; parametrized execution count is 1,866.

## Fresh audit gates

| Command | Actual result |
| --- | --- |
| `.venv\Scripts\python.exe -m ruff check .` | PASS |
| `.venv\Scripts\python.exe -m ruff format --check .` | PASS, 73 files formatted |
| `.venv\Scripts\python.exe -m mypy --strict` | PASS, 64 source files |
| `python -m bandit -r backend/core backend/domain backend/risk backend/data backend/agents scripts -c pyproject.toml -q` | PASS, 0 production findings |
| `python -m pip_audit -r requirements-lock.txt --no-deps --disable-pip --progress-spinner off --timeout 15` | PASS, no known vulnerabilities in 109 exact pins |
| `python -m pip check` | PASS, no broken requirements |
| `python -m backend.core.source_guard .` | PASS, current total execution ban |
| `python -m pytest -q --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov-branch --cov-fail-under=100 --cov-report=term-missing` | PASS, 1,866 tests, 185.51s, one SDK deprecation warning; 1,108 statements/360 branches, 100% |
| `detect_secrets scan --all-files` with verified cross-platform exclusions | PASS, 0 authored-source findings, scanner 1.5.0 |
| `gitleaks git . --log-opts=--all --redact --no-banner` | PASS, gitleaks 8.30.1, 0 commits/0 bytes/no leaks |

The initial broad Bandit command scanned test assertions due to Windows path
normalization and produced test-only findings; the explicit production scan above
is the gate. A first secrets command similarly used a malformed Windows path
exclusion and scanned dependency/cache/test files. Its corrected scan was rerun
and returned zero authored-source findings. Neither noisy scan is reported PASS.
The correct shell exclusion is `(^|[\\/])(\.venv|backend[\\/]tests|deliveries|\.git|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.hypothesis|__pycache__|mutants|build|dist)[\\/]`.

## Audit fixes gate

Final whole-suite gate: **2,167 passed**, one upstream SDK deprecation warning,
240.36 seconds. All risk modules, tax contracts and durable state: **100%** of
1,238 statements and 400 branches. Ruff lint/format (78 files), strict mypy
(70 authored sources), execution guard, explicit production Bandit, pip check,
pip-audit (109 unchanged exact pins), source secrets scan (0 findings), and all
five actual Git-root pre-commit hooks passed. Gitleaks 8.30.1 scanned the full
one-commit history, 2.11 MB, with no leaks; rerun after the audit-fixes commit.
The current authored inventory is 70 Python files: 43 production/script and
27 test-package files, with 631 test-function declarations.

Resolved: explicit broker account type; five YAML-only schedule/cooldown keys
with wrong-home rejection; ten removed-field guard positive controls; extended
crypto-wallet/money-movement bans; narrative-only fundamental prompt; and
session daily-loss persistence. `risk/portfolio_marks.py` plus
`test_portfolio_marks.py` bind observations and immutable breach evidence to
account/session/source seq/stored limit/config hash. A breach survives recovery,
restart and threshold changes until the next XNYS open. `data/boundary.py`
records every valid broker read, and `risk/boundary.py` uses that evidence.
Drawdown/fault states still latch; held exits bypass the daily entry block.

`vws/progress.py`/`test_progress.py` provide the bounded progress command and
private-chat subset. CI enforces progress changes alongside code; the Telegram
command remains pending F. The page has 43 lines; AGENTS.md has 66.
Verbatim specification and historical-delivery bytes are protected by Git
attributes. An accidentally tracked generated coverage report is removed from
the index; coverage outputs are ignored. No ledger rows or history were deleted.
A collection-time synthetic Settings fixture needed explicit CASH after the
required-field correction; it was fixed before the complete gate rerun.

## Contamination and STOP audit

No reachable submit/replace/cancel/close/transfer/bank-link/crypto-wallet calls
were found. Git had no commits at audit start, so no committed secrets existed.
No migration rewrites/deletes ledger rows. `database.py:729` replaces protection
triggers transactionally; incompatible schemas fail at lines 701/711.

| Finding | Location before fixes | Required action |
| --- | --- | --- |
| LLM fundamental boolean verdicts | prompts/fundamental_analyst.md:34,39,41,56,60 | Replace unused prompt with narrative-only role |
| Superseded floats/client/DROP plan | FUNDAMENTAL_ADDENDUM.md:20â€“30,46,50 | Mark superseded; use amended deterministic Decimal FA framework, default annotate |
| Duplicated schedule homes | .env.example:73â€“74; config.py:115â€“116,205â€“206,558â€“559; config.yaml:10â€“11 | YAML only; reject those env keys |
| Daily loss latches REDUCE_ONLY | system_state.py:87; risk_cro.py:134; data/boundary.py:104 | Session entry gate; next-open baseline rollover; drawdown/fault remains latched |
| Account type defaults to CASH | config.py:164 | Require explicit account type |
| Plaid token env/file source | liquidity.py:286â€“287 | Replace with keyring-only storage in S |
| SIP end lacks 16-minute clamp | data_layer.py:554,568 | DAT-07 in expanded D |
| Old scanner anchor definition | scanner.py:142 | Amend exact anchor definition for playbooks in E |

No response_format argument, hard-coded model, malformed Markdown URL,
development Plaid environment, import-time Settings, unauthorized wall clock,
production financial float, bare/swallowed exception, Decimal price truthiness,
non-PK seq autoincrement or deprecated Alpaca-field read was found. No callback
handler exists yet. `source_guard.py:53` split('_') normalizes identifiers only.
Order strings in execution_policy/test_no_order_exec are guard declarations and
positive controls, never executed. SentimentSignal.score (models.py:487â€“491) is
an advisory sentiment field allowed by the master; no LLM caller exists. It must
never set a playbook score or trade decision. No yfinance/WhaleAlert/Etherscan/
LangGraph/FastAPI/frontend/genetic implementation exists.

The earlier fundamentals addendum produced a planning document and full prompt
only. No FundamentalAnalyst, ModelAgnosticClient, fundamentals computation,
provider, fan-out or approval integration was built. Those artifacts are now
superseded by Amendment 01 section 4.2.

## Installed versions

alpaca-py 0.44.0; pydantic 2.13.5; pydantic-settings 2.15.0; SQLAlchemy 2.0.54;
python-telegram-bot 22.8; APScheduler 3.11.3; openai 3.24.0;
exchange-calendars 4.13.2; Python 3.12.14. Alpaca 0.44.0 includes upstream
fd14c0af0e1c346d5881865a83d6b3a8aa00cd80 (37 commits ahead, zero behind),
verified against tagged upstream source; no local SDK patch is required.

## Master requirement traceability

All code paths below are under backend/; all test names are under backend/tests/.
Line references in contamination inventory above refer to the pre-fix snapshot.

| Requirement | Code | Test | Status |
| --- | --- | --- | --- |
| R-01 | domain/models.py; risk/risk_cro.py | test_domain.py; test_risk_cro.py | Whole shares/long-only shape implemented |
| R-02 | core/system_state.py; risk boundaries; data/boundary.py | test_system_state.py; test_risk_boundary.py; test_compliance_boundary.py; test_read_boundary.py | Current fail-closed boundaries implemented |
| R-03 | risk/risk_cro.py; risk/compliance.py | test_risk_cro.py; test_compliance.py | Pure rules implemented |
| R-04 | core/money.py; core/database.py; core/ledger.py | test_money.py; test_ledger.py | Exact money implemented |
| R-05 | core/clock.py; domain/models.py | test_config_safety.py; test_domain.py | UTC injected time implemented |
| R-06 | core/config.py; data/broker_state.py | test_config_safety.py; test_broker_state.py | Manual mode guard implemented; auto binding pending I |
| R-07 | core/config.py; core/logging.py | test_config_safety.py; test_logging.py | Foundation implemented; keyring/rotation pending S |
| R-08 | data/broker_state.py; data/liquidity.py | test_broker_state.py; test_liquidity.py | Read-only runtime implemented |
| R-09 | core/system_state.py; risk/risk_cro.py; risk/compliance.py | test_risk_cro.py; test_compliance.py | Manual held exits implemented; AX-30 pending I |
| R-10 | core/source_guard.py; core/execution_policy.py | test_no_order_exec.py | Total ban implemented before I |
| R-11 | domain/models.py; agents/scanner.py | test_domain.py; test_scanner.py | Deterministic contracts/scanner only; LLM pending E |
| R-12 | core/config.py; domain/models.py | test_yaml_config.py; test_domain.py | Partial; sanitization/delimiters/display pending S/E/F |
| R-13 | core/money.py; domain/models.py; agents/indicators.py | test_money.py; test_indicators.py | Implemented current boundaries |
| R-14 | core/config.py; core/ledger.py | test_config_safety.py; test_research_ledger.py | Storage/readiness only; callbacks pending F |
| CRO-01 | risk/risk_cro.py; core/system_state.py | test_risk_cro.py; test_system_state.py | Implemented |
| CRO-02 | risk/risk_cro.py | test_risk_cro.py; test_stage_b_adversarial.py | Implemented |
| CRO-03 | risk/risk_cro.py | test_risk_cro.py | Implemented |
| CRO-04 | risk/risk_cro.py | test_risk_cro.py; test_stage_b_adversarial.py | Implemented |
| CRO-05 | risk/risk_cro.py; domain/instruments.py | test_risk_cro.py; test_domain.py | Implemented |
| CRO-06 | risk/risk_cro.py | test_risk_cro.py | Implemented |
| CRO-07 | risk/risk_cro.py | test_risk_cro.py | Implemented |
| CRO-08 | risk/risk_cro.py | test_risk_cro.py | Implemented |
| CRO-09 | core/system_state.py; core/ledger.py; risk/risk_cro.py | test_system_state.py; test_ledger.py; test_risk_cro.py | Implemented |
| CRO-10 | risk/risk_cro.py; risk/portfolio_marks.py; data/boundary.py | test_risk_cro.py; test_portfolio_marks.py; test_read_boundary.py | Session block corrected and certified |
| CRO-11 | risk/risk_cro.py; domain/models.py | test_risk_cro.py | Implemented; macro loader pending K |
| CRO-12 | data/liquidity.py; risk/risk_cro.py | test_liquidity.py; test_risk_cro.py | Implemented |
| CRO-13 | risk/risk_cro.py | test_risk_cro.py; test_stage_b_adversarial.py | Known/unknown only; estimated earnings pending D |
| CMP-01 | risk/compliance.py; risk/wash_sales.py | test_compliance.py; test_wash_sales.py | Implemented |
| CMP-02 | risk/compliance.py; risk/wash_sales.py | test_compliance.py; test_stage_c_adversarial.py | Implemented |
| CMP-03 | risk/compliance.py | test_compliance.py; test_stage_c_adversarial.py | Implemented |
| CMP-04 | risk/compliance.py | test_compliance.py | Implemented |
| CMP-05 | risk/compliance.py | test_compliance.py; test_stage_c_adversarial.py | Implemented |
| CMP-06 | risk/compliance.py; data/boundary.py | test_compliance.py; test_read_boundary.py | Implemented |
| CMP-07 | risk/compliance.py | test_compliance.py | Implemented |
| DAT-01 | data/data_layer.py; data/market_calendar.py | test_data_layer.py; test_market_calendar.py | Original D implemented |
| DAT-02 | data/data_layer.py; data/broker_state.py | test_data_layer.py; test_broker_state.py | Original D implemented |
| DAT-03 | data/data_layer.py | test_data_layer.py; test_scanner.py | Original D implemented |
| DAT-04 | data/data_layer.py; data/broker_state.py | test_data_layer.py; test_broker_state.py | Original D synchronous implementation |
| GD-01 | core/config.py; core/database.py; core/ledger.py | test_config_safety.py; test_research_ledger.py | Storage/config only; LLM wrapper pending E |
| GD-02 | core/config.py | test_yaml_config.py | Prompt loader pending E; old fundamental prompt superseded |
| GD-03 | agents/scanner.py; core/database.py | test_scanner.py; test_research_ledger.py | Scanner/storage only; hunter/swarm pending E/F |
| GD-04 | core/config.py | test_yaml_config.py | Schedule only; jobs pending F |
| GD-05 | core/database.py; core/ledger.py | test_research_ledger.py | Bot/storage foundation only; bot pending F |
| GD-06 | core/ledger.py | test_research_ledger.py | Ticket storage only; secure approval/display pending F |
| GD-07 | core/source_guard.py; core/execution_policy.py | test_no_order_exec.py | Original ban implemented; isolated I whitelist future |
| GD-08 | â€” | â€” | Offline dry run missing |
| GD-09 | â€” | â€” | Docker missing |

## Amendment traceability and remaining work

DAT-05 batching/cache/memoization; DAT-06 async shared token bucket/Retry-After;
DAT-07 SIP clamp; DAT-08 async SDK worker/semaphore; DAT-09 news/stable IDs;
DAT-10 corporate-actions provider; DAT-11 earnings precedence/estimate;
DAT-12 manual CSV/account-type check: all new work pending expanded D.

FA-01..09: deterministic SEC fundamentals pending E. EV-01..03: outcomes/replay/
report pending G. OPS-01..08: doctor/start/watchdog/backup/migrations/CI/deploy/logs
pending H, except existing chain/schema/logging foundations. AX-01..06,10..16,
20..31,40..44,50..54 pending I. FN-01..06, PL-01..06, TX-01..10 pending J;
money ban, record_cash_flow and Stage C tax matching are foundations. XK-01..10
pending K except keyring/drill dependencies that earlier security/ops stages need.
SEC-01..75 pending S/H/L according to placement; existing SecretStr, redaction,
hash chains and AST bans are foundations. PG-01..04 page/CI checks implemented;
PG-05 CLI implemented and tested, Telegram pending F. WZ-01..10 wizard pending H.

## Owner choices and unverified checks

Defaults per Amendment 01 section 9: Alpaca paper, fundamentals annotate, LLM off,
20 liquid stocks + SPY + 11 sector ETFs (registry expansion pending), both Windows
and VPS instructions, no external tax accounts (show warning), no tax rates
(totals only). Account type/equity, credentials, private Telegram chat and SEC
contact identity will be collected by setup; no credentials are needed for
current offline development. Host/account MFA settings can only be ATTESTED,
never described as remotely verified.

UNVERIFIED: real paper `/v2/account` recording; current fixture is synthetic.
Command after keys: `python -m pytest -m integration` (integration tests pending D).
UNVERIFIED: mutation `python -m mutmut run`, PostgreSQL service tests and
`docker compose build`; local Windows prerequisites are absent, CI jobs pending.
No broker, bank, LLM, Telegram send or order action occurred in the audit.
