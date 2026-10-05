"""R-08/R-10/GD-07: source safety, positive controls, and reflection bypasses."""

import ast
import sys
from pathlib import Path

import pytest

from backend.core.errors import ConfigurationError
from backend.core.execution_policy import (
    BANNED_ALPACA_FIELDS,
    BANNED_EXECUTION_METHODS,
    BANNED_ORDER_REQUESTS,
)
from backend.core.source_guard import main as source_guard_main
from backend.core.source_guard import require_safe_sources, scan_file, scan_project


def _source(tmp_path: Path, source: str, name: str = "sample.py") -> Path:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source + "\n", encoding="utf-8")
    return target


def test_GD_07_every_authored_repository_file_is_read_only() -> None:
    root = Path(__file__).resolve().parents[2]
    violations = scan_project(root)
    assert not violations, "\n".join(map(str, violations))


@pytest.mark.parametrize("name", sorted(BANNED_ORDER_REQUESTS))
def test_GD_07_order_request_imports_and_aliases_are_rejected(tmp_path: Path, name: str) -> None:
    path = _source(tmp_path, f"from alpaca.trading.requests import {name} as Request\n")
    assert scan_file(path)


@pytest.mark.parametrize("name", sorted(BANNED_EXECUTION_METHODS))
def test_GD_07_execution_attributes_are_rejected_even_without_a_call(
    tmp_path: Path, name: str
) -> None:
    path = _source(tmp_path, f"operation = client.{name}\n")
    assert scan_file(path)


@pytest.mark.parametrize("field", sorted(BANNED_ALPACA_FIELDS))
@pytest.mark.parametrize(
    "source",
    [
        "value = account.{field}",
        "value = account['{field}']",
        "key = '{field}'\nvalue = account[key]",
        "value = account.get('{field}')",
        "pick = account.get\nvalue = pick('{field}')",
        "value = account.pop('{field}')",
        "value = account.setdefault('{field}', None)",
        "value = getattr(account, '{field}', None)",
        "import builtins as b\npick = b.getattr\nvalue = pick(account, '{field}')",
        "from builtins import getattr as pick\nvalue = pick(account, '{field}')",
        "value = account.__getattribute__('{field}')",
        "from operator import attrgetter\nvalue = attrgetter('{field}')(account)",
        "from vendor import {field}",
    ],
)
def test_GD_07_amendment_01_removed_alpaca_fields_are_never_read(
    tmp_path: Path, field: str, source: str
) -> None:
    """R-02/GD-07: every retired account/asset field fails before startup."""
    assert len(BANNED_ALPACA_FIELDS) == 10
    findings = scan_file(_source(tmp_path, source.format(field=field)))
    assert findings
    assert any(field in finding.message for finding in findings)


@pytest.mark.parametrize(
    "source",
    [
        "value = asset.borrow_status",
        "value = asset.margin_requirement_long",
        "value = asset.margin_requirement_short",
        "value = account['cash']",
        "value = account.get('equity')",
        "value = getattr(account, 'status', None)",
    ],
)
def test_GD_07_current_account_and_asset_fields_remain_readable(
    tmp_path: Path, source: str
) -> None:
    """R-02/GD-07: current read-only financial projections stay supported."""
    assert not scan_file(_source(tmp_path, source))


@pytest.mark.parametrize("verb", ["POST", "PATCH", "PUT", "DELETE"])
@pytest.mark.parametrize(
    "segments",
    [
        ("v2", "wallets"),
        ("v2", "wallets", "whitelists"),
        ("v2", "crypto", "whitelists", "id"),
        ("v2", "crypto", "transfers"),
        ("v1", "journals"),
        ("v1", "accounts", "id", "ach_relationships"),
        ("v1", "accounts", "id", "bank_accounts"),
        ("v2", "funding"),
        ("v2", "deposits"),
        ("v2", "withdrawals"),
    ],
)
def test_GD_07_AX_13_SEC_02_all_money_movement_http_mutations_are_banned(
    tmp_path: Path, verb: str, segments: tuple[str, ...]
) -> None:
    """AX-13/SEC-02: wallet/whitelist/funding APIs have no mutation path."""
    endpoint = "/" + "/".join(segments)
    source = f"client.request('{verb}', 'https://api.alpaca.markets{endpoint}')"
    assert any(
        "mutating HTTP" in finding.message for finding in scan_file(_source(tmp_path, source))
    )


@pytest.mark.parametrize(
    "member",
    [
        "create_crypto_wallet",
        "add_crypto_whitelist",
        "update_wallet",
        "remove_whitelist",
        "CreateCryptoTransferRequest",
        "CreateACHRelationshipRequest",
        "CreateJournalRequest",
        "link_bank_account",
        "move_money",
    ],
)
def test_GD_07_AX_13_SEC_02_money_mutation_members_and_requests_are_banned(
    tmp_path: Path, member: str
) -> None:
    """AX-13/SEC-02: prohibit both direct and CamelCase mutation capabilities."""
    assert scan_file(_source(tmp_path, f"operation = client.{member}"))


def test_GD_07_AX_13_read_only_funding_and_wallet_history_is_permitted(tmp_path: Path) -> None:
    """AX-13/FN-02: read-only observations cannot mutate broker money."""
    assert not scan_file(_source(tmp_path, "client.get('/v2/wallets/transfers')"))


@pytest.mark.parametrize(
    "source",
    [
        "eval('untrusted')",
        "exec('untrusted')",
        "compile('untrusted', 'source', 'exec')",
        "__import__('untrusted')",
        "import builtins as b\nb.eval('untrusted')",
        "__builtins__.eval('untrusted')",
        "from builtins import eval as run\nrun('untrusted')",
        "run = eval\nnext_run = run\nnext_run('untrusted')",
        "import importlib\nimportlib.import_module('untrusted')",
        "import importlib as modules\nmodules.import_module('untrusted')",
        "from importlib import import_module as load\nload('untrusted')",
        "import importlib\nload = importlib.import_module\nload('untrusted')",
        "getattr(client, name)",
        "setattr(client, name, value)",
        "getattr(client, 'submit_order')",
        "setattr(client, 'submit_order', value)",
        "pick = getattr\npick(client, name)",
        "from builtins import getattr as getAttribute\ngetAttribute(client, name)",
        "from builtins import getattr as getAttribute\ngetAttribute(client, 'submit_order')",
        "import builtins as b\npick = b.getattr\npick(client, name)",
        "method = client.__dict__['submit_order']\nmethod(request)",
        "client.__dict__['submit_order'](request)",
        "name = 'submit_order'\nclient.__dict__[name](request)",
        "client.__dict__[name](request)",
        "__builtins__['eval']('untrusted')",
        "__builtins__['getattr'](client, name)",
        "client.__getattribute__('submit_order')(request)",
        "client.__getattribute__(name)(request)",
        "getattr(client, '__getattribute__')(name)(request)",
        "from alpaca.trading import requests as r\nr.MarketOrderRequest()",
        "import alpaca.trading.requests.OrderRequest as Request",
        "from alpaca.trading.requests import *",
        "client.create_internal_transfer(request)",
        "client.createTransfer(request)",
        "from operator import attrgetter\nattrgetter('submit_order')(client)(request)",
        "import operator\noperator.methodcaller('submit_order', request)(client)",
        "from operator import attrgetter as pick\npick('client.submit_order')(context)(request)",
        "from operator import attrgetter\npick = attrgetter\npick(name)(client)(request)",
        "from operator import attrgetter\nattrgetter('safe', 'submit_order')(client)",
        "from operator import methodcaller as call\ncall(name, request)(client)",
        "client.__dict__.get('submit_order')(request)",
        "vars(client).get('submit_order')(request)",
        "methods = client.__dict__\nmethods.get('submit_order')(request)",
        "import pandas as pd\npd.eval('untrusted')",
        "object.eval('untrusted')",
        "object.exec('untrusted')",
        "object.__import__('untrusted')",
        "object.import_module('untrusted')",
        "object.compile('untrusted')",
        "compiler = object.compile\ncompiler('untrusted')",
        "def execute(re):\n    re.compile('untrusted')",
        "import re\ndef execute(re):\n    re.compile('untrusted')",
        "import re as regex\ndef execute(regex):\n    regex.compile('untrusted')",
        "re.compile('untrusted')",
    ],
)
def test_GD_07_dynamic_code_reflection_and_import_bypasses_fail_closed(
    tmp_path: Path, source: str
) -> None:
    findings = scan_file(_source(tmp_path, source))
    assert findings, source
    assert all(item.rule_id == "GD-07" and item.line >= 1 and item.column >= 1 for item in findings)


@pytest.mark.parametrize(
    "source",
    [
        "client.post('/v2/orders', json=payload)",
        "client.delete('https://api.alpaca.markets/v2/orders/id')",
        "client.patch('/v2/orders/id', json=payload)",
        "client.request('POST', '/v1/accounts/account/transfers')",
        "client.request(method='DELETE', url='/v2/orders/id')",
        "verb = 'PATCH'\nurl = '/v2/orders/id'\nclient.request(method=verb, url=url)",
        "send = client.post\nurl = '/v2/orders'\nsend(url, json=payload)",
        "client.request(**{'method': 'POST', 'url': '/v2/orders'})",
        "client.post('/v2/' + 'orders')",
        "client.patch(f'/v2/orders/{identifier}')",
        "client.post('/v2/transfers', json=payload)",
        "client._post('/v2/orders', payload)",
        "client.request(method='POST', url='/v2/orders'.format())",
        "client.post('/v2/{endpoint}'.format(endpoint='orders'))",
        "endpoint = '/v2/orders'\nclient.request(method='POST', url=str(endpoint))",
        "client.post(normalize('/v2/orders'))",
        "from operator import attrgetter\nattrgetter('post')(client)('/v2/orders')",
        "from operator import attrgetter\npost = attrgetter('post')(client)\npost('/v2/orders')",
        "from operator import methodcaller\nmethodcaller('post', '/v2/orders')(client)",
        "from operator import attrgetter\nget, post = attrgetter('get', 'post')(client)\npost('/v2/orders')",
        "client.post('/v2/%s' % 'orders')",
        "client.post(''.join(['/v2/', 'orders']))",
        "client.post(b'/v2/orders'.decode())",
        "client.post('/sredro/2v/'[::-1])",
    ],
)
def test_GD_07_order_and_transfer_mutating_http_endpoints_are_rejected(
    tmp_path: Path, source: str
) -> None:
    findings = scan_file(_source(tmp_path, source))
    assert any("mutating HTTP" in item.message for item in findings), source


@pytest.mark.parametrize(
    "source",
    [
        "request.method = 'POST'\nrequest.url = '/v2/orders'\nsession.send(request)",
        "request.method = 'PATCH'\nrequest.url = b'/v2/orders'.decode()\nsession.send(request)",
        "request.method = 'DELETE'\nrequest.url = '/sredro/2v/'[::-1]\nsession.send(request)",
        "request.method = b'POST'.decode()\nrequest.url = '/v2/orders'\nsession.send(request)",
        "request.method = 'PO' + 'ST'\nrequest.url = '/v2/orders'\nsession.send(request)",
        "request.method = 'TSOP'[::-1]\nrequest.url = '/v2/orders'\nsession.send(request)",
    ],
)
def test_GD_07_separately_constructed_mutating_requests_fail_closed(
    tmp_path: Path, source: str
) -> None:
    assert scan_file(_source(tmp_path, source))


@pytest.mark.parametrize(
    "source",
    [
        "client.get_account()\nclient.get_all_positions()\nclient.get_orders(request)",
        "from alpaca.trading.requests import GetOrdersRequest\nquery = GetOrdersRequest()",
        "getattr(response, 'status_code', None)",
        "setattr(value, 'label', 'safe')",
        "import builtins as b\npick = b.getattr\npick(response, 'status_code', None)",
        "from builtins import getattr as getAttribute\ngetAttribute(response, 'cash')",
        "import re\npattern = re.compile('^[A-Z]+$')",
        "from re import compile as regex_compile\npattern = regex_compile('^[A-Z]+$')",
        "import re as regex\ncompile_pattern = regex.compile\ncompile_pattern('[A-Z]')",
        "import re as regex\nregex.compile('[A-Z]')",
        "client.get('/v2/orders')",
        "client.request('GET', '/v1/accounts/account/transfers')",
        "object.__setattr__(self, 'current', value)",
        "value.__getattribute__('cash')",
        "from operator import attrgetter\nattrgetter('cash')(account)",
        "from operator import methodcaller\nmethodcaller('get_account')(client)",
        "from operator import attrgetter\nattrgetter('get')(client)('/v2/orders')",
        "data = {'submit_order': 'untrusted text only'}",
        "sql = 'SELECT * FROM orders'",
    ],
)
def test_GD_07_safe_literal_reflection_regex_and_read_only_clients_are_allowed(
    tmp_path: Path, source: str
) -> None:
    findings = scan_file(_source(tmp_path, source))
    assert not findings, "\n".join(map(str, findings))


def test_GD_07_positive_control_scans_tests_scripts_and_other_authored_paths(
    tmp_path: Path,
) -> None:
    paths = (
        _source(tmp_path, "client.submit_order(request)", "backend/tests/planted.py"),
        _source(tmp_path, "client.close_position('AAPL')", "scripts/planted.py"),
        _source(tmp_path, "client.create_transfer(request)", "misc/planted.py"),
        _source(tmp_path, "client.cancel_orders()", "root_script.py"),
    )
    findings = scan_project(tmp_path)
    assert {item.path for item in findings} == set(paths)
    with pytest.raises(ConfigurationError, match="GD-07"):
        require_safe_sources(tmp_path)


def test_GD_07_only_canonical_constants_module_is_exempt(tmp_path: Path) -> None:
    canonical = _source(
        tmp_path, "client.submit_order(request)", "backend/core/execution_policy.py"
    )
    lookalike = _source(tmp_path, "client.submit_order(request)", "scripts/execution_policy.py")
    findings = scan_project(tmp_path)
    assert {item.path for item in findings} == {lookalike}
    assert all(item.path != canonical for item in findings)


def test_GD_07_generated_dependencies_are_explicitly_outside_authored_scan(tmp_path: Path) -> None:
    _source(tmp_path, "client.submit_order(request)", ".venv/Lib/site-packages/sdk.py")
    _source(tmp_path, "client.submit_order(request)", "__pycache__/generated.py")
    _source(tmp_path, "client.submit_order(request)", "build/generated.py")
    require_safe_sources(tmp_path)


@pytest.mark.parametrize("source", ["if (", "\x00", "not valid python source!"])
def test_GD_07_unparseable_source_fails_closed(tmp_path: Path, source: str) -> None:
    findings = scan_file(_source(tmp_path, source))
    assert len(findings) == 1
    assert "cannot be verified" in findings[0].message


def test_GD_07_unreadable_or_missing_source_fails_closed(tmp_path: Path) -> None:
    assert scan_file(tmp_path / "missing.py")
    assert scan_project(tmp_path / "missing")
    binary = tmp_path / "invalid_encoding.py"
    binary.write_bytes(bytes([0xFF, 0xFE, 0xFD]))
    assert scan_file(binary)


def test_GD_07_symbolic_links_fail_closed_without_following_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path, "client.get_account()")
    original = Path.is_symlink

    def observed_link(path: Path) -> bool:
        return path == source or original(path)

    monkeypatch.setattr(Path, "is_symlink", observed_link)
    assert "symbolic" in scan_file(source)[0].message
    assert "symbolic" in scan_project(tmp_path)[0].message


def test_GD_07_paths_that_resolve_outside_project_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path, "client.get_account()")
    original = Path.resolve
    outside = tmp_path.parent / "escaped.py"

    def observed_escape(path: Path, strict: bool = False) -> Path:
        return outside if path == source else original(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", observed_escape)
    findings = scan_project(tmp_path)
    assert len(findings) == 1
    assert "escapes" in findings[0].message


def test_GD_07_cli_reports_pass_and_nonzero_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["source_guard", str(tmp_path)])
    assert source_guard_main() == 0
    assert "passed" in capsys.readouterr().out
    _source(tmp_path, "client.submit_order(request)")
    assert source_guard_main() == 1
    assert "GD-07" in capsys.readouterr().err


def test_GD_07_unexpected_parser_or_directory_error_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path, "client.get_account()")

    def parser_failure(_source: str, filename: str) -> ast.AST:
        raise RuntimeError("sensitive source must not appear in diagnostics")

    monkeypatch.setattr(ast, "parse", parser_failure)
    findings = scan_file(source)
    assert "RuntimeError" in findings[0].message
    assert "sensitive" not in findings[0].message

    def directory_failure(_path: Path) -> list[Path]:
        raise RuntimeError("sensitive path must not appear in diagnostics")

    monkeypatch.setattr(Path, "iterdir", directory_failure)
    findings = scan_project(tmp_path)
    assert "RuntimeError" in findings[0].message
    assert "sensitive" not in findings[0].message
    with pytest.raises(ConfigurationError):
        require_safe_sources(tmp_path)
