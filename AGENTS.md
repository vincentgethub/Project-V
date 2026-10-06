# Project V / vws-core

The owner's latest instructions and these specifications govern this repository:
- [Master spec](vws-core/docs/spec/MASTER_SPEC.md)
- [Amendment 01](vws-core/docs/spec/AMENDMENT_01.md)
- [Amendment 02](vws-core/docs/spec/AMENDMENT_02.md)
- [Amendment 03](vws-core/docs/spec/AMENDMENT_03.md)
- [Amendment 04](vws-core/docs/spec/AMENDMENT_04.md)
- [Amendment 05](vws-core/docs/spec/AMENDMENT_05.md)
- [Amendment 06](vws-core/docs/spec/AMENDMENT_06.md)
- [Owner tax profile](vws-core/docs/spec/TAX_PROFILE.md)

Later amendments override conflicts in earlier specifications/addenda. The
earlier LLM fundamental framework is superseded by Amendment 01 section 4.2.
Amendment 04 was replaced verbatim by the owner's October 6 attachment; its
revised wizard order, skip behavior and full private progress page now apply.
Build only specified features. Put optional ideas at the bottom of PROGRESS.md
under Suggestions: purpose, benefit, risk, effort. Wait for the owner's plain-
words approval before implementing them. Never suggest weakening safety.

Work order: Step 0 audit/fixes, Stage S, finish D, E, F, G with G+, H, J, I, K, V, W.
Amendment 05 puts cost/data-quality/performance/edge reporting in open Stage G;
walk-forward validation, overlays, exit variants and readiness verdict follow K.
Its later READY verdict prerequisite also applies to any live unlock. No
optimization or generated parameter combinations; overlays only reduce size.
Amendment 06 adds Stage W after V. The running process never writes its own
source, settings, fees, variants or risk rules. Lessons are proposals for owner
review and registered validation only. Required healthy realtime feeds for at
least five sessions are an additional live-unlock prerequisite.
After each green stage, post at most 25 lines, make a local Git commit, continue
automatically. Never push unless asked. Stop only for the amendment's explicit
conditions: unresolved gate after a genuine fix attempt, required credential or
owner decision, a STOP-class issue, or a safety weakening.

Report real gate counts. UNVERIFIED is never PASS. Unavailable local mutation,
PostgreSQL, Docker and paper integration checks get exact reproduction commands;
run supported gates in CI. Do not read real dotenv files implicitly in tests.

Keep docs/STATUS.md technical with requirement-to-code-to-test traceability.
Rewrite docs/PROGRESS.md after each stage in the same commit; at most 60 lines,
plain words, seven specified sections in order, then Suggestions. The stage
report's final line is: PROGRESS.md updated.

Safety rules:
- MANUAL + paper defaults. Telegram can only downgrade modes. Mode upgrades,
  resets and live unlocks happen on the host with the required explicit phrases.
- Before Stage I there is no order execution code. Stage I permits only the
  specified order calls in backend/execution/alpaca_executor.py, reachable only
  in AUTO_*; MANUAL never imports it. Keep the full AST positive controls.
- No money movement anywhere, including crypto wallets, ACH, transfers, journals
  and bank linking. Funding is detected, never initiated. No market entries,
  options, shorting or leverage. Every auto position needs broker stop coverage.
- Idempotent client_order_id; after ambiguity look it up before any retry.
- Paper/live keys, endpoint, account and reports stay bound and separate.
- AUTO_LIVE requires history, report, Stage J, drill, explicit unlock, ceilings,
  security prerequisites and the capital ramp. Never enable it silently.
- Halts stop entries; never trap valid held exits or stop protection. Cap sells
  at held shares. Reconciliation mismatches halt. Withdrawals notify urgently.
- Daily loss blocks entries for the session; drawdown/fault halts latch until
  audited operator reset. External cash flows scale equity baselines.
- LLMs interpret public evidence only; code sets metrics, statuses, scores,
  levels, quantities, risk and approval. No tools or account data in prompts.
- LLM off by default, finite typed output, bounded strings, injection defense,
  atomic budget reservations. Never count unavailable evidence as a pass.
- Exact Decimal money, cents at price boundaries, integer shares. Float64 only
  inside indicators. UTC storage, injected clocks, CT display. Pure risk rules.
- Frozen extra-forbid models; revalidate at boundaries. Unknown/invalid/stale
  input fails closed with typed errors, audit evidence and required durable HALT.
- Append-only ledger and additive migrations; never rewrite/delete ledger rows.
  Back up before migrations; encrypted verified backups and ledger anchors.
- One wash-sale engine for compliance/tax; 1099-B authoritative, estimates marked.
- Banned removed Alpaca fields live only in the guard constants list; never read
  them. Verify pinned SDK calls; explicit feed, SIP end safely delayed.
- HTTPS allowlisted egress, verified TLS, explicit timeouts, bounded retries,
  SDK backstop and no inbound ports. Keyring secrets and redacted tracebacks.
- Private Telegram chats, allowlist + HMAC + message binding, atomic single use,
  rate limits, no reset or upgrade from Telegram.
- Hash-pinned dependencies, SHA-pinned CI actions, least privilege, audits.
- No hype, expected-profit claims, parameter search, extra servers or dashboards.
