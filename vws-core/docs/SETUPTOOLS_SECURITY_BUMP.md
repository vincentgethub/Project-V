# Security bumps - October 24, 2026

Only setuptools 83.0.0 -> 84.1.0, filelock 4.0.12 -> 4.2.1 and virtualenv 21.14.9 -> 21.14.10 are changed. No new dependency, application source, gate, selector, timeout, threshold, kill rule or equivalent allowance changes. AUTO_LIVE locked; MANUAL_CSV disabled; paper only.

## Dependency origins

| Package | Inputs and locks | Dependency purpose |
|---|---|---|
| setuptools | pyproject.toml build-system.requires; runtime and dev locks | Pinned build backend, included by --all-build-deps; dev also lists pip-tools. |
| filelock | Dev lock only | virtualenv, python-discovery and cachecontrol. |
| virtualenv | Dev lock only | pre-commit. |

The only project-input edit is pyproject.toml line 2, setuptools==83.0.0 -> setuptools==84.1.0. No other tracked outside-lock pin remains below the target. The old main CI install log explicitly downloads setuptools 83.0.0 from its old dev lock; its vulnerable copy is not merely an opaque runner seed. Workflows install the hash-pinned dev lock before the editable project using --no-build-isolation.

## Advisories

| Package | Advisory | Fixed target |
|---|---|---|
| setuptools | [GHSA-xmj3-9gf7-h52w](https://github.com/advisories/GHSA-xmj3-9gf7-h52w) | 84.1.0 |
| filelock | [GHSA-v4x8-3wr5-3wq8](https://github.com/advisories/GHSA-v4x8-3wr5-3wq8), CVE-2026-112940 | 4.2.1 |
| filelock | [GHSA-9vhv-jxww-xfm5](https://github.com/advisories/GHSA-9vhv-jxww-xfm5), CVE-2026-112913 | 4.2.1 |
| filelock | [GHSA-567q-5qvw-pf92](https://github.com/advisories/GHSA-567q-5qvw-pf92), CVE-2026-112907 | 4.2.1 |
| virtualenv | [GHSA-4f8h-vr72-p32c](https://github.com/advisories/GHSA-4f8h-vr72-p32c), CVE-2026-113713 | 21.14.10 |

No additional advisories were found in the updated locks. The standing dev-only rule was not needed for another package.

## Setuptools acceptance proof

Uploader identity: **not publicly available**. Trusted Publishing was not used. The owner-approved replacement checks all pass:

- Eight sdist-only files are generated metadata/configuration: PKG-INFO; setup.cfg; setuptools.egg-info/{PKG-INFO,SOURCES.txt,dependency_links.txt,entry_points.txt,requires.txt,top_level.txt}. No extra executable Python/build logic was found. setup.cfg contains only egg_info tag_build (empty) and tag_date = 0.
- All 511 shared sdist/tag files and all 224 wheel Python files match the v84.1.0 tag byte-for-byte.
- The wheel has 343 files: 336 tag-identical, six wheel-only metadata files and one distutils-precedence.pth hook.
- The startup hook is byte-identical in the downloaded, PyPI-hash-verified 83.0.0 and 84.1.0 wheels. Both SHA256 values are sha256:2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07b0dd223da5f5d224. No new startup code is added by this upgrade.
- None of the 46 tag-only paths occurs in the installed wheel (set intersection is empty). Counts by directory: root 12, .github 11, docs 13, setuptools 7, bootstrap.egg-info 2, launcher 1. The launcher CMake file and bootstrap metadata are accepted repo-only build inputs.
- Both lock hash sets exactly equal the wheel and sdist hashes in PyPI JSON.

The upstream tag resolves to 77b7ace0aaf660beeb9b3f9da4aabf21cbcf3fa9. All-path CSV comparisons, sorted wheel/tag/sdist file lists, verified archives and amended-acceptance-proof.json are retained in build/pass7/setuptools-security/source-verification.

## Eight sdist-only file classifications

| File | Classification |
|---|---|
| PKG-INFO | Core distribution metadata. |
| setup.cfg | Generated egg_info version-tag configuration, with empty tag_build and tag_date=0. |
| setuptools.egg-info/PKG-INFO | Core distribution metadata. |
| setuptools.egg-info/SOURCES.txt | Distribution file manifest. |
| setuptools.egg-info/dependency_links.txt | Empty dependency-link metadata (one newline). |
| setuptools.egg-info/entry_points.txt | Entry-point metadata referencing tag source. |
| setuptools.egg-info/requires.txt | Dependencies and extras metadata. |
| setuptools.egg-info/top_level.txt | Package-name metadata. |

## Release provenance and upload times

| Package/file | Trusted publisher | Upload UTC | Younger than three days? |
|---|---|---|---|
| setuptools-84.1.0-py3-none-any.whl | No Trusted Publishing; uploader not publicly available | 2026-10-19T20:11:41.684844Z | No |
| setuptools-84.1.0.tar.gz | No Trusted Publishing; uploader not publicly available | 2026-10-19T20:11:43.489136Z | No |
| filelock-4.2.1-py3-none-any.whl | tox-dev/filelock / release.yaml / release | 2026-10-17T16:48:12.937020Z | No |
| filelock-4.2.1.tar.gz | tox-dev/filelock / release.yaml / release | 2026-10-17T16:48:14.435351Z | No |
| virtualenv-21.14.10-py3-none-any.whl | pypa/virtualenv / release.yaml / release | 2026-10-17T17:31:53.082439Z | No |
| virtualenv-21.14.10.tar.gz | pypa/virtualenv / release.yaml / release | 2026-10-17T17:31:55.115787Z | No |

Filelock and virtualenv target publisher identities match their respective previous releases. Provenance JSON is saved for both wheels and sdists of each old/new release. All target hashes are fetched from PyPI JSON and checked against the generated locks; none is typed in by hand.

## Filelock changelog and caller check

Reviewed [4.0.12 through 4.2.1](https://py-filelock.readthedocs.io/en/latest/changelog.html). Relevant changes: stricter timeout/mode/blocking validation; finite waits honor their deadline; non-created Unix lock files retain contents/permissions; safer soft-lock marker ownership and Windows ACL handling; relative paths stay bound during a hold; interrupted release and singleton/fork cleanup fixes. Other changes concern SQLite reader/writer, lease and async locks. Imports become lazy outside FileLock. Filelock now requires Python >=3.11; this project already requires >=3.11 and verification uses 3.12.14.

Virtualenv uses a FileLock subclass, numeric timeout/poll arguments, acquire/release and context managers; python-discovery uses ordinary FileLock. Pre-commit has its own store file-lock utility and reaches filelock through virtualenv. No removed API used by these paths was found. Fresh venv installation and the existing callers are checked below. No application lock implementation was changed.

## Full compiler output and changed-line classification

The unchanged `python -m scripts.compile_locks` ran under Python 3.12.14 with pip-tools 7.6.1 and its existing flags. Approved target pins/hashes seeded its constraints; both final lockfiles are its complete output, including annotations. No generated version/hash blocks were spliced into old locks.

| Lock | Records before/after | Approved version/hash lines | Comment lines | Other lines |
|---|---:|---:|---:|---:|
| requirements.lock | 62/62 | 6 | 48 | 0 |
| requirements-dev.lock | 141/141 | 18 | 206 | 0 |

Counts include removed and added lines. Every other package/version/hash/marker/option is unchanged. Every changed annotation is listed in the appendix. Classifier and machine-readable per-line evidence are in build/pass7/security-bumps-final.

## Verification

- Runtime pip-audit: exit 0, zero findings.
- Development pip-audit: exit 0, zero findings.

An earlier normal verification was interrupted at 86% during a desktop/tool refresh, with no final summary or coverage result. Its partial log is retained separately and is not counted as PASS. Fresh complete normal/random verification runs independently; the hourly continuation completes the authorized publication and CI report after successful evidence checks. No failed-test retry mechanism was added.

Both fresh suites completed successfully. The private post-run reporter initially compared the ordered perf-deselection list across random order; the same four original cases appeared in a different order. It now compares the exact multiset. Existing JUnit, coverage, source and collection evidence passes; no suite was rerun for that reporting correction and no CI gate, selector or test assertion changed.

### clean-install-results.json

```json
[
  {
    "lock": "requirements.lock",
    "install_exit": 0,
    "pip_check_exit": 0,
    "pip_check": "No broken requirements found."
  },
  {
    "lock": "requirements-dev.lock",
    "install_exit": 0,
    "pip_check_exit": 0,
    "pip_check": "No broken requirements found."
  }
]
```

### checks.json

```json
{
  "ruff_lint": {
    "exit": 0,
    "result": "All checks passed"
  },
  "ruff_format": {
    "exit": 0,
    "files": 475
  },
  "strict_types": {
    "exit": 0,
    "source_files": 432
  },
  "GD_07": {
    "exit": 0
  },
  "Bandit": {
    "exit": 0,
    "findings": 0,
    "scan_errors": 0
  },
  "existing_lock_api_smoke": {
    "passed": true,
    "versions": {
      "setuptools": "84.1.0",
      "filelock": "4.2.1",
      "virtualenv": "21.14.10"
    },
    "production_asserts": []
  },
  "old_wheel_hash_in_original_lock": true,
  "editable_install": {
    "exit": 0,
    "pip_check_exit": 0
  },
  "ci.yml_copies_identical": true,
  "mutation-pilot.yml_copies_identical": true,
  "new_tests_added": 0,
  "tests_removed": 0,
  "gitleaks_precommit": {
    "exit": 0,
    "findings": 0,
    "scope": "complete Git history --all before security commit"
  }
}
```

### suite-proof.json

```json
{
  "normal": {
    "exit": 0,
    "passed": 6737,
    "skipped": 61,
    "deselected": 4,
    "failures": 0,
    "added": 0,
    "removed": 0,
    "unchanged_existing_skip_ids": true,
    "only_original_perf_deselections": true,
    "source_unchanged": true,
    "coverage_percent": 100.0,
    "statements": 9510,
    "branches": 3394,
    "missing_lines": 0,
    "missing_branches": 0,
    "executor": {
      "covered_lines": 1871,
      "num_statements": 1871,
      "percent_covered": 100.0,
      "percent_covered_display": "100",
      "missing_lines": 0,
      "excluded_lines": 12,
      "percent_statements_covered": 100.0,
      "percent_statements_covered_display": "100",
      "num_branches": 784,
      "num_partial_branches": 0,
      "covered_branches": 784,
      "missing_branches": 0,
      "percent_branches_covered": 100.0,
      "percent_branches_covered_display": "100"
    },
    "random_seed": null,
    "wall_seconds": 2564.982
  },
  "random": {
    "exit": 0,
    "passed": 6737,
    "skipped": 61,
    "deselected": 4,
    "failures": 0,
    "added": 0,
    "removed": 0,
    "unchanged_existing_skip_ids": true,
    "only_original_perf_deselections": true,
    "source_unchanged": true,
    "coverage_percent": 100.0,
    "statements": 9510,
    "branches": 3394,
    "missing_lines": 0,
    "missing_branches": 0,
    "executor": {
      "covered_lines": 1871,
      "num_statements": 1871,
      "percent_covered": 100.0,
      "percent_covered_display": "100",
      "missing_lines": 0,
      "excluded_lines": 12,
      "percent_statements_covered": 100.0,
      "percent_statements_covered_display": "100",
      "num_branches": 784,
      "num_partial_branches": 0,
      "covered_branches": 784,
      "missing_branches": 0,
      "percent_branches_covered": 100.0,
      "percent_branches_covered_display": "100"
    },
    "random_seed": 20261021,
    "wall_seconds": 3425.639
  },
  "same_test_multiset_different_order": true
}
```

### commit-proof.json

Pending; not counted as PASS.

### push-receipt.json

Pending; not counted as PASS.

Both ci.yml copies unchanged and byte-identical: True. Current working-byte SHA256: sha256:7d35b1d72280028d86725a176fe9386de4a6d5bd9a78164543444de9b03f94d1.

## CI and diagnostic pilot

[Existing pilot 40067369610](https://github.com/vincentgethub/Project-V/actions/runs/40067369610) and [existing main 40067326239](https://github.com/vincentgethub/Project-V/actions/runs/40067326239) are left untouched. No cancel/rerun/extra dispatch is authorized or performed. Pilot initially queues behind 20 main runners; no concurrency group or plan dependency blocks it. Its artifact steps have if: always(); actual uploads and measurements will be reported from completed run evidence.

Fresh pilot timing median/p95, slowest fingerprints, test-selection counts, whole-suite incidence, exception sample classifications and measured <=90-minute repartition proposal are pending. They are not inferred from historical results. No partition proposal is applied and no extra full mutation rerun is started.

## Dependency diff

```diff
diff --git a/vws-core/pyproject.toml b/vws-core/pyproject.toml
index 5f00b55..271ca18 100644
--- a/vws-core/pyproject.toml
+++ b/vws-core/pyproject.toml
@@ -1,5 +1,5 @@
 [build-system]
-requires = ["setuptools==83.0.0"]
+requires = ["setuptools==84.1.0"]
 build-backend = "setuptools.build_meta"

 [project]
diff --git a/vws-core/requirements-dev.lock b/vws-core/requirements-dev.lock
index 12a286b..cae2ed1 100644
--- a/vws-core/requirements-dev.lock
+++ b/vws-core/requirements-dev.lock
@@ -8,15 +8,15 @@ alpaca-py==0.44.0 \
     --hash=sha256:5388715b67b51ad30fa07308e89299d48b19bed65b81013b8a1158fa5837337b \
     --hash=sha256:b54673f967c0c814a5e0223cbb0211a5d9d75a8d107e792872b14e5bae957c03
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 annotated-types==0.8.0 \
     --hash=sha256:13b2beaad985e05e2d6407ee4c4f35590b11f8d693a258a561055cac8f64cab7 \
     --hash=sha256:f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   pydantic
@@ -24,7 +24,7 @@ anyio==4.15.1 \
     --hash=sha256:6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101 \
     --hash=sha256:9f28306018cbd6d329e64a36d58256edff76dd996fe423bc957326e578b82a94
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   httpx
@@ -34,10 +34,10 @@ apscheduler==3.11.3 \
     --hash=sha256:bbeb2ec02d23d3c06a6c07ed7f0f3939ada6680eb121fae809a69bb42c537a30 \
     --hash=sha256:cd2fcc9330039a81a5893472ad49facf23a6d5604cbe1d918c835c6de7834d5a
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 arrow==1.4.0 \
     --hash=sha256:749f0769958ebdc79c173ff0b0670d59051a535fa26e8eba02953dc19eb43205 \
     --hash=sha256:ed0cc050e98001b8779e84d461b0098c4ac597e88704a655582b21d116e526d7
@@ -117,7 +117,7 @@ bandit==1.9.4 \
     --hash=sha256:f89ffa663767f5a0585ea075f01020207e966a9c0f2b9ef56a57c7963a3f6f8e
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 boolean-py==5.0 \
     --hash=sha256:60cbc4bad079753721d32649545505362c754e121570ada4658b852a3a318d95 \
     --hash=sha256:ef28a70bd43115208441b53a045d1549e2f0ec6e3d08a9d142cbc41c1938e8d9
@@ -141,7 +141,7 @@ certifi==2026.10.19 \
     --hash=sha256:035c1e85572b141bf1c3a3eff0e33a8eb74917522f2559075ff8d2fea780a1ae \
     --hash=sha256:42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   httpcore
@@ -249,7 +249,7 @@ cffi==2.1.1 \
     --hash=sha256:fb92203a88b3d3053034db775110081c49d28be6551923805e039924093761e4 \
     --hash=sha256:fcd22650c908d7b7da162bbfaab594a1227a15d1643a98c68b122ac642fa2264
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   cryptography
@@ -483,7 +483,7 @@ charset-normalizer==3.5.2 \
     --hash=sha256:fd1fbe0f116b6e55da77aca2c6ddcddcfac2186cbf78bdebf40fc156efca389d \
     --hash=sha256:fe9753dfee015c570d73df76f899f18444d41388bffcde097deba51c4fadbb9f
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   requests
@@ -689,17 +689,17 @@ cryptography==50.0.2 \
     --hash=sha256:fa8f5efb344d6908a1ce62f4a24e2e5780f825d6f53f5f50ec5ffacac72936cb \
     --hash=sha256:fdd28f912fccfec1846a94e2e1e8f9b0012f557f0c46fe4f3eb0d7a87afcf90b
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
     #   secretstorage
 cyclonedx-bom==7.5.0 \
     --hash=sha256:396cc8c9cb7533d25a21f930b45d2699a1839e3ba2be9ba88f8bd61c566b51dc \
     --hash=sha256:a3020e225107214a66cb9c79ae83e3a71640a06d4ff3a0e2f9cb0d238f7061fd
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 cyclonedx-python-lib==11.12.0 \
     --hash=sha256:0e807521a921a5c3cb8ce1153f8a61d29eedfe76a46aac2796b7c6b573391a54 \
     --hash=sha256:16767c4039de90c04e9f03348f8f0ed4b8ff842eaa7eefcad3a95685f970dacf
@@ -718,7 +718,7 @@ detect-secrets==1.5.0 \
     --hash=sha256:e24e7b9b5a35048c313e983f76c4bd09dad89f045ff059e354f9943bf45aa060
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 distlib==0.4.3 \
     --hash=sha256:4b0ce306c966eb73bc3a7b6abad017c556dadd92c44701562cd528ac7fde4d5b \
     --hash=sha256:f152097224a0ae24be5a0f6bae1b9359af82133bce63f98a95f86cae1aede9ed
@@ -729,29 +729,29 @@ exchange-calendars==4.13.2 \
     --hash=sha256:a9459425dd64142cd54fbc639847403c7e0c33d60fbc326c94fc1d6bd127f002 \
     --hash=sha256:fc5a2ad0d61b5c3a6539a3061cd4cbb55c59f4a903455cec7926e4b798919996
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 feedparser==6.0.14 \
     --hash=sha256:088679b0c4b543ee211a820dd544698c76a402122eae7473c04a43425f283d06 \
     --hash=sha256:e35e3f760151b0c3b22cac9684155cae186a233e16c49bcbc6c49e91e3131137
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 feedparser-sgmllib==2.1.0 \
     --hash=sha256:2cab2d43b95a954f920f18aebce7a4dbbb3f539780b127e2aa114f579821e01d \
     --hash=sha256:61facf2918c4389b5b00714f76c5e03431ffcd94cd1f51d657edd6cd7c396579
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   feedparser
-filelock==4.0.12 \
-    --hash=sha256:5f17ee83ecee8a6f3e389c75822fb70a1c2f0506b99438a6dffa1d56793588c8 \
-    --hash=sha256:cf42711a7ac791818b299fab0332a088c65aeeefa36290de98db92c434303b0c
+filelock==4.2.1 \
+    --hash=sha256:7be2662e9e826b9bba28afc0f843a123280d799a2ea44bb5d35ccec67905ae44 \
+    --hash=sha256:c4c937ccac2a813cee448e662a56366cfb374c0f8702e75f295c412cc1c5d5a3
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   cachecontrol
@@ -844,7 +844,7 @@ greenlet==3.5.6 \
     --hash=sha256:fe3170a69fe039b18ad18171e66faa9a75f6fe9d78f968fd9b54e09fbd714d81 \
     --hash=sha256:fea4427d1ffdb3b523d7daa6712038428a4c16c450b9777bdd1221cfee0eab49
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   sqlalchemy
@@ -852,7 +852,7 @@ h11==0.16.0 \
     --hash=sha256:4e35b956cf45792e4caa5885e69fba00bdbc6ffafbfa020300e549b208ee5ff1 \
     --hash=sha256:63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   httpcore
@@ -861,7 +861,7 @@ httpcore==1.0.9 \
     --hash=sha256:2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55 \
     --hash=sha256:6e34463af53fd2ab5d807f399a9b45ea31c3dfa2276f15a2c3f00afff6e176e8
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   httpx
@@ -869,7 +869,7 @@ httpcore2==2.13.1 \
     --hash=sha256:e0aa977abe17e69a3b820a24542a6fa88702676d83880b8d194dcd18408e5103 \
     --hash=sha256:e1e05d4f25f7d7d496bfb96748f6f4b67657b03da069b3a68c36069f3db73d0a
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   httpx2
@@ -877,16 +877,16 @@ httpx==0.28.1 \
     --hash=sha256:75e98c5f16b0f35b567856f597f06ff2270a374470a5c2392242528e3e3e42fc \
     --hash=sha256:d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   python-telegram-bot
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 httpx2==2.13.1 \
     --hash=sha256:6dff50fabc270ee5fd25d845d0b078ed20564579744d6d962850975996d2f9a4 \
     --hash=sha256:e48744a19e3af5ee48313d0ce5fe941d5422fae5705ea922a4aabf94d7800dfa
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   openai
@@ -978,7 +978,7 @@ hypothesis==6.168.3 \
     --hash=sha256:fd81241f4cd76fb18d481e87b9688b30a0cb5c30841730513323ba1c7aba1837
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 identify==2.6.20 \
     --hash=sha256:6a16b69b93187244e0548cbfd25b3e4a6f9a7a2ad784625c3bec2b8d27b81aaa \
     --hash=sha256:ad729860a923858d26917c2f4fb0a1d83d27a75b1e090c06440c573f048f3285
@@ -989,7 +989,7 @@ idna==3.20 \
     --hash=sha256:a7db850025b95ded1eae8a46181a1a6c56c92c96f0e2b005d9ff8dc0210cab44 \
     --hash=sha256:ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   anyio
@@ -1013,7 +1013,7 @@ jaraco-classes==3.4.0 \
     --hash=sha256:47a024b51d0239c0dd8c8540c6c7f484be3b8fcf0b2d85c13825780d3b3f3acd \
     --hash=sha256:f662826b6bed8cace05e7ff873ce0f9283b5c924470fe664fff1c2f00f581790
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   keyring
@@ -1021,7 +1021,7 @@ jaraco-context==6.1.2 \
     --hash=sha256:bf8150b79a2d5d91ae48629d8b427a8f7ba0e1097dd6202a9059f29a36379535 \
     --hash=sha256:f1a6c9d391e661cc5b8d39861ff077a7dc24dc23833ccee564b234b81c82dfe3
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   keyring
@@ -1029,7 +1029,7 @@ jaraco-functools==4.6.0 \
     --hash=sha256:880c577ec9720b3a052d5bc611fb9f2269b3d87902ef42440df443b88e443280 \
     --hash=sha256:99e3dc0060c5cbe8fcd1cdb36258e2a65ca40f1566b2033b12abb1bb44dd3c30
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   keyring
@@ -1037,10 +1037,10 @@ jeepney==0.9.0 \
     --hash=sha256:97e5714520c16fc0a45695e5365a2e11b81ea79bba796e26f9f1d178cb182683 \
     --hash=sha256:cf0e9e845622b81e4a28df94c40345400256ec608d0e55bb8a3feaa9163f5732
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
     #   secretstorage
 jiter==0.17.0 \
     --hash=sha256:00b5a98df3e3a3e8cf7b619f4ac2f8bf975bbf3d95d02c5d17b8dbfe5c8b8245 \
@@ -1163,7 +1163,7 @@ jiter==0.17.0 \
     --hash=sha256:fe15ddf316f1f1f643347d3a474e74ce61880c79a11ec5dca53df20c071bd3e8 \
     --hash=sha256:ffa0380ad091de7d3fc33e17a97ff479851ee18a0a2a3ee56ff3215cdc886656
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   openai
@@ -1189,15 +1189,15 @@ keyring==25.7.0 \
     --hash=sha256:be4a0b195f149690c166e850609a477c532ddbfbaed96a404d4e43f8d5e2689f \
     --hash=sha256:fe01bd85eb3f8fb3dd0405defdeac9a5b4f6f0439edbb3149577f244a2e8245b
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 korean-lunar-calendar==0.4.0 \
     --hash=sha256:be56f27bc0594fdbbdf7bbe00f504a9f929a31e311bd7d9bb93561b645afade7 \
     --hash=sha256:c042e20de0bb702add6bec8d0f6da1ea8d3b170838e63846f70420cf341fe4e7
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   exchange-calendars
@@ -1632,7 +1632,7 @@ more-itertools==11.1.0 \
     --hash=sha256:48e8f4d9e7e5878571ecf6f2b4e57634f93cd474cc8cfbd2376f2d11b396e30d \
     --hash=sha256:4b65538ae22f6fed0ce4874efd317463a7489796a0939fa66824dd542125a192
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   jaraco-classes
@@ -1730,7 +1730,7 @@ msgpack==1.2.3 \
     --hash=sha256:fafc3b8898b432b841d30a61082c599fa7f4d06885f9dc58ad72259e12059fa6 \
     --hash=sha256:fcc6800daac4922960f6eeb7a0dda3dd4105e0bf7bce0e83ebc465a78cb7bdba
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   alpaca-py
@@ -1740,7 +1740,7 @@ mutmut==3.8.0 \
     --hash=sha256:bc670276518f893ab356f1d28826c49b7e606e7cf89c300e3888c0b52fc1d2ed
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 mypy==2.4.0 \
     --hash=sha256:058165f564ccf559c68c70fec2091fca5891110480210c22594635e3f6683437 \
     --hash=sha256:0bb95cf34899e4619c61ab0a8667804e139e580b30d5df12af2102dfe44d0c97 \
@@ -1796,7 +1796,7 @@ mypy==2.4.0 \
     --hash=sha256:ffda5244fd1ad71a1e54405e35f50d09b80c3978efa120f58bd1252ae32c62d2
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 mypy-extensions==1.1.0 \
     --hash=sha256:1be4cccdb0f2482337c4743e60421de3a356cd97508abadd57d47403e94f5505 \
     --hash=sha256:52e68efc3284861e772bbcd66823fde5ae21fd2fdb51c62a211403730b916558
@@ -1813,7 +1813,7 @@ nulltype==2.3.1 \
     --hash=sha256:16ae565745118e37e0558441f5821c76351d8c3a789640b5bca277cf65b2271b \
     --hash=sha256:64aa3cb2ab5e904d1b37175b9b922bea268c13f9ce32e3d373313150ab5ef272
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   plaid-python
@@ -1885,21 +1885,21 @@ numpy==2.5.3 \
     --hash=sha256:fc36dc566135b5eceec4cf89758fcb719266a019ef07dae1754ae7c9f617ef3e \
     --hash=sha256:ffdc76bfcae6b255dff75202c5e7feaf95b40246bc0a17944facc1fecf9f79ab
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   exchange-calendars
     #   pandas
     #   pandas-stubs
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 openai==3.24.0 \
     --hash=sha256:1e7463f7d78773ab2ce4fe85710481aa5bd5ffefd54c8de4b067506cd2d42895 \
     --hash=sha256:b59703a3e3b5df78b269e90049d383a1dda58c90104cc4be59db21078db4b7a4
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 packageurl-python==0.17.6 \
     --hash=sha256:1252ce3a102372ca6f86eb968e16f9014c4ba511c5c37d95a7f023e2ca6e5c25 \
     --hash=sha256:31a85c2717bc41dd818f3c62908685ff9eebcb68588213745b14a6ee9e7df7c9
@@ -1979,18 +1979,18 @@ pandas==3.0.6 \
     --hash=sha256:fb625f426b375bcc96e3a04c5d5d266cd7be6ae5d6866e0e703382ab5164068c \
     --hash=sha256:ff51a4459ed036e93d1eb1bb5e6e7b28685d3cb6b7c12b91c05b31024e234729
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   alpaca-py
     #   exchange-calendars
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pandas-stubs==3.0.5.260914 \
     --hash=sha256:39a1300c5c5c55fdf609e3476805decce5d5015539a4dcb683449f8feaeee2fb \
     --hash=sha256:3f6fc1f147f68fd89c007105e7c94a948acb4ecd7eb20dc1c02e153c4ed5c250
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pathspec==1.1.1 \
     --hash=sha256:17db5ecd524104a120e173814c90367a96a98d07c45b2e10c2f3919fff91bf5a \
     --hash=sha256:a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189
@@ -2008,7 +2008,7 @@ pip-audit==2.10.1 \
     --hash=sha256:99ef3f600a317c1945f1e89e227ef26e1c2d618429b8bd3fa6f4f7c440c4611a
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pip-requirements-parser==32.0.1 \
     --hash=sha256:4659bc2a667783e7a15d190f6fccf8b2486685b6dba4c19c3876314769c57526 \
     --hash=sha256:b4fa3a7a0be38243123cf9d1f3518da10c51bdb165a2b2985566247f9155a7d3
@@ -2021,14 +2021,14 @@ pip-tools==7.6.1 \
     --hash=sha256:695556edeb647eb94ee8345cc7108657fdb7fb16b3876623a399b4f61bbede01
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 plaid-python==45.0.0 \
     --hash=sha256:e884aa3f54c86c8433c07dff2de14cf5c365a9618c029a77dd5c5ca61928842e
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 platformdirs==4.12.3 \
     --hash=sha256:080f3b39423b5abfca9a23d84c4e9795f54d395cd8459867a8ded44084fcd5f8 \
     --hash=sha256:427fc0bb321ae0c5b037fa03238ca74820437be162e78b4848c4d4055b9b766c
@@ -2049,15 +2049,15 @@ pre-commit==4.6.2 \
     --hash=sha256:e2dde9a75d3bce11bd3831c26d134df00a2803c1d818be6a0383c3dcda25dc4e
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 psycopg==3.3.6 \
     --hash=sha256:a1db9f7148b06a28606767efaca51fa6f9398c5c0a3810519be69d7000bdb631 \
     --hash=sha256:c081f2250df751a943036e42db6df4571c66cd0aabe8291a7a506512b12007d2
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 psycopg-binary==3.3.6 \
     --hash=sha256:05a83ac9fd52b9bca7cb5ab04b3691163170bd16f53defa27216ea3aa07ee781 \
     --hash=sha256:0a52991594ac4db888c7d39bccef331797e30cb31a95cae02cf2607f83a42dc2 \
@@ -2126,7 +2126,7 @@ psycopg-binary==3.3.6 \
     --hash=sha256:fa34eb47969297471db7b7f193622c7e3ee839ec05abd05f1fe104d5b1b1dcf4 \
     --hash=sha256:fdccb3a0e184b03e9baa673b15a809cf36c339c85dbda0ebc25a698846dfbee8
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   psycopg
@@ -2140,7 +2140,7 @@ pycparser==3.0 \
     --hash=sha256:600f49d217304a5902ac3c37e1281c9fe94e4d0489de643a9504c5cdfdfc6b29 \
     --hash=sha256:b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   cffi
@@ -2148,13 +2148,13 @@ pydantic==2.13.5 \
     --hash=sha256:346a034f080da3755d8e9cb5e00e8b07de1d39e4f6e2c87d8ab7cafa0b269a73 \
     --hash=sha256:51a9c5f7b2f8e636f04c6cada605d9b6a3bf1348fdf945a3d8869b19bba0ee08
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   alpaca-py
     #   openai
     #   pydantic-settings
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pydantic-core==2.46.5 \
     --hash=sha256:013d6f3483d81e02e7c328831808f336c8596ee33b4bd4026b9ffb1e960b8942 \
     --hash=sha256:03b9666e41e35d8909852ba191a0607520f81b74eaf12ccf8737005dbb313821 \
@@ -2277,7 +2277,7 @@ pydantic-core==2.46.5 \
     --hash=sha256:fc8515076c11f3cfdf4fb142dcca0fe384b1230a3b5415458ac84f3e0903ec13 \
     --hash=sha256:ff218293c9c806138dca139765e3b067621be52bcd93cdc14c7711be7ddc90a9
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   pydantic
@@ -2285,10 +2285,10 @@ pydantic-settings==2.15.0 \
     --hash=sha256:0ba092c291c94baceb5eff768aa0d56400a457585bc0175925a5a5510303da42 \
     --hash=sha256:694b793e84f766ba76a90ebdefc01d0a9a045dab0382bee70393da93712ad117
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pygments==2.21.0 \
     --hash=sha256:2363c69b61c4a97c838da3b130dcd6468f4848992b21a82f2a63ec34377137d9 \
     --hash=sha256:610ca751c9bc2492b38eb9a38a7fbc93edbbb2d7182edaf34e66ae493dee5c8c
@@ -2301,7 +2301,7 @@ pyluach==2.3.0 \
     --hash=sha256:4497b731aef59508b079dbf5f00bc5bf4329ac45090a6cd37b5a83756f0e69ab \
     --hash=sha256:ec6e30669d1df50c9ca160486da44a8195bb4c7a5d3d533990d0c5b03accd281
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   exchange-calendars
@@ -2327,30 +2327,30 @@ pytest==9.1.1 \
     #   pytest-asyncio
     #   pytest-cov
     #   pytest-socket
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pytest-asyncio==1.4.0 \
     --hash=sha256:933ca923a23075a87fb7070c0ec272a6848489824d887c85c812670932835aa1 \
     --hash=sha256:c6c0d2259945122819f171a32ecea2c349ead889ee28176caaf492143424be42
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pytest-cov==7.1.0 \
     --hash=sha256:30674f2b5f6351aa09702a9c8c364f6a01c27aae0c1366ae8016160d1efc56b2 \
     --hash=sha256:a0461110b7865f9a271aa1b51e516c9a95de9d696734a2f71e3e78f46e1d4678
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pytest-socket==0.8.1 \
     --hash=sha256:2f57787914ad2e1308d09ce141b95c3e55741fbb4fb7b7556593a6b063e0c9c7 \
     --hash=sha256:f9846bed1dcd96eed459e5e14795bbaf96715cf4e827891fe70773817ecb8ed4
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 python-dateutil==2.9.0.post0 \
     --hash=sha256:37dd54208da7e1cd875388217d5e00ebd4179249f90fb72437e91a35459a0ad3 \
     --hash=sha256:a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   arrow
@@ -2366,7 +2366,7 @@ python-dotenv==1.2.4 \
     --hash=sha256:42269a8a5b3fd54ffa6f3d84b18abed50064717576b4ecf03dc4a55d8aa04fdc \
     --hash=sha256:f0d53e69935a851c0dcc78f3ab7aaccd8cabef0b92382b576b824212902873c0
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   pydantic-settings
@@ -2374,15 +2374,15 @@ python-telegram-bot==22.8 \
     --hash=sha256:42373918097f1b837cc4e717d588c19ea79651497ec712bb5b0c76e5e63c50e1 \
     --hash=sha256:f9d3847fcb23ee603477e442800b33bb4adf851a73e0619d2050be879decf1ef
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pytz==2026.5 \
     --hash=sha256:e658af3757f9e26a9d25dd2aff38335acd92bc9104f890a894b2c1ba28311b03 \
     --hash=sha256:fa23724b9c486543b9ff54a327ee7569ac83ade54bb9afd0fc18676620401c86
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   alpaca-py
@@ -2390,7 +2390,7 @@ pywin32-ctypes==0.2.3 \
     --hash=sha256:8a1513379d709975552d202d942d9837758905c8d01eb82b8bcc30918929e7b8 \
     --hash=sha256:d162dc04946d704503b2edc4d55f3dba5c1d539ead017afa00142c38b9885755
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   keyring
@@ -2469,14 +2469,14 @@ pyyaml==6.0.3 \
     --hash=sha256:fa160448684b4e94d80416c0fa4aac48967a969efe22931448d853ada8baf926 \
     --hash=sha256:fc09d0aa354569bc501d4e787133afc08552722d3ab34836a80547331bb5d4a0
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   bandit
     #   detect-secrets
     #   libcst
     #   pre-commit
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 referencing==0.37.0 \
     --hash=sha256:381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231 \
     --hash=sha256:44aefc3142c5b842538163acb373e24cce6632bd54bdb01b21ad5863489f50d8
@@ -2489,14 +2489,14 @@ requests==2.34.2 \
     --hash=sha256:2a0d60c172f83ac6ab31e4554906c0f3b3588d37b5cb939b1c061f4907e278e0 \
     --hash=sha256:f288924cae4e29463698d6d60bc6a4da69c89185ad1e0bcc4104f584e960b9ed
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   alpaca-py
     #   cachecontrol
     #   detect-secrets
     #   pip-audit
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 rfc3339-validator==0.1.4 \
     --hash=sha256:138a2abdf93304ad60530167e51d2dfb9549521a836871b88d7f4695d0022f6b \
     --hash=sha256:24f6ec1eda14ef823da9e36ec7113124b39c04d50a4d3d3a3c2859577e7791fa
@@ -2677,15 +2677,15 @@ ruff==0.16.10 \
     --hash=sha256:f33f43a864a8483eebd160e713336c8bab02c934feaff0a33cf5ccb41546d09a
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 secretstorage==3.5.0 \
     --hash=sha256:0ce65888c0725fcb2c5bc0fdb8e5438eece02c523557ea40ce0703c266248137 \
     --hash=sha256:f04b8e4689cbce351744d5537bf6b1329c6fc68f91fa666f60a380edddcd11be
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 setproctitle==1.3.8 \
     --hash=sha256:09cb645c6ae440286391e256203fc03522b3b0f55fda8219f698abb5c447cce7 \
     --hash=sha256:0a582308ba43afa7233d28243d9d1212e11c81d3c187a43929ec0cb70c4781c5 \
@@ -2794,7 +2794,7 @@ six==1.17.0 \
     --hash=sha256:4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274 \
     --hash=sha256:ff70335d468e7eb6ec65b95b99d3a2836546063f63acc5171de367e834932a81
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   python-dateutil
@@ -2803,7 +2803,7 @@ sniffio==1.3.1 \
     --hash=sha256:2f6da418d1f1e0fddd844478f41680e794e6051915791a034ff65e5f100525a2 \
     --hash=sha256:f4324edc670a0f49750a81b895f35c3adb843cca46f0530f79fc1babb23789dc
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   openai
@@ -2874,14 +2874,14 @@ sqlalchemy==2.0.54 \
     --hash=sha256:f8cc6532f930c27974e9239e5ce5abebe7600ba9807cea4fcf42f1b6cab18fe7 \
     --hash=sha256:ffba7eb2d67c7505e82a0902aa854d8824b74c28a183820d6a8bd3cfd0f812c2
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 sseclient-py==1.9.0 \
     --hash=sha256:340062b1587fc2880892811e2ab5b176d98ef3eee98b3672ff3a3ba1e8ed0f6f
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   alpaca-py
@@ -2895,18 +2895,18 @@ structlog==26.1.0 \
     --hash=sha256:e081a26d6c373e6d201eca24eede26d8ffab07f88f477822e679183428d3d91e \
     --hash=sha256:f63a716cbd1b1291cf7661de7794b455acfa4c43c5bcf1630e6ad5ddc1adb3b7
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 tenacity==9.1.4 \
     --hash=sha256:6095a360c919085f28c6527de529e76a06ad89b23659fa881ae0649b867a9d55 \
     --hash=sha256:adb31d4c263f2bd041081ab33b498309a57c77f9acf2db65aadf0898179cf93a
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 textual==8.2.8 \
     --hash=sha256:267375fd402dc8d981457212efa71f0e3365fd17bba144ba9bb3ed7563cb374a \
     --hash=sha256:3f106a9fbc73e39dd266c9712432087de78a6d644084c7c241d6a25c3169115b
@@ -2974,7 +2974,7 @@ toolz==1.1.0 \
     --hash=sha256:15ccc861ac51c53696de0a5d6d4607f99c210739caf987b5d2054f3efed429d8 \
     --hash=sha256:27a5c770d068c110d9ed9323f24f1543e83b2f300a687b7891c1a6d56b697b5b
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   exchange-calendars
@@ -2982,7 +2982,7 @@ truststore==0.10.4 \
     --hash=sha256:9d91bd436463ad5e4ee4aba766628dd6cd7010cf3e2461756b3303710eebc301 \
     --hash=sha256:adaeaecf1cbb5f4de3b1959b42d41f6fab57b2b1666adb59e89cb0b53361d981
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   httpcore2
@@ -2992,18 +2992,18 @@ types-pyyaml==6.0.12.20260906 \
     --hash=sha256:f59c1cc05010b833d2d72287bbaa72610106b28d42d89a907313117faba85212
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 types-requests==2.32.4.20250913 \
     --hash=sha256:78c9c1fffebbe0fa487a418e0fa5252017e9c60d1a2da394077f1780f655d7e1 \
     --hash=sha256:abd6d4f9ce3a9383f269775a9835a4c24e5cd6b9f647d64f88aa4613c33def5d
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 typing-extensions==4.16.0 \
     --hash=sha256:481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8 \
     --hash=sha256:dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   anyio
@@ -3023,7 +3023,7 @@ typing-inspection==0.4.4 \
     --hash=sha256:547274fa6b0a561ccf549cc9524b999a578e737d015d8709d021f9d0d13bea47 \
     --hash=sha256:65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   pydantic
@@ -3032,20 +3032,20 @@ tzdata==2026.5 \
     --hash=sha256:8cc73c0a0bfca7dbfa59235d60b2eff82231dee33f53d206db1acd9173cfc0a7 \
     --hash=sha256:b683bd1b6659ddcd810ff02ad09ba821d4bf1065072805063eb35c49617905ac
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   arrow
     #   exchange-calendars
     #   pandas
     #   psycopg
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
     #   tzlocal
 tzlocal==5.4.4 \
     --hash=sha256:8dbb8660838688a7b6ba4fed31d18dedf842afb4d47ca050d6d891c2c15f3be4 \
     --hash=sha256:aae09f0126a8a86fa736be266eb4a471380d26a0de3bc14844e7821fee3e2a15
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   apscheduler
@@ -3059,15 +3059,15 @@ urllib3==2.8.0 \
     --hash=sha256:0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3 \
     --hash=sha256:63bf2ead4c879426ebf22ef2a781eeb4aa3b4ae798a0435506f8687fd5bb9b63
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   plaid-python
     #   requests
     #   types-requests
-virtualenv==21.14.9 \
-    --hash=sha256:4d1bee354cd81c820da3bee56e38be3426490f8d1fc54e10ea5b2072ebad8ef8 \
-    --hash=sha256:ac51744da66ae56ff814b087d65096c94de698ec520adc624b108b679655809b
+virtualenv==21.14.10 \
+    --hash=sha256:bf4a0f9671731d097e017e41280aa05e1e1adcd536b0e804fceb3179947ad50e \
+    --hash=sha256:f733501a49404c91b5bb1d34d107073b8f4b93a9a1ddb7e9a950eb8ce60f38ad
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   pre-commit
@@ -3227,7 +3227,7 @@ websockets==17.2 \
     --hash=sha256:fb78fb4158c12f77a934a003006784108a27a6553cfc0c6f10483c9c02e94f48 \
     --hash=sha256:fcce735ffd72ac4056db05325d9f0232382b74826f0196eb6a15ca903abdaa0f
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   alpaca-py
@@ -3246,12 +3246,12 @@ pip==26.2.1 \
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   pip-api
     #   pip-tools
-setuptools==83.0.0 \
-    --hash=sha256:025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef \
-    --hash=sha256:29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3
+setuptools==84.1.0 \
+    --hash=sha256:23657205b63d4d31395ab917815247f694aafad28cd21316bf5fd45a51048ea0 \
+    --hash=sha256:5231689c6ac8156cd155cfb98c3fd6fb252c3e7e9bd3d78b64d3c55f132624c9
     # via
-    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
+    #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   pip-tools
-    #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-z7kxt28r\pyproject.toml::build-system.requires)
+    #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-4dwfs0dt\pyproject.toml::build-system.requires)
diff --git a/vws-core/requirements.lock b/vws-core/requirements.lock
index d3ef9ae..6ebde45 100644
--- a/vws-core/requirements.lock
+++ b/vws-core/requirements.lock
@@ -10,7 +10,7 @@ alpaca-py==0.44.0 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 annotated-types==0.8.0 \
     --hash=sha256:13b2beaad985e05e2d6407ee4c4f35590b11f8d693a258a561055cac8f64cab7 \
     --hash=sha256:f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0
@@ -33,7 +33,7 @@ apscheduler==3.11.3 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 certifi==2026.10.19 \
     --hash=sha256:035c1e85572b141bf1c3a3eff0e33a8eb74917522f2559075ff8d2fea780a1ae \
     --hash=sha256:42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b
@@ -388,7 +388,7 @@ cryptography==50.0.2 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
     #   secretstorage
 exchange-calendars==4.13.2 \
     --hash=sha256:a9459425dd64142cd54fbc639847403c7e0c33d60fbc326c94fc1d6bd127f002 \
@@ -396,14 +396,14 @@ exchange-calendars==4.13.2 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 feedparser==6.0.14 \
     --hash=sha256:088679b0c4b543ee211a820dd544698c76a402122eae7473c04a43425f283d06 \
     --hash=sha256:e35e3f760151b0c3b22cac9684155cae186a233e16c49bcbc6c49e91e3131137
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 feedparser-sgmllib==2.1.0 \
     --hash=sha256:2cab2d43b95a954f920f18aebce7a4dbbb3f539780b127e2aa114f579821e01d \
     --hash=sha256:61facf2918c4389b5b00714f76c5e03431ffcd94cd1f51d657edd6cd7c396579
@@ -524,7 +524,7 @@ httpx==0.28.1 \
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   python-telegram-bot
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 httpx2==2.13.1 \
     --hash=sha256:6dff50fabc270ee5fd25d845d0b078ed20564579744d6d962850975996d2f9a4 \
     --hash=sha256:e48744a19e3af5ee48313d0ce5fe941d5422fae5705ea922a4aabf94d7800dfa
@@ -569,7 +569,7 @@ jeepney==0.9.0 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
     #   secretstorage
 jiter==0.17.0 \
     --hash=sha256:00b5a98df3e3a3e8cf7b619f4ac2f8bf975bbf3d95d02c5d17b8dbfe5c8b8245 \
@@ -701,7 +701,7 @@ keyring==25.7.0 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 korean-lunar-calendar==0.4.0 \
     --hash=sha256:be56f27bc0594fdbbdf7bbe00f504a9f929a31e311bd7d9bb93561b645afade7 \
     --hash=sha256:c042e20de0bb702add6bec8d0f6da1ea8d3b170838e63846f70420cf341fe4e7
@@ -892,14 +892,14 @@ numpy==2.5.3 \
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   exchange-calendars
     #   pandas
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 openai==3.24.0 \
     --hash=sha256:1e7463f7d78773ab2ce4fe85710481aa5bd5ffefd54c8de4b067506cd2d42895 \
     --hash=sha256:b59703a3e3b5df78b269e90049d383a1dda58c90104cc4be59db21078db4b7a4
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pandas==3.0.6 \
     --hash=sha256:0704044b676496b8350e023b09f174a26772456c974a2b11c36bebb558c9490d \
     --hash=sha256:085e3786ae6b2e82b406266bce36690f72b9dc1421903ba9296b2981a9fcf586 \
@@ -964,20 +964,20 @@ pandas==3.0.6 \
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   alpaca-py
     #   exchange-calendars
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 plaid-python==45.0.0 \
     --hash=sha256:e884aa3f54c86c8433c07dff2de14cf5c365a9618c029a77dd5c5ca61928842e
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 psycopg==3.3.6 \
     --hash=sha256:a1db9f7148b06a28606767efaca51fa6f9398c5c0a3810519be69d7000bdb631 \
     --hash=sha256:c081f2250df751a943036e42db6df4571c66cd0aabe8291a7a506512b12007d2
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 psycopg-binary==3.3.6 \
     --hash=sha256:05a83ac9fd52b9bca7cb5ab04b3691163170bd16f53defa27216ea3aa07ee781 \
     --hash=sha256:0a52991594ac4db888c7d39bccef331797e30cb31a95cae02cf2607f83a42dc2 \
@@ -1065,7 +1065,7 @@ pydantic==2.13.5 \
     #   alpaca-py
     #   openai
     #   pydantic-settings
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pydantic-core==2.46.5 \
     --hash=sha256:013d6f3483d81e02e7c328831808f336c8596ee33b4bd4026b9ffb1e960b8942 \
     --hash=sha256:03b9666e41e35d8909852ba191a0607520f81b74eaf12ccf8737005dbb313821 \
@@ -1197,7 +1197,7 @@ pydantic-settings==2.15.0 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pyluach==2.3.0 \
     --hash=sha256:4497b731aef59508b079dbf5f00bc5bf4329ac45090a6cd37b5a83756f0e69ab \
     --hash=sha256:ec6e30669d1df50c9ca160486da44a8195bb4c7a5d3d533990d0c5b03accd281
@@ -1226,7 +1226,7 @@ python-telegram-bot==22.8 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 pytz==2026.5 \
     --hash=sha256:e658af3757f9e26a9d25dd2aff38335acd92bc9104f890a894b2c1ba28311b03 \
     --hash=sha256:fa23724b9c486543b9ff54a327ee7569ac83ade54bb9afd0fc18676620401c86
@@ -1318,7 +1318,7 @@ pyyaml==6.0.3 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 requests==2.34.2 \
     --hash=sha256:2a0d60c172f83ac6ab31e4554906c0f3b3588d37b5cb939b1c061f4907e278e0 \
     --hash=sha256:f288924cae4e29463698d6d60bc6a4da69c89185ad1e0bcc4104f584e960b9ed
@@ -1326,14 +1326,14 @@ requests==2.34.2 \
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
     #   alpaca-py
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 secretstorage==3.5.0 \
     --hash=sha256:0ce65888c0725fcb2c5bc0fdb8e5438eece02c523557ea40ce0703c266248137 \
     --hash=sha256:f04b8e4689cbce351744d5537bf6b1329c6fc68f91fa666f60a380edddcd11be
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 six==1.17.0 \
     --hash=sha256:4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274 \
     --hash=sha256:ff70335d468e7eb6ec65b95b99d3a2836546063f63acc5171de367e834932a81
@@ -1410,7 +1410,7 @@ sqlalchemy==2.0.54 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 sseclient-py==1.9.0 \
     --hash=sha256:340062b1587fc2880892811e2ab5b176d98ef3eee98b3672ff3a3ba1e8ed0f6f
     # via
@@ -1423,14 +1423,14 @@ structlog==26.1.0 \
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 tenacity==9.1.4 \
     --hash=sha256:6095a360c919085f28c6527de529e76a06ad89b23659fa881ae0649b867a9d55 \
     --hash=sha256:adb31d4c263f2bd041081ab33b498309a57c77f9acf2db65aadf0898179cf93a
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
 toolz==1.1.0 \
     --hash=sha256:15ccc861ac51c53696de0a5d6d4607f99c210739caf987b5d2054f3efed429d8 \
     --hash=sha256:27a5c770d068c110d9ed9323f24f1543e83b2f300a687b7891c1a6d56b697b5b
@@ -1477,7 +1477,7 @@ tzdata==2026.5 \
     #   exchange-calendars
     #   pandas
     #   psycopg
-    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
+    #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
     #   tzlocal
 tzlocal==5.4.4 \
     --hash=sha256:8dbb8660838688a7b6ba4fed31d18dedf842afb4d47ca050d6d891c2c15f3be4 \
@@ -1649,10 +1649,10 @@ websockets==17.2 \
     #   alpaca-py

 # The following packages are considered to be unsafe in a requirements file:
-setuptools==83.0.0 \
-    --hash=sha256:025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef \
-    --hash=sha256:29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3
+setuptools==84.1.0 \
+    --hash=sha256:23657205b63d4d31395ab917815247f694aafad28cd21316bf5fd45a51048ea0 \
+    --hash=sha256:5231689c6ac8156cd155cfb98c3fd6fb252c3e7e9bd3d78b64d3c55f132624c9
     # via
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements.lock
-    #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-z7kxt28r\pyproject.toml::build-system.requires)
+    #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-4dwfs0dt\pyproject.toml::build-system.requires)
```

## Every changed annotation line

### requirements.lock

```text
old:13:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:13:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:36:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:36:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:391:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:391:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:399:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:399:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:406:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:406:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:527:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:527:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:572:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:572:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:704:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:704:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:895:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:895:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:902:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:902:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:967:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:967:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:973:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:973:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:980:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:980:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1068:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1068:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1200:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1200:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1229:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1229:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1321:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1321:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1329:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1329:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1336:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1336:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1413:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1413:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1426:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1426:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1433:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1433:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1480:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1480:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1658:     #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-z7kxt28r\pyproject.toml::build-system.requires)
new:1658:     #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-4dwfs0dt\pyproject.toml::build-system.requires)
```

### requirements-dev.lock

```text
old:11:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:11:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:14:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:14:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:19:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:19:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:27:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:27:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:37:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:37:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:40:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:40:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:120:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:120:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:144:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:144:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:252:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:252:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:486:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:486:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:692:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:692:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:695:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:695:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:702:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:702:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:721:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:721:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:732:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:732:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:735:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:735:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:740:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:740:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:743:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:743:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:748:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:748:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:847:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:847:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:855:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:855:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:864:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:864:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:872:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:872:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:880:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:880:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:884:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:884:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:889:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:889:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:981:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:981:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:992:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:992:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1016:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1016:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1024:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1024:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1032:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1032:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1040:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1040:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1043:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1043:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1166:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1166:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1192:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1192:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1195:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1195:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1200:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1200:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1635:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1635:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1733:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1733:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1743:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1743:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1799:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1799:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1816:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1816:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1888:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1888:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1894:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1894:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1899:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1899:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1902:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1902:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1982:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1982:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:1987:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1987:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:1993:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1993:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2011:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2011:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2024:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2024:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2028:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2028:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2031:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2031:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2052:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2052:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2057:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2057:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2060:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2060:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2129:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2129:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2143:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2143:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2151:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2151:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2157:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2157:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2280:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2280:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2288:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2288:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2291:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2291:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2304:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2304:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2330:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2330:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2336:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2336:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2342:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2342:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2348:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2348:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2353:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2353:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2369:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2369:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2377:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2377:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2380:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2380:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2385:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2385:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2393:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2393:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2472:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2472:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2479:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2479:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2492:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2492:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2499:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2499:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2680:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2680:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2685:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2685:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2688:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2688:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2797:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2797:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2806:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2806:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2877:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2877:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2880:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2880:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2884:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2884:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2898:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2898:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2901:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2901:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2906:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2906:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2909:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2909:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:2977:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2977:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2985:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2985:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:2995:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:2995:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:3001:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:3001:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:3006:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:3006:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:3026:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:3026:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:3035:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:3035:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:3042:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:3042:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/pyproject.toml)
old:3048:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:3048:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:3062:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:3062:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:3230:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:3230:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:3253:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:3253:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-4dwfs0dt/requirements.lock
old:3257:     #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-z7kxt28r\pyproject.toml::build-system.requires)
new:3257:     #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-4dwfs0dt\pyproject.toml::build-system.requires)
```
