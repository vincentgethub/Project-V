# Security dependency bumps — October 21, 2026

Only certifi 2026.7.22 → 2026.10.19 and virtualenv 21.14.5 → 21.14.9 are updated. No dependency input, compiler, risk setting, gate or selector changes.

The unmodified `python -m scripts.compile_locks` ran with Python 3.12.14 and pip-tools 7.6.1. Its full output is retained, including generated annotations; no package blocks were hand-spliced into the old locks. Both locks parse to their original record counts: 62 runtime and 141 development. All other package==version records and hashes are identical.

| Lock | Approved version/hash changed lines (a) | Comment changed lines (b) | Other changed lines (c) |
|---|---:|---:|---:|
| requirements.lock | 6 | 50 | 0 |
| requirements-dev.lock | 12 | 208 | 0 |

Counts include old removed and new added lines. The classifier tracks the package owning each hash row and parses complete package inventories before and after; it does not treat arbitrary hash lines as approved. Local executable check and machine-readable evidence: `build/pass7/check_dependency_locks.py` and `build/pass7/dependency-lock-trial/classified-lock-diff.json`.

## Advisory and dependency scope

- certifi: GHSA-6q48-6c7w-9gw2 / PYSEC-2026-4320; target 2026.10.19 fixes the advisory. Runtime through httpcore, httpx and requests, present in both locks.
- virtualenv: GHSA-vxj4-q4g9-crj7 / CVE-2026-113725 (fixed 21.14.7), GHSA-c978-59m8-c77v / CVE-2026-113722 (fixed 21.14.9). Dev/CI through pre-commit. Target requirements accept all existing dependency pins.

Both exact CI pip-audit commands returned zero findings. Two separate clean venvs successfully installed the respective locks with `--require-hashes --no-deps`; both `pip check` commands returned zero and “No broken requirements found.” No audit ignore or allowlist was added.

## PyPI provenance and release hashes

PyPI's integrity provenance API reports the same trusted publisher for both files in each old, immediately preceding, and target release (certifi 2026.10.18 and virtualenv 21.14.8 were also checked):

| Package | Old and new trusted publisher | Environment | Target upload UTC (wheel / sdist) |
|---|---|---|---|
| certifi | certifi/python-certifi, release.yml | release | 2026-10-20 02:24:15.072385 / 02:24:16.604828 |
| virtualenv | pypa/virtualenv, release.yaml | release | 2026-10-17 16:09:40.584722 / 16:09:42.345293 |

Sources: [certifi release](https://pypi.org/project/certifi/2026.10.19/), [virtualenv release](https://pypi.org/project/virtualenv/21.14.9/). Version JSON supplies upload timestamps and SHA256 values. The classifier compares compiler-produced hash sets against those fetched JSON values. No hash was entered manually. A separate full-lock check matched all 2,470 unique package hashes across all 141 releases against PyPI JSON, with zero unmatched hashes. The complete provenance responses for old/new wheels and source archives are saved locally under `build/pass7/dependency-lock-trial/`.

## Every changed annotation line

The following list includes every class-b changed line, with old/new side and one-based line number. Only comments are included here; all class-a changes are visible in the lock diff. Class c is empty.

### requirements.lock

```text
old:13:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:13:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:36:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:36:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:391:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:391:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:399:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:399:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:406:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:406:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:527:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:527:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:570:     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
old:571:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:572:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:703:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:704:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:894:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:895:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:901:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:902:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:966:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:967:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:972:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:973:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:979:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:980:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1067:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1068:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1199:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1200:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1228:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1229:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1320:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1321:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1328:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1329:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
new:1334:     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
old:1334:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1336:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1411:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1413:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1424:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1426:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1431:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1433:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1478:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1480:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1656:     #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-ae5phb7p\pyproject.toml::build-system.requires)
new:1658:     #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-z7kxt28r\pyproject.toml::build-system.requires)
```

### requirements-dev.lock

```text
old:11:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:11:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:14:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:14:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:19:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:19:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:27:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:27:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:37:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:37:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:40:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:40:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:120:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:120:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:144:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:144:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:252:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:252:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:486:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:486:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:692:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:692:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:695:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:695:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:702:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:702:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:721:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:721:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:732:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:732:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:735:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:735:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:740:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:740:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:743:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:743:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:748:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:748:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:847:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:847:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:855:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:855:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:864:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:864:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:872:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:872:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:880:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:880:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:884:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:884:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:889:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:889:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:981:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:981:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:992:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:992:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1016:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1016:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1024:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1024:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1032:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1032:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1040:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1040:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:1041:     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
old:1042:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1043:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1165:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1166:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1191:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1192:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1194:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1195:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1199:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1200:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1634:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1635:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1732:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1733:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1742:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1743:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1798:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1799:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1815:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1816:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1887:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1888:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1893:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1894:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1898:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1899:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1901:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1902:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1981:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:1982:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:1986:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1987:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:1992:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:1993:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2010:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2011:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2023:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2024:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2027:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2028:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2030:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2031:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2051:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2052:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2056:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2057:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2059:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2060:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2128:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2129:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2142:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2143:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2150:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2151:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2156:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2157:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2279:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2280:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2287:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2288:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2290:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2291:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2303:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2304:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2329:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2330:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2335:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2336:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2341:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2342:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2347:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2348:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2352:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2353:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2368:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2369:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2376:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2377:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2379:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2380:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2384:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2385:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2392:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2393:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2471:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2472:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2478:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2479:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2491:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2492:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2498:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2499:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2679:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2680:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2684:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2685:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
new:2686:     #   -c C:/Users/vince/OneDrive/Documents/ChatGPT/Project V/vws-core/requirements-dev.lock
old:2686:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2688:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2795:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2797:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2804:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2806:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2875:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2877:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2878:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2880:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2882:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2884:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2896:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2898:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2899:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2901:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2904:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2906:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2907:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2909:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2975:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2977:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2983:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:2985:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:2993:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:2995:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:2999:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:3001:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:3004:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:3006:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:3024:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:3026:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:3033:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:3035:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:3040:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/pyproject.toml)
new:3042:     #   scalp-city-vws-core (C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/pyproject.toml)
old:3046:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:3048:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:3060:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:3062:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:3228:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:3230:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:3251:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-ae5phb7p/requirements.lock
new:3253:     #   -c C:/Users/vince/AppData/Local/Temp/vws-lock-compile-z7kxt28r/requirements.lock
old:3255:     #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-ae5phb7p\pyproject.toml::build-system.requires)
new:3257:     #   scalp-city-vws-core (C:\Users\vince\AppData\Local\Temp\vws-lock-compile-z7kxt28r\pyproject.toml::build-system.requires)
```


## Executed classifier source

Saved locally as `build/pass7/check_dependency_locks.py`. Its old inputs are the unchanged 5dc9af8 locks saved with `.before` suffix; target release metadata is fetched from the public PyPI JSON endpoints. Every changed comment is listed above.

```python
"""Classify every changed lock line, preserving package ownership of hash rows."""
from pathlib import Path
import difflib, json, re
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/pass7/dependency-lock-trial'
APPROVED={'certifi':('2026.7.22','2026.10.19'),'virtualenv':('21.14.5','21.14.9')}
def parse(text):
    rows=text.splitlines(); owners=[]; pins={}; owner=None
    for line in rows:
        match=re.match(r'^([a-zA-Z0-9_.-]+)==([^\s;]+)',line)
        if match:
            owner=match[1]; pins[owner]=match[2]
        owners.append(owner)
    return rows,owners,pins
report={}
for name,count in [('requirements.lock',62),('requirements-dev.lock',141)]:
    old=(OUT/(name+'.before')).read_text(); new=(ROOT/name).read_text()
    a,ao,ap=parse(old); b,bo,bp=parse(new)
    expected={k:APPROVED.get(k,(v,v))[1] for k,v in ap.items()}
    if len(ap)!=count or len(bp)!=count or bp!=expected: raise SystemExit('STOP: package records changed outside approved bumps')
    classes={'a':[],'b':[],'c':[]}
    for op,i,j,k,l in difflib.SequenceMatcher(a=a,b=b,autojunk=False).get_opcodes():
        if op=='equal': continue
        for side,lines,owners,start,end in [('old',a,ao,i,j),('new',b,bo,k,l)]:
            for n in range(start,end):
                line=lines[n]; owner=owners[n]
                if line.lstrip().startswith('#'): category='b'
                elif owner in APPROVED and (re.fullmatch(r'[a-zA-Z0-9_.-]+==[^\s]+ \\',line) or re.fullmatch(r'    --hash=sha256:[0-9a-f]{64}( \\)?',line)): category='a'
                else: category='c'
                classes[category].append({'side':side,'line':n+1,'text':line,'package':owner})
    for package in set(ap)&APPROVED.keys():
        meta=json.loads((OUT/f'{package}-{bp[package]}-pypi.json').read_text())
        expected_hashes={f['digests']['sha256'] for f in meta['urls']}
        actual={re.search(r'sha256:([a-f0-9]{64})',line)[1] for line,owner in zip(b,bo) if owner==package and '--hash=' in line}
        if actual!=expected_hashes: raise SystemExit('STOP: PyPI hash mismatch')
    report[name]={'old_records':len(ap),'new_records':len(bp),'counts':{x:len(y) for x,y in classes.items()},'changed_lines':classes}
    (OUT/(name+'.final.diff')).write_text(''.join(difflib.unified_diff(a,b,fromfile=name+'.old',tofile=name+'.new',lineterm='\n')))
    print(name,len(ap),'->',len(bp),{x:len(y) for x,y in classes.items()})
(OUT/'classified-lock-diff.json').write_text(json.dumps(report,indent=2))
if any(v['counts']['c'] for v in report.values()): raise SystemExit('STOP: unapproved changed lines')
print('PASS: every changed line is approved version/hash or comment; class c = 0.')

```
