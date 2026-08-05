CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS cartography;

CREATE TABLE IF NOT EXISTS cartography.admin_boundaries (
    id bigserial PRIMARY KEY,
    country_code text NOT NULL,
    state_name text NOT NULL,
    municipality_name text NOT NULL,
    admin_level smallint NOT NULL,
    osm_relation_id bigint NOT NULL UNIQUE,
    wikidata text,
    wikipedia text,
    source text NOT NULL DEFAULT 'OpenStreetMap',
    source_url text NOT NULL,
    source_license text NOT NULL DEFAULT 'ODbL-1.0',
    halo_color text NOT NULL DEFAULT '#00AEEF',
    halo_width_px numeric(6, 2) NOT NULL DEFAULT 3.00,
    fill_color text NOT NULL DEFAULT '#00AEEF',
    fill_opacity numeric(4, 3) NOT NULL DEFAULT 0.180,
    geom geometry(MultiPolygon, 4326) NOT NULL,
    bbox geometry(Polygon, 4326) GENERATED ALWAYS AS (ST_Envelope(geom)) STORED,
    label_point geometry(Point, 4326) GENERATED ALWAYS AS (ST_PointOnSurface(geom)) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT admin_boundaries_admin_level_check CHECK (admin_level > 0),
    CONSTRAINT admin_boundaries_fill_opacity_check CHECK (fill_opacity >= 0 AND fill_opacity <= 1)
);

CREATE INDEX IF NOT EXISTS admin_boundaries_geom_gix
    ON cartography.admin_boundaries
    USING gist (geom);

CREATE INDEX IF NOT EXISTS admin_boundaries_bbox_gix
    ON cartography.admin_boundaries
    USING gist (bbox);

CREATE INDEX IF NOT EXISTS admin_boundaries_label_point_gix
    ON cartography.admin_boundaries
    USING gist (label_point);

CREATE INDEX IF NOT EXISTS admin_boundaries_state_name_idx
    ON cartography.admin_boundaries (state_name);

CREATE OR REPLACE FUNCTION cartography.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS admin_boundaries_set_updated_at
    ON cartography.admin_boundaries;

CREATE TRIGGER admin_boundaries_set_updated_at
BEFORE UPDATE ON cartography.admin_boundaries
FOR EACH ROW
EXECUTE FUNCTION cartography.set_updated_at();
