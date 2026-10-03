import csv
import io
import logging
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime

from psycopg import sql

from mobility.ingestion.archive import describe_error, sha256_hex

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class ScheduleLoad:
    schedule_sha256: str
    object_key: str
    started_at: datetime
    status: str
    error: str | None = None


_SELECT_LATEST_VERSION = """
SELECT sha256, object_key
FROM metadata.fetch_attempt
WHERE source_id = %s AND status <> 'failed'
ORDER BY fetched_at DESC
LIMIT 1
"""


def latest_schedule_version(conn, source_id: str) -> tuple[str, str] | None:
    """Return the hash and object key of the most recently archived schedule."""
    return conn.execute(_SELECT_LATEST_VERSION, (source_id,)).fetchone()


def is_loaded(conn, schedule_sha256: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM metadata.schedule_load
        WHERE schedule_sha256 = %s AND status = 'loaded'
        """,
        (schedule_sha256,),
    ).fetchone()
    return row is not None


def copy_rows(conn, table: str, schedule_sha256: str, rows: Iterator[tuple]) -> int:
    statement = sql.SQL("COPY staging.{} FROM STDIN").format(sql.Identifier(table))
    count = 0
    with conn.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row((schedule_sha256, *row))
            count += 1
    return count


_INSERT_LOAD = """
INSERT INTO metadata.schedule_load
    (schedule_sha256, object_key, started_at, status, error)
VALUES (%s, %s, %s, %s, %s)
"""


def record_load(conn, load: ScheduleLoad) -> None:
    conn.execute(
        _INSERT_LOAD,
        (
            load.schedule_sha256,
            load.object_key,
            load.started_at,
            load.status,
            load.error,
        ),
    )


def load_schedule(
    client, bucket: str, conn, schedule_sha256: str, object_key: str
) -> ScheduleLoad:
    """Load one archived schedule version into staging and record the attempt.

    Never raises: a failure rolls back every row of the version and is
    recorded as a failed load.
    """
    started_at = datetime.now(UTC)
    try:
        data = client.get_object(Bucket=bucket, Key=object_key)["Body"].read()
        if sha256_hex(data) != schedule_sha256:
            raise ValueError(f"{object_key} does not match its SHA-256")
        loaded = ScheduleLoad(schedule_sha256, object_key, started_at, "loaded")
        # The rows and the "loaded" record commit together, so a version is
        # either complete or absent.
        with zipfile.ZipFile(io.BytesIO(data)) as zip_file, conn.transaction():
            for file_name, table, to_row in SCHEDULE_FILES:
                rows = parse_file(zip_file, file_name, to_row)
                count = copy_rows(conn, table, schedule_sha256, rows)
                logger.info("%s: %d rows", file_name, count)
            record_load(conn, loaded)
    except Exception as e:
        # Any failure must still produce a record, written after the rollback
        # so that it is kept.
        failed = ScheduleLoad(
            schedule_sha256, object_key, started_at, "failed", describe_error(e)
        )
        record_load(conn, failed)
        return failed
    return loaded
