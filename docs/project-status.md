# Project status

Last updated: 2026-09-30.

- Current stage: 3 — GTFS/RT archiving with fetch records; in progress.
  Stage 2 (local PostgreSQL and S3 storage) is complete.
- Implemented: the `mobility` package, CLI, uv configuration, lockfile, Ruff,
  pytest, and the GTFS/GTFS-RT profiler with [A/M/T reports](../tools/feed_profiler/data-profile.md).
- RAW schedule archiving: `mobility.ingestion.gtfs` downloads `GTFS_KRK_M.zip`,
  rejects payloads that are not a valid ZIP (HTML pages, truncated downloads, CRC
  errors), computes the SHA-256 of the exact bytes and stores them under
  `raw/gtfs/source_id=krakow_ztp_m/sha256=<hash>/schedule.zip` in the `mobility`
  bucket. An existing key is not rewritten, so repeated runs are idempotent;
  S3 errors other than a missing object are propagated.
- Verification: CLI help and version work; `make lint` and `make test` pass
  (23 Python tests). Ingestion tests use simulated HTTP responses and a fake S3
  client. A manual run against local MinIO stored the object and a repeated run
  skipped it.
- Local data: ZIP and PB files in `tools/feed_profiler/data/` (excluded from Git).
- Data verification: ZIP hashes match `sources.json` and the archived reports;
  PB counts: A=55, M=66, T=66.
- Report reproducibility: English A/M/T reports reproduced from local ZIP/PB files
  match the archived reports after normalizing generation timestamps and historical
  source labels. Translation preserved every reported number and source URL.
- Initial source: `krakow_ztp_m` — Mobilis buses;
  see the [city and feed selection decision](adr/001-krakow-m-first.md).
- Infrastructure: `compose.yaml` runs PostgreSQL 17.11 and a source-built MinIO
  server with persistent named volumes, loopback ports and health checks. All four
  SQL schemas exist and the configured `mobility` bucket is ready.
- Persistence evidence: `make check-infra` authenticated to PostgreSQL over TCP,
  wrote a SQL row and S3 object, recreated both containers without deleting volumes,
  reinitialized the bucket, and read both original values successfully. Test probes
  were cleaned up afterward. Services remain running for ingestion development.
- Failure evidence: bucket initialization with `S3_BUCKET=INVALID_BUCKET` exited
  with status 1, rather than reporting success. Repeated valid initialization passes.
- Tooling: `make setup/up/down/ps/logs/postgres/check-infra/test/lint` and
  [local setup instructions](local-development.md) are available.
- CI: the workflow runs Python quality checks and Compose/shell validation.
- Storage decision: see [ADR 002](adr/002-local-storage.md). MinIO Community is
  archived; it is used only for local S3-compatible learning. The server includes
  the October 2025 security release, built from pinned sources. Reassess the service
  before shared or cloud deployment.
- Limitations: only the Mobilis schedule ZIP is archived; GTFS-RT snapshots are
  not collected by the platform yet. There is no fetch record or registry of HTTP
  attempts, so a run that finds an unchanged feed leaves no trace. The ingestion
  entry point is a module script with a fixed URL and source ID, not a CLI command.
  The profiler remains an exploratory tool. The short sample does not validate
  overnight service or daylight saving time transitions.
- Open questions: longer observation of M, time/delay consistency, service date
  resolution, vehicle state interpretation, and arrival estimation accuracy.
- Next task (user implementation): add a fetch record with URL, fetch time, size
  and hash. Decide first whether it is a JSON manifest in S3 or a table in the
  `metadata` schema, and whether every attempt is recorded or only new files;
  record the decision in an ADR. No domain tables have been added yet.
