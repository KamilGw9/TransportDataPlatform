"""Check the TripUpdates staging tables against the local PostgreSQL.

Run with the services from make up and the variables from .env loaded:
    set -a; source .env; set +a
    uv run pytest -m integration
"""

import io
from datetime import UTC, date, datetime

import psycopg
import pytest
from google.transit import gtfs_realtime_pb2
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from mobility.ingestion.archive import connect_postgres, sha256_hex
from mobility.trip_updates import (
    STAGING_LOCK_KEY,
    load_snapshot,
    lock_staging,
    pending_snapshots,
    prune_staging,
    snapshots_to_reload,
)

pytestmark = pytest.mark.integration

SNAPSHOT = "a" * 64


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


def test_snapshot_is_in_staging_at_most_once(conn: psycopg.Connection) -> None:
    insert_snapshot(conn)

    with pytest.raises(UniqueViolation):
        insert_snapshot(conn)


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


def snapshot_data(arrival_delays: list[int | None]) -> bytes:
    """Build a snapshot with one trip whose stops arrive with these delays."""
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 1791404400
    trip_update = message.entity.add(id="trip_1686_9067").trip_update
    trip_update.trip.trip_id = "1686_9067"
    for stop_sequence, delay in enumerate(arrival_delays, start=1):
        update = trip_update.stop_time_update.add(stop_sequence=stop_sequence)
        update.arrival.time = 1791404400 + 60 * stop_sequence
        if delay is not None:
            update.arrival.delay = delay
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
        VALUES ('test_trip_updates', 'https://example.test/tu.pb', %s,
            'stored', 10, %s, %s)
        """,
        (fetched_at, sha256, object_key),
    )


def test_load_snapshot_stores_trips_and_stops_under_one_snapshot_id(
    conn: psycopg.Connection,
) -> None:
    data = snapshot_data([0, 60])
    snapshot_sha256 = sha256_hex(data)

    load = load_snapshot(FakeS3(data), "bucket", conn, snapshot_sha256, "a.pb")

    assert load.status == "loaded"
    assert conn.execute(
        """
        SELECT snapshot.feed_timestamp, trip.trip_id, count(*)
        FROM staging.trip_update_snapshot AS snapshot
        JOIN staging.trip_update AS trip USING (snapshot_id)
        JOIN staging.stop_time_update USING (snapshot_id, entity_index)
        WHERE snapshot.snapshot_sha256 = %s
        GROUP BY snapshot.feed_timestamp, trip.trip_id
        """,
        (snapshot_sha256,),
    ).fetchall() == [(datetime(2026, 10, 7, 20, 20, tzinfo=UTC), "1686_9067", 2)]


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

    assert pending_snapshots(conn, "test_trip_updates") == [
        (SNAPSHOT, "date=2026-10-03/a.pb")
    ]


def remove_from_staging(conn: psycopg.Connection, snapshot_sha256: str) -> None:
    [snapshot_id] = conn.execute(
        "SELECT snapshot_id FROM staging.trip_update_snapshot"
        " WHERE snapshot_sha256 = %s",
        (snapshot_sha256,),
    ).fetchone()
    for statement in [
        "DELETE FROM staging.stop_time_update WHERE snapshot_id = %s",
        "DELETE FROM staging.trip_update WHERE snapshot_id = %s",
        "DELETE FROM staging.trip_update_snapshot WHERE snapshot_id = %s",
    ]:
        conn.execute(statement, (snapshot_id,))


def test_snapshots_to_reload_are_stored_on_the_dates_and_missing_from_staging(
    conn: psycopg.Connection,
) -> None:
    in_staging = snapshot_data([0])
    insert_stored_attempt(
        conn, sha256_hex(in_staging), "in.pb", datetime(2026, 10, 3, 8, tzinfo=UTC)
    )
    load_snapshot(FakeS3(in_staging), "bucket", conn, sha256_hex(in_staging), "in.pb")
    insert_stored_attempt(
        conn, SNAPSHOT, "missing.pb", datetime(2026, 10, 3, 23, 59, tzinfo=UTC)
    )
    insert_stored_attempt(
        conn, "b" * 64, "next_day.pb", datetime(2026, 10, 4, 0, 1, tzinfo=UTC)
    )

    assert snapshots_to_reload(
        conn, "test_trip_updates", date(2026, 10, 3), date(2026, 10, 3)
    ) == [(SNAPSHOT, "missing.pb")]


def test_snapshot_removed_from_staging_is_loaded_again(
    conn: psycopg.Connection,
) -> None:
    data = snapshot_data([0, 60])
    snapshot_sha256 = sha256_hex(data)
    load_snapshot(FakeS3(data), "bucket", conn, snapshot_sha256, "a.pb")
    remove_from_staging(conn, snapshot_sha256)

    load = load_snapshot(FakeS3(data), "bucket", conn, snapshot_sha256, "a.pb")

    assert load.status == "loaded"
    assert conn.execute(
        "SELECT count(*) FROM metadata.trip_update_load"
        " WHERE snapshot_sha256 = %s AND status = 'loaded'",
        (snapshot_sha256,),
    ).fetchone() == (2,)


def test_load_snapshot_rolls_back_snapshot_with_time_but_no_delay(
    conn: psycopg.Connection,
) -> None:
    data = snapshot_data([0, None])
    snapshot_sha256 = sha256_hex(data)

    load = load_snapshot(FakeS3(data), "bucket", conn, snapshot_sha256, "a.pb")

    assert load.status == "failed"
    assert load.error.startswith("CheckViolation")
    # The foreign keys leave no stop time updates without the snapshot row.
    assert (
        conn.execute(
            "SELECT 1 FROM staging.trip_update_snapshot WHERE snapshot_sha256 = %s",
            (snapshot_sha256,),
        ).fetchone()
        is None
    )
    [error] = conn.execute(
        "SELECT error FROM metadata.trip_update_load WHERE snapshot_sha256 = %s",
        (snapshot_sha256,),
    ).fetchone()
    assert error == load.error


def try_lock_staging(conn: psycopg.Connection) -> bool:
    return conn.execute(
        "SELECT pg_try_advisory_lock(%s)", (STAGING_LOCK_KEY,)
    ).fetchone()[0]


def test_staging_lock_is_held_until_the_writer_disconnects() -> None:
    with connect_postgres() as writer:
        lock_staging(writer)
        with connect_postgres() as other:
            assert not try_lock_staging(other)

    with connect_postgres() as other:
        assert try_lock_staging(other)


def staged_snapshot(conn: psycopg.Connection, feed_timestamp: datetime) -> int:
    snapshot_id = conn.execute(
        """
        INSERT INTO staging.trip_update_snapshot (snapshot_sha256, feed_timestamp)
        VALUES (md5(random()::text) || md5(random()::text), %s)
        RETURNING snapshot_id
        """,
        (feed_timestamp,),
    ).fetchone()[0]
    insert_trip_update(conn, snapshot_id, 0, "867")
    insert_stop_time_update(conn, snapshot_id, None, None)
    return snapshot_id


def staged_snapshot_ids(conn: psycopg.Connection, snapshot_ids: list[int]) -> list[int]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT snapshot_id FROM staging.trip_update_snapshot"
            " WHERE snapshot_id = ANY(%s) ORDER BY snapshot_id",
            (snapshot_ids,),
        )
    ]


def test_prune_staging_deletes_built_snapshots_before_the_window(
    conn: psycopg.Connection,
) -> None:
    # Long before the collected data in the local database.
    window_start = datetime(2001, 10, 2, tzinfo=UTC)
    old = staged_snapshot(conn, datetime(2001, 10, 1, 23, 59, tzinfo=UTC))
    in_window = staged_snapshot(conn, datetime(2001, 10, 2, tzinfo=UTC))
    # Reloaded from RAW after the last build.
    old_not_built = staged_snapshot(conn, datetime(2001, 10, 1, 12, tzinfo=UTC))

    pruned = prune_staging(conn, window_start, built_snapshot_id=in_window)

    assert pruned == 1
    assert staged_snapshot_ids(conn, [old, in_window, old_not_built]) == [
        in_window,
        old_not_built,
    ]
    assert (
        conn.execute(
            "SELECT count(*) FROM staging.stop_time_update WHERE snapshot_id = %s",
            (old,),
        ).fetchone()[0]
        == 0
    )


def test_prune_staging_before_the_first_build_keeps_everything(
    conn: psycopg.Connection,
) -> None:
    old = staged_snapshot(conn, datetime(2001, 10, 1, tzinfo=UTC))

    pruned = prune_staging(conn, datetime(2001, 10, 2, tzinfo=UTC), None)

    assert pruned == 0
    assert staged_snapshot_ids(conn, [old]) == [old]
