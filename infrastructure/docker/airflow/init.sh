#!/usr/bin/env bash
# Create Airflow's database next to the mobility one, then bring its schema
# up to date. Both steps are safe to repeat.
set -euo pipefail

export PGHOST=postgres PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD"

exists=$(psql -d "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname = 'airflow'")
if [ -z "$exists" ]; then
    createdb airflow
fi

exec airflow db migrate
