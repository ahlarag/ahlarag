# Cartografia de Nueva Esparta

Entregable para obtener los limites municipales del estado Nueva Esparta
(Venezuela) desde OpenStreetMap y prepararlos para PostgreSQL/PostGIS.

## Contenido

- `scripts/fetch_nueva_esparta_osm.py`: descarga relaciones OSM y genera
  `data/nueva_esparta_estado.geojson`,
  `data/nueva_esparta_municipios.geojson` y
  `data/isla_margarita_municipios.geojson`.
- `scripts/geojson_to_postgis_sql.py`: convierte el GeoJSON en SQL de importacion
  para PostGIS.
- `sql/001_cartography_schema.sql`: esquema recomendado para almacenar los
  poligonos y estilos basicos de halo/transparencia.
- `overpass/nueva_esparta_municipios.overpassql`: consulta de referencia para
  inspeccionar las relaciones en Overpass Turbo.
- `docs/nueva_esparta_cartography.md`: guia de uso, importacion y ejemplo de
  visualizacion en mapas libres.

## Uso rapido

```bash
python3 scripts/fetch_nueva_esparta_osm.py
python3 scripts/geojson_to_postgis_sql.py
python3 scripts/geojson_to_postgis_sql.py \
  --input data/nueva_esparta_estado.geojson \
  --output sql/003_import_nueva_esparta_estado.sql
psql "$DATABASE_URL" -f sql/001_cartography_schema.sql
psql "$DATABASE_URL" -f sql/002_import_nueva_esparta_municipios.sql
psql "$DATABASE_URL" -f sql/003_import_nueva_esparta_estado.sql
```

Las coordenadas quedan en GeoJSON con orden `[longitud, latitud]` y geometria
`MultiPolygon` en SRID 4326.
