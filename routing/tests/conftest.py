"""Shared fixtures: small synthetic sites written to a temp folder in the data/out format.

Each site fixture returns a Site with the folder, the arrays and the grid. Only the
end-to-end test (phase 7) reads the real data/out/.
"""
import json
import sys
from collections import namedtuple
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

ROUTING = Path(__file__).resolve().parents[1]
if str(ROUTING) not in sys.path:
    sys.path.insert(0, str(ROUTING))

Site = namedtuple("Site", "folder dem hazard width height cell_m")


def write_site(folder, dem, hazard, cell_m, name="Synthetic test site"):
    """Write layers.json, dem.tif and hazard.tif for the given arrays (row 0 = north)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    height, width = dem.shape
    layers = {
        "site": {
            "name": name,
            "grid": {"width": width, "height": height, "cell_m": cell_m},
            "extent_m": [width * cell_m, height * cell_m],
        },
        "layers": [],
        "vectors": {"route": "route.geojson", "waypoints": "waypoints.geojson"},
        "tables": {"weather": "weather.csv", "radiation": "radiation.csv"},
        "plan": "plan.json",
    }
    (folder / "layers.json").write_text(json.dumps(layers, indent=2))
    for fname, arr, dtype in (("dem.tif", dem, "float32"), ("hazard.tif", hazard, "uint8")):
        with rasterio.open(
            folder / fname, "w", driver="GTiff", height=height, width=width, count=1,
            dtype=dtype, transform=from_origin(0, height * cell_m, cell_m, cell_m),
        ) as dst:
            dst.write(arr.astype(dtype), 1)
    return Site(folder, dem, hazard, width, height, cell_m)


@pytest.fixture
def flat_site(tmp_path):
    """20 x 20 cells, 5 m, flat at 0 m, all hazard green."""
    dem = np.zeros((20, 20), dtype=np.float32)
    hazard = np.zeros((20, 20), dtype=np.uint8)
    return write_site(tmp_path / "flat", dem, hazard, 5.0)


@pytest.fixture
def tilted_site(tmp_path):
    """20 x 20 cells, 5 m, rising 10% towards the east (0.5 m per cell), all green."""
    cols = np.arange(20, dtype=np.float32)
    dem = np.tile(0.5 * cols, (20, 1)).astype(np.float32)
    hazard = np.zeros((20, 20), dtype=np.uint8)
    return write_site(tmp_path / "tilted", dem, hazard, 5.0)


@pytest.fixture
def red_wall_site(tmp_path):
    """20 x 20 cells, 5 m, flat. A red wall in column 10 from row 0 to row 14; rows 15-19 are open."""
    dem = np.zeros((20, 20), dtype=np.float32)
    hazard = np.zeros((20, 20), dtype=np.uint8)
    hazard[0:15, 10] = 2
    return write_site(tmp_path / "red_wall", dem, hazard, 5.0)


@pytest.fixture
def wide_site(tmp_path):
    """120 x 80 cells (width x height), 10 m cells, flat, all green. For site-agnostic checks."""
    dem = np.zeros((80, 120), dtype=np.float32)
    hazard = np.zeros((80, 120), dtype=np.uint8)
    return write_site(tmp_path / "wide", dem, hazard, 10.0)

def write_waypoints(folder, items):
    """Write waypoints.geojson. items: (id, name, kind, x, y) tuples, x and y in metres."""
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [x, y]},
            "properties": {"id": wid, "name": name, "kind": kind, "why": "test", "photo": None},
        }
        for wid, name, kind, x, y in items
    ]
    path = Path(folder) / "waypoints.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    return path
