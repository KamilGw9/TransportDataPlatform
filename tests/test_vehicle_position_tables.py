"""Check the vehicle position staging tables against the local PostgreSQL.

Run with the services from make up and the variables from .env loaded:
    set -a; source .env; set +a
    uv run pytest -m integration
"""

import io
from datetime import UTC, datetime

import psycopg
import pytest
from google.transit import gtfs_realtime_pb2
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from mobility.ingestion.archive import sha256_hex
from mobility.vehicle_positions import load_snapshot, pending_snapshots

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


def snapshot_data(direction_ids: list[int]) -> bytes:
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 1791036302
    for number, direction_id in enumerate(direction_ids):
        vehicle = message.entity.add(id=f"vehicle_{number}").vehicle
        vehicle.trip.trip_id = f"1685_{number}"
        vehicle.trip.direction_id = direction_id
    return message.SerializeToString()


class FakeS3:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": io.BytesIO(self.data)}


def insert_stored_attempt(
    conn: psycopg.Connection, sha256: str, object_key: str, fetched_at: datetime
) -> None:
    conn.execute(
        """
        INSERT INTO metadata.fetch_attempt
            (source_id, url, fetched_at, status, size_bytes, sha256, object_key)
        VALUES ('test_vehicle_positions', 'https://example.test/vp.pb', %s,
            'stored', 10, %s, %s)
        """,
        (fetched_at, sha256, object_key),
    )


def count_positions(conn: psycopg.Connection, snapshot_sha256: str) -> int:
    [count] = conn.execute(
        "SELECT count(*) FROM staging.vehicle_position WHERE snapshot_sha256 = %s",
        (snapshot_sha256,),
    ).fetchone()
    return count


def test_load_snapshot_stores_positions_and_feed_timestamp(
    conn: psycopg.Connection,
) -> None:
    data = snapshot_data([0, 1])
    snapshot_sha256 = sha256_hex(data)

    load = load_snapshot(FakeS3(data), "bucket", conn, snapshot_sha256, "a.pb")

    assert load.status == "loaded"
    assert count_positions(conn, snapshot_sha256) == 2
    assert conn.execute(
        """
        SELECT feed_timestamp FROM staging.vehicle_position_snapshot
        WHERE snapshot_sha256 = %s
        """,
        (snapshot_sha256,),
    ).fetchone() == (datetime(2026, 10, 3, 14, 5, 2, tzinfo=UTC),)


def test_pending_snapshots_skip_loaded_and_repeated_ones(
    conn: psycopg.Connection,
) -> None:
    loaded_data = snapshot_data([0])
    loaded_sha256 = sha256_hex(loaded_data)
    insert_stored_attempt(
        conn, loaded_sha256, "loaded.pb", datetime(2026, 10, 3, tzinfo=UTC)
    )
    load_snapshot(FakeS3(loaded_data), "bucket", conn, loaded_sha256, "loaded.pb")
    # The same content stored again after midnight UTC gets a second object.
    insert_stored_attempt(
        conn,
        SNAPSHOT,
        "date=2026-10-03/a.pb",
        datetime(2026, 10, 3, 23, 59, tzinfo=UTC),
    )
    insert_stored_attempt(
        conn, SNAPSHOT, "date=2026-10-04/a.pb", datetime(2026, 10, 4, 0, 1, tzinfo=UTC)
    )

    assert pending_snapshots(conn, "test_vehicle_positions") == [
        (SNAPSHOT, "date=2026-10-03/a.pb")
    ]


def test_load_snapshot_rolls_back_snapshot_with_invalid_position(
    conn: psycopg.Connection,
) -> None:
    data = snapshot_data([0, 2])
    snapshot_sha256 = sha256_hex(data)

    load = load_snapshot(FakeS3(data), "bucket", conn, snapshot_sha256, "a.pb")

    assert load.status == "failed"
    assert load.error.startswith("CheckViolation")
    assert count_positions(conn, snapshot_sha256) == 0
    assert (
        conn.execute(
            "SELECT 1 FROM staging.vehicle_position_snapshot WHERE snapshot_sha256 = %s",
            (snapshot_sha256,),
        ).fetchone()
        is None
    )
    [error] = conn.execute(
        """
        SELECT error FROM metadata.vehicle_position_load
        WHERE snapshot_sha256 = %s
        """,
        (snapshot_sha256,),
    ).fetchone()
    assert error == load.error
