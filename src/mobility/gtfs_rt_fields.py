from datetime import UTC, datetime

from google.protobuf.message import Message


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
