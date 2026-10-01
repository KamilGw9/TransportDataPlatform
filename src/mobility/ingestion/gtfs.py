import io
import zipfile
import zlib

from mobility.ingestion.archive import FetchAttempt, archive

MOBILIS_SCHEDULE = {"krakow_ztp_m": "https://gtfs.ztp.krakow.pl/GTFS_KRK_M.zip"}


def validate_zip(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zip_file:
            bad_member = zip_file.testzip()
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
