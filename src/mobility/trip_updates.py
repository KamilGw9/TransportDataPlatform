from dataclasses import dataclass
from datetime import UTC, datetime

from google.protobuf.message import Message
from google.transit import gtfs_realtime_pb2

from mobility.gtfs_rt_fields import (
    optional_enum_name,
    optional_field,
    optional_timestamp,
)
from mobility.ingestion.archive import describe_error, sha256_hex

SOURCE_ID = "krakow_ztp_m_trip_updates"


@dataclass(frozen=True)
class TripUpdateSnapshot:
    feed_timestamp: datetime | None
    trip_updates: list[tuple]
    stop_time_updates: list[tuple]


def trip_update_row(entity_index: int, entity_id: str, trip_update: Message) -> tuple:
    trip = trip_update.trip
    return (
        entity_index,
        entity_id,
        optional_field(trip, "trip_id"),
        optional_field(trip, "route_id"),
        optional_field(trip, "direction_id"),
        optional_enum_name(trip, "schedule_relationship"),
        optional_field(trip_update.vehicle, "id"),
        optional_field(trip_update.vehicle, "label"),
        optional_timestamp(trip_update, "timestamp"),
    )


def stop_time_update_row(entity_index: int, update: Message) -> tuple:
    # An unset arrival reads as an empty StopTimeEvent, whose time and delay
    # are unset too, so no HasField("arrival") check is needed.
    return (
        entity_index,
        optional_field(update, "stop_sequence"),
        optional_field(update, "stop_id"),
        optional_enum_name(update, "schedule_relationship"),
        optional_timestamp(update.arrival, "time"),
        optional_field(update.arrival, "delay"),
        optional_timestamp(update.departure, "time"),
        optional_field(update.departure, "delay"),
    )


def parse_snapshot(data: bytes) -> TripUpdateSnapshot:
    message = gtfs_realtime_pb2.FeedMessage()
    message.ParseFromString(data)
    trip_updates = []
    stop_time_updates = []
    for entity_index, entity in enumerate(message.entity):
        if not entity.HasField("trip_update"):
            continue
        trip_update = entity.trip_update
        trip_updates.append(trip_update_row(entity_index, entity.id, trip_update))
        stop_time_updates.extend(
            stop_time_update_row(entity_index, update)
            for update in trip_update.stop_time_update
        )
    return TripUpdateSnapshot(
        optional_timestamp(message.header, "timestamp"),
        trip_updates,
        stop_time_updates,
    )


@dataclass(frozen=True)
class TripUpdateLoad:
    snapshot_sha256: str
    object_key: str
    started_at: datetime
    status: str
    error: str | None = None


# A snapshot stored on two UTC dates has two objects with the same content;
# either of them will do.
_SELECT_PENDING_SNAPSHOTS = """
SELECT DISTINCT ON (attempt.sha256) attempt.sha256, attempt.object_key
FROM metadata.fetch_attempt AS attempt
WHERE attempt.source_id = %s
    AND attempt.status = 'stored'
    AND NOT EXISTS (
        SELECT 1 FROM metadata.trip_update_load AS load
        WHERE load.snapshot_sha256 = attempt.sha256 AND load.status = 'loaded'
    )
ORDER BY attempt.sha256, attempt.fetched_at
"""


def pending_snapshots(conn, source_id: str) -> list[tuple[str, str]]:
    """Return the hash and object key of each stored snapshot not yet loaded."""
    return conn.execute(_SELECT_PENDING_SNAPSHOTS, (source_id,)).fetchall()


_INSERT_LOAD = """
INSERT INTO metadata.trip_update_load
    (snapshot_sha256, object_key, started_at, status, error)
VALUES (%s, %s, %s, %s, %s)
"""


def record_load(conn, load: TripUpdateLoad) -> None:
    conn.execute(
        _INSERT_LOAD,
        (
            load.snapshot_sha256,
            load.object_key,
            load.started_at,
            load.status,
            load.error,
        ),
    )


def load_snapshot(
    client, bucket: str, conn, snapshot_sha256: str, object_key: str
) -> TripUpdateLoad:
    """Load one archived snapshot into staging and record the attempt.

    Never raises: a failure rolls back the snapshot and is recorded as a
    failed load.
    """
    started_at = datetime.now(UTC)
    try:
        data = client.get_object(Bucket=bucket, Key=object_key)["Body"].read()
        if sha256_hex(data) != snapshot_sha256:
            raise ValueError(f"{object_key} does not match its SHA-256")
        snapshot = parse_snapshot(data)
        loaded = TripUpdateLoad(snapshot_sha256, object_key, started_at, "loaded")
        with conn.transaction():
            [snapshot_id] = conn.execute(
                """
                INSERT INTO staging.trip_update_snapshot
                    (snapshot_sha256, feed_timestamp)
                VALUES (%s, %s)
                RETURNING snapshot_id
                """,
                (snapshot_sha256, snapshot.feed_timestamp),
            ).fetchone()
            with conn.cursor() as cursor:
                with cursor.copy("COPY staging.trip_update FROM STDIN") as copy:
                    for trip_update in snapshot.trip_updates:
                        copy.write_row((snapshot_id, *trip_update))
                with cursor.copy("COPY staging.stop_time_update FROM STDIN") as copy:
                    for stop_time_update in snapshot.stop_time_updates:
                        copy.write_row((snapshot_id, *stop_time_update))
            record_load(conn, loaded)
    except Exception as e:
        # Same boundary as load_schedule: the failure is recorded after the
        # rollback so that it is kept.
        failed = TripUpdateLoad(
            snapshot_sha256, object_key, started_at, "failed", describe_error(e)
        )
        record_load(conn, failed)
        return failed
    return loaded
