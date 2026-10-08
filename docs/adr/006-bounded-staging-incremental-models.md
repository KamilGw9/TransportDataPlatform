# ADR 006: Bounded staging and incremental models for realtime data

Status: accepted

Date: 2026-10-08

## Context

Staging keeps every stop time update of every TripUpdates snapshot. On
2026-10-08, `staging.stop_time_update` held 15.7 million rows in 1.9 GB, out of
a 3.3 GB database. Continuous collection adds about 7.6 million rows, or 0.9 GB,
a day, while the archived protobuf messages in MinIO grow by about 0.3 GB a day.
The local database and MinIO share a WSL disk on a host drive with 83 GB free.

The first model over these rows, `core.stop_time_prediction`, merges unchanged
predictions in consecutive snapshots into periods. Built as a table from all of
staging, it took 173 s for 4.9 million periods, almost all of it in sorting,
and the time grows with the history. [ADR 004](004-dbt-core-models.md) rebuilds
every model from scratch, and `refresh_models` stops a task after 10 minutes
([ADR 005](005-airflow-scheduling.md)), which this model would reach after
about a week of collection.

Four options were considered:

- Keep full rebuilds and tune PostgreSQL. More sort memory brought the build
  to 133 s; neither this nor indexes change how cost and size grow.
- Keep a window of recent days in staging and rebuild models from it. This
  bounds size and build time, but results older than the window disappear
  from `core` on the next build.
- Store only changed predictions at load time. The loader takes snapshots in
  any order, so the stored rows would depend on the order of loading; this was
  rejected when the staging tables were designed.
- Move realtime history to a columnar database such as ClickHouse, which is in
  the project plan. It would compress the rows and sort them quickly, but adds
  a second database to run and keep in sync before the first dashboard exists.

## Decision

- Staging is a working window for TripUpdates: rows of snapshots older than
  7 days are deleted after the models have been built. RAW objects in MinIO,
  referenced by `metadata.fetch_attempt`, remain the full record. A command to
  reload a date range from them comes with the window, and nothing is deleted
  until both exist.
- Models over TripUpdates are dbt incremental models partitioned by the hour
  of the scheduled arrival. A prediction refers to one scheduled arrival, so no
  period spans two partitions. Each build deletes and recomputes the hours
  touched by snapshots loaded since the previous build, including snapshots
  loaded late. Partitions of whole dates were tried first: a build after 16
  minutes of new snapshots recomputed 1.9 million periods in 111 s, against
  74,000 in 18 s by the hour.
- New snapshots are found by `snapshot_id`, which assumes one loader at a
  time: an id is assigned when a row is inserted, not when it is committed, so
  a snapshot committed after a build that has seen a higher id would never be
  built. The loader will take a PostgreSQL advisory lock, so that a manual load
  or a reload from RAW waits for a running load instead of interleaving with it.
- Results compact enough to keep, such as the prediction for each arrival at
  fixed horizons and the marts, keep their full history. Intermediate models
  with a row per prediction period follow the staging window. This replaces the
  point of ADR 004 that everything in `core` can be recomputed from `staging`:
  outside RAW, `core.arrival_prediction` holds the only copy of predictions
  older than the window.
- Hours that have left the staging window are frozen in the models that keep
  their history. A build will not recompute them, even when a trusted arrival
  from vehicle positions changes, because their prediction periods are gone and
  the recomputed arrivals would have no prediction. `core.arrival_prediction`
  will refuse `--full-refresh`; rebuilding it is a deliberate step after the
  days it needs have been reloaded from RAW.
- The rule applies to TripUpdates first. Vehicle positions, which grow about
  30 times more slowly in rows, stay on full rebuilds until a measured build
  time requires the same change.

## Consequences

Build time of the prediction periods and the size of staging depend on the
window and the daily volume, not on how long collection has run. The steady
size of TripUpdates staging is about 7 GB at the current volume. Models that
keep their full history still grow with it: `core.arrival_prediction` checks
every trusted arrival against all of its rows, and the vehicle position models
and the marts are rebuilt from all of their history.

`dbt build --full-refresh` no longer reproduces the full history by itself: it
recomputes only the dates still in staging, so older dates must first be
reloaded from RAW. A change to how arrivals are estimated reaches the
prediction accuracy of older days only after that reload. An incremental model
needs tests of both the first and a later build, and a mistake in choosing the
dates to recompute leaves stale rows that a normal build does not repair.

A snapshot loaded late also moves the ends of periods of trips that it does not
include, as it changes which snapshots are consecutive. Those periods may lie
in hours that the snapshot does not touch, and they stay as they were until
their hour is recomputed for another reason.

Deleting from staging leaves space that PostgreSQL reuses for new rows but does
not return to the disk, and the WSL disk file does not shrink on its own. If
deleting a day of rows becomes slow, the staging tables can be partitioned by
date. ClickHouse remains the option if months of prediction periods have to stay
queryable.
