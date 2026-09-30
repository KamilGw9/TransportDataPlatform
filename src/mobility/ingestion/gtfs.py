import hashlib
import io
import os
import sys
import zipfile
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime

import boto3
import httpx
import psycopg
from botocore.exceptions import ClientError


def fetch_data(url: str) -> httpx.Response:
    response = httpx.get(url, timeout=30, follow_redirects=True)
    response.raise_for_status()
    return response


def validate_zip(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            bad_member = archive.testzip()
    except (zipfile.BadZipFile, zlib.error, EOFError) as e:
        raise ValueError("Downloaded data is not a valid ZIP file") from e
    if bad_member is not None:
        raise ValueError(f"CRC error in ZIP member: {bad_member}")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_object_key(source_id: str, sha256: str) -> str:
    return f"raw/gtfs/source_id={source_id}/sha256={sha256}/schedule.zip"


_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


def make_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{os.environ.get('MINIO_API_PORT', '9000')}",
        aws_access_key_id=os.environ["MINIO_ROOT_USER"],
        aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    )


def upload_raw(client, bucket: str, key: str, data: bytes) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return False
    except ClientError as e:
        code = str(e.response.get("Error", {}).get("Code", ""))
        if code not in _NOT_FOUND_CODES:
            raise

    client.put_object(Bucket=bucket, Key=key, Body=data)
    return True


def describe_error(error: BaseException) -> str:
    message = f"{type(error).__name__}: {error}"
    cause = error.__cause__
    if cause is not None:
        message += f" (caused by {type(cause).__name__}: {cause})"
    return message


@dataclass(frozen=True)
class FetchAttempt:
    source_id: str
    url: str
    fetched_at: datetime
    status: str
    http_status: int | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    object_key: str | None = None
    error: str | None = None


def archive_schedule(client, bucket: str, source_id: str, url: str) -> FetchAttempt:
    fetched_at = datetime.now(UTC)
    http_status = None
    data = None
    digest = None
    key = None
    try:
        response = fetch_data(url)
        http_status = response.status_code
        data = response.content
        validate_zip(data)
        digest = sha256_hex(data)
        key = raw_object_key(source_id, digest)
        stored = upload_raw(client, bucket, key, data)
    except Exception as e:
        # Any failure must still produce a record, so catch everything here.
        if isinstance(e, httpx.HTTPStatusError):
            http_status = e.response.status_code
        return FetchAttempt(
            source_id=source_id,
            url=url,
            fetched_at=fetched_at,
            status="failed",
            http_status=http_status,
            size_bytes=None if data is None else len(data),
            sha256=digest,
            object_key=key,
            error=describe_error(e),
        )

    return FetchAttempt(
        source_id=source_id,
        url=url,
        fetched_at=fetched_at,
        status="stored" if stored else "unchanged",
        http_status=http_status,
        size_bytes=len(data),
        sha256=digest,
        object_key=key,
    )


_INSERT_ATTEMPT = """
INSERT INTO metadata.fetch_attempt
    (source_id, url, fetched_at, status, http_status, size_bytes, sha256,
     object_key, error)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def record_attempt(conn, attempt: FetchAttempt) -> None:
    conn.execute(
        _INSERT_ATTEMPT,
        (
            attempt.source_id,
            attempt.url,
            attempt.fetched_at,
            attempt.status,
            attempt.http_status,
            attempt.size_bytes,
            attempt.sha256,
            attempt.object_key,
            attempt.error,
        ),
    )


def connect_postgres() -> psycopg.Connection:
    # Autocommit: no transaction stays open while the connection waits for the
    # download and upload; each INSERT is committed immediately.
    return psycopg.connect(
        host="127.0.0.1",
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "mobility"),
        user=os.environ.get("POSTGRES_USER", "mobility"),
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
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
