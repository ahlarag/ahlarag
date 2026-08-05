# Cartografia de Nueva Esparta para PostGIS y mapas libres

Este paquete prepara los limites administrativos municipales del estado Nueva
Esparta, Venezuela, para almacenarlos en PostgreSQL/PostGIS y dibujarlos en un
cliente de mapa libre como MapLibre GL JS, OpenLayers o Leaflet.

## Sistema de coordenadas

- Formato de salida: GeoJSON `FeatureCollection`.
- CRS: WGS84 / CRS84, equivalente practico a EPSG:4326 para GeoJSON.
- Orden de coordenadas: `[longitud, latitud]`.
- Tipo geometrico por municipio: `MultiPolygon`.

Para PostGIS se almacena como:

```sql
geometry(MultiPolygon, 4326)
```

## Fuente libre recomendada

La fuente usada es OpenStreetMap:

- Estado Nueva Esparta: relacion OSM `2269770`.
- Municipios: relaciones `admin_level=6` incluidas como `subarea` del estado.
- Licencia: Open Database License (ODbL 1.0).

Al publicar o redistribuir el mapa/datos, incluyan atribucion a OpenStreetMap y
sus contribuidores segun la ODbL.

## Municipios incluidos

| Municipio | Relacion OSM | Wikidata |
| --- | ---: | --- |
| Antolin del Campo | 8150244 | Q2856992 |
| Arismendi | 8150245 | Q1925791 |
| Diaz | 8150249 | Q2068516 |
| Garcia | 8150248 | Q2029662 |
| Gomez | 8150243 | Q2451657 |
| Maneiro | 8150246 | Q3066174 |
| Marcano | 8150242 | Q748134 |
| Marino | 8150247 | Q2413769 |
| Macanao / Peninsula de Macanao | 8150251 | Q2239704 |
| Tubores | 8150250 | Q2102962 |
| Villalba | 8150252 | Q2208173 |

Nota cartografica: el estado Nueva Esparta incluye Isla de Margarita, Isla de
Coche e Isla de Cubagua. Si el producto necesita mostrar estrictamente Isla de
Margarita, normalmente se excluye Villalba porque corresponde a Isla de Coche.
Tubores puede incluir geometria asociada a Cubagua segun la division municipal;
si necesitan separar isla fisica de municipio politico, conviene crear una capa
adicional de islas o recortar la geometria contra una mascara costera validada.

## Generar GeoJSON

Desde la raiz del repositorio:

```bash
python3 scripts/fetch_nueva_esparta_osm.py \
  --output data/nueva_esparta_municipios.geojson
```

El script:

1. Lee la relacion del estado `2269770`.
2. Extrae sus 11 relaciones municipales `subarea`.
3. Descarga cada relacion con `/relation/{id}/full`.
4. Reconstruye los anillos `outer` e `inner`.
5. Escribe `data/nueva_esparta_municipios.geojson`.

## Importar a PostGIS

Opcion A: SQL generado por este paquete.

```bash
python3 scripts/geojson_to_postgis_sql.py
psql "$DATABASE_URL" -f sql/001_cartography_schema.sql
psql "$DATABASE_URL" -f sql/002_import_nueva_esparta_municipios.sql
```

Opcion B: GDAL/ogr2ogr.

```bash
psql "$DATABASE_URL" -f sql/001_cartography_schema.sql
ogr2ogr \
  -f PostgreSQL "$DATABASE_URL" \
  data/nueva_esparta_municipios.geojson \
  -nln cartography.admin_boundaries_staging \
  -nlt PROMOTE_TO_MULTI \
  -lco GEOMETRY_NAME=geom \
  -t_srs EPSG:4326 \
  -overwrite
```

Despues de cargar con staging, mapeen los campos del GeoJSON hacia
`cartography.admin_boundaries`.

## Ejemplo de consulta para el frontend

```sql
SELECT jsonb_build_object(
    'type', 'FeatureCollection',
    'features', jsonb_agg(
        jsonb_build_object(
            'type', 'Feature',
            'id', 'osm:relation:' || osm_relation_id,
            'properties', jsonb_build_object(
                'id', id,
                'municipality_name', municipality_name,
                'osm_relation_id', osm_relation_id,
                'halo_color', halo_color,
                'halo_width_px', halo_width_px,
                'fill_color', fill_color,
                'fill_opacity', fill_opacity
            ),
            'geometry', ST_AsGeoJSON(geom)::jsonb
        )
    )
) AS geojson
FROM cartography.admin_boundaries
WHERE state_name = 'Nueva Esparta';
```

## Ejemplo de halo y transparencia en MapLibre GL JS

```js
map.addSource('municipios-nueva-esparta', {
  type: 'geojson',
  data: '/api/cartography/nueva-esparta/municipios'
});

map.addLayer({
  id: 'municipios-fill',
  type: 'fill',
  source: 'municipios-nueva-esparta',
  paint: {
    'fill-color': ['coalesce', ['get', 'fill_color'], '#00AEEF'],
    'fill-opacity': ['coalesce', ['get', 'fill_opacity'], 0.18]
  }
});

map.addLayer({
  id: 'municipios-halo',
  type: 'line',
  source: 'municipios-nueva-esparta',
  paint: {
    'line-color': ['coalesce', ['get', 'halo_color'], '#00AEEF'],
    'line-width': ['coalesce', ['get', 'halo_width_px'], 3],
    'line-opacity': 0.9,
    'line-blur': 1.2
  }
});
```

Para senalar elementos internos, guarden esos puntos/lineas/poligonos en otra
tabla con una clave foranea al municipio o calculen la pertenencia con
`ST_Contains(admin.geom, element.geom)`.
