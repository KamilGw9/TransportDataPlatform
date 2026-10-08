{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='scheduled_arrival_hour',
) }}

-- The TripUpdates prediction in force 1, 3, 5, 10 and 15 minutes before each
-- trusted arrival, and its error against the arrival window. The horizon is
-- counted from the start of the window, so the prediction was published at
-- least that long before the vehicle arrived. A positive error means the
-- vehicle came earlier than predicted. A row without a prediction means none
-- was in force at that moment, or collection had a gap.
--
-- The prediction periods follow the staging window, but this model keeps its
-- history (ADR 006): a build recomputes only the hours whose predictions
-- changed since it last ran, or which have arrivals it has not seen.
WITH arrival AS (
    SELECT
        schedule_sha256,
        trip_id,
        service_date,
        vehicle_id,
        stop_sequence,
        stop_id,
        scheduled_arrival,
        date_trunc('hour', scheduled_arrival, 'UTC') AS scheduled_arrival_hour,
        arrived_after,
        arrived_by
    FROM {{ ref('trusted_stop_arrival') }}
    -- A stop sequence that the schedule does not have.
    WHERE scheduled_arrival IS NOT NULL
),
prediction_hour AS (
    SELECT scheduled_arrival_hour, max(last_snapshot_id) AS last_snapshot_id
    FROM {{ ref('stop_time_prediction') }}
    GROUP BY scheduled_arrival_hour
),
{%- if is_incremental() %}
built_hour AS (
    SELECT scheduled_arrival_hour, max(last_snapshot_id) AS last_snapshot_id
    FROM {{ this }}
    GROUP BY scheduled_arrival_hour
),
changed_hour AS (
    SELECT prediction_hour.scheduled_arrival_hour
    FROM prediction_hour
    LEFT JOIN built_hour USING (scheduled_arrival_hour)
    WHERE prediction_hour.last_snapshot_id > coalesce(built_hour.last_snapshot_id, 0)
    UNION
    SELECT arrival.scheduled_arrival_hour
    FROM arrival
    WHERE NOT EXISTS (
        SELECT 1
        FROM {{ this }} AS built
        WHERE built.trip_id = arrival.trip_id
            AND built.service_date = arrival.service_date
            AND built.stop_sequence = arrival.stop_sequence
            AND built.vehicle_id = arrival.vehicle_id
            AND built.arrived_by = arrival.arrived_by
    )
),
{%- endif %}
lookup AS (
    SELECT
        arrival.*,
        horizon.minutes AS horizon_minutes,
        arrival.arrived_after - horizon.minutes * interval '1 minute' AS predicted_at
    FROM arrival
    CROSS JOIN unnest(ARRAY[1, 3, 5, 10, 15]) AS horizon (minutes)
    {%- if is_incremental() %}
    WHERE arrival.scheduled_arrival_hour IN (SELECT scheduled_arrival_hour FROM changed_hour)
    {%- endif %}
)
SELECT
    lookup.schedule_sha256,
    lookup.trip_id,
    lookup.service_date,
    lookup.vehicle_id,
    lookup.stop_sequence,
    lookup.stop_id,
    lookup.scheduled_arrival,
    lookup.scheduled_arrival_hour,
    lookup.arrived_after,
    lookup.arrived_by,
    lookup.horizon_minutes,
    prediction.predicted_arrival,
    extract(epoch FROM prediction.predicted_arrival - lookup.arrived_by)::integer
        AS min_error_seconds,
    extract(epoch FROM prediction.predicted_arrival - lookup.arrived_after)::integer
        AS max_error_seconds,
    prediction_hour.last_snapshot_id
FROM lookup
LEFT JOIN prediction_hour USING (scheduled_arrival_hour)
-- The vehicle that arrived, as two vehicles on one trip predict differently.
LEFT JOIN {{ ref('stop_time_prediction') }} AS prediction
    ON prediction.trip_id = lookup.trip_id
    AND prediction.vehicle_id = lookup.vehicle_id
    AND prediction.stop_sequence = lookup.stop_sequence
    AND prediction.scheduled_arrival = lookup.scheduled_arrival
    AND lookup.predicted_at >= prediction.in_force_from
    AND lookup.predicted_at < prediction.in_force_until
