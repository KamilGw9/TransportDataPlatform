# Project status

Last updated: 2026-10-03.

Current stage: 4 of the [project plan](project-plan.md), realtime-to-schedule
matching. The schedule and vehicle positions are in staging and matched by trip;
validation and analytical models are not started. Stages 1 to 3 are complete.

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
  `mobility collect-realtime` repeats this every 30 seconds until stopped and
  survives PostgreSQL restarts; `make collect` runs it as a Compose service.
- Fetch records: every run writes one row to `metadata.fetch_attempt` with
  status `stored`, `unchanged` or `failed`, including the error for failures
  ([ADR 003](adr/003-fetch-records.md)). Schema changes are applied by
  `make migrate` from numbered SQL files.
- Freshness check: the `metadata.feed_freshness` view gives the latest attempt,
  successful download and content change of each source, and
  `mobility check-freshness` exits with status 1 if any Mobilis GTFS-RT feed has
  not changed for 5 minutes, naming whether the collector, the download or the
  feed itself is the cause.
- Schedule staging: `mobility load-schedule` loads the latest archived
  schedule ZIP into `staging.schedule_*` tables keyed by the ZIP's SHA-256, in
  one transaction, and records each load in `metadata.schedule_load`. Loading a
  version twice is prevented by a unique index. All trip IDs in a realtime
  snapshot from 2026-10-03 were found in the schedule archived the same day.
  `mobility collect-schedule` archives and loads the schedule every hour;
  `make collect` runs it as a second Compose service.
- Vehicle positions: `mobility load-vehicle-positions` decodes every stored
  VehiclePositions snapshot not yet loaded into `staging.vehicle_position`, one
  transaction per snapshot, and records each attempt in
  `metadata.vehicle_position_load`. The header timestamp is kept per snapshot.
  `core.vehicle_position_match` matches each position to the schedule version
  that was the latest archived one when the snapshot was downloaded. Of 45,373
  positions collected by 2026-10-03, 71.5% matched a trip: none between 08:00
  and 09:44 UTC, when the feed already used trips from a schedule that had not
  been archived yet, and all of them otherwise, always with the same route.
- Feed profiler with [A/M/T reports](../tools/feed_profiler/data-profile.md),
  which led to starting with Mobilis buses
  ([ADR 001](adr/001-krakow-m-first.md)).

## Limitations

- Nothing runs `check-freshness` on a schedule or sends alerts, so a stopped
  collector is noticed only when someone checks.
- Freshness is judged by changes of the content hash. The GTFS-RT header
  timestamp is stored only for VehiclePositions loaded into staging; on those,
  a snapshot reached the collector a median of 8 s after it was generated.
- A new schedule reaches staging up to an hour after Mobilis publishes it, and
  only while the schedule collector runs. Realtime trip IDs did not match a
  schedule archived three days earlier, so a stopped schedule collector breaks
  matching within days. `check-freshness` covers only the realtime feeds.
- Staging keeps only the schedule columns needed for matching; shapes, agency
  and feed info stay in the RAW ZIP.
- Mobilis does not send `start_date` in trip descriptors, and the service date of
  a trip is not inferred yet. Matching uses the schedule version known at
  download time, not the version that applies on the service date.
- `load-vehicle-positions` runs only by hand. A snapshot that cannot be loaded is
  retried, and recorded as failed again, on every run.
- `core.vehicle_position_match` is a plain view, computed on every query; it
  takes about 2 s over 45,000 positions, while a day of collection adds about
  230,000. TripUpdates and ServiceAlerts are archived but not decoded.
- Sources and URLs are fixed in code; only Mobilis is configured.
- If the database write fails after an upload, that attempt is not recorded.
- Ingestion tests use fakes for HTTP and S3; only the database tables, the
  freshness view, schedule and vehicle position loading and the matching view
  are tested against a real database.
- MinIO Community is archived upstream and is used here only as local
  S3-compatible storage.
- The profiling sample is short and does not cover overnight service or daylight
  saving time changes.

## Next

Infer the service date of each matched trip, so that a position can be compared
with the scheduled stop times. The collectors have been running since
2026-10-03; the next measurement should cover a service date change after
midnight. Open questions: interpretation of vehicle states and the accuracy of
arrival estimates.
