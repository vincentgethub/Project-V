# Mutation Pass 4: approved partition and native gate

Base: `d6ed66bc9ba9bec99722642f7caeb26b02672384`. Delivery commit and final
CI links/counts are in the handoff `build/pass4/FINAL_REPORT.md` after the one
normal push finishes. CI results are UNVERIFIED until that run completes.

## Approved reversions

Both `.github/workflows/ci.yml` copies are byte-identical. Their native command
moves from the former inline block into `scripts/run_mutation_shard.py`:

```diff
-subprocess.run([sys.executable, "-m", "scripts.profile_mutations", *manifest["patterns"]], check=True)
+subprocess.run([sys.executable, "-m", "mutmut", "run", *manifest["patterns"]], check=False)
```

The native exit code is required to be zero. Exporting its results on failure
preserves honest evidence; it does not turn an execution error into a pass.
`scripts/profile_mutations.py` remains manual diagnostics only, with no workflow
references. Native workers, per-mutant limits and test assertions are unchanged.

```diff
-@pytest.fixture(scope="session")
-def pristine_research_indicators(...):
-    seeds = {}
-    try:
-        yield seeds
-    finally:
-        seeds.clear()
```

The complete cache removal (including the harness key, seed read/write and
imports) restores both fixture files byte-for-byte to `2bd8ea28` in Git.
The calendar and pristine-schema fixtures from `3e934857` remain in memory
per run. No test assertion was removed. The planted schema test remains.

## Exact approved partition

`config/mutation-shards.json` copies each proposed bin's exact ordered ID list
without balancing it again. Parent job counts are executor-a 8, executor-b 9,
risk-controls 27, risk-sizing 7, fundamentals/callbacks 11, tax 1: **63 jobs**.
The ID lists were directly compared with the saved proposal before committing.
All jobs retain Linux, a 120-minute timeout, fail-fast false, and the 100% gate.

The preflight and final aggregate regenerate all 18 configured source files
with pinned mutmut 3.8.0 and compare sets, not just counts. Every one of the
**13,381 IDs** must have exactly one owner, belong to that job's source files,
and match the fresh inventory. Inventory SHA256:
`08c86e0fdfe567a5eb9577766fd7d2c976db5cc3f7445dec4e2b2c06f92a9a37`.
The aggregate binds each report to the commit, assignment hash and inventory
hash; all 63 exact report names and all owned result IDs must be present.
Missing reports, job cancellation/timeout, native/export failure, no-tests,
unprocessed, malformed or unlisted surviving results fail. Only the owner's
six individual surviving equivalents are accepted; none can be no-test or
timeout. Native status counts are never rewritten as killed.

Selector additions: risk-controls adds `test_risk_boundary.py`; risk-sizing
adds `test_v_risk.py`, `test_v_risk_boundaries.py`, `test_portfolio_marks.py`,
`test_risk_boundary.py`, `test_v_connections.py`. All paths retain the
`backend/tests/` prefix. The original 17 files stay selected in every job.
This adds five unique files across six family/file selections, reaching the
ten risk functions previously missing from mutation selection (650 IDs).
Tax, fundamentals and executor selection gets no additional test files.

## Tax evidence and individual approvals

Only the six individually approved IDs appear in
`config/tax-equivalent-mutants.json`; the checker independently pins that exact
set and rejects expansion, duplication, deletion or an unapproved owner.
The remaining 27 IDs are separately bound to authentic generated mutations
in `TAX_EQUIVALENCE_PROOFS.md` and its executable proof-obligation tests.
They remain unlisted and continue to fail CI if they survive. No tax production
source was changed and no new production bug is claimed.

The 23 added public behavior cases check Decimal types and zero/exponent
representation, unwashed disposal adjustments, all rate-availability cases,
Unicode export bytes and immutable account hashes. A pristine baseline and
each of the 27 authentic mutant bodies pass these cases locally; they are
not falsely reported killed. The 27 syntax/premise proof cases are outside
mutation selection so they cannot manufacture kills. There are also 25 new
partition/gate regression cases. Total new offline cases: **75**.

## Executor coverage: exact unchanged inclusion lines

There is no function-specific omit/exclusion rule for these 13 functions.
The required coverage gate names source modules explicitly and omits
`backend.execution`, so it does not require executor coverage.

`pyproject.toml:67-69`:

```toml
[tool.coverage.run]
branch = true
source = ["backend.core.system_state", "backend.risk", "backend.domain.compliance_models"]
```

Both workflow copies, line 68 (the CLI source list overrides the TOML list):

```yaml
        run: python -m pytest -q -m 'not perf' --cov=backend.core.system_state --cov=backend.risk --cov=backend.domain.compliance_models --cov=backend.agents.fundamentals --cov=backend.notifications --cov=backend.tax --cov=backend.evaluation --cov-branch --cov-fail-under=100 --cov-report=term-missing
```

There is no `.coveragerc`. Ruff/Bandit excludes are not coverage rules.
The 13 function names and their baseline 795 no-test IDs remain individually
listed in `NON_TAX_NO_TEST_FUNCTIONS.md`. No executor tests or configuration
were changed. No gate, threshold, worker limit or timeout was weakened.

## Verification

Normal and random offline suites: 5,538 passed, 61 skipped, 4 performance cases deselected each; zero failures. Required coverage remains 100% (7,625 statements, 2,606 branches). Random seed: `20261014`.

Whole authored-source typing: 425 files. Ruff lint/format, complete source
guard and production/scripts Bandit pass. Changed authored-file secret scan
passes without an added detector allowance. Full-history gitleaks before the
delivery commit: 46 commits, no leaks. A second full-history scan including
the delivery commit is required before the one normal push and recorded in
the final handoff. Retained schema proof: clean/planted/restored **0/1/0**.
The runner's seven failure/restoration scenarios pass; aggregate negative
cases reject every unlisted/missing/stale/no-test/timeout condition.


Native Windows mutmut cannot use its required fork runner. Supported Linux
reproduction: `VWS_MUTATION_SHARD=tax RUNNER_TEMP=/tmp python -m
scripts.mutation_inventory`, then the same environment with `python -m
scripts.run_mutation_shard`; select any of the 63 names from the manifest.
Final aggregation uses the same commit's downloaded 63 reports with
`GITHUB_SHA=<commit> MUTATIONS_RESULT=success python -m scripts.aggregate_mutations`.
Performance and real provider evidence retain their existing UNVERIFIED status.
AUTO_LIVE remains locked; MANUAL_CSV remains disabled; no keys/setup were touched.
