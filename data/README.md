# data/ (Person 1: Data lead)

You own the data going in and the file everyone reads: `layers.json`.

## Your job

1. Keep `make_fake.py` working so everyone can test with fake data.
2. Download public data for the chosen site into `raw/` (it is ignored by Git): HiRISE terrain model and imagery, THEMIS thermal map, CRISM mineral maps, Curiosity REMS weather, Curiosity RAD radiation, NASA DONKI solar storms.
3. Crop and align every layer to the same grid (see [../CONTRACT.md](../CONTRACT.md)) and write it to `out/`.
4. On Saturday, write `adapters/official.py` to convert the official dataset into the contract format.

## Folders

- `out/`: the shared folder everyone reads. Fake data is committed here so the app runs straight after cloning.
- `raw/`: big downloaded files. Never committed.
- `adapters/`: scripts that convert one data source into the contract format.

## Quick start

```bash
python data/make_fake.py
```

## Before you go further

- Write down the mission and instrument for every layer in the `source` field of `layers.json` and in the main README.
- Check each new file's projection and units before overlaying it. Misaligned layers are the most common failure.
