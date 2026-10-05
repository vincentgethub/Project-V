# ASSUMPTIONS

The master specification and Amendments 01–04 in docs/spec govern this project.
Later amendments override conflicting earlier specifications and addenda. The
earlier LLM fundamental addendum is superseded by deterministic Stage E rules.
The owner authorized automatic continuation: audit/fixes → S → D → E → F → G → H
→ J → I → K, with a report and local commit after each green stage. Required
credentials/decisions, an unresolved gate, a STOP-class finding or a safety
weakening stops progress. No push is authorized.

Stages A–C have historical verified deliveries. The current audited baseline ran
1,866 offline tests; audit corrections are under final verification. Stage D is
unfinished under the amended requirements. Order execution is absent before
Stage I; current ledger orders are local proposal/audit records. Stage I alone
may add the specified isolated executor. Money movement remains banned everywhere.

1. Financial inputs are exact decimal text, integers or Decimal. R-13 price
   boundaries specifically require positive Decimal cent prices; quantities are
   whole integers. Indicator math alone may use float64 in later stages.
2. Sub-cent proposed prices are rejected rather than silently rounded. General
   money, costs and balances retain millionths in signed 64-bit storage.
3. Settings never load a real `.env` implicitly. Secret-bearing database URLs are
   SecretStr. Their non-secret identity participates in configuration hashing.
4. Protective minima cannot be reduced below the blueprint defaults: the checking
   buffer, cash reserve, minimum price, slippage allowance and margin equity floor.
   Unspecified absolute bounds are documented in config source.
5. SQLite is the local default. PostgreSQL-compatible SQL, row locks and triggers
   are supplied; PostgreSQL runtime verification is separately reported.
6. Audit tables are append-only. Two deliberately mutable singleton rows allocate
   sequence numbers and project current operating state. Verification reconciles
   the projection with immutable transition events.
7. A database or notifier fault also latches the current process HALTED. Persisting
   a halt cannot be guaranteed while storage itself is unavailable; failure is
   surfaced and no approval can rely on that process state.
8. Only an attributed operator reset lowers a latched operating state. A recovered
   quote, restart or new session alone never clears a halt.
9. XNYS sessions are bounded by an explicit calendar range. Dates outside that
   range fail closed; timestamps at the exact close belong to a completed session.
   T+1 starts from a verified trading session, with holidays and early closes honored.
10. Supplied CSVs are sample configuration, not an authoritative production
    instrument universe or current ETF weights. Unknown instruments fail closed.
11. The checking-buffer gate caps new funding only. It never moves bank money and
    does not treat checking funds as already settled brokerage cash.
12. Valid held-position reductions bypass entry-specific market, funding and
    concentration checks. The HALTED/manual exception remains explicit.
13. A pure CRO returns decisions and evidence. Persistence, state escalation,
    notifications and veto logging happen in the enclosing gate.
14. Alpaca does not provide a settled-cash field in the required account contract.
    Cash-account purchases need an injected settlement ledger; absent proof means
    zero settled cash.
15. Plaid Balance is not a standalone Link/Sandbox initialization product. Sandbox
    setup uses the supported Auth entitlement to obtain an Item token; application
    runtime calls only the balance endpoint. No Auth data retrieval or funding exists.
16. The account-schema test fixture is synthetic and follows verified current
    fields. It is not misrepresented as a captured live account response. A genuine
    sanitized recording requires credentials and remains an integration check.

Stage-specific additions and unresolved verification items are recorded with each
delivery and in VERIFY.md.

17. BROKER_ACCOUNT_TYPE is required with no default. Isolated tests explicitly
    inject synthetic CASH, which is not an attestation about the owner's account.
    Offline core tests otherwise need no connected credentials. Connected
    startup must call assert_research_ready() and/or assert_telegram_ready(). The
    model, credentials, nonempty user allowlist, and >=32-byte callback secret
    have no usable offline defaults. No model name is hard-coded.
18. Zero LLM daily budget disables calls. Explicit verified input/output token
    rates plus assert_llm_call_budget_ready() are also required. Stage E implements
    actual calls and budget accounting; no cost is guessed.
19. Historical Stage A source bounds resolved unspecified ceilings: setup
    score 6..10, cooldown 1..30 sessions, LLM budget 0..1,000 USD/day, timeout 1..60
    seconds, max tokens 1..8,192. YAML is separate, frozen, exact Decimal, rejects
    risk keys/duplicates/anchors/aliases/oversize/depth >20, and requires an explicit
    instrument allowlist. Criterion weights support at most six decimal places.
    with_yaml_hash() combines the validated YAML with nonsecret environment policy.
    Amendment 01 supersedes the historical LLM budget ceiling with 20 USD/day;
    Stage E must enforce the amended optional-LLM configuration and accounting.
    Schedule and alert-cooldown bounds now belong exclusively to YAML, not env.
20. Alert.id is the stable alert ID. PENDING means not yet delivered; an append-only
    AlertEvent SENT makes the awaiting-human alert actionable. This resolves the
    spec's ambiguous requirement that a delivered alert still be called PENDING.
    Terminal statuses are new events. Chat/message IDs belong to delivery evidence.
21. Manual approval and its ticket commit atomically; a unique alert FK makes
    tickets single-use. Exact ticket values come from the linked local proposal.
    Ledger.record_trade_ticket() is a low-level persistence primitive: Stage F
    must authenticate the human and revalidate fresh data before calling it.
22. Schema version 2 rejects old/incompatible databases; no silent migration is
    performed. Use a new development database or an explicitly reviewed migration.
    PostgreSQL is schema-compatible but no server runtime test is claimed.
    Administrators can disable triggers/rewrite evidence; this is not a claim of
    protection from a privileged database owner.
23. Every halt invokes a notifier. Repeated successful redacted state/reason
    messages are deduplicated for a local halt episode; failed delivery is retried.
    Daily loss is a session-scoped ENTRY/ADD block through the next XNYS session
    open, not a latched state transition. Drawdown tiers and fault HALTs remain
    latched until explicit operator reset.
24. The AST guard scans every authored Python file including tests/scripts/drafts;
    only execution_policy.py's banned-list constants are exempt. Generated virtual
    environments/caches/vendor dependencies are not authored repository sources.
    Builtin compile is banned; re.compile is permitted regex construction.
25. Stage D's existing data providers, indicators and scanner form the audited
    baseline, not completion of the amended Stage D scope. The older core/gate.py
    remains uncertified as a human-approval boundary.
    The current Git root is Project V, so a root CI workflow mirrors the requested
    project workflow, pre-commit configuration, and .gitignore. These support
    nested or standalone project checkouts.

26. Stage B adds required proposal expires_at and optional target_price. An ENTRY
    or ADD target, when supplied, must exceed the limit. Prices require Decimal
    cents even in model validation; JSON/API adapters must decode exact Decimal
    values before entering these contracts. Float prices and sub-cent prices fail.
27. Existing Pydantic instances, including nested positions/orders, are revalidated
    at risk ingress. Policy and registry mappings are detached/revalidated at CRO
    construction. The service objects and compiled calendar are trusted injected
    dependencies; callers must not reassign their policy references during use.
28. High-water and daily-start marks must already be persisted and positive. Zero
    is missing evidence and recommends HALTED. First-run initialization belongs
    outside the pure CRO and must explicitly persist actual equity as the baseline.
29. Unconfigured known sectors use a 35% cap; unconfigured themes use zero. Unknown
    sectors block. An ETF with complete verified look-through to known sectors may
    have UNKNOWN declared sector; without weights its declared sector is 100%.
30. Pending BUY notional reserves concentration, gross exposure and cash. Pending
    SELL quantities reserve inventory and never release exposure before a fill.
    Same-name pending BUY stop risk uses its supplied stop; an absent stop reserves
    the full notional as loss. ADD also covers existing shares at the proposed stop.
31. max_allowed_qty is advisory and never exceeds requested qty. It finds the
    largest whole quantity satisfying complete CRO-02..08 evidence; it does not
    certify earnings, funding, operating state, or later compliance approval.
32. Unknown earnings is an explicit failed WARN. A known past date blocks as
    unresolved. A non-session earnings date includes the preceding exchange session
    plus the configured prior sessions. UTC blackout windows include both endpoints.
33. Verifiable exits bypass entry gates but still require matching accounts,
    live proposal lifetime, fresh inventory, and held minus pending SELL quantity.
    Snapshot freshness uses the quote TTL; stale holdings cannot prove held qty.
34. recommended_state is a typed Verdict extension carrying a pure CRO tier to
    RiskBoundary for persistence. A new financial HALT does not retroactively trap
    a valid held exit from a permitted starting state. Later HALTED calls require
    MANUAL source. A fatal batch result also gates subsequent entries in that batch.
35. RiskBoundary checks current state before and after evaluation, consumes the
    persisted escalation result, logs each blocking veto, and halts on any fault.
    Its Verdict is research evidence. The Stage F human gate still needs fresh
    revalidation and atomic state checks when writing alert/ticket evidence.
36. MarketContext carries no symbol field in the specified contract. Stage D's
    per-symbol provider must bind its returned market data to the requested symbol.
    Stage B never fetches data or substitutes default quote/funding evidence.
37. ProviderResult and research output contracts, read-only data providers,
    indicators and the deterministic scanner are present. Amended data additions,
    research agents, optional LLM clients, scheduler and Telegram remain pending.
    LLMs cannot set metrics, pass/fail status, trade levels/qty, setup score or a
    CRO decision. The fundamental prompt is narrative-only.

38. Stage C's account taxonomy attests accounts belonging to the same taxpayer.
    The supplied history must include relevant-window purchases/dispositions,
    DRIP, other accounts, and the original BUY for explicitly referenced lots.
    The software cannot discover omitted spouse/entity accounts or future trades.
    Substantially identical groups remain explicit operator-reviewed metadata.
39. TradeRecord.price remains strict Decimal cents; TaxLot.cost_basis, realized
    losses and adjusted tax basis retain micro-unit money. Prior adjustments can
    create fractional-cent basis, so basis is not silently rounded to a price.
    Fractional-share DRIP evidence is unverifiable under this whole-share contract.
40. A loss sale represents one original acquisition lot and attests its realized
    loss after previous basis adjustments. Aggregate multi-lot losses must be split.
    acquired_at is the actual purchase timestamp. An earlier holding_period_start
    represents prior tacking and requires acquisition_trade_id. Untacked origins
    absent from a relevant window can be attested older acquisitions; ambiguous
    missing lineage or simultaneous trades with unresolved disposal order fail.
41. Wash matching uses disjoint replacement-share intervals shared across loss
    sales. Already disposed shares and the sold lot's original purchase are not
    replacements. Proportional micro allocations reconcile cumulatively; an amount
    below supported precision raises rather than erasing a wash flag. Prior basis
    and tacking must already be reflected in the caller's executed loss evidence.
42. IRA/Roth replacement losses are permanent and do not increase retirement basis.
    Form 8949 exports matched sale slices with code W and positive adjustments.
    Column (b) uses actual acquisition date, separate from tacked holding duration.
    Unmatched shares remain separate broker reconciliation rows; these exports do
    not constitute a complete tax return or replace cross-account verification.
43. Settlement and wash dates use New York calendar dates; T+1 uses bounded XNYS
    sessions. Reconstructed sale proceeds and date-only funding evidence become
    usable at settlement-session close. Confirmed broker settled cash may establish
    earlier availability. Missing funding evidence WARNs a verifiable exit; a
    non-session or out-of-range settlement date is unverifiable and requests HALT.
44. INTRADAY_MARGIN is default. LEGACY_PDT remains an explicit broker-transition
    policy. The conservative counter maximizes distinct same-day opening orders
    touched by available closing shares, counting an opening order only once
    across partial sales. This upper bound can exceed a broker's actual method.
    Partial fills must first be consolidated into one executed-order TradeRecord.
    The legacy entry guard is inclusive at three completed day trades and applies
    below $25,000 in a margin account; exits retain WARN findings.
45. ComplianceEngine.check() preserves the specified list-of-RuleResult API.
    assess() adds frozen provenance, input_hash, and recommended_state. The full
    input hash binds proposal values, snapshot, lots, history, account taxonomy,
    flags, instruments, identical groups and restricted symbols. Settings retain
    the master settings-only config_hash. A malformed input can carry a zero
    digest only as restrictive HALTED failure evidence.
46. ComplianceBoundary persists broker/input/provider HALTs and logs every failed
    WARN or BLOCK outside pure rules. Ordinary cash/wash/restriction failures do
    not themselves halt. Valid, fresh held exits receive WARNs even on unknown
    tax/funding context; invalid or oversized sells do not get that exception.
    The later human gate must combine CRO/state and compliance evidence before
    authenticated fresh approval. No standalone compliance result authorizes a ticket.
47. APScheduler 3.11.3 is the stable installed release with AsyncIOScheduler;
    actual scheduling is deferred to Stage F. Full source delivery uses a local
    Markdown artifact: assumptions, SHA-256 manifest, then every file in full.
48. SQLite recursive triggers are explicitly enabled to prevent REPLACE from
    deleting/replacing protected rows. State-control projections are verified
    against immutable events during live reads/transitions, not only at startup.
49. Stage E fundamentals use exact Decimal ratios and cash flow. All five strict
    thresholds must pass: gross margin >0.40, operating margin >0.15, ROIC >0.10,
    FCF >0, interest coverage >3. Missing evidence is not a pass; ETFs, cash
    equivalents and configured exempt sectors have explicit applicability status.
    Code computes the report; an optional LLM only describes it.
50. scan_interval_minutes, offhours_interval_minutes,
    scheduler_misfire_grace_seconds, daily_bar_sip_lag_seconds and
    alert_cooldown_sessions have one YAML home. Startup rejects these keys in
    process env, explicitly loaded dotenv or Settings, even at equal values.
