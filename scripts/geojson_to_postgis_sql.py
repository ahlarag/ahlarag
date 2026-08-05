#!/usr/bin/env python3
"""Convert the Nueva Esparta GeoJSON file into PostGIS upsert SQL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PostGIS upsert SQL from GeoJSON.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/nueva_esparta_municipios.geojson"),
        help="Input GeoJSON path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("sql/002_import_nueva_esparta_municipios.sql"),
        help="Output SQL path.",
    )
    return parser.parse_args()


def feature_to_insert(feature: dict[str, Any]) -> str:
    properties = feature["properties"]
    geometry_json = json.dumps(feature["geometry"], ensure_ascii=False, separators=(",", ":"))
    area_type = properties.get("area_type") or (
        "state" if int(properties["admin_level"]) == 4 else "municipality"
    )
    area_name = properties.get("area_name") or properties["name_clean"]
    municipality_name = area_name if area_type == "municipality" else None

    values = [
        sql_literal(properties["country_code"]),
        sql_literal(area_type),
        sql_literal(area_name),
        sql_literal(properties["state"]),
        sql_literal(municipality_name),
        str(int(properties["admin_level"])),
        str(int(properties["osm_relation_id"])),
        sql_literal(properties.get("wikidata")),
        sql_literal(properties.get("wikipedia")),
        sql_literal(properties["source"]),
        sql_literal(properties["source_url"]),
        sql_literal(properties["license"]),
        f"ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($geojson${geometry_json}$geojson$), 4326))",
    ]

    return f"""
INSERT INTO cartography.admin_boundaries (
    country_code,
    area_type,
    area_name,
    state_name,
    municipality_name,
    admin_level,
    osm_relation_id,
    wikidata,
    wikipedia,
    source,
    source_url,
    source_license,
    geom
) VALUES (
    {values[0]},
    {values[1]},
    {values[2]},
    {values[3]},
    {values[4]},
    {values[5]},
    {values[6]},
    {values[7]},
    {values[8]},
    {values[9]},
    {values[10]},
    {values[11]},
    {values[12]}
)
ON CONFLICT (osm_relation_id) DO UPDATE SET
    country_code = EXCLUDED.country_code,
    area_type = EXCLUDED.area_type,
    area_name = EXCLUDED.area_name,
    state_name = EXCLUDED.state_name,
    municipality_name = EXCLUDED.municipality_name,
    admin_level = EXCLUDED.admin_level,
    wikidata = EXCLUDED.wikidata,
    wikipedia = EXCLUDED.wikipedia,
    source = EXCLUDED.source,
    source_url = EXCLUDED.source_url,
    source_license = EXCLUDED.source_license,
    geom = EXCLUDED.geom;
""".strip()


def main() -> int:
    args = parse_args()
    feature_collection = json.loads(args.input.read_text(encoding="utf-8"))
    features = feature_collection["features"]

    statements = [
        f"-- Generated from {args.input}.",
        "-- Run sql/001_cartography_schema.sql before this file.",
        "BEGIN;",
        *[feature_to_insert(feature) for feature in features],
        "COMMIT;",
        "",
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n\n".join(statements), encoding="utf-8")
    print(f"Wrote {args.output} with {len(features)} upserts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
