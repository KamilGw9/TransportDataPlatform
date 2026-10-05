-- core.vehicle_position_match is now a dbt model (transform/models/core);
-- migrations own only the metadata and staging schemas.
DROP VIEW IF EXISTS core.vehicle_position_match;
