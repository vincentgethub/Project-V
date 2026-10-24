# Dispatch-only mutation measurement pilot

The owner approved one diagnostic dispatch after a single push of local commits
0ef6323, 90c567f and the pilot commit. This workflow cannot certify the mutation
gate. The normal 135-child CI workflow, mutation command, covering-test selector,
100% gate, kill qualification and 120-minute job limit are unchanged.

## Scope and reproducibility

The baseline is [run 39856462454](https://github.com/vincentgethub/Project-V/actions/runs/39856462454).
`config/mutation-pilot.json` records its 18 timed-out original parents and the
provenance hashes. They own 6,115 current mutants. The committed exception pool
contains the baseline's 5,162 exception-only IDs, representing 5,043 distinct
fingerprints. Its checksum normalizes CSV newlines to LF.

Seed: **39856462454**. Rank distinct fingerprints by
`sha256(str(seed) + ':' + fingerprint)`, breaking ties by fingerprint, and take
the first 100. Within a duplicate fingerprint choose the first native-ID
occurrence in numeric order; retain every occurrence in the sample manifest.
This is deterministic sampling, with no security exception for pseudo-randomness.

Fourteen samples overlap the 18-parent set; 86 are outside it. The union has
**6,201 distinct IDs**, executed once each, grouped only within their existing
original parent and cohort. Sort each parent's IDs by fingerprint and native ID,
then divide into diagnostic batches of at most 40. There are **190 nonempty
batches**, plus plan and reporting jobs: 192 expanded jobs, below 256.
These diagnostic batches do not change the normal partition.

Generate the same plan locally with:

```text
python -m scripts.mutation_pilot plan
```

`build/mutation-pilot/plan.json` records every selected ID, fingerprint, duplicate
occurrence, sample membership, inherited selector and batch. A second generation
must be byte-identical. Native execution remains Linux-only; nothing is installed
on the owner's PC to work around that limitation.

## Gate separation

Both workflow copies accept only `workflow_dispatch`. Pilot artifacts start with
`diagnostic-pilot-`; normal CI downloads only `mutation-result-*` from its own run.
Pilot files stay under `build/mutation-pilot`, never `build/mutation-results`.
Every pilot manifest names a `pilot-*` batch and explicitly says diagnostic-only.
Pilot reports omit the normal gate's required `passed`, `fingerprint_records`,
`run_exit` and `export_exit` fields. There is no call to the gate or aggregate.

Infrastructure tests exercise the normal aggregate with all pilot native statuses
set to killed, both as an extra file and renamed as a normal result: both fail.
The normal text gate also rejects pilot JSON, timing CSV and survivor Markdown.
The normal workflow's content hash is pinned in the separation test; its mirrored
copies must remain identical. A successful diagnostic workflow is only successful
data collection, never mutation-gate evidence.

## Instrumentation and reporting

Use the existing native status and per-mutant duration metadata. Pytest audit
records retain counts, phase timing and sanitized exception frames containing
only relative source file, function, line and origin. No messages, source lines,
locals, environment values or absolute paths are exported in frames.

Each batch uploads native-status JSON, timing CSV, test-selection mappings,
sanitized frames, every observed survivor, and every missing ID. Reporting lists
every planned mutant even when an entire batch has no export. Timeouts and
exception-only results remain unqualified under the unchanged kill rule.

Fresh measurements, sample classifications, main-CI results and a measured
partition proposal will be added after the single approved dispatch. Unmeasured
mutants must remain explicitly unmeasured; no historical kill or survivor result
is accepted as fresh evidence. Any partition remains a proposal, never applied.

Paper only. AUTO_LIVE stays locked; MANUAL_CSV stays disabled. No survivor-killing
tests, dependencies, production logic or safety settings change in this pilot.

## Local verification before the push

- Full offline suite: **6,737 passed**, 61 existing skips, four original perf
  deselections, zero failures; 2,486.05 seconds. Skip and deselection identities
  match 90c567f. Source hashes were unchanged throughout the completed run.
- Required coverage: **9,510 statements and 3,394 branches, 100%**, zero missing.
- Pilot cases: **14 added, zero removed**; 92 focused pilot/partition/evidence
  cases pass. The earlier instrumentation commit separately added 36 cases.
- Ruff lint and formatting pass all 473 files; strict types pass 432 sources.
- CI-scope Bandit: zero findings and zero scan errors. All five pre-commit hooks
  pass without suppressions. The two checksum identifiers use explicit `sha256:`
  prefixes, rather than bare strings that the secrets hook flags as ambiguous.
- Plan regenerated twice: identical bytes, SHA-256
  `12a8a6d7ed34bcb00bc0b424ac46d1a79f655e8b73b440bee5ac7fabe27d8bd2`.
- Both normal CI copies and both pilot workflow copies are byte-identical.
  Normal CI is unchanged from 90c567f; its normalized LF SHA-256 is
  `9824325fd123bec943c0b0f03a8a96762339dac4fce380a0b7182591ce3cc5d4`.
