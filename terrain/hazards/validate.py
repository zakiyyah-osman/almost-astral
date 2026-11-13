"""Sanity checks: do real rover tracks land on passable cells?"""
from __future__ import annotations

import numpy as np

from . import GREEN, YELLOW, RED, UNKNOWN, CLASS_NAMES, REASON_BITS


def _lines(geojson: dict):
    for f in geojson.get("features", []):
        g = f.get("geometry") or {}
        name = (f.get("properties") or {}).get("name", "track")
        if g.get("type") == "LineString":
            yield name, np.asarray(g["coordinates"], float)[:, :2]
        elif g.get("type") == "MultiLineString":
            for part in g["coordinates"]:
                yield name, np.asarray(part, float)[:, :2]


def sample_line(coords: np.ndarray, step_m: float) -> np.ndarray:
    pts = [coords[0]]
    for a, b in zip(coords[:-1], coords[1:]):
        n = max(1, int(np.ceil(np.hypot(*(b - a)) / step_m)))
        t = np.linspace(0, 1, n + 1)[1:, None]
        pts.extend(a + t * (b - a))
    return np.asarray(pts)


def check_tracks(tracks: dict, grid, classes, reasons, slope, max_red_fraction: float) -> dict:
    """Sample every track at grid resolution and report what it crosses."""
    report = {"tracks": [], "passed": True}
    rows, cols = classes.shape
    for name, coords in _lines(tracks):
        pts = sample_line(coords, grid.cell_m)
        r, c = grid.to_rowcol(pts[:, 0], pts[:, 1])
        r, c = np.round(r).astype(int), np.round(c).astype(int)
        inside = (r >= 0) & (r < rows) & (c >= 0) & (c < cols)
        cls = classes[r[inside], c[inside]]
        n = len(cls)
        known = cls != UNKNOWN
        frac = {CLASS_NAMES[k]: float(np.mean(cls == k)) if n else 0.0 for k in (GREEN, YELLOW, RED, UNKNOWN)}
        red_frac_known = float(np.mean(cls[known] == RED)) if known.any() else 0.0

        red_idx = np.flatnonzero(cls == RED)
        why = {}
        for i in red_idx:
            bits = reasons[r[inside][i], c[inside][i]]
            for k, v in REASON_BITS.items():
                if bits & v:
                    why[k] = why.get(k, 0) + 1
        ok = red_frac_known <= max_red_fraction
        report["passed"] &= ok
        report["tracks"].append({
            "name": name,
            "length_m": float(np.sum(np.hypot(*np.diff(coords, axis=0).T))),
            "samples": int(n),
            "outside_grid": int((~inside).sum()),
            "fraction_by_class": frac,
            "red_fraction_of_known": red_frac_known,
            "red_reasons": dict(sorted(why.items(), key=lambda kv: -kv[1])),
            "max_slope_deg": float(np.nanmax(slope[r[inside], c[inside]])) if n else None,
            "first_red_points_en": pts[inside][red_idx[:10]].round(1).tolist(),
            "passed": ok,
        })
    if not report["tracks"]:
        report["passed"] = None
    return report
