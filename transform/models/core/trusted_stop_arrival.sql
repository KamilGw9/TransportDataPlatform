-- Estimated arrivals precise enough to measure against a scheduled or predicted
-- time: within 50 m of the stop and with a window of at most 60 s, as a longer
-- one spans a gap in collection. One arrival per stop of a trip instance.
SELECT DISTINCT ON (trip_id, service_date, stop_sequence)
    *
FROM {{ ref('stop_arrival_delay') }}
WHERE distance_to_stop_m <= 50
    AND arrived_by - arrived_after <= interval '60 seconds'
-- When two vehicles report the same trip, the first to arrive served the stop.
ORDER BY trip_id, service_date, stop_sequence, arrived_by
