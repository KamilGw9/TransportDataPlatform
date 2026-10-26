#!/bin/sh
# Let the dashboard role from migration 009 log in with the password from .env.
# Safe to repeat; a new password in .env applies on the next start.
set -eu

export PGHOST=postgres PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD" PGDATABASE="$POSTGRES_DB"

psql -v ON_ERROR_STOP=1 -q -v password="$DASHBOARD_DB_PASSWORD" <<'SQL'
ALTER ROLE dashboard WITH LOGIN PASSWORD :'password';
SQL
