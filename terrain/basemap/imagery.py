"""Dataset day: put real map products on the shared site grid.

1) Pin the site grid to the real imagery's projection (who: Person 2). Keeps the team's
   grid/extent_m/center; adds source_crs + origin_source_xy so products can be placed:

    python -m basemap.imagery define-site --layers data/layers.json \
        --center-lat 18.46 --center-lon 77.4 --clon 0 --lat-ts 0 \
        --crs "Mars equirectangular, lat_ts 0, lon_0 0 (from the product label)"

   (--size / --cell are optional and only needed to change the grid.)
   Share map_config.json afterwards (python -m basemap.build).

2) Resample any georeferenced product onto the grid:

    # data raster (written next to layers.json, noted in sources_notes)
    python -m basemap.imagery resample JEZ_hirise_..._DTM_...tif --layers data/layers.json \
        --out data/dem.tif --nodata -3.4028227e+38 --source "HiRISE DTM, USGS Mars 2020 TRN"
    # display image (PNG, registered as a layer in layers.json)
    python -m basemap.imagery resample PSP_003798_1985_..._25cm_...tif --layers data/layers.json \
        --out data/hirise.png --id hirise --title "HiRISE image" --source "HiRISE (MRO) ..."

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
def _site(meta):
    from hazards.io import site_grid
    g = site_grid(meta["site"])
    return {"width_m": g.width_m, "height_m": g.height_m, "cell_m": g.cell_m,
            "origin_source_xy": meta["site"].get("origin_source_xy")}


def cmd_resample(a):
    lj = Path(a.layers)
    meta = json.loads(lj.read_text())
    site = _site(meta)
    if not site["origin_source_xy"]:
        raise SystemExit("site.origin_source_xy is not set - run `define-site` first.")
    A = read_affine(Path(a.image))
    arr = load_image(Path(a.image))
    nat = native_cell_m(A)
    # average down first when the product is much finer than the grid (e.g. 25 cm HiRISE -> 5 m)
    f = int(site["cell_m"] // nat) if nat < site["cell_m"] / 1.5 else 1
    if f > 1:
        h, w = (arr.shape[0] // f) * f, (arr.shape[1] // f) * f
        arr = np.nanmean(arr[:h, :w].reshape(h // f, f, w // f, f), axis=(1, 3))
        A = A.copy()
        A[:, 2] = A @ np.array([(f - 1) / 2, (f - 1) / 2, 1.0])
        A[:, :2] *= f
    out = resample_to_site(arr, A, site, order=1, nodata=a.nodata)
    outp = Path(a.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    if outp.suffix.lower() == ".png":
        ok = np.isfinite(out)
        lo, hi = np.percentile(out[ok], [0.5, 99.5]) if ok.any() else (0, 1)
        g8 = (np.clip((np.nan_to_num(out) - lo) / max(hi - lo, 1e-9), 0, 1) * 255).astype(np.uint8)
        Image.fromarray(np.dstack([g8, g8, g8, (ok * 255).astype(np.uint8)]), "RGBA").save(outp, optimize=True)
    else:
        tifffile.imwrite(outp, out, compression="zlib")
    cover = float(np.isfinite(out).mean())
    print(f"{a.image}: native {nat:.2f} m/px -> grid {site['cell_m']} m; covers {cover:.1%} of the site -> {outp}")
    if nat > 1.5 * site["cell_m"]:
        print(f"  note: product is coarser than the grid ({nat:.1f} m vs {site['cell_m']} m) - soft edges are expected")
    if cover < 0.999:
        print("  note: part of the site has no data here - it will show as a coverage gap")
    rel = outp.resolve().relative_to(lj.parent.resolve()).as_posix() if outp.resolve().is_relative_to(lj.parent.resolve()) else str(outp)
    if a.source:
        meta.setdefault("sources_notes", {})[rel] = a.source
    if a.id:
        entry = {"id": a.id, "title": a.title or a.id, "file": rel, "source": a.source or Path(a.image).name,
                 "default": False, "opacity": 1.0, "native_resolution_m": round(nat, 3)}
        old = next((l for l in meta["layers"] if l["id"] == a.id), None)
        if old:
            entry = {**old, **{k: v for k, v in entry.items() if k in ("file", "source", "native_resolution_m")}}
            meta["layers"][meta["layers"].index(old)] = entry
        else:
            meta["layers"].append(entry)
    if a.id or a.source:
        lj.write_text(json.dumps(meta, indent=2))
        print("  layers.json updated")


def cmd_define_site(a):
    lj = Path(a.layers)
    meta = json.loads(lj.read_text()) if lj.exists() else {"site": {}, "layers": []}
    site = meta.setdefault("site", {})
    if a.size or a.cell or "grid" not in site:
        cell = a.cell or site.get("grid", {}).get("cell_m", 5.0)
        W, H = a.size or site.get("extent_m", [2000.0, 2000.0])
        site["grid"] = {"width": int(round(W / cell)), "height": int(round(H / cell)), "cell_m": cell}
        site["extent_m"] = [float(W), float(H)]
    W, H = site["extent_m"]
    lat_c = a.center_lat if a.center_lat is not None else site["center_lat"]
    lon_c = a.center_lon if a.center_lon is not None else site["center_lon_east"]
    site["center_lat"], site["center_lon_east"] = lat_c, lon_c
    k = np.cos(np.radians(a.lat_ts))
    xc = MARS_R * np.radians(lon_c - a.clon) * k
    yc = MARS_R * np.radians(lat_c)
    site["source_crs"] = a.crs
    site["origin_source_xy"] = [round(float(xc - W / 2), 3), round(float(yc - H / 2), 3)]
    if a.name:
        site["name"] = a.name
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
    r.add_argument("--id", help="register the output as a display layer with this id (for PNG outputs)")
    r.add_argument("--title")
    r.add_argument("--source", help="where it came from; written to layers.json")
    r.add_argument("--nodata", type=float)
    r.set_defaults(fn=cmd_resample)
    d = sub.add_parser("define-site", help="set the site grid, origin and projection in layers.json")
    d.add_argument("--layers", required=True)
    d.add_argument("--center-lat", type=float, help="default: site.center_lat")
    d.add_argument("--center-lon", type=float, help="east-positive; default: site.center_lon_east")
    d.add_argument("--size", type=float, nargs=2, metavar=("WIDTH_M", "HEIGHT_M"), help="only to change the grid")
    d.add_argument("--cell", type=float, help="only to change the grid")
    d.add_argument("--clon", type=float, default=0.0, help="projection centre longitude (deg)")
    d.add_argument("--lat-ts", type=float, default=0.0, help="projection latitude of true scale (deg)")
    d.add_argument("--crs", default="Mars equirectangular, lat_ts 0, lon_0 0, R 3396190 m")
    d.add_argument("--name")
    d.set_defaults(fn=cmd_define_site)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
