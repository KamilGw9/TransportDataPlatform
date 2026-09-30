-- One row per download attempt, including unchanged feeds and failures.
CREATE TABLE IF NOT EXISTS metadata.fetch_attempt (
    attempt_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id text NOT NULL,
    url text NOT NULL,
    fetched_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('stored', 'unchanged', 'failed')),
    http_status integer,
    size_bytes bigint CHECK (size_bytes >= 0),
    sha256 text CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    object_key text,
    error text,
    CHECK ((status = 'failed') = (error IS NOT NULL)),
    CHECK (
        status = 'failed'
        OR (size_bytes IS NOT NULL AND sha256 IS NOT NULL AND object_key IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS fetch_attempt_source_time_idx
    ON metadata.fetch_attempt (source_id, fetched_at DESC);
