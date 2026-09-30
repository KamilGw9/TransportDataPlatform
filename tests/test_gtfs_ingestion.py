"""Check GTFS downloads using simulated HTTP responses."""

import io
import zipfile

import httpx
import pytest
from botocore.exceptions import ClientError

from mobility.ingestion.gtfs import (
    fetch_data,
    raw_object_key,
    sha256_hex,
    upload_raw,
    validate_zip,
)

URL = "https://example.test/schedule.zip"


def test_fetch_preserves_binary_content(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"PK\x03\x04\x00\xff\x80\r\n"

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(httpx, "get", client.get)

        assert fetch_data(URL) == payload


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
