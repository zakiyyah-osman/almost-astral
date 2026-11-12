# routing/ — Route planning and safety (owner: Tushaar)

## Scope
- Create or edit files only in routing/. Read anything else; never edit it.
- Never edit CONTRACT.md, requirements.txt, or other people's folders/outputs. If a change is needed there, stop and tell me.
- Write only these to data/out/, exactly per CONTRACT.md: route.geojson, shelter_time.png, plan.json.

## Inputs (data/out/)
dem.tif (m, float32), hazard.tif (uint8: 0 green, 1 yellow, 2 red = impassable),
waypoints.geojson (rover + stops), radiation.csv, layers.json.
Read width/height/cell_m from layers.json site.grid. Never hard-code 400 or 5.

## Grid
- Row 0 = north edge. Cell centre: x = (c + 0.5) * cell_m, y = (rows - r - 0.5) * cell_m.
- GeoJSON coordinates are [x, y] in metres, not lon/lat. No Earth distance formulas.

## Model
All parameters live in routing/config.toml, each with value, source and type
(observation / proxy / scenario).
- Speed: Tobler's hiking function × suit factor (default 0.5); storm speed multiplier.
- Cost: cell_m / speed + penalties for roughness, loose ground, cross-slope. Red = impassable.
- Route: skimage.graph.MCP_Geometric, rover → each stop → rover.
- Shelter time: minutes back to the rover from every cell, including ingress time.
- Timeline: walk + stop + ingress, checked against eva_max_min, reserve_pct and radiation limit.
- Radiation: background ≈ 0.64 mSv/day (Gale RAD, applied to Jezero as a scenario).
  Solar-event dose stays in Gy; never add it to Sv values.
- If a stop is on a red cell or unreachable, fail with a clear message naming the stop.

## Site
Jezero for now. Code must stay site-agnostic so switching to Gale only means new data.

## Workflow
- Python 3.11, venv in .venv. Ask before adding dependencies.
- Test on fake data: python data/make_fake.py, then python data/validate.py after writing outputs.
- Put pytest tests in routing/tests/: grid/coordinate conversion, a tiny hand-checked cost map, unreachable stop.
- Small commits on branch tushaar. Never push to main.