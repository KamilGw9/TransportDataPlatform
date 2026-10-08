{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='scheduled_arrival_hour',
) }}

-- Arrival predictions from TripUpdates, one row per period in which a vehicle
-- kept the same prediction for a stop of a trip. Staging repeats every
-- prediction in each snapshot, about every 30 s, although only a quarter of
-- them change between snapshots.
--
-- A prediction is in force from the first snapshot that has it until the next
-- snapshot after the last one that has it. Snapshots more than 2 minutes apart
-- mean a gap in collection, during which nothing is known, so a period ends at
-- the gap and lasts at most 2 minutes past its last snapshot.
--
-- A build recomputes only the hours of scheduled arrivals that appear in
-- snapshots loaded since the previous build (ADR 006). A prediction refers to
-- one scheduled arrival, so recomputing an hour never splits a period. Snapshot
-- ids grow in the order of loading, so a snapshot loaded late is found too.
-- New snapshots predict the next hour or two, so whole dates would recompute
-- most periods of the day on every build. A period that ends at the newest
-- snapshot lasts 2 minutes past it until its hour is recomputed, which may not
-- happen if no later snapshot predicts that hour.
WITH snapshot AS (
    SELECT
        snapshot_id,
        feed_timestamp,
        row_number() OVER feed_order AS snapshot_number,
        lead(feed_timestamp) OVER feed_order AS next_feed_timestamp,
        feed_timestamp - lag(feed_timestamp) OVER feed_order > interval '2 minutes'
            AS after_gap
    FROM {{ source('staging', 'trip_update_snapshot') }}
    WINDOW feed_order AS (ORDER BY feed_timestamp, snapshot_id)
),
stop_prediction AS (
    SELECT
        stop.snapshot_id,
        stop.entity_index,
        stop.stop_sequence,
        stop.stop_id,
        -- Matches the schedule at every stop, and tells apart the dates on
        -- which the same trip_id runs.
        stop.arrival_time - stop.arrival_delay * interval '1 second'
            AS scheduled_arrival,
        stop.arrival_time AS predicted_arrival
    FROM {{ source('staging', 'stop_time_update') }} AS stop
    -- The first stop of a trip has only a departure.
    WHERE stop.arrival_time IS NOT NULL
),
-- Used twice, so PostgreSQL would otherwise compute it once for all of
-- staging, and finding the new snapshots could not use the primary key.
hourly_prediction AS NOT MATERIALIZED (
    SELECT
        *,
        date_trunc('hour', scheduled_arrival, 'UTC') AS scheduled_arrival_hour
    FROM stop_prediction
),
{%- if is_incremental() %}
new_hour AS (
    SELECT DISTINCT scheduled_arrival_hour
    FROM hourly_prediction
    -- coalesce: a table built from an empty staging is filled from all of it.
    WHERE snapshot_id > (SELECT coalesce(max(last_snapshot_id), 0) FROM {{ this }})
),
{%- endif %}
prediction AS (
    SELECT
        trip.trip_id,
        trip.vehicle_id,
        stop.stop_sequence,
        stop.stop_id,
        stop.scheduled_arrival,
        stop.scheduled_arrival_hour,
        stop.predicted_arrival,
        snapshot.snapshot_id,
        snapshot.snapshot_number,
        snapshot.feed_timestamp,
        snapshot.next_feed_timestamp,
        snapshot.after_gap
    FROM hourly_prediction AS stop
    JOIN {{ source('staging', 'trip_update') }} AS trip
        USING (snapshot_id, entity_index)
    JOIN snapshot USING (snapshot_id)
    {%- if is_incremental() %}
    WHERE stop.scheduled_arrival_hour IN (SELECT scheduled_arrival_hour FROM new_hour)
    {%- endif %}
),
with_previous AS (
    SELECT
        *,
        lag(predicted_arrival) OVER series AS previous_predicted_arrival,
        lag(snapshot_number) OVER series AS previous_snapshot_number
    FROM prediction
    -- Two vehicles on one trip have their own predictions.
    WINDOW series AS (
        PARTITION BY trip_id, vehicle_id, stop_sequence, scheduled_arrival
        ORDER BY snapshot_number
    )
),
numbered AS (
    SELECT
        *,
        count(*) FILTER (
            WHERE previous_snapshot_number IS DISTINCT FROM snapshot_number - 1
                OR after_gap
                OR predicted_arrival <> previous_predicted_arrival
        ) OVER (
            PARTITION BY trip_id, vehicle_id, stop_sequence, scheduled_arrival
            ORDER BY snapshot_number
        ) AS period_number
    FROM with_previous
)
SELECT
    trip_id,
    vehicle_id,
    stop_sequence,
    stop_id,
    scheduled_arrival,
    scheduled_arrival_hour,
    predicted_arrival,
    min(feed_timestamp) AS in_force_from,
    max(least(next_feed_timestamp, feed_timestamp + interval '2 minutes'))
        AS in_force_until,
    max(snapshot_id) AS last_snapshot_id
FROM numbered
GROUP BY
    trip_id,
    vehicle_id,
    stop_sequence,
    stop_id,
    scheduled_arrival,
    scheduled_arrival_hour,
    predicted_arrival,
    period_number
