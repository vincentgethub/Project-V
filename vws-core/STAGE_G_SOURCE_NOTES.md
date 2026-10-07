# Stage G source verification

Checked October 7, 2026. Real account subscription and commission-plan checks
remain UNVERIFIED. No paid request or owner-account call was made.

- [SEC FY2026 order](https://www.sec.gov/files/rules/other/2026/34-104909.pdf):
  Section 31 sells use $20.60 per million from April 4, 2026. Annual review is
  still required; no future appropriation date is invented.
- [Current Alpaca schedule](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf),
  revised October 1: equity sell SEC rate 0.0000206, TAF zero in the current
  holiday, CAT 0.000003 per NMS share on both sides. Standard retail commission
  zero is a model assumption until the actual plan is checked. Broker fee
  components round up per account/day; CM conservatively rounds each per trade.
- [FINRA holiday filing](https://www.sec.gov/files/rules/sro/finra/2026/34-106409.pdf):
  October–December 2026 TAF is zero; January 2027 resumes prior rates. Footnote
  18 cites SR-FINRA-2026-020 maintaining current rates through December 2028.
  The earlier [2024 schedule proposal](https://www.finra.org/sites/default/files/2024-11/sr-finra-2024-019.pdf)
  contains the old 2027 increase; the later filing supersedes it. The modeled
  January row uses 0.000195/share and $9.79 cap with an overdue-review note.
- CM's first known combined row is September 1, 2026. Earlier replay dates
  use that row with an explicit approximation note, as specified. This does
  not claim that historical fees were identical. Actual bound FEE observations
  replace modeled amounts through the shared pure interface; FN-02 ingestion
  remains in its scheduled later stage.
- [Stock historical bars](https://docs.alpaca.markets/us/reference/stockbars)
  support raw, split, dividend, spin-off and all adjustments, plus `asof` ticker
  mapping. [Pinned SDK enums](https://alpaca.markets/sdks/python/api_reference/data/enums.html)
  expose only RAW/SPLIT/DIVIDEND/ALL; no missing spin-off enum is fabricated.
- [Quote request schema](https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html)
  supports multi-symbol StockQuotesRequest with explicit SIP/start/end; actual
  quote measurement entitlement/call cost remain subject to fake-SDK and later
  connected checks. SIP end stays at least sixteen minutes behind the clock.

Implementation assumptions: unknown ADV20 uses the lowest-liquidity floor;
entry prices round up and exits down to cents. Zero-volume bars fail DQ-03.
Close decisions never fill that session; protective stops may apply on the fill
session. Time/signal exits fill the next open. CM-05's after-tax line follows its
specified yearly net-gains multiplication, including negative years; it appears
only with all TX-08 rates set. This rough arithmetic ignores wash sales and
carryovers and does not establish actual loss-credit eligibility. No tax advice;
1099-B is authoritative for actual taxes. TX-08's actual set-aside tracker retains
its separate max(0, gains) rule.

DQ-01's later replay-distribution requirement supersedes the earlier replay use
of the dividend-ignoring tracker. Tracker outcomes still exclude dividends.
Replay uses the adjacent ALL/SPLIT adjustment-factor change and prior native
close (converted for a known same-day split) to estimate distribution return.
It requires exact proportional OHLC factors; ambiguous or reversing factors
are rejected. Per-share estimates round down to eight decimal places, whole-
share credits round down to cents, and income never enters settled entry cash.
No actual payment date or broker dividend is inferred. Reports disclose this
as an adjusted-return estimate. SPY comparisons use ALL-adjusted closes.

The frozen manifests certify exact local file contents and declared source
identity, not independent vendor authenticity. Synthetic acceptance tapes have
a saved request/report label and isolated cache; they cannot establish account
performance, an edge or live-unlock evidence. Observed-history collector and
notifier startup composition remains H. Live vendor/subscription verification
is not replaced by the fake SDK call-count and delay tests.
