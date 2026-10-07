"""Check the TripUpdates staging tables against the local PostgreSQL.

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
        INSERT INTO metadata.trip_update_load
            (snapshot_sha256, object_key, started_at, status, error)
        VALUES (%s, 'raw/gtfs_rt/a.pb', %s, %s, %s)
        """,
        (SNAPSHOT, datetime(2026, 10, 3, tzinfo=UTC), status, error),
    )


def insert_snapshot(conn: psycopg.Connection) -> int:
    return conn.execute(
        """
        INSERT INTO staging.trip_update_snapshot (snapshot_sha256, feed_timestamp)
        VALUES (%s, %s)
        RETURNING snapshot_id
        """,
        (SNAPSHOT, datetime(2026, 10, 3, 12, tzinfo=UTC)),
    ).fetchone()[0]


def insert_trip_update(
    conn: psycopg.Connection, snapshot_id: int, entity_index: int, vehicle_id: str
) -> None:
    conn.execute(
        """
        INSERT INTO staging.trip_update
            (snapshot_id, entity_index, entity_id, trip_id, vehicle_id)
        VALUES (%s, %s, 'trip_1686_42676', '1686_42676', %s)
        """,
        (snapshot_id, entity_index, vehicle_id),
    )


def insert_stop_time_update(
    conn: psycopg.Connection,
    snapshot_id: int,
    arrival_time: datetime | None,
    arrival_delay: int | None,
) -> None:
    conn.execute(
        """
        INSERT INTO staging.stop_time_update
            (snapshot_id, entity_index, stop_sequence, arrival_time, arrival_delay)
        VALUES (%s, 0, 2, %s, %s)
        """,
        (snapshot_id, arrival_time, arrival_delay),
    )


def test_snapshot_is_loaded_at_most_once(conn: psycopg.Connection) -> None:
    insert_load(conn, "failed", "DecodeError: truncated message")
    insert_load(conn, "loaded", None)

    with pytest.raises(UniqueViolation):
        insert_load(conn, "loaded", None)


def test_trip_reported_by_two_vehicles_keeps_both_entities(
    conn: psycopg.Connection,
) -> None:
    snapshot_id = insert_snapshot(conn)

    insert_trip_update(conn, snapshot_id, 0, "867")
    insert_trip_update(conn, snapshot_id, 1, "869")

    count = conn.execute(
        "SELECT count(*) FROM staging.trip_update WHERE snapshot_id = %s",
        (snapshot_id,),
    ).fetchone()[0]
    assert count == 2


def test_stop_time_update_rejects_unknown_trip_update(
    conn: psycopg.Connection,
) -> None:
    snapshot_id = insert_snapshot(conn)

    with pytest.raises(ForeignKeyViolation):
        insert_stop_time_update(conn, snapshot_id, None, None)


def test_stop_time_update_rejects_arrival_time_without_delay(
    conn: psycopg.Connection,
) -> None:
    snapshot_id = insert_snapshot(conn)
    insert_trip_update(conn, snapshot_id, 0, "867")

    with pytest.raises(CheckViolation):
        insert_stop_time_update(
            conn, snapshot_id, datetime(2026, 10, 3, 12, 5, tzinfo=UTC), None
        )
