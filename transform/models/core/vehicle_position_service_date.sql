{{ config(
    materialized='incremental',
    incremental_strategy='append',
    indexes=[
        {'columns': ['snapshot_sha256']},
        {'columns': ['built_at']},
        {'columns': ['service_date']},
    ],
) }}

-- The service date of the trip each matched position refers to. Mobilis does
-- not send start_date, and a trip_id runs on every date of its service, so the
-- date is the one whose scheduled trip lies nearest to the position time.
-- Stop times reach 27:39 and vehicles report a trip before it starts, so the
-- day before and after the local date are candidates too.
--
-- The date of a position depends on no other position, so a build adds the
-- snapshots matched since the previous one (ADR 006). built_at tells the
-- models of arrivals which service dates have new positions.
WITH new_snapshot AS (
    SELECT snapshot.snapshot_sha256
    FROM {{ source('staging', 'vehicle_position_snapshot') }} AS snapshot
    WHERE EXISTS (
        SELECT 1
        FROM {{ ref('vehicle_position_match') }} AS match
        WHERE match.snapshot_sha256 = snapshot.snapshot_sha256
            AND match.trip_found
    )
    {%- if is_incremental() %}
        AND NOT EXISTS (
            SELECT 1
            FROM {{ this }} AS dated
            WHERE dated.snapshot_sha256 = snapshot.snapshot_sha256
        )
    {%- endif %}
),
position AS (
    SELECT
        match.snapshot_sha256,
        match.entity_id,
        match.schedule_sha256,
        match.trip_id,
        vehicle.position_timestamp,
        -- agency_timezone of Mobilis in agency.txt.
        (vehicle.position_timestamp AT TIME ZONE 'Europe/Warsaw')::date AS local_date
    FROM new_snapshot
    JOIN {{ ref('vehicle_position_match') }} AS match USING (snapshot_sha256)
    JOIN {{ source('staging', 'vehicle_position') }} AS vehicle
        USING (snapshot_sha256, entity_id)
    WHERE match.trip_found
),
trip_window AS (
    SELECT
        schedule_sha256,
        trip_id,
        min(arrival_seconds) AS start_seconds,
        max(departure_seconds) AS end_seconds
    FROM {{ source('staging', 'schedule_stop_time') }}
    -- Every stop time of every schedule version would grow with each version.
    WHERE (schedule_sha256, trip_id) IN (
        SELECT schedule_sha256, trip_id FROM position
    )
    GROUP BY schedule_sha256, trip_id
),
candidate AS (
    SELECT
        position.*,
        service_date.service_date,
        {{ service_day_start('service_date.service_date') }} AS service_day_start,
        trip_window.start_seconds,
        trip_window.end_seconds
    FROM position
    JOIN {{ source('staging', 'schedule_trip') }} AS trip
        USING (schedule_sha256, trip_id)
    LEFT JOIN trip_window USING (schedule_sha256, trip_id)
    -- A position whose service runs on none of the candidate dates, or whose
    -- trip has no stop times to place it on a date, is kept with a null
    -- service date.
    LEFT JOIN {{ ref('service_date') }} AS service_date
        ON trip_window.trip_id IS NOT NULL
        AND service_date.schedule_sha256 = position.schedule_sha256
        AND service_date.service_id = trip.service_id
        AND service_date.service_date BETWEEN position.local_date - 1
            AND position.local_date + 1
),
trip_instance AS (
    SELECT
        *,
        service_day_start + start_seconds * interval '1 second' AS trip_start,
        service_day_start + end_seconds * interval '1 second' AS trip_end
    FROM candidate
)
SELECT DISTINCT ON (snapshot_sha256, entity_id)
    snapshot_sha256,
    entity_id,
    position_timestamp,
    trip_id,
    schedule_sha256,
    service_date,
    trip_start,
    trip_end,
    now() AS built_at
FROM trip_instance
ORDER BY
    snapshot_sha256,
    entity_id,
    greatest(trip_start - position_timestamp, position_timestamp - trip_end),
    -- Without it, a position equally distant from two dates could get a
    -- different one on every build.
    service_date
