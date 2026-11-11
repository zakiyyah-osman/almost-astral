"""Build the hazard map from the terrain model.

Person 2: fill this in. Reads data/out/dem.tif and thresholds.toml, writes
data/out/hazard.tif, hazard.png, relief.png and slope.png (see CONTRACT.md).
"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "out"


def load_thresholds():
    with open(Path(__file__).with_name("thresholds.toml"), "rb") as f:
        return tomllib.load(f)


def main():
    thresholds = load_thresholds()
    print("Thresholds:", thresholds)
    raise NotImplementedError("TODO (Person 2): compute slope, roughness and the hazard map")


if __name__ == "__main__":
    main()
