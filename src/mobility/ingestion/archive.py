import hashlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import boto3
import httpx
import psycopg
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def fetch_data(url: str) -> httpx.Response:
    response = httpx.get(url, timeout=30, follow_redirects=True)
    response.raise_for_status()
    return response


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


def make_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get(
            "S3_ENDPOINT_URL",
            f"http://127.0.0.1:{os.environ.get('MINIO_API_PORT', '9000')}",
        ),
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


def archive(
    client,
    bucket: str,
    source_id: str,
    url: str,
    *,
    validate: Callable[[bytes], None],
    object_key: Callable[[str, datetime], str],
) -> FetchAttempt:
    """Download, validate and store one payload in S3.

    Never raises: any failure is returned as a failed attempt that keeps
    whatever was known before the failure.
    """
    fetched_at = datetime.now(UTC)
    http_status = None
    data = None
    digest = None
    key = None
    try:
        response = fetch_data(url)
        http_status = response.status_code
        data = response.content
        validate(data)
        digest = sha256_hex(data)
        key = object_key(digest, fetched_at)
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


def archive_and_record(
    client,
    bucket: str,
    conn,
    feeds: dict[str, str],
    archive_feed: Callable[..., FetchAttempt],
) -> bool:
    """Archive each feed and record every attempt; return False if any failed."""
    ok = True
    for source_id, url in feeds.items():
        attempt = archive_feed(client, bucket, source_id, url)
        record_attempt(conn, attempt)
        if attempt.status == "failed":
            logger.error("%s: failed: %s", source_id, attempt.error)
            ok = False
        else:
            logger.info(
                "%s: %s, %d bytes, %s",
                source_id,
                attempt.status,
                attempt.size_bytes,
                attempt.object_key,
            )
    return ok


def connect_postgres() -> psycopg.Connection:
    # Autocommit: no transaction stays open while the connection waits for the
    # download and upload; each INSERT is committed immediately.
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "mobility"),
        user=os.environ.get("POSTGRES_USER", "mobility"),
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    )
