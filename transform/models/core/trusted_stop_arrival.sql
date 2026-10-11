{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='service_date',
    indexes=[{'columns': ['service_date']}, {'columns': ['built_at']}],
) }}

-- depends_on: {{ ref('stop_arrival') }}

-- Estimated arrivals precise enough to measure against a scheduled or predicted
-- time: within 50 m of the stop and with a window of at most 60 s, as a longer
-- one spans a gap in collection. One arrival per stop of a trip instance.
--
-- A table, so that the models that measure arrivals read only the service
-- dates they recompute: a filter on a view with DISTINCT ON reaches its rows
-- only after all of them are computed. A build recomputes the service dates
-- whose arrivals were recomputed since the previous one (ADR 006).
{%- if is_incremental() %}
-- Materialized, so that the dates are found once, not for every arrival.
WITH changed_date AS MATERIALIZED (
    SELECT DISTINCT service_date
    FROM {{ ref('stop_arrival') }}
    WHERE built_at > (SELECT coalesce(max(built_at), '-infinity') FROM {{ this }})
)
{%- endif %}
SELECT DISTINCT ON (trip_id, service_date, stop_sequence)
    *,
    now() AS built_at
FROM {{ ref('stop_arrival_delay') }}
WHERE distance_to_stop_m <= 50
    AND arrived_by - arrived_after <= interval '60 seconds'
    {%- if is_incremental() %}
    AND service_date IN (SELECT service_date FROM changed_date)
    {%- endif %}
-- When two vehicles report the same trip, the first to arrive served the stop.
ORDER BY trip_id, service_date, stop_sequence, arrived_by
