# terrain/ (Person 2: Terrain and hazards)

You turn the terrain model into a map of where the crew can and cannot walk.

## What it does

`hazard_map.py` reads `data/out/dem.tif` (and `thermal_inertia.tif` if present) and writes `hazard.tif`, `hazard.png`, `relief.png` and `slope.png` into `data/out/` (formats in [../CONTRACT.md](../CONTRACT.md)). It also writes `hazard_stats.json` here, with the share of green, yellow and red cells.

Hazard values: `0` green (fine), `1` yellow (careful), `2` red (do not enter).

How a cell is classified:
- **Slope** in degrees, using the real cell size from `site.json`.
- **Roughness** in metres: how bumpy the ground is once the slope is removed. This is a **stand-in for rocks**: the terrain model has no rock layer, and a 5 m grid smooths out small boulders. Say so in the pitch.
- **Loose sand** from thermal inertia (low = sand). THEMIS pixels are 100 m wide, so sand alone only gives yellow. It gives red only where slope or roughness is already yellow.
- **Missing terrain data** is never green (red by default).
- The worst of these decides the cell.

## Thresholds

All limits are in `thresholds.toml`. They are **team assumptions, not sourced limits.** Replace them with sourced values if you find any, and write the source next to the number.

## Run it

```bash
python terrain/hazard_map.py                # rebuild the four files
python terrain/hazard_map.py --check-route  # also report hazard along route.geojson
python -m pytest terrain/tests           # tests
python data/validate.py                  # check data/out/ against the contract
```

## Saturday (official data)

Rerun `python terrain/hazard_map.py` after Yaj rebuilds `dem.tif`. If it stops with a grid-size message, ask Yaj to rebuild the data. Then check `terrain/hazard_stats.json`, adjust `thresholds.toml` if the shares look wrong, and check the route with `--check-route`.

## Hands over

`hazard.tif` and the PNG layers, to Person 3 (routing) and Person 4 (web app).

## Still to do

- Find sources for the slope, roughness and sand limits.
- Check the map against the real Perseverance traverse (green cells), once the real data is in.
