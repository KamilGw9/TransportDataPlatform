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
  7 whole UTC days are deleted after the models have been built from them.
  RAW objects in MinIO, referenced by `metadata.fetch_attempt`, remain the
  full record, and a command reloads the snapshots downloaded on a range of
  UTC dates from them.
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
  built. The loader, the reload and the deletion take one PostgreSQL advisory
  lock, so that a manual load or a reload waits for a running load instead of
  interleaving with it.
- Results compact enough to keep, such as the prediction for each arrival at
  fixed horizons and the marts, keep their full history. Intermediate models
  with a row per prediction period follow the staging window. This replaces the
  point of ADR 004 that everything in `core` can be recomputed from `staging`:
  outside RAW, `core.arrival_prediction` holds the only copy of predictions
  older than the window.
- Hours without prediction periods are frozen in the models that keep their
  history. A build does not recompute them, even when a trusted arrival from
  vehicle positions changes, because the recomputed arrivals would have no
  prediction. Reloading their dates from RAW brings the periods back, and the
  next build recomputes them. `core.arrival_prediction` ignores
  `--full-refresh`.
- An hour of prediction periods is computed only if staging has snapshots from
  every UTC date on which it could have been predicted, so that an hour at the
  edge of a reload is not replaced by one computed from part of its
  predictions. On 2026-10-09, a snapshot predicted arrivals scheduled from 49
  minutes before to 3 hours 5 minutes after it was published, so the range
  checked is 4 hours before to 2 hours after the hour.
- The rule applied to TripUpdates first. Vehicle positions, which grow about
  30 times more slowly in rows, followed on 2026-10-11. With memory limited
  as on a 2 GB host, matching 527,000 positions to the schedule took 113 s of
  a 188 s build, and at about 230,000 positions a day a linear estimate put
  the build past the 10-minute limit within two weeks. Choosing the schedule
  version per snapshot instead of per position brought matching to 4 s, but
  the service dates, arrivals and punctuality still read every position on
  each build.
- Matching and service dates only add the positions of new snapshots, as
  neither depends on other positions. Arrivals and punctuality recompute the
  service dates that new positions touch: an arrival compares consecutive
  positions of a trip on one service date, and a date holds about 230,000
  positions, so hours are not needed. Staging keeps every position, so
  `--full-refresh` still rebuilds these models from staging.
- New position snapshots are found by comparing staging with the snapshots
  already in `core.vehicle_position_match`, not by an id, so the order in
  which snapshots are committed does not matter and the position loader needs
  no lock.
- A position snapshot is matched only once every schedule version archived
  before it has been loaded into staging, and waits until then. A full
  rebuild corrected a match against an older version on the next build; an
  incremental model would keep it. A data test fails the build when a
  snapshot has waited for more than 2 hours, so a failed schedule load shows
  up as a failed run.

## Consequences

Build time of the prediction periods and the size of staging depend on the
window and the daily volume, not on how long collection has run. The steady
size of TripUpdates staging is about 7 GB at the current volume. Models that
keep their full history still grow with it: `core.arrival_prediction` checks
every trusted arrival against all of its rows, and `marts.prediction_accuracy`
is rebuilt from all of its history. New vehicle positions are not matched while
a schedule version waits to be loaded, so a failed schedule load also stops
the position models from advancing until it succeeds.

`dbt build --full-refresh` no longer reproduces the full history: it rebuilds
the prediction periods from staging and leaves `core.arrival_prediction` as it
is. A change to how arrivals are estimated reaches the prediction accuracy of
older days only after their dates are reloaded from RAW, and rebuilding the
table from scratch means dropping it by hand. If Mobilis starts predicting
further than 3 hours ahead, hours at the edge of a reload are computed from
part of their predictions. An incremental model
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
