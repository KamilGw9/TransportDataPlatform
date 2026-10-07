from dataclasses import dataclass
from datetime import datetime

from google.protobuf.message import Message
from google.transit import gtfs_realtime_pb2

from mobility.gtfs_rt_fields import (
    optional_enum_name,
    optional_field,
    optional_timestamp,
)


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
