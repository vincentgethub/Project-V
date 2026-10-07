"""OPS-06/R-02: explicit disposable PostgreSQL triggers and serialized writers.

No dotenv is read. Default offline collection skips this suite. Only the CLI
option --postgres-test-url for a loopback database named vws_ci permits I/O.
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import (
    LEDGER_MODELS,
    LedgerRecord,
    SecurityEvent,
    create_database,
    create_schema,
)
from backend.core.errors import ConfigurationError
from backend.core.ledger import Ledger
from backend.tests.test_ledger import _all_records


@pytest.fixture
def postgres_engine(request: pytest.FixtureRequest) -> Iterator[Engine]:
    supplied = request.config.getoption("--postgres-test-url")
    if supplied is None:
        pytest.skip("UNVERIFIED: explicit disposable PostgreSQL URL not supplied")
    url = make_url(supplied)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != "vws_ci"
        or url.username != "vws_ci"
    ):
        raise ConfigurationError(
            "OPS-06: PostgreSQL tests require the named disposable loopback database"
        )
    request.getfixturevalue("socket_enabled")
    admin = create_database(url.render_as_string(hide_password=False))
    schema = "vws_test_" + uuid4().hex
    with admin.begin() as connection:
        connection.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
    query = {**url.query, "options": "-csearch_path=" + schema}
    engine = create_database(url.set(query=query).render_as_string(hide_password=False))
    try:
        create_schema(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            # Only the generated isolated test schema is destroyed.
            connection.exec_driver_sql('DROP SCHEMA "' + schema + '" CASCADE')
        admin.dispose()


@pytest.mark.parametrize("model", LEDGER_MODELS)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_OPS_06_every_postgres_ledger_table_blocks_raw_mutation(
    postgres_engine: Engine, clock: FrozenClock, model: type[LedgerRecord], operation: str
) -> None:
    ledger = Ledger(postgres_engine, clock)
    records = _all_records(ledger, clock)
    row = records[model]
    with pytest.raises(DBAPIError):
        with postgres_engine.begin() as connection:
            if operation == "UPDATE":
                connection.execute(
                    update(model).where(model.id == row.id).values(row_hash="f" * 64)
                )
            else:
                connection.execute(delete(model).where(model.id == row.id))
    ledger.verify_chain()


def test_OPS_06_postgres_concurrent_append_has_unique_complete_sequence(
    postgres_engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(postgres_engine, clock)

    def append(number: int) -> int:
        return ledger.append(SecurityEvent, kind="CI_CONCURRENT", detail={"worker": number}).seq

    with ThreadPoolExecutor(max_workers=8) as pool:
        allocated = sorted(pool.map(append, range(32)))
    assert allocated == list(range(1, 33))
    with Session(postgres_engine) as session:
        assert tuple(
            session.scalars(select(SecurityEvent.seq).order_by(SecurityEvent.seq))
        ) == tuple(allocated)
    ledger.verify_chain()
