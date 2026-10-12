# Reading registered validation

This stage is still under construction. No real edge or READY verdict has been
established. Hypothetical/past results; not indicative of future returns.

The configuration lists a small, explicit set of variants. Registration stores
the file hash, public history and financial-filing hashes, fee schedule, settings
and instrument definitions in the append-only ledger. Each family includes the
unchanged baseline. Trials accumulate across registrations; changing a name or
registering again does not erase the earlier comparisons. The program does not
generate parameter combinations or search for better parameters.

The final 18 calendar months of the first registered history are reserved. The
ordinary replay and hypothetical report paths refuse overlapping dates. Final
validation requires the exact host phrase `RUN HOLDOUT FAMILY`. A durable start
record consumes that family's one-use test even if execution later crashes.
After completion, another invocation displays the stored result. Known
unsupported implementations are refused before a start record is written.

Training starts after a 200-session warm-up. Each following test window spans
six months. Training selects the variant with the highest lower confidence
bound among variants with at least 50 resolved trades; ties and shortfalls use
the baseline. The concatenated selected test windows measure that selection
process. The report also shows each fixed variant's own test-window results.

Each replay window starts flat with the same explicitly supplied hypothetical
cash. It carries positions within that window, reserves pending entries, and
excludes unsettled proceeds from new purchases until the next session. Open
positions at the window's end affect marked equity but are excluded from resolved
trade statistics. Separate windows do not carry positions between them. This
boundary assumption must be considered when reading the estimates.

Daily decisions use public evidence available by that session. Entry fills start
the following session. The cost model includes spread, dated fees, participation
limits, conservative same-bar stop precedence and stop slippage. Price paths,
cash, sizing and CRO decisions are rerun for every variant; only indicator
preparation with identical dependencies can be reused.

The 90% confidence interval uses 10,000 circular block bootstrap samples with
the fixed registered seed. Holm correction applies across each family, and
deflated Sharpe uses cumulative trials. Fewer than 30 out-of-sample resolved
trades is INSUFFICIENT and UNPROVEN. WORKING additionally needs at least 50,
a positive lower bound, profit factor at least 1.2 and deflated Sharpe at least
0.95. A confidence interval is an estimate, not a profit promise.

Without `config/universe_history.csv`, reports warn that today's watchlist has
survivorship bias. The optional file requires exactly `symbol,date_added,date_removed`;
addition is inclusive, removal exclusive, and re-addition needs a separate interval.
Its full contents and hash are registered before evaluation. Symbols require
allowlisted instrument metadata and complete sealed RAW/SPLIT/ALL bars; incomplete
delisted histories fail closed, and actual provider availability is UNVERIFIED.
Membership never changes the live watchlist. Missing public evidence is unavailable, never
a passing observation. Actual broker fills, hypothetical tracker outcomes,
in-sample replay and out-of-sample replay retain separate labels.

The readiness verdict informs the owner and never unlocks a mode. It prefers
AUTO_PAPER evidence when present; otherwise the specified alert-tracker fallback
is visibly labeled hypothetical. Every required safety, sample, drawdown,
benchmark, drill and incident input must be verified. Live execution still needs
its separate host unlock, actual paper history, security checks and healthy
realtime sessions. The build does not enable or run AUTO_LIVE.

Physical A/B brackets count as one resolved proposal only after all acquired
shares are sold and both entry roots are terminal. Current-policy approval
hashes bind the sample; another policy cannot certify its edge. Actual attributed
fees replace CM estimates when available; missing attribution stays labeled
modeled. Trade R uses fill proceeds less purchase costs/fees. Cash distributions
are included in account daily returns, but are not allocated to physical trade R.
Hypothetical results never top up a small physical sample.

Fill quality uses recorded decision/limit prices and genuinely observed arrival
quotes; a stale stop-creation quote cannot stand in for a stop-trigger quote.
Missing evidence is counted separately. Monthly p50/p90 and stop p90 remain
account/environment bound. A realized median above the model by more than two
basis points over at least twenty fills can only raise the effective cost floor.
Replay, registration, tracker, reports and verdict share the calibration hash;
a changed cost context requires new registered validation. Runtime never edits fees.

Edge drift compares current-policy actual PAPER R with that policy's registered
OOS sample by playbook. Missing or short samples remain UNVERIFIED. Incident
windows predating the new durable reconciliation/circuit telemetry are also
UNVERIFIED; absence of older telemetry is never a clean bill of health.

RS, PR, SZ and CRO filter cohorts overlap. They preserve the unsized candidate
as a counterfactual and cannot be added to approval counts or portfolio returns.
Reports show each filter's taken-versus-filtered comparison separately.
