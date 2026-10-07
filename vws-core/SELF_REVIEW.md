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

Connected orchestration still needs Stage H's host startup, live history-source
composition, notifier wiring, encrypted scheduled maintenance and watchdog.
The Stage G ledger source and publisher exist; fake test providers do not certify
real connections. Actual account/tax activities remain J, emergency drills K,
registered validation V and realtime feed health W.
