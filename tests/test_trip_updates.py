"""Check TripUpdates parsing on GTFS-RT messages built in memory."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from google.transit import gtfs_realtime_pb2

from mobility.trip_updates import parse_snapshot, staging_window_start

StopTimeUpdate = gtfs_realtime_pb2.TripUpdate.StopTimeUpdate


def feed_message() -> gtfs_realtime_pb2.FeedMessage:
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 1791404400
    return message


def add_mobilis_trip_update(
    message: gtfs_realtime_pb2.FeedMessage, vehicle_id: str
) -> gtfs_realtime_pb2.TripUpdate:
    """Add an entity shaped like the ones in the Mobilis feed.

    The first stop has only a departure, the last one only an arrival.
    """
    trip_update = message.entity.add(id="trip_1686_9067").trip_update
    trip_update.trip.trip_id = "1686_9067"
    trip_update.trip.route_id = "147"
    trip_update.trip.direction_id = 0
    trip_update.trip.schedule_relationship = gtfs_realtime_pb2.TripDescriptor.SCHEDULED
    trip_update.vehicle.id = vehicle_id
    trip_update.vehicle.label = vehicle_id
    trip_update.timestamp = 1791404395
    first = trip_update.stop_time_update.add(
        stop_sequence=1, stop_id="3947", schedule_relationship=StopTimeUpdate.SCHEDULED
    )
    first.departure.time = 1791404400
    first.departure.delay = 0
    last = trip_update.stop_time_update.add(
        stop_sequence=2, stop_id="3449", schedule_relationship=StopTimeUpdate.SCHEDULED
    )
    last.arrival.time = 1791404520
    last.arrival.delay = 60
    return trip_update


def test_parse_snapshot_reads_mobilis_trip_update() -> None:
    message = feed_message()
    add_mobilis_trip_update(message, "867")

    snapshot = parse_snapshot(message.SerializeToString())

    assert snapshot.feed_timestamp == datetime(2026, 10, 7, 20, 20, tzinfo=UTC)
    assert snapshot.trip_updates == [
        (
            0,
            "trip_1686_9067",
            "1686_9067",
            "147",
            0,
            "SCHEDULED",
            "867",
            "867",
            datetime(2026, 10, 7, 20, 19, 55, tzinfo=UTC),
        )
    ]
    assert snapshot.stop_time_updates == [
        (
            0,
            1,
            "3947",
            "SCHEDULED",
            None,
            None,
            datetime(2026, 10, 7, 20, 20, tzinfo=UTC),
            0,
        ),
        (
            0,
            2,
            "3449",
            "SCHEDULED",
            datetime(2026, 10, 7, 20, 22, tzinfo=UTC),
            60,
            None,
            None,
        ),
    ]


def test_parse_snapshot_keeps_trip_reported_by_two_vehicles_apart() -> None:
    message = feed_message()
    add_mobilis_trip_update(message, "867")
    add_mobilis_trip_update(message, "869")

    snapshot = parse_snapshot(message.SerializeToString())

    assert [(row[0], row[1], row[6]) for row in snapshot.trip_updates] == [
        (0, "trip_1686_9067", "867"),
        (1, "trip_1686_9067", "869"),
    ]
    assert [row[:2] for row in snapshot.stop_time_updates] == [
        (0, 1),
        (0, 2),
        (1, 1),
        (1, 2),
    ]


def test_parse_snapshot_reads_skipped_stop_without_times() -> None:
    message = feed_message()
    trip_update = add_mobilis_trip_update(message, "867")
    trip_update.stop_time_update.add(
        stop_sequence=3, stop_id="2322", schedule_relationship=StopTimeUpdate.SKIPPED
    )

    snapshot = parse_snapshot(message.SerializeToString())

    assert snapshot.stop_time_updates[-1] == (
        0,
        3,
        "2322",
        "SKIPPED",
        None,
        None,
        None,
        None,
    )


def test_staging_window_starts_at_utc_midnight_seven_days_before() -> None:
    # Already 10 October in Kraków, still 9 October in UTC.
    now = datetime(2026, 10, 10, 0, 30, tzinfo=ZoneInfo("Europe/Warsaw"))

    assert staging_window_start(now) == datetime(2026, 10, 2, tzinfo=UTC)
