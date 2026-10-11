{{ config(
    materialized='incremental',
    incremental_strategy='append',
    indexes=[{'columns': ['snapshot_sha256']}],
) }}

-- Each Mobilis vehicle position with the trip it refers to in the schedule
-- version that was the latest one archived when the snapshot was first
-- downloaded. A version archived later can contain the same trip_id, but the
-- pipeline did not know it at that time.
--
-- A build adds the snapshots not matched yet, in whatever order they were
-- loaded (ADR 006). A match is never revised, so a snapshot waits while a
-- schedule version archived before it is not loaded: the schedule collector
-- loads the latest archived version, which takes seconds and can fail. A
-- version replaced by a newer one before it loaded never will, and the
-- snapshots that waited for it get the version before it.
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
),
waiting_since AS (
    SELECT min(fetched_at) AS fetched_at
    FROM {{ source('metadata', 'fetch_attempt') }}
    WHERE source_id = 'krakow_ztp_m'
        AND status <> 'failed'
        AND fetched_at > (SELECT max(fetched_at) FROM schedule_version)
),
new_snapshot AS (
    SELECT *
    FROM snapshot_fetch
    WHERE first_fetched_at < coalesce(
        (SELECT fetched_at FROM waiting_since), 'infinity'
    )
    {%- if is_incremental() %}
        AND NOT EXISTS (
            SELECT 1
            FROM {{ this }} AS matched
            WHERE matched.snapshot_sha256 = snapshot_fetch.snapshot_sha256
        )
    {%- endif %}
),
-- Chosen per snapshot, not per position: a lookup for each of 527,000
-- positions took 87 s of a 89 s build on 2026-10-11.
snapshot_version AS (
    SELECT new_snapshot.*, version.schedule_sha256
    FROM new_snapshot
    LEFT JOIN LATERAL (
        SELECT schedule_version.schedule_sha256
        FROM schedule_version
        WHERE schedule_version.fetched_at <= new_snapshot.first_fetched_at
        ORDER BY schedule_version.fetched_at DESC
        LIMIT 1
    ) AS version ON true
)
SELECT
    position.snapshot_sha256,
    snapshot_version.first_fetched_at,
    position.entity_id,
    position.trip_id,
    position.route_id,
    snapshot_version.schedule_sha256,
    trip.trip_id IS NOT NULL AS trip_found,
    trip.route_id = position.route_id AS route_matches
FROM {{ source('staging', 'vehicle_position') }} AS position
JOIN snapshot_version USING (snapshot_sha256)
LEFT JOIN {{ source('staging', 'schedule_trip') }} AS trip
    ON trip.schedule_sha256 = snapshot_version.schedule_sha256
    AND trip.trip_id = position.trip_id
