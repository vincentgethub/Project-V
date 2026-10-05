"""SEC-30/33/34/60/61: planted source controls must block startup."""

from pathlib import Path

import pytest

from backend.core.source_guard import scan_file, scan_project


@pytest.mark.parametrize(
    "source,rule",
    [
        ("import requests as r\nr.get('https://example.com')", "SEC-30"),
        ("from requests import Session as S\ns = S()", "SEC-30"),
        ("import httpx as h\nc = h.AsyncClient()", "SEC-30"),
        ("from httpx import Client as C\nclass Unsafe(C):\n pass", "SEC-30"),
        ("import requests\nread = requests.get\nread('https://example.com')", "SEC-30"),
        ("import httpx\nhttpx.get('https://example.com', verify=True)", "SEC-30"),
        ("client.get('https://example.com', verify=False)", "SEC-33"),
        ("unsafe = False\nclient.get('https://example.com', verify=unsafe)", "SEC-33"),
        ("options = {'verify': False}\nclient.get('https://example.com', **options)", "SEC-33"),
        ("import ssl\nctx.verify_mode = ssl." + "CERT" + "_NONE", "SEC-33"),
        ("import ssl\nctx = ssl." + "_create_unverified" + "_context()", "SEC-33"),
        ("ctx.check_hostname = False", "SEC-33"),
        ("s.bind(('0.0.0.0', 80))", "SEC-34"),
        ("import asyncio\nasyncio.start_server(callback, 'localhost', 80)", "SEC-34"),
        ("from http.server import HTTPServer\nHTTPServer(('localhost', 80), Handler)", "SEC-34"),
        ("llm.create(tools=[{'name': 'anything'}])", "SEC-61"),
        ("llm.create(functions=[])", "SEC-61"),
        ("llm.create(tool_choice='auto')", "SEC-61"),
        ("options = {'tools': []}\nllm.create(**options)", "SEC-61"),
        ("llm.create(messages=[{'cash': '1000'}])", "SEC-61"),
        ("payload = {'positions': []}\nllm.create(messages=payload)", "SEC-61"),
        ("def send(value: PortfolioSnapshot):\n llm.create(prompt=value.model_dump())", "SEC-61"),
        ("llm.chat.completions.create(messages=[{'content':'public'}])", "SEC-60"),
    ],
)
def test_SEC_30_61_planted_unsafe_source_is_rejected(
    tmp_path: Path, source: str, rule: str
) -> None:
    path = tmp_path / "planted.py"
    path.write_text(source, encoding="utf-8")
    findings = scan_file(path)
    assert any(finding.rule_id == rule for finding in findings), findings


def test_SEC_33_http_literals_only_allow_localhost_in_tests(tmp_path: Path) -> None:
    source = f"URL = '{'http'}://localhost:8000'"
    ordinary = tmp_path / "production.py"
    ordinary.write_text(source, encoding="utf-8")
    assert any(item.rule_id == "SEC-33" for item in scan_file(ordinary))
    test = tmp_path / "test_local.py"
    test.write_text(source, encoding="utf-8")
    assert not scan_file(test)
    test.write_text(f"URL = '{'http'}://example.com'", encoding="utf-8")
    assert any(item.rule_id == "SEC-33" for item in scan_file(test))


def test_SEC_30_factory_exception_requires_trusted_exact_path(tmp_path: Path) -> None:
    path = tmp_path / "backend" / "net" / "http.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "import httpx\nclient = httpx.AsyncClient(verify=True, timeout=5)", encoding="utf-8"
    )
    assert any(item.rule_id == "SEC-30" for item in scan_file(path))
    assert not scan_project(tmp_path)


def test_SEC_30_trusted_factory_still_requires_explicit_timeout(tmp_path: Path) -> None:
    path = tmp_path / "backend" / "net" / "http.py"
    path.parent.mkdir(parents=True)
    path.write_text("import httpx\nclient = httpx.AsyncClient(verify=True)", encoding="utf-8")
    assert any(item.rule_id == "SEC-30" for item in scan_project(tmp_path))


def test_SEC_33_configuration_urls_scanned(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(f"feed: {'http'}://example.com/rss", encoding="utf-8")
    assert any(item.rule_id == "SEC-33" for item in scan_project(tmp_path))


def test_SEC_61_public_payload_and_required_token_cap_allowed(tmp_path: Path) -> None:
    path = tmp_path / "public.py"
    path.write_text(
        "llm.chat.completions.create(messages=[{'content': 'AAPL public headline'}], max_tokens=100)",
        encoding="utf-8",
    )
    assert not scan_file(path)


def test_GD_07_separate_functions_do_not_create_false_recursive_constants(tmp_path: Path) -> None:
    path = tmp_path / "scopes.py"
    path.write_text(
        "def encode(image):\n"
        " encoded = 'header'\n"
        " token = wrap(encoded + image)\n"
        " return token\n"
        "def decode(token):\n"
        " authenticated = unwrap(token)\n"
        " encoded, image = authenticated.split('separator')\n"
        " return image\n",
        encoding="utf-8",
    )
    assert not scan_file(path)


@pytest.mark.parametrize(
    "source,rule",
    [
        ("import requests\ndef bind():\n global read\n read = requests.get", "SEC-30"),
        ("import requests\ndef bind():\n return requests.get", "SEC-30"),
        ("import requests\nread = requests.get\ndef f():\n read('https://example.com')", "SEC-30"),
        ("ENDPOINT='/orders'\ndef send(client):\n client.post(ENDPOINT)", "GD-07"),
        (
            "import requests\ndef outer():\n read = requests.get\n def inner():\n  read('https://example.com')",
            "SEC-30",
        ),
        (
            "def outer(value: PortfolioSnapshot):\n def inner():\n  llm.create(prompt=value)",
            "SEC-61",
        ),
    ],
)
def test_GD_07_lexical_scopes_retain_ancestor_prohibitions(
    tmp_path: Path, source: str, rule: str
) -> None:
    path = tmp_path / "scopes.py"
    path.write_text(source, encoding="utf-8")
    assert any(item.rule_id == rule for item in scan_file(path))
