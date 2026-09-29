#!/bin/sh
set -eu

attempt=0
until mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 12 ]; then
        echo "Cannot authenticate to MinIO after 12 attempts." >&2
        exit 1
    fi
    sleep 2
done

mc mb --ignore-existing "local/$S3_BUCKET"
mc stat "local/$S3_BUCKET" >/dev/null
echo "MinIO bucket is ready."
