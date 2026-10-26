{{ config(materialized='table') }}

-- How many scheduled trips of each route appear in VehiclePositions and
-- TripUpdates, by service date and the hour of the service day in which they
-- start.
--
-- A trip is collected if a new VehiclePositions snapshot was downloaded and
-- loaded at least once between its scheduled start and end, up to the latest
-- snapshot matched so far: positions are loaded up to 30 minutes after
-- download, and a trip that has just started would otherwise count as unseen.
-- A download that returned the previous snapshot again brings no positions.
-- Only collected trips can be seen, so a gap in collection lowers
-- collected_trips, not the share of them that was seen.
--
-- A trip is seen if any position on its service date names its trip_id,
-- whatever schedule version the position was matched with: the version of the
-- date and the version known when a position was downloaded can differ, and
-- on 2026-10-16 they kept the same trip_ids.
--
-- A trip is predicted if it appeared in TripUpdates. Both feeds are
-- downloaded together, so it is counted among the collected trips too. For an
-- hour with trips that started before the earliest prediction kept, the count
-- is unknown rather than 0.

-- Used twice, so PostgreSQL would otherwise compute it once in full, and the
-- downloads during each trip could not be found by the index on fetched_at.
WITH vehicle_position_attempt AS NOT MATERIALIZED (
    SELECT attempt.sha256 AS snapshot_sha256, attempt.fetched_at
    FROM {{ source('metadata', 'fetch_attempt') }} AS attempt
    JOIN {{ source('staging', 'vehicle_position_snapshot') }} AS snapshot
        ON snapshot.snapshot_sha256 = attempt.sha256
    WHERE attempt.source_id = 'krakow_ztp_m_vehicle_positions'
        AND attempt.status = 'stored'
),
-- From the newest download back, so that the index on snapshot_sha256 finds
-- it without reading every match.
matched_until AS (
    SELECT fetched_at
    FROM vehicle_position_attempt AS attempt
    WHERE EXISTS (
        SELECT 1
        FROM {{ ref('vehicle_position_match') }} AS match
        WHERE match.snapshot_sha256 = attempt.snapshot_sha256
    )
    ORDER BY fetched_at DESC
    LIMIT 1
),
predicted_from AS (
    SELECT min(first_predicted_at) AS predicted_at FROM {{ ref('trip_update_trip') }}
),
seen_trip AS (
    SELECT DISTINCT service_date, trip_id
    FROM {{ ref('vehicle_position_service_date') }}
),
-- Materialized: inlined, each count below that uses collected looked up the
-- downloads again, which more than doubled the time of the query.
trip AS MATERIALIZED (
    SELECT
        scheduled.*,
        EXISTS (
            SELECT 1
            FROM vehicle_position_attempt AS attempt
            WHERE attempt.fetched_at BETWEEN scheduled.trip_start AND scheduled.trip_end
                AND attempt.fetched_at <= (SELECT fetched_at FROM matched_until)
        ) AS collected,
        seen_trip.trip_id IS NOT NULL AS seen,
        predicted_trip.trip_id IS NOT NULL AS predicted
    FROM {{ ref('scheduled_trip') }} AS scheduled
    LEFT JOIN seen_trip USING (service_date, trip_id)
    LEFT JOIN {{ ref('trip_update_trip') }} AS predicted_trip USING (service_date, trip_id)
)
SELECT
    route.route_short_name,
    trip.service_date,
    -- Hours past 24 belong to trips after midnight, as in GTFS stop times.
    {{ service_hour('trip.service_date', 'trip.trip_start') }}
        AS service_hour,
    count(*) AS scheduled_trips,
    count(*) FILTER (WHERE trip.collected) AS collected_trips,
    count(*) FILTER (WHERE trip.collected AND trip.seen) AS seen_trips,
    CASE WHEN min(trip.trip_start) >= (SELECT predicted_at FROM predicted_from)
        THEN count(*) FILTER (WHERE trip.collected AND trip.predicted)
    END AS predicted_trips
FROM trip
JOIN {{ source('staging', 'schedule_route') }} AS route
    ON route.schedule_sha256 = trip.schedule_sha256
    AND route.route_id = trip.route_id
GROUP BY route.route_short_name, trip.service_date, service_hour
