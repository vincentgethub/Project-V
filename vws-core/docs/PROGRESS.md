# Project V progress
Last updated: October 5, 2026 - security stage checked

## Where things stand
The safety rules, security protections and offline data tests passed their checks,
and the alert service and automatic trading are unfinished.

## What works now
From the vws-core folder in PowerShell:
- Run the offline checks: `.venv\Scripts\python.exe -m pytest -q`
- Read this page in the terminal: `.venv\Scripts\python.exe -m vws progress`
- Test encrypted backups and emergency halts: `.venv\Scripts\python.exe -m pytest -q backend/tests/test_backups.py backend/tests/test_ops_security.py`

## What's being built next
Expand market and account data reads, with shared limits, news and earnings checks.

## Waiting on you
No answer is needed for the current offline work. Later setup will need:
- Paper broker keys and CASH or MARGIN account type, to check real account data.
- A Telegram bot and private chat, to deliver alerts only to you.
- Plaid dashboard credentials and a checking account, for read-only cash checks.
- Confirm broker, recovery email, GitHub and Plaid two-step security;
  Telegram password/devices, phone lock, carrier PIN and password manager.
- Confirm broker email notices and unused crypto disabled. Save the backup key
  in your password manager when setup shows it once; losing it prevents restores.
- Optional: other tax accounts, rates and filing state; skipping rates shows totals.
The company-filing contact has been provided; its details stay out of these docs.
Defaults: paper account, fundamentals annotated, AI summaries off, default watchlist.
Setup will guide these choices; do not paste secrets into chat.

## Not checked yet
Real broker, bank and Telegram connections need your saved credentials.
AI service checks matter only if you choose to turn summaries on.
Your computer's secret storage, account protections and real backup need checking.
Broker key scopes and approved-IP restrictions have not been confirmed.
Checks that deliberately change code, another database and deployment packaging
have not run on this computer. Remote checks have not run.
Setup, connected alerts, reports and automatic trading are unfinished.

## Try this next
Run `.venv\Scripts\python.exe -m vws progress` from the vws-core folder.

## Safety status
Current behavior: MANUAL research only, paper by default. No order calls exist.
Real-money order path reachable: No.
Last emergency drill: not built or run. Backup restore tests passed October 5,
2026 with test data; your real database backup has not been checked.

## Suggestions
None proposed. Extra features require your plain-words approval before building.
