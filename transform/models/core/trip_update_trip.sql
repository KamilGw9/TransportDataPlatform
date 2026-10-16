{{ config(
    materialized='incremental',
    incremental_strategy='append',
    full_refresh=false,
    indexes=[{'columns': ['service_date']}],
) }}

-- The scheduled trips that appeared in TripUpdates. A prediction belongs to
-- the trip of the service date whose scheduled times include its scheduled
-- arrival; the dates of one trip_id are a day apart.
--
-- TripUpdates staging keeps 7 days (ADR 006), but a trip that appeared stays
-- appeared, so a build only adds the trips of prediction periods newer than
-- the newest snapshot it has seen, and nothing is ever deleted. For the same
-- reason, --full-refresh leaves this table as it is. first_predicted_at tells
-- from when TripUpdates are known: when this table is first built, older
-- predictions have already left staging.
--
-- A date is added to scheduled_trip only after a schedule download after its
-- start, up to an hour later or longer while a version waits to load, and its
-- first trips are predicted before that. So the periods from the start of the
-- day after the newest date here are read on every build until their date is
-- added. A date that waits longer than staging keeps TripUpdates loses those
-- trips; reloading it from RAW gives the snapshots new ids and brings them back.
WITH new_period AS (
    SELECT trip_id, scheduled_arrival, in_force_from, last_snapshot_id
    FROM {{ ref('stop_time_prediction') }}
    {%- if is_incremental() %}
    WHERE last_snapshot_id > (SELECT coalesce(max(last_snapshot_id), 0) FROM {{ this }})
        OR scheduled_arrival >= (
            SELECT {{ service_day_start('max(service_date) + 1') }} FROM {{ this }}
        )
    {%- endif %}
)
SELECT
    scheduled.service_date,
    scheduled.trip_id,
    min(new_period.in_force_from) AS first_predicted_at,
    max(new_period.last_snapshot_id) AS last_snapshot_id
FROM new_period
JOIN {{ ref('scheduled_trip') }} AS scheduled
    ON scheduled.trip_id = new_period.trip_id
    AND new_period.scheduled_arrival BETWEEN scheduled.trip_start AND scheduled.trip_end
{%- if is_incremental() %}
WHERE NOT EXISTS (
    SELECT 1
    FROM {{ this }} AS appeared
    WHERE appeared.service_date = scheduled.service_date
        AND appeared.trip_id = scheduled.trip_id
)
{%- endif %}
GROUP BY scheduled.service_date, scheduled.trip_id
