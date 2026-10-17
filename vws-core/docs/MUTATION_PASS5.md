# Mutation Pass 5 - safety behavior tests

Base: e09684a. Delivery evidence, final commit and the single normal-push CI
are recorded after completion in `build/pass5/FINAL_REPORT.md`.

## Baseline and fixed constraints

[Every affected function in all 63 jobs](MUTATION_SURVIVORS_BY_FUNCTION.md)
records 3,761 survivors (including six approved equivalents), 795 no-test
mutants and six per-mutant timeouts. All 13,381 IDs were processed in the
completed baseline CI 38951494223. The per-job 100% gate, 120-minute limit,
exact split, selectors and six-entry equivalent list remain byte-for-byte
unchanged. No production source or existing assertion changed.

## Added behavior tests

180 cases are added in six already-selected files. Paper fakes exercise all
13 previously unmapped executor functions: transport binding/factory, live
raise-readiness refusal, latest absence evidence, held quotes/observations,
stop-movement audit, split-profit fills, paper cancellation proof/inspection,
repair, close and stream start. No real credentials or network calls are used.
AUTO_LIVE stays locked; the tests never unlock it or contact a live endpoint.

Assertions cover exact broker request dictionaries and cent/integer fields;
exact error types/messages; paper account and prerequisite faults; finite
stream retries and their audit payloads; one DELETE followed by fresh GETs;
ambiguous cancellation without replacement; real sibling fills before a
trail; failed/ambiguous repairs without a blind retry; and exact 30-second
stop-window boundaries. CRO/compliance examples assert complete auditable
rule payloads, loss-block/veto integrity, settled-cash faults and inclusive
earnings-session boundaries. Original assertions are retained. The legacy retry fake and sizing examples also enforce finite work budgets, so mutation test ordering cannot reintroduce those hangs.

All six baseline timeouts fail focused authentic-body replay, with clean
controls passing. Stream fake transport has a finite three-connection budget;
advisory sizing has a finite protective-work budget. These are observable
behavior assertions, not changed mutmut or pytest timeout settings. Native
per-ID results from CI remain authoritative for the final outcome counts.

## Required executor coverage

There were no individual exclusion directives for the 13 functions: the
required source lists omitted execution. The inclusion below removes that
omission, retaining the 100% branch threshold. Both workflow copies are
byte-identical. No other workflow text changes.

The first executor-only diagnostic was 81% (269 tests passed): it exposes both
real remaining gaps and unreachable defensive branches elsewhere in the
module. In particular, the missing-side guard at alpaca_executor.py:213 is
after mandatory model revalidation, which already refuses every no-side
order shape. Four real refusal tests and individual proofs document this;
no validator is bypassed to fabricate coverage. A coverage failure remains
a failure, never a passing offline certificate.

Exact configuration diff:

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index 68ce3b5..997a6fc 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -65,7 +65,7 @@ jobs:
           git diff-tree --root --no-commit-id --name-only -r HEAD > /tmp/vws-changed-files.txt
           python -c "from pathlib import Path; from vws.progress import read_progress, require_progress_update; read_progress(); require_progress_update(tuple(Path('/tmp/vws-changed-files.txt').read_text().splitlines()))"
       - name: Offline tests and complete risk/state/fundamentals/card/tax branch coverage
-        run: python -m pytest -q -m 'not perf' --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov=backend.evaluation --cov-branch --cov-fail-under=100 --cov-report=term-missing
+        run: python -m pytest -q -m 'not perf' --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov=backend.evaluation --cov=backend.execution.alpaca_executor --cov-branch --cov-fail-under=100 --cov-report=term-missing
       - name: Prescribed synthetic performance workloads without coverage overhead
         env:
           VWS_PERF_BUDGET_SECONDS: '420'
diff --git a/vws-core/.github/workflows/ci.yml b/vws-core/.github/workflows/ci.yml
index 68ce3b5..997a6fc 100644
--- a/vws-core/.github/workflows/ci.yml
+++ b/vws-core/.github/workflows/ci.yml
@@ -65,7 +65,7 @@ jobs:
           git diff-tree --root --no-commit-id --name-only -r HEAD > /tmp/vws-changed-files.txt
           python -c "from pathlib import Path; from vws.progress import read_progress, require_progress_update; read_progress(); require_progress_update(tuple(Path('/tmp/vws-changed-files.txt').read_text().splitlines()))"
       - name: Offline tests and complete risk/state/fundamentals/card/tax branch coverage
-        run: python -m pytest -q -m 'not perf' --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov=backend.evaluation --cov-branch --cov-fail-under=100 --cov-report=term-missing
+        run: python -m pytest -q -m 'not perf' --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov=backend.evaluation --cov=backend.execution.alpaca_executor --cov-branch --cov-fail-under=100 --cov-report=term-missing
       - name: Prescribed synthetic performance workloads without coverage overhead
         env:
           VWS_PERF_BUDGET_SECONDS: '420'
diff --git a/vws-core/pyproject.toml b/vws-core/pyproject.toml
index bdb8487..5f00b55 100644
--- a/vws-core/pyproject.toml
+++ b/vws-core/pyproject.toml
@@ -66,7 +66,7 @@ ignore_missing_imports = true
 
 [tool.coverage.run]
 branch = true
-source = ["backend.core.system_state", "backend.risk", "backend.domain.compliance_models"]
+source = ["backend.core.system_state", "backend.risk", "backend.domain.compliance_models", "backend.execution.alpaca_executor"]
 
 [tool.bandit]
 exclude_dirs = ["backend/tests", ".venv", "mutants"]
```

## Individual proposals

[Six individual IDs, exact diffs and reasons](MUTATION_EQUIVALENT_PROPOSALS_PASS5.md)
remain proposals only. Reachable messages are asserted as audit behavior.
Nothing was added to the equivalent list; all six proposals still fail.

## Verification and delivery

The complete normal/random offline suites use the strengthened executor
coverage target and the unchanged 100% threshold; random seed 20261014.
Final counts before commit:

- normal: 5,718 passed, 61 skipped, 4 performance cases deselected; zero test failures/errors. Required coverage **97.3413% / 100%: FAIL**; 182 missing statements and 141 missing branches. Process exit 1; 1306.43s.
- random: 5,718 passed, 61 skipped, 4 performance cases deselected; zero test failures/errors. Required coverage **97.3413% / 100%: FAIL**; 182 missing statements and 141 missing branches. Process exit 1; 2440.05s.
- Random seed 20261014; identical full-suite case multisets verified.

Full-history gitleaks is redacted and repeated after the delivery commit.
Source guard, strict typing (425 files), Ruff and Actionlint pass. The retained
same-interpreter schema proof is clean/planted/restored 0/1/0. Session fixture
caches remain in memory; the original per-test isolation is unchanged.
One normal push is authorized. No gate, split, selection, allowance, assertion
or timeout is weakened in response to a failure. The final run is allowed to
finish fully; no second push, rerun or cancellation is made.
