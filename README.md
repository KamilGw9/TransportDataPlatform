# Transport data platform

A data platform for Kraków public transport, built on the GTFS schedule and the
GTFS-Realtime feeds of Mobilis buses (`krakow_ztp_m`). It keeps a history of
vehicle positions and trip updates, matches them to the schedule, and measures
how punctual the buses are and how accurate their predicted arrival times are.

## How data flows

Two collectors download the realtime feeds every 30 seconds and the schedule
every hour, and store each file unchanged in S3-compatible storage (MinIO) under
a key containing its SHA-256 hash. Every download attempt, including failed
ones, is recorded in PostgreSQL. Loaders decode the stored files into `staging`
tables, from which dbt builds the `core` and `marts` models: matching positions
to scheduled trips, arrivals at stops, route punctuality and prediction
accuracy. Airflow runs the loaders and the dbt build every 30 minutes and checks
feed freshness every 5 minutes. Since the original files are kept, staging and
the models can be rebuilt from the archive.

## Results so far

The data was collected in the first week of October 2026, mostly in the
afternoons and evenings, because collection stopped while the laptop slept. Of
18,233 arrivals, 59% were on time (from 1 minute early to 3 minutes late) and
40% late. Predictions made 1 minute before an arrival were within a minute of it
in 89% of cases, and those made 15 minutes before in 41%, while the scheduled
time was within a minute in 29%. The figures say nothing about mornings or
nights; [project status](docs/project-status.md) describes how they are computed
and what limits them.

## Documentation

- [Current status and limitations](docs/project-status.md)
- [Project plan](docs/project-plan.md)
- [Local setup and lifecycle](docs/local-development.md)
- [Deployment on the AWS host](docs/aws-deployment.md)
- Decisions: [Kraków Mobilis first](docs/adr/001-krakow-m-first.md),
  [local storage](docs/adr/002-local-storage.md),
  [fetch records](docs/adr/003-fetch-records.md),
  [dbt for core models](docs/adr/004-dbt-core-models.md),
  [Airflow scheduling](docs/adr/005-airflow-scheduling.md),
  [bounded staging and incremental models](docs/adr/006-bounded-staging-incremental-models.md),
  [AWS hosting](docs/adr/007-aws-hosting.md)
- [Feed profiler](tools/feed_profiler/README.md) and its
  [findings](tools/feed_profiler/data-profile.md), from the study that preceded
  the pipeline

## Running locally

Requirements: Docker with Compose v2, GNU Make, and uv. The project uses
Python 3.12.

```bash
make setup      # create .env with generated passwords
make up         # PostgreSQL, MinIO, bucket and migrations
make collect    # collect GTFS-RT every 30 s and the schedule hourly
make airflow    # load data and rebuild models every 30 minutes
```

PostgreSQL is available at `127.0.0.1:5432`, the S3 endpoint at
`http://127.0.0.1:9000` with a console at `http://127.0.0.1:9001`, and the
Airflow UI at `http://127.0.0.1:8080`. Credentials are in the ignored `.env`.
`make down` stops everything and keeps the database and object volumes. The
first MinIO source build takes several minutes.

Without Airflow, the same steps can be run by hand:

```bash
set -a; source .env; set +a
uv run mobility load-vehicle-positions
uv run mobility load-trip-updates
make dbt-build
```

`uv run mobility --help` lists the other commands.

## Development

```bash
uv sync --locked
make lint
make test
uv run pytest -m integration   # needs make up and the variables from .env
make check-dags                # import the DAGs in the Airflow image
```
