# data/ (Person 1: Data lead)

You own the data going in and the file everyone reads: `layers.json`.

## Your job

1. Keep `make_fake.py` working so everyone can test with fake data.
2. Download public data for the chosen site into `raw/` (it is ignored by Git): HiRISE terrain model and imagery, THEMIS thermal map, CRISM mineral maps, Perseverance MEDA weather, NASA DONKI solar storms. Radiation is an estimate from Curiosity RAD's published average (Perseverance has no dose instrument).
3. Crop and align every layer to the same grid (see [../CONTRACT.md](../CONTRACT.md)) and write it to `out/`.
4. On Saturday, write `adapters/official.py` to convert the official dataset into the contract format.

## Folders and files

- `out/`: the shared folder everyone reads. Fake data is committed here so the app runs straight after cloning.
- `raw/`: big downloaded files. Never committed.
- `adapters/`: one script per data source (`hirise.py`, `themis.py`, `crism.py`, `meda.py`, `rems.py`, `rad.py`, `donki.py`; `rems.py` is for Curiosity and unused at Jezero), plus `official.py` for Saturday.
- `site.json`: the site centre, the grid, and which raw file each source uses. Set a source to `null` to keep its fake data.
- `grid.py`: shared code that reprojects any map file onto the site grid and writes contract-format files.
- `tables.py`: shared code that turns MEDA/REMS/RAD readings into hourly rows. `python data/tables.py <file>` shows a file's columns.
- `inspect_raw.py`: `python data/inspect_raw.py <file>` shows a raster's projection, pixel size, and whether the site is inside it.
- `SOURCES.md`: where to download each dataset.

## Quick start

```bash
python data/make_fake.py               # fake data for everything
python data/build_real.py --list       # which sources are set in site.json
python data/build_real.py              # swap in every real source that is set
python data/build_real.py themis meda  # or only some
python data/validate.py
```

`make_fake.py` rewrites all of `out/`, including `layers.json`. If you run it after real data is in, run `build_real.py` again.

## Extra files the real build adds

These are additions; the contract allows extra fields and files:

- `hirise.png`: a new optical layer (HiRISE image), listed after `relief` in `layers.json`.
- `thermal_inertia.tif`: real thermal inertia values (float32, NaN = no data) for Nahla's thresholds.
- `space_weather.csv`: solar flares, CMEs and SEP events from DONKI, listed under `tables.space_weather`.
- In `layers.json`: `site.center_lat` / `center_lon_east`, `sources_notes` (credits for the tables and `dem.tif`), and on some layers `native_resolution_m`, `note` and `legend`.

## Before you go further

- Write down the mission and instrument for every layer in the `source` field of `layers.json` and in the main README.
- Check each new file's projection and units before overlaying it. Misaligned layers are the most common failure.
