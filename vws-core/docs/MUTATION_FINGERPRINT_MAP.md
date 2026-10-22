# Fingerprint inventory and source ownership

The owner has since approved child jobs. The completed 135-child proof, canonical LF map hash and current dependency-audit stop are recorded in [MUTATION_PASS7.md](MUTATION_PASS7.md); the intermediate ownership discussion and CSV serialization hashes below are historical.

Baseline: `5dc9af896d3fec6bc8e1b38eb2159641a740b27a`. This fingerprint analysis supersedes the earlier stop based on numeric ID names. No historical mutation test results are reused.

## Fingerprint definition

The fingerprint is SHA256 of the UTF-8 canonical JSON array `[file, function, normalized_original_line, operator, mutated_text]`, serialized with `ensure_ascii=False` and separators `,` and `:`. File paths are repository-relative POSIX paths; methods are class-qualified. Only the original physical source line is whitespace-normalized with `" ".join(text.split())`. Mutated text is the exact rendered mutated CST node, preserving its text and whitespace. Line numbers and mutmut numbers are absent from the payload. Every digest can be independently reconstructed from `build/pass7/inventory-fingerprint-components.csv`.

The pinned native `create_mutations` generator supplies mutation nodes, operator outputs and occurrence order. Temporary diagnostic wrappers tag operators without adding, removing or filtering their outputs. Per-function enumeration follows the pinned native trampoline generator. Old names exactly equal all 15,457 names in the committed partition; current names exactly equal the previous full native 18-file generation. This work generates mutation metadata and identities, not kill results.

## Bucket proof

| Bucket | Count |
|---|---:|
| MATCHED | 15,456 |
| NEW | 11 |
| GONE | 1 |

**15,456 + 11 = 15,467; 15,456 + 1 = 15,457.** Each original ID occurs exactly once in the old side of the CSV and every current ID exactly once in its new side. All NEW and GONE mutations are on approved changed lines; unchanged-line violations: zero.

Files under `build/pass7`:

- `inventory-fingerprint-map.csv`: requested five columns, with a blank old/new side for NEW/GONE.
- `inventory-fingerprint-components.csv`: all five identity components for every distinct digest.
- `inventory-fingerprint-details.json`: bucket details, exact source fragments, changed-line intersections, diff hunks and duplicate groups.
- `inventory-fingerprint-duplicates.csv`: every occurrence pair in all 379 duplicate groups, in native appearance order. No duplicate is silently discarded.
- `fingerprint-repeat-proof.json`: byte-identical generation proof.

Two complete old/current metadata generations and maps are byte-identical. A preliminary diagnostic normalized mutated text too; its earlier reported hash is superseded by the final encoding above, which normalizes only the original line. Final comparisons:

| Artifact | SHA256 |
|---|---|
| `inventory-fingerprint-map.csv` | `8ca299b27c31e6253b92e5081db33c7f6e5a0bc27a392abc7b3092f2d5f3ae49` |
| `inventory-fingerprint-details.json` | `d80ec5f59c3e42720a0e13b54ea9194ac8a6a7ef2cf5898dba09e0dda5938d1e` |
| `inventory-fingerprint-components.csv` | `7ab87341428e2b53aaa2ec2e0800f094a809e330f732893bfbfc90b02917b700` |
| `fingerprint-inventory-old.txt` | `dbfac7037b0f4edf8d416b114cd0a465d8b681620b3ea0139596f61282762ed5` |
| `fingerprint-inventory-new.txt` | `06c72e5a85ffd05be5827cce74c84b0406007e29e4c2687bbc5d9326eee331ed` |

## Every NEW and GONE mutation

| Bucket | ID | Fingerprint | File:line | Function | Operator |
|---|---|---|---|---|---|
| GONE | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_135` | `sha256:1cd19ef8c3123adaf2a94f71aafcc73b2bd2282a0ff23df34098cd17db8d3021` | `backend/execution/alpaca_executor.py:2502` | `AlpacaExecutor._journaled_stop_repair` | `operator_keywords` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_24` | `sha256:2e38277614d82728e8a3befbdb9e72a399ad86d47e462830aa794c68f0e4dd4c` | `backend/execution/alpaca_executor.py:1866` | `AlpacaExecutor._finalize_entry_cancellation` | `operator_swap_op` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_25` | `sha256:c882d1bd4684930195fbb9b790ab6d76362ff633a723bcde76ea78cc3a95046f` | `backend/execution/alpaca_executor.py:1867` | `AlpacaExecutor._finalize_entry_cancellation` | `operator_keywords` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_79` | `sha256:2e38277614d82728e8a3befbdb9e72a399ad86d47e462830aa794c68f0e4dd4c` | `backend/execution/alpaca_executor.py:1904` | `AlpacaExecutor._finalize_entry_cancellation` | `operator_swap_op` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_80` | `sha256:c882d1bd4684930195fbb9b790ab6d76362ff633a723bcde76ea78cc3a95046f` | `backend/execution/alpaca_executor.py:1905` | `AlpacaExecutor._finalize_entry_cancellation` | `operator_keywords` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_105` | `sha256:2e38277614d82728e8a3befbdb9e72a399ad86d47e462830aa794c68f0e4dd4c` | `backend/execution/alpaca_executor.py:1919` | `AlpacaExecutor._finalize_entry_cancellation` | `operator_swap_op` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_106` | `sha256:c882d1bd4684930195fbb9b790ab6d76362ff633a723bcde76ea78cc3a95046f` | `backend/execution/alpaca_executor.py:1920` | `AlpacaExecutor._finalize_entry_cancellation` | `operator_keywords` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_135` | `sha256:0f1f9e5215cdc855e4d957aa02cb138ccd6fa0d85246c56ad75ae2a286707bd3` | `backend/execution/alpaca_executor.py:2508` | `AlpacaExecutor._journaled_stop_repair` | `operator_keywords` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_136` | `sha256:6adf940d45e2fab14d0c630d10ad24e2618db181ee169938298f510ff17f956f` | `backend/execution/alpaca_executor.py:2509` | `AlpacaExecutor._journaled_stop_repair` | `operator_arg_removal` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_137` | `sha256:ba7968c1cf6ceee9277ad9b3c83a9e2035c92f4067fe5d6619d33d96a2f00d88` | `backend/execution/alpaca_executor.py:2509` | `AlpacaExecutor._journaled_stop_repair` | `operator_string` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_138` | `sha256:a63bfbb3f5ce0502396ff622ffa992686d88d8755ad487dcc547f068283c0ae4` | `backend/execution/alpaca_executor.py:2509` | `AlpacaExecutor._journaled_stop_repair` | `operator_string` |
| NEW | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_139` | `sha256:9635915ad2d26462c5dcbfcc8015c5a94ba14f48869335c44e2395df23f94911` | `backend/execution/alpaca_executor.py:2509` | `AlpacaExecutor._journaled_stop_repair` | `operator_string` |

### GONE backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_135

Fingerprint: `sha256:1cd19ef8c3123adaf2a94f71aafcc73b2bd2282a0ff23df34098cd17db8d3021`.

Approved change: production assert to explicit integrity error.

Original normalized line: `assert approval is not None`.

Mutated text:

```text
" is "
```

Approved diff hunk:

```diff
@@ -2499,7 +2505,8 @@
             selected = new_stop
             restoring_selected = False
             if standalone_repair:
-                assert approval is not None
+                if approval is None:
+                    raise DataIntegrityError("Standalone stop repair requires a recorded approval")
                 level = approval.old_stop
                 try:
                     inputs = await self._fresh_exit_inputs(entry)
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_24

Fingerprint: `sha256:2e38277614d82728e8a3befbdb9e72a399ad86d47e462830aa794c68f0e4dd4c`.

Approved change: panic deadline race.

Original normalized line: `if loop.time() >= deadline:`.

Mutated text:

```python
 > deadline
```

Approved diff hunk:

```diff
@@ -1863,6 +1863,8 @@
         absent = {row.id for row in legs if self._confirmed_absence(row)}
         fresh: set[UUID] = set()
         for leg in legs:
+            if loop.time() >= deadline:
+                break
             try:
                 async with asyncio.timeout_at(deadline):
                     await self._read_bound(leg)
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_25

Fingerprint: `sha256:c882d1bd4684930195fbb9b790ab6d76362ff633a723bcde76ea78cc3a95046f`.

Approved change: panic deadline race.

Original normalized line: `break`.

Mutated text:

```python
return
```

Approved diff hunk:

```diff
@@ -1863,6 +1863,8 @@
         absent = {row.id for row in legs if self._confirmed_absence(row)}
         fresh: set[UUID] = set()
         for leg in legs:
+            if loop.time() >= deadline:
+                break
             try:
                 async with asyncio.timeout_at(deadline):
                     await self._read_bound(leg)
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_79

Fingerprint: `sha256:2e38277614d82728e8a3befbdb9e72a399ad86d47e462830aa794c68f0e4dd4c`.

Approved change: panic deadline race.

Original normalized line: `if loop.time() >= deadline:`.

Mutated text:

```python
 > deadline
```

Approved diff hunk:

```diff
@@ -1899,6 +1901,8 @@
                 )
         faults: dict[str, str] = {}
         for leg in legs:
+            if loop.time() >= deadline:
+                break
             if leg.id in absent:
                 continue
             try:
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_80

Fingerprint: `sha256:c882d1bd4684930195fbb9b790ab6d76362ff633a723bcde76ea78cc3a95046f`.

Approved change: panic deadline race.

Original normalized line: `break`.

Mutated text:

```python
return
```

Approved diff hunk:

```diff
@@ -1899,6 +1901,8 @@
                 )
         faults: dict[str, str] = {}
         for leg in legs:
+            if loop.time() >= deadline:
+                break
             if leg.id in absent:
                 continue
             try:
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_105

Fingerprint: `sha256:2e38277614d82728e8a3befbdb9e72a399ad86d47e462830aa794c68f0e4dd4c`.

Approved change: panic deadline race.

Original normalized line: `if loop.time() >= deadline:`.

Mutated text:

```python
 > deadline
```

Approved diff hunk:

```diff
@@ -1912,6 +1916,8 @@
         while loop.time() < deadline:
             observed: dict[UUID, BrokerOrder] = {}
             for leg in legs:
+                if loop.time() >= deadline:
+                    break
                 if leg.id in absent:
                     continue
                 try:
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_finalize_entry_cancellation__mutmut_106

Fingerprint: `sha256:c882d1bd4684930195fbb9b790ab6d76362ff633a723bcde76ea78cc3a95046f`.

Approved change: panic deadline race.

Original normalized line: `break`.

Mutated text:

```python
return
```

Approved diff hunk:

```diff
@@ -1912,6 +1916,8 @@
         while loop.time() < deadline:
             observed: dict[UUID, BrokerOrder] = {}
             for leg in legs:
+                if loop.time() >= deadline:
+                    break
                 if leg.id in absent:
                     continue
                 try:
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_135

Fingerprint: `sha256:0f1f9e5215cdc855e4d957aa02cb138ccd6fa0d85246c56ad75ae2a286707bd3`.

Approved change: production assert to explicit integrity error.

Original normalized line: `if approval is None:`.

Mutated text:

```text
" is not "
```

Approved diff hunk:

```diff
@@ -2499,7 +2505,8 @@
             selected = new_stop
             restoring_selected = False
             if standalone_repair:
-                assert approval is not None
+                if approval is None:
+                    raise DataIntegrityError("Standalone stop repair requires a recorded approval")
                 level = approval.old_stop
                 try:
                     inputs = await self._fresh_exit_inputs(entry)
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_136

Fingerprint: `sha256:6adf940d45e2fab14d0c630d10ad24e2618db181ee169938298f510ff17f956f`.

Approved change: production assert to explicit integrity error.

Original normalized line: `raise DataIntegrityError("Standalone stop repair requires a recorded approval")`.

Mutated text:

```python
DataIntegrityError(None)
```

Approved diff hunk:

```diff
@@ -2499,7 +2505,8 @@
             selected = new_stop
             restoring_selected = False
             if standalone_repair:
-                assert approval is not None
+                if approval is None:
+                    raise DataIntegrityError("Standalone stop repair requires a recorded approval")
                 level = approval.old_stop
                 try:
                     inputs = await self._fresh_exit_inputs(entry)
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_137

Fingerprint: `sha256:ba7968c1cf6ceee9277ad9b3c83a9e2035c92f4067fe5d6619d33d96a2f00d88`.

Approved change: production assert to explicit integrity error.

Original normalized line: `raise DataIntegrityError("Standalone stop repair requires a recorded approval")`.

Mutated text:

```python
"XXStandalone stop repair requires a recorded approvalXX"
```

Approved diff hunk:

```diff
@@ -2499,7 +2505,8 @@
             selected = new_stop
             restoring_selected = False
             if standalone_repair:
-                assert approval is not None
+                if approval is None:
+                    raise DataIntegrityError("Standalone stop repair requires a recorded approval")
                 level = approval.old_stop
                 try:
                     inputs = await self._fresh_exit_inputs(entry)
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_138

Fingerprint: `sha256:a63bfbb3f5ce0502396ff622ffa992686d88d8755ad487dcc547f068283c0ae4`.

Approved change: production assert to explicit integrity error.

Original normalized line: `raise DataIntegrityError("Standalone stop repair requires a recorded approval")`.

Mutated text:

```python
"standalone stop repair requires a recorded approval"
```

Approved diff hunk:

```diff
@@ -2499,7 +2505,8 @@
             selected = new_stop
             restoring_selected = False
             if standalone_repair:
-                assert approval is not None
+                if approval is None:
+                    raise DataIntegrityError("Standalone stop repair requires a recorded approval")
                 level = approval.old_stop
                 try:
                     inputs = await self._fresh_exit_inputs(entry)
```

### NEW backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_journaled_stop_repair__mutmut_139

Fingerprint: `sha256:9635915ad2d26462c5dcbfcc8015c5a94ba14f48869335c44e2395df23f94911`.

Approved change: production assert to explicit integrity error.

Original normalized line: `raise DataIntegrityError("Standalone stop repair requires a recorded approval")`.

Mutated text:

```python
"STANDALONE STOP REPAIR REQUIRES A RECORDED APPROVAL"
```

Approved diff hunk:

```diff
@@ -2499,7 +2505,8 @@
             selected = new_stop
             restoring_selected = False
             if standalone_repair:
-                assert approval is not None
+                if approval is None:
+                    raise DataIntegrityError("Standalone stop repair requires a recorded approval")
                 level = approval.old_stop
                 try:
                     inputs = await self._fresh_exit_inputs(entry)
```

## Original source-job proof

The inventory is updated to 15,467. Only EXPECTED_TOTAL and its two numeric messages change in `scripts/mutation_inventory.py`; the generator, gate and proof logic are unchanged. MATCHED mutants are assigned by their old fingerprint owner, rather than numeric name. All 15,456 MATCHED mutants retain their exact original source job. NEW mutations stay in the unique source job holding their function; no cohort changes.

| Job | Before | NEW | GONE | After |
|---|---:|---:|---:|---:|
| executor-b-2 | 1,274 | 5 | 1 | 1,278 |
| executor-b-4 | 559 | 6 | 0 | 565 |
| Other 61 jobs | unchanged | 0 | 0 | unchanged |

The unchanged `load_shards` / `prove_partition` checks pass for all 63 original source jobs: exactly 15,467 unique current IDs, zero overlap, zero missing and zero matched-owner changes. Inventory digest: `a40f765c721166356c590037b8299b40eb7805deec9f3e9a027956d2bf878f14`. This is the source-owner proof, not a completed 135-job execution partition or a claimed invocation of the full preflight CLI.

## 135-job ownership decision pending

All 63 original jobs retain MATCHED mutants. Keeping those exact job names fixed leaves only 11 NEW mutants to populate additional nonempty jobs: at most **63 + 11 = 74**, short of 135. Empty jobs are prohibited by the existing partition check and would not constitute the requested split. The 135-job requirement therefore needs permission to subdivide existing jobs into child execution jobs while retaining their original source owner and cohort. A clarification question is pending; no child partition, matrix or gate change has been applied.

No commit, push, workflow dispatch, fresh native kill run or later pass was performed. Current weekly-audit edits and prior safety fixes remain local. AUTO_LIVE, MANUAL_CSV, the four ledger transitions, GD-07, equivalent allowances, commands, selectors and timeouts are unchanged.
