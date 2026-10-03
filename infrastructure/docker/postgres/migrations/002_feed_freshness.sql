-- Latest attempt, latest success and latest content change for each source.
-- A content change is a successful attempt whose hash differs from the previous
-- successful one, so failures in between and the daily re-store of the same
-- snapshot do not count.
CREATE OR REPLACE VIEW metadata.feed_freshness AS
SELECT
    source_id,
    max(fetched_at) AS last_attempt_at,
    max(fetched_at) FILTER (WHERE status <> 'failed') AS last_success_at,
    max(fetched_at) FILTER (
        WHERE status <> 'failed' AND content_changed
    ) AS last_change_at
FROM (
    SELECT
        source_id,
        fetched_at,
        status,
        -- Partitioning by failure compares each success only with the previous
        -- success.
        sha256 IS DISTINCT FROM lag(sha256) OVER (
            PARTITION BY source_id, status = 'failed'
            ORDER BY fetched_at
        ) AS content_changed
    FROM metadata.fetch_attempt
) AS attempt
GROUP BY source_id;
