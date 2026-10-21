# Pass 6 STOP: advisory sizing assumes monotone arithmetic failures

Historical diagnosis, superseded by the owner's approved local-context fix and
physical-send CRO recheck. The old snapshot fails the corrected expectation;
the current source passes it and the 7,296-case matrix. Current verification and
remaining native gate obligations are in [MUTATION_PASS6.md](MUTATION_PASS6.md).

October 18, 2026. Baseline remains `2d0f9c6ca10ed1894445afb5c771ee95fd691a3c`.
No Pass 6 commit, push or CI run. No further inventory update. The previously
approved 15,300-ID inventory/helper work and all other uncommitted work remain.

## Reproduced behavior

Use the ordinary CASH/paper risk fixtures: $10,000 cash and equity, no holdings
or pending orders, a fresh $100 quote, and an eight-share BUY with a $95 stop.
No broker, network, keys, execution-mode upgrade or live unlock is involved.

Inside a valid local Decimal context with `Emin = 0` and
`traps[Subnormal] = True`:

1. `ChiefRiskOfficer.evaluate` approves the full eight-share order.
2. `ChiefRiskOfficer.max_allowed_qty` returns **0**, rather than **8**.
3. An independent control loading the unchanged risk source into a fresh class,
   without the test work-budget wrapper, reproduces the same result. Normal
   Decimal context returns 8; the strict context still fully approves quantities
   5 through 10 when evaluated directly.

The enabled regression is
`backend/tests/test_risk_cro.py::test_CRO_03_advisory_keeps_an_already_approved_quantity_under_subnormal_traps`.
Its approval assertion passes; its final assertion fails with `assert 0 == 8`.
This is a conservative sizing/refusal defect; the reproduction submits no order.

## Root cause and correction boundary

`backend/risk/risk_cro.py:354` calculates the four-share probe's $0.80 slippage
under the inherited exponent context. That exact value signals `Subnormal` with
this context. `evaluate:162` catches the arithmetic error and returns a fault
verdict. `max_allowed_qty:560` treats this as an ordinary quantity rejection:
the first midpoint is 4 (`:590`), so it reduces the upper bound to 3 (`:606`) and
never tests the already-approved quantity 8. Arithmetic fault verdicts are not
necessarily monotone with quantity, although the binary search assumes they are.

The risk source is unchanged from HEAD (`git diff -- backend/risk/risk_cro.py`
is empty). Correcting arithmetic-context handling or distinguishing arithmetic
faults from size rejections would require changing risk source outside the
approved nine executor functions and their private helpers. **No fix is applied.**
`max_allowed_qty__mutmut_37` is not proposed as equivalent: its alternate probe
order cannot be justified by assuming the currently broken monotonicity contract.

Reproduce from `vws-core`:

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -q --no-cov backend/tests/test_risk_cro.py::test_CRO_03_advisory_keeps_an_already_approved_quantity_under_subnormal_traps
```

Local evidence: `build/pass6/advisory-subnormal-regression-before.log`,
`advisory-subnormal-pristine-control.log`, and `advisory-subnormal-probe.json`.

## Verification completed before this STOP

| Check | Result |
|---|---|
| Fresh frozen complete normal offline suite | 6,090 passed, 61 skipped, exactly four original perf deselections; 2,355.55 seconds |
| Required full-suite coverage | 9,463/9,463 statements and 3,368/3,368 branches; 100% |
| Executor full-suite coverage | 1,838/1,838 statements and 762/762 branches; 100%; no new exclusion or pragma |
| Focused risk/compliance baseline before the new failing regression | 514 passed |
| Collected additions versus Pass 5 | 537 added, zero removed; four pre-existing config parameter suffix renames verified against unchanged source; exactly the four original perf cases deselected |
| Local replay of the original 427 risk survivors and four timeouts | 384 now fail real behavior checks, including all four former timeouts; 47 remain; these are CST diagnostics, not native CI results |
| Equivalent proposals | Two individual `typing.cast` proposals in `MUTATION_PASS6_EQUIVALENT_PROPOSALS.md`; no allowlist additions; the other survivors are not declared equivalent |
| Partition preflight | Previously passed: 18 files, 63 jobs, 15,300 unique IDs owned exactly once; no retained ID moved |
| GD-07 | Prior scoped verification: 337 passed; guard and allowlist unchanged |

The current tree is **not green**: the newly enabled regression fails. Final
normal/random suites and final full-history gitleaks have not run. Executor-a
and executor-b replay preparation is read-only; their kill passes have not
started. There are no native after-counts, Pass 6 commit or CI links to report.
All unlisted survivors remain gate failures; gates, timeouts, selectors,
cohorts and equivalent allowances remain unchanged.
