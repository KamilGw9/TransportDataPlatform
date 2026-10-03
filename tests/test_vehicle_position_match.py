"""Check how vehicle positions are matched to schedule versions.

Run with the services from make up and the variables from .env loaded:
    set -a; source .env; set +a
    uv run pytest -m integration
"""

from datetime import UTC, datetime

import psycopg
import pytest

pytestmark = pytest.mark.integration

OLD_VERSION = "1" * 64
NEW_VERSION = "2" * 64
EARLY_SNAPSHOT = "a" * 64
LATE_SNAPSHOT = "b" * 64


def insert_attempt(
    conn: psycopg.Connection, source_id: str, sha256: str, fetched_at: datetime
) -> None:
    conn.execute(
        """
        INSERT INTO metadata.fetch_attempt
            (source_id, url, fetched_at, status, size_bytes, sha256, object_key)
        VALUES (%s, 'https://example.test', %s, 'stored', 10, %s, 'key')
        """,
        (source_id, fetched_at, sha256),
    )


def insert_schedule_version(
    conn: psycopg.Connection, version: str, trip_id: str, archived_at: datetime
) -> None:
    insert_attempt(conn, "krakow_ztp_m", version, archived_at)
    conn.execute(
        """
        INSERT INTO metadata.schedule_load
            (schedule_sha256, object_key, started_at, status)
        VALUES (%s, 'key', %s, 'loaded')
        """,
        (version, archived_at),
    )
    conn.execute(
        "INSERT INTO staging.schedule_route VALUES (%s, '147', '147', NULL, 3)",
        (version,),
    )
    conn.execute(
        """
        INSERT INTO staging.schedule_trip (schedule_sha256, trip_id, route_id, service_id)
        VALUES (%s, %s, '147', 'PO')
        """,
        (version, trip_id),
    )


def insert_snapshot(
    conn: psycopg.Connection, snapshot: str, trip_id: str, fetched_at: datetime
) -> None:
    insert_attempt(conn, "krakow_ztp_m_vehicle_positions", snapshot, fetched_at)
    conn.execute(
        "INSERT INTO staging.vehicle_position_snapshot VALUES (%s, %s)",
        (snapshot, fetched_at),
    )
    conn.execute(
        """
        INSERT INTO staging.vehicle_position (snapshot_sha256, entity_id, trip_id, route_id)
        VALUES (%s, 'vehicle_401', %s, '147')
        """,
        (snapshot, trip_id),
    )


def test_position_is_matched_to_schedule_archived_before_snapshot(
    conn: psycopg.Connection,
) -> None:
    # Dates after any local data, so that real attempts in the development
    # database do not count as later schedule versions.
    insert_schedule_version(
        conn, OLD_VERSION, "1684_1", datetime(2030, 1, 1, tzinfo=UTC)
    )
    insert_schedule_version(
        conn, NEW_VERSION, "1685_1", datetime(2030, 1, 3, 9, 44, tzinfo=UTC)
    )
    insert_snapshot(conn, EARLY_SNAPSHOT, "1685_1", datetime(2030, 1, 3, 8, tzinfo=UTC))
    insert_snapshot(conn, LATE_SNAPSHOT, "1685_1", datetime(2030, 1, 3, 10, tzinfo=UTC))

    rows = conn.execute(
        """
        SELECT snapshot_sha256, schedule_sha256, trip_found
        FROM core.vehicle_position_match
        WHERE snapshot_sha256 = ANY(%s)
        ORDER BY first_fetched_at
        """,
        ([EARLY_SNAPSHOT, LATE_SNAPSHOT],),
    ).fetchall()

    assert rows == [
        (EARLY_SNAPSHOT, OLD_VERSION, False),
        (LATE_SNAPSHOT, NEW_VERSION, True),
    ]
