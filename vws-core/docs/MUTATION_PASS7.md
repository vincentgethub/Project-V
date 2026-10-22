# Pass 7: child partition, fingerprint checks and security dependency updates

Status: final normal and random suites pass at 100% coverage; final hooks and two separate commits precede the single push. The owner approved the two security dependency bumps and full generated comment annotations. Both updated locks audit with zero findings and install successfully into separate clean venvs with hashes enforced. No commit, push or dispatch yet.

## Resolved dependency audit findings

| Lock | Package | Locked | Advisory | Fixed version reported by audit |
|---|---|---|---|---|
| Runtime and development | certifi | 2026.7.22 | PYSEC-2026-4320 / GHSA-6q48-6c7w-9gw2 | 2026.10.19 |
| Development | virtualenv | 21.14.5 | CVE-2026-113725 / GHSA-vxj4-q4g9-crj7 | 21.14.7 |
| Development | virtualenv | 21.14.5 | CVE-2026-113722 / GHSA-c978-59m8-c77v | 21.14.9 |

The old locks failed on these advisories. The approved updates are certifi 2026.10.19 and virtualenv 21.14.9. Both updated-lock audits now return zero findings, without ignores or allowances. The unchanged compiler ran with Python 3.12.14 and pip-tools 7.6.1; its full generated output is retained. Classification: 18 approved version/hash changed lines, 258 comment changed lines, zero other changed lines; original 62 runtime and 141 development records remain. Every one of the 2,470 unique package hashes matches public PyPI JSON across 141 releases. Two separate clean hashed installs and both pip checks pass. [Dependency report](DEPENDENCY_SECURITY_BUMPS.md) lists every changed annotation line and the same-publisher provenance for old, immediately preceding, and target releases. No other dependency changes.

## Completed ownership and fingerprint work

- Exactly 135 nonempty child jobs, named `<original-parent>-<n>`, under all 63 original source jobs.
- Exactly 15,467 IDs assigned once; zero missing, duplicate or crossed-parent assignments.
- MATCHED 15,456; NEW 11; GONE 1. Every NEW/GONE mutation is on an approved changed line. All 379 duplicate fingerprint groups are paired in source order.
- Each parent union is its mapped MATCHED set plus NEW identities, with GONE removed. The exact fingerprint multiplicity is preserved, including duplicates.
- Child split regeneration is byte-identical; SHA256 `7898a2e550038160daab907d1681d98e5e075579a7ae38087934b0b890925132`.
- Fingerprint map regenerated twice using the authored CI checker, byte-identical; canonical LF CSV SHA256 `2215743e95287a806b9ed544a188b70036c2fa21ff4d291d1c0465ed53f38515`. Only source-line whitespace is normalized; mutated text remains exact.
- All six approved tax fingerprints and IDs are unchanged and unique, under the original tax owner and its `tax-1` child. No approval was added. The 24 proposals remain individually UNAPPROVED and are re-keyed in config and docs.
- Native preflight PASS: 18 files, 135 jobs, 15,467 freshly generated unique IDs, exactly-once ownership. `build/pass7/child-native-preflight.log` records the result.
- Both main CI copies contain the 135-child matrix and fingerprint regeneration check. Native mutmut command, test selection, 100% gate, fail-fast=false and 120-minute job limit stay intact.
- Each weekly-audit copy changes only the default working-directory to `vws-core`; both copies are byte-identical. No dispatch has occurred.

The map requested for commit is `build/pass7/inventory-fingerprint-map.csv`. It remains local and ignored until explicitly force-added as a single authorized artifact at commit time; no commit has occurred. The authored check uses the exact 5dc9af8 baseline from Git, regenerates the map, rejects differences and rejects NEW/GONE mutations on unchanged lines. No historical kill/survivor result is reused.

The 135-child matrix is below GitHub's [256-job limit](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstrategymatrix).

## Coverage selection, native timeout and kill evidence

Clean statistics map tests to functions through native trampoline hits. Each mutant runs only its mapped tests, ordered by observed test-call duration in the default fork runner; it does not rerun the entire selected cohort for every mutant. Missing mappings remain no-tests failures. No selection setting changed.

Pinned mutmut 3.8.0 defaults remain timeout_constant=1 and timeout_multiplier=15. For estimated mapped-test call time T seconds, wall timeout is 15*(T+1), CPU limit is ceil(30*(T+1)); SIGKILL follows the CPU limit by the existing one-second margin. These are per-mutant bounds, separate from the unchanged 120-minute job limit. No timeout changed.

New audit evidence records phase, exception type, test ID, mapped tests collected/run and panic cases, without exception values or secret-bearing output. Assertions and pytest expectation failures are distinguished from setup/runtime/import failures, unfinished workers and native timeouts. Raw native killed tags caused only by crashes or missing assertion evidence are not qualified kills and fail certification. Existing native gates still run; no threshold is lowered. Reports are evidence, not a test cache; no report is read to avoid executing a mutant. The runner requires a fresh mutants directory and audit directory.

No fresh native mutation run has occurred before the required local checks and single push. Therefore fresh per-cohort kill/survivor counts, per-mutant reasons and clean-statistics results for all 135 jobs remain UNVERIFIED. The prior 5dc9af8 counts are not reused as current results.

## Focused verification completed

- Partition and audit tests: **42 passed**. These include native pytest child processes for assertions, expectation failures, setup errors, runtime exceptions and collection/import errors, plus refusal of crash-only, missing or tampered evidence.
- Source/security/mutation/tax proof group: **103 passed**.
- Risk counterexamples and injected qty=4 faults: **7 passed**; four newly committed-to-be behavior cases cover strict financial-policy exports, canonical loss audit export and primary fault logging.
- Exact panic deadline checks: **5 passed**. Original deterministic fail-before and 50-run proof remain recorded in MUTATION_PANIC_DEADLINE.md.
- Additional exact-boundary randomized proof with the updated development environment: **50 completed fresh processes / 200 passing cases**, zero failures or retries (seeds 2026102151–2026102200). This complete run supersedes the earlier 40-process partial diagnostic interrupted for dependency approval.
- Authored strict typing: **428 source files pass**. Ruff check/format pass.
- GD-07 authored-source scan passes without policy/allowlist changes. A new test monkeypatch overload was corrected to a literal module/attribute form; no waiver was added.
- Full Bandit scan: zero findings. No nosec or skip was added.
- Production AST assertion sweep: zero remaining Assert nodes outside tests. Production Emin=0 assignments: zero.
- An intermediate normal run passed 6,632 cases / 61 skips / four perf deselections with 100% of 9,510 statements and 3,394 branches. After that run, 55 validated behavior cases were added to four existing selected files; every old function body is unchanged, verified by AST comparison after a caught-and-restored UTF-8 integration mistake. The 55 cases pass together, and strict types, lint, format and GD-07 pass. Final normal and random runs both pass **6,687 cases / 61 existing skips / four original perf-only deselections**, with **100% of 9,510 statements and 3,394 branches**; executor covers **1,871 statements and 784 branches**. Their selected-case multisets and frozen Python source hashes match. Normal elapsed 2,666.28 seconds; random seed 20261021 elapsed 63,178.36 seconds (wall time, not a throughput benchmark). Final full Bandit and all pre-commit hooks pass. Post-commit full-history gitleaks, commit, push, weekly dispatch and full CI remain pending. There is no new commit hash or CI URL yet.

## Added survivor behavior cases

The added 55 cases cover exact fundamental-number/SEC/report errors, the 30,000-fact ingress boundary, exact metric notes and failure reasons, callback refusal/audit reasons, scoped click context, configured fundamental exemptions, risk-fault logger namespaces, exact exit/reconciliation/hybrid refusals, masked trade quantities, exact take-profit cents, paper stream credential/keepalive wiring, valid stream events and unknown-event integrity evidence. The complete case/function evidence is in `build/pass7/added-behavior-functions.json` and `integrated-behavior-results.log`. Combined with the earlier 25 new cases, this pass adds **80 cases and removes zero**, proven against the 5dc9af8 collection; the same four perf-only cases are deselected. No production change was needed for these cases. Native kill claims await the fresh run; local passing behavior tests are not native kill evidence.

## Required CRO and protection checks

Emin=0 originates in `backend/tests/test_risk_cro.py` (the enabled subnormal-context regression and parameterized context tests), not production. The injected qty=4 arithmetic-fault tests pass and return zero with the fault reason. The existing 7,296-case matrix explicitly checks monotonic eligibility and the exhaustive maximum; it passed again in both completed full suites with zero disagreements or oversizing.

The six final-CRO blocker cases and the no-await/IO ordering test remain enabled in `backend/tests/test_auto_admission.py`. Each blocker asserts zero orders; the clear case asserts exactly one. They pass in both completed full suites. The final synchronous CRO call in `enter()` is followed only by pure verdict checking on success; the worker then calls physical submit without await between them. No production recheck code was changed in this pass.

MUTATION_PASS6.md explicitly documents the journaled cancel-then-submit protection gap, the durable entry block throughout it, and restoration/HALT behavior. The panic root-cause one-sentence explanation is present in MUTATION_PANIC_DEADLINE.md.

## Approved diff and the formerly renumbered tail lines

All eleven NEW and the one GONE fingerprint, source lines, operators and exact approved hunks are individually listed in MUTATION_FINGERPRINT_MAP.md and the fingerprint-details evidence. Finalizer line 1952 and repair lines 2576–2578 are **unchanged context** with MATCHED fingerprints; they are not NEW/GONE identities. The extended exact hunks containing those lines and the earlier approved edits are saved as `build/pass7/approved-source-context.diff`. No production change was made at those tail lines.

## Timing plan and missing historical GONE status

`build/pass7/child-timing-plan.csv` lists every child with its mutant count, estimate and explicit PENDING actual time. Of 135 estimates, 127 use their own parent's observed setup and per-mutant timing, and eight use the historical cohort median because their parent never reached mutant execution. These are planning estimates, never reused correctness results. The 29 prior timeouts receive 101 children; the other 34 source owners receive one each. The original parent snapshot is byte-identical to the archived 5dc9af8 manifest (SHA256 `c639171f045d0057b856177a7e9d75907f290335b5a11841f60f3bc5797c2139`); CI also compares these exact files before child ownership proof, so the proof does not trust a redefined baseline. The expanded workflow has 138 jobs (135 children plus verify, aggregate, PostgreSQL); the aggregate uses `needs: mutations` and `always()`, with fail-fast false and an unchanged 120-minute child limit.

The GONE fingerprint is `sha256:1cd19ef8c3123adaf2a94f71aafcc73b2bd2282a0ff23df34098cd17db8d3021`, formerly `_journaled_stop_repair__mutmut_135`. It is not in the 24 proposals. Its old killed/survived status is UNVERIFIED: [old executor-b-2 job](https://github.com/vincentgethub/Project-V/actions/runs/39533721705/job/119005363863) timed out after 121 processed mutants and did not upload an export (the log explicitly says no artifact file existed). Aggregate counters cannot establish this individual mutant's result.

Production grep hits are only docstrings: `backend/core/config.py:832` and `backend/evaluation/costs.py:233`. AST verification finds zero executable assertions and zero production assignments setting Emin=0.

## Source parent unions

| Original parent | Cohort | Children | Current assigned |
|---|---|---:|---:|
| executor-a-1 | executor-a | 2 | 370 |
| executor-a-2 | executor-a | 3 | 432 |
| executor-a-3 | executor-a | 2 | 255 |
| executor-a-4 | executor-a | 3 | 251 |
| executor-a-5 | executor-a | 6 | 598 |
| executor-a-6 | executor-a | 2 | 387 |
| executor-a-7 | executor-a | 4 | 251 |
| executor-a-8 | executor-a | 1 | 383 |
| executor-b-1 | executor-b | 4 | 257 |
| executor-b-2 | executor-b | 21 | 1278 |
| executor-b-3 | executor-b | 4 | 462 |
| executor-b-4 | executor-b | 1 | 565 |
| executor-b-5 | executor-b | 2 | 262 |
| executor-b-6 | executor-b | 4 | 253 |
| executor-b-7 | executor-b | 3 | 385 |
| executor-b-8 | executor-b | 1 | 258 |
| executor-b-9 | executor-b | 4 | 543 |
| risk-controls-1 | risk-controls | 1 | 85 |
| risk-controls-2 | risk-controls | 1 | 85 |
| risk-controls-3 | risk-controls | 1 | 107 |
| risk-controls-4 | risk-controls | 1 | 107 |
| risk-controls-5 | risk-controls | 1 | 107 |
| risk-controls-6 | risk-controls | 1 | 117 |
| risk-controls-7 | risk-controls | 1 | 85 |
| risk-controls-8 | risk-controls | 1 | 107 |
| risk-controls-9 | risk-controls | 1 | 107 |
| risk-controls-10 | risk-controls | 1 | 107 |
| risk-controls-11 | risk-controls | 1 | 107 |
| risk-controls-12 | risk-controls | 1 | 85 |
| risk-controls-13 | risk-controls | 2 | 107 |
| risk-controls-14 | risk-controls | 1 | 85 |
| risk-controls-15 | risk-controls | 1 | 107 |
| risk-controls-16 | risk-controls | 1 | 109 |
| risk-controls-17 | risk-controls | 1 | 107 |
| risk-controls-18 | risk-controls | 1 | 85 |
| risk-controls-19 | risk-controls | 1 | 107 |
| risk-controls-20 | risk-controls | 1 | 85 |
| risk-controls-21 | risk-controls | 1 | 85 |
| risk-controls-22 | risk-controls | 1 | 85 |
| risk-controls-23 | risk-controls | 1 | 86 |
| risk-controls-24 | risk-controls | 1 | 107 |
| risk-controls-25 | risk-controls | 1 | 85 |
| risk-controls-26 | risk-controls | 1 | 85 |
| risk-controls-27 | risk-controls | 1 | 85 |
| risk-sizing-1 | risk-sizing | 1 | 363 |
| risk-sizing-2 | risk-sizing | 3 | 222 |
| risk-sizing-3 | risk-sizing | 2 | 232 |
| risk-sizing-4 | risk-sizing | 4 | 203 |
| risk-sizing-5 | risk-sizing | 2 | 331 |
| risk-sizing-6 | risk-sizing | 3 | 354 |
| risk-sizing-7 | risk-sizing | 3 | 209 |
| fundamentals-callbacks-1 | fundamentals-callbacks | 2 | 184 |
| fundamentals-callbacks-2 | fundamentals-callbacks | 2 | 184 |
| fundamentals-callbacks-3 | fundamentals-callbacks | 1 | 185 |
| fundamentals-callbacks-4 | fundamentals-callbacks | 2 | 184 |
| fundamentals-callbacks-5 | fundamentals-callbacks | 2 | 186 |
| fundamentals-callbacks-6 | fundamentals-callbacks | 1 | 183 |
| fundamentals-callbacks-7 | fundamentals-callbacks | 3 | 182 |
| fundamentals-callbacks-8 | fundamentals-callbacks | 1 | 182 |
| fundamentals-callbacks-9 | fundamentals-callbacks | 3 | 185 |
| fundamentals-callbacks-10 | fundamentals-callbacks | 2 | 184 |
| fundamentals-callbacks-11 | fundamentals-callbacks | 2 | 184 |
| tax | tax | 1 | 1724 |

AUTO_LIVE stays locked; MANUAL_CSV stays disabled; paper-only test fakes; no money movement, secrets output, lifecycle expansion, new pragma/exclusion/nosec/skip/xfail, retries or sleeps. No force push or hook bypass.

Final staged scanning identified the public baseline SHA as a secret-detector false positive in two newly added provenance fields. The baseline is now expressed as its public GitHub commit URL, from which the same exact full SHA is extracted and checked. No detector rule, exclusion or allowance changed. This metadata-only representation change leaves the map and split bytes identical; all 42 partition/audit tests and regeneration checks pass again. The full-suite source freeze precedes this two-line checker representation update; production and test sources remain identical to the completed suites.
