# Technical status

Audit date: 2026-10-04 America/Chicago. The initial audit results below describe the pre-fix working
tree. Audit-fixes and Stage S results below are historical; the Stage D gate
records the certified implementation. Amendments 01–06 supersede conflicts in the master and
earlier addenda. Execution order: audit/fixes → S → D → E → F → G/G+ → H → J → I → K → V → W.
Optional ideas require plain-words approval and live only in PROGRESS Suggestions.

Owner status instruction, October 7: finish G before H/J/I/K/V/W; S is already
certified offline. Collect the available FRED key only inside setup and store it
only in the OS keyring; never request or persist it in source, tests, logs or Git.
SEC_USER_AGENT is entered as name plus email in setup. Until configured, their
connected checks remain UNVERIFIED and fail closed. After all stages, create
docs/FINAL_REPORT.md with per-stage gates, the final cumulative offline/replay
result, every unverified prerequisite, unmet spec IDs, known risks and exact
setup/doctor/paper-start commands; then stop. No AUTO_LIVE or live trading.

## Stage H GREEN OFFLINE - October 8

The final cumulative offline gate passed **4,080 tests, 46 skipped, one perf
deselected, two warnings, 1,001.32s**. All required coverage, including evaluation,
is **100%: 4,168 statements and 1,346 branches, zero missing/partial**.
The 46 skips are 45 explicit PostgreSQL cases and one explicit-key paper check,
never passes. The separately recorded fixed replay adds one distinct passed case;
its 97.666-second run/443 decisions and SHA are retained below. Offline success
does not verify owner services, deployment, mutation, PostgreSQL, Docker or CI.

| Requirement | Implementation | Offline evidence / operational limit |
| --- | --- | --- |
| OPS-01; RT-01 folded into H | ops/doctor.py, host.py, read_checks.py; data/broker_clock.py; vws/security_cli.py | test_doctor.py / test_host_probes.py / test_broker_clock.py / test_read_checks.py: required failures, optional UNVERIFIED, broker identity, five-second skew, strict dates/early close/DST/cache, native probes; actual account/host remains UNVERIFIED |
| WZ-01..10; TAX_PROFILE defaults | vws/setup.py, setup_cli.py, host_config.py; ops/apply_config.py; README.md | test_setup_wizard.py / test_host_config.py: revised order, retry/skip unsets unknown evidence, hidden native secrets, private confirmation, cancellation restores files/keyring, names-only audit, no DB before confirmation, rerun/section isolation, MANUAL lock, single/Texas zero/NIIT zero/federal unset |
| OPS-02; private process health | vws/runtime_cli.py, __main__.py; ops/runtime.py, process.py, desk_source.py, account_context.py; agents/orchestrator.py, jobs.py | test_host_runtime.py / test_process_health.py / test_security_cli.py / test_desk_jobs.py / test_account_context.py: six connected bodies, no execution import, bound per-candidate refresh, missing J evidence blocks, actual OS lock, WAL, signal cleanup/draining, saved HALT, bounded heartbeat, retry retained urgent notice |
| OPS-03; AX-43 foundation | ops/watchdog.py, job_health.py; orchestrator completion hook | test_watchdog_maintenance.py / test_job_health.py: missed close+90, three failures, durable dedup, success-only guarded bounded HTTPS ping, no redirects; actual Telegram/dead-man service remains UNVERIFIED |
| OPS-04; SEC-40/42 | ops/maintenance.py, backups.py; runtime_cli nightly composition | test_watchdog_maintenance.py / test_backups.py: online authenticated scratch restore, explicit retention, corruption refuses pruning, nightly anchors/private notice; real owner restore/off-box anchor remains UNVERIFIED |
| OPS-05 | ops/migrations.py; vws/migrate_cli.py; core/database.py schema v5 | test_migrations.py / test_ledger.py / test_security_cli.py: only additive DDL for exact legacy v2/v3/v4 layouts, verified encrypted backup first, old hashes intact, transactional failure rollback; PostgreSQL automated upgrade refused, documented pg_dump/isolated restore |
| OPS-06; SEC-22..24 | actual Git-root and mirrored .github/workflows/{ci,weekly-audit}.yml, dependabot.yml; ops/dependency_audit.py; pyproject/locks | test_supply_chain_h.py / test_dependency_audit.py: 40-hex actions, read permissions, no PR secrets/automerge, real CycloneDX CLI inventories, current platform lock coverage/hash-bound host audit; mutation/PG/Docker/remote CI remain UNVERIFIED locally |
| OPS-07; SEC-35/70 | deploy/vws.service, windows_start.ps1; Dockerfile/compose; README.md/RUNBOOK.md | Reviewed standard-user/hidden scheduled-task and non-root systemd instructions, bounded restarts and graceful SIGTERM; no actual deployment performed; restricted Docker cannot access native keyring and refuses connected startup |
| OPS-08; SEC-75 | core/logging.py; context binding in scheduler/swarm/callback/delivery | test_logging.py: UTF-8 redacted byte limits, UTC day boundary, five size archives/day, age retention 7-365; existing synthetic-secret fixture interference corrected; no external telemetry |
| SEC-11/32 native Linux compatibility | security/native_ipc.py; secrets.py; net/egress.py | test_native_ipc.py / test_egress.py / test_secrets.py: synchronous thread-local native-store capability for the exact owned /run/user/UID/bus socket only; alternate/TCP buses, symlinks, wrong UID/family, other threads and listeners fail; real Linux Secret Service UNVERIFIED |

Completed focused runs are overlapping evidence, never summed: initial combined
components 411 PASS; immutable tables 183 PASS; native security union 168 PASS;
startup/log/scheduler union 87 PASS. The expanded H regression had 555 PASS and
one log fixture failure: earlier tests registered repeated synthetic x strings,
which correctly shortened the redacted record. Isolating that registry and testing
an explicit redacted secret made the final logging/read/worker union pass 64 cases.
Additional real-factory composition and start/signal cases passed 4; setup CLI
composition passed 2; account context 8; dependency proof 12; desk refresh 15.
The first cumulative run passed 3,974 tests, skipped 46 unavailable integration
cases and deselected one perf case (1,032.93s), but FAILED the required coverage
gate: 99.97%, with callback branch 220->224 missing. A valid-HMAC click for an
unknown proposal now checks that path without accessing fresh private evidence.
Connected quote reads now validate against the injected completion clock; fresh
quotes arriving during the GET pass, while backward clocks, future timestamps
and a changed completed session halt. The focused regression passed 197 before
one new test-fixture construction error; that fixture was corrected, and the
final targeted callback/quote gate passed 8 cases. The subsequent runs follow below.
The 46 skips are exactly 45 PostgreSQL cases and one explicit-key paper check.
The rerun passed **3,978 tests, 46 skipped, one perf deselected, two warnings,
955.84s**; the original protected scope is **100%: 2,217 statements and 718
branches**. This does NOT close H: Amendment 01 section 7 also requires 100%
evaluation branch coverage, omitted from earlier coverage commands. The actual
Git-root/mirrored CI gate now includes evaluation and its guard test enforces it.
The initial 241-case evaluation gate failed at 91.93%; the broader 283-case
gate after new proof tests still failed at 93.25%. The final fresh focused gate
passed **364 tests, one perf deselected, one SDK warning, 169.20s** with **100%
coverage: 1,951 statements / 628 branches, zero missing/partial**. Nine safety
test modules cover malformed filings, account/cost bindings, projection faults,
publication proofs, capacity limits, cash conservation, splits and held exits.
Production capacity values remain unchanged; named constants make restrictive
test bounds possible without manufacturing huge tapes. The full combined gate
including evaluation passed as recorded above. No guard or coverage exclusion was relaxed.
Intermediate appended coverage is diagnostic only; final evidence must be a
fresh run against the final source. No failed run is counted as green.

Strict typing currently passes 257 authored sources; full AST source guard PASS;
production Bandit zero findings; pip check PASS. Actual JSON pip-audit invocations
covered all 62 runtime and 141 development pins, with no skipped/vulnerable pin.
The new direct development dependency cyclonedx-bom==7.5.0 implements SEC-23;
all earlier pins are retained. Generated public SBOMs belong in build/sbom, an
existing generated-artifact exclusion; source/config checks are not relaxed.

Schema v5 adds only chained schema_version records. Unknown schemas and altered
columns are refused. Setup cancellation leaves immutable audit/doctor evidence;
power loss between multiple file renames cannot be atomic, so startup validates
the whole configuration and its drift hash. No automatic repair or source writes.
H's account reader requires Stage J's actual account/lot/fill context, never an
invented empty history. The weekly report requires a current sealed RAW/SPLIT/ALL
history and includes the managed account from its first tracked alert; missing or
stale history refuses. Recorded planned stops never claim broker stop coverage.
Paper/live/order execution remains I; before I start refuses AUTO modes.
No real dotenv, owner DB, keyring, FRED/SEC/chat/broker or host setting was used.

## Stage G/G+ traceability - October 7 (offline gate passed)

| Requirement | Implementation | Current focused evidence / remaining work |
| --- | --- | --- |
| CM-01..06 | evaluation/costs.py; data/fee_schedule.py, historical_spread.py; core/config.py; config/fees.yaml | test_costs.py / test_historical_spread.py: exact dated ceilings, trade-through/participation, stop-first, next-open exits, multi-symbol delayed SIP quotes/physical budget, unavailable floor and actual-fee identity; FN-02 activity ingestion remains J |
| DQ-01/03/04 | data/history.py, split_cache.py, data_layer.py; agents/peer_strength.py | test_adjustment_data.py / test_split_epochs.py / test_data_layer.py: RAW audit, SPLIT signals, ALL peers, adjustment-key isolation, durable split epochs/refetch/invalidation, sanity -> SUSPECT, immutable old levels and manifest-only bounded canonical reads |
| DQ-01 replay distributions | evaluation/dividends.py; outcomes.py/equity.py/replay.py | test_replay_dividends.py: adjacent ALL/SPLIT factors cancel future factors; native prior close/current split shares; conservative estimated credits outside settled entry cash; ambiguous/reversing factors fail; tracker dividends remain excluded |
| EV-01 | evaluation/outcomes.py, provenance.py, ledger_inputs.py, ledger_source.py, evidence.py | test_outcomes_history.py / test_ledger_evaluation.py / test_ledger_weekly_source.py: actual alert lifecycle/CRO shadow, recorded expiry/ATR/ADV/spread/equity, shared fills, raw shares, splits, R/MAE/MFE/time/reason; legacy/unbound evidence refused; per-alert proofs retained |
| EV-02/ER-03..05 | evaluation/equity.py, weekly.py, publication.py; agents/briefing.py /edge | test_weekly_equity.py / test_weekly_publication.py: independent cash/mark/metric goldens, cohorts/statuses/filters/score bands, CSV formula protection, hashes, write-once files, private current-policy masking and cancellation/failure HALT |
| ER-01/02; QV-05 baseline | evaluation/edge.py; indicators/statistics.py; ops/playbook_kill.py | test_edge.py / test_edge_statistics.py: actual CM goldens [+2,-1,+0.5,-1,+3]R, strict fixed grades, 10,000 circular resamples/90% CI/seed, no-loss PF n/a, replay-in-sample UNPROVEN; shared XK-05 function only, later K persistence |
| EV-03/PF-03 | evaluation/replay.py, fundamental_timeline.py; indicators/replay.py; data/frozen_filings.py; vws/replay_cli.py | test_replay.py / test_replay_gates.py / test_frozen_filings.py / test_replay_cli.py: actual shared hunter gates/CRO sequential portfolio, settled entry cash/T+1, missing fundamentals skipped, filed-date/staleness timeline, halt cancels entries but held exit runs, fixed-parameter sealed CLI |
| PF-01/02 | indicators/vectorized.py, reference.py, seeding.py, cache.py, causal_cache.py; agents/indicators.py | test_vectorized.py / test_npz_cache.py / test_causal_cache.py: golden/random relative <=1e-9 and identical quantized levels, once-per-symbol economic indicators, no-pickle/decoded ZIP bounds/readonly arrays/source+output hashes, memory+both disk caches invalidated |
| SEC-13/42/72 weekly | evaluation/security_summary.py; ledger_source.py/publication.py/weekly.py | test_weekly_security.py: event counts/new numeric IDs/age boundaries/unknown dates, latest failed check retained, verified old prefix anchor repeated, masked IDs, CT display, no keyring or secret values |

The final cumulative non-perf gate passed **3,709 tests, 44 skipped, one perf
case deselected, two warnings, 835.06s**. Required statement/branch coverage is
**100%: 2,202 statements, 716 branches, zero missing/partial** across
risk/state/compliance contracts/fundamentals/notifications/tax. The skipped
cases are one explicit-key paper integration and 43 disposable PostgreSQL
cases, never PASS. Warnings are the pinned SDK deprecation and deliberate
socket-blocking positive control.
Separate actual 20-symbol, seven-year replay: **1 PASS, 4 deselected, 115.23s
overall; timed replay 88.411s, 443 decisions**, under 180s, three compute workers
plus the sequential parent. Proof SHA:
`d81cb662aa155344891c91e4911c2fbe7841f6137aecdc74cc7523f19cb8919c`.
This perf case was excluded from the cumulative gate; the other four deselected
cases were included there. Focused gates overlap and are never added: report/
source/CLI/data 153 PASS; fill matcher 21 PASS; latest progress page 11 PASS.
The first expanded full run had six manual-fill failures (3,702 PASS, 44 SKIP,
one perf deselected). It still required ALL after signals moved to SPLIT. The
matcher now requires SPLIT and refuses ALL-only evidence; the final rerun passed.
Ruff lint/format: **231 files**. Strict authored-source typing: **213 files**.
Full AST positive/negative source guard PASS. Production Bandit: **zero findings,
27,856 lines, eight explicit skips**. All five actual Git-root hooks passed.
Authored secret findings: zero. Gitleaks: **nine prior commits, 25.96MB, zero
leaks**. pip check PASS; unchanged 123-pin dev lock audit: no known vulnerabilities.

Replay snapshots record the synthetic flag, source hashes, virtual seed/funding,
survivorship and fixed disclaimers. Synthetic caches use a separate namespace.
Real replay requires explicit seed/funding and sealed history plus filing
manifests; an empty filing manifest means unavailable evidence, never PASS.
The local replay introduces no provider, LLM, order or owner-database calls.
H still supplies connected startup/history-source/notifier composition. J owns
actual fee activities, V registered validation/overlays/readiness, W realtime
health. Real service/OS keyring/host/owner backup checks, POSIX mutation,
PostgreSQL, Docker build/runtime and remote CI remain UNVERIFIED. VERIFY.md has
exact reproduction commands and CI runs supported platform gates when invoked;
no push or remote CI run occurred. STAGE_G_SOURCE_NOTES.md records primary
SDK/fee verification and assumptions. No owner DB, dotenv or credentials were
opened. The next stage is H; DQ-02 and remaining PF gates remain scheduled V.

## Stage F traceability - October 7 (offline gate passed)

| Requirement | Implementation | Test / verification limit |
| --- | --- | --- |
| GD-01..03 fan-out | agents/swarm_runner.py; peer_strength.py | test_swarm_and_callbacks.py; test_peer_strength.py; two CRO checks, CMP, deterministic fundamentals, six bounded public results plus immutable desk policy |
| GD-06 candidate provenance | SwarmRunner cache reconstruction and actual hunter recomputation | forged score/level/quantity, changed or future bars, source sequence/hash and SIP lag cases; connected sources require persisted financial marks |
| GD-04/XNYS jobs | agents/orchestrator.py and jobs.py; core/database.py JobRun | test_scheduler.py: early close/holiday/DST/HALT/coalescing/failure; test_desk_jobs.py actual daily/premarket/monitor/news/housekeeping bodies |
| GD-04 suppression | agents/desk.py atomic DESK_RESERVED/DESK_COMPLETED | concurrent admission, session cooldown and daily cap cases; reservations count in-flight proposals |
| GD-05/GD-06/SEC-51 | notifications/callbacks.py; telegram_bot.py | test_swarm_and_callbacks.py/test_telegram_flow.py real pinned SDK via fake HTTP; private allowlist, HMAC/action/config/chat/message binding; no external sends |
| Fresh approval boundary | ApprovalGate fresh IEX/account/CRO/CMP/fundamental checks and serialized state/time recheck | double approve creates exactly one ticket; actual-check phone-halt/expiry/stale races; valid capped held SELL works during HALT |
| Details/manual tickets/P/S | notifications/card_formatter.py; callbacks.py; additive TicketEvent | exact card/ticket goldens, full RuleResults, immutable ticket hash; read-only Details; single-use approved-ticket placement/skip; Approve replay preserves follow-up buttons |
| Quiet hours/expiry/annotations | TelegramBot durable queued notice/note evidence; terminal ApprovalEvent | frozen CT/DST queue/urgent stop tests; changed policy/lost provenance HALT; expiry writer-consumption and failed-edit tests; HTML/UTF-16 boundaries |
| Private commands/PG-04 | agents/briefing.py DeskCommands; TelegramBot command admission | test_desk_jobs.py/test_telegram_flow.py status/positions/digest/report/help/full progress; missing reports/evidence explicit; wrong account/stale holdings fail job and halt |
| R-09 monitor | agents/position_monitor.py; jobs.py | test_position_monitor.py/test_desk_jobs.py fresh explicit IEX/symbol checks, held-share caps, open-ticket zero sell shares, urgent suggestions during HALT |
| Read-only fills | data/fill_polling.py; Ledger.record_fill optional serialized session | test_fill_polling.py 20 cases passed; account-bound GET activity parsing, dedup/partial/order binding/qty/limit/expiry; unmatched MANUAL observations without invented stop |
| GD-08 offline run | agents/offline_run.py and scripts/dry_run.py | test_dry_run.py actual SwarmRunner, RAM-only, sockets blocked, zero LLM calls; CLI preview passed with no sends/orders |
| R-02/schema v4 | core/database.py; core/ledger.py | adds only job_runs/ticket_events; raw UPDATE/DELETE controls; exact prior v2/v3 emergency inventories; no owner migration |
| GD-09/OPS-06 package | Dockerfile/docker-compose.yml; .github/workflows/ci.yml | digest-pinned Python/PostgreSQL, non-root app, no production ports; SHA-pinned CI mutation/PG/build jobs; local Docker/PG/remote CI UNVERIFIED |
| Mutation certification | pyproject.toml; scripts/check_mutations.py | test_mutation_gate.py 10 cases passed; non-killed/unverified results rejected; actual POSIX mutation run UNVERIFIED on Windows |
| SEC-20 closure | pyproject.toml; requirements*.lock; docs/DEPENDENCIES.md | 62 runtime/123 dev hash records compiled, all prior pins retained; hash install/editable/pip check passed; 123-pin dev audit has no known vulnerabilities |
| F final artifacts | README.md, RUNBOOK.md, VERIFY.md, ASSUMPTIONS.md, SELF_REVIEW.md | applied safety review covers 23 failure routes with code/test references; owner progress rewritten in the same stage commit |

Current static checks: Ruff lint PASS, 178 files format clean; strict authored-source
mypy PASS for 162 files; full AST source guard PASS; production Bandit zero
findings across 21,965 lines. The final cumulative gate passed **3,366 tests,
44 skipped, 2 warnings, 739.93s**. Risk/state/compliance contracts/fundamentals/
notifications/tax have **100% statement and branch coverage: 2,202 statements,
716 branches, zero missing/partial**. The skips are one explicit-key paper test
and 43 explicit-URL PostgreSQL cases; none are counted as PASS. Warnings are the
pinned SDK deprecation and the deliberate socket-blocking positive control.
All five actual Git-root pre-commit hooks passed. Authored secret findings are
zero; only the public disposable CI password is explicitly allowlisted at its
example lines. Gitleaks scanned eight prior commits/25.65MB with zero leaks.
Earlier focused runs overlap: 182 PASS with 99% combined selected coverage before
the final Telegram policy/provenance/expiry cases; 20 fill cases PASS and 392
source-guard/egress cases PASS. Counts are never added across those runs.
Two later injected tests initially failed due to fixture assumptions (the first
Alert read was intercepted too early; 31 seconds was inside the configured
60-second freshness limit). Both were corrected; the final full suite passed both.

Python base OCI index: 3.12.14-slim-bookworm sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e.
Optional PostgreSQL 16 index: sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4.
Both were resolved from the official registry. Docker/psql are absent locally.
The container startup/health CLI and actual connected source/notifier/maintenance
composition are Stage H dependencies; weekly report production is Stage G.
No real keys, Telegram messages, broker orders, owner database migration or push occurred.

## Stage E traceability - current October 6 work

| Requirement | Implementation | Actual local evidence / limit |
| --- | --- | --- |
| FA-01..09 | agents/fundamentals.py; data/sec_edgar.py | test_fundamentals.py: 83 cases, 302 statements/118 branches, 100%; 5 recorded real issuer payloads with independent FY/TTM expected values |
| FA-02/DAT-11 | SEC point-in-time tags, bounded cached provider | test_sec_edgar.py request/rate/cache/hash/fault checks; real fixtures recorded with transient authorized contact; no account credential required |
| GD-03 playbooks/DAT-05 | setup_hunter.py, indicators.py, shared anchors.py/scanner.py | test_setup_hunter.py hard/score/level/quantity goldens; test_indicators.py hand arithmetic; shared memo rejects changed bars/anchors |
| GD-01/GD-02/SEC-60..62 | LLMClient, prompts.py, four versioned Markdown prompts, PublicResearchInput/Narrative | test_llm_client.py: 49 cases; invalid/duplicate/nonfinite JSON, bounded strings, citations, public-only data, injected instructions, cache/singleflight, three-attempt transient cap |
| GD-01 atomic budget | agents/llm_budget.py immutable reservation/settlement security events and per-attempt llm_calls | 20 simultaneous fake calls cannot overspend; actual/estimated settlement, single-use receipt, overrun disable, NY midnight and cancellation evidence |
| SEC-30/31 optional SDK | net/http.py SDKLLMClient exact configured POST path, verified TLS, 2MiB body, full deadline, no redirects/ambient credentials | test_llm_client.py exercises actual pinned SDK through MockTransport; paid network/model/prices UNVERIFIED |
| GD-03 providers | providers.py/news_reader.py/flow_tracker.py | test_research_agents.py: 13 cases; unavailable flow/IV/earnings remain explicit; no paid context assumed; only new eligible headline batches summarized |
| GD-08/E disabled acceptance | agents/offline_run.py, scripts/dry_run.py, recorded synthetic NVDA fixture; notifications/card_formatter.py | test_dry_run.py: 8 cases; socket blocked; real indicators/scoring/two CRO checks/compliance; zero LLM calls; ambient AUTO_LIVE/DB URL ignored; RAM-only ledger verified; manual preview only |
| GD-05 card foundation | validated CardContext; exact price/qty/risk/weight/reward calculations; HTML escaping and CT display | 58 statements/6 branches, 100%; changed qty/price or partial evidence rejected; oversize card fails without truncation; private connected callbacks pending F |
| TX-08 / owner profile | docs/spec/TAX_PROFILE.md, domain/tax_profile.py, Settings, tax/tax_tracker.py | test_tax_profile.py/test_tax_tracker.py: exact owner defaults/explicit override; totals-only while federal rates unknown; tracker estimate and shared wash-awareness foundation passed |
| Owner external-sale awareness | WashSaleMatcher.marked_external_lots; TaxTracker.review_sale | Inclusive +/-30-day hand goldens; other-account and supplied identity-group checks; IRA/Roth/Merrill/401(k) prompts; unknown/corrupt lots fail closed; no inferred 401(k) treatment; durable J import/UI pending |
| Amendment05 PR-02 | core/dependencies.py bans optimizer packages in direct/transitive lock records | test_dependencies.py planted optuna/hyperopt/scikit-optimize/deap/nevergrad records rejected; G+/V features remain pending |
| Amendment06 no self-modification | security/write_guard.py; source_guard.py; ops/anchors.controlled_path | test_write_guard.py planted source/config writes, forged trusted basename, source writes from trusted config writer, central artifact path refusal; full no-order positives retained |
| Build metadata exception | exact standalone scripts/compile_locks.py outputs requirements.lock and requirements-dev.lock | Fixture compiler can touch only those two paths; runtime import of compiler is rejected; no runtime source-write exception |
| PG-01..05/latest Amendment04 | vws/progress.py full current page; tests/test_progress.py | Seven owner sections/Suggestions/60-line ceiling; all source changes require progress update; private handler admission/masking/rate pending F |

The initially failed full run had one obsolete expected zero LLM budget. The
amended default is 1.00 while LLM_ENABLED remains false; that test was corrected.
The next full run passed 3,147 tests with one credential-dependent skip and two
warnings (418.40s), 1,555 statements/520 branches at 100%. Later card/tax additions
passed the final expanded cumulative gate below; counts are not added
across overlapping runs. Focused new tax/wash tests passed 89 cases with 100%
coverage; card/dry-run passed 8 cases with 100% notification coverage.

Current source lint passes; 155 files format clean, 140 sources type strictly,
production Bandit has zero findings. B105 suppressions label enum value PASS;
B106 explicitly supplies an empty unused SDK webhook secret to disable ambient
inheritance. The allowlisted entropy constant is the public SHA-256 of `{}` for
missing companyfacts, never a credential. Source secret scan reports zero.
The 121-pin dev lock audit reports no known vulnerabilities; pip check is clean.
Gitleaks scanned all seven prior commits/25.33MB with zero leaks. Its initial
remote-link warning exposed a Markdown-wrapped Git URL; the local URL was fixed
to the identical plain HTTPS target. No push, broker/Plaid call, paid LLM request
or Telegram send occurred in this stage's fake gates.

Amendments05/06 are preserved verbatim and linked by AGENTS. Offline card/preview
dependencies were built now to meet E's explicit disabled-client acceptance;
connected swarm, scheduler, callback lifecycle and deployment remain Stage F.
The owner tax request was wired now to shared defaults and pure tracker services;
H consumes those defaults in setup and J supplies durable sale/import/report UI.

Final expanded cumulative gate: **3,172 PASS, 1 SKIP, 2 warnings, 435.29s**.
Risk/state/compliance contracts/fundamentals/notifications/tax: **100%**, 1,674
statements and 534 branches. After that run began, final calendar expiry code
and ten new expiry cases were added. Its separate final hunter/config/dry-run
gate passed **339 tests** (9.26s); overlapping counts are never summed. The
expiry rule now uses the Nth exchange close strictly after creation, including
at-close, holiday, DST and early-close fixtures. Final Ruff formats 157 files;
final authored-source typing passed 142 files. All five actual Git-root hooks
passed after the client-rename formatting fix; final production Bandit is clean.
Final optional-LLM/no-order/writeguard/dependency/research/dry-run gate: **443
PASS**, 17.91s; no weakened source positive controls.

Historical checkpoint before Stage F: **2026-10-06 America/Chicago**. Stage S is complete in local
commit `bc3e6f0`. Its offline gates and fresh hash-lock installation passed;
actual owner services remain UNVERIFIED. Expanded Stage D passed its offline
gates and is complete; deterministic Stage E's offline gates passed. Stage F
connected composition is next.
Owner attachment commit `485ec7a` contains unfinished E evidence, not a certified
stage. The latest Amendment 04 replaces the previous saved text verbatim;
Amendment 05 is newly saved verbatim. AGENTS links both. Their specified reminder
lines are appended to Amendment 02 without rewriting its earlier bytes.
Amendment 06 is saved verbatim with its reminder appended and AGENTS link.
Its runtime self-modification ban applies immediately; lessons never auto-apply.
RT-01 clock/calendar reads may be folded into H doctor (read-only and already
needed for early-close safety); the Stage H report must state that justification.
EVT display-only schedule work may be folded into F, with report justification.
Owner TAX_PROFILE is saved. Settings/TaxProfile and tax/tax_tracker.py use
single/Texas state0/NIIT0; the H wizard and J durable tax/import UI are pending.
TX-08 has no federal ST/LT defaults; those stay unset (totals only) until supplied.
External IRA/Roth, Merrill taxable and 401(k)
lots are manually entered/imported only; shared wash checks, no logins or funding.

## Stage inventory

| Stage | Existing deliverable | Current amended status |
| --- | --- | --- |
| A | core config/money/clock/logging/database/ledger/state/guard; XNYS calendar; Stage_A.md | Original stage certified; configuration/guard corrections certified |
| B | frozen contracts, registry, CRO, risk boundary; Stage_B.md | Original certified; session daily-loss correction certified |
| C | compliance, wash matching, tax models, compliance boundary; Stage_C.md | Original certified; shared tax-core move reserved for J |
| D | market/broker/liquidity boundaries, async batch/cache, news/actions, earnings and manual CSV providers | DAT-05..12 offline gate passed; actual paper integration UNVERIFIED |
| S | security/net/ops/Telegram admission/content/dependency services and host CLI | Offline gates passed; connected verification and later pipeline wiring tracked below |
| E | Deterministic playbooks/fundamentals; public providers; optional bounded LLM; offline card/preview | Offline cumulative gate PASS; recorded SEC fixtures and final expiry checks passed |
| F | Swarm, jobs, private alert lifecycle, read-only fill matcher, packaging and CI | Offline gate passed in d628a7c; actual owner connections and remote CI remain UNVERIFIED |
| G/G+ | Costs, outcome tracker, frozen history, edge statistics and vector/cache foundations | Work in progress; remaining report/replay/data wiring/performance gates above; not certified |
| H–K | Configuration/storage foundations and Stage S security services | Setup/service startup/funding/P&L/durable tax/auto/extras remain pending |
| V | Amendment 05 QV, PR, RS, SZ, EX, EG, GV, XA, DQ-02 and remaining PF gates | Scheduled after K; all pending; READY verdict becomes a live-unlock prerequisite |
| W | Amendment 06 LJ, LP, RT, EVT, AC, private lesson/event/journal commands and AX-40 RT health | Scheduled after V; all pending; no source/config self-modification and at least5 healthy RT sessions before live unlock |

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

Paths below are relative to backend/. Combined Stage D gates passed.

| ID | Implementation | Acceptance evidence |
| --- | --- | --- |
| DAT-05 | data/data_layer.py AsyncAlpacaMarketData/BatchBars; agents/indicators.py IndicatorMemo | test_batch_data.py; test_indicator_cache.py; warm 50-symbol request count |
| DAT-06 | data/async_reader.py AsyncTokenBucket/physical-request admission | test_async_reader.py fake-clock burst/429/Retry-After; test_batch_data.py actual page count |
| DAT-07 | data/data_layer.py SIP clamp/completed session; core/config.py ScheduleConfig | test_data_layer.py; test_batch_data.py SIP end, close+30 minutes, NY/DST labels |
| DAT-08 | data/async_reader.py bounded shielded workers; data/boundary.py async account/funding; data/data_layer.py async IEX quote/trade | test_async_reader.py timeout/cancellation/concurrency; test_stage_d_boundaries.py durable worker HALT/no late marks; test_batch_data.py shared IEX budget/no extra ADV fetch |
| DAT-09 | data/news.py providers/NewsStore; core/content.py citation helpers; database.py NewsHeadlineRecord | test_news.py provider-ID/hash dedupe and restart; test_stage_d_boundaries.py provenance/schema/metadata controls; all-table mutation tests |
| DAT-10 | data/corporate_actions.py verified process/effective-date evidence | test_corporate_actions.py unavailable/malformed/future/action-date controls; gap status integration |
| DAT-11 | domain/models.py EarningsInfo; data/earnings.py precedence; risk/risk_cro.py earnings_rule | test_earnings.py precedence/as-of/windows; test_earnings_risk.py confirmed BLOCK/estimated WARN/unknown WARN/proof revalidation |
| DAT-12 | data/manual_broker.py ManualCSVBrokerState; data/broker_state.py account-type crosscheck | test_manual_broker.py CSV/session age/explicit restrictions/order evidence; test_stage_d_boundaries.py mismatched account type durable HALT |

Stage D adds NewsHeadlineRecord to the registered immutable ledger inventory
(19 tables), schema version 3. Fresh databases receive version 3; ordinary
startup refuses version 2 rather than silently adding a table. Stage H supplies
the explicit verified-backup-first additive migration. SEC-73 emergency panic
uses database.prepare_panic_schema on the exact compatible prior inventory,
retaining version 2 and persisting HALTED without a chain-certification claim.
test_security_cli.py covers prior-schema panic, normal refusal and incompatible
table/column/version controls; test_ledger.py applies raw/ORM/REPLACE mutation
controls to the newly registered table too. No owner database was modified.

### Final Stage D gate - 2026-10-05

`python -m pytest -q --cov --cov-branch --cov-report=term-missing --cov-fail-under=100`:
**2,901 passed, one skipped, two warnings**, 404.77 seconds. Risk/state/contracts
reached **100% of 1,253 statements and 402 branches**. Current collection is
2,902 cases; the skipped case is explicit paper integration without credentials.
The warnings are the pinned SDK deprecation and deliberate socket-blocking
positive control. The first whole attempt had one ambient-Decimal-context
indicator validation failure; it was fixed, the 87-case scanner/indicator gate
passed, and the entire suite was rerun green. Focused counts are not summed
into a fabricated whole-suite count.

Ruff lint/format (112 authored files), strict typing (112 sources), source guard,
production Bandit (zero findings), pip check, unchanged 121-pin dev-lock audit,
authored secret scan (zero findings), and all five Git-root hooks passed.
Warm 50-symbol plus benchmark scan: one physical bar GET for the new session;
repeat scan: zero. SDK pagination/quotes/news/actions share the physical budget.
Final full-history scan is recorded after the local stage commit.

Actual paper/news/action services, paid NewsAPI terms, owner keyring/permissions,
PostgreSQL/Docker/mutation and remote CI remain UNVERIFIED with reproduction
commands below and in VERIFY.md/RUNBOOK.md. No order or money-movement calls
exist; mode remains MANUAL with paper defaults. There are no extra features
or suggestions. Stage E adds only the amended deterministic research scope.

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
Command after keys: `python -m pytest -m integration --paper-integration-env-file PRIVATE_PAPER_CONFIG`.
The file is read only when explicitly selected. Default tests do not read real
dotenv files or the owner's native keyring. The connected test never places an order.
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
