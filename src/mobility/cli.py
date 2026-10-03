import argparse
import logging
import os
import signal
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version

from mobility import schedule
from mobility.ingestion import gtfs, gtfs_rt
from mobility.ingestion.archive import (
    FetchAttempt,
    archive_and_record,
    connect_postgres,
    make_s3_client,
)
from mobility.ingestion.collector import collect
from mobility.ingestion.freshness import load_freshness, stale_reason

logger = logging.getLogger(__name__)


def run_archive(
    client,
    bucket: str,
    feeds: dict[str, str],
    archive_feed: Callable[..., FetchAttempt],
) -> bool:
    # Connect before downloading so an unavailable database fails the run
    # before anything is uploaded.
    with connect_postgres() as conn:
        return archive_and_record(client, bucket, conn, feeds, archive_feed)


def stop_on_signals() -> threading.Event:
    stop = threading.Event()
    # docker stop sends SIGTERM, Ctrl+C sends SIGINT; both end the loop after
    # the current cycle.
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    return stop


def collect_realtime(client, bucket: str, interval: float) -> None:
    stop = stop_on_signals()
    logger.info(
        "Collecting %d GTFS-RT feeds every %g s",
        len(gtfs_rt.MOBILIS_FEEDS),
        interval,
    )
    # A new connection per cycle: a database restart costs one cycle instead
    # of breaking a connection held for days.
    collect(
        lambda: run_archive(
            client, bucket, gtfs_rt.MOBILIS_FEEDS, gtfs_rt.archive_snapshot
        ),
        interval,
        stop,
    )
    logger.info("Collector stopped")


def check_freshness(conn) -> bool:
    now = datetime.now(UTC)
    fresh = True
    for feed in load_freshness(conn, list(gtfs_rt.MOBILIS_FEEDS)):
        reason = stale_reason(feed, now)
        if reason is None:
            print(f"{feed.source_id}: ok")
        else:
            print(f"{feed.source_id}: STALE, {reason}")
            fresh = False
    return fresh


def load_latest_schedule(client, bucket: str) -> bool:
    with connect_postgres() as conn:
        for source_id in gtfs.MOBILIS_SCHEDULE:
            version = schedule.latest_schedule_version(conn, source_id)
            if version is None:
                logger.error(
                    "%s: no archived schedule, run archive-schedule", source_id
                )
                return False
            schedule_sha256, object_key = version
            if schedule.is_loaded(conn, schedule_sha256):
                logger.info("%s: %s already loaded", source_id, object_key)
                continue
            load = schedule.load_schedule(
                client, bucket, conn, schedule_sha256, object_key
            )
            if load.status == "failed":
                logger.error("%s: load failed: %s", source_id, load.error)
                return False
            logger.info("%s: loaded %s", source_id, object_key)
    return True


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mobility",
        description="Collect and process urban transport data.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('mobility')}",
    )
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.add_parser(
        "archive-schedule", help="Archive the Mobilis GTFS schedule ZIP once"
    )
    commands.add_parser(
        "archive-realtime", help="Archive one snapshot of each Mobilis GTFS-RT feed"
    )
    collect_parser = commands.add_parser(
        "collect-realtime",
        help="Archive Mobilis GTFS-RT snapshots repeatedly until stopped",
    )
    collect_parser.add_argument(
        "--interval",
        type=positive_seconds,
        default=30.0,
        help="Seconds between the starts of two cycles (default: 30)",
    )
    commands.add_parser(
        "load-schedule",
        help="Load the latest archived Mobilis schedule into staging tables",
    )
    commands.add_parser(
        "check-freshness",
        help="Exit with 1 if a Mobilis GTFS-RT feed has not changed recently",
    )
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    # httpx logs every request at INFO; our own line per attempt is enough.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.command == "check-freshness":
        with connect_postgres() as conn:
            return 0 if check_freshness(conn) else 1

    client = make_s3_client()
    bucket = os.environ.get("S3_BUCKET", "mobility")
    if args.command == "archive-schedule":
        ok = run_archive(client, bucket, gtfs.MOBILIS_SCHEDULE, gtfs.archive_schedule)
        return 0 if ok else 1
    if args.command == "archive-realtime":
        ok = run_archive(
            client, bucket, gtfs_rt.MOBILIS_FEEDS, gtfs_rt.archive_snapshot
        )
        return 0 if ok else 1
    if args.command == "load-schedule":
        return 0 if load_latest_schedule(client, bucket) else 1
    collect_realtime(client, bucket, args.interval)
    return 0
