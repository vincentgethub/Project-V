# AMENDMENT 03: Security hardening

To Codex: this builds on the MASTER SPEC and AMENDMENTS 01–02, which all still apply. Save this verbatim to `docs/spec/AMENDMENT_03.md` and add it to `AGENTS.md`. Same protocol as before: stage report, local commit, honest UNVERIFIED list (a check you couldn't run is never a PASS).

**Placement.** Each item is tagged:
- **[S] Stage S**: cheap code-level items. Run them right after the Step 0 audit fixes, before the next pending stage.
- **[H] Stage H**: host, deploy and CI items.
- **[L] AUTO_LIVE unlock**: appended to AX-40 (§10).

**Already enforced; reference these, don't redo them:** Telegram callback HMAC, allowlist and single-use (01); AST order isolation and no money movement (AX-13/14); withdrawal alerts (FN-04); `/halt` and the drill (XK-01); the keyring backend (XK-10); SecretStr and log redaction; detect-secrets, bandit and pip-audit in CI.

**Out of scope:** terms of service, privacy policy and multi-user auth, until the app is shared with anyone.

## 1. THREAT MODEL

| Threat | Main controls |
|---|---|
| Stolen Alpaca keys: orders and liquidation, but no ACH or wire (Alpaca, Sep 2026); crypto wallet-whitelist calls are still in scope | Keyring, rotation, scoping, egress guard, unknown-order halt (AX-31), panic, Alpaca MFA |
| Compromised host | Non-admin user, disk encryption, keyring, off-box chain anchors, panic runbook |
| Malicious dependency | Hash-pinned lock, minimal deps, pip-audit, SBOM, egress allowlist |
| Telegram account takeover | 2-step verification; Telegram can only downgrade (AX-02); approvals bounded by the CRO and live ceilings; private-chat only; masked mode |
| Bot token leak (fake alerts, webhook hijack) | Webhook check, `/revoke` rotation, allowlist (01) |
| Prompt injection via news | LLM is non-decisive (01); caps, stripping, no tools, flagging |
| Tampered config or ledger | Config-drift alert, hash chain plus off-box anchors |
| Lost or stolen laptop | Disk encryption, keyring, encrypted backups, remote key revoke |
| MITM | TLS always verified, https only, host allowlist |
| SIM swap or email takeover | Dedicated email with passkey or 2FA, carrier port-out PIN |

## 2. ACCOUNTS (SEC-01..02)

- SEC-01 [S] **Checklist.** The README section "Secure your accounts" lists these items. `vws ops attest ITEM` records each one as a dated ledger event. `doctor` shows ATTESTED (date) or WARN, and never claims to have verified a third-party setting.
  1. Alpaca MFA. 2. A dedicated email (for Alpaca, Plaid, GitHub and Telegram recovery) with a passkey or 2FA. 3. A Telegram two-step verification password, plus reviewing Devices. 4. A phone passcode. 5. GitHub 2FA, repo private. 6. A carrier port-out/SIM PIN. 7. A password manager holding every secret and the backup key. 8. Plaid dashboard 2FA. 9. Alpaca email notifications on (`# VERIFY`). 10. Crypto disabled on Alpaca if unused (`# VERIFY`).
- SEC-02 [S] **Alpaca keys.**
  - Per-scope access (Read only / Read & Write / No access) is documented for Broker API credentials. `# VERIFY` whether it exists for Trading API keys. If it does, MANUAL and the data paths use a read-only key, and the AUTO key gets Trading + Data with Funding and Journaling set to No access (attested; never probed destructively).
  - The AX-13 ban explicitly covers crypto wallet, whitelist and transfer endpoints. Those are in a leaked key's scope even though ACH and wire aren't.
  - IP allowlisting isn't generally available: a June 2026 forum post says the field exists but is disabled (`# VERIFY`). If it becomes available, bind the live key to the VPS IP.
  - `doctor` WARNs if a paper key doesn't start `PK` or a live key doesn't start `AK` (only a hint; AX-15 stays authoritative).

## 3. SECRETS (SEC-10..15)

- SEC-10 [L] **Live secrets from the keyring.** In AUTO_LIVE, startup and `doctor` refuse if `ALPACA_LIVE_*`, `TELEGRAM_BOT_TOKEN`, `PLAID_SECRET` or the Plaid access token is set in `.env` or the process env.
- SEC-11 [S] **Plaid access token** lives in the keyring in every mode.
- SEC-12 [S] **Permissions.**
  - POSIX: `.env` needs mode `& 0o077 == 0`, and `data/`, `logs/`, `backups/` need `0700`, owned by the run user. WARN otherwise, and refuse in AUTO_*. A world-writable DB is always refused.
  - Windows: read the ACL (`icacls` or `pywin32 GetFileSecurity`, `# VERIFY`). WARN only, if Everyone, Users or Authenticated Users can read.
- SEC-13 [S] **Rotation.** `vws ops rotate-secret NAME` takes the value with no echo and validates it live (Alpaca `get_account`, Telegram `getMe`, Plaid `/item/get`) before swapping. It writes `SECRET_ROTATED` with an HMAC fingerprint (local salt), never the value. Secret ages show in `/status`, `doctor` and the weekly report, with a WARN at `SECRET_MAX_AGE_DAYS` (90).
- SEC-14 [S] **Never log secrets.** Set the `httpx`, `httpcore`, `urllib3` and `telegram` loggers to WARNING, because their INFO lines carry URLs, and **Telegram URLs contain the bot token**. Extend redaction to `bot\d+:[A-Za-z0-9_-]{30,}`, `APCA-API-*`/`Authorization` headers and Plaid `access-` tokens, including in tracebacks and Telegram error text.
- SEC-15 [S] **Git and backup key.**
  - Run `gitleaks detect` over the **full history** once now. Any finding is STOP-class: rotate first, then optionally purge.
  - Add a pre-commit hook (gitleaks or detect-secrets) and a full-history scan in CI. `.gitignore` covers `.env*`, `*.key`, `*.pem`, `data/`, `backups/`, `logs/`.
  - The backup key (§6) is generated into the keyring. `vws ops show-backup-key` prints it once for his password manager. The RUNBOOK says plainly that losing it means backups can't be restored.

## 4. SUPPLY CHAIN (SEC-20..24)

- SEC-20 [S] **Hash-pinned lock.** Generate `requirements.lock` with `uv pip compile --generate-hashes` or `pip-compile --generate-hashes` (pick one). Install everywhere (Docker, CI, setup script) with `pip install --require-hashes --no-deps -r requirements.lock`. Keep a separate dev lock.
- SEC-21 [S] **Dependency policy.** `docs/DEPENDENCIES.md` gives one justification line per direct dependency, and a test fails on any unlisted one. Prefer the standard library, and justify each new dependency in the stage report.
- SEC-22 [H] **Audits and updates.**
  - pip-audit runs against the lock in CI and in a **weekly scheduled workflow**. A known vulnerability fails the build, and an ignore needs a dated reason. `doctor` shows the last result.
  - `.github/dependabot.yml` covers pip, github-actions and docker, weekly, grouped, no automerge, with the lock regenerated with hashes.
- SEC-23 [H] **SBOM.** CI builds a CycloneDX SBOM from the lock (`cyclonedx-py`, `# VERIFY` flags) and uploads it as an artifact.
- SEC-24 [H] **Actions.** Every `uses:` is pinned to a full 40-hex SHA (version in a comment). Top-level `permissions: contents: read`, elevated per job only where needed. No `pull_request_target`, and no secrets in PR jobs.

## 5. NETWORK (SEC-30..35)

- SEC-30 [S] **One HTTP factory.** `backend/net/http.py: make_client(purpose)` returns httpx with https only, `verify=True`, and timeouts (connect 5 s, read 20 s, total 30 s).
  - It checks the host against the egress allowlist, including on every redirect.
  - Direct `requests.*`/`httpx.*` calls outside it are banned (AST test); SDK internals are exempt.
- SEC-31 [S] **The egress allowlist** is built at startup:
  - `paper-api.alpaca.markets`; `api.alpaca.markets` (AUTO_LIVE only); `data.alpaca.markets` and the stream hosts (`# VERIFY` names)
  - `api.telegram.org`; `www.sec.gov`, `data.sec.gov`; the Plaid host for the configured env
  - the `LLM_BASE_URL` host (only when the LLM is enabled); the `HEALTHCHECK_PING_URL` host
  - RSS hosts and `egress.extra_hosts` from config

  Anything else raises `EgressDeniedError` and writes a `security_events` row.
- SEC-32 [S] **SDK backstop.** alpaca-py uses `requests` and websockets, which bypass the factory. A `sys.addaudithook` on the `socket.getaddrinfo`/`socket.connect` events refuses non-allowlisted, non-loopback hosts. `# VERIFY` the event names for the pinned Python. It fails closed but never breaks logging.
- SEC-33 [S] **TLS is never disabled.** An AST/grep test bans `verify=False`, `CERT_NONE`, `check_hostname = False`, `_create_unverified_context`, and `http://` in code or config (localhost in tests excepted). `doctor` WARNs if `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE` or `PYTHONHTTPSVERIFY` is set.
- SEC-34 [S] **No inbound ports.** Long polling only, and nothing ever binds a server port (tested). `doctor` and startup call `getWebhookInfo`. A non-empty URL is urgent ("bot token may be leaked") and refuses AUTO_*.
- SEC-35 [H] **Docker.**
  - Image: base pinned by digest, built from the lock, `USER 10001`.
  - Compose: `read_only: true` with a tmpfs `/tmp`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, memory/pids limits.
  - Never: `ports:`, `privileged`, or a docker.sock mount. Volumes are only `data/`, `logs/`, `backups/`.

## 6. DATA AT REST (SEC-40..43)

- SEC-40 [S] **Encrypted backups.** Fernet from `cryptography` (pinned; `# VERIFY` the API), with the key in the keyring.
  - Format `.vwsbak`: a header (version, created_at, plaintext sha256) plus ciphertext. No plaintext backups.
  - Restore decrypts, checks the sha256, runs `verify_chain`, and refuses any mismatch. `vws ops restore-test` restores into a temp dir.
  - Off-box copies are his choice and safe because they're encrypted.
- SEC-41 [H] **Disk encryption** (BitLocker or LUKS) is recommended. `doctor` reports it where it can without admin: Linux `lsblk` crypt on the data dir's device; Windows `manage-bde -status` / `Get-BitLockerVolume` (`# VERIFY`; may need admin). Otherwise it reports UNKNOWN plus the attestation.
- SEC-42 [S] **Chain anchors.**
  - After the evening digest, send "🔗 Ledger anchor · seq N · <first 16 hex of head hash>" to Telegram, and optionally append it to `ANCHOR_FILE_PATH` on another device.
  - `vws ledger verify-anchor --seq N --hash H` (or `--file`) recomputes and fails loudly on a mismatch.
  - The weekly report repeats the latest anchor, and the RUNBOOK adds a monthly spot check against an old Telegram anchor. Tampering stays detectable even if the host is owned.
- SEC-43 [S] **Config drift.** Each monitor cycle hashes the non-secret effective config: env values, `config.yaml`, `instruments.csv`, `macro_events.csv`, `accounts.yaml`. A change not preceded by `vws ops apply-config` (`CONFIG_APPLIED`) sends an urgent alert, and in AUTO_* pauses new entries until `vws ops ack-config` is run on the host.

## 7. TELEGRAM BEYOND 01 (SEC-50..54)

- SEC-50 [S] **BotFather settings.** The RUNBOOK covers BotFather `/setjoingroups` → Disable and `/setprivacy` → Enable (verified commands). `doctor` checks `getMe`: `can_join_groups` false and `can_read_all_group_messages` false, otherwise WARN (refuse in AUTO_LIVE).
- SEC-51 [S] **Private chats only.** Updates from any non-`private` chat type are ignored, followed by `leaveChat` and a security event.
- SEC-52 [S] **Strangers and rate limits.**
  - A stranger's first command notifies him: "Someone (id, @username) tried /cmd", at most once per id per hour. Five or more attempts in 24 hours is urgent. Strangers never get a reply.
  - Allowlisted users get a token bucket: `TG_RATE_PER_MIN` (20), and `TG_HEAVY_RATE_PER_MIN` (5) for `/watch`, `/pnl`, `/report`, `/tax`. Excess gets one "slow down" reply, then is dropped. `/halt` and `/pause` are never limited.
- SEC-53 [S] **Masked mode.** `TELEGRAM_MASK_AMOUNTS` (default false).
  - When on: equity, cash, buying power, P&L $, deposit and withdrawal amounts, tax $, position values and qty show as `$•••`.
  - Percentages, symbols, prices and stop/target levels stay visible, and urgent alerts still fire.
  - The CLI and the HTML report are unaffected.
- SEC-54 [S] **Token rotation runbook:** BotFather `/revoke` (kills the old token instantly) → `vws ops rotate-secret TELEGRAM_BOT_TOKEN` → `doctor`.

## 8. LLM (SEC-60..62)

- SEC-60 [S] **Caps and sanitizing.** `max_tokens` on every call, and a post-validation cap on every string field (280 characters for summaries). Before display, strip URLs, markdown, HTML, control, zero-width and bidi characters, then apply the existing escaping.
- SEC-61 [S] **No tools, no account data.** Never send `tools`, `functions` or `tool_choice` (AST test). Prompts carry no secrets and **no account data**: only tickers, headlines and public fundamentals. News is delimited and labelled untrusted.
- SEC-62 [S] **Injection flagging.** A deterministic heuristic flags instruction-like phrases ("ignore previous", "system prompt"), role or `<…>` tags, and links to non-allowlisted hosts. Flagged items log `PROMPT_INJECTION_SUSPECT` and are shown as the bare headline with no LLM summary.

## 9. HOST, MONITORING, INCIDENTS, PRIVACY (SEC-70..75)

- SEC-70 [H] **Host runbook.**
  - Windows: BitLocker, Defender, auto-updates, firewall, screen lock ≤ 5 minutes, and a dedicated **standard (non-admin) user** for vws.
  - VPS: SSH keys only, `PasswordAuthentication no`, `PermitRootLogin no`, ufw deny inbound except SSH, unattended-upgrades, fail2ban, and a dedicated `vws` user.
- SEC-71 [H] **Doctor host checks** return PASS/WARN/UNKNOWN, and UNKNOWN never counts as a pass:
  - running as admin or root (WARN; refuse in AUTO_LIVE)
  - Linux: the sshd_config and `sshd_config.d` settings, and auto-upgrades configured
  - Windows: Defender via `Get-MpComputerStatus` (`# VERIFY`)
  - firewall status where readable
- SEC-72 [S] **Security events and alerts.**
  - Weekly report: event counts by type, new ids, secret ages, and the last drill, anchor verify, pip-audit and restore test.
  - Urgent alerts: repeated strangers, config drift, a webhook found, and an Alpaca account number or key fingerprint change without `SECRET_ROTATED` (that last one also halts entries).
  - Alpaca logins and IPs aren't exposed via the API (`# VERIFY`), so rely on its email notices (SEC-01).
- SEC-73 [S] **`vws ops panic`** (host CLI; works with Telegram and the network down):
  1. Persist HALTED locally *first*.
  2. Stop the entry jobs.
  3. AUTO_* only: cancel unfilled entries, keeping the stop and target legs.
  4. Write `PANIC`.
  5. Notify Telegram if it's reachable.
  6. List the last 30 days of non-FILL activities and any order without the `vws-` prefix.
  7. Print the revoke checklist: Alpaca dashboard → API Keys → Regenerate (invalidates the old pair); BotFather `/revoke`; rotate the Plaid secret or remove the item; GitHub tokens; email password; then `rotate-secret` for each.

  It never flattens positions; that's his call in the Alpaca dashboard. Resuming uses the existing CLI reset.
- SEC-74 [S] **`docs/INCIDENT.md`** (one page): panic → revoke at Alpaca (works from the phone) → rotate the Telegram token → check for withdrawals and unknown orders → restore a verified backup on a clean host → rotate everything → verify anchors. It has variants for a key leak, a lost laptop and a Telegram takeover.
- SEC-75 [S] **Privacy.**
  - Store Telegram numeric ids only.
  - From Plaid, store balances and the account mask only (never account or routing numbers).
  - App logs rotate daily, kept `LOG_RETENTION_DAYS` (30, range 7–365).
  - The ledger, tax records and security events are kept permanently, local plus encrypted backups.
  - No telemetry.

New config, all validated: `ANCHOR_FILE_PATH`, `TELEGRAM_MASK_AMOUNTS`, `LOG_RETENTION_DAYS`, `SECRET_MAX_AGE_DAYS` (30–365), `TG_RATE_PER_MIN`, `TG_HEAVY_RATE_PER_MIN`, `egress.extra_hosts` (YAML; each entry needs a comment).

## 10. AUTO_LIVE ADDITIONS (append to AX-40)

AUTO_LIVE also refuses to start unless all of these hold:
- live secrets come from the keyring (SEC-10)
- the live key is ≤ `SECRET_MAX_AGE_DAYS` old
- SEC-01 items 1–7 are attested within 365 days
- permissions pass (SEC-12)
- a `restore-test` passed within 30 days
- an anchor verify passed within 31 days
- pip-audit is clean within 7 days
- the webhook is empty and the `getMe` group settings pass
- the process isn't running as admin or root
- the egress guard is active

## 11. ACCEPTANCE (fakes everywhere; pytest-socket on)

**Stage S**
1. The factory and audit hook refuse `example.com`, an IP literal, `http://`, and a bad redirect, each logged. Allowlisted hosts pass.
2. The ban test catches planted `verify=False`, `CERT_NONE`, `_create_unverified_context`, a bare `requests.get`, a missing timeout, and `tools=`.
3. AUTO_LIVE with a live key in `.env` or env is refused. Fake-keyring keys pass.
4. A POSIX `0644` `.env` WARNs, and refuses in AUTO_*. A mocked Windows Everyone:R ACL WARNs.
5. `rotate-secret` keeps the old value on failed validation, stores only a fingerprint, and the age WARN fires at 90 days.
6. A forced httpx or Telegram error leaves no secret in the logs.
7. Backup round-trip is byte-identical. A flipped byte, wrong key or bad sha256 refuses. No plaintext backup exists.
8. One modified ledger row makes `verify-anchor` fail at that seq. An intact chain passes.
9. Drift without `apply-config` alerts, and pauses in AUTO_*. With it, nothing happens.
10. Telegram: groups and channels are refused and left; the stranger notice is throttled, with 5 in 24 hours urgent; the 21st command in a minute is dropped while `/halt` never is; a webhook alerts.
11. Masked golden messages hide account $ and qty and keep percentages.
12. LLM: truncation, stripping (URLs, markdown, zero-width, bidi), injection flagging, and no account data in the prompt payload.
13. Panic: HALTED is persisted before any network call, only unfilled entries are canceled, it completes offline, and the checklist is printed. MANUAL never imports the executor.
14. Every lock line has `--hash=`, the install uses `--require-hashes`, and an unlisted dependency fails.
15. A key-fingerprint change without rotation halts entries.

**Stage H**
16. Every workflow `uses:` is pinned to a 40-hex SHA, with top-level `contents: read`, no `pull_request_target`, and the weekly audit and SBOM jobs present.
17. Dockerfile and compose are parsed: non-root `USER`, `read_only`, `cap_drop: ALL`, `no-new-privileges`, no `ports:`, no docker.sock. Optionally, CI checks `id -u` ≠ 0 in the container.
18. Doctor host checks give PASS/WARN/UNKNOWN on mocked probes, and UNKNOWN never counts as PASS.
19. The full-history gitleaks result is in the stage report.

**Stage L**
20. Each §10 condition, when missing, blocks AUTO_LIVE with a named reason.

**Definition of done additions:** SEC- IDs in the traceability matrix. README "Secure your accounts". RUNBOOK sections on host hardening and rotation. `docs/INCIDENT.md`.

## 12. REMINDERS

Append this line to AMENDMENT 02 §13 (don't rewrite it):

· Security: https egress to allowlisted hosts only, TLS always verified · live secrets in the keyring, rotated ≤ 90 days, never logged · hash-pinned deps, SHA-pinned Actions, least-privilege CI · encrypted backups, anchored ledger · private-chat-only, rate-limited Telegram · the LLM gets no tools and no account data · panic halts first, then you revoke keys.