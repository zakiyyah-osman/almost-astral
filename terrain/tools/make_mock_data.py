"""Stand-in inputs in the TEAM's layers.json format (Jezero-style site, 2000 m at 5 m
cells), so Person 2's code can be tested without the real files. NOT real Mars data:
everything is labelled FAKE / SIMULATED.

    python tools/make_mock_data.py --out data_mock            # 400 x 400 cells of 5 m
    python tools/make_mock_data.py --out tiny --size 120      # quick test site
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import tifffile
from scipy.ndimage import (binary_dilation, distance_transform_edt, gaussian_filter,
                           maximum_filter, minimum_filter)
from scipy.special import expit
from skimage.graph import MCP_Geometric

R = 3396190.0


def terrain(n, cell, rng):
    """Fractal hills + craters + boxwork-like ridges + a scarp with a ramp (metres)."""
    # weight by s**2: with s**1 the smallest bumps are as tall as the hills (everything > 25 deg)
    z = sum(gaussian_filter(rng.normal(size=(n, n)), s) * s**2 for s in (2, 6, 20, 60))
    z = (z - z.min()) / np.ptp(z) * 90.0
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    craters = []
    for _ in range(18):
        cx, cy = rng.uniform(0, n, 2)
        r = rng.uniform(4, 22)                        # cells
        d = np.hypot(xx - cx, yy - cy) / r
        depth = 0.2 * r * cell
        z += np.where(d < 1, -depth * (1 - d**2), np.where(d < 1.6, 0.25 * depth * (1.6 - d) / 0.6, 0))
        craters.append((cx, cy, r))
    # ridge network (boxwork / fractured delta caprock): 4 m high narrow ridges
    seeds = rng.uniform([0.2 * n, 0.2 * n], [0.5 * n, 0.5 * n], (40, 2)).astype(int)
    lab = np.zeros((n, n), int)
    lab[seeds[:, 0], seeds[:, 1]] = np.arange(1, 41)
    _, idx = distance_transform_edt(lab == 0, return_indices=True)
    cells = lab[idx[0], idx[1]]
    edge = np.zeros((n, n), bool)
    edge[:-1] |= cells[:-1] != cells[1:]
    edge[:, :-1] |= cells[:, :-1] != cells[:, 1:]
    inside = np.clip(1.3 - np.hypot(yy - 0.35 * n, xx - 0.35 * n) / (0.17 * n), 0, 1)
    ridge = gaussian_filter(edge.astype(float), 0.6)
    z += 4.0 * ridge / ridge.max() * inside
    # delta-front scarp, 25 m high, with a gentle ramp near row 0.55 n
    d = (xx - 0.72 * n) - 0.4 * (yy - 0.5 * n)
    width = 0.8 + 11 * np.clip(1 - np.abs(yy - 0.55 * n) / (0.035 * n), 0, 1)
    z += 25.0 * expit(d / width)
    return z - 2500.0, craters  # Jezero floor is roughly -2.5 km


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data_mock")
    p.add_argument("--size", type=int, default=400, help="cells per side")
    p.add_argument("--cell", type=float, default=5.0, help="cell size in m")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    rng = np.random.default_rng(a.seed)
    n, cell = a.size, a.cell
    W = n * cell
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    z, craters = terrain(n, cell, rng)
    dem = z.astype(np.float32)
    dem[int(0.62 * n):int(0.74 * n), int(0.10 * n):int(0.24 * n)] = -3.4028227e38  # HiRISE-style nodata
    # georeferenced like the team's dem.tif: transform (cell, 0, 0, 0, -cell, height_m), pixel corners
    geo = [(33550, "d", 3, (cell, cell, 0.0), False),
           (33922, "d", 6, (0.0, 0.0, 0.0, 0.0, W, 0.0), False),
           (34735, "H", 12, (1, 1, 0, 2, 1024, 0, 1, 1, 1025, 0, 1, 1), False)]  # projected, PixelIsArea
    tifffile.imwrite(out / "dem.tif", dem, compression="zlib", extratags=geo)

    yy, xx = np.mgrid[0:n, 0:n]
    ti = 380 + 2500 * gaussian_filter(rng.normal(size=(n, n)), 12)
    sand = np.exp(-(((yy - 0.85 * n) / (0.07 * n)) ** 2 + ((xx - 0.45 * n) / (0.2 * n)) ** 2))
    ti = np.clip(ti * (1 - 0.85 * sand), 40, 1200).astype(np.float32)
    ti = gaussian_filter(ti, 4)  # THEMIS is ~100 m: soft edges
    tifffile.imwrite(out / "thermal_inertia.tif", ti.astype(np.float32), compression="zlib", extratags=geo)

    en = lambda col, row: [round((col + 0.5) * cell, 1), round(W - (row + 0.5) * cell, 1)]
    rocks = []
    for k, (e0, e1, n0, n1, scale) in enumerate([(0, W, 0, W, 0.2), (0.78 * W, 0.92 * W, 0.15 * W, 0.40 * W, 0.5)]):
        cnt = 3000 if k else 2500
        rocks += [(float(rng.uniform(e0, e1)), float(rng.uniform(n0, n1)), float(rng.pareto(2.5) * scale + 0.3)) for _ in range(cnt)]
    fc = lambda feats: {"type": "FeatureCollection", "features": feats}
    pt = lambda c, props: {"type": "Feature", "geometry": {"type": "Point", "coordinates": c}, "properties": props}
    (out / "rocks.geojson").write_text(json.dumps(fc([pt([round(e, 1), round(nn, 1)], {"diameter_m": round(d, 2)}) for e, nn, d in rocks])))

    # a plausible rover drive that keeps off steep ground and scarps
    zf = np.nan_to_num(np.where(dem < -1e30, np.nan, dem), nan=float(np.nanmean(z)))
    gy, gx = np.gradient(zf, cell)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    rel = maximum_filter(zf, 3) - minimum_filter(zf, 3)
    blocked = binary_dilation((slope > 16) | (rel > 6) | (dem < -1e30), iterations=2)
    cost = 1 + (slope / 8) ** 4
    cost[blocked] = 1e6
    rc = lambda e, nn: (int((W - nn) / cell), int(e / cell))
    stops = [(0.08 * W, 0.08 * W), (0.30 * W, 0.40 * W), (0.55 * W, 0.62 * W), (0.62 * W, 0.90 * W)]
    path = []
    for (e0, n0), (e1, n1) in zip(stops[:-1], stops[1:]):
        m = MCP_Geometric(cost)
        m.find_costs([rc(e0, n0)], [rc(e1, n1)])
        path += m.traceback(rc(e1, n1))
    drive = [en(c, r) for r, c in path[::2]]
    line = lambda coords, name: {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": {"name": name}}
    (out / "rover_tracks.geojson").write_text(json.dumps(fc([
        line(drive, "simulated rover drive"),
        line([[0.70 * W, 0.30 * W], [0.95 * W, 0.40 * W]], "deliberately bad line (should FAIL)"),
    ])))
    # a route straight through the coverage gap: must report Unknown terrain coverage
    (out / "route.geojson").write_text(json.dumps(fc([line([[0.05 * W, 0.32 * W], [0.30 * W, 0.32 * W]], "test route through coverage gap")])))

    big = sorted([c for c in craters if 0.1 * n < c[0] < 0.9 * n and 0.1 * n < c[1] < 0.9 * n], key=lambda c: -c[2])[:4]
    marks = [pt(en(cx, cy), {"name": f"Crater {chr(65 + i)} (r={r * cell:.0f} m)", "kind": "crater_centre"}) for i, (cx, cy, r) in enumerate(big)]
    marks += [pt(en(0.35 * n, 0.35 * n), {"name": "Ridge network centre", "kind": "ridges"}),
              pt(en(0.72 * n + 0.4 * 0.05 * n, 0.55 * n), {"name": "Scarp ramp", "kind": "ramp"}),
              pt(en(0.24 * n, 0.62 * n), {"name": "Coverage gap NE corner", "kind": "gap_corner"})]
    (out / "landmarks.geojson").write_text(json.dumps(fc(marks), indent=1))

    lat_c, lon_c = 18.46, 77.4
    x_c = R * math.radians(lon_c)  # equirectangular, lat_ts 0, lon0 0 (as the HiRISE Jezero mosaics)
    y_c = R * math.radians(lat_c)
    fake = "FAKE (SIMULATED stand-in from tools/make_mock_data.py)"
    layers = {
        "site": {
            "name": "Jezero crater (SIMULATED test site)",
            "grid": {"width": n, "height": n, "cell_m": cell},
            "extent_m": [W, W],
            "center_lat": lat_c,
            "center_lon_east": lon_c,
            "source_crs": "Mars equirectangular, lat_ts 0, lon_0 0, R 3396190 m",
            "origin_source_xy": [round(x_c - W / 2, 1), round(y_c - W / 2, 1)],
        },
        "layers": [
            {"id": "relief", "title": "Shaded relief", "file": "relief.png", "source": fake, "default": True, "opacity": 1.0},
            {"id": "slope", "title": "Slope", "file": "slope.png", "source": fake, "default": False, "opacity": 0.6},
            {"id": "hazard", "title": "Hazards", "file": "hazard.png", "source": fake, "default": True, "opacity": 0.7},
        ],
        "vectors": {"route": "route.geojson", "rocks": "rocks.geojson",
                    "rover_tracks": "rover_tracks.geojson", "landmarks": "landmarks.geojson"},
        "sources_notes": {"dem.tif": fake, "thermal_inertia.tif": fake},
    }
    (out / "layers.json").write_text(json.dumps(layers, indent=2))
    print(f"Wrote stand-in data to {out}/ ({n}x{n} cells of {cell} m)")


if __name__ == "__main__":
    main()
