"""Build the hazard map from the terrain model.

Reads data/out/dem.tif (HiRISE heights on the site grid), data/out/thermal_inertia.tif
(THEMIS, optional) and thresholds.toml. Writes data/out/relief.png, slope.png,
hazard.tif and hazard.png (see CONTRACT.md), and records their sources in layers.json.

    python terrain/hazards.py

Needs only data/out/, not the raw downloads, so it can run on any machine.

How a cell is classed (0 green, 1 yellow, 2 red; the worst rule wins):
- slope over [slope_deg] yellow / red. Cliffs are the steepest of these, so they are red;
  routing/config.toml adds its own buffer ring around red slopes (cliff_buffer_m).
- roughness over [roughness] yellow / red. Roughness is the RMS height difference, in
  metres, from a plane fitted to the 3 x 3 cells around the cell (15 m x 15 m).
- thermal inertia under [thermal_inertia] yellow_below / red_below (loose sand or dust).
  THEMIS pixels are 100 m, so this marks broad sandy patches, not single ripples.
- no height, or no slope or roughness because a neighbour has no height: red. A cell
  without data is never shown as safe (FR-40). It is drawn in a darker red in hazard.png.
"""
import datetime
import json
import sys
import tomllib
from pathlib import Path

import numpy as np
import rasterio
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "out"

GREEN, YELLOW, RED = 0, 1, 2
ROUGH_WINDOW = 3  # cells per side of the roughness window

# hazard.png colours. The web app reads them back with classifyPixel (web/src/lib/routeCheck.js):
# see-through = fine, red > 180 and green < 110 = red, red > 200 and green > 150 = yellow.
HAZARD_RGBA = {GREEN: (34, 170, 90, 0), YELLOW: (240, 190, 40, 150), RED: (220, 50, 50, 170)}
NO_DATA_RGBA = (185, 30, 90, 210)  # still read as red by classifyPixel


def load_thresholds():
    with open(Path(__file__).with_name("thresholds.toml"), "rb") as f:
        return tomllib.load(f)


def read_raster(name):
    """(float64 array with NaN for no data, rasterio profile), or (None, None) if missing."""
    path = OUT / name
    if not path.is_file():
        return None, None
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float64)
        if src.nodata is not None and not np.isnan(src.nodata):
            arr[arr == src.nodata] = np.nan
        arr[~np.isfinite(arr)] = np.nan
        return arr, src.profile


def grid_cell_m():
    index = json.loads((OUT / "layers.json").read_text(encoding="utf-8"))
    return float(index["site"]["grid"]["cell_m"]), index


def slope_deg(dem, cell_m):
    """Same maths as routing/grid.py slope_deg and web/src/lib/terrain.js slopeDeg:
    numpy.gradient (central differences, one-sided at the edges). NaN spreads to neighbours."""
    dz_drow, dz_dx = np.gradient(dem, cell_m)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_drow)))
    slope[np.isnan(dem)] = np.nan
    return slope


def hillshade(dem, cell_m, azimuth_deg=315.0, altitude_deg=45.0):
    """0..1 brightness, light from azimuth (clockwise from north) and altitude above the horizon."""
    dz_drow, dz_dx = np.gradient(dem, cell_m)
    dz_dnorth = -dz_drow  # row 0 is the north edge, so rows run south
    az, alt = np.radians(azimuth_deg), np.radians(altitude_deg)
    sun = np.array([np.sin(az) * np.cos(alt), np.cos(az) * np.cos(alt), np.sin(alt)])  # east, north, up
    normal = np.stack([-dz_dx, -dz_dnorth, np.ones_like(dem)], axis=-1)
    shade = (normal @ sun) / np.linalg.norm(normal, axis=-1)
    return np.clip(shade, 0, 1)


def roughness_m(dem, cell_m, k=ROUGH_WINDOW):
    """RMS residual (m) from a least-squares plane over the k x k cells centred on each cell.
    Edges reuse the edge heights; a window holding a NaN gives NaN."""
    p = k // 2
    win = sliding_window_view(np.pad(dem, p, mode="edge"), (k, k))
    d = (np.arange(k) - p) * cell_m
    dx, dy = d[None, :], d[:, None]
    # On a regular symmetric grid the plane terms separate: mean, x slope, y slope.
    a = win.mean(axis=(-1, -2))
    bx = (win * dx).sum(axis=(-1, -2)) / (k * (d**2).sum())
    by = (win * dy).sum(axis=(-1, -2)) / (k * (d**2).sum())
    res = win - a[..., None, None] - bx[..., None, None] * dx - by[..., None, None] * dy
    return np.sqrt((res**2).sum(axis=(-1, -2)) / (k * k - 3))


def classify(slope, rough, ti, t):
    """Hazard classes and the no-data mask. rough or ti may be None to skip that rule
    (the crater-wide build in data/adapters/crater.py uses slope only)."""
    hazard = np.full(slope.shape, GREEN, np.uint8)

    def mark(mask, level):
        hazard[mask & (hazard < level)] = level

    with np.errstate(invalid="ignore"):
        mark(slope > t["slope_deg"]["yellow"], YELLOW)
        mark(slope > t["slope_deg"]["red"], RED)
        if rough is not None:
            mark(rough > t["roughness"]["yellow"], YELLOW)
            mark(rough > t["roughness"]["red"], RED)
        if ti is not None:  # a cell with no THEMIS value skips only this rule
            mark(ti < t["thermal_inertia"]["yellow_below"], YELLOW)
            mark(ti < t["thermal_inertia"]["red_below"], RED)
    no_data = np.isnan(slope) if rough is None else np.isnan(slope) | np.isnan(rough)
    hazard[no_data] = RED
    return hazard, no_data


def slope_rgba(slope):
    """Same colour scale as the fake slope.png: blue-green at 0 degrees to red at 30 and above."""
    v = np.clip(np.nan_to_num(slope) / 30, 0, 1)
    return np.dstack([255 * v, 120 * (1 - v), 200 * (1 - v), np.where(np.isnan(slope), 0, 170)])


def hazard_rgba(hazard, no_data):
    rgba = np.zeros(hazard.shape + (4,))
    for level, colour in HAZARD_RGBA.items():
        rgba[hazard == level] = colour
    rgba[no_data] = NO_DATA_RGBA
    return rgba


def save_png(name, rgba):
    Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA").save(OUT / name)


def write_outputs(dem_profile, slope, shade, hazard, no_data, t):
    tone = 0.25 + 0.75 * shade
    relief = np.dstack([tone[..., None] * np.array([215, 150, 105]), np.where(np.isnan(shade), 0, 255)])
    save_png("relief.png", relief)
    save_png("slope.png", slope_rgba(slope))
    save_png("hazard.png", hazard_rgba(hazard, no_data))

    profile = {**dem_profile, "dtype": "uint8", "nodata": None, "count": 1}
    with rasterio.open(OUT / "hazard.tif", "w", **profile) as dst:
        dst.write(hazard, 1)
        dst.update_tags(
            classes="0 green fine, 1 yellow careful, 2 red do not enter (also no data)",
            thresholds=json.dumps(t),
            no_data_cells=str(int(no_data.sum())),
        )


def update_layers(index, ti_used, t):
    sys.path.insert(0, str(ROOT / "data"))
    import grid  # data/grid.py: updates layers.json without disturbing other entries

    notes = index.get("sources_notes", {})
    dtm = notes.get("dem.tif", "HiRISE (MRO) terrain model")
    today = datetime.date.today().isoformat()
    s, r, ti = t["slope_deg"], t["roughness"], t["thermal_inertia"]

    relief_src = f"Derived from {dtm}: hillshade, sun azimuth 315°, altitude 45°"
    slope_src = f"Derived from {dtm}: slope in degrees (central differences on the {grid_cell_m()[0]:g} m grid)"
    hazard_src = ("Derived from HiRISE (MRO) slope and roughness"
                  + (" and THEMIS (Mars Odyssey) thermal inertia" if ti_used else "")
                  + ", thresholds in terrain/thresholds.toml")
    for id_, src in (("relief", relief_src), ("slope", slope_src), ("hazard", hazard_src)):
        grid.update_layers_json(layer={"id": id_, "source": src})

    grid.update_layers_json(extra={
        "relief.png": f"{relief_src}. Built {today} by terrain/hazards.py. Confidence: high (direct from the DTM).",
        "slope.png": f"{slope_src}. Built {today} by terrain/hazards.py. Confidence: high at 5 m scale; "
                     "slopes shorter than one cell (5 m) are smoothed out.",
        "hazard.tif": (
            f"{hazard_src}. Built {today} by terrain/hazards.py. Careful over {s['yellow']}°, no-go over {s['red']}° "
            f"(cliffs included); roughness over {r['yellow']} / {r['red']} m RMS from a local plane (3 x 3 cells); "
            + (f"thermal inertia under {ti['yellow_below']} / {ti['red_below']} SI (THEMIS 100 m pixels, coarse); "
               if ti_used else "thermal inertia not used (thermal_inertia.tif missing); ")
            + "cells without height data are no-go. Confidence: medium. The thresholds are starting values, "
            "and boulders smaller than the 5 m grid are not visible."
        ),
    })


def main():
    t = load_thresholds()
    dem, profile = read_raster("dem.tif")
    if dem is None:
        sys.exit("data/out/dem.tif is missing. Run python data/make_fake.py or the hirise step first.")
    cell_m, index = grid_cell_m()
    if (dem.shape[1], dem.shape[0]) != (index["site"]["grid"]["width"], index["site"]["grid"]["height"]):
        sys.exit(f"dem.tif is {dem.shape[1]} x {dem.shape[0]}, layers.json says otherwise")

    ti, _ = read_raster("thermal_inertia.tif")
    if ti is not None and ti.shape != dem.shape:
        print("WARNING thermal_inertia.tif is not on the dem.tif grid: skipping the sand rule")
        ti = None

    slope = slope_deg(dem, cell_m)
    shade = hillshade(dem, cell_m)
    rough = roughness_m(dem, cell_m)
    hazard, no_data = classify(slope, rough, ti, t)
    write_outputs(profile, slope, shade, hazard, no_data, t)

    dem_is_fake = "dem.tif" not in index.get("sources_notes", {})
    if dem_is_fake:
        print("dem.tif has no source in layers.json (fake terrain): layers keep their FAKE tags")
    else:
        update_layers(index, ti is not None, t)

    n = hazard.size
    print(f"Slope: median {np.nanmedian(slope):.1f} deg, max {np.nanmax(slope):.1f} deg")
    print(f"Roughness: median {np.nanmedian(rough):.2f} m, 99th percentile {np.nanpercentile(rough, 99):.2f} m")
    print(f"Hazard cells: {(hazard == GREEN).sum() / n:.1%} green, {(hazard == YELLOW).sum() / n:.1%} yellow, "
          f"{(hazard == RED).sum() / n:.1%} red ({int(no_data.sum())} without data)")
    return [f"relief.png, slope.png, hazard.tif, hazard.png from dem.tif"
            + (" and thermal_inertia.tif" if ti is not None else "")]


def run(site=None):
    """Entry point for data/build_real.py (the site settings are not needed)."""
    return main()


if __name__ == "__main__":
    main()
