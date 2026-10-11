{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='scheduled_arrival_hour',
    full_refresh=false,
    indexes=[{'columns': ['scheduled_arrival_hour']}],
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
-- changed since it last ran, or which have arrivals it has not seen. Hours
-- without prediction periods are frozen, as recomputing them would replace
-- their predictions with nulls; reloading their dates from RAW brings the
-- periods back. For the same reason, --full-refresh leaves this table as it is.
WITH prediction_hour AS (
    SELECT scheduled_arrival_hour, max(last_snapshot_id) AS last_snapshot_id
    FROM {{ ref('stop_time_prediction') }}
    GROUP BY scheduled_arrival_hour
),
arrival AS (
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
    {%- if is_incremental() %}
        -- Only hours with prediction periods are recomputed. A scheduled
        -- arrival lies on its service date or the day after, and the margin
        -- covers the time zone.
        AND service_date BETWEEN
            (SELECT min(scheduled_arrival_hour) FROM prediction_hour)::date - 1
            AND (SELECT max(scheduled_arrival_hour) FROM prediction_hour)::date + 1
    {%- endif %}
),
{%- if is_incremental() %}
-- Frozen hours are never recomputed, so the rows of this table outside the
-- prediction hours are not read.
built_hour AS (
    SELECT scheduled_arrival_hour, max(last_snapshot_id) AS last_snapshot_id
    FROM {{ this }}
    WHERE scheduled_arrival_hour IN (SELECT scheduled_arrival_hour FROM prediction_hour)
    GROUP BY scheduled_arrival_hour
),
-- Materialized, so that the arrivals are narrowed to these hours before they
-- are joined with the prediction periods: otherwise PostgreSQL joined every
-- arrival with all 4.8 million periods first, 14 of 16 s on 2026-10-11.
changed_hour AS MATERIALIZED (
    SELECT prediction_hour.scheduled_arrival_hour
    FROM prediction_hour
    LEFT JOIN built_hour USING (scheduled_arrival_hour)
    WHERE prediction_hour.last_snapshot_id > coalesce(built_hour.last_snapshot_id, 0)
    UNION
    SELECT arrival.scheduled_arrival_hour
    FROM arrival
    JOIN prediction_hour USING (scheduled_arrival_hour)
    WHERE NOT EXISTS (
        SELECT 1
        FROM {{ this }} AS built
        WHERE built.scheduled_arrival_hour = arrival.scheduled_arrival_hour
            AND built.trip_id = arrival.trip_id
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
