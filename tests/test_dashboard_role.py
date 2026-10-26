"""Check what the dashboard role can do against the local PostgreSQL.

Run with the services from make up and the variables from .env loaded:
    set -a; source .env; set +a
    uv run pytest -m integration
"""

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege

pytestmark = pytest.mark.integration


def as_dashboard(conn: psycopg.Connection) -> None:
    conn.execute("SET LOCAL ROLE dashboard")


def test_dashboard_role_reads_feed_freshness(conn: psycopg.Connection) -> None:
    as_dashboard(conn)

    conn.execute("SELECT * FROM metadata.feed_freshness").fetchall()


def test_dashboard_role_cannot_record_fetch_attempts(conn: psycopg.Connection) -> None:
    as_dashboard(conn)

    with pytest.raises(InsufficientPrivilege):
        conn.execute(
            """
            INSERT INTO metadata.fetch_attempt (source_id, url, fetched_at, status, error)
            VALUES ('integration_test', 'https://example.test', now(), 'failed', 'test')
            """
        )


def test_dashboard_role_cannot_read_staging(conn: psycopg.Connection) -> None:
    as_dashboard(conn)

    with pytest.raises(InsufficientPrivilege):
        conn.execute("SELECT * FROM staging.vehicle_position LIMIT 1")
