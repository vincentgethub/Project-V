"""DAT-11: strict precedence, point-in-time estimates, and unavailable evidence."""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.data.earnings import EarningsProvider
from backend.domain.models import EarningsInfo, EarningsStatus

NOW = datetime(2026, 10, 5, 15, tzinfo=UTC)
pytestmark = pytest.mark.asyncio


def calendar(tmp_path: Path, content: str = "symbol,date\n") -> Path:
    path = tmp_path / "earnings.csv"
    path.write_text(content, encoding="utf-8")
    return path


def submissions(*rows: tuple[str, str]) -> Mapping[str, object]:
    return {
        "filings": {
            "recent": {
                "form": [form for form, _day in rows],
                "filingDate": [day for _form, day in rows],
            }
        }
    }


async def test_DAT_11_manual_precedence_never_queries_optional_sources(tmp_path: Path) -> None:
    calls: list[str] = []

    async def optional(symbol: str, now: datetime) -> EarningsInfo:
        calls.append("optional")
        raise AssertionError("manual override must win")

    async def sec(symbol: str, now: datetime) -> Mapping[str, object]:
        calls.append("SEC")
        raise AssertionError("manual override must win")

    source = EarningsProvider(
        calendar(tmp_path, "symbol,date\nAAPL,2026-10-15\n"),
        known_symbols=frozenset({"AAPL"}),
        third_party=optional,
        submissions=sec,
    )
    result = await source.get("AAPL", NOW)
    assert result == EarningsInfo(
        date=date(2026, 10, 15), status=EarningsStatus.KNOWN, source="manual CSV"
    )
    assert calls == []


async def test_DAT_11_manual_earliest_upcoming_date_and_edits_are_observed(tmp_path: Path) -> None:
    path = calendar(tmp_path, "symbol,date\nAAPL,2026-11-01\nAAPL,2026-10-10\nAAPL,2026-09-01\n")
    source = EarningsProvider(path, known_symbols=frozenset({"AAPL"}))
    assert (await source.get("AAPL", NOW)).date == date(2026, 10, 10)
    path.write_text("symbol,date\nAAPL,2026-10-08\n", encoding="utf-8")
    assert (await source.get("AAPL", NOW)).date == date(2026, 10, 8)


async def test_DAT_11_optional_known_precedence_over_sec(tmp_path: Path) -> None:
    calls: list[str] = []
    expected = EarningsInfo(
        date=date(2026, 10, 12), status=EarningsStatus.KNOWN, source="injected optional provider"
    )

    async def optional(symbol: str, now: datetime) -> EarningsInfo:
        assert symbol == "AAPL" and now == NOW
        calls.append("optional")
        return expected

    async def sec(symbol: str, now: datetime) -> Mapping[str, object]:
        calls.append("SEC")
        return submissions(("10-Q", "2026-07-25"))

    result = await EarningsProvider(
        calendar(tmp_path), known_symbols=frozenset({"AAPL"}), third_party=optional, submissions=sec
    ).get("AAPL", NOW)
    assert result == expected and result is not expected
    assert calls == ["optional"]


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        EarningsInfo(status=EarningsStatus.UNKNOWN, source="unavailable"),
        EarningsInfo(date=date(2026, 9, 1), status=EarningsStatus.KNOWN, source="old"),
        EarningsInfo(
            status=EarningsStatus.ESTIMATED,
            source="old window",
            window_start=date(2026, 9, 1),
            window_end=date(2026, 9, 20),
        ),
    ],
)
async def test_DAT_11_old_or_unknown_optional_evidence_falls_through_to_sec(
    tmp_path: Path, evidence: EarningsInfo | None
) -> None:
    calls: list[str] = []

    async def optional(symbol: str, now: datetime) -> EarningsInfo | None:
        calls.append("optional")
        return evidence

    async def sec(symbol: str, now: datetime) -> Mapping[str, object]:
        calls.append("SEC")
        return submissions(("10-K", "2026-04-25"), ("8-K", "2026-09-30"), ("10-Q", "2026-07-25"))

    result = await EarningsProvider(
        calendar(tmp_path, "symbol,date\nAAPL,2026-09-30\n"),
        known_symbols=frozenset({"AAPL"}),
        third_party=optional,
        submissions=sec,
    ).get("AAPL", NOW)
    assert result.status == EarningsStatus.ESTIMATED and result.date is None
    assert result.window_start == date(2026, 10, 18) and result.window_end == date(2026, 11, 2)
    assert calls == ["optional", "SEC"]


async def test_DAT_11_current_optional_estimate_remains_an_estimate(tmp_path: Path) -> None:
    expected = EarningsInfo(
        status=EarningsStatus.ESTIMATED,
        source="optional estimate",
        window_start=date(2026, 10, 1),
        window_end=date(2026, 10, 7),
    )

    async def optional(symbol: str, now: datetime) -> EarningsInfo:
        return expected

    result = await EarningsProvider(
        calendar(tmp_path), known_symbols=frozenset({"AAPL"}), third_party=optional
    ).get("AAPL", NOW)
    assert result.status == EarningsStatus.ESTIMATED and result.date is None


async def test_DAT_11_sec_future_filings_ignored_using_new_york_asof_day(tmp_path: Path) -> None:
    async def sec(symbol: str, now: datetime) -> Mapping[str, object]:
        return submissions(("10-Q", "2026-07-25"), ("10-Q", "2026-10-06"), ("8-K", "2026-10-05"))

    result = await EarningsProvider(
        calendar(tmp_path), known_symbols=frozenset({"AAPL"}), submissions=sec
    ).get("AAPL", datetime(2026, 10, 6, 1, tzinfo=UTC))
    assert result.window_start == date(2026, 10, 18) and result.window_end == date(2026, 11, 2)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        submissions(),
        submissions(("8-K", "2026-10-05")),
        submissions(("10-Q", "2026-01-01")),
        submissions(("10-K", "2027-01-01")),
    ],
)
async def test_DAT_11_missing_ineligible_or_expired_sec_is_unknown_not_clear(
    tmp_path: Path, payload: Mapping[str, object] | None
) -> None:
    async def sec(symbol: str, now: datetime) -> Mapping[str, object] | None:
        return payload

    result = await EarningsProvider(
        calendar(tmp_path), known_symbols=frozenset({"AAPL"}), submissions=sec
    ).get("AAPL", NOW)
    assert result.status == EarningsStatus.UNKNOWN and result.date is None
    assert result.window_start is None and result.window_end is None


@pytest.mark.parametrize(
    "failure", [ProviderError("unavailable"), OSError("offline"), TimeoutError("deadline")]
)
async def test_DAT_11_expected_source_unavailability_returns_unknown(
    tmp_path: Path, failure: Exception
) -> None:
    async def optional(symbol: str, now: datetime) -> EarningsInfo | None:
        raise failure

    async def sec(symbol: str, now: datetime) -> Mapping[str, object] | None:
        raise failure

    result = await EarningsProvider(
        calendar(tmp_path), known_symbols=frozenset({"AAPL"}), third_party=optional, submissions=sec
    ).get("AAPL", NOW)
    assert result.status == EarningsStatus.UNKNOWN


async def test_DAT_11_disabled_sources_and_missing_manual_file_make_no_network(
    tmp_path: Path,
) -> None:
    result = await EarningsProvider(
        tmp_path / "missing.csv", known_symbols=frozenset({"AAPL"})
    ).get("AAPL", NOW)
    assert result.status == EarningsStatus.UNKNOWN


@pytest.mark.parametrize(
    "content",
    [
        "",
        "ticker,date\nAAPL,2026-10-12\n",
        "symbol,date,date\nAAPL,2026-10-12,2026-10-13\n",
        "symbol,date\nAAPL,2026-10-12,extra\n",
        "symbol,date\nAAPL\n",
        "symbol,date\nAAPL,\n",
        "symbol,date\naapl,2026-10-12\n",
        "symbol,date\nMSFT,2026-10-12\n",
        "symbol,date\nAAPL,2026-10-12\nAAPL,2026-10-12\n",
        "symbol,date\nAAPL,2026-2-01\n",
        "symbol,date\nAAPL,2026-02-30\n",
        "symbol,date\nAAPL,2026-10-12T00:00:00\n",
    ],
)
async def test_DAT_11_malformed_manual_override_is_typed_not_silently_ignored(
    tmp_path: Path, content: str
) -> None:
    source = EarningsProvider(calendar(tmp_path, content), known_symbols=frozenset({"AAPL"}))
    with pytest.raises(DataIntegrityError):
        await source.get("AAPL", NOW)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"filings": []},
        {"filings": {"recent": {}}},
        {"filings": {"recent": {"form": ["10-Q"], "filingDate": []}}},
        submissions(("10-Q", "2026-02-30")),
        {"filings": {"recent": {"form": [None], "filingDate": ["2026-07-25"]}}},
    ],
)
async def test_DAT_11_malformed_sec_payload_has_no_estimated_clearance(
    tmp_path: Path, payload: Mapping[str, object]
) -> None:
    async def sec(symbol: str, now: datetime) -> Mapping[str, object]:
        return payload

    with pytest.raises(DataIntegrityError):
        await EarningsProvider(
            calendar(tmp_path), known_symbols=frozenset({"AAPL"}), submissions=sec
        ).get("AAPL", NOW)


async def test_DAT_11_forged_optional_instance_is_revalidated(tmp_path: Path) -> None:
    invalid = EarningsInfo(status=EarningsStatus.UNKNOWN, source="fixture").model_copy(
        update={"status": EarningsStatus.KNOWN, "date": None}
    )

    async def optional(symbol: str, now: datetime) -> EarningsInfo:
        return invalid

    with pytest.raises(DataIntegrityError):
        await EarningsProvider(
            calendar(tmp_path), known_symbols=frozenset({"AAPL"}), third_party=optional
        ).get("AAPL", NOW)


async def test_DAT_11_unexpected_provider_fault_is_typed_and_secret_free(tmp_path: Path) -> None:
    async def sec(symbol: str, now: datetime) -> Mapping[str, object]:
        raise RuntimeError("access-sandbox-isolated-error-token")

    with pytest.raises(ProviderError) as caught:
        await EarningsProvider(
            calendar(tmp_path), known_symbols=frozenset({"AAPL"}), submissions=sec
        ).get("AAPL", NOW)
    assert "access-sandbox-isolated-error-token" not in str(caught.value)
    assert caught.value.__suppress_context__ is True


@pytest.mark.parametrize(
    "symbol,instant", [("MSFT", NOW), ("aapl", NOW), ("AAPL", NOW.replace(tzinfo=None))]
)
async def test_DAT_11_invalid_requests_fail_before_sources(
    tmp_path: Path, symbol: str, instant: datetime
) -> None:
    with pytest.raises(DataIntegrityError):
        await EarningsProvider(calendar(tmp_path), known_symbols=frozenset({"AAPL"})).get(
            symbol, instant
        )


@pytest.mark.parametrize("timeout", [0, 61, True])
async def test_DAT_11_invalid_timeout_cannot_construct_provider(
    tmp_path: Path, timeout: int
) -> None:
    with pytest.raises(ConfigurationError):
        EarningsProvider(
            tmp_path / "unused", known_symbols=frozenset({"AAPL"}), timeout_seconds=timeout
        )


async def test_DAT_11_allowlist_and_optional_capabilities_are_explicit(tmp_path: Path) -> None:
    for symbols in (frozenset(), frozenset({"aapl"}), cast(frozenset[str], {"AAPL"})):
        with pytest.raises(ConfigurationError):
            EarningsProvider(tmp_path / "unused", known_symbols=symbols)
    with pytest.raises(ConfigurationError):
        EarningsProvider(
            tmp_path / "unused", known_symbols=frozenset({"AAPL"}), third_party=cast(Any, 1)
        )


async def test_DAT_11_manual_directory_or_oversized_file_is_not_ignored(tmp_path: Path) -> None:
    directory = tmp_path / "directory.csv"
    directory.mkdir()
    with pytest.raises(DataIntegrityError):
        await EarningsProvider(directory, known_symbols=frozenset({"AAPL"})).get("AAPL", NOW)
    oversized = calendar(tmp_path, "symbol,date\n" + "x" * 1_048_576)
    with pytest.raises(DataIntegrityError, match="oversized"):
        await EarningsProvider(oversized, known_symbols=frozenset({"AAPL"})).get("AAPL", NOW)


async def test_DAT_11_even_a_broken_manual_symlink_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "broken.csv"
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda candidate: candidate == path or original(candidate)
    )
    with pytest.raises(DataIntegrityError, match="symbolic link"):
        await EarningsProvider(path, known_symbols=frozenset({"AAPL"})).get("AAPL", NOW)
