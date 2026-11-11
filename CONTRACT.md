# Data contract

This file is the agreement between everyone's code. **Do not change it without telling the team.** If every file in `data/out/` follows these rules, each person can build and test their part alone, using the fake data until the real data is ready.

## The grid

All layers use the same **local site grid**, measured in metres, not latitude and longitude.

- `x` is metres east of the south-west corner of the site. `y` is metres north of it.
- Default size: **400 x 400 cells, 5 m per cell**, so the site is 2000 m x 2000 m.
- **Images and rasters** have one pixel per cell. **Row 0 is the north edge** (the normal way images are stored).
- A cell at row `r`, column `c` has its centre at `x = (c + 0.5) * cell_m` and `y = (rows - r - 0.5) * cell_m`.
- **Vector files** (GeoJSON) store coordinates as `[x, y]` in metres. This is not real GeoJSON geography. The web app reads it as a flat map.
- In Leaflet with `CRS.Simple`, a point is `L.latLng(y, x)`. Note that **y comes first**.

If the real site needs a different size, change it in `layers.json` (`site.grid`). Nobody should hard-code 400 or 5.

## Files in `data/out/`

| File | Owner | What it is |
| --- | --- | --- |
| `layers.json` | Person 1 | The index of everything below. The web app is driven by this file. |
| `dem.tif` | Person 1 | Terrain height in metres, float32. |
| `relief.png` | Person 2 | Shaded relief image (base layer). |
| `slope.png` | Person 2 | Slope colour layer, with transparency. |
| `hazard.tif` | Person 2 | Hazard map, uint8: `0` green (fine), `1` yellow (careful), `2` red (do not enter). |
| `hazard.png` | Person 2 | The same hazard map as a coloured, see-through image. |
| `thermal.png` | Person 1 | Thermal layer (loose sand against bedrock). |
| `minerals.png` | Person 1 | Mineral map layer. |
| `weather.csv` | Person 1 | `sol,local_hour,temp_c,pressure_pa,dust_tau` |
| `radiation.csv` | Person 1 | `sol,local_hour,dose_rate_usv_h` |
| `waypoints.geojson` | Person 5 | The rover and the science stops. See below. |
| `route.geojson` | Person 3 | The planned walking route. See below. |
| `shelter_time.png` | Person 3 | Minutes back to the rover for every cell, as a coloured layer. |
| `plan.json` | Person 3 | The EVA timeline and the budgets. See below. |

## `layers.json`

```json
{
  "site": {
    "name": "Name of the site",
    "grid": { "width": 400, "height": 400, "cell_m": 5 },
    "extent_m": [2000, 2000]
  },
  "layers": [
    {
      "id": "hazard",
      "title": "Hazards",
      "file": "hazard.png",
      "source": "Mission and instrument, e.g. HiRISE (MRO)",
      "default": true,
      "opacity": 0.7
    }
  ],
  "vectors": { "route": "route.geojson", "waypoints": "waypoints.geojson" },
  "tables": { "weather": "weather.csv", "radiation": "radiation.csv" },
  "plan": "plan.json"
}
```

Layers are drawn in the order they appear, first at the bottom. Every layer needs a `source`.

## `waypoints.geojson`

A `FeatureCollection` of `Point` features. Properties: `id`, `name`, `kind` (`"rover"` or `"stop"`), `why` (one sentence on the science), `photo` (a file name in `mission/photos/`, or `null`).

## `route.geojson`

A `FeatureCollection` with one `LineString` feature: the whole walk, rover to stops and back. The coordinates are `[x, y]` in metres.

## `plan.json`

```json
{
  "crew": 2,
  "legs": [
    { "from": "rover", "to": "stop1", "distance_m": 780, "walk_min": 19 }
  ],
  "totals": { "walk_min": 89, "stop_min": 75, "total_min": 164 },
  "budgets": { "eva_max_min": 360, "radiation_limit_usv": 1000 },
  "radiation_dose_usv": 74
}
```

Times are in minutes, distances in metres, radiation in microsieverts (µSv).

## Rules

1. Keep file names and formats exactly as above.
2. Add fields freely, but never rename or remove one without telling everyone.
3. Fake data must keep working until the real data replaces it. Run `python data/make_fake.py` to rebuild it.
