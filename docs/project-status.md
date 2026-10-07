# Project status

Last updated: 2026-10-07.

Current stage: 5 of the [project plan](project-plan.md), scheduled runs.
Airflow loads vehicle positions and rebuilds the models every 30 minutes and
checks feed freshness every 5 minutes. Stage 4 delivered realtime-to-schedule
matching, arrivals at stops and route punctuality; validation of the source
data from that stage is not started. Stages 1 to 3 are complete.

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
  that was the latest archived one when the snapshot was downloaded. Of 193,868
  positions collected by 2026-10-06, 93.3% matched a trip: none between 08:00
  and 09:44 UTC on 2026-10-03, when the feed already used trips from a schedule
  that had not been archived yet, and all of them otherwise, always with the
  same route.
- Service dates: `core.service_date` lists the dates on which each service of a
  schedule version runs, from `calendar` and `calendar_dates`.
  `core.vehicle_position_service_date` gives each matched position the service
  date whose scheduled trip lies nearest to the position time, choosing between
  the local date and the days before and after, with the scheduled start and end
  of that trip. Service days start at noon minus 12 hours in Europe/Warsaw, as
  GTFS defines them, so trips keep their clock times when daylight saving time
  ends. All 180,934 matched positions got a service date; 67% lie within the
  scheduled time of their trip, and 99% of the rest within 30 minutes of it.
- Arrivals: `core.stop_arrival` estimates an arrival when a vehicle is first
  seen stopped at a stop that it had not reached in its previous observation.
  The arrival is the window between the two observations, with the distance of
  the vehicle from the stop at the end of it. Of 18,471 arrivals by 2026-10-06,
  the window had a median of 30 s, and 99.7% of those with a known position were
  within 50 m of the stop (median 10 m). `core.trip_stop_time` gives the
  scheduled times of each trip seen in realtime data, and
  `core.stop_arrival_delay` the delay of each arrival as a range.
- Punctuality: `marts.route_punctuality` counts early, on-time and late arrivals
  per route, service date and hour of the service day. It uses the first arrival
  at each stop of a trip, within 50 m of the stop and with a window of at most
  60 s; an arrival is on time from 1 minute early to 3 minutes late, judged by
  the middle of its delay range. Of 18,233 such arrivals by 2026-10-06, 59.3%
  were on time, 40.4% late and 0.3% early.
- Models in `core` and `marts` are built by dbt from `transform/`
  (`make dbt-build`), with unit tests of each model and a uniqueness test on the
  matching output. The two position models and the punctuality model are
  tables, rebuilt in about 35 s; migrations cover only `metadata` and `staging`
  ([ADR 004](adr/004-dbt-core-models.md)). CI builds the models after the
  migrations.
- Scheduled runs: `make airflow` starts Airflow 3 in Compose with the
  LocalExecutor, keeping its metadata in a separate `airflow` database on the
  same PostgreSQL ([ADR 005](adr/005-airflow-scheduling.md)). The
  `refresh_models` DAG runs `mobility load-vehicle-positions` and then
  `dbt build` every 30 minutes, without overlapping runs; dbt builds even if a
  snapshot failed to load, and the run is then marked as failed. A run on
  2026-10-07 loaded 12 snapshots in 7 s and built and tested the models in
  45 s. The `check_freshness` DAG runs `mobility check-freshness` every 5
  minutes, so a stale feed shows up as a failed run in the Airflow UI at
  `http://127.0.0.1:8080`. A task that runs longer than 10 minutes, or a
  freshness check longer than 2, is stopped and fails. CI checks that the DAG
  files import in the Airflow image and that a failed load fails a test run of
  `refresh_models`.
- Feed profiler with [A/M/T reports](../tools/feed_profiler/data-profile.md),
  which led to starting with Mobilis buses
  ([ADR 001](adr/001-krakow-m-first.md)).

## Limitations

- A stale feed fails a run in Airflow, but nothing sends an alert, so it is
  noticed only when someone opens the UI.
- Freshness is judged by changes of the content hash. The GTFS-RT header
  timestamp is stored only for VehiclePositions loaded into staging; on those,
  a snapshot reached the collector a median of 8 s after it was generated.
- A new schedule reaches staging up to an hour after Mobilis publishes it, and
  only while the schedule collector runs. Realtime trip IDs did not match a
  schedule archived three days earlier, so a stopped schedule collector breaks
  matching within days. `check-freshness` covers only the realtime feeds.
- Staging keeps only the schedule columns needed for matching; shapes, agency
  and feed info stay in the RAW ZIP.
- Collection runs only while the host is awake. Between 2026-10-03 and 2026-10-06
  the collectors were stopped for 17 to 23 hours each night by the laptop's sleep,
  so about 17 hours of realtime data were collected in four days and none of it
  covers midnight. Service dates after midnight are checked only by unit tests.
  Nothing reports such gaps after the fact. Airflow sleeps with the host too:
  missed runs are not repeated, and the next run loads everything collected
  since.
- Mobilis does not send `start_date` in trip descriptors, so the service date is
  inferred from the schedule. Matching uses the schedule version known at
  download time, not the version that applies on the service date. The time zone
  is fixed to Europe/Warsaw, the `agency_timezone` of Mobilis. A position
  without `vehicle.timestamp` gets no service date, and `make dbt-build` warns
  when there is one; none has appeared so far.
- A snapshot that cannot be loaded is retried, and recorded as failed again, on
  every run of `refresh_models`, which then fails. This has not happened yet.
- The position models in `core` are rebuilt from scratch on every build and
  include only positions loaded before it, so they lag the collected data by up
  to 30 minutes plus the length of a run. As views, they took 11 s
  per query over 194,000 positions and 15 s over the 181,000 matched ones; a day
  of continuous collection adds about 230,000. TripUpdates and ServiceAlerts are
  archived but not decoded.
- The punctuality figures come from afternoons and evenings of four days,
  including a Saturday, and say nothing about mornings or nights. Arrivals are
  estimated only where the vehicle reports STOPPED_AT; a vehicle first seen
  stopped, such as at the first stop of a trip, gives no arrival.
- 440 positions (0.2%) report coordinates of exactly 0, 0, from vehicles without
  a GPS fix. They stay in staging; their distance from a stop is unknown and
  punctuality leaves them out.
- Sources and URLs are fixed in code; only Mobilis is configured.
- If the database write fails after an upload, that attempt is not recorded.
- Ingestion tests use fakes for HTTP and S3; only the database tables, the
  freshness view and schedule and vehicle position loading are tested against a
  real database. The dbt models have unit tests, which also need PostgreSQL.
- MinIO Community is archived upstream and is used here only as local
  S3-compatible storage.
- The profiling sample is short and does not cover overnight service or daylight
  saving time changes.

## Next

Keep the host awake and collect for at least a week, including nights, then
measure the service date inference across midnight and validate the source
data. Open questions:
how far the realtime trips cover the schedule, and how accurate the TripUpdates
predictions are.
