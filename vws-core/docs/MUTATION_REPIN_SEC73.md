# Mutation re-pin for SEC-73 panic clock (Boss rulings Nov 18, 2026)

Source change: night1/sec73-panic-clock (d9ad62f, 6a22cc1) adds a test-only injectable panic clock and timer to
`AlpacaExecutor`; production keeps `loop.time` and `asyncio.timeout_at(deadline)`.

| Pin | Before | After |
|---|---|---|
| EXPECTED_TOTAL (`scripts/mutation_inventory.py`) | 15,467 | 15,471 |
| Fresh inventory digest | `a40f765c721166356c590037b8299b40eb7805deec9f3e9a027956d2bf878f14` | `c04858bad713b5d4d4682ce937cee92b22a7e460ca8cc3e19f8bd3cab12114e1` |
| Fingerprint map (`build/pass7/inventory-fingerprint-map.csv`) | MATCHED 15,456 / NEW 11 / GONE 1 | MATCHED 15,436 / NEW 35 / GONE 21, sha256 `75fd6a14774bf81993e41a1e8145f5a3ffddcadf11460ea0645eb78983260fa1` |
| Child partition (`config/mutation-shards.json`) | 135 children | 135 children, sha256 `d71b24451e24ff51d57da59165ae4db6444732d4a059a25804164f3a53f1789d` |
| Approved added IDs (`config/mutation-added-ids.json`) | none | 5 IDs, `sha256:08c0b800ff96b22eab6058721f56b621d0307bbbb7a2a82facd628197d9a7124` (re-pinned when the commit fields became `base_commit_url`/`source_commit_url`; was `233e865e…24c4`) |
| Pilot exception pool (`config/mutation-pilot-exception-pool.csv`, `pool_sha256` in `config/mutation-pilot.json`) | 5,162 rows, `f607469cfb39ed3b2006bf3fc51945c6564100e5fa697028512524cc214ad9e9` | 5,161 rows, `e98c6ebef4987587929a04752dd2f6f3b783c25636611a416cfc910463e5238e` |
| Pilot pool size (`scripts/mutation_pilot.py`) | 5162 | 5161 |
| Normal CI workflow sha256 (`.github/workflows/ci.yml`, both copies; step name now says 15471) | `9824325fd123bec943c0b0f03a8a96762339dac4fce380a0b7182591ce3cc5d4` | `c4228f37a7f03fd0b119bbaf86b1b2655f8b14be33bf719966d10f94c1ba5063` |

- ID diff vs 3cd644dc: only `backend/execution/alpaca_executor.py`, 7,190 -> 7,194 (+4/-0), all in edited functions
  (`__init__`, `_finalize_entry_cancellation`, `cancel_unfilled_entries`). No NEW/GONE mutant on an unchanged line.
- Inventory and map generated twice from independent copies: identical.
- Per-child partition proof vs the 3cd644dc split: 15,444 mutants present in both, **child moves: 0**; only
  executor-a-1-1 (+1 approved), executor-b-1-1 (+4 approved) and executor-b-8-1 (-1) change size.
- All 27 new or changed mutants (vs 3cd644dc content) were run with the approved executor configuration: 27/27 killed, all with reason "assertion" (scoped run, Nov 18 05:14 CT).
- The 100% gate (`run_mutation_shard.py`, `check_mutations.py`, `aggregate_mutations.py`) is unchanged.

## Pilot exception pool
- Pool IDs were remapped only through matched map rows, never by fingerprint lookup: pool ID -> the
  previous map's row (new_id equal to the pool ID, map `2215743e`) -> its baseline old_id -> the map
  `75fd6a14` row with that old_id -> its new_id. Every fingerprint is byte-identical. 74 IDs were renumbered
  (6 in `AlpacaExecutor.__init__`, 68 in `cancel_unfilled_entries`).
- One row was removed with no substitute: `AlpacaExecutor.cancel_unfilled_entries__mutmut_43`, fingerprint
  `sha256:e45691748426e121863232e436bd377927f3e83b54e95b46a2dddd0ecfe7ed51`. Its source line (the old
  one-line `deadline = asyncio.get_running_loop().time() + ...`) no longer exists, so map `75fd6a14` lists it as
  GONE. No current mutant carries that fingerprint.
- `baseline_run`, `seed`, `sample_size`, `parents` and `source_unqualified_kills_sha256` are unchanged. The
  100-fingerprint pilot sample is the same set of fingerprints, and the removed fingerprint was not in it.

## Known dependency: mutmut test order
mutmut 3.8.0 runs a mutant's covering tests fastest first (by recorded call-phase duration) and stops at
the first failure. The SEC-73 outcome tests therefore build and enter the order in fixture setup
(`entered`, `live_refusal` in `backend/tests/test_auto_safety.py`), so their timed call phase is
0.0001-0.24 s and they run before older tests that would only crash on the same mutants. If those
fixtures are moved into the test body, or mutmut changes its ordering, crash-first ordering can return
and the assertion-only gate would then reject these mutants.

## Pilot counts
Mutant changes by source job in `config/mutation-shards.json` (3cd644dc -> this commit) for the three
SEC-73 functions:

| Source job | Function | Before | After | Pilot parent |
|---|---|---|---|---|
| executor-a-1 | `__init__` | 18 | 19 | yes |
| executor-b-4 | `_finalize_entry_cancellation` | 174 | 175 | yes |
| executor-b-4 | `cancel_unfilled_entries` | 5 | 4 | yes |
| executor-b-1 | `cancel_unfilled_entries` | 6 | 10 | no |
| executor-b-8 | `cancel_unfilled_entries` | 7 | 6 | no |

Net change for pilot parents: +1 (a-1) +1 -1 (b-4) = +1. Parent mutants go 6,115 -> 6,116 and assigned
IDs go 6,201 -> 6,202 (6,116 + 86 samples outside the parents). Batches stay at 190 and samples outside
the parents stay at 86.
