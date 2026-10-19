# ADR 004: dbt for models in core

Status: accepted; [ADR 005](005-airflow-scheduling.md) and
[ADR 006](006-bounded-staging-incremental-models.md) replace one point each

Date: 2026-10-05

## Context

Stage 4 of the [project plan](../project-plan.md) adds SQL that joins sources. The
first such query, `core.vehicle_position_match`, was created as a view by
migration 005. Inferring the service date and the analytical models will add more
queries of this kind, each built on the previous ones.

Migrations ([ADR 003](003-fetch-records.md)) run each file once and refuse edited
files. That fits tables written by the Python loaders, but not a view: every
correction becomes a new file repeating the whole query, and the query can only be
tested by inserting rows into the shared database from Python.

Three options were considered: keeping views in migrations, a Python script that
recreates SQL files in order on every run, and dbt Core with the PostgreSQL
adapter.

## Decision

- Migrations own the `metadata` and `staging` schemas: tables that Python code
  writes, with their constraints.
- Everything in `core` and `marts` is a dbt model in `transform/`. Models read
  tables through `source()`, so dbt knows the dependencies and builds models in
  order.
- `make dbt-build` runs `dbt build`: unit tests, models, then data tests. CI runs
  it after the migrations on an empty database.
- Migration 006 drops the view created by migration 005, and dbt creates it again
  under the same name.
- dbt is a development dependency. It runs from the host and is not installed in
  the collector image.
- Models stay views until a measured query time justifies a table.

## Consequences

A model is changed by editing its file and rebuilding. Nothing in `core` needs a
migration, because it can be recomputed from `staging`. Model logic is tested with
dbt unit tests on fixture rows, independent of the data in the local database;
they still need a running PostgreSQL, because dbt reads the column types of the
sources.

Two tools now change the database, and the order matters: `make migrate` before
`make dbt-build`. Between the two, `core.vehicle_position_match` does not exist on
a new database. dbt adds a large set of development dependencies.
