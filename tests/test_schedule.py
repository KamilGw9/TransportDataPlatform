"""Check GTFS schedule parsing on small ZIP files built in memory."""

import io
import zipfile
from datetime import date

import pytest

from mobility.schedule import (
    WEEKDAYS,
    calendar_row,
    parse_file,
    parse_gtfs_time,
    stop_time_row,
)


def zip_with(file_name: str, content: str) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        zip_file.writestr(file_name, content.encode("utf-8"))
    return zipfile.ZipFile(buffer)


STOP_TIMES_HEADER = (
    "trip_id,arrival_time,departure_time,stop_id,stop_sequence,"
    "pickup_type,drop_off_type\n"
)


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("06:38:00", 23880), ("7:05:30", 25530), ("27:39:00", 99540)],
)
def test_parse_gtfs_time_counts_from_service_day_start(
    value: str, seconds: int
) -> None:
    assert parse_gtfs_time(value) == seconds


@pytest.mark.parametrize("value", ["", "06:38", "ab:cd:ef", "06:60:00", "-1:00:00"])
def test_parse_gtfs_time_rejects_malformed_time(value: str) -> None:
    with pytest.raises(ValueError):
        parse_gtfs_time(value)


def test_parse_file_reads_stop_times_after_midnight() -> None:
    zip_file = zip_with(
        "stop_times.txt",
        STOP_TIMES_HEADER + "1684_1,27:39:00,27:39:00,2581,1,0,1\n",
    )

    assert list(parse_file(zip_file, "stop_times.txt", stop_time_row)) == [
        ("1684_1", 1, "2581", 99540, 99540, 0, 1)
    ]


def test_parse_file_handles_byte_order_mark() -> None:
    zip_file = zip_with(
        "stop_times.txt",
        "﻿" + STOP_TIMES_HEADER + "1684_1,06:38:00,06:38:00,2581,1,0,0\n",
    )

    [row] = parse_file(zip_file, "stop_times.txt", stop_time_row)
    assert row[0] == "1684_1"


def test_empty_or_missing_optional_columns_become_none() -> None:
    zip_file = zip_with(
        "stop_times.txt",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
        "1684_1,06:38:00,06:38:00,2581,1,\n",
    )

    [row] = parse_file(zip_file, "stop_times.txt", stop_time_row)
    assert row[5:] == (None, None)


def test_parse_file_names_file_and_line_of_bad_row() -> None:
    zip_file = zip_with(
        "stop_times.txt",
        STOP_TIMES_HEADER
        + "1684_1,06:38:00,06:38:00,2581,1,0,0\n"
        + "1684_1,6.40,6.40,2582,2,0,0\n",
    )

    with pytest.raises(ValueError, match="stop_times.txt line 3"):
        list(parse_file(zip_file, "stop_times.txt", stop_time_row))


def test_calendar_row_reads_all_zero_weekdays() -> None:
    # Mobilis defines service days only through calendar_dates.txt.
    row = {
        "service_id": "1684_PO",
        **dict.fromkeys(WEEKDAYS, "0"),
        "start_date": "20260927",
        "end_date": "20270131",
    }

    assert calendar_row(row) == (
        "1684_PO",
        *[False] * 7,
        date(2026, 9, 27),
        date(2027, 1, 31),
    )


def test_calendar_row_rejects_flag_other_than_zero_or_one() -> None:
    row = {
        "service_id": "1684_PO",
        "monday": "2",
        "start_date": "20260927",
        "end_date": "20270131",
    }

    with pytest.raises(ValueError):
        calendar_row(row)
