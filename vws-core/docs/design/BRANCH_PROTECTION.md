# Design note: branch protection and required checks for main (night1 item 8)

Design only. **No ruleset or setting is applied by this note.** Source: Project
V Ideas, `keys-and-branch-protection.md` (sha256 da9e470c…a93c4), section 8.
Decision: Boss, 2026-11-16 02:23 CT: "Item 8 (branch protection ruleset)
adopted as written; apply only after first green CI on imported history."

## Current state (read-only GETs, 2026-11-16 ~16:50 CT)
- `repos/vincentgethub/Project-V/rulesets` returns `[]`.
- `branches/main/protection` returns 404 "Branch not protected".
- `visibility: public`, `default_branch: main`.

## When to apply
In this order:
1. The S1/S2 import push.
2. The first green CI run on the imported history.
3. Apply the ruleset.
4. Every later change goes through a pull request.

Applying it earlier would block the import push.

## Ruleset on main (enforcement active, empty bypass list)
- Block force pushes and deletion; require linear history.
- Require a pull request with 0 approvals (single maintainer); require
  conversation resolution.
- Require status checks, strict (branch up to date).
  - Use the exact check names read from the first green run
    (`gh api repos/vincentgethub/Project-V/commits/<sha>/check-runs`), never
    guessed names.
  - Include both OSes, GD-07, coverage-100, gitleaks and the ci.yml
    byte-identical check.
  - Scheduled workflows (weekly audit; nightly replay, item 5) are not required
    checks: they don't run on pull requests.

## Actions settings
- Default `GITHUB_TOKEN` read-only. Already `read` (backlog audit #13).
- Actions may not create or approve pull requests.
- Require approval for workflows from all outside contributors and forks.
- Keep actions pinned by full SHA. `sha_pinning_required` is `false` today;
  turning it on is part of the same change.
- CODEOWNERS for `.github/workflows/**`, both ci.yml copies, `deploy/**` and the
  guard tests.
- Leave on: secret scanning, push protection, Dependabot, private vulnerability
  reporting.

## Public-visibility risks (repo stays public for now)
- The code shows the strategy logic and risk limits. No secrets, as long as
  gitleaks stays green.
- Never commit REPORT/HANDOFF backups, account IDs or the runtime DB.
- Going private is possible, but private Actions minutes are capped
  (2,000/month on the free plan). One ~2 h full suite on two OSes uses that up
  fast, so changing visibility is Vincent's call, with the cost spelled out.

## Who applies it
The settings are GitHub writes (`gh api` ruleset and settings calls). They need
Vincent's explicit OK at apply time. No builder applies them on its own.
