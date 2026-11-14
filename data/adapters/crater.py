"""USGS Mars 2020 CTX DEM of Jezero -> out/crater/: the whole crater and rim at rover scale.

Writes into data/out/crater/ compact grids the web app's route worker reads (little-endian, row 0 =
north edge, one value per 40 m cell, no file over 10 MB):
  grid.json   the header: rows, cols, cell size, projection, lat/lon bounds, files, no-data values
  height.i16  height in whole metres, Int16, -32768 = no data
  hazard.u8   0 fine, 1 careful, 2 do not enter (no-data cells are 2)
  slope.u8    slope in quarter degrees (value / 4), 255 = no data; worked out here from the full-precision
              heights, because slope from whole-metre heights at 40 m would be off by up to ~0.7 degrees
plus the map overlays slope.png and hazard.png, and the "crater" block in layers.json.
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
LABEL = "40 m, rover-scale"
HEIGHT_NODATA = -32768
SLOPE_NODATA = 255
SLOPE_STEP_DEG = 0.25
MAX_FILE_BYTES = 10_000_000


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


def write_grid(name, arr, dtype):
    """One compact grid file: raw little-endian values, row 0 = north edge. Returns its size in bytes."""
    path = grid.OUT / FOLDER / name
    data = np.ascontiguousarray(arr, dtype=np.dtype(dtype).newbyteorder("<")).tobytes()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"{FOLDER}/{name} would be {len(data) / 1e6:.1f} MB, over the 10 MB limit: use larger cells")
    path.write_bytes(data)
    return len(data)


def run(site):
    csite, cfg = crater_site(site)
    path = grid.raw_file(cfg.get("dem"))
    if not path:
        return []
    g = csite["grid"]
    cell = g["cell_m"]
    out = grid.OUT / FOLDER
    out.mkdir(exist_ok=True)

    # 20 m -> 40 m: average the four source pixels in each cell.
    dem, info = grid.warp_to_grid(path, csite, resampling="average")
    dem = dem.astype("float64")
    nodata = ~np.isfinite(dem)

    t = hazards.load_thresholds()
    slope = hazards.compute_slope(dem, cell)
    # Slope rule only: zero roughness never passes a roughness threshold, and no thermal inertia.
    # Cells without height get NaN slope, which classify() makes red (missing data is never safe).
    hazard = hazards.classify(slope, np.zeros_like(slope), None, t)
    hazard[nodata] = 2
    no_data = ~np.isfinite(slope)
    grid.save_png(f"{FOLDER}/slope.png", hazards.slope_image(slope))
    grid.save_png(f"{FOLDER}/hazard.png", hazards.hazard_image(hazard))

    # The compact grids for the web app's route worker.
    height = np.where(nodata, HEIGHT_NODATA, np.rint(np.nan_to_num(dem))).astype(np.int16)
    slope_q = np.where(no_data, SLOPE_NODATA, np.clip(np.rint(np.nan_to_num(slope) / SLOPE_STEP_DEG), 0, SLOPE_NODATA - 1)).astype(np.uint8)
    sizes = {
        "height.i16": write_grid("height.i16", height, "int16"),
        "hazard.u8": write_grid("hazard.u8", hazard, "uint8"),
        "slope.u8": write_grid("slope.u8", slope_q, "uint8"),
    }
    # The old float32 rasters are replaced by the compact grids (dem.tif was over 10 MB).
    for old in ("dem.tif", "hazard.tif"):
        (out / old).unlink(missing_ok=True)

    today = datetime.date.today().isoformat()
    label = cfg.get("label", "USGS Mars 2020 CTX DEM mosaic, 20 m")
    s = t["slope_deg"]
    derived = f"Derived from {label} ({path.name})"
    confidence = ("Confidence: medium for broad terrain (crater walls, scarps, the delta front); "
                  "low for anything smaller than a few cells. Slopes are averaged over 40 m, so they read "
                  "lower than the 5 m site slopes, and boulders and small ledges do not show.")
    header = {
        "format": "almost-astral crater grid, version 1",
        "rows": g["height"],
        "cols": g["width"],
        "cell_m": cell,
        "row0": "north",
        "byte_order": "little",
        "projection": {"type": "equirectangular on a sphere", "radius_m": csite["mars_radius_m"],
                       "center_lat": csite["center_lat"], "center_lon_east": csite["center_lon_east"],
                       "lat_ts": csite["center_lat"], "note": "x = metres east of the west edge, y = metres north of the south edge"},
        "bounds_latlon": bounds_latlon(csite),
        "height": {"file": f"{FOLDER}/height.i16", "dtype": "int16", "units": "m", "nodata": HEIGHT_NODATA},
        "hazard": {"file": f"{FOLDER}/hazard.u8", "dtype": "uint8", "classes": {"0": "fine", "1": "careful", "2": "do not enter"},
                   "nodata_class": 2},
        "slope": {"file": f"{FOLDER}/slope.u8", "dtype": "uint8", "units": "deg", "scale": SLOPE_STEP_DEG, "nodata": SLOPE_NODATA},
        "thresholds_deg": {"careful_over": s["yellow"], "no_go_over": s["red"]},
        "label": LABEL,
        "source": f"{label} ({path.name})",
        "built": today,
    }
    (out / "grid.json").write_text(json.dumps(header, indent=2), encoding="utf-8")
    entry = {
        "name": cfg.get("name", "Jezero crater"),
        "grid": g,
        "extent_m": [g["width"] * cell, g["height"] * cell],
        "center_lat": csite["center_lat"],
        "center_lon_east": csite["center_lon_east"],
        "bounds_latlon": bounds_latlon(csite),
        "grid_header": f"{FOLDER}/grid.json",
        "source": label,
        "built": today,
        "scale_note": SCALE_NOTE,
        "label": LABEL,
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
    for old in ("dem.tif", "hazard.tif"):
        notes.pop(f"{FOLDER}/{old}", None)
    notes[f"{FOLDER}/grid.json"] = (f"{label}: {path.name}, resampled to {cell:g} m cells (average of the 20 m pixels); "
                                    f"height (whole metres), slope and hazard classes ({derived}: slope only, {SCALE_NOTE}). "
                                    f"Built {today}. {confidence}")
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    n = hazard.size
    return [
        f"crater grid {g['width']} x {g['height']} cells of {cell:g} m from {path.name} "
        f"(covers {info['coverage']:.1%}, height {float(np.nanmin(dem)):.0f} to {float(np.nanmax(dem)):.0f} m, {int(nodata.sum())} no-data cells)",
        "files: " + ", ".join(f"{k} {v / 1e6:.2f} MB" for k, v in sizes.items()) + ", grid.json",
        f"crater hazards: {(hazard == 0).sum() / n:.1%} green, {(hazard == 1).sum() / n:.1%} yellow, "
        f"{(hazard == 2).sum() / n:.1%} red",
    ]


if __name__ == "__main__":
    for line in run(grid.load_site()) or ["nothing to do: set crater.dem in data/site.json"]:
        print(line)
