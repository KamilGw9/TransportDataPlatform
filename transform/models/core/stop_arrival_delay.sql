-- Delay of each estimated arrival against the scheduled arrival at that stop.
-- An arrival is a window, so the delay is a range: the vehicle arrived between
-- min_delay_seconds and max_delay_seconds after the scheduled time.
SELECT
    arrival.schedule_sha256,
    arrival.trip_id,
    arrival.service_date,
    arrival.vehicle_id,
    arrival.stop_sequence,
    arrival.stop_id,
    arrival.arrived_after,
    arrival.arrived_by,
    arrival.distance_to_stop_m,
    stop_time.scheduled_arrival,
    extract(epoch FROM arrival.arrived_after - stop_time.scheduled_arrival)::integer
        AS min_delay_seconds,
    extract(epoch FROM arrival.arrived_by - stop_time.scheduled_arrival)::integer
        AS max_delay_seconds
FROM {{ ref('stop_arrival') }} AS arrival
LEFT JOIN {{ ref('trip_stop_time') }} AS stop_time
    USING (schedule_sha256, trip_id, service_date, stop_sequence)
