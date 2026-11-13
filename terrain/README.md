# Interplanetary Survival Guide: Martial Map — Person 2 (`terrain/`)

**Base map, shared coordinates, terrain and hazards. Works with the team's `layers.json` format.**

```bash
python3 tools/make_mock_data.py --out data_mock     # stand-in Jezero-style site (2000 m, 5 m cells, team format)
./run_all.sh data_mock/layers.json out             # hazards -> alignment -> base map
python3 -m pytest -q                               # 30 tests, including the team-contract checks
xdg-open out/martial_map.html
```

To run on the team's data, point it at the team's `layers.json`:

```bash
./run_all.sh ../path/to/team/layers.json out
```

Needs numpy, scipy, scikit-image, matplotlib, Pillow, PyYAML and tifffile (plus pytest for the tests). Node is used only for the JS tests.

---

## The team contract (what this code reads and writes)

### Reads

| what | where |
|---|---|
| Grid | `site.grid {width, height, cell_m}` and `site.extent_m [w, h]`. The run stops if the two disagree |
| Location | `site.center_lat`, `site.center_lon_east`. The SW corner is computed from these |
| Terrain model | `dem.tif` next to `layers.json`. HiRISE nodata (−3.4e38) counts as no data |
| Thermal inertia | `thermal_inertia.tif` next to `layers.json`, where NaN = no data. Optional |
| Vectors | `vectors.route` (checked against hazards); optional `vectors.rocks`, `vectors.rover_tracks`, `vectors.landmarks`. `vectors.waypoints` appears on the map as science stops |
| Display layers | `layers[]` in the team's order, with `default` (visible), `opacity` and `legend`. Used by the base map |

### Writes (to `--out`)

| file | contract |
|---|---|
| `hazard.tif` | uint8, **only 0 / 1 / 2** (go / caution / no-go). **Cells with no terrain data are 2**, so a route can never cross ground we know nothing about |
| `hazard.png` | RGBA: no-go **(220,50,50)**, caution **(240,190,40)**, go **transparent**, so the HiRISE image shows through |
| `coverage.tif` / `coverage.png` | 1 = terrain data, 0 = none. The PNG shows grey stripes labelled *Unknown terrain coverage* |
| `relief.png`, `slope.png` | replace the FAKE relief and slope layers |
| `slope.tif`, `roughness.tif`, `reasons.tif` | for routing (Person 3) and "why is this no-go" messages |
| `track_check.json/.png` | rover tracks: PASS/FAIL. The **route**: PASS, FAIL, or *Unknown terrain coverage* if it enters a gap |
| `map_config.json`, `martial_map.html`, `index.html` + JS | the base map (see below) |

`run_all.sh` writes to `out/` and **does not touch the team's data folder**. To publish, copy `hazard.png`, `hazard.tif`, `relief.png`, `slope.png`, `coverage.png` and `coverage.tif` into it, or run `python3 -m hazards.run --layers <team>/layers.json --out <team folder>`. Either way, the FAKE relief, slope and hazard PNGs get replaced.

### Coordinates (shared with everyone)

* `[east, north]` in metres from the **SW corner**; row 0 = north edge; cell centre = `((col+0.5)·cell, H−(row+0.5)·cell)`.
* Leaflet `CRS.Simple` bounds: `[[0, 0], [height_m, width_m]]`.
* `basemap/web/coords.js` (`MarsCoords`) is the one conversion everyone uses: `toScreen`, `toMap`, `enToLatLon`, `latLonToEN`, `niceScaleBar`, …

---

## How a cell is classed (`config/hazards.yaml`)

| class | rule (default thresholds; all assumptions for a suited, walking astronaut) |
|---|---|
| 0 Go | none of the conditions below |
| 1 Caution | slope ≥ 15°, roughness ≥ 0.15 m, thermal inertia < 200 (loose sand), ≥ 0.05 rocks/m² |
| 2 No-go | slope ≥ 25°, roughness ≥ 0.40 m, thermal inertia < 100, ≥ 0.15 rocks/m², rock ≥ 1 m (+1 m clearance), cliff edge, a safety buffer around every no-go area, **and every cell with no terrain data** |

The rules adapt to coarse grids. On 5 m cells the cliff test uses a 15 m window with the drop scaled to keep the same steepness. The safety buffer is never smaller than one cell; otherwise a 2 m buffer would vanish on a 5 m grid.

---

## The base map

`out/martial_map.html` is a single file that works offline and on a tablet. It shows:

* the team's display layers in the order of `layers.json`, with on/off switches, opacity, legends and sources;
* coverage gaps as grey stripes;
* the planned route (dashed), rover tracks, science stops (waypoints), landmarks, and an optional coordinate grid;
* a north arrow, a scale bar that adjusts to the zoom, and zoom buttons sized for a tablet;
* a cursor readout: E/N metres, lat/lon, grid cell, and the hazard class under the cursor;
* a *Simulated data* banner whenever any layer is marked FAKE or SIMULATED.

Teammates can draw their own layers on top with `martialMap.addOverlay(id, (g, view, C, el) => …)`.

---

## Dataset day (about 3 hours)

1. **Inventory (with the data person).** For each product, note its projection, cell size, extent and nodata value. Check the `.lbl`/`.xml` label or the GeoTIFF tags.
2. **Pin the grid to the real projection.** This keeps the team's grid and centre and adds `source_crs` and `origin_source_xy`:
   ```bash
   python3 -m basemap.imagery define-site --layers <team>/layers.json --clon 0 --lat-ts 0 \
       --crs "Mars equirectangular, lat_ts 0, lon_0 0 (from the product label)"
   ```
   The Jezero HiRISE mosaics are `Eqc_latTs0_lon0`, so `--clon 0 --lat-ts 0`. Post the printed values to the team.
3. **Put the products on the grid:**
   ```bash
   python3 -m basemap.imagery resample <HiRISE DTM>.tif --layers <team>/layers.json --out <team>/dem.tif \
       --nodata -3.4028227e+38 --source "HiRISE DTM, USGS Mars 2020 TRN"
   python3 -m basemap.imagery resample <HiRISE 25 cm>.tif --layers <team>/layers.json --out <team>/hirise.png \
       --id hirise --title "HiRISE image" --source "HiRISE (MRO) ..."
   ```
   Products finer than the grid (25 cm → 5 m) are averaged down first. **The full 25 cm mosaic is many GB.** Crop it to the site first: `gdal_translate -projwin <x0> <y1> <x1> <y0>`, using `origin_source_xy` plus the extent.
4. **Run:** `./run_all.sh <team>/layers.json out`
5. **Check alignment:** `alignment_report.json` gives the HiRISE-vs-terrain offset in metres and the shift to apply; anything over 1.5 cells (7.5 m) is wrong. `landmark_chips.png` shows each landmark and waypoint in every layer: features should sit on the crosshair.
6. **Check hazards:** with real rover tracks (`--tracks`), a track red all along = misalignment; short red stretches = thresholds to tune in `config/hazards.yaml`. If the route shows *Unknown terrain coverage*, tell Person 3/5.
7. **Publish** the hazard, relief, slope and coverage files into the team folder (see above), commit, and tell the team.

---

## Tested

* **30 tests.** These include checks that `hazard.tif` holds only 0, 1 and 2; that `hazard.png` uses exactly the three contract colours and agrees with `hazard.tif` cell for cell; that no-data cells are 2; that the route through the gap is reported as *Unknown terrain coverage*; that the team's `layers.json` (saved in `tests/fixtures/`) parses correctly; the 5 m cliff and buffer rules; and the JS coordinate maths.
* **Alignment on 5 m cells.** A fake orbital image placed correctly measures under 2.5 m off; a 15 m E / 10 m N error is measured to within 1.5 m. A 1.25 m product averaged down to 5 m lands under 1 m off.
* **Viewer.** Rendered in Chrome with no console errors.

## About the stand-in data

`tools/make_mock_data.py` builds a FAKE Jezero-style site in the team format: 2000 m at 5 m cells, centred at 18.46°N 77.4°E. It contains: fractal terrain with craters; a ridge network; a 25 m delta-front scarp with a ramp; a coverage gap; a sand sheet; a rock field; landmarks; a rover drive (should **PASS**); a deliberately bad line (should **FAIL**); and a route through the gap (should report **Unknown terrain coverage**). Because of the last two, `run_all.sh` ends with "check FAILED" on this data, on purpose.
