"""Check how feed freshness is judged, without database access."""

from datetime import UTC, datetime, timedelta

import pytest

from mobility.ingestion.freshness import FeedFreshness, format_age, stale_reason

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
RECENT = NOW - timedelta(seconds=30)
OLD = NOW - timedelta(hours=37)


def feed(
    attempt: datetime | None, success: datetime | None, change: datetime | None
) -> FeedFreshness:
    return FeedFreshness("krakow_ztp_m_trip_updates", attempt, success, change)


def test_recently_changed_feed_is_fresh() -> None:
    assert stale_reason(feed(RECENT, RECENT, RECENT), NOW) is None


@pytest.mark.parametrize(
    ("freshness", "reason"),
    [
        (feed(None, None, None), "no attempt recorded"),
        (feed(OLD, OLD, OLD), "last attempt 37 h ago"),
        (feed(RECENT, None, None), "no successful download recorded"),
        (feed(RECENT, OLD, OLD), "last successful download 37 h ago"),
        (feed(RECENT, RECENT, OLD), "last content change 37 h ago"),
    ],
    ids=[
        "never-fetched",
        "collector-stopped",
        "only-failures",
        "downloads-failing",
        "content-frozen",
    ],
)
def test_stale_reason_names_first_failing_check(
    freshness: FeedFreshness, reason: str
) -> None:
    assert stale_reason(freshness, NOW) == reason


@pytest.mark.parametrize(
    ("age", "text"),
    [
        (timedelta(seconds=45), "45 s"),
        (timedelta(minutes=12, seconds=59), "12 min"),
        (timedelta(days=2, hours=1), "49 h"),
    ],
)
def test_format_age_keeps_numbers_readable(age: timedelta, text: str) -> None:
    assert format_age(age) == text
