# SIG de Nueva Esparta y red eléctrica

Dos entregables complementarios sobre PostgreSQL/PostGIS:

1. Cartografía municipal del estado Nueva Esparta obtenida de OpenStreetMap.
2. Sistema de información geográfica de red eléctrica de distribución, con
   análisis de topología, flujos de carga, maniobras y confiabilidad.

## Red eléctrica

- `sql/010_electric_network_schema.sql`: modelo de datos de la red, de la
  subestación al cliente.
- `sql/011_electric_network_topology.sql`: funciones de trazado de energización,
  aislamiento y transferencias.
- `sql/012_seed_sample_network.sql`: red de ejemplo en Isla de Margarita.
- `sql/013_validate_topology.sql`: validación automática de las funciones.
- `electric_gis/`: motor de análisis en Python. Topología, flujo de carga radial
  de media y baja tensión, maniobras y confiabilidad.
- `.cursor/skills/electrical-gis-*`: skills con los criterios de ingeniería.
- `docs/electrical_gis_architecture.md`: arquitectura, alcance y puesta en marcha.

```bash
createdb gis_electrico
psql -d gis_electrico -f sql/010_electric_network_schema.sql
psql -d gis_electrico -f sql/011_electric_network_topology.sql
psql -d gis_electrico -f sql/012_seed_sample_network.sql
psql -d gis_electrico -f sql/013_validate_topology.sql
python3 -m pytest tests -q
```

## Cartografía municipal

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
