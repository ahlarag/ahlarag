#!/usr/bin/env python3
"""Fetch Nueva Esparta municipality boundaries from OpenStreetMap.

The script uses the public OSM API, reconstructs administrative boundary
relations from their member ways, and writes a GeoJSON FeatureCollection in
EPSG:4326 (longitude, latitude). It intentionally avoids third-party Python
dependencies so it can run in CI or on a clean workstation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


OSM_API = "https://www.openstreetmap.org/api/0.6"
STATE_RELATION_ID = 2269770
USER_AGENT = "nueva-esparta-cartography-fetcher/1.0"


@dataclass(frozen=True)
class BoundaryRelation:
    osm_relation_id: int
    name: str
    tags: dict[str, str]
    geometry: dict[str, Any]
    bbox: list[float]


def fetch_url(url: str, retries: int = 4) -> bytes:
    """Fetch a URL with small exponential backoff for transient failures."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == retries - 1:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"Could not fetch {url}: {last_error}") from last_error


def parse_tags(element: ET.Element) -> dict[str, str]:
    return {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}


def get_state_subarea_relation_ids(state_relation_id: int) -> list[int]:
    xml = fetch_url(f"{OSM_API}/relation/{state_relation_id}")
    root = ET.fromstring(xml)
    relation = root.find("relation")
    if relation is None:
        raise RuntimeError(f"State relation {state_relation_id} was not found")

    relation_ids: list[int] = []
    for member in relation.findall("member"):
        if member.attrib.get("type") == "relation" and member.attrib.get("role") == "subarea":
            relation_ids.append(int(member.attrib["ref"]))
    if not relation_ids:
        raise RuntimeError(f"State relation {state_relation_id} has no subarea members")
    return relation_ids


def signed_area(ring: list[list[float]]) -> float:
    area = 0.0
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        area += (x1 * y2) - (x2 * y1)
    return area / 2.0


def orient_ring(ring: list[list[float]], clockwise: bool) -> list[list[float]]:
    is_clockwise = signed_area(ring) < 0
    if is_clockwise != clockwise:
        return list(reversed(ring))
    return ring


def point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test for assigning holes to outers."""
    x, y = point
    inside = False
    previous_x, previous_y = ring[-1]
    for current_x, current_y in ring:
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            slope_x = (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
            if x < slope_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def join_way_segments(segments: list[list[int]], relation_id: int, role: str) -> list[list[int]]:
    """Join OSM way node sequences into closed rings."""
    remaining = [segment[:] for segment in segments if len(segment) > 1]
    rings: list[list[int]] = []

    while remaining:
        ring = remaining.pop(0)

        while ring[0] != ring[-1]:
            matched_index: int | None = None
            matched_ring: list[int] | None = None

            for index, segment in enumerate(remaining):
                if ring[-1] == segment[0]:
                    matched_ring = ring + segment[1:]
                elif ring[-1] == segment[-1]:
                    matched_ring = ring + list(reversed(segment[:-1]))
                elif ring[0] == segment[-1]:
                    matched_ring = segment[:-1] + ring
                elif ring[0] == segment[0]:
                    matched_ring = list(reversed(segment[1:])) + ring

                if matched_ring is not None:
                    matched_index = index
                    break

            if matched_index is None or matched_ring is None:
                raise RuntimeError(
                    f"Relation {relation_id} has an open {role} boundary ring "
                    f"with endpoints {ring[0]} and {ring[-1]}"
                )

            ring = matched_ring
            remaining.pop(matched_index)

        rings.append(ring)

    return rings


def ring_bbox(ring: list[list[float]]) -> list[float]:
    longitudes = [point[0] for point in ring]
    latitudes = [point[1] for point in ring]
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def merge_bboxes(bboxes: list[list[float]]) -> list[float]:
    return [
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    ]


def relation_to_boundary(relation_id: int, expected_admin_level: str | None = None) -> BoundaryRelation:
    xml = fetch_url(f"{OSM_API}/relation/{relation_id}/full")
    root = ET.fromstring(xml)

    nodes: dict[int, list[float]] = {}
    for node in root.findall("node"):
        nodes[int(node.attrib["id"])] = [float(node.attrib["lon"]), float(node.attrib["lat"])]

    ways: dict[int, list[int]] = {}
    for way in root.findall("way"):
        ways[int(way.attrib["id"])] = [int(nd.attrib["ref"]) for nd in way.findall("nd")]

    relation = None
    for candidate in root.findall("relation"):
        if candidate.attrib.get("id") == str(relation_id):
            relation = candidate
            break
    if relation is None:
        raise RuntimeError(f"Relation {relation_id} was not found in full OSM payload")

    tags = parse_tags(relation)
    if tags.get("boundary") != "administrative":
        raise RuntimeError(f"Relation {relation_id} is not an administrative boundary")
    if expected_admin_level is not None and tags.get("admin_level") != expected_admin_level:
        raise RuntimeError(f"Relation {relation_id} is not admin_level={expected_admin_level}")

    role_segments: dict[str, list[list[int]]] = {"outer": [], "inner": []}
    for member in relation.findall("member"):
        if member.attrib.get("type") != "way":
            continue
        role = member.attrib.get("role", "")
        if role not in role_segments:
            continue
        way_id = int(member.attrib["ref"])
        if way_id not in ways:
            raise RuntimeError(f"Relation {relation_id} references missing way {way_id}")
        role_segments[role].append(ways[way_id])

    outer_node_rings = join_way_segments(role_segments["outer"], relation_id, "outer")
    inner_node_rings = join_way_segments(role_segments["inner"], relation_id, "inner")

    outer_rings = [
        orient_ring([nodes[node_id] for node_id in ring], clockwise=False)
        for ring in outer_node_rings
    ]
    inner_rings = [
        orient_ring([nodes[node_id] for node_id in ring], clockwise=True)
        for ring in inner_node_rings
    ]

    polygons = [[outer] for outer in outer_rings]
    for inner in inner_rings:
        assigned = False
        test_point = inner[0]
        for polygon in polygons:
            if point_in_ring(test_point, polygon[0]):
                polygon.append(inner)
                assigned = True
                break
        if not assigned:
            raise RuntimeError(f"Inner ring in relation {relation_id} is not inside any outer ring")

    bboxes = [ring_bbox(polygon[0]) for polygon in polygons]
    geometry = {"type": "MultiPolygon", "coordinates": polygons}
    return BoundaryRelation(
        osm_relation_id=relation_id,
        name=tags.get("name", f"OSM relation {relation_id}"),
        tags=tags,
        geometry=geometry,
        bbox=merge_bboxes(bboxes),
    )


def feature_from_boundary(boundary: BoundaryRelation, area_type: str) -> dict[str, Any]:
    tags = boundary.tags
    name_clean = boundary.name.removeprefix("Municipio ").strip()
    return {
        "type": "Feature",
        "id": f"osm:relation:{boundary.osm_relation_id}",
        "bbox": boundary.bbox,
        "properties": {
            "country_code": "VE",
            "state": "Nueva Esparta",
            "state_osm_relation_id": STATE_RELATION_ID,
            "name": boundary.name,
            "name_clean": name_clean,
            "area_name": name_clean,
            "area_type": area_type,
            "admin_level": int(tags["admin_level"]),
            "osm_relation_id": boundary.osm_relation_id,
            "wikidata": tags.get("wikidata"),
            "wikipedia": tags.get("wikipedia"),
            "source": "OpenStreetMap",
            "source_url": f"https://www.openstreetmap.org/relation/{boundary.osm_relation_id}",
            "license": "ODbL-1.0",
        },
        "geometry": boundary.geometry,
    }


def write_geojson(features: list[dict[str, Any]], output_path: Path, collection_name: str) -> None:
    feature_collection = {
        "type": "FeatureCollection",
        "name": collection_name,
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "bbox": merge_bboxes([feature["bbox"] for feature in features]),
        "features": sorted(features, key=lambda feature: feature["properties"]["name_clean"]),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(feature_collection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Nueva Esparta municipality boundaries from OpenStreetMap as GeoJSON."
    )
    parser.add_argument(
        "--state-relation-id",
        type=int,
        default=STATE_RELATION_ID,
        help="OSM relation ID for Nueva Esparta State.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/nueva_esparta_municipios.geojson"),
        help="Municipality output GeoJSON path.",
    )
    parser.add_argument(
        "--state-output",
        type=Path,
        default=Path("data/nueva_esparta_estado.geojson"),
        help="State boundary output GeoJSON path.",
    )
    parser.add_argument(
        "--margarita-output",
        type=Path,
        default=Path("data/isla_margarita_municipios.geojson"),
        help="Municipality subset for Isla de Margarita. This excludes Villalba/Isla de Coche.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state_boundary = relation_to_boundary(args.state_relation_id, expected_admin_level="4")
    write_geojson(
        [feature_from_boundary(state_boundary, "state")],
        args.state_output,
        "estado_nueva_esparta_osm",
    )
    print(f"Wrote {args.state_output} with the Nueva Esparta state boundary")

    relation_ids = get_state_subarea_relation_ids(args.state_relation_id)
    features: list[dict[str, Any]] = []

    for relation_id in relation_ids:
        boundary = relation_to_boundary(relation_id, expected_admin_level="6")
        print(f"Fetched {boundary.name} ({relation_id})", file=sys.stderr)
        features.append(feature_from_boundary(boundary, "municipality"))

    if len(features) != 11:
        raise RuntimeError(f"Expected 11 municipalities, got {len(features)}")

    write_geojson(features, args.output, "municipios_nueva_esparta_osm")
    print(f"Wrote {args.output} with {len(features)} municipality features")

    margarita_features = [
        feature
        for feature in features
        if feature["properties"]["name_clean"] != "Villalba"
    ]
    write_geojson(
        margarita_features,
        args.margarita_output,
        "municipios_isla_margarita_osm",
    )
    print(
        f"Wrote {args.margarita_output} with {len(margarita_features)} Isla de Margarita municipality features"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
