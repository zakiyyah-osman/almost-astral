"""Check data/out/ against CONTRACT.md.

    python data/validate.py                  # errors fail; fake data only warns
    python data/validate.py --strict         # fake data fails too (run before submitting)
    python data/validate.py path/to/folder   # check another folder

Run it after you change anything in data/out/. It catches a wrong file name, a
wrong size or a missing field before it breaks somebody else's code.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

errors = []
fake = []


def err(message):
    errors.append(message)


def load_json(out, name):
    path = out / name
    if not path.is_file():
        err(f"{name}: file is missing")
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        err(f"{name}: not valid JSON ({e})")
        return None


def check_layers(out, index):
    """Check layers.json and every layer file. Returns (width, height, extent) or None."""
    grid = index.get("site", {}).get("grid", {})
    try:
        w, h, cell = grid["width"], grid["height"], grid["cell_m"]
    except KeyError as e:
        err(f"layers.json: site.grid is missing {e}")
        return None
    extent = index["site"].get("extent_m")
    if extent != [w * cell, h * cell]:
        err(f"layers.json: site.extent_m is {extent} but the grid gives {[w * cell, h * cell]}")

    if not index.get("layers"):
        err("layers.json: there are no layers")
    for layer in index.get("layers", []):
        lid = layer.get("id", "?")
        for key in ("id", "title", "file", "source"):
            if not layer.get(key):
                err(f"layers.json: layer '{lid}' has no '{key}'")
        if "FAKE" in str(layer.get("source", "")):
            fake.append(f"layer '{lid}' still uses fake data")
        path = out / layer.get("file", "")
        if not path.is_file():
            err(f"layers.json: layer '{lid}' points to {layer.get('file')}, which does not exist")
        elif path.suffix == ".png":
            size = Image.open(path).size
            if size != (w, h):
                err(f"{path.name}: image is {size[0]}x{size[1]} but the grid is {w}x{h}")
    # Real tables get a credit in sources_notes from their adapter; fake ones never do.
    notes = index.get("sources_notes", {})
    for table_file in index.get("tables", {}).values():
        if table_file not in notes:
            fake.append(f"{table_file} still uses fake data (no entry in layers.json sources_notes)")
    return w, h, extent


def check_raster(out, name, w, h, allowed=None):
    path = out / name
    if not path.is_file():
        err(f"{name}: file is missing")
        return
    with rasterio.open(path) as src:
        if (src.width, src.height) != (w, h):
            err(f"{name}: raster is {src.width}x{src.height} but the grid is {w}x{h}")
        if allowed is not None:
            values = set(np.unique(src.read(1)).tolist())
            if not values <= allowed:
                err(f"{name}: values {sorted(values - allowed)} are not allowed (use {sorted(allowed)})")


def check_crater_grids(out, header_file, w, h):
    """The compact crater grids (grid.json + height.i16, hazard.u8, slope.u8): sizes, values, < 10 MB."""
    header = load_json(out, header_file)
    if not header:
        return
    if (header.get("cols"), header.get("rows")) != (w, h):
        err(f"{header_file}: {header.get('cols')} x {header.get('rows')} cells, layers.json crater.grid says {w} x {h}")
        return
    for key, dtype in (("height", "<i2"), ("hazard", "u1"), ("slope", "u1")):
        spec = header.get(key) or {}
        path = out / spec.get("file", "")
        if not spec.get("file") or not path.is_file():
            err(f"{header_file}: the {key} grid file {spec.get('file')} does not exist")
            continue
        size = path.stat().st_size
        if size != w * h * np.dtype(dtype).itemsize:
            err(f"{spec['file']}: {size} bytes, expected {w * h * np.dtype(dtype).itemsize} for {w} x {h} {dtype}")
            continue
        if size > 10_000_000:
            err(f"{spec['file']}: {size / 1e6:.1f} MB, over the 10 MB limit")
        if key == "hazard":
            bad = set(np.unique(np.fromfile(path, dtype=dtype)).tolist()) - {0, 1, 2}
            if bad:
                err(f"{spec['file']}: values {sorted(bad)} are not hazard classes (0, 1, 2)")


def check_crater(out, index):
    """Optional whole-crater block (data/adapters/crater.py): its own grid, files and lat/lon bounds."""
    crater = index.get("crater")
    if not crater:
        return
    try:
        w, h, cell = crater["grid"]["width"], crater["grid"]["height"], crater["grid"]["cell_m"]
    except KeyError as e:
        err(f"layers.json: crater.grid is missing {e}")
        return
    if crater.get("extent_m") != [w * cell, h * cell]:
        err(f"layers.json: crater.extent_m is {crater.get('extent_m')} but the grid gives {[w * cell, h * cell]}")
    b = crater.get("bounds_latlon", {})
    if not all(k in b for k in ("south", "west", "north", "east")) or not (b["south"] < b["north"] and b["west"] < b["east"]):
        err("layers.json: crater.bounds_latlon needs south < north and west < east")
    for key in ("source", "grid_header"):
        if not crater.get(key):
            err(f"layers.json: crater has no '{key}'")
    check_crater_grids(out, crater.get("grid_header", "crater/grid.json"), w, h)
    for layer in crater.get("layers", []):
        lid = layer.get("id", "?")
        for key in ("id", "title", "file", "source"):
            if not layer.get(key):
                err(f"layers.json: crater layer '{lid}' has no '{key}'")
        path = out / layer.get("file", "")
        if not path.is_file():
            err(f"layers.json: crater layer '{lid}' points to {layer.get('file')}, which does not exist")
        elif Image.open(path).size != (w, h):
            err(f"{layer.get('file')}: image is {Image.open(path).size} but the crater grid is {w}x{h}")


def check_geojson(out, name, geometry_type, extent):
    data = load_json(out, name)
    if data is None:
        return
    features = data.get("features") if isinstance(data, dict) else None
    if not features:
        err(f"{name}: needs a FeatureCollection with at least one feature")
        return
    for i, feature in enumerate(features):
        geometry = feature.get("geometry", {})
        props = feature.get("properties", {})
        if props.get("fake"):
            fake.append(f"{name} still uses fake data")
        if geometry.get("type") != geometry_type:
            err(f"{name}: feature {i} should be a {geometry_type}")
            continue
        coords = geometry["coordinates"] if geometry_type == "LineString" else [geometry["coordinates"]]
        for x, y in coords:
            if extent and not (0 <= x <= extent[0] and 0 <= y <= extent[1]):
                err(f"{name}: feature {i} has a point ({x}, {y}) outside the site (0 to {extent})")
        if name == "waypoints.geojson":
            for key in ("id", "name", "kind"):
                if not props.get(key):
                    err(f"{name}: feature {i} has no '{key}'")
            if props.get("kind") not in ("rover", "stop"):
                err(f"{name}: feature {i} 'kind' must be 'rover' or 'stop'")


def check_csv(out, name, header):
    path = out / name
    if not path.is_file():
        err(f"{name}: file is missing")
        return
    with open(path, newline="") as f:
        first = next(csv.reader(f), None)
    if first != header:
        err(f"{name}: the header row should be {','.join(header)}")


def check_plan(out):
    plan = load_json(out, "plan.json")
    if plan is None:
        return
    if plan.get("fake"):
        fake.append("plan.json still uses fake data")
    for key in ("crew", "legs", "totals", "budgets", "radiation_dose_usv"):
        if key not in plan:
            err(f"plan.json: '{key}' is missing")
    for key in ("walk_min", "stop_min", "total_min"):
        if key not in plan.get("totals", {}):
            err(f"plan.json: totals.{key} is missing")
    for i, leg in enumerate(plan.get("legs", [])):
        for key in ("from", "to", "distance_m", "walk_min"):
            if key not in leg:
                err(f"plan.json: leg {i} has no '{key}'")


def check_big_files(limit_mb=50):
    """No file Git could commit (tracked, or untracked and not ignored) may be over limit_mb."""
    import subprocess
    root = Path(__file__).resolve().parents[1]
    try:
        names = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                               cwd=root, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    except (OSError, subprocess.CalledProcessError):
        return  # not a Git checkout: nothing to check
    for name in filter(None, names):
        path = root / name
        if path.is_file() and path.stat().st_size > limit_mb * 1_000_000:
            err(f"{name} is {path.stat().st_size / 1e6:.0f} MB: over {limit_mb} MB, too big for Git. "
                "Put raw downloads in data/raw/ (ignored) or make the file smaller.")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    out = Path(args[0]) if args else Path(__file__).resolve().parent / "out"

    check_big_files()
    index = load_json(out, "layers.json")
    grid = check_layers(out, index) if index else None
    if grid:
        w, h, extent = grid
        check_raster(out, "dem.tif", w, h)
        check_raster(out, "hazard.tif", w, h, allowed={0, 1, 2})
        check_crater(out, index)
    else:
        extent = None
    check_geojson(out, "route.geojson", "LineString", extent)
    check_geojson(out, "waypoints.geojson", "Point", extent)
    check_csv(out, "weather.csv", ["sol", "local_hour", "temp_c", "pressure_pa", "dust_tau"])
    check_csv(out, "radiation.csv", ["sol", "local_hour", "dose_rate_usv_h"])
    check_plan(out)

    for message in errors:
        print(f"ERROR   {message}")
    for message in fake:
        print(f"{'ERROR  ' if strict else 'WARNING'} {message}")
    if errors or (strict and fake):
        print(f"\nFailed: {len(errors) + (len(fake) if strict else 0)} problem(s) in {out}")
        return 1
    note = f" ({len(fake)} fake-data warning(s))" if fake else ""
    print(f"OK: {out} follows CONTRACT.md{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
