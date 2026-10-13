# Stage W safety review - GREEN OFFLINE

The current W/write boundary selection passed 159 cases. Whole strict types,
Ruff/format, the execution/write guards, five actual root hooks, production
Bandit, pinned dependency audits and redacted full-history secret scan pass.
The final whole-suite certificate is 5,316 passes / 59 skips / 100% required
critical branch coverage (7,624 statements, 2,606 branches). Fixed replay,
warm scan and RT fake performance also pass, for 5,319 available distinct passes.
STATUS/VERIFY hold the exact evidence. The Stage J review below is historical.

| W failure route | Applied protection | Evidence |
| --- | --- | --- |
| One news transport failure erases a healthy other transport | Preserve genuinely fresh shared heartbeat; failures never refresh it | test_w_recovery: 119s/121s boundaries |
| Private notice failure loses a held flag or duplicates it | Separate received/flag/delivered receipts; durable retry | test_w_recovery: one FLAG, retry, one delivery; halt never AX-29 |
| Old entry news becomes the cause of a later loss | Separate opening tags from causal loss-day/during-hold event receipts | test_w_recovery: actual split loss, timestamp/symbol binding, backdated receipt refusal, stable replay |
| Closing snapshots falsely satisfy five feed sessions | Whole XNYS open-to-close samples, maximum gaps and explicit outage refusal | test_w_core: five sessions, missing open/closing-only/gap controls |
| Learning silently modifies trading | Typed fixed proposals only, owner review, registered QV caps, AST positive controls | test_w_learning_feeds, test_w_integration, test_write_guard |
| Context subgroups inflate total trade counts | Base totals exclude overlapping event/filter cards | test_w_event_reports; existing weekly/equity regressions |

Unknown excursions, gap-open prices and unassigned external holdings remain
unknown; authenticated feeds, real paper behavior and host protections remain
UNVERIFIED. No credentials, owner DB or real orders were used by these tests.

## Retained Stage J safety review - GREEN OFFLINE with owner deferral

Final cumulative gate: 4,266 passes, 52 unavailable service checks skipped,
100% required branch coverage (5,244 statements / 1,684 branches). The fixed
replay passed in 75.600s with 443 decisions and unchanged H proof hash. All five
local pre-commit hooks pass. Real services/platform integrations stay UNVERIFIED.
Owner declined manual CSV and the host evidence file on Oct 8 2026. Primary
state/funding stay ALPACA only; MANUAL_CSV refuses before files, provider calls
or cached returns. Its Amendment 02 acceptance is DEFERRED by owner decision.
No extra input feature was built. Stage I follows the local green commit.

| Failure route | Applied protection | Evidence |
| --- | --- | --- |
| A disabled manual source accesses a file or cached context | Explicit ALPACA guards, unconditional disabled adapter boundaries; no manual file-read implementation | test_manual_broker.py; test_accounting_service.py; test_doctor.py; test_tax_cli.py |
| Current cash hides missing opening transactions | Complete bound activities, current holdings reconciliation and verified book hash before publishing | test_accounting_service.py; test_tax_cli.py |
| Duplicate activity scales risk baselines twice | Stable IDs/content checks and atomic ledger/state transaction; restart dedupe | test_funding_and_pnl.py; test_accounting_service.py |
| A failed book suppresses an urgent withdrawal warning | Attempt the withdrawal notice before later reconciliation; durable acknowledgement | test_accounting_service.py |
| Faulted accounting traps held-position warnings | Monitor catches accounting failure, persists HALT and still checks held quotes/capped exits | test_desk_jobs.py; test_host_runtime.py |
| Deposits appear to be profitable trades | Exact external-flow subtraction, specified return denominator, separate cohort/account TWR | test_funding_and_pnl.py |
| A report invents historic cash or a missing session | Evidence-based COMPUTED reconstruction; no unknown close/fee substitution | test_accounting_service.py |
| Compliance and tax use conflicting wash rules | One matcher in tax/lots.py; risk compatibility import only | unchanged test_wash_sales.py; test_tax_guards.py |
| Sold slices replace their own wash loss | Final inventory excludes sold siblings, shared replacement capacity, chained basis/tacking | test_tax_accounting.py; test_wash_sales.py |
| Actual FEE activity gets charged again as modeled fees | Exact attribution/conservation checks; typed refusal for ambiguity or unverified credits | test_accounting_service.py; test_tax_reports.py |
| Paper or another account enters a real return | Account/env binding in history, events, book, manifests and exports | test_tax_cli.py; test_tax_reports.py; test_tax_guards.py |
| Forged accounting evidence renders a plausible CSV | Rebuild the book, compare its hash and require latest successful reconciliation after checkpoint | test_tax_reports.py; test_tax_cli.py |
| Corrected imports erase original evidence | Append-only correction versions/manifests; write-once content-addressed outputs | test_tax_accounting.py; test_tax_cli.py; test_ledger.py |
| Untrusted mapping instantiates objects or aliases | Restricted SafeLoader, explicit bounded distinct columns, alias/depth refusal | test_tax_reports.py; reviewed B506 skip |
| Migration destroys old audit history | Exact v2–6 inventories, encrypted verified backup, additive tables and retained chain | test_migrations.py; test_security_cli.py; test_ledger.py |

Known limitations: native manual input is DEFERRED by owner; missing marked-lot
retirement can overstate wash awareness; tied same-side fills use a UUID ordering
that needs actual broker reconciliation; real fee allocation, corporate-action
basis, 1099-B format/lot method and 2026 IRS forms are UNVERIFIED. No claim of
tax-filing readiness, real trading edge or completed host deployment is made.

# Stage H safety review - GREEN OFFLINE

The final cumulative gate passed 4,080 cases with 46 unavailable service checks
skipped. Required branch coverage, including the entire evaluation package,
is 100% (4,168 statements / 1,346 branches). The fixed replay passed separately.
All five local Git-root pre-commit hooks passed. Real deployment/services remain
UNVERIFIED; the following review covers implemented offline boundaries.

H's final regression passed. No connected owner check is claimed.

| Failure route | Applied protection | Evidence |
| --- | --- | --- |
| Setup saves an unchecked key after a skipped test | Skip unsets the credential and labels UNVERIFIED; final confirmation and reversible keyring/files apply | test_setup_wizard.py; test_host_config.py |
| Cancellation deletes audit evidence | Settings/secret rollback leaves append-only events and records cancellation; later startup detects drift | test_setup_wizard.py; test_security_cli.py |
| Two desktop/service processes operate one ledger | Actual OS-held byte/flock lock for the whole CLI lifecycle; release on exception/crash | test_process_health.py; test_security_cli.py |
| A stale heartbeat pretends to prove service health | Exact bounded UTC schema, three-minute freshness, paper/scheduler flags and a held OS lock; no config/keyring/DB reads | test_process_health.py; test_security_cli.py |
| Shutdown closes the DB before pending jobs audit their cancellations | Stop dispatch, await canceled jobs, drain admitted SDK threads, independently attempt polling/resources, durable failed-cleanup HALT | test_host_runtime.py; test_async_reader.py |
| Restart silently clears a halt | State startup verifies projection/chain; initial notice includes saved state/reason, never resets it | test_host_runtime.py |
| Urgent delivery disappears after a network error | Bounded thread-safe queue retains its head until confirmed, logs failure, HALTs and lets heartbeat expire | test_host_runtime.py |
| Linux secret-store IPC bypasses general network policy | Thread-local synchronous store-only capability for exact owned Unix user bus; no other threads/families/endpoints/listeners | test_native_ipc.py; test_egress.py; test_secrets.py |
| A saved empty history becomes a safe account assumption | Typed account/cohort-bound complete context; absent, stale, malformed or extra fields refuse | test_account_context.py; test_security_cli.py; J producer pending |
| Long scans reuse stale portfolio/quote evidence | Per-proposal bound refresh repeats hunter before research; changed identity or snapshot refuses | test_desk_jobs.py; existing CRO/swarm fresh evidence tests |
| A schema upgrade silently rewrites the past | Exact known layouts only; encrypted authenticated backup/scratch restore first; additive DDL and version evidence | test_migrations.py; test_ledger.py |
| Backups/log cleanup deletes unrelated or corrupt files | Direct owned paths, authentication before backup pruning, exact log names and age/size bounds | test_backups.py; test_watchdog_maintenance.py; test_logging.py |
| Old dependency success conceals a new lock or partial audit | Actual complete platform inventory and clean output; both lock hashes rechecked and bound in dated event; doctor compares current hashes | test_dependency_audit.py; actual 62/141-pin JSON audits |
| A public SBOM is read as application configuration | Generated build/sbom output in the existing artifact directory; authored source/config scans unchanged | test_supply_chain_h.py; full source guard |
| CI exists only in a nested folder GitHub cannot reach | Actual Git-root workflows and byte-identical project mirrors, SHA pins and read permissions | test_supply_chain_h.py |
| Reports trust a valid row that violates portfolio conservation | Independent cash/held-share/split checks after outcome validation; 100% evaluation branch gate in both CI mirrors | test_evaluation_equity_guards.py; test_evaluation_replay_portfolio_guards.py; test_evaluation_remaining_proofs.py |
| A forged publication changes counts, dates or accounting policy | Bind exact report membership, metric counts, source hashes, account/cohort, costs and earliest equity; typed refusal | test_evaluation_safety.py; test_evaluation_report_safety.py; test_evaluation_source_safety.py; test_evaluation_ledger_safety.py |

Known limits: multiple configuration renames are reversible on caught faults,
not power-loss atomic; native Windows/Linux owner checks and real Telegram remain
unverified; optional PostgreSQL upgrade is refused. Restricted Docker lacks a
native secret store and refuses connected startup. Systemd must preserve the
read-only user bus and requires the user's unlocked Secret Service. Planned
ticket stops are never called broker stop coverage. Weekly reports need current
sealed history; J's later history producer still needs real-service verification.
No real credentials, bank operations, orders, deployment or source self-writes.

# Stage G/G+ safety review

This review covers the implemented offline boundary. The final cumulative gate
passed 3,709 cases; the separate fixed replay perf case also passed. Real connections, Linux mutation
testing, PostgreSQL and container execution remain UNVERIFIED. There is no
broker order execution code before Stage I. Retained Stage F controls follow
the applied Stage G protections.

| Failure route | Applied protection | Evidence |
| --- | --- | --- |
| Old data gets relabeled as another adjustment | RAW/SPLIT/ALL cache keys; SPLIT signals and observed fills, RAW audit, ALL peers | test_adjustment_data.py; test_fill_polling.py including ALL-only refusal |
| Malformed bars silently produce a setup | Full OHLC/session/sequence checks, SUSPECT evidence and durable HALT | test_data_layer.py; test_adjustment_data.py |
| Known splits change old ledger levels | Durable split epochs invalidate derived caches and require fresh data; immutable ledger | test_split_epochs.py; test_causal_cache.py |
| Later actions leak into earlier signals | Causal RAW history and known splits; adjacent ALL/SPLIT distribution factors cancel future factors | test_causal_cache.py; test_replay_dividends.py |
| Estimated distributions fund entries | Estimates accrue outside settled entry cash; require proportional evidence and held whole shares; tracker excludes them | test_replay_dividends.py; test_weekly_equity.py |
| Touches, unlimited fills or favorable bar order invent returns | Cent trade-through, one-percent participation, first partial only, stop first, gap and next-open exits | test_costs.py; test_outcomes_history.py |
| Future cost evidence rewrites a proposal | Persist and use original ATR, median dollar volume, expiry and measured spread | test_ledger_weekly_source.py; test_ledger_evaluation.py |
| Missing evidence counts as a pass | Typed unavailability, dated fees, conservative floors; missing fundamentals skip candidates | test_historical_spread.py; test_costs.py; test_frozen_filings.py |
| Reports invent delivered alerts or vetoes | Verified ledger plus actual alert lifecycle/CRO veto binding; refuse legacy unbound proposals | test_ledger_evaluation.py; test_ledger_weekly_source.py |
| Aggregate results lose individual proof | Immutable per-alert outcomes; validate sets, counts, yearly sums, hashes, account and mode | test_weekly_publication.py; test_ledger_weekly_source.py |
| Paper/live/replay results mix | Separate cohort identity in outcomes, cards, taxes, publications and commands | test_edge.py; test_weekly_publication.py; test_weekly_equity.py |
| Small or in-sample results become proven edges | Strict sample/CI/PF thresholds; no-loss PF unavailable; in-sample replay UNPROVEN; validation remains V | test_edge.py; test_edge_statistics.py |
| Settlement or halts are ignored | Exact sequential cash and T+1; cancel halted entries; valid held stop/exit paths continue | test_replay_gates.py; test_weekly_equity.py |
| Workers or caches change decisions | Shared hunter/CRO, sorted merge, one-versus-four hash parity, vector/reference goldens | test_replay.py; test_vectorized.py; test_npz_cache.py |
| Cache decoding executes code or exceeds limits | No pickle, bounded NPZ inventory/decoded bytes, readonly arrays, verified hashes | test_npz_cache.py; test_causal_cache.py |
| Replay touches owner DB or trading | Explicit sealed files or labeled fixtures, protected paths; no provider, LLM, ledger or executor composition | test_replay_cli.py; test_replay_gates.py; test_no_order_exec.py |
| Absent security checks look successful | Latest PASS/FAIL/UNVERIFIED, UNKNOWN ages and verified anchor; no guessed dates | test_weekly_security.py |
| Saved text bypasses current masking | Revalidate stored proof and render with current private-command policy | test_weekly_publication.py; test_weekly_security.py |
| Canceled publication commits a result | Cancellation checks before files and ledger event, failure HALT, write-once proof | test_weekly_publication.py |

## Retained Stage F controls

| Failure route | Applied protection | Evidence |
| --- | --- | --- |
| An invented score, price or quantity reaches the swarm | Reconstruct the immutable bar cache and rerun the same hunter; reject any changed candidate | test_swarm_and_callbacks.py cache/hunter tampering cases |
| A future or prematurely fetched SIP bar becomes research evidence | Bound source sequence/time and enforce the 16-minute SIP completion lag | test_swarm_and_callbacks.py provenance/lag cases |
| Missing financial metrics are represented as passes | Exact deterministic ratios and an explicit INCOMPLETE framework; require mode drops unavailable evidence | test_fundamentals.py; test_swarm_and_callbacks.py |
| Headline instructions change trade values | Public-only typed LLM input, no tools, finite output and bounded citations; code retains every trade decision | test_llm_client.py; test_swarm_and_callbacks.py; test_dry_run.py |
| A provider outage yields an actionable neutral result | Expected unavailability remains explicit; unexpected/invalid data durably halts | test_swarm_and_callbacks.py; test_scheduler.py |
| An outsider guesses or reuses a callback | Allowlisted private user, action HMAC, exact original chat/message binding and immutable configuration identity | test_swarm_and_callbacks.py; test_telegram_flow.py |
| Two phones approve one card at once | Shared serialized gate plus atomic ticket/approval writer and unique alert constraint | test_swarm_and_callbacks.py concurrent approval cases |
| Details or placement buttons approve indirectly | Details is read-only; P/S require an existing approved ticket and are single-use | test_swarm_and_callbacks.py; test_telegram_flow.py |
| Cached account or quote data approves a changed setup | Fetch fresh account-bound IEX data; rerun CRO/CMP/fundamentals; recheck time and state inside the writer | test_swarm_and_callbacks.py fresh-source and expiry/phone-halt races |
| The phone halts during a slow revalidation but an entry ticket commits | Concurrent update slots preserve phone command handling; transactional state recheck blocks entry | test_swarm_and_callbacks.py halt during checks; test_telegram_flow.py |
| HALTED blocks a valid manual held exit | Entry checks are conditional on side; reductions remain capped by fresh held shares | test_swarm_and_callbacks.py manual SELL; test_position_monitor.py; test_desk_jobs.py |
| Quiet hours hide a stop breach or enable an expired card | Urgent notices bypass the queue; expiry consumes the card and removes actions, including during HALT | test_telegram_flow.py; test_desk_jobs.py |
| Delivery ambiguity triggers repeated actionable messages | Delivery failure halts and records evidence; no retry after ambiguity; only confirmed SENT provenance is actionable | test_telegram_flow.py failed delivery and replay cases |
| A webhook intercepts updates or old updates are silently discarded | Polling admission refuses any webhook and never deletes it; pending updates are preserved | test_telegram_flow.py startup admission cases |
| Unsafe text leaks HTML or loses risk evidence at the message limit | Escape all public text, measure UTF-16 boundaries, split read-only details and refuse oversized cards | test_swarm_and_callbacks.py; test_telegram_flow.py; test_desk_jobs.py |
| Changed policy or lost delivery provenance edits a trusted card | Reject configuration mismatch and missing binding, durably halt, retain original card identity | test_telegram_flow.py changed-policy/lost-annotation cases |
| Expiry cleanup races another consumer and recreates actions | Re-read the latest state inside the serialized writer; terminal states remain terminal | test_telegram_flow.py expiry writer-consumption case |
| An open-ticket warning claims a SIP quote is IEX | Revalidate a typed symbol/feed wrapper at the source boundary | test_desk_jobs.py wrong feed/symbol; test_position_monitor.py |
| News requests use another account's or stale holdings | Bind the portfolio account and timestamp before deriving the symbol list | test_desk_jobs.py wrong/stale/future holdings cases |
| A duplicate, oversized or changed broker fill is attributed twice | Atomic immutable fill proof, ticket capacity/price/validity and broker-order binding; changed IDs halt | test_fill_polling.py |
| An unmatched manual fill is given a fictitious entry or stop | Persist an observed MANUAL signal with public snapshot provenance, never an invented trade ticket | test_fill_polling.py unmatched/manual cases |
| Scheduled jobs overlap or a failure disappears | Single-instance locks and six bounded jobs; append PASS/FAIL/SKIPPED JobRun evidence | test_scheduler.py; test_desk_jobs.py |
| A future code change opens an order or funding route | Full AST negative and positive controls over all authored Python; no executor exists | test_no_order_exec.py and core/source_guard.py |

Stage H now supplies host startup, notifier wiring, encrypted scheduled
maintenance and watchdog. J supplies the later history composition under final
checks; fake providers do not certify real connections. Emergency drills remain
K, registered validation V and realtime feed health W.
