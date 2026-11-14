# routing/ (Person 3: route planning and safety)

Plans the walk between the science stops and checks that it is safe: three routes (fastest, balanced, safest), a map of the minutes back to the start from every cell (a safety layer, not a route the user can pick), the EVA timeline with its budgets, and, as a safety figure, the fastest way back to the start from sampled points of the walk (the storm re-plan). It also judges where a lander can come down safely and exports the cost surface, so the app can let the user click any landing zone (moved to the nearest safe spot if needed), click a destination and get the three one-way walking paths. No return-route option is built or exported.

The walker is an astronaut on foot. There are no fixed starts: the app's start is the landing spot the user picks, and the full outing starts at `--start x,y` or at the demo start (below).

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
python routing/plan_route.py         # routes, back-to-start map and plan (demo start; or --start x,y)
python routing/export_landing.py     # landing safety and the cost surface, into data/out/landing/
python data/validate.py              # checks data/out/ against CONTRACT.md
```

`make_fake.py` overwrites `route.geojson`, `plan.json` and `shelter_time.png` with fake versions, so run `plan_route.py` after it every time. Once the real data is in `data/out/`, run `plan_route.py` and `export_landing.py` after any change to `dem.tif`, `hazard.tif`, `waypoints.geojson` or `routing/config.toml`.

### Options

| Option | Meaning | Default |
| --- | --- | --- |
| `--in DIR` | folder the inputs are read from | `data/out` |
| `--out DIR` | folder the outputs are written to | the `--in` folder |
| `--config FILE` | parameter file | `routing/config.toml` |
| `--start X,Y` | start of the walk in metres on the site grid (`plan_route.py`, `analysis.py`) | the demo start |

With `--in` and no `--out`, the outputs go into the `--in` folder, never into `data/out`, so a run on a test folder cannot overwrite the shared data by accident.

```bash
python routing/plan_route.py --in data/out --out scratch_out     # reads data/out, writes only into scratch_out (created if missing)
python routing/plan_route.py --config routing/config.toml        # the same parameter file as the default
```

The command prints the status, the start, the totals, the three profiles and any warning. A plan that goes over a budget is still written, with status `over_budget` and a warning, so the map stays usable. If the start is outside the grid, the start or a stop is on a blocked cell, a stop cannot be reached, or an input is missing or malformed, the run stops with a message that names the problem, exits with a non-zero code and writes nothing.

## The start

There are no fixed starts and no landing-spot coordinates anywhere in `routing/`. In the app, the user clicks a landing zone and the browser uses the landing export below. For the full outing, `plan_route.py` and `analysis.py` take the start on the command line:

```bash
python routing/plan_route.py --start 1017.5,1112.5   # x,y in metres on the site grid
python routing/plan_route.py                         # no --start: the demo start
```

- With no `--start`, the walk starts at the **demo start**: the centre of the safe landing cell nearest the grid centre. `plan.json` `start` says `"kind": "demo"`, `"name": "Demo start"`, and the command line prints `demo start at (x, y) m`.
- `plan.json` `start` keeps its keys (`id` is always `start`; `landing_id` is now always `null`) and adds `kind` (`cli` or `demo`), `landing_status` (the landing-safety code name of the start cell) and a `source` that says which of the two it was.
- **Error** (non-zero exit, nothing written): the start is outside the grid or on a blocked cell (no DEM data, red, slope over 20°, cliff buffer, sealed gap).
- **Warning only**: a start on yellow ground or on slope above 10°, or a `--start` point that is not a safe or marginal landing spot.
- A waypoint of kind `start` (or the old `rover`, still read with a deprecation warning) is **never** used as the start; a warning says it is ignored.
- The stops in `waypoints.geojson` are unverified, so `plan.json` always carries a warning that the outing plan is a demonstration.

## Landing export (landing safety and the browser's cost surface)

```bash
python routing/export_landing.py                       # reads data/out, writes data/out/landing/
python routing/export_landing.py --in DIR --out DIR2 --config FILE
```

**Landing safety.** For every cell, a lander pad of radius `landing.pad_radius_m` (25 m) centred there is judged on the real layers only. Codes in `landing_safety.u8`; when several failures apply the lowest code wins:

| Code | Name | The pad ... |
| --- | --- | --- |
| 0 | safe | passes every rule |
| 1 | marginal | passes, but within 20% (`landing.marginal_pct`) of a limit |
| 2 | outside_coverage | or its 30 m clearance circle does not fit inside the data |
| 3 | no_data | has a cell with no DEM or slope value |
| 4 | hazard_or_clearance | has a non-green or unwalkable cell, or a red / over-limit-slope / cliff-buffer cell lies within 30 m (`landing.hazard_clearance_m`) |
| 5 | too_steep | best-fit plane tilts more than 5° (`landing.max_pad_slope_deg`) |
| 6 | height_range | more than 1.0 m from lowest to highest once the tilt is removed (`landing.max_height_range_m`) |
| 7 | too_rough | more than 0.25 m RMS about that plane (`landing.max_roughness_m`) |

Every limit is in metres or degrees and is a **team assumption pending Nahla** (type `assumption` in `config.toml`). Roughness is computed from `dem.tif`, because `layers.json` lists no roughness layer. Its scale differs from terrain's (RMS about the local mean in a 25 m window, `terrain/thresholds.toml`), so the two numbers are not directly comparable. The 1.0 m height range is a team assumption, not a sourced lander clearance. THEMIS thermal inertia only sets a warning bit (`landing_warn.u8`: 1 = below `landing.ti_warn_below` on the pad, 2 = no value), and only while `layers.json` marks the thermal layer as real.

**Nearest safe cell.** `nearest_safe.u16` holds, for every cell, the row and column (window rows/cols) of the nearest safe cell; `nearest_safe_dist.f32` the distance in metres. A click on a safe or marginal cell stays; any other click moves to the centre of that cell (straight line: a lander comes down from above).

**Measured values.** Four more float32 grids hold the numbers behind the codes, exactly as `landing.py` checks them: `pad_slope_deg.f32` (tilt of the pad's best-fit plane), `pad_roughness_m.f32`, `pad_height_range_m.f32` (after removing the plane) and `hazard_dist_m.f32` (from the cell centre to the nearest red, over-limit-slope or cliff-buffer cell). The first three are NaN where the pad was not computed (codes 2 and 3). `hazard_dist_m` is never NaN; it is +Infinity when the site has no such cell at all (the front end reads `Infinity` and shows no distance). The manifest gives each grid's unit, its `[landing]` limit and `fails_when`.

**Zones image.** `landing_zones.png` is one RGBA image for the whole window, the same size and placement as `hazard.png` on the current site: safe cells semi-transparent green, marginal cells semi-transparent amber, everything else fully transparent. The colours are `landing.display_safe_rgba` and `landing.display_marginal_rgba` in `config.toml`; the manifest's `zones_png` has the legend.

**Messages.** `landing_check` also returns `measured` and `chosen_measured` (the four values at the clicked and at the chosen cell), `messages` (one `{reason, code, title, detail, moved_m}` per reason, with the number and the limit in the text) and `moved_text`. The wording lives once in `landing.MESSAGE_TEMPLATES` and is copied to the manifest as `message_templates`, with the rules for filling it, so the front end shows the same text (DESIGN section 14.5).

**Cost surface.** `time_rate.f64`, `risk_rate.f64` and `mask.u8` are exactly what `cost.build` makes (float64, so the browser's numbers are the same bits). They do not depend on the profile: the browser computes `time_rate × (1 + w × risk_rate)` for w = 0, 1, 5. The exact search rule is DESIGN section 15; `golden_cases.json` holds 10 landing/destination pairs × 3 profiles (one unreachable, one over budget under its own smaller test budget) to test against.

**Files** (all little-endian, row 0 = north, no header):

```
data/out/landing/
  manifest.json          grid, window, tiles, dtypes, code tables, thresholds, message templates, budget rule, edge rule, hashes
  golden_cases.json      reference paths and totals
  landing_zones.png      safe (green) and marginal (amber) cells of the whole window, RGBA
  tiles/<ti>_<tj>/       landing_safety.u8  landing_warn.u8  nearest_safe.u16  nearest_safe_dist.f32
                         time_rate.f64  risk_rate.f64  mask.u8
                         pad_slope_deg.f32  pad_roughness_m.f32  pad_height_range_m.f32  hazard_dist_m.f32
```

On the 400 x 400 site this is one tile, **7,095,045 bytes (7.10 MB) in 14 files**. For a bigger grid, `landing.window_centre_m` / `landing.window_size_m` choose a window and `landing.tile_size_m` (5120 m, 1024 cells at 5 m) cuts it into tiles; the manifest lists each tile's index, origin, shape and files. The safety codes are computed on the whole site grid and `nearest_safe` on the whole window before tiling, so both are right across tile edges. Paths never leave the window. Crater-scale processing itself is not built yet; only the formats and functions are ready for it.

The user gets one-way paths only. A destination is over budget when `walk_min + ingress_min + stop_min > usable_min`, i.e. when its walking time is above `budget.walk_limit_min` in the manifest (212 min: 252 - 15 - 25). `budget.destination_stop = false` leaves the stop out.

Reference functions, which the app must reproduce:

```python
import sys; sys.path.insert(0, "routing")
import export_landing
export_landing.landing_check(1000.0, 1000.0)                        # {status, reasons, chosen_xy_m, moved_m, measured, messages, ...}
export_landing.route((1017.5, 1112.5), (1500.0, 1300.0), "safest")  # a GeoJSON Feature
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
- `start`: the start actually used: `id` (always `start`), `name` ("Start" or "Demo start"), `landing_id` (always `null` now), `xy_m`, `cell`, `source`, `kind` (`cli` or `demo`) and `landing_status`.
- `shelter_map`: the legend for `shelter_time.png` (`label` "Minutes back to start", the colour stops, `colour_max_min`, `contour_interval_min`, `includes_ingress`), because the app cannot read minutes back out of a picture. The exact value at each point of the walk is in `track[].shelter_min`.
- `radiation`: the background rate, the median and storm hours found in `radiation.csv`, and `solar_event`. The solar-event dose stays in milligray and is never added to `radiation_dose_usv`.
- `assumptions`: every parameter from `routing/config.toml`, with its value, unit, type and source.
- `inputs`: the site name, the grid, and `inputs_fake` (true while any layer in `layers.json` says FAKE).
- `warnings`: anything worth a look, such as a `radiation.csv` that disagrees with the background rate.

The same inputs always give the same file: there is no timestamp. `plan.json` is about 120 kB for the fake site.

## Parameters

Every number the model uses is in [config.toml](config.toml), each with a `value`, a `unit`, a `type` (`observation`, `proxy`, `scenario` or `assumption`) and a `source`. The loader rejects a missing or misspelt parameter, a value out of range, and a walking speed above the walk-run limit for Mars gravity. Do not relax the slope limits because gravity is low: traction drops with it too.

## Tests

```bash
python -m pytest routing/tests
```

Most tests use small synthetic grids and pass each site's start with `--start` (`with_start` in `tests/conftest.py`). `tests/replay.py` is a plain Dijkstra written only from the documented edge rule; it stands in for the browser and must reproduce the golden cases. `test_end_to_end.py` and the real-site golden test read `data/out/`, so run `plan_route.py` and `export_landing.py` first.

## More

- [docs/DESIGN.md](docs/DESIGN.md): what the planner does and why, and the assumptions still to confirm.
- [docs/CHECKLIST.md](docs/CHECKLIST.md): the build order and what is done.
