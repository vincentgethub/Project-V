# Stage I GREEN OFFLINE - 2026-10-09

The full offline run passed 4,503 cases, skipped 58, deselected one perf case
and emitted two warnings in 1,102.35s. A later three-file reporting/notification
fix passed all 314 affected cases (438.53s), including nine new cases:
4,512 distinct safety passes plus the fixed replay. Required coverage was rebuilt
for those changed files and is 100% (5,302 statements / 1,714 branches). This is
an explicit evidence union; the full run predates that small fix. The fixed
20-symbol/seven-year replay passed in 86.479s timed, with 443 identical decisions.
Ruff, strict typing, the whole AST guard, Bandit, pinned dependency audits, SBOMs
and wheel build passed. Execution is restricted to the sole
Alpaca executor; MANUAL defaults to paper and never imports it. No real service,
secret, owner database or actual order was used. Real integration remains
UNVERIFIED, including Amendment 02 acceptance 11.1 item 15's one-share far-price
paper bracket submit/cancel, leg verification and reconciliation. The existing
opt-in paper test verifies read-only account/SIP data; it does not certify orders.
The specified integration item explicitly permits UNVERIFIED when unavailable.

From vws-core (PowerShell), final offline/replay commands:
```powershell
.venv\Scripts\python.exe -m pytest -q -m 'not perf' --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov=backend.evaluation --cov-branch --cov-fail-under=100 --cov-report=term-missing
.venv\Scripts\python.exe -m pytest backend/tests/test_replay_cli.py -q -m perf
.venv\Scripts\python.exe -m backend.core.check_stage_d
.venv\Scripts\python.exe -m backend.core.source_guard .
.venv\Scripts\python.exe -m vws setup
.venv\Scripts\python.exe -m vws doctor
```
Only an explicit integration configuration can open native paper credentials:
```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_paper_integration.py -q -m integration --paper-integration-env-file C:\PRIVATE\paper.env
```
That file contains public MANUAL/paper settings, never keys. Set paper secrets
only through setup/native keyring. This read-only command is not the unverified
order probe. No real order probe was run; AUTO_LIVE remains locked.

Linux CI mutation reproduction (new targets include executor, modes, ceilings):
```sh
python -m pip install --require-hashes --no-deps -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m mutmut run
python -m mutmut results --all > /tmp/vws-mutants.txt
python -m scripts.check_mutations /tmp/vws-mutants.txt
```
Windows lacks mutmut's POSIX fork; no score is claimed. Root/project CI mirrors
include these targets and execution security scanning. Remote CI has not run;
the owner forbids a push. Existing PostgreSQL/Docker reproduction commands below
remain applicable, without implying a pass or access to owner resources.

# Stage J GREEN OFFLINE with owner deferral - 2026-10-08

Final frozen-code gate: **4,266 passed, 52 skipped, one perf deselected, two
warnings, 1,114.23s**, exit zero. Required coverage: **100%, 5,244 statements /
1,684 branches, zero missing/partial**. Skips are 51 explicit PostgreSQL checks
and one explicit-key paper integration, never passes. Warnings: pinned SDK
deprecation and deliberate blocked-socket positive control. Fixed replay:
**one PASS, four deselected, 102.44s overall; 75.600s timed, 443 decisions**.
SHA256: `783fe52c18b79f3921628abed5dd05d3969af0549c15347e7a256a684ad1226d`.
Distinct available passes including replay: **4,267**, without adding focused
counts. Focused deferral union: **468 PASS, 87.84s, 1,403 statements / 440 branches,
100%**. Ruff/format (301), strict types (283), AST, pip check and all five local
pre-commit hooks PASS. Production Bandit: zero findings/errors, 35,820 lines,
13 reviewed skips. CI mirrors identical; six supply-chain cases PASS.

Owner Oct 8 decision: ALPACA primary state/funding only. MANUAL_CSV refuses at
startup, doctor, constructors and direct methods before filesystem/provider
access; cached accounting contexts cannot bypass it. No host evidence file was
built. Amendment 02 §11.2 item 1 / DAT-12 / FN-02 manual acceptance is **DEFERRED
(user decision, Oct 8 2026)**, retained for FINAL_REPORT. Other-account tax CSV
imports remain explicit inputs, never primary state/funding.

Historical failed gates are retained in STATUS.md. The earlier 4,321-case gate
predates the deferral and is superseded. The narrow 95-test selection passed
cases but failed its 98.61% service coverage gate; the final wider selection
includes the existing missing branches. No failed gate is called PASS.
Owner DB, dotenv, keyring and account services were not opened. No order code
exists before Stage I. Real services and platform checks remain UNVERIFIED.

From the activated vws-core environment, reproduce:

```text
python -m pytest -q --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov=backend.evaluation --cov-branch --cov-fail-under=100 --cov-report=term-missing -m "not perf"
python -m pytest -q backend/tests/test_tax_accounting.py backend/tests/test_tax_reports.py backend/tests/test_wash_sales.py backend/tests/test_compliance.py backend/tests/test_tax_profile.py backend/tests/test_tax_tracker.py backend/tests/test_funding_and_pnl.py backend/tests/test_accounting_service.py backend/tests/test_tax_guards.py backend/tests/test_tax_cli.py backend/tests/test_manual_broker.py backend/tests/test_doctor.py --cov=backend.tax --cov=backend.domain.compliance_models --cov-branch --cov-fail-under=100 --cov-report=term-missing
python -m pytest -q -s backend/tests/test_replay_cli.py -m perf
python -m bandit -r backend/core backend/domain backend/risk backend/data backend/agents backend/net backend/ops backend/security backend/telegram backend/notifications backend/tax backend/funding backend/pnl backend/evaluation backend/indicators scripts vws -c pyproject.toml -f json -o data/j-bandit-production.json
```

Temporary databases, fake transports and disabled sockets only; real dotenv is
never selected implicitly. Mutation targets include shared tax/lots, holding
period and netting in pyproject.toml. POSIX mutation, PostgreSQL, Docker, real
paper integration and remote CI remain UNVERIFIED; exact platform reproduction
commands are retained below. Stage I starts after J's local commit.

# Stage H verified offline - 2026-10-08

The final cumulative offline safety gate passed **4,080 tests, 46 skipped,
one perf deselected, two warnings, 1,001.32s**. Required state/risk/contracts,
fundamentals, notifications, tax and evaluation coverage is **100%: 4,168
statements / 1,346 branches, zero missing/partial**. H is GREEN OFFLINE.
The first attempt passed 3,974 cases but failed required coverage (99.97%);
the missing callback branch and connected quote timing have been addressed.
The subsequent targeted gate passed eight cases. A later 3,978-case gate passed
but omitted the required evaluation scope; it was not H certification. The
final full command below corrects that omission. Its 46 unavailable cases are 45 PostgreSQL
checks and one explicit-key paper integration, never counted as passes.
Latest static evidence: 257 strictly typed sources, full AST guard PASS, pip
check PASS and production Bandit zero findings (32,194 lines, 12 explicitly
reviewed skips). Both real JSON lock audits matched every selected pin: 62
runtime and 141 development, with no skips or known vulnerabilities. Generated
CycloneDX inventories match those locks; the actual CLI accepts the tested flags.
Amendment 01 section 7 also requires the complete evaluation package. Earlier
coverage commands omitted it; the final H command below includes that scope.
The fresh focused evaluation gate passed 364 tests, one perf case deselected,
one SDK warning, 169.20s; 1,951 statements and 628 branches, 100%, no exclusions.
Full-history Gitleaks 8.30.1: ten commits, 26.44MB, zero leaks. Authored-source
secret scan: zero findings. These checks touched no owner DB, dotenv or keyring.

Separate current fixed 20-symbol/seven-year replay: **1 PASS, 4 deselected,
133.74s overall; replay 97.666s, 443 decisions**, three workers plus parent.
SHA: `783fe52c18b79f3921628abed5dd05d3969af0549c15347e7a256a684ad1226d`.
The four other replay CLI cases belong to the full non-perf gate; do not sum them.

Focused history is retained in STATUS.md, including failed attempts and genuine
fixes. The same cumulative coverage command below is H's required final gate.
To check the implemented host components independently:

```text
python -m pytest -q --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov=backend.evaluation --cov-branch --cov-fail-under=100 --cov-report=term-missing -m "not perf"
python -m pytest -q backend/tests/test_host_runtime.py backend/tests/test_process_health.py backend/tests/test_security_cli.py backend/tests/test_scheduler.py backend/tests/test_desk_jobs.py
python -m pytest -q backend/tests/test_setup_wizard.py backend/tests/test_host_config.py backend/tests/test_doctor.py backend/tests/test_read_checks.py backend/tests/test_broker_clock.py backend/tests/test_host_probes.py
python -m pytest -q backend/tests/test_native_ipc.py backend/tests/test_secrets.py backend/tests/test_egress.py
python -m pytest -q backend/tests/test_migrations.py backend/tests/test_backups.py backend/tests/test_watchdog_maintenance.py backend/tests/test_job_health.py
python -m pytest -q backend/tests/test_supply_chain_h.py backend/tests/test_dependency_audit.py backend/tests/test_account_context.py backend/tests/test_logging.py
python -m cyclonedx_py requirements requirements.lock --output-format JSON --output-file build/sbom/runtime.json
python -m cyclonedx_py requirements requirements-dev.lock --output-format JSON --output-file build/sbom/development.json
```

After owner setup, use `python -m vws doctor`, then `python -m vws start` for
MANUAL paper. `python -m vws --healthcheck` inspects only the heartbeat and OS
lock and never reads credentials or storage. Migration is explicit:
`python -m vws ops migrate --operator NAME`; it backs up before additive DDL.
Host audit evidence is produced with `python -m vws ops audit-dependencies
--operator NAME`, never by asserting a CI success on this machine.

Actual owner services, host protections/native stores/backup, Linux runtime,
remote CI, PostgreSQL and Docker remain UNVERIFIED. Supported Linux CI gates
are present at the actual Git root and mirrored under vws-core. Local Windows
reproduction uses a disposable database or synthetic configuration only:

```text
python -m pytest -q backend/tests/test_postgres.py --postgres-test-url postgresql+psycopg://vws_ci:CI_FIXTURE_ONLY@127.0.0.1:5432/vws_ci # pragma: allowlist secret - public disposable CI fixture
python -m mutmut run
python -m mutmut results > build/mutmut-results.txt
python -m scripts.check_mutations build/mutmut-results.txt
docker compose build
python -m pytest -q backend/tests/test_paper_integration.py --paper-integration-env-file PATH_TO_PRIVATE_PAPER_CONFIG
```

Do not use an owner database as the disposable target. Native secret storage is
mandatory; the restricted Docker mounts do not expose the host store and the
container refuses connected startup. No fallback or secret environment file is
provided. The Linux unit requires an available unlocked user Secret Service and
the exact owned user bus. Reviewed references: [systemd execution settings](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml),
[Microsoft Task Scheduler contexts](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks),
[CycloneDX usage](https://cyclonedx-bom-tool.readthedocs.io/en/v7.5.0/usage.html).
Systemd's read-only home/runtime-user view preserves native IPC visibility;
actual Linux startup is still unverified. No service or scheduled task was installed.

# Stage G/G+ verification - 2026-10-07

The final cumulative non-perf offline gate passed **3,709 tests, 44 skipped,
one perf case deselected, two warnings, 835.06s**. Required safety coverage is
**100%: 2,202 statements and 716 branches, zero missing/partial**. The excluded
fixed 20-symbol/seven-year replay passed separately: **1 PASS, 4 deselected,
115.23s overall, timed replay 88.411s, 443 decisions**, three workers plus parent.
The four deselected cases are already in the cumulative gate; do not add them.
Proof SHA: `d81cb662aa155344891c91e4911c2fbe7841f6137aecdc74cc7523f19cb8919c`.
The first expanded run failed six fill cases because the matcher still required
ALL-adjusted evidence. It now requires SPLIT; the final rerun also proves that
ALL-only evidence fails closed. No failed run is counted as PASS.

Static gates passed: Ruff 231 files; strict mypy 213 authored sources; full
execution/source-write guard; production Bandit zero findings, 27,856 lines,
eight explicit skips. All five actual Git-root hooks passed. Authored secret
findings zero; nine-commit/25.96MB Git-history scan zero leaks; pip check and
unchanged 123-pin development lock audit clean. Real services, owner keyring/
host/backups, PostgreSQL, Docker/runtime, POSIX mutation and remote CI remain
UNVERIFIED. Exact service/platform reproduction commands follow in the retained
Stage F section. The FRED key and SEC contact are entered only through setup.

From an activated venv in vws-core, reproduce the G gates:

```text
python -m ruff check .
python -m ruff format --check .
python -m backend.core.check_stage_d
python -m backend.core.source_guard .
python -m bandit -r backend/core backend/domain backend/risk backend/data backend/agents backend/net backend/ops backend/security backend/telegram backend/notifications backend/tax backend/evaluation backend/indicators scripts vws -c pyproject.toml
python -m pip check
python -m pip_audit -r requirements-dev.lock --no-deps --disable-pip --progress-spinner off --timeout 15
python -m pytest -q --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov-branch --cov-fail-under=100 --cov-report=term-missing -m "not perf"
python -m pytest -q -s backend/tests/test_replay_cli.py -m perf
python -m vws progress
```

Only test fixtures and in-memory/disposable ledgers were used; no owner DB,
dotenv, native credential, chat or broker was opened. No order execution or
money movement exists. Connected runtime remains H; DQ-02/remaining PF, registered
validation and readiness remain V; realtime health remains W.

# Stage F verification - 2026-10-07

The full cumulative offline gate passed **3,366 tests, 44 skipped, 2 warnings**
in **739.93 seconds**. Required coverage is **100%: 2,202 statements and 716
branches, zero missing/partial** across risk/state/compliance contracts/
fundamentals/notifications/tax. All five actual Git-root hooks passed.
Actual static checks: 178 files formatted, 162 strictly typed authored sources,
production Bandit zero findings, full AST guard PASS, hash-lock install and
pip check PASS. The 123-pin development lock audit found no known vulnerabilities.
Gitleaks scanned eight prior commits/25.65MB with zero leaks. The synthetic NVDA
preview passed: one card, zero LLM calls, verified RAM ledger, no send or order.
Authored secret findings are zero. The only inline secret allowlist additions
identify the public disposable CI fixture password at its example lines.

Reproduce the complete local gate from an activated venv in vws-core:

```text
python -m ruff check .
python -m ruff format --check .
python -m backend.core.check_stage_d
python -m backend.core.source_guard .
python -m bandit -r backend/core backend/domain backend/risk backend/data backend/agents backend/net backend/ops backend/security backend/telegram backend/notifications backend/tax scripts vws -c pyproject.toml
python -m pip check
python -m pip_audit -r requirements-dev.lock --no-deps --disable-pip --progress-spinner off --timeout 15
python -m pytest -q --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov-branch --cov-fail-under=100 --cov-report=term-missing
python scripts/dry_run.py --dry-run NVDA --offline
```

On Windows, set `$env:PYTHONIOENCODING = 'utf-8'` before the strict mypy wrapper.
Unit tests block sockets and isolate application variables; they never discover
real dotenv or keyring values. Private Telegram flow uses actual PTB 22.8 SDK
calls through MockTransport. No real chat has been contacted or admitted.

**UNVERIFIED**: POSIX mutation testing (Windows has no fork), real PostgreSQL,
Docker build/runtime, remote CI, paper/Plaid/Telegram/optional LLM connections,
owner keyring/host attestations and real encrypted backups. Forty-three PG
cases skip unless an explicit disposable loopback URL is supplied. The real
paper check separately requires explicit credentials. Never count skips as PASS.

Linux CI now schedules separate mutation/PG jobs and a synthetic container build.
Actions and official Python/PostgreSQL images use verified SHA/digest pins.
CI has not run remotely, and no push is authorized. Exact reproduction:

```text
python -m mutmut run
python -m mutmut results --all > /tmp/vws-mutants.txt
python -m scripts.check_mutations /tmp/vws-mutants.txt
python -m pytest -q backend/tests/test_postgres.py --postgres-test-url 'postgresql+psycopg://vws_ci:CI_FIXTURE_ONLY@127.0.0.1:5432/vws_ci' # pragma: allowlist secret - public disposable CI fixture
python -m pytest -m integration --paper-integration-env-file PRIVATE_PAPER_CONFIG
```

PG requires a disposable PostgreSQL 16 database/user named `vws_ci`; CI_FIXTURE_ONLY
is a public test password. The tests isolate generated schemas and cannot accept
an owner database URL. For Docker in a disposable checkout only, copy
`.env.example` to `.env`, then `docker compose build`. There are no application
ports; the optional PG production profile also exposes no ports. Its secret
password file must be deliberately supplied. Connected startup and healthcheck
CLI composition await Stage H, so a build will not certify running service health.

Read-only fill polling uses documented [Trading API account activities](https://docs.alpaca.markets/us/reference/getaccountactivities-2),
not an invented SDK method. Installed TradingClient 0.44.0 has no activity reader.
The central HTTPS adapter binds account/key/endpoint, disables redirects, bounds
response size and pages, and accepts only whole-share/cent-price observed fills.
The pinned PTB request boundary follows [BaseRequest](https://docs.python-telegram-bot.org/en/latest/telegram.request.baserequest.html).
These contracts are verified offline; actual account entitlements remain unchecked.

# Stage D verification - 2026-10-05

The final whole-suite Stage D gate passed 2,901 cases in 404.77 seconds, with
one paper integration skipped and two warnings. Risk/state/contracts reached
100% across 1,253 statements and 402 branches. The results below are actual
focused/static checks; they are not added to the whole-suite count.
Historical audit-fixes and Stage S counts remain preserved below.

| Check | Actual evidence |
| --- | --- |
| Final whole suite and risk/state/contract coverage | 2,901 passed, 1 skipped, 2 warnings; 100% of 1,253 statements/402 branches |
| Async reader, batch/cache, indicator memo and legacy data | 161 focused cases passed: 38 new and 123 legacy |
| News and corporate actions | 132 focused cases passed: 78 news and 54 corporate actions |
| Earnings and manual CSV | 111 focused cases passed |
| Scanner with injected indicator memo | 27 cases passed; final scanner/indicator regression gate 87 passed |
| Earnings risk and SEC header configuration | 25 cases passed |
| Selected risk/state/contracts coverage | 644 cases passed; 1,253 statements/402 branches, 100% |
| Prior-schema emergency panic compatibility | Four cases passed; old version retained, normal startup refused |
| Whole Ruff lint/format and strict mypy | PASS: 112 formatted files and 112 strictly typed sources |
| Source guard, production Bandit and source secrets | PASS: zero findings |
| Dev lock audit and pip check | PASS: unchanged 121 exact pins, no known vulnerabilities or broken requirements |
| Actual Git-root pre-commit hooks | All five passed |
| Real paper integration | UNVERIFIED: explicit credentials absent; one test skipped |

The 50-symbol warm-scan fixture includes benchmark ETFs and makes one physical
bar GET for the new session, within the specified ten-call maximum. A repeat
scan makes no new GET. SDK pagination is charged per physical request; the plan
budgets are 180/min and 9,000/min. IEX quotes reuse the completed batch for ADV20.
Timeout slots remain occupied until the worker stops; late portfolio/bar data
cannot become stored evidence. Database reads/writes also use bounded workers.

Installed alpaca-py 0.44.0 signatures and raw mappings are exercised by synthetic
SDK tests. Public SDK prose still says raw_data is unimplemented in places;
the installed code and fixtures verify this pinned version's actual behavior.
This does not verify a real paper account or subscription entitlement.

| Contract | Primary source and exact verified use |
| --- | --- |
| Multi-symbol daily bars and pagination | [Alpaca stock bars](https://docs.alpaca.markets/us/reference/stockbars); pinned get_stock_bars, explicit SIP/ALL, repeated GET /v2/stocks/bars |
| Latest quotes/trades | [Stock data SDK](https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html), [latest quotes](https://docs.alpaca.markets/us/reference/stocklatestquotes-1), [latest trades](https://docs.alpaca.markets/us/reference/stocklatesttrades-1); explicit IEX |
| Default news | [Alpaca news](https://docs.alpaca.markets/us/reference/news-3); pinned NewsClient.get_news(NewsRequest), GET /v1beta1/news, comma-separated symbols |
| Corporate actions | [Alpaca actions](https://docs.alpaca.markets/us/reference/corporateactions-1), [SDK client](https://alpaca.markets/sdks/python/api_reference/data/corporate_actions/historical.html); submodule import, GET /v1/corporate-actions, process-date bounds distinct from effective/ex dates |
| Opt-in NewsAPI | [Everything endpoint](https://newsapi.org/docs/endpoints/everything); explicit paid-terms attestation and key required, actual entitlement UNVERIFIED |

News dedupe keeps immutable canonical rows while repeated suspicious input
still receives hash-only injection evidence. Earnings precedence is manual
calendar, optional provider, SEC filing-window estimate. Confirmed dates block
nearby entries; estimated/unknown dates WARN. Manual CSV needs fresh prices,
account restrictions and pending-order evidence; missing proof never passes.

The added nineteenth ledger table uses schema version 3. Existing version 2
requires Stage H's explicit backed-up additive migration. Emergency host panic
can halt on the exact compatible prior schema without upgrading/certifying it.
Unknown versions and incompatible control inventories refuse.

The first whole-suite attempt found one Decimal-context regression in cached
indicator validation (2,900 passed, one failed, one skipped). The fix uses an
explicit precision; all 87 scanner/indicator cases and the full rerun passed.
The warnings are the pinned SDK deprecation and a deliberate socket-blocking
positive control. No failed run is labeled PASS.

Reproduction from an activated venv in vws-core:

```text
python -m pytest -q --cov --cov-branch --cov-report=term-missing --cov-fail-under=100
python -m backend.core.check_stage_d
python -m backend.core.source_guard .
python -m pytest -m integration --paper-integration-env-file PRIVATE_PAPER_CONFIG
python -m mutmut run
docker compose build
```

The integration configuration is read only when explicitly selected; normal
tests do not read real dotenv files or native keyring secrets. It reads account
and safely delayed SIP bars without submitting orders. Real paper/news/action
services, NewsAPI paid terms, mutation/PostgreSQL/Docker and remote CI remain
UNVERIFIED. PostgreSQL reproduction is detailed in docs/STATUS.md; its service
acceptance and the deployment/mutation jobs are completed in Stage H.

# Stage S verification - 2026-10-05

Stage S offline gates passed. Actual remote services and CI remain UNVERIFIED.
Historical audit-fixes and A-C delivery results below remain unchanged.

| Focused check | Actual observed/reported result |
| --- | --- |
| Ops security, backups and anchors | 137 passed in 40.22s; 100% of 490 statements/114 branches |
| Ops Ruff lint/format and strict mypy | PASS, 7 sources typed |
| Ops Bandit | PASS, zero production findings |
| Keyring/permissions/redaction recovery gate | 138 reported tests and 10 strictly typed sources passed |
| Runtime/dev hash-lock compilation | PASS: 60 runtime/121 dev records, original pins retained; Linux keyring dependencies and pinned setuptools included |
| Hash-enforced existing-venv install | PASS: final dev lock, --require-hashes --no-deps; pip check clean |
| Fresh hash-enforced Windows dev install/pip check | PASS: final dev lock and authored editable source, no dependency resolution |
| Whole-source Ruff lint/format and strict mypy | PASS: 91 formatted files and 97 typed sources |
| Whole production Bandit and dev-lock audit | PASS: zero findings; 121 packages with no known vulnerabilities |
| Collected full suite | PASS: 2,535 tests, two warnings; 1,238 risk/state/contract statements and 400 branches, 100% |
| Final expanded CLI suite | PASS: 31 separate cases, including seven added after the earlier whole-suite collection |
| Final CLI/progress regression gate | PASS: 42 cases; appended coverage remains 100% |
| Final current collection | 2,542 cases; seven added CLI cases covered by the final regression gate |
| Whole authored-source guard and secrets scan | PASS; zero source secret findings |
| Full-history Gitleaks 8.30.1 | PASS before stage commit: 4 commits, 2.34 MB, zero leaks |
| Native Windows ACL read | PASS on synthetic temporary file; owner paths UNVERIFIED |
| Actual Git-root pre-commit run | PASS: all five hooks on all files |

Fakes exercise keyring selection/rollback, immutable HMAC rotation evidence,
90-day age warnings, POSIX and Windows ACL policy, URL/header/traceback
redaction, encrypted backup corruption, off-box prefix verification, config
drift, identity changes and offline panic. A fake test cannot verify the owner's
actual keyring, permissions, MFA or remote account.

Current Stage S contracts and source references:

| Contract | Primary reference | Verification scope |
| --- | --- | --- |
| Fernet authenticated encryption | [cryptography Fernet API](https://cryptography.io/en/stable/fernet/) | Installed encrypt/decrypt tests; key/byte/header/digest failures; actual owner backup UNVERIFIED |
| Consistent SQLite backup and serialization | [Python 3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup) | Pinned Python online-backup/serialize fixtures; PostgreSQL tooling not guessed |
| Native Windows keyring and local-machine persistence | [keyring 25.7.0 Windows backend](https://github.com/jaraco/keyring/blob/v25.7.0/keyring/backends/Windows.py) | Explicit native class chosen in fake tests; real Credential Manager UNVERIFIED |
| Native Linux Secret Service | [keyring 25.7.0 Secret Service](https://github.com/jaraco/keyring/blob/v25.7.0/keyring/backends/SecretService.py) | Backend fakes and transitive lock closure verified; native session UNVERIFIED |
| Read-only Windows ACL inspection | [Microsoft icacls](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls) | Mocked broad-group/UNKNOWN/world-write controls; real host ACL results UNVERIFIED |
| Python DNS/connect audit events | [Python 3.12 audit events](https://docs.python.org/3.12/library/audit_events.html) | socket.getaddrinfo/socket.connect fake and isolated subprocess controls; not a malicious-code sandbox |
| Audit-hook trust boundary | [Python sys.addaudithook](https://docs.python.org/3.12/library/sys.html#sys.addaudithook) | Guard supplements hostname/TLS checks; no OS-sandbox claim |
| Compiled package hashes | [pip-tools hash generation](https://pip-tools.readthedocs.io/en/stable/#using-hashes) | Final runtime/dev locks, hash parser, fresh Windows install and 121-pin audit passed |

Reproduction uses the activated venv in vws-core:

```text
python -m pytest -q backend/tests/test_backups.py backend/tests/test_anchors.py backend/tests/test_ops_security.py --cov=backend.ops --cov-branch --cov-fail-under=100
python -m pytest -q backend/tests/test_secrets.py backend/tests/test_permissions.py backend/tests/test_logging.py
python -m pytest -q backend/tests/test_egress.py backend/tests/test_security_source_guard.py backend/tests/test_telegram_security.py backend/tests/test_content.py backend/tests/test_dependencies.py
python -m mypy --strict
python -m backend.core.source_guard .
python -m pip install --require-hashes --no-deps -r requirements.lock
python -m pip install --require-hashes --no-deps -r requirements-dev.lock
python -m pip_audit -r requirements.lock --no-deps --disable-pip --progress-spinner off --timeout 15
python -m pip_audit -r requirements-dev.lock --no-deps --disable-pip --progress-spinner off --timeout 15
```

UNVERIFIED: real paper account capture, Plaid response, Telegram getMe/webhook,
provider-validating credential rotation, OS keyring, live host permissions,
owner backup/anchor/drill, PostgreSQL concurrency, Docker, mutation score and
remote CI. The exact local/connected commands are in docs/STATUS.md and RUNBOOK.md.
Trading API key scope controls and IP allowlisting are not certified by Broker
API documentation or key-prefix hints. Alpaca email/crypto settings require
owner verification. Logs/IPs are not assumed available through the Trading API.

The Stage S services and host CLI do not constitute the full running alert
pipeline. Monitor cycles, bot handlers and digest/report composition are wired
in their specified stages. Per-call LLM token limits and the actual public-only
provider request remain Stage E work. Cancellation and AUTO_LIVE prerequisite
composition remain Stage I work. No order executor exists before Stage I.

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

Provider response-format support differs. The implemented client requests JSON in the
prompt and validates it with Pydantic; no response_format assumption is baked in.
No provider-specific model or token price is supplied by default.

## Stage E evidence - October 6, 2026

`LLMClient` uses the pinned OpenAI 3.24.0 SDK with explicit URL/model/key and
zero SDK retries. The SDK's verified legacy httpx.AsyncClient bridge is exercised
through MockTransport in test_llm_client.py. HTTPX2 is the SDK default; the
custom legacy bridge, bounded body/deadline, exact endpoint and redirect refusal
are tested locally. [Official Python reference](https://developers.openai.com/api/reference/python)
documents the configured SDK controls. No paid provider request occurred;
actual model availability, rates and account permission remain UNVERIFIED.

The five recorded companyfacts fixtures (MSFT, COST, JPM, AAPL, SNAP) have raw
SHA-256/fetch provenance in backend/tests/fixtures/sec/manifest.json. Their
independent expected arithmetic exercises FY/TTM, sector exemption, noncalendar
fiscal years and negative earnings. The SEC provider's request contract is
separate from broker/paper integration. Owner contact was used transiently and
was not saved in source, fixture headers or documentation.

The GD-08 offline command now runs actual indicators and hunter, two CRO checks,
fundamentals, news/flow/earnings/IV, compliance, a RAM-only ledger and escaped card
plus manual preview. NVDA inputs are explicitly synthetic recorded fixtures.
This verifies no paid SDK construction or real-ledger write with sentiment off;
connected swarm deadlines, private Telegram callbacks and actual approved ticket
creation remain F work. Unknown fundamentals/earnings/flow/SPY are visible.

```text
python scripts/dry_run.py --dry-run NVDA --offline
python -m pytest -q backend/tests/test_fundamentals.py backend/tests/test_sec_edgar.py backend/tests/test_llm_client.py backend/tests/test_dry_run.py
python -m pytest -m integration --paper-integration-env-file PATH_TO_PRIVATE_PAPER_ENV
```

Paper integration is UNVERIFIED without an explicitly supplied private file.
Local mutation, PostgreSQL, Docker and remote CI remain UNVERIFIED; exact
reproduction and prerequisite limitations are retained in docs/STATUS.md.

## Complete VERIFY tag inventory

Stage K's document transport was checked against pinned python-telegram-bot 22.8
RequestData/InputFile multipart behavior with MockTransport and the official
[sendDocument contract](https://core.telegram.org/bots/api#senddocument).
Only generated, bounded latest.html bytes to an admitted owner private chat are
allowed. No actual document or DRILL was sent; real Telegram remains UNVERIFIED.

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
