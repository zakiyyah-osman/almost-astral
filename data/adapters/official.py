"""Convert the official challenge dataset into the format in CONTRACT.md.

Person 1: fill this in on Saturday, once the official data is available.

Steps:
1. List what the dataset contains: file types, resolution, projection, coverage.
2. Clip every layer to the chosen walking area and resample to one common grid.
3. Write the results into data/out/ using the file names in CONTRACT.md.
4. Update data/out/layers.json (with a `source` for every layer).
"""
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "raw"
OUT = Path(__file__).resolve().parents[1] / "out"


def main():
    raise NotImplementedError("TODO (Person 1): convert the official data into data/out/")


if __name__ == "__main__":
    main()
