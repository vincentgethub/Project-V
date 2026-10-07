# Project V progress
Last updated: October 7, 2026 - private alert stage checked offline

## Where things stand
Safety, security, data, research and private alerts passed their offline gates.
The latest full run passed 3,366 tests; 44 connection/database checks were skipped.
All required safety branches were covered. Fake services checked the alert loop.
Setup, outcome reports and auto trading are unfinished. Live stays locked.

## What works now
From the vws-core folder in PowerShell:
- Run offline checks: `.venv\Scripts\python.exe -m pytest -q`
- Read this page: `.venv\Scripts\python.exe -m vws progress`
- Preview a synthetic setup: `.venv\Scripts\python.exe scripts/dry_run.py --dry-run NVDA --offline`
The preview uses RAM, shows manual instructions and sends nothing.
Private approval code rechecks fresh evidence and creates one manual ticket.
Quiet queues, expiry, phone halts and held-position warnings passed fake tests.
Read-only fill matching records observed trades. Optional AI summaries start off.
Tax defaults are single, Texas state zero and NIIT zero; federal rates are unset.

## What's being built next
Build outcome reports and historical replay with dated costs and data checks.
Then finish guided setup, account reports and the remaining safety stages.

## Waiting on you
Nothing right now for offline work. Later setup will need:
- Paper broker keys and your actual CASH or MARGIN account type.
- A Telegram bot and confirmed private chat for alerts only to you.
- Plaid credentials and a checking account for read-only cash checks.
- Two-step security, broker email notices, phone lock, carrier PIN,
  password manager and unused crypto disabled.
- A backup key saved in your password manager when setup shows it.
- Federal ST/LT tax rates; enter/import IRA/Roth, Merrill and 401(k) lots.
The filing contact was supplied and stays out of these docs. Do not paste secrets.

## Not checked yet
Real broker, bank and Telegram connections need saved credentials.
One paper test and 43 database tests were skipped, not passed.
Code-changing checks, another database, container build/runtime and remote CI
have not run here. Linux CI jobs and exact reproduction commands are supplied.
Your secret storage, account protections and real backup remain unchecked.
The setup/start commands and connected service are still being built.
An older database needs a backed-up upgrade; yours has not been opened.
Tax imports, sale-screen prompts and final tax reports come in the later stage.

## Try this next
Run the synthetic setup preview command above. It cannot place a trade.

## Safety status
Default mode: MANUAL, paper account. No order calls exist; live remains locked.
No trading session runs here; your saved halt state has not been checked.
Live unlock still needs paper history/report, the safety stage, an emergency
drill, explicit host approval, small limits, account protections, a readiness
verdict and five healthy feed sessions. Last drill: not built or run.
Test backup restores passed October 5; your real backup has not been checked.

## Suggestions
None proposed. Extra features require your plain-words approval before building.
