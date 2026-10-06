# AMENDMENT 05: Professional-grade validation, risk and edge management

To Codex: this builds on the MASTER SPEC and AMENDMENTS 01–04, which all still apply. Save this verbatim to `docs/spec/AMENDMENT_05.md` and add it to `AGENTS.md`. Same protocol: stage report, local commit, an honest UNVERIFIED list, and a plain-English `docs/PROGRESS.md` rewrite (PG-01..05) at every stage.

**Purpose.** Measure honestly whether the playbooks have an edge after costs. Size more carefully at the portfolio level. Give the user a plain-English answer to "is it ready?". Nothing here predicts or promises returns. Every report keeps the line "Hypothetical/past results; not indicative of future returns."

**Non-negotiables, unchanged:** no money movement; order calls only in `alpaca_executor.py`; MANUAL default; Telegram downgrade-only; paper first; the AUTO_LIVE unlock; fail closed; the LLM never decides; no options, shorting or leverage. The `vws setup` wizard (WZ-01..10) can't enable auto mode or anything here that affects trading.

**No optimization.** The only multi-variant evaluation allowed is QV: a small, pre-registered, fixed variant set, evaluated out-of-sample with a multiple-testing correction. No grid, random or genetic search. Ban `optuna`, `hyperopt`, `scikit-optimize`, `deap` and `nevergrad` in the SEC-21 dependency policy (test). No code may generate parameter combinations.

**Everything here can only reduce exposure or add information.** Each size multiplier is in [0, 1]. The CRO stays the final authority and is never bypassed or relaxed.

**Build order.**
- **G+** goes into Stage G if it's still open, otherwise it's the first part of Stage V: CM, DQ-01/03/04, PF-01..03, ER-01..05. These make G's numbers honest.
- **Stage V** comes after K: QV, PR, RS, SZ, EX, EG, GV, XA, DQ-02.
- GV and XA use AUTO_PAPER data when it exists, otherwise EV-01 tracker data, labelled as such.

## 1. COST AND FILL MODEL (CM-01..07)

Pure module `backend/evaluation/costs.py`. EV-01, EV-03, ER, QV and GV all use it, and nothing else models fills.

- CM-01 **Half-spread** (bps) = max(liquidity floor, measured median). Floors by 20-session median dollar volume: ≥ $500M → 2, $50–500M → 5, < $50M → 15. The measurement samples historical SIP quotes from 15:45–15:50 ET after the 15-minute delay (free on Basic, verified; `# VERIFY` the request class and call cost), in multi-symbol calls. With no measurement, use the floor.
- CM-02 **Entry** (limit L): if open ≤ L, fill at min(open × (1 + half_spread), L). If open > L, it fills only when low ≤ L − $0.01 (a trade-through), at L; a touch is NOT_FILLED. Fill at most `cm.max_participation` (0.01) × session volume, otherwise PARTIAL.
- CM-03 **Exits.** Stop: min(open, stop) − half_spread − `cm.stop_slip_atr_frac` (0.05) × ATR14 (a gap fills at open − half_spread). Target T: needs high ≥ T + $0.01, fills at T. Time and signal exits: next open − half_spread. Same-bar stop and target → stop.
- CM-04 **Fees** come from a dated table, `config/fees.yaml` (`effective_from` rows), matched by trade date. Verified Oct 6, 2026:
  - Alpaca commission $0 (`# VERIFY` the account's plan).
  - SEC Section 31: $0.0000206 × sell proceeds from 2026-04-04, until 60 days after the FY2027 appropriation (`# VERIFY` each Oct).
  - FINRA TAF: $0.000195/share sold, cap $9.79, through 2026-09-30. **$0 for 2026-10-01..12-31** (FINRA TAF holiday). For 2027, `# VERIFY`: filings show both $0.000195 and the earlier scheduled $0.000232 (cap $11.61).
  - CAT: $0.000003/share on buys and sells (Alpaca schedule, Sep 1, 2026).
  - Each fee is rounded up to $0.01 per trade (conservative; Alpaca rounds daily totals). Dates before the first row use the first row, with a note.
  - Actual FEE activities (FN-02) replace modelled fees for paper and live.
- CM-05 **After-tax view** (only with TX-08 rates set): net gains per calendar year × (1 − fed_ST − state − NIIT), with every replay trade treated as short-term. Labelled "rough; wash sales and carryovers ignored".
- CM-06 **Interfaces:** `estimate_fill(order, bar, ctx) -> FillResult` and `fees(side, qty, price, trade_date) -> FeeBreakdown`. Decimal at the boundaries.
- CM-07 CRO-04's `STOP_SLIPPAGE_BUFFER` is unchanged. `doctor` WARNs if XA-01's realized p90 stop slippage exceeds it.

## 2. DATA QUALITY (DQ-01..04)

- DQ-01 **Adjustments** (`raw|split|dividend|spin-off|all`, verified). Signals and levels use `split`; RS, benchmarks and replay dividends use `all`; `raw` is kept for audit. Cache keys include the adjustment. A new split refetches that symbol and invalidates its caches; ledger levels stay as recorded (DAT-10 handles open positions).
- DQ-02 **Feed cross-check** (WARN). After the close, flag if |close_sip/close_iex − 1| > max(1%, 0.3 × ATR14/close), or IEX volume > SIP volume. Three consecutive flags → SUSPECT. Same vendor, and IEX is about 2.5% of volume, so it's not independent; the report says so.
- DQ-03 **Bar sanity** (extends DAT-02): low ≤ min(O, C), max(O, C) ≤ high, volume > 0, exactly one bar per XNYS session, and the split/raw ratio changes only on known corporate-action dates. Any violation → SUSPECT.
- DQ-04 Replay and QV read only frozen `data/history/` with a manifest (symbol, adjustment, sessions, sha256). Reports cite the manifest hash.

## 3. EDGE REPORT CARD (ER-01..05)

`backend/evaluation/edge.py`. Per playbook, per variant and per cohort (replay-OOS, paper, live), never mixed, and always after CM costs.

- ER-01 **Metrics:** n, win rate, average win/loss R, payoff ratio, expectancy in R and $ (CRO sizing), profit factor ("n/a" with no losses), max drawdown (% and duration), Sharpe and Sortino of daily returns (×√252), 90% bootstrap CI of expectancy (QV-05), average hold, % time exposed.
- ER-02 **Grades** are constants, not config:
  - **LOSING**: n ≥ 30 and CI upper < 0, or the XK-05 condition. ER calls XK-05's function, and XK-05 alone pauses playbooks.
  - **WORKING**: n ≥ 50, CI lower > 0, PF ≥ 1.2, and for replay OOS-only with DSR ≥ 0.95.
  - **UNPROVEN**: everything else.
- ER-03 Shown in the weekly report, the HTML report (XK-08) and `/edge`, e.g. "BASE_BREAKOUT: UNPROVEN · 22 paper trades · avg +0.18R after costs (range −0.21R to +0.55R) · needs ≥ 50 trades."
- ER-04 **Filter value.** Extend the EV-01 shadow cohort to candidates removed or downsized by RS, PR, SZ or the CRO. Report taken vs filtered-out expectancy for each filter.
- ER-05 **Score calibration.** Expectancy by score band ([7,8), [8,9), [9,10]) with CIs, plus Spearman ρ(score, R).

## 4. WALK-FORWARD VALIDATION (QV-01..07)

- QV-01 **Registry.** `config/variants.yaml` holds families (playbook params, EX, SZ, RS). Each family has ≤ 8 variants and the total is ≤ 24. Each variant is explicit overrides of the baseline, which is always included.
  - `vws validate register` writes `VARIANTS_REGISTERED` (file hash) before any run.
  - Trials per family are **cumulative across registrations** (`variant_trials`, never reset) and feed the deflation.
- QV-02 **Holdout.** At the first registration, the last `qv.holdout_months` (18) of history are frozen, with dates in the ledger, and every run and report refuses them. `vws validate final --family F` (typed confirmation) runs the holdout **once per registration**; later calls only re-display that result.
- QV-03 **Anchored walk-forward.** Train runs from after a 200-session warm-up up to each test window. Test windows are `qv.test_months` (6), stepping 6 months.
  - Per fold, select the variant with the highest train expectancy CI-lower bound among those with ≥ `qv.min_train_trades` (50); ties or shortfalls go to the baseline.
  - Record its next test window. The concatenated test windows are the honest estimate of "choosing among these variants". Each variant's own OOS is also reported.
- QV-04 OOS needs n ≥ 30, otherwise INSUFFICIENT (graded UNPROVEN).
- QV-05 **Statistics.**
  - Circular block bootstrap of per-trade R by exit date: L = max(1, round(n^(1/3))), B = 10,000, seed `qv.seed`, 90% percentile CI. One-sided p = share of resampled means ≤ 0.
  - Holm–Bonferroni across a family at α = 0.10.
  - Deflated Sharpe (Bailey & López de Prado) on the selected OOS daily returns: γ = 0.5772156649, Z = normal CDF, N = cumulative trials, T = days, and SR̂, γ3 (skew) and γ4 (non-excess kurtosis) from the daily series.
    - SR0 = √Var[SR_k] × ((1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e))), with Var over the per-variant OOS daily Sharpes; SR0 = 0 if N < 2
    - DSR = Z((SR̂ − SR0)·√(T−1) / √(1 − γ3·SR̂ + ((γ4 − 1)/4)·SR̂²))
- QV-06 **Bias.**
  - Survivorship: with `config/universe_history.csv` (symbol, date_added, date_removed), the universe is point-in-time and includes delisted names where Alpaca has bars. `# VERIFY` delisted history; the `asof` ticker-mapping parameter exists (verified). Otherwise every report header says "SURVIVORSHIP BIAS: universe = today's watchlist; results likely overstated."
  - Look-ahead: decisions at t use data ≤ t, fills come at t+1 at the earliest, and fundamentals go by `filed` date.
- QV-07 `vws validate walkforward --family F` writes `data/validation/<registration_hash>/` (CSV + a plain-English summary). Re-runs are byte-identical.

## 5. PORTFOLIO RISK OVERLAYS (PR-01..05)

`backend/risk/overlays.py`: pure functions applied before CRO check #1. The CRO never calls them, and they can't relax it.

- PR-01 **Total open risk, a new CRO rule** (next free ID, expected CRO-14).
  - open_risk = Σ max(0, fill − current_stop) × qty over positions, plus (limit − stop) × qty over pending entries.
  - BLOCK if open_risk plus the new risk > `PORTFOLIO_MAX_OPEN_RISK` (env 0.04 of equity, ceiling 0.06). The overlay pre-sizes down to fit; 0 means skip.
  - Add `LIVE_MAX_OPEN_RISK` (0.02) to the AX-42 table.
- PR-02 **Correlation overlay** (size only; AMENDMENT 02's no-hard-rule decision stands). ρ comes from 60-session split-adjusted log returns. k = open positions with ρ ≥ `pr.corr_threshold` (0.70) → multiplier 1.0 / 0.75 / 0.5 / 0.25 for k = 0 / 1 / 2 / ≥3. Fewer than 50 overlapping returns → 0.75 ("correlation unknown").
- PR-03 **Volatility targeting.** σ20 = SPY 20-day log-return stdev × √252. Anchor = the median rolling σ20 over 5 years, or `pr.vol_anchor` (0.16) with less history. m = min(1, anchor/σ20), floored at 0.25.
- PR-04 **Stacking.** M = the product of XK-03 regime, XK-06 ramp, PR-02, PR-03, RS-03 and SZ-01.
  - M < `sizing.min_multiplier` (0.25) → skip (goes to the ER-04 cohort). Otherwise qty = floor(base_qty × M), then the CRO as usual.
  - Multipliers are stored on the proposal. The card shows only those < 1, e.g. "Size 0.5× (vol 0.5)".
- PR-05 **Property test:** each m ∈ [0, 1], final qty ≤ base qty, and no CRO BLOCK ever becomes a PASS.

## 6. RELATIVE STRENGTH AND REGIME (RS-01..05; extends XK-03)

- RS-01 **Sector RS** over the 11 SPDR ETFs (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY): rs = 0.5·(r63 − r63_SPY) + 0.5·(r126 − r126_SPY) on `all`-adjusted closes, ranked 1–11 daily. A stock's sector comes from instruments.csv. Sector ETFs use their own rank; broad ETFs are exempt.
- RS-02 **Stock RS percentile.** Same formula, across the watchlist (n/a if fewer than 20 symbols). Shown on the card, never added to the §4.3 score. `rs.min_stock_percentile` defaults to 0 (off), with a variant at 50 in the registry.
- RS-03 **Sector filter.** `rs.sector_filter`: `annotate` (default in every mode) | `half_size_outside` (0.5 outside the top N) | `top_n` (only the top `rs.top_n_sectors`, 4). PROGRESS.md suggests `top_n` for AUTO only after its variant grades WORKING and beats the baseline OOS. The user flips the setting; code never does.
- RS-04 **Breadth** (`rs.use_breadth: false`): % of watchlist closing above its EMA50. `doctor` WARNs that it's noisy below 50 symbols. When on, XK-03 states are RISK_ON (SPY > EMA200 and breadth ≥ 50%), NEUTRAL (one fails) and RISK_OFF (both fail), mapped by `regime_filter.actions` {RISK_ON: none, NEUTRAL: annotate, RISK_OFF: the XK-03 setting}. When off, XK-03 is unchanged.
- RS-05 `/status` and the XK-07 briefing show "Regime: RISK_ON · Top sectors: XLK, XLI, XLF, XLV".

## 7. EXIT VARIANTS (EX-01..06)

The default is `exits.variant: BASELINE`, today's bracket (AX-23). Each variant is registered in QV and tested in replay first. Replay applies stop changes decided at close t from open t+1.

- EX-01 **SPLIT_1R.** At entry, two brackets with the same stop: A = floor(qty/2) with target entry + 1R, and B = the rest with the normal target. qty must be ≥ 2. Nothing is ever modified, and each bracket has its own broker-side stop, so AX-23/27 hold. client_order_ids end in `-a`/`-b`, and AX-23 allows 2 brackets per proposal.
- EX-02 **SPLIT_1R_TRAIL.** Like EX-01, but B is an OTO with a stop leg only (`OrderClass.OTO`, `# VERIFY`). After A fills, B's stop is raised daily to max(stop, close − `ex.trail_atr_mult` (3.0) × ATR14) via EX-05.
- EX-03 **TRAIL_EMA20.** Baseline bracket. Once MFE ≥ 1R, a daily close below EMA20 triggers the AX-29 exit procedure the next session. No stop moves.
- EX-04 **Time stop** ∈ {10, 20, 30} sessions (baseline 20).
- EX-05 **Stop raise.** Only upward, never via `ReplaceOrderRequest` (still banned).
  - Preconditions: regular hours, outside the first and last 30 minutes, a fresh quote with last_trade ≥ new_stop + 0.5 × ATR14, and qty from the broker.
  - Steps:
    1. Cancel the stop or OCO (`# VERIFY` OCO sibling-cancel semantics).
    2. Poll until canceled (≤ 10 s).
    3. Submit a GTC stop for the broker qty, or an OCO exit (`OrderClass.OCO`, `# VERIFY`) if a target applies.
    4. Confirm it was accepted.
  - On any failure, AX-27 repair places a stop at max(old stop, new stop if it's below last_trade); if that fails, HALT and send an urgent message.
  - Log the unprotected window as `STOP_MOVED` (ms); anything > 30 s is an ops event. AX-12 gains OTO-stop and OCO-exit, in the executor only.
- EX-06 **Availability.** BASELINE, EX-01, EX-03 and EX-04 are allowed in every mode once WORKING. EX-02/05:
  - MANUAL: a suggestion only ("Raise stop to $X")
  - AUTO_PAPER: allowed
  - AUTO_LIVE: `doctor` refuses until the variant is WORKING, there have been ≥ 30 AUTO_PAPER raises with zero failures and no window > 30 s, and a `-m integration` paper test has confirmed the OCO/OTO cancel semantics

## 8. EARNINGS_GAP PLAYBOOK (EG-01..04)

- EG-01 It's off by default: not in `playbooks.enabled`.
  - MANUAL may enable it, with a WARN.
  - AUTO_* refuses it until its QV walk-forward grade is WORKING.
  - It applies to stocks only, never ETFs.
- EG-02 **Earnings event.** The gap session g is the first session after a KNOWN report (DAT-11). If the report time is unknown, g ∈ {d, d+1}, and the gap must occur on one of them.
  - Replay, and live as a fallback, use SEC 8-K Item 2.02 filings from the submissions API as point-in-time report dates, with acceptance time deciding before or after the open (`# VERIFY` the field names `items` and `acceptanceDateTime`).
- EG-03 **Definition** (§4.3 conventions; candidate session t ∈ [g+1, g+3]):

| Playbook | Hard gates | Criteria (points) |
|---|---|---|
| EARNINGS_GAP | open_g/close_{g−1} − 1 ≥ 0.04; RVOL_g ≥ 2.0; min(low over g..t) > close_{g−1} (gap unfilled); close_t ≥ (high_g + low_g)/2; close_t > EMA50_t | gap 4–8% (2) / >8% (1); RVOL_g ≥ 3.0 (2) / ≥ 2.0 (1); range_pos_g ≥ 0.7 (2) / ≥ 0.5 (1); EMA50 > EMA200 (2); r63_stock > r63_SPY (1); (entry − stop) ≤ 2×ATR14 (1) |

- EG-04 **Levels.** entry = high_t + $0.01. stop = min(entry − STOP_ATR_MULT × ATR14, min(low over g..t) − $0.01). This replaces the 10-session swing low, which sits before the gap. All other §4.3 level rules apply unchanged: max_stop_pct, target_r, R/R ≥ 1.5, sizing, CRO-13.

## 9. CONFIDENCE SIZING (SZ-01..02)

- SZ-01 `sizing.confidence_mode`: `off` (default; 1.0) | `bands`, with default bands [9, 10] → 1.0, [8, 9) → 0.75, [7, 8) → 0.5. Values must be in (0, 1], non-decreasing, and the lowest band must start at MIN_SETUP_SCORE. Feeds PR-04.
- SZ-02 It's a QV family. PROGRESS.md recommends `bands` only if ER-05 shows expectancy rising with score (ρ > 0, CI excluding 0) and the variant isn't worse than the baseline OOS.

## 10. MONTHLY GO-LIVE VERDICT (GV-01..05)

- GV-01 Computed after the close on the first session of each month and on `/verdict`. It goes into PROGRESS.md section 1 "Where things stand" (PG-02), with no new section, and is stored as a `VERDICT` ledger event with its input hash.
- GV-02 **READY** needs all of these. The `gv.*` validator accepts only values *stricter* than these defaults.
  1. ≥ 50 resolved paper trades over ≥ 60 sessions.
  2. Expectancy CI lower > 0R after costs.
  3. Max drawdown ≤ 10%, and CRO-09 REDUCE_ONLY never hit.
  4. Sharpe ≥ SPY total-return Sharpe over the same dates − 0.2.
  5. No circuit-breaker or reconciliation HALT in 20 sessions.
  6. A drill within 31 days, and AMENDMENT 03 §10 green.
  7. No playbook in use LOSING, and no XA-02 flag.
- GV-03 **STOP** if any of these hold: CI upper < 0 with n ≥ 30; max drawdown ≥ 12%; an unresolved reconciliation mismatch; a `PANIC` this month; ≥ 2 circuit-breaker halts this month. Otherwise **NOT YET**, listing every unmet item.
- GV-04 Plain English, e.g. "NOT YET · 32 of 50 trades · avg +0.21R after costs, but the range still includes zero (−0.05R to +0.47R) · max drawdown 4.1% (limit 10%) · next check Nov 2." Plus the disclaimer.
- GV-05 It never unlocks anything. **Add to AX-40:** the latest verdict is READY and ≤ 35 days old; `ops enable-live` prints it.

## 11. PERFORMANCE (PF-01..06)

- PF-01 Vectorized numpy/pandas indicators (`backend/indicators/vectorized.py`) alongside simple loop references (`reference.py`). Wilder seeding is defined once (SMA of the first 14). Golden plus hypothesis equivalence tests: relative difference ≤ 1e-9, and identical levels after Decimal quantization.
- PF-02 Cache in `data/cache/ind/<symbol>_<adj>_<last_session>_<params_hash>_<code_version>.npz` (numpy, no new dependency), invalidated by DQ-01 splits.
- PF-03 Replay precomputes indicator and gate arrays once per symbol. The day loop does lookups plus sequential portfolio/CRO sizing. QV variants that share indicator params reuse the arrays. `ProcessPoolExecutor` (cores − 1) with a deterministic merge.
- PF-04 Budgets (`-m perf`, fakes, warm cache): 100-symbol daily scan < 60 s; 20 symbols × 7 years replay < 3 min; 8 variants × 20 symbols × 7 years walk-forward < 15 min on 4 cores. `vws profile scan|replay` writes the cProfile top 20.
- PF-05 No numba, cython, polars, dask or GPU unless a budget fails and profiling names the hotspot (justified per SEC-21).
- PF-06 Output hashes are identical across runs and worker counts.

## 12. EXTRAS (XA-01..02)

- XA-01 **Fill-quality tracking (TCA).** Each paper or live fill records the decision price, limit, arrival quote, fill price, and slippage in bps vs arrival and vs CM. A monthly table shows p50/p90 by liquidity bucket. If realized p50 exceeds the model by > 2 bps over ≥ 20 fills, that bucket uses the realized value. Calibration only ever raises costs. *Why:* it ties every backtest and verdict to the costs he actually pays.
- XA-02 **Edge-drift flag.** With ≥ 30 paper trades in a playbook, flag EDGE DRIFT if paper mean R is below the 5th percentile of its walk-forward OOS bootstrap. The flag shows in ER, GV and PROGRESS, and nothing changes automatically. *Why:* it catches "the backtest looked better than reality" early.

## 13. CONFIG

Env (risk-related, frozen): `PORTFOLIO_MAX_OPEN_RISK` (0.04, ceiling 0.06), `LIVE_MAX_OPEN_RISK` (0.02).

YAML:
- `qv` {holdout_months 18, test_months 6, min_train_trades 50, max_variants_per_family 8, max_variants_total 24, bootstrap_resamples 10000, seed 20261006}
- `cm` {spread_floor_bps {high 2, mid 5, low 15}, stop_slip_atr_frac 0.05, max_participation 0.01}
- `pr` {corr_threshold 0.70, corr_lookback 60, corr_multipliers [1.0, 0.75, 0.5, 0.25], vol_anchor 0.16}
- `sizing` {min_multiplier 0.25, confidence_mode off, confidence_bands}
- `rs` {sector_filter annotate, top_n_sectors 4, min_stock_percentile 0, use_breadth false}
- `exits` {variant BASELINE}, `ex` {trail_atr_mult 3.0}
- `gv` {…}
- `config/fees.yaml`, `config/variants.yaml`, `config/universe_history.csv` (optional)

Every value is validated. ER grade thresholds are constants.

## 14. ACCEPTANCE (hand-computed goldens, boundaries, determinism, no network)

- **CM:** open 100.00, L 101.00, 2 bps → 100.02. Open > L: low = L → NOT_FILLED; low = L − 0.01 → filled at L. Gap-through stop → open − half-spread. Selling 100 sh @ $50 on 2026-09-15 = SEC $0.11 + TAF $0.02 + CAT $0.01 = $0.14; on 2026-10-15 = $0.12; buying 100 = $0.01. The participation cap gives PARTIAL. The after-tax line only appears when rates are set.
- **DQ:** each sanity violation → SUSPECT; the cross-check threshold boundary and the 3rd consecutive flag; a split invalidates caches; the manifest hash appears in reports.
- **ER:** [+2, −1, +0.5, −1, +3]R → win 60%, average win 1.833R, payoff 1.833, expectancy 0.70R, PF 2.75. Grade boundaries: n 49/50, CI lower 0 vs > 0, PF 1.19/1.2. LOSING equals XK-05.
- **QV:**
  - Registry: rejects a 9th variant per family and a 25th total; the trial count is cumulative.
  - Holdout: dates refused; `final` runs once, then only re-displays.
  - Folds and selection: fold boundaries; the baseline wins ties and trade shortfalls.
  - Statistics: the same seed gives identical bootstrap results; DSR equals a hand-computed example (N = 1 → PSR); Holm on fixed p-values.
  - Bias and policy: a future-poison fixture (bars after t changed) never changes the decision at t; the banned-optimizer test passes.
- **PR:** $10,000 equity, 4% cap, $320 open risk, $2 risk/share, base 60 → 40 sh. σ20 0.32 vs 0.16 → 0.5; 0.10 → 1.0. k = 2 → 0.5; short history → 0.75. M 0.375 on 40 → 15; M 0.2 → skip. PR-05 property test.
- **RS:** ranking golden on 11 synthetic ETFs; each filter mode; breadth state boundaries; breadth off leaves XK-03 unchanged.
- **EX:**
  - Replay: goldens per variant (same-bar ambiguity, a gap through a raised stop, odd qty for the split).
  - EX-05 with fakes: cancel failure; submit failure → repair → HALT; the window is recorded; a stop is never lowered; no `ReplaceOrderRequest`.
  - AUTO_LIVE: `doctor` refuses EX-02/05 without the evidence.
- **EG:** one pass, plus one fail per gate (gap 3.99% vs 4%, a filled gap, t = g + 4); unknown report time; the stop uses the gap-period low; refused in AUTO unless WORKING.
- **SZ:** edges at 8.0 and 9.0; invalid bands rejected; off → 1.0.
- **GV:** each READY item fails at its boundary; each STOP trigger; golden NOT YET text; looser thresholds rejected; AX-40 blocked by a stale or non-READY verdict.
- **PF:** equivalence tests; budgets met, or reported UNVERIFIED with timings; identical hashes with 1 and 4 workers.
- **XA:** calibration never lowers costs; the drift flag at exactly the 5th-percentile boundary.

**Definition of done additions:** all new IDs in the traceability matrix; `docs/VALIDATION.md` (walk-forward, holdout, multiple testing, survivorship and costs in plain English); a RUNBOOK section "Reading the edge report and the verdict"; current grades and verdict in PROGRESS.md.

## 15. REMINDER

Append this line to AMENDMENT 02 §13:

· Validation: a small pre-registered variant set only, never optimization · out-of-sample with costs, deflated for trials, the holdout touched once · overlays only shrink size and the CRO stays final · the verdict informs, never unlocks · no profit claims.