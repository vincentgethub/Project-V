# AMENDMENT 01 to MASTER SPEC: vws-core (audit · corrections · completion)

To Codex: this is an addition to the MASTER SPEC you already have, not a replacement. Everything in the MASTER SPEC still applies unless this amendment explicitly changes it. Where they conflict, this amendment wins. Where this amendment conflicts with any earlier pasted addendum, this amendment also wins. That includes the "FUNDAMENTAL ANALYST 5-POINT FRAMEWORK" addendum and any Gemini-authored code or prompts.

## 0. HOW TO USE THIS AMENDMENT

0.1 Persistence: Save this text verbatim to `docs/spec/AMENDMENT_01.md`. If the MASTER SPEC isn't already in the repo, save it to `docs/spec/MASTER_SPEC.md`. Create or update `AGENTS.md` (keep it under 120 lines) with the non-negotiables (§10 here plus MASTER SPEC §12), the precedence rule above, and links to both spec files. That way the rules survive context compaction.

0.2 Execution protocol: This changes MASTER SPEC §0. The user wants you to work to completion without typing a command per stage. Run in this order: **Step 0 (audit) → finish Stage D → E → F → G → H** (§3). After each stage:
- post a stage report of 25 lines or fewer: what changed, the gate command output summary, anything unverified, and the assumptions you made
- make a local git commit (`git init` first if there's no repo)
- continue automatically if the gate is green

Never push to a remote unless the user asks.

0.3 STOP and wait for the user only if one of these happens:
- (a) a stage gate can't be made green after a genuine fix attempt
- (b) the next step needs a credential, an account, or a decision listed in §9
- (c) the audit finds a STOP-class issue (§1.3)
- (d) a change would weaken any safety requirement

When you stop, say exactly what you need.

0.4 Honesty rule: Report anything you could not run (mutmut, PostgreSQL, Docker, live paper API) as UNVERIFIED, with the exact command the user would run. Never describe a check as passing unless it actually ran.

---

## 1. STEP 0: AUDIT BEFORE CHANGING ANYTHING (read-only)

1.1 Produce `docs/STATUS.md` and post a summary that covers:
- Stage status A–D: what exists, which files, and whether Stage D finished (it was in progress when the user last checked).
- Gate results run fresh now: ruff check, ruff format --check, mypy --strict, bandit, pip-audit, detect-secrets, pytest with the MASTER SPEC coverage gate, and the AST no-execution test. Give real counts.
- A traceability matrix (requirement ID → code → test) for every MASTER SPEC requirement implemented so far. Mark missing ones.
- Whether you acted on the earlier "FUNDAMENTAL ANALYST 5-POINT FRAMEWORK" addendum, and what you built for it if anything. It is superseded by §4.2 here.
- Installed versions of alpaca-py, pydantic, pydantic-settings, SQLAlchemy, python-telegram-bot, APScheduler, openai, and exchange_calendars.
- Which items in §1.2 you found, with file:line references.

1.2 Contamination checklist. The user also pasted prompts and code from other chats, and some of it is unsafe. Search the repo and report each hit:
- `response_format=` passed to the LLM client (Anthropic's OpenAI-compatible endpoint ignores it).
- Hard-coded model names such as "gpt-4o".
- URLs containing markdown link syntax, for example `"[https://api.openai.com/v1](...)"`.
- `PLAID_ENV` allowing `"development"`. Plaid decommissioned that environment on 2024-06-20, so the only valid values are `sandbox` and `production`.
- A module-level `settings = Settings()` that reads `.env` at import time, which breaks R-07 ("tests never read a real .env").
- `datetime.now(` / `date.today(` outside `core/clock.py`.
- `float(`, or float literals, in money paths outside indicator math.
- Bare `except:` or `except Exception: pass`.
- Telegram callback parsing with `split("_")`, `parse_mode="Markdown"` (legacy), or any callback handler without allowlist + HMAC + single-use.
- Any LLM output that sets stop, target, entry, qty, score, or a pass/fail flag.
- Any of these identifiers or imports: `ModelAgnosticClient`, `yfinance`, Whale Alert/Etherscan, `langgraph`, `fastapi`, `frontend/`, genetic/breeder modules.
- Truthiness checks on Decimal prices (`if proposal.stop_price:`).
- `seq` columns that rely on non-PK autoincrement (this doesn't work on SQLite).
- Any banned Alpaca field from §2.1.

1.3 STOP-class findings. Report these and stop before building anything new:
- any code path that can submit, replace, or cancel an order, or move money (AMENDMENT 02 later allows order calls ONLY inside `backend/execution/alpaca_executor.py`, built in its Stage I; anything found before then, or anywhere else, is STOP-class)
- secrets committed in git history
- any migration that would rewrite or delete existing ledger rows

Fix everything else from §1.2 in a dedicated commit "audit fixes" before you continue, with regression tests.

---

## 2. CORRECTIONS (apply everywhere)

### 2.1 Verified facts, updated Oct 4 2026 (these override your training data)
- FINRA Rule 4210 intraday-margin amendments were SEC-approved on 2026-04-14 and took effect on 2026-06-04. Firms may phase in until **2027-10-20** (FINRA Regulatory Notice 26-10). Alpaca has already switched to the new framework.
  - Keep `DAY_TRADE_REGIME` configurable for each broker account. `LEGACY_PDT` exists only for brokers still in transition.
  - The standard $2,000 margin minimum still applies (`MIN_MARGIN_EQUITY` 2000 is correct).
- Banned Alpaca fields, removed 2026-07-06 per the Alpaca changelog. Put them in one constant list, and make a test fail if code reads any of them:
  - `pattern_day_trader`, `daytrade_count`, `last_daytrade_count`, `daytrading_buying_power`, `last_daytrading_buying_power`, `bod_dtbp`, `pdt_check`, `dtbp_check`
  - Asset fields removed 2026-09-22: `easy_to_borrow` (use `borrow_status`) and `maintenance_margin_requirement` (use `margin_requirement_long`/`_short`)
- Pin alpaca-py to a release that includes the upstream commit "Tolerate Alpaca's deprecated PDT/DTBP account fields (removed 2026-07-06)". `# VERIFY` the release number on PyPI or GitHub.
- Replace the synthetic `/v2/account` fixture with a sanitized real paper-account recording once keys exist. Until then, keep the synthetic one, marked UNVERIFIED in VERIFY.md.
- Alpaca Basic (free) data plan:
  - Real-time IEX only. SIP queries must have `end` at least 15 minutes in the past, otherwise the API returns "subscription does not permit querying recent SIP data". 200 historical calls/min.
  - Always pass `feed` explicitly. The `latest_*` endpoints on Basic must use `feed=iex`.
  - Daily-bar timestamps are midnight America/New_York of the session date. Convert the timestamp to an NY date to get the session label; never use the UTC date.
- Alpaca News API (`/v1beta1/news`, Benzinga-sourced) works with Alpaca keys and is the default NewsProvider.
  - NewsAPI.org's free plan is 24-hour delayed and limited to development use, so it is only an opt-in paid provider and never the default.
  - RSS is the secondary provider.
- Anthropic's OpenAI-compatible endpoint (`https://api.anthropic.com/v1/`) silently ignores `response_format`. xAI is at `https://api.x.ai/v1`. Keep "JSON requested in the prompt + Pydantic validation" as the only structured-output mechanism.
- APScheduler 3.11.x is the stable line (4.0 is not stable). Use 3.x `AsyncIOScheduler`.
- Plaid `/sandbox/public_token/create` needs non-empty `initial_products`, and `balance` is not a valid value there.
  - Initialize the Sandbox item with `transactions` (or `auth`), then call only `/accounts/balance/get` at runtime. `# VERIFY`.
  - Runtime scope stays balance-only.
- SEC EDGAR APIs (`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`, `data.sec.gov/submissions/CIK##########.json`, ticker map `https://www.sec.gov/files/company_tickers.json`) are free and need no key. They do require a descriptive `User-Agent` with a contact email and a rate of ≤10 requests/s.

### 2.2 The 5-point fundamentals addendum is replaced
The earlier addendum had six problems:
- It had an LLM extract the metrics and set `passed_5_point_framework`, which violates R-11.
- It used `float` types, which violates R-04/R-13.
- It referenced `ModelAgnosticClient`, which doesn't exist in this spec.
- It targeted "Stage C", which here is compliance and is already done.
- It allowed yfinance, an unofficial scraper.
- It ignored companies where the metrics aren't meaningful (banks, insurers, REITs, no-debt firms, negative denominators).

Implement it as deterministic code per §4.2. Keep the user's exact thresholds: gross margin > 40%, operating margin > 15%, ROIC > 10%, FCF > 0, interest coverage > 3x. All comparisons are strict.

### 2.3 Resolutions to the conflicts you raised after the MASTER SPEC
Keep the resolutions you already chose: exits are never blocked by entry-only checks, delivery state is separate from approval state, there is one fresh retry on invalid JSON, and fakes are injected for offline runs. Settle the rest as follows:
- **Daily loss (CRO-10)**: implement it as a session-scoped rule that blocks ENTRY/ADD until the next XNYS session open. It is not a latched system-state transition, so a normal bad day doesn't need a manual reset. Drawdown tiers (CRO-09) and fault halts still latch and need `operator_reset`. If your implementation latches on daily loss, change it and update the tests.
- **Session expiry**: `valid_until` = the close of the N-th XNYS session that closes strictly after `created_at`, where N = `PROPOSAL_TTL_SESSIONS`. That makes an after-close alert valid through the next session's close. Use the calendar's actual close, which handles early closes.
- **Callback security**: hmac16 = the first 16 hex chars of HMAC-SHA256(secret, `"v1|{action}|{proposal_hex}|{chat_id}"`).
  - On click, also require `query.message.chat.id == alert.telegram_chat_id` and `query.message.message_id == alert.telegram_message_id`.
  - Enforce single use atomically with an append-only `alert_decisions` table that has `UNIQUE(alert_id)`. A second insert fails, and the user sees "already handled".
- **LLM cost**: see §4.4. Missing price config means the LLM is disabled, not that calls go unbudgeted.
- **YAML vs env**: env holds only secrets, mode flags, and risk limits. YAML holds schedules, strategy parameters, and the watchlist. Each key has exactly one home. Remove `SCAN_INTERVAL_MINUTES`/`OFFHOURS_INTERVAL_MINUTES` from env, and fail at startup if a key appears in the wrong place.
- **Prompt files**: only LLM-calling roles get prompt files (§4.4). The scanner and hunter are deterministic, so delete `market_scanner.md`, `setup_hunter.md`, and `whale_tracker.md` (or never create them). Change the GD-02 test to: every prompt referenced in code exists, and every prompt file is referenced in code.
- **Real account fixture**: covered in §2.1.
- **Mutation/PostgreSQL/Docker unavailable on this Windows machine**: run them in CI (§4.8). Locally, mark them UNVERIFIED and don't block on them.

### 2.4 Values that win when the pasted sources disagree
The MASTER SPEC values stand: 10% single stock, 1% max risk per trade, 2% daily loss, 8%/12% drawdown tiers, 15 max positions, MIN_SETUP_SCORE 7.0. Ignore the GrokDesk values ("3% daily loss", "max 3 ideas") and the Gemini value ("-5% drawdown"). New: the sizing target is 0.5% risk per trade (`sizing.target_risk_per_trade`), capped by the 1% CRO limit, so rounding and slippage never push a proposal over the cap.

---

## 3. PRIORITY ORDER (stages; gate = all MASTER SPEC gates + this stage's acceptance tests)

| Stage | Scope | Why this order |
|---|---|---|
| Step 0 | Audit + audit fixes (§1) | Know the real state before adding anything |
| D (finish) | MASTER SPEC D + §4.1 data additions | Every later stage depends on correct, fresh data |
| E | Agents as amended: indicators/playbooks (§4.3), fundamentals (§4.2), providers, optional LLM (§4.4) | Deterministic signal generation first; LLM optional |
| F | Swarm, orchestrator (§4.5), Telegram UX + tickets (§4.6), dry run, Docker | User-facing loop |
| G | Evaluation: paper outcome tracker + historical replay (§4.7) | Shows the user whether the alerts are any good before real money is involved |
| H | Ops: doctor, watchdog, backups, CI, deploy units (§4.8) | Unattended reliability |

(AMENDMENT 02 continues after H with J → I → K.)

---

## 4. MODULE SPECS (new or changed)

### 4.1 Data layer additions (Stage D)
- DAT-05 **Batching + caching**:
  - Fetch daily bars for the whole watchlist plus benchmark ETFs (SPY and the sector ETFs used for relative strength) in multi-symbol `StockBarsRequest` calls.
  - Fetch incrementally: only sessions newer than the last stored one.
  - Cache per (symbol, session).
  - Indicators are computed once per session per symbol and memoized.
  - Target: a 50-symbol daily scan uses ≤10 bar API calls when the cache is warm.
- DAT-06 **Rate limiting**: one shared async token bucket for all Alpaca data calls, sized from `ALPACA_DATA_PLAN` (BASIC → 180/min, which leaves 10% headroom; ALGO_TRADER_PLUS → 9,000/min). It works alongside the DAT-04 retries and circuit breaker. A 429 response drains the bucket and honors `Retry-After` when present.
- DAT-07 **SIP end guard**: for `feed=sip`, set `end = min(requested_end, now − 16 min)`. A completed daily bar is requested only after the close plus `schedule.daily_scan_delay_minutes`.
- DAT-08 **Async boundary**: SDK clients are synchronous. Call them through `asyncio.to_thread` with explicit timeouts, and bound concurrency with a semaphore. Nothing blocks the event loop, which Telegram also uses.
- DAT-09 **News**:
  - Providers: `AlpacaNewsProvider` (default), `RssNewsProvider`, `NewsApiProvider` (opt-in), `FakeNewsProvider`.
  - Dedupe by provider id, then by normalized-headline hash.
  - Store headlines with a stable id. These ids are what the LLM and the card cite.
- DAT-10 **Corporate actions**: an Alpaca corporate-actions provider (`# VERIFY` the client and endpoint) feeds DAT-02's "known corporate action" check. If it's unavailable, a gap still marks the symbol SUSPECT. That's fail-closed.
- DAT-11 **Earnings**: `EarningsProvider` returns `EarningsInfo(date|None, status KNOWN|ESTIMATED|UNKNOWN, source)`. Resolve in this order:
  1. `config/earnings_calendar.csv`, a manual override.
  2. An optional third-party provider (`# VERIFY` terms; off by default).
  3. An SEC estimate: from the submissions API, take the last 10-Q/10-K filing date and estimate the next report window as last + 85..100 days.

  Effects:
  - KNOWN within `EARNINGS_BLACKOUT_SESSIONS` → CRO-13 BLOCK.
  - ESTIMATED window overlapping the blackout → WARN only.
  - UNKNOWN → WARN only. Never treat it as clear.
- DAT-12 **Broker state source**: `BROKER_STATE_SOURCE = ALPACA | MANUAL_CSV`.
  - MANUAL_CSV reads `data/manual_positions.csv` (symbol, qty, avg_cost) plus cash and settled_cash from `data/manual_cash.csv`. It's for tickets placed at a broker without an API. File age > 1 session → STALE → no new alerts.
  - If ALPACA is selected and the broker reports an account type, cross-check it against `BROKER_ACCOUNT_TYPE`. A mismatch HALTs.

Acceptance (D):
- Unit tests with fakes cover: batching call count, token bucket under burst (fake clock), SIP end clamp, NY-date session mapping across DST, news dedupe, earnings precedence, and manual CSV staleness.
- `pytest -m integration` with paper keys pulls SIP daily bars and parses `/v2/account`. Skip it without keys and report it UNVERIFIED.

### 4.2 Fundamentals: Paul Harris 5-point framework (Stage E; replaces the earlier addendum)
Files:
- `backend/agents/fundamentals.py`, which is pure computation
- `backend/data/sec_edgar.py`, the provider (ticker→CIK map cached 7 days, companyfacts cached `fundamentals.cache_hours`=24, ≤8 req/s, `SEC_USER_AGENT` required)
- `prompts/fundamental_analyst.md`, optional and used only for a one-line narrative when the LLM is enabled. It may never change values or status.

```python
class MetricStatus(StrEnum): PASS="PASS"; FAIL="FAIL"; INSUFFICIENT_DATA="INSUFFICIENT_DATA"; NOT_MEANINGFUL="NOT_MEANINGFUL"
class FrameworkStatus(StrEnum): PASS="PASS"; FAIL="FAIL"; INCOMPLETE="INCOMPLETE"; NOT_APPLICABLE="NOT_APPLICABLE"

class MetricResult(BaseModel):  # frozen, extra="forbid", allow_inf_nan=False
    name: Literal["gross_margin", "operating_margin", "roic", "free_cash_flow", "interest_coverage"]
    value: Decimal | None          # ratios as fractions (0.42 = 42%); FCF in USD
    threshold: Decimal             # 0.40, 0.15, 0.10, 0, 3.0
    status: MetricStatus           # PASS only if value > threshold (strict)
    source_tags: tuple[str, ...]   # XBRL tags actually used
    period_end: date | None
    note: str                      # e.g. "no debt", "negative invested capital"

class FundamentalReport(BaseModel):  # frozen
    symbol: str; cik: str | None; as_of: datetime
    latest_filing_date: date | None; latest_period_end: date | None
    basis: Literal["TTM", "FY"]
    metrics: tuple[MetricResult, ...]    # exactly 5, fixed order
    framework_status: FrameworkStatus
    passed_count: int                    # 0..5
    failure_reasons: tuple[str, ...]     # human-readable, e.g. "ROIC 8.2% (needs >10%)"
    data_sha256: str                     # hash of the raw companyfacts payload used
```

Rules:
- FA-01 **Applicability**: ETFs and CASH_EQUIV, and STOCKs whose `gics_sector` is in `fundamentals.exempt_sectors` (default `["Financials", "Real Estate"]`), get NOT_APPLICABLE. That status is neither a pass nor a fail.
- FA-02 **Point-in-time**: use only facts with `filed <= as_of`, units USD, forms 10-K/10-Q (and /A amendments). For each (tag, start, end), keep the latest `filed`. If `latest_period_end` is older than `fundamentals.max_filing_age_days` (200), every metric is INSUFFICIENT_DATA.
- FA-03 **TTM** for duration concepts:
  - TTM = FY_latest + YTD_current − YTD_prior.
  - YTD_current is the newest fact that ends after FY_latest and starts within ±10 days after FY_latest's end.
  - YTD_prior has the same duration (±10 days) and ends ≈1 year earlier (±10 days).
  - If no newer YTD exists, TTM = FY_latest and basis = FY.
  - If any piece is missing, that metric is INSUFFICIENT_DATA. Never interpolate.
  - Instant concepts use the latest balance-sheet value. For averaging, also use the value ≈1 year earlier (±20 days) when present.
- FA-04 **Formulas**:
  - Gross margin = GrossProfit / Revenue, or (Revenue − CostOfRevenue) / Revenue.
  - Operating margin = OperatingIncome / Revenue.
  - FCF = CFO − CapEx.
  - ROIC = NOPAT / avg(InvestedCapital), where:
    - NOPAT = OperatingIncome × (1 − t)
    - t = clamp(TaxExpense / PretaxIncome, 0, 0.35), falling back to 0.21 if pretax income is ≤ 0 or missing
    - InvestedCapital = StockholdersEquity + TotalDebt − Cash
  - Interest coverage = OperatingIncome / InterestExpense.
- FA-05 **Edge cases**:
  - Revenue ≤ 0 → margins NOT_MEANINGFUL.
  - InvestedCapital ≤ 0 → ROIC NOT_MEANINGFUL.
  - OperatingIncome ≤ 0 → coverage FAIL.
  - InterestExpense absent or 0 *and* TotalDebt == 0 → coverage PASS with note "no debt".
  - InterestExpense absent with TotalDebt > 0 → INSUFFICIENT_DATA.
  - Non-USD filers → all metrics INSUFFICIENT_DATA.
- FA-06 **Tag fallbacks**: first available for the period wins. Record the tag used. This is a starting list: verify it against recorded fixtures, and add a tag only with a fixture that needs it.
  - revenue: `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueNet`
  - gross profit: `GrossProfit`
  - cost of revenue: `CostOfRevenue`, `CostOfGoodsAndServicesSold`, `CostOfGoodsSold`
  - operating income: `OperatingIncomeLoss`
  - CFO: `NetCashProvidedByUsedInOperatingActivities`
  - capex: `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets`
  - interest: `InterestExpense`, `InterestExpenseNonoperating`, `InterestExpenseDebt`, `InterestAndDebtExpense`
  - tax: `IncomeTaxExpenseBenefit`
  - pretax: `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`, `IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments`
  - equity: `StockholdersEquity`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`
  - debt: `LongTermDebt` if present, else `LongTermDebtNoncurrent` + `LongTermDebtCurrent`; then add `ShortTermBorrowings` and `CommercialPaper` if reported separately. Guard against double counting and test it.
  - cash: `CashAndCashEquivalentsAtCarryingValue`, falling back to `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`
- FA-07 **Status roll-up**:
  - PASS iff all 5 metrics PASS.
  - FAIL if any metric FAILs.
  - Otherwise INCOMPLETE. INSUFFICIENT_DATA or NOT_MEANINGFUL is never counted as a pass.
- FA-08 **Use in the pipeline**: `fundamentals.mode = annotate` (default) | `require`.
  - annotate: the card shows "Fundamentals 4/5 ✗ ROIC 8.2% (needs >10%)".
  - require: STOCK candidates without PASS are dropped (and logged) before any LLM call. NOT_APPLICABLE symbols pass through, marked "n/a".
  - The framework never changes the setup score, levels, or size, and it is not a CRO rule.
- FA-09 Fundamentals are cheap and cached, so they run before the LLM, which is the expensive step.

Acceptance (E, fundamentals):
- Record ≥5 real companyfacts fixtures, chosen to exercise: an all-pass high-margin issuer, a low-gross-margin fail, a Financials-exempt issuer, a fiscal year that isn't the calendar year, and a negative-operating-income issuer. Add synthetic fixtures for "no debt" and "negative invested capital".
- Hand-compute the expected values from the fixture into the test. Don't copy them from the code.
- Boundary tests: exactly 0.40 / 0.15 / 0.10 / 0 / 3.0 → FAIL. Threshold + 0.0001 → PASS.
- Point-in-time test: a fact filed after `as_of` is ignored.
- Stale-filing test, TTM Q4-derivation test, and double-count debt test.
- An offline run makes no network calls.

### 4.3 Playbooks: exact deterministic definitions (Stage E)
These are initial defaults in `config.yaml`. They are not tuned and not claimed to be profitable. Stage G measures them.

Conventions:
- t = latest completed session.
- Hard gates must all hold, otherwise there's no candidate.
- Each criterion returns (name, points, reason), and the score is the sum (max 10).
- Indicators: EMA, RSI14 Wilder, ATR14 Wilder, RVOL = volume_t / mean(volume over the prior 20 sessions).
- `range_pos` = (close − low) / (high − low), set to 0 when high == low.

| Playbook | Hard gates | Criteria (points) |
|---|---|---|
| TREND_50EMA | close>EMA200; EMA50_t > EMA50_{t−10}; min(low over last 5) ≤ EMA50×1.01; close_t > EMA50_t and close_t > high_{t−1} | EMA20>EMA50>EMA200 (2); EMA50 10-session slope ≥2% (2) / ≥1% (1); pullback low within 1% of EMA50 (2); range_pos ≥0.7 (1.5); RVOL ≥1.2 (1); RSI14 in [45,65] (1.5) |
| BASE_BREAKOUT | close_t > max(high over prior 20, excl. t); RVOL ≥1.5; 20-session range/close ≤0.15 | breakout margin 0.5–3% (2) / >3% (1); RVOL ≥2.0 (2) / ≥1.5 (1); base range ≤0.10 (2) / ≤0.15 (1); close>EMA50>EMA200 (2); RSI14 in [55,75] (1); range_pos ≥0.75 (1) |
| ANCHORED_VWAP_RECLAIM | close_{t−1} < AVWAP_{t−1} and close_t > AVWAP_t; RVOL ≥1.2 | reclaim margin 0.5–3% (2); RVOL ≥1.5 (2) / ≥1.2 (1); EMA50 rising over 10 sessions (2); (entry − stop) ≤ 2×ATR14 (2); RSI14 in [45,65] (1); range_pos ≥0.7 (1) |

Definitions:
- **AVWAP anchor**: the session of the lowest low in the last 60 completed sessions. If a gap session is more recent than that low, the anchor is the gap session instead. A gap session has |open/prev_close − 1| ≥ 0.04 and RVOL ≥ 2.0. AVWAP = Σ(typical × volume) / Σ volume from the anchor through t inclusive, with typical = (H + L + C) / 3.
- **Levels**:
  - entry = high_t + $0.01. It's a limit order: a maximum price, not a trigger.
  - stop = min(entry − `STOP_ATR_MULT`×ATR14, lowest low of the last `swing_lookback`=10 sessions − $0.01).
  - Drop the candidate if (entry − stop)/entry > `sizing.max_stop_pct` (0.12).
  - target = entry + `TARGET_R`×(entry − stop). Require R/R ≥ 1.5.
- **Size**: qty = min(floor(target_risk_per_trade × equity / (risk_per_share + entry × STOP_SLIPPAGE_BUFFER)), CRO.max_allowed_qty()). Here risk_per_share = entry − stop, and the second term uses the same slippage buffer CRO-04 charges, so the per-share risk matches CRO-04. If qty = 0, drop the candidate silently (logged, no alert, no LLM call).
- **Market context line**: SPY close vs its EMA200 is shown on the card and in the digest. It's informational only in v1 (AMENDMENT 02 XK-03 adds an optional regime filter).

Acceptance (E, playbooks):
- Golden fixtures per playbook: one pass, one fail per hard gate, and score boundaries at exactly 7.0 vs 6.99.
- AVWAP anchor selection tests for both anchor types.
- Indicator values match hand-computed fixtures.
- The same input always gives the same output.

### 4.4 LLM: optional, cheap, never decisive (Stage E)
- `LLM_ENABLED=false` by default. The full pipeline (scan → score → fundamentals → CRO → card → ticket) must work with the LLM off. In that case the card shows "News: 3 headlines (sentiment off)" and lists up to 3 escaped headline titles.
- `LLM_ENABLED=true` requires all of these, otherwise startup fails with a clear message: `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_API_KEY`, `LLM_PRICE_INPUT_PER_MTOK`, `LLM_PRICE_OUTPUT_PER_MTOK`, and `LLM_DAILY_BUDGET_USD` > 0 (default 1.00, ceiling 20).
- **Budget**:
  - Before each call, reserve `est_input_tokens × in_price + LLM_MAX_TOKENS × out_price` atomically (DB transaction). If the reservation would exceed the day's remaining budget, return None.
  - After the call, settle to actual usage. Use usage numbers from the response when present, otherwise the reserved estimate.
  - The budget day resets at 00:00 America/New_York.
- **Efficiency**:
  - Make LLM calls only for candidates that passed CRO check #1 and the fundamentals mode.
  - Make one call per symbol per cycle, with all new headlines batched.
  - Cache by sha256(prompt_hash + canonical input). If there are no new headlines since the last call, reuse the cached result with no new call.
- **Prompt files**: `news_sentiment.md`, `research_synthesis.md` (narrative only), `head_of_desk.md` (EOD narrative only), and `fundamental_analyst.md` (narrative only). Each has front-matter version, role, input schema, output JSON schema, rules, and injection defense, per GD-02.

Acceptance (E, LLM):
- With the LLM disabled: the dry run is complete and no `openai` client is constructed.
- Budget tests: a reservation that would exceed the budget is refused, settlement is correct, and concurrent calls can't overspend (run 20 concurrent fake calls).
- Cache hit means no call.
- The GD prompt-injection tests still pass.

### 4.5 Orchestrator: a schedule that fits daily-bar swing trading (Stage F; replaces the GD-04 intervals)
Daily-bar setups only change at the close, so scanning for new setups every 15 minutes wastes calls and money. All times below are America/New_York and come from the XNYS calendar.

| Job | When | Does |
|---|---|---|
| daily_scan | each session close + `daily_scan_delay_minutes` (30; uses the actual early close) | Full pipeline on completed bars → up to MAX_ALERTS_PER_DAY cards + one evening digest |
| premarket_check | 08:45 on session days | Revalidate PENDING alerts against overnight news, corporate actions, and earnings. Expire or annotate cards whose facts changed. Re-check fundamentals cache age. |
| position_monitor | every `monitor_interval_minutes` (15) during regular hours | For held positions and open tickets: stop breached (last trade ≤ stop), target reached, earnings now inside blackout, symbol SUSPECT. Each sends an EXIT/REDUCE suggestion card. These are never blocked by risk rules, per R-09. Price is IEX latest trade, labelled as such. |
| news_watch | every `offhours_news_interval_minutes` (60) | Headlines for held positions and pending alerts only. THESIS_CHANGING (when the LLM is on) or a keyword flag (when it's off) annotates the card. |
| weekly_report | Fri, 30 min after close | §4.7 report |
| housekeeping | daily 02:00 | Backups, verify_chain, cache pruning, expiring alerts |

All jobs run with `max_instances=1, coalesce=True` and a misfire grace. Each run appends a `job_runs` row: job, started_at, finished_at, outcome, counts, duration_ms. If state != RUNNING, no new-setup alerts go out; monitoring and exit suggestions continue.

Acceptance (F, orchestrator):
- Frozen-clock tests for: normal close, early-close day (e.g., the day after Thanksgiving), holiday (no daily_scan), DST transition week, and HALTED (no new alerts, but exit cards still go out).
- `job_runs` rows are written, including on failure.

### 4.6 Telegram UX: simple for the user, strict underneath (Stage F)
Card. Plain language. Every number is computed by code, and dollar amounts come first. Times use `DISPLAY_TZ` (default America/Chicago, "CT"); storage stays UTC.
```
🟢 NVDA · Buy setup · Base breakout (score 8.5/10)
Buy limit $128.50 · Stop $124.20 · Target $137.00
Size 19 sh = $2,441.50 (9.8% of account)
If stopped: about −$87 (0.35%) · Reward:risk 1.98
News: +4 confirming [h3] · Fundamentals 5/5 ✓ · Earnings ~41 sessions
Market: SPY above 200-day avg · Flow: n/a
All risk checks passed · Valid until Tue Oct 6, 3:00 PM CT
[✅ Approve] [❌ Reject] [ℹ️ Details]
```
- **Details** (action `D`) edits the message to show every RuleResult (rule id, observed, limit), WARNs, data timestamps, config_hash prefix, and the fundamentals breakdown. It's read-only. Approve and Reject buttons remain.
- **Approve**:
  1. Immediately answer the callback with "Re-checking…".
  2. Revalidate per GD-06.
  3. Edit the message into a ticket card with copyable broker instructions, and the buttons `[📌 I placed it] [⏭ Skip]` (actions `P`/`S`, recorded as approval events `TICKET_PLACED`/`TICKET_SKIPPED`).

  Example ticket card:
  ```
  TICKET 7f3a… (valid until Tue 3:00 PM CT)
  1) BUY 19 NVDA, LIMIT $128.50, DAY
  2) After it fills: SELL STOP 19 NVDA at $124.20, GTC
  3) Optional: SELL LIMIT 19 NVDA at $137.00, GTC (use OCO if your broker supports it)
  ```
- **Commands**: allowlisted users only. Everyone else is ignored and logged to `security_events`.
  - `/status`: state, last successful job per type, data freshness, pending alerts, open tickets, LLM spend today.
  - `/positions`: each holding's distance to stop.
  - `/digest`: resends today's digest.
  - `/report`: latest §4.7 report.
  - `/halt <reason>`: escalates to HALTED. Always allowed, and it's the phone kill switch.
  - `/help`.
  - There is **no** resume/reset over Telegram. Reset is CLI-only on the host: `python -m vws ops reset --operator NAME --reason "..."`, which requires typing `RESET` to confirm and writes a ledger event.
- **Ticket↔fill matching**:
  - With `BROKER_STATE_SOURCE=ALPACA`, read-only order and position polling links fills to tickets (same symbol and side, qty ≤ ticket qty, fill price ≤ limit, within validity) and records them via `record_fill`.
  - Unmatched broker fills are recorded as MANUAL signals. That's not a halt (in AUTO_* modes, AMENDMENT 02 AX-31 makes it a halt).
  - Position mismatches still go through `reconcile()`.
- **Quiet hours**: `quiet_hours` from 22:00 to 07:00 CT. Alerts are queued until 07:00, except halts and stop-breach cards, which send immediately.
- Message length is capped, everything is escaped with HTML parse mode, and callback data stays ≤64 bytes. Use `v1:<A|R|D|P|S>:<32hex>:<16hex>`.

Acceptance (F, UX):
- All GD-06 tests, plus: chat/message binding mismatch rejected; concurrent double-approve → exactly one ticket (UNIQUE constraint); Details doesn't change state; P/S only valid after APPROVED.
- `/halt` from an allowlisted user → HALTED and a ledger event. `/halt` from a non-allowlisted user → ignored and a security event.
- Quiet-hours queueing works with a frozen clock.
- Card golden test: every number on the card is recomputed from proposal + Verdict and matches.
- Ticket text golden test.

### 4.7 Evaluation: is any of this working? (Stage G)
- EV-01 **Paper outcome tracker** (`backend/evaluation/outcomes.py`). It's pure and uses SIP daily bars with split adjustment. It runs for every alert: approved, rejected, expired, and (as a separate "shadow" cohort) CRO-vetoed candidates with qty > 0.
  - Fill: on the first session within validity where low ≤ limit, at min(open, limit). Otherwise NOT_FILLED.
  - Exit on later sessions, and on the fill session itself:
    - If low ≤ stop, exit at min(open, stop), minus the STOP_SLIPPAGE_BUFFER.
    - Otherwise, if high ≥ target, exit at the target.
    - If stop and target are both touched in the same bar, assume the stop. That's the conservative choice.
    - Time stop: exit at the close after `evaluation.max_hold_sessions` (20).
  - Record R-multiple, MAE/MFE, sessions held, and exit reason.
  - Ignore dividends, and say so in the report.
- EV-02 **Weekly report** (Telegram, plus CSV in `data/reports/`):
  - count, fill rate, win rate, average R, expectancy, and the max drawdown of a simulated equity curve using the CRO sizing
  - split by playbook, by fundamentals status, and approved vs rejected (shows whether the user's discretion adds value)
  - SPY buy-and-hold over the same dates for comparison
  - Under 30 resolved trades, print "too few trades to judge".
  - Every report carries "Hypothetical results; not indicative of future returns."
- EV-03 **Historical replay** (`python -m vws replay --start YYYY-MM-DD --end YYYY-MM-DD [--symbols ...]`):
  - Runs the same hunter → fundamentals (point-in-time by `filed` date; skipped if unavailable) → CRO sizing → EV-01 simulation, day by day over stored SIP history.
  - Fixed parameters only. **No parameter search, optimization, or genetic breeding.**
  - Prints a survivorship-bias warning, because the watchlist is today's.
  - Target: 20 symbols × 7 years finishes in under 3 minutes on a laptop.

Acceptance (G):
- Hand-built bar sequences for: gap below the stop, same-bar stop and target, never filled, time stop, split during a hold.
- Report numbers recomputed independently in the test.
- Replay is deterministic, so two runs produce identical output hashes.
- No network in unit tests.

### 4.8 Ops and reliability (Stage H)
- OPS-01 `python -m vws doctor` prints a green/red checklist with a fix hint per line and exits non-zero on any red. It checks:
  - Python version
  - required env vars by enabled feature
  - ceilings
  - DB writable
  - verify_chain
  - exchange calendar loaded
  - clock skew
  - Alpaca paper endpoint reachable, the account parses, and mode/endpoint match
  - Telegram token valid, and the chat is private with an allowlisted user
  - SEC user agent present (if fundamentals are enabled)
  - LLM config (if enabled)
  - disk space
- OPS-02 `python -m vws start` runs everything in one asyncio process: scheduler, Telegram polling, and workers. Use SQLite in WAL mode with `busy_timeout`, and serialize ledger writes. PostgreSQL stays optional through `DB_URL`.
- OPS-03 **Watchdog**:
  - If daily_scan hasn't succeeded by close + 90 min on a session day, or any job fails 3 times in a row, notify on Telegram.
  - Optionally, `HEALTHCHECK_PING_URL` is pinged after each successful job. That gives an external dead-man switch if the process or machine dies.
- OPS-04 **Backups**: a nightly SQLite online backup (`sqlite3.Connection.backup`) to `BACKUP_DIR`, kept for `BACKUP_RETENTION_DAYS` (30). Run verify_chain on the backup copy and alert on failure. Document `pg_dump` for PostgreSQL.
- OPS-05 **Schema changes**:
  - Use Alembic if it's already present. Otherwise use a minimal versioned migration runner with a `schema_version` table.
  - Migrations only add tables or columns. They never rewrite or delete ledger rows.
  - Make a backup before migrating.
- OPS-06 **CI** (`.github/workflows/ci.yml` on ubuntu-latest): all gates, plus mutmut on `backend/risk`, the callback validation, and `backend/agents/fundamentals.py`; PostgreSQL trigger tests via a service container; and `docker compose build`. Locally on Windows, these are UNVERIFIED until CI runs.
- OPS-07 **Deploy**:
  - Dockerfile and compose per GD-09.
  - `deploy/vws.service`, a systemd unit for a Linux VPS: non-root, restart on failure, env file.
  - `deploy/windows_start.ps1`, which runs `vws start` in the venv, with Task Scheduler "at logon" instructions.
  - A README section "Run it 24/7" with both options.
- OPS-08 **Logs**: structlog JSON with `cycle_id`/`proposal_id`/`alert_id` correlation, secrets redacted, rotating files (10 MB × 5).

Acceptance (H):
- doctor output tests with each failure injected.
- A watchdog fires on a missed daily_scan (frozen clock).
- A backup restores and passes verify_chain.
- A migration on a copy of a populated DB keeps all hash chains valid.

---

## 5. CONFIG ADDITIONS
Env (secrets, mode flags, risk-related; frozen; validated):
- `DISPLAY_TZ` America/Chicago
- `ALPACA_DATA_PLAN` BASIC|ALGO_TRADER_PLUS (BASIC)
- `BROKER_STATE_SOURCE` ALPACA|MANUAL_CSV (ALPACA)
- `TELEGRAM_CHAT_ID` int, required
- `NEWS_PROVIDER` ALPACA|RSS|NEWSAPI (ALPACA)
- `SEC_USER_AGENT` (required if fundamentals are enabled)
- `LLM_ENABLED` (false), `LLM_PRICE_INPUT_PER_MTOK`, `LLM_PRICE_OUTPUT_PER_MTOK`, `LLM_DAILY_BUDGET_USD` 1.00 (ceiling 20)
- `HEALTHCHECK_PING_URL` (optional)
- `BACKUP_DIR` ./data/backups, `BACKUP_RETENTION_DAYS` 30

`BROKER_ACCOUNT_TYPE` has no default: it's required.

`config.yaml` (extra="forbid"; may not contain risk limits; validated against env, e.g. `target_risk_per_trade` ≤ `MAX_RISK_PER_TRADE`):
```yaml
watchlist: [...]                 # must be a subset of instruments.csv
schedule: {daily_scan_delay_minutes: 30, premarket_check: "08:45", monitor_interval_minutes: 15,
           offhours_news_interval_minutes: 60, quiet_hours: {start: "22:00", end: "07:00", tz: "America/Chicago"}}
sizing: {target_risk_per_trade: 0.005, max_stop_pct: 0.12, stop_atr_mult: 2.0, target_r: 2.0, swing_lookback: 10}
playbooks: {enabled: [TREND_50EMA, BASE_BREAKOUT, ANCHORED_VWAP_RECLAIM], weights: {...per §4.3...}}
fundamentals: {enabled: true, mode: annotate, gross_margin_min: 0.40, operating_margin_min: 0.15,
               roic_min: 0.10, fcf_min: 0, interest_coverage_min: 3.0,
               exempt_sectors: [Financials, Real Estate], max_filing_age_days: 200, cache_hours: 24}
evaluation: {max_hold_sessions: 20, min_trades_to_judge: 30}
```
`.env.example` groups variables as REQUIRED / OPTIONAL BY FEATURE, with one comment line each.

---

## 6. CHANGES TO THE MASTER SPEC FILE TREE
Add:
- `backend/agents/fundamentals.py`
- `backend/data/sec_edgar.py`
- `backend/data/news.py` (if news isn't already in providers.py)
- `backend/evaluation/{outcomes.py, replay.py, report.py}`
- `backend/ops/{doctor.py, watchdog.py, backup.py, cli.py}` (`python -m vws ...`)
- `deploy/{vws.service, windows_start.ps1}`
- `config/earnings_calendar.csv`
- `docs/spec/`, `docs/STATUS.md`
- the matching tests

Remove or don't create: `prompts/market_scanner.md`, `prompts/setup_hunter.md`, `prompts/whale_tracker.md`.

Adapt to the real layout you find, for example the existing `risk/boundary.py` and `risk/compliance_boundary.py`. Don't restructure working code just to match this list.

---

## 7. DEFINITION OF DONE (end of Stage H)
- All MASTER SPEC §11 commands pass, plus: `python -m vws doctor` (green with paper keys, or red with clear hints and no keys), `python scripts/dry_run.py --dry-run NVDA --offline`, `python -m vws replay --start 2019-01-01 --end 2025-12-31 --offline-fixtures`.
- Coverage gate extended to `backend/agents/fundamentals.py` and `backend/evaluation/` (100% branch).
- Deliverables:
  - updated traceability matrix including FA-/DAT-05..12/EV-/OPS-/UX IDs
  - VERIFY.md, with each line marked VERIFIED (how) or UNVERIFIED
  - ASSUMPTIONS.md
  - a self-review listing at least 12 ways a bad proposal, forged click, stale datum, or LLM output could still reach a ticket, with the fix for each
  - a 1-page RUNBOOK: start/stop, halt/reset, rotate secrets, restore a backup, a 4-week paper checklist, and how to read the weekly report
- README quick start for a non-developer, in five steps at most: install → copy `.env.example` → `vws doctor` → `vws start` → approve cards in Telegram.

## 8. OUT OF SCOPE (do not build; refuse if a later message asks without the user confirming in plain words)
- Order submission/replacement/cancellation, money movement, or autonomous execution of any kind (R-10 stands). **Changed by AMENDMENT 02:** the user has confirmed opt-in auto mode, so order execution is in scope exactly as AMENDMENT 02 defines it. Money movement stays banned.
- Options, shorting, leverage, 0DTE/1DTE
- The genetic "breeder" or any parameter search
- LangGraph, FastAPI/WebSocket server, Redis/Kafka
- The 3D "Scalp City" dashboard. A later phase may add a read-only view over the ledger; keep `/status` data in one function so it can be reused then.
- yfinance as a default source; Whale Alert/Etherscan (crypto, irrelevant to US equities)
- Any wording in the UI, README, or reports that implies guaranteed or expected profits

## 9. DECISIONS ONLY THE USER CAN MAKE (use the defaults; list these in STATUS.md; don't block on them)
- Which account the tickets will be placed in (default: Alpaca paper, read-only), plus account type and approximate equity
- Where it runs 24/7 (default: documented for both the Windows PC and a VPS)
- `fundamentals.mode` (default annotate)
- LLM provider, model, and daily budget (default off)
- The watchlist (default: 20 liquid large-cap US stocks plus SPY and the 11 SPDR sector ETFs, all in instruments.csv)
- External accounts (IRA/Roth/other brokers) for wash-sale checks (default: none, plus a warning in `/status`)
- Tax rates and filing state for the tax set-aside estimate (default: unset, so totals only)

## 10. REMINDERS (superseded by AMENDMENT 02 §13)
Audit first · LLMs interpret, code decides (including fundamentals) · fail closed; UNAVAILABLE/INSUFFICIENT_DATA is never a pass · Decimal at boundaries · exits are never trapped · daily loss is session-scoped, while drawdown and fault halts latch · paper by default · banned Alpaca fields stay banned · always pass `feed` explicitly; SIP `end` ≥ 15 min old · LLM off by default and budget-reserved when on · times shown in CT, stored in UTC · report unverified checks honestly · no hype, no profit claims.

