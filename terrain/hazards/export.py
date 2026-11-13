"""PNG map layers for the front end (Person 4) plus a manifest describing them."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib import colormaps
from matplotlib.colors import to_rgba
from PIL import Image

from . import CLASS_COLORS, CLASS_NAMES


def _save(path: Path, rgba: np.ndarray) -> None:
    Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), "RGBA").save(path, optimize=True)


def ramp_png(path, arr, vmin, vmax, cmap, nan_alpha=0.0):
    norm = (np.asarray(arr, float) - vmin) / (vmax - vmin)
    rgba = colormaps[cmap](np.nan_to_num(np.clip(norm, 0, 1)))
    rgba[~np.isfinite(arr), 3] = nan_alpha
    _save(path, rgba)


def hillshade_png(path, shade, gap):
    g = 0.15 + 0.8 * shade
    rgba = np.dstack([g * 0.98, g * 0.80, g * 0.66, np.ones_like(g)])  # Mars-tinted grey
    rgba[gap] = (0, 0, 0, 0)
    _save(path, rgba)


def classes_png(path, classes, palette: dict, unknown_hatch=True):
    rgba = np.zeros(classes.shape + (4,))
    for value, colour in palette.items():
        rgba[classes == value] = to_rgba(colour)
    if unknown_hatch and 3 in palette:  # diagonal stripes so "unknown" never looks like terrain
        yy, xx = np.indices(classes.shape)
        stripe = ((yy + xx) // 6) % 2 == 0
        rgba[(classes == 3) & stripe] = to_rgba("#5a5a5a")
    _save(path, rgba)


def export_all(out: Path, grid, *, shade, slope, classes, gap, cfg, thermal=None, minerals=None):
    d = cfg["display"]
    bounds = grid.leaflet_bounds
    entries = []

    def add(id_, file, title, units, legend, source):
        entries.append({"id": id_, "file": file, "title": title, "units": units,
                        "bounds": bounds, "legend": legend, "source": source})

    hillshade_png(out / "shaded_relief.png", shade, gap)
    add("shaded_relief", "shaded_relief.png", "Shaded relief", None, None,
        f"Computed from DTM, sun az {d['hillshade_azimuth_deg']}°, alt {d['hillshade_altitude_deg']}°")

    smax = d["slope_png_max_deg"]
    ramp_png(out / "slope.png", np.where(gap, np.nan, slope), 0, smax, "magma_r")
    add("slope", "slope.png", "Slope", "degrees",
        {"type": "ramp", "min": 0, "max": smax, "cmap": "magma_r",
         "marks": [cfg["slope_deg"]["yellow"], cfg["slope_deg"]["red"]]}, "Computed from DTM")

    hz_palette = {k: CLASS_COLORS[k] for k in CLASS_NAMES}
    classes_png(out / "hazards.png", classes, hz_palette)
    add("hazards", "hazards.png", "EVA hazard classes", "class",
        {"type": "classes", "items": [{"value": k, "name": CLASS_NAMES[k], "color": CLASS_COLORS[k]} for k in CLASS_NAMES]},
        "Slope + roughness + cliff + rocks + thermal inertia; thresholds in config/hazards.yaml")

    if thermal is not None:
        lo, hi = d["thermal_png_range_tiu"]
        ramp_png(out / "thermal.png", thermal, lo, hi, "inferno")
        add("thermal_inertia", "thermal.png", "Thermal inertia (low = loose sand)", "TIU",
            {"type": "ramp", "min": lo, "max": hi, "cmap": "inferno",
             "marks": [cfg["thermal_inertia_tiu"]["very_loose"], cfg["thermal_inertia_tiu"]["loose"]]},
            "thermal_inertia layer from layers.json")

    if minerals is not None:
        mc = {int(k): v for k, v in d["minerals_classes"].items()}
        classes_png(out / "minerals.png", np.nan_to_num(minerals).astype(int),
                    {k: v["color"] for k, v in mc.items()}, unknown_hatch=False)
        add("minerals", "minerals.png", "Mineral map", "class",
            {"type": "classes", "items": [{"value": k, "name": v["name"], "color": v["color"]} for k, v in mc.items() if k != 0]},
            "minerals layer from layers.json")

    return entries
