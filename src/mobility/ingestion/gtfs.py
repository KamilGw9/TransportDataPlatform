import io
import os
import sys
import zipfile
import zlib

from mobility.ingestion.archive import (
    FetchAttempt,
    archive,
    connect_postgres,
    make_s3_client,
    record_attempt,
)


def validate_zip(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            bad_member = archive.testzip()
    except (zipfile.BadZipFile, zlib.error, EOFError) as e:
        raise ValueError("Downloaded data is not a valid ZIP file") from e
    if bad_member is not None:
        raise ValueError(f"CRC error in ZIP member: {bad_member}")


def raw_object_key(source_id: str, sha256: str) -> str:
    return f"raw/gtfs/source_id={source_id}/sha256={sha256}/schedule.zip"


def archive_schedule(client, bucket: str, source_id: str, url: str) -> FetchAttempt:
    return archive(
        client,
        bucket,
        source_id,
        url,
        validate=validate_zip,
        object_key=lambda sha256, _fetched_at: raw_object_key(source_id, sha256),
    )


if __name__ == "__main__":
    source_id = "krakow_ztp_m"
    url = "https://gtfs.ztp.krakow.pl/GTFS_KRK_M.zip"
    client = make_s3_client()
    bucket = os.environ.get("S3_BUCKET", "mobility")

    # Connect before downloading so an unavailable database fails the run
    # before anything is uploaded.
    with connect_postgres() as conn:
        print(f"Downloading GTFS from: {url}")
        attempt = archive_schedule(client, bucket, source_id, url)
        record_attempt(conn, attempt)

    print(f"Status: {attempt.status}")
    if attempt.status == "failed":
        print(f"Error: {attempt.error}", file=sys.stderr)
        sys.exit(1)
    print(f"Size: {attempt.size_bytes:,} bytes")
    print(f"SHA-256: {attempt.sha256}")
    print(f"S3 key: {attempt.object_key}")
