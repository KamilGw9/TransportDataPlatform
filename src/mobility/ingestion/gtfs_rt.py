from datetime import UTC, datetime

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from mobility.ingestion.archive import FetchAttempt, archive

MOBILIS_FEEDS = {
    "krakow_ztp_m_vehicle_positions": "https://gtfs.ztp.krakow.pl/VehiclePositions_M.pb",
    "krakow_ztp_m_trip_updates": "https://gtfs.ztp.krakow.pl/TripUpdates_M.pb",
    "krakow_ztp_m_service_alerts": "https://gtfs.ztp.krakow.pl/ServiceAlerts_M.pb",
}


def validate_feed_message(data: bytes) -> None:
    message = gtfs_realtime_pb2.FeedMessage()
    try:
        message.ParseFromString(data)
    except DecodeError as e:
        raise ValueError("Downloaded data is not a GTFS-RT message") from e
    # Protobuf parses some foreign payloads, such as empty bytes, without error;
    # a valid feed always has the required header fields.
    if not message.IsInitialized():
        raise ValueError("GTFS-RT message lacks required fields")


def raw_object_key(source_id: str, sha256: str, fetched_at: datetime) -> str:
    # Snapshots are partitioned by UTC fetch date, so identical content is
    # stored once per day while fetch_attempt keeps the full timeline.
    date = fetched_at.astimezone(UTC).date().isoformat()
    return f"raw/gtfs_rt/source_id={source_id}/date={date}/sha256={sha256}.pb"


def archive_snapshot(client, bucket: str, source_id: str, url: str) -> FetchAttempt:
    return archive(
        client,
        bucket,
        source_id,
        url,
        validate=validate_feed_message,
        object_key=lambda sha256, fetched_at: raw_object_key(
            source_id, sha256, fetched_at
        ),
    )
