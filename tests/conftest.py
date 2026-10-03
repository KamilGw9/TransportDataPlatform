import os

import pytest

from mobility.ingestion.archive import connect_postgres


@pytest.fixture
def conn():
    if "POSTGRES_PASSWORD" not in os.environ:
        pytest.fail("Load .env first: set -a; source .env; set +a")
    with connect_postgres() as conn:
        # Every test runs in a transaction that is rolled back, so no rows stay.
        with conn.transaction(force_rollback=True):
            yield conn
