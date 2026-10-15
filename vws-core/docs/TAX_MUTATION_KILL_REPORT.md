# Tax mutation kill report - October 14, 2026

The 100% tax mutation gate is **not achieved**. No equivalence entry is approved or installed. Every remaining survivor still fails the unchanged checker.

Base: `3e9348573f71481065a41e80bae179e9e3939715`, CI run `38640865007`; baseline diagnostics artifact from run `38640898728`.

## Changes and actual scope

- 93 new collected test cases in 48 new test functions; one case requires POSIX permissions and skips on Windows.
- Tests stay in the three already-selected wash/accounting/report test files. No selector, gate, threshold, timeout, workflow, dependency, cache fixture or equivalent list was changed.
- One production change fixes the demonstrated TX-08 precision bug below. Tax accounting/matching source is unchanged.
- AUTO_LIVE stays locked, MANUAL_CSV disabled. No keys/setup changes, extra shard/workflow dispatches, Dependabot changes, force push or hook bypass.

## Focused mutation evidence

Pinned mutmut generation identifies 1,724 current tax mutants: lots 433, accounting 574, reports 717. The precision fix adds 14 report mutants to the original 1,710. Original report IDs map individually by identical mutation-body differences; both old and current IDs are shown below.

| Cohort | Replayed | Killed by tests | Surviving | No tests in replay |
| --- | ---: | ---: | ---: | ---: |
| Original no-test marked external lots | 38 | 26 | 12 | 0 |
| Original 419 survivors | 419 | 226 | 193 | 0 |
| Added by precision repair | 14 | 12 | 2 | 0 |
| Total focused cohort | 471 | 264 | 207 | 0 |

| File | Current inventory | Focused cases | Killed | Remaining |
| --- | ---: | ---: | ---: | ---: |
| lots.py | 433 | 116 | 35 | 81 |
| accounting.py | 574 | 96 | 37 | 59 |
| reports.py | 717 | 259 | 192 | 67 |

The 207 remaining cases are 203 individual equivalence proposals and four POSIX permission cases. Proposals are documentation only and still fail the gate. There are no blanket/pattern approvals.

These are Windows, unforked, in-memory single-function replays. Each pytest invocation creates and tears down its own session fixtures; imported aliases keep pointing to the callable whose code is temporarily replaced and restored. Focused selections can prove a kill but cannot certify a survivor equivalent. The 1,253 prior native kills were not rerun in this focused pass, and must not be added to claim a fresh full native score. Supported Linux tax mutation profiling and the current full 100% shard result remain UNVERIFIED. Native mutmut refuses Windows; WSL is unavailable.

The same strict ASCII-ID encoding as CI is used in build/tax-kill/targeted-results.txt. All 471 IDs are unique and every case executed tests; the unchanged checker refuses its surviving records. This is a focused export, not a complete shard certificate.

## Real bug and before/after proof

TX-08 accepted finite federal rates with more than 80 significant digits, but annual() rounded them before the conservative cent ceiling. On $1 of interest, a rate 0.01 followed by 79 or 80 zeros and a final 1 is strictly above 1%; the old estimate was $0.01 instead of $0.02.

Both regression cases FAIL before the change (build/tax-kill/rate-bug-before.log) and PASS after it (rate-bug-after.log). reports.py now retains the 80-digit floor and increases precision using all supplied rate exponents plus a 32-digit integral/carry allowance, sufficient for at most 100,000 signed-64-bit micro-unit monetary rows. Rates, set-aside formula, final cent ceiling and all limits are unchanged. All-rates-unavailable still gives totals only. No other production tax source changed.

## Local gates and isolation

| Completed run | Passed | Failed/errors | Skipped | Required branch coverage | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ordered | 5,408 | 0 | 60 | 100% | 1129.13s |
| Random, seed 20261014 | 5,408 | 0 | 60 | 100% | 1287.09s |

Both used the unchanged `-m "not perf"` selector (four performance tests deselected) and produced the same 5,468-case ID multiset in different order. Comparison with the base run proves 93 added cases and zero removed cases. Each covers 7,625 required statements and 2,606 branches with zero missing/partial and the same 20 inherited exclusions. Skips are 57 PostgreSQL, two explicit paper integrations and the new POSIX permission case; none is a pass. Two inherited warnings remain.

The final fixed-decimal formatting witness uses valid $100 input (`Decimal("1E+2")`); its updated control passes and its format mutant fails. The final three-file tax selection is also rechecked after that fixture adjustment; its overlap is not added to the full-suite count. Production code is identical throughout the completed full runs.

Whole Ruff/format, strict types (419 sources), authored-source guard and tax Bandit (zero findings) pass. All five root pre-commit checks pass, including the staged-source secret check. Complete-history gitleaks 8.30.1 before commit: 43 commits, zero leaks. The final reply records the post-commit history scan and delivery status. Raw logs/XML/coverage, per-ID replay evidence and exact cohort-accounting proof are in `build/tax-kill/` (uncommitted evidence).

The planted create_schema RUNNING-to-HALTED mutation is retained: clean/planted/restored exit codes 0 / 1 / 0 in the same interpreter. Session calendar/schema caches remain in memory and teardown clears/disposes them. No disk fixture cache was introduced.

Three preliminary ordered attempts were interrupted while final behavior tests were added; none counts as passing evidence. Only completed final runs are reported above.

## Four cases awaiting supported POSIX execution

The real-filesystem owner-private directory test uses a permissive umask and checks every created directory. It skips on this Windows host; UNVERIFIED is never PASS. These four are not proposed equivalents:

- `backend.tax.reports.x_save_report__mutmut_51`: default or changed mkdir permissions can expose a directory; POSIX test supplied, local kill UNVERIFIED.
- `backend.tax.reports.x_save_report__mutmut_53`: default or changed mkdir permissions can expose a directory; POSIX test supplied, local kill UNVERIFIED.
- `backend.tax.reports.x_save_report__mutmut_61`: default or changed mkdir permissions can expose a directory; POSIX test supplied, local kill UNVERIFIED.
- `backend.tax.reports.x_save_report__mutmut_63`: default or changed mkdir permissions can expose a directory; POSIX test supplied, local kill UNVERIFIED.

## Reproduce on supported Linux without running another mutation shard

From vws-core with the pinned development environment, in a disposable checkout (never owner keys/setup):

```sh
mkdir -p build
python -m pytest -q backend/tests/test_tax_reports.py::test_TX_10_new_export_directories_are_owner_private_under_permissive_umask
python -m mutmut run --max-children 4 'backend.tax.*'
python -m mutmut results --all true > build/tax-results-all.txt
python - <<'PY'
from pathlib import Path
records = {}
for line in Path("build/tax-results-all.txt").read_text().splitlines():
    key, sep, status = line.strip().partition(": ")
    assert sep and key not in records
    records[key] = status
tax = {k: v for k, v in records.items() if k.startswith("backend.tax.")}
assert len(tax) == 1724
Path("build/tax-results.txt").write_text("".join(
    "m_" + key.encode("utf-8").hex() + ": " + status + "\n"
    for key, status in sorted(tax.items())))
PY
python -m scripts.check_mutations build/tax-results.txt
```

No gate change or approval is implied by these reproduction commands. The last command must fail while any surviving/unverified case remains. PostgreSQL/paper integrations were not started; their skips remain unverified.

## Individual proposed equivalents - NOT approved

Each row is a separate proposal requiring the owner's later one-at-a-time review. Reasons concern validated tax behavior; diagnostic wording changes are explicitly disclosed. Unusual private-helper inputs, diagnostic preferences and platform assumptions remain review considerations. No row is an allowance, suppression or passing result.

| Baseline ID (3e934857), or NEW | Current ID when changed | Verifiable reason |
| --- | --- | --- |
| `backend.tax.accounting.x__rebuild__mutmut_107` | same | zip(strict=None) and zip(strict=False) both disable strict length checking; the same adjacent share boundaries are paired. |
| `backend.tax.accounting.x__rebuild__mutmut_110` | same | Omitting zip(strict=False) selects the same False default and produces the same adjacent share intervals. |
| `backend.tax.accounting.x__rebuild__mutmut_15` | same | At tied timestamps same-account BUY/SELL is refused; an other-account replacement cannot be disposed at that instant, so either application point gives the same basis/tacking. |
| `backend.tax.accounting.x__rebuild__mutmut_17` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: wash allocation lacks an actual disposition' becomes None. |
| `backend.tax.accounting.x__rebuild__mutmut_18` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: wash allocation lacks an actual disposition' becomes 'XXTX-05: wash allocation lacks an actual dispositionXX'. |
| `backend.tax.accounting.x__rebuild__mutmut_19` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: wash allocation lacks an actual disposition' becomes 'tx-05: wash allocation lacks an actual disposition'. |
| `backend.tax.accounting.x__rebuild__mutmut_20` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: wash allocation lacks an actual disposition' becomes 'TX-05: WASH ALLOCATION LACKS AN ACTUAL DISPOSITION'. |
| `backend.tax.accounting.x__rebuild__mutmut_276` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02: sale exceeds verified long inventory' becomes None. |
| `backend.tax.accounting.x__rebuild__mutmut_277` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02: sale exceeds verified long inventory' becomes 'XXTX-02: sale exceeds verified long inventoryXX'. |
| `backend.tax.accounting.x__rebuild__mutmut_278` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02: sale exceeds verified long inventory' becomes 'tx-02: sale exceeds verified long inventory'. |
| `backend.tax.accounting.x__rebuild__mutmut_279` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02: sale exceeds verified long inventory' becomes 'TX-02: SALE EXCEEDS VERIFIED LONG INVENTORY'. |
| `backend.tax.accounting.x__rebuild__mutmut_283` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02: bounded accounting intervals exceeded' becomes None. |
| `backend.tax.accounting.x__rebuild__mutmut_284` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02: bounded accounting intervals exceeded' becomes 'XXTX-02: bounded accounting intervals exceededXX'. |
| `backend.tax.accounting.x__rebuild__mutmut_285` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02: bounded accounting intervals exceeded' becomes 'tx-02: bounded accounting intervals exceeded'. |
| `backend.tax.accounting.x__rebuild__mutmut_286` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02: bounded accounting intervals exceeded' becomes 'TX-02: BOUNDED ACCOUNTING INTERVALS EXCEEDED'. |
| `backend.tax.accounting.x__rebuild__mutmut_35` | same | Parts are made from consecutive distinct sorted boundaries and zero-quantity parts are removed; start == end never reaches this selection. |
| `backend.tax.accounting.x__rebuild__mutmut_39` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: replacement share intervals are unavailable' becomes None. |
| `backend.tax.accounting.x__rebuild__mutmut_40` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: replacement share intervals are unavailable' becomes 'XXTX-05: replacement share intervals are unavailableXX'. |
| `backend.tax.accounting.x__rebuild__mutmut_41` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: replacement share intervals are unavailable' becomes 'tx-05: replacement share intervals are unavailable'. |
| `backend.tax.accounting.x__rebuild__mutmut_42` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: replacement share intervals are unavailable' becomes 'TX-05: REPLACEMENT SHARE INTERVALS ARE UNAVAILABLE'. |
| `backend.tax.accounting.x__rebuild__mutmut_53` | same | The shared matcher assigns each replacement share once; a selected part has zero prior extra basis before its sole wash allocation. |
| `backend.tax.accounting.x__rebuild__mutmut_59` | same | 80 to 81 precision digits leave all valid bounded cent/micro-unit arithmetic exact; oversized results are refused by money validation. |
| `backend.tax.accounting.x_anniversary__mutmut_6` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-04: acquisition date cannot establish an anniversary' becomes None. |
| `backend.tax.accounting.x_anniversary__mutmut_7` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-04: acquisition date cannot establish an anniversary' becomes 'XXTX-04: acquisition date cannot establish an anniversaryXX'. |
| `backend.tax.accounting.x_anniversary__mutmut_8` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-04: acquisition date cannot establish an anniversary' becomes 'tx-04: acquisition date cannot establish an anniversary'. |
| `backend.tax.accounting.x_anniversary__mutmut_9` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-04: acquisition date cannot establish an anniversary' becomes 'TX-04: ACQUISITION DATE CANNOT ESTABLISH AN ANNIVERSARY'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_104` | same | 80 to 81 precision digits cannot alter sums of at most 100,000 bounded micro-unit wash amounts. |
| `backend.tax.accounting.x_build_tax_book__mutmut_114` | same | Removing the Decimal zero start leaves nonempty Decimal sums unchanged; the empty integer zero is normalized by TaxSale money validation. |
| `backend.tax.accounting.x_build_tax_book__mutmut_12` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: bounded immutable evidence and explicit environment required' becomes None. |
| `backend.tax.accounting.x_build_tax_book__mutmut_123` | same | Removing the Decimal zero start leaves permanent-loss sums unchanged; TaxSale converts the empty integer zero to the same Decimal zero. |
| `backend.tax.accounting.x_build_tax_book__mutmut_13` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: bounded immutable evidence and explicit environment required' becomes 'XXTX-01: bounded immutable evidence and explicit environment requiredXX'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_134` | same | Economic gain plus an empty integer zero equals gain plus Decimal zero; nonempty disallowed-loss sums remain Decimal. |
| `backend.tax.accounting.x_build_tax_book__mutmut_14` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: bounded immutable evidence and explicit environment required' becomes 'tx-01: bounded immutable evidence and explicit environment required'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_15` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: bounded immutable evidence and explicit environment required' becomes 'TX-01: BOUNDED IMMUTABLE EVIDENCE AND EXPLICIT ENVIRONMENT REQUIRED'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_154` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: wash basis/tacking did not converge within its bound' becomes None. |
| `backend.tax.accounting.x_build_tax_book__mutmut_155` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: wash basis/tacking did not converge within its bound' becomes 'XXTX-05: wash basis/tacking did not converge within its boundXX'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_156` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: wash basis/tacking did not converge within its bound' becomes 'tx-05: wash basis/tacking did not converge within its bound'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_157` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-05: wash basis/tacking did not converge within its bound' becomes 'TX-05: WASH BASIS/TACKING DID NOT CONVERGE WITHIN ITS BOUND'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_158` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-01..05: tax accounting evidence is unverifiable' becomes None. |
| `backend.tax.accounting.x_build_tax_book__mutmut_159` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-01..05: tax accounting evidence is unverifiable' becomes 'XXTX-01..05: tax accounting evidence is unverifiableXX'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_160` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-01..05: tax accounting evidence is unverifiable' becomes 'tx-01..05: tax accounting evidence is unverifiable'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_161` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-01..05: tax accounting evidence is unverifiable' becomes 'TX-01..05: TAX ACCOUNTING EVIDENCE IS UNVERIFIABLE'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_32` | same | SELL tag 1 to 2 preserves BUY-before-SELL order, timestamps and fill UUID ordering. |
| `backend.tax.accounting.x_build_tax_book__mutmut_34` | same | Duplicate account/fill identities still refuse in the shared matcher or final TaxBook lineage validation; no invalid book returns (diagnostic may differ). |
| `backend.tax.accounting.x_build_tax_book__mutmut_35` | same | Empty/duplicate owners still refuse through fill ownership, the shared matcher or final TaxBook account validation (diagnostic may differ). |
| `backend.tax.accounting.x_build_tax_book__mutmut_40` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: account/fill identities must be unique' becomes None. |
| `backend.tax.accounting.x_build_tax_book__mutmut_41` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: account/fill identities must be unique' becomes 'XXTX-01: account/fill identities must be uniqueXX'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_42` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: account/fill identities must be unique' becomes 'tx-01: account/fill identities must be unique'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_43` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: account/fill identities must be unique' becomes 'TX-01: ACCOUNT/FILL IDENTITIES MUST BE UNIQUE'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_44` | same | A newly admitted wrong environment/unknown owner still refuses through account lookup, matching ownership or final TaxBook environment binding (diagnostic may differ). |
| `backend.tax.accounting.x_build_tax_book__mutmut_47` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: fill ownership/environment differs' becomes None. |
| `backend.tax.accounting.x_build_tax_book__mutmut_48` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: fill ownership/environment differs' becomes 'XXTX-01: fill ownership/environment differsXX'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_49` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: fill ownership/environment differs' becomes 'tx-01: fill ownership/environment differs'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_50` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: fill ownership/environment differs' becomes 'TX-01: FILL OWNERSHIP/ENVIRONMENT DIFFERS'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_61` | same | Diagnostic-only: same ValueError refusal; message 'TX-02: tied BUY/SELL fills cannot establish an intraday sequence' becomes None. |
| `backend.tax.accounting.x_build_tax_book__mutmut_62` | same | Diagnostic-only: same ValueError refusal; message 'TX-02: tied BUY/SELL fills cannot establish an intraday sequence' becomes 'XXTX-02: tied BUY/SELL fills cannot establish an intraday sequenceXX'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_63` | same | Diagnostic-only: same ValueError refusal; message 'TX-02: tied BUY/SELL fills cannot establish an intraday sequence' becomes 'tx-02: tied buy/sell fills cannot establish an intraday sequence'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_64` | same | Diagnostic-only: same ValueError refusal; message 'TX-02: tied BUY/SELL fills cannot establish an intraday sequence' becomes 'TX-02: TIED BUY/SELL FILLS CANNOT ESTABLISH AN INTRADAY SEQUENCE'. |
| `backend.tax.accounting.x_build_tax_book__mutmut_78` | same | One extra potential iteration is beyond the fill-bounded chronological wash dependency/refinement chain; the independent 1,024-pass cap remains. |
| `backend.tax.lots.xǁWashSaleMatcherǁ__init____mutmut_10` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Cannot verify wash-sale registry' becomes 'cannot verify wash-sale registry'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ__init____mutmut_2` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash matcher requires an explicit instrument registry' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ__init____mutmut_3` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash matcher requires an explicit instrument registry' becomes 'XXWash matcher requires an explicit instrument registryXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ__init____mutmut_4` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash matcher requires an explicit instrument registry' becomes 'wash matcher requires an explicit instrument registry'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ__init____mutmut_5` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash matcher requires an explicit instrument registry' becomes 'WASH MATCHER REQUIRES AN EXPLICIT INSTRUMENT REGISTRY'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ__init____mutmut_9` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Cannot verify wash-sale registry' becomes 'XXCannot verify wash-sale registryXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_adjustment__mutmut_24` | same | The UTCDateTime boundary normalizes the intermediate local aware timestamp to the same UTC instant within supported report dates. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_adjustment__mutmut_3` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Loss sale lacks holding-period metadata' becomes 'XXLoss sale lacks holding-period metadataXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_adjustment__mutmut_4` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Loss sale lacks holding-period metadata' becomes 'loss sale lacks holding-period metadata'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_adjustment__mutmut_9` | same | 80 to 81 precision digits: valid cent prices and signed-64-bit micro-unit output money require far fewer digits; accepted amounts stay exact. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_available_slices__mutmut_4` | same | At end == cursor the available gap is zero and cursor is unchanged, so processing that interval instead of skipping it allocates no shares. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_13` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Tax account identifiers must be unique' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_14` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Tax account identifiers must be unique' becomes 'XXTax account identifiers must be uniqueXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_15` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Tax account identifiers must be unique' becomes 'tax account identifiers must be unique'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_16` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Tax account identifiers must be unique' becomes 'TAX ACCOUNT IDENTIFIERS MUST BE UNIQUE'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_29` | same | Changing the SELL sort tag from 1 to 2 preserves BUY-before-SELL ordering and the timestamp/UUID tie breakers. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_32` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Executed trade identifiers must be unique' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_33` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Executed trade identifiers must be unique' becomes 'XXExecuted trade identifiers must be uniqueXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_34` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Executed trade identifiers must be unique' becomes 'executed trade identifiers must be unique'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_35` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Executed trade identifiers must be unique' becomes 'EXECUTED TRADE IDENTIFIERS MUST BE UNIQUE'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_38` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Executed trade ownership/tax status is unknown' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_39` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Executed trade ownership/tax status is unknown' becomes 'XXExecuted trade ownership/tax status is unknownXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_4` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash-sale evidence must be immutable tuples' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_40` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Executed trade ownership/tax status is unknown' becomes 'executed trade ownership/tax status is unknown'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_41` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Executed trade ownership/tax status is unknown' becomes 'EXECUTED TRADE OWNERSHIP/TAX STATUS IS UNKNOWN'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_48` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Disposal execution slices differ in account, symbol, timestamp or price' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_49` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Disposal execution slices differ in account, symbol, timestamp or price' becomes 'XXDisposal execution slices differ in account, symbol, timestamp or priceXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_5` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash-sale evidence must be immutable tuples' becomes 'XXWash-sale evidence must be immutable tuplesXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_50` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Disposal execution slices differ in account, symbol, timestamp or price' becomes 'disposal execution slices differ in account, symbol, timestamp or price'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_51` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Disposal execution slices differ in account, symbol, timestamp or price' becomes 'DISPOSAL EXECUTION SLICES DIFFER IN ACCOUNT, SYMBOL, TIMESTAMP OR PRICE'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_6` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash-sale evidence must be immutable tuples' becomes 'wash-sale evidence must be immutable tuples'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_68` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Tied BUY/SELL execution requires original-lot metadata' becomes 'XXTied BUY/SELL execution requires original-lot metadataXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_7` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash-sale evidence must be immutable tuples' becomes 'WASH-SALE EVIDENCE MUST BE IMMUTABLE TUPLES'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_20` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL references an unavailable original purchase' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_21` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL references an unavailable original purchase' becomes 'XXSELL references an unavailable original purchaseXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_22` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL references an unavailable original purchase' becomes 'sell references an unavailable original purchase'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_23` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL references an unavailable original purchase' becomes 'SELL REFERENCES AN UNAVAILABLE ORIGINAL PURCHASE'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_27` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL holding-period evidence disagrees with purchase' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_28` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL holding-period evidence disagrees with purchase' becomes 'XXSELL holding-period evidence disagrees with purchaseXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_29` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL holding-period evidence disagrees with purchase' becomes 'sell holding-period evidence disagrees with purchase'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_30` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL holding-period evidence disagrees with purchase' becomes 'SELL HOLDING-PERIOD EVIDENCE DISAGREES WITH PURCHASE'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_38` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL original purchase is ambiguous; supply its ID' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_39` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL original purchase is ambiguous; supply its ID' becomes 'XXSELL original purchase is ambiguous; supply its IDXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_40` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL original purchase is ambiguous; supply its ID' becomes 'sell original purchase is ambiguous; supply its id'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_41` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL original purchase is ambiguous; supply its ID' becomes 'SELL ORIGINAL PURCHASE IS AMBIGUOUS; SUPPLY ITS ID'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_57` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL exceeds verified original-purchase inventory' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_58` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL exceeds verified original-purchase inventory' becomes 'XXSELL exceeds verified original-purchase inventoryXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_59` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL exceeds verified original-purchase inventory' becomes 'sell exceeds verified original-purchase inventory'. |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_60` | same | Diagnostic-only: same DataIntegrityError refusal; message 'SELL exceeds verified original-purchase inventory' becomes 'SELL EXCEEDS VERIFIED ORIGINAL-PURCHASE INVENTORY'. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_100` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Cannot verify wash-sale matching evidence' becomes 'cannot verify wash-sale matching evidence'. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_44` | same | The preceding membership test guarantees the replacement ID exists; the changed dict.get default is never used. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_46` | same | The preceding membership test guarantees the replacement ID exists; omitting the dict.get default cannot change a matched quantity. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_47` | same | The preceding membership test guarantees the replacement ID exists; changing its unused default to 1 cannot change a matched quantity. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_75` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash loss allocation is below supported micro-unit precision' becomes 'XXWash loss allocation is below supported micro-unit precisionXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_76` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Wash loss allocation is below supported micro-unit precision' becomes 'wash loss allocation is below supported micro-unit precision'. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_99` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Cannot verify wash-sale matching evidence' becomes 'XXCannot verify wash-sale matching evidenceXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_11` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Form 8949 evidence repeats a loss/replacement slice' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_12` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Form 8949 evidence repeats a loss/replacement slice' becomes 'XXForm 8949 evidence repeats a loss/replacement sliceXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_13` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Form 8949 evidence repeats a loss/replacement slice' becomes 'form 8949 evidence repeats a loss/replacement slice'. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_14` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Form 8949 evidence repeats a loss/replacement slice' becomes 'FORM 8949 EVIDENCE REPEATS A LOSS/REPLACEMENT SLICE'. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_16` | same | 80 to 81 precision digits cannot round the addition/subtraction of bounded signed-64-bit micro-unit money differently. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_2` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Form 8949 evidence must be an immutable tuple' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_3` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Form 8949 evidence must be an immutable tuple' becomes 'XXForm 8949 evidence must be an immutable tupleXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_38` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Cannot verify Form 8949 wash-sale evidence' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_39` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Cannot verify Form 8949 wash-sale evidence' becomes 'XXCannot verify Form 8949 wash-sale evidenceXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_4` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Form 8949 evidence must be an immutable tuple' becomes 'form 8949 evidence must be an immutable tuple'. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_40` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Cannot verify Form 8949 wash-sale evidence' becomes 'cannot verify form 8949 wash-sale evidence'. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_41` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Cannot verify Form 8949 wash-sale evidence' becomes 'CANNOT VERIFY FORM 8949 WASH-SALE EVIDENCE'. |
| `backend.tax.lots.xǁWashSaleMatcherǁform_8949_rows__mutmut_5` | same | Diagnostic-only: same DataIntegrityError refusal; message 'Form 8949 evidence must be an immutable tuple' becomes 'FORM 8949 EVIDENCE MUST BE AN IMMUTABLE TUPLE'. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_15` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: duplicate external marked lot' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_16` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: duplicate external marked lot' becomes 'XXTX: duplicate external marked lotXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_17` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: duplicate external marked lot' becomes 'tx: duplicate external marked lot'. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_18` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: duplicate external marked lot' becomes 'TX: DUPLICATE EXTERNAL MARKED LOT'. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_35` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: external marked lot awareness cannot be validated' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_36` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: external marked lot awareness cannot be validated' becomes 'XXTX: external marked lot awareness cannot be validatedXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_37` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: external marked lot awareness cannot be validated' becomes 'tx: external marked lot awareness cannot be validated'. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_38` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: external marked lot awareness cannot be validated' becomes 'TX: EXTERNAL MARKED LOT AWARENESS CANNOT BE VALIDATED'. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_6` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: sale awareness requires SELL and immutable marked lots' becomes None. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_7` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: sale awareness requires SELL and immutable marked lots' becomes 'XXTX: sale awareness requires SELL and immutable marked lotsXX'. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_8` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: sale awareness requires SELL and immutable marked lots' becomes 'tx: sale awareness requires sell and immutable marked lots'. |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_9` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX: sale awareness requires SELL and immutable marked lots' becomes 'TX: SALE AWARENESS REQUIRES SELL AND IMMUTABLE MARKED LOTS'. |
| `backend.tax.reports.x__cell__mutmut_6` | same | Decimal f and F formatting are identical for the finite monetary values permitted in validated tax exports. |
| `backend.tax.reports.x__csv__mutmut_18` | same | UTF-8 and utf-8 name the same Python codec; exported bytes are identical. |
| `backend.tax.reports.x__net_terms__mutmut_11` | same | The added st == 0 branch has min(abs(st), abs(lt)) == 0, so no capital amount is offset. |
| `backend.tax.reports.x__net_terms__mutmut_13` | same | The added lt == 0 branch has zero offset, so neither capital amount changes. |
| `backend.tax.reports.x__net_terms__mutmut_14` | same | The added lt == 0 branch has zero offset; capital netting is unchanged. |
| `backend.tax.reports.x__net_terms__mutmut_16` | same | The added st == 0 branch has zero offset; capital netting is unchanged. |
| `backend.tax.reports.x__net_terms__mutmut_22` | same | At st == 0 the offset is zero, so choosing addition instead of subtraction does not change the tax amount. |
| `backend.tax.reports.x__net_terms__mutmut_28` | same | At lt == 0 the offset is zero, so choosing addition instead of subtraction does not change the tax amount. |
| NEW | `backend.tax.reports.x_annual__mutmut_104` | The changed min default is used only when all rates are None; the 80-digit floor dominates both 32 and 31 and no estimate is calculated. |
| `backend.tax.reports.x_annual__mutmut_95` | `backend.tax.reports.x_annual__mutmut_109` | A missing ST sum starts at integer zero instead of Decimal zero; later money validation normalizes it, and nonempty Decimal sums are unchanged. |
| `backend.tax.reports.x_annual__mutmut_105` | `backend.tax.reports.x_annual__mutmut_119` | A missing LT sum starts at integer zero instead of Decimal zero; later money validation normalizes it, and nonempty Decimal sums are unchanged. |
| `backend.tax.reports.x_annual__mutmut_19` | same | Year 9999 still refuses: the wash-window deadline overflows and AnnualTax independently forbids years above 9998. |
| `backend.tax.reports.x_annual__mutmut_176` | `backend.tax.reports.x_annual__mutmut_190` | Empty dividend integer zero is normalized by AnnualTax money validation; nonempty dividend sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_186` | `backend.tax.reports.x_annual__mutmut_200` | Empty interest integer zero is normalized by AnnualTax money validation; nonempty interest sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_196` | `backend.tax.reports.x_annual__mutmut_210` | Empty fee integer zero is normalized by AnnualTax money validation; nonempty absolute fee sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_212` | `backend.tax.reports.x_annual__mutmut_226` | Adding an empty integer-zero dividend sum to Decimal interest gives the same ordinary-income amount. |
| `backend.tax.reports.x_annual__mutmut_228` | `backend.tax.reports.x_annual__mutmut_242` | An empty qualified-income integer zero is used in the same Decimal arithmetic and final cent quantization. |
| `backend.tax.reports.x_annual__mutmut_31` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: paper requires --simulate; live and paper reports stay separate' becomes None. |
| `backend.tax.reports.x_annual__mutmut_32` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: paper requires --simulate; live and paper reports stay separate' becomes 'XXTX-01: paper requires --simulate; live and paper reports stay separateXX'. |
| `backend.tax.reports.x_annual__mutmut_33` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: paper requires --simulate; live and paper reports stay separate' becomes 'tx-01: paper requires --simulate; live and paper reports stay separate'. |
| `backend.tax.reports.x_annual__mutmut_34` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: paper requires --simulate; live and paper reports stay separate' becomes 'TX-01: PAPER REQUIRES --SIMULATE; LIVE AND PAPER REPORTS STAY SEPARATE'. |
| `backend.tax.reports.x_annual__mutmut_326` | `backend.tax.reports.x_annual__mutmut_340` | Empty wash-disallowed integer zero is normalized by AnnualTax money validation; nonempty wash sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_332` | `backend.tax.reports.x_annual__mutmut_346` | Empty permanent-loss integer zero is normalized by AnnualTax money validation; nonempty permanent-loss sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_347` | `backend.tax.reports.x_annual__mutmut_361` | Diagnostic-only: same DataIntegrityError refusal; message 'TX-01/06..08: annual tax evidence cannot be verified' becomes None. |
| `backend.tax.reports.x_annual__mutmut_348` | `backend.tax.reports.x_annual__mutmut_362` | Diagnostic-only: same DataIntegrityError refusal; message 'TX-01/06..08: annual tax evidence cannot be verified' becomes 'XXTX-01/06..08: annual tax evidence cannot be verifiedXX'. |
| `backend.tax.reports.x_annual__mutmut_349` | `backend.tax.reports.x_annual__mutmut_363` | Diagnostic-only: same DataIntegrityError refusal; message 'TX-01/06..08: annual tax evidence cannot be verified' becomes 'tx-01/06..08: annual tax evidence cannot be verified'. |
| `backend.tax.reports.x_annual__mutmut_350` | `backend.tax.reports.x_annual__mutmut_364` | Diagnostic-only: same DataIntegrityError refusal; message 'TX-01/06..08: annual tax evidence cannot be verified' becomes 'TX-01/06..08: ANNUAL TAX EVIDENCE CANNOT BE VERIFIED'. |
| `backend.tax.reports.x_annual__mutmut_44` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: no selected taxable account' becomes None. |
| `backend.tax.reports.x_annual__mutmut_45` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: no selected taxable account' becomes 'XXTX-01: no selected taxable accountXX'. |
| `backend.tax.reports.x_annual__mutmut_46` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: no selected taxable account' becomes 'tx-01: no selected taxable account'. |
| `backend.tax.reports.x_annual__mutmut_47` | same | Diagnostic-only: same ValueError refusal; message 'TX-01: no selected taxable account' becomes 'TX-01: NO SELECTED TAXABLE ACCOUNT'. |
| `backend.tax.reports.x_annual__mutmut_63` | same | Diagnostic-only: same ValueError refusal; message 'TX-01/06: income/fill source or date differs from the report' becomes None. |
| `backend.tax.reports.x_annual__mutmut_64` | same | Diagnostic-only: same ValueError refusal; message 'TX-01/06: income/fill source or date differs from the report' becomes 'XXTX-01/06: income/fill source or date differs from the reportXX'. |
| `backend.tax.reports.x_annual__mutmut_65` | same | Diagnostic-only: same ValueError refusal; message 'TX-01/06: income/fill source or date differs from the report' becomes 'tx-01/06: income/fill source or date differs from the report'. |
| `backend.tax.reports.x_annual__mutmut_66` | same | Diagnostic-only: same ValueError refusal; message 'TX-01/06: income/fill source or date differs from the report' becomes 'TX-01/06: INCOME/FILL SOURCE OR DATE DIFFERS FROM THE REPORT'. |
| `backend.tax.reports.x_annual__mutmut_85` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-06: positive fee adjustment needs verified refund attribution' becomes None. |
| `backend.tax.reports.x_annual__mutmut_86` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-06: positive fee adjustment needs verified refund attribution' becomes 'XXTX-06: positive fee adjustment needs verified refund attributionXX'. |
| `backend.tax.reports.x_annual__mutmut_87` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-06: positive fee adjustment needs verified refund attribution' becomes 'tx-06: positive fee adjustment needs verified refund attribution'. |
| `backend.tax.reports.x_annual__mutmut_88` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-06: positive fee adjustment needs verified refund attribution' becomes 'TX-06: POSITIVE FEE ADJUSTMENT NEEDS VERIFIED REFUND ATTRIBUTION'. |
| `backend.tax.reports.x_annual__mutmut_90` | same | In the repaired source, raising the minimum precision from 80 to 81 adds no rounding: exponent-based precision already covers bounded amounts and every rate digit. |
| NEW | `backend.tax.reports.x_annual__mutmut_97` | 32 to 33 carry/integral digits both exceed bounded money-sum requirements; the same complete rate digits and cent ceiling are retained. |
| `backend.tax.reports.x_render_report__mutmut_16` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02/10: tax book differs from verified executed accounting' becomes None. |
| `backend.tax.reports.x_render_report__mutmut_17` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02/10: tax book differs from verified executed accounting' becomes 'XXTX-02/10: tax book differs from verified executed accountingXX'. |
| `backend.tax.reports.x_render_report__mutmut_18` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02/10: tax book differs from verified executed accounting' becomes 'tx-02/10: tax book differs from verified executed accounting'. |
| `backend.tax.reports.x_render_report__mutmut_19` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-02/10: tax book differs from verified executed accounting' becomes 'TX-02/10: TAX BOOK DIFFERS FROM VERIFIED EXECUTED ACCOUNTING'. |
| `backend.tax.reports.x_render_report__mutmut_195` | same | README UTF-8 and utf-8 encoding use the same Python codec and produce identical bytes. |
| `backend.tax.reports.x_render_report__mutmut_91` | same | Pinned Pydantic serializes mode=None through the same Python-value branch; CSV cell values remain the same. |
| `backend.tax.reports.x_render_report__mutmut_92` | same | Pinned Pydantic uses Python-value serialization for this non-json mode string; validated report cell values remain the same. |
| `backend.tax.reports.x_render_report__mutmut_93` | same | Pinned Pydantic uses Python-value serialization for this non-json mode string; validated report cell values remain the same. |
| `backend.tax.reports.x_save_report__mutmut_27` | same | Diagnostic-only: same ValueError refusal; message 'TX-07: bounded complete tax report required' becomes None. |
| `backend.tax.reports.x_save_report__mutmut_28` | same | Diagnostic-only: same ValueError refusal; message 'TX-07: bounded complete tax report required' becomes 'XXTX-07: bounded complete tax report requiredXX'. |
| `backend.tax.reports.x_save_report__mutmut_29` | same | Diagnostic-only: same ValueError refusal; message 'TX-07: bounded complete tax report required' becomes 'tx-07: bounded complete tax report required'. |
| `backend.tax.reports.x_save_report__mutmut_30` | same | Diagnostic-only: same ValueError refusal; message 'TX-07: bounded complete tax report required' becomes 'TX-07: BOUNDED COMPLETE TAX REPORT REQUIRED'. |
| `backend.tax.reports.x_save_report__mutmut_44` | same | UTF-8 and utf-8 encode account names identically, so the account-bound directory hash is unchanged. |
| `backend.tax.reports.x_save_report__mutmut_74` | same | Both versions accept only the exact immutable payload and reject extra bytes; reading at most one additional byte does not change that decision. |
| `backend.tax.reports.x_save_report__mutmut_76` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-10: existing immutable export differs' becomes None. |
| `backend.tax.reports.x_save_report__mutmut_77` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-10: existing immutable export differs' becomes 'XXTX-10: existing immutable export differsXX'. |
| `backend.tax.reports.x_save_report__mutmut_78` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-10: existing immutable export differs' becomes 'tx-10: existing immutable export differs'. |
| `backend.tax.reports.x_save_report__mutmut_79` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-10: existing immutable export differs' becomes 'TX-10: EXISTING IMMUTABLE EXPORT DIFFERS'. |
| `backend.tax.reports.x_save_report__mutmut_84` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-07/10: tax report could not be safely published' becomes None. |
| `backend.tax.reports.x_save_report__mutmut_85` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-07/10: tax report could not be safely published' becomes 'XXTX-07/10: tax report could not be safely publishedXX'. |
| `backend.tax.reports.x_save_report__mutmut_86` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-07/10: tax report could not be safely published' becomes 'tx-07/10: tax report could not be safely published'. |
| `backend.tax.reports.x_save_report__mutmut_87` | same | Diagnostic-only: same DataIntegrityError refusal; message 'TX-07/10: tax report could not be safely published' becomes 'TX-07/10: TAX REPORT COULD NOT BE SAFELY PUBLISHED'. |

## Every killed focused case

Each row records the first failing behavior test from its single-mutant replay; all ordinary controls pass in the completed offline runs. This table plus the proposals and four POSIX rows accounts for all 471 targeted cases, including every original survivor/no-test ID.

| Baseline ID, or NEW | Current ID when changed | First failing test |
| --- | --- | --- |
| `backend.tax.accounting.x__rebuild__mutmut_129` | same | `backend/tests/test_tax_accounting.py::test_TX_06_drip_acquisition_remains_identified_in_shared_history` |
| `backend.tax.accounting.x__rebuild__mutmut_158` | same | `backend/tests/test_tax_accounting.py::test_TX_03_sell_fees_are_allocated_once_across_multiple_original_lots` |
| `backend.tax.accounting.x__rebuild__mutmut_167` | same | `backend/tests/test_tax_accounting.py::test_TX_03_sell_fees_are_allocated_once_across_multiple_original_lots` |
| `backend.tax.accounting.x__rebuild__mutmut_241` | same | `backend/tests/test_tax_accounting.py::test_TX_03_sell_fees_are_allocated_once_across_multiple_original_lots` |
| `backend.tax.accounting.x__rebuild__mutmut_252` | same | `backend/tests/test_tax_accounting.py::test_TX_03_sell_fees_are_allocated_once_across_multiple_original_lots` |
| `backend.tax.accounting.x__rebuild__mutmut_267` | same | `backend/tests/test_tax_accounting.py::test_TX_05_partial_washed_share_interval_preserves_undisposed_extra_basis` |
| `backend.tax.accounting.x__rebuild__mutmut_268` | same | `backend/tests/test_tax_accounting.py::test_TX_05_partial_washed_share_interval_preserves_undisposed_extra_basis` |
| `backend.tax.accounting.x__rebuild__mutmut_269` | same | `backend/tests/test_tax_accounting.py::test_TX_05_partial_disposals_conserve_remaining_wash_basis` |
| `backend.tax.accounting.x__rebuild__mutmut_282` | same | `backend/tests/test_tax_accounting.py::test_TX_02_row_capacity_accepts_exact_boundary_and_refuses_overflow` |
| `backend.tax.accounting.x__rebuild__mutmut_296` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compressed_open_lots_conserve_uneven_pool_rounding` |
| `backend.tax.accounting.x__rebuild__mutmut_47` | same | `backend/tests/test_tax_accounting.py::test_TX_05_partial_disposals_conserve_remaining_wash_basis` |
| `backend.tax.accounting.x__rebuild__mutmut_55` | same | `backend/tests/test_tax_accounting.py::test_TX_05_partial_disposals_conserve_remaining_wash_basis` |
| `backend.tax.accounting.x__rebuild__mutmut_57` | same | `backend/tests/test_tax_accounting.py::test_TX_05_partial_disposals_conserve_remaining_wash_basis` |
| `backend.tax.accounting.x_anniversary__mutmut_22` | same | `backend/tests/test_tax_accounting.py::test_TX_04_february_nonleap_anniversary_preserves_day` |
| `backend.tax.accounting.x_build_tax_book__mutmut_1` | same | `backend/tests/test_tax_accounting.py::test_TX_01_untrusted_history_cannot_hide_its_advertised_capacity_overflow` |
| `backend.tax.accounting.x_build_tax_book__mutmut_10` | same | `backend/tests/test_tax_accounting.py::test_TX_01_live_accounting_uses_only_live_bound_fills` |
| `backend.tax.accounting.x_build_tax_book__mutmut_11` | same | `backend/tests/test_tax_accounting.py::test_TX_01_live_accounting_uses_only_live_bound_fills` |
| `backend.tax.accounting.x_build_tax_book__mutmut_124` | same | `backend/tests/test_tax_accounting.py::test_TX_05_permanent_loss_is_attributed_only_to_its_own_disposal` |
| `backend.tax.accounting.x_build_tax_book__mutmut_2` | same | `backend/tests/test_tax_accounting.py::test_TX_01_public_accounting_requires_immutable_evidence[accounts]` |
| `backend.tax.accounting.x_build_tax_book__mutmut_28` | same | `backend/tests/test_tax_accounting.py::test_TX_05_simultaneous_cross_account_rebuy_has_available_replacement_shares` |
| `backend.tax.accounting.x_build_tax_book__mutmut_29` | same | `backend/tests/test_tax_accounting.py::test_TX_05_simultaneous_cross_account_rebuy_has_available_replacement_shares` |
| `backend.tax.accounting.x_build_tax_book__mutmut_3` | same | `backend/tests/test_tax_accounting.py::test_TX_01_public_accounting_requires_immutable_evidence[fills]` |
| `backend.tax.accounting.x_build_tax_book__mutmut_30` | same | `backend/tests/test_tax_accounting.py::test_TX_05_simultaneous_cross_account_rebuy_has_available_replacement_shares` |
| `backend.tax.accounting.x_build_tax_book__mutmut_31` | same | `backend/tests/test_tax_accounting.py::test_TX_05_simultaneous_cross_account_rebuy_has_available_replacement_shares` |
| `backend.tax.accounting.x_build_tax_book__mutmut_33` | same | `backend/tests/test_tax_accounting.py::test_TX_01_duplicate_broker_activity_cannot_create_two_acquisitions` |
| `backend.tax.accounting.x_build_tax_book__mutmut_6` | same | `backend/tests/test_tax_accounting.py::test_TX_02_row_capacity_accepts_exact_boundary_and_refuses_overflow` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_10` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_11` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_12` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_13` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_14` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_22` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_23` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_30` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_31` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_8` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.accounting.xǁTaxBookǁcompliance_lots__mutmut_9` | same | `backend/tests/test_tax_accounting.py::test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence` |
| `backend.tax.lots.xǁWashSaleMatcherǁ_available_slices__mutmut_20` | same | `backend/tests/test_wash_sales.py::test_cmp_02_retained_share_ranges_skip_previous_matches_without_reusing_them[0-assigned0-3-expected0]` |
| `backend.tax.lots.xǁWashSaleMatcherǁ_available_slices__mutmut_21` | same | `backend/tests/test_wash_sales.py::test_cmp_02_retained_share_ranges_skip_previous_matches_without_reusing_them[0-assigned0-3-expected0]` |
| `backend.tax.lots.xǁWashSaleMatcherǁ_available_slices__mutmut_28` | same | `backend/tests/test_wash_sales.py::test_cmp_02_retained_share_ranges_skip_previous_matches_without_reusing_them[0-assigned0-3-expected0]` |
| `backend.tax.lots.xǁWashSaleMatcherǁ_available_slices__mutmut_5` | same | `backend/tests/test_wash_sales.py::test_cmp_02_retained_share_ranges_skip_previous_matches_without_reusing_them[4-assigned1-2-expected1]` |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_30` | same | `backend/tests/test_wash_sales.py::test_cmp_02_same_time_replacements_have_stable_share_priority` |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_53` | same | `backend/tests/test_wash_sales.py::test_cmp_02_fifo_disposal_spanning_purchases_keeps_only_retained_shares` |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_54` | same | `backend/tests/test_wash_sales.py::test_cmp_02_fifo_disposal_spanning_purchases_keeps_only_retained_shares` |
| `backend.tax.lots.xǁWashSaleMatcherǁ_survivors__mutmut_61` | same | `backend/tests/test_wash_sales.py::test_cmp_02_one_execution_with_gain_and_loss_slices_has_only_a_loss_snapshot` |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_57` | same | `backend/tests/test_wash_sales.py::test_cmp_02_partial_replacements_cannot_overallocate_remaining_loss` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_1` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_10` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_11` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_12` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_13` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_14` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_19` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_2` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_20` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_21` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_22` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_23` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_24` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_25` | same | `backend/tests/test_wash_sales.py::test_TX_marked_lots_use_declared_identity_and_external_ownership` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_26` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-30-True-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_27` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-30-True-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_28` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-30-True-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_29` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_3` | same | `backend/tests/test_wash_sales.py::test_TX_marked_awareness_refuses_invalid_evidence[buy]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_30` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_31` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_32` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_33` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-30-True-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_34` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_4` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.lots.xǁWashSaleMatcherǁmarked_external_lots__mutmut_5` | same | `backend/tests/test_wash_sales.py::test_TX_marked_outside_accounts_review_inclusive_window[-31-False-ira]` |
| `backend.tax.reports.x__cell__mutmut_19` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_text_cannot_be_interpreted_as_a_spreadsheet_formula[+SUM(A1)]` |
| `backend.tax.reports.x__cell__mutmut_20` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_text_cannot_be_interpreted_as_a_spreadsheet_formula[-2+3]` |
| `backend.tax.reports.x__cell__mutmut_21` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_text_cannot_be_interpreted_as_a_spreadsheet_formula[@SUM(A1)]` |
| `backend.tax.reports.x__cell__mutmut_22` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_text_cannot_be_interpreted_as_a_spreadsheet_formula[\t=1]` |
| `backend.tax.reports.x__cell__mutmut_23` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_text_cannot_be_interpreted_as_a_spreadsheet_formula[\r=1]` |
| `backend.tax.reports.x__cell__mutmut_4` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_uses_exact_fixed_decimal_and_handles_embedded_newlines` |
| `backend.tax.reports.x__csv__mutmut_11` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_uses_exact_fixed_decimal_and_handles_embedded_newlines` |
| `backend.tax.reports.x__csv__mutmut_12` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_uses_exact_fixed_decimal_and_handles_embedded_newlines` |
| `backend.tax.reports.x__csv__mutmut_2` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_text_cannot_be_interpreted_as_a_spreadsheet_formula[\r=1]` |
| `backend.tax.reports.x__csv__mutmut_8` | same | `backend/tests/test_tax_reports.py::test_TX_10_csv_uses_exact_fixed_decimal_and_handles_embedded_newlines` |
| `backend.tax.reports.x__net_terms__mutmut_12` | same | `backend/tests/test_tax_reports.py::test_TX_07_schedule_d_offsets_only_opposite_terms[-.25-.10-result0]` |
| `backend.tax.reports.x__net_terms__mutmut_15` | same | `backend/tests/test_tax_reports.py::test_TX_07_schedule_d_offsets_only_opposite_terms[.10--.25-result1]` |
| `backend.tax.reports.x__net_terms__mutmut_19` | same | `backend/tests/test_tax_reports.py::test_TX_07_schedule_d_offsets_only_opposite_terms[-.25-.10-result0]` |
| `backend.tax.reports.x__net_terms__mutmut_21` | same | `backend/tests/test_tax_reports.py::test_TX_07_schedule_d_offsets_only_opposite_terms[-.25-.10-result0]` |
| `backend.tax.reports.x__net_terms__mutmut_23` | same | `backend/tests/test_tax_reports.py::test_TX_07_schedule_d_offsets_only_opposite_terms[.10--.25-result1]` |
| `backend.tax.reports.x__net_terms__mutmut_26` | same | `backend/tests/test_tax_reports.py::test_TX_07_schedule_d_offsets_only_opposite_terms[-.25-.10-result0]` |
| `backend.tax.reports.x__net_terms__mutmut_29` | same | `backend/tests/test_tax_reports.py::test_TX_07_schedule_d_offsets_only_opposite_terms[-.25-.10-result0]` |
| `backend.tax.reports.x__net_terms__mutmut_3` | same | `backend/tests/test_tax_reports.py::test_TX_07_schedule_d_offsets_only_opposite_terms[.25-.10-result2]` |
| `backend.tax.reports.x__net_terms__mutmut_30` | same | `backend/tests/test_tax_reports.py::test_TX_07_schedule_d_offsets_only_opposite_terms[-.25-.10-result0]` |
| `backend.tax.reports.x_annual__mutmut_10` | same | `backend/tests/test_tax_reports.py::test_TX_01_annual_rejects_mutable_income_and_non_boolean_simulation` |
| NEW | `backend.tax.reports.x_annual__mutmut_100` | `backend/tests/test_tax_reports.py::test_all_simulated_export_headers_rows_and_immutable_files` |
| NEW | `backend.tax.reports.x_annual__mutmut_101` | `backend/tests/test_tax_reports.py::test_TX_08_all_rates_unavailable_still_reports_totals_without_an_estimate` |
| NEW | `backend.tax.reports.x_annual__mutmut_102` | `backend/tests/test_tax_reports.py::test_all_simulated_export_headers_rows_and_immutable_files` |
| NEW | `backend.tax.reports.x_annual__mutmut_103` | `backend/tests/test_tax_reports.py::test_all_simulated_export_headers_rows_and_immutable_files` |
| `backend.tax.reports.x_annual__mutmut_11` | same | `backend/tests/test_tax_reports.py::test_TX_01_05_report_calendar_evidence_cannot_override_comparisons[cutoff]` |
| `backend.tax.reports.x_annual__mutmut_12` | same | `backend/tests/test_tax_reports.py::test_TX_01_05_report_calendar_evidence_cannot_override_comparisons[year]` |
| `backend.tax.reports.x_annual__mutmut_135` | `backend.tax.reports.x_annual__mutmut_149` | `backend/tests/test_tax_reports.py::test_TX_07_long_term_carryover_consumes_only_unused_short_term_deduction[15-9-0-0-0]` |
| `backend.tax.reports.x_annual__mutmut_136` | `backend.tax.reports.x_annual__mutmut_150` | `backend/tests/test_tax_reports.py::test_TX_07_long_term_carryover_consumes_only_unused_short_term_deduction[9-5-3000-0-3000]` |
| `backend.tax.reports.x_annual__mutmut_16` | same | `backend/tests/test_tax_reports.py::test_TX_07_supported_tax_year_endpoints[1900]` |
| `backend.tax.reports.x_annual__mutmut_146` | `backend.tax.reports.x_annual__mutmut_160` | `backend/tests/test_tax_reports.py::test_TX_07_long_term_carryover_consumes_only_unused_short_term_deduction[11-5-3000-0-1000]` |
| `backend.tax.reports.x_annual__mutmut_151` | `backend.tax.reports.x_annual__mutmut_165` | `backend/tests/test_tax_reports.py::test_TX_07_long_term_carryover_consumes_only_unused_short_term_deduction[9-5-3000-0-3000]` |
| `backend.tax.reports.x_annual__mutmut_17` | same | `backend/tests/test_tax_reports.py::test_TX_07_supported_tax_year_endpoints[1900]` |
| `backend.tax.reports.x_annual__mutmut_160` | `backend.tax.reports.x_annual__mutmut_174` | `backend/tests/test_tax_reports.py::test_TX_07_long_term_carryover_consumes_only_unused_short_term_deduction[9-5-3000-0-3000]` |
| `backend.tax.reports.x_annual__mutmut_161` | `backend.tax.reports.x_annual__mutmut_175` | `backend/tests/test_tax_reports.py::test_TX_07_long_term_carryover_consumes_only_unused_short_term_deduction[9-5-3000-0-3000]` |
| `backend.tax.reports.x_annual__mutmut_18` | same | `backend/tests/test_tax_reports.py::test_TX_07_supported_tax_year_endpoints[9998]` |
| `backend.tax.reports.x_annual__mutmut_167` | `backend.tax.reports.x_annual__mutmut_181` | `backend/tests/test_tax_reports.py::test_TX_07_long_term_carryover_consumes_only_unused_short_term_deduction[9-5-3000-0-3000]` |
| `backend.tax.reports.x_annual__mutmut_188` | `backend.tax.reports.x_annual__mutmut_202` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_189` | `backend.tax.reports.x_annual__mutmut_203` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_197` | `backend.tax.reports.x_annual__mutmut_211` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_198` | `backend.tax.reports.x_annual__mutmut_212` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_199` | `backend.tax.reports.x_annual__mutmut_213` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_200` | `backend.tax.reports.x_annual__mutmut_214` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_202` | `backend.tax.reports.x_annual__mutmut_216` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_213` | `backend.tax.reports.x_annual__mutmut_227` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_220` | `backend.tax.reports.x_annual__mutmut_234` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_221` | `backend.tax.reports.x_annual__mutmut_235` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_231` | `backend.tax.reports.x_annual__mutmut_245` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_232` | `backend.tax.reports.x_annual__mutmut_246` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_234` | `backend.tax.reports.x_annual__mutmut_248` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_235` | `backend.tax.reports.x_annual__mutmut_249` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_240` | `backend.tax.reports.x_annual__mutmut_254` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_242` | `backend.tax.reports.x_annual__mutmut_256` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_245` | `backend.tax.reports.x_annual__mutmut_259` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_252` | `backend.tax.reports.x_annual__mutmut_266` | `backend/tests/test_tax_reports.py::test_TX_08_empty_income_and_gains_do_not_invent_a_one_dollar_tax_base` |
| `backend.tax.reports.x_annual__mutmut_253` | `backend.tax.reports.x_annual__mutmut_267` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_254` | `backend.tax.reports.x_annual__mutmut_268` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_255` | `backend.tax.reports.x_annual__mutmut_269` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_262` | `backend.tax.reports.x_annual__mutmut_276` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_263` | `backend.tax.reports.x_annual__mutmut_277` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_270` | `backend.tax.reports.x_annual__mutmut_284` | `backend/tests/test_tax_reports.py::test_TX_08_empty_income_and_gains_do_not_invent_a_one_dollar_tax_base` |
| `backend.tax.reports.x_annual__mutmut_271` | `backend.tax.reports.x_annual__mutmut_285` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_272` | `backend.tax.reports.x_annual__mutmut_286` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_273` | `backend.tax.reports.x_annual__mutmut_287` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_29` | same | `backend/tests/test_tax_reports.py::test_TX_06_income_capacity_is_exact_and_never_silently_truncates[100000-True]` |
| `backend.tax.reports.x_annual__mutmut_280` | `backend.tax.reports.x_annual__mutmut_294` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_281` | `backend.tax.reports.x_annual__mutmut_295` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_3` | same | `backend/tests/test_tax_reports.py::test_TX_01_annual_paper_reporting_requires_explicit_simulation` |
| `backend.tax.reports.x_annual__mutmut_30` | same | `backend/tests/test_tax_reports.py::test_TX_06_income_capacity_is_exact_and_never_silently_truncates[100001-False]` |
| `backend.tax.reports.x_annual__mutmut_322` | `backend.tax.reports.x_annual__mutmut_336` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_334` | `backend.tax.reports.x_annual__mutmut_348` | `backend/tests/test_tax_reports.py::test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate` |
| `backend.tax.reports.x_annual__mutmut_336` | `backend.tax.reports.x_annual__mutmut_350` | `backend/tests/test_tax_reports.py::test_TX_05_export_discloses_open_or_complete_year_end_wash_window[day0-False]` |
| `backend.tax.reports.x_annual__mutmut_69` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_annual__mutmut_7` | same | `backend/tests/test_tax_reports.py::test_TX_01_annual_rejects_mutable_income_and_non_boolean_simulation` |
| `backend.tax.reports.x_annual__mutmut_75` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_annual__mutmut_83` | same | `backend/tests/test_tax_reports.py::test_TX_06_zero_fee_is_valid_income_evidence` |
| NEW | `backend.tax.reports.x_annual__mutmut_91` | `backend/tests/test_tax_reports.py::test_all_simulated_export_headers_rows_and_immutable_files` |
| NEW | `backend.tax.reports.x_annual__mutmut_92` | `backend/tests/test_tax_reports.py::test_all_simulated_export_headers_rows_and_immutable_files` |
| NEW | `backend.tax.reports.x_annual__mutmut_93` | `backend/tests/test_tax_reports.py::test_all_simulated_export_headers_rows_and_immutable_files` |
| NEW | `backend.tax.reports.x_annual__mutmut_94` | `backend/tests/test_tax_reports.py::test_all_simulated_export_headers_rows_and_immutable_files` |
| NEW | `backend.tax.reports.x_annual__mutmut_95` | `backend/tests/test_tax_reports.py::test_all_simulated_export_headers_rows_and_immutable_files` |
| NEW | `backend.tax.reports.x_annual__mutmut_96` | `backend/tests/test_tax_reports.py::test_TX_08_exact_rate_tail_cannot_round_a_positive_cent_remainder_down[79]` |
| NEW | `backend.tax.reports.x_annual__mutmut_98` | `backend/tests/test_tax_reports.py::test_all_simulated_export_headers_rows_and_immutable_files` |
| NEW | `backend.tax.reports.x_annual__mutmut_99` | `backend/tests/test_tax_reports.py::test_TX_08_all_rates_unavailable_still_reports_totals_without_an_estimate` |
| `backend.tax.reports.x_render_report__mutmut_100` | same | `backend/tests/test_tax_reports.py::test_TX_05_export_discloses_open_or_complete_year_end_wash_window[day1-True]` |
| `backend.tax.reports.x_render_report__mutmut_101` | same | `backend/tests/test_tax_reports.py::test_TX_05_export_discloses_open_or_complete_year_end_wash_window[day0-False]` |
| `backend.tax.reports.x_render_report__mutmut_102` | same | `backend/tests/test_tax_reports.py::test_TX_05_export_discloses_open_or_complete_year_end_wash_window[day0-False]` |
| `backend.tax.reports.x_render_report__mutmut_112` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_113` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_114` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_115` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_116` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_117` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_118` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_119` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_120` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_121` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_122` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_123` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_124` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_125` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_126` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_127` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_128` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_129` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_130` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_131` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_132` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_133` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_134` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_135` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_136` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_137` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_154` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_155` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_156` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_157` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_158` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_159` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_160` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_161` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_162` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_163` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_164` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_165` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_174` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_175` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_176` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_177` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_178` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_179` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_180` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_181` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_182` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_183` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_184` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_185` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_186` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_187` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_188` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_189` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_33` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_37` | same | `backend/tests/test_tax_reports.py::test_TX_01_live_exports_keep_estimate_label_and_multiple_owner_names` |
| `backend.tax.reports.x_render_report__mutmut_38` | same | `backend/tests/test_tax_reports.py::test_TX_01_live_exports_keep_estimate_label_and_multiple_owner_names` |
| `backend.tax.reports.x_render_report__mutmut_39` | same | `backend/tests/test_tax_reports.py::test_TX_01_live_exports_keep_estimate_label_and_multiple_owner_names` |
| `backend.tax.reports.x_render_report__mutmut_43` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_44` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_46` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_51` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_52` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_53` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_54` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_55` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_56` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_57` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_58` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_59` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_60` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_61` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_62` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_63` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_64` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_65` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_66` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_67` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_68` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_69` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_70` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_71` | same | `backend/tests/test_tax_reports.py::test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code[boxes0]` |
| `backend.tax.reports.x_render_report__mutmut_74` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_75` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_76` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_81` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_84` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_85` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_86` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_87` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_88` | same | `backend/tests/test_tax_reports.py::test_TX_01_07_export_selection_filters_account_and_year_in_every_table` |
| `backend.tax.reports.x_render_report__mutmut_96` | same | `backend/tests/test_tax_reports.py::test_TX_01_live_exports_keep_estimate_label_and_multiple_owner_names` |
| `backend.tax.reports.x_render_report__mutmut_97` | same | `backend/tests/test_tax_reports.py::test_TX_05_export_discloses_open_or_complete_year_end_wash_window[day1-True]` |
| `backend.tax.reports.x_render_report__mutmut_98` | same | `backend/tests/test_tax_reports.py::test_TX_05_export_discloses_open_or_complete_year_end_wash_window[day0-False]` |
| `backend.tax.reports.x_render_report__mutmut_99` | same | `backend/tests/test_tax_reports.py::test_TX_05_export_discloses_open_or_complete_year_end_wash_window[day1-True]` |
| `backend.tax.reports.x_save_report__mutmut_15` | same | `backend/tests/test_tax_reports.py::test_TX_07_export_payload_capacity_is_inclusive[33554433-False]` |
| `backend.tax.reports.x_save_report__mutmut_19` | same | `backend/tests/test_tax_reports.py::test_TX_07_export_payload_capacity_is_inclusive[33554433-False]` |
| `backend.tax.reports.x_save_report__mutmut_21` | same | `backend/tests/test_tax_reports.py::test_TX_07_export_payload_capacity_is_inclusive[33554432-True]` |
| `backend.tax.reports.x_save_report__mutmut_24` | same | `backend/tests/test_tax_reports.py::test_TX_07_export_payload_capacity_is_inclusive[33554433-False]` |
| `backend.tax.reports.x_save_report__mutmut_25` | same | `backend/tests/test_tax_reports.py::test_TX_07_export_payload_capacity_is_inclusive[33554433-False]` |
| `backend.tax.reports.x_save_report__mutmut_26` | same | `backend/tests/test_tax_reports.py::test_TX_07_export_payload_capacity_is_inclusive[33554433-False]` |
| `backend.tax.reports.x_save_report__mutmut_36` | same | `backend/tests/test_tax_reports.py::test_TX_10_publication_paths_bind_year_account_environment_and_content` |
| `backend.tax.reports.x_save_report__mutmut_42` | same | `backend/tests/test_tax_reports.py::test_TX_10_publication_paths_bind_year_account_environment_and_content` |
| `backend.tax.reports.x_save_report__mutmut_45` | same | `backend/tests/test_tax_reports.py::test_TX_10_publication_paths_bind_year_account_environment_and_content` |
| `backend.tax.reports.x_save_report__mutmut_54` | same | `backend/tests/test_tax_reports.py::test_TX_10_publication_paths_bind_year_account_environment_and_content` |
| `backend.tax.reports.x_save_report__mutmut_72` | same | `backend/tests/test_tax_reports.py::test_TX_10_corrupt_existing_export_is_refused_without_reading_its_large_tail` |

## Delivery condition

Commit locally as vincentgethub <325278731+vincentgethub@users.noreply.github.com>. After that commit, confirm every job in CI run 38640865007 has completed/timed out before a normal push, then stop. The final reply supplies the resulting commit hash and observed delivery status; no new CI result is claimed here.
