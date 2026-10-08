# Project V progress
Last updated: October 8, 2026 - host stage passed offline

## Where things stand
Research, tickets, host checks and reports pass their offline safety tests.
Account/tax records, auto trading, validation and learning remain unfinished.

## What works now
From the vws-core folder in PowerShell:
- Read this page: `.venv\Scripts\python.exe -m vws progress`
- Preview a fake setup: `.venv\Scripts\python.exe scripts/dry_run.py --dry-run NVDA --offline`
- Replay fake data: `.venv\Scripts\python.exe -m vws replay --start 2026-08-01 --end 2026-10-02 --symbols NVDA --offline-fixtures --workers 1`
- Guided configuration: `.venv\Scripts\python.exe -m vws setup`
Preview and replay do not open your DB. Setup needs confirmation before saving.
Private approvals create manual tickets after fresh checks; AI starts off.
Tax defaults are single, Texas state zero and NIIT zero; federal rates are unset.

## What's being built next
Build account and tax records, then paper auto trading,
emergency drills, validation and the learning loop, in that order.

## Waiting on you
Nothing right now for offline work. Setup will later need:
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
The full safety run passed 4,080 tests; 46 service checks were skipped.
The current seven-year, 20-stock fake replay passed in 97.7 seconds.
All required safety and report coverage is 100%; missing history blocks tickets.
Skipped checks are not passes. Code-changing tests, the optional database,
container build/runtime and remote CI have not run here; commands are supplied.
Your secret storage, protections and actual backup remain unchecked.
Containers lack native secret storage; tax imports and sale prompts are unfinished.
Your DB has not been opened; older versions need a backed-up upgrade.
No real trading edge or readiness verdict has been established.

## Try this next
After setup: `.venv\Scripts\python.exe -m vws doctor`, then `-m vws start`.
Start requires verified checks and MANUAL paper. Fake preview/replay remains safe.

## Safety status
Default: MANUAL, paper account. No order calls exist; live remains locked.
No trading process runs here; your saved halt state has not been checked.
Live still needs paper history/report, account/tax completion, an emergency
drill, explicit host unlock, small limits, account protections, a readiness
verdict and five healthy feed sessions. Last drill: not built or run.
Test backup restores passed October 5; your real backup remains unchecked.
After all stages, the final build report will list gaps and next steps; then stop.

## Suggestions
None proposed. Extra features need your plain-words approval before building.
