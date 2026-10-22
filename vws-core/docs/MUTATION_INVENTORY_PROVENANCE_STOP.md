# Inventory provenance: required stop

Historical numeric-ID stop, superseded by the owner's fingerprint decision. The current fingerprint proof and source-job status are in [MUTATION_FINGERPRINT_MAP.md](MUTATION_FINGERPRINT_MAP.md).

The conditional approval fails at its first source-line check: all ten additional native ID names mutate unchanged lines. No inventory, assignment, generator, gate, workflow, production code or test was changed during this provenance check. Nothing was committed, pushed or dispatched.

Pinned mutmut 3.8.0 numbers mutations sequentially per function (`function_trampoline_arrangement` uses `enumerate(mutants)` and `i + 1`). Adding earlier mutations shifts later numbers. The approved fixes increase the total by ten, but the ten name-set additions are renumbered old mutations at the ends of the same functions. Being in an approved function does not mean their own source lines changed.

## Each added ID

| ID | Source file:line | Operator | Approved change association | Identical local mutation previously numbered |
|---|---|---|---|---|
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_169` | `backend/execution/alpaca_executor.py:1952` | `operator_swap_op` | Panic-race fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_163` |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_170` | `backend/execution/alpaca_executor.py:1952` | `operator_string` | Panic-race fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_164` |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_171` | `backend/execution/alpaca_executor.py:1952` | `operator_string` | Panic-race fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_165` |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_172` | `backend/execution/alpaca_executor.py:1952` | `operator_string` | Panic-race fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_166` |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_173` | `backend/execution/alpaca_executor.py:1952` | `operator_arg_removal` | Panic-race fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_167` |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_174` | `backend/execution/alpaca_executor.py:1952` | `operator_string` | Panic-race fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_168` |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_279` | `backend/execution/alpaca_executor.py:2576` | `operator_arg_removal` | Assert-to-raise fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_275` |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_280` | `backend/execution/alpaca_executor.py:2577` | `operator_string` | Assert-to-raise fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_276` |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_281` | `backend/execution/alpaca_executor.py:2577` | `operator_string` | Assert-to-raise fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_277` |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_282` | `backend/execution/alpaca_executor.py:2577` | `operator_string` | Assert-to-raise fix, indirect numbering shift only | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_278` |

The call mutation at line 2576 spans 2576–2578. The other repair mutations affect the unchanged string at line 2577. All six finalizer mutations affect line 1952. None intersects a changed source line. Current changed lines are 1866–1867, 1904–1905, 1919–1920, and 2508–2509. The original assert was at committed line 2502.

## Exact mutation fragments

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_169`

```diff
-"Cancellation confirmation unresolved for legs: " + ", ".join(unresolved)
+"Cancellation confirmation unresolved for legs: " - ", ".join(unresolved)
```

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_170`

```diff
-"Cancellation confirmation unresolved for legs: "
+"XXCancellation confirmation unresolved for legs: XX"
```

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_171`

```diff
-"Cancellation confirmation unresolved for legs: "
+"cancellation confirmation unresolved for legs: "
```

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_172`

```diff
-"Cancellation confirmation unresolved for legs: "
+"CANCELLATION CONFIRMATION UNRESOLVED FOR LEGS: "
```

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_173`

```diff
-", ".join(unresolved)
+", ".join(None)
```

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_174`

```diff
-", "
+"XX, XX"
```

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_279`

```diff
-ReconciliationError(
-    "Journaled protection and old-level restoration could not be confirmed; HALTED"
-)
+ReconciliationError(
+    None
+)
```

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_280`

```diff
-"Journaled protection and old-level restoration could not be confirmed; HALTED"
+"XXJournaled protection and old-level restoration could not be confirmed; HALTEDXX"
```

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_281`

```diff
-"Journaled protection and old-level restoration could not be confirmed; HALTED"
+"journaled protection and old-level restoration could not be confirmed; halted"
```

`backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_282`

```diff
-"Journaled protection and old-level restoration could not be confirmed; HALTED"
+"JOURNALED PROTECTION AND OLD-LEVEL RESTORATION COULD NOT BE CONFIRMED; HALTED"
```

## Identifier strings versus mutation identity

The sorted identifier-name comparison contains ten additions and zero removals. All 15,457 original identifier strings remain byte-identical and present. This is a name-set fact, not proof that those names still identify the same mutations: numbering shifted inside both changed methods. The old-to-new fragment matches above expose that distinction.

The before list comes from the unchanged committed partition. The after list reconstructs the previous complete 18-file generation from its saved +10/−0 result; it is explicitly named `inventory-names-after-prior-generation.txt`. This provenance check does not claim two fresh complete generations. The newly requested double regeneration was not performed after the source-line condition failed.

Saved evidence under `build/pass7`:

- `inventory-provenance.json`: original and mutated CST fragments, exact positions, operator names, old matching IDs and changed-line intersections. Produced using the pinned generator's `create_mutations`, without changing or filtering it.
- `inventory-names-before.txt` and `inventory-names-after-prior-generation.txt`: UTF-8, LF, sorted ID-name lists.
- `inventory-names.diff`: saved name-list diff, ten additions and zero removals.
- `trace_inventory_provenance.py`: read-only tracing script.

Before-list SHA256: `04d2a419e45afe044ceffd7e003bb8faa5b2088003a9e405238312d17e44b926`.

After-list SHA256: `a40f765c721166356c590037b8299b40eb7805deec9f3e9a027956d2bf878f14`.

## Status at the stop

No later steps in the new approval were started: no production-assert sweep or additional fixes, 135-job partition, dispatch, kill classification, survivor tests, full suite, coverage gate, new gitleaks scan, commit or push. The prior panic and explicit-raise corrections, four new cases and one-line weekly-audit changes remain uncommitted exactly as previously reported. Prior evidence remains 50 randomized fresh-process runs / 200 passing focused cases, 48 passing panic-group cases, normal and optimized-Python guard passes, and zero Bandit findings.

Continuing requires a decision that explicitly permits native ID renumbering onto unchanged source lines. No generator change, filtering, ID removal, equivalent allowance or gate change has been made to bypass the condition.
