"""Build the hazard map from the terrain model.

Person 2. Reads data/out/dem.tif (and thermal_inertia.tif if it exists) plus
terrain/thresholds.toml. Writes data/out/hazard.tif, hazard.png, relief.png and
slope.png (formats in CONTRACT.md) and terrain/hazard_stats.json.

Hazard values: 0 green (fine), 1 yellow (careful), 2 red (do not enter).
Where the terrain model has no value the cell is never green (see
[missing_data] in thresholds.toml).

Run:
    python terrain/hazards.py                  # rebuild everything
    python terrain/hazards.py --check-route    # also report hazard along route.geojson
"""
import argparse
import json
import sys
import tomllib
from pathlib import Path

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "out"
THRESHOLDS = Path(__file__).with_name("thresholds.toml")

sys.path.insert(0, str(ROOT / "data"))  # reuse Person 1's file writers
import grid as site_grid  # noqa: E402  (data/grid.py)

GREEN, YELLOW, RED = 0, 1, 2


def load_thresholds():
    with open(THRESHOLDS, "rb") as f:
        return tomllib.load(f)


# --- terrain maths (pure functions, no files) -------------------------------

def compute_slope(dem, cell_m):
    """Slope in degrees. Array row 0 is north, so gy points south; only its size matters.

    np.gradient uses one-sided differences at the edges, so there is no false
    steep border. NaN in the terrain spreads to its neighbours (slope is NaN there).
    """
    gy, gx = np.gradient(dem, cell_m)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def compute_roughness(dem, window_cells):
    """Bumpiness in metres: RMS of how far each cell sits from its local mean height.

    A smooth slope has zero roughness (a plane equals its own local mean), so
    slope is not counted twice. Near the map edge the window does not fit, so
    those cells copy the nearest fully-covered value instead of showing a false border.
    """
    if window_cells < 3 or window_cells % 2 == 0:
        raise ValueError("roughness.window_cells must be an odd number of at least 3")
    k = window_cells // 2
    if min(dem.shape) <= 4 * k:
        raise ValueError("the map is too small for this roughness window")
    residual = dem - ndimage.uniform_filter(dem, window_cells, mode="nearest")
    rms = np.sqrt(ndimage.uniform_filter(residual * residual, window_cells, mode="nearest"))
    inner = rms[2 * k:-2 * k, 2 * k:-2 * k]
    return np.pad(inner, 2 * k, mode="edge")


def classify(slope, roughness, thermal_inertia, thr):
    """Combine slope, roughness and thermal inertia into 0/1/2 (uint8)."""
    hazard = np.zeros(slope.shape, np.uint8)

    s, r = thr["slope_deg"], thr["roughness"]
    with np.errstate(invalid="ignore"):
        hazard[(slope >= s["yellow"]) | (roughness >= r["yellow"])] = YELLOW
        hazard[(slope >= s["red"]) | (roughness >= r["red"])] = RED

        if thermal_inertia is not None:
            ti = thr["thermal_inertia"]
            sand_yellow = thermal_inertia < ti["yellow_below"]
            sand_red = thermal_inertia < ti["red_below"]
            hazard[sand_yellow & (hazard == GREEN)] = YELLOW
            if ti.get("sand_red_needs_other_hazard", True):
                hazard[sand_red & (hazard == YELLOW) & ((slope >= s["yellow"]) | (roughness >= r["yellow"]))] = RED
            else:
                hazard[sand_red] = RED

    # Missing terrain data is never green.
    missing = ~np.isfinite(slope) | ~np.isfinite(roughness)
    missing_class = int(thr.get("missing_data", {}).get("class", RED))
    if missing_class == GREEN:
        raise ValueError("missing_data.class must not be 0: missing data is never safe")
    hazard[missing] = np.maximum(hazard[missing], missing_class)
    return hazard


def hazard_shares(hazard):
    return {name: float((hazard == v).mean()) for name, v in (("green", GREEN), ("yellow", YELLOW), ("red", RED))}


def route_hazard(route_xy, hazard, cell_m, step_m=1.0):
    """Share of green/yellow/red cells along a polyline of [x, y] points in metres."""
    rows, cols = hazard.shape
    counts = np.zeros(3)
    for (x0, y0), (x1, y1) in zip(route_xy[:-1], route_xy[1:]):
        n = max(int(np.hypot(x1 - x0, y1 - y0) / step_m), 1)
        t = np.linspace(0, 1, n, endpoint=False)
        xs, ys = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
        c = np.clip((xs / cell_m).astype(int), 0, cols - 1)
        r = np.clip(rows - 1 - (ys / cell_m).astype(int), 0, rows - 1)
        counts += np.bincount(hazard[r, c], minlength=3)
    total = counts.sum() or 1
    return {name: float(counts[i] / total) for i, name in enumerate(("green", "yellow", "red"))}


# --- images ------------------------------------------------------------------

def relief_image(dem, cell_m):
    """Shaded relief, light from the north-west (same look as the fake data)."""
    dem = np.nan_to_num(dem, nan=float(np.nanmean(dem)) if np.isfinite(dem).any() else 0.0)
    gy, gx = np.gradient(dem, cell_m)
    normal = np.stack([-gx, gy, np.ones_like(gx)], axis=-1)
    light = np.array([-0.5, 0.5, 0.7])
    shade = (normal @ light) / (np.linalg.norm(normal, axis=-1) * np.linalg.norm(light))
    shade = 0.25 + 0.75 * np.clip(shade, 0, 1)
    h, w = dem.shape
    return np.dstack([shade[..., None] * np.array([215, 150, 105]), np.full((h, w, 1), 255)])


def slope_image(slope):
    v = np.clip(np.nan_to_num(slope, nan=30.0) / 30, 0, 1)
    h, w = slope.shape
    return np.dstack([255 * v, 120 * (1 - v), 200 * (1 - v), np.full((h, w), 170)])


def hazard_image(hazard):
    colours = np.array([[34, 170, 90, 0], [240, 190, 40, 150], [220, 50, 50, 170]])
    return colours[hazard]


# --- files -------------------------------------------------------------------

def read_raster(path):
    import rasterio
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
    arr[np.abs(arr) > 1e30] = np.nan
    return arr


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check-route", action="store_true", help="report hazard along data/out/route.geojson")
    args = parser.parse_args()

    thr = load_thresholds()
    site = site_grid.load_site()
    width, height, cell_m = site_grid.grid_size(site)

    dem = read_raster(OUT / "dem.tif")
    if dem.shape != (height, width):
        sys.exit(f"dem.tif is {dem.shape[1]}x{dem.shape[0]} but the site grid is {width}x{height}. "
                 "Ask Person 1 to rebuild the data (python data/build_real.py).")

    ti_path = OUT / "thermal_inertia.tif"
    ti = read_raster(ti_path) if ti_path.is_file() else None
    if ti is None:
        print("No thermal_inertia.tif: loose sand is not checked.")
    elif ti.shape != dem.shape:
        sys.exit("thermal_inertia.tif does not match the grid of dem.tif.")

    slope = compute_slope(dem, cell_m)
    roughness = compute_roughness(dem, int(thr["roughness"]["window_cells"]))
    hazard = classify(slope, roughness, ti, thr)

    site_grid.save_tif("hazard.tif", hazard, "uint8", site)
    site_grid.save_png("hazard.png", hazard_image(hazard))
    site_grid.save_png("relief.png", relief_image(dem, cell_m))
    site_grid.save_png("slope.png", slope_image(slope))

    stats = {
        "cell_m": cell_m,
        "shares": hazard_shares(hazard),
        "max_slope_deg": float(np.nanmax(slope)),
        "missing_cells": int((~np.isfinite(dem)).sum()),
        "thresholds": thr,
        "note": "Thresholds are team assumptions, not sourced limits. Roughness is a stand-in for rocks.",
    }

    if args.check_route:
        route = json.loads((OUT / "route.geojson").read_text(encoding="utf-8"))
        coords = route["features"][0]["geometry"]["coordinates"]
        stats["route_shares"] = route_hazard(coords, hazard, cell_m)

    (Path(__file__).with_name("hazard_stats.json")).write_text(json.dumps(stats, indent=2), encoding="utf-8")

    sh = stats["shares"]
    print(f"Slope max {stats['max_slope_deg']:.1f} deg. Hazard: {sh['green']:.0%} green, "
          f"{sh['yellow']:.0%} yellow, {sh['red']:.0%} red.")
    if "route_shares" in stats:
        rs = stats["route_shares"]
        print(f"Along the route: {rs['green']:.0%} green, {rs['yellow']:.0%} yellow, {rs['red']:.0%} red.")
    print("Wrote hazard.tif, hazard.png, relief.png, slope.png to data/out/ and terrain/hazard_stats.json")


if __name__ == "__main__":
    main()
