# Project status

Last updated: 2026-10-19.

Current stage: 6 of the [project plan](project-plan.md), an always-on host in
AWS. Since 2026-10-15 one EC2 instance collects the feeds, and Airflow on it
loads vehicle positions and trip updates and rebuilds the models every 30
minutes and checks feed freshness every 5 minutes, with an email alert when
either stops succeeding. In its first day, including the night, no realtime
feed went more than 2 minutes without a download attempt. Stage 5 delivered
the scheduled runs. Stage 4 delivered realtime-to-schedule matching, arrivals
at stops, route punctuality and the accuracy of TripUpdates predictions;
validation of the source data from that stage is not started. Stages 1 to 3
are complete.

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
- Trip updates: `mobility load-trip-updates` decodes every stored TripUpdates
  snapshot not yet loaded into `staging.trip_update` (one row per trip) and
  `staging.stop_time_update` (one row per predicted stop), recording each
  attempt in `metadata.trip_update_load`. The 2,965 snapshots collected by
  2026-10-07 loaded in 4 min 42 s, with no failures, into 9.8 million stop
  time updates; with the trip rows, the tables take 1.2 GB. In 55 of 200
  sampled snapshots, a trip appeared twice, once for each of two vehicles, so
  trips are keyed by their position in the message. In the samples, Mobilis
  sent only `SCHEDULED` trips and stops, always with both the predicted time
  and the delay.
- TripUpdates staging window: `mobility prune-trip-updates` deletes snapshots
  older than 7 whole UTC days, once the prediction periods have been built
  from them, and `mobility reload-trip-updates` loads the snapshots of given
  UTC dates back from RAW ([ADR 006](adr/006-bounded-staging-incremental-models.md)).
  Both take the advisory lock that the loader holds. On 2026-10-09, staging was
  pruned to 2026-10-04 and 2026-10-01 to 2026-10-03 were reloaded: 1,016
  snapshots deleted in 19 s and reloaded in 68 s. After each step and a build,
  the arrival predictions of every day were identical to those before, and
  after the reload the prediction periods were too.
- Prediction accuracy: `core.stop_time_prediction` merges the predictions that
  stayed the same in consecutive snapshots into periods, 4.9 million of them
  from 15.7 million stop time updates. The predicted time minus the delay
  equals the scheduled time at every stop, which identifies the trip date.
  `core.arrival_prediction` takes, for each trusted arrival, the prediction of
  the arriving vehicle in force 1, 3, 5, 10 and 15 minutes before it, and
  `marts.prediction_accuracy` counts predictions within 1 minute of the arrival
  per route, service date, hour and horizon, against the schedule on the same
  arrivals. Of 44,293 arrivals by 2026-10-08, 99% had a prediction 1 minute
  before and 90% 15 minutes before. Within 1 minute were 89% of predictions
  made 1 minute before, 66% at 5 minutes and 41% at 15 minutes, against 29%
  of scheduled times.
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
  within 50 m of the stop (median 10 m). `core.stop_arrival_delay` gives the
  delay of each arrival as a range, against the scheduled time from the stop
  times of the trip's schedule version.
- Punctuality: `marts.route_punctuality` counts early, on-time and late arrivals
  per route, service date and hour of the service day. It uses the first arrival
  at each stop of a trip, within 50 m of the stop and with a window of at most
  60 s; an arrival is on time from 1 minute early to 3 minutes late, judged by
  the middle of its delay range. Of 18,233 such arrivals by 2026-10-06, 59.3%
  were on time, 40.4% late and 0.3% early.
- Trip coverage: `core.scheduled_trip` lists the trips scheduled for each
  service date, from the schedule version that was the latest one archived
  when the service day started. Versions overlap: the one archived on
  2026-10-16 covered the same dates as the previous one, but renamed every
  trip from 2026-10-17. `core.trip_update_trip` keeps the trips that appeared
  in TripUpdates beyond the staging window, dating each prediction by the
  scheduled trip that includes its scheduled arrival. `marts.trip_coverage`
  counts, per route, service date and hour, the scheduled trips, those that
  ran while VehiclePositions was collected, and how many of these appeared in
  VehiclePositions and in TripUpdates. The TripUpdates count is empty for
  hours with trips that started before the earliest prediction
  `core.trip_update_trip` keeps, as older ones left staging before it was
  first built. On the host, where `refresh_models` builds these models, all
  2,594 trips of 2026-10-16 were collected; 2,575 (99.3%) of them appeared in
  VehiclePositions and 2,585 (99.7%) in TripUpdates. All 1,791 trips of
  Saturday 2026-10-17 appeared in both.
- Models in `core` and `marts` are built by dbt from `transform/`
  (`make dbt-build`), with unit tests of each model, including a later build of
  each incremental one, and uniqueness tests on the matching and prediction
  outputs; migrations cover only `metadata` and `staging`
  ([ADR 004](adr/004-dbt-core-models.md)). All models except
  `marts.prediction_accuracy` and `marts.trip_coverage` are incremental
  ([ADR 006](adr/006-bounded-staging-incremental-models.md)). Scheduled trips
  add each service date once, after it starts; matching and
  service dates add the positions of new snapshots; arrivals, trusted arrivals
  and route punctuality recompute the service dates with new positions; the
  two prediction models recompute the hours of scheduled arrivals touched by
  new snapshots or arrivals. A position snapshot is matched only once every
  schedule version archived before it has loaded, and a data test fails the
  build if one has waited for more than 2 hours. The prediction periods follow
  the staging window, while `core.arrival_prediction` keeps hours that have
  left it frozen and ignores `--full-refresh`; the position models can be
  rebuilt from staging with it. With a few new snapshots, the prediction
  periods took 18 s against 169 s for a full build. On 2026-10-11, with half an
  hour of new data, the models from matching to route punctuality and the
  arrival predictions took 4.5 s in all, against 130 s as full rebuilds. Each
  of them matched a full build row for row, and the arrival predictions matched
  the previous query. CI builds the models after the migrations.
- Scheduled runs: `make airflow` starts Airflow 3 in Compose with the
  LocalExecutor, keeping its metadata in a separate `airflow` database on the
  same PostgreSQL ([ADR 005](adr/005-airflow-scheduling.md)). The
  `refresh_models` DAG runs `mobility load-vehicle-positions` and `mobility
  load-trip-updates` side by side and then `dbt build` every 30 minutes, without
  overlapping runs; dbt builds even if a snapshot failed to load, and the run is
  then marked as failed. After a successful build, the run prunes TripUpdates
  staging; its first run in Airflow, on 2026-10-11, deleted 1,005 snapshots
  older than the window. A run on 2026-10-08 loaded both
  feeds in 3 s and built and tested the models, including the incremental
  prediction models, in 107 s. The `check_freshness` DAG runs `mobility
  check-freshness` every 5 minutes, so a stale feed shows up as a failed run in
  the Airflow UI at `http://127.0.0.1:8080`. Both DAGs end with a
  `send_heartbeat` task, described under Alerts. A task that runs longer than 10
  minutes, or a freshness check longer than 2, is stopped and fails. CI checks
  that the DAG files import in the Airflow image and that a failed load of
  either feed fails a test run of `refresh_models`.
- AWS host: Terraform in `infrastructure/terraform/` describes the RAW bucket,
  a host role limited to that bucket and SSM, a budget alert and a
  c7i-flex.large Spot instance, with the database on a separate EBS volume
  snapshotted daily ([ADR 007](adr/007-aws-hosting.md)). `compose.aws.yaml`
  points the services at S3 and that volume, and
  [the deployment guide](aws-deployment.md) describes how they are started
  there. On 2026-10-13 they ran on the instance for the first time: the
  collectors stored the schedule and the realtime snapshots in S3 under the
  same keys as locally, with no failed attempts, and runs of `refresh_models`
  and `check_freshness` succeeded. Since 2026-10-15 the instance collects,
  loads and builds the models, and the collectors on the laptop are stopped.
  The data from the laptop was not moved to the host, so the figures above
  come from the laptop's database. In the host's first day, to 2026-10-16
  21:00 UTC, no realtime feed had a gap of more than 2 minutes between
  attempts. A schedule version archived at 14:37 UTC on 2026-10-16 was loaded
  in the same collector cycle, and every position matched a trip before and
  after it. Positions of the night trips after midnight got the previous
  service date, and their arrivals the service hours 24 to 27, as in the
  schedule.
- Alerts: after a successful run, `check_freshness` and `refresh_models` send a
  heartbeat metric to CloudWatch (`mobility send-heartbeat`). A CloudWatch
  alarm for each emails the `alert_email` address in Terraform when three
  5-minute periods or two 30-minute periods in a row have no heartbeat, so a
  failed run, a stopped scheduler and a stopped host all raise it. The periods
  are aligned to the clock, so an alarm fires 15 to 20 or 60 to 90 minutes
  after the last heartbeat, plus the time CloudWatch takes to evaluate it. The
  schedule collector has no alarm. Both alarms have been `OK` since
  2026-10-15; a stale feed or a failed run has not raised one yet.
- Feed profiler with [A/M/T reports](../tools/feed_profiler/data-profile.md),
  which led to starting with Mobilis buses
  ([ADR 001](adr/001-krakow-m-first.md)).

## Limitations

- An alert says only which DAG has had no successful run; the cause is in the
  task logs in Airflow. A feed fails the freshness check once it has not
  changed for 5 minutes, so the email comes 15 to 25 minutes after it stops
  changing; a failed model refresh is reported 60 to 90 minutes after the last
  successful one.
- About 1% of realtime downloads on the host fail on the Mobilis side, half
  with 404 for the feed URL and half with an incomplete or undecodable
  message. A failed download is not retried; the next collector cycle starts
  30 s after the previous one started. In the first day, none failed twice in
  a row.
- Freshness is judged by changes of the content hash. The GTFS-RT header
  timestamp is stored only for VehiclePositions loaded into staging; on those,
  a snapshot reached the collector a median of 8 s after it was generated.
- A new schedule reaches staging up to an hour after Mobilis publishes it, and
  only while the schedule collector runs. Realtime trip IDs did not match a
  schedule archived three days earlier, so a stopped schedule collector breaks
  matching within days. `check-freshness` covers only the realtime feeds.
- Staging keeps only the schedule columns needed for matching; shapes, agency
  and feed info stay in the RAW ZIP.
- On the laptop, collection ran only while it was awake. Between 2026-10-03 and
  2026-10-06 the collectors were stopped for 17 to 23 hours each night by the
  laptop's sleep, so about 17 hours of realtime data were collected in four days
  and none of it covers midnight. Service dates after midnight are checked on
  one night of data from the host. A stopped collector raises the freshness
  alarm, but a gap shorter than about 20 minutes raises nothing, and nothing
  lists past gaps. Airflow stops with its host too: missed runs are not
  repeated, and the next run loads everything collected since.
- Mobilis does not send `start_date` in trip descriptors, so the service date is
  inferred from the schedule. Matching uses the schedule version known at
  download time, not the version that applies on the service date. The time zone
  is fixed to Europe/Warsaw, the `agency_timezone` of Mobilis. A position
  without `vehicle.timestamp` gets no service date, and `make dbt-build` warns
  when there is one; none has appeared so far.
- A snapshot that cannot be loaded is retried, and recorded as failed again, on
  every run of `refresh_models`, which then fails. This has not happened yet.
- The position models include only positions loaded before a build, so they
  lag the collected data by up to 30 minutes plus the length of a run. A
  schedule version that fails to load holds back new positions until it loads
  or a newer version replaces it. Each build still compares every staged
  position snapshot with the matched ones, and the uniqueness test reads every
  match; both grow with history, but this has not been measured beyond 530,000
  positions. ServiceAlerts are archived but not decoded.
- The incremental models assume one dbt build at a time. Two builds at once
  would add the same positions twice, and the arrival models of one could skip
  the service dates of positions dated by the other for good, because
  `built_at` is when a build started its transaction, not when it committed.
  Airflow runs one at a time, but a manual `make dbt-build` during a run is not
  prevented; `dbt build --full-refresh --select vehicle_position_match+`
  repairs both.
- A schedule version is recorded in `metadata.fetch_attempt` only after its
  download and upload, a few seconds after its `fetched_at`. A position
  snapshot downloaded and matched within those seconds keeps the previous
  version, as a match is never revised.
- The arrival models replace the rows of each service date they recompute, so a
  date that no longer gives any arrival would keep its old rows. New positions
  only add observations, which makes this unlikely, but it is not checked.
- Staging keeps every stop time update of every TripUpdates snapshot, although
  only 27% of them change between consecutive snapshots. A day of continuous
  collection adds about 7.6 million rows, about 0.9 GB at the measured 124
  bytes per row, and the archive in MinIO about 0.3 GB; the disk holding both
  had 83 GB free on 2026-10-08. With the 7-day window, staging should level
  off at about 7 GB, which has not been reached yet; PostgreSQL reuses the
  space of deleted rows but does not return it to the disk. The first load of
  a backlog of several days can exceed the 10-minute task limit in Airflow.
- Every build of the prediction periods reads all of staging to select the
  hours to recompute, about 10 s for 15 million rows. With memory limited as
  on a 2 GB host, the prediction periods took 77 s of a 117 s build on
  2026-10-11, with 15.6 million rows in staging; at the expected 7 GB of
  staging this has not been measured. A period that ends at the
  newest snapshot is taken to last 2 minutes past it until its hour is
  recomputed. A mistake in choosing the hours would leave stale rows; in the
  prediction periods `--full-refresh` repairs them, in the arrival predictions
  only dropping the table and reloading every day from RAW does. An hour is
  computed only if staging covers the dates from 4 hours before to 2 hours
  after it, a range taken from one day of predictions.
- The prediction accuracy covers the same afternoons and evenings as the
  punctuality figures, and only arrivals estimated from vehicle states. The
  schedule is the only baseline; whether Mobilis predicts more than the current
  delay carried forward is not measured.
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
  freshness view and the loading of schedules, vehicle positions and trip
  updates are tested against a real database. The dbt models have unit tests, which also need PostgreSQL.
- MinIO Community is archived upstream and is used here only as local
  S3-compatible storage.
- The profiling sample is short and does not cover overnight service or daylight
  saving time changes.
- Trip coverage takes the trips of a service date from the version archived
  before the date started. A version published during a day that renamed the
  trips of that same day would make them look unseen; on 2026-10-16 the
  renamed trips started the next day. A version replaced by a newer one before
  it loaded never loads, and the dates that waited for it get the version
  before it, as the matching of positions does. Why 19 collected trips of
  2026-10-16 never appeared in VehiclePositions is not known.
- A trip counts as collected if a new VehiclePositions snapshot was downloaded
  and loaded at least once during its scheduled time, and the same trips are
  the base for TripUpdates, which predicts them up to 3 hours earlier.
  `marts.trip_coverage` is rebuilt in full and reads every dated position on
  each build.
- TripUpdates predictions made before their service date was added to
  `core.scheduled_trip` are kept for as long as staging keeps them, 7 days. A
  date that waits longer for a schedule version loses those trips; reloading
  it from RAW brings them back. `core.trip_update_trip` ignores
  `--full-refresh`, as it keeps more than staging, so if a rebuild of
  `core.scheduled_trip` gives a date another schedule version, the trips of
  that date have to be reloaded from RAW too.

## Next

Collect on the AWS host for at least a week, including nights, then measure
the service date inference across midnight and validate the source data. Look
into the trips that never appear in the realtime feeds.
