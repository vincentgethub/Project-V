# Direct dependency policy

Use the standard library when it supplies the required behavior. Every direct
runtime, development and build dependency must appear here. Transitive packages
are recorded by the compiled hash locks. Additions need a stated purpose and the
security audit gates. Never add telemetry or an order-capable integration outside
the specified broker executor.
Amendment 05 prohibits optuna, hyperopt, scikit-optimize, deap and nevergrad in
both direct dependencies and compiled transitive locks, even with justification.
Only the specified fixed, registered variants are allowed; no generated search.

- `pydantic`: frozen validated domain contracts and exact output schemas.
- `pydantic-settings`: explicit environment configuration with masked secrets.
- `sqlalchemy`: transactional append-only ledger on SQLite/PostgreSQL.
- `alpaca-py`: specified broker/data SDK, with order isolation and endpoint binding.
- `plaid-python`: specified read-only pinned checking-account balance SDK.
- `pandas`: tabular market-data handling specified by the master.
- `exchange-calendars`: actual XNYS sessions, holidays and early closes.
- `tenacity`: bounded retry support specified by the master.
- `structlog`: structured safety/audit logs with redaction.
- `cryptography`: authenticated encrypted backups using Fernet.
- `requests`: Alpaca's read-only transport with fixed timeouts and exact JSON.
- `tzdata`: consistent IANA time zones on Windows and deployed hosts.
- `openai`: model-neutral public-evidence LLM transport specified for Stage E.
- `python-telegram-bot`: private long-poll Telegram transport specified for Stage F.
- `apscheduler`: exchange-aware jobs specified for Stage F.
- `httpx`: central HTTPS egress factory and bounded async public reads.
- `feedparser`: secondary public RSS news parsing specified for Stage D.
- `numpy`: internal float64 calculations for deterministic indicator outputs.
- `pyyaml`: strict exact-value YAML loading without unsafe constructors.
- `keyring`: native OS secret storage; no plaintext or file fallback.
- `pytest`: offline acceptance and regression tests.
- `pytest-cov`: statement/branch coverage gates.
- `pytest-socket`: forbid network use in unit tests.
- `hypothesis`: adversarial/property checks for money and risk invariants.
- `mutmut`: mutation gates for risk and approval logic.
- `ruff`: lint and formatting checks.
- `mypy`: strict static typing.
- `pandas-stubs`: typed pandas boundaries.
- `bandit`: authored production-source security checks.
- `pip-audit`: vulnerability audit of exact locked dependencies.
- `detect-secrets`: pre-commit and authored-source secret scanning.
- `pre-commit`: local source gates before commits.
- `types-requests`: typed SDK transport integration.
- `pytest-asyncio`: offline async admission/scheduler/provider tests.
- `types-pyyaml`: typed strict YAML handling.
- `pip-tools`: reproducible runtime/dev locks with package SHA256 hashes.
- `setuptools`: pinned build backend and editable local package metadata.

The standalone CI history scanner is Gitleaks 8.30.1. Its Linux archive is
verified against SHA256
`551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`
before extracting its executable. It scans every Git ref with redacted output;
the existing detect-secrets hook checks each authored commit.
The archive and published checksum are from the
[official release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1).

`requirements-platform.in` retains keyring's Linux SecretStorage and jeepney
runtime requirements when pip-tools runs on Windows. The runtime and dev locks
compile the union of this input and `pyproject.toml`, keeping existing pins.
These packages are transitive requirements of the already specified native
keyring backend, rather than additional integrations. Both platforms install
the same fully hashed locks; there is no unhashed platform fallback.
Regenerate both with `python -m scripts.compile_locks`. The tool builds temporary
compiler metadata so pip-tools can apply `--all-build-deps`, validates every
existing pin and hash, and leaves application metadata unchanged.
