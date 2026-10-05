# Project V progress
Last updated: October 4, 2026 - audit fixes

## Where things stand
The safety rules, ledger and offline data tests work. The alert service is not
ready yet. Automatic trading has not been built.

## What works now
From the vws-core folder in PowerShell:
- Run the offline checks: `.venv\Scripts\python.exe -m pytest -q`
- Check the trading-code ban: `.venv\Scripts\python.exe -m backend.core.source_guard .`
- Read this page in the terminal: `.venv\Scripts\python.exe -m vws progress`

## What's being built next
The audit fixes passed. Security protections come next, then the expanded data stage.
Daily losses now block new entries until the next market opening.

## Waiting on you
No answer is needed for the current offline work. Later setup will need:
- Your paper broker account type and keys to check real account data.
- Your Telegram bot and private chat to deliver alerts to you.
- Your name and email for the public filing service's required contact header.
- Account security confirmations: broker/email/GitHub/Plaid two-step security,
  Telegram password and devices, phone lock, carrier PIN and password manager.
- Optional: other tax accounts and tax rates; without rates, reports show totals.
Defaults: paper account, fundamentals annotated, AI summaries off, default watchlist.
Setup will guide these choices; do not paste secrets into chat.

## Not checked yet
Real broker, bank and Telegram connections have not been tested.
Database server, Docker container and mutation checks have not run locally.
The new security, setup, alert, evaluation and automatic trading stages are unfinished.

## Try this next
Open this page to follow progress while offline development continues.

## Safety status
Current behavior: MANUAL research only, paper by default. No order calls exist.
Real-money order path reachable: No.
Last emergency drill: not built or run. Last backup restore test: not built or run.

## Suggestions
None proposed. Extra features require your plain-words approval before building.
