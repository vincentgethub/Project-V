# Final build report - October 12, 2026

Post-build follow-up, October 15: [Non-tax mutation profiling](NON_TAX_MUTATION_SPEED.md)
records before/after setup and call observations, all five planted-mutant proofs,
and the limited in-memory indicator seed change. No test cases, assertions,
production sources, shard assignments or gates change. The full no-test function
inventory and 33 individual tax review rows are linked there. Native Linux
counts, slowest observed mutants and any proposed split are in the delivery handoff;
no second push is used to update this document after CI.

Post-build follow-up, October 15: [Tax kill pass 2](TAX_MUTATION_KILL_PASS_2.md)
supersedes the first pass's message-only proposals. It records 56 added cases,
169 newly killed focused mutants, 32 separate proposals, one unresolved bound
and five cases awaiting POSIX execution. The strict 100% gate remains unmet;
no equivalent allowance is installed. Delivery CI evidence is in the handoff.

Post-build follow-up, October 14: [Tax mutation kill report](TAX_MUTATION_KILL_REPORT.md)
records the owner's tests-first audit, one proven exact-rate ceiling fix, fresh
offline evidence and every individual equivalence proposal. The 100% mutation
gate remains unmet; no proposal is approved or excluded. Historical build-stage
counts below are retained, rather than represented as the current test count.

All requested build stages are GREEN OFFLINE. Stage W is committed locally as
`0c7823a`. Available gates pass; deployment, actual integrations and live
readiness are not fully verified. MANUAL paper remains default, MANUAL_CSV is
disabled and AUTO_LIVE remains locked. Work stops after this report.

## Build status and stage counts

The requested implementation sequence is audit/fixes, S, D, E, F, G/G+, H, J,
I, K, V and W. A/B/C are earlier deliveries. GREEN OFFLINE certifies available
fake/offline gates, not authenticated integrations, an edge, or live readiness.
UNVERIFIED and owner-deferred acceptance items never count as passes.
Historical stage counts are cumulative selections and must not be summed.

| Stage | Status | Recorded safety passes | Skips / deferred evidence |
| --- | --- | ---: | --- |
| A | GREEN OFFLINE | 845 | Owner services were not certified. |
| B | GREEN OFFLINE | 1,167 | Cumulative A/B selection; owner services not certified. |
| C | GREEN OFFLINE | 1,441 | Cumulative A-C selection; later deterministic fundamental amendment supersedes the earlier LLM addendum. |
| Step 0 audit/fixes | GREEN OFFLINE | 2,167 | One upstream SDK warning; private/platform checks unverified. |
| S | GREEN OFFLINE | 2,535 full + 7 later CLI cases = 2,542 distinct | Expanded evidence union, not a later 2,542-case full run; native services/platform evidence unverified. |
| D | GREEN OFFLINE | 2,901 | One paper integration skipped. |
| E | GREEN OFFLINE | 3,172 | One paper integration skipped. |
| F | GREEN OFFLINE | 3,366 | 44 skips: PostgreSQL and explicit paper integration. |
| G/G+ | GREEN OFFLINE | 3,709 | 44 skips; separate fixed replay passed. |
| H | GREEN OFFLINE | 4,080 | 46 skips; host/services, Docker, POSIX mutation and remote CI unverified. |
| J | GREEN OFFLINE with owner deferral | 4,266 | 52 skips; Amendment 02 11.2 item 1 MANUAL_CSV acceptance DEFERRED by owner, Oct 8 2026. |
| I | GREEN OFFLINE | 4,503 full + 9 later cases = 4,512 distinct | 58 skips; corrected affected-source/coverage evidence union. Paper bracket order acceptance 11.1 item 15 unverified. |
| K | GREEN OFFLINE | 4,644 full + 7 later cases = 4,651 distinct | 58 skips; corrected affected-source/coverage union. Real private drill delivery unverified. |
| V | GREEN OFFLINE | 5,179 | 59 skips; full-plus-overlapping-selection critical coverage union 100%; fixed replay and warm scan passed. Eight-variant walk-forward speed UNVERIFIED. |
| W | GREEN OFFLINE | 5,316 | 59 skips; fresh full critical coverage 100%, zero failures. Current W/write selection 159 passed overlaps this gate. Three separate perf cases passed. |
| Stage L / actual live unlock | LOCKED, not executed | Not a build pass | Requires the independent explicit host unlock and all prerequisites; outside this authorized build run. |

Historical detailed timings and failed attempts are retained in STATUS.md and
VERIFY.md. The final count below supersedes stage snapshots. No actual orders,
owner database migrations, native credentials or authenticated integrations were
used for development tests. Optional suggestions never apply themselves.

## Final available gate evidence

- Full offline safety suite: **5,316 passed, 59 skipped, four perf deselected,
  two warnings, 2,368.18s**, zero failures/errors; data/w-final-full.xml and .log.
  Skips: 57 explicit disposable PostgreSQL cases, one read-only paper account/SIP
  integration, one GET-only paper OTO/OCO proof. Warnings: pinned websockets
  legacy deprecation and the deliberately refused socket positive control.
- Required critical branch coverage: **100%, 7,624 statements / 2,606 branches,
  zero missing/partial, 20 inherited exclusions**; data/w-final-full-coverage.json.
  Scope: state machine, risk, compliance models, deterministic fundamentals,
  notifications, tax and the entire evaluation package. No new exclusions or
  reduced targets were added. This does not claim 100% of every project module.
- Fresh fixed 20-symbol/seven-year replay: **one passed, four deselected, one
  warning, 203.24s overall; 172.520s timed**, under the 180s budget, 443 decisions.
  SHA256: 82534b12f27d10ba8787236a94a8beefc7103d65efda9671b383e78ce0dd4024.
  Artifacts: data/w-final-replay.xml and .log. Timed work excludes fixture setup.
- Fresh 100-symbol warm scan and realtime fake idle/queue: **two passed, one
  deselected, one warning, 13.01s overall**. Warm scan **2.450009s**, under 60s;
  fake idle **0.000% CPU over 1.003s**, under 2%, with queue 1000/drop-oldest OTHER
  and dedupe. Artifacts: data/w-final-perf.xml and .log. These are fake budgets,
  not authenticated production performance claims.
- **Total: 5,317 distinct passes for safety + fixed replay; 5,319 including warm
  scan and realtime fake performance.** Focused selections overlap the full
  suite and are never added again. The 59 skips and unverified walk-forward
  budget are not passing tests. No coverage union is needed for this final full run.
- Ruff and format pass (437 formatted files); whole strict types pass (419
  sources); full execution/self-write AST controls and actual five root hooks pass.
- Production Bandit: zero findings across 56,631 lines, 16 reviewed
  narrow skips; pip check: no broken requirements.
- Exact runtime/development dependency audits: 62 / 141 active pins, no known
  vulnerabilities or audit skips; hash-pinned locks and SHA-pinned actions kept.
- Authored source secret scan: zero findings. Gitleaks 8.30.1 redacted history
  scan: zero leaks; data/w-gitleaks-history.log records its pre-stage checkpoint,
  and data/w-gitleaks-history-final.log records the post-report checkpoint.
  Windows archive checked against official
  release checksum d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e.
- Runtime/development CycloneDX inventories generated in build/sbom. Initially
  putting them in data caused a guard refusal; moving generated inventories to
  the existing build directory repaired it without changing the safety guard.
- Wheel built with no dependency resolution/build isolation; SHA256
  44b228bbf07ebf89fa8bdaf6fd5a42643f23e72b209e9b051a741e88417394ac.
  It contains the learning/realtime modules and currently includes test packages.

## Still UNVERIFIED - exact evidence needed

| Check / requirement IDs | Credential, service or evidence needed | Verification path |
| --- | --- | --- |
| DAT-05..12, AX-15/20/22/28; actual paper account, SIP/IEX, clock/calendar and activity history | Matching Alpaca PAPER key pair in native keyring, actual account type/ID, entitlements and complete activity history | setup, doctor, explicit read-only paper integration; account/lot/history reconcile before reports. |
| Amendment 02 11.1 item 15; AX-23/24/27/29/31 real bracket/leg/cancel behavior | Disposable configured AUTO_PAPER account and owner's separately authorized paper drill; existing canceled OTO/OCO roots for GET-only proof | Order acceptance was not exercised; read-only integration cannot certify submit/cancel. Exact GET-only cancel test below. |
| EX-06/AX-40 real stop-raise prerequisites | At least 30 actual failure-free paper raises, no unprotected window over 30s, policy/variant-bound proof | Paper observation and doctor; fake raises never qualify live. |
| FN-01..05, PL-01..06; actual funding/P&L reconstruction | Complete Alpaca activities, initial-flow/baseline evidence, current holdings, read-only Plaid checking credentials/account | setup, doctor and account reconciliation. Funding is detected only; no transfers. |
| GD-05/06, SEC-50..54, XK-01; real private Telegram delivery, webhook/BotFather state and drill | Native bot token/callback secret, confirmed owner private chat, BotFather security flags; owner's explicit drill send | setup, doctor, explicit host drill. No real message was sent by this build. |
| FA-01..08, RT-06; actual SEC filings/submissions | Descriptive SEC_USER_AGENT entered through wizard (name/contact email), public HTTPS access and fresh typed filings | setup, doctor; aggregate <=10 req/s. No missing filing is a pass. |
| RT-07; actual FRED/VIX | Owner's FRED API key entered only in setup/native keyring, HTTPS access and completed-session VIX observation | setup, doctor; missing/stale evidence fails closed. No key is in a file/test/log/commit. |
| RT-02/04/05; actual News REST/WSS, assets and corporate actions | Matching paper data keys, authenticated News entitlement, verified TLS/allowlisted hosts; current watchlist/held coverage | doctor and MANUAL paper runtime. Published Basic limits alone do not certify News entitlement. Corporate actions have no freshness guarantee. |
| RT-03; operational Nasdaq halt feed | Public HTTPS RSS access with parseable qualified symbols/times and successful bounded minute polls | doctor/runtime; public prior RSS response was not owner-host operational certification. |
| RT-08/EVT-01..05; current macro schedules | Owner-curated current-quarter FOMC/CPI/NFP/GDP/PCE CSV, official-source review and exact host confirmation | vws events refresh-schedules; the shipped empty CSV is not verified. |
| RT-14/AX-40; >=5 whole healthy XNYS sessions | Actual scoped required-feed samples from open to close, no missing opening/closing evidence, gaps or outages, current policy hash | Runtime accumulation then doctor/live guard. Five snapshots or fake sessions cannot qualify. |
| SEC-01..04/41/70..72; owner host/account security | Non-admin host protections/updates/Defender/firewall/encryption as available; authenticator/backup codes, email alerts, carrier PIN, phone lock, unused crypto disabled, API restrictions/scopes/IP evidence | doctor and explicit host attestations with authoritative account checks. Unavailable probes remain UNKNOWN/UNVERIFIED. |
| SEC-10..14/40..43; actual native store, ACLs, backup/restore/anchors | Working OS keyring, restricted real paths, saved backup key, actual encrypted backup and scratch verified restore, off-box/Telegram anchor comparison | setup, ops backup/restore-test, ledger verify-anchor and doctor. No owner's DB was opened/migrated here. |
| AX-40, GV-01..05, DQ-02, XA-01/02; readiness, drift, incident and calibrated cost proof | Qualified current-policy PAPER history/report, actual fills/arrival quotes/fee attribution, benchmark/secondary-feed data, security/drill/incident evidence | Reports, registered validation, doctor and read-only /verdict. No edge or READY has been established. |
| SEC-73/AX-40; actual watchdog/external healthcheck | Native HEALTHCHECK_PING_URL from setup, owner-run watchdog and external checker | doctor and host runtime; no configured service was assumed. |
| Optional GD-01/SEC-60..62 and LJ-04 narration | Owner-chosen LLM provider/model/base URL/API key and pricing, enablement plus budget; optional news provider key if selected | setup, doctor; LLM remains off by default. Local typed fakes do not certify paid service behavior. |
| TX-08 / TAX_PROFILE; numerical tax set-aside | Owner-supplied federal ST/LT rates (TX-08 supplies none), review of NIIT applicability | setup. Defaults single/Texas zero/state and TX NIIT zero; federal unset means totals only, not a guessed estimate. |
| CMP-06, TX-01..10; actual cross-account wash awareness / tax forms | Marked/imported IRA/Roth, Merrill and 401(k) lots plus completeness/identity/lot-method review, actual broker 1099-B/mapping and current form review | explicit tax import/export/reconcile. No login to outside accounts; 1099-B is authoritative and numbers are estimates. |
| QV-03, DQ-01..04; real survivorship/delisted/replay inputs | Complete sealed RAW/SPLIT/ALL bars and causal filings, dated membership/removal evidence, provider availability/terms | Explicit history import/registration; current watchlist-only results warn about survivorship. Missing histories refuse rather than invent. |
| LJ-02/04; actual MFE/MAE, gap-open/arrival evidence | Complete causal observed held-price coverage and genuine opening/arrival quotes | Current journal records unknowns as null; physical fill R never invents excursions. No fake historical bounds are presented as actual. |
| R-10, mutation and PostgreSQL service gates | Supported POSIX/Linux mutation environment and explicit disposable loopback PostgreSQL 16 service | Exact commands below; 57 PG cases skipped when service absent. Mutation score not inferred from ordinary tests. |
| GD-09, SEC-35; container build/runtime | Docker engine and disposable checkout; native OS secret-store availability for connected runtime | Exact build command below; native keyring unavailability makes connected container startup refuse. |
| SEC-24, remote CI | Owner-authorized later push / GitHub job execution | Both CI layouts include supported audit, safety, performance, mutation, PG and container gates. No push means no CI execution claimed. |
| PF-04 eight-variant walk-forward speed | Prescribed fixed 8-variant/20-symbol/7-year fake workload on a supported machine | V measured 19 incomplete windows in 949.845s, no result. Current W source not recertified for this budget. Explicit spec exception permits UNVERIFIED with timings. |

## Deferred / not fully met by ID

- Amendment 02 11.2 item 1 and earlier manual-state/funding requirements:
  MANUAL_CSV acceptance is DEFERRED by the owner's Oct 8 decision; ALPACA is
  the only primary state source. Disabled startup/doctor/no-read regressions
  remain. The declined host evidence file was never built.
- Amendment 02 11.1 items 15/16, R-10/GD-07 mutation certification, SEC-24/35:
  real paper order acceptance, actual POSIX mutations, remote CI and Docker
  have not been run. Offline source controls pass; these external gates do not.
- PF-04 eight-variant speed: UNVERIFIED under Amendment 05's acceptance exception.
- LJ-02/04 actual excursions/gap-open records are not complete where necessary
  observed price coverage is unavailable. Fields remain unknown. Causal news,
  halt and dilution tags are connected and tested; no inference fills gaps.
- TAX_PROFILE/TX-08 federal numerical defaults cannot be populated because TX-08
  explicitly supplies no ST/LT rates. The setup asks for them; totals-only while
  unset is the specified fallback. TX-09/10 actual 1099-B/2026 form agreement
  remains unverified without owner evidence and official form review.
- Actual acceptance of the service/security/readiness IDs in the table remains
  unverified. The code paths are implemented and covered with fakes; no claim
  that the complete deployment or all acceptance criteria are 100% verified.

## Precedence decisions, limitations and repairs

1. Amendment 02 supersedes the master's execution ban only for the isolated
   guarded AUTO paths. MANUAL stays default and never imports the executor.
   Amendment 03 replaces the older env-secret default with native keyring.
2. Amendment 01 supersedes the earlier LLM five-point addendum: exact metrics,
   statuses, score/levels/risk/qty/approval are code decisions; LLMs only interpret
   bounded public evidence. The five strict thresholds are deterministic.
3. The replacement Amendment 04 wizard/skip order and full private progress
   page apply. Owner-deferred MANUAL_CSV overrides earlier acceptance items.
4. Amendment 06's event table supersedes XK-04's blanket macro-day blackout in
   host composition; FOMC/CPI/jobs halve, GDP/PCE annotate. Earnings/early-close
   gates keep their rules. Simultaneous events use the lowest multiplier once
   as the PR-04 event factor. V READY and W five-session proof add live prerequisites.
5. Broker-generated child IDs need verified nested-parent proof; unknown orders
   halt. A persisted AUTO-to-MANUAL downgrade may retain entry-disabled recovery
   for held protection. Configured MANUAL never imports the concrete executor.
6. Whole critical coverage uses explicit inherited exclusions, not entire-project
   coverage. Preliminary W full runs were stopped for a fixture-alias repair and
   causal journal fix; they produced no final passing result. Counts are honest.
7. Physical trade R includes attributed/model-labeled costs but excludes cash
   distributions not allocated to the trade. Account daily returns include them.
   Same-side fill-time ties use stable IDs; opposite-side ambiguity refuses.
   Corporate-action basis transformations and unknown fee/refund attribution
   halt rather than guess. Missing external-lot tombstones can overstate awareness.
8. Actual price excursions, startup histories, optional IEX comparison from the
   same vendor, News entitlement, SDK private connection calls and OS/container
   keyring operation need the stated verification. No failing guard was weakened.
9. Reported replay timings exclude coverage overhead; interrupted historical
   full-suite wall times are not performance claims. No parameter search or
   optimization was added. No extra server, dashboard, transfer or wallet code.
10. Source currently packages tests in the wheel. Setup's multi-file save is
    rollback-capable but not power-loss atomic; drift detection refuses partial
    configuration. Unknown incident-history windows do not establish a clean record.
    Bounded evidence-read inventories refuse on exhaustion; never delete ledger
    rows to bypass a capacity or integrity refusal.

## Exact next steps for the owner

From PowerShell:
```powershell
Set-Location -LiteralPath 'C:\Users\vince\OneDrive\Documents\ChatGPT\Project V\vws-core'
.venv\Scripts\python.exe -m vws setup
```
Use only paper credentials, retain MANUAL/paper, identify the real account type,
enter FRED and SEC identification in the wizard, complete read-only Plaid and
the private bot checks, enter/review tax rates and outside lots, and save the
backup recovery key when shown. A skipped test remains UNVERIFIED; do not
silence the checks. No secret should be pasted into this chat or a config file.

For an existing older known schema, stop the runtime before the following.
Migration authenticates an encrypted backup and scratch restore before additive
DDL; current schema is 7. Never edit version numbers, delete the DB or ledger
rows. A fresh current DB does not need an extra migration. The owner DB was
not inspected, so its existing version is unknown.
```powershell
.venv\Scripts\python.exe -m vws ops migrate --operator 'Vincent La Rocca'
.venv\Scripts\python.exe -m vws ops backup
.venv\Scripts\python.exe -m vws ops restore-test --file 'PATH_TO_NEW_ENCRYPTED_BACKUP.vwsbak'
.venv\Scripts\python.exe -m vws doctor
```
Curate and confirm the current-quarter schedule before considering AUTO_PAPER.
Review config drift acknowledgements and security attestations using RUNBOOK.
Do not proceed on a required RED or UNVERIFIED check.
```powershell
.venv\Scripts\python.exe -m vws events refresh-schedules
.venv\Scripts\python.exe -m vws doctor
.venv\Scripts\python.exe -m vws start
```
Start remains MANUAL paper and tap-to-approve produces a manual ticket. Enter
and execute any paper trade yourself in the broker. Do not run enable-live,
set AUTO_LIVE, bypass a gate, or treat this report as a trading recommendation.
An optional later AUTO_PAPER mode needs its separate explicit host workflow.

## Reproduce the unavailable gates

Use a disposable checkout/database; native secrets remain in keyring. No real
dotenv is selected implicitly by tests. From a supported Linux environment:
```sh
python -m pip install --require-hashes --no-deps -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m mutmut run
python -m mutmut results --all > build/mutmut-results.txt
python -m scripts.check_mutations build/mutmut-results.txt
python -m pytest -q backend/tests/test_postgres.py --postgres-test-url 'postgresql+psycopg://vws_ci:CI_FIXTURE_ONLY@127.0.0.1:5432/vws_ci' # pragma: allowlist secret - public disposable CI fixture
cp .env.example .env
docker compose build
```
The sample password is a public disposable fixture, not an owner's credential.
The PostgreSQL service/user/database must be explicitly created. Container
build does not prove connected keyring or runtime health. The existing CI jobs
provide the supported service/platform gates after a separately authorized push.

Read-only paper verification after setup, with a private **public-settings-only**
paper configuration file and paper keys in OS keyring:
```powershell
.venv\Scripts\python.exe -m pytest -q -m integration backend/tests/test_paper_integration.py --paper-integration-env-file C:\PRIVATE\paper.env
.venv\Scripts\python.exe -m pytest -q -m integration backend/tests/test_v_paper_cancel_integration.py --paper-integration-env-file C:\PRIVATE\paper.env --paper-cancel-order-ids EXISTING_OTO_ROOT_UUID,EXISTING_OCO_ROOT_UUID
.venv\Scripts\python.exe -m pytest -q -s -m perf --no-cov backend/tests/test_v_performance.py -k eight_explicit --basetemp data/w-perf-walkforward-temp
```
These GET-only integration tests do not submit or cancel orders. The actual
one-share far-price bracket probe is still unverified and requires a separately
authorized disposable paper drill. PF timings never optimize variants/parameters.

## Git and stopping point

Local author is vincentgethub / 325278731+vincentgethub@users.noreply.github.com.
Eleven older commits use codex@local.invalid and were not rewritten. The origin
remote already existed when checked; this run did not add/change it or push.
Local W commit: `0c7823a`; this report is saved in the following local documentation
commit (inspect with `git log -1`). Work stops after this report; no actual live
path, secret collection, account action or future work is started automatically.

Hypothetical/past results; not indicative of future returns. Tax calculations
are estimates and record-keeping aids, not tax advice; broker 1099-B wins.
