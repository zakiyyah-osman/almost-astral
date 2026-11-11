# Almost Astral

Entry for the NASA Space Apps Challenge 2026, **Interplanetary Survival Guide: Martian Map**.

An interactive map of one walkable area on Mars. It layers several kinds of NASA data, plans a safe walking route between science stops, and briefs the crew on terrain hazards, conditions and radiation.

## Who owns what

Everyone works in their own folder, so nobody edits the same file at the same time. Folders talk to each other only through the files in `data/out/` (see [CONTRACT.md](CONTRACT.md)).

| Person | Role | Folder | Hands over (in `data/out/`) |
| --- | --- | --- | --- |
| 1 | Data lead | `data/` | `layers.json`, layer images, `weather.csv`, `radiation.csv` |
| 2 | Terrain and hazards | `terrain/` | `hazard.tif`, `hazard.png`, slope and relief images |
| 3 | Route planning and safety | `routing/` | `route.geojson`, `shelter_time.png`, `plan.json` |
| 4 | Front end | `web/` | the deployed app |
| 5 | Science, HUD, pitch | `mission/` and `web/src/hud/` | `waypoints.geojson`, the HUD view, the demo and slides |

The full task list and schedule are in [docs/work-split.md](docs/work-split.md).

## Run the web app

Needs Node.js 20 or newer.

```bash
cd web
npm install
npm run dev
```

Open the address it prints (usually http://localhost:5173). You should see a flat map of a fake site with layer switches. The fake data is already included, so this works straight after cloning.

## Run the Python scripts

Needs Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python data/make_fake.py         # regenerates the fake data in data/out/
python data/validate.py          # checks data/out/ against CONTRACT.md
```

Run `validate.py` every time you change a file in `data/out/`. It lists anything that breaks the contract. Before we submit, run `python data/validate.py --strict`: it also fails if any layer still uses fake data.

If you use the NASA solar-storm API (DONKI), copy `.env.example` to `.env` and put your key in it. `.env` is ignored by Git, so it never gets uploaded.

## Working together with Git

You do not need to know much Git. The VS Code **Source Control** tab (the branch icon on the left) does all of this with buttons.

1. **Make your own branch once**, named after your folder (for example `p3-routing`).
2. **Work only in your folder.** If you need a change in someone else's folder, ask them.
3. **Commit often** with a short message that says what you did.
4. **Before you push, pull** (Source Control, then **Pull**) so you have everyone's latest work.
5. **Push your branch** and open a pull request into `main` once something works. Someone else clicks **Merge**.
6. **Never change `CONTRACT.md` without telling the whole team.** Everyone's code depends on it.
7. **Never commit raw datasets.** They are huge. Put them in `data/raw/`, which Git ignores.

## AI tools and licence

How we used AI tools is written up in [docs/ai-use.md](docs/ai-use.md). The code is released under the [MIT licence](LICENSE). NASA data keeps its own terms: credit every dataset below.

## Data sources

Every layer must name the mission and instrument it comes from. Keep this table up to date.

| Layer | Mission / instrument |
| --- | --- |
| *(add each real dataset here as it is used)* | |
