{{ config(
    materialized='incremental',
    incremental_strategy='append',
    indexes=[{'columns': ['service_date']}],
) }}

-- Each trip that the schedule promised for a service date, from the schedule
-- version that was the latest one archived when that service day started.
-- Versions overlap: the one archived on 2026-10-16 covered the same dates as
-- the previous one but gave every trip from 2026-10-17 a new trip_id, so
-- taking trips from every version that lists a date would count them twice.
--
-- A date is added once, when a schedule download after its start shows that
-- no later version was archived before it. Like the matching of positions, a
-- date waits while a version archived before it is not loaded.
WITH schedule_attempt AS (
    SELECT sha256 AS schedule_sha256, fetched_at
    FROM {{ source('metadata', 'fetch_attempt') }}
    WHERE source_id = 'krakow_ztp_m' AND status <> 'failed'
),
schedule_version AS (
    SELECT attempt.schedule_sha256, attempt.fetched_at
    FROM schedule_attempt AS attempt
    JOIN {{ source('metadata', 'schedule_load') }} AS schedule_load
        ON schedule_load.schedule_sha256 = attempt.schedule_sha256
        AND schedule_load.status = 'loaded'
),
known_until AS (
    SELECT coalesce(
        (
            SELECT min(fetched_at)
            FROM schedule_attempt
            WHERE fetched_at > (
                SELECT coalesce(max(fetched_at), '-infinity') FROM schedule_version
            )
        ),
        (SELECT max(fetched_at) FROM schedule_attempt)
    ) AS fetched_at
),
new_date AS (
    SELECT DISTINCT
        service_date,
        {{ service_day_start('service_date') }} AS service_day_start
    FROM {{ ref('service_date') }}
    {%- if is_incremental() %}
    WHERE service_date > (SELECT coalesce(max(service_date), '-infinity') FROM {{ this }})
    {%- endif %}
),
date_version AS (
    SELECT new_date.*, version.schedule_sha256
    FROM new_date
    JOIN LATERAL (
        SELECT schedule_version.schedule_sha256
        FROM schedule_version
        WHERE schedule_version.fetched_at <= new_date.service_day_start
        ORDER BY schedule_version.fetched_at DESC
        LIMIT 1
    ) AS version ON true
    WHERE new_date.service_day_start < (SELECT fetched_at FROM known_until)
),
trip_window AS (
    SELECT
        schedule_sha256,
        trip_id,
        min(arrival_seconds) AS start_seconds,
        max(departure_seconds) AS end_seconds
    FROM {{ source('staging', 'schedule_stop_time') }}
    WHERE schedule_sha256 IN (SELECT schedule_sha256 FROM date_version)
    GROUP BY schedule_sha256, trip_id
)
SELECT
    date_version.service_date,
    date_version.schedule_sha256,
    trip.trip_id,
    trip.route_id,
    date_version.service_day_start + trip_window.start_seconds * interval '1 second'
        AS trip_start,
    date_version.service_day_start + trip_window.end_seconds * interval '1 second'
        AS trip_end
FROM date_version
JOIN {{ ref('service_date') }} AS service_date
    USING (schedule_sha256, service_date)
JOIN {{ source('staging', 'schedule_trip') }} AS trip
    ON trip.schedule_sha256 = service_date.schedule_sha256
    AND trip.service_id = service_date.service_id
-- A trip without stop times has no time to run at.
JOIN trip_window
    ON trip_window.schedule_sha256 = trip.schedule_sha256
    AND trip_window.trip_id = trip.trip_id
