"""Fill missing local settings without replacing existing credentials."""

import os
import re
import secrets
from pathlib import Path

PASSWORD_KEYS = {
    "POSTGRES_PASSWORD",
    "MINIO_ROOT_PASSWORD",
    "AIRFLOW_JWT_SECRET",
    "DASHBOARD_DB_PASSWORD",
}


def prepare_env(root: Path) -> None:
    """Create or extend .env from its template, generating missing passwords."""
    target = root / ".env"
    original = target.read_text() if target.exists() else ""
    updated = original
    for line in (root / ".env.example").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, default = line.split("=", 1)
        pattern = re.compile(
            rf"^[ \t]*(?:export[ \t]+)?{re.escape(key)}[ \t]*=(.*)$", re.M
        )
        match = pattern.search(updated)
        if match:
            # Existing nonempty values belong to the user, including passwords.
            if match.group(1).strip() not in {"", "''", '""'}:
                continue
        value = secrets.token_hex(24) if key in PASSWORD_KEYS else default
        if match:
            updated = pattern.sub(lambda _: f"{key}={value}", updated, count=1)
        else:
            updated = updated.rstrip("\n") + f"\n{key}={value}\n"
    if updated != original:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(updated.lstrip("\n"))
    target.chmod(0o600)
    print("Local .env is ready; existing credentials were preserved.")


if __name__ == "__main__":
    prepare_env(Path(__file__).resolve().parents[1])
