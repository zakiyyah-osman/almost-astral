"""Output files in the team's naming: hazard.png, hazard.tif, relief.png, slope.png,
plus coverage.tif / coverage.png for the 'Unknown terrain coverage' areas."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib import colormaps
from PIL import Image

from . import CONTRACT_RGBA, GREEN, RED, UNKNOWN, YELLOW


def _save_rgba8(path: Path, rgba8: np.ndarray) -> None:
    Image.fromarray(rgba8.astype(np.uint8), "RGBA").save(path, optimize=True)


def contract_classes(classes: np.ndarray) -> np.ndarray:
    """0/1/2 only: unknown (no terrain data) becomes 2, never 'go'."""
    out = classes.copy()
    out[classes == UNKNOWN] = RED
    return out.astype(np.uint8)


def hazard_png(path: Path, classes012: np.ndarray) -> None:
    rgba = np.zeros(classes012.shape + (4,), np.uint8)
    for k in (GREEN, YELLOW, RED):
        rgba[classes012 == k] = CONTRACT_RGBA[k]
    _save_rgba8(path, rgba)


def coverage_png(path: Path, gap: np.ndarray) -> None:
    """Grey diagonal stripes where there is no terrain data, transparent elsewhere."""
    yy, xx = np.indices(gap.shape)
    stripe = ((yy + xx) // 4) % 2 == 0
    rgba = np.zeros(gap.shape + (4,), np.uint8)
    rgba[gap & stripe] = (90, 90, 90, 230)
    rgba[gap & ~stripe] = (200, 200, 200, 140)
    _save_rgba8(path, rgba)


def relief_png(path: Path, shade: np.ndarray, gap: np.ndarray) -> None:
    g = 0.15 + 0.8 * shade
    rgba = np.dstack([g * 0.98, g * 0.80, g * 0.66, np.ones_like(g)])
    rgba[gap] = 0
    _save_rgba8(path, np.clip(rgba, 0, 1) * 255)


def ramp_png(path: Path, arr: np.ndarray, vmin: float, vmax: float, cmap: str) -> None:
    norm = (np.asarray(arr, float) - vmin) / (vmax - vmin)
    rgba = colormaps[cmap](np.nan_to_num(np.clip(norm, 0, 1)))
    rgba[~np.isfinite(arr), 3] = 0
    _save_rgba8(path, rgba * 255)


def export_all(out: Path, grid, *, shade, slope, classes, gap, cfg) -> list[dict]:
    """Write the PNGs and return manifest entries describing them."""
    d = cfg["display"]
    smax = d["slope_png_max_deg"]
    relief_png(out / "relief.png", shade, gap)
    ramp_png(out / "slope.png", np.where(gap, np.nan, slope), 0, smax, "magma_r")
    hazard_png(out / "hazard.png", contract_classes(classes))
    coverage_png(out / "coverage.png", gap)
    bounds = grid.leaflet_bounds
    return [
        {"id": "relief", "file": "relief.png", "title": "Shaded relief", "bounds": bounds,
         "source": f"Computed from the terrain model, sun az {d['hillshade_azimuth_deg']}°, alt {d['hillshade_altitude_deg']}°"},
        {"id": "slope", "file": "slope.png", "title": "Slope", "units": "degrees", "bounds": bounds,
         "legend": {"type": "ramp", "min": 0, "max": smax, "cmap": "magma_r",
                    "marks": [cfg["slope_deg"]["yellow"], cfg["slope_deg"]["red"]]},
         "source": "Computed from the terrain model"},
        {"id": "hazard", "file": "hazard.png", "title": "Hazards", "bounds": bounds,
         "legend": {"type": "classes", "items": [
             {"value": 0, "name": "Go", "color": "transparent"},
             {"value": 1, "name": "Caution", "color": "#f0be28"},
             {"value": 2, "name": "No-go", "color": "#dc3232"}]},
         "source": "Slope, roughness, cliffs, rocks and thermal inertia; thresholds in config/hazards.yaml"},
        {"id": "coverage", "file": "coverage.png", "title": "Unknown terrain coverage", "bounds": bounds,
         "legend": {"type": "classes", "items": [{"value": 0, "name": "No terrain data", "color": "#8a8a8a"}]},
         "source": "Cells where the terrain model has no data (also no-go in hazard.tif)"},
    ]
