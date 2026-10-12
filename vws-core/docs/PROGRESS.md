# Project V progress
Last updated: October 12, 2026 - validation passed its offline safety checks
## Where things stand
Research, tickets, isolated paper auto and reports pass offline safety checks.
Account, tax, watch cards, reducing controls and fake emergency drills pass.
Validation, split exits and readiness reporting now pass offline safety checks.
Readiness stays NOT YET: real evidence and drift are UNVERIFIED.

## What works now
From the vws-core folder in PowerShell:
- Read this page: `.venv\Scripts\python.exe -m vws progress`
- Preview a fake setup: `.venv\Scripts\python.exe scripts/dry_run.py --dry-run NVDA --offline`
- Replay fake data: `.venv\Scripts\python.exe -m vws replay --start 2026-08-01 --end 2026-10-02 --symbols NVDA --offline-fixtures --workers 1`
- Guided configuration: `.venv\Scripts\python.exe -m vws setup`
Fake preview/replay leave your DB closed. Setup confirms saves; AI starts off.
Tax defaults are single, Texas state zero and NIIT zero; federal rates are unset.

## What's being built next
Learning and realtime feeds are next. Then final checks and one build report.

## Waiting on you
Setup later needs the following; broker state stays ALPACA only:
- Paper broker keys and your actual CASH or MARGIN account type.
- A Telegram bot and confirmed private chat, for alerts only to you.
- Plaid credentials and a checking account, for read-only cash checks.
- Your FRED key in setup only; enter a filing name and email there too.
- Federal ST/LT tax rates; enter or import IRA/Roth, Merrill and 401(k) lots.
- Account security, email notices, phone lock, carrier PIN and unused crypto disabled.
- A backup key saved in your password manager when setup shows it.
Do not paste secrets; setup stores keys in the computer's secret store.

## Not checked yet
Real broker, bank, Telegram, FRED and SEC checks need setup.
Validation: 5,179 safety tests passed; 59 integrations were skipped.
The separate replay and warm scan passed; combined critical coverage is 100%.
The overlapping focused checks are not added to the safety test count.
Amendment 02 "MANUAL_CSV path works": DEFERRED (user decision, Oct 8 2026).
Walk-forward speed is UNVERIFIED: 19 windows took 949.845 seconds without finishing.
Mutation, database, container and CI reproduction commands are supplied.
Your secret storage, protections, backup, real stop raises and drill are unchecked.
Real fee attribution, tax forms, delisted history and container secrets need checks.
No real trading edge or READY verdict has been established.

## Try this next
After setup: `.venv\Scripts\python.exe -m vws doctor`, then `-m vws start`.
Start requires verified checks and MANUAL paper. Fake preview/replay remains safe.

## Safety status
MANUAL paper defaults. Isolated auto passed offline checks; live stays locked.
Live still needs paper history/report, account/tax completion, an emergency
drill, explicit host unlock, small limits, account protections, a READY verdict
and five healthy feed sessions. Halts keep held exits and protection available.
After all stages, the final report will list gaps; then building stops.

## Suggestions
Manual account evidence file declined by owner, Oct 8 2026; not built.
Purpose: supply the account ID, restrictions and pending orders missing from CSVs.
Benefit: connect manual holdings/funding. Risk: owner mistakes; all safety limits stay.
Effort: a small input adapter, host checks and offline tests. No safety rule changes.
