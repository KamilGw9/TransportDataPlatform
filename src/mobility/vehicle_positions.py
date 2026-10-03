from dataclasses import dataclass
from datetime import UTC, datetime

from google.protobuf.message import Message
from google.transit import gtfs_realtime_pb2


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
