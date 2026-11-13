"""Stand-in inputs in the shared layers.json format, so Person 2's pipeline can run
before Person 1's data/ folder is ready. NOT real Mars data - every file is labelled
"SIMULATED" in its source field.

    python tools/make_mock_data.py --out data_mock --size 1000
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import tifffile
from scipy.ndimage import gaussian_filter, distance_transform_edt
from scipy.special import expit
from skimage.graph import MCP_Geometric


def synthetic_dtm(n, rng):
    # Step 2 of the team plan, with one fix: weight by s**2 (not s). With s**1 the
    # 4-cell noise is as tall as the 200-cell hills, so 1 m cells are ~50 deg steep.
    z = sum(gaussian_filter(rng.normal(size=(n, n)), s) * s**2 for s in (4, 16, 64, 200))
    z = (z - z.min()) / np.ptp(z) * 120
    yy, xx = np.mgrid[0:n, 0:n]
    craters = []
    for _ in range(25):
        cx, cy, r = *rng.integers(0, n, 2).tolist(), int(rng.integers(5, 60))
        d = np.hypot(xx - cx, yy - cy) / r
        z += np.where(d < 1, -0.2 * r * (1 - d**2), np.where(d < 1.5, 0.05 * r * (1.5 - d), 0))
        craters.append((cx, cy, r))
    return z, yy, xx, craters


def add_boxwork(z, yy, xx, rng, centre, radius):
    """Boxwork: a net of narrow resistant ridges ~1.5 m high around hollows."""
    n = z.shape[0]
    seeds = rng.uniform([centre[0] - radius, centre[1] - radius], [centre[0] + radius, centre[1] + radius], (60, 2))
    lab = np.zeros(z.shape, int)
    lab[np.clip(seeds[:, 0].astype(int), 0, n - 1), np.clip(seeds[:, 1].astype(int), 0, n - 1)] = np.arange(1, 61)
    _, idx = distance_transform_edt(lab == 0, return_indices=True)
    cells = lab[idx[0], idx[1]]
    edge = np.zeros(z.shape, bool)
    edge[:-1] |= cells[:-1] != cells[1:]
    edge[:, :-1] |= cells[:, :-1] != cells[:, 1:]
    ridge = gaussian_filter(edge.astype(float), 1.2)
    ridge = ridge / ridge.max()
    inside = np.clip(1.2 - np.hypot(yy - centre[0], xx - centre[1]) / radius, 0, 1)
    return z + 1.5 * ridge * inside


def add_scarp(z, yy, xx, height=6.0):
    """A straight scarp (cliff) running SW-NE through the east half."""
    n = z.shape[0]
    d = (xx - 0.75 * n) - 0.4 * (yy - 0.5 * n)
    # a ~40 m wide ramp (about 8 deg) breaks the cliff so rovers and crews can climb it
    width = 0.6 + 9.4 * np.clip(1 - np.abs(yy - 0.55 * n) / (0.03 * n), 0, 1)
    return z + height * expit(d / width)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data_mock")
    p.add_argument("--size", type=int, default=1000, help="cells per side (1 m cells)")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    rng = np.random.default_rng(a.seed)
    n, cell = a.size, 1.0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    z, yy, xx, craters = synthetic_dtm(n, rng)
    z = add_boxwork(z, yy, xx, rng, centre=(0.35 * n, 0.35 * n), radius=0.18 * n)
    z = add_scarp(z, yy, xx)
    z = z - 4200.0  # Gale floor is roughly -4.2 km relative to the Mars datum
    dtm = z.astype(np.float32)
    dtm[int(0.62 * n):int(0.74 * n), int(0.10 * n):int(0.24 * n)] = np.nan  # coverage gap
    tifffile.imwrite(out / "dtm.tif", dtm, compression="zlib")

    # thermal inertia: bedrock high, a sand sheet in the south-west low
    ti = 420 + 160 * gaussian_filter(rng.normal(size=(n, n)), 25) * 25
    sand = np.exp(-(((yy - 0.85 * n) / (0.08 * n)) ** 2 + ((xx - 0.45 * n) / (0.20 * n)) ** 2))
    ti = np.clip(ti * (1 - 0.85 * sand), 40, 1200).astype(np.float32)
    tifffile.imwrite(out / "ti.tif", ti, compression="zlib")

    # minerals: sulfate background, clays in the boxwork hollows, hematite patch, basaltic sand
    m = np.ones((n, n), np.uint8)
    m[np.hypot(yy - 0.35 * n, xx - 0.35 * n) < 0.15 * n] = 2
    m[np.hypot(yy - 0.20 * n, xx - 0.70 * n) < 0.06 * n] = 3
    m[sand > 0.5] = 4
    m[gaussian_filter(rng.normal(size=(n, n)), 8) > 0.03] = 0
    tifffile.imwrite(out / "minerals.tif", m, compression="zlib")

    # rocks: background scatter + a dense blocky field below the scarp
    def rocks_in(k, e0, e1, n0, n1, scale):
        return [(float(rng.uniform(e0, e1)), float(rng.uniform(n0, n1)), float(rng.pareto(2.5) * scale + 0.2))
                for _ in range(k)]
    W = n * cell
    rocks = rocks_in(1500, 0, W, 0, W, 0.15) + rocks_in(3000, 0.78 * W, 0.92 * W, 0.15 * W, 0.40 * W, 0.4)
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(e, 2), round(nn, 2)]},
              "properties": {"diameter_m": round(d, 2)}} for e, nn, d in rocks]
    (out / "rocks.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))

    # a plausible rover track: a drive that avoids steep ground (rovers keep < ~20 deg)
    gy, gx = np.gradient(np.nan_to_num(z, nan=np.nanmean(z)), cell)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    from scipy.ndimage import binary_dilation, maximum_filter, minimum_filter
    relief = maximum_filter(z, 3) - minimum_filter(z, 3)
    blocked = binary_dilation((slope > 18) | (relief > 1.2) | np.isnan(dtm), iterations=4)
    cost = 1 + (slope / 8) ** 4
    cost[blocked] = 1e6
    rr = lambda e, nn: (int(n - nn / cell), int(e / cell))  # [east,north] -> (row,col)
    stops = [(0.08 * W, 0.08 * W), (0.30 * W, 0.40 * W), (0.55 * W, 0.62 * W), (0.62 * W, 0.90 * W)]
    path = []
    for (e0, n0), (e1, n1) in zip(stops[:-1], stops[1:]):
        mcp = MCP_Geometric(cost)
        mcp.find_costs([rr(e0, n0)], [rr(e1, n1)])
        path += mcp.traceback(rr(e1, n1))
    coords = [[round((c + 0.5) * cell, 1), round(W - (r + 0.5) * cell, 1)] for r, c in path[::5]]
    tracks = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
         "properties": {"name": "simulated rover drive"}},
        {"type": "Feature", "properties": {"name": "deliberately bad line (should FAIL)"},
         "geometry": {"type": "LineString", "coordinates": [[0.70 * W, 0.30 * W], [0.95 * W, 0.40 * W]]}},
    ]}
    (out / "rover_tracks.geojson").write_text(json.dumps(tracks))

    # landmarks: features anyone can find on every layer, used to check alignment
    def en(col, row):
        return [round((col + 0.5) * cell, 1), round(W - (row + 0.5) * cell, 1)]
    marks = [("Crater %s (r=%d m)" % (chr(65 + i), r), "crater_centre", en(cx, cy))
             for i, (cx, cy, r) in enumerate(sorted([c for c in craters if 0.1 * n < c[0] < 0.9 * n and 0.1 * n < c[1] < 0.9 * n],
                                                    key=lambda c: -c[2])[:4])]
    marks += [("Boxwork network centre", "boxwork", en(0.35 * n, 0.35 * n)),
              ("Scarp ramp", "ramp", en(0.75 * n + 0.4 * 0.05 * n, 0.55 * n)),
              ("Coverage gap NE corner", "gap_corner", en(0.24 * n, 0.62 * n))]
    lm = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": c}, "properties": {"name": nm, "kind": k}}
        for nm, k, c in marks]}
    (out / "landmarks.geojson").write_text(json.dumps(lm, indent=2))

    src = "SIMULATED stand-in (tools/make_mock_data.py) - replace with Person 1's data"
    layers = {
        "site": {"name": "Gale - Boxwork (SIMULATED)", "crs": "local_meters", "origin_latlon": [-4.7, 137.4],
                 "width_m": W, "height_m": W, "cell_m": cell, "simulated": True,
                 # SW corner of the grid in the source map projection (metres). Person 2 fills
                 # this in on dataset day from the real imagery's georeferencing.
                 "source_crs": "Mars 2000 equirectangular, centre lon 0, lat_ts 0, R=3396190 m (placeholder)",
                 "origin_source_xy": [round(3396190 * np.radians(137.4), 1), round(3396190 * np.radians(-4.7), 1)]},
        "layers": [
            {"id": "dtm", "kind": "raster", "units": "m", "file": "dtm.tif", "source": src},
            {"id": "thermal_inertia", "kind": "raster", "units": "TIU", "file": "ti.tif", "source": src},
            {"id": "minerals", "kind": "raster", "units": "class", "file": "minerals.tif", "source": src},
            {"id": "rocks", "kind": "vector", "file": "rocks.geojson", "source": src},
            {"id": "rover_tracks", "kind": "vector", "file": "rover_tracks.geojson", "source": src},
            {"id": "landmarks", "kind": "vector", "file": "landmarks.geojson", "source": src},
        ],
    }
    (out / "layers.json").write_text(json.dumps(layers, indent=2))
    print(f"Wrote stand-in data to {out}/")


if __name__ == "__main__":
    main()
