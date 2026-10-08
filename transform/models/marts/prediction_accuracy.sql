{{ config(materialized='table') }}

-- Accuracy of TripUpdates predictions by route, service date, hour of the
-- scheduled arrival and horizon, with the schedule as a baseline. Both are
-- judged by the middle of the error range and are accurate within 1 minute
-- either way. The baseline counts only arrivals that had a prediction, so that
-- both describe the same arrivals.
WITH arrival AS (
    SELECT
        schedule_sha256,
        trip_id,
        service_date,
        scheduled_arrival,
        horizon_minutes,
        predicted_arrival IS NOT NULL AS predicted,
        abs(min_error_seconds + max_error_seconds) / 2.0 AS prediction_error_seconds,
        abs(extract(epoch FROM scheduled_arrival - arrived_after)
            + extract(epoch FROM scheduled_arrival - arrived_by)) / 2.0
            AS schedule_error_seconds
    FROM {{ ref('arrival_prediction') }}
)
SELECT
    route.route_short_name,
    arrival.service_date,
    -- Hours past 24 belong to trips after midnight, as in GTFS stop times.
    floor(extract(epoch FROM arrival.scheduled_arrival
        - {{ service_day_start('arrival.service_date') }}) / 3600)::smallint
        AS service_hour,
    arrival.horizon_minutes,
    count(*) AS arrivals,
    count(*) FILTER (WHERE arrival.predicted) AS predicted_arrivals,
    count(*) FILTER (WHERE arrival.prediction_error_seconds <= 60)
        AS accurate_predictions,
    count(*) FILTER (WHERE arrival.predicted AND arrival.schedule_error_seconds <= 60)
        AS accurate_schedule_times,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY arrival.prediction_error_seconds)
        AS median_prediction_error_seconds,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY arrival.schedule_error_seconds)
        FILTER (WHERE arrival.predicted) AS median_schedule_error_seconds
FROM arrival
JOIN {{ source('staging', 'schedule_trip') }} AS trip
    USING (schedule_sha256, trip_id)
JOIN {{ source('staging', 'schedule_route') }} AS route
    ON route.schedule_sha256 = trip.schedule_sha256
    AND route.route_id = trip.route_id
GROUP BY route.route_short_name, arrival.service_date, service_hour, arrival.horizon_minutes
