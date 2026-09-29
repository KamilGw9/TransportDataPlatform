#!/usr/bin/env bash
# Recreate only this project's services; volumes and user data stay intact.
set -euo pipefail
cd "$(dirname "$0")/.."

probe="infra_$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"

sql() {
    docker compose exec -T postgres sh -ec '
        export PGPASSWORD="$POSTGRES_PASSWORD"
        exec psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -v ON_ERROR_STOP=1 -At
    '
}

object_probe() {
    docker compose run --rm --no-deps -T \
        -e "PROBE=$probe" -e "PROBE_ACTION=$1" \
        --entrypoint /bin/sh minio-init -ec '
        mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
        object="local/$S3_BUCKET/_infrastructure_checks/$PROBE.txt"
        case "$PROBE_ACTION" in
            write) printf "%s" "$PROBE" | mc pipe "$object" >/dev/null ;;
            read) test "$(mc cat "$object")" = "$PROBE" ;;
            delete) mc rm "$object" >/dev/null ;;
            *) exit 2 ;;
        esac
    '
}

cleanup() {
    printf 'DROP TABLE IF EXISTS metadata.%s;\n' "$probe" | sql >/dev/null || true
    object_probe delete >/dev/null 2>&1 || true
}

make up
schema_count=$(printf "SELECT count(*) FROM information_schema.schemata WHERE schema_name IN ('metadata','staging','core','marts');\n" | sql)
test "$schema_count" = 4
trap cleanup EXIT
printf "CREATE TABLE metadata.%s (value text NOT NULL); INSERT INTO metadata.%s VALUES ('%s');\n" "$probe" "$probe" "$probe" | sql >/dev/null
object_probe write

echo "Recreating PostgreSQL and MinIO containers with existing volumes..."
docker compose up -d --force-recreate --wait --wait-timeout 120 postgres minio
docker compose run --rm --no-deps minio-init

value=$(printf 'SELECT value FROM metadata.%s;\n' "$probe" | sql)
test "$value" = "$probe"
object_probe read
echo "PASS: all schemas exist; SQL row and S3 object survived container recreation."
