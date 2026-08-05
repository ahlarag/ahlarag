/*
  Nueva Esparta municipalities from OpenStreetMap.

  Use in https://overpass-turbo.eu/ to inspect the source relations.
  Export as GeoJSON from Overpass Turbo if you only need a quick manual export.
*/
[out:json][timeout:180];
relation(2269770)->.state;
rel(r.state)["boundary"="administrative"]["admin_level"="6"];
out tags bb;
>;
out skel qt;
