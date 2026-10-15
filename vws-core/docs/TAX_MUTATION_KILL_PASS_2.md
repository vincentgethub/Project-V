# Tax mutation kill pass 2 - October 15, 2026

The 100% tax gate remains unmet. All unlisted survivors still fail; no equivalent list entry is installed. This report supersedes the diagnostic-only proposals in TAX_MUTATION_KILL_REPORT.md.

Base: `09a713b03a532cbe85663e4ed631c2b915547f88`. The delivery commit and all six normal Linux shard results are recorded in the final handoff. The owner approved only the two inventory-number corrections in both byte-identical workflow copies.

## Changes

- 56 new collected cases in 16 new test functions in the three existing selected tax test files; one additional POSIX timezone case skips on Windows. Existing cases remain collected.
- Exact exception class and text are asserted. Wrapped refusals also assert the retained inner exception class/text, because the public wrapper deliberately uses a generic message.
- All 153 diagnostic-only mutants, the three diagnostic-changing accounting guards, six zero-term netting mutants, the year-9999 refusal, the missing-disposition branch, and four audit-serialization mutants now fail focused tests.
- Audit serialization tests pin accepted 09a713b evidence identities and export addresses alongside hand-calculated totals; valid padded money and a precise supplied rate are retained as inputs.
- A strict Decimal rounding-trap case preserves the exact accounting refusal and retained numeric reason; it kills the previously proposed rebuild precision mutant.
- A hand-computed chained partial wash fixture independently checks old basis, unassigned share capacity, and taxable/IRA/Roth treatment under FIFO and compressed FIFO.
- No tax production source, equivalent allowance, test selector, score gate, threshold, timeout, fixture/cache, key or setup changed. AUTO_LIVE stays locked; MANUAL_CSV stays disabled.

## Local mutation evidence

Unforked, in-memory Windows replays cover all 207 remaining records from pass 1. Each invocation creates/tears down its own pytest session. Mutant IDs are current 09a713b IDs; the source inventory is 1724 tax mutants (433 lots, 574 accounting, 717 reports).

| File | Replayed | Newly killed | Remaining on Windows | No test calls |
| --- | ---: | ---: | ---: | ---: |
| lots.py | 81 | 75 | 6 | 0 |
| accounting.py | 59 | 49 | 10 | 0 |
| reports.py | 67 | 45 | 22 | 0 |
| Total | 207 | 169 | 38 | 0 |

The 38 records consist of 32 individual proposals below, one unresolved convergence-bound mutant, and five POSIX cases. The earlier 1253 native kills and 264 pass-1 replay kills were not rerun in this focused pass; these figures are not a fresh native shard certificate. Native mutmut requires Linux/WSL and refuses this Windows host. No-test counts here describe the replay cohort; current native counts await Linux CI.

All twelve original marked_external_lots message survivors are killed, completing focused coverage of the earlier 38 no-test cohort. No diagnostic/message mutant remains proposed. The unchanged strict checker rejects the focused surviving records. Raw per-ID failures, controls, coverage and suite XML are retained in `build/tax-kill-2/` as uncommitted evidence.

## Unresolved, not proposed equivalent

- `backend.tax.accounting.x_build_tax_book__mutmut_78`: changes the potential fill-dependent iteration allowance from len(fills)+2 to +3. Real wash-chain and interval tests still survive this mutation. An additional deterministic comparison of 128 valid 24-fill histories (grouped symbols, FIFO/compressed FIFO, taxable/IRA ownership, partial fills and fees) returned identical books. This is not a general proof covering all possible partial-share refinements, so the previous equivalence proposal is withdrawn. It remains a gate failure.

## POSIX cases awaiting Linux

- `backend.tax.lots.xǁWashSaleMatcherǁ_adjustment__mutmut_24`: converting a valid year-9999 tacked instant through host local time can overflow in UTC+14; the new test changes/restores TZ with tzset and checks the UTC result.
- `backend.tax.reports.x_save_report__mutmut_51`: permissive umask exposes changed/default root mkdir mode; existing real-filesystem 0700 test retained.
- `backend.tax.reports.x_save_report__mutmut_53`: permissive umask exposes changed/default root mkdir mode; existing real-filesystem 0700 test retained.
- `backend.tax.reports.x_save_report__mutmut_61`: permissive umask exposes changed/default nested mkdir mode; existing real-filesystem 0700 test retained.
- `backend.tax.reports.x_save_report__mutmut_63`: permissive umask exposes changed/default nested mkdir mode; existing real-filesystem 0700 test retained.

Windows skips are UNVERIFIED, never kills or passes. The final handoff records supported normal-CI execution.

## Remaining individual equivalent proposals - no approvals

Each ID is a separate proposal. Proofs concern the validated tax interface and enforced caller invariants; tests alone do not prove equivalence. Every row continues to fail the gate pending individual owner approval.

| Current mutant ID | One-line verifiable reason |
| --- | --- |
| `backend.tax.lots.xǁWashSaleMatcherǁ_available_slices__mutmut_4` | Reachable assigned intervals satisfy start <= end; at end == cursor the gap is zero and max(cursor,end) is unchanged, so no share/output can differ. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_29` | For every validated BUY/SELL, tags (0,1) and (0,2) impose the identical timestamp/side/UUID total order. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_44` | The preceding membership test guarantees the replacement ID exists; the changed dict.get default is never used. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_46` | The preceding membership test guarantees the replacement ID exists; omitting the dict.get default cannot change a matched quantity. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_47` | The preceding membership test guarantees the replacement ID exists; changing its unused default to 1 cannot change a matched quantity. |
| `backend.tax.accounting.x__rebuild__mutmut_107` | zip(strict=None) and zip(strict=False) both disable strict length checking; the same adjacent share boundaries are paired. |
| `backend.tax.accounting.x__rebuild__mutmut_110` | Omitting zip(strict=False) selects the same False default and produces the same adjacent share intervals. |
| `backend.tax.accounting.x__rebuild__mutmut_35` | Distinct sorted share boundaries create only positive-width parts, and exhausted parts are removed before apply; start == end cannot be selected. |
| `backend.tax.accounting.x__rebuild__mutmut_53` | The sole caller supplies matcher allocations that assign every physical replacement share once; each selected part therefore has extra == 0 before its only addition. |
| `backend.tax.accounting.x_build_tax_book__mutmut_104` | All summed disallowances come from scaled integer money (at most 19 digits), with at most 100000 rows (at most 24 digits); precision 80/81 cannot round or change representation. |
| `backend.tax.accounting.x_build_tax_book__mutmut_114` | Removing the Decimal zero start leaves nonempty Decimal sums unchanged; the empty integer zero is normalized by TaxSale money validation. |
| `backend.tax.accounting.x_build_tax_book__mutmut_123` | Removing the Decimal zero start leaves permanent-loss sums unchanged; TaxSale converts the empty integer zero to the same Decimal zero. |
| `backend.tax.accounting.x_build_tax_book__mutmut_134` | Economic gain plus an empty integer zero equals gain plus Decimal zero; nonempty disallowed-loss sums remain Decimal. |
| `backend.tax.accounting.x_build_tax_book__mutmut_32` | For all validated fill sides, replacing SELL tag 1 with 2 preserves the complete timestamp/BUY-before-SELL/UUID order. |
| `backend.tax.reports.x__cell__mutmut_6` | Every Decimal reaching a validated export is finite; f/F formatting differs only for nonfinite spellings, which public money validation rejects before export. |
| `backend.tax.reports.x__csv__mutmut_18` | UTF-8 and utf-8 name the same Python codec; exported bytes are identical. |
| `backend.tax.reports.x_annual__mutmut_119` | A missing LT sum starts at integer zero instead of Decimal zero; later money validation normalizes it, and nonempty Decimal sums are unchanged. |
| `backend.tax.reports.x_annual__mutmut_190` | Empty dividend integer zero is normalized by AnnualTax money validation; nonempty dividend sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_200` | Empty interest integer zero is normalized by AnnualTax money validation; nonempty interest sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_210` | Empty fee integer zero is normalized by AnnualTax money validation; nonempty absolute fee sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_226` | Adding an empty integer-zero dividend sum to Decimal interest gives the same ordinary-income amount. |
| `backend.tax.reports.x_annual__mutmut_242` | An empty qualified-income integer zero is used in the same Decimal arithmetic and final cent quantization. |
| `backend.tax.reports.x_annual__mutmut_340` | Empty wash-disallowed integer zero is normalized by AnnualTax money validation; nonempty wash sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_346` | Empty permanent-loss integer zero is normalized by AnnualTax money validation; nonempty permanent-loss sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_109` | A missing ST sum starts at integer zero instead of Decimal zero; later money validation normalizes it, and nonempty Decimal sums are unchanged. |
| `backend.tax.reports.x_render_report__mutmut_195` | README UTF-8 and utf-8 encoding use the same Python codec and produce identical bytes. |
| `backend.tax.reports.x_render_report__mutmut_91` | AnnualTax includes only built-in int/str/bool/finite Decimal/None cells and has no custom serializers; pinned Pydantic treats mode=None as the same non-JSON Python-value branch. |
| `backend.tax.reports.x_render_report__mutmut_92` | AnnualTax includes only built-in int/str/bool/finite Decimal/None cells and has no custom serializers; pinned Pydantic treats mode=XXpythonXX as the same non-JSON Python-value branch. |
| `backend.tax.reports.x_render_report__mutmut_93` | AnnualTax includes only built-in int/str/bool/finite Decimal/None cells and has no custom serializers; pinned Pydantic treats mode=PYTHON as the same non-JSON Python-value branch. |
| `backend.tax.reports.x_save_report__mutmut_44` | UTF-8 and utf-8 encode account names identically, so the account-bound directory hash is unchanged. |
| `backend.tax.reports.x_save_report__mutmut_74` | For every regular-file byte content, read(n+1) == the n-byte payload iff read(n+2) == it; exact files return the same path and all mismatches retain the same refusal. |
| `backend.tax.reports.x_annual__mutmut_104` | The changed min default is reached only with four unavailable rates; max(80,32) == max(80,31), so all arithmetic and the unavailable estimate are identical. |

## Validation and delivery

| Final run | Passed | Failed/errors | Skipped | Required branch coverage | Elapsed (pytest stdout) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ordered | 5463 | 0 | 61 | 100% | 1298.22s |
| Random, seed 20261014 | 5463 | 0 | 61 | 100% | 1447.09s |

Both use the unchanged `-m "not perf"` selector (four performance cases deselected) and report two inherited warnings. JUnit proves identical multisets of 5524 cases in different execution order, with 56 added and zero removed relative to 09a713b. All 7625 required statements and 2606 branches are covered, with zero missing/partial and the same 20 inherited exclusions. The 61 skips are 57 PostgreSQL, two explicit paper integrations, and two POSIX cases; none is a pass.

Final focused tax selection: 232 passed, two POSIX skips. All Python test-file hashes remain unchanged throughout the final completed suite runs. Their XML, logs, coverage JSON and exact multiset/source proof are in build/tax-kill-2/.

Ruff lint/format, the full authored-source guard, staged/source secrets checks and tax Bandit pass (zero Bandit findings; one inherited unused-nosec warning). Four of five root pre-commit checks pass. The strict typing check cannot start because Windows Application Control blocks mypy's compiled extension `6ec57f84c680d3a3778b__mypyc`; it remains UNVERIFIED locally, with no policy change or hook bypass. Reproduce with `.venv\Scripts\python.exe -m backend.core.check_stage_d` on this host, or `python -m backend.core.check_stage_d` in the pinned supported Linux environment.

Complete-history gitleaks 8.30.1 before commit: 44 commits, zero leaks, non-shallow repository. The final handoff records the post-commit scan. No actual tax source bug was repaired in this pass; tax production code is unchanged from 09a713b.

The retained planted-schema check passes, fails with the in-memory RUNNING-to-HALTED mutant, then passes after restoration in the same interpreter (0 / 1 / 0). No disk template or session cache was introduced.

Two preliminary ordered runs were interrupted: the first when four audit-record cases were added, the second when the app session ended at 35%. Neither is passing evidence. Completed 55-case-addition runs precede the final arithmetic-trap case; they are retained separately. Only completed runs of the final 56-case-addition set are used as final suite evidence.

## Approved normal CI inventory correction

Normal run [38662583897](https://github.com/vincentgethub/Project-V/actions/runs/38662583897) on 09a713b completed: verify/PostgreSQL passed; all six mutation jobs failed before mutation execution because the workflow still asserted 13367 generated mutants and 1710 tax mutants after the rate fix added 14. None of those six failures was a 120-minute timeout.

The independently generated inventory is 13381 overall / 1724 tax. The owner explicitly approved these two numbers only; both workflow copies are byte-identical and contain only these numeric replacements. The earlier full-disjoint-assignment preflight passed (18 files, executor union 5159, no overlap). Selectors, functions, files, other shard counts, 100% checker and 120-minute limit are unchanged. A fresh generator invocation is now unavailable because Windows Application Control also blocks libcst native; no host protection was changed.


Exact diff below applies identically to both `.github/workflows/ci.yml` and `vws-core/.github/workflows/ci.yml` (paths relative to the Git root):

```diff
-            count: 1710
+            count: 1724
-          require(len(all_mutants) == 13367, "generated total differs from 13367")
+          require(len(all_mutants) == 13381, "generated total differs from 13381")
-          print("Verified all 18 files, all functions, 13367 unique mutants; executor overlap=0, union=5159")
+          print("Verified all 18 files, all functions, 13381 unique mutants; executor overlap=0, union=5159")
```

All 14 added IDs belong to `backend.tax.reports.annual`, the sole function changed by the 09a713b rate-ceiling fix:

- `backend.tax.reports.x_annual__mutmut_91`
- `backend.tax.reports.x_annual__mutmut_92`
- `backend.tax.reports.x_annual__mutmut_93`
- `backend.tax.reports.x_annual__mutmut_94`
- `backend.tax.reports.x_annual__mutmut_95`
- `backend.tax.reports.x_annual__mutmut_96`
- `backend.tax.reports.x_annual__mutmut_97`
- `backend.tax.reports.x_annual__mutmut_98`
- `backend.tax.reports.x_annual__mutmut_99`
- `backend.tax.reports.x_annual__mutmut_100`
- `backend.tax.reports.x_annual__mutmut_101`
- `backend.tax.reports.x_annual__mutmut_102`
- `backend.tax.reports.x_annual__mutmut_103`
- `backend.tax.reports.x_annual__mutmut_104`

A fresh standard-library AST comparison of the saved generated bodies accounts for all 703 old report mutants one-to-one after removing the inserted precision statement. Each of the 14 additional bodies differs only within that inserted statement. Report inventory rises from 703 to 717; all other 17 configured source files are unchanged from 3e934857. No additional mutant originates elsewhere. This verifies origin, not a fresh native mutation score.

## Session-cache applicability to the five other shards

All six normal jobs copy backend/tests/conftest.py and invoke the same pytest selections. pristine_calendars is session-autouse for every backend test; pristine_schema is used by the shared engine fixture. The default unmodified XNYS constructor can reuse only immutable schedule tuples inside one invocation; direct/custom/invalid calendar paths still validate normally. Each engine receives a fresh in-memory SQLite backup; session teardown clears/disposes both caches. They therefore apply to non-tax shard tests using those fixtures, with no disk cache or cross-mutant reuse.

This establishes applicability, not a measured non-tax speed-up. Tax diagnostics measured setup savings; equivalent before/after non-tax timings are unavailable. Any timeout and last observed mutant progress on the delivered normal run will be recorded in the final handoff; a timeout remains a failure. No other shard was started locally or dispatched separately.
