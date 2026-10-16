{{ config(materialized='table') }}

-- How many scheduled trips of each route appear in VehiclePositions and
-- TripUpdates, by service date and the hour of the service day in which they
-- start.
--
-- A trip is collected if VehiclePositions was downloaded at least once between
-- its scheduled start and end, up to the latest snapshot matched so far:
-- positions are loaded up to 30 minutes after download, and a trip that has
-- just started would otherwise count as unseen. Only collected trips can be
-- seen, so a gap in collection lowers collected_trips, not the share of them
-- that was seen.
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
WITH matched_until AS (
    SELECT max(first_fetched_at) AS fetched_at FROM {{ ref('vehicle_position_match') }}
),
predicted_from AS (
    SELECT min(first_predicted_at) AS predicted_at FROM {{ ref('trip_update_trip') }}
),
seen_trip AS (
    SELECT DISTINCT service_date, trip_id
    FROM {{ ref('vehicle_position_service_date') }}
),
trip AS (
    SELECT
        scheduled.*,
        EXISTS (
            SELECT 1
            FROM {{ source('metadata', 'fetch_attempt') }} AS attempt
            WHERE attempt.source_id = 'krakow_ztp_m_vehicle_positions'
                AND attempt.status <> 'failed'
                AND attempt.fetched_at BETWEEN scheduled.trip_start AND scheduled.trip_end
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
    floor(extract(epoch FROM trip.trip_start
        - {{ service_day_start('trip.service_date') }}) / 3600)::smallint
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
