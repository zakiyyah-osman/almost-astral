# terrain/ (Person 2: Terrain and hazards)

You turn the terrain model into a map of where the crew can and cannot walk.

## Your job

1. Compute slope and roughness from `data/out/dem.tif`.
2. Combine slope, rocks and thermal inertia (loose sand) into a hazard map: `0` green, `1` yellow, `2` red.
3. Keep every threshold in `thresholds.toml`, so anyone can change them without touching the code.
4. Write `hazard.tif`, `hazard.png`, `relief.png` and `slope.png` into `data/out/` (formats in [../CONTRACT.md](../CONTRACT.md)).
5. Check your work: real Curiosity tracks should land on green cells.
6. On Saturday, rerun everything on the official data and fix grid alignment with Person 1.

## Run it

```bash
python terrain/hazards.py
```

## Hands over

`hazard.tif` and the PNG layers, to Person 3 (routing) and Person 4 (web app).
