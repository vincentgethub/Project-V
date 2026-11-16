# Macro calendar sources (night1 item 16)

Retrieved: 2026-11-16 09:14-09:20 UTC (03:14-03:20 CT) by the night1 builder.
Every row in `config/macro_events.csv` was read from the official page in its
`source` column at that time. No row is estimated or carried from memory.
Owner review (`CONFIRM MACRO SCHEDULES`, RUNBOOK) still applies before use.

Scope: rest of the current quarter (2026-11-16 to 2026-12-31) and the next
quarter (2027-01-01 to 2027-03-31). Earlier Q4 2026 releases had already
happened at retrieval and are not listed.

| date | et_time | event | source |
| --- | --- | --- | --- |
| 2026-11-25 | 08:30 | GDP | https://www.bea.gov/news/schedule/full |
| 2026-11-25 | 08:30 | PCE | https://www.bea.gov/news/schedule/full |
| 2026-12-04 | 08:30 | NFP | https://www.bls.gov/schedule/news_release/empsit.htm |
| 2026-12-09 | 14:00 | FOMC | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm |
| 2026-12-10 | 08:30 | CPI | https://www.bls.gov/schedule/news_release/cpi.htm |
| 2026-12-23 | 08:30 | GDP | https://www.bea.gov/news/schedule/full |
| 2026-12-23 | 08:30 | PCE | https://www.bea.gov/news/schedule/full |
| 2027-01-08 | 08:30 | NFP | https://www.bls.gov/schedule/news_release/empsit.htm |
| 2027-01-13 | 08:30 | CPI | https://www.bls.gov/schedule/news_release/cpi.htm |
| 2027-01-27 | 14:00 | FOMC | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm |
| 2027-02-05 | 08:30 | NFP | https://www.bls.gov/schedule/news_release/empsit.htm |
| 2027-02-11 | 08:30 | CPI | https://www.bls.gov/schedule/news_release/cpi.htm |
| 2027-03-05 | 08:30 | NFP | https://www.bls.gov/schedule/news_release/empsit.htm |
| 2027-03-10 | 08:30 | CPI | https://www.bls.gov/schedule/news_release/cpi.htm |
| 2027-03-17 | 14:00 | FOMC | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm |

Pages and what they showed:

- Federal Reserve, https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm:
  2026 meetings Oct 27-28 and Dec 8-9; 2027 meetings Jan 26-27, Mar 16-17,
  Apr 27-28, Jun 8-9, Jul 27-28, Sep 14-15, Oct 26-27, Nov 16-17. The row uses
  the meeting's last day. https://www.federalreserve.gov/newsevents/2026-december.htm
  lists the Dec 9 FOMC statement at 2:00 p.m. (Oct 28 likewise on the October
  page). The 2027 monthly calendar pages returned 404 at retrieval, so the 2027
  rows use the same 2:00 p.m. ET statement time: a judgment call, flagged for
  owner review.
- BLS CPI, https://www.bls.gov/schedule/news_release/cpi.htm: Dec 10 2026,
  Jan 13, Feb 11, Mar 10 2027, all 08:30 AM.
- BLS Employment Situation (NFP), https://www.bls.gov/schedule/news_release/empsit.htm:
  Dec 04 2026, Jan 08, Feb 05, Mar 05 2027, all 08:30 AM.
- BEA, https://www.bea.gov/news/schedule/full: GDP second estimate Q3 2026 and
  Personal Income and Outlays (PCE) October 2026 on Nov 25 08:30 AM; GDP third
  estimate Q3 2026 and Personal Income and Outlays November 2026 on Dec 23
  08:30 AM.

UNAVAILABLE (left out on purpose, consumers fail safe):

- GDP and PCE for 2027 Q1: BEA had not published its 2027 schedule.
- Earnings (`earnings_calendar.csv`): not fetched from a provider; header only.
- ETF sector weights (`etf_sector_weights.csv`): not fetched from the issuers;
  header only.
- `substantially_identical.csv`: stays empty by ruling; grouping is the owner's
  tax judgment, not a fetched fact.
- `blackout_windows.csv`: header only. Macro blackout windows are derived at
  runtime from this calendar (`MacroEvent.window`: release day 00:00 ET to
  release + 30 minutes), so copying them here would double-count.
