"""Check VehiclePositions parsing on GTFS-RT messages built in memory."""

from datetime import UTC, datetime

import pytest
from google.transit import gtfs_realtime_pb2

from mobility.vehicle_positions import parse_snapshot

VehiclePosition = gtfs_realtime_pb2.VehiclePosition


def feed_message() -> gtfs_realtime_pb2.FeedMessage:
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 1791036302
    return message


def add_mobilis_vehicle(message: gtfs_realtime_pb2.FeedMessage) -> None:
    """Add an entity shaped like the ones in the Mobilis feed."""
    entity = message.entity.add(id="vehicle_401")
    vehicle = entity.vehicle
    vehicle.trip.trip_id = "1685_13717"
    vehicle.trip.route_id = "147"
    vehicle.trip.direction_id = 0
    vehicle.trip.schedule_relationship = gtfs_realtime_pb2.TripDescriptor.SCHEDULED
    vehicle.position.latitude = 50.0748405
    vehicle.position.longitude = 19.9363594
    vehicle.position.bearing = 270
    vehicle.position.speed = 0
    vehicle.current_stop_sequence = 1
    vehicle.current_status = VehiclePosition.STOPPED_AT
    vehicle.timestamp = 1791036298
    vehicle.stop_id = "3947"
    vehicle.vehicle.id = "401"
    vehicle.vehicle.label = "401"


def test_parse_snapshot_reads_mobilis_vehicle() -> None:
    message = feed_message()
    add_mobilis_vehicle(message)

    snapshot = parse_snapshot(message.SerializeToString())

    assert snapshot.feed_timestamp == datetime(2026, 10, 3, 14, 5, 2, tzinfo=UTC)
    [position] = snapshot.positions
    assert position == (
        "vehicle_401",
        "401",
        "401",
        "1685_13717",
        "147",
        0,
        "SCHEDULED",
        pytest.approx(50.0748405),
        pytest.approx(19.9363594),
        270.0,
        0.0,
        "STOPPED_AT",
        1,
        "3947",
        datetime(2026, 10, 3, 14, 4, 58, tzinfo=UTC),
    )


def test_parse_snapshot_keeps_unset_fields_empty_instead_of_zero() -> None:
    message = feed_message()
    entity = message.entity.add(id="vehicle_402")
    entity.vehicle.trip.trip_id = "1685_13718"
    entity.vehicle.position.latitude = 50.06
    entity.vehicle.position.longitude = 19.94

    [position] = parse_snapshot(message.SerializeToString()).positions

    assert position == (
        "vehicle_402",
        None,
        None,
        "1685_13718",
        None,
        None,
        None,
        pytest.approx(50.06),
        pytest.approx(19.94),
        None,
        None,
        None,
        None,
        None,
        None,
    )


def test_parse_snapshot_skips_entities_without_vehicle() -> None:
    message = feed_message()
    add_mobilis_vehicle(message)
    message.entity.add(id="trip_1685_13717").trip_update.trip.trip_id = "1685_13717"

    snapshot = parse_snapshot(message.SerializeToString())

    assert [position[0] for position in snapshot.positions] == ["vehicle_401"]
