# routing/ (Person 3: route planning and safety)

Plans the walk between the science stops and checks that it is safe: three routes (fastest, balanced, safest), a map of the minutes back to the start from every cell (a safety layer, not a route the user can pick), the EVA timeline with its budgets, and, as a safety figure, the fastest way back to the start from sampled points of the walk (the storm re-plan). It also exports reach grids, so the app can show the three one-way paths from a start the user picks (landing spot L1, L2 or L3) to any point the user clicks. No return-route option is built or exported.

The walker is an astronaut on foot. The walk starts from one of the **starts** listed in [config.toml](config.toml) as `[starts.<id>]`. For now there are three, landing spots L1 (1112.5, 607.5) m, L2 (1007.5, 367.5) m and L3 (1187.5, 1227.5) m, copied from the output of `web/src/lib/landing.js`. They are temporary: they change when the data does (the config records which `dem.tif` and `hazard.tif` they were computed on and warns when those change) and when the full Jezero dataset is loaded.

Everything is in metres on the local site grid (see [../CONTRACT.md](../CONTRACT.md)). The grid size and cell size are read from `data/out/layers.json`, so switching sites only means new data.

## Setup

- **Python 3.11 or 3.12.** Python 3.13 and later cannot install scikit-image yet.
- The packages in `requirements.txt`, plus three more that are not in that file yet:

```bash
python3 -m venv .venv
source .venv/bin/activate            # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install scikit-image scipy pytest
```

## Run it

From the repository root, in this order:

```bash
python data/make_fake.py             # rebuilds the fake data in data/out/
python routing/plan_route.py         # routes, back-to-start map and plan
python routing/export_reach.py       # reach grids for point-to-point routes, into data/out/reach/
python data/validate.py              # checks data/out/ against CONTRACT.md
```

`make_fake.py` overwrites `route.geojson`, `plan.json` and `shelter_time.png` with fake versions, so run `plan_route.py` after it every time. Once the real data is in `data/out/`, run `plan_route.py` and `export_reach.py` after any change to `dem.tif`, `hazard.tif`, `waypoints.geojson` or `routing/config.toml`.

### Options

| Option | Meaning | Default |
| --- | --- | --- |
| `--in DIR` | folder the inputs are read from | `data/out` |
| `--out DIR` | folder the outputs are written to | the `--in` folder |
| `--config FILE` | parameter file | `routing/config.toml` |

With `--in` and no `--out`, the outputs go into the `--in` folder, never into `data/out`, so a run on a test folder cannot overwrite the shared data by accident.

```bash
python routing/plan_route.py --in data/out --out scratch_out     # reads data/out, writes only into scratch_out (created if missing)
python routing/plan_route.py --config routing/config.toml        # the same parameter file as the default
```

The command prints the status, the start, the totals, the three profiles and any warning. A plan that goes over a budget is still written, with status `over_budget` and a warning, so the map stays usable. If the start or a stop is on a blocked cell, a stop cannot be reached, or an input is missing or malformed, the run stops with a message that names the problem, exits with a non-zero code and writes nothing.

## The starts

`[starts.L1]`, `[starts.L2]`, `[starts.L3]` in `config.toml` are the starts (each `value = [x, y]` in metres on the site grid); `start.default` (L1) says which one `plan_route.py` plans the full outing from. Add or remove `[starts.<id>]` tables freely: an id starts with a letter and uses letters, digits, `_` or `-`.

- `plan_route.py` plans from the **default** start only, so the plan, the minutes-back-to-start map and `plan.json` measure from it. `plan.json` `start.landing_id` records which one (`"L1"`); the start's `id` in legs and routes stays `start`.
- `export_reach.py` exports one set of grids for **every** start.
- Both scripts check **every** start first. **Error** (non-zero exit, nothing written), naming the start and the reason: outside the grid (or outside the exported area), no DEM data, red cell, slope over the limit (20 deg), inside the cliff buffer, or a sealed gap. For example `start 'L2' (1007.5, 367.5) m, cell (326, 201), is on a blocked cell: red hazard cell. Set starts.L2 in routing/config.toml to passable ground.`
- **Warning only** (in `plan.json` and `reach.json` `warnings`, naming the start): a start on yellow ground or on slope above 10 deg.
- **Warning only**: `waypoints.geojson` has a start waypoint more than half a cell from the default start. The config value is used, and the start's id in every output is `start`, whatever id the file uses.
- **Warning only**: `dem.tif` or `hazard.tif` is not the file the starts were computed on (`start.dem_sha256`, `start.hazard_sha256`). Rerun `web/src/lib/landing.js`, put its three spots in `[starts.*]` and the new hashes in the config.

In `waypoints.geojson`, the start waypoint's `kind` is now `start`, and the old `rover` is still accepted and read as `start`, with a deprecation warning. The shared file keeps `rover` for now, because `data/validate.py` (the contract check) still accepts only `rover` and `stop`.

## Reach export (point-to-point routes)

```bash
python routing/export_reach.py                       # reads data/out, writes data/out/reach/
python routing/export_reach.py --in DIR              # reads DIR, writes DIR/reach/
python routing/export_reach.py --in DIR --out DIR2   # reads DIR, writes DIR2
python routing/export_reach.py --config FILE         # another parameter file
```

One search per profile and start gives the best path from that start to every cell. The output is one folder per start, named by its id, and one manifest beside them:

```
data/out/reach/
  reach.json                 the manifest: the starts, the grid, encodings, profile weights, budget rule, hashes
  L1/ L2/ L3/                one folder per start, each with:
      {fastest,balanced,safest}_time.f32   walking minutes from the start along that profile's path (float32, NaN where unreachable)
      {fastest,balanced,safest}_dist.f32   metres along that path
      {fastest,balanced,safest}_risk.f32   risk-minutes along that path
      {fastest,balanced,safest}_dir.u8     the step back toward the start, codes 0-8 (0 = the start or no path)
      reason.u8                            0 reachable; otherwise why not: 1 no data, 2 red, 3 slope, 4 buffer, 5 sealed, 6 walled off
```

`reach.json` lists the starts (`starts[]`: `id`, `xy_m`, `cell`, `default`, `warnings` and the file paths), so **the front end reads the landing spots from it** instead of computing them. Reason 6 (walled off) depends on the start, so every start has its own `reason.u8`; today all three starts reach the same cells, so it is the same for all three.

All grids are little-endian, row 0 = north, `width x height` values, no header. On the 400 x 400 site each start is 6.4 MB (each `.f32` file 640,000 bytes, each `.u8` file 160,000 bytes), so the three starts are **19.21 MB** with the manifest. `reach.crop_m` (a box in metres, or `"full"`) and `reach.downsample` (whole cells per export cell) in `config.toml` shrink it.

After writing, the export deletes the 13 grid files of the old one-start layout and the grid files of any start folder that is no longer in the config, and lists them. Other files are left alone.

The user gets one-way paths only, from the start to the destination. A destination is over budget when `time + ingress_min + stop_min > usable_min`, i.e. when its walking time is above `budget.walk_limit_min` in the manifest (212 min with the current values: 252 - 15 - 25). No return walk is counted. `reach.destination_stop = false` leaves the stop out.

`export_reach.trace(folder, start_id, profile, x, y)` is the reference traceback the app copies: it returns the path as a GeoJSON `LineString` from that start, with `distance_m`, `walk_min`, `risk_min`, `needed_min`, `over_budget` and the cells. The algorithm is written out step by step in [docs/DESIGN.md](docs/DESIGN.md) section 13.

```python
import sys; sys.path.insert(0, "routing")
import export_reach
export_reach.trace("data/out/reach", "L2", "safest", 500.0, 1500.0)
```

## Sweep and sensitivity

```bash
python routing/analysis.py                                   # reads data/out, writes routing/reports/
python routing/analysis.py --in DIR --config FILE --reports DIR
```

Writes two CSV files into `--reports` (default `routing/reports`) and nothing else; it has no `--out` and never writes to `data/out`.

- `sweep.csv`: the time against risk-exposure table. One row per weight in `profiles.sweep_w`: distance, walk minutes, and risk minutes split into `yellow_min`, `steep_min` and `near_red_min`. The same rows are in `plan.json` under `sweep`.
- `sensitivity.csv`: every combination of the walking speed, the slope limit and w from the `[sensitivity]` section of `config.toml` (18 runs). Each row has the walk, total and risk minutes and the budget `status` (`ok` or `over_budget`), or `infeasible` with the `failed_stop` (the start or stop that is on a blocked cell or cannot be reached) and the `reason`.

## Inputs

Read from the `--in` folder: `layers.json` (grid size, site name, whether layers are fake), `dem.tif`, `hazard.tif`, `waypoints.geojson` (at least one `stop`, and at most one `start`, which is optional) and `radiation.csv`. `dem.tif` and `hazard.tif` must have the pixel size in `layers.json`, be north-up and share one geotransform.

## Outputs

Written to the `--out` folder (default `data/out`):

| File | What it is |
| --- | --- |
| `route.geojson` | the balanced route, start to stops and back (contract file) |
| `route_fastest.geojson` | the fastest route, same format |
| `route_safest.geojson` | the safest route, same format |
| `shelter_time.png` | minutes back to the start for every cell, with contour lines (contract file) |
| `plan.json` | the EVA timeline, budgets and the extra data below (contract file) |

The three routes share one stop order and differ only in how much extra time they accept to avoid yellow cells and the edge of red ones.

## plan.json

The contract fields keep their names: `crew`, `legs`, `totals`, `budgets`, `radiation_dose_usv`. Times are minutes, distances metres, radiation microsieverts. Contract values are whole numbers; added values use one decimal.

**`totals.total_min` now includes ingress** (walk + stops + ingress), and `totals.ingress_min` is added so the parts still sum. The fake `plan.json` did not include ingress.

Added fields:

- `status` (`ok` or `over_budget`) and `checks`: the reserve (`total_min` against the usable time), the abort check (elapsed time plus the way back, against the hard EVA limit) and the radiation limit, each with its value, limit and a message.
- `legs[]`: also `risk_min`, `ascent_m`, `descent_m`, `max_slope_deg`, `depart_min`, `arrive_min`, `stop_min`.
- `budgets`: also `reserve_pct` and `usable_min`.
- `stop_order`: the `mode` used, the mode `requested`, the stop `order` and `warnings` (optimising falls back to the file order above `timeline.optimise_max_stops` stops).
- `profiles`: `fastest`, `balanced`, `safest`, each with its risk weight `w`, output `file`, `distance_m`, `walk_min`, `risk_min` (split into `yellow_min`, `steep_min`, `near_red_min`), `total_min` and `status`.
- `sweep[]`: the w-sweep table (see above), one row per weight.
- `track[]`: the balanced route sampled every `track.spacing_m` and at each stop, for the slope profile and the timeline: `distance_m`, `x`, `y`, `elev_m`, `slope_deg`, `hazard`, `elapsed_min` (clock time, including time at stops already visited) and `shelter_min` (minutes back to the start, ingress included). Stop arrivals also carry `stop`.
- `storm_replan`: the fastest way back from points of the route. `points[]` have `x`, `y`, `route_distance_m`, `elapsed_min`, `return_min`, `return_distance_m` and `path` (a list of `[x, y]` ending at the start); `worst` is the index of the point with the longest way back.
- `start`: the start actually used: `id` (always `start`), `name`, `landing_id` (the default start, for example `L1`), `xy_m`, `cell`, `source`.
- `shelter_map`: the legend for `shelter_time.png` (`label` "Minutes back to start", the colour stops, `colour_max_min`, `contour_interval_min`, `includes_ingress`), because the app cannot read minutes back out of a picture. The exact value at each point of the walk is in `track[].shelter_min`.
- `radiation`: the background rate, the median and storm hours found in `radiation.csv`, and `solar_event`. The solar-event dose stays in milligray and is never added to `radiation_dose_usv`.
- `assumptions`: every parameter from `routing/config.toml`, with its value, unit, type and source.
- `inputs`: the site name, the grid, and `inputs_fake` (true while any layer in `layers.json` says FAKE).
- `warnings`: anything worth a look, such as a `radiation.csv` that disagrees with the background rate.

The same inputs always give the same file: there is no timestamp. `plan.json` is about 120 kB for the fake site.

## Parameters

Every number the model uses is in [config.toml](config.toml), each with a `value`, a `unit`, a `type` (`observation`, `proxy` or `scenario`) and a `source`. The loader rejects a missing or misspelt parameter, a value out of range, and a walking speed above the walk-run limit for Mars gravity. Do not relax the slope limits because gravity is low: traction drops with it too.

## Tests

```bash
python -m pytest routing/tests
```

Most tests use small synthetic grids; each one gets a copy of `config.toml` with its starts (and the hashes of its own `dem.tif` and `hazard.tif`) on its own points (`config_for` in `tests/conftest.py`). `test_end_to_end.py` reads the real `data/out/`, so run `plan_route.py` first.

## More

- [docs/DESIGN.md](docs/DESIGN.md): what the planner does and why, and the assumptions still to confirm.
- [docs/CHECKLIST.md](docs/CHECKLIST.md): the build order and what is done.
