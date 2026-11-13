"""Shared helpers for turning real downloads into the files in data/out/.

Every adapter uses these, so all layers land on exactly the same grid
(see CONTRACT.md): width x height cells of cell_m metres, row 0 at the north
edge, centred on the site centre in data/site.json.

How the alignment works: each raw file is reprojected from its own map
projection into a flat "equirectangular" projection centred on the site, then
cut to the site square. At 2 km across, the distortion of that projection is
far below one cell.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

DATA = Path(__file__).resolve().parent
OUT = DATA / "out"
RAW = DATA / "raw"


# --- settings ---------------------------------------------------------------

def load_site():
    return json.loads((DATA / "site.json").read_text(encoding="utf-8"))


def raw_file(rel):
    """Return the full path of a raw file named in site.json, or None if unset."""
    if not rel:
        return None
    path = DATA / rel
    if not path.is_file():
        raise FileNotFoundError(f"{rel} is set in data/site.json but the file is not there")
    return path


def grid_size(site):
    g = site["grid"]
    return g["width"], g["height"], float(g["cell_m"])


def site_proj4(site):
    lat, lon, r = site["center_lat"], site["center_lon_east"], site["mars_radius_m"]
    return (f"+proj=eqc +lat_ts={lat} +lat_0={lat} +lon_0={lon} "
            f"+x_0=0 +y_0=0 +R={r} +units=m +no_defs +type=crs")


# --- reprojecting a raster onto the site grid -------------------------------

def warp_to_grid(path, site, band=1, resampling="bilinear"):
    """Read one band of a raster file and return it on the site grid.

    Returns (array, info). The array is float32, shape (height, width), with
    NaN where the file has no data. Scale and offset from the file are applied.
    """
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    w, h, cell = grid_size(site)
    dst = np.full((h, w), np.nan, np.float32)
    dst_transform = from_origin(-w * cell / 2, h * cell / 2, cell, cell)

    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError(f"{Path(path).name} has no map projection, so it cannot be "
                             "aligned. Use a map-projected product (see data/SOURCES.md).")
        reproject(
            source=rasterio.band(src, band), destination=dst,
            src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
            dst_transform=dst_transform, dst_crs=CRS.from_proj4(site_proj4(site)),
            dst_nodata=np.nan, resampling=Resampling[resampling],
        )
        scale, offset = src.scales[band - 1], src.offsets[band - 1]
        native_m = abs(src.res[0]) if src.crs.is_projected else None

    dst[np.abs(dst) > 1e30] = np.nan  # PDS "missing" markers such as -3.4e38
    if scale not in (None, 1.0) or offset not in (None, 0.0):
        dst = dst * (scale or 1.0) + (offset or 0.0)
    coverage = float(np.isfinite(dst).mean())
    return dst, {"coverage": coverage, "native_resolution_m": native_m}


def require_full_coverage(arr, name, max_gap=0.02):
    """Fill tiny gaps by averaging neighbours; stop if the site is not covered."""
    gap = float(np.isnan(arr).mean())
    if gap > max_gap:
        raise ValueError(f"{name} covers only {1 - gap:.0%} of the site. Move the site "
                         "centre in data/site.json or use a file that covers it.")
    arr = arr.copy()
    while np.isnan(arr).any():
        padded = np.pad(arr, 1, mode="edge")
        stack = np.stack([padded[1:-1, :-2], padded[1:-1, 2:], padded[:-2, 1:-1], padded[2:, 1:-1]])
        with np.errstate(invalid="ignore"):
            fill = np.nanmean(stack, axis=0)
        arr = np.where(np.isnan(arr), fill, arr)
    return arr


# --- writing files in the contract format ------------------------------------

def save_tif(name, arr, dtype, site):
    """Write a GeoTIFF on the local grid, exactly like make_fake.py does."""
    import rasterio
    from rasterio.transform import from_origin

    w, h, cell = grid_size(site)
    with rasterio.open(
        OUT / name, "w", driver="GTiff", height=h, width=w, count=1, dtype=dtype,
        transform=from_origin(0, h * cell, cell, cell),
    ) as dst:
        dst.write(arr.astype(dtype), 1)
        dst.update_tags(site_proj4=site_proj4(site), units_note="local site metres, see CONTRACT.md")


def save_png(name, rgba):
    Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA").save(OUT / name)


def stretch(arr, low_pct=1, high_pct=99):
    """Scale to 0..1 between two percentiles, ignoring NaN."""
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return np.zeros_like(arr)
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    return np.clip((arr - lo) / ((hi - lo) or 1.0), 0, 1)


def colour_ramp(v, stops, alpha, nan_mask):
    """Map 0..1 values to colours through a list of RGB stops. NaN becomes transparent."""
    stops = np.asarray(stops, float)
    pos = np.linspace(0, 1, len(stops))
    v = np.nan_to_num(v, nan=0.0)
    rgb = np.stack([np.interp(v, pos, stops[:, i]) for i in range(3)], axis=-1)
    a = np.where(nan_mask, 0, alpha)[..., None]
    return np.concatenate([rgb, a], axis=-1)


# --- layers.json ------------------------------------------------------------

def update_layers_json(layer=None, insert_after=None, table=None, extra=None):
    """Update data/out/layers.json in place without disturbing other entries.

    layer: a layer dict; replaces the layer with the same id, or is inserted
           after `insert_after` (or at the end).
    table: (name, file) to add under "tables".
    extra: dict merged into the "sources_notes" field (free-text credits).
    """
    path = OUT / "layers.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    if layer:
        layers = index.setdefault("layers", [])
        ids = [l["id"] for l in layers]
        if layer["id"] in ids:
            old = layers[ids.index(layer["id"])]
            layers[ids.index(layer["id"])] = {**old, **layer}
        elif insert_after in ids:
            layers.insert(ids.index(insert_after) + 1, layer)
        else:
            layers.append(layer)
    if table:
        index.setdefault("tables", {})[table[0]] = table[1]
    if extra:
        index.setdefault("sources_notes", {}).update(extra)
    path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def set_site_name(site):
    path = OUT / "layers.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    index["site"]["name"] = site["name"]
    index["site"]["center_lat"] = site["center_lat"]
    index["site"]["center_lon_east"] = site["center_lon_east"]
    path.write_text(json.dumps(index, indent=2), encoding="utf-8")
