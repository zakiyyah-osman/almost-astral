# Interplanetary Survival Guide: Martial Map — Person 2

**Base map, shared coordinates, terrain and hazards.**

This package covers both Person 2 jobs:

* **Base map and coordinates.** The SVG map with imagery, north arrow and scale bar; the one shared function that converts map coordinates to screen positions; and, once the dataset arrives, the real imagery plus the projection, origin and bounds for the whole team, with a check that landmarks line up across layers.
* **Terrain and hazards.** Slope, roughness and a green/yellow/red hazard map built from the terrain model, rocks and thermal inertia, plus a check that real rover tracks fall on passable ground.

Today everything runs on **stand-in data**, and the map shows a *Simulated data* banner. Tomorrow you switch to the NASA dataset by pointing the same commands at `data/layers.json`.

```bash
python3 tools/make_mock_data.py --out data_mock     # stand-in site (only needed before the real data)
./run_all.sh data_mock/layers.json out             # hazards -> alignment -> base map
# open out/martial_map.html  (a single file that works offline and on a tablet)
python3 -m pytest -q                               # 26 tests (Python + the JS coordinate tests via node)
```

Needs numpy, scipy, scikit-image, matplotlib, Pillow, PyYAML and tifffile. Node is used only to run the JS tests. rasterio is optional.

---

## 1. The shared coordinate contract (agree on this first)

| | |
|---|---|
| Map coordinates | `[east, north]` in **metres** from the **SW corner** of the site grid |
| Raster rows | row 0 = **north** edge, col 0 = west edge; one cell = `cell_m` |
| Bounds | E 0 → `width_m`, N 0 → `height_m` |
| Leaflet `CRS.Simple` | bounds `[[0, 0], [height_m, width_m]]` (Leaflet uses [north, east] order) |
| Source projection | `site.source_crs` + `site.origin_source_xy` (the SW corner in the product's projected metres) |
| Lat/lon | `site.origin_latlon` (the SW corner); `MarsCoords.enToLatLon` / `latLonToEN` convert |

All of this is published in **`out/map_config.json`**. Teammates read that file and don't hard-code anything.

### `basemap/web/coords.js`: the one conversion function everyone uses

```js
const v = MarsCoords.fit(site, width, height);   // view {cx, cy, s, w, h}
MarsCoords.toScreen(v, [east, north])  -> [x, y] px
MarsCoords.toMap(v, [x, y])            -> [east, north] m
MarsCoords.latLonToEN(site, [lat, lon]) // e.g. place a Curiosity stop from its lat/lon
MarsCoords.niceScaleBar(v), zoomAt, pan, toCell, svgTransform ...
```

The functions are pure and have no dependencies. The same file works in the browser (`window.MarsCoords`) and in Node (`require`).

### Adding your layer to the base map (Persons 3–5)

```js
martialMap.addOverlay("routes", (g, view, C, el) => {
  const d = route.map((en, i) => (i ? "L" : "M") + C.toScreen(view, en).join(",")).join("");
  el("path", { d, class: "my-route" }, g);
});
```

Overlays are redrawn in screen pixels on every pan and zoom, so symbols stay the same size. `martialMap.setLayerVisible(id, on)`, `setLayerOpacity`, `flyTo([e, n])` and `fit()` are also available.

---

## 2. What's in `out/`

| file | for | what |
|---|---|---|
| `martial_map.html` | everyone, demo | the whole viewer in **one file** (imagery inlined) |
| `index.html`, `*.js`, `viewer.css` | Person 1 (interface) | the same viewer, unbundled; serve it with `python3 -m http.server` |
| `map_config.json` | everyone | projection, origin, bounds and the layer list with legends and sources |
| `imagery.png` | Person 1, 4 | base imagery on the grid (orbital image, or the shaded-relief placeholder) |
| `hazard.tif`, `slope.tif`, `roughness.tif` | Person 3 (routes) | classes 0 go / 1 caution / 2 no-go / 3 unknown; slope in degrees; roughness in metres |
| `reasons.tif` | Persons 4, 5 | bitmask of *why* each cell is caution or no-go (for "No-go: cliff edge" messages) |
| `hazards.png`, `slope.png`, `thermal.png`, `minerals.png`, `shaded_relief.png` | the map | RGBA overlays, one pixel per cell |
| `hazards_manifest.json` | | thresholds used, legend items and the share of the area in each class |
| `track_check.json` / `.png` | the team | rover tracks compared with the hazard classes |
| `alignment_report.json`, `landmark_chips.png` | the team | measured offset of each layer, and close-ups of each landmark in every layer |

### What the base map shows

* Imagery, with layers above it: slope, thermal inertia, minerals and hazards (each with an opacity slider and legend), an optional coordinate grid, rover tracks, and landmarks.
* A **north arrow**. The grid is north-aligned, so north is up.
* A **scale bar** that picks a 1, 2 or 5 length to suit the zoom and shows the ground size of one pixel.
* A **cursor readout**: E/N metres, lat/lon, grid cell, and the hazard or mineral class under the cursor.
* Drag, wheel or pinch to zoom; arrow keys and +/−/0; zoom buttons sized for a tablet.
* Hazard **unknown** areas (coverage gaps) appear as **grey stripes**, so a gap is never mistaken for terrain.

---

## 3. Tomorrow: when the NASA dataset arrives (budget about 3 hours)

**Step 1. Inventory (30 min, with Person 1).** For each file, note the projection, cell size, extent, and nodata value. On PDS products this is usually in the `.lbl`/`.xml` label or the GeoTIFF tags.

**Step 2. Define the site and share it (20 min). This unblocks everyone.**
Choose the site centre in the imagery's projected metres, then run:
```bash
python3 -m basemap.imagery define-site --layers data/layers.json \
    --center-xy <X> <Y> --size 1000 1000 --cell 1 \
    --clon <projection centre lon> --lat-ts <latitude of true scale> \
    --crs "<projection name from the label>" --name "Gale – Mount Sharp boxwork"
```
This writes `width/height/cell`, `origin_source_xy` and `origin_latlon` into `layers.json`. Post those values in the team chat straight away.
**Cell size:** if the terrain model is 1 m (HiRISE DTM), use 1 m. If it's coarser, use its own size; don't resample finer.

**Step 3. Put the imagery and terrain on the grid (30 min).**
```bash
python3 -m basemap.imagery resample <ortho.tif> --layers data/layers.json --out data/ortho.tif --id ortho --source "<product id, PDS>"
python3 -m basemap.imagery resample <dtm.tif>   --layers data/layers.json --out data/dtm.tif   --id dtm --units m --nodata <value>
```
Georeferencing is read from a world file or the GeoTIFF tags. If a product uses a different projection from the site, reproject it first with `gdalwarp -t_srs <site projection>`, or ask Person 1's converter to do it. The script reports coverage, and any part of the site with no data becomes "unknown terrain coverage".

**Step 4. Run everything (5 min):** `./run_all.sh data/layers.json out`

**Step 5. Check that landmarks line up (30 min).**
* Add 4–8 landmarks to `data/landmarks.geojson`: crater centres, a sharp ridge corner, Curiosity drill sites. Convert lat/lon with `MarsCoords.latLonToEN`.
* `alignment_report.json` gives the offset between the orbital image and the terrain in metres, plus the shift to apply. More than 1.5 cells means something is wrong. Usual causes are a pixel-corner vs pixel-centre mix-up (half a cell), the wrong product, or the wrong projection centre.
* Open `landmark_chips.png`. Every feature should sit on the crosshair in every column. Coarse layers (THEMIS about 100 m, CRISM about 18 m) can only be checked by eye.
* In the viewer, toggle each layer over a landmark and confirm nothing jumps.

**Step 6. Hazards on the real terrain (30 min).** Open `track_check.png` with Curiosity's real tracks loaded (`--tracks`):
* If the track is red along its whole length, or offset from the visible rover path, the grid is misaligned. Go back to step 5.
* If it's red only in short stretches, check the reason. If it's `slope_nogo` or `rough_nogo`, adjust `config/hazards.yaml`: smoothed models under-report slope, noisy ones over-report roughness.
* If more than about 30% of the site is red, something is probably wrong.

**Step 7. Hand off (10 min).** Commit `out/`. Tell Person 3 to rerun routes on the new `hazard.tif`, and Person 1 to reload `map_config.json`. The *Simulated data* banner turns off by itself once nothing in `layers.json` is marked SIMULATED.

---

## 4. How a cell is classed (`config/hazards.yaml`)

| class | rule (default thresholds; all assumptions for a suited, walking astronaut) |
|---|---|
| Go | none of the conditions below |
| Caution | slope ≥ 15°, roughness ≥ 0.15 m, thermal inertia < 200 TIU (loose sand), ≥ 0.05 rocks/m² |
| No-go | slope ≥ 25°, roughness ≥ 0.40 m, thermal inertia < 100 TIU, ≥ 0.15 rocks/m², a rock ≥ 1 m wide (+1 m clearance), a cliff edge (> 2 m drop within 3 m), **plus a 2 m buffer** |
| Unknown | no terrain data. Never treated as safe |

Roughness is the scatter of heights in a 5 × 5 m window after the local slope is removed, so a smooth steep slope isn't counted as rough.

---

## 5. Tested

* **26 tests.** They cover: slope maths; class thresholds; cliffs, sand and rocks; coverage gaps; the rover-track check; the JS coordinate conversions (screen ↔ map round trips, zoom about the cursor, scale-bar lengths, lat/lon); world-file and GeoTIFF georeferencing; and the build.
* **Dataset-day rehearsal.** A fake orbital image of the site, lit from a different sun, was put on the grid with a correct world file and measured **0.00 m** off. With a world file deliberately wrong by 3 m E and 2 m N, the tool measured **3.00 m E and 2.00 m N** and told us to move the layer back.
* **Viewer.** Rendered in Chrome at desktop and tablet sizes with no console errors. The cursor readout matched the expected cell and class.

The offset check estimates the image's sun direction from the terrain itself. Comparing against plain shaded relief lit from a different sun biased the result by about 1 m.

## About the stand-in data

`tools/make_mock_data.py` builds a 1 km site. It has: fractal terrain with craters; a boxwork ridge network; a 6 m cliff with a ramp; a coverage gap; a sand sheet with low thermal inertia; a blocky rock field; mineral zones; 7 landmarks; a simulated rover drive (should **PASS**); and a deliberately bad line (should **FAIL**).

`run_all.sh` therefore reports a failed track on the stand-in data. That's on purpose, and it proves the check works.

One change from the team plan's fake-terrain code: bumps are weighted by `s**2`, not `s`. With `s`, almost every 1 m cell is steeper than 25°.
