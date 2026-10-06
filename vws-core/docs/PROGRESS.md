# Project V progress
Last updated: October 6, 2026 - research stage checked

## Where things stand
The safety, security, data and research stages passed their offline checks.
The full run passed 3,172 tests; a later focused run checked session expiry.
Readiness and playbook grades have not been measured. Connected alerts,
the setup wizard, reports and auto trading are unfinished.

## What works now
From the vws-core folder in PowerShell:
- Run offline checks: `.venv\Scripts\python.exe -m pytest -q`
- Read this page: `.venv\Scripts\python.exe -m vws progress`
- Preview a synthetic setup: `.venv\Scripts\python.exe scripts/dry_run.py --dry-run NVDA --offline`
Company checks use exact filing numbers. Optional AI summaries start off.
The offline preview checks risk and shows manual instructions; it sends nothing.
Tax estimates wait for your federal rates. External-lot sale checks are tested.

## What's being built next
Connect the research loop to private alerts, fresh approval checks and tickets.
Then build outcome reports, the guided setup, and the remaining safety stages.

## Waiting on you
Nothing right now for offline work. Later setup will need:
- Paper broker keys and CASH or MARGIN account type for connection checks.
- A Telegram bot and confirmed private chat for alerts only to you.
- Plaid credentials and a checking account for read-only cash checks.
- Account protections: two-step security, broker email notices, phone lock,
  carrier PIN, password manager and unused crypto disabled.
- A backup key saved in your password manager when setup shows it.
- Federal ST/LT tax rates. Single, Texas state zero and NIIT zero are saved.
  Enter/import IRA/Roth, Merrill taxable and 401(k) lots; no account logins.
The filing contact was supplied and stays out of these docs. Do not paste secrets.

## Not checked yet
Real broker, bank and Telegram connections need saved credentials.
The paper connection test was skipped because paper keys were not supplied.
AI service checks apply only if you turn summaries on.
Your secret storage, key restrictions, account protections and real backup
remain unchecked. Code-changing checks, another database, deployment packaging
and remote checks have not run here. An older database needs a backed-up upgrade.
Tax imports, sale-screen prompts and final tax reports come in the later stage.

## Try this next
Run the synthetic setup preview command above. It cannot place a trade.

## Safety status
Default mode: MANUAL, paper account. No order calls exist; live remains locked.
No trading session is running here; your saved halt state has not been checked.
Live unlock still needs paper history/report, the safety stage, an emergency
drill, explicit host approval, small limits, account protections, the readiness
verdict and five healthy feed sessions. Last drill: not built or run.
Test backup restores passed October 5; your real backup has not been checked.

## Suggestions
None proposed. Extra features require your plain-words approval before building.
