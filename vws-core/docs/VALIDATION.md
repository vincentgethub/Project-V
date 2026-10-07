# Reading the evaluation

Hypothetical/past results; not indicative of future returns.

Stage G measures the fixed playbooks. The alert tracker models approved,
rejected, expired and pending alerts and fresh-check failures. Positive-share
CRO vetoes have a separate shadow view. These are hypothetical fills; a paper
or live label identifies the managed account, not its actual broker returns.

Every result uses the same cost model: liquidity-floor or measured half-spread,
trade-through limit entries, a volume cap, conservative stop-first exits and
dated fees rounded up per component. Gaps and next-open exits can differ from
the recorded levels. The first partial entry is not topped up. Fees before the
first dated row use that row and are disclosed as estimates. Broker FEE activity
ingestion arrives in Stage J; subscription and commission-plan facts are still
unverified. Signal prices use split adjustments, with native RAW fills and
whole shares. A fractional or subcent split is unavailable, never a fabricated
fill. The alert tracker ignores dividends. Replay uses adjacent ALL/SPLIT
distribution-return estimates, conservatively rounded down and kept outside
settled entry cash; these are not actual dividend payments or payment dates.
Ambiguous adjustments refuse the run. SPY uses ALL-adjusted total-return prices.

An R is the filled shares' recorded limit-to-stop risk. Reports subtract costs
before calculating R, win/loss averages, expectancy and profit factor. Daily
equity uses actual modeled holdings and cash; unavailable seed/history, too much
concurrent exposure or invalid split evidence makes those metrics unavailable.
Replay reserves pending entries, excludes sale proceeds until T+1 and cancels
pending entries after a latched entry halt. Held exits remain available.

The 90% range comes from 10,000 circular block resamples, with a fixed seed.
It describes uncertainty in the recorded sample. Fewer than 30 resolved trades
prints "too few trades to judge". WORKING requires at least 50, a positive lower
bound and profit factor at least 1.2; replay also needs out-of-sample validation
and its required deflated Sharpe. An in-sample replay remains UNPROVEN even with
positive averages. LOSING uses the specified negative range/XK-05 condition.
Grades never change settings or pause a playbook by themselves.

Replay reads only sealed local manifests with exact file hashes. Fundamentals
use filed dates and age limits, and missing evidence skips the stock. Decisions
at a close cannot fill that session. Indicators and gates are precomputed once;
cash and CRO admission remain sequential. Proof hashes match with one and four
workers. Synthetic acceptance tapes and filings are labeled in the saved proof,
report and output; their caches are separate from observed-history caches.

Today's watchlist omits historical and delisted names: survivorship can overstate
the result. No point-in-time universe or out-of-sample result is claimed yet.
The later Stage V adds the small registered variant set, cumulative trial
counts, anchored walk-forward windows, family multiple-testing correction and
one-use holdout. There is no parameter search. Its readiness verdict informs
the owner and is a live-unlock prerequisite; it never unlocks trading itself.
Stage W also requires five healthy realtime feed sessions before live unlock.

Rough after-tax replay numbers appear only with all supplied rates. The saved
report includes those rates; yearly net and the estimate are checked against
the per-alert evidence. Wash sales/carryovers are excluded from this rough
view. The shared tax engine and authoritative 1099-B handle actual tax records.
These numbers are estimates, not tax advice. No money is moved.
