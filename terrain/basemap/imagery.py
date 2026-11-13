"""Dataset day: put real map products on the shared site grid.

1) Define the site once (who: Person 2), from the real imagery's projection:

    python -m basemap.imagery define-site --layers data/layers.json \
        --center-xy 8143850 -278210 --size 1000 1000 --cell 1 \
        --clon 0 --lat-ts 0 --crs "Mars 2000 equirectangular (from the product label)"

   This writes width/height/cell, origin_source_xy (SW corner) and origin_latlon into
   layers.json -> site. Share map_config.json afterwards (python -m basemap.build).

2) Resample any georeferenced product onto the grid:

    python -m basemap.imagery resample ESP_xxx_RED.tif --layers data/layers.json \
        --out data/ortho.tif --id ortho --units DN --source "HiRISE ESP_xxx RED, PDS"
    python -m basemap.imagery resample DTEEC_xxx.tif --layers data/layers.json \
        --out data/dtm.tif --id dtm --units m --nodata -3.4028227e+38

Georeferencing is read from (in order): a world file next to the image
(.tfw/.pgw/.jgw/.wld), GeoTIFF ModelTransformation, or GeoTIFF PixelScale+Tiepoint.
The product must be in a projected CRS in metres, north-up or rotated (affine).
If the product is in a different projection from the site, reproject it first
(gdalwarp, or Person 1's converter with rasterio).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image
from scipy.ndimage import map_coordinates

MARS_R = 3396190.0
WORLD_EXT = (".tfw", ".pgw", ".jgw", ".wld", ".tifw", ".pngw", ".jpgw")


# ---- georeferencing ---------------------------------------------------------------
def read_affine(path: Path) -> np.ndarray:
    """Affine A (2x3) mapping pixel CENTRE (col, row) -> projected (x, y) metres."""
    path = Path(path)
    for cand in [path.with_suffix(ext) for ext in WORLD_EXT] + [Path(str(path) + "w")]:
        if cand.exists() and cand != path:
            a, d, b, e, c, f = [float(x) for x in cand.read_text().split()[:6]]
            return np.array([[a, b, c], [d, e, f]])  # world files use pixel centres
    if path.suffix.lower() in (".tif", ".tiff"):
        with tifffile.TiffFile(path) as tf:
            tags = tf.pages[0].tags
            if 34264 in tags:  # ModelTransformationTag (4x4, pixel corner)
                m = np.array(tags[34264].value, float).reshape(4, 4)
                A = np.array([[m[0, 0], m[0, 1], m[0, 3]], [m[1, 0], m[1, 1], m[1, 3]]])
                return _corner_to_centre(A, tags)
            if 33550 in tags and 33922 in tags:
                sx, sy = tags[33550].value[:2]
                i, j, _, x, y, _ = tags[33922].value[:6]
                A = np.array([[sx, 0, x - i * sx], [0, -sy, y + j * sy]])
                return _corner_to_centre(A, tags)
    raise ValueError(f"No georeferencing found for {path} (need a world file or GeoTIFF tags)")


def _corner_to_centre(A, tags):
    """GeoTIFF default is PixelIsArea: the transform addresses pixel corners."""
    raster_type = 1
    if 34735 in tags:  # GeoKeyDirectory: key 1025 = GTRasterTypeGeoKey
        k = tags[34735].value
        for n in range(k[3]):
            key, loc, cnt, val = k[4 + 4 * n: 8 + 4 * n]
            if key == 1025 and loc == 0:
                raster_type = val
    if raster_type == 2:  # PixelIsPoint: already centres
        return A
    B = A.copy()
    B[:, 2] = A @ np.array([0.5, 0.5, 1.0])
    return B


def load_image(path: Path) -> np.ndarray:
    path = Path(path)
    if path.suffix.lower() in (".tif", ".tiff"):
        arr = tifffile.imread(path)
    else:
        arr = np.asarray(Image.open(path))
    arr = np.asarray(arr, float)
    if arr.ndim == 3:  # bands-last colour -> luminance; bands-first (3, H, W) too
        arr = arr.mean(axis=2) if arr.shape[2] in (3, 4) else arr[0]
    return arr


# ---- resampling ---------------------------------------------------------------------
def resample_to_site(arr: np.ndarray, A: np.ndarray, site: dict, order=1, nodata=None) -> np.ndarray:
    """Sample `arr` (georeferenced by A) at every site cell centre. Outside = NaN."""
    W, H, cell = site["width_m"], site["height_m"], site["cell_m"]
    x0, y0 = site["origin_source_xy"]
    rows, cols = int(round(H / cell)), int(round(W / cell))
    e = (np.arange(cols) + 0.5) * cell
    n = H - (np.arange(rows) + 0.5) * cell
    E, N = np.meshgrid(e, n)
    X, Y = E + x0, N + y0
    M = np.vstack([A, [0, 0, 1]])
    inv = np.linalg.inv(M)
    c = inv[0, 0] * X + inv[0, 1] * Y + inv[0, 2]
    r = inv[1, 0] * X + inv[1, 1] * Y + inv[1, 2]
    src = arr.astype(float).copy()
    bad = ~np.isfinite(src)
    if nodata is not None:
        bad |= np.isclose(src, nodata) | (src <= -1e30)
    fill = np.nanmean(src[~bad]) if (~bad).any() else 0.0
    src[bad] = fill
    out = map_coordinates(src, [r, c], order=order, mode="constant", cval=np.nan)
    badmask = map_coordinates(bad.astype(float), [r, c], order=1, mode="constant", cval=1.0) > 0.01
    out[badmask] = np.nan
    return out.astype(np.float32)


def native_cell_m(A) -> float:
    return float(np.sqrt(abs(np.linalg.det(A[:, :2]))))


# ---- CLI ------------------------------------------------------------------------------
def cmd_resample(a):
    lj = Path(a.layers)
    meta = json.loads(lj.read_text())
    site = meta["site"]
    if not site.get("origin_source_xy"):
        raise SystemExit("site.origin_source_xy is not set - run `define-site` first.")
    A = read_affine(Path(a.image))
    arr = load_image(Path(a.image))
    out = resample_to_site(arr, A, site, order=1, nodata=a.nodata)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(a.out, out, compression="zlib")
    cover = float(np.isfinite(out).mean())
    nat = native_cell_m(A)
    print(f"{a.image}: native {nat:.2f} m/px -> site grid {site['cell_m']} m; covers {cover:.1%} of the site -> {a.out}")
    if nat > 1.5 * site["cell_m"]:
        print(f"  note: product is coarser than the grid ({nat:.1f} m vs {site['cell_m']} m) - it will look blocky, that's honest")
    if cover < 0.999:
        print("  note: part of the site has no data here - it will show as a coverage gap")
    if a.id:
        rel = Path(a.out).resolve().relative_to(lj.parent.resolve()).as_posix()
        layers = [l for l in meta["layers"] if l["id"] != a.id]
        layers.append({"id": a.id, "kind": "raster", "units": a.units, "file": rel,
                       "source": a.source or Path(a.image).name, "native_cell_m": round(nat, 3),
                       "coverage": round(cover, 4)})
        meta["layers"] = layers
        lj.write_text(json.dumps(meta, indent=2))
        print(f"  layers.json updated: layer '{a.id}'")


def cmd_define_site(a):
    lj = Path(a.layers)
    meta = json.loads(lj.read_text()) if lj.exists() else {"site": {}, "layers": []}
    W, H = a.size
    cx, cy = a.center_xy
    x0, y0 = cx - W / 2, cy - H / 2
    lat0 = np.degrees(y0 / MARS_R)
    lon0 = a.clon + np.degrees(x0 / (MARS_R * np.cos(np.radians(a.lat_ts))))
    site = meta.get("site", {})
    site.update({"width_m": W, "height_m": H, "cell_m": a.cell, "crs": "local_meters",
                 "source_crs": a.crs, "origin_source_xy": [round(x0, 3), round(y0, 3)],
                 "origin_latlon": [round(float(lat0), 6), round(float(lon0), 6)], "simulated": False})
    if a.name:
        site["name"] = a.name
    meta["site"] = site
    lj.parent.mkdir(parents=True, exist_ok=True)
    lj.write_text(json.dumps(meta, indent=2))
    print(json.dumps(site, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resample", help="put a georeferenced product on the site grid")
    r.add_argument("image")
    r.add_argument("--layers", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--id", help="register as this layer id in layers.json (e.g. ortho, dtm)")
    r.add_argument("--units", default="DN")
    r.add_argument("--source")
    r.add_argument("--nodata", type=float)
    r.set_defaults(fn=cmd_resample)
    d = sub.add_parser("define-site", help="set the site grid, origin and projection in layers.json")
    d.add_argument("--layers", required=True)
    d.add_argument("--center-xy", type=float, nargs=2, required=True, help="site centre in source projection metres")
    d.add_argument("--size", type=float, nargs=2, default=[1000, 1000], metavar=("WIDTH_M", "HEIGHT_M"))
    d.add_argument("--cell", type=float, default=1.0)
    d.add_argument("--clon", type=float, default=0.0, help="projection centre longitude (deg)")
    d.add_argument("--lat-ts", type=float, default=0.0, help="projection latitude of true scale (deg)")
    d.add_argument("--crs", default="Mars 2000 equirectangular")
    d.add_argument("--name")
    d.set_defaults(fn=cmd_define_site)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
