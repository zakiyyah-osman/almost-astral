# routing/ design

What the route planner does and why. Build order is in `CHECKLIST.md`; independent checks are in `QA.md`.

Status: everything is built except the hard-mask validation against the Perseverance traverse (CHECKLIST 6.3), which waits for the traverse data. Phase 10 removed the fixed starts and the per-start reach export, and added landing safety (section 14) and the cost surface the browser searches (section 15). Items still waiting for a decision are collected in sections 11 and 12.

The walk is for an astronaut on foot only. The user clicks anywhere to choose a landing zone; if it is not safe, the lander moves to the nearest safe spot. From the landing spot the user clicks a destination and gets three one-way walking paths (fastest, balanced, safest), found in the browser. The full outing (`plan_route.py`) starts at `--start x,y` or at the demo start (section 4.9) and ends there.

## 1. Scope

Reads from `data/out/` (never writes these):

| File | Used for |
| --- | --- |
| `layers.json` | `site.grid` (width, height, cell_m), site name, whether inputs are still fake |
| `dem.tif` | terrain slope, elevation along the route |
| `hazard.tif` | red cells (blocked) and yellow cells (penalised) |
| `waypoints.geojson` | the science stops (unverified, section 4.9); a `start` waypoint (or the old `rover`) is never used, only reported as ignored |
| `radiation.csv` | cross-check of the background rate, storm hours for the demo |
| `thermal_inertia.tif` | landing warning only (section 14), while `layers.json` marks the thermal layer real |

Writes to `data/out/`:

| File | Contract status |
| --- | --- |
| `route.geojson` | contract file: the balanced route |
| `shelter_time.png` | contract file |
| `plan.json` | contract file, with added fields (section 9) |
| `route_fastest.geojson`, `route_safest.geojson` | new files, same format as `route.geojson` |
| `landing/` (`manifest.json`, `golden_cases.json`, `landing_zones.png`, `tiles/<ti>_<tj>/` grids) | new folder, written by `export_landing.py` (sections 14 to 16) |

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
| `tour.py` | load and check waypoints, choose the start (`--start` or demo start), decide stop order, build the three profile routes |
| `start.py` | the start checks (section 4.9) and the blocked-reason codes |
| `landing.py` | landing safety per cell, nearest safe cell, `landing_check` (section 14) |
| `shelter.py` | minutes-back-to-start array and its PNG rendering |
| `storm.py` | return paths from sampled route points |
| `timeline.py` | legs, totals, track samples, budget checks, radiation |
| `outputs.py` | writers for the GeoJSON files and `plan.json` |
| `analysis.py` | the w-sweep function, sensitivity runs, hard-mask validation against the Perseverance traverse. Run as a script it writes CSV reports only |
| `plan_route.py` | wires everything; takes the command-line options below |
| `export_landing.py` | the landing grids and the cost surface in tiles, golden cases, the manifest, and the reference `route` and `landing_check` (sections 14 to 16) |
| `escape.py` | escape rates for walking out of a red zone, the reference escape and its golden cases (section 17) |
| `tests/` | pytest, on small synthetic grids built in `conftest.py`; only the end-to-end test reads `data/out/` |
| `docs/` | `DESIGN.md`, `CHECKLIST.md`, `QA.md` |
| `reports/` | CSV tables from `analysis.py` |

**Command-line options.**

| Option | `plan_route.py` | `analysis.py` | `export_landing.py` | Meaning | Default |
| --- | --- | --- | --- | --- | --- |
| `--in DIR` | yes | yes | yes | folder the inputs are read from | `data/out` |
| `--config FILE` | yes | yes | yes | parameter file | `routing/config.toml` |
| `--out DIR` | yes | no | yes | folder the outputs are written to | `plan_route.py`: the value of `--in`; `export_landing.py`: `<--in>/landing` |
| `--reports DIR` | no | yes | no | folder the CSV reports are written to | `routing/reports` |
| `--start X,Y` | yes | yes | no | start of the walk, metres on the site grid | the demo start (section 4.9) |

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
--start x,y or the demo start (4.9, landing.py) ─► start cell checked         ┐
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
- The start is `--start` or the demo start (section 4.9), never a waypoint position. At most one waypoint of `kind: "start"` is allowed; it is optional and only reported as ignored. The start's id is always `start` (the `from`/`to` of the first and last legs). A stop may not use the id `start`.
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

There are no configured starts. In the app the start is the landing spot the user chose (section 14). For the full outing, `plan_route.py` and `analysis.py` take the start on the command line:

- `--start x,y` (metres on the site grid): that point, used as given.
- No `--start`: the **demo start**, the centre of the safe landing cell (code 0, section 14) nearest the cell that holds the grid centre, found with the same `nearest_safe` grid the app uses. It is labelled "demo start" in `plan.json` (`start.kind` = `demo`, `start.name` = "Demo start") and on the command line, with a warning saying so. With no safe cell anywhere the run stops with an error.

Checks (`tour.choose_start` with `start.py`), in this order:

1. The point must lie on the grid.
2. The cell must be passable. Each blocked reason is its own error message: no DEM data, red cell, slope over `constraints.slope_max_deg`, inside the cliff buffer, sealed gap. These are exactly the hard constraints of section 4.1.
3. A start on a yellow cell, or on slope above `risk.steep_onset_deg`, is allowed with a warning. A `--start` point whose landing-safety code is not safe or marginal is allowed with a warning too: the walk can start there, but a lander should not.
4. A waypoint of kind `start` (or the old `rover`) in `waypoints.geojson` is never used as the start, whatever its position; a warning says it is ignored.

A failed check stops the run with a non-zero exit code and writes nothing, for example `start (--start) (12.5, 47.5) m, cell (10, 2), is on a blocked cell: red hazard cell. Choose a start on passable ground (--start x,y).` In the sensitivity table, a start that becomes blocked under a tighter slope limit makes the run `infeasible` with `failed_stop` = `start`.

The stops in `waypoints.geojson` are treated as unverified: they belong to Zakiyyah and were placed on earlier data. Nothing here depends on them being real, and `plan.json` always carries the warning that the outing plan is a demonstration.

The blocked-reason codes are used per cell in `landing/mask.u8` (section 15): 0 passable, 1 no data, 2 red, 3 slope, 4 buffer, 5 sealed. A cell blocked for several reasons takes the first in that order. Code 6 (walled off: passable but not reachable from the landing spot) is a search result, never stored.

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
- `start` (added): `id` (always `start`), `name` ("Start" or "Demo start"), `landing_id` (kept, always `null` since phase 10), `xy_m`, `cell`, `source` (the command line, or the demo-start rule), `kind` (`cli` or `demo`) and `landing_status` (the landing-safety code name of the start cell). The first leg's `from` and the last leg's `to` are `start`. Phase 10 changed nothing else in `plan.json`, apart from `assumptions` now holding the `budget.*` and `landing.*` entries and no `start.*`, `starts.*` or `reach.*`.
- `shelter_map.label` (added): "Minutes back to start".
- `assumptions` is the whole of `config.toml`, copied.
- `inputs_fake` is true while any layer `source` in `layers.json` contains `FAKE`. The file carries no top-level `fake` key, so `validate.py` treats the plan as real output.

## 10. `routing/config.toml`

Every parameter is a table with `value`, `unit`, `type` and `source`. Types:

- `observation`: measured for this quantity at this site.
- `proxy`: measured elsewhere or for a related quantity, and transferred.
- `scenario`: a planning value the team chose.
- `assumption`: a team assumption with no source yet, waiting for a teammate to confirm it (the `[landing]` limits).

Values measured at Gale are `proxy` while the site is Jezero and become `observation` if the site switches to Gale.

```toml
# routing/config.toml
# Every parameter: value, unit, type (observation / proxy / scenario / assumption), source.

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

# ---- one-way budget (point-to-point paths from a landing spot) ------------
[budget.destination_stop]
value = true
unit = "true | false"
type = "scenario"
source = "Team choice (Tushaar): the one-way over-budget limit counts one stop of timeline.stop_min_default at the destination; false sets it to 0"

# ---- landing safety (landing.py, export_landing.py) ----------------------
# Every limit is in metres or degrees, never in cells: the pad and the clearance are turned into
# cells from cell_m, so the same values hold on any grid. All of them are team assumptions waiting
# for Nahla's confirmation; none has a published source.
[landing.pad_radius_m]
value = 25
unit = "m"
type = "assumption"
source = "Team assumption (Tushaar), pending Nahla: radius of the circular lander pad that must be safe"

[landing.max_pad_slope_deg]
value = 5
unit = "deg"
type = "assumption"
source = "Team assumption (Tushaar), pending Nahla: tilt of the best-fit plane through the pad's DEM cells"

[landing.max_roughness_m]
value = 0.25
unit = "m (RMS of the DEM about the pad's best-fit plane)"
type = "assumption"
source = "Team assumption (Tushaar), pending Nahla: half of the yellow (careful) roughness of 0.5 m in terrain/thresholds.toml [roughness], so a pad is clearly smoother than ground that is only walkable with care. Scale differs: terrain measures RMS about the local mean in a 5 x 5 cell (25 m) window on the 5 m grid; this is RMS about a plane over the whole pad (50 m across) on the same grid"

[landing.max_height_range_m]
value = 1.0
unit = "m (highest minus lowest DEM cell on the pad, after removing the best-fit plane)"
type = "assumption"
source = "Team assumption (Tushaar), pending Nahla: catches a single step, mound or pit that the RMS roughness averages away; not a sourced lander clearance"

[landing.hazard_clearance_m]
value = 30
unit = "m (from the pad centre)"
type = "assumption"
source = "Team assumption (Tushaar), pending Nahla: no red cell, over-limit slope cell or cliff-buffer cell this close to the pad centre"

[landing.marginal_pct]
value = 20
unit = "percent of a limit"
type = "assumption"
source = "Team assumption (Tushaar): a pad that passes but is within this share of any limit is marked marginal"

[landing.ti_warn_below]
value = 150
unit = "J m^-2 K^-1 s^-1/2"
type = "assumption"
source = "terrain/thresholds.toml [thermal_inertia] yellow_below (loose sand; terrain's starting value, not checked against Jezero data). Used only for a warning flag, never a hard rule, and only while layers.json marks the thermal layer as real"

[landing.window_centre_m]
value = "site"
unit = "\"site\" (the centre of site.grid) or [x, y] in m on the site grid"
type = "scenario"
source = "Team choice: the export window is centred on the site"

[landing.window_size_m]
value = "full"
unit = "\"full\" (the whole site.grid) or [width, height] in m"
type = "scenario"
source = "Team choice: the whole site grid of layers.json; a smaller window is for the future full-crater grid"

[landing.tile_size_m]
value = 5120
unit = "m (square tiles; whole cells; edge tiles are smaller)"
type = "scenario"
source = "Team choice: 1024 cells at 5 m, so the current 2 km site is one tile and a 9,000 x 9,000 cell grid would be 9 x 9 tiles"

# Display: the colours of landing_zones.png (export_landing.py). Every other cell is fully transparent.
[landing.display_safe_rgba]
value = [46, 160, 67, 140]
unit = "[red, green, blue, alpha], each 0 to 255"
type = "scenario"
source = "Team display choice (Tushaar): semi-transparent green for safe landing cells (code 0) in landing_zones.png"

[landing.display_marginal_rgba]
value = [240, 170, 30, 140]
unit = "[red, green, blue, alpha], each 0 to 255"
type = "scenario"
source = "Team display choice (Tushaar): semi-transparent amber for marginal landing cells (code 1) in landing_zones.png"

# ---- escape from a red zone (Team outing start inside blocked ground; DESIGN section 17) ----
# Emergency estimate only: the escape rates extrapolate the walking model beyond its intended slope range.
[escape.zone_codes]
value = [2, 3, 4, 5]
unit = "mask codes (start.py): 2 red hazard, 3 slope over the limit, 4 cliff buffer, 5 sealed gap"
type = "assumption"
source = "Team assumption (Tushaar): the blocked ground a crew may walk out of in an emergency; never 1 (no data: no slope, so no speed)"

[escape.risk_rate]
value = 1.0
unit = "risk-min per min"
type = "assumption"
source = "Team assumption (Tushaar): every escape minute counts fully as risky; equal to the highest rate passable ground can reach (risk.yellow_rate, risk.near_red_rate_max), so a zone minute never counts as safer than the worst legal ground"

[escape.max_slope_deg]
value = 35
unit = "deg"
type = "assumption"
source = "Team assumption (Tushaar): about the angle of repose of loose dry granular material, where walking becomes scrambling or sliding; not relaxed for Mars gravity (traction drops with g). Above it a cell cannot be walked out of even in an emergency"
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

Start and landing (phase 10):

35. The demo start is the safe landing cell nearest the cell that holds the grid centre. It is a demonstration start, not a recommendation.
36. A destination is over budget when `walk_min + ingress_min + stop_min > usable_min` (section 15.5): one way only. One stop of `timeline.stop_min_default` is counted at the destination; `budget.destination_stop = false` sets it to 0.
37. With a window smaller than the site, paths cannot leave it. The mask, the risk and the landing codes are built on the whole grid first, so the buffer, the near-red term, the pad and the clearance see cells just outside it.
38. The landing pad is judged on the 5 m grid. Boulders smaller than a cell, and slopes shorter than one, are not seen; the hazard map is the only place a sub-cell rock could show.
39. The `[landing]` limits (section 14.3) are team assumptions pending Nahla, with the roughness scale caveat of 14.3.
40. An unsafe click moves to the nearest safe cell measured from the clicked cell's centre (up to half a cell diagonal from the true nearest to the click point). Marginal cells are accepted but never a move target.
41. The landing spot is assumed reachable on foot from where the lander sits: a safe pad is always passable (section 14.2), but it can still be walled off from a chosen destination (reason 6).

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

**Phase 10: landing safety and the browser search**

- Loick: delete the spot selection in `web/src/lib/landing.js` (`recommendLanding`). Read `data/out/landing/manifest.json` and the tiles: `landing_safety.u8` for the click, `nearest_safe.u16` / `nearest_safe_dist.f32` to move an unsafe click, and `time_rate.f64`, `risk_rate.f64`, `mask.u8` for the search. Run the Dijkstra in `pathfind.js` exactly as section 15.2 says (float64, the step-cost order, the diagonal length, strict `<`), with totals as in 15.3, and test it against `golden_cases.json` (same cells; totals within 1e-9 relative). Then `buildCost` in `pathfind.js` is no longer needed for the walk. Remove the L1–L3 markers, the Rover start marker and the team planner route from the map.
- Zakiyyah: verify or replace the stops in `waypoints.geojson`, and remove the start/rover waypoint (routing ignores it and warns).
- Nahla: confirm the `[landing]` thresholds (section 14.3): 25 m pad, 5° tilt, 0.25 m roughness, 1.0 m height range, 30 m clearance, 20% marginal band, and the thermal-inertia warning at 150. Also: the hazard source note in `layers.json` still describes the older `terrain/hazards` pipeline (3 x 3 plane roughness, thermal 250 / 150), not `hazard_map.py` and `thresholds.toml`. Which one built the current `hazard.tif`?
- Yaj: add `data/out/landing/` to `layers.json` (for example `"landing": "landing/manifest.json"`). The `shelter_time` layer's title still says "Minutes back to rover".
- Team: `CONTRACT.md` still describes `kind` as `"rover"` or `"stop"`, and `data/validate.py` rejects any other kind.

**Loick (front end)**

- `totals.total_min` in `plan.json` now includes ingress (walk + stops + ingress), which the fake file did not. `totals.ingress_min` is added so the parts still sum. Does anything in the app assume the old meaning?
- Will the app show all three routes, with a way to switch?
- Is `plan.json` `track[]` (distance, elevation, slope, elapsed, minutes back to the start) enough for the slope profile and the timeline chart?
- Contour lines are burned into `shelter_time.png`. Is that fine, or do you want to draw them yourself?
- `plan.json` grows to roughly 120 kB with the track and return paths. Any problem?

## 13. The per-start reach export (removed)

Phases 8 and 9 exported, for each of three configured landing spots, the best path from that spot to every cell (`export_reach.py`, `data/out/reach/`). It was removed in phase 10: the landing spots came from fake data, and the user now picks any landing spot, so the browser runs the search itself on the exported cost surface (section 15). The one-way over-budget rule of that export is kept unchanged in section 15.5.

## 14. Landing safety (`landing.py`)

The user clicks anywhere to choose a landing zone. Every cell gets a safety code for a lander pad centred on it; an unsafe click is moved to the nearest safe cell.

### 14.1 The pad and its measures

- **Pad:** the cells whose centre is within `landing.pad_radius_m` (25 m) of the centre cell's centre: 81 cells at 5 m, more on a finer grid. Every limit is in metres or degrees and turned into cells from `cell_m`.
- **Tilt:** the slope of the least-squares plane `z = a + b·x + c·y` through the pad's DEM heights, `atan(hypot(b, c))` in degrees. It uses the whole pad, not the centre cell's own slope. The steepest single 5 m cell on the pad is not used: at that scale it is noisy (median 6.7° over the all-green pads of the current site against a median plane tilt of 2.5°).
- **Roughness:** RMS of the DEM about that plane over the pad. `layers.json` lists no roughness layer, so it is computed from `dem.tif`. If terrain's roughness becomes a real layer (`id` "roughness", `roughness.tif`), the pad roughness becomes its maximum over the pad, compared with the same limit.
- **Height range:** highest minus lowest pad cell about the plane. The raw range is not used, because the allowed 5° tilt alone gives 4.4 m across 50 m and would only repeat the slope rule; the range about the plane catches a single step, block or pit that the RMS averages away.
- **Clearance:** distance from the centre cell's centre to the nearest red, over-limit-slope or cliff-buffer cell (`distance_transform_edt`, metres).
- **Hazard:** any pad cell that is not green, or that is blocked for walking (section 4.1).
- **Coverage:** the pad and the clearance circle (the larger of the two radii) must fit inside the grid; any NaN DEM or slope on the pad is "no data".

### 14.2 Codes (`landing_safety.u8`)

| Code | Name | Fails when |
| --- | --- | --- |
| 0 | safe | nothing fails and nothing is within the marginal band |
| 1 | marginal | nothing fails, but tilt, roughness or height range is above (1 − `landing.marginal_pct`/100) × its limit, or the clearance is below (1 + `marginal_pct`/100) × its limit |
| 2 | outside_coverage | the pad or the clearance circle reaches past the grid edge |
| 3 | no_data | a pad cell has no DEM or slope value |
| 4 | hazard_or_clearance | a pad cell is not green or is blocked, or the clearance is below `landing.hazard_clearance_m` (30 m) |
| 5 | too_steep | tilt > `landing.max_pad_slope_deg` (5°) |
| 6 | height_range | range > `landing.max_height_range_m` (1.0 m) |
| 7 | too_rough | roughness > `landing.max_roughness_m` (0.25 m) |

When several failures apply, **the lowest code wins**: outside coverage > no data > hazard or clearance > too steep > height range > too rough. The order puts first what makes the other measures meaningless (no data, no coverage), then what is dangerous whatever the terrain (hazards), then the terrain measures from the most to the least severe. Because blocked cells fail rule 4, a safe or marginal cell can always be walked from.

On the current site: 30,564 safe, 15,243 marginal, 9,456 outside coverage, 66,518 hazard or clearance, 7,731 too steep, 30,326 height range, 162 too rough. The 0.25 m roughness limit rarely decides on its own: the 1.0 m height range catches most rough pads first.

**Warnings (`landing_warn.u8`, bits, never a rule):** bit 1 when a pad cell's THEMIS thermal inertia is below `landing.ti_warn_below` (150, loose ground), bit 2 when a pad cell has no thermal-inertia value. Only checked while `layers.json` marks the `thermal` layer as real and `thermal_inertia.tif` exists; otherwise the grid is all zero and the manifest says so. On the current data the lowest value is 241, so no pad is flagged.

### 14.3 Where the thresholds come from

All seven are team assumptions pending Nahla (type `assumption` in `config.toml`); none has a published source.

- 25 m pad, 5° tilt, 30 m clearance: the team's starting values.
- **Roughness 0.25 m:** half of terrain's yellow (careful) roughness of 0.5 m in `terrain/thresholds.toml` [roughness], the current file read by `terrain/hazard_map.py`. A pad should be clearly smoother than ground that is only walkable with care. **Scale caveat:** terrain's roughness is the RMS about the local mean in a 5 x 5 cell (25 m) window on the 5 m grid; the older `terrain/hazards` pipeline (`terrain/config/hazards.yaml`, 0.15 / 0.40 m) used a 5 m window on 1 m data; ours is the RMS about one plane over the whole 50 m pad on the 5 m grid. The three numbers are not directly comparable. (An earlier proposal of 0.15 m came from that older file, which is no longer the live one.)
- **Height range 1.0 m:** a team assumption, not a sourced lander clearance.
- **Thermal inertia 150:** `terrain/thresholds.toml` [thermal_inertia] `yellow_below`, terrain's loose-sand value (itself a starting value, not checked against Jezero data).
- Marginal band 20%: team choice.

### 14.4 Nearest safe cell and the landing check

`nearest_safe`: `scipy.ndimage.distance_transform_edt(codes != 0, sampling=cell_m, return_indices=True)` gives, for every cell, the row and column of the nearest **safe** (code 0) cell and the distance between the two cell centres in metres. Marginal cells are accepted where they are clicked but are never a move target. Ties go to the cell scipy returns, which is the same on every run. With no safe cell in the window the run stops with an error.

`landing_check(x, y)` (reference: `export_landing.landing_check`, `landing.LandingMap.landing_check`) returns `{status, reasons, chosen_xy_m, moved_m}` plus `code`, `code_name`, `cell`, `chosen_cell` and `warnings`:

- safe or marginal cell: `status` "safe" / "marginal", `chosen_xy_m` = the clicked point, `moved_m` = 0. A marginal result lists the limits it is close to (`near_too_steep`, ...).
- any other cell: `status` "moved", `chosen_xy_m` = the centre of the nearest safe cell, `moved_m` = the straight-line distance from the click to it (a lander comes down from above, so no walking path is needed). The move target is the nearest safe cell to the clicked cell's centre, so it can be up to half a cell diagonal from the true nearest to the click.
- outside the grid: `status` "outside", nothing chosen.

### 14.5 Measured values, the zones image and the messages

**Measured grids** (per tile, float32, the values `landing.measure` computes and `failures` compares with the limits; nothing is recomputed for the export):

| File | Value (14.1) | Unit | Limit (`[landing]`) | Fails when |
| --- | --- | --- | --- | --- |
| `pad_slope_deg.f32` | tilt of the best-fit plane | deg | `max_pad_slope_deg` | value > limit |
| `pad_roughness_m.f32` | roughness | m | `max_roughness_m` | value > limit |
| `pad_height_range_m.f32` | height range about the plane | m | `max_height_range_m` | value > limit |
| `hazard_dist_m.f32` | clearance: cell centre to the nearest red, over-limit-slope or cliff-buffer cell | m | `hazard_clearance_m` | value < limit |

- **NaN** in the first three means not computed: the pad or its clearance circle does not fit inside the site grid (code 2) or a pad cell has no DEM or slope value (code 3).
- `hazard_dist_m` is computed for every cell and is **never NaN**. It is **+Infinity** when the site grid has no red, over-limit-slope or cliff-buffer cell at all; a `Float32Array` reads it as `Infinity`, and no message shows a distance then. NaN is kept for "no data" only.
- The codes are decided on the float64 values, so a stored float32 value can sit exactly on a limit that its code says it crossed.
- The manifest's `grids` entry of each carries `unit`, `limit_key`, `limit`, `fails_when` and `decimals`; `measured_note` repeats the NaN and Infinity rules.

**`landing_zones.png`**: one RGBA image for the whole window (not per tile), one pixel per cell, row 0 = north. It covers `origin_m` to `origin_m + extent_m`, so with the default window it has the size and placement of `hazard.png`. Safe cells (code 0) are `landing.display_safe_rgba`, marginal cells (code 1) `landing.display_marginal_rgba` (semi-transparent green and amber, team display choices in `config.toml`); every other cell is `[0, 0, 0, 0]`. The manifest's `zones_png` holds the file, size, placement and the legend (code, name, rgba, label).

**`landing_check` additions.** The result also has:

- `measured`: the four values at the clicked cell, `chosen_measured`: at the chosen cell. Keys are the grid names; a NaN is `None`, the float32 value otherwise (so `math.inf` is possible for `hazard_dist_m`). Both are `None` for a click outside the grid, or on a folder written before these grids.
- `messages`: one `{reason, code, title, detail, moved_m}` per entry of `reasons`, in that order. A safe point gets the one `safe` message, a marginal point with no `near_*` reason the one `marginal` message, a click outside the data the one `outside` message.
- `moved_text`: "Landing spot moved 113.9 m to the nearest safe spot." when the click was moved, else `None`.
- `reasons` for a failing cell now always includes the stored code's own name.

**Templates.** The text lives once, in `landing.MESSAGE_TEMPLATES`, and is copied to the manifest as `message_templates`: `templates` (per reason: `code`, `measure`, `title`, `detail`, sometimes `detail_no_value`, and for a measured reason `limit_key`, `limit`, `decimals`), `moved`, `moved_decimals`, `fields` (`pad_radius_m`, `marginal_pct`, `reach_m`), `rules` and `reasons`. There is a template for every code 0 to 7, for the four `near_*` reasons and for `outside`. To fill one:

- `{value}` is the template's `measure` grid at the **clicked** cell, with `decimals` fixed decimals, halves rounded up (JavaScript `toFixed`; `landing.fixed` does the same). `{moved_m}` has 1 decimal the same way.
- `{limit}`, `{pad_radius_m}`, `{marginal_pct}`, `{reach_m}` are written in their shortest form (`String(number)`).
- Use `detail_no_value` instead of `detail` when the template has one and the value is missing, NaN or Infinity, or, for `hazard_or_clearance` only, when the value is not below the limit: the pad then fails on one of its own cells, not on the distance, so no distance is shown.

**Reasons from the files.** The browser has the code and the four values: a failing cell's reasons are its stored code, plus `too_steep` / `height_range` / `too_rough` where the value is above its limit and `hazard_or_clearance` where `hazard_dist_m` is below its limit, lowest code first; a marginal cell's are the `near_*` tests of 14.2. This is what `Landing.load(...).landing_check` does, and it equals the computed map except under codes 2 and 3, where a pad-cell hazard is not in the files (`test_messages_from_the_manifest_match_landing_check_everywhere`).

## 15. The cost surface and the browser's search (`export_landing.py`)

The browser runs the search from any landing spot, so it gets exactly what the Python search uses, and the exact rule.

### 15.1 Grids

`time_rate.f64` (minutes per metre, −1 where blocked), `risk_rate.f64` (risk-minutes per minute walked, 0 where blocked) and `mask.u8` (0 passable, else the blocked reason 1–5 of section 4.9) are `cost.build`'s `time_rate`, `risk_rate` and the block codes, bit for bit. They are float64 so the browser computes the same numbers: rounding them to float32 would change paths. They do not depend on the profile; only w does. They are written once, not per profile, and the browser forms the planning rate itself.

### 15.2 The edge rule (what `MCP_Geometric` does here, checked bit for bit)

For profile weight w (fastest 0, balanced 1, safest 5):

1. Planning rate per cell, in float64: `p = time_rate × (1 + w × risk_rate)`, multiplied in that order (`w × risk_rate`, then `1 +`, then `time_rate ×`). Cells with `mask ≠ 0` are impassable.
2. Neighbours: the 8 cells around the current one (`search.connectivity` = 8). A neighbour outside the window, or with `mask ≠ 0`, is never entered. No corner check is needed: the sealing rule (section 4.1) has already blocked every free cell that two diagonal blocked cells would squeeze.
3. Step length `L`: `cell_m` for a straight step; `sqrt(cell_m × cell_m + cell_m × cell_m)` for a diagonal one. (This is how skimage builds it from `sampling`; it can differ from `cell_m × sqrt(2)` in the last bit.)
4. Step cost from cell a to cell b: `L × (p_a + p_b) / 2`, evaluated as `L × (p_a + p_b)` then `/ 2`. The skimage docstring writes `(L/2)·p_a + (L/2)·p_b`, which differs in the last bit; the form here is the one that matches.
5. Dijkstra from the landing cell, cost 0. A neighbour is updated only when `g + step < g_neighbour` (strictly less).
6. The path is the chain of predecessors from the destination back to the landing cell, reversed.

`tests/replay.py` is a plain Dijkstra written only from these six lines. On random grids and on the export, its cumulative costs equal `MCP_Geometric.find_costs` exactly, for every reachable cell and all three profiles (`test_export_landing.py::test_the_edge_rule_reproduces_mcp_cumulative_costs_bit_for_bit`). Paths agree unless two paths cost exactly the same, which does not happen in the golden cases. On ties the two heaps may pick differently, and both answers are optimal.

### 15.3 Totals along a path

Taken after the path is found, in path order from the landing cell, in float64, as `search.summarise` defines them (section 4.3). Here `step_m` is `cell_m` straight and `cell_m × sqrt(2)` diagonal:

```
distance_m += step_m
walk_min   += step_m × (time_rate_a + time_rate_b) / 2
risk_min   += step_m × (time_rate_a × risk_rate_a + time_rate_b × risk_rate_b) / 2
```

`walk_min` is physical time: risk never inflates it. `summarise` adds the three risk parts separately, so its `risk_min` can differ from this single sum in the last digits; golden totals are compared within 1e-9 relative.

### 15.4 Reference route and golden cases

`export_landing.route(landing_xy, dest_xy, profile)` gives the output the front end will produce: a GeoJSON Feature with a `LineString` of cell centres (`[x, y]` metres, landing first) and `profile`, `w`, `reachable`, `reason`, `reason_text`, `distance_m`, `walk_min`, `risk_min`, `needed_min`, `over_budget`, `landing_cell`, `dest_cell` and `cells` (`[row, col]` in window cells). With no path the geometry is null and `reason` is a mask code (1–5) for a blocked destination, 6 for walled off, `"outside"` for a point outside the window, or `"landing_blocked"`.

`golden_cases.json`: 10 landing/destination pairs between real safe cells × 3 profiles, computed by that function. The landing spots are the nearest safe cells to a 3 x 3 lattice over the window (1/6, 1/2, 5/6 of each side), each paired with the spot half the list away. There are 8 ordinary pairs, one destination that is passable but walled off from the first spot (or a blocked cell if none is walled off; on a site where every cell is reachable the case is left out and `skipped` says why), and one over-budget case. No walk on a 2 km site comes near the 212 min limit, so the over-budget case is the longest pair under its own smaller test budget, stored in the case: the same rule with an `eva_max_min` that leaves about half of that walk.

### 15.5 Over budget (unchanged from the old reach export)

```
usable_min        = eva_max_min × (1 − reserve_pct / 100)                       252 with the current values
stop_min          = timeline.stop_min_default if budget.destination_stop else 0  25
walk_limit_min    = usable_min − ingress_min − stop_min                         252 − 15 − 25 = 212
needed_min        = walk_min + ingress_min + stop_min                           for one destination
```

One way only: no return walk is counted. A destination is over budget when `needed_min > usable_min`, i.e. when `walk_min > walk_limit_min`. The manifest carries every number and the rule text.

## 16. Files, window and tiles

```
data/out/landing/
  manifest.json
  golden_cases.json
  golden_escape_cases.json
  landing_zones.png
  tiles/<ti>_<tj>/landing_safety.u8  landing_warn.u8  nearest_safe.u16  nearest_safe_dist.f32
                  time_rate.f64  risk_rate.f64  mask.u8
                  pad_slope_deg.f32  pad_roughness_m.f32  pad_height_range_m.f32  hazard_dist_m.f32
                  escape_time_rate.f64  escape_risk_rate.f64
```

| File | Type | Values per cell |
| --- | --- | --- |
| `landing_safety.u8` | uint8 | the code of section 14.2 |
| `landing_warn.u8` | uint8 | warning bits (14.2) |
| `nearest_safe.u16` | uint16 | 2: `[2i]` = row, `[2i+1]` = col of the nearest safe cell, in **window** rows/cols (not tile rows/cols) |
| `nearest_safe_dist.f32` | float32 | metres, cell centre to cell centre |
| `time_rate.f64`, `risk_rate.f64` | float64 | 15.1 |
| `mask.u8` | uint8 | 15.1 |
| `pad_slope_deg.f32`, `pad_roughness_m.f32`, `pad_height_range_m.f32` | float32 | the measured pad values of 14.5; NaN where not computed |
| `hazard_dist_m.f32` | float32 | metres to the nearest hazard cell (14.5); never NaN, +Infinity when there is none |
| `escape_time_rate.f64`, `escape_risk_rate.f64` | float64 | 17.2 |
| `landing_zones.png` (one for the window) | RGBA PNG | safe and marginal cells in colour, the rest transparent (14.5) |

Raw values, no header, little-endian, row-major inside each tile, row 0 = the tile's north edge. The u16 limits a window to 65,536 cells a side, enough for a 9,000 x 9,000 cell crater grid.

**Window.** `landing.window_centre_m` ("site" or `[x, y]`) and `landing.window_size_m` ("full" or `[width, height]`, metres) pick the exported box, snapped outward to whole cells; it must lie inside the site grid. The defaults ("site", "full") give the whole site grid. Safety codes and the cost are computed on the whole site grid and then cut, so the pad, the clearance and the cliff buffer see cells just outside the window. `nearest_safe` is computed on the whole window before tiling, so it is right across tile edges; it never points outside the window. The browser only searches inside the window.

**Tiles.** `landing.tile_size_m` (5120 m) must be a whole number of cells (1024 at 5 m); the window is cut into square tiles from its north-west corner, and the tiles on the south and east edges are smaller. With the defaults the current 400 x 400 site is one tile; a 9,000 x 9,000 grid at 5 m would be 9 x 9 tiles. Crater-scale processing is not built: the whole site grid is still loaded in memory. Only the formats and the functions are ready for it.

**Manifest** (`manifest.json`): `format_version` (1), `site`, `fake` (same rule as `plan.json` `inputs_fake`); `grid` (`width`, `height`, `cell_m`, `origin_m` = the south-west corner of the window in site metres, `extent_m`, `row0` "north edge", `window` and `site_grid`); `layout` (cell formulas, tile lookup, the `nearest_safe` layout, the search bound); `byte_order` "little"; `grids` (file, dtype, values per cell, meaning, and for the measured grids unit, limit and `fails_when`); `measured_note`; `zones_png` (file, size, placement, legend); `message_templates` (14.5); `tile_size_m`, `tile_cells`; `tiles` (per tile: `index` [ti, tj], `row0`, `col0`, `shape` [rows, cols], `origin_m`, `files`); `safety_codes`, `safety_order`, `safety_counts`, `warning_bits`, `landing_rule`; `thresholds` (the `[landing]` entries of the config with value, unit, type and source); `roughness_source`, `roughness_note` (the scale caveat), `height_range_note` (a team assumption); `thermal_inertia` (checked or not, and why); `mask_codes`; `profiles` (w); `search` (connectivity and the edge rule of 15.2–15.3); `budget` (15.5); `golden_cases`; `escape` (17.2); `config_sha256`; `inputs_sha256` (`dem.tif`, `hazard.tif`, and `thermal_inertia.tif` when used); `files` (bytes and SHA-256 of every file); `warnings`. There is no timestamp: the same inputs give the same bytes.

**Size on the current site:** 160,000 bytes for each u8 grid, 640,000 for `nearest_safe.u16` and `nearest_safe_dist.f32`, 1,280,000 for each f64 grid, plus 174,508 bytes of golden cases and 11,974 of manifest: 4,506,482 bytes in 9 files before the measured grids. The four measured f32 grids add 640,000 bytes each and `landing_zones.png` 18,577; the manifest is now 21,943 bytes: **7,095,045 bytes (7.10 MB) in 14 files**, against 19.2 MB for the old reach export. The two escape f64 grids add 1,280,000 bytes each and `golden_escape_cases.json` 37,302; the manifest is now 24,951 bytes: **9,695,355 bytes (9.70 MB) in 17 files**. The grids scale with the number of cells: 57 bytes per cell. `format_version` stays 1: the change only adds files and fields.

## 17. Walking out of a red zone (`escape.py`)

A Team outing may start inside blocked ground (a red zone). The web app (`web/src/lib/escape.js`) then walks the crew out first and plans the normal route from the exit. Normal routing is unchanged: the mask, `time_rate.f64`, `risk_rate.f64` and `golden_cases.json` keep their bytes, and the normal search still never enters a blocked cell.

**Emergency estimate only (team assumption).** Escape speeds apply the walking model (section 5) to slopes above `constraints.slope_max_deg`, which is beyond the range it was meant for. The escape times are rough. `escape.risk_rate` and `escape.max_slope_deg` are team assumptions with no sources.

### 17.1 Parameters (`[escape]`, all `assumption`)

| Key | Value | Why |
| --- | --- | --- |
| `zone_codes` | `[2, 3, 4, 5]` | red hazard, over-limit slope, cliff buffer, sealed gap. Never 1 (no data: no slope, so no speed). The loader accepts only distinct codes from 2 to 5. |
| `risk_rate` | 1.0 risk-min per min | Every escape minute counts fully as risky. It equals the highest rate passable ground can reach (`risk.yellow_rate`, `risk.near_red_rate_max`), so a zone minute never counts as safer than the worst legal ground. |
| `max_slope_deg` | 35° | About the angle of repose of loose dry granular material, where walking turns into scrambling or sliding. Not relaxed for Mars gravity (traction drops with g). The model gives 0.23 km/h there. On the current site this excludes 205 of 7,190 zone cells (2.9%); 30° would exclude 839 and 40° would exclude 52. |

### 17.2 Grids

- `escape_time_rate.f64` (min/m): in cells whose mask code is in `zone_codes` and whose slope is ≤ `max_slope_deg`, it is `cost.time_rate` at that cell's slope (the same function, formula and parameters, so the bits are the same), not clipped by the 20° limit. Everywhere else it is −1: passable ground, no data, codes left out of `zone_codes`, slopes above `max_slope_deg`, and NaN slope.
- `escape_risk_rate.f64` (risk-min per min): `risk_rate` in those same cells, and 0 elsewhere.

Current site: **6,985** zone cells have a finite rate and **205** are excluded by `max_slope_deg`. The manifest gives each grid's unit, dtype and the meaning of −1 or 0, and an `escape` block with `zone_codes`, `risk_rate`, `max_slope_deg`, `cell_counts`, `rule`, `note` and `golden_cases`.

### 17.3 The rule the web app applies

1. **Zone.** The zone is the 8-connected region of cells whose mask code is in `zone_codes` and that contains the start. If the start is not in such a zone, the normal outing applies.
2. **Start too steep.** If `escape_time_rate` at the start is < 0, there is no exit, with reason `start_too_steep`: the start is steeper than `max_slope_deg`, so the crew cannot walk out.
3. **Phase 1.** Dijkstra runs from the start inside the zone with the edge rule of 15.2. Zone cells use the escape rates and exit cells use their normal rates. A zone cell with `escape_time_rate < 0` is never entered. An exit is a passable cell (mask 0) next to the zone; it is entered in one step and never expanded further.
4. **Exit.** Among the exits that lie in the destination's 8-connected passable region, pick the one with the lowest escape cost at w = 0 (physical minutes). If there is none, the result is `no_exit`. Exact ties go to the lowest total planning cost for the profile, which is the escape at w plus the normal search from the exit. The escape walk is the same for every profile.
5. **Phase 2.** The normal search (15.2) runs from the exit and never re-enters blocked ground, including the zone.
6. **Totals.** The escape totals use 15.3 with the escape rates in the zone. The full totals are escape plus route (distance, walk, risk). `needed_min` = total walk + `ingress_min` + `stop_min`, and the route is over budget when the total walk exceeds `walk_limit_min`.

`escape.Escape.plan` is the reference. `Landing.load` builds it as `Landing.escape` when the folder has the escape grids, and sets it to `None` for an older folder.

### 17.4 Golden escape cases (`golden_escape_cases.json`)

The destination is the safe landing cell nearest the window centre. Each case is given for all three profiles.

- `escape1`–`escape3`: the deepest eligible cell of each of the three largest zones that have a valid exit (1,664, 1,434 and 424 cells). The escape walks are 42.4 m / 5.70 min, 48.3 m / 4.19 min and 26.2 m / 3.14 min.
- `start_too_steep`: the deepest zone cell above 35°.
- `no_exit`: the destination is a cell in a walled-off passable pocket (68 cells), and the start is in the largest zone, which does not border that pocket. On the current data every zone has an exit to the main ground, so this is the only real no-exit case.

Each case gives the start and destination cells and points, the start's mask code and escape rate, and per profile `status`, `reason`, `zone_cells`, `exits_found` and `tie`. For an ok result it also gives `escape` (exit cell and point, cells, distance_m, walk_min, risk_min), `route` (cells and totals) and `total`. `tests/test_escape.py` checks them against an independent replay written from the rule text.
