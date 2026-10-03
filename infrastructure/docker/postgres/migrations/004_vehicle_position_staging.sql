-- One row per attempt to load a stored VehiclePositions snapshot into staging.
CREATE TABLE IF NOT EXISTS metadata.vehicle_position_load (
    load_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    object_key text NOT NULL,
    started_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('loaded', 'failed')),
    error text,
    CHECK ((status = 'failed') = (error IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS vehicle_position_load_loaded_once_idx
    ON metadata.vehicle_position_load (snapshot_sha256)
    WHERE status = 'loaded';

-- Fetch times stay in metadata.fetch_attempt; the same snapshot can be
-- downloaded several times, but it was generated once.
CREATE TABLE IF NOT EXISTS staging.vehicle_position_snapshot (
    snapshot_sha256 text PRIMARY KEY,
    feed_timestamp timestamptz NOT NULL
);

-- Enum values are stored by name so that queries read without a lookup table.
-- Mobilis does not send start_date or start_time, so the service date of a trip
-- has to be inferred from the schedule.
CREATE TABLE IF NOT EXISTS staging.vehicle_position (
    snapshot_sha256 text NOT NULL
        REFERENCES staging.vehicle_position_snapshot (snapshot_sha256),
    entity_id text NOT NULL,
    vehicle_id text,
    vehicle_label text,
    trip_id text,
    route_id text,
    direction_id smallint CHECK (direction_id IN (0, 1)),
    trip_schedule_relationship text CHECK (
        trip_schedule_relationship IN (
            'SCHEDULED', 'ADDED', 'UNSCHEDULED', 'CANCELED',
            'REPLACEMENT', 'DUPLICATED', 'DELETED'
        )
    ),
    latitude double precision CHECK (latitude BETWEEN -90 AND 90),
    longitude double precision CHECK (longitude BETWEEN -180 AND 180),
    bearing real CHECK (bearing >= 0 AND bearing < 360),
    speed real CHECK (speed >= 0),
    current_status text CHECK (
        current_status IN ('INCOMING_AT', 'STOPPED_AT', 'IN_TRANSIT_TO')
    ),
    current_stop_sequence integer CHECK (current_stop_sequence >= 0),
    stop_id text,
    position_timestamp timestamptz,
    PRIMARY KEY (snapshot_sha256, entity_id),
    CHECK ((latitude IS NULL) = (longitude IS NULL))
);
