-- Scheduled arrival and departure at each stop of every trip seen in the
-- realtime data, on its service date. Expanding every trip on every date of
-- every schedule version would give tens of millions of rows that nothing
-- compares with observations.
WITH trip_instance AS (
    SELECT DISTINCT schedule_sha256, trip_id, service_date
    FROM {{ ref('vehicle_position_service_date') }}
    WHERE service_date IS NOT NULL
)
SELECT
    trip_instance.schedule_sha256,
    trip_instance.trip_id,
    trip_instance.service_date,
    stop_time.stop_sequence,
    stop_time.stop_id,
    {{ service_day_start('trip_instance.service_date') }}
        + stop_time.arrival_seconds * interval '1 second' AS scheduled_arrival,
    {{ service_day_start('trip_instance.service_date') }}
        + stop_time.departure_seconds * interval '1 second' AS scheduled_departure
FROM trip_instance
JOIN {{ source('staging', 'schedule_stop_time') }} AS stop_time
    USING (schedule_sha256, trip_id)
