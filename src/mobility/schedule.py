import csv
import io
import zipfile
from collections.abc import Callable, Iterator
from datetime import date, datetime

Row = dict[str, str]


def parse_gtfs_time(value: str) -> int:
    """Convert H:MM:SS to seconds from the start of the service day."""
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    # Hours may exceed 23 for trips that run after midnight.
    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise ValueError(f"invalid GTFS time: {value!r}")
    return hours * 3600 + minutes * 60 + seconds


def parse_gtfs_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def parse_flag(value: str) -> bool:
    if value not in ("0", "1"):
        raise ValueError(f"expected 0 or 1, got {value!r}")
    return value == "1"


def optional_text(row: Row, column: str) -> str | None:
    # Optional GTFS columns may be empty or missing from the header.
    return row.get(column) or None


def optional_int(row: Row, column: str) -> int | None:
    value = row.get(column)
    return int(value) if value else None


def route_row(row: Row) -> tuple:
    return (
        row["route_id"],
        optional_text(row, "route_short_name"),
        optional_text(row, "route_long_name"),
        int(row["route_type"]),
    )


def stop_row(row: Row) -> tuple:
    lat = optional_text(row, "stop_lat")
    lon = optional_text(row, "stop_lon")
    return (
        row["stop_id"],
        optional_text(row, "stop_code"),
        optional_text(row, "stop_name"),
        None if lat is None else float(lat),
        None if lon is None else float(lon),
    )


def trip_row(row: Row) -> tuple:
    return (
        row["trip_id"],
        row["route_id"],
        row["service_id"],
        optional_text(row, "trip_headsign"),
        optional_int(row, "direction_id"),
        optional_text(row, "block_id"),
        optional_text(row, "shape_id"),
    )


def stop_time_row(row: Row) -> tuple:
    return (
        row["trip_id"],
        int(row["stop_sequence"]),
        row["stop_id"],
        parse_gtfs_time(row["arrival_time"]),
        parse_gtfs_time(row["departure_time"]),
        optional_int(row, "pickup_type"),
        optional_int(row, "drop_off_type"),
    )


WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def calendar_row(row: Row) -> tuple:
    return (
        row["service_id"],
        *(parse_flag(row[day]) for day in WEEKDAYS),
        parse_gtfs_date(row["start_date"]),
        parse_gtfs_date(row["end_date"]),
    )


def calendar_date_row(row: Row) -> tuple:
    return (
        row["service_id"],
        parse_gtfs_date(row["date"]),
        int(row["exception_type"]),
    )


# Loading order follows the foreign keys: routes and stops before trips,
# trips before stop times.
SCHEDULE_FILES: list[tuple[str, str, Callable[[Row], tuple]]] = [
    ("routes.txt", "schedule_route", route_row),
    ("stops.txt", "schedule_stop", stop_row),
    ("trips.txt", "schedule_trip", trip_row),
    ("stop_times.txt", "schedule_stop_time", stop_time_row),
    ("calendar.txt", "schedule_calendar", calendar_row),
    ("calendar_dates.txt", "schedule_calendar_date", calendar_date_row),
]


def parse_file(
    zip_file: zipfile.ZipFile, file_name: str, to_row: Callable[[Row], tuple]
) -> Iterator[tuple]:
    with zip_file.open(file_name) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        for row in reader:
            try:
                yield to_row(row)
            except (KeyError, ValueError) as e:
                raise ValueError(f"{file_name} line {reader.line_num}: {e!r}") from e
