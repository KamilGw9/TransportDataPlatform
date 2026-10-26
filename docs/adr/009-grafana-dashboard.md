# ADR 009: Grafana for the dashboard

Status: accepted

Date: 2026-10-26

## Context

Stage 7 of the [project plan](../project-plan.md) requires a dashboard for
punctuality, predicted delays, coverage and data freshness. The figures exist as
tables: `marts.route_punctuality`, `marts.prediction_accuracy` and
`marts.trip_coverage`, rebuilt every 30 minutes, and `metadata.feed_freshness`
and `metadata.fetch_attempt`, written by the collectors. Today they are read
only through SQL. The dashboard is for the author; others will see screenshots
in the README.

Four options were considered:

- Grafana in Compose. Panels are SQL queries on the existing tables, and the
  data source and dashboards can be provisioned from files in the repository.
  It suits time series such as fetch attempts per hour, and has no notion of a
  semantic model.
- Metabase in Compose. Questions are built in its UI and kept in its own
  database, so the dashboards are not in the repository and a new host starts
  without them.
- Streamlit. A Python application gives full control over the pages, but every
  chart and filter is code to write, test and maintain, and it is a new
  dependency.
- Power BI Desktop on the laptop. It reads PostgreSQL through a tunnel to the
  host, but a report is a file outside the stack, refreshed only when someone
  opens it, and sharing it needs Power BI Service and a licence.

## Decision

- Run Grafana OSS in Compose, started by `make dashboard`, with its UI on
  `127.0.0.1` only. On the AWS host it is reached through an SSM port
  forwarding session, as the Airflow UI is.
- Provision the PostgreSQL data source and the dashboards from files in the
  repository. A change made in the UI is lost on the next start until it is
  exported to those files.
- Connect as a separate `dashboard` role that can only read the marts and the
  freshness view, not the owner of the database.
- Keep Grafana's own database in the container, not in a volume: everything
  in it that matters is provisioned again on start, so it is neither kept nor
  backed up.

## Consequences

The dashboards are reviewed and versioned like the models, and a new host gets
them by starting the service. The panels are SQL against the marts, so a
change of a mart's columns can break a panel without failing any test. The
stack grows by one container. No one but the author can open the dashboard, so
screenshots in the README show it to others and age with the data.
