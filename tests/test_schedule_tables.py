"""Check the schedule staging tables against the local PostgreSQL.

Run with the services from make up and the variables from .env loaded:
    set -a; source .env; set +a
    uv run pytest -m integration
"""

import io
import zipfile
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import sql
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from mobility.ingestion.archive import sha256_hex
from mobility.schedule import is_loaded, load_schedule

pytestmark = pytest.mark.integration

VERSION = "c" * 64
OTHER_VERSION = "d" * 64


def insert_trip(conn: psycopg.Connection, version: str) -> None:
    conn.execute(
        "INSERT INTO staging.schedule_route VALUES (%s, '100', '100', '100', 3)",
        (version,),
    )
    conn.execute(
        "INSERT INTO staging.schedule_stop VALUES (%s, '12', '101-05', 'Stella', 50.07, 20.0)",
        (version,),
    )
    conn.execute(
        """
        INSERT INTO staging.schedule_trip
        VALUES (%s, '1684_1', '100', '1684_PO', 'Kopiec', 0, '101-01', '1')
        """,
        (version,),
    )


def insert_stop_time(
    conn: psycopg.Connection, trip_id: str, arrival: int, departure: int
) -> None:
    conn.execute(
        """
        INSERT INTO staging.schedule_stop_time
        VALUES (%s, %s, 1, '12', %s, %s, 0, 0)
        """,
        (VERSION, trip_id, arrival, departure),
    )


def insert_load(conn: psycopg.Connection, status: str, error: str | None) -> None:
    conn.execute(
        """
        INSERT INTO metadata.schedule_load
            (schedule_sha256, object_key, started_at, status, error)
        VALUES (%s, 'raw/gtfs/schedule.zip', %s, %s, %s)
        """,
        (VERSION, datetime(2026, 10, 3, tzinfo=UTC), status, error),
    )


def test_stop_time_after_midnight_is_accepted(conn: psycopg.Connection) -> None:
    insert_trip(conn, VERSION)

    insert_stop_time(conn, "1684_1", arrival=99540, departure=99540)  # 27:39:00

    assert conn.execute(
        "SELECT arrival_seconds FROM staging.schedule_stop_time WHERE schedule_sha256 = %s",
        (VERSION,),
    ).fetchall() == [(99540,)]


def test_same_trip_id_may_exist_in_two_versions(conn: psycopg.Connection) -> None:
    insert_trip(conn, VERSION)
    insert_trip(conn, OTHER_VERSION)


def test_stop_time_rejects_unknown_trip(conn: psycopg.Connection) -> None:
    insert_trip(conn, VERSION)

    with pytest.raises(ForeignKeyViolation):
        insert_stop_time(conn, "missing_trip", arrival=0, departure=0)


def test_stop_time_rejects_departure_before_arrival(conn: psycopg.Connection) -> None:
    insert_trip(conn, VERSION)

    with pytest.raises(CheckViolation):
        insert_stop_time(conn, "1684_1", arrival=600, departure=540)


def test_version_is_loaded_at_most_once(conn: psycopg.Connection) -> None:
    insert_load(conn, "failed", "BadZipFile: truncated")
    insert_load(conn, "failed", "BadZipFile: truncated")
    insert_load(conn, "loaded", None)

    with pytest.raises(UniqueViolation):
        insert_load(conn, "loaded", None)


def test_failed_load_needs_an_error(conn: psycopg.Connection) -> None:
    with pytest.raises(CheckViolation):
        insert_load(conn, "failed", None)


SCHEDULE_FILES = {
    "routes.txt": "route_id,route_short_name,route_long_name,route_type\n"
    "100,100,100,3\n",
    "stops.txt": "stop_id,stop_code,stop_name,stop_lat,stop_lon\n"
    "12,101-05,Stella,50.07,20.0\n",
    "trips.txt": "route_id,service_id,trip_id,direction_id\n100,1684_PO,1684_1,0\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
    "1684_1,23:59:00,23:59:00,12,1\n"
    "1684_1,24:04:00,24:04:00,12,2\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,"
    "saturday,sunday,start_date,end_date\n"
    "1684_PO,0,0,0,0,0,0,0,20260927,20270131\n",
    "calendar_dates.txt": "service_id,date,exception_type\n1684_PO,20261005,1\n",
}


def schedule_zip(files: dict[str, str] = SCHEDULE_FILES) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        for name, content in files.items():
            zip_file.writestr(name, content)
    return buffer.getvalue()


class FakeS3:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": io.BytesIO(self.data)}


def count_rows(conn: psycopg.Connection, table: str, version: str) -> int:
    query = sql.SQL(
        "SELECT count(*) FROM staging.{} WHERE schedule_sha256 = %s"
    ).format(sql.Identifier(table))
    [count] = conn.execute(query, (version,)).fetchone()
    return count


def load_errors(conn: psycopg.Connection, version: str) -> list[str]:
    rows = conn.execute(
        "SELECT error FROM metadata.schedule_load WHERE schedule_sha256 = %s",
        (version,),
    ).fetchall()
    return [error for (error,) in rows]


def test_load_schedule_stores_complete_version(conn: psycopg.Connection) -> None:
    data = schedule_zip()
    version = sha256_hex(data)

    load = load_schedule(FakeS3(data), "bucket", conn, version, "raw/gtfs/a.zip")

    assert load.status == "loaded"
    assert is_loaded(conn, version)
    assert count_rows(conn, "schedule_stop_time", version) == 2
    assert count_rows(conn, "schedule_calendar_date", version) == 1


def test_load_schedule_rolls_back_version_with_unknown_stop(
    conn: psycopg.Connection,
) -> None:
    unknown_stop = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "1684_1,06:38:00,06:38:00,999,1\n"
    )
    data = schedule_zip(SCHEDULE_FILES | {"stop_times.txt": unknown_stop})
    version = sha256_hex(data)

    load = load_schedule(FakeS3(data), "bucket", conn, version, "raw/gtfs/a.zip")

    assert load.status == "failed"
    assert not is_loaded(conn, version)
    assert count_rows(conn, "schedule_trip", version) == 0
    [error] = load_errors(conn, version)
    assert error.startswith("ForeignKeyViolation")


def test_load_schedule_rejects_object_that_does_not_match_hash(
    conn: psycopg.Connection,
) -> None:
    version = "e" * 64

    load = load_schedule(
        FakeS3(schedule_zip()), "bucket", conn, version, "raw/gtfs/a.zip"
    )

    assert load.status == "failed"
    assert "does not match its SHA-256" in load.error
    assert count_rows(conn, "schedule_route", version) == 0
