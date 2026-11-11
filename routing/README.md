# routing/ (Person 3: Route planning and safety)

You plan the walk and make sure it is safe.

## Your job

1. **Walking speed** for a suited astronaut: Tobler's hiking function with a penalty for the suit and the load.
2. **Cost map and route (A\*)** from the rover through each science stop and back, using `data/out/hazard.tif` (red cells are not allowed).
3. **Time-back-to-shelter map** with contour lines in minutes: `shelter_time.png`.
4. **EVA timeline:** walking time plus time at each stop, checked against the oxygen, battery and radiation budgets in `plan.json`.
5. **Solar storm re-plan:** from any point on the route, compute the fastest way back to the rover.
6. On Saturday, rerun everything on the official terrain.

## Inputs and outputs

- Reads: `data/out/hazard.tif`, `data/out/waypoints.geojson` (from Person 5), `data/out/radiation.csv`.
- Writes: `data/out/route.geojson`, `data/out/shelter_time.png`, `data/out/plan.json` (formats in [../CONTRACT.md](../CONTRACT.md)).

## Run it

```bash
python routing/plan_route.py
```

## Hands over

The three output files, to Person 4 (web app) and Person 5 (HUD and demo).
