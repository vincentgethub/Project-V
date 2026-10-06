"""FA-02 acceptance: record public SEC fixtures, never owner/account secrets."""

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.core.clock import SystemClock
from backend.core.config import load_settings
from backend.core.database import create_database, create_schema
from backend.core.errors import SafetyError
from backend.core.ledger import Ledger
from backend.data.sec_edgar import SecEdgarProvider
from backend.net.egress import EgressPolicy, SDKSocketGuard, build_allowlist
from backend.net.http import configure_network

SYMBOLS = ("MSFT", "COST", "JPM", "AAPL", "SNAP")


async def record(output: Path) -> None:
    """FA-02: SEC_USER_AGENT must be deliberately supplied by the operator."""
    # CASH is a detached test-policy value; no broker or owner account is read.
    settings = load_settings(broker_account_type="CASH")
    with TemporaryDirectory(prefix="vws-sec-public-") as scratch:
        engine = create_database(f"sqlite:///{(Path(scratch) / 'evidence.db').as_posix()}")
        try:
            create_schema(engine)
            ledger = Ledger(engine, SystemClock())
            policy = EgressPolicy(build_allowlist(), ledger)
            configure_network(policy)
            SDKSocketGuard(policy).install()
            provider = SecEdgarProvider(settings, ledger)
            manifest: list[dict[str, object]] = []
            output.mkdir(parents=True, exist_ok=True)
            for symbol in SYMBOLS:
                payload = await provider.companyfacts(symbol)
                filename = f"{symbol.lower()}_companyfacts.json"
                (output / filename).write_bytes(payload.raw)
                manifest.append(
                    {
                        "symbol": symbol,
                        "cik": payload.cik,
                        "fetched_at": payload.fetched_at.isoformat(),
                        "data_sha256": payload.data_sha256,
                        "bytes": len(payload.raw),
                        "file": filename,
                        "source": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{payload.cik}.json",
                    }
                )
                print(
                    f"Recorded {symbol}: {len(payload.raw)} public bytes; SHA-256 {payload.data_sha256}"
                )
            (output / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            ledger.verify_chain()
        finally:
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Record five public SEC companyfacts fixtures")
    parser.add_argument("--output", type=Path, default=Path("backend/tests/fixtures/sec"))
    options = parser.parse_args()
    try:
        asyncio.run(record(options.output))
        return 0
    except SafetyError as error:
        print(f"SEC recording unavailable: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
