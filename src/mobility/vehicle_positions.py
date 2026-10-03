from dataclasses import dataclass
from datetime import UTC, datetime

from google.protobuf.message import Message
from google.transit import gtfs_realtime_pb2

from mobility.ingestion.archive import describe_error, sha256_hex

SOURCE_ID = "krakow_ztp_m_vehicle_positions"


@dataclass(frozen=True)
class VehiclePositionSnapshot:
    feed_timestamp: datetime | None
    positions: list[tuple]


def optional_field(message: Message, field: str):
    # GTFS-RT uses proto2, where an unset field reads as 0 or "". A missing
    # bearing must not become a heading of 0 degrees.
    return getattr(message, field) if message.HasField(field) else None


def optional_enum_name(message: Message, field: str) -> str | None:
    value = optional_field(message, field)
    if value is None:
        return None
    enum_type = message.DESCRIPTOR.fields_by_name[field].enum_type
    return enum_type.values_by_number[value].name


def optional_timestamp(message: Message, field: str) -> datetime | None:
    value = optional_field(message, field)
    return None if value is None else datetime.fromtimestamp(value, UTC)


def position_row(entity_id: str, vehicle: Message) -> tuple:
    trip = vehicle.trip
    position = vehicle.position
    return (
        entity_id,
        optional_field(vehicle.vehicle, "id"),
        optional_field(vehicle.vehicle, "label"),
        optional_field(trip, "trip_id"),
        optional_field(trip, "route_id"),
        optional_field(trip, "direction_id"),
        optional_enum_name(trip, "schedule_relationship"),
        optional_field(position, "latitude"),
        optional_field(position, "longitude"),
        optional_field(position, "bearing"),
        optional_field(position, "speed"),
        optional_enum_name(vehicle, "current_status"),
        optional_field(vehicle, "current_stop_sequence"),
        optional_field(vehicle, "stop_id"),
        optional_timestamp(vehicle, "timestamp"),
    )


def parse_snapshot(data: bytes) -> VehiclePositionSnapshot:
    message = gtfs_realtime_pb2.FeedMessage()
    message.ParseFromString(data)
    positions = [
        position_row(entity.id, entity.vehicle)
        for entity in message.entity
        if entity.HasField("vehicle")
    ]
    return VehiclePositionSnapshot(
        optional_timestamp(message.header, "timestamp"), positions
    )


@dataclass(frozen=True)
class VehiclePositionLoad:
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
        SELECT 1 FROM metadata.vehicle_position_load AS load
        WHERE load.snapshot_sha256 = attempt.sha256 AND load.status = 'loaded'
    )
ORDER BY attempt.sha256, attempt.fetched_at
"""


def pending_snapshots(conn, source_id: str) -> list[tuple[str, str]]:
    """Return the hash and object key of each stored snapshot not yet loaded."""
    return conn.execute(_SELECT_PENDING_SNAPSHOTS, (source_id,)).fetchall()


_INSERT_LOAD = """
INSERT INTO metadata.vehicle_position_load
    (snapshot_sha256, object_key, started_at, status, error)
VALUES (%s, %s, %s, %s, %s)
"""


def record_load(conn, load: VehiclePositionLoad) -> None:
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
) -> VehiclePositionLoad:
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
        loaded = VehiclePositionLoad(snapshot_sha256, object_key, started_at, "loaded")
        with conn.transaction():
            conn.execute(
                "INSERT INTO staging.vehicle_position_snapshot VALUES (%s, %s)",
                (snapshot_sha256, snapshot.feed_timestamp),
            )
            with (
                conn.cursor() as cursor,
                cursor.copy("COPY staging.vehicle_position FROM STDIN") as copy,
            ):
                for position in snapshot.positions:
                    copy.write_row((snapshot_sha256, *position))
            record_load(conn, loaded)
    except Exception as e:
        # Same boundary as load_schedule: the failure is recorded after the
        # rollback so that it is kept.
        failed = VehiclePositionLoad(
            snapshot_sha256, object_key, started_at, "failed", describe_error(e)
        )
        record_load(conn, failed)
        return failed
    return loaded
