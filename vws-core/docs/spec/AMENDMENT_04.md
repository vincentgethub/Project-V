# AMENDMENT 04: Setup wizard and plain-English progress page

To Codex: this builds on the MASTER SPEC and AMENDMENTS 01–03, which all still apply. Save this verbatim to `docs/spec/AMENDMENT_04.md` and add it to `AGENTS.md`. Same protocol: stage report, local commit, honest UNVERIFIED list (a check you couldn't run is never a PASS). AMENDMENT 05 follows in a separate message. Don't add features that aren't in the spec.

**Placement.**
- §1 (progress page) starts **immediately**. Create it now, cover the stages already done, and keep it updated after every stage.
- §2 (setup wizard) is built in **Stage H**, alongside `doctor`. If Stage H is already finished, build it as a small follow-up stage right after the current one. Its secret-storage parts reuse XK-10 and SEC-10..13; build any missing pieces when those stages land.

## 1. PLAIN-ENGLISH PROGRESS PAGE (PG-01..PG-05)

- PG-01 **File.** `docs/PROGRESS.md` is for the owner, who is not a programmer. It's separate from `docs/STATUS.md`, which stays technical. Keep it to one screen, 60 lines at most.
- PG-02 **Sections, always in this order:**
  1. **Where things stand**: one or two sentences, e.g. "The alert system works on paper. Auto mode isn't built yet."
  2. **What works now**: a short list of things he can actually try, each with the exact command or Telegram action.
  3. **What's being built next**: the next stage in one sentence, plus what it will let him do.
  4. **Waiting on you**: every decision, account, key or attestation needed from him (AMENDMENT 01 §9, AMENDMENT 03 SEC-01). Say why each one matters and how to do it, in 1–2 lines. Write "Nothing right now" if it's empty.
  5. **Not checked yet**: every UNVERIFIED item in plain words, e.g. "Haven't tested against a real Alpaca paper account yet (needs your paper keys)."
  6. **Try this next**: one concrete thing he should do or test before the next session.
  7. **Safety status**: the current execution mode (MANUAL / AUTO_PAPER / AUTO_LIVE), whether trading is halted, whether live trading is still locked and which unlock conditions are missing, and the date of the last drill.
  An optional **Suggestions** section may follow section 7: one line per idea (what it does, why it helps, risk, effort). Ideas are never built without his plain-words approval, and none may weaken a safety rule.
- PG-03 **Language.** Plain English, short sentences. No requirement IDs, no jargon without a short explanation, and file paths only when he has to run or open something. Never claim profits, and never call something working if it hasn't been tested.
- PG-04 **Update rule.** Rewrite PROGRESS.md (don't append to it) at the end of every stage, in the same commit as the code. Every stage report ends with a pointer to it.
- PG-05 **Access.** `vws progress` prints it in the terminal. The Telegram `/progress` command sends it: allowlist-only, rate-limited, respects masked mode, and never includes secrets or account numbers.

## 2. SETUP WIZARD (WZ-01..WZ-10)

- WZ-01 **Command.** `python -m vws setup` (alias `vws setup`). It asks plain-English questions one at a time and shows the default in brackets. It's safe to rerun: it shows current values (secrets only as "saved ✓"), and pressing Enter keeps them.
- WZ-02 **Steps, in order:**
  1. Welcome: what it will do and that it never turns on auto mode.
  2. Telegram bot token (hidden input), checked live with `getMe`.
  3. Chat ID: ask him to send `/start` to the bot from his phone, read the update, show the account name, and save only after he confirms. Private chats only; group chats are ignored.
  4. Alpaca **paper** key and secret (hidden input), checked live with a read-only account call on the paper endpoint. Show account status and buying power.
  5. Watchlist: each ticker checked against the asset list (active, tradable, US stock or ETF).
  6. Budget and risk settings, limited to the ranges in the spec.
  7. Timezone: confirm Central Time for display (storage stays UTC).
  8. Summary of everything that will be saved, then a final yes/no.
  9. Write the files (WZ-06).
  10. Run `vws doctor`, explain the results in plain words, and list what's left. Those items feed PROGRESS.md "Waiting on you".
- WZ-03 **Secrets.** Every secret goes to the OS keyring only (XK-10, SEC-10..13). `.env` and `config.yaml` hold only non-secret settings and keyring references. Secrets are never echoed, logged or put in events.
- WZ-04 **Mode lock.** The wizard can only ever write `EXECUTION_MODE=MANUAL`. If an existing file has AUTO_*, leave that value untouched and print the CLI command that controls it. The wizard never collects live keys; live setup goes only through `vws ops enable-live` and its checks.
- WZ-05 **Validation.** Every answer is validated before anything is saved. Invalid answers are re-asked with a plain reason. If a live check fails because of the network, offer retry or skip. Skip leaves the item unset and lists it under "Waiting on you"; an unchecked secret is never marked valid.
- WZ-06 **Safe writes.** Write to a temp file, fsync, then rename. Before changing an existing file, copy it to `<name>.bak-<UTC timestamp>`. Ctrl-C at any point leaves every file unchanged.
- WZ-07 **Sections.** `vws setup --section telegram|alpaca|watchlist|risk` reruns only that part and changes only those keys.
- WZ-08 **Audit.** Each run logs a `CONFIG_APPLIED` event listing the names of changed keys, never their values.
- WZ-09 **Windows first.** It works in Windows Terminal and PowerShell, and with Windows Credential Manager through `keyring`. Avoid characters that break the default Windows console. It also works on Linux.
- WZ-10 **README.** The quick start becomes: install → `vws setup` → `vws start` → approve cards in Telegram. The manual `.env` steps move to an "Advanced" section.

## 3. ACCEPTANCE (fakes everywhere; pytest-socket on)

1. A scripted wizard run (fake prompts, fake Telegram, fake Alpaca, fake keyring) produces a `.env` and `config.yaml` that pass startup validation, with every secret in the keyring and none in any file.
2. A wizard run can never produce `EXECUTION_MODE` other than MANUAL, including when existing files contain AUTO_*: it keeps the existing value untouched and shows the CLI command.
3. Invalid answers (bad token, unknown ticker, out-of-range budget) are re-asked, and nothing invalid is written.
4. Ctrl-C mid-run leaves files byte-identical. Changed files get a `.bak-` copy first.
5. Rerunning with `--section watchlist` changes only `watchlist` in `config.yaml`.
6. Hidden inputs never appear in captured stdout, logs or `CONFIG_APPLIED` events.
7. The chat-ID step refuses to save without explicit confirmation, and ignores group chats.
8. `PROGRESS.md` exists, has all 7 sections in order, is 60 lines or fewer, and contains no requirement IDs. A test fails if a stage commit changes code without updating it.
9. `/progress` is allowlist-only, rate-limited, and never includes secrets or account numbers.

**Definition of done additions:** WZ- and PG- IDs in the traceability matrix; a README quick start using `vws setup`; `docs/PROGRESS.md` current as of the final stage.

## 4. REMINDERS

Append this line to AMENDMENT 02 §13 (don't rewrite it):

· PROGRESS.md is rewritten in plain English every stage · `vws setup` is the only way he should need to configure the app, stores secrets in the keyring, and can never turn on auto mode · ideas go in Suggestions and are never built without approval · no new features beyond the spec.