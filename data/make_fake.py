"""Make fake data for every layer so nobody has to wait for the real data.

Run from the repo root:

    python data/make_fake.py

Everything lands in data/out/, the shared folder the web app reads. File names and
formats follow CONTRACT.md. Person 1 replaces these files with real data as it
arrives; as long as the names and formats stay the same, nobody else's code changes.
"""
import csv
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin

W = H = 400  # grid size in cells
CELL_M = 5.0  # metres per cell
EXTENT_M = W * CELL_M
WALK_M_PER_MIN = 2500 / 60  # fake walking speed: 2.5 km/h
STOP_MIN = 25  # fake time spent at each stop

OUT = Path(__file__).resolve().parent / "out"
rng = np.random.default_rng(42)

# Row 0 is the north edge. x_m and y_m give each cell's centre in metres.
rows, cols = np.mgrid[0:H, 0:W]
x_m = (cols + 0.5) * CELL_M
y_m = (H - rows - 0.5) * CELL_M

ROVER = ("rover", "Rover", 1000, 900)
STOPS = [
    ("stop1", "Clay outcrop", 500, 1500, "Clay minerals can preserve traces of ancient water."),
    ("stop2", "Crater rim ridges", 1400, 1760, "Ridges left by groundwater flowing through rock cracks."),
    ("stop3", "Carbonate patch", 1600, 500, "Carbonates form in water and can trap signs of past life."),
]


def blob(cx, cy, r):
    return np.exp(-(((x_m - cx) ** 2 + (y_m - cy) ** 2) / (2 * r**2)))


def save_png(name, rgba):
    Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8)).save(OUT / name)


def save_tif(name, arr, dtype):
    with rasterio.open(
        OUT / name, "w", driver="GTiff", height=H, width=W, count=1, dtype=dtype,
        transform=from_origin(0, EXTENT_M, CELL_M, CELL_M),
    ) as dst:
        dst.write(arr.astype(dtype), 1)


def rgba(r, g, b, a):
    return np.stack([np.broadcast_to(c, (H, W)) for c in (r, g, b, a)], axis=-1)


# --- terrain -------------------------------------------------------------
dem = 80 * blob(600, 600, 300) - 60 * blob(1400, 1250, 300)
dem += 40 * np.exp(-((np.hypot(x_m - 1400, y_m - 1250) - 420) / 60) ** 2)  # crater rim
dem += 2 * np.sin(x_m / 140) * np.cos(y_m / 170) + rng.normal(0, 0.15, dem.shape)

gy, gx = np.gradient(dem, CELL_M)  # gy is per row, so it points south
slope = np.degrees(np.arctan(np.hypot(gx, gy)))

hazard = np.zeros((H, W), np.uint8)
hazard[slope >= 10] = 1
hazard[slope >= 20] = 2
for _ in range(60):  # scattered rocks
    cx, cy = rng.uniform(0, EXTENT_M, 2)
    hazard[np.hypot(x_m - cx, y_m - cy) < rng.uniform(8, 20)] = 2


def make_images():
    # shaded relief: light from the north-west
    normal = np.stack([-gx, gy, np.ones_like(gx)], axis=-1)
    light = np.array([-0.5, 0.5, 0.7])
    shade = (normal @ light) / (np.linalg.norm(normal, axis=-1) * np.linalg.norm(light))
    shade = 0.25 + 0.75 * np.clip(shade, 0, 1)
    save_png("relief.png", np.dstack([shade[..., None] * np.array([215, 150, 105]), np.full((H, W, 1), 255)]))

    v = np.clip(slope / 30, 0, 1)
    save_png("slope.png", np.dstack([255 * v, 120 * (1 - v), 200 * (1 - v), np.full((H, W), 170)]))

    colours = np.array([[34, 170, 90, 0], [240, 190, 40, 150], [220, 50, 50, 170]])
    save_png("hazard.png", colours[hazard])

    t = 0.5 + 0.35 * np.sin(x_m / 220) * np.cos(y_m / 260) - 0.3 * blob(1400, 1250, 260)
    t = np.clip(t, 0, 1)
    save_png("thermal.png", np.dstack([120 + 135 * t, 60 + 80 * t, np.full((H, W), 40), np.full((H, W), 150)]))

    img = np.zeros((H, W, 4))
    img[blob(500, 1500, 120) > 0.4] = [150, 90, 200, 170]
    img[blob(1600, 500, 110) > 0.4] = [60, 190, 150, 170]
    save_png("minerals.png", img)

    minutes = np.hypot(x_m - ROVER[2], y_m - ROVER[3]) / WALK_M_PER_MIN
    v = np.clip(minutes / 60, 0, 1)
    save_png("shelter_time.png", np.dstack([np.full((H, W), 60), np.full((H, W), 110), np.full((H, W), 220), 40 + 120 * v]))


def make_tables():
    with open(OUT / "weather.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sol", "local_hour", "temp_c", "pressure_pa", "dust_tau"])
        for h in range(24):
            temp = -70 + 62 * math.sin(math.pi * (h - 1) / 24) ** 2
            w.writerow([40, h, round(temp, 1), round(740 + 15 * math.sin(h / 24 * 2 * math.pi), 1), 0.5])
    with open(OUT / "radiation.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sol", "local_hour", "dose_rate_usv_h"])
        for h in range(24):
            w.writerow([40, h, 90 if h in (15, 16) else 27])  # fake solar storm at 15:00


def make_vectors():
    points = [ROVER] + [s[:4] for s in STOPS] + [ROVER]
    route = [[p[2], p[3]] for p in points]
    legs, walk = [], 0.0
    for a, b in zip(points, points[1:]):
        d = math.hypot(b[2] - a[2], b[3] - a[3])
        legs.append({"from": a[0], "to": b[0], "distance_m": round(d), "walk_min": round(d / WALK_M_PER_MIN)})
        walk += d / WALK_M_PER_MIN
    stop_min = STOP_MIN * len(STOPS)
    total = round(walk + stop_min)

    (OUT / "route.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"fake": True},
                      "geometry": {"type": "LineString", "coordinates": route}}],
    }, indent=2))

    feats = [{"type": "Feature",
              "properties": {"id": "rover", "name": "Rover", "kind": "rover", "why": "Start and safe haven.", "photo": None},
              "geometry": {"type": "Point", "coordinates": [ROVER[2], ROVER[3]]}}]
    feats += [{"type": "Feature",
               "properties": {"id": i, "name": n, "kind": "stop", "why": why, "photo": None},
               "geometry": {"type": "Point", "coordinates": [x, y]}} for i, n, x, y, why in STOPS]
    (OUT / "waypoints.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, indent=2))

    (OUT / "plan.json").write_text(json.dumps({
        "fake": True,
        "crew": 2,
        "legs": legs,
        "totals": {"walk_min": round(walk), "stop_min": stop_min, "total_min": total},
        "budgets": {"eva_max_min": 360, "radiation_limit_usv": 1000},
        "radiation_dose_usv": round(27 * total / 60),
    }, indent=2))


def make_layers_json():
    def layer(id_, title, file, source, default, opacity):
        return {"id": id_, "title": title, "file": file, "source": source, "default": default, "opacity": opacity}

    (OUT / "layers.json").write_text(json.dumps({
        "site": {"name": "Fake site (replace with the real one)",
                 "grid": {"width": W, "height": H, "cell_m": CELL_M}, "extent_m": [EXTENT_M, EXTENT_M]},
        "layers": [
            layer("relief", "Shaded relief", "relief.png", "FAKE (real: HiRISE terrain model, MRO)", True, 1.0),
            layer("slope", "Slope", "slope.png", "FAKE (real: derived from HiRISE terrain model)", False, 0.6),
            layer("thermal", "Thermal inertia", "thermal.png", "FAKE (real: THEMIS, Mars Odyssey)", False, 0.6),
            layer("minerals", "Minerals", "minerals.png", "FAKE (real: CRISM, MRO)", False, 0.8),
            layer("hazard", "Hazards", "hazard.png", "FAKE (real: slope, rocks and thermal inertia)", True, 0.7),
            layer("shelter_time", "Minutes back to rover", "shelter_time.png", "FAKE (real: routing model)", False, 0.7),
        ],
        "vectors": {"route": "route.geojson", "waypoints": "waypoints.geojson"},
        "tables": {"weather": "weather.csv", "radiation": "radiation.csv"},
        "plan": "plan.json",
    }, indent=2))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    save_tif("dem.tif", dem, "float32")
    save_tif("hazard.tif", hazard, "uint8")
    make_images()
    make_tables()
    make_vectors()
    make_layers_json()
    print(f"Wrote fake data to {OUT}")
    print(f"Slope: max {slope.max():.0f} deg; hazard cells: "
          f"{(hazard == 1).mean():.0%} yellow, {(hazard == 2).mean():.0%} red")
