# Local development

This guide runs the whole pipeline on one machine: PostgreSQL and MinIO, the
collectors, the loaders, the dbt models and Airflow. Requirements: Docker with
Compose v2, GNU Make, a system `python3` for `make setup`, and uv, which
installs Python 3.12 for the project. Run commands from the repository root.
Docker Desktop users must enable integration with their WSL distribution.

## Start and stop

```bash
make setup
make up
make ps
```

`make setup` fills missing settings in `.env` and generates missing passwords. It
preserves existing nonempty values, including your PostgreSQL password. `.env` is
ignored by Git and restricted to its owner. `.env.example` contains no secrets.
Compose reads this file; Make never evaluates it as shell code.

The first build compiles the pinned MinIO source release and can take several
minutes, with substantially more disk and memory use than subsequent starts.
`make up` waits for PostgreSQL and MinIO to become healthy, then runs bucket
initialization in the foreground, then applies SQL migrations (`make migrate`).
A failed initialization or migration makes the command fail. Repeated
initialization preserves existing buckets and objects.

```bash
make logs
make down
make up
```

`make down` removes containers and the Compose network but retains named volumes.
`docker compose down -v` deletes database and object data; it is not part of the
normal workflow. Volumes are not backups. The Compose project is `urban-mobility`;
changing that name selects different volumes rather than moving existing data.

## Connections

| Service | From WSL / host | From another container on the Compose network |
| --- | --- | --- |
| PostgreSQL | `127.0.0.1:5432` | `postgres:5432` |
| S3 API | `http://127.0.0.1:9000` | `http://minio:9000` |
| MinIO console | `http://127.0.0.1:9001` | `http://minio:9001` |
| Airflow UI | `http://127.0.0.1:8080` | `http://airflow-api-server:8080` |
| Grafana | `http://127.0.0.1:3000` | `http://grafana:3000` |

Host ports can be changed with `POSTGRES_PORT`, `MINIO_API_PORT`,
`MINIO_CONSOLE_PORT`, `AIRFLOW_PORT` and `GRAFANA_PORT` in `.env`; internal ports stay the same. Host ports bind only
to loopback. Use local `.env` values for credentials; do not paste them into logs.

PostgreSQL defaults to database/user `mobility`. `make postgres` opens psql using
the configured values. Schemas:

- `metadata`: fetch records (`metadata.fetch_attempt`), the loads of schedules,
  vehicle positions and trip updates (`metadata.*_load`) and the
  `metadata.feed_freshness` view;
- `staging`: schedule versions loaded from the RAW ZIP (`staging.schedule_*`),
  vehicle positions (`staging.vehicle_position*`) and trip updates
  (`staging.trip_update*`, `staging.stop_time_update`);
- `core`: dbt models that join the sources;
- `marts`: dbt models that answer analytical questions.

The initial SQL only runs on a new empty PostgreSQL volume. Changes to init SQL or
`POSTGRES_PASSWORD` do not migrate an existing database. Tables are added by files
in `infrastructure/docker/postgres/migrations/`, applied in name order by
`make migrate`. Each file runs once in a transaction and is recorded with its
SHA-256 in `metadata.schema_migrations`. Do not edit an applied migration: the
next `make migrate` fails with an error. Add a new file instead (see
[ADR 003](adr/003-fetch-records.md)).

Migrations cover only `metadata` and `staging`. Models in `core` are defined in
`transform/` and built by `make dbt-build`, which loads `.env` and runs
`dbt build`: unit tests, models, then data tests. Run it after `make migrate` and
after changing a model (see [ADR 004](adr/004-dbt-core-models.md)).

S3 defaults to bucket `mobility`, region `us-east-1`, path-style addressing.
For the local Python collector, the access key is `MINIO_ROOT_USER`, the
secret key is `MINIO_ROOT_PASSWORD`, and the endpoint is `S3_ENDPOINT_URL`,
the host S3 URL above. If `S3_ENDPOINT_URL` is not set, the client connects to
AWS S3 and boto3 finds the credentials itself, as on the AWS host
([ADR 007](adr/007-aws-hosting.md)); an `.env` created before this variable
existed gets it from `make setup`.
These are development administrator credentials; application-scoped credentials
are required before sharing or deploying this environment.

## Verify persistence

```bash
make check-infra
```

This integration check starts the stack, checks all four schemas, authenticates
to PostgreSQL over TCP, writes a uniquely named SQL table and S3 object, recreates
both service containers, runs bucket initialization again, and checks both values.
It briefly interrupts this project's database and storage. It retains all volumes
and removes only its own test table/object afterward. Cleanup after a service
failure is best-effort; remaining probes use `infra_` names or
`_infrastructure_checks/` object keys.

Expected result: `PASS: all schemas exist; SQL row and S3 object survived container recreation.`

## Archive the GTFS schedule

```bash
set -a; source .env; set +a
uv run mobility archive-schedule
```

The command needs `S3_ENDPOINT_URL`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`
and `POSTGRES_PASSWORD` in the environment; `S3_REGION`, `S3_BUCKET`,
`POSTGRES_PORT`, `POSTGRES_DB` and `POSTGRES_USER` default to the
`.env.example` values, and `POSTGRES_HOST` to the loopback address above. It
downloads `GTFS_KRK_M.zip`, rejects invalid ZIP data and stores the exact bytes
under `raw/gtfs/source_id=krakow_ztp_m/sha256=<hash>/schedule.zip`. Running it
again with an unchanged feed skips the upload. Objects can be inspected in the
MinIO console.

Every run adds one row to `metadata.fetch_attempt` with status `stored`,
`unchanged` or `failed`; a failed run exits with status 1. Recent attempts:

```sql
SELECT fetched_at, status, http_status, size_bytes, left(sha256, 12), error
FROM metadata.fetch_attempt
ORDER BY fetched_at DESC
LIMIT 10;
```

## Load the schedule into staging

```bash
uv run mobility load-schedule
```

The command takes the most recently archived schedule from
`metadata.fetch_attempt`, reads the ZIP from S3, checks it against its SHA-256 and
copies routes, stops, trips, stop times and both calendar files into the
`staging.schedule_*` tables. Every row carries `schedule_sha256`, so several
versions are kept side by side. A version loads in one transaction together with
its `loaded` row in `metadata.schedule_load`; a failure leaves no rows and is
recorded as `failed` with the error. A version that is already loaded is
skipped. Stop times are stored as seconds from the start of the service day,
because GTFS times can exceed `24:00:00`.

Mobilis publishes a new schedule every few days and realtime trip IDs follow the
newest one, so run `archive-schedule` before `load-schedule`.
`mobility collect-schedule` does both every hour until stopped; an unchanged ZIP
is not stored again and an already loaded version is skipped, so most cycles
only download the file. Mobilis sets every weekday in `calendar.txt` to 0 and
lists service days only in `calendar_dates.txt`.

## Archive GTFS-RT snapshots

```bash
uv run mobility archive-realtime
```

One run downloads the Mobilis VehiclePositions, TripUpdates and ServiceAlerts
feeds once, rejects payloads that are not a valid GTFS-RT message and stores each
under `raw/gtfs_rt/source_id=<feed>/date=<UTC date>/sha256=<hash>.pb`. Each feed
has its own `source_id` (for example `krakow_ztp_m_trip_updates`) and its own row
in `metadata.fetch_attempt`. A snapshot identical to one already stored that day
is recorded as `unchanged`.

To collect continuously, run:

```bash
uv run mobility collect-realtime --interval 30
```

Each cycle archives all three feeds and opens a new database connection, so a
PostgreSQL restart only skips the cycles while the database is down. Ctrl+C or
SIGTERM stops the collector after the current cycle.

## Run the collectors as services

```bash
make collect
make logs
make collect-stop
```

`make collect` runs `make up`, builds the application image from the root
`Dockerfile` and starts two services that restart unless stopped: `collector`
runs `mobility collect-realtime` and `schedule-collector` runs
`mobility collect-schedule`. Inside the Compose network they reach
`postgres:5432` and `http://minio:9000`. Their logs are rotated at 10 MB, three
files. `make collect-stop` stops both collectors; `make down` stops everything.

## Run loading and model builds in Airflow

```bash
make airflow
```

`make airflow` runs `make up`, builds the Airflow image from
`infrastructure/docker/airflow/Dockerfile` and starts the API server with the
web UI, the scheduler and the DAG processor. Before they start, `airflow-init`
creates the `airflow` database if it is missing and migrates it. The image
installs `mobility` and dbt in `/opt/mobility/.venv`, separately from Airflow,
and contains the code, the dbt project and the DAGs from `dags/`, so rebuild it
with `make airflow` after changing any of them. The UI has no login, because
it listens only on the loopback address. Run `make setup` first if `.env` was
created before Airflow was added; it generates `AIRFLOW_JWT_SECRET`, which all
Airflow components share.

Two DAGs start unpaused:

- `refresh_models` runs `mobility load-vehicle-positions` and
  `mobility load-trip-updates` side by side and then `dbt build` every 30
  minutes, one run at a time. dbt builds even when a load task fails, because
  each snapshot is committed separately. After a successful build,
  `mobility prune-trip-updates` deletes trip updates older than the staging
  window.
- `check_freshness` runs `mobility check-freshness` every 5 minutes and fails
  when a feed is stale.

Both DAGs end with a `send_heartbeat` task, which reports a successful run to
CloudWatch on the AWS host ([deployment guide](aws-deployment.md)). Locally
`HEARTBEAT_NAMESPACE` is not set, so the task is marked as skipped and the run
still succeeds.

Task logs are kept in the `airflow_logs` volume and shown in the UI.
`make check-dags` builds the image and checks that every DAG file imports.

## Dashboards

```bash
make dashboard
```

`make dashboard` runs `make up` and starts Grafana at `http://127.0.0.1:3000`,
without a login, as the Airflow UI. Before it starts, `grafana-init` lets the
`dashboard` role from migration 009 log in with `DASHBOARD_DB_PASSWORD` from
`.env`. The role reads only the marts and the fetch records, and dbt grants it
the marts on every build, so the punctuality dashboard stays empty until the
first `dbt build` after the migration.

The data source and the dashboards `Data freshness` and `Punctuality and
predictions` are provisioned from `infrastructure/docker/grafana/`. A change
made in the UI cannot be saved; edit the JSON files instead and restart the
service with `docker compose restart grafana`
([ADR 009](adr/009-grafana-dashboard.md)).

## Load vehicle positions and match them to the schedule

```bash
uv run mobility load-vehicle-positions
```

The command finds stored VehiclePositions snapshots in `metadata.fetch_attempt`
that have no `loaded` row in `metadata.vehicle_position_load`, reads each from S3,
checks it against its SHA-256 and loads it in its own transaction: the header
timestamp goes to `staging.vehicle_position_snapshot` and one row per vehicle to
`staging.vehicle_position`. A failed snapshot is recorded with the error and the
others still load. Running the command again loads only new snapshots. Fields
that the feed leaves unset are stored as `NULL`, not as protobuf defaults.

The position models in `core` are incremental tables, so run `make dbt-build`
after loading to add the new positions. With `make airflow` running, both steps
run every 30 minutes. After a change to their SQL, rebuild them from staging
with `dbt build --full-refresh --select vehicle_position_match+` in
`transform/`. `core.vehicle_position_match` joins each position
to the schedule version that was the latest archived one when the snapshot was
first downloaded. Share of positions whose trip was found, per hour:

```sql
SELECT date_trunc('hour', first_fetched_at) AS hour,
       count(*) AS positions,
       round(100.0 * count(*) FILTER (WHERE trip_found) / count(*), 1) AS matched_pct
FROM core.vehicle_position_match
GROUP BY 1
ORDER BY 1;
```

`core.vehicle_position_service_date` adds the service date of each matched trip
and its scheduled start and end. Positions outside the scheduled time of their
trip, in minutes:

```sql
SELECT round(extract(epoch FROM greatest(trip_start - position_timestamp,
                                         position_timestamp - trip_end)) / 60) AS minutes,
       count(*) AS positions
FROM core.vehicle_position_service_date
WHERE position_timestamp NOT BETWEEN trip_start AND trip_end
GROUP BY 1
ORDER BY 1;
```

Arrivals at stops and their delays are in `core.stop_arrival_delay`;
`marts.route_punctuality` counts them per route and hour. Share of on-time
arrivals per route:

```sql
SELECT route_short_name,
       sum(arrivals) AS arrivals,
       round(100.0 * sum(on_time_arrivals) / sum(arrivals), 1) AS on_time_pct
FROM marts.route_punctuality
GROUP BY 1
ORDER BY 3;
```

## Load trip updates

```bash
uv run mobility load-trip-updates
```

The command works like the vehicle position loader, with its attempts in
`metadata.trip_update_load`. Each snapshot gets a `snapshot_id` in
`staging.trip_update_snapshot`, one row per trip in `staging.trip_update` and
one row per predicted stop in `staging.stop_time_update`. A trip is identified
by `entity_index`, its position in the message, because Mobilis repeats the
entity id when two vehicles report the same trip. A stop time update must carry
both the predicted time and the delay, or the snapshot fails to load.

The first load of an archive with several days of snapshots takes several
minutes and may not fit in the 10-minute limit of an Airflow task, so run it by
hand before starting Airflow on a new database. Predictions for one stop of a
trip, as they changed from snapshot to snapshot:

```sql
SELECT snapshot.feed_timestamp, trip.vehicle_id, stop.arrival_time, stop.arrival_delay
FROM staging.stop_time_update AS stop
JOIN staging.trip_update AS trip USING (snapshot_id, entity_index)
JOIN staging.trip_update_snapshot AS snapshot USING (snapshot_id)
WHERE trip.trip_id = '1686_50791' AND stop.stop_sequence = 10
ORDER BY 1;
```

dbt merges these rows into `core.stop_time_prediction`, one row per period in
which a vehicle kept the same prediction. `core.arrival_prediction` takes the
prediction in force 1, 3, 5, 10 and 15 minutes before each arrival in
`core.trusted_stop_arrival`, and `marts.prediction_accuracy` compares them with
the schedule. Both core models are incremental
([ADR 006](adr/006-bounded-staging-incremental-models.md)): a normal build
recomputes only the hours of scheduled arrivals that new snapshots or arrivals
touch. After a change to the SQL of the prediction periods, rebuild them from
staging with `dbt build --full-refresh --select stop_time_prediction+` in
`transform/`; `core.arrival_prediction` ignores `--full-refresh` and keeps the
predictions of days no longer in staging.
Share of predictions within 1 minute of the arrival, with the schedule as a
baseline:

```sql
SELECT horizon_minutes,
       round(100.0 * sum(accurate_predictions) / sum(predicted_arrivals), 1)
           AS prediction_pct,
       round(100.0 * sum(accurate_schedule_times) / sum(predicted_arrivals), 1)
           AS schedule_pct
FROM marts.prediction_accuracy
GROUP BY 1
ORDER BY 1;
```

`marts.trip_coverage` compares both feeds with the trips in
`core.scheduled_trip`: per route, service date and hour, the scheduled trips,
those that ran while vehicle positions were collected, and how many of these
appeared in each feed. The TripUpdates count is empty for hours older than
the earliest prediction kept. Share of collected trips seen per service date:

```sql
SELECT service_date,
       sum(collected_trips) AS collected,
       round(100.0 * sum(seen_trips) / sum(collected_trips), 1) AS positions_pct,
       round(100.0 * sum(predicted_trips)
             / sum(collected_trips) FILTER (WHERE predicted_trips IS NOT NULL), 1)
           AS predictions_pct
FROM marts.trip_coverage
WHERE collected_trips > 0
GROUP BY 1
ORDER BY 1;
```

Staging keeps the trip updates of the last 7 whole UTC days.
`mobility prune-trip-updates` deletes older snapshots, but only those that the
prediction periods have been built from. To bring older days back, for example
after a change to the models:

```bash
uv run mobility reload-trip-updates --from 2026-10-01 --to 2026-10-03
make dbt-build
```

The command loads the snapshots downloaded on those UTC dates that are missing
from staging, and the build recomputes their hours; the next pruning deletes
them again. Reload whole days next to each other: an hour less than 4 hours
from a date missing from staging is not recomputed. The loader, the reload and
the pruning take one advisory lock, so a reload started during a load waits for
it.

## Check feed freshness

```bash
set -a; source .env; set +a
uv run mobility check-freshness
```

The command reads `metadata.feed_freshness`, a view with the latest attempt,
latest successful download and latest content change of each source, and prints
one line per Mobilis GTFS-RT feed. A feed is stale when any of the three is older
than 5 minutes; the line names the first one, which separates a stopped collector
from failing downloads and from a feed that no longer changes. The command exits
with status 1 if any feed is stale. A content change means a new SHA-256; the
Mobilis feeds change on every download because the header timestamp does.
Airflow runs this check every 5 minutes.

## Database tests

`make test` skips tests marked `integration`. They check the
`metadata.fetch_attempt` constraints, the `metadata.feed_freshness` view, and
the staging tables and loaders of schedules, vehicle positions and trip
updates, including pruning and the advisory lock, against the running
PostgreSQL, inside transactions that are rolled back:

```bash
set -a; source .env; set +a
uv run pytest -m integration
```

CI runs them against a fresh PostgreSQL container after `make migrate`, followed
by `make dbt-build`. The dbt models are covered by unit tests next to them in
`transform/models/`, which also need the running database. CI also runs
`make check-dags`.

## Troubleshooting

- Connection to `docker.sock` denied: check Docker Desktop WSL integration or
  Docker permissions for the current terminal.
- Port already allocated: change the corresponding host port in `.env` and run
  `make up` again.
- Unhealthy service: inspect `docker compose logs --tail=100 postgres minio`.
- Airflow does not start: inspect `docker compose logs airflow-init`. Compose
  reporting `Run make setup` means `.env` lacks `AIRFLOW_JWT_SECRET`.
- Bucket initialization failed: check MinIO health and credentials, then rerun
  `docker compose run --rm --no-deps minio-init`.
- Schema missing on an existing database: inspect the database before applying
  `infrastructure/docker/postgres/init.sql`; do not reset the volume to repair it.

## MinIO lifecycle

MinIO Community is archived and no longer maintained. It is kept only as local
S3-compatible storage; the AWS host uses S3 instead. The server
is compiled from `RELEASE.2025-10-15T17-29-55Z`, which includes the last published
security fix, rather than using an older prebuilt server image. This does not make
the archived release suitable for a new public production deployment.

The same image contains `mc`, compiled from `RELEASE.2025-08-13T08-35-41Z`, for
bucket initialization and storage checks. This avoids dependency on unavailable
historical client images in external registries. Both base images are pinned by
digest in the Dockerfile.

See [ADR 002](adr/002-local-storage.md), [upstream status](https://github.com/minio/minio)
and [release notes](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z).
The ingestion code should use the S3 API so that the backing service can be replaced
independently of data processing.
