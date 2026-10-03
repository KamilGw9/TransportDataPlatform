"""Check the schedule staging tables against the local PostgreSQL.

Run with the services from make up and the variables from .env loaded:
    set -a; source .env; set +a
    uv run pytest -m integration
"""

from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

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
