# Mutation instrumentation — local validation, October 23, 2026

This change retains evidence; it changes no mutation verdict, selector, threshold,
gate, timeout, partition or equivalent allowance. No push or CI dispatch occurs.
It is a separate local change from `0ef6323` (`docs: fix example formatting`).
Paper only; AUTO_LIVE remains locked; MANUAL_CSV remains disabled.

## Instrumentation

- `scripts/run_mutation_shard.py` writes the preflight identity before starting
  mutmut, so cancellation cannot erase the association with assigned fingerprints.
- `scripts/mutation_audit.py` records monotonic pytest-session duration, UTC start,
  per-phase time, collection count and sanitized code locations for call, setup,
  collection/import and internal exceptions. It retains chained exception locations.
  Frames contain only relative code file, function, line and origin. It never
  serializes locals, environment, exception messages, source lines or absolute paths.
  Each record belongs to one pytest invocation; no test cache is persisted or reused.
  Locations are relative to the running repository/mutant root. Line numbers and
  mangled function names are runtime locations, not reconstructed original lines.
- `scripts/mutation_evidence.py` reads native `.meta` exit codes, actual mutant
  durations, estimated test durations and the native function-to-test mapping after
  execution, including after cancellation. Actual native duration is distinct from
  pytest duration. Unknown timings remain null, not zero. Median and nearest-rank
  p95 use only available native durations. Every assigned ID remains visible.
- Exports contain `native-status.json`, `timings.csv`, `exception-frames.json`,
  `test-selection.json`, `ALL_SURVIVORS.md`, `MISSING_IDS.csv` and an identity manifest.
  Partial native observations are labeled incomplete and cannot satisfy the gate.
  Fingerprints, child, original parent and cohort are retained and checked.
- Both CI workflow copies add one always-run diagnostic export step and artifact
  paths. Child evidence remains under its own directory, preventing merge collisions.
  The aggregate publishes the complete survivor list and every missing ID. It still
  waits for every existing child and fails for every previously disallowed result.

AST comparison proves the existing `audit_results()` kill decision is unchanged.
The aggregate gate function is unchanged apart from its diagnostic output call.
Parsed workflow comparison proves the only changes are diagnostic export/publication.
The 135 jobs, native command, 120-minute limit, selectors and six tax approvals stay.
Both workflow copies are byte-identical, SHA256:
`9824325fd123bec943c0b0f03a8a96762339dac4fce380a0b7182591ce3cc5d4`
for their Git-normalized LF bytes. The two local CRLF copies are also byte-identical,
SHA256 `7d35b1d72280028d86725a176fe9386de4a6d5bd9a78164543444de9b03f94d1`.

## Local tests and redaction

There are **36 new infrastructure tests and zero removed tests**. No survivor-killing
test was added, and no mutation-selection test file was changed. The focused set
passes **78 infrastructure tests**, and the final combined infrastructure/GD-07
set passes **415 tests**. It covers interrupted startup, native timing/status preservation,
unknown data, missing IDs, stale identity/ownership rejection, exact survivor exports,
diagnostic attribution without kill qualification, real pytest call/setup/import/
internal failures, redaction, and unchanged workflow/gate behavior.

Four real pytest probes inject a synthetic private value into exception messages
and environment. Their retained audit files contain no injected value. The grep
proof uses this pattern without printing matching content:

```text
rg --files-with-matches --ignore-case '(?i)(api[_-]?key|token|password|authorization)\s*[:=]|FRAME_CANARY_VALUE' build/pass7/instrumentation/redaction-proof -g '*.json'
```

Result: **exit 1, zero matching files**. Frame keys are exactly file/function/line/
origin. Untrusted external filenames are redacted. Evidence:
`build/pass7/instrumentation/redaction-grep-proof.json`.
An additional scan for GitHub, PyPI, AWS and bearer-token shapes also finds zero
matching files; its exact command and exit status are retained in that proof.

Strict typing passes all **430 source files**. Ruff lint and the final formatter
pass. Full-suite results are recorded below.

## Requested native child proof: blocked by this host

The selected child is `risk-sizing-1-1`, the only child of `risk-sizing-1`, with
**363 assigned IDs**. Windows has no WSL installation, Docker or Podman. Python
supports only `spawn`. Pinned mutmut explicitly exits on Windows at
`mutmut/__main__.py:15–19`, requesting WSL, before running any mutant. The same
entry guard prevents every alternative child from running locally.

The actual CI preflight, native wrapper and diagnostic command were exercised in
an isolated copy of tracked public project files, plus the two new source files.
No real dotenv, keys, setup state or ledger was copied. Preflight passed for all
**15,467 IDs / 135 jobs**. The native wrapper then failed at the Windows entry
guard. Its gate remained FAIL. The exporter succeeded and listed **all 363 IDs as
missing**, with fingerprints, null native timings and zero invented survivors.

| Same child | Historical CI 39856462454 | Local instrumented attempt |
|---|---:|---:|
| Assigned IDs | 363 | 363 |
| Last native processed counter | 332 | 0; native startup refused |
| Finished pytest audits | 333 | 0; native startup refused |
| Wall minutes | 120.417 | approximately 3.64 for preflight/wrapper/export; no mutant execution |
| Exception-only mutant observations | 183; native export absent | unavailable; one child-level platform refusal |
| Native median / p95 seconds | not retained | unavailable |
| Slowest 10 native mutant durations | not retained | unavailable |
| Selected tests, median / max | 26 / 485, observed finished sessions | unavailable for a fresh native run |

The local stages took 109.549 seconds for preflight, 108.344 for the wrapper's
preflight plus startup refusal, and 0.236 for export. These are **not throughput
improvement measurements**. Zero executed mutants is not a successful kill pass.

Historical native stats collected 2,293 tests; the clean selected run used 1,228.
Across the 333 finished mutant sessions, collection ranged from 7 to 485 tests,
median 26. **Covering-test selection was working in those observed sessions;
each mutant did not run the whole suite.** This is historical evidence, not fresh
native confirmation. New instrumentation also retains the exact mapping for review.

No fresh child exception-only results exist to split between runner and mutated
production code, so the requested three actual samples per class cannot be supplied.
All 183 historical exception observations lack recorded traceback origins; their
origin remains unverified. Synthetic attribution tests are not substituted for
real child samples. Production-origin exceptions remain unqualified under the
unchanged kill rule, just like runner exceptions and timeouts.

For the outstanding proof, use a fresh Linux checkout with the existing pinned,
hash-installed development dependencies and no existing `mutants/` or child audit
directory. From `vws-core`, run this child once:

```bash
export VWS_MUTATION_SHARD=risk-sizing-1-1
export RUNNER_TEMP="$(mktemp -d)"
python -m scripts.mutation_inventory
python -m scripts.run_mutation_shard
```

Preserve the native wrapper's exit status. After it finishes, run the independent
diagnostic command, including when the unchanged gate fails:

```bash
python -m scripts.mutation_evidence
```

Its successful export never replaces or overrides the native gate result. No Linux
run, environment installation or CI dispatch was performed here.

## The 106 historically failed children

These exclude the 29 canceled job-timeout children. All 106 have complete exports;
every native run and export returned zero. There was no observed export error.

| First blocking check (timeout takes priority) | Children |
|---|---:|
| Unlisted survivors, no timeout; also contains unqualified exceptions | 99 |
| Native mutant timeout, also with exceptions and survivors | 1 (`executor-b-7-2`) |
| Unqualified exception-evidence gate only; no survivors or timeout | 6 |
| Total | 106 |

In the literal sense, there are **zero survivor-only failures**: all 106 contain
unqualified exception evidence. There are **zero actual runner/export failures**.
Excluding the timeout child leaves 105 exception-evidence failures, 99 also with
survivors and six without. The requested three categories are not exhaustive unless
exception-evidence failures are relabeled infrastructure errors. Their traceback
origin was not retained, so that relabeling would be unsupported. Individual child
counts and links are in `build/pass7/instrumentation/historical-106-failures.csv`.

A local re-export of the historical artifacts produces **15,467 assigned rows,
1,155 survivor entries and 4,298 missing IDs**, with zero omissions. The six approved
tax equivalents remain within the survivor list. This proves exporter completeness;
it does not turn historical observations into fresh native results.

## Split estimate

No new per-mutant native timings were obtainable, so a fresh measured cost-weighted
split cannot be justified. The earlier **221-child / approximately 90-minute worst
child** arithmetic forecast remains an uncertain historical estimate, not a new
measurement or a validated bound. It would expand to 224 jobs, below 256; its
proposal-only proof preserves original parent/cohort ownership and deterministic
fingerprint/appearance ordering. **No partition is changed.** A future measurement-
based proposal must retain exactly-once ownership and require every child in the
aggregate. Linux execution is needed before revising the estimate from fresh data.

## Final local verification

The first completed full suite reached 100% coverage but failed GD-07 because the
new privacy test referenced `exec()` and `compile()`. The fixture now supplies
structured traceback metadata instead; all original privacy assertions remain.
The four real pytest exception probes remain in place. No guard, allowance or
production behavior was changed. The unchanged authored-source scan and all 415
focused/source-guard tests pass. The complete full-suite run on the final source
passes **6,723 tests**, with **61 existing skips** and **four original perf
deselections**. There are no failures, no new deselections and no removed cases.
Required coverage is **100% statements and branches**: **9,510 / 9,510 statements**
and **3,394 / 3,394 branches**, with zero missing or partial branches.
The source hashes are identical before and after the suite.

The completed suite took **2440.40 seconds**. All five pre-commit checks pass
(Ruff lint/format, GD-07, strict types and secrets). Formatter: **470 files already
formatted**. The pre-commit full-history gitleaks scan found zero leaks across
52 commits; the post-commit scan is reported separately in the final response.
The failed development run is retained as `pre-GD07-fix-normal.log`; it is never
counted as a passing full suite. Fresh native child timings, actual runner versus
production samples, and a fresh measured split remain unverified because Linux
is unavailable. No push or CI dispatch occurred.
