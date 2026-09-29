-- Version 1. Run explicitly with scripts/setup_database.py, never at app startup.
BEGIN;
CREATE TABLE IF NOT EXISTS aircraft (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 icao text NOT NULL UNIQUE,
 first_seen timestamptz NOT NULL,
 last_seen timestamptz NOT NULL,
 last_position_at timestamptz,
 position_messages bigint NOT NULL DEFAULT 0,
 manufacturer text, model text, owner text, registration text,
 callsign text, latitude double precision, longitude double precision,
 altitude_ft double precision, speed_kt double precision,
 latest jsonb NOT NULL DEFAULT '{}'::jsonb,
 stats_date date,
 daily jsonb NOT NULL DEFAULT '{}'::jsonb,
 metadata_retry_at timestamptz,
 CHECK (latitude BETWEEN -90 AND 90), CHECK (longitude BETWEEN -180 AND 180)
);
CREATE INDEX IF NOT EXISTS aircraft_last_seen ON aircraft(last_seen);
CREATE TABLE IF NOT EXISTS aircraft_positions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 aircraft_id bigint NOT NULL REFERENCES aircraft(id),
 observed_at timestamptz NOT NULL,
 received_at timestamptz NOT NULL,
 latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
 longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
 altitude_ft double precision, speed_kt double precision,
 distance_km double precision, bearing_deg double precision,
 details jsonb NOT NULL DEFAULT '{}'::jsonb,
 UNIQUE(aircraft_id, observed_at)
);
CREATE INDEX IF NOT EXISTS positions_received ON aircraft_positions(received_at,id);
CREATE TABLE IF NOT EXISTS performance_stats (
 sampled_at timestamptz PRIMARY KEY,
 cpu_percent double precision, ram_percent double precision,
 disk_percent double precision, temperature_c double precision,
 api_calls_10_min integer NOT NULL,
 receiver_status text NOT NULL, api_available boolean NOT NULL,
 firebase_available boolean NOT NULL
);
CREATE TABLE IF NOT EXISTS tracker_stats (
 day date PRIMARY KEY,
 updated_at timestamptz NOT NULL,
 total_aircraft integer NOT NULL, active_aircraft integer NOT NULL,
 top_airline text, top_aircraft text, top_manufacturer text,
 summary jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS tracker_samples (
 sampled_at timestamptz PRIMARY KEY,
 active integer, total integer NOT NULL,
 receiver_status text NOT NULL,
 details jsonb NOT NULL DEFAULT '{}'::jsonb
);
COMMENT ON TABLE aircraft IS 'PlaneTracker schema version 1; one identifier per aircraft row';
COMMIT;
