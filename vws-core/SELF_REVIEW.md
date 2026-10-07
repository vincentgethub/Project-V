# Stage F safety review

This review covers the implemented offline boundary. Real connections, Linux
mutation testing, PostgreSQL and container execution remain UNVERIFIED. There
is no broker order execution code before Stage I. The fixes below are applied;
they are exercised by the named tests, rather than treated as future promises.

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

Connected orchestration still needs Stage H's host startup, notifier wiring,
encrypted scheduled maintenance and watchdog. Weekly outcome/report production
is Stage G. Current constructors require those dependencies; fake test bodies
are labelled as such and do not certify deployment readiness.
