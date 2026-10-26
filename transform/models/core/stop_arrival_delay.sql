-- Delay of each estimated arrival against the scheduled arrival at that stop.
-- An arrival is a window, so the delay is a range: the vehicle arrived between
-- min_delay_seconds and max_delay_seconds after the scheduled time.
WITH arrival AS (
    SELECT
        arrival.*,
        {{ scheduled_time('arrival.service_date', 'stop_time.arrival_seconds') }}
            AS scheduled_arrival
    FROM {{ ref('stop_arrival') }} AS arrival
    LEFT JOIN {{ source('staging', 'schedule_stop_time') }} AS stop_time
        USING (schedule_sha256, trip_id, stop_sequence)
)
SELECT
    schedule_sha256,
    trip_id,
    service_date,
    vehicle_id,
    stop_sequence,
    stop_id,
    arrived_after,
    arrived_by,
    distance_to_stop_m,
    scheduled_arrival,
    extract(epoch FROM arrived_after - scheduled_arrival)::integer
        AS min_delay_seconds,
    extract(epoch FROM arrived_by - scheduled_arrival)::integer
        AS max_delay_seconds
FROM arrival
