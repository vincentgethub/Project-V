# Instrument metadata

The default scan list contains 20 US large-cap stock candidates, SPY and 11 sector
ETFs. This list does not attest to current liquidity or broker eligibility:
quotes/ADV and the setup broker-asset check must establish them before entries.
Other retained examples (QQQ, TQQQ, SH) are outside the default scan list.
Leveraged and inverse examples remain nontradable and subject to the CRO veto.

The 11 sector mappings were checked against [State Street's issuer page](https://www.ssga.com/us/en/intermediary/capabilities/equities/sector-investing/select-sector-etfs)
on 2026-10-06. Their declared sector produces conservative 100% sector exposure.
Stock sectors/themes are explicit provisional operator policy and require review.

The former broad-ETF sector percentages were demonstration guesses. They were
removed. SPY and QQQ now have UNKNOWN look-through and cannot pass sector caps
until verified weights are supplied; SPY remains usable as a price benchmark.
The [SPY issuer page](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy)
publishes sector percentages dated 2026-10-05, but those rounded figures total
100.01%. They were neither silently normalized nor entered as exact evidence.
The CSV contract requires exact finite fractions summing to one. No current
ETF holding verification is claimed. Setup must explain missing metadata.
