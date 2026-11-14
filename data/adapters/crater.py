"""USGS Mars 2020 CTX DEM of Jezero -> out/crater/: the whole crater and rim at rover scale.

Writes data/out/crater/dem.tif (float32 heights, uncompressed so the web app can read it for
route finding), hazard.tif (0/1/2), slope.png and hazard.png, and a "crater" block in layers.json.
Slope maths, thresholds and colours are the site build's (terrain/hazard_map.py and
terrain/thresholds.toml). Only the slope rule applies here: roughness at 40 m cells would measure
something different from the site's 5 m cells, and there is no crater-wide thermal inertia grid yet.

Settings: the "crater" block in data/site.json.
Run with:  python data/build_real.py crater
"""
import datetime
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "terrain"))
import grid  # noqa: E402
import hazard_map as hazards  # noqa: E402  terrain/hazard_map.py (Person 2); terrain/hazards/ is a different package

FOLDER = "crater"
SCALE_NOTE = "rover-scale, 40 m from CTX DEM, misses boulders/small ledges"


def crater_site(site):
    """The crater grid as a site-like dict, so grid.warp_to_grid and grid.save_tif work on it."""
    cfg = site["crater"]
    cell = float(cfg["cell_m"])
    n = int(round(cfg["size_m"] / cell))
    return {
        "center_lat": cfg["center_lat"],
        "center_lon_east": cfg["center_lon_east"],
        "mars_radius_m": site["mars_radius_m"],
        "grid": {"width": n, "height": n, "cell_m": cell},
    }, cfg


def bounds_latlon(csite):
    """South, west, north, east in degrees (east longitude) of the crater grid."""
    g = csite["grid"]
    r = csite["mars_radius_m"]
    half_h = g["height"] * g["cell_m"] / 2
    half_w = g["width"] * g["cell_m"] / 2
    dlat = math.degrees(half_h / r)
    dlon = math.degrees(half_w / (r * math.cos(math.radians(csite["center_lat"]))))
    lat, lon = csite["center_lat"], csite["center_lon_east"]
    return {"south": round(lat - dlat, 6), "west": round(lon - dlon, 6),
            "north": round(lat + dlat, 6), "east": round(lon + dlon, 6)}


def run(site):
    csite, cfg = crater_site(site)
    path = grid.raw_file(cfg.get("dem"))
    if not path:
        return []
    g = csite["grid"]
    cell = g["cell_m"]
    (grid.OUT / FOLDER).mkdir(exist_ok=True)

    # 20 m -> 40 m: average the four source pixels in each cell.
    dem, info = grid.warp_to_grid(path, csite, resampling="average")
    grid.save_tif(f"{FOLDER}/dem.tif", dem, "float32", csite)

    t = hazards.load_thresholds()
    slope = hazards.compute_slope(dem.astype("float64"), cell)
    # Slope rule only: zero roughness never passes a roughness threshold, and no thermal inertia.
    # Cells without height get NaN slope, which classify() makes red (missing data is never safe).
    hazard = hazards.classify(slope, np.zeros_like(slope), None, t)
    no_data = ~np.isfinite(slope)
    grid.save_tif(f"{FOLDER}/hazard.tif", hazard, "uint8", csite)
    grid.save_png(f"{FOLDER}/slope.png", hazards.slope_image(slope))
    grid.save_png(f"{FOLDER}/hazard.png", hazards.hazard_image(hazard))

    today = datetime.date.today().isoformat()
    label = cfg.get("label", "USGS Mars 2020 CTX DEM mosaic, 20 m")
    s = t["slope_deg"]
    derived = f"Derived from {label} ({path.name})"
    confidence = ("Confidence: medium for broad terrain (crater walls, scarps, the delta front); "
                  "low for anything smaller than a few cells. Slopes are averaged over 40 m, so they read "
                  "lower than the 5 m site slopes, and boulders and small ledges do not show.")
    entry = {
        "name": cfg.get("name", "Jezero crater"),
        "grid": g,
        "extent_m": [g["width"] * cell, g["height"] * cell],
        "center_lat": csite["center_lat"],
        "center_lon_east": csite["center_lon_east"],
        "bounds_latlon": bounds_latlon(csite),
        "dem": f"{FOLDER}/dem.tif",
        "hazard": f"{FOLDER}/hazard.tif",
        "source": label,
        "built": today,
        "scale_note": SCALE_NOTE,
        "confidence": confidence,
        "layers": [
            {"id": "crater_slope", "title": "Crater slope (40 m)", "file": f"{FOLDER}/slope.png",
             "source": f"{derived}: slope in degrees, {SCALE_NOTE}", "default": False, "opacity": 0.6},
            {"id": "crater_hazard", "title": "Crater hazards (40 m)", "file": f"{FOLDER}/hazard.png",
             "source": f"{derived}: careful over {s['yellow']}°, no-go over {s['red']}° (terrain/thresholds.toml), "
                       f"{SCALE_NOTE}", "default": True, "opacity": 0.5},
        ],
    }
    index_path = grid.OUT / "layers.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["crater"] = entry
    notes = index.setdefault("sources_notes", {})
    notes[f"{FOLDER}/dem.tif"] = (f"{label}: {path.name}, resampled to {cell:g} m cells (average of the 20 m pixels). "
                                  f"Built {today}. {confidence}")
    notes[f"{FOLDER}/hazard.tif"] = (f"{derived}: slope only, {SCALE_NOTE}. Built {today}. {confidence}")
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    n = hazard.size
    return [
        f"crater/dem.tif {g['width']} x {g['height']} cells of {cell:g} m from {path.name} "
        f"(covers {info['coverage']:.1%}, height {float(dem[~no_data].min()):.0f} to {float(dem[~no_data].max()):.0f} m)",
        f"crater hazards: {(hazard == 0).sum() / n:.1%} green, {(hazard == 1).sum() / n:.1%} yellow, "
        f"{(hazard == 2).sum() / n:.1%} red ({int(no_data.sum())} cells without data)",
    ]


if __name__ == "__main__":
    for line in run(grid.load_site()) or ["nothing to do: set crater.dem in data/site.json"]:
        print(line)
