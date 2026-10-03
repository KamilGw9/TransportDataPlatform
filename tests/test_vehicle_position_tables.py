"""Check the vehicle position staging tables against the local PostgreSQL.

Run with the services from make up and the variables from .env loaded:
    set -a; source .env; set +a
    uv run pytest -m integration
"""

from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

pytestmark = pytest.mark.integration

SNAPSHOT = "a" * 64


def insert_load(conn: psycopg.Connection, status: str, error: str | None) -> None:
    conn.execute(
        """
        INSERT INTO metadata.vehicle_position_load
            (snapshot_sha256, object_key, started_at, status, error)
        VALUES (%s, 'raw/gtfs_rt/a.pb', %s, %s, %s)
        """,
        (SNAPSHOT, datetime(2026, 10, 3, tzinfo=UTC), status, error),
    )


def insert_position(
    conn: psycopg.Connection, latitude: float | None, longitude: float | None
) -> None:
    conn.execute(
        """
        INSERT INTO staging.vehicle_position
            (snapshot_sha256, entity_id, trip_id, latitude, longitude)
        VALUES (%s, 'vehicle_401', '1685_13717', %s, %s)
        """,
        (SNAPSHOT, latitude, longitude),
    )


def insert_snapshot(conn: psycopg.Connection) -> None:
    conn.execute(
        "INSERT INTO staging.vehicle_position_snapshot VALUES (%s, %s)",
        (SNAPSHOT, datetime(2026, 10, 3, 12, tzinfo=UTC)),
    )


def test_snapshot_is_loaded_at_most_once(conn: psycopg.Connection) -> None:
    insert_load(conn, "failed", "DecodeError: truncated message")
    insert_load(conn, "loaded", None)

    with pytest.raises(UniqueViolation):
        insert_load(conn, "loaded", None)


def test_position_rejects_unknown_snapshot(conn: psycopg.Connection) -> None:
    with pytest.raises(ForeignKeyViolation):
        insert_position(conn, 50.07, 19.94)


def test_position_rejects_latitude_without_longitude(
    conn: psycopg.Connection,
) -> None:
    insert_snapshot(conn)

    with pytest.raises(CheckViolation):
        insert_position(conn, 50.07, None)
