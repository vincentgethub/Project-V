# Panic deadline regression diagnosis

The panic finalizer could start another leg read after its deadline expired, occupying both worker slots and blocking reconciliation only when scheduling left the timed-out reads unfinished.

The eight unmutated statistics failures from [CI 39533721705](https://github.com/vincentgethub/Project-V/actions/runs/39533721705) stop at the exact-message assertion in `backend/tests/test_auto_safety.py:3490`.

| Job | Parameter | Job ID |
|---|---|---|
| risk-controls-8 | read | 119005363787 |
| executor-a-8 | pending | 119005363723 |
| risk-controls-12 | pending | 119005363738 |
| fundamentals-callbacks-3 | read | 119005363696 |
| risk-controls-16 | pending | 119005363846 |
| executor-b-4 | pending | 119005363834 |
| risk-controls-18 | pending | 119005363913 |
| risk-sizing-1 | read | 119005364430 |

## Reproduction and state

Test: `test_SEC_73_pending_cancel_timeout_processes_other_leg_and_resumes_after_restart[pending-harness0]` or `[read-harness0]`.

CI used normal collection order, without a random seed. Pinned mutmut explicitly disables the randomly and random-order plugins. The pending variant precedes the read variant. CI logs do not retain the complete per-test order or worker-state trace; no further state is inferred from them.

A controlled scheduling reproduction delays completion of order reads and advances the event-loop deadline during the first polling read after B's cancellation. It uses events, without added sleeps or retries. The new cases call the existing regression, retaining every exact-message, ledger, protection, HALT, restart and idempotence assertion.

Expected: `Panic cancellation incomplete; unresolved orders: f3161902-f8ea-4242-8e6a-6300f7f74aa6`.

Actual: `Panic cancellation incomplete; unresolved orders: f3161902-f8ea-4242-8e6a-6300f7f74aa6, account-reconciliation`.

| State at deterministic failure | Value |
|---|---|
| Shared ledger | PROPOSED, APPROVED, SUBMITTED, CANCEL_REQUESTED |
| A | qty 4, filled 0, pending_cancel; both exits held |
| B | qty 5, filled 0, canceled; both exits canceled |
| Ledger / broker / active protected shares | 0 / 0 / 0 |
| Durable state | HALTED |
| Panic result | Failed shared order plus account-reconciliation; no finalized canceled or filled orders |
| Underlying error | ProviderError: Order worker is closed or has two unresolved physical attempts |

The finalizer checked the deadline only at the start of its polling loop. When it expired inside the per-leg scan, another leg read was admitted inside an already-expired timeout. Both unresolved reads occupied the worker slots, so the subsequent position request failed admission. This is a production scheduling defect reproduced without preceding tests, shared ledgers, clock leakage, or changed Decimal context. The CI symptom matches; the worker-level diagnosis comes from controlled local tracing rather than unavailable CI tracing.

## Correction boundary and proof

Only `_finalize_entry_cancellation` changes: before each initial observation, cancel scan and confirmation scan, check the same existing deadline and stop starting work when it has expired. No retries, sleeps, timeout/config increases, lifecycle changes, worker changes, skips or weakened assertions are introduced. An already-admitted read remains tracked, preserving ambiguity isolation while leaving the other slot available for reconciliation.

Both new deterministic cases fail against the exact HEAD finalizer loaded in memory and pass with the correction. A third case starts with an expired deadline: no broker work starts, the state stays CANCEL_REQUESTED, both zero-fill BUY orders and their held exits stay untouched, HALT stays durable, and the ledger chain remains valid.

All 50 fresh-process randomized runs pass: 200 passed cases, zero failures and zero retries. Each run executes the two original and two controlled-scheduling cases. Seeds: 2026102101 through 2026102150; 20 distinct four-case permutations were exercised. Every seed's order and log are saved under `build/pass7`; the runner stops on its first failure and never retries.

Evidence under `build/pass7`: `panic-failure.json`, `panic-deterministic-before.log`, `panic-deterministic-after.log`, `panic-new-tests-before.log`, `panic-focused.log`, `panic-expired-before-start.log`, and `panic-50-runs.json`.

The full SEC_73 group passes: 48 passed, 260 unrelated cases deselected by the focused command, 158.40 seconds. This is a focused diagnosis run, not the final whole-suite gate or a change to configured test selection. Ruff and strict typing pass for the two changed Python files.

## Production assert and weekly audit

The production assert formerly at `alpaca_executor.py:2502` is replaced in place by an explicit `DataIntegrityError("Standalone stop repair requires a recorded approval")` check. The missing-approval test fails against the committed method and passes normally and under `python -O`. It asserts the exact exception type and text, no extra submitted order, the outstanding repair journal and its entry block, and a valid ledger chain. No Bandit suppression or configuration change is added. The full CI Bandit command reports zero findings.

Both weekly-audit workflow copies change one line only:

```diff
-        working-directory: ${{ env.VWS_PROJECT_DIR || '.' }}
+        working-directory: vws-core
```

They remain byte-identical. No dispatch has occurred: the correction is still local and the authorized single commit/push follows the remaining checks. The intended artifact is `weekly-dependency-sboms`; execution of pip-audit and SBOM generation is not yet verified.

## Earlier numeric-inventory stop (superseded)

The owner subsequently approved fingerprint matching. The current proof is in [MUTATION_FINGERPRINT_MAP.md](MUTATION_FINGERPRINT_MAP.md): 15,456 MATCHED, 11 NEW and 1 GONE; every NEW/GONE mutation is on an approved changed line. The inventory is now 15,467, with original source-job ownership preserved. The 135-job split awaits clarification about child jobs; the paragraphs below retain the earlier stop record.

Pinned mutmut 3.8.0 regenerated all 18 configured source files once, without writing generated inventory or changing assignments. The current total is **15,467**, versus the approved **15,457**. Exactly ten IDs were added and none retired; all additions are in the two approved production methods. Every other generated ID remains present.

The unchanged CI `prove_partition` check rejects this fresh ID set: `OPS-06: unassigned or nonexistent generated ID`. The existing partition still has 63 jobs and 15,457 exactly-once assignments; ten fresh IDs are unassigned. No PASS is claimed for the current source, and no 135-job repartition has been applied.

Added IDs (each listed individually):

- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_169`
- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_170`
- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_171`
- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_172`
- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_173`
- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_174`
- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_279`
- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_280`
- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_281`
- `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_282`

Retired IDs: none. Per-job assignment counts: unchanged for all 63 jobs. Updating the inventory to 15,467 and assigning these ten IDs needs owner approval because the latest split authorization explicitly fixes the ID set at 15,457.

Four new test cases were added and none removed. Focused checks and Bandit are described above. The whole normal/random suites, new coverage gate, gitleaks scan, kill-reliability classification and survivor work have not been run in this stopped pass. The weekly workflow correction is prepared but has not been dispatched, so no new audit artifact or run link is claimed. No commit, push or new CI run occurred. AUTO_LIVE, MANUAL_CSV, the four ledger transitions, GD-07, existing mutation commands, selectors, timeouts, gates and equivalent allowances remain unchanged.

## Updated-environment exact-boundary proof

On October 21, the final exact-equality deadline tests passed 50 fresh-process randomized runs (seeds 2026102151–2026102200): 200 passing cases, zero failures and zero retries. Both test orders and both read/pending variants were exercised. Evidence: `build/pass7/exact-panic-50-updated-deps.log` and `build/pass7/exact-reliability/panic-50-runs.json`. This supersedes the incomplete 40-process extra diagnostic stopped for dependency approval; the earlier original 50-run proof remains separately recorded. No scheduling sleep or retry was added.
