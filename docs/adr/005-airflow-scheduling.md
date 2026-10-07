# ADR 005: Airflow for scheduled loading and model builds

Status: accepted

Date: 2026-10-07

## Context

The collectors run as Compose services and archive data without manual steps,
but nothing after them does. `mobility load-vehicle-positions` and
`make dbt-build` run only by hand, so `marts.route_punctuality` is as old as the
last time someone ran both. `mobility check-freshness` is also run only by hand,
so a stopped collector is noticed only when someone checks. Stage 5 of the
[project plan](../project-plan.md) requires these steps to run on a schedule.

The two refresh steps depend on each other: dbt must build after the load, and
two builds must not run at the same time, because each rebuilds the same tables.

Three options were considered:

- cron on the host. It needs no new service, but it keeps no history of runs
  besides log files, has no retries, and on this laptop it would depend on the
  WSL distribution being started.
- A Compose service with a loop, like `mobility collect-schedule`. It is the
  smallest change, but the order of steps, retries and the record of each run
  would all be written in Python, and a failed build would only be visible in
  container logs.
- Apache Airflow in Compose. It records every run and task with its logs, retries
  failed tasks, prevents overlapping runs and shows failures in a web UI, at the
  cost of several new containers and a large dependency.

## Decision

- Run Airflow 3 in Compose with the LocalExecutor: an API server with the web UI,
  a scheduler and a DAG processor. The UI listens only on `127.0.0.1` and every
  user is an admin, as there are no other users of this machine.
- Keep Airflow's metadata in a separate `airflow` database on the existing
  PostgreSQL, so it does not mix with the `mobility` schemas and needs no extra
  container.
- Build an Airflow image that installs the `mobility` package and dbt in a
  separate virtual environment, so their dependencies do not have to agree with
  Airflow's. Tasks run the existing commands (`mobility load-vehicle-positions`,
  `dbt build`) with the BashOperator; the DAGs contain no loading logic.
- One DAG loads vehicle positions and then builds the dbt models every 30 minutes,
  with at most one active run and without catching up on missed intervals, because
  each run processes everything not yet loaded.
- A second DAG runs `mobility check-freshness` every 5 minutes. Its exit status 1
  fails the task, so a stale feed shows up as a failed run in the UI.
- The collectors stay long-running Compose services. Polling every 30 seconds
  does not fit a scheduler, and their attempts are already recorded in
  `metadata.fetch_attempt`.
- dbt is no longer only a development dependency: it moves to its own dependency
  group, which the Airflow image installs. This replaces the corresponding point
  of [ADR 004](004-dbt-core-models.md).

## Consequences

`marts.route_punctuality` is at most about 30 minutes behind the collected data
while the services run, and each refresh is recorded with its logs in Airflow.
A failed freshness check is visible but still not sent anywhere; alerts need a
separate step. Airflow does not help when the host sleeps: runs missed during
that time are not repeated, and the next run loads everything collected since.

The stack grows by three long-running containers and a large image.
Airflow is not part of the uv project, so the DAG files are checked by importing
them in the Airflow image, not by `make test`. Two places now install the
`mobility` package: the collector image and the Airflow image.
