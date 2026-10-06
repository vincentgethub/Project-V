# AMENDMENT 06: Learning loop and real-time context (never self-modifying)

To Codex: this builds on the MASTER SPEC and AMENDMENTS 01–05, which all still apply. Save this verbatim to `docs/spec/AMENDMENT_06.md` and add it to `AGENTS.md`. Same protocol: stage report, local commit, an honest UNVERIFIED list, and a plain-English `docs/PROGRESS.md` rewrite (PG-01..05) at every stage.

**Purpose.** Learn from mistakes honestly, and use a small set of free real-time feeds so auto mode can shrink or pause exposure when the tape or filings turn against a name. Nothing here predicts or promises returns. Every report keeps "Hypothetical/past results; not indicative of future returns."

**Hard ban — no self-coding.** The running process must NEVER modify its own source, config, thresholds, playbook params, `variants.yaml`, fees, or CRO rules. No auto-tuning, no online learning that changes live behaviour, no ML that sizes or picks trades. Learning produces **proposals only**. The user decides; QV + paper come first. An AST/grep test fails on any write under the package root, `config/`, or `.env` outside `vws ops apply-config` / the setup wizard (WZ). Ban `optuna`/`hyperopt`/etc. stays (SEC-21, Amendment 05).

**Everything here can only reduce exposure or add information.** Size multipliers stay in [0, 1] and feed PR-04. Nothing relaxes a CRO rule, adds a trade, or raises size. Halts still stop entries, never exits (AX-30). LLMs interpret; code decides (SEC-60..62). Fail closed: UNAVAILABLE never counts as a pass.

**Build order — Stage W after V.**
- **Stage W** (after K and V): LJ, LP, RT, EVT, AC (accuracy), Telegram `/lessons` `/events`, AX-40 RT health.
- **Fold earlier only if cheap and safe (justify in the stage report):**
  - RT-01 clock skew + Alpaca `/v2/clock`/`/v2/calendar` cache into Stage H/`doctor` if H is still open (already needed for AX-22 early-close).
  - EVT-01 FOMC/BLS/BEA schedule file + annotate-only mode into Stage F briefing (XK-07) as display-only.
  - LJ write-path stubs (schema only, no mining) may land with XA-01 once Stage V exists, so every paper fill can attach a journal row later.

## 1. MISTAKE JOURNAL (LJ-01..08)

Pure module `backend/learning/journal.py`. Append-only rows in the ledger (or `data/journal/`), never rewritten.

- LJ-01 **Triggers** (automatic): every resolved losing trade (R < 0 after CM); every stop-out; every fill with slippage vs CM/XA-01 above the bucket's p90; every missed fill (limit never traded through); every rule-blocked candidate later marked REGRETTED by the user (`/regret <proposal_id>` or CLI); every DQ/ops incident that touched a live decision (STALE/SUSPECT, halt feed down, clock skew).
- LJ-02 **Record fields:** trade/proposal id, symbol, playbook, variant id, mode (paper/live), entry/exit times and prices, R after costs, MFE/MAE in R, stop/target, size multipliers product (PR-04), open RT/EVT context tags (see RT-12), which CRO/overlay rule fired if blocked, fill vs model bps (XA-01), and a **cause_tag** from the fixed taxonomy below.
- LJ-03 **Cause taxonomy** (enum, closed set; unknown → `UNCLASSIFIED` then human review):
  `GAP_THROUGH_STOP` · `LATE_ENTRY` · `NEWS_SHOCK` · `REGIME_SHIFT` · `SLIPPAGE_ABOVE_MODEL` · `EARNINGS_SURPRISE` · `SECTOR_WEAK` · `NORMAL_VARIANCE` · `RULE_BLOCKED_REGRET` · `MISSED_FILL` · `DATA_OPS_INCIDENT` · `HALT_DURING_HOLD` · `DILUTION_EVENT` · `UNCLASSIFIED`
- LJ-04 **Tagging rules are deterministic** (code, not LLM). Examples: gap open through stop → `GAP_THROUGH_STOP`; loss with |R| ≤ playbook's OOS |mean| + 1σ and no other tag → `NORMAL_VARIANCE`; XA-01 slip > model p90 → `SLIPPAGE_ABOVE_MODEL`; held name with RT news category `MATERIAL_NEGATIVE` on the loss day → `NEWS_SHOCK`. The LLM may only draft a plain-English **narrative** field from the structured row (SEC-61: no account $, no tools); it never picks the tag.
- LJ-05 **Bad luck vs mistake.** `NORMAL_VARIANCE` is not a defect. Mining (LP) ignores it for "what to change" and reports it separately as expected noise. Over-reacting to `NORMAL_VARIANCE` is a forbidden behaviour (test: a stream of only NORMAL_VARIANCE losses produces zero proposals).
- LJ-06 **Idempotent:** one journal row per (trigger, trade_id, cause_tag primary). Replays and reconnects dedupe by that key. Journal replay from the ledger is byte-deterministic given the same seed and frozen history (DQ-04).
- LJ-07 `/journal` (Telegram, allowlist, heavy rate-limit, masked mode) and `vws journal recent` show the last N rows in plain English. No secrets, no account numbers.
- LJ-08 Weekly report gains a "Lessons" subsection: counts by cause_tag, NORMAL_VARIANCE share, and open LP proposals (see §2).

## 2. LESSON PROPOSALS (LP-01..07)

- LP-01 **Mining** (`backend/learning/proposals.py`) runs weekly (and on `vws lessons mine`). Inputs: journal rows with n ≥ `lj.min_tag_n` (15) per cause_tag×playbook cell; else INSUFFICIENT — no proposal.
- LP-02 **Statistics reuse QV/ER:** circular block bootstrap and Holm–Bonferroni from QV-05; every proposal's claimed lift needs a 90% CI. Multiple-testing uses the family's **cumulative** `variant_trials` (QV-01). No new optimizer libraries.
- LP-03 **Proposal shape** (written only to PROGRESS.md Suggestions and `data/proposals/<id>.json`): what to change (a single named config key or a new QV variant override), evidence (n, CI, tag breakdown), expected effect with CI, risk, effort. Ideas never build themselves (PG Suggestions rule). Code never applies a proposal.
- LP-04 **Mandatory path:** every accepted-for-testing proposal becomes a QV pre-registered variant (`vws validate register`), counts toward the ≤8 / ≤24 caps, walk-forward + paper before the user flips any live setting. Rejected or abandoned proposals stay in Suggestions as "declined".
- LP-05 **LLM role:** optional wording only. Structured fields are authoritative. If the LLM is down, the proposal still ships with a template sentence.
- LP-06 `/lessons` lists open proposals (allowlist, heavy rate-limit, masked). It cannot enable anything.
- LP-07 Ban: any code path that writes `config.yaml` / env / variants from LP output. Test plants a call and expects failure.

## 3. REAL-TIME FEEDS (RT-01..14)

One async process `backend/realtime/supervisor.py`: bounded queues, exponential backoff with jitter, reconnect, dedupe by event id, budgets in `-m perf`. Tests use fakes; pytest-socket on; no network in unit tests. Every new host → SEC-31 egress allowlist; tokens in keyring (SEC-10); inbound text is untrusted (SEC-60..62).

- RT-01 **Clock.** Compare host UTC to Alpaca `GET /v2/clock` (`https://api.alpaca.markets/v2/clock`, free with trading keys; `# VERIFY` paper host). Skew > `rt.clock_skew_ms` (500) → WARN; > 2000 → UNAVAILABLE for RT gating and block new AUTO entries. Cache `GET /v2/calendar` (early closes) daily; AX-22 already forbids late entries on early-close days.
- RT-02 **Alpaca News** (Benzinga; free on Basic as of docs checked Oct 6, 2026 — `# VERIFY` plan matrix still lists News under Basic).
  - REST: `GET https://data.alpaca.markets/v1beta1/news` (symbols, start/end, limit ≤50; Basic 200 calls/min shared with market data).
  - Stream: `wss://stream.data.alpaca.markets/v1beta1/news`, subscribe watchlist + `*`. Auth: `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY`.
  - Use: deterministic keyword/category rules on headline+summary (strip HTML first). Categories: `MATERIAL_NEGATIVE` (offering, dilution, fraud, going-concern, FDA reject, downgrade cluster), `HALT_NEWS`, `OTHER`. LLM summary is display-only. Never triggers entries or size-ups. Stale if no successful poll/stream event heartbeat in `rt.news_stale_sec` (120).
- RT-03 **Nasdaq Trader Trade Halts RSS** (free). URL: `https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts` (verified live Oct 6, 2026). Poll ≤ 1/min (Nasdaq guideline). Parse `ndaq:IssueSymbol`, `ReasonCode`, halt/resume times. Codes of interest: `T1`/`T2`/`T12` (news), `T3` (news disseminated), `LUDP`/`LUDS` (LULD), `MWC1..3` (market-wide). Covers Nasdaq-listed and other exchange-listed. Host `www.nasdaqtrader.com` → allowlist.
- RT-04 **Alpaca asset status.** `GET /v2/assets/{symbol}`: `tradable`, `status`. On watchlist + open positions, refresh every `rt.asset_poll_sec` (60). `tradable=false` or `status!=active` → block new entries on that symbol; FLAG open position.
- RT-05 **Alpaca corporate actions.** `GET https://data.alpaca.markets/v1/corporate-actions` (types filter; `region=us`; `data_quality=all` for early records). Free with data keys; **no freshness guarantee** (Alpaca warning) — treat as delayed confirmation, not a primary alert. Useful types: `worthless_removal`, `name_change`, mergers, splits (feeds DAT-10). Poll watchlist 2×/session. Stale threshold `rt.ca_stale_hours` (36).
- RT-06 **SEC EDGAR submissions** (free, no key). `https://data.sec.gov/submissions/CIK##########.json` plus ticker map `https://www.sec.gov/files/company_tickers.json`. Required descriptive `User-Agent` with contact email (env `SEC_USER_AGENT`); ≤ 10 req/s aggregate. Watch Forms `8-K` (items), `4` (insider), `13D`/`13G`, `S-3`, `424B*`. For open positions and pending entries only (not the whole universe every minute). New `S-3`/`424B` on a held name → `DILUTION_EVENT` alert; see EVT-04 for exit policy. Hosts already on allowlist.
- RT-07 **FRED** (free API key in keyring). `https://api.stlouisfed.org/fred/series/observations?series_id=VIXCLS&file_type=json` (and optional `T10Y2Y`). Limit 120 req/min. Daily close is enough for a daily-bar system; poll after 16:00 ET. VIX ≥ `rt.vix_stress` (30) → market stress tag; feeds EVT size policy, never a forced flatten. Host `api.stlouisfed.org` → allowlist.
- RT-08 **Economic calendars (published schedules, not live scrapers of lockups).** Store `config/macro_events.csv` (already hashed by SEC-43) curated from:
  - FOMC: `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`
  - BLS CPI / Employment: `https://www.bls.gov/schedule/news_release/cpi.htm` and the BLS year schedule
  - BEA GDP / PCE: `https://www.bea.gov/news/schedule`
  Refresh quarterly via `vws events refresh-schedules` (manual confirm). No headless browser. Missing file → UNAVAILABLE for EVT gating in AUTO.
- RT-09 **OPEX / triple-witching.** Compute monthly options-expiration Fridays (3rd Friday) and quarterly triple-witching in-process — no external feed. Tag the session; default EVT policy `annotate`.
- RT-10 **Fail closed.** Each feed has status OK | DEGRADED | UNAVAILABLE. For AUTO_* entry gating, required feeds (clock, halts, news heartbeat, asset status) must be OK; UNAVAILABLE blocks new AUTO entries and shows a warning on MANUAL cards. Protective exits and AX-27 never wait on RT.
- RT-11 **Hard events → actions** (config `rt.hard_events`):
  - Active halt on symbol → block entries; FLAG open position; **do not exit** (AX-30).
  - `worthless_removal` / delisting corporate action on held name → may run AX-29 (default **on**).
  - Dilution filing (S-3/424B) on held name → default **alert_only**; optional AX-29 if user sets `exit`.
  - MWC1/2 → `half_size` new entries; MWC3 → `no_new_entries` (market-wide).
  Never increase size; never add a trade.
- RT-12 **Context tags on every proposal/trade** (for LJ and ER-04): `halt`, `news_neg`, `vix_stress`, `fomc_day`, `cpi_day`, `jobs_day`, `opex`, `early_close`, `ca_pending`, `edgar_dilution`, etc. ER-04 cohorts measure whether each filter helped.
- RT-13 **Performance budgets** (fakes): supervisor idle CPU < 2%; queue depth cap 1000 with drop-oldest on non-critical news; reconnect ≤ 30 s under a flaky fake; dedupe drops duplicate ids.
- RT-14 **Add to AX-40:** required RT feeds OK for ≥ `AUTO_LIVE_MIN_RT_SESSIONS` (5, floor 5) XNYS sessions before AUTO_LIVE; `doctor` names any unhealthy feed.

## 4. EVENT-DAY POLICY (EVT-01..05)

- EVT-01 Per event type in `config/events_policy.yaml`: `annotate` | `half_size` | `no_new_entries`. Multiplier 1.0 / 0.5 / 0.0 feeds PR-04 (0.0 → skip, ER-04 cohort).
- EVT-02 **Defaults** (conservative, not paralyzing): FOMC decision day `half_size`; CPI and Employment `half_size`; GDP/PCE `annotate`; OPEX `annotate`; session before earnings already DAT-11/CRO-13 — **reference, don't duplicate**; VIX stress `half_size`; early-close already AX-22.
- EVT-03 MANUAL cards always show the active event tags. AUTO respects the policy table.
- EVT-04 Dilution/delist hard events use RT-11, not the soft EVT table.
- EVT-05 `/events` shows the next 10 scheduled macros + today's active tags (allowlist, rate-limit, masked).

## 5. ACCURACY HARDENING (AC-01..04)

Do not redo CM/DQ/ER/QV/XA — reference them.

- AC-01 Clock skew: RT-01; `doctor` surface.
- AC-02 Idempotent event processing: every RT event has a durable idempotency key; at-least-once delivery never double-applies a FLAG or AX-29.
- AC-03 Journal replay golden: freeze a fixture week → identical LJ rows and LP outputs.
- AC-04 `vws doctor` section "Realtime + learning": feed statuses, last heartbeat ages, journal write OK, open proposal count, SEC_USER_AGENT set, FRED key present if VIX policy ≠ off.

## 6. CONFIG

Env: `SEC_USER_AGENT` (required when RT-06 on), `FRED_API_KEY` (keyring), `AUTO_LIVE_MIN_RT_SESSIONS` (5).

YAML:
- `lj` {min_tag_n 15, narrative_llm false}
- `lp` {mine_cron weekly, max_open_proposals 10}
- `rt` {clock_skew_ms 500, news_stale_sec 120, asset_poll_sec 60, ca_stale_hours 36, halt_poll_sec 60, vix_stress 30, hard_events {...}, required_feeds [clock, halts, news, assets]}
- `events_policy` {fomc half_size, cpi half_size, jobs half_size, gdp annotate, opex annotate, vix_stress half_size}
- egress hosts added: `www.nasdaqtrader.com`, `api.stlouisfed.org`, `www.federalreserve.gov`, `www.bls.gov`, `www.bea.gov` (schedule refresh only)

All validated. Taxonomy and ER/QV thresholds stay code constants.

## 7. ACCEPTANCE (goldens, boundaries, no network)

- **Ban:** planted self-modifying write, planted auto-apply of an LP proposal, planted size multiplier > 1 from RT/EVT — each fails. Halt on held name never calls AX-29. Dilution default is alert-only.
- **LJ:** one loss fixture → one row; duplicate trigger → still one row; only-NORMAL_VARIANCE series → zero LP proposals; tag rules hit GAP_THROUGH_STOP and SLIPPAGE_ABOVE_MODEL goldens.
- **LP:** n = 14 → INSUFFICIENT; n = 15 with CI crossing 0 → no "change it" proposal; register path increments `variant_trials`; Suggestions line format golden.
- **RT:** fake halt RSS blocks entry on that symbol; news HTML stripped; SEC User-Agent missing → EDGAR UNAVAILABLE; skew 501 ms WARN / 2001 ms blocks AUTO entries; stale news heartbeat → UNAVAILABLE; dedupe drops second identical id; supervisor reconnect golden.
- **EVT:** FOMC day × half_size on base 40 → 20; no_new_entries → skip; earnings blackout still CRO-13 only.
- **AX-40:** < 5 healthy RT sessions blocks AUTO_LIVE with a named reason.
- **Telegram:** `/lessons`, `/events`, `/journal` allowlist-only, heavy-rate, masked; strangers ignored.
- **Perf:** budgets met or UNVERIFIED with timings; pytest-socket green.

**Definition of done additions:** LJ/LP/RT/EVT/AC IDs in the traceability matrix; RUNBOOK "Learning loop and realtime feeds"; PROGRESS Suggestions seeded with any open LP proposals; `docs/VALIDATION.md` notes that lessons are proposals, not live changes.

## 8. REMINDER

Append this line to AMENDMENT 02 §13:

· Learning: journal and proposals only — never self-modify code, config or thresholds · real-time feeds may only shrink or pause exposure, fail closed, and never relax the CRO · every lesson is a QV variant before any flip · no profit claims.