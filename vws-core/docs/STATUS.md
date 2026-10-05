# Technical status

Audit date: 2026-10-04 America/Chicago. The initial audit results below describe the pre-fix working
tree. The audit-fixes gate below certifies the current implementation. Amendments 01–04 supersede conflicts in the master and
earlier addenda. Execution order: audit/fixes → S → D → E → F → G → H → J → I → K.
Optional ideas require plain-words approval and live only in PROGRESS Suggestions.

Current work date: **2026-10-05 America/Chicago**. Stage S is in progress.
The Step 0 audit-fixes results are certified history; the combined Stage S gate,
fresh hash-lock installation and final current-source inventory are pending.

## Stage inventory

| Stage | Existing deliverable | Current amended status |
| --- | --- | --- |
| A | core config/money/clock/logging/database/ledger/state/guard; XNYS calendar; Stage_A.md | Original stage certified; configuration/guard corrections certified |
| B | frozen contracts, registry, CRO, risk boundary; Stage_B.md | Original certified; session daily-loss correction certified |
| C | compliance, wash matching, tax models, compliance boundary; Stage_C.md | Original certified; shared tax-core move reserved for J |
| D | data_layer/broker_state/liquidity/read boundary; indicators/scanner; Sandbox helper; six test modules | Original source tests pass; no final D delivery; DAT-05..12 missing |
| S | security/net/ops/Telegram admission/content/dependency services and host CLI | Focused fake gates passed; final combined gate pending; later pipeline wiring tracked below |
| E–K | Configuration/storage foundations and Stage S security services | Research swarm/bot handlers/evaluation/service startup/funding/P&L/tax/auto/extras not implemented |

Initial pre-fix inventory: 64 authored Python files, 39 production/script and 25 test-package files.
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
two-commit history, 2.19 MB, with no leaks after the audit-fixes commit.
The audit-fixes authored inventory was 70 Python files: 43 production/script and
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
attributes. A final blob comparison caught pre-existing Git newline normalization;
explicit renormalization now makes every specification and historical delivery
blob byte-identical to its saved source. An accidentally tracked generated coverage report is removed from
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
| Superseded floats/client/DROP plan | FUNDAMENTAL_ADDENDUM.md:20–30,46,50 | Mark superseded; use amended deterministic Decimal FA framework, default annotate |
| Duplicated schedule homes | .env.example:73–74; config.py:115–116,205–206,558–559; config.yaml:10–11 | YAML only; reject those env keys |
| Daily loss latches REDUCE_ONLY | system_state.py:87; risk_cro.py:134; data/boundary.py:104 | Session entry gate; next-open baseline rollover; drawdown/fault remains latched |
| Account type defaults to CASH | config.py:164 | Require explicit account type |
| Plaid token env/file source | liquidity.py:286–287 | Replace with keyring-only storage in S |
| SIP end lacks 16-minute clamp | data_layer.py:554,568 | DAT-07 in expanded D |
| Old scanner anchor definition | scanner.py:142 | Amend exact anchor definition for playbooks in E |

No response_format argument, hard-coded model, malformed Markdown URL,
development Plaid environment, import-time Settings, unauthorized wall clock,
production financial float, bare/swallowed exception, Decimal price truthiness,
non-PK seq autoincrement or deprecated Alpaca-field read was found. No callback
handler exists yet. `source_guard.py:53` split('_') normalizes identifiers only.
Order strings in execution_policy/test_no_order_exec are guard declarations and
positive controls, never executed. SentimentSignal.score (models.py:487–491) is
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
| R-07 | core/config.py; core/logging.py; security/secrets.py | test_config_safety.py; test_logging.py; test_secrets.py; test_security_cli.py | Stage S fake/CLI gates passed; native owner services UNVERIFIED |
| R-08 | data/broker_state.py; data/liquidity.py | test_broker_state.py; test_liquidity.py | Read-only runtime implemented |
| R-09 | core/system_state.py; risk/risk_cro.py; risk/compliance.py | test_risk_cro.py; test_compliance.py | Manual held exits implemented; AX-30 pending I |
| R-10 | core/source_guard.py; core/execution_policy.py | test_no_order_exec.py | Total ban implemented before I |
| R-11 | domain/models.py; agents/scanner.py | test_domain.py; test_scanner.py | Deterministic contracts/scanner only; LLM pending E |
| R-12 | core/config.py; domain/models.py; core/content.py | test_yaml_config.py; test_domain.py; test_content.py | Public-only sanitization/delimiters implemented; actual LLM/display composition pending E/F |
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
| GD-08 | — | — | Offline dry run missing |
| GD-09 | — | — | Docker missing |

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
SEC traceability below separates implemented Stage S components from pending
H/L prerequisites and later service composition. PG-01..04 page/CI checks implemented;
PG-05 CLI implemented and tested, Telegram pending F. WZ-01..10 wizard pending H.

## Owner choices and unverified checks

Defaults per Amendment 01 section 9: Alpaca paper, fundamentals annotate, LLM off,
20 liquid stocks + SPY + 11 sector ETFs (registry expansion pending), both Windows
and VPS instructions, no external tax accounts (show warning), no tax rates
(totals only). Account type/equity, credentials and private Telegram chat will be
collected by setup. The owner supplied a legitimate SEC contact separately;
its name/email are never copied into committed documentation. No credentials are needed for
current offline development. Host/account MFA settings can only be ATTESTED,
never described as remotely verified.

UNVERIFIED: real paper `/v2/account` recording; current fixture is synthetic.
Command after keys: `python -m pytest -m integration` (integration tests pending D).
UNVERIFIED: mutation `python -m mutmut run`, PostgreSQL service tests and
`docker compose build`; local Windows prerequisites are absent, CI jobs pending.
No broker, bank, LLM, Telegram send or order action occurred in the audit.

## Stage S verification - 2026-10-05

The full collected suite passed **2,535 tests** with two warnings: the pinned
SDK deprecation and a deliberate socket-blocked positive control. All risk,
state and tax contracts reached **100%**: 1,238 statements and 400 branches.
Elapsed time was 3,580.63 seconds, including the long turn interruption. The
final CLI suite separately passed **31 tests** after additional CLI cases were
added. These counts are not added together or claimed as a newer whole-suite
run. Current-source collection and final cross-platform lock/secrets gates are
completed below. The final collection contains 2,542 cases: the 2,535-case full
run plus seven added CLI cases. A final 42-case CLI/progress run passed, with
coverage appended to retain 100% across 1,238 statements and 400 branches.

| Gate | Actual evidence |
| --- | --- |
| `pytest -q backend/tests/test_backups.py backend/tests/test_anchors.py backend/tests/test_ops_security.py --cov=backend.ops --cov-branch --cov-fail-under=100` | PASS: 137 tests, 40.22s; 490 statements/114 branches, 100% |
| Ops Ruff lint/format, strict mypy, Bandit | PASS: 7 sources typed; 0 production Bandit findings |
| Keyring/permissions/redaction focused recovery gate | PASS: 138 reported tests; strict typing across 10 sources |
| Runtime/dev compiled locks | PASS: 60 runtime/121 dev hash-pinned records; all previous pins retained; Linux SecretStorage/jeepney closure included |
| Hash-enforced install into existing venv | PASS: final 121-record dev lock, --require-hashes --no-deps; pip check clean |
| Fresh hash-enforced Windows venv install and pip check | PASS: isolated fresh venv, final 121-record lock; authored editable source installed without dependency resolution |
| Whole-source Ruff lint/format and strict mypy | PASS: 91 formatted files, 97 strictly typed sources |
| Whole production Bandit and 121-record dev-lock pip-audit | PASS: zero findings and no known vulnerabilities; dev pins include every runtime pin |
| Collected full suite | PASS: 2,535 tests, two warnings; risk/state/contracts 100%, 1,238 statements/400 branches |
| Final expanded host CLI suite | PASS: 31 separate cases; seven later cases were not claimed in the earlier full-suite count |
| Final CLI/progress gate | PASS: 42 cases, 10.50s; appended coverage remains 100% |
| Authored-source guard and secrets scan | PASS: complete source guard; zero authored secret findings |
| Full-history Gitleaks 8.30.1 | PASS before stage commit: four commits, 2.34 MB, zero leaks |
| Native Windows ACL probe | PASS on a synthetic temporary file; owner's actual paths remain UNVERIFIED |
| Actual Git-root pre-commit run, all staged/authored files | PASS: all five hooks, including source guard, whole typing and secrets |

The backup/anchor readers explicitly decode ISO timestamps before frozen UTC
schema validation; raw JSON strings cannot bypass aware-time validation. Fernet
ciphertext must use canonical base64, its authenticated inner header must match
the outer header, and plaintext length/SHA-256 must match. Restore uses private
temporary files and verifies all chains. A successful anchor check appends
ANCHOR_VERIFIED. Anchors hash all globally ordered `(seq, table, row_hash)` rows,
so an independently saved prefix detects even a recomputed local table chain.

Panic persists HALTED before every callback and keeps the offline revoke result
after callback/audit failures. MANUAL never invokes cancellation or imports an
executor. AUTO cancellation remains an injected interface until Stage I.
Config drift remains paused through a revert until a host apply/ack event.
An unexplained fingerprint change persists HALT and BROKER_IDENTITY_CHANGED;
only later matching SECRET_ROTATED evidence authorizes rotation.

## Security traceability

Paths below are relative to backend/ unless explicitly prefixed with vws/docs.
Service-level fake acceptance is distinct from real host/provider verification.

| ID / placement | Implementation | Tests / evidence | Remaining integration or verification |
| --- | --- | --- | --- |
| SEC-01 S | ops/security.py AccountAttestation/SecurityOps; vws/security_cli.py doctor/attest; README checklist | test_ops_security.py ten dated items; test_security_cli.py host dispatch | Third-party settings owner-ATTESTED only; never remote PASS |
| SEC-02 S | core/execution_policy.py/source_guard.py money bans; doctor key-prefix hint | test_no_order_exec.py retired fields/wallet endpoints | Trading API scopes and IP allowlisting UNVERIFIED; prefix not authoritative |
| SEC-10 L | security/secrets.py assert_secret_sources; vws/security_cli.py open_context | test_secrets.py env/dotenv refusal; test_security_cli.py explicit context | Full AUTO_LIVE prerequisite composition pending I |
| SEC-11 S | security/secrets.py native SecretStore/plaid_access_token; data/liquidity.py; sandbox helper | test_secrets.py; test_liquidity.py | Real Credential Manager/Secret Service and Plaid calls UNVERIFIED |
| SEC-12 S | security/permissions.py check_permissions; doctor | test_permissions.py; test_security_cli.py pre-connect refusal; native synthetic ACL read | Owner ACL/ownership UNVERIFIED; unknown never PASS |
| SEC-13 S | security/secrets.py RotationService; host hidden-input rotate_secret | test_secrets.py rollback/HMAC/age; test_security_cli.py provider reads/mode binding | Connected provider validation/account binding UNVERIFIED; status/report composition later |
| SEC-14 S | core/logging.py redaction/logger levels; typed redacted errors | test_logging.py; test_secrets.py; test_security_cli.py secret-free errors | Real provider error paths UNVERIFIED |
| SEC-15 S | native backup key; ops/backups.py show_key_once; ignore/hooks/history scan | test_backups.py; four-commit full-history scan, zero leaks | CI written but unrun; owner recovery-key export not run |
| SEC-20 S | requirements.lock/requirements-dev.lock; scripts/compile_locks.py; core/dependencies.py | test_dependencies.py; existing/fresh Windows hash installs; Linux metadata closure | Actual Linux native backend UNVERIFIED |
| SEC-21 S | docs/DEPENDENCIES.md; core/dependencies.py | test_dependencies.py declared/unlisted controls, 9 passed | No undocumented direct dependency |
| SEC-22 H | Lock audit foundation | Final 121-pin dev lock audited clean, includes all runtime pins | Weekly workflow and doctor audit evidence pending H |
| SEC-23 H | No SBOM job certified | UNVERIFIED | CycloneDX flags/job/artifact pending H |
| SEC-24 H | Least-privilege CI foundation | Final workflow gate pending | Full SHA-pinned action acceptance and remote CI UNVERIFIED |
| SEC-30 S | net/http.py make_client; guarded HTTP SDK transport; AST factory rule | test_egress.py deadlines/redirect controls; test_security_source_guard.py | Fake gates passed; connected HTTP UNVERIFIED |
| SEC-31 S | net/egress.py build_allowlist/EgressPolicy; startup composition | test_egress.py denied host/IP/scheme and EGRESS_DENIED evidence | RSS/provider grants wired with D/E/F; real network UNVERIFIED |
| SEC-32 S | net/egress.py SDKSocketGuard controlled DNS/connect | test_egress.py planted and actual Python audit-event controls | Guard is defense against accidental bypass, not malicious-code sandbox |
| SEC-33 S | source_guard.py TLS rules; doctor CA-env WARN | test_security_source_guard.py positive controls | Real host CA override inspection UNVERIFIED |
| SEC-34 S | no-bind guard; telegram/security.py bot_security_findings; doctor | test_egress.py; test_telegram_security.py webhook refusal | Bot startup/getWebhookInfo wiring F; real bot state UNVERIFIED |
| SEC-35 H | No Docker deployment certified | UNVERIFIED | Digest/non-root/readonly/no-ports compose gate pending H |
| SEC-40 S | ops/backups.py BackupService encrypted SQLite .vwsbak and restore_test | test_backups.py roundtrip/bit flip/key/digest/chain/private scratch | Real ledger/keyring backup UNVERIFIED; scheduled/PG tooling H |
| SEC-41 H | Host runbook recommendation | UNVERIFIED | Disk encryption probes/attestation fallback pending H |
| SEC-42 S | ops/anchors.py LedgerAnchors full global prefix/verify_file | test_anchors.py table-chain rewrite/offbox prefix/date evidence | Evening digest and weekly report wiring F/G; owner old anchor unavailable |
| SEC-43 S | ops/security.py effective_config_hash/ConfigDriftGuard; host apply/ack | test_ops_security.py four-file hashes/latching drift | Monitor-cycle urgent notification/entry pause composition F/I |
| SEC-50 S | telegram/security.py bot_security_findings; doctor; RUNBOOK BotFather steps | test_telegram_security.py; test_security_cli.py warning/no false PASS | Real getMe settings UNVERIFIED; AUTO_LIVE composition I |
| SEC-51 S | telegram/security.py TelegramSecurity admission/leave boundary | test_telegram_security.py groups/channels/no handling | Runtime handler long-poll composition F |
| SEC-52 S | TelegramSecurity stranger history and normal/heavy buckets | test_telegram_security.py notice/urgent/21st/heavy/emergency controls | Runtime command handlers F; username ephemeral, numeric IDs retained |
| SEC-53 S | telegram/security.py mask_account_fields | test_telegram_security.py golden masked fields | Card/P&L/tax rendering F/J; CLI/report unaffected |
| SEC-54 S | RUNBOOK.md token rotation; README secure accounts | Hidden-input rotation services tested | Owner BotFather revoke/getMe path UNVERIFIED |
| SEC-60 S | core/content.py sanitize_text; configured max-token boundary | test_content.py cap/URL/markup/control/zero-width/bidi controls | Actual per-call max_tokens enforcement E |
| SEC-61 S | core/content.py public_llm_payload; source guard tool ban | test_content.py public allowlist/account-data controls; source positives | Actual provider payload integration E |
| SEC-62 S | core/content.py injection_suspect/prepare_headline | test_content.py suspect event/bare headline/no summary | News ingestion and optional summary composition D/E |
| SEC-70 H | RUNBOOK.md Windows/VPS host instructions | Operational documentation only | Host settings owner checks pending; no remote setting PASS |
| SEC-71 H | Doctor security foundation | UNVERIFIED | Admin/root/SSH/upgrades/Defender/firewall probes pending H |
| SEC-72 S | ops/security.py counts/observe_identity; immutable security events | test_ops_security.py changed/stale/matching proof and HALT | Weekly new-ID/secret-age/last-check composition G; account emails owner verification |
| SEC-73 S | ops/security.py panic; vws host command | test_ops_security.py; test_security_cli.py corrupt-chain local HALT | Entry-job shutdown F; actual cancellation/protection and activity composition I |
| SEC-74 S | docs/INCIDENT.md one-page variants | Documentation matches current --file restore syntax | Owner recovery on clean host UNVERIFIED |
| SEC-75 S | core/logging.py daily retention; numeric-ID/no username records; balance-only Plaid | test_logging.py; test_telegram_security.py; test_liquidity.py | Real log-retention/backup operation UNVERIFIED; permanent evidence/no telemetry policy retained |

PG-01..04: docs/PROGRESS.md is rewritten for October 5, 2026, within 60 lines,
with seven exact ordered owner sections followed by Suggestions. PG-05 terminal
read/access helpers are tested; allowlisted heavy-limited `/progress` composition
is pending F. WZ-01..10 remain Stage H work. README labels setup/start flow as
forthcoming rather than falsely claiming those commands exist today.

## Stage S UNVERIFIED and reproduction

No owner secrets, real keyring entries, broker orders, bank transfer or Telegram
messages were used in fake gates. From an activated venv in vws-core:

```text
python -m pytest -q backend/tests/test_secrets.py backend/tests/test_permissions.py backend/tests/test_logging.py
python -m pytest -q backend/tests/test_egress.py backend/tests/test_security_source_guard.py backend/tests/test_telegram_security.py backend/tests/test_content.py backend/tests/test_dependencies.py
python -m pytest -q backend/tests/test_backups.py backend/tests/test_anchors.py backend/tests/test_ops_security.py --cov=backend.ops --cov-branch --cov-fail-under=100
python -m vws --env-file .env doctor
python -m vws --env-file .env ops backup
python -m vws --env-file .env ops restore-test --file PATH.vwsbak
python -m vws --env-file .env ledger verify-anchor --seq N --hash HASH
python -m mutmut run
docker compose build
```

Connected commands require owner configuration; real keyring/provider/ACL facts
remain UNVERIFIED. Mutation requires its supported platform. Docker compose and
PostgreSQL server runtime jobs remain pending their stage/prerequisites; a build
command is not represented as working before the Docker files exist.
For a disposable PostgreSQL database with its driver installed and URL supplied,
the exact schema/chain smoke is:

```text
python -c "import os; from backend.core.clock import SystemClock; from backend.core.database import create_database,create_schema; from backend.core.ledger import Ledger; e=create_database(os.environ['VWS_POSTGRES_TEST_URL']); create_schema(e); Ledger(e,SystemClock()).verify_chain(); e.dispose()"
```

Use only a fresh isolated test database, never a production URL. This command
checks schema/chain runtime; it does not certify PostgreSQL concurrency, which
still needs the specified CI service suite. No remote workflow run is claimed.
