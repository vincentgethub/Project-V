# Non-tax mutation setup profiling

Base: `2bd8ea28ff1d08ef5f25a16886a3e351f48a4022`. This pass adds no test cases and changes no test body or assertion. All production sources, six shard assignments, mutation selectors, required coverage, 100% gates, worker limits and 120-minute timeouts remain unchanged. Every unlisted survivor and no-test mutant still fails the gate. No equivalent allowance is installed. AUTO_LIVE stays locked and MANUAL_CSV disabled.

The 32 individual tax proposals and unresolved accounting mutant 78 are documented with individual exact normalized diffs in [TAX_EQUIVALENT_PROPOSALS.md](TAX_EQUIVALENT_PROPOSALS.md). The full no-test inventory is in [NON_TAX_NO_TEST_FUNCTIONS.md](NON_TAX_NO_TEST_FUNCTIONS.md).

## Method and limits

Risk-controls was measured first. Fresh pinned 3.8.0 instrumentation and its unchanged 17-file pytest selection establish each shard's function-to-test mapping. All five before/after mappings match exactly. A setup-only cProfile observer and pytest phase/fixture reports identify costs. Twenty high-estimated-cost literal-bearing candidates per shard are replayed before/after with identical mapped tests and native fast-tests-first ordering. All 100 exits and every recorded test/phase outcome match. This scoped cohort is not the global slowest-20 ranking. Windows cannot run native forked mutmut here; WSL is not installed. Unforked wall time includes cold Windows compilation/imports, and concurrent host load and generated Hypothesis examples can vary. Phase measurements are comparable observations, not native mutation certification or a controlled causal speed estimate.

The normal delivery CI invokes `scripts.profile_mutations` with exactly the original patterns. It calls the pinned native `mutmut run` CLI, forwarding the original runner arguments and return codes. It observes setup/call/teardown, cumulative fixture bodies, mapped/executed tests, worker limits and native results. Per-test JSONL timing snapshots in RUNNER_TEMP are diagnostic output, never cached fixture inputs; partial CPU-timeout observations are explicitly incomplete. The gate continues to consume native mutmut results through the unchanged strict checker. The only workflow edit, byte-identical in both copies, is:

```diff
-          subprocess.run([sys.executable, "-m", "mutmut", "run", *manifest["patterns"]], check=True)
+          subprocess.run([sys.executable, "-m", "scripts.profile_mutations", *manifest["patterns"]], check=True)
```

## Setup change and isolation

The research harness repeatedly rebuilds the same synthetic NVDA indicators, including repeated bar/money validation. A pytest-session dictionary now holds only immutable serialized pure indicator entries. Each test creates a new IndicatorMemo and validates fresh IndicatorSeries models from JSON; the real hunt, CRO cap, sizing, ledger, settings, database and clocks still run independently. The key binds synthetic input, helper code identities, model validators, Decimal context and calendar data; custom disk/provider memos bypass it. Nothing is persisted to disk or reused by a later mutant, and session teardown clears the seed dictionary. The existing schema/calendar isolation remains intact.

An active-cache pilot observed 114 fresh JSON clones in 115 harnesses; cumulative IndicatorMemo.calculate setup work fell from 11.127s to 3.476s, with 1.17s spent validating clones. Those full-selection pilot runs had different concurrent load, so their wall time is not presented as a controlled speed gain. Call work dominates several cohorts and remains untouched. The measured setup reduction does not establish a uniform total speedup.

## Paired cohort means, seconds per mutant

| Shard | Before setup / call / total phase | After setup / call / total phase | Phase reduction | Mapped tests per mutant | Mean executed calls before / after |
| --- | ---: | ---: | ---: | ---: | ---: |
| risk-controls | 39.558 / 51.182 / 90.942 | 33.259 / 51.553 / 85.012 | 6.52% | 240–326 | 193.0 / 193.0 |
| risk-sizing | 29.553 / 39.235 / 68.905 | 26.751 / 44.206 / 71.076 | -3.15% | 115–115 | 57.5 / 57.5 |
| fundamentals-callbacks | 23.968 / 39.270 / 63.347 | 21.971 / 44.088 / 66.184 | -4.48% | 115–168 | 81.7 / 81.7 |
| executor-a | 19.255 / 36.522 / 55.866 | 16.982 / 36.392 / 53.463 | 4.30% | 60–60 | 36.5 / 36.5 |
| executor-b | 2.423 / 0.055 / 2.481 | 2.466 / 0.053 / 2.523 | -1.68% | 51–51 | 1.0 / 1.0 |

Negative reduction means slower measured total phase time. In particular, sizing and fundamentals show lower setup cost but higher call time in these observations; this pass does not claim their total runtime improved. The delivery CI supplies actual Linux throughput, native counts and the slowest 20 observed mutants per shard in the final handoff. A job timeout leaves all unfinished mutants unverified. Any proposed split in that handoff is for owner approval only and is not applied here.

Full-inventory tests per mutant, weighted over every assigned ID rather than only the paired cohort. These are unchanged function mappings; early failure can execute fewer tests.

| Shard | Assigned IDs | Mean mapped tests | Range | Zero mapped tests |
| --- | ---: | ---: | ---: | ---: |
| risk-controls | 2,561 | 187.64 | 0–326 | 4 |
| risk-sizing | 1,914 | 48.70 | 0–198 | 646 |
| fundamentals-callbacks | 2,023 | 82.09 | 4–168 | 0 |
| executor-a | 2,580 | 29.76 | 0–60 | 552 |
| executor-b | 2,579 | 24.72 | 0–51 | 243 |

## What setup spends time on

Cumulative setup cProfile times below include nested calls and must not be summed. These are clean selected-suite baselines, used to explain the per-mutant fixture measurements in the tables below.

| Shard | Setup function | Calls | Cumulative seconds |
| --- | --- | ---: | ---: |
| risk-controls | `backend/tests/test_swarm_and_callbacks.py:121 make_research_harness` | 115 | 43.659 |
| risk-controls | `backend/agents/setup_hunter.py:418 hunt` | 115 | 25.525 |
| risk-controls | `backend/core/money.py:33 decimal_money` | 3111911 | 17.545 |
| risk-controls | `backend/agents/indicators.py:80 _bars` | 920 | 15.780 |
| risk-controls | `backend/core/money.py:14 validate_cent_price` | 2026177 | 15.079 |
| risk-controls | `backend/core/money.py:47 _scaled` | 3111911 | 14.192 |
| risk-controls | `backend/domain/models.py:50 _cent_price` | 1662736 | 13.253 |
| risk-sizing | `backend/tests/test_swarm_and_callbacks.py:121 make_research_harness` | 115 | 43.453 |
| risk-sizing | `backend/agents/setup_hunter.py:418 hunt` | 115 | 25.063 |
| risk-sizing | `backend/core/money.py:33 decimal_money` | 3111911 | 17.287 |
| risk-sizing | `backend/agents/indicators.py:80 _bars` | 920 | 15.533 |
| risk-sizing | `backend/core/money.py:14 validate_cent_price` | 2026177 | 14.825 |
| risk-sizing | `backend/core/money.py:47 _scaled` | 3111911 | 13.950 |
| risk-sizing | `backend/domain/models.py:50 _cent_price` | 1662736 | 13.033 |
| fundamentals-callbacks | `backend/tests/test_swarm_and_callbacks.py:121 make_research_harness` | 115 | 43.808 |
| fundamentals-callbacks | `backend/agents/setup_hunter.py:418 hunt` | 115 | 25.677 |
| fundamentals-callbacks | `backend/core/money.py:33 decimal_money` | 3111911 | 18.118 |
| fundamentals-callbacks | `backend/agents/indicators.py:80 _bars` | 920 | 16.054 |
| fundamentals-callbacks | `backend/core/money.py:14 validate_cent_price` | 2026177 | 15.407 |
| fundamentals-callbacks | `backend/core/money.py:47 _scaled` | 3111911 | 14.761 |
| fundamentals-callbacks | `backend/domain/models.py:50 _cent_price` | 1662736 | 13.576 |
| executor-a | `backend/tests/test_swarm_and_callbacks.py:121 make_research_harness` | 115 | 63.790 |
| executor-a | `backend/agents/setup_hunter.py:418 hunt` | 115 | 38.055 |
| executor-a | `backend/core/money.py:33 decimal_money` | 3111911 | 26.036 |
| executor-a | `backend/agents/indicators.py:80 _bars` | 920 | 24.006 |
| executor-a | `backend/core/money.py:14 validate_cent_price` | 2026177 | 22.388 |
| executor-a | `backend/core/money.py:47 _scaled` | 3111911 | 21.308 |
| executor-a | `backend/domain/models.py:50 _cent_price` | 1662736 | 19.828 |
| executor-b | `backend/tests/test_swarm_and_callbacks.py:121 make_research_harness` | 115 | 56.976 |
| executor-b | `backend/agents/setup_hunter.py:418 hunt` | 115 | 33.357 |
| executor-b | `backend/core/money.py:33 decimal_money` | 3111911 | 22.768 |
| executor-b | `backend/agents/indicators.py:80 _bars` | 920 | 20.758 |
| executor-b | `backend/core/money.py:14 validate_cent_price` | 2026177 | 19.510 |
| executor-b | `backend/core/money.py:47 _scaled` | 3111911 | 18.458 |
| executor-b | `backend/domain/models.py:50 _cent_price` | 1662736 | 17.126 |

## Planted mutation and isolation results

These diagnostic replays use existing behavior tests with a real generated mutant, in the same interpreter: clean succeeds, planted fails, restored succeeds. They are not additional test cases. The seed dictionary starts and ends empty whenever the fixture is reached, and mutable memos are distinct. A planted failure before fixture creation is recorded explicitly in the raw observations.

| Shard | Planted mutant | Existing test | Clean / planted / restored |
| --- | --- | --- | --- |
| risk-controls | `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_1` | `backend/tests/test_auto_admission.py::test_AX_42_exact_live_ceiling_boundary_and_first_excess[daily]` | 0 / 1 / 0 |
| risk-sizing | `backend.risk.overlays.x_fit_open_risk__mutmut_11` | `backend/tests/test_swarm_and_callbacks.py::test_GD_06_gate_refuses_unbound_clock_and_result_disclosure` | 0 / 1 / 0 |
| fundamentals-callbacks | `backend.notifications.callbacks.xǁApprovalGateǁ__init____mutmut_1` | `backend/tests/test_swarm_and_callbacks.py::test_GD_06_gate_refuses_unbound_clock_and_result_disclosure` | 0 / 1 / 0 |
| executor-a | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_10` | `backend/tests/test_auto_execution.py::test_AX_11_downgraded_constructor_refuses_before_client_calls[harness0]` | 0 / 1 / 0 |
| executor-b | `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_10` | `backend/tests/test_auto_contracts.py::test_AX_28_stream_stops_after_three_auth_failures_and_rest_monitor_survives[harness0]` | 0 / 1 / 0 |

The retained schema proof also returns 0 / 1 / 0 for initial state RUNNING → HALTED. A separate two-existing-test poison check mutates the first test's local IndicatorSeries.ema20 to an empty tuple after its assertions; the next test gets fresh validated models, passes, leaves serialized seeds unchanged, and teardown clears the session. No test assertion was altered.

## Full verification and reproduction

Normal/random offline suites both pass with the identical 5,524-case multiset: 5,463 passed, 61 skipped, four performance cases deselected and two warnings each. Random seed: 20261014. Durations: 1,180.04s normal and 1,338.39s random. Both cover all 7,625 required statements and 2,606 branches, with zero missing lines/branches. No test case was added.

Ruff lint and formatting pass for all 420 authored Python files; whole strict typing passes for all 420; the source guard passes. Bandit using the exact CI production/script scope reports zero findings and zero errors (an existing unused B506 suppression warning remains). The secrets hook passes. The full-history gitleaks 8.30.1 `git .. --log-opts=--all --redact --no-banner` scan finds no leaks across all 45 pre-delivery commits; the checkout is not shallow. The committed tree is rescanned before the sole push, with that result included in the final handoff. The progress-page parser passes (51 lines).

Native Linux completion, per-shard processed/killed/survived/no-test counts, slowest observed mutants and any proposed split are recorded in the final delivery handoff, since no second push is permitted.

On Linux with the pinned dependencies, use the unchanged workflow preflight to create RUNNER_TEMP/vws-mutation-shard.json for the selected row, select that row's original source_paths, then run `python -m scripts.profile_mutations` with that row's original patterns. Export `python -m mutmut results --all true`; the original workflow verifies the complete generated/selected inventory and runs `scripts.check_mutations` against every assigned ID. Profiling does not certify a passing gate. Native Windows execution remains unavailable.

Exact Linux reproduction in a disposable checkout with the pinned dependencies installed (replace the shard name with an unchanged matrix row). This executes the workflow's existing preflight and mutation/gate steps verbatim, including source-path selection; it does not dispatch CI:

```bash
export VWS_MUTATION_SHARD=risk-controls
export RUNNER_TEMP="$(mktemp -d)"
python - <<'PY'
import os
import subprocess
from pathlib import Path
import yaml
job = yaml.safe_load(Path('.github/workflows/ci.yml').read_text())['jobs']['mutations']
steps = [s for s in job['steps'] if 'run' in s]
for step in steps:
    if step['name'] in (
        'Prove complete disjoint file function and mutant assignments',
        'Mutate every assigned mutant and enforce the unchanged 100 percent gate',
    ):
        subprocess.run(['bash', '-eu', '-o', 'pipefail', '-c', step['run']], check=True, env=os.environ)
PY
```

## risk-controls paired observational cohort

These are the same 20 high-estimated-cost literal-bearing candidates, not a claim of the global before-run ranking. Actual slowest completed native mutants are reported from delivery CI. Mapped test sets and fast-tests-first ordering are held fixed; exits are identical. Windows unforked wall includes cold imports/compilation and is not a native gate certificate. Setup/call figures include the same setup cProfile observer in both variants. Host contention and generated Hypothesis examples can vary.

| Mutant ID | Mapped tests | Before setup / call / wall (s) | After setup / call / wall (s) | After dominant setup fixture |
| --- | ---: | ---: | ---: | --- |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_10` | 326 | 0.463 / 0.000 / 30.114 | 0.456 / 0.000 / 29.253 | calendar: 0.441s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_11` | 326 | 0.477 / 0.000 / 29.478 | 0.475 / 0.000 / 29.595 | calendar: 0.461s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_16` | 326 | 71.161 / 95.599 / 196.773 | 57.970 / 97.735 / 185.999 | harness: 51.535s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_17` | 326 | 71.212 / 95.676 / 198.025 | 58.267 / 97.954 / 186.210 | harness: 51.790s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_18` | 326 | 70.974 / 97.315 / 180.513 | 58.864 / 97.660 / 169.723 | harness: 52.810s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_27` | 326 | 71.559 / 96.371 / 180.301 | 58.320 / 98.355 / 169.472 | harness: 52.187s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_28` | 326 | 70.667 / 95.888 / 180.543 | 61.672 / 94.972 / 171.654 | harness: 54.857s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_29` | 326 | 71.961 / 95.182 / 181.159 | 61.502 / 96.410 / 172.849 | harness: 54.722s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_3` | 326 | 68.370 / 97.728 / 179.241 | 58.145 / 97.177 / 169.010 | harness: 51.668s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_4` | 326 | 67.458 / 98.096 / 178.742 | 57.889 / 97.295 / 168.974 | harness: 51.455s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_5` | 326 | 11.784 / 0.315 / 25.221 | 11.487 / 0.325 / 25.660 | harness: 6.828s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_6` | 326 | 0.590 / 0.000 / 13.463 | 0.581 / 0.000 / 14.079 | calendar: 0.553s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_7` | 326 | 11.187 / 0.292 / 25.533 | 10.579 / 0.290 / 25.535 | harness: 6.313s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_8` | 326 | 11.195 / 0.288 / 25.544 | 10.451 / 0.290 / 25.395 | harness: 6.223s |
| `backend.risk.compliance.xǁComplianceEngineǁ__init____mutmut_9` | 326 | 0.249 / 0.000 / 12.849 | 0.278 / 0.000 / 13.065 | calendar: 0.252s |
| `backend.risk.risk_cro.xǁChiefRiskOfficerǁ__init____mutmut_10` | 240 | 6.671 / 0.024 / 15.618 | 6.555 / 0.022 / 15.645 | harness: 6.025s |
| `backend.risk.risk_cro.xǁChiefRiskOfficerǁ__init____mutmut_11` | 240 | 7.736 / 0.021 / 16.369 | 7.258 / 0.021 / 16.124 | harness: 6.664s |
| `backend.risk.risk_cro.xǁChiefRiskOfficerǁ__init____mutmut_18` | 240 | 58.136 / 84.184 / 153.354 | 47.704 / 84.567 / 143.468 | harness: 45.967s |
| `backend.risk.risk_cro.xǁChiefRiskOfficerǁ__init____mutmut_19` | 240 | 59.929 / 83.028 / 153.999 | 47.913 / 84.600 / 143.799 | harness: 46.220s |
| `backend.risk.risk_cro.xǁChiefRiskOfficerǁ__init____mutmut_20` | 240 | 59.381 / 83.631 / 152.476 | 48.808 / 83.385 / 141.172 | harness: 47.059s |

## risk-sizing paired observational cohort

These are the same 20 high-estimated-cost literal-bearing candidates, not a claim of the global before-run ranking. Actual slowest completed native mutants are reported from delivery CI. Mapped test sets and fast-tests-first ordering are held fixed; exits are identical. Windows unforked wall includes cold imports/compilation and is not a native gate certificate. Setup/call figures include the same setup cProfile observer in both variants. Host contention and generated Hypothesis examples can vary.

| Mutant ID | Mapped tests | Before setup / call / wall (s) | After setup / call / wall (s) | After dominant setup fixture |
| --- | ---: | ---: | ---: | --- |
| `backend.risk.overlays.x_fit_open_risk__mutmut_10` | 115 | 57.912 / 79.367 / 150.565 | 51.304 / 89.835 / 152.517 | harness: 50.053s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_11` | 115 | 2.950 / 0.000 / 15.194 | 2.907 / 0.000 / 13.162 | harness: 2.853s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_12` | 115 | 2.921 / 0.000 / 15.385 | 2.904 / 0.000 / 12.968 | harness: 2.847s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_13` | 115 | 3.002 / 0.000 / 15.281 | 2.885 / 0.000 / 13.256 | harness: 2.831s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_14` | 115 | 57.827 / 80.149 / 144.170 | 50.749 / 89.403 / 146.120 | harness: 49.498s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_15` | 115 | 56.981 / 82.051 / 145.164 | 49.901 / 91.465 / 147.314 | harness: 48.638s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_16` | 115 | 57.070 / 81.398 / 144.554 | 51.114 / 90.035 / 147.108 | harness: 49.829s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_17` | 115 | 59.474 / 81.470 / 146.156 | 51.243 / 93.429 / 150.119 | harness: 49.968s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_18` | 115 | 59.983 / 79.330 / 145.439 | 52.536 / 92.457 / 150.374 | harness: 51.231s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_19` | 115 | 59.425 / 79.896 / 145.310 | 53.566 / 91.717 / 151.153 | harness: 52.269s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_20` | 115 | 2.969 / 0.000 / 8.438 | 2.543 / 0.000 / 7.814 | harness: 2.500s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_21` | 115 | 2.886 / 0.000 / 6.888 | 2.733 / 0.000 / 8.369 | harness: 2.691s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_22` | 115 | 3.204 / 0.000 / 7.255 | 4.048 / 0.000 / 8.504 | harness: 4.005s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_23` | 115 | 2.765 / 0.000 / 6.810 | 3.360 / 0.000 / 8.497 | harness: 3.319s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_24` | 115 | 56.055 / 81.206 / 141.698 | 51.754 / 90.898 / 147.779 | harness: 50.443s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_25` | 115 | 49.845 / 70.345 / 125.232 | 46.402 / 79.163 / 131.227 | harness: 45.227s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_27` | 115 | 2.548 / 0.000 / 7.112 | 2.874 / 0.000 / 7.786 | harness: 2.831s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_28` | 115 | 2.502 / 0.000 / 6.946 | 2.924 / 0.000 / 7.698 | harness: 2.879s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_29` | 115 | 2.512 / 0.000 / 7.131 | 2.958 / 0.000 / 7.711 | harness: 2.914s |
| `backend.risk.overlays.x_fit_open_risk__mutmut_31` | 115 | 48.239 / 69.498 / 122.987 | 46.317 / 75.712 / 127.365 | harness: 45.187s |

## fundamentals-callbacks paired observational cohort

These are the same 20 high-estimated-cost literal-bearing candidates, not a claim of the global before-run ranking. Actual slowest completed native mutants are reported from delivery CI. Mapped test sets and fast-tests-first ordering are held fixed; exits are identical. Windows unforked wall includes cold imports/compilation and is not a native gate certificate. Setup/call figures include the same setup cProfile observer in both variants. Host contention and generated Hypothesis examples can vary.

| Mutant ID | Mapped tests | Before setup / call / wall (s) | After setup / call / wall (s) | After dominant setup fixture |
| --- | ---: | ---: | ---: | --- |
| `backend.notifications.callbacks.xǁApprovalGateǁ__init____mutmut_22` | 115 | 55.200 / 80.097 / 183.967 | 49.365 / 88.084 / 188.653 | harness: 48.110s |
| `backend.notifications.callbacks.xǁApprovalGateǁ__init____mutmut_23` | 115 | 55.611 / 79.750 / 183.836 | 49.334 / 87.857 / 188.222 | harness: 48.080s |
| `backend.notifications.callbacks.xǁApprovalGateǁ__init____mutmut_24` | 115 | 56.121 / 80.390 / 185.184 | 49.278 / 89.121 / 189.500 | harness: 48.018s |
| `backend.agents.fundamentals.x__number__mutmut_20` | 168 | 47.798 / 79.998 / 176.781 | 41.929 / 89.879 / 183.588 | harness: 40.742s |
| `backend.agents.fundamentals.x__number__mutmut_21` | 168 | 46.925 / 80.693 / 133.674 | 44.833 / 95.663 / 147.655 | harness: 43.668s |
| `backend.agents.fundamentals.x__number__mutmut_4` | 168 | 46.439 / 81.004 / 134.614 | 44.857 / 95.934 / 149.215 | harness: 43.677s |
| `backend.agents.fundamentals.x__number__mutmut_5` | 168 | 45.987 / 82.008 / 135.126 | 44.004 / 96.090 / 148.790 | harness: 42.813s |
| `backend.agents.fundamentals.x__number__mutmut_6` | 168 | 46.750 / 81.103 / 134.512 | 43.921 / 95.945 / 148.242 | harness: 42.762s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_11` | 157 | 0.005 / 0.001 / 5.173 | 0.007 / 0.001 / 7.615 | isolated_environment: 0.000s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_118` | 157 | 0.020 / 0.008 / 5.465 | 0.027 / 0.013 / 10.027 | isolated_environment: 0.003s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_119` | 157 | 0.028 / 0.014 / 6.524 | 0.026 / 0.012 / 10.031 | isolated_environment: 0.003s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_12` | 157 | 0.005 / 0.001 / 6.843 | 0.005 / 0.002 / 9.978 | isolated_environment: 0.000s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_120` | 157 | 0.021 / 0.009 / 6.893 | 0.028 / 0.012 / 9.464 | isolated_environment: 0.003s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_121` | 157 | 0.021 / 0.009 / 6.281 | 0.025 / 0.011 / 9.938 | isolated_environment: 0.003s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_122` | 157 | 0.021 / 0.009 / 6.117 | 0.027 / 0.015 / 9.992 | isolated_environment: 0.003s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_123` | 157 | 0.021 / 0.009 / 6.566 | 0.026 / 0.011 / 9.968 | isolated_environment: 0.003s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_124` | 157 | 0.021 / 0.009 / 6.725 | 0.032 / 0.014 / 9.786 | isolated_environment: 0.003s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_125` | 157 | 0.025 / 0.013 / 6.376 | 0.028 / 0.012 / 8.069 | isolated_environment: 0.003s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_126` | 157 | 39.610 / 69.623 / 115.170 | 35.671 / 71.292 / 115.656 | harness: 34.666s |
| `backend.agents.fundamentals.x_compute_fundamentals__mutmut_127` | 157 | 38.734 / 70.649 / 114.770 | 35.994 / 71.797 / 116.247 | harness: 35.001s |

## executor-a paired observational cohort

These are the same 20 high-estimated-cost literal-bearing candidates, not a claim of the global before-run ranking. Actual slowest completed native mutants are reported from delivery CI. Mapped test sets and fast-tests-first ordering are held fixed; exits are identical. Windows unforked wall includes cold imports/compilation and is not a native gate certificate. Setup/call figures include the same setup cProfile observer in both variants. Host contention and generated Hypothesis examples can vary.

| Mutant ID | Mapped tests | Before setup / call / wall (s) | After setup / call / wall (s) | After dominant setup fixture |
| --- | ---: | ---: | ---: | --- |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_10` | 60 | 3.147 / 0.031 / 248.278 | 3.167 / 0.030 / 238.982 | harness: 3.100s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_101` | 60 | 29.331 / 61.083 / 335.791 | 26.317 / 59.755 / 322.390 | harness: 25.716s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_102` | 60 | 29.776 / 61.053 / 335.911 | 25.580 / 59.553 / 321.341 | harness: 24.966s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_103` | 60 | 29.969 / 61.349 / 336.590 | 25.729 / 59.170 / 321.138 | harness: 25.123s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_116` | 60 | 2.715 / 0.010 / 4.777 | 2.819 / 0.009 / 4.825 | harness: 2.757s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_118` | 60 | 2.645 / 0.009 / 4.704 | 2.815 / 0.009 / 5.072 | harness: 2.767s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_12` | 60 | 30.863 / 60.625 / 94.004 | 25.903 / 59.726 / 88.247 | harness: 25.294s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_120` | 60 | 30.240 / 59.234 / 92.402 | 25.964 / 60.775 / 89.576 | harness: 25.349s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_121` | 60 | 2.572 / 0.010 / 5.169 | 2.565 / 0.011 / 5.029 | harness: 2.523s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_122` | 60 | 2.524 / 0.010 / 4.941 | 2.607 / 0.010 / 4.826 | harness: 2.562s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_124` | 60 | 29.614 / 60.558 / 92.861 | 25.754 / 61.094 / 89.545 | harness: 25.143s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_126` | 60 | 2.590 / 0.011 / 4.934 | 2.548 / 0.012 / 5.008 | harness: 2.503s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_127` | 60 | 2.784 / 0.010 / 4.978 | 2.791 / 0.012 / 5.074 | harness: 2.746s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_129` | 60 | 2.712 / 0.009 / 5.119 | 2.706 / 0.010 / 5.188 | harness: 2.663s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_13` | 60 | 31.120 / 58.913 / 92.768 | 26.204 / 61.970 / 91.073 | harness: 25.581s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_130` | 60 | 30.152 / 60.526 / 93.174 | 26.546 / 62.329 / 91.641 | harness: 25.921s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_131` | 60 | 30.729 / 62.398 / 95.791 | 27.521 / 61.972 / 92.313 | harness: 26.882s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_134` | 60 | 31.161 / 62.391 / 96.256 | 28.349 / 60.959 / 92.138 | harness: 27.721s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_135` | 60 | 30.207 / 61.344 / 94.165 | 27.845 / 60.270 / 91.060 | harness: 27.235s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ__init____mutmut_136` | 60 | 30.250 / 60.858 / 93.658 | 25.904 / 60.164 / 88.976 | harness: 25.295s |

## executor-b paired observational cohort

These are the same 20 high-estimated-cost literal-bearing candidates, not a claim of the global before-run ranking. Actual slowest completed native mutants are reported from delivery CI. Mapped test sets and fast-tests-first ordering are held fixed; exits are identical. Windows unforked wall includes cold imports/compilation and is not a native gate certificate. Setup/call figures include the same setup cProfile observer in both variants. Host contention and generated Hypothesis examples can vary.

| Mutant ID | Mapped tests | Before setup / call / wall (s) | After setup / call / wall (s) | After dominant setup fixture |
| --- | ---: | ---: | ---: | --- |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_10` | 51 | 2.712 / 0.074 / 240.617 | 2.828 / 0.055 / 245.005 | harness: 2.777s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_11` | 51 | 2.711 / 0.060 / 240.530 | 2.791 / 0.062 / 245.171 | harness: 2.737s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_12` | 51 | 2.792 / 0.070 / 240.632 | 2.809 / 0.066 / 245.177 | harness: 2.757s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_13` | 51 | 2.778 / 0.065 / 240.697 | 2.863 / 0.084 / 245.011 | harness: 2.802s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_14` | 51 | 2.344 / 0.051 / 4.709 | 2.423 / 0.051 / 4.977 | harness: 2.382s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_15` | 51 | 2.314 / 0.049 / 4.627 | 2.396 / 0.050 / 4.941 | harness: 2.355s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_16` | 51 | 2.324 / 0.053 / 4.694 | 2.371 / 0.053 / 4.889 | harness: 2.333s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_17` | 51 | 2.301 / 0.051 / 4.633 | 2.416 / 0.053 / 4.929 | harness: 2.377s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_18` | 51 | 2.356 / 0.050 / 4.753 | 2.423 / 0.046 / 4.656 | harness: 2.381s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_19` | 51 | 2.368 / 0.047 / 4.698 | 2.405 / 0.050 / 4.696 | harness: 2.365s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_20` | 51 | 2.342 / 0.052 / 4.781 | 2.403 / 0.051 / 4.690 | harness: 2.362s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_21` | 51 | 2.320 / 0.053 / 4.754 | 2.435 / 0.056 / 4.706 | harness: 2.393s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_22` | 51 | 2.366 / 0.045 / 4.587 | 2.340 / 0.044 / 4.536 | harness: 2.297s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_23` | 51 | 2.366 / 0.049 / 4.576 | 2.354 / 0.050 / 4.534 | harness: 2.308s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_24` | 51 | 2.327 / 0.055 / 4.678 | 2.309 / 0.053 / 4.508 | harness: 2.268s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_25` | 51 | 2.357 / 0.057 / 4.693 | 2.292 / 0.053 / 4.473 | harness: 2.251s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_26` | 51 | 2.360 / 0.046 / 4.633 | 2.374 / 0.045 / 4.511 | harness: 2.325s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_27` | 51 | 2.328 / 0.064 / 4.645 | 2.391 / 0.048 / 4.562 | harness: 2.350s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_28` | 51 | 2.351 / 0.054 / 4.626 | 2.348 / 0.049 / 4.693 | harness: 2.307s |
| `backend.execution.alpaca_executor.xǁAlpacaExecutorǁ_verify_account__mutmut_29` | 51 | 2.350 / 0.054 / 4.608 | 2.360 / 0.050 / 4.677 | harness: 2.317s |
