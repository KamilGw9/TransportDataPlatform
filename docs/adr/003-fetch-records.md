# ADR 003: Fetch records in PostgreSQL

Status: accepted

Date: 2026-09-30

## Context

RAW schedule archiving stores each distinct GTFS ZIP once, keyed by its SHA-256.
A run that finds an unchanged feed, or fails before upload, left no trace. Stage 3
of the [project plan](../project-plan.md) requires fetch records, and the
`metadata` schema was reserved for fetch, file and processing records.

Two options were considered: a JSON manifest next to each object in S3, or a table
in PostgreSQL.

## Decision

- Record every download attempt as one row in `metadata.fetch_attempt`, including
  unchanged feeds and failures. Columns: source, URL, fetch time (UTC), status
  (`stored`, `unchanged`, `failed`), HTTP status, size, SHA-256, object key and
  error text.
- Enforce consistency in the table: failed attempts carry an error; successful
  attempts carry size, hash and object key.
- Keep the archived bytes in S3 only; the table references them by object key.
- Add schema changes as idempotent SQL files in
  `infrastructure/docker/postgres/migrations/`, applied by `make migrate` (also
  run by `make up`). `init.sql` stays limited to schemas, because it only runs on
  an empty volume.

## Consequences

Questions such as "when did the feed last change" or "how often do downloads fail"
are answered with SQL. A single S3 object may be referenced by many attempts.
Ingestion now requires PostgreSQL as well as S3. If the database write fails
after a successful upload, the object exists without a record; the next run
records it as `unchanged`. Migrations have no applied-version tracking yet, so each
file must be safe to repeat; revisit this when a migration cannot be.
