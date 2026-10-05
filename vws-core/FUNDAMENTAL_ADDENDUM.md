# Fundamental Analyst addendum

User instruction received during Execute Stage D, on 2026-10-04. The supplied
"Paul Harris 5-Point Framework" is a user-specified screening policy. It adds a
Fundamental Analyst before human approval of every STOCK proposal.

| Metric | Exact passing condition | Equality |
| --- | --- | --- |
| Gross margin | gross_margin_pct > 40 | Fails |
| Operating margin | operating_margin_pct > 15 | Fails |
| Return on invested capital | roic_pct > 10 | Fails |
| Free cash flow | verified free cash flow > 0 | Zero fails |
| Interest coverage | interest_coverage_ratio > 3 | Fails |

All five conditions must pass. Missing, nonfinite, stale, conflicting or
unverifiable evidence cannot pass. The user requires these seven output fields,
with no extra fields:

```text
gross_margin_pct: float
operating_margin_pct: float
roic_pct: float
fcf_positive: bool
interest_coverage_ratio: float
passed_5_point_framework: bool
failure_reasons: list[str]
```

Margin/ROIC fields use percentage points: 40 means 40%, rather than 0.40.
Interest coverage uses a multiple. Required floats are an explicit exception
for this structured fundamental output to the master spec's Decimal convention.
They must be finite; financial calculations and exact threshold comparisons use
validated Decimal source values in deterministic code. Price/quantity contracts
and the existing CRO/compliance rules retain their exact-money requirements.

An LLM may extract and describe source evidence. It cannot invent missing values,
compute a trade level/size, change a threshold, or override a failed result.
Code must verify returned metrics against the supplied evidence and reject an
inconsistent passed flag or failure list. Unknown or zero interest expense is
not automatically converted to infinite coverage. FCF requires a source numeric
amount or a reproducible operating-cash-flow minus capital-expenditure result;
a bare unverified positive claim is insufficient.

The prompt is supplied now in prompts/fundamental_analyst.md. Stage C was already
completed before this addendum arrived. Stage E will implement FundamentalAnalyst
in backend/agents/fundamental.py using the ModelAgnosticClient interface alongside
the master LLM wrapper, the strict frozen schema, source/provenance contracts,
and tests for every exact threshold, invalid evidence and hostile payload.
Stage F will await its result in swarm_runner.py before HITL. The default policy
is DROP for failed/unavailable STOCK ENTRY/ADD fundamentals. Valid held
REDUCE/EXIT proposals retain WARN findings and are never trapped by an entry
fundamental gate (R-09); all five metrics are still evaluated where evidence is
available and any failure/unavailability is shown to the human. An explicit configured WARN
mode may retain a failed setup only with deterministic failure reasons displayed
on the Telegram card; it must never describe that stock as having passed. Fresh
approval revalidation must preserve/recheck this evidence. ETFs are outside the
user's stock-only framework, with an explicit applicability status in research
metadata. No neutral or positive result is inferred from unavailable evidence.

The analyst and approval integration are scheduled requirements, not implemented
or certified as part of Stage D. This addendum does not weaken the human gate or
permit any order-execution capability.
