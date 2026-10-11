{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='service_date',
    indexes=[{'columns': ['service_date']}, {'columns': ['built_at']}],
) }}

-- Arrivals at stops estimated from vehicle states. A vehicle arrived at a stop
-- between its last observation before reaching it and its first observation
-- stopped at it, so each arrival is a time window, not a moment. A vehicle
-- first seen already stopped has no arrival, as there is no lower bound. The
-- distance from the stop, at the end of the window, shows when the vehicle
-- reported a stop it had not reached.
WITH observation AS (
    SELECT
        service_date.schedule_sha256,
        service_date.trip_id,
        service_date.service_date,
        vehicle.vehicle_id,
        vehicle.current_status,
        vehicle.current_stop_sequence,
        vehicle.stop_id,
        vehicle.position_timestamp,
        vehicle.latitude,
        vehicle.longitude
    FROM {{ ref('vehicle_position_service_date') }} AS service_date
    JOIN {{ source('staging', 'vehicle_position') }} AS vehicle
        USING (snapshot_sha256, entity_id)
    WHERE service_date.service_date IS NOT NULL
    {%- if is_incremental() %}
        -- A new position changes which observations are consecutive, so a
        -- build recomputes every service date with new positions (ADR 006).
        AND service_date.service_date IN (
            SELECT service_date
            FROM {{ ref('vehicle_position_service_date') }}
            WHERE built_at > (
                SELECT coalesce(max(built_at), '-infinity') FROM {{ this }}
            )
        )
    {%- endif %}
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
    arrival.schedule_sha256,
    arrival.trip_id,
    arrival.service_date,
    arrival.vehicle_id,
    arrival.current_stop_sequence AS stop_sequence,
    arrival.stop_id,
    arrival.previous_timestamp AS arrived_after,
    arrival.position_timestamp AS arrived_by,
    -- Haversine distance. Some positions are exactly 0, 0, sent by a vehicle
    -- without a GPS fix, so their distance is unknown.
    CASE WHEN NOT (arrival.latitude = 0 AND arrival.longitude = 0) THEN
        round((2 * 6371000 * asin(sqrt(
            power(sin(radians(stop.stop_lat - arrival.latitude) / 2), 2)
            + cos(radians(arrival.latitude)) * cos(radians(stop.stop_lat))
            * power(sin(radians(stop.stop_lon - arrival.longitude) / 2), 2)
        )))::numeric, 1)
    END AS distance_to_stop_m,
    now() AS built_at
FROM with_previous AS arrival
LEFT JOIN {{ source('staging', 'schedule_stop') }} AS stop
    USING (schedule_sha256, stop_id)
WHERE arrival.current_status = 'STOPPED_AT'
    AND (
        arrival.previous_stop_sequence < arrival.current_stop_sequence
        OR (
            arrival.previous_stop_sequence = arrival.current_stop_sequence
            AND arrival.previous_status <> 'STOPPED_AT'
        )
    )
