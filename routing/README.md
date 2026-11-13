# routing/ (Person 3: route planning and safety)

Plans the walk between the science stops and checks that it is safe: three routes (fastest, balanced, safest), a map of the minutes back to the rover from every cell, the EVA timeline with its budgets, and the fastest way home from any point of the walk.

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
python routing/plan_route.py         # routes, shelter map and plan
python data/validate.py              # checks data/out/ against CONTRACT.md
```

`make_fake.py` overwrites `route.geojson`, `plan.json` and `shelter_time.png` with fake versions, so run `plan_route.py` after it every time. Once the real data is in `data/out/`, run `plan_route.py` after any change to `dem.tif`, `hazard.tif`, `waypoints.geojson` or `routing/config.toml`.

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

The command prints the status, the totals, the three profiles and any warning. A plan that goes over a budget is still written, with status `over_budget` and a warning, so the map stays usable. If a stop is on a blocked cell, a stop cannot be reached, or an input is missing or malformed, the run stops with a message that names the problem, exits with a non-zero code and writes nothing.

## Sweep and sensitivity

```bash
python routing/analysis.py                                   # reads data/out, writes routing/reports/
python routing/analysis.py --in DIR --config FILE --reports DIR
```

Writes two CSV files into `--reports` (default `routing/reports`) and nothing else; it has no `--out` and never writes to `data/out`.

- `sweep.csv`: the time against risk-exposure table. One row per weight in `profiles.sweep_w`: distance, walk minutes, and risk minutes split into `yellow_min`, `steep_min` and `near_red_min`. The same rows are in `plan.json` under `sweep`.
- `sensitivity.csv`: every combination of the walking speed, the slope limit and w from the `[sensitivity]` section of `config.toml` (18 runs). Each row has the walk, total and risk minutes and the budget `status` (`ok` or `over_budget`), or `infeasible` with the `failed_stop` (the rover or stop that is on a blocked cell or cannot be reached) and the `reason`.

## Inputs

Read from the `--in` folder: `layers.json` (grid size, site name, whether layers are fake), `dem.tif`, `hazard.tif`, `waypoints.geojson` (exactly one `rover` and at least one `stop`) and `radiation.csv`. `dem.tif` and `hazard.tif` must have the pixel size in `layers.json`, be north-up and share one geotransform.

## Outputs

Written to the `--out` folder (default `data/out`):

| File | What it is |
| --- | --- |
| `route.geojson` | the balanced route, rover to stops and back (contract file) |
| `route_fastest.geojson` | the fastest route, same format |
| `route_safest.geojson` | the safest route, same format |
| `shelter_time.png` | minutes back to the rover for every cell, with contour lines (contract file) |
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
- `track[]`: the balanced route sampled every `track.spacing_m` and at each stop, for the slope profile and the timeline: `distance_m`, `x`, `y`, `elev_m`, `slope_deg`, `hazard`, `elapsed_min` (clock time, including time at stops already visited) and `shelter_min` (minutes back to the rover, ingress included). Stop arrivals also carry `stop`.
- `storm_replan`: the fastest way back from points of the route. `points[]` have `x`, `y`, `route_distance_m`, `elapsed_min`, `return_min`, `return_distance_m` and `path` (a list of `[x, y]` ending at the rover); `worst` is the index of the point with the longest way back.
- `shelter_map`: the legend for `shelter_time.png` (the colour stops, `colour_max_min`, `contour_interval_min`, `includes_ingress`), because the app cannot read minutes back out of a picture. The exact value at each point of the walk is in `track[].shelter_min`.
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

Most tests use small synthetic grids. `test_end_to_end.py` reads the real `data/out/`, so run `plan_route.py` first.

## More

- [docs/DESIGN.md](docs/DESIGN.md): what the planner does and why, and the assumptions still to confirm.
- [docs/CHECKLIST.md](docs/CHECKLIST.md): the build order and what is done.
