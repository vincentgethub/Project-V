# AMENDMENT 04: Setup wizard and plain-English progress page

To Codex: this builds on the MASTER SPEC and AMENDMENTS 01–03, which all still apply. Save this verbatim to `docs/spec/AMENDMENT_04.md` and add it to `AGENTS.md`. Same protocol: stage report, local commit, honest UNVERIFIED list. This is the last amendment for now. After it, finish the stages in order, and don't add features that aren't in the spec.

**Placement.**
- §1 (progress page) starts **immediately**: create it now and keep it updated after every stage, including the ones already done.
- §2 (setup wizard) is built in **Stage H**, alongside `doctor`. Its secret-storage parts reuse XK-10 and SEC-10..13; build any missing pieces when those stages land.

## 1. PLAIN-ENGLISH PROGRESS PAGE (PG-01..PG-05)

- PG-01 **File.** `docs/PROGRESS.md` is for the owner, who is not a programmer. It's separate from `docs/STATUS.md`, which stays technical. Keep it to one screen, 60 lines at most.
- PG-02 **Sections, always in this order:**
  1. **Where things stand**: one or two sentences, e.g. "The alert system works on paper. Auto mode isn't built yet."
  2. **What works now**: a short list of things he can actually try, each with the exact command or Telegram action.
  3. **What's being built next**: the next stage in one sentence, plus what it will let him do.
  4. **Waiting on you**: every decision, account, key or attestation needed from him (AMENDMENT 01 §9, AMENDMENT 03 SEC-01). Say why each one matters and how to do it, in 1–2 lines. Write "Nothing right now" if it's empty.
  5. **Not checked yet**: every UNVERIFIED item in plain words, e.g. "Haven't tested against a real Alpaca paper account yet (needs your paper keys)."
  6. **Try this next**: one concrete thing he should do or test before the next session.
  7. **Safety status**: the current execution mode (MANUAL / AUTO_PAPER / AUTO_LIVE), whether any real-money path is reachable (should say "No" until AUTO_LIVE is unlocked), and the date of the last drill and backup test.
- PG-03 **Style.** Plain words and short sentences. No jargon without a 3–5 word explanation the first time, no requirement IDs, and no code beyond the commands he types. Never say something works unless its tests ran and passed. Never claim or imply profits.
- PG-04 **Updates.** Rewrite it (don't append) at the end of every stage report and in the same commit. Add a "Last updated" line with the date and the stage. The stage report's last line is "PROGRESS.md updated."
- PG-05 **Access.** `python -m vws progress` prints it in the terminal, and the Telegram `/progress` command (allowlisted users only, heavy rate limit per SEC-52) sends sections 1, 4 and 7. Telegram never shows secrets or account numbers.

## 2. SETUP WIZARD: `python -m vws setup` (WZ-01..WZ-10)

- WZ-01 **Purpose.** A guided first-run setup, so he never edits `.env` or YAML by hand. It's interactive in the terminal, with plain-English questions, and safe to rerun at any time to change one answer. It has no GUI and no web server.
- WZ-02 **Flow.** Each step shows what it's for, how to get the value (with the exact website page to open), and a default where one exists:
  1. Welcome, and a summary of what will be set up. Confirm that it starts in **MANUAL + paper**.
  2. Display timezone (default America/Chicago).
  3. Telegram: walk through BotFather (`/newbot`, `/setjoingroups` → Disable, `/setprivacy` → Enable). Paste the bot token (hidden input). Then "send /start to your bot now": the wizard listens briefly via `getUpdates`, shows the first chat's name and numeric id, and asks him to confirm it's him. That saves `TELEGRAM_CHAT_ID` and the allowlisted user id. Then send a test message.
  4. Alpaca **paper** keys (hidden input), validated live with `get_account()` against the paper endpoint. Show the account status and buying power. **Never ask for live keys here**; live keys are only added via `vws ops secrets set` after the AX-40 unlock.
  5. Account type (CASH or MARGIN) and broker state source (ALPACA or MANUAL_CSV), with one line explaining each.
  6. Watchlist: offer the default (AMENDMENT 01 §9) and let him add or remove tickers. Validate every symbol against `instruments.csv`, and explain any rejection.
  7. Fundamentals mode (annotate or require), with a one-line explanation. `SEC_USER_AGENT` is built from his name and email.
  8. LLM: default off. If he turns it on, ask for the base URL, model, key (hidden) and daily budget, and require the price fields.
  9. Optional: tax rates and filing state (TX-08; skipping keeps totals only), external accounts for wash sales (TX-01), and `HEALTHCHECK_PING_URL`.
  10. Security: generate the backup key into the keyring and show it **once** with "save this in your password manager now" (SEC-15). Then walk through the SEC-01 checklist and record each item he confirms with `vws ops attest`. Skipped items stay WARN.
  11. Run `vws doctor` and show the results in plain English, with a fix for each red or WARN line.
  12. Finish with what to do next: `vws start`, what the first alert will look like, and where `docs/PROGRESS.md` is.
- WZ-03 **Where answers go.** Secrets go to the keyring (`SECRETS_BACKEND=keyring` is set by the wizard), never to `.env`. Non-secret env values go to `.env`, and strategy/schedule values go to `config.yaml`, keeping AMENDMENT 01's one-home-per-key rule. Files are written atomically (temp file + rename) with SEC-12 permissions. Back up any existing file to `*.bak-<timestamp>` before changing it.
- WZ-04 **Validation.** Every answer goes through the same Pydantic models and ranges as startup, and the wizard explains errors in plain words and re-asks. It never writes a value startup would reject.
- WZ-05 **Never upgrades mode.** The wizard cannot set `EXECUTION_MODE` to anything except MANUAL, and cannot enable AUTO_PAPER or AUTO_LIVE. On rerun it shows the current mode and the exact host command to change it (AX-02 / AX-41). The AST and acceptance tests include the wizard.
- WZ-06 **Rerun and edit.** On rerun, it shows the current settings (secrets shown as "saved ✓", never the value) and a menu to change one section. `vws setup --section telegram|alpaca|watchlist|llm|tax|security` jumps straight there.
- WZ-07 **Logging.** Every change writes a `CONFIG_APPLIED` ledger event (SEC-43) with the changed key names, never secret values. Hidden input uses `getpass`, and nothing typed appears in logs, shell history or tracebacks.
- WZ-08 **Offline and failure.** If a live validation can't reach the service, say so plainly. He can then save the value marked UNVERIFIED, and doctor will flag it. Ctrl-C at any point leaves existing files untouched.
- WZ-09 **Windows first.** It works in Windows Terminal/PowerShell and with Windows Credential Manager via `keyring`. Avoid characters that break the default Windows console. It also works on Linux.
- WZ-10 **README.** The quick start becomes: install → `vws setup` → `vws start` → approve cards in Telegram. The manual `.env` steps move to an "Advanced" section.

## 3. ACCEPTANCE (fakes everywhere; pytest-socket on)

1. A scripted wizard run (fake prompts, fake Telegram, fake Alpaca, fake keyring) produces a `.env` and `config.yaml` that pass startup validation, with every secret in the keyring and none in any file.
2. A wizard run can never produce `EXECUTION_MODE` other than MANUAL, including when existing files contain AUTO_*: it keeps the existing value untouched and shows the CLI command.
3. Invalid answers (bad token, unknown ticker, out-of-range budget) are re-asked, and nothing invalid is written.
4. Ctrl-C mid-run leaves files byte-identical. Changed files get a `.bak-` copy first.
5. Rerunning with `--section watchlist` changes only `watchlist` in `config.yaml`.
6. Hidden inputs never appear in captured stdout, logs or `CONFIG_APPLIED` events.
7. The chat-id step refuses to save without explicit confirmation, and ignores group chats.
8. `PROGRESS.md` exists, has all 7 sections in order, is ≤ 60 lines, and contains no requirement IDs. A test fails if a stage commit changes code without updating it.
9. `/progress` is allowlist-only, rate-limited, and never includes secrets or account numbers.

**Definition of done additions:** WZ- and PG- IDs in the traceability matrix; a README quick start using `vws setup`; `docs/PROGRESS.md` current as of the final stage.

## 4. REMINDERS

Append this line to AMENDMENT 02 §13 (don't rewrite it):

· PROGRESS.md is rewritten in plain English every stage · `vws setup` is the only way he should need to configure the app, stores secrets in the keyring, and can never turn on auto mode · no new features beyond the spec.