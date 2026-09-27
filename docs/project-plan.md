# Project plan

An urban transport data platform for Kraków. The goal is to collect GTFS and
GTFS-Realtime history and provide analysis of predicted delays, realtime trip
coverage, and source data quality.

## Initial scope

Start with Mobilis buses (`krakow_ztp_m`). The first working pipeline will download
schedules and realtime snapshots, retain the original data, normalize records,
and expose SQL queries and a basic dashboard.

## Implementation sequence

1. Set up a reproducible Python environment, a minimal CLI, tests, and CI.
2. Run PostgreSQL and MinIO locally with persistent storage.
3. Archive GTFS/RT with fetch records and extend the Mobilis observation period.
4. Implement validation, realtime-to-schedule matching, and basic analytical models.
5. Provide a dashboard for predicted delays, coverage, and data freshness.

After the first working pipeline, planned additions include Airflow orchestration,
Kafka streaming, realtime history in ClickHouse, monitoring, and replay from the
archive. Weather, A/T feeds, and AWS are later extensions.

## Principles

- Retain original data so that results can be recomputed.
- Distinguish predicted arrival times from windows estimated using vehicle states.
- Validate arrival estimation accuracy separately.
- Introduce technologies and sources incrementally; the list above describes planned work.

See [project status](project-status.md) for implementation progress and
[ADR 001](adr/001-krakow-m-first.md) for the source selection decision.
