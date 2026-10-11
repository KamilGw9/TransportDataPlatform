-- A snapshot that has left the staging window can be reloaded from RAW
-- (ADR 006), so it may have more than one successful load. Staging still holds
-- each snapshot at most once, by the unique hash in trip_update_snapshot.
CREATE INDEX IF NOT EXISTS trip_update_load_loaded_idx
    ON metadata.trip_update_load (snapshot_sha256)
    WHERE status = 'loaded';

DROP INDEX IF EXISTS metadata.trip_update_load_loaded_once_idx;
