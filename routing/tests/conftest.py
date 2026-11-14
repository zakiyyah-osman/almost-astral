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
_STARTS_BLOCK = re.compile(r"# ---- starts -.*?(?=# ---- reach export)", re.S)
ZERO_SHA = "0" * 64


def _sha_in(text, key, fallback):
    m = re.search(rf'\[start\.{key}\]\s*\nvalue = "([0-9a-f]{{64}})"', text)
    return m.group(1) if m else fallback


def start_block(starts, default, dem_sha, hazard_sha):
    """The TOML text of the starts section: [start.*] and one [starts.<id>] per start."""
    out = [
        "# ---- starts ----- (written by the tests) ---------------------------------\n",
        f'[start.default]\nvalue = "{default}"\nunit = "id"\ntype = "scenario"\nsource = "test"\n\n',
        f'[start.dem_sha256]\nvalue = "{dem_sha}"\nunit = "sha256"\ntype = "scenario"\nsource = "test"\n\n',
        f'[start.hazard_sha256]\nvalue = "{hazard_sha}"\nunit = "sha256"\ntype = "scenario"\nsource = "test"\n\n',
    ]
    for sid, (x, y) in starts.items():
        out.append(
            f'[starts.{sid}]\nvalue = [{float(x)!r}, {float(y)!r}]\nunit = "m"\ntype = "scenario"\n'
            f'source = "test start {sid}, temporary"\n\n'
        )
    return "".join(out)


def config_text(starts, text=None, default=None, dem_sha=None, hazard_sha=None):
    """routing/config.toml (or `text`) with its starts section replaced.

    starts: {id: (x, y)}, or one (x, y) point for a single start L1. The default start is `default`
    or else the first. The data hashes are `dem_sha` and `hazard_sha`, or else the ones already in
    the text.
    """
    text = REPO_CONFIG.read_text(encoding="utf-8") if text is None else text
    if not isinstance(starts, dict):
        starts = {"L1": starts}
    default = next(iter(starts)) if default is None else default
    dem_sha = _sha_in(text, "dem_sha256", ZERO_SHA) if dem_sha is None else dem_sha
    hazard_sha = _sha_in(text, "hazard_sha256", ZERO_SHA) if hazard_sha is None else hazard_sha
    new, n = _STARTS_BLOCK.subn(lambda m: start_block(starts, default, dem_sha, hazard_sha), text)
    assert n == 1, "the starts section was not found in the config text"
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


def write_config(path, starts, text=None, **kw):
    """Write a config with the given starts (see config_text) to `path`."""
    path = Path(path)
    path.write_text(config_text(starts, text, **kw), encoding="utf-8")
    return path


def sha256_of(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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


def write_full_site(folder, dem, hazard, cell_m, waypoints, fake=False, start=None, starts=None, default=None):
    """A complete input folder as plan_route.py and data/validate.py expect it.

    waypoints: (id, name, kind, x, y) tuples. Adds radiation.csv, weather.csv and one layer image.
    Also writes config_for(folder): routing/config.toml with its starts set to `starts` ({id: (x, y)}),
    or to one start L1 at `start`, or else at the first start waypoint (kind start, or the deprecated
    rover), because the start always comes from the config. The config carries the hashes of this
    site's dem.tif and hazard.tif, so a site written here gives no staleness warning.
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
    if starts is None:
        if start is None:
            start = next(((x, y) for _, _, kind, x, y in waypoints if kind in START_KINDS), None)
        starts = None if start is None else {"L1": start}
    if starts is not None:
        write_config(config_for(folder), starts, default=default,
                     dem_sha=sha256_of(folder / "dem.tif"), hazard_sha=sha256_of(folder / "hazard.tif"))
    return site
