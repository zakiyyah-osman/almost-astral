# routing/ — Route planning and safety (owner: Tushaar)

## Scope
- Create or edit files only in routing/. Read anything else; never edit it.
- Never edit CONTRACT.md, requirements.txt, or other people's folders/outputs. If a change is needed there, stop and tell me.
- Write to data/out/ only: route.geojson, shelter_time.png, plan.json (exactly per CONTRACT.md),
  plus new files route_fastest.geojson and route_safest.geojson.
- plan.json: add fields freely, never rename or remove contract fields.

## Inputs (data/out/)
dem.tif (m, float32), hazard.tif (uint8: 0 green, 1 yellow, 2 red), waypoints.geojson,
radiation.csv, layers.json. Read width/height/cell_m from layers.json site.grid. Never hard-code 400 or 5.

## Grid
- Row 0 = north edge. Cell centre: x = (c + 0.5) * cell_m, y = (rows - r - 0.5) * cell_m.
- GeoJSON coordinates are [x, y] in metres, not lon/lat. No Earth distance formulas.

## Constraints (mentor guidance)
- Hard constraints = impassable (negative/inf cost): red cells, slope above the limit, optional cliff-edge buffer.
- Soft constraints = penalties expressed in minutes: yellow cells, steep-but-legal slope, proximity to red.
- Keep two quantities separate:
  - planning cost = physical time + w × risk (only chooses the path)
  - physical walk time (used for timeline, shelter map, plan.json, budgets)
- Three profiles: fastest (w = 0), balanced (default → route.geojson), safest (high w).
- A w-sweep producing a time vs risk-exposure table; a sensitivity run over v_flat, slope limit and w.

## Walking model (Mars gravity)
- v(S) = v_flat × exp(-3.5(|S| + 0.05)) / exp(-3.5 × 0.05). Tobler gives only the slope shape, normalised to 1 on flat ground.
- v_flat = 2.7 km/h (scenario, Apollo walkback planning); alternative 3.4 km/h (Mars energy-optimal gait, Cavagna et al.).
- gravity_m_s2 = 3.71. Check v_flat < walk–run transition sqrt(0.5 × g × leg_length_m), with leg_length_m = 0.9.
- Do not relax slope limits for lower gravity: traction drops with g.

## Safety and budgets
- Shelter time: physical minutes back to the rover from every cell, including ingress time.
- Timeline: walk + stops + ingress, checked against eva_max_min, reserve_pct (30) and the radiation limit.
- Radiation: background ≈ 0.64 mSv/day (Gale RAD, applied to Jezero as a scenario). Solar-event dose stays in Gy; never add it to Sv.
- Storm re-plan: fastest return from sampled route points.
- A stop on a red cell or one that can't be reached → fail with a clear message naming the stop.

## Assumptions
Every parameter lives in routing/config.toml with value, unit, type (observation / proxy / scenario) and source.
No magic numbers in code. plan.json carries an assumptions block copied from config.

## Site
Jezero for now. Code must stay site-agnostic so switching to Gale only means new data.

## Workflow
- Documents: routing/docs/DESIGN.md (what and why), CHECKLIST.md (build order), QA.md (independent checks).
- Build only what CHECKLIST.md says, in order. Tick items as you go. Stop at the end of each phase for my review.
- Never mark an item done without running its acceptance check.
- Tests in routing/tests/ with pytest. After writing outputs, run python data/validate.py.
- Small commits on branch tushaar after each phase. Never push.
- Python 3.12 (3.11–3.12 only; 3.13+ lacks scikit-image wheels), venv in .venv. Ask before adding dependencies.