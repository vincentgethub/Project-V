# Design note: Linux key storage without a plaintext .env (night1 item 7)

Design only. This note adds no code. Source: Project V Ideas,
`keys-and-branch-protection.md` (4,683 B, sha256 da9e470c…a93c4), section 7.
Decisions: Boss, 2026-11-16 02:23 CT (BOSS-CHECKLIST-night1.md, item 9).

## Problem
`deploy/vws.service:15` on main loads `EnvironmentFile=/opt/vws-core/.env`, a
plaintext file on disk. `docker-compose.yml:5` does the same with `env_file`.
The build host shares one OS user across every bot, so anything at rest there
is readable by all of them.

## Decision: one loader, strict order, refuse otherwise
1. **systemd credentials** (a real Linux host with systemd as init):
   - `systemd-creds encrypt --with-key=tpm2` (or `host+tpm2`) into
     `/etc/credstore.encrypted/vws.<name>`, root-owned.
   - The unit has one `LoadCredentialEncrypted=vws.<name>:...` line per secret.
   - The app reads `$CREDENTIALS_DIRECTORY/vws.<name>`, a 0400 ramfs that only
     this service can read.
   - `--with-key=host` (no TPM) is allowed, but it is recorded as weaker: the host
     key is a root-only file on the same disk. That protects against other users
     and leaked backups, not against root.
2. **A real Secret Service through keyring** (desktop/PC).
   - The plaintext and file backends are refused by class: keyrings.alt
     PlaintextKeyring/EncryptedKeyring, the chainer fallback, and subclasses.
3. **Injected in-memory** (shared build host only).
   - Off by default. Enabled only by `VWS_SECRET_SOURCE=injected`, **PAPER keys only**.
   - Values arrive as process env from the masked store at launch and are never
     written to disk, logs, the DB or reports.
   - Honest risk: same-user processes can read `/proc/<pid>/environ`. Real-money
     keys never go on that host.
4. **Anything else is a loader refusal, `LOADER_REFUSAL`** (the code name since
   a6ffa19; raised as `SecretsUnavailableError`): nonzero exit, no partial start.

Never allowed: `.env` secrets, a plaintext keyring, a passphrase file next to
the ciphertext, or keys in a CLI argument.

## Headless fallback when Secret Service / D-Bus is absent
There is no silent fallback.
- With systemd as init, use (1).
- Without systemd and without a real Secret Service, the only remaining source is
  (3), and it is restricted to paper keys. Otherwise the start refuses.
- The night1 box (PID 1 is tini, no TPM) can therefore run paper only. 24/7 there
  was measured and accepted as FAIL (item 10, Boss 07:40).

## Status of the decisions
- Built as night1 item 9 on `night1/secret-loader` @ a6ffa19 (ACCEPTED). It provides:
  - the single loader `select_secret_store` in backend/security;
  - deploy/vws.service with `EnvironmentFile` removed and five `LoadCredentialEncrypted=` lines;
  - compose with `env_file` removed;
  - `.env` refused when it holds secret settings;
  - doctor showing the source name only.
- The non-secret paper `THEME_CAPS` travels in the unit's `Environment=`
  (night1 item 17, @57bcc09, ACCEPTED).
- Open, DEFERRED-TO-SETUP:
  - `systemd-analyze verify` and `systemctl show vws -p Environment` on the
    real host (evidence handoff D-1);
  - `systemd-creds encrypt` of each secret on that host;
  - whether a TPM exists there (otherwise `host` key, recorded as weaker).
- Vincent's call: whether a systemd host (for example a VPS, which costs money)
  is wanted for 24/7.
