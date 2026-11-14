"""Shared fixtures: small synthetic sites written to a temp folder in the data/out format.

Each site fixture returns a Site with the folder, the arrays and the grid. Only the
end-to-end test (phase 7) reads the real data/out/.
"""
import json
import re
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
REPO_CONFIG = ROUTING / "config.toml"
START_KINDS = ("start", "rover")
_START_VALUE = re.compile(r"(\[start\.xy_m\]\s*\nvalue = )\[[^\]]*\]")


def config_text(start_xy, text=None):
    """The text of routing/config.toml (or `text`) with start.xy_m set to start_xy."""
    text = REPO_CONFIG.read_text(encoding="utf-8") if text is None else text
    new, n = _START_VALUE.subn(lambda m: f"{m.group(1)}[{float(start_xy[0])!r}, {float(start_xy[1])!r}]", text)
    assert n == 1, "start.xy_m not found in the config text"
    return new


def config_for(folder):
    """The config written next to a synthetic site by write_full_site (start = its start waypoint)."""
    folder = Path(folder)
    return folder.parent / f"{folder.name}.config.toml"


def with_config(folder):
    """["--config", <config_for(folder)>] when write_full_site wrote one, else []. Put it first:
    a later --config on the same command line still wins."""
    path = config_for(folder)
    return ["--config", str(path)] if path.exists() else []


def run_site(folder):
    """plan_route.run on a synthetic site, with the config written next to it."""
    import plan_route
    path = config_for(folder)
    return plan_route.run(folder, path if path.exists() else None)


def write_config(path, start_xy, text=None):
    path = Path(path)
    path.write_text(config_text(start_xy, text), encoding="utf-8")
    return path


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


def write_full_site(folder, dem, hazard, cell_m, waypoints, fake=False, start=None):
    """A complete input folder as plan_route.py and data/validate.py expect it.

    waypoints: (id, name, kind, x, y) tuples. Adds radiation.csv, weather.csv and one layer image.
    Also writes config_for(folder): routing/config.toml with start.xy_m set to `start`, or else
    to the first start waypoint (kind start, or the deprecated rover), because the start always comes
    from the config.
    """
    from PIL import Image

    site = write_site(folder, dem, hazard, cell_m)
    height, width = dem.shape
    folder = Path(folder)
    Image.fromarray(np.zeros((height, width, 4), np.uint8), mode="RGBA").save(folder / "hazard.png")
    layers = json.loads((folder / "layers.json").read_text(encoding="utf-8"))
    layers["layers"] = [{
        "id": "hazard", "title": "Hazards", "file": "hazard.png",
        "source": "FAKE (test)" if fake else "Test site", "default": True, "opacity": 0.7,
    }]
    if not fake:                                          # data/validate.py: real tables are credited in sources_notes
        layers["sources_notes"] = {
            "radiation.csv": "Synthetic test table, not a measurement.",
            "weather.csv": "Synthetic test table, not a measurement.",
        }
    (folder / "layers.json").write_text(json.dumps(layers, indent=2), encoding="utf-8")
    rows = ["sol,local_hour,dose_rate_usv_h", *(f"40,{h},27" for h in range(24))]
    (folder / "radiation.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    weather = ["sol,local_hour,temp_c,pressure_pa,dust_tau", "40,12,-20,700,0.5"]
    (folder / "weather.csv").write_text("\n".join(weather) + "\n", encoding="utf-8")
    write_waypoints(folder, waypoints)
    if start is None:
        start = next(((x, y) for _, _, kind, x, y in waypoints if kind in START_KINDS), None)
    if start is not None:
        write_config(config_for(folder), start)
    return site
