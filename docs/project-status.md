# Project status

Last updated: 2026-09-29.

- Current stage: 2 — local PostgreSQL and S3 storage; verified locally.
- Implemented: the `mobility` package, CLI, uv configuration, lockfile, Ruff,
  pytest, and the GTFS/GTFS-RT profiler with [A/M/T reports](../tools/feed_profiler/data-profile.md).
- Verification: CLI help and version work; `make lint` and `make test` pass
  (7 Python tests, including local credential preservation and repeatable setup).
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
- CI: copied the previously green workflow from `ci/python-quality-checks` into
  this infrastructure branch and included new Python paths and Compose/shell
  validation. These checks pass locally; this updated workflow has not been pushed
  or verified by GitHub Actions in this session.
- Storage decision: see [ADR 002](adr/002-local-storage.md). MinIO Community is
  archived; it is used only for local S3-compatible learning. The server includes
  the October 2025 security release, built from pinned sources. Reassess the service
  before shared or cloud deployment.
- Limitations: the profiler is an exploratory tool. It does not yet provide full
  RAW archiving or a registry of every HTTP attempt. The short sample does not
  validate overnight service or daylight saving time transitions.
- Open questions: longer observation of M, time/delay consistency, service date
  resolution, vehicle state interpretation, and arrival estimation accuracy.
- Next task (user implementation): download `GTFS_KRK_M.zip`, calculate its SHA-256,
  and save the exact bytes under `raw/gtfs/source_id=krakow_ztp_m/sha256=<hash>/schedule.zip`
  in the `mobility` bucket. Then add a fetch record/manifest with URL, time, size and
  hash. No platform ingestion code or domain tables were added in this stage.
