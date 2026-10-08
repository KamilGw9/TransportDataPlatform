-- One row per attempt to load a stored TripUpdates snapshot into staging.
CREATE TABLE IF NOT EXISTS metadata.trip_update_load (
    load_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    object_key text NOT NULL,
    started_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('loaded', 'failed')),
    error text,
    CHECK ((status = 'failed') = (error IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS trip_update_load_loaded_once_idx
    ON metadata.trip_update_load (snapshot_sha256)
    WHERE status = 'loaded';

-- A snapshot has about 2,600 stop time updates, so the child tables refer to it
-- by a bigint instead of repeating the 64-character hash in every row and index.
CREATE TABLE IF NOT EXISTS staging.trip_update_snapshot (
    snapshot_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_sha256 text NOT NULL UNIQUE
        CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    feed_timestamp timestamptz NOT NULL
);

-- Mobilis repeats an entity id when two vehicles report the same trip, so an
-- entity is identified by its position in the message.
CREATE TABLE IF NOT EXISTS staging.trip_update (
    snapshot_id bigint NOT NULL
        REFERENCES staging.trip_update_snapshot (snapshot_id),
    entity_index integer NOT NULL CHECK (entity_index >= 0),
    entity_id text NOT NULL,
    trip_id text,
    route_id text,
    direction_id smallint CHECK (direction_id IN (0, 1)),
    trip_schedule_relationship text CHECK (
        trip_schedule_relationship IN (
            'SCHEDULED', 'ADDED', 'UNSCHEDULED', 'CANCELED',
            'REPLACEMENT', 'DUPLICATED', 'DELETED'
        )
    ),
    vehicle_id text,
    vehicle_label text,
    update_timestamp timestamptz,
    PRIMARY KEY (snapshot_id, entity_index)
);

-- The scheduled time of a stop is its predicted time minus the delay, so a
-- prediction must carry both; Mobilis has always sent both.
CREATE TABLE IF NOT EXISTS staging.stop_time_update (
    snapshot_id bigint NOT NULL,
    entity_index integer NOT NULL,
    stop_sequence integer NOT NULL CHECK (stop_sequence >= 0),
    stop_id text,
    schedule_relationship text CHECK (
        schedule_relationship IN ('SCHEDULED', 'SKIPPED', 'NO_DATA', 'UNSCHEDULED')
    ),
    arrival_time timestamptz,
    arrival_delay integer,
    departure_time timestamptz,
    departure_delay integer,
    PRIMARY KEY (snapshot_id, entity_index, stop_sequence),
    FOREIGN KEY (snapshot_id, entity_index)
        REFERENCES staging.trip_update (snapshot_id, entity_index),
    CHECK ((arrival_time IS NULL) = (arrival_delay IS NULL)),
    CHECK ((departure_time IS NULL) = (departure_delay IS NULL))
);
