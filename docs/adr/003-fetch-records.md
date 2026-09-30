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
  attempts carry size, hash and object key. A failed attempt keeps whatever was
  already known, such as the hash when only the upload failed.
- Keep the archived bytes in S3 only; the table references them by object key.
- Add schema changes as SQL files in `infrastructure/docker/postgres/migrations/`,
  applied in name order by `make migrate` (also run by `make up`). Each file runs
  once in a transaction and is recorded with its SHA-256 in
  `metadata.schema_migrations`; a changed file that was already applied stops the
  run. `init.sql` stays limited to schemas, because it only runs on an empty volume.
- Connect to PostgreSQL before downloading, so an unavailable database stops the
  run before anything is uploaded, and use autocommit so no transaction stays
  open during the download.

## Consequences

Questions such as "when did the feed last change" or "how often do downloads fail"
are answered with SQL. A single S3 object may be referenced by many attempts.
Ingestion now requires PostgreSQL as well as S3. If the database write still
fails after a successful upload, the object exists without a record and the next
run records it as `unchanged`, so no `stored` row marks that version. Applied
migrations must not be edited; changes go into a new file.
