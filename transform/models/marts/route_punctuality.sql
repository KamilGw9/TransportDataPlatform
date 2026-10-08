{{ config(materialized='table') }}

-- Punctuality of each route by service date and hour of the scheduled arrival.
-- An arrival is on time from 1 minute early to 3 minutes late, judged by the
-- middle of its delay range.
WITH arrival AS (
    SELECT
        schedule_sha256,
        trip_id,
        service_date,
        scheduled_arrival,
        (min_delay_seconds + max_delay_seconds) / 2.0 AS delay_seconds
    FROM {{ ref('trusted_stop_arrival') }}
)
SELECT
    route.route_short_name,
    arrival.service_date,
    -- Hours past 24 belong to trips after midnight, as in GTFS stop times.
    floor(extract(epoch FROM arrival.scheduled_arrival
        - {{ service_day_start('arrival.service_date') }}) / 3600)::smallint
        AS service_hour,
    count(*) AS arrivals,
    count(*) FILTER (WHERE arrival.delay_seconds < -60) AS early_arrivals,
    count(*) FILTER (WHERE arrival.delay_seconds BETWEEN -60 AND 180)
        AS on_time_arrivals,
    count(*) FILTER (WHERE arrival.delay_seconds > 180) AS late_arrivals,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY arrival.delay_seconds)
        AS median_delay_seconds
FROM arrival
JOIN {{ source('staging', 'schedule_trip') }} AS trip
    USING (schedule_sha256, trip_id)
JOIN {{ source('staging', 'schedule_route') }} AS route
    ON route.schedule_sha256 = trip.schedule_sha256
    AND route.route_id = trip.route_id
GROUP BY route.route_short_name, arrival.service_date, service_hour
