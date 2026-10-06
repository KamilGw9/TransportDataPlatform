-- Arrivals at stops estimated from vehicle states. A vehicle arrived at a stop
-- between its last observation before reaching it and its first observation
-- stopped at it, so each arrival is a time window, not a moment. A vehicle
-- first seen already stopped has no arrival, as there is no lower bound.
WITH observation AS (
    SELECT
        service_date.schedule_sha256,
        service_date.trip_id,
        service_date.service_date,
        vehicle.vehicle_id,
        vehicle.current_status,
        vehicle.current_stop_sequence,
        vehicle.stop_id,
        vehicle.position_timestamp
    FROM {{ ref('vehicle_position_service_date') }} AS service_date
    JOIN {{ source('staging', 'vehicle_position') }} AS vehicle
        USING (snapshot_sha256, entity_id)
    WHERE service_date.service_date IS NOT NULL
),
with_previous AS (
    SELECT
        *,
        lag(current_status) OVER vehicle_trip AS previous_status,
        lag(current_stop_sequence) OVER vehicle_trip AS previous_stop_sequence,
        lag(position_timestamp) OVER vehicle_trip AS previous_timestamp
    FROM observation
    -- Some trip instances are reported by two vehicles.
    WINDOW vehicle_trip AS (
        PARTITION BY vehicle_id, trip_id, service_date
        ORDER BY position_timestamp
    )
)
SELECT
    schedule_sha256,
    trip_id,
    service_date,
    vehicle_id,
    current_stop_sequence AS stop_sequence,
    stop_id,
    previous_timestamp AS arrived_after,
    position_timestamp AS arrived_by
FROM with_previous
WHERE current_status = 'STOPPED_AT'
    AND (
        previous_stop_sequence < current_stop_sequence
        OR (
            previous_stop_sequence = current_stop_sequence
            AND previous_status <> 'STOPPED_AT'
        )
    )
