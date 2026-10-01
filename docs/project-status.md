# Project status

Last updated: 2026-10-01.

Current stage: 3 of the [project plan](project-plan.md), GTFS/RT archiving with
fetch records. Stages 1 and 2 are complete.

## What works

- Python package `mobility` with a minimal CLI, managed with uv; Ruff and pytest
  run locally (`make lint`, `make test`) and in CI, which also validates the
  Compose file and shell scripts.
- Local PostgreSQL 17 and MinIO in Docker Compose, with persistent volumes and
  health checks (`make up`, `make down`). `make check-infra` confirms that a SQL
  row and an S3 object survive container recreation. Storage choices are in
  [ADR 002](adr/002-local-storage.md).
- RAW schedule archiving for `krakow_ztp_m` (`mobility archive-schedule`). The ZIP
  is validated, hashed with SHA-256 and stored under
  `raw/gtfs/source_id=krakow_ztp_m/sha256=<hash>/schedule.zip`. An existing
  object is not rewritten, so repeated runs are idempotent.
- RAW GTFS-RT archiving for the three Mobilis feeds
  (`mobility archive-realtime`): each run validates the protobuf message and
  stores it under `raw/gtfs_rt/source_id=<feed>/date=<UTC date>/sha256=<hash>.pb`.
- Fetch records: every run writes one row to `metadata.fetch_attempt` with
  status `stored`, `unchanged` or `failed`, including the error for failures
  ([ADR 003](adr/003-fetch-records.md)). Schema changes are applied by
  `make migrate` from numbered SQL files.
- Feed profiler with [A/M/T reports](../tools/feed_profiler/data-profile.md),
  which led to starting with Mobilis buses
  ([ADR 001](adr/001-krakow-m-first.md)).

## Limitations

- GTFS-RT snapshots are fetched once per run; there is no continuous collection
  yet.
- Sources and URLs are fixed in code; only Mobilis is configured.
- If the database write fails after an upload, that attempt is not recorded.
- Ingestion tests use fakes for HTTP, S3 and PostgreSQL; table constraints are
  only checked manually against the local database.
- MinIO Community is archived upstream and is used here only as local
  S3-compatible storage.
- The profiling sample is short and does not cover overnight service or daylight
  saving time changes.

## Next

Collect GTFS-RT snapshots continuously.
Open questions: service date resolution, interpretation of vehicle states and
the accuracy of arrival estimates.
