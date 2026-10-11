-- Position snapshots in staging that are still not matched, because a schedule
-- version archived before them has not loaded (ADR 006). The schedule collector
-- retries the load every hour, so after 2 hours a retry has failed too.
SELECT
    snapshot.snapshot_sha256,
    min(attempt.fetched_at) AS first_fetched_at
FROM {{ source('staging', 'vehicle_position_snapshot') }} AS snapshot
JOIN {{ source('metadata', 'fetch_attempt') }} AS attempt
    ON attempt.sha256 = snapshot.snapshot_sha256
    AND attempt.source_id = 'krakow_ztp_m_vehicle_positions'
    AND attempt.status = 'stored'
WHERE NOT EXISTS (
    SELECT 1
    FROM {{ ref('vehicle_position_match') }} AS matched
    WHERE matched.snapshot_sha256 = snapshot.snapshot_sha256
)
GROUP BY snapshot.snapshot_sha256
HAVING min(attempt.fetched_at) < now() - interval '2 hours'
