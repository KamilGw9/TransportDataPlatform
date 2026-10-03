from dataclasses import dataclass
from datetime import datetime, timedelta

# Ten collector cycles of 30 s; a single slow or failed cycle is not an alarm.
MAX_AGE = timedelta(minutes=5)


@dataclass(frozen=True)
class FeedFreshness:
    source_id: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_change_at: datetime | None


_SELECT_FRESHNESS = """
SELECT source_id, last_attempt_at, last_success_at, last_change_at
FROM metadata.feed_freshness
WHERE source_id = ANY(%s)
"""


def load_freshness(conn, source_ids: list[str]) -> list[FeedFreshness]:
    rows = conn.execute(_SELECT_FRESHNESS, (source_ids,)).fetchall()
    found = {row[0]: FeedFreshness(*row) for row in rows}
    # A source that was never fetched has no row in the view.
    return [
        found.get(source_id, FeedFreshness(source_id, None, None, None))
        for source_id in source_ids
    ]


def format_age(age: timedelta) -> str:
    seconds = int(age.total_seconds())
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h"


def stale_reason(feed: FeedFreshness, now: datetime) -> str | None:
    """Return why the feed is stale, or None if it is fresh."""
    # Checked in this order, the first failing check names the cause: a stopped
    # collector, failing downloads, or a feed that no longer changes.
    checks = [
        ("attempt", feed.last_attempt_at),
        ("successful download", feed.last_success_at),
        ("content change", feed.last_change_at),
    ]
    for event, at in checks:
        if at is None:
            return f"no {event} recorded"
        if now - at > MAX_AGE:
            return f"last {event} {format_age(now - at)} ago"
    return None
