# Mutation Pass 6 — approved Decimal context and physical-send CRO recheck

**Verified October 20:** the owner approved `ChiefRiskOfficer.evaluate()`,
`max_allowed_qty()` and one private Decimal-context helper, plus the final CRO
recheck inside `AlpacaExecutor.enter()` and its physical guard. Both risk methods
now own precision, rounding, exponent limits and trap defaults without changing
risk formulas, limits or the caller context. An arithmetic-fault sizing probe
returns zero with its fault reason and ends the search. The 7,296-case matrix
passes with zero discrepancies, zero oversizing and monotonic eligibility.

The original `Emin=0` assignment is in the enabled test
`test_CRO_03_advisory_keeps_an_already_approved_quantity_under_subnormal_traps`
in `backend/tests/test_risk_cro.py`; the diagnostic script repeats it. There is
no production `Emin=0` assignment. The owned context explicitly uses the ordinary
Decimal baseline: precision 28 (with existing local increases), HALF_EVEN,
Emin -999999, Emax 999999 and InvalidOperation/DivisionByZero/Overflow traps.
Whole positive share counts still truncate downward; no risk setting changes.

The early full CRO check remains. Each physical entry leg receives fresh inputs
after the other awaited broker work. Its exact request quantity, symbol, limit
and stop then pass full CRO in the synchronous submit guard. The worker runs
that guard after token admission, and the production HTTP transport runs it
again immediately before `Session.request`. No await or separate I/O follows a
successful final check before the submit itself. A veto retains the existing
no-send/refusal audit path, including the blocking rule IDs.

An unavoidable gap remains between the last client-side check and broker receipt:
time and external conditions can change while a request is serialized, sent or
queued at the broker. A client cannot make its local ledger/state and a remote
broker's receipt one atomic transaction. The final guard minimizes that gap;
it cannot promise that no condition changes in transit. No new broker API or
replacement-order capability is introduced. The final inventory, both full
offline suites, required 100% coverage and pre-commit checks pass. Native Linux
mutation outcomes remain pending at this delivery commit.

Change baseline: `2d0f9c6ca10ed1894445afb5c771ee95fd691a3c`. All previously approved build work is retained in the single delivery commit. The latest inventory update is **15,457 IDs across the same 63 jobs**, 157 additions and no retirements relative to 15,300. The CI preflight passes, and no retained ID changes owner. See [every added/retired ID, the six-line script diff and ownership proof](MUTATION_PASS6_INVENTORY.md). The final delivery handoff records the commit, one normal push, post-commit history scan and completed native CI; no second push updates this snapshot.

## Current verification, October 20

The untouched 2d0f9c6 snapshot fails the corrected eight-share expectation; the
working tree passes it. The 7,296-case matrix has zero discrepancies and zero
oversizing. Explicit arithmetic faults and incomplete evidence return zero with
a fault reason and no further probes. The caller context is unchanged.

| Offline run | Passed | Skipped | Perf-only deselected | Statement / branch coverage | Wall |
|---|---:|---:|---:|---|---:|
| Normal | 6,607 | 61 | 4 | 100% / 100% | 2,605.61s |
| Random, seed 20261020 | 6,607 | 61 | 4 | 100% / 100% | 3,665.24s |

Both cover **9,503/9,503 required statements and 3,386/3,386 branches**;
executor alone covers **1,864/1,864 statements and 776/776 branches**.
There are zero missing statements or branches. Both source fingerprints stayed
unchanged and match each other. The case multisets are identical, their orders
differ, and only the four original perf cases are deselected. No new pragma,
exclusion or omit rule was added. The normal process and random process exit 0.

The six timed CRO blockers each produce zero fake-broker orders; a clear recheck
sends one order. The ordering test proves no await in the synchronous handoff,
and the runtime SQL hook proves no database I/O follows final pure approval.
Earlier durable observations occur before that final evaluation. The original
early full check remains in place. All fake executions use paper only.

The 47 original risk survivors now have **20 local CST test kills and 27 local
survivors**. The additional serialization tests distinguish Decimal policy/audit
imports from JSON export formatting. Every remaining proposal has its own ID,
exact diff and reason in MUTATION_PASS6_EQUIVALENT_PROPOSALS.md. None is allowed;
the gate must fail for every unlisted survivor. Native Linux results are pending.
Focused executor diagnostics completed 316 executor-a and 255 executor-b
five-case probes before stopping to free local suite resources. They have
100 and 108 failed test calls respectively; 61 and two usage-error results are
not kills. Unattempted/interrupted probes have no result. These limited CST
probes are diagnostics, never a native gate pass or complete survivor count.

Full-history gitleaks before commit: 48 commits, 59.55 MB, zero findings. Whole
strict typing passes for 425 authored sources; Ruff lint/format, the actual
repository-wide GD-07 scan and every pre-commit hook pass. An earlier partial
random run found prohibited test-only call/reflection patterns; those fixtures
now use the existing fake broker path and explicit attributes. GD-07 and its
allowlist are unchanged. The fresh complete runs above supersede partial logs.
The post-commit history scan and all 63 native jobs are delivery obligations;
their actual results are recorded in the final handoff, never inferred from CST.

Fresh collection selects **6,668 cases** against the Pass 5 baseline of 5,779:
**889 added, zero removed behaviors**. Four old configuration parameter IDs
only change ordinal suffixes; their test source and original bound tuples are
unchanged. Exactly the four original perf-marked cases are deselected.
The six timed blockers assert both the exact refusal audit and log; the
CRO-01 case latches HALT during the last durable observation, after the earlier
guard checks. SQL-hook checks cover both persisted marks and the supported
no-marks path. These are fresh focused passes, not substituted full-suite gates.

The single deleted line in the Pass 5 `test_auto_safety.py` diff was its import:

```diff
-from backend.core.errors import ExecutionDisabledError, ReconciliationError
+from backend.core.errors import ExecutionDisabledError, ProviderError, ReconciliationError
```

It adds the exact provider-error type used by new refusal tests; no assertion
was removed in that commit. The retained planted-schema proof passes again on
the current source: clean/planted/restored exits **0 / 1 / 0**, same interpreter.
Immutable calendar/schema caches remain in memory per pytest invocation.

## Earlier local diagnostics (historical)

The fresh complete normal-order offline suite passed **6,090 tests, 61 skips and four original perf-only deselections** in 2,355.55 seconds. All required CI targets reached **100% statement/branch coverage**: 9,463 statements and 3,368 branches; executor alone covered **1,838/1,838 statements and 762/762 branches**. Backend/scripts fingerprints stayed unchanged (`step1-normal-evidence.json`). This supersedes the earlier combined diagnostic. No pragma or exclusion was added. Final normal/random suites after the kill passes, post-commit full-history gitleaks and Linux CI remain pending.

The risk/compliance additions pass **420 focused tests**, lint and strict typing. Fresh-process local CST diagnostics leave all 419 non-sizing baseline survivors alive before these additions. The twelve sizing replays after the additions fail all four former timeout IDs (32, 35, 38, 67) and four exact-error-message mutants (69–72); four remain under individual review. The 64-evaluation advisory bound is call-local and test-local, and retains the legacy bound and message. No risk production source, selector, CI timeout or gate changed. Local diagnostics are not native mutation results. Two individual `typing.cast` proposals are recorded in [the proposal report](MUTATION_PASS6_EQUIVALENT_PROPOSALS.md); neither is allowed.

Additional same-family protection bug: the old `_cancel_sells` precheck stopped at the first open sell and could cancel existing protection before finding a later unresolved sell intent. The new restart regression fails before the fix (one DELETE, protection removed) and passes after it (zero DELETEs, old stop live, durable HALT, failed/open-blocking journal, no POST). The precheck now validates every candidate before cancellation; it retains fresh reads at each actual cancellation. Production changes remain inside `_cancel_sells` and its private helper. Evidence: `repair-unresolved-later-intent-before.log` and `repair-unresolved-later-intent-after.log` (10 related checks pass).

Two additional integrity predicates are retained as pure private helpers, with direct pass/raise tests: pre-extraction line 2739, `An unknown sell outcome prevents a conflicting stop or replacement`, in `_require_known_sell_outcome`; and pre-extraction line 3711, `EX-05: durable repair cannot be repeated`, in `_require_active_durable_repair`. The latter follows an earlier live-stop fast return; HALT and alert handling stay in `_raise_repair` unchanged. All ten extracted guards preserve their condition, exception and message. No pragma, exclusion, allowance, lifecycle transition or workflow was added.

The first broad, source-stable executor diagnostic passed **763 tests** and failed its 100% coverage gate at **96.64%**; focused checks then closed its gaps. Newly verified cases include late terminal observations waiting for canonical fill capture, a repair starting after an entry intent vetoing physical submission, approved pre-journal restart handling, exact remaining-share protection after an exit guard refusal, repeated hard-event suppression, late generated-child binding, unchanged EMA protection when no exit signal exists, bounded repeated pending/unknown panic, and a fresh orphan-cleanup position mismatch. Lint/format and whole-source strict typing pass; GD-07 is **337 passed** without policy or allowlist changes. Latest tracked-file collection is **370 added, zero removed**; two automatic panic-timeout boundary cases bring the semantic whole-repository increase to **372**. Four old config parameter IDs only changed automatic ordinal suffixes; their test bodies and bound tuples are unchanged. Exactly the original four perf cases are deselected.

## October 18 continuation checks

Both additional partial-fill timings pass: before physical submission and during the bound broker-order confirmation read. The repair ends with two ledger-held = two broker-held = two stop-protected shares; the remaining BUY is canceled through the existing finalizer. The confirmation test now hooks broker order-ID reads, which the production confirmation path uses, rather than client-ID lookup. No production change was required for this test correction.

Six new restart/control cases pass: a process interruption after live-stop confirmation resumes without another POST (new candidate or restored old level, in monitor and reconcile); closing the completed journal again adds zero ledger rows; and host RESUME followed by either cycle HALTs when an open journal has lost its durable block. Together with the partial-fill timings: **8 passed** (`repair-confirmation-restart.log`).

The older held-exit/stop-raise diagnostic returned 20 passes and one obsolete reject-once expectation. The approved journaled replacement contract explicitly restores the old stop on new-stop refusal and releases its own pause after confirmation. Its expected price is therefore the old stop and its state is RUNNING after successful restoration. Broker POST counts, REPAIRED audit status, no duplicate on the next cycle, and ledger verification remain asserted. The original standalone-stop/OCO assertion is unchanged. All seven recovery variants now pass (`raise-recovery-approved-contract.log`).

Further focused checks pass: seven cancellation-authority/audit-context/zero-fill cases, two persisted-refusal/ambiguity no-repost cases, two physical-guard/client-ID collision cases, the stale-quote restoration case, the short-OCO protection case, and five unresolved-worker/live-order idempotence cases. The source guard caught dynamic method dispatch in two new tests; these now use explicit monitor/reconcile calls. The unchanged full GD-07 file passes **337** cases again. Latest collection: **323 added, zero removed** (524 versus 201 in the tracked files). This is a collection delta, not a final full-suite result. Lint/format and strict typing pass for the latest test sources.

The current AST comparison against the retained pre-journal source shows changes only to `_cancel_sells`, `_ensure_stop`, `_protect_and_exit`, `_raise_repair`, `_raise_step`, `enter`, `monitor`, and `reconcile`; no changed existing function lies outside the approved boundary. Workflow copies are byte-identical and unchanged; HTTP transport, execution policy and tax-equivalent list are unchanged. Evidence: `build/pass6/current-scope-proof.json`.

Whole-repository collection now selects **6,110** non-performance cases versus 5,779 in the Pass 5 XML: **331 additional cases and zero removed behaviors**. Raw node-ID comparison reports 335 additions/four removals solely because adding `panic_cancel_timeout_seconds` to the integer-bound table shifts the automatic `bounds19/20` suffixes of four unchanged paper/realtime-session cases. AST comparison proves every pre-existing integer-bound tuple unchanged and `test_config_safety.py` has no diff. The two new timeout-bound cases plus 329 tracked executor/migration additions account for the full increase. All four deselections are the original perf-marked tests, with no new deselection (`all-case-count.json`). No test was removed or disabled.

Two flat/sibling journal cases and four account-position disagreement cases also pass: flat recovery sends no additional sell and leaves the sibling protected; discrepant broker holdings HALT before any cancellation/POST. These are focused checks, not the final full-suite result.

A stable-source executor coverage run over all 24 supporting test files is in progress (`coverage-current.log`, source snapshot `coverage-current-source.py`). It is diagnostic, not a claimed full-suite pass. Final inventory generation and risk/executor kill passes remain pending executor 100% coverage. Full-history gitleaks precheck: **48 commits, no leaks**, with redaction enabled; it must be repeated after the authorized commit so the new commit is included. No Pass 6 commit, push or CI run.

## Current verification notes — protection/flatten recovery

The first full offline run is a diagnostic of the source loaded before the later fixes below. It retains the full 100% gate and only the normal four perf deselections. Its failures are not a passing suite; current source has since changed, and its executor coverage cannot certify the current source. A separately pinned current-source executor diagnostic is running (`current-scoped-source.py`, `current-scoped.log`, isolated `current-scoped.coverage`). That diagnostic temporarily excludes only the unchanged, slow 1,001-record history case; the final full normal/random suites must include it. No permanent selector changed.

Additional fixes remain inside the nine functions/private helpers:

- Approved AX-29/30 flatten windows are now journaled in `_cancel_sells` before removing stop coverage. Entries remain vetoed while the bound DAY exit works. Resume verifies the active cycle, exact bound exit and remaining held quantity. Once captured flat, the journal closes. This preserves the existing flatten exception without exempting arbitrary unprotected positions. All **26 existing exit cases** (excluding the slow inventory-bound diagnostic case) pass unchanged; **two added journal lifecycle/restart cases** also pass. `_exit_step` is unchanged.
- A cancellation proved to be a no-op now returns before demanding orphan/replacement authorization. This covers never-submitted split siblings and already-terminal exit legs; unknown sell outcomes still refuse. The five split-veto/panic-inventory regressions pass without changing their existing expected outcomes.
- If a journal's stop approval already has a canonical STOP_MOVED event, later recovery uses the current audited stop and fresh IDs rather than trying to restore the superseded lower level. Prior journal rows remain unchanged; the updated context is another append-only record. Closed-journal completion is idempotent. No ledger validation was loosened and no LedgerIntegrityError was caught to continue. The original paper publisher assertions are unchanged and pass.
- Before any journaled repair cancellation/submit, `_repair_position` verifies complete open broker orders against bound managed IDs. A new foreign-sell/open-journal regression fails before this fix (an extra stop is sent), then passes with no new POST and no cancellation, durable HALT, an outstanding journal and exact refusal context. Combined foreign-sell, publisher and price checks: **16 passed**.

Fixture clarifications preserve each tested scenario: monitor/downgrade cases that claim an existing verified stop now establish it through the real `_ensure_stop` before injecting the separate fault. Interrupted-repair cases explicitly open their durable journal before the fault. The inactive panic case now requires both replacement and old-level restoration attempts (three total POSTs including the entry), retaining exact error/HALT/held-quantity assertions; the original standalone-stop contract assertion remains unchanged. Focused monitor/publisher result **17 passed**; known repair/downgrade **8 passed**; inactive stop **3 passed**. These focused results do not replace either final full-suite run.

Read-only risk preparation mapped all **427 survivors and four timeout IDs** to exact original/mutated nodes (`risk-survivor-node-diffs.json`); zero unmapped. No risk tests, native after-counts, new equivalent proposals, inventory regeneration, partition assignments or gates have changed at this point. No commit, push or CI run.

## Current approved build — clarified nine-function boundary

The owner clarified that the eight original functions plus enter(), and private helpers they call, remain approved. `_raise_repair` needs no further boundary approval. The two repair issues below are now corrected; the old STOP narratives are historical evidence.

Verified pre-Pass-6 contract from `2d0f9c6`, executor lines 2690–2697:

```python
level = plan.old_stop
try:
    inputs = await self._fresh_exit_inputs(entry)
    if plan.new_stop < inputs.market.last_price:
        level = plan.new_stop
except ExecutionDisabledError:
    # Protect at the proved old level when a fresh quote is unavailable.
    pass
```

The journaled repair restores this strict comparison, with no new buffer or threshold. At latest price 103.12 or below the proposed 103.12 raise, it selects the old 99.12 stop; only a price strictly above 103.12 permits the raise. The stop-attempt helper obtains fresh evidence again before submitting: a known stop level at/above the fresh price is refused, and an invalid raise routes to old-level restoration. Failure to restore leaves the journal failed, durably HALTs, sends an urgent notice and raises a typed error. An unavailable fresh quote retains the original old-level recovery policy.

The failing standalone assertion was `assert repair["type"] == "stop" and repair["stop_price"] == f"{level:.2f}"`. The test was correct: baseline `_raise_repair` called `_repair_stop(..., repair=True, repair_level=level)`, and baseline `_repair_stop:1659` omitted the target when repair=True. Journaled `_raise_repair` now uses a standalone GTC stop, preserves its `vws-m-<raise_id>-r` identity for the selected repair, and confirms coverage before closing the journal. It does not use the initial raise's OCO shape. The original standalone assertion was not changed. A separately confirmed refused repair may restore the old stop using a distinct unused client ID; no failed/ambiguous ID is resubmitted. Initial `_raise_step` retains its OCO contract.

Latest focused result: **15 passed**, comprising six new price/failure cases, six existing journaled raise success/refusal cases, and the three previously failing contract cases (`build/pass6/restored-price-matrix-verified.log`). Each new case checks exact standalone request fields, durable failure state and exact alert/error where applicable, as well as broker/ledger/protection equality outside the journaled repair window. The earlier six-case test now expects the repair's journal to close after live confirmation, as explicitly required; its canonical STOP_MOVED check remains. The original standalone-stop assertion remains unchanged and passes.

Independent entry-veto checks remain **12 passed**, and GD-07 remains **337 passed**, with its source and allowlist unchanged. Whole-repository Ruff check/format passes (455 formatted files checked); strict authored-source typing passes (425 files). The full offline coverage run is active under the unchanged 100% gate. No current full-suite coverage pass, final inventory regeneration, partition proof, kill-pass after-count, final gitleaks, commit, push or CI completion is claimed yet. No workflow change, fifth transition, threshold, timeout, selector or equivalent allowance has been added. AUTO_LIVE remains locked; MANUAL_CSV disabled; all broker tests are offline paper fakes.

## Previous fresh-price stop — resolved within the clarified boundary

The approved independent entry veto and GD-07 compliance change are retained and pass their focused checks. The broader executor run exposed a protection regression in the earlier uncommitted journaled-repair implementation. The owner's latest instruction is to STOP if anything beyond enter() needs changing. No corrective production change was made after this finding.

Existing enabled test `test_EX_05_repair_respects_unresolved_work_durable_identity_and_price[low_price-harness0]` fails: after an approved raise, the fresh market price is lowered to the planned new stop, **103.12**. `_raise_repair` returns/confirms **103.12**, while the required safe recovery is the old **99.12** level. The pre-journal method saved in `build/pass6/executor-expanded-source.py:2922` obtained fresh exit inputs, kept `plan.old_stop` by default, and chose `plan.new_stop` only when it was below the fresh last price. The journaled replacement bypassed that decision: `_raise_repair:3519` hands the approval to `_journaled_stop_repair`, and `_repair_stop_attempt:2196` validates quote age but does not revalidate the fresh price before selecting the raised level. This regression is in our retained uncommitted implementation; it is not caused by the new independent entry veto.

Smallest proposed correction: restore the fresh-price selection in `_raise_repair` / its journaled stop helper so a no-longer-valid raise uses the old proved level. Preserve the journal, entry block, live-confirmation proof, fallback, failure HALT and canonical STOP_MOVED audit. No PATCH, new transition, allowance, gate or configuration change is needed. **Not applied:** it is a behavior change beyond the newly authorized enter-only veto and helper-compliance rename.

Focused reproduction:

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest backend/tests/test_auto_safety.py -k repair_respects_unresolved --no-cov -q
```

Result: **2 failed, 1 passed** in 8.21 seconds (`build/pass6/entry-veto-repair-compatibility.log`). The low-price failure above is the safety blocker. The other failure, `inactive_previous`, asserts a standalone STOP request while the new journal path creates an OCO with a stop child; that mismatch remains unresolved, and is not claimed as another proved safety bug. The pending-worker refusal still passes. The separate pending-cancel timeout check passes; the first progress update had attributed the two broad-run failure dots to the wrong adjacent cases before isolation identified these exact nodes.

The local broader executor/coverage diagnostic was stopped at this explicit boundary stop; its partial log (`build/pass6/entry-veto-executor.log`) is not a full-suite result and no current coverage percentage is certified. No CI run was canceled: none was started. Final normal/random suites, current 100% coverage, final inventory/partition proof, full-history gitleaks, risk/executor mutation kill passes, commit, push and CI remain unfinished. HEAD is still `2d0f9c6ca10ed1894445afb5c771ee95fd691a3c`.

Latest collected delta is **290 added cases, zero removed** (201 baseline / 491 current across the five executor files and migration tests). The final focused veto check passes **12 cases** with exact type/message assertions and refusal-only row counts; complete GD-07 passes **337 cases**, with no rule or allowlist change. Ruff and strict typing pass for the latest entry-veto edits. Both workflow copies remain byte-identical and unchanged. No inventory regeneration or additional equivalent allowance occurred. All uncommitted work remains available. AUTO_LIVE stays locked; MANUAL_CSV disabled; every broker in these checks is an offline paper fake.

## Approved entry-veto continuation — completed focused checks

The owner approved `enter()` only for an independent account protection veto, plus making the flagged private stop helper comply with unchanged GD-07. No other existing function was added to the correction boundary.

`enter()` now refuses before building requests if any OPEN/FAILED repair journal exists, any symbol has positive held shares without an active stop, or held shares exceed stop-protected shares. It checks the union of fresh broker holdings and captured ledger holdings; active broker stop IDs are deduplicated, and held/suspended/pending-cancel legs do not cover positive holdings. Zero-fill BUYs with held contingent legs remain valid. Read-only broker snapshots are refreshed before request construction and each physical submission; the journal/captured-holding veto is repeated in serialized admission and the physical worker guard. This veto is independent of ordinary PAUSE/HALT, so host RESUME does not erase the repair obligation. Refusal uses existing AUTO_ENTRY_BLOCKED with an exact reason and creates no order/intent. RESUME itself is unchanged.

GD-07's existing `_prohibited_member` combines `words & MONEY_ENDPOINT_WORDS` with `words & TRANSFER_CREATION_WORDS`; `journal` and `submit` made `_submit_journal_stop` look like a money-movement operation. Its two calls were `await self._submit_journal_stop(entry, journal, restore=restore)` and `await self._submit_journal_stop(entry, journal, restore=True)`. The helper is now named `_repair_stop_attempt`; it still routes all order sends through the pre-existing guarded `_submit(instruction, request, guard=guard)` path. There is no new raw broker submission, guard change or allowlist entry. The complete GD-07 file passes **337 tests**.

The original host-RESUME regression fails before this fix (new BUY incorrectly submitted) and passes now. Latest focused check: **12 passed**, covering that regression, three retained repair-control cases, and eight separate journal/short-stop/no-stop/closed-healthy cases across normal and restarted executors. Refusal adds exactly one existing audit row, no execution intent, and zero new broker POSTs. After restart a journal remains an independent veto following RESUME; closing it with confirmed coverage allows the new BUY. Ruff and strict typing pass. The broader diagnostic subsequently reached the fresh-price boundary stop above; no full-suite/100% coverage, final inventory, kill-pass, gitleaks, commit, push or CI completion is claimed.

The following previous stop narrative is historical evidence, not the current status.

## Previous boundary stop — resolved by owner-approved enter() veto

The approved cancel-then-submit repair is implemented inside the eight-function boundary and new private helpers, but is not ready to ship. Its durable PAUSE can be cleared by the existing, legitimate host RESUME while a PROTECTION_REPAIR journal remains OPEN. Entry admission does not independently inspect that journal. This violates the requirement that entries stay blocked for the entire repair window.

The enabled fake-broker regression `test_AX_27_host_resume_cannot_admit_a_buy_during_an_open_protection_repair` proves the sequence using real executor admission, risk/compliance checks, worker and ledger. An NVDA entry fills nine shares; its journal opens and its old exits are confirmed canceled. Entries are initially blocked. Host RESUME then clears the ordinary mode pause. With the same repair still OPEN and NVDA still held without a stop, a valid, delivered JNJ research card passes fresh admission and submits a second BUY (two shares). Broker POST count becomes 2 rather than the required 1. The ledger remains valid. This is entirely a paper fake; no network, real broker or keys are involved.

| Point | NVDA ledger / broker held | Active NVDA protection | Pending journal | New JNJ entry |
| --- | ---: | ---: | --- | --- |
| Old exits canceled inside repair | 9 / 9 | 0 | OPEN | Blocked by PAUSE |
| Host RESUME, before next monitor | 9 / 9 | 0 | OPEN | Incorrectly submitted: 2 shares |

Root of this blocker: `ModeStore.resume` (`backend/execution/modes.py:196`, unchanged) appends a normal unpaused override. `AlpacaExecutor.enter` (`backend/execution/alpaca_executor.py:1036`, unchanged by this protection correction) checks ordinary mode state at initial admission, serialized intent creation and the physical worker guard, but not the outstanding repair journal. `_resume_protection_repairs:2321` detects a lost block only on a later monitor/reconcile cycle; that cannot prevent an intervening BUY.

The smallest proposed boundary expansion is **`AlpacaExecutor.enter` only**, using the existing journal-reading helper to veto unresolved repairs at initial admission, inside serialized admission, and immediately before each physical submission. A journal must remain an independent veto even after an explicit RESUME. No change to modes.py, http.py, execution_policy.py, storage.validate_record(), model statuses, transitions or gates is proposed. **This additional production change is not applied** because `enter()` is outside the owner's exact boundary. Do not replace the repair pause with a fabricated drift event or a resettable HALT to evade that boundary.

Reproduce from vws-core:

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest backend/tests/test_auto_safety.py -k 'host_resume_cannot or repair_pause_is_durable' --no-cov -q
```

Latest result: **1 failed, 3 passed, 235 deselected**; the deselection here is only this diagnostic's explicit `-k`, not an offline-suite selector change. Synthetic-only evidence: `build/pass6/repair-host-resume.log`. The failure is the unexpected second physical BUY. Three repair pause/restart/operator-control cases pass after their fixture obtains fresh broker stop confirmation. The earlier broader journal check had 17 passes and three missing-confirmation fixture failures; those same three cases now pass. These focused checks are not a full-suite pass.

## Approved protection correction retained, uncommitted

Original root cause: `_protect_and_exit` treated zero canonical held shares as proof that a parent was terminal and its contingent exits were orphans. Healthy monitor/reconcile could therefore cancel both held bracket exits while the BUY was still open. The correction now requires fresh broker-terminal parent evidence and reconciled zero ledger/broker attributable holdings before orphan cleanup. Working zero-fill BUYs retain held exits. The original two enabled regression cases now pass; baseline-method substitution previously reproduced their failure.

The correction also adds append-only PROTECTION_REPAIR records, an owned durable entry pause, confirmed cancellation and fresh position reads, new-stop confirmation, old-level restoration on new-stop refusal, persistent failure plus HALT/alert when restoration fails, and restart recovery. Closing requires confirmed stop coverage and cannot release another operator's PAUSE/HALT or another pending account repair. `_ensure_stop`, `_raise_step` and `_raise_repair` all use the journaled cancel-then-submit path. No PATCH/replace support was added: the owner explicitly parked it. Existing broker fakes prove the cancel-before-submit sequence and restoration behavior, not real Alpaca integration.

Monitor/reconcile run the protection fail-safe before further cancellation and again at cycle completion. Positive held shares require sufficient active stop coverage outside a journaled repair window. Zero-fill BUYs with held bracket legs do not false-HALT. A recognized journal exempts its bounded repair window; an unresolved restart restores or HALTs. Partial BUY remainder cancellation still uses the CANCEL_REQUESTED finalizer without canceling independently confirmed filled-share coverage.

Focused passing evidence covers working-entry late fills/terminal cleanup; all three replacement paths with success, old-level restoration and double refusal; repair-window entry blocking absent host RESUME; restart restore/HALT; partial-remainder cancellation; fail-safe short/no-stop cases; eight alternating monitor/reconcile state walks; and refusal to close an unprotected journal. Logs under `build/pass6/` include `working-entry-cycles.log`, `journaled-ensure-stop.log`, `journaled-raise-paths.log`, `repair-failsafe-restart.log`, `protected-partial-remainder.log` and `protection-state-walks.log`. The state-walk run's four multi-repair fixture failures were corrected by recording fresh stop observations; their rerun is in `journal-confirmation-checks.log` (17 pass, three other fixture failures subsequently corrected as above).

The AST boundary comparison against `build/pass6/executor-expanded-source.py` reports existing-method changes only in `_cancel_sells`, `_ensure_stop`, `_protect_and_exit`, `_raise_repair`, `_raise_step`, `monitor` and `reconcile`; no existing function outside the approved boundary changed for this correction. New private helpers are listed in `build/pass6/repair-stop-boundary-proof.json`. Both ci.yml copies remain byte-identical and unchanged. No PATCH, new pragma, exclusion, model status, ledger transition, equivalent allowance, gate, selector, split or timeout change was added in this correction.

Collection against the Pass 5 XML records **282 added cases, zero removed** across the five executor files and migration tests (201 baseline, 483 current). This is collected count, not a pass count. Ruff check/format pass for executor and the two latest edited test files. The authored-source guard currently **fails**: GD-07 flags the new private helper name `_submit_journal_stop` at its two call sites (lines 2279 and 2290). The guard is unchanged; no further production edit was made after the boundary stop. Evidence: `build/pass6/repair-stop-source-guard.log`. Final normal/random suites, current 100% coverage, full-history gitleaks, inventory/partition proof, mutation kill passes and CI remain **UNVERIFIED / unfinished**. The historical pre-journal expanded diagnostic was 470 passed with 97.39% executor coverage; it does not measure this new source.

Risk-controls remains at the last native baseline of 427 survivors / four timeouts; executor-a at 863 survivors and executor-b at 925 survivors. No native after-count is available. The earlier side-helper-only 13,383 inventory patch remains stale; final regeneration is deferred until the complete approved source is stable. AUTO_LIVE stays locked and MANUAL_CSV disabled.

## Approved implementation retained before this stop

The owner resolved the pending/all-rejected outcome without adding a transition: CANCEL_REQUESTED → CANCELED, retaining each leg's broker-rejection observation. Before any cancel request, all rejected with zero fills uses the existing SUBMITTED → REJECTED. The transition map still has exactly the four approved additions and no removal; CANCELED and REJECTED remain final.

`backend/execution/storage.py:135` now contains the shared persisted finalizer. Both the executor cancellation coordinator and canonical aggregate fill capture call it. It requires every entry leg's terminal broker evidence (or proved no-send/rejection absence) to match captured fills before appending a terminal shared-order event. The executor's rejection writer no longer terminalizes one leg's shared order independently. Canonical full-quantity capture waits for both terminal confirmations; reconciliation can finish deferred full fills.

Broker rejection reason and failed_at timestamp, when supplied, are retained in each typed EXECUTION_ORDER_OBSERVED event. Missing broker fields remain explicitly unavailable rather than fabricated; observation time remains recorded. A pending all-rejected order has the reason/report text "canceled; both legs broker-rejected." Optional fields are omitted when absent, preserving old observation payloads for replay.

Focused checks passed: the original accepted-A/rejected-B/fill-A reproduction; 30 cancellation timing cases across panic/monitor/recovery in both orders; seven new classification/aggregate/admission cases; six rejection-before/during/after-fill cases; two bounded timeout/read-error cases with restart and zero-row repeat; terminal-fill refusal and forbidden-transition checks; third-leg and legacy-fill-writer refusal. Raw broker fault checks pass 22 cases. The version-7 backup/migration/replay/idempotence check passed, alongside the previous 15 migration tests.

The first full offline diagnostic finished with 5,879 passes, five failures, 61 skips and the same four performance deselections; required coverage was 98.70% (executor 92.40%). The single-leg rejection wording, storage fixture's missing terminal proof, and authored-source guard failures are corrected and their focused checks pass. Two partition assertions still expect the old inventory total; their exact equality remains pending the final generated inventory. No full-suite pass or 100% coverage is claimed. The expanded executor diagnostic is complete as recorded above. Inventory regeneration, risk/executor kill passes, final normal/random suites, full-history gitleaks, commit, push and completed CI remain outstanding.

Recent passing checks cover a HALT during serialized admission; daily/persisted entry limits; exact client-ID and price refusals; unbound children and uncaptured fills; invalid cancel budgets; inactive replacement protection; failed exit stop restoration; ambiguous-exit no-retry/no-overlap; opening-window/price/allocation stop-raise refusals; unavailable panic inventory; a real 1,001-record stop-inventory bound; refusal-only environment/configuration drift; physical stop-raise quote expiry with old protection restored; repair identity and unresolved-worker guards; and delayed canonical child activity. These focused results do not replace either required full-suite run.

Two further pure integrity guards were extracted unchanged and directly tested under the standing approval: working-tree line 1709, "Cancellation has no order lifecycle" (a verified execution intent already requires its lifecycle); working-tree line 1408, "EX-05: OCO stop child lost its held entry" (append/replay requires a REPAIR to reference an earlier ENTRY). They join the six earlier retained helpers. No additional transition, allowance, pragma, exclusion or workflow change was made. Ruff and strict typing pass for the latest executor/test edits.

### Current terminal-writer routing

| File:line | Trigger | Finalization / race evidence |
| --- | --- | --- |
| `backend/execution/alpaca_executor.py:1498` | Admission revocation between split submissions | Shared coordinator/finalizer; racing accepted-leg fill test passes. |
| `backend/execution/alpaca_executor.py:1511` | Broker rejects a submitted entry leg | Shared finalizer with no speculative cancellation/final state; original reproduction and both leg orders/timings pass. |
| `backend/execution/alpaca_executor.py:3356` | Protection recovery cancels a remainder | Shared coordinator/finalizer; timing matrix passes. |
| `backend/execution/alpaca_executor.py:3509` | Panic cancellation | Shared coordinator/finalizer; timing, pending rejection, bounded failure/resume and idempotence checks pass. |
| `backend/execution/alpaca_executor.py:3658` | Monitor cancellation / validity expiry / blocked entries | Shared coordinator/finalizer; timing matrix passes. |
| `backend/core/ledger.py:331` | Aggregate canonical auto-entry fill | Shared persisted finalizer; full quantity remains nonterminal until both broker terminals match. |
| `backend/execution/storage.py:196` | Sole shared auto-order terminal append | Classifies FILLED, CANCELED or pre-cancel REJECTED only after all leg evidence matches. |
| `backend/core/ledger.py:298` | Legacy fill's automatic FILLED | Cannot apply to an auto split: ledger.py:941 refuses legacy fills when execution instructions exist. Partial/full overwrite refusal tests pass without changing any rows. |

There is no shared EXPIRED/DONE/CLOSED OrderEvent writer. Expired broker legs aggregate with mixed terminal outcomes as CANCELED. Approval expiry writes a separate AlertEvent. Exit-cycle DONE and individual submit outcomes are separate audit records. The older line-numbered sweep and stops below are historical, superseded by this approved build.

## Earlier transition conflict (resolved by the owner)

The owner authorized sweeping the same bug family and routing every terminal writer through the shared finalizer, preserving the existing transitions plus exactly four additions. The sweep below is complete for production Python under backend/, vws/ and scripts/ (tests and generated diagnostics excluded). No production change was made during this sweep.

An outstanding CANCEL_REQUESTED order can receive terminal rejected responses for both entry legs with zero captured fills. The required aggregate outcome is REJECTED. Current transitions allow only CANCEL_REQUESTED → CANCELED or FILLED, both final; neither can reach REJECTED. Existing SUBMITTED → REJECTED handles an all-rejected order that has not entered pending cancellation, but cannot resolve this pending case. Cancel intent cannot be silently removed or the outcome relabeled CANCELED.

Exact proposed additional transition: **CANCEL_REQUESTED → REJECTED**, usable only after both entry legs are confirmed rejected and their captured/broker fill quantities all equal zero. This is NOT implemented or approved. CANCELED and REJECTED would remain final; no outgoing transition from either is proposed. The owner's explicit instruction to stop when an outcome needs a new transition applies.

Reachability was checked against the current transition map: CANCEL_REQUESTED can reach only CANCELED and FILLED; REJECTED is unreachable. Evidence: `build/pass6/pending-rejection-transition-conflict.json`. No inventory regeneration, gate/test-selector changes, new test runs, commit or push occurred in this sweep. Prior uncommitted work is retained.

### Complete terminal-order writer and caller sweep

Line numbers refer to the current uncommitted source. Four formerly direct CANCELED writers now call the shared finalizer; their call sites and both finalizer append sites are listed to make the inventory exhaustive.

| File:line | Trigger / terminal state | Does the single-leg finalization race apply? |
| --- | --- | --- |
| `backend/execution/alpaca_executor.py:1336` | `enter`, confirmed rejection of one submitted leg; appends shared REJECTED. | **Yes.** Another accepted leg can still fill. This is the retained failing regression; routing is unfinished because of the pending → rejected conflict. |
| `backend/execution/alpaca_executor.py:1322` | Admission guard revocation, including stale quote, mode or policy changes; formerly appended shared CANCELED. | **Yes in the original writer** when an earlier split leg was already submitted. Currently calls the shared finalizer. |
| `backend/execution/alpaca_executor.py:2513` | Reconciliation/protection recovery cancels a verified unfilled remainder; formerly shared CANCELED or REJECTED from one result. | **Yes in the original writer.** Currently calls the shared finalizer. |
| `backend/execution/alpaca_executor.py:2661` | Panic cancels an entry remainder; formerly shared CANCELED or REJECTED from one result. | **Yes in the original writer**, including the reversed split regression. Currently calls the shared finalizer. |
| `backend/execution/alpaca_executor.py:2790` | Monitor cancels on blocked entries, entry validity expiry/time-based cleanup, or a partially filled remainder; formerly shared CANCELED or REJECTED. | **Yes in the original writer.** Currently calls the shared finalizer. There is no separate end-of-day CANCELED writer. |
| `backend/execution/alpaca_executor.py:1701` | Shared finalizer's direct CANCELED branch when every leg has verified no-send/rejection evidence. | **Not based on one leg:** checks all legs. Classification is incomplete: all-rejected evidence must yield REJECTED; no-submit remains eligible for direct CANCELED. |
| `backend/execution/alpaca_executor.py:1754` / `:1767` | Shared finalizer chooses and appends FILLED or CANCELED after every submitted entry leg is terminal and fills match. | **Not based on one leg.** Both-leg terminal/fill checks exist. Required all-rejected REJECTED result is missing and blocked when already pending. |
| `backend/core/ledger.py:322` | Canonical ENTRY ExecutionFillRecord append automatically emits FILLED when cumulative fills equal the total of all entry instructions; emits PARTIALLY_FILLED otherwise; emits neither while pending. | **Quantity is aggregated**, so one incomplete leg cannot make a valid two-leg order fully filled. However it does not separately confirm both broker terminal statuses; this FILLED path must also be routed through the finalizer under the latest requirement. Not yet changed. |
| `backend/core/ledger.py:286` / `:298` | Legacy Fill append automatically emits FILLED at the original order's full quantity, unless pending. | **Not reachable for a shared auto split.** `_validate_fill` at ledger.py:930 rejects legacy fills for any order with execution instructions. Included to account for every remaining terminal OrderEvent append. |

No shared OrderEvent EXPIRED, DONE or CLOSED writer exists. The order-state database constraint does not contain those states. Broker expired is leg-level terminal evidence; zero-fill mixed rejected/canceled/expired legs should aggregate to CANCELED using the existing transition, with no better existing shared state. Approval expiry writes AlertEvent, not OrderEvent; exit-cycle DONE and per-leg submit outcomes are separate audit records, not shared-order lifecycle transitions. Core gate and read-only fill polling append only nonterminal order states.

Outcomes otherwise fit existing/approved transitions: full aggregate quantity → FILLED; partial fills remain durable while pending → CANCELED; zero-fill mixed terminal outcomes → CANCELED. The only identified transition conflict is pending plus zero-fill/all-rejected → REJECTED. No additional transition was added.

## Previous stop and reproduced bug: accepted A, rejected B, then A fills

The separate `except OrderRejectedError` writer in `AlpacaExecutor.enter` marks the shared order REJECTED when B is rejected even though A has already been accepted. The writer is AST-identical to 2d0f9c6. The enabled regression `test_EX_01_rejected_second_leg_does_not_prevent_first_leg_fill_capture` submits two paper legs, confirms B's rejection, and then captures A's real canonical fill. Capture fails with `ReconciliationError("Auto fill failed closed; inspect account evidence")`; tracing records the underlying `LedgerIntegrityError("Invalid appended order lifecycle transition")`.

Both the current entry method and the baseline 2d0f9c6 entry method reproduce it: four broker-held shares, four active stop shares, zero ledger-held shares, durable HALT, two entry submissions, and a valid ledger ending PROPOSED → APPROVED → SUBMITTED → REJECTED. The fill transaction is rolled back. No unprotected holding is claimed from these reproductions.

This REJECTED writer is separate from the four approved CANCELED writers. It has not been fixed, and no new transition from REJECTED or CANCELED has been added. The owner's instruction to stop on another real behavior bug applies.

Reproduction from vws-core:

```powershell
.venv\Scripts\python.exe -m pytest -q --no-cov backend/tests/test_auto_safety.py -k rejected_second_leg
```

Safe evidence: `build/pass6/rejected-sibling-working-tree-evidence.json`, `rejected-sibling-baseline-evidence.json`, and `reproduce_rejected_sibling.py`. Each reproduction fails one test; the baseline diagnostic substitutes only the original entry method and runs the same real fake-broker/ledger test.

## Approved build retained in the working tree

- Collection compared with the Pass 5 XML: 150 added cases, zero removed, across the five executor test files plus the migration tests. The new rejection regression remains enabled and failing. Lint, formatting, strict typing for the seven directly changed files, and diff whitespace checks pass; this does not certify the full suite.
- Exactly four transitions were added: SUBMITTED → CANCEL_REQUESTED; PARTIALLY_FILLED → CANCEL_REQUESTED; CANCEL_REQUESTED → FILLED; CANCEL_REQUESTED → CANCELED. None were removed. Pending fills retain cancellation intent and preserve the existing identity, quantity, price and time checks. No pending → partial or canceled → filled transition exists.
- Schema version 8 adds the state constraint. The explicit SQLite migration authenticates an encrypted backup, preserves all original stored order-event values and hashes, reinstalls append-only triggers/indexes, verifies replay, and is idempotent. The populated actual-version-7 migration/replay/backup/idempotence test passes. Existing 15 migration tests passed separately.
- `_finalize_entry_cancellation` is used by panic, admission revocation, recovery and monitor cancellation. It coordinates the shared entry legs and leaves unresolved confirmations pending. The new bounded wait defaults to 30 seconds, validates 1–30 seconds, and changes no mutation timeout.
- Thirty timing cases pass: before, between, after cancellation requests, both legs filled, and multiple fills while pending; both leg orders; panic, monitor and recovery. They compare ledger holdings, broker holdings and active stop shares. Panic cases also assert that a second completed panic adds zero ledger rows.
- The third-entry-leg test passes with the exact EX-01 error and no ledger-row or allocation change. The split contract remains one A then one B.
- The original full-fill panic regression and all seven other panic-focused cases passed together. These are focused checks, not a full-suite coverage certification.
- Admission-race, timeout/resume/failure-continuation and exhaustive integrity verification remain unfinished. The full normal/random suites, 100% coverage, risk/executor mutation pass and final full-history gitleaks remain UNVERIFIED.
- Inventory regeneration remains deferred. The earlier side-helper-only 13,383 patch is stale after subsequent source changes; no fresh partition PASS is claimed. Gates, equivalent allowances, selectors and workflow copies were not changed in this continuation.
- No new equivalent proposals, allowances, pragma or coverage exclusion was added. Per-run in-memory fixture caching and the planted schema mutant test remain unchanged.

AUTO_LIVE remains locked and MANUAL_CSV remains disabled. All brokers, accounts, credentials and fills in these tests are offline paper fakes.

## Earlier continuation evidence (historical)

### Earlier stop on the original panic-cancel race

Baseline: `2d0f9c6ca10ed1894445afb5c771ee95fd691a3c`. No commit, push or new CI run.

## Reproduced behavior bug: SEC-73 / AX-26 / AX-30

`test_SEC_73_fill_during_panic_cancel_keeps_newly_held_shares_protected` uses a paper fake, the real single-attempt worker, canonical `observe_fill`, and real append/ledger validators. No validator or record is patched or bypassed.

1. Submit one paper bracket; the entry is unfilled when panic begins under durable HALT.
2. While the broker cancel is pending, the broker fills the entry and canonical capture records that fill.
3. Cancel polling correctly sees FILLED with the matching captured quantity.
4. `cancel_unfilled_entries` nevertheless appends CANCELED. The ledger rejects FILLED → CANCELED with **LedgerIntegrityError("Invalid appended order lifecycle transition")**.

The reproduction records nine held shares, nine active stop shares, one physical submit, durable HALT and a valid ledger ending PROPOSED → APPROVED → SUBMITTED → FILLED. The demonstrated defect is the unexpected panic-command failure. No unprotected position is claimed from this run.

The affected method is AST-identical to baseline 2d0f9c6 (baseline line 2483, current start line 2513). The failure therefore precedes any bug fix and is independent of the approved guard extractions. The failing test remains enabled, with worker cleanup in a finally block. No fix, xfail, skip, exclusion, allowance or weakened assertion was added.

A correction must recognize the completed fill and refresh held quantity before deciding whether to preserve/repair protection or cancel orphan sells. That changes behavior, so the latest standing rule requires stopping for an owner decision before implementing it.

Reproduce from vws-core:

```powershell
.venv\Scripts\python.exe -m pytest -q --no-cov backend/tests/test_auto_safety.py::test_SEC_73_fill_during_panic_cancel_keeps_newly_held_shares_protected
```

Evidence: `build/pass6/panic-cancel-race-evidence.json`, `panic-cancel-race-confirmed.log`, and `reproduce_panic_race.py`. The reproducer reports **one failed test**; lint and strict typing pass for the executor and five changed test files.

## Retained defensive guards extracted under owner approval

Line numbers below refer to baseline 2d0f9c6. The two specifically approved working-tree lines 2422/2432 correspond to baseline 2417/2427. Each condition, error type and message is preserved. Direct tests cover raise and pass paths; valid input objects/enum values are preserved.

| Baseline line | Private helper | Exact exception and message | Why the public path cannot reach the raise with accepted state |
| ---: | --- | --- | --- |
| 213 | `_require_side` | DataIntegrityError: Validated order has no side | Mandatory revalidation requires BUY or SELL for every accepted order shape. |
| 1196 | `_require_entry_projection` | DataIntegrityError: Entry state projection is missing | Entry has already verified the initialized state singleton; supported writers never delete it. |
| 1530 | `_require_fresh_cancel_roots` | DataIntegrityError: EX-06: fresh paper roots unavailable | Both roots have just passed successful binding observation before the lookup. |
| 2242 | `_require_absent_sell_unfilled` | ReconciliationError: Absent sell intent has captured fills | A missing binding cannot have a valid captured sell; fill validation requires a proved binding. |
| 2417 | `_require_fill_parent` | ReconciliationError: Fill notification lost its managed entry | The preceding full ledger verification requires every non-entry instruction to have a matching ENTRY parent. |
| 2427 | `_require_acquisition_basis` | ReconciliationError: Fill notice has no verified acquisition basis | An ENTRY fill includes itself; a valid positive sell requires preceding acquired shares retained in append-only history. |

No non-guard production behavior has been changed. The panic method itself is unchanged.

The complete working-tree [helper extraction diff](../build/pass6/guards.diff) records all six retained guards and their call sites.

## Test and inventory status

- Collection compared with the Pass 5 full-suite XML: **107 added cases, zero removed**, across five already-selected executor test files; 293 cases now collect in those files.
- New focused behavior groups pass after fixture corrections. The real panic-race regression is intentionally still failing before its fix. No whole-current-suite pass is claimed.
- The earlier 217-case focused run passed tests but failed its unchanged 100% coverage gate at 77.56%. A later 48-case diagnostic also passed tests and failed coverage; neither is a full-suite measurement.
- Full normal/random suites at 100%, risk-controls (427 survivors/four timeouts), executor-a (863 survivors), executor-b (925 survivors), native after counts, final gitleaks, commit/push and CI completion remain **UNVERIFIED / not performed** for this continuation.
- The earlier side-helper inventory update to 13,383 remains in the working tree. Under the latest instruction, inventory regeneration is deferred until all helper work is finished. It has **not** been regenerated after these five additional helpers; the old 13,383 preflight is not a current certification.
- No new equivalent proposal or approved allowance was added. The six-entry equivalent list remains unchanged.
- Gates, thresholds, timeouts, source/test selectors, both byte-identical ci.yml copies, and coverage rules remain unchanged. Per-run fixture caches and the planted schema test were not modified.

AUTO_LIVE remains locked; MANUAL_CSV remains disabled. No real keys, network, account orders, host setup or Dependabot changes were used. Live refusal cases use only isolated test snapshots and a paper fake and always refuse before transport use.
