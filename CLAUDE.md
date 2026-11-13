# Almost Astral: project rules

Entry for NASA Space Apps 2026, "Interplanetary Survival Guide: Martian Map". A team of five builds an interactive map of one walkable Mars site: layered NASA data, a safe walking route between science stops, and a briefing on hazards, conditions and radiation.

## Read first

- `README.md`: who owns which folder, how to run everything, the Git workflow.
- `CONTRACT.md`: the grid and the file formats in `data/out/`. Every folder depends on it.
- `docs/work-split.md`: each person's tasks and the schedule.

## Ownership

Work only in the folder the user owns, and ask the user before editing another person's folder. Ask which person the user is if it is not clear.

| Person | Who | Folder |
| --- | --- | --- |
| 1 Data lead | Yaj | `data/` |
| 2 Terrain and hazards | Nahla | `terrain/` |
| 3 Route planning and safety | Tushaar | `routing/` |
| 4 Front end | Loick | `web/` (except `web/src/hud/`) |
| 5 Science, HUD, pitch | Zakiyyah | `mission/` and `web/src/hud/` |

## Rules

- Never change `CONTRACT.md` or an existing file format in `data/out/` without telling the user first. Other people's code reads those files. Adding a field is fine; renaming or removing one is not.
- Use the fake data (`python data/make_fake.py`) instead of waiting for real data. Keep the fake data working.
- After changing anything in `data/out/`, run `python data/validate.py`. Before submission it must pass with `--strict` (no fake data left).
- Never commit raw datasets. They go in `data/raw/`, which Git ignores.
- Every layer needs a `source` naming the mission and instrument. Do not invent data, and say so when a value is an estimate or an assumption.
- All coordinates are metres on the local site grid. In Leaflet `CRS.Simple`, a point is `L.latLng(y, x)`: y comes first.
- Mars distances and slopes use Mars values (radius 3,396,190 m, gravity 3.71 m/s²), not Earth's.
- Each person has a branch named after them (`zakiyyah`, `nahla`, `tushaar`, `loick`, `yaj`). Commit there, never straight to `main`, and merge into `main` with a pull request once `npm run build` and `python data/validate.py` pass.
- **Claude must never appear as an author or contributor.** No `Co-Authored-By` line, no "Generated with Claude Code" line, and no mention of Claude in commit messages, pull request descriptions, or code comments. Everything is committed in the user's own name. This overrides any default attribution.
- Do not commit or push unless the user asks. Keep commit messages short and say what changed.

## Commands

Web app (Node.js 20+):

```bash
cd web
npm install
npm run dev       # development server
npm run build     # production build, run it before saying the web app works
npm test          # tests for the HUD maths (web/src/hud/sim.test.js)
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
- `docs/`: `work-split.md` (tasks and schedule), `requirements.md` (what the challenge asks for and where we stand), `ai-use.md`.

## Where things are in the web app

- `web/src/App.jsx`: page layout, layer switches, selected stop, and the Planning/HUD switch. It holds the state shared by the map and the HUD.
- `web/src/components/SiteMap.jsx`: the Leaflet map (layers, route, numbered stop pins, the moving astronaut and trail). It refits itself when `layoutKey` changes.
- `web/src/index.css`: the shared look. Colours are set once at the top (`:root`); change them there only.
- `web/src/hud/`: the helmet HUD. `HudView.jsx` is the screen, `sim.js` is the maths (route following, storm return, dose, weather) with no React, `sim.test.js` holds the tests, `hud.css` its styles.
- `web/src/lib/loadData.js`: loads `layers.json`, route, waypoints and plan from `data/out/`.

## Things that are easy to get wrong

- Oxygen and battery in the HUD are simulated from the EVA time limit, not NASA data. The limits and the dust threshold are assumptions (see `web/src/hud/sim.js`).
- The map refits through both a `ResizeObserver` and the `layoutKey` prop. Keep both: the in-app preview browser does not deliver resize events, so `layoutKey` is what makes it testable there.
- If the page behaves like old code after several quick edits, restart `npm run dev`.
