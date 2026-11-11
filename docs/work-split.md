# Work split for 5 people

Each person owns one part from start to finish: work before Saturday, work on Saturday, and clear files they hand to others. The workloads are roughly equal, about 12 to 15 hours each before Saturday.

## Person 1: Yaj, Data lead (`data/`)

**Before Saturday**
- Write and maintain `layers.json`, the data format everyone else reads.
- Download public data for the site: HiRISE terrain model and imagery, THEMIS thermal map, CRISM mineral maps.
- Collect weather data (Curiosity REMS) and radiation data (Curiosity RAD, plus the NASA DONKI API for solar storms) into `weather.csv` and `radiation.csv`.
- Keep the fake-data generator (`make_fake.py`) working so nobody waits for a missing layer.
- Crop and align every layer to the same grid.

**Saturday:** take inventory of the official dataset and write `data/adapters/official.py`, the converter that turns it into the contract format. You are the critical person that day.

**Hands over:** a ready `data/out/` folder by Wednesday evening. Fake data is fine at first.

## Person 2: Nahla, Terrain and hazards (`terrain/`)

**Before Saturday**
- Compute slope and roughness from the terrain model.
- Combine slope, rocks and thermal inertia (loose sand) into a hazard map: green, yellow, red.
- Make the thresholds adjustable in one config file (`terrain/thresholds.toml`).
- Export the map layers as PNG files: shaded relief, slope, hazards.
- Check the results: real Curiosity tracks should land on green cells.

**Saturday:** rerun everything on the official data, adjust the thresholds and fix grid alignment problems with Person 1.

**Hands over:** `hazard.tif` and the PNG layers to Persons 3 and 4.

## Person 3: Tushaar, Route planning and safety (`routing/`)

**Before Saturday**
- Walking-speed model for a suited astronaut (Tobler's hiking function with a suit penalty).
- Cost map and route calculation (A*) from the rover through each science stop and back.
- Time-back-to-shelter map, with contour lines in minutes.
- EVA timeline: walking time plus time at each stop, checked against oxygen, battery and radiation budgets.
- Solar storm re-planning: from any point on the route, compute the fastest way back to the rover.

**Saturday:** rerun everything on the new terrain and confirm the route still works.

**Hands over:** `route.geojson`, `shelter_time.png` and `plan.json` to Persons 4 and 5.

## Person 4: Loick, Front end, planning and tablet views (`web/`)

**Before Saturday**
- React and Leaflet app with `CRS.Simple`, which treats the site as a flat grid in metres.
- Layer switches and transparency sliders, all driven by `layers.json`.
- Show the route, stops and hazards. Add a slope profile chart along the route and a timeline chart.
- Weather and radiation panel.
- Tablet view: a simplified version of the same map.
- Optional: 3D terrain view with Three.js.

**Saturday:** load the real layers and fix any display bugs.

**Hands over:** a working app, deployed by Thursday evening (on fake data if needed).

## Person 5: Zakiyyah, Science, helmet HUD and pitch (`mission/`, `web/src/hud/`)

**Before Saturday**
- One-page mission brief: science goals, crew setup, limits.
- Choose 3 to 5 science stops with coordinates and a justification for each. Give them to Person 3 by Wednesday.
- Find a Curiosity ground-level photo for each stop.
- Build the HUD view: heading, distance to the next stop, time back to shelter, oxygen and battery, radiation dose rate, alerts.
- Build the "simulate EVA" demo: an astronaut walks the route, a solar storm hits, and the plan switches to the return route.

**Saturday:** write the demo script and slides, and run rehearsals.

**Hands over:** `waypoints.geojson` by Wednesday, and the HUD as a component inside Person 4's app.

## Schedule

| Day | Milestone |
| --- | --- |
| Today | Shared Git repo created; everyone reads `CONTRACT.md`; Person 5 picks the site |
| Wednesday | Data in place (fake is fine); science stops chosen |
| Thursday | First full run: data, hazards, route, displayed in the app |
| Friday | Everything connected; first demo run; list of bugs |
| Saturday morning | Official data arrives; Persons 1 and 2 convert it, the others keep polishing |
| Saturday afternoon | Full rerun on real data; Person 5 writes the pitch |
| Sunday | Rehearse twice, fix only critical bugs, present |

## Rules to keep everyone unblocked

- Nobody changes `CONTRACT.md` without telling Person 1.
- Always use fake data instead of waiting. Each person can test their part alone.
- Hold a 10-minute check-in every evening: what is done, what is blocked, what is next.
- Each person presents one slide about their own part on Sunday. That is equal credit, and the pitch gets written faster.
