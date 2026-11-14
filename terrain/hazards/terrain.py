"""Terrain derivatives: slope, roughness, cliff edges, hillshade, rock density."""
from __future__ import annotations

import numpy as np
from scipy import ndimage
from scipy.signal import fftconvolve


def fill_gaps(z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fill NaN cells with the nearest valid height so filters don't smear NaNs.
    Returns (filled, gap_mask). Gap cells are marked 'unknown' later anyway."""
    gap = ~np.isfinite(z)
    if not gap.any():
        return z.astype(float), gap
    if gap.all():
        raise ValueError("Terrain model has no valid cells.")
    idx = ndimage.distance_transform_edt(gap, return_distances=False, return_indices=True)
    return z[tuple(idx)].astype(float), gap


def slope_deg(z: np.ndarray, cell_m: float) -> np.ndarray:
    """Slope in degrees (Step 3.1 of the plan)."""
    dz_dy, dz_dx = np.gradient(z, cell_m)
    return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))


def aspect_deg(z: np.ndarray, cell_m: float) -> np.ndarray:
    """Downslope direction, degrees clockwise from north (row 0 = north)."""
    dz_drow, dz_dcol = np.gradient(z, cell_m)
    # north = -row direction, east = +col direction; downslope = -gradient
    return (np.degrees(np.arctan2(-dz_dcol, dz_drow)) + 360) % 360


def roughness_m(z: np.ndarray, cell_m: float, window_m: float) -> np.ndarray:
    """Local standard deviation of height after removing the local mean.

    A box mean reproduces a plane exactly, so a smooth slope scores ~0 and only
    bumps, blocks and small ridges count as rough."""
    n = max(3, int(round(window_m / cell_m)) | 1)  # odd window, at least 3 cells
    k = n  # pad by odd reflection: continues the local slope past the map edge,
    zp = np.pad(z, k, mode="reflect", reflect_type="odd")  # so edges aren't scored rough
    resid = zp - ndimage.uniform_filter(zp, n)
    rough = np.sqrt(np.maximum(ndimage.uniform_filter(resid**2, n), 0))
    return rough[k:-k, k:-k]


def local_relief_m(z: np.ndarray, cell_m: float, window_m: float) -> np.ndarray:
    """Max minus min height inside a window: large values = cliff / scarp edge."""
    n = max(3, int(round(window_m / cell_m)) | 1)
    return ndimage.maximum_filter(z, n, mode="nearest") - ndimage.minimum_filter(z, n, mode="nearest")


def hillshade(z: np.ndarray, cell_m: float, azimuth_deg=315.0, altitude_deg=45.0) -> np.ndarray:
    """Shaded relief in 0..1, light from the given azimuth (clockwise from north)."""
    dz_drow, dz_dcol = np.gradient(z, cell_m)
    dz_de, dz_dn = dz_dcol, -dz_drow            # east and north gradients
    slope = np.arctan(np.hypot(dz_de, dz_dn))
    aspect = np.arctan2(-dz_de, -dz_dn)         # downslope azimuth, clockwise from north
    az, alt = np.radians(azimuth_deg), np.radians(altitude_deg)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(shade, 0, 1)


def _disk(radius_cells: float) -> np.ndarray:
    r = int(np.ceil(radius_cells))
    yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
    return (np.hypot(yy, xx) <= radius_cells).astype(float)


def rock_layers(rocks_geojson: dict, grid, cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """From rock points -> (density in rocks/m^2, large-rock obstacle mask).

    Each feature is a Point at [east, north] metres with property 'diameter_m'.
    Polygons are accepted too (their vertex mean is used as the centre)."""
    rows, cols = grid.shape
    counts = np.zeros(grid.shape)
    large = np.zeros(grid.shape, bool)
    min_d, big_d = cfg["min_diameter_m"], cfg["large_diameter_m"]

    for f in rocks_geojson.get("features", []):
        geom, props = f.get("geometry") or {}, f.get("properties") or {}
        d = float(props.get("diameter_m", props.get("diameter", 0)) or 0)
        if d < min_d:
            continue
        if geom.get("type") == "Point":
            e, n = geom["coordinates"][:2]
        elif geom.get("type") == "Polygon":
            e, n = np.mean(np.asarray(geom["coordinates"][0])[:, :2], axis=0)
        else:
            continue
        r, c = grid.to_rowcol(e, n)
        ri, ci = int(round(float(r))), int(round(float(c)))
        if 0 <= ri < rows and 0 <= ci < cols:
            counts[ri, ci] += 1
        if d >= big_d:  # stamp an obstacle disk: rock radius + clearance
            rad = (d / 2 + cfg["large_clearance_m"]) / grid.cell_m
            k = int(np.ceil(rad))
            r0, r1 = max(0, ri - k), min(rows, ri + k + 1)
            c0, c1 = max(0, ci - k), min(cols, ci + k + 1)
            if r0 < r1 and c0 < c1:
                yy, xx = np.mgrid[r0:r1, c0:c1]
                large[r0:r1, c0:c1] |= np.hypot(yy - float(r), xx - float(c)) <= rad

    kernel = _disk(cfg["density_radius_m"] / grid.cell_m)
    area_m2 = kernel.sum() * grid.cell_m**2
    density = np.clip(fftconvolve(counts, kernel, mode="same"), 0, None) / area_m2
    return density, large
