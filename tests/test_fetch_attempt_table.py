"""Check metadata.fetch_attempt and its views against the local PostgreSQL.

Run with the services from make up and the variables from .env loaded:
    set -a; source .env; set +a
    uv run pytest -m integration
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.errors import CheckViolation

from mobility.ingestion.archive import FetchAttempt, record_attempt
from mobility.ingestion.freshness import FeedFreshness, load_freshness

pytestmark = pytest.mark.integration

SOURCE_ID = "integration_test"

STORED = FetchAttempt(
    source_id=SOURCE_ID,
    url="https://example.test/feed.pb",
    fetched_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    status="stored",
    http_status=200,
    size_bytes=15,
    sha256="a" * 64,
    object_key="raw/gtfs_rt/source_id=integration_test/date=2026-10-01/sha256=a.pb",
)


def stored_rows(conn: psycopg.Connection) -> list[tuple]:
    return conn.execute(
        """
        SELECT source_id, url, fetched_at, status, http_status, size_bytes,
               sha256, object_key, error
        FROM metadata.fetch_attempt
        WHERE source_id = %s
        """,
        (SOURCE_ID,),
    ).fetchall()


def test_stored_attempt_round_trips(conn: psycopg.Connection) -> None:
    record_attempt(conn, STORED)

    assert stored_rows(conn) == [
        (
            STORED.source_id,
            STORED.url,
            STORED.fetched_at,
            "stored",
            200,
            15,
            STORED.sha256,
            STORED.object_key,
            None,
        )
    ]


def test_failed_upload_keeps_known_hash_and_key(conn: psycopg.Connection) -> None:
    record_attempt(conn, replace(STORED, status="failed", error="ClientError: 403"))

    [row] = stored_rows(conn)
    assert row[3] == "failed"
    assert row[6] == STORED.sha256


def test_failed_download_needs_only_an_error(conn: psycopg.Connection) -> None:
    failed = FetchAttempt(
        source_id=SOURCE_ID,
        url=STORED.url,
        fetched_at=STORED.fetched_at,
        status="failed",
        error="ReadTimeout: timed out",
    )

    record_attempt(conn, failed)

    assert len(stored_rows(conn)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "failed"},
        {"error": "unexpected error on success"},
        {"sha256": None},
        {"object_key": None},
        {"size_bytes": None},
        {"size_bytes": -1},
        {"sha256": "ABC"},
        {"status": "skipped"},
    ],
    ids=[
        "failed-without-error",
        "stored-with-error",
        "stored-without-hash",
        "stored-without-key",
        "stored-without-size",
        "negative-size",
        "malformed-hash",
        "unknown-status",
    ],
)
def test_table_rejects_inconsistent_attempt(
    conn: psycopg.Connection, changes: dict
) -> None:
    with pytest.raises(CheckViolation):
        record_attempt(conn, replace(STORED, **changes))


def freshness(conn: psycopg.Connection) -> tuple:
    return conn.execute(
        """
        SELECT last_attempt_at, last_success_at, last_change_at
        FROM metadata.feed_freshness
        WHERE source_id = %s
        """,
        (SOURCE_ID,),
    ).fetchone()


def test_freshness_ignores_failures_and_daily_restore(
    conn: psycopg.Connection,
) -> None:
    t0 = STORED.fetched_at
    minute = timedelta(minutes=1)
    failed = FetchAttempt(
        source_id=SOURCE_ID,
        url=STORED.url,
        fetched_at=t0 + minute,
        status="failed",
        error="ReadTimeout: timed out",
    )
    for attempt in [
        STORED,
        failed,
        replace(STORED, fetched_at=t0 + 2 * minute),
        replace(failed, fetched_at=t0 + 3 * minute),
    ]:
        record_attempt(conn, attempt)

    assert freshness(conn) == (t0 + 3 * minute, t0 + 2 * minute, t0)


def test_freshness_tracks_new_content(conn: psycopg.Connection) -> None:
    changed_at = STORED.fetched_at + timedelta(seconds=30)
    record_attempt(conn, STORED)
    record_attempt(conn, replace(STORED, fetched_at=changed_at, sha256="b" * 64))

    assert freshness(conn) == (changed_at, changed_at, changed_at)


def test_load_freshness_reports_never_fetched_source(
    conn: psycopg.Connection,
) -> None:
    record_attempt(conn, STORED)
    at = STORED.fetched_at

    assert load_freshness(conn, [SOURCE_ID, "never_fetched"]) == [
        FeedFreshness(SOURCE_ID, at, at, at),
        FeedFreshness("never_fetched", None, None, None),
    ]
