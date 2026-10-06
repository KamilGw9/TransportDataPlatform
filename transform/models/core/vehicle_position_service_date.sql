{{ config(materialized='table') }}

-- A table: as a view it took 15 s over 181,000 positions on every query.

-- The service date of the trip each matched position refers to. Mobilis does
-- not send start_date, and a trip_id runs on every date of its service, so the
-- date is the one whose scheduled trip lies nearest to the position time.
-- Stop times reach 27:39 and vehicles report a trip before it starts, so the
-- day before and after the local date are candidates too.
WITH position AS (
    SELECT
        match.snapshot_sha256,
        match.entity_id,
        match.schedule_sha256,
        match.trip_id,
        vehicle.position_timestamp,
        -- agency_timezone of Mobilis in agency.txt.
        (vehicle.position_timestamp AT TIME ZONE 'Europe/Warsaw')::date AS local_date
    FROM {{ ref('vehicle_position_match') }} AS match
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
    GROUP BY schedule_sha256, trip_id
),
candidate AS (
    SELECT
        position.*,
        service_date.service_date,
        -- GTFS times count from noon minus 12 hours, which differs from
        -- midnight on the days the clocks change.
        (service_date.service_date + time '12:00') AT TIME ZONE 'Europe/Warsaw'
            - interval '12 hours' AS service_day_start,
        trip_window.start_seconds,
        trip_window.end_seconds
    FROM position
    JOIN {{ source('staging', 'schedule_trip') }} AS trip
        USING (schedule_sha256, trip_id)
    JOIN trip_window USING (schedule_sha256, trip_id)
    -- A position whose service runs on none of the candidate dates is kept
    -- with a null service date.
    LEFT JOIN {{ ref('service_date') }} AS service_date
        ON service_date.schedule_sha256 = position.schedule_sha256
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
    trip_end
FROM trip_instance
ORDER BY
    snapshot_sha256,
    entity_id,
    greatest(trip_start - position_timestamp, position_timestamp - trip_end)
