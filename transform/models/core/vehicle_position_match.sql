-- Each Mobilis vehicle position with the trip it refers to in the schedule
-- version that was the latest one archived when the snapshot was first
-- downloaded. A version archived later can contain the same trip_id, but the
-- pipeline did not know it at that time.
WITH snapshot_fetch AS (
    SELECT sha256 AS snapshot_sha256, min(fetched_at) AS first_fetched_at
    FROM {{ source('metadata', 'fetch_attempt') }}
    WHERE source_id = 'krakow_ztp_m_vehicle_positions' AND status = 'stored'
    GROUP BY sha256
),
schedule_version AS (
    SELECT attempt.sha256 AS schedule_sha256, attempt.fetched_at
    FROM {{ source('metadata', 'fetch_attempt') }} AS attempt
    JOIN {{ source('metadata', 'schedule_load') }} AS schedule_load
        ON schedule_load.schedule_sha256 = attempt.sha256
        AND schedule_load.status = 'loaded'
    WHERE attempt.source_id = 'krakow_ztp_m' AND attempt.status <> 'failed'
)
SELECT
    position.snapshot_sha256,
    snapshot_fetch.first_fetched_at,
    position.entity_id,
    position.trip_id,
    position.route_id,
    version.schedule_sha256,
    trip.trip_id IS NOT NULL AS trip_found,
    trip.route_id = position.route_id AS route_matches
FROM {{ source('staging', 'vehicle_position') }} AS position
JOIN snapshot_fetch USING (snapshot_sha256)
LEFT JOIN LATERAL (
    SELECT schedule_version.schedule_sha256
    FROM schedule_version
    WHERE schedule_version.fetched_at <= snapshot_fetch.first_fetched_at
    ORDER BY schedule_version.fetched_at DESC
    LIMIT 1
) AS version ON true
LEFT JOIN {{ source('staging', 'schedule_trip') }} AS trip
    ON trip.schedule_sha256 = version.schedule_sha256
    AND trip.trip_id = position.trip_id
