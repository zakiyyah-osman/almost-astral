# routing/ design

What the route planner does and why. Build order is in `CHECKLIST.md`; independent checks are in `QA.md`.

Status: design only, nothing is built yet. Items still waiting for a decision are collected in sections 11 and 12.

## 1. Scope

Reads from `data/out/` (never writes these):

| File | Used for |
| --- | --- |
| `layers.json` | `site.grid` (width, height, cell_m), site name, whether inputs are still fake |
| `dem.tif` | terrain slope, elevation along the route |
| `hazard.tif` | red cells (blocked) and yellow cells (penalised) |
| `waypoints.geojson` | the rover and the science stops |
| `radiation.csv` | cross-check of the background rate, storm hours for the demo |

Writes to `data/out/`:

| File | Contract status |
| --- | --- |
| `route.geojson` | contract file: the balanced route |
| `shelter_time.png` | contract file |
| `plan.json` | contract file, with added fields (section 9) |
| `route_fastest.geojson`, `route_safest.geojson` | new files, same format as `route.geojson` |

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
| `shelter.py` | minutes-to-rover array and its PNG rendering |
| `storm.py` | return paths from sampled route points |
| `timeline.py` | legs, totals, track samples, budget checks, radiation |
| `outputs.py` | writers for the GeoJSON files and `plan.json` |
| `analysis.py` | the w-sweep function, sensitivity runs, hard-mask validation against the Perseverance traverse. Run as a script it writes CSV reports only |
| `plan_route.py` | wires everything; takes the command-line options below |
| `tests/` | pytest, on small synthetic grids built in `conftest.py`; only the end-to-end test reads `data/out/` |
| `docs/` | `DESIGN.md`, `CHECKLIST.md`, `QA.md` |
| `reports/` | CSV tables from `analysis.py` |

**Command-line options.**

| Option | `plan_route.py` | `analysis.py` | Meaning | Default |
| --- | --- | --- | --- | --- |
| `--in DIR` | yes | yes | folder the inputs are read from | `data/out` |
| `--config FILE` | yes | yes | parameter file | `routing/config.toml` |
| `--out DIR` | yes | no | folder the route files, `shelter_time.png` and `plan.json` are written to | the value of `--in` |
| `--reports DIR` | no | yes | folder the CSV reports are written to | `routing/reports` |

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
waypoints.geojson ─► snap to cells, check passable ──► MCP_Geometric from each waypoint
                                                                                     │
                                          stop order ─► fastest / balanced / safest routes
                                                                                     │
                 MCP_Geometric from rover, w = 0 ─► shelter-time array ─► shelter_time.png
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

So `planning cost = physical_min + w × risk_min` holds exactly, and only `physical_min` goes into the timeline, the shelter map, the budgets and `plan.json`. Risk never inflates a reported time.

### 4.4 Slope is the terrain slope, not the slope along the path

`MCP_Geometric` takes one cost per cell, so `v(S)` uses the steepest slope of the terrain at that cell. Walking along a contour is timed as slowly as climbing straight up. This overestimates time on slopes, which is the safe direction, and it keeps one model for routes, the shelter map and storm returns.

The direction-aware alternative is `MCP_Flexible` with `travel_cost` overridden and elevation as the cost array. Its hook receives only the two cell values, so blocks and risk would need a workaround. It is recorded as a possible upgrade and is not part of this design. This choice is listed in section 11.

Because the cost is the same in both directions, the time from A to B equals the time from B to A. One search from the rover therefore gives the time back to the rover from every cell.

### 4.5 Search

- `MCP_Geometric(planning_rate, fully_connected=True, sampling=(cell_m, cell_m))`.
- `find_costs` from each waypoint gives the cost to every other waypoint; `traceback` gives the path as cells.
- It is Dijkstra-based and returns the same optimum A* would. `README.md` and `docs/work-split.md` say A*; the result is identical.
- 8 neighbours, horizontal distance. A grid path is up to about 8% longer than a free-angle path, so distances and times lean high.

### 4.6 Waypoints and stop order

- A point `(x, y)` snaps to the cell that contains it. Route vertices are cell centres, so a marker can sit up to half a cell diagonal from the line.
- Exactly one `kind: "rover"` is required.
- A stop on a blocked cell, or with no path to the rover, stops the run with a non-zero exit code. The message names the stop id, its name, its coordinates and the reason (red cell, slope over limit, inside buffer, unreachable). No output file is written.
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
- **Hard-mask validation:** the share of Perseverance traverse points that fall on passable cells, reported in `reports/validation.csv`. A rover drove there, so a low share means the mask is too strict. Blocked until Yaj supplies the traverse in grid coordinates (section 12).

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

## 6. Shelter map

- One `MCP_Geometric` run from the rover cell on `time_rate` (w = 0) gives the fastest physical minutes from every cell.
- `shelter_min = walk minutes + timeline.ingress_min`. At the rover cell it equals the ingress time.
- Blocked and unreachable cells have no value.

`shelter_time.png` is RGBA, exactly `width x height`, row 0 at the north edge. Cells are coloured on a ramp from 0 to `shelter_map.colour_max_min` (longer times take the last colour). Contour lines are burned in wherever a cell and a neighbour fall in different `shelter_map.contour_interval_min` bands. Cells with no value are fully transparent.

The web app cannot read minutes back out of a picture, so `plan.json` carries the legend (`shelter_map`: colour stops, interval, maximum) and the exact value at each track point (`track[].shelter_min`).

## 7. Storm re-plan

- Sample the balanced route every `storm.sample_spacing_m`, and at every stop.
- For each sample, the return path is the `traceback` from the rover-rooted search of section 6: the fastest physical way back, ignoring risk weights but never crossing a blocked cell.
- Each sample reports where it is, how far along the route, elapsed minutes on arrival, `return_min` (walk plus ingress), `return_distance_m` and the return path.
- `worst` points at the sample with the largest `return_min`.

**Solar-event dose.** Curiosity RAD measured 8.1 mGy absorbed dose on 20 May 2024 (NASA). `plan.json` reports it in its own field, in Gy, as the whole-event figure for someone who stays unsheltered. It is never converted to Sv and never added to `radiation_dose_usv`. Scaling it by the return time would need the event's duration, which this design has no source for (section 11).

## 8. Timeline and budgets

**Times.**

```
walk_min    = sum of physical_min over legs
stop_min    = sum of stop durations (timeline.stop_min_default each)
ingress_min = timeline.ingress_min
total_min   = walk_min + stop_min + ingress_min
```

The clock starts when the crew leaves the rover. Legs run rover → stops → rover. Each leg records arrival and departure times, so the web app can draw the timeline.

**Track.** The balanced route sampled every `track.spacing_m`: position, distance, elevation, slope, hazard class, elapsed minutes, minutes back to shelter. `elapsed_min` is clock time since leaving the rover, so it includes the time spent at every stop already visited, not only walking time. It feeds the slope profile chart and the HUD.

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

`route.geojson`, `route_fastest.geojson` and `route_safest.geojson`: a `FeatureCollection` with one `LineString`, coordinates `[x, y]` in metres, rover to rover. Vertices on a straight run are dropped, which changes nothing about the line. No `fake` property.

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
      "from": "rover", "to": "stop1", "distance_m": 812, "walk_min": 21,
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
      "note": "Whole-event absorbed dose if unsheltered. In Gy; not added to radiation_dose_usv."
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
source = "Team choice: rate next to a red cell, falling to 0 at the radius"

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
source = "Team choice, confirmed by Tushaar"

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

# ---- shelter map --------------------------------------------------------
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

15. The clock starts outside the rover; egress time is not counted.
16. `total_min` includes ingress, which the fake `plan.json` did not.
17. Oxygen and battery are folded into `eva_max_min`.
18. `stop_order` defaults to `as_listed`.
19. The Sv dose uses the config background rate, not the hourly values in `radiation.csv`.
20. The 8.1 mGy figure is reported as a whole-event value. There is no event duration here, so it is not scaled to the time needed to reach shelter.
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

**Loick (front end)**

- `totals.total_min` in `plan.json` now includes ingress (walk + stops + ingress), which the fake file did not. `totals.ingress_min` is added so the parts still sum. Does anything in the app assume the old meaning?
- Will the app show all three routes, with a way to switch?
- Is `plan.json` `track[]` (distance, elevation, slope, elapsed, shelter minutes) enough for the slope profile and the timeline chart?
- Contour lines are burned into `shelter_time.png`. Is that fine, or do you want to draw them yourself?
- `plan.json` grows to roughly 100 kB with the track and return paths. Any problem?
