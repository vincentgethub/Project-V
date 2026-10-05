# AMENDMENT 02: Auto mode, funding, P&L, tax, extras

To Codex: this builds on the MASTER SPEC and AMENDMENT 01. Everything there still applies unless this text changes it. Save this verbatim to `docs/spec/AMENDMENT_02.md`, add it to `AGENTS.md`, and replace the reminders there with §13 below.

**Authorization.** The user confirmed in plain words that he wants an opt-in mode that places orders without asking him each time. He also asked for funding support, daily P&L, a tax record-keeper, and extras of your choosing. That meets AMENDMENT 01 §8, so order execution comes into scope only as defined here. This amendment overrides MASTER SPEC R-08 (broker side only; bank access stays read-only), R-10, GD-07 (the AST test) and §7.1 (only so that HALTED still allows protective exits, AX-30), plus AMENDMENT 01 §8 (first bullet) and §10. Nothing else changes. **MANUAL stays the default and behaves exactly as it does today.**

**Order of work.** Same protocol as AMENDMENT 01 §0: stage report, local commit, honest UNVERIFIED list.
- **Stage J** (funding, P&L, tax; §6–8) comes right after H. It must work in MANUAL too.
- **Stage I** (auto; §1–5) comes after J, so every auto fill lands in the cash-flow, P&L and tax records from the first order.
- **Stage K** (extras; §9) comes last.

So the build order is H → J → I → K.

---

## 1. MODES (AX-01..AX-06)

- AX-01 `EXECUTION_MODE = MANUAL | AUTO_PAPER | AUTO_LIVE`. It's an env var with default MANUAL.
- AX-02 The **effective mode** is the configured mode, downgraded by any persisted runtime override. Downgrades are always allowed, from Telegram (`/manual`, `/pause`, `/halt`) or the system (halts, circuit breaker). Upgrades happen **only on the host**: change env and restart, or run `python -m vws ops resume-auto --operator NAME` (type `RESUME`; writes a ledger event). Unknown mode values mean MANUAL.
- AX-03 MANUAL: card → Approve → ticket. No order calls are reachable.
- AX-04 AUTO_PAPER: orders go to the Alpaca **paper** endpoint only.
- AX-05 AUTO_LIVE: orders go to the Alpaca **live** endpoint, behind the §4 unlock.
- AX-06 **Broker scope.** Auto mode exists only for Alpaca (`BROKER_STATE_SOURCE=ALPACA`). If the user's tickets go to Merrill or any broker without an API, auto mode is not available. `MANUAL_CSV` is manual-only, and if you set `AUTO_*` alongside it, startup fails with that sentence.

## 2. EXECUTOR ISOLATION (AX-10..AX-16)

- AX-10 All order calls live in **one module**, `backend/execution/alpaca_executor.py`: one `AlpacaExecutor` behind an `OrderExecutor` Protocol. Unit tests use `FakeOrderExecutor` / `FakeTradingClient`, with no network.
- AX-11 The constructor raises `ExecutionDisabledError` unless the effective mode is `AUTO_*`, and the composition root wires it in only then. In MANUAL, approve always produces a ticket and never imports the executor (proved by an import-graph test).
- AX-12 **Allowed in the executor, and nothing else:** `LimitOrderRequest` with `OrderClass.BRACKET` + `TakeProfitRequest` + `StopLossRequest`; plain `LimitOrderRequest` (exits); `StopOrderRequest` (stop repair only); `submit_order`, `cancel_order_by_id`, `get_order_by_client_id`, plus read-only calls. `# VERIFY` each against the pinned alpaca-py.
- AX-13 Banned **everywhere, including the executor**:
  - `MarketOrderRequest`, `TrailingStopOrderRequest`, `ReplaceOrderRequest`, `close_position`, `close_all_positions`, `cancel_orders` (cancel-all), and anything options-related
  - Any transfer, ACH, journal, withdrawal or bank-link call, and any money movement via Plaid
  - Dynamic dispatch: `eval`/`exec`/`getattr` with non-literal names
- AX-14 **GD-07 v2.** The AST scan keeps every MASTER SPEC check, with this whitelist: an order-placing name is allowed iff the file path equals `backend/execution/alpaca_executor.py`.
  - Positive controls that must fail: a planted `submit_order` in any other file; a planted `MarketOrderRequest` or `close_position` *inside* the executor; a planted transfer call anywhere.
- AX-15 **Paper/live binding.** Checked at startup and in `doctor`; any failure means the process refuses to start.
  - Use separate `ALPACA_PAPER_KEY_ID/_SECRET` and `ALPACA_LIVE_KEY_ID/_SECRET`. MANUAL may use either set read-only.
  - AUTO_PAPER: paper keys only (no live keys present), `PAPER_TRADING=true`, `TradingClient(paper=True)`.
  - AUTO_LIVE: live keys only (no paper keys present), the full R-06 triple gate, `paper=False`, and the §4 unlock.
  - Assert the resolved base URL (`https://paper-api.alpaca.markets` / `https://api.alpaca.markets`, verified Oct 2026). `get_account()` must return ACTIVE with nothing blocked.
- AX-16 **Idempotency.** `client_order_id = "vws-" + proposal_id.hex` for entries, and `"vws-x-" + proposal_id.hex + "-" + n` for exit attempt n (unique and ≤128 characters per Alpaca). After a timeout or ambiguous error, call `get_order_by_client_id` before any retry. If the order exists, it was submitted; never resubmit.

## 3. ENTRY AND EXIT FLOW (AX-20..AX-31)

- AX-20 **Eligibility.** An alert can auto-enter only if it passed every existing gate (MIN_SETUP_SCORE, fundamentals mode, CRO check #1 and #2, compliance, freshness) **and** passes revalidation at submit time (GD-06 rules) against a fresh broker snapshot and a fresh IEX quote.
- AX-21 **Hybrid.** `AUTO_MIN_SCORE` (8.5, must be ≥ MIN_SETUP_SCORE). Alerts at or above it auto-submit. Alerts below it get approve cards, and in `AUTO_*`, Approve submits through the executor after revalidation instead of producing a ticket. Setting it equal to MIN_SETUP_SCORE makes the mode fully automatic.
- AX-22 **Timing.** Alerts are still produced after the close. `auto_entry` runs at the next open + `AUTO_NO_TRADE_OPEN_MINUTES` (15, range 5–60). There are no submits in the last `AUTO_NO_TRADE_CLOSE_MINUTES` (15, range 10–60), no entries in the final 60 minutes of an early-close day, and none at all when data is STALE/SUSPECT, outside regular hours, or on non-sessions.
- AX-23 **Entry order shape.** One bracket: BUY LIMIT at the proposal's limit for whole shares, `take_profit.limit_price = target`, `stop_loss.stop_price = stop` (stop-market, so it exits even through a gap), `time_in_force=GTC` so the legs survive overnight, and `extended_hours` omitted. `# VERIFY` that legs inherit the parent's TIF, and Alpaca's bracket price rules (stop < limit < target, minimum distance). Never a market order for an entry.
- AX-24 **Entry expiry.** At `valid_until` the executor cancels any unfilled entry it created. After a partial fill, keep the shares and confirm the legs cover the filled qty; if they don't, apply AX-27.
- AX-25 **Pre-submit checklist.** This runs in order, inside one asyncio lock per account. Any failure means no submit, with a logged reason.
  1. Effective mode is AUTO, state is RUNNING, and the account isn't paused.
  2. The market-hours guard passes.
  3. A fresh `PortfolioSnapshot` comes from the broker, not the cache.
  4. CRO `evaluate()` passes, using the AX-42 live overlay in AUTO_LIVE.
  5. Compliance passes. That includes CMP-03 settled cash and free-riding checks for CASH accounts, and CMP-05 `DAY_TRADE_REGIME`.
     - Under LEGACY_PDT, auto entries are blocked when the 5-session day-trade count is ≥ 2, because a bracket leg can close the position the same day.
  6. The daily cap holds: `AUTO_MAX_ENTRIES_PER_DAY` (paper 5, ceiling 10).
  7. Duplicate guard: no open order, position or pending entry for that symbol, and no prior order with this `client_order_id`.
  8. Submit.
- AX-26 **Ledger.** Order events go PROPOSED → APPROVED (`AUTO_APPROVED`, approver "auto" + config_hash; hybrid clicks record the Telegram user ID) → SUBMITTED → … → FILLED/CANCELED/REJECTED. Every fill goes through `record_fill()`, so lots, wash sales and 8949 rows match manual fills.
- AX-27 **Every filled position has a broker-side stop.** After every fill and every monitor cycle, verify an open stop covers the held qty. If it's missing or short, submit a GTC `StopOrderRequest` at the recorded stop. If that fails, set HALTED and send an urgent message.
- AX-28 **Fills.** Use the Alpaca trade-updates stream (`TradingStream`, `# VERIFY`), with 60 s REST polling as a fallback during regular hours. Every fill triggers `reconcile()`.
- AX-29 **Automated exits** (`AUTO_EXITS=true` is the default in `AUTO_*`). Stop and target are the broker legs. Code triggers an exit for only three reasons: the time stop (`evaluation.max_hold_sessions`), earnings entering the blackout (`AUTO_EXIT_BEFORE_EARNINGS=true`), or the symbol turning SUSPECT. LLM and news output never trigger exits; they produce FYI messages only.
  - Procedure: cancel both legs and confirm (`# VERIFY` OCO cancel semantics), then submit a DAY sell LIMIT at `last_trade × (1 − AUTO_EXIT_LIMIT_OFFSET)` (0.01) for the broker-reported qty, re-pricing up to 3× at 2-minute intervals.
  - If it's still unfilled, re-place the stop and send an urgent message.
- AX-30 **Exits are never blocked.** HALTED, REDUCE_ONLY, `/pause`, `/manual`, the daily-loss block (CRO-10), the drawdown tiers (CRO-09) and the circuit breaker stop new entries only, never exits or stop protection. Sells are capped at the broker qty, so there's no shorting. On HALTED, `/pause` or `/manual`, the executor cancels its **unfilled entries** and leaves the protective legs in place.
- AX-31 **Circuit breakers** latch HALTED and reset via CLI only. They trip on:
  - `AUTO_MAX_CONSECUTIVE_ORDER_FAILURES` (3) rejected or errored submits in a row
  - any reconciliation mismatch: an unknown position or order, a qty that differs from the ledger, or an order in this account without the `vws-` prefix
  - a fill outside the limit
  - a stop AX-27 can't repair

  The notice says manual trading belongs in a different account.

## 4. AUTO_LIVE UNLOCK (AX-40..AX-44)

`vws doctor` checks every condition below at startup. If any one fails, AUTO_LIVE refuses to start, and nothing falls back silently to another mode.

- AX-40 **History.** All of these:
  - ≥ `AUTO_LIVE_MIN_PAPER_SESSIONS` (20, floor 20) XNYS sessions with a successful AUTO_PAPER `auto_entry` and `daily_scan`, counted from `job_runs`
  - a Stage G report produced after the 20th
  - no circuit-breaker or reconciliation HALT in the last 5 paper sessions
  - Stage J running for the account
  - a passed `vws ops drill` within 45 days (XK-01)
- AX-41 **Explicit enable.** `python -m vws ops enable-live --operator NAME` prints the live ceilings, requires typing `I UNDERSTAND THIS TRADES REAL MONEY`, and writes a ledger event bound to the config_hash. Any change to a risk or live setting invalidates it. `ops disable-live` downgrades immediately.
- AX-42 **Live ceilings.** These must be explicitly present in env (`.env.example` only suggests values). Each must be ≤ its CRO counterpart, and at runtime the effective limit is the lower of the live value and the CRO value.

  | Var | Suggested | Hard ceiling |
  |---|---|---|
  | `LIVE_MAX_ORDER_NOTIONAL` | $500 | ≤ MAX_SINGLE_STOCK_WEIGHT × equity |
  | `LIVE_MAX_DAILY_ORDERS` (entries) | 2 | 5 |
  | `LIVE_MAX_OPEN_POSITIONS` | 3 | MAX_OPEN_POSITIONS |
  | `LIVE_MAX_GROSS_EXPOSURE_PCT` | 0.30 | MAX_GROSS_EXPOSURE |
  | `LIVE_MAX_RISK_PER_TRADE` | 0.005 | MAX_RISK_PER_TRADE |
  | `LIVE_DAILY_LOSS_LIMIT` | 0.01 | DAILY_LOSS_LIMIT |
- AX-43 **Ops prerequisites for any AUTO_*:** `HEALTHCHECK_PING_URL` set and the watchdog on; the last backup under 26 hours old and passing `verify_chain`; Telegram reachable; clock skew OK; `doctor` fully green.
- AX-44 Paper and live history are tagged separately everywhere and never mixed in reports.

## 5. SET-AND-FORGET TELEGRAM (AX-50..AX-54)

- AX-50 **FYI messages replace approve cards** for auto-eligible alerts. Numbers come from code, and times are shown in CT. Example: "🤖 PAPER · Bought 19 NVDA @ $128.47 · stop $124.20 (at broker) · target $137.00 · risk ≈ $87". The same style covers submitted, partial, canceled-unfilled, stop/target hit, time-stop exit, stop repaired, and halt, always prefixed `PAPER` or `LIVE`.
- AX-51 **Daily summary** after the close: entries, exits, realized and open P&L, open risk in $, cash, the account state, and tomorrow's candidates. Quiet hours apply to everything except halts, stop repairs, and failed exits.
- AX-52 **Commands.** Kept: `/status` (now also shows the effective mode and PAPER/LIVE), `/positions`, `/halt`. Added: `/manual` (back to approve cards; cancels unfilled auto entries; positions and stops stay) and `/pause` (no new entries; exits and stop protection continue). Neither can be undone from Telegram, and the reply gives the exact CLI command to resume.
- AX-53 Hybrid approve cards say "Approve = places the order now (PAPER/LIVE)". Unauthorized users are ignored and logged to `security_events`, as before.

## 6. FUNDING: detected, never initiated (FN-01..FN-06)

- FN-01 **The money-movement ban stands** (AX-13). The software never deposits, withdraws, transfers or links banks. The user funds the account himself in the broker's app.
- FN-02 **Detection (read-only).** At startup and every monitor cycle, poll Alpaca account activities with `after=<last seen>` and pagination (page_size 100) for these types: `CSD` (deposit), `CSW` (withdrawal), `JNLC`, `DIV*`, `INT*`, `FEE`, `PTC`/`PTR`, and split/merger/spinoff/reorg types. `# VERIFY` the names and the alpaca-py request class, because the docs list overlapping variants. With `MANUAL_CSV`, read `data/manual_cash_flows.csv` (date, amount, type, note) instead. Dedupe on activity id, and record each once as an append-only `cash_flows` event: account_id, env, type, amount, date, payload sha256.
- FN-03 **Effects.** A deposit, withdrawal or cash journal calls the existing `record_cash_flow()` (CRO-09), so the high-water mark and the day's starting equity scale correctly. P&L treats them as external flows (§7), never as gains or losses.
- FN-04 **Notifications.** Deposit: "💵 Deposit of $1,000.00 detected · buying power now $3,412.18". **Withdrawals are urgent and bypass quiet hours** ("⚠️ Withdrawal of $X detected; if this wasn't you, secure your broker account now"), because the software never withdraws. Unknown types are recorded and announced, never acted on.
- FN-05 **Corporate actions and dividends.** These feed the tax ledger (§8) and the DAT-02 known-corporate-action check.
- FN-06 **README "How to fund your account".** Paper: virtual money, reset and set a balance in the Alpaca dashboard (`# VERIFY` the steps); a reset brings new keys and account id, so it's treated as a new paper account. Live: link a bank and make an ACH deposit in the Alpaca dashboard; vws detects it once buying power updates, and you never enter bank details into vws. Plaid stays balance-only and is only for the buffer gate.

## 7. DAILY P&L (PL-01..PL-06)

- PL-01 **Snapshot.** `backend/pnl/` records one end-of-day row per account per session at the close + `daily_scan_delay_minutes`: equity, cash, long market value, external flows (FN-03), realized P&L (from §8 lots, before wash adjustments), dividends/interest, fees, env, and source (BROKER|COMPUTED). Missing days are backfilled from Alpaca portfolio history (`# VERIFY`), otherwise computed and marked COMPUTED. Rows are append-only; corrections are new rows with `supersedes`.
- PL-02 **Day math** (Decimal):
  - `day_pnl = E_end − E_start − flows`
  - `day_ret = E_end / (E_start + flows) − 1` (flows treated as arriving at the start of the day)
  - Unrealized change = day_pnl − realized − dividends − interest + fees. The identity must hold to ±$0.01, otherwise alert and mark the day COMPUTED.
  - TWR over a period = ∏(1 + day_ret) − 1, so a deposit is never counted as a gain.
- PL-03 **Stats** over 7/30 sessions, MTD, YTD and since inception: average daily $ and %, up/down/flat day counts, best and worst day, max drawdown on the TWR index (with dates), and SPY over the same sessions (labelled "price only").
- PL-04 Paper and live are separate series, keyed by account_id + env, and are never summed or mixed. A paper reset starts a new series.
- PL-05 **Where it shows up.** Digest line: "Today +$123.45 (+0.82%) · 7-day avg +$41/day · 30-day avg −$12/day · YTD +3.1% vs SPY +5.0%". `/pnl [today|week|month|ytd]` replies with that window's stats.
- PL-06 These are not tax numbers. Tax figures come only from §8.

## 8. TAX LEDGER, the "tax bot" (TX-01..TX-10)

Deterministic code in `backend/tax/`, with no LLM numbers.

**Refactor first.** Move the Stage C wash-sale matching core into `backend/tax/lots.py`, then make compliance CMP-01/02 (pre-trade) and the tax ledger (post-trade) both call it. Never keep two copies. The existing Stage C tests must pass unchanged.

- TX-01 **Scope.** Live accounts, plus external accounts in `config/accounts.yaml` (id, name, TAXABLE|IRA|ROTH, and a fills CSV for accounts without an API, e.g. Merrill). Paper is excluded from real reports. `--simulate` runs on paper with "SIMULATED – NOT FOR FILING" on every header and row.
- TX-02 **Lots.** Each buy fill creates a lot (qty, cost incl. fees, trade date). Sales relieve lots per `LOT_METHOD`:
  - `ALPACA_COMPRESSED_FIFO` (default for Alpaca accounts): same-day buys of a symbol are compressed into one weighted-average lot, and intraday round trips use weighted average. Prior-day lots are FIFO.
  - Plain `FIFO` is the default for external CSV accounts.
  - `# VERIFY` both against Alpaca's "position average entry price calculation" doc and a real 1099-B. The goal is to match the broker.
- TX-03 **Realized P&L** per sale: proceeds net of FEE/REG/TAF, basis, gain/loss. Use trade dates (not settlement) for the holding period and the tax year.
- TX-04 **Holding period.** Long-term iff `sale_date > anniversary(acq_date)` (same month and day next year; Feb 29 maps to Feb 28); otherwise short-term. A wash replacement takes on the replaced lot's holding period (tacking).
- TX-05 **Wash sales.** The window is 30 days before and after a loss sale. Use config's substantially-identical groups across every listed account, and match proportionally, oldest replacement first. The disallowed loss is added to the replacement lot's basis, with tacking. Chains carry forward, and a December loss with a January rebuy defers into the new lot. An IRA/Roth replacement makes the loss permanent: flagged, no basis added. Gains are never washed.
- TX-06 **Income.** Dividends (`DIV*`, keeping the broker's subtype), interest and fees are recorded per year. Whether a dividend is qualified comes from the broker's 1099-DIV. Until then, label them "unclassified" and estimate them at the short-term rate.
- TX-07 **Outputs.** `python -m vws tax report --year YYYY [--account ID|all] [--simulate]` writes `data/tax/YYYY/`:
  - `form8949.csv`: description, dates acquired/sold, proceeds, basis, code `W` + adjustment, gain/loss, ST|LT, box (`# VERIFY` against current IRS instructions)
  - `schedule_d_summary.csv`: ST/LT netting, with the $3,000 net-loss limit ($1,500 if MFS) and carryover
  - `income.csv`, `lots_open.csv`, and a `README.txt` with the disclaimer
- TX-08 **Estimated set-aside.** Rates are user-set in env: `TAX_FED_ST_RATE`, `TAX_FED_LT_RATE`, `TAX_STATE_RATE`, `TAX_NIIT_RATE` (default 0). **No silent defaults:** until they're set, `/tax` shows totals only. `.env.example` includes Illinois 4.95% (verified for 2026) and Texas 0%. Set-aside = max(0, net ST) × (fed ST + state + NIIT) + max(0, net LT) × (fed LT + state + NIIT), always labelled "estimate". `/tax` and the weekly report show YTD realized ST/LT, wash-disallowed totals, dividends and the set-aside.
- TX-09 **Reconcile.** `vws tax reconcile --year YYYY --1099b file.csv [--mapping config/1099b_columns.yaml]` imports the broker's 1099-B CSV through a column mapping (`# VERIFY` Alpaca's export format) and matches by symbol, sale date and qty. It flags proceeds, basis, wash or term differences over $0.01, and unmatched rows, with a likely cause for each (a cross-account wash the broker can't see, the lot method, or a corporate action). Output: `reconcile_YYYY.csv` + a summary. **The 1099-B is authoritative.**
- TX-10 **Storage and disclaimer.** Everything is Decimal and append-only. A corrected import is a new version, never an edit. Every tax output and `/tax` reply carries:
  > Estimate and record-keeping aid, not tax advice. Your broker's 1099-B is the official record; consult a tax professional.

## 9. STAGE K EXTRAS (ranked by value; anything that changes trading is configurable with the safe default shown)

1. **XK-01 Kill-switch drill.** `vws ops drill` runs the halt path end to end against a scratch DB with the fake executor: `/halt` → HALTED persisted → unfilled entries canceled → Telegram delivered (real send, marked DRILL) → CLI reset. It reports pass/fail and appends a ledger event. If no drill has passed in 31 days, `/status` and the weekly report send a reminder, and AUTO_LIVE start fails if none has passed in 45 days. It never touches the real account.
2. **XK-02 Trade journal.** An append-only entry for every alert, auto entry, exit and veto: playbook, criteria points, levels, fundamentals, news ids, CRO results, and the outcome when resolved.
   - Vetoes get a plain-English "why not" built from RuleResults, e.g. "Skipped AMD: would put Information Technology at 38% (cap 35%)". The digest shows at most 5.
   - **Reply to any card or FYI message in Telegram** to add a note (allowlisted users only, escaped, ≤1,000 characters). Notes are untrusted and never feed trading logic.
   - `vws journal export` writes a CSV.
3. **XK-03 Market-regime filter.** `regime_filter` sets what happens when SPY closes below its EMA200: `annotate | half_size | no_new_entries`. The default is `annotate` in MANUAL and `half_size` (halving the target risk) in AUTO. It can only reduce exposure.
4. **XK-04 Macro-event blackout.** `config/macro_events.csv` (date, ET time, event FOMC/CPI/NFP, source) generates CRO-11 blackout windows. Reuse CRO-11; don't add a new rule. By default there are no new auto entries on event days until release + 30 minutes, and MANUAL cards are annotated. An optional loader from official calendars is allowed (`# VERIFY` source and terms). The file ships empty, and `/status` warns if it's more than 90 days old.
5. **XK-05 Playbook kill switch.** A playbook is disabled for auto entries when its mean R (from the Stage G tracker, paper and live computed separately) is < 0 after `playbook_kill.min_trades` (30) resolved trades. There is no tuning or parameter search. MANUAL cards from it are labelled "playbook paused". Re-enable only via `vws ops playbook enable NAME` (writes a ledger event).
6. **XK-06 Live capital ramp.** AUTO_LIVE sizes at 25% of the computed qty (floor; 0 means skip). It steps up to 50% after 10 resolved live trades with no halt and drawdown < 5%, and to 100% after 20 more. Any REDUCE_ONLY/HALTED event or drawdown ≥ 5% drops it back one step. The multiplier stays ≤ 1 under the AX-42 ceilings, is persisted, and every step writes a ledger event and an FYI message.
7. **XK-07 Morning briefing.** One message at 08:45 ET, built from premarket_check, and **sent only if something matters**: entries planned today, holdings with earnings within 5 sessions, a macro event today, overnight halts or withdrawals, or a stale data source.
8. **XK-08 Nightly HTML report.** `data/reports/latest.html` is one self-contained file (inline SVG, no JavaScript, no server). It shows the equity curve (TWR vs SPY), a P&L calendar heat map, positions with stops, the last 20 trades, tax YTD and health. It's sent as a Telegram document weekly or on `/report`. `vws report monthly --month YYYY-MM` writes the same sections as CSV. PDF dropped: printing the HTML is enough.
9. **XK-09 `/watch TICKER`.** Runs the deterministic pipeline for one symbol in instruments.csv and replies with the card. It never auto-trades; in MANUAL, the card is approvable. Limit 10 per day, and the LLM is used only if it's enabled and the budget allows.
10. **XK-10 OS keyring secrets.** `SECRETS_BACKEND=env|keyring` (default env). Uses the `keyring` package, so Windows Credential Manager works. `vws ops secrets set NAME` prompts without echoing. Recommended for live keys, and doctor shows which backend is used.

Dropped:
- correlation caps: sector/theme caps with ETF look-through already cover most concentration, and 60-day correlations are noisy for a small book
- PDF statements
- anything needing paid data or a public server

## 10. CONFIG

New env values with defaults and ranges are given inline above: AUTO_*, LIVE_* (AX-42), the split Alpaca keys, TAX_* and SECRETS_BACKEND.

New YAML: `regime_filter`, `playbook_kill.min_trades`, `ramp` steps, and `lot_method` per account in `accounts.yaml`.

Every value is validated, and any value outside its range or ceiling means startup fails. Document each one in `.env.example` / `config.yaml`.

## 11. ACCEPTANCE (each stage's gate = all prior gates + its list; fakes everywhere, pytest-socket on)

### 11.1 Stage I (auto)

1. The mode can't be upgraded via Telegram: fuzz every command and callback in every mode and the effective mode never rises. `/manual`, `/pause` and `/halt` downgrade and write ledger events.
2. GD-07 v2 and every AX-14 positive control pass. MANUAL never imports the executor, and constructing it in MANUAL raises.
3. Every AX-15 mismatch fails startup and is named by doctor, including `MANUAL_CSV` with `AUTO_*`.
4. `enable-live` is refused with <20 sessions, no report, a recent HALT, Stage J not running, a stale drill, or a wrong phrase. A config change after enabling makes AUTO_LIVE refuse to start.
5. Every entry is a GTC bracket LIMIT with both legs and stop < limit < target. No `MarketOrderRequest` exists (AST + runtime).
6. Idempotency: a timeout after a server-side accept leads to a lookup and no duplicate. A double-triggered `auto_entry` makes one order.
7. The circuit breaker trips on the 3rd consecutive failure, latches HALTED, and survives a restart.
8. Halt, pause, the daily-loss block and the drawdown tiers stop entries and cancel unfilled entries. Stop protection and exits still run. Sells never exceed the broker qty.
9. Every AX-31 reconciliation mismatch halts, both on startup and after a fill.
10. AX-27: a missing stop gets repaired. A failed repair halts and sends an urgent message.
11. Live ceilings hold at boundaries (= passes; +$0.01, +1 share or +1 order fails). CRO limits still apply in AUTO_PAPER.
12. The market-hours guard is tested on a normal day, an early-close day, a holiday and across DST. The CASH settled-cash guard and the LEGACY_PDT guard each block an entry.
13. Auto fills produce the same lots, wash-sale flags and 8949 rows as identical manual fills (golden comparison).
14. FYI messages and the daily summary pass golden tests (numbers recomputed; quiet hours respected).
15. Integration (`-m integration`, paper keys only): submit and then cancel a 1-share bracket far from the market, verify the legs, and reconcile. Otherwise report it UNVERIFIED.
16. Mutation testing in CI covers the executor checklist, mode resolution and the ceiling overlay.

### 11.2 Stage J (funding, P&L, tax)
1. Funding: each activity is recorded once across repeated polls and restarts, and calls `record_cash_flow` (HWM and day-start scale per CRO-09). Withdrawals bypass quiet hours. Unknown types are recorded, never acted on. The MANUAL_CSV path works. The AST test still finds no transfer calls.
2. P&L: a golden multi-day series with a mid-period deposit and withdrawal gives exact day_pnl, day_ret, TWR, 7/30-day averages, best/worst day and max drawdown. The PL-02 identity holds. A flat-price deposit day shows $0. Paper and live never mix, and a reset starts a new series.
3. Tax goldens, hand-computed: partial-lot wash; loss sale then rebuy within 30 days; rebuy before the sale; day 30 vs 31; chained washes; December loss with a January rebuy; IRA replacement; gain never washed; ST/LT on the anniversary vs the day after, including a Feb 29 acquisition; tacking that turns ST into LT; compressed FIFO vs FIFO; fees reduce proceeds; Schedule D netting with the $3,000 cap and carryover; set-aside math, and totals-only when rates are unset.
4. 8949 CSV golden. `--simulate` labels every row, and paper is excluded without it. Reconcile flags each mismatch type and unmatched rows. Stage C tests pass unchanged on the shared core, and a test proves only one wash-sale implementation exists. Mutation testing in CI covers `tax/lots.py`, holding period and netting.

### 11.3 Stage K (extras)
- The drill passes without touching the real DB or account, and a stale drill blocks AUTO_LIVE.
- "Why not" text exists for every CRO and compliance rule ID (goldens).
- Reply-notes attach to the right alert, are escaped, and reject non-allowlisted users.
- The regime filter is tested at the SPY/EMA200 boundary for each setting and never raises qty.
- Macro events become CRO-11 windows with DST-correct ET→UTC conversion.
- The playbook kill trips at exactly N trades with mean R < 0, but not at N−1 or with mean R = 0, and re-enable is CLI-only.
- Ramp steps hold at their boundaries, stay ≤ 1, and survive a restart.
- The briefing stays silent when there's nothing to report.
- The HTML report has no `<script>` and no external URLs, and its numbers match the P&L and tax outputs.
- `/watch` limits and symbol validation hold, and it never orders.
- The keyring works with a fake backend, and secrets never appear in logs.

**Definition of done additions:**
- FN-, PL-, TX-, AX- and XK- IDs in the traceability matrix.
- RUNBOOK sections: switching modes, reading FYI messages, recovering from a halt, going back to MANUAL, the AUTO_LIVE unlock checklist, funding, reading `/pnl`, year-end tax steps (export → compare with the 1099-B → give both to the preparer), and the monthly drill.

## 12. README WARNING (verbatim, top of the Auto mode section and in the `vws ops enable-live` output; the TX-10 disclaimer heads the tax docs)

> **Auto mode places real orders without asking you each time.** In AUTO_LIVE it trades your real money, and you can lose money, including more than a stop-loss suggests (gaps, halts, outages). Nothing in this software predicts or guarantees profits; paper results don't predict live results. Auto mode works only with Alpaca. Start with AUTO_PAPER, keep live limits small, and use `/halt` or `/manual` any time to stop new trades.

## 13. REMINDERS (replace AMENDMENT 01 §10; highest priority)

Audit first · MANUAL is the default, and Telegram can only downgrade · order calls exist only in `alpaca_executor.py` and are reachable only in AUTO_* · no market entries, and every position has a broker-side stop · **no money movement ever: funding is detected, never initiated** · idempotent client_order_id, and look it up before any retry · paper and live bound to keys and endpoint, and never mixed in P&L, tax or reports · AUTO_LIVE needs 20 paper sessions + a report + Stage J + a recent drill + enable-live + live ceilings, starting at a 25% ramp · halts stop entries, never exits · reconciliation mismatch halts · withdrawals alert immediately · TWR excludes deposits · one wash-sale engine shared by compliance and tax, matched to the broker's lot method · tax numbers are estimates and the 1099-B wins · LLMs interpret, code decides · fail closed; UNAVAILABLE is never a pass · Decimal and append-only · banned Alpaca fields stay banned · always pass `feed` explicitly · times shown in CT, stored in UTC · report unverified checks honestly · no profit claims.

· Security: https egress to allowlisted hosts only, TLS always verified · live secrets in the keyring, rotated ≤ 90 days, never logged · hash-pinned deps, SHA-pinned Actions, least-privilege CI · encrypted backups, anchored ledger · private-chat-only, rate-limited Telegram · the LLM gets no tools and no account data · panic halts first, then you revoke keys.

· PROGRESS.md is rewritten in plain English every stage · `vws setup` is the only way he should need to configure the app, stores secrets in the keyring, and can never turn on auto mode · no new features beyond the spec.
