import hashlib
import io
import os
import zipfile
import zlib

import boto3
import httpx
from botocore.exceptions import ClientError


def fetch_data(url: str) -> bytes:
    response = httpx.get(url, timeout=30, follow_redirects=True)
    response.raise_for_status()
    return response.content


def validate_zip(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            bad_member = archive.testzip()
    except (zipfile.BadZipFile, zlib.error, EOFError) as e:
        raise ValueError("Pobrane dane nie są poprawnym plikiem ZIP") from e
    if bad_member is not None:
        raise ValueError(f"Błąd CRC w pliku ZIP: {bad_member}")


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


if __name__ == "__main__":
    source_id = "krakow_ztp_m"
    url = "https://gtfs.ztp.krakow.pl/GTFS_KRK_M.zip"
    client = make_s3_client()
    bucket = os.environ.get("S3_BUCKET", "mobility")

    print(f"Pobieranie GTFS z: {url}")
    data = fetch_data(url)
    validate_zip(data)
    digest = sha256_hex(data)
    key = raw_object_key(source_id, digest)

    print(f"✓ Pobrano: {len(data):,} bajtów")
    print(f"✓ SHA-256: {digest}")
    print(f"✓ Klucz S3: {key}")

    if upload_raw(client, bucket, key, data):
        print("✓ Zapisano do S3")
    else:
        print("✓ Plik już istnieje w S3, pominięto zapis")
