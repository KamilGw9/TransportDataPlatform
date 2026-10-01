import argparse
import logging
import os
from collections.abc import Callable
from importlib.metadata import version

from mobility.ingestion import gtfs, gtfs_rt
from mobility.ingestion.archive import (
    FetchAttempt,
    archive_and_record,
    connect_postgres,
    make_s3_client,
)


def run_archive(
    feeds: dict[str, str], archive_feed: Callable[..., FetchAttempt]
) -> int:
    client = make_s3_client()
    bucket = os.environ.get("S3_BUCKET", "mobility")
    # Connect before downloading so an unavailable database fails the run
    # before anything is uploaded.
    with connect_postgres() as conn:
        ok = archive_and_record(client, bucket, conn, feeds, archive_feed)
    return 0 if ok else 1


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
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    # httpx logs every request at INFO; our own line per attempt is enough.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "archive-schedule":
        return run_archive(gtfs.MOBILIS_SCHEDULE, gtfs.archive_schedule)
    if args.command == "archive-realtime":
        return run_archive(gtfs_rt.MOBILIS_FEEDS, gtfs_rt.archive_snapshot)
    parser.print_help()
    return 0
