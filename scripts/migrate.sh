#!/usr/bin/env bash
# Apply each SQL migration once, in name order, and refuse edited migrations.
set -euo pipefail
cd "$(dirname "$0")/.."

migrations_dir=infrastructure/docker/postgres/migrations

sql() {
    docker compose exec -T postgres sh -ec '
        export PGOPTIONS="-c client_min_messages=warning"
        exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -v ON_ERROR_STOP=1 -q -At "$@"
    ' sh "$@"
}

sql <<'SQL'
CREATE TABLE IF NOT EXISTS metadata.schema_migrations (
    filename text PRIMARY KEY,
    sha256 text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

shopt -s nullglob
files=("$migrations_dir"/*.sql)
if [ "${#files[@]}" -eq 0 ]; then
    echo "No migrations in $migrations_dir"
    exit 0
fi

for file in "${files[@]}"; do
    name=$(basename "$file")
    checksum=$(sha256sum "$file" | cut -d ' ' -f 1)
    applied=$(printf "SELECT sha256 FROM metadata.schema_migrations WHERE filename = :'name';\n" |
        sql -v name="$name")

    if [ -n "$applied" ]; then
        if [ "$applied" != "$checksum" ]; then
            echo "ERROR: $name changed after it was applied; add a new migration instead." >&2
            exit 1
        fi
        echo "Up to date: $name"
        continue
    fi

    echo "Applying $name"
    {
        echo "BEGIN;"
        cat "$file"
        printf "\nINSERT INTO metadata.schema_migrations (filename, sha256) VALUES (:'name', :'checksum');\n"
        echo "COMMIT;"
    } | sql -v name="$name" -v checksum="$checksum"
done
