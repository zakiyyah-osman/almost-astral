# Almost Astral: project rules

Entry for NASA Space Apps 2026, "Interplanetary Survival Guide: Martian Map". A team of five builds an interactive map of one walkable Mars site: layered NASA data, a safe walking route between science stops, and a briefing on hazards, conditions and radiation.

## Read first

- `README.md`: who owns which folder, how to run everything, the Git workflow.
- `CONTRACT.md`: the grid and the file formats in `data/out/`. Every folder depends on it.
- `docs/work-split.md`: each person's tasks and the schedule.

## Ownership

Work only in the folder the user owns, and ask the user before editing another person's folder. Ask which person the user is if it is not clear.

| Person | Folder |
| --- | --- |
| 1 Data lead | `data/` |
| 2 Terrain and hazards | `terrain/` |
| 3 Route planning and safety | `routing/` |
| 4 Front end | `web/` (except `web/src/hud/`) |
| 5 Science, HUD, pitch | `mission/` and `web/src/hud/` |

## Rules

- Never change `CONTRACT.md` or an existing file format in `data/out/` without telling the user first. Other people's code reads those files. Adding a field is fine; renaming or removing one is not.
- Use the fake data (`python data/make_fake.py`) instead of waiting for real data. Keep the fake data working.
- After changing anything in `data/out/`, run `python data/validate.py`. Before submission it must pass with `--strict` (no fake data left).
- Never commit raw datasets. They go in `data/raw/`, which Git ignores.
- Every layer needs a `source` naming the mission and instrument. Do not invent data, and say so when a value is an estimate or an assumption.
- All coordinates are metres on the local site grid. In Leaflet `CRS.Simple`, a point is `L.latLng(y, x)`: y comes first.
- Mars distances and slopes use Mars values (radius 3,396,190 m, gravity 3.71 m/s²), not Earth's.
- Do not commit or push unless the user asks. Keep commit messages short and say what changed.

## Commands

Web app (Node.js 20+):

```bash
cd web
npm install
npm run dev       # development server
npm run build     # production build, run it before saying the web app works
```

Python (3.11+):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python data/make_fake.py     # rebuilds the fake data in data/out/
python data/validate.py      # checks data/out/ against CONTRACT.md
```

## Layout

- `data/`: data going in (`make_fake.py`, `adapters/`, `raw/`) and the shared output folder `data/out/`.
- `terrain/`: slope, roughness and the hazard map (`thresholds.toml` holds the limits).
- `routing/`: walking speed, route finding, shelter-time map and the EVA plan.
- `web/`: React + Vite + Leaflet app. `vite.config.js` serves `data/out/` as the site's public folder.
- `mission/`: science stops, mission brief, photos, slides and the demo script.
