# Project V progress
Last updated: October 9, 2026 - extras passed offline; manual CSV deferred

## Where things stand
Research, tickets, isolated paper auto and reports pass their offline safety tests.
Account and tax stage passed offline; the manual CSV connection stays disabled.
Journal, watch cards, reducing controls, reports and fake emergency drills pass.

## What works now
From the vws-core folder in PowerShell:
- Read this page: `.venv\Scripts\python.exe -m vws progress`
- Preview a fake setup: `.venv\Scripts\python.exe scripts/dry_run.py --dry-run NVDA --offline`
- Replay fake data: `.venv\Scripts\python.exe -m vws replay --start 2026-08-01 --end 2026-10-02 --symbols NVDA --offline-fixtures --workers 1`
- Guided configuration: `.venv\Scripts\python.exe -m vws setup`
Preview/replay leave your DB closed. Setup confirms saves; AI starts off.
Tax defaults are single, Texas state zero and NIIT zero; federal rates are unset.

## What's being built next
Next: registered validation and readiness, then the learning and realtime stages.

## Waiting on you
Setup later needs the following; broker state stays ALPACA only:
- Paper broker keys and your actual CASH or MARGIN account type.
- A Telegram bot and confirmed private chat, for alerts only to you.
- Plaid credentials and a checking account, for read-only cash checks.
- Your FRED key in setup only; also enter a filing name and email there.
- Federal ST/LT tax rates; enter or import IRA/Roth, Merrill and 401(k) lots.
- Account security, broker email notices, phone lock, carrier PIN, password
  manager and unused crypto disabled; setup will list the checks.
- A backup key saved in your password manager when setup shows it.
Do not paste secrets; setup stores keys in the computer's secret store.

## Not checked yet
Real broker, bank, Telegram, FRED and SEC checks need setup.
The full extras gate passed 4,644 tests; 58 checks were skipped.
Amendment 02 "MANUAL_CSV path works": DEFERRED (user decision, Oct 8 2026).
The seven-year, 20-stock fake replay passed in 78.144 seconds; worker results match.
Seven later safety tests pass; required coverage is 100% across both runs.
Skipped checks are not passes. Code-changing tests, the optional database,
container build/runtime and remote CI have not run here; commands are supplied.
Your secret storage, protections and actual backup remain unchecked.
Real fee attribution, tax forms and container secret storage need checks.
No real trading edge or readiness verdict has been established.

## Try this next
After setup: `.venv\Scripts\python.exe -m vws doctor`, then `-m vws start`.
Start requires verified checks and MANUAL paper. Fake preview/replay remains safe.

## Safety status
MANUAL paper defaults. Isolated auto passed offline checks; live stays locked.
Live still needs paper history/report, account/tax completion, an emergency
drill, explicit host unlock, small limits, account protections, a readiness
verdict and five healthy feed sessions. Fake drills pass; a real drill is unchecked.
Your real backup is unchecked. After all stages, the final report lists gaps; then stop.

## Suggestions
Manual account evidence file declined by owner, Oct 8 2026; not built.
Purpose: supply the account ID, restrictions and pending orders missing from CSVs.
Benefit: connect manual holdings/funding. Risk: owner mistakes; all safety limits stay.
Effort: a small input adapter, host checks and offline tests. No safety rule changes.
