"""Check GTFS downloads using simulated HTTP responses."""

import io
import zipfile
from datetime import UTC, datetime

import httpx
import pytest
from botocore.exceptions import ClientError
from google.transit import gtfs_realtime_pb2

from mobility.ingestion import gtfs_rt
from mobility.ingestion.archive import (
    FetchAttempt,
    fetch_data,
    record_attempt,
    sha256_hex,
    upload_raw,
)
from mobility.ingestion.gtfs import archive_schedule, raw_object_key, validate_zip

URL = "https://example.test/schedule.zip"


def test_fetch_preserves_binary_content(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"PK\x03\x04\x00\xff\x80\r\n"

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(httpx, "get", client.get)

        assert fetch_data(URL).content == payload


@pytest.mark.parametrize("status_code", [404, 500])
def test_fetch_rejects_http_errors(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=b"Error page")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(httpx, "get", client.get)

        with pytest.raises(httpx.HTTPStatusError) as error:
            fetch_data(URL)

    assert error.value.response.status_code == status_code


def test_fetch_propagates_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Simulated timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(httpx, "get", client.get)

        with pytest.raises(httpx.ReadTimeout):
            fetch_data(URL)


def make_zip(compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        archive.writestr("stops.txt", "stop_id,stop_name\n1,Rondo Mogilskie\n")
    return buffer.getvalue()


def test_validate_zip_accepts_valid_archive() -> None:
    validate_zip(make_zip())


def test_validate_zip_rejects_non_zip_payload() -> None:
    with pytest.raises(ValueError, match="ZIP"):
        validate_zip(b"<html>Przerwa techniczna</html>")


def test_validate_zip_rejects_truncated_archive() -> None:
    with pytest.raises(ValueError):
        validate_zip(make_zip()[:-10])


def corrupt_first_member(payload: bytes) -> bytes:
    corrupted = bytearray(payload)
    data_start = corrupted.index(b"stops.txt") + len(b"stops.txt")
    corrupted[data_start] ^= 0xFF
    return bytes(corrupted)


def test_validate_zip_rejects_crc_mismatch() -> None:
    with pytest.raises(ValueError, match="CRC"):
        validate_zip(corrupt_first_member(make_zip(zipfile.ZIP_STORED)))


def test_validate_zip_rejects_corrupted_compressed_data() -> None:
    with pytest.raises(ValueError, match="ZIP"):
        validate_zip(corrupt_first_member(make_zip()))


def test_sha256_matches_known_value() -> None:
    assert (
        sha256_hex(b"")
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_sha256_is_stable_for_same_bytes() -> None:
    assert sha256_hex(b"PK\x03\x04") == sha256_hex(b"PK\x03\x04")


def test_sha256_changes_when_one_byte_changes() -> None:
    assert sha256_hex(b"PK\x03\x04") != sha256_hex(b"PK\x03\x05")


def test_raw_object_key_layout() -> None:
    assert (
        raw_object_key("krakow_ztp_m", "abc123")
        == "raw/gtfs/source_id=krakow_ztp_m/sha256=abc123/schedule.zip"
    )


class FakeS3:
    def __init__(self, head_error_code: str | None = None) -> None:
        self.head_error_code = head_error_code
        self.puts: list[dict] = []

    def head_object(self, **kwargs: str) -> dict:
        if self.head_error_code is not None:
            raise ClientError({"Error": {"Code": self.head_error_code}}, "HeadObject")
        return {}

    def put_object(self, **kwargs: object) -> None:
        self.puts.append(kwargs)


def test_upload_writes_exact_bytes_when_key_is_missing() -> None:
    client = FakeS3(head_error_code="404")
    payload = b"PK\x03\x04\x00\xff"

    assert upload_raw(client, "bucket", "some/key", payload) is True
    assert client.puts == [{"Bucket": "bucket", "Key": "some/key", "Body": payload}]


def test_upload_skips_existing_key() -> None:
    client = FakeS3()

    assert upload_raw(client, "bucket", "some/key", b"data") is False
    assert client.puts == []


def test_upload_propagates_other_errors() -> None:
    client = FakeS3(head_error_code="403")

    with pytest.raises(ClientError):
        upload_raw(client, "bucket", "some/key", b"data")

    assert client.puts == []


def serve(
    monkeypatch: pytest.MonkeyPatch, status_code: int, content: bytes
) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=content)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "get", client.get)
    return client


def test_archive_records_stored_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = make_zip()
    s3 = FakeS3(head_error_code="404")

    with serve(monkeypatch, 200, payload):
        attempt = archive_schedule(s3, "bucket", "krakow_ztp_m", URL)

    digest = sha256_hex(payload)
    assert attempt.status == "stored"
    assert attempt.http_status == 200
    assert attempt.size_bytes == len(payload)
    assert attempt.sha256 == digest
    assert attempt.object_key == raw_object_key("krakow_ztp_m", digest)
    assert attempt.error is None
    assert attempt.fetched_at.tzinfo is not None
    assert s3.puts[0]["Body"] == payload


def test_archive_records_unchanged_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = make_zip()
    s3 = FakeS3()

    with serve(monkeypatch, 200, payload):
        attempt = archive_schedule(s3, "bucket", "krakow_ztp_m", URL)

    assert attempt.status == "unchanged"
    assert attempt.sha256 == sha256_hex(payload)
    assert s3.puts == []


def test_archive_records_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3(head_error_code="404")

    with serve(monkeypatch, 503, b"Service unavailable"):
        attempt = archive_schedule(s3, "bucket", "krakow_ztp_m", URL)

    assert attempt.status == "failed"
    assert attempt.http_status == 503
    assert attempt.size_bytes is None
    assert attempt.sha256 is None
    assert attempt.error.startswith("HTTPStatusError")
    assert s3.puts == []


def test_archive_records_invalid_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3(head_error_code="404")

    with serve(monkeypatch, 200, b"<html>maintenance</html>"):
        attempt = archive_schedule(s3, "bucket", "krakow_ztp_m", URL)

    assert attempt.status == "failed"
    assert attempt.http_status == 200
    assert attempt.size_bytes == len(b"<html>maintenance</html>")
    assert attempt.object_key is None
    assert attempt.error.startswith("ValueError")
    assert "caused by BadZipFile" in attempt.error
    assert s3.puts == []


def test_archive_records_s3_error(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3(head_error_code="403")
    payload = make_zip()

    with serve(monkeypatch, 200, payload):
        attempt = archive_schedule(s3, "bucket", "krakow_ztp_m", URL)

    assert attempt.status == "failed"
    assert attempt.error.startswith("ClientError")
    assert attempt.sha256 == sha256_hex(payload)
    assert attempt.object_key == raw_object_key("krakow_ztp_m", sha256_hex(payload))


def test_archive_records_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenS3(FakeS3):
        def head_object(self, **kwargs: str) -> dict:
            raise RuntimeError("unexpected")

    with serve(monkeypatch, 200, make_zip()):
        attempt = archive_schedule(BrokenS3(), "bucket", "krakow_ztp_m", URL)

    assert attempt.status == "failed"
    assert attempt.error == "RuntimeError: unexpected"


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, query: str, params: tuple) -> None:
        self.executed.append((query, params))


def test_record_attempt_inserts_all_fields() -> None:
    conn = FakeConnection()
    fetched_at = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    attempt = FetchAttempt(
        source_id="krakow_ztp_m",
        url=URL,
        fetched_at=fetched_at,
        status="stored",
        http_status=200,
        size_bytes=10,
        sha256="abc",
        object_key="raw/key",
    )

    record_attempt(conn, attempt)

    [(query, params)] = conn.executed
    assert "INSERT INTO metadata.fetch_attempt" in query
    assert params == (
        "krakow_ztp_m",
        URL,
        fetched_at,
        "stored",
        200,
        10,
        "abc",
        "raw/key",
        None,
    )


def make_feed_message() -> bytes:
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 1790000000
    entity = message.entity.add()
    entity.id = "vehicle-1"
    entity.vehicle.trip.trip_id = "block_1_trip_1"
    return message.SerializeToString()


def test_validate_feed_message_accepts_valid_feed() -> None:
    gtfs_rt.validate_feed_message(make_feed_message())


@pytest.mark.parametrize(
    "payload",
    [b"<html>Przerwa techniczna</html>", make_feed_message()[:-3]],
    ids=["html", "truncated"],
)
def test_validate_feed_message_rejects_corrupt_payload(payload: bytes) -> None:
    with pytest.raises(ValueError, match="not a GTFS-RT message"):
        gtfs_rt.validate_feed_message(payload)


def test_validate_feed_message_rejects_missing_header() -> None:
    with pytest.raises(ValueError, match="required fields"):
        gtfs_rt.validate_feed_message(b"")


def test_realtime_object_key_uses_utc_fetch_date() -> None:
    warsaw_after_midnight = datetime.fromisoformat("2026-10-02T00:30:00+02:00")

    assert gtfs_rt.raw_object_key("feed", "abc123", warsaw_after_midnight) == (
        "raw/gtfs_rt/source_id=feed/date=2026-10-01/sha256=abc123.pb"
    )


def test_archive_snapshot_stores_feed_under_fetch_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = make_feed_message()
    s3 = FakeS3(head_error_code="404")

    with serve(monkeypatch, 200, payload):
        attempt = gtfs_rt.archive_snapshot(s3, "bucket", "feed", URL)

    digest = sha256_hex(payload)
    assert attempt.status == "stored"
    assert attempt.object_key == gtfs_rt.raw_object_key(
        "feed", digest, attempt.fetched_at
    )
    assert s3.puts[0]["Body"] == payload


def test_archive_snapshot_records_invalid_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s3 = FakeS3(head_error_code="404")

    with serve(monkeypatch, 200, b"<html>maintenance</html>"):
        attempt = gtfs_rt.archive_snapshot(s3, "bucket", "feed", URL)

    assert attempt.status == "failed"
    assert "caused by DecodeError" in attempt.error
    assert s3.puts == []
