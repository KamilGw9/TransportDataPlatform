-- Grafana reads as this role, so a dashboard query cannot change data or read
-- staging (ADR 009). dbt grants it the marts, which it recreates on full
-- builds; make dashboard gives it a password and the right to log in.
-- Roles belong to the whole server and outlive a dropped database.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dashboard') THEN
        CREATE ROLE dashboard;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA metadata, marts TO dashboard;
GRANT SELECT ON metadata.fetch_attempt, metadata.feed_freshness TO dashboard;
