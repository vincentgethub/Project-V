# Project V progress
Last updated: October 13, 2026 - narrow CI repairs awaiting checks
## Where things stand
Research, tickets, paper auto, account/tax reports and fake drills pass offline checks.
Validation, split exits and readiness reporting pass offline checks.
Readiness stays NOT YET: real evidence and drift are UNVERIFIED.

## What works now
From the vws-core folder in PowerShell:
- Read this page: `.venv\Scripts\python.exe -m vws progress`
- Preview a fake setup: `.venv\Scripts\python.exe scripts/dry_run.py --dry-run NVDA --offline`
- Guided configuration: `.venv\Scripts\python.exe -m vws setup`
Fake preview/replay keep your DB closed. Setup confirms saves; AI starts off.

## What's being built next
Learning and realtime passed the final offline checks.
FINAL_REPORT.md is complete. Build work has stopped for your setup.

## Waiting on you
Setup later needs paper broker keys and your CASH or MARGIN account type;
your Telegram bot/private chat; read-only Plaid checking credentials;
your FRED key and filing name/email; federal ST/LT rates and marked outside lots.
Check account security, notices, phone lock, carrier PIN and unused crypto.
Save the backup key in your password manager when setup shows it.
Setup stores keys in the computer's secret store; do not paste them here.

## Not checked yet
Real broker, bank, Telegram, FRED and SEC checks need setup.
Final safety suite: 5,316 passes, 59 skips and complete required branch coverage.
Replay, warm scan and realtime fakes passed: 5,319 distinct available passes total.
Amendment 02 "MANUAL_CSV path works": DEFERRED (user decision, Oct 8 2026).
Walk-forward speed is UNVERIFIED: 19 windows took 949.845 seconds without finishing.
Mutation, database, container and CI reproduction commands are supplied.
Your host protections, backups, real stop raises, tax forms and drill are unchecked.
No real trading edge or READY verdict has been established.

## Try this next
After setup, follow the backup-first migration steps in RUNBOOK.md.
Run `.venv\Scripts\python.exe -m vws doctor`, then `-m vws start` when checks pass.
Start defaults to MANUAL paper. Missing credentials never count as a pass.

## Safety status
ALPACA-only state. MANUAL_CSV refuses startup. MANUAL paper defaults; live is locked.
Live still needs paper history/report, account/tax completion, an emergency
drill, explicit host unlock, small limits, account protections, a READY verdict
and five healthy feed sessions. Halts keep held exits and protection available; lessons never apply themselves.

## Suggestions
DECLINED, owner Oct 8 2026: manual account evidence file. Purpose: fill CSV account/restriction gaps. Benefit: manual holdings/funding checks. Risk: input mistakes. Effort: adapter and tests. Not built; all safety limits stay.
