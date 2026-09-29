"""Test local credential setup without Docker or network access."""

import runpy
import stat
from collections.abc import Callable
from pathlib import Path
from typing import cast

prepare_env = cast(
    Callable[[Path], None],
    runpy.run_path(str(Path(__file__).parents[1] / "scripts/setup_env.py"))[
        "prepare_env"
    ],
)


def test_setup_preserves_existing_values_and_is_repeatable(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "POSTGRES_DB=mobility\nPOSTGRES_PASSWORD=\nMINIO_ROOT_PASSWORD=\n"
    )
    original = '  POSTGRES_DB=custom\nPOSTGRES_PASSWORD="keep $literal # text"\n'
    (tmp_path / ".env").write_text(original)

    prepare_env(tmp_path)
    first = (tmp_path / ".env").read_text()
    prepare_env(tmp_path)

    assert first.startswith(original)
    assert (tmp_path / ".env").read_text() == first
    password = first.split("MINIO_ROOT_PASSWORD=", 1)[1].strip()
    assert len(password) == 48
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


def test_setup_generates_empty_passwords_and_preserves_unknown_keys(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env.example").write_text(
        "POSTGRES_PASSWORD=\nMINIO_ROOT_PASSWORD=\nS3_BUCKET=mobility\n"
    )
    (tmp_path / ".env").write_text(
        'export POSTGRES_PASSWORD=""\nMINIO_ROOT_PASSWORD=\nCUSTOM=keep\n'
    )

    prepare_env(tmp_path)

    values = dict(
        line.split("=", 1) for line in (tmp_path / ".env").read_text().splitlines()
    )
    assert len(values["POSTGRES_PASSWORD"]) == 48
    assert len(values["MINIO_ROOT_PASSWORD"]) == 48
    assert values["POSTGRES_PASSWORD"] != values["MINIO_ROOT_PASSWORD"]
    assert values["CUSTOM"] == "keep"
    assert values["S3_BUCKET"] == "mobility"
