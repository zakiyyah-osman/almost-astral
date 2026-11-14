# routing/ design

What the route planner does and why. Build order is in `CHECKLIST.md`; independent checks are in `QA.md`.

Status: everything is built except the hard-mask validation against the Perseverance traverse (CHECKLIST 6.3), which waits for the traverse data. Phase 8 added the fixed start (section 4.9) and the reach export for point-to-point routes (section 13). Items still waiting for a decision are collected in sections 11 and 12.

The walk is for an astronaut on foot only. Every walk starts and ends at the start point `start.xy_m` in `config.toml`, which is landing spot L1 for now.

## 1. Scope

Reads from `data/out/` (never writes these):

| File | Used for |
| --- | --- |
| `layers.json` | `site.grid` (width, height, cell_m), site name, whether inputs are still fake |
| `dem.tif` | terrain slope, elevation along the route |
| `hazard.tif` | red cells (blocked) and yellow cells (penalised) |
| `waypoints.geojson` | the science stops, and optionally a `start` waypoint, which is only compared with `start.xy_m` (the old kind `rover` is still read, with a warning) |
| `radiation.csv` | cross-check of the background rate, storm hours for the demo |

Writes to `data/out/`:

| File | Contract status |
| --- | --- |
| `route.geojson` | contract file: the balanced route |
| `shelter_time.png` | contract file |
| `plan.json` | contract file, with added fields (section 9) |
| `route_fastest.geojson`, `route_safest.geojson` | new files, same format as `route.geojson` |
| `reach/` (13 binary grids and `reach.json`) | new folder, written by `export_reach.py` (section 13) |

Writes inside `routing/` only: `reports/sweep.csv`, `reports/sensitivity.csv`, `reports/validation.csv`. These come from `analysis.py`, which never writes to `data/out/`.

Nothing in the code may assume the site, the grid size or the cell size. Switching from Jezero to Gale means new files in `data/out/` and no code change.

## 2. Module layout

Flat modules in `routing/`. The entry point stays `python routing/plan_route.py`.

| Module | Responsibility |
| --- | --- |
| `config.toml` | every parameter, with value, unit, type and source (section 10) |
| `config.py` | load and validate the config; run the gravity check |
| `grid.py` | read `layers.json`, `dem.tif`, `hazard.tif`; cell ↔ metre conversion; terrain slope. Holds the contract constants (file names, hazard codes 0/1/2) |
| `walking.py` | walking speed as a function of slope |
| `cost.py` | hard mask, risk rate, time-rate array and planning-cost array |
| `search.py` | thin wrapper over `skimage.graph.MCP_Geometric`: cumulative cost from a start cell, path to any cell, time and risk summed along a path |
| `tour.py` | load and check waypoints, decide stop order, build the three profile routes |
| `start.py` | the start from `start.xy_m`, its checks (section 4.9), and the blocked-reason codes |
| `shelter.py` | minutes-back-to-start array and its PNG rendering |
| `storm.py` | return paths from sampled route points |
| `timeline.py` | legs, totals, track samples, budget checks, radiation |
| `outputs.py` | writers for the GeoJSON files and `plan.json` |
| `analysis.py` | the w-sweep function, sensitivity runs, hard-mask validation against the Perseverance traverse. Run as a script it writes CSV reports only |
| `plan_route.py` | wires everything; takes the command-line options below |
| `export_reach.py` | reach grids from the start for the three profiles, the manifest, and the reference `trace` (section 13) |
| `tests/` | pytest, on small synthetic grids built in `conftest.py`; only the end-to-end test reads `data/out/` |
| `docs/` | `DESIGN.md`, `CHECKLIST.md`, `QA.md` |
| `reports/` | CSV tables from `analysis.py` |

**Command-line options.**

| Option | `plan_route.py` | `analysis.py` | `export_reach.py` | Meaning | Default |
| --- | --- | --- | --- | --- | --- |
| `--in DIR` | yes | yes | yes | folder the inputs are read from | `data/out` |
| `--config FILE` | yes | yes | yes | parameter file | `routing/config.toml` |
| `--out DIR` | yes | no | yes | folder the outputs are written to | `plan_route.py`: the value of `--in`; `export_reach.py`: `<--in>/reach` |
| `--reports DIR` | no | yes | no | folder the CSV reports are written to | `routing/reports` |

With no options, `plan_route.py` reads and writes `data/out`. When `--in` is set and `--out` is not, outputs go to the `--in` folder, never to `data/out`: a run pointed at a test folder cannot overwrite the shared data by accident.

`analysis.py` writes CSV files only, into `--reports`. It has no `--out` and never writes to `data/out/`. The `sweep` block in `plan.json` is produced by `plan_route.py`, which calls the sweep function in `analysis.py`; `analysis.py` run as a script writes the same rows to `sweep.csv`.

Tests and `QA.md` use these options to run on a temporary copy and to change parameters without editing `routing/config.toml`.

Dependencies beyond `requirements.txt`: `scikit-image` (search), `scipy` (distance transform), `pytest`. See section 12.

## 3. Data flow

```
layers.json ──► grid (width, height, cell_m)
dem.tif ──────► terrain slope ──┬─► walking speed ─► time rate (min/m) ─────────────┐
                                │                                                    │
hazard.tif ───► red, yellow ────┼─► hard mask (red, slope limit, buffer, sealed)     │
                                └─► risk rate (yellow, steep, near-red)              │
                                                                                     ▼
config.toml ──► w per profile ───────────────► planning cost = time rate × (1 + w × risk rate)
                                                                                     │
start.xy_m ─► start cell, checked (4.9) ┐
waypoints.geojson ─► snap to cells, check passable ──► MCP_Geometric from each waypoint
                                                                                     │
                                          stop order ─► fastest / balanced / safest routes
                                                                                     │
                 MCP_Geometric from start, w = 0 ─► back-to-start time array ─► shelter_time.png
                                                          │
                                                          └─► storm return paths
                                                                                     │
radiation.csv ─► cross-check ─► timeline: legs, track, budget checks, dose ◄─────────┘
                                                                                     │
                        route.geojson, route_fastest.geojson, route_safest.geojson, plan.json
                                                                                     │
                                                                       python data/validate.py
```

## 4. Cost model

### 4.1 Hard constraints (impassable)

A cell is blocked when any of these holds:

- `hazard.tif` is red (2).
- Terrain slope is above `constraints.slope_max_deg`.
- It lies within `constraints.cliff_buffer_m` of a cell that is over the slope limit (0 turns the buffer off; a value below `cell_m` has no effect). Distance comes from `scipy.ndimage.distance_transform_edt` with `sampling=cell_m`.
- The DEM has no data there.
- It is sealed by the gap rule. The search allows diagonal moves, so without it a path could squeeze between two blocked cells that touch only at a corner. In any 2x2 block where one diagonal is blocked and the other is free, both free cells are sealed. Sealing is repeated until no such block remains (it only adds blocked cells, so it ends); a sealed cell can create a new squeeze, which the next pass closes. A free cell is not sealed just because two perpendicular neighbours are blocked: if the cell on its own diagonal is blocked too, there is no gap, so the bend of a 1-wide corridor and the cells around a no-data cell stay open.

Blocked cells get cost −1, which `MCP_Geometric` treats as impassable.

### 4.2 Soft constraints (risk)

Each passable cell has a risk rate, in risk-minutes per minute walked:

```
risk_rate = yellow_rate      × [cell is yellow]
          + steep_rate_max   × ramp(slope; steep_onset_deg → slope_max_deg)
          + near_red_rate_max × (1 − d_red / near_red_radius_m), clipped at 0
```

`ramp` is 0 at the onset, 1 at the limit, linear between. The steep term is built but switched off (`steep_rate_max` = 0): yellow already encodes 10–20° slope, so leaving it on would count the same slope twice. `d_red` is the distance in metres to the nearest red cell, from `distance_transform_edt`. A rate of 1.0 means a minute spent there counts as one extra minute when choosing the path.

### 4.3 Planning cost and physical time

Two per-cell arrays, both in minutes per metre:

```
time_rate     = 1 / v(slope)                          physical
planning_rate = time_rate × (1 + w × risk_rate)       only for choosing the path
```

A move between neighbouring cells a and b of length L metres costs `L × (rate_a + rate_b) / 2`. This is what `MCP_Geometric` computes when given `sampling=(cell_m, cell_m)` and `fully_connected=True`, so no search code is written here.

After a path is chosen, three sums are taken along it with the same edge formula:

- `physical_min` from `time_rate`
- `risk_min` from `time_rate × risk_rate`, also split into `yellow_min`, `steep_min`, `near_red_min`
- `distance_m` from L

So `planning cost = physical_min + w × risk_min` holds exactly, and only `physical_min` goes into the timeline, the back-to-start map, the budgets and `plan.json`. Risk never inflates a reported time.

### 4.4 Slope is the terrain slope, not the slope along the path

`MCP_Geometric` takes one cost per cell, so `v(S)` uses the steepest slope of the terrain at that cell. Walking along a contour is timed as slowly as climbing straight up. This overestimates time on slopes, which is the safe direction, and it keeps one model for routes, the back-to-start map and storm returns.

The direction-aware alternative is `MCP_Flexible` with `travel_cost` overridden and elevation as the cost array. Its hook receives only the two cell values, so blocks and risk would need a workaround. It is recorded as a possible upgrade and is not part of this design. This choice is listed in section 11.

Because the cost is the same in both directions, the time from A to B equals the time from B to A. One search from the start therefore gives the time back to the start from every cell.

### 4.5 Search

- `MCP_Geometric(planning_rate, fully_connected=True, sampling=(cell_m, cell_m))`.
- `find_costs` from each waypoint gives the cost to every other waypoint; `traceback` gives the path as cells.
- It is Dijkstra-based and returns the same optimum A* would. `README.md` and `docs/work-split.md` say A*; the result is identical.
- 8 neighbours, horizontal distance. A grid path is up to about 8% longer than a free-angle path, so distances and times lean high.

### 4.6 Waypoints and stop order

- A point `(x, y)` snaps to the cell that contains it. Route vertices are cell centres, so a marker can sit up to half a cell diagonal from the line.
- The start is `start.xy_m` from the config (section 4.9), never a waypoint position. At most one waypoint of `kind: "start"` is allowed; it is optional and only compared with `start.xy_m`. The start's id is always `start` (the `from`/`to` of the first and last legs), whatever id the file uses. A stop may not use the id `start`.
- `kind: "rover"` is the old name for `start`. It is still read, as `start`, and logs a deprecation warning that is also written to `plan.json` `warnings`. Any other kind fails.
- At least one `kind: "stop"` is required.
- A stop on a blocked cell, or with no path to the start, stops the run with a non-zero exit code. The message names the stop id, its name, its coordinates and the reason (red cell, slope over limit, inside buffer, unreachable). No output file is written.
- `timeline.stop_order` chooses the order: `as_listed` follows `waypoints.geojson`; `optimise` tries every order (3 to 5 stops is at most 120) on the balanced planning cost, uses that order for all three profiles, and breaks ties by file order. The pairwise costs come from one search per waypoint, computed once and reused for every order. With more than `timeline.optimise_max_stops` stops (8, which is 40,320 orders) `optimise` falls back to `as_listed` and records a warning in `plan.json` (`stop_order.warnings`). Default is `as_listed` until Zakiyyah answers.

### 4.7 Profiles

| Profile | w | File |
| --- | --- | --- |
| fastest | `profiles.w_fastest` (0) | `route_fastest.geojson` |
| balanced | `profiles.w_balanced` (1) | `route.geojson` |
| safest | `profiles.w_safest` (5) | `route_safest.geojson` |

All three share the hard mask. They differ only in how much risk exposure they trade for time.

### 4.8 Sweep and sensitivity

- **w-sweep:** rerun the route for each value in `profiles.sweep_w`. One row per w: distance, walk minutes, risk minutes and its three parts. This is the time against risk-exposure table. `plan_route.py` writes it into `plan.json` (`sweep`); `analysis.py` writes the same rows to `reports/sweep.csv`. Both call one sweep function, so the two cannot disagree.
- **Sensitivity:** every combination of `sensitivity.v_flat_kmh`, `sensitivity.slope_max_deg` and `sensitivity.w` (2 x 3 x 3 = 18 runs). One row each: walk minutes, total minutes, risk minutes, budget status, or `infeasible` with the stop that failed. Goes to `reports/sensitivity.csv`.
- **Hard-mask validation:** the share of Perseverance traverse points that fall on passable cells, reported in `reports/validation.csv`. Perseverance drove there, so a low share means the mask is too strict. Blocked until Yaj supplies the traverse in grid coordinates (section 12).

### 4.9 The start

Every walk starts and ends at `start.xy_m` (metres, `[x, y]`) in `config.toml`. For now this is landing spot L1: the first of the recommended landing spots that `web/src/lib/landing.js` (`recommendLanding`) computes in the browser, here (1387.5, 712.5) m, the centre of cell (row 257, col 277), on the data in `data/out/` of 2026-11-14. It is marked temporary and will change when the full Jezero dataset is loaded. `plan_route.py` and `export_reach.py` both use it, so the outing plan, the minutes-back-to-start map and the reach grids measure from the same cell.

Checks, in this order (`start.py`):

1. The point must lie on the grid (for the reach export, inside the exported area after `reach.crop_m` and `reach.downsample`).
2. The cell must be passable. Each blocked reason is its own error message: no DEM data, red cell, slope over `constraints.slope_max_deg`, inside the cliff buffer, sealed gap. These are exactly the hard constraints of section 4.1, so a start the route cannot leave is refused.
3. A start on a yellow cell, or on slope above `risk.steep_onset_deg`, is allowed. It gives a warning in `plan.json` `warnings` and `reach.json` `warnings`.
4. If `waypoints.geojson` has a start (or rover) waypoint more than half a cell from `start.xy_m`, the config value is used and a warning is logged and written to `plan.json` `warnings`.

A failed check stops the run with a non-zero exit code and writes nothing. In the sensitivity table, a start that becomes blocked under a tighter slope limit makes the run `infeasible` with `failed_stop` = `start`.

The same reason codes are used per cell in `reach/reason.u8` (section 13): 0 reachable, 1 no data, 2 red, 3 slope, 4 buffer, 5 sealed, 6 passable but walled off from the start. A cell blocked for several reasons takes the first in that order.

## 5. Walking model

```
v(S) = v_flat × exp(−k × (|S| + s0)) / exp(−k × s0)        k = 3.5, s0 = 0.05
```

`S` is slope as rise over run, not degrees. Tobler's hiking function supplies only the shape; it is normalised to 1 on flat ground, so `v(0) = v_flat`. The expression reduces to `v_flat × exp(−3.5 × |S|)`: the same speed uphill and downhill.

- `v_flat` = 2.7 km/h, the NASA Apollo planning value for walkbacks over 1 hour. It already describes a suited walker, so no separate suit penalty is applied.
- Alternative for the sensitivity run: 3.4 km/h, the energy-optimal walking speed in Mars gravity (Cavagna et al.).
- Example: on a 10% slope the factor is `exp(−0.35)` = 0.705, so 1.90 km/h.

**Gravity check.** Walking turns into running near Froude number 0.5, so the fastest possible walk is `sqrt(0.5 × g × leg_length)`. With g = 3.71 m/s² and leg length 0.9 m that is 1.29 m/s = 4.65 km/h. `config.py` computes it at load and refuses to run if `v_flat`, or any sensitivity value, is at or above it. Both 2.7 and 3.4 km/h pass.

**Slope limits are not relaxed for low gravity.** Lower weight lowers traction as well, so a slope that is unsafe on Earth is not made safe by Mars gravity. Gravity enters this module only through the check above.

Distances are plain metres on the local grid. No latitude, longitude or planetary-radius formula is used anywhere.

## 6. Back-to-start map

- One `MCP_Geometric` run from the start cell on `time_rate` (w = 0) gives the fastest physical minutes from every cell. The layer is "minutes back to start".
- `shelter_min = walk minutes + timeline.ingress_min`. At the start cell it equals the ingress time.
- Blocked and unreachable cells have no value.

`shelter_time.png` is RGBA, exactly `width x height`, row 0 at the north edge. Cells are coloured on a ramp from 0 to `shelter_map.colour_max_min` (longer times take the last colour). Contour lines are burned in wherever a cell and a neighbour fall in different `shelter_map.contour_interval_min` bands. Cells with no value are fully transparent.

The web app cannot read minutes back out of a picture, so `plan.json` carries the legend (`shelter_map`: `label` "Minutes back to start", colour stops, interval, maximum) and the exact value at each track point (`track[].shelter_min`). The file name and the `shelter_*` keys keep their names (contract).

## 7. Storm re-plan

- Sample the balanced route every `storm.sample_spacing_m`, and at every stop.
- For each sample, the return path is the `traceback` from the start-rooted search of section 6: the fastest physical way back, ignoring risk weights but never crossing a blocked cell.
- Each sample reports where it is, how far along the route, elapsed minutes on arrival, `return_min` (walk plus ingress), `return_distance_m` and the return path.
- `worst` points at the sample with the largest `return_min`.

**Solar-event dose.** Curiosity RAD measured 8.1 mGy absorbed dose on 20 May 2024 (NASA). `plan.json` reports it in its own field, in Gy, as the whole-event figure for someone who stays unprotected. It is never converted to Sv and never added to `radiation_dose_usv`. Scaling it by the return time would need the event's duration, which this design has no source for (section 11).

## 8. Timeline and budgets

**Times.**

```
walk_min    = sum of physical_min over legs
stop_min    = sum of stop durations (timeline.stop_min_default each)
ingress_min = timeline.ingress_min
total_min   = walk_min + stop_min + ingress_min
```

The clock starts when the crew leaves the start. Legs run start → stops → start. Each leg records arrival and departure times, so the web app can draw the timeline.

**Track.** The balanced route sampled every `track.spacing_m`: position, distance, elevation, slope, hazard class, elapsed minutes, minutes back to the start. `elapsed_min` is clock time since leaving the start, so it includes the time spent at every stop already visited, not only walking time. It feeds the slope profile chart and the HUD.

**Checks**, each written to `plan.json` with its value and limit:

| id | Passes when |
| --- | --- |
| `reserve` | `total_min ≤ eva_max_min × (1 − reserve_pct / 100)`. With 360 and 30 the usable time is 252 min |
| `abort` | at every track point, `elapsed_min + shelter_min ≤ eva_max_min`: the crew can always get back inside the hard limit |
| `radiation` | `radiation_dose_usv ≤ radiation.limit_usv` |

`eva_max_min` stands for the suit's limiting consumable. Oxygen and battery are not modelled separately.

**Radiation.** `radiation_dose_usv = background rate × total_min`. The rate is `radiation.background_dose_rate_msv_day` (0.64 mSv/day = 26.7 µSv/h); a 180-minute EVA gives 80 µSv. `radiation.csv` is read for two things only: its median is compared with the config rate (a warning if they differ by more than `radiation.baseline_tolerance_pct`), and hours at or above `radiation.storm_detect_factor` times the median are listed as storm hours for the demo. Storm hours are not added to the Sv figure.

**Outcomes.**

- All checks pass: `status: "ok"`, exit code 0.
- A check fails: outputs are still written, `status: "over_budget"`, a clear warning is printed, exit code 0. The map stays usable and the failure is visible.
- A stop is blocked or unreachable, or an input is malformed: non-zero exit, nothing written.

## 9. Output formats

### 9.1 Route files

`route.geojson`, `route_fastest.geojson` and `route_safest.geojson`: a `FeatureCollection` with one `LineString`, coordinates `[x, y]` in metres, start to start. Vertices on a straight run are dropped, which changes nothing about the line. No `fake` property.

Properties: `profile`, `w`, `distance_m`, `walk_min`, `risk_min`, `source` ("routing model over dem.tif and hazard.tif").

### 9.2 `plan.json`

Contract fields keep their names and meaning. Contract times and distances are whole minutes and metres; added fields use one decimal. There is no timestamp, so the same inputs give the same file.

One intended difference from the fake file: `totals.total_min` now includes ingress, and `totals.ingress_min` is added so the sum is visible.

Shape (numbers are placeholders):

```json
{
  "crew": 2,
  "legs": [
    {
      "from": "start", "to": "stop1", "distance_m": 812, "walk_min": 21,
      "risk_min": 3.4, "ascent_m": 12.0, "descent_m": 4.5, "max_slope_deg": 8.2,
      "depart_min": 0.0, "arrive_min": 21.3, "stop_min": 25
    }
  ],
  "totals": { "walk_min": 96, "stop_min": 75, "total_min": 186, "ingress_min": 15 },
  "budgets": {
    "eva_max_min": 360, "radiation_limit_usv": 1000,
    "reserve_pct": 30, "usable_min": 252
  },
  "radiation_dose_usv": 83,

  "status": "ok",
  "checks": [
    { "id": "reserve", "ok": true, "value": 186, "limit": 252, "unit": "min", "message": "..." }
  ],
  "stop_order": { "mode": "as_listed", "order": ["stop1", "stop2", "stop3"], "warnings": [] },
  "profiles": {
    "balanced": {
      "w": 1, "file": "route.geojson", "distance_m": 3890, "walk_min": 96.2,
      "risk_min": 7.8, "yellow_min": 6.1, "steep_min": 0.0, "near_red_min": 1.7,
      "total_min": 186.2, "status": "ok"
    }
  },
  "sweep": [
    { "w": 0, "distance_m": 3760, "walk_min": 92.8, "risk_min": 14.0,
      "yellow_min": 11.0, "steep_min": 0.0, "near_red_min": 3.0 }
  ],
  "track": [
    { "distance_m": 0, "x": 1002.5, "y": 902.5, "elev_m": 3.1, "slope_deg": 1.2,
      "hazard": 0, "elapsed_min": 0.0, "shelter_min": 15.0 }
  ],
  "storm_replan": {
    "sample_spacing_m": 100,
    "points": [
      { "x": 652.5, "y": 1322.5, "route_distance_m": 500, "elapsed_min": 13.1,
        "return_min": 28.0, "return_distance_m": 498, "path": [[652.5, 1322.5], [1002.5, 902.5]] }
    ],
    "worst": 7
  },
  "shelter_map": {
    "file": "shelter_time.png", "includes_ingress": true,
    "contour_interval_min": 10, "colour_max_min": 60,
    "stops": [ { "min": 0, "rgba": [0, 0, 0, 0] } ]
  },
  "radiation": {
    "background_usv_h": 26.7,
    "csv_median_usv_h": 27.0, "csv_storm_hours": [15, 16],
    "solar_event": {
      "absorbed_dose_mgy": 8.1, "date": "2024-05-20",
      "source": "Curiosity RAD (MSL), NASA",
      "note": "Whole-event absorbed dose if unprotected. In Gy; not added to radiation_dose_usv."
    }
  },
  "assumptions": {
    "walking.v_flat_kmh": { "value": 2.7, "unit": "km/h", "type": "scenario", "source": "..." }
  },
  "inputs": {
    "site": "Name from layers.json",
    "grid": { "width": 400, "height": 400, "cell_m": 5.0 },
    "inputs_fake": true
  }
}
```

- `profiles` has the same block for `fastest` and `safest`.
- `start` (added): `id`, `name`, `xy_m`, `cell` and `source`, the start actually used (section 4.9). The id is always `start`, whatever id `waypoints.geojson` uses, and the first leg's `from` and the last leg's `to` are that id.
- `shelter_map.label` (added): "Minutes back to start".
- `assumptions` is the whole of `config.toml`, copied.
- `inputs_fake` is true while any layer `source` in `layers.json` contains `FAKE`. The file carries no top-level `fake` key, so `validate.py` treats the plan as real output.

## 10. `routing/config.toml`

Every parameter is a table with `value`, `unit`, `type` and `source`. Types:

- `observation`: measured for this quantity at this site.
- `proxy`: measured elsewhere or for a related quantity, and transferred.
- `scenario`: a planning value the team chose.

Values measured at Gale are `proxy` while the site is Jezero and become `observation` if the site switches to Gale.

```toml
# routing/config.toml
# Every parameter: value, unit, type (observation / proxy / scenario), source.

# ---- crew ---------------------------------------------------------------
[crew.size]
value = 2
unit = "people"
type = "scenario"
source = "CONTRACT.md plan.json example"

# ---- walking ------------------------------------------------------------
[walking.v_flat_kmh]
value = 2.7
unit = "km/h"
type = "scenario"
source = "NASA Apollo planning value for walkbacks over 1 hour"

[walking.tobler_k]
value = 3.5
unit = "per unit slope (m/m)"
type = "proxy"
source = "Tobler hiking function (1993), fitted to unsuited walkers on Earth; used for the slope shape only"

[walking.tobler_offset]
value = 0.05
unit = "m/m"
type = "proxy"
source = "Tobler hiking function (1993); cancels after normalising to 1 on flat ground"

[walking.gravity_m_s2]
value = 3.71
unit = "m/s^2"
type = "observation"
source = "NASA Mars Fact Sheet (NSSDC), surface gravity"

[walking.leg_length_m]
value = 0.9
unit = "m"
type = "scenario"
source = "Team choice: typical adult leg length"

[walking.froude_walk_run]
value = 0.5
unit = "dimensionless"
type = "proxy"
source = "Walk-run transition at Froude number 0.5, Kram et al. 1997 (reduced-gravity locomotion)"

# ---- hard constraints ---------------------------------------------------
[constraints.slope_max_deg]
value = 20
unit = "deg"
type = "scenario"
source = "Same as the red slope threshold in terrain/thresholds.toml (a starting value there)"

[constraints.cliff_buffer_m]
value = 5
unit = "m"
type = "scenario"
source = "Team choice: ring around over-limit slopes. Has no effect when below cell_m (the nearest neighbour is already one cell away); 0 turns it off"

# ---- soft constraints (risk) --------------------------------------------
[risk.yellow_rate]
value = 1.0
unit = "risk-min per min"
type = "scenario"
source = "Team choice: a minute on yellow counts double at w = 1"

[risk.steep_onset_deg]
value = 10
unit = "deg"
type = "scenario"
source = "Same as the yellow slope threshold in terrain/thresholds.toml"

[risk.steep_rate_max]
value = 0.0
unit = "risk-min per min"
type = "scenario"
source = "disabled: yellow already encodes 10–20° slope; re-enable if Nahla changes yellow"

[risk.near_red_radius_m]
value = 15
unit = "m"
type = "scenario"
source = "Team choice: three cells at 5 m"

[risk.near_red_rate_max]
value = 1.0
unit = "risk-min per min"
type = "scenario"
source = "Team choice: rate at distance 0 from a red cell, falling linearly to 0 at near_red_radius_m"

# ---- profiles -----------------------------------------------------------
[profiles.w_fastest]
value = 0.0
unit = "dimensionless"
type = "scenario"
source = "Definition of the fastest profile: risk is ignored"

[profiles.w_balanced]
value = 1.0
unit = "dimensionless"
type = "scenario"
source = "Team choice, confirmed for now"

[profiles.w_safest]
value = 5.0
unit = "dimensionless"
type = "scenario"
source = "Team choice, confirmed for now"

[profiles.sweep_w]
value = [0.0, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
unit = "dimensionless"
type = "scenario"
source = "Team choice: spans fastest to beyond safest"

# ---- sensitivity --------------------------------------------------------
[sensitivity.v_flat_kmh]
value = [2.7, 3.4]
unit = "km/h"
type = "scenario"
source = "2.7: Apollo walkback planning value. 3.4: energy-optimal walking speed in Mars gravity, Cavagna et al. 1998"

[sensitivity.slope_max_deg]
value = [15, 20, 25]
unit = "deg"
type = "scenario"
source = "Team choice: 5 degrees either side of the limit"

[sensitivity.w]
value = [0.0, 1.0, 5.0]
unit = "dimensionless"
type = "scenario"
source = "The three profile weights"

# ---- timeline and budgets -----------------------------------------------
[timeline.stop_order]
value = "as_listed"
unit = "as_listed | optimise"
type = "scenario"
source = "Default until Zakiyyah decides whether routing may reorder stops"

[timeline.optimise_max_stops]
value = 8
unit = "stops"
type = "scenario"
source = "Team choice: 8 stops is 40,320 orders, still fast; above this, optimise falls back to as_listed with a warning"

[timeline.stop_min_default]
value = 25
unit = "min"
type = "scenario"
source = "STOP_MIN in data/make_fake.py; to be replaced by the mission brief"

[timeline.ingress_min]
value = 15
unit = "min"
type = "scenario"
source = "Team choice, confirmed by Tushaar: time to get back inside at the start"

[timeline.eva_max_min]
value = 360
unit = "min"
type = "scenario"
source = "CONTRACT.md plan.json example; to be replaced by the mission brief"

[timeline.reserve_pct]
value = 30
unit = "percent"
type = "scenario"
source = "Team choice"

# ---- radiation ----------------------------------------------------------
[radiation.background_dose_rate_msv_day]
value = 0.64
unit = "mSv/day"
type = "proxy"
source = "Curiosity RAD (MSL) at Gale, Hassler et al. 2014; applied to Jezero"

[radiation.limit_usv]
value = 1000
unit = "uSv"
type = "scenario"
source = "CONTRACT.md plan.json example; to be replaced by the mission brief"

[radiation.solar_event_dose_mgy]
value = 8.1
unit = "mGy (absorbed, whole event)"
type = "proxy"
source = "Curiosity RAD (MSL) at Gale, 20 May 2024, NASA; applied to Jezero. Stays in Gy"

[radiation.baseline_tolerance_pct]
value = 25
unit = "percent"
type = "scenario"
source = "Team choice: warn when the radiation.csv median differs from the config rate by more"

[radiation.storm_detect_factor]
value = 2.0
unit = "times the radiation.csv median"
type = "scenario"
source = "Team choice: hours at or above this are listed as storm hours"

# ---- storm re-plan ------------------------------------------------------
[storm.sample_spacing_m]
value = 100
unit = "m"
type = "scenario"
source = "Team choice: keeps plan.json small"

# ---- back-to-start map (the keys keep the contract name shelter_map) ---
[shelter_map.contour_interval_min]
value = 10
unit = "min"
type = "scenario"
source = "Team choice"

[shelter_map.colour_max_min]
value = 60
unit = "min"
type = "scenario"
source = "Same range as the fake layer in data/make_fake.py"

# ---- track --------------------------------------------------------------
[track.spacing_m]
value = 25
unit = "m"
type = "scenario"
source = "Team choice: five cells at 5 m, enough for the slope profile"

# ---- search -------------------------------------------------------------
[search.connectivity]
value = 8
unit = "neighbours"
type = "scenario"
source = "skimage.graph.MCP_Geometric with fully_connected=True"

# ---- start --------------------------------------------------------------
# The fixed start (and end) of every walk, in metres on the site grid: [x, y].
# This is landing spot L1, and it is TEMPORARY. It is the first of the recommended landing
# spots from web/src/lib/landing.js (recommendLanding), computed on data/out on 2026-11-14.
# Recompute it when the full Jezero dataset is loaded.
[start.xy_m]
value = [1387.5, 712.5]
unit = "m (site grid x, y)"
type = "scenario"
source = "Landing spot L1 from web/src/lib/landing.js recommendLanding (flat 50 m pad, shortest walk to the first and last stop), computed on data/out of 2026-11-14; temporary until the full Jezero dataset is loaded"

# ---- reach export (export_reach.py) --------------------------------------
[reach.crop_m]
value = "full"
unit = "\"full\" or [x0, y0, x1, y1] in m on the site grid"
type = "scenario"
source = "Team choice: the whole site.grid of layers.json until the full-crater grid is decided"

[reach.downsample]
value = 1
unit = "site cells per export cell (whole number)"
type = "scenario"
source = "Team choice: 1 keeps the site resolution"

[reach.destination_stop]
value = true
unit = "true | false"
type = "scenario"
source = "Team choice (Tushaar): the over-budget limit counts one stop of timeline.stop_min_default at the destination; false sets it to 0"
```

Not in the config, because `CONTRACT.md` fixes them: file names, hazard codes (0, 1, 2), and the grid (always read from `layers.json`).

## 11. Assumptions not yet confirmed

Confirmed by Tushaar and so not listed: ingress 15 min; over budget is a warning, not a failure; w = 1 (balanced) and 5 (safest) for now.

Model:

1. Speed uses the terrain's steepest slope at each cell, not the slope along the direction of travel (section 4.4).
2. No suit penalty on top of `v_flat`, on the reading that the Apollo figure already describes a suited walker.
3. Distance is horizontal map distance on an 8-neighbour grid.
4. The three risk terms add, each as a rate per minute walked.
5. Diagonal gaps between blocked cells are sealed.
6. Route vertices are cell centres; markers can be up to half a cell diagonal off the line.

Values:

7. `slope_max_deg` 20 and `steep_onset_deg` 10, copied from `terrain/thresholds.toml`, which calls them starting values.
8. `cliff_buffer_m` 5.
9. `yellow_rate` and `near_red_rate_max` both 1.0; `near_red_radius_m` 15.
9a. `steep_rate_max` is 0, so the steep-slope penalty is off and `steep_min` is always 0. This rests on yellow meaning 10–20° slope, which is true of the fake hazard map and of `terrain/thresholds.toml` today. If Nahla changes what yellow means, re-enable it.
10. `stop_min_default` 25, taken from the fake-data generator.
11. `eva_max_min` 360 and radiation limit 1000 µSv, taken from the contract example.
12. Sweep and sensitivity value lists.
13. Storm sample spacing 100 m, track spacing 25 m, contour interval 10 min, colour range 60 min.
14. `baseline_tolerance_pct` 25 and `storm_detect_factor` 2.

Timeline and radiation:

15. The clock starts outside, at the start; egress time is not counted.
16. `total_min` includes ingress, which the fake `plan.json` did not.
17. Oxygen and battery are folded into `eva_max_min`.
18. `stop_order` defaults to `as_listed`.
19. The Sv dose uses the config background rate, not the hourly values in `radiation.csv`.
20. The 8.1 mGy figure is reported as a whole-event value. There is no event duration here, so it is not scaled to the time needed to get back to the start.
21. Gale measurements are typed `proxy` for Jezero. The routing instructions word the background rate as a scenario.

Sources and environment:

22. The literature references added here (Tobler 1993, Cavagna et al. 1998, Kram et al. 1997, Hassler et al. 2014) are cited from memory and need checking before they go on a slide.
23. `.venv` is Python 3.12 with `scikit-image`, `scipy` and `pytest` installed locally only. They are requested from Yaj but not yet in `requirements.txt`, so a teammate's fresh install will not have them. Python 3.13 and later lack wheels, so 3.12 is the newest version this module runs on; the project docs say 3.11+.
24. `skimage.graph.MCP_Geometric` behaves as this design needs. Checked in `.venv` (scikit-image 0.26.0) on a 5 x 5 grid: `sampling` scales move lengths to metres, a negative cost is impassable, unreachable cells come back as `inf`, and `traceback` returns the path as cells.

Grid and rasters:

25. The raster origin is not checked against (0, 0). The pixel indices define the grid (row 0 is the north edge, `CONTRACT.md`). `dem.tif` and `hazard.tif` must carry the same geotransform (origin, pixel size, orientation), and each must have a pixel size equal to `cell_m` on both axes, be north-up and have no rotation; otherwise the run stops with an error naming the file or both files.
26. A TIFF with no geotransform at all (GDAL then reports the identity transform) is rejected with its own message, not as "south-up".
27. Slope is the central difference of the four neighbours, so a cell's own height does not enter its slope. A single-cell spike or pit is invisible to it and must come from the hazard map.
28. A no-data DEM cell is NaN in the DEM and NaN in the slope, and so are its four neighbours (the central difference reads them). `cost.py` blocks every NaN-slope cell. The no-data marker is still an open question for Yaj (section 12).

Back-to-start map, storm, timeline and outputs:

29. The back-to-start map is built on `time_rate` directly (a search over the physical rate, w = 0), not through the fastest profile route. The colour ramp (ColorBrewer YlOrRd, five stops spread evenly over `colour_max_min`, alpha 210) and the contour colour are presentation choices; the ramp is written to `plan.json` (`shelter_map.stops`, `contour_rgba`). A contour cell is the one in the higher 10-minute band of two horizontally or vertically adjacent cells, so lines are one cell wide; a cell with no value never starts a line.
30. Storm samples and track points sit on the route cell whose distance along the route is nearest to each multiple of the spacing, not on interpolated points. Every value (elevation, slope, hazard, minutes back to the start, return path) is then the exact value of one cell, and the reported `distance_m` is the actual distance to that cell, within half a step of the multiple. The arrival at each stop is always a sample, and the track also ends at the final cell. `elapsed_min` counts the time spent at a stop from the cell after the arrival cell.
31. The `abort` check covers every track point and also the moment of leaving each stop (arrival time plus stop time plus the way back from the stop). It cannot fail while `reserve` passes, because the way back is never longer than finishing the route, so the worst moment is the end of the walk; it is kept because section 8 asks for it and because its limit is the hard EVA limit.
32. `radiation.csv` that is missing gives a warning in `plan.json` (`warnings`) and skips the cross-check; a file with the wrong columns or non-numeric values stops the run. The date and source text of the 2024-05-20 solar event are fixed strings in `timeline.py`; its dose comes from `radiation.solar_event_dose_mgy`.
33. `plan.json` carries extra fields beyond section 9.2: `warnings`, `stop_order.requested` and `stop_order.warnings`, `shelter_map.contour_rgba`, and `stop` on track and storm points that are a stop arrival.
34. The w-sweep reruns the route for every w over the stop order chosen for the plan (balanced weight), so the rows differ only in w. Each sensitivity run rebuilds the cost for its walking speed and slope limit, chooses the stop order again as the plan does (`timeline.stop_order`, balanced weight) and routes at its own w. A run is `infeasible` when the start or a stop stands on a blocked cell or cannot be reached, and the row names that waypoint; the start (`failed_stop` = `start`) can be the one that fails, for example when a tighter slope limit puts it inside the cliff buffer. Contract fields are whole minutes and metres; `totals.total_min` is the sum of the rounded parts. The file is about 120 kB for the fake site (arrays of numbers are kept on one line).

Start and reach export (phase 8):

35. The start is landing spot L1 as the web app computes it today. The app builds L1 on hazards from slope alone (`web/src/lib/useTerrain.js`, while the hazard layer says FAKE), not on `hazard.tif`. L1 was checked against this planner's model: green, slope 0.96 deg, not blocked.
36. A reach destination is over budget when `time + ingress_min + stop_min > usable_min` (section 13.4): one way only, because the user only gets the path from the start to the destination. No return walk is counted. One stop of `timeline.stop_min_default` is counted at the destination; `reach.destination_stop = false` sets it to 0.
37. With `reach.crop_m`, paths cannot leave the box: the search runs on the cropped grid. The hard mask and the risk are built on the whole grid first, so the buffer and the near-red term still see cells just outside it.
38. With `reach.downsample` = k > 1, the export runs on a coarser grid: DEM block mean (a block with any no-data cell has no data), hazard block maximum (the worst class), slope recomputed at k x `cell_m`. Rows and columns left over at the north and east edges are dropped. Times on a coarse grid are not the times of `plan.json`.
39. Reach values are float32 (about 7 significant digits); `trace` reports them as stored.

## 12. Open questions for teammates

**Yaj (data)**

- Dependency request: add `scikit-image` (route search, `skimage.graph`), `scipy` (`ndimage.distance_transform_edt`) and `pytest` to `requirements.txt`.
- Add `vectors.route_fastest` and `vectors.route_safest` to `layers.json` so the web app can find the two extra routes.
- The `shelter_time` layer's `source` says `FAKE`, so `validate.py --strict` fails even with a real map. What should it say? Suggested: "Routing model over HiRISE terrain model (MRO)".
- `make_fake.py` overwrites `route.geojson`, `plan.json` and `shelter_time.png`. Can it skip them when they are not fake, or do we agree that `plan_route.py` always runs after it?
- `radiation.csv` gives the storm hours in µSv/h. Solar-event dose should stay in Gy. Can a `dose_rate_ugy_h` column be added, or should the storm stay out of the Sv column?
- Please supply the Perseverance traverse as points in grid coordinates (`[x, y]` in metres on the site grid). Routing uses it to validate the hard mask; CHECKLIST 6.3 is blocked until it arrives.
- What marks missing data in `dem.tif`?
- What grid size and cell size will the Jezero site use?

**Nahla (terrain)**

- Does red in `hazard.tif` already include slope above 20°? If so the routing slope limit only repeats it, which is harmless, but the two numbers must stay equal.
- Yellow currently equals slope 10–20°, so routing has switched off its own steep-slope penalty (`risk.steep_rate_max` = 0) to avoid counting the same slope twice. Will yellow come to mean something other than that slope band? If so, tell Tushaar so the penalty can be re-enabled.
- Which slope method do you use, so both folders get the same slope from the same DEM?
- Are 10° and 20° final?

**Zakiyyah (science, HUD, pitch)**

- May routing reorder the stops to shorten the walk, or is the order in `waypoints.geojson` fixed? This decides the `stop_order` default.
- Time at each stop: 25 minutes everywhere, or a `stop_min` per stop in `waypoints.geojson`?
- Limits for the mission brief: maximum EVA time, reserve, radiation limit per EVA.
- Does the HUD need separate oxygen and battery figures, or is one "time remaining" enough?
- For the demo: at which point of the walk does the storm hit, and what local hour does the EVA start?

**Phase 8: start and reach export**

- Zakiyyah: `waypoints.geojson` still uses `kind: "rover"`. Keep it until the contract and `data/validate.py` accept `"start"` (see the Team line below); the routing code accepts both and warns about the old kind. Its position (1000, 900) m is no longer used: the start is `start.xy_m` in `routing/config.toml`.
- Loick: `web/src/App.jsx` finds the start with `kind === 'rover'`, so it breaks the moment the waypoints switch to `start`. The new destination picker should read `data/out/reach/reach.json` and follow section 13.3; the grids are built from `hazard.tif`, while the app routes on hazards from slope alone while the hazard layer says FAKE.
- Yaj: the title of the `shelter_time` layer in `layers.json` should read "Minutes back to start" (it still carries the old wording). Could `layers.json` point at `reach/reach.json` (for example `vectors.reach` or a new `reach` key)? The hazard layer's `source` still says FAKE although `hazard.tif` was regenerated on real Jezero data, so `reach.json` `fake` and `plan.json` `inputs_fake` are still true.
- Team: `CONTRACT.md` still describes `kind` as `"rover"` or `"stop"`, and `data/validate.py` rejects any other kind, so `waypoints.geojson` cannot switch to `"start"` until the contract and `validate.py` are changed together. `CONTRACT.md` also still words the `shelter_time.png` description with the old start name.

**Loick (front end)**

- `totals.total_min` in `plan.json` now includes ingress (walk + stops + ingress), which the fake file did not. `totals.ingress_min` is added so the parts still sum. Does anything in the app assume the old meaning?
- Will the app show all three routes, with a way to switch?
- Is `plan.json` `track[]` (distance, elevation, slope, elapsed, minutes back to the start) enough for the slope profile and the timeline chart?
- Contour lines are burned into `shelter_time.png`. Is that fine, or do you want to draw them yourself?
- `plan.json` grows to roughly 120 kB with the track and return paths. Any problem?

## 13. Reach export (`export_reach.py`)

The user clicks any destination on the map and gets three paths from the start: fastest (the app calls it "efficient", w = `profiles.w_fastest`), balanced (w = `profiles.w_balanced`) and safest (w = `profiles.w_safest`), each with distance, walking time, risk and the terrain along the way. One search per profile from the start answers every destination at once, so the browser only follows pointers.

### 13.1 What runs

1. Load the site (`grid.load_site`). If `reach.downsample` > 1, coarsen it (assumption 38).
2. Build the cost on the whole grid with `cost.build` (section 4), then cut it to `reach.crop_m` (assumption 37).
3. Check the start on the exported grid (section 4.9).
4. For each profile, one `search.build_tree` on that profile's planning rate from the start cell. Its own traceback array becomes the direction grid, so following it gives exactly the path `Tree.path_to` returns.
5. Along each tree, every cell adds one step to its predecessor's totals, with the edge formula of section 4.3 (a step of length L between cells a and b adds `L x (rate_a + rate_b) / 2`). Cells are filled in order of rising planning cost, so a predecessor is always filled first. `time` uses `time_rate` (physical minutes), `risk` uses `time_rate x risk_rate`, `dist` uses L. These are exactly `summarise` along the traced path.
6. Write the grids and, last, `reach.json`. Nothing is written if any step fails.

On the 400 x 400 site at 5 m this takes about 2 seconds.

### 13.2 Files

All grids are raw values with no header, little-endian, row-major, row 0 = north edge, index `row * width + col`, `width x height` values each.

| File | Type | Content |
| --- | --- | --- |
| `{profile}_time.f32` | float32 | walking minutes from the start along that profile's best path; NaN where `reason != 0` |
| `{profile}_dist.f32` | float32 | metres along that path; NaN where `reason != 0` |
| `{profile}_risk.f32` | float32 | risk-minutes along that path; NaN where `reason != 0` |
| `{profile}_dir.u8` | uint8 | direction code: the step from this cell to the previous cell of its best path, toward the start |
| `reason.u8` | uint8 | 0 reachable, 1 no data, 2 red, 3 slope, 4 buffer, 5 sealed, 6 walled off (section 4.9); shared by the profiles, which share one hard mask |
| `reach.json` | JSON | the manifest |

`{profile}` is `fastest`, `balanced` or `safest`. Direction codes, as (row change, column change):

| Code | 0 | 1 N | 2 NE | 3 E | 4 SE | 5 S | 6 SW | 7 W | 8 NW |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| step | none: the start, or no path | (−1, 0) | (−1, +1) | (0, +1) | (+1, +1) | (+1, 0) | (+1, −1) | (0, −1) | (−1, −1) |

Sizes on the current 400 x 400 grid: each `.f32` file is 640,000 bytes and each `.u8` file 160,000 bytes, so 2,080,000 bytes per profile and 6,400,000 bytes for all 13 grids, plus about 6 kB of manifest. The size grows with the number of cells: a crop or a downsample of 2 divides it by the area ratio or by 4.

`reach.json` holds: `format_version`; `site`; `fake` (same rule as `plan.json` `inputs_fake`); `grid` (`width`, `height`, `cell_m`, `origin_m` = south-west corner `[x0, y0]` of the export in site metres, `extent_m`, `crop_m`, `crop_cells`, `downsample`, `site_grid`); `layout` (the formulas in 13.3); `byte_order` (`little`); `dtypes`; `nodata`; `units`; `start` (`xy_m`, `cell` on the exported grid, `note`); `profiles` (per profile: `w`, `files`, `reachable_cells`); `reason_file` and `reason_codes` (`code`, `name`, `text`); `direction_meaning` and `direction_codes` (`code`, `name`, `drow`, `dcol`); `budget` (13.4); `config_sha256` (SHA-256 of the whole config, keys sorted); `inputs_sha256` (`dem.tif`, `hazard.tif`); `files` (bytes and SHA-256 of each grid file); `warnings`. There is no timestamp: the same inputs give the same bytes.

### 13.3 Traceback (the reference is `export_reach.Reach.trace`)

Inputs: the manifest, `reason.u8`, and the profile's four grids. Destination `(x, y)` in site metres.

1. Cell: `col = floor((x − origin_x) / cell_m)`, `row = height − 1 − floor((y − origin_y) / cell_m)`. If `row` or `col` is outside `0 .. height−1` / `0 .. width−1`, stop: "outside the exported area".
2. `code = reason[row * width + col]`. If `code != 0`, stop and show `reason_codes[code].text` (no path, no totals).
3. `cells = [(row, col)]`. Repeat at most `width x height` times: `d = dir[last]`; if `d == 0`, stop; else append `(last.row + drow[d], last.col + dcol[d])`. If the loop runs out, the grid is corrupt.
4. The last cell must equal `start.cell`; otherwise the grid is corrupt.
5. Reverse `cells`, so they run from the start to the destination. Vertex `k` is the cell centre `x = origin_x + (col + 0.5) x cell_m`, `y = origin_y + (height − row − 0.5) x cell_m`. If there is only one cell (the destination is the start), repeat it so the LineString has two positions.
6. Totals are the grid values at the destination cell, not sums: `distance_m = dist[i]`, `walk_min = time[i]`, `risk_min = risk[i]`.
7. One way only, no return walk: `needed_min = walk_min + budget.ingress_min + budget.stop_min`; `over_budget = needed_min > budget.usable_min`, which is the same as `walk_min > budget.walk_limit_min`.

The result is a GeoJSON Feature with a `LineString` (`[x, y]` metres) and these properties, plus `cells` as `[row, col]` from the start, so the app can read elevation, slope and hazard class along the way from its own grids for the terrain profile.

### 13.4 Over budget

```
usable_min        = eva_max_min x (1 − reserve_pct / 100)          252 with the current values
stop_min          = timeline.stop_min_default if reach.destination_stop else 0     25
walk_limit_min    = usable_min − ingress_min − stop_min             252 − 15 − 25 = 212
needed_min        = time + ingress_min + stop_min                   for one destination
```

The user only gets a one-way path, from the start to the destination, so no return walk is counted. A destination is over budget when `needed_min > usable_min`, i.e. when its walking time exceeds `walk_limit_min`. The manifest carries every number and the rule text, so the app can show them; there is no separate over-budget grid, and no return-route grid is exported.
