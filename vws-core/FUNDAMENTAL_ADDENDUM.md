# Superseded fundamental addendum

The earlier user addendum was superseded by Amendment 01 sections 2.2 and 4.2.
Its unused extraction prompt and planning document were the only artifacts built.
No analyst, client, provider or approval integration was implemented.

The current contract is deterministic Decimal computation in
backend/agents/fundamentals.py, sourced from SEC companyfacts by
backend/data/sec_edgar.py, with MetricResult and FundamentalReport contracts.
Exact strict thresholds remain 0.40 gross margin, 0.15 operating margin,
0.10 ROIC, zero free cash flow, and 3 interest coverage. Edge cases, applicability,
point-in-time facts and status roll-up follow the amended FA requirements.
The default pipeline mode is annotate. The optional LLM prompt supplies only a
one-line narrative; code owns every value, status, failure reason and decision.
Valid held exits remain exempt from entry-only restrictions.

See docs/spec/AMENDMENT_01.md section 4.2 for the authoritative complete contract.
Implementation and real-fixture acceptance tests belong to Stage E.
