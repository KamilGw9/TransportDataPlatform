-- One row per attempt to load a schedule version (the ZIP's SHA-256) into staging.
CREATE TABLE IF NOT EXISTS metadata.schedule_load (
    load_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    schedule_sha256 text NOT NULL CHECK (schedule_sha256 ~ '^[0-9a-f]{64}$'),
    object_key text NOT NULL,
    started_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('loaded', 'failed')),
    error text,
    CHECK ((status = 'failed') = (error IS NOT NULL))
);

-- A version is loaded at most once; failed attempts may repeat.
CREATE UNIQUE INDEX IF NOT EXISTS schedule_load_loaded_once_idx
    ON metadata.schedule_load (schedule_sha256)
    WHERE status = 'loaded';

-- Staging tables keep the columns needed for matching realtime data; the rest
-- stays in the RAW ZIP. Every key includes schedule_sha256 because GTFS ids are
-- only unique within one version.
CREATE TABLE IF NOT EXISTS staging.schedule_route (
    schedule_sha256 text NOT NULL,
    route_id text NOT NULL,
    route_short_name text,
    route_long_name text,
    route_type smallint NOT NULL,
    PRIMARY KEY (schedule_sha256, route_id)
);

CREATE TABLE IF NOT EXISTS staging.schedule_stop (
    schedule_sha256 text NOT NULL,
    stop_id text NOT NULL,
    stop_code text,
    stop_name text,
    stop_lat double precision CHECK (stop_lat BETWEEN -90 AND 90),
    stop_lon double precision CHECK (stop_lon BETWEEN -180 AND 180),
    PRIMARY KEY (schedule_sha256, stop_id)
);

CREATE TABLE IF NOT EXISTS staging.schedule_trip (
    schedule_sha256 text NOT NULL,
    trip_id text NOT NULL,
    route_id text NOT NULL,
    service_id text NOT NULL,
    trip_headsign text,
    direction_id smallint CHECK (direction_id IN (0, 1)),
    block_id text,
    shape_id text,
    PRIMARY KEY (schedule_sha256, trip_id),
    FOREIGN KEY (schedule_sha256, route_id)
        REFERENCES staging.schedule_route (schedule_sha256, route_id)
);

-- Times are seconds from the start of the service day: GTFS allows values past
-- 24:00:00 for trips that run after midnight, which the time type cannot hold.
CREATE TABLE IF NOT EXISTS staging.schedule_stop_time (
    schedule_sha256 text NOT NULL,
    trip_id text NOT NULL,
    stop_sequence integer NOT NULL CHECK (stop_sequence >= 0),
    stop_id text NOT NULL,
    arrival_seconds integer NOT NULL CHECK (arrival_seconds >= 0),
    departure_seconds integer NOT NULL,
    pickup_type smallint CHECK (pickup_type BETWEEN 0 AND 3),
    drop_off_type smallint CHECK (drop_off_type BETWEEN 0 AND 3),
    PRIMARY KEY (schedule_sha256, trip_id, stop_sequence),
    CHECK (departure_seconds >= arrival_seconds),
    FOREIGN KEY (schedule_sha256, trip_id)
        REFERENCES staging.schedule_trip (schedule_sha256, trip_id),
    FOREIGN KEY (schedule_sha256, stop_id)
        REFERENCES staging.schedule_stop (schedule_sha256, stop_id)
);

CREATE TABLE IF NOT EXISTS staging.schedule_calendar (
    schedule_sha256 text NOT NULL,
    service_id text NOT NULL,
    monday boolean NOT NULL,
    tuesday boolean NOT NULL,
    wednesday boolean NOT NULL,
    thursday boolean NOT NULL,
    friday boolean NOT NULL,
    saturday boolean NOT NULL,
    sunday boolean NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    PRIMARY KEY (schedule_sha256, service_id),
    CHECK (end_date >= start_date)
);

-- No foreign key to schedule_calendar: GTFS allows services defined only here.
CREATE TABLE IF NOT EXISTS staging.schedule_calendar_date (
    schedule_sha256 text NOT NULL,
    service_id text NOT NULL,
    service_date date NOT NULL,
    exception_type smallint NOT NULL CHECK (exception_type IN (1, 2)),
    PRIMARY KEY (schedule_sha256, service_id, service_date)
);
