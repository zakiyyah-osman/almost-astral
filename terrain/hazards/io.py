"""Reading the team's layers.json and the files next to it.

Team format (agreed contract):
    "site": {"grid": {"width": cols, "height": rows, "cell_m": 5.0},
             "extent_m": [width_m, height_m],
             "center_lat": 18.46, "center_lon_east": 77.4, ...}
    "layers":  display layers (PNG files) - relief, hirise, slope, thermal, minerals, hazard ...
    "vectors": {"route": "route.geojson", "waypoints": "waypoints.geojson", ...}
Data rasters live next to layers.json: dem.tif (heights, m), thermal_inertia.tif (NaN = no data).

Grid convention (shared with the whole team):
  * row 0 is the NORTH edge, column 0 is the WEST edge;
  * coordinates are [east, north] in metres, with (0, 0) at the SW corner;
  * cell (row, col) has its centre at
        east  = (col + 0.5) * cell_m
        north = height_m - (row + 0.5) * cell_m
  * Leaflet CRS.Simple bounds for every PNG: [[0, 0], [height_m, width_m]]
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:  # rasterio is optional; plain TIFF/PNG work without it
    import rasterio  # type: ignore
except ImportError:  # pragma: no cover
    rasterio = None
import tifffile
from PIL import Image

MARS_R = 3396190.0

# Where each data raster is looked for, in order (relative to layers.json).
DATA_FILES = {
    "dtm": ["dem.tif", "dtm.tif"],
    "thermal_inertia": ["thermal_inertia.tif", "ti.tif"],
}


@dataclass
class Grid:
    width_m: float
    height_m: float
    cell_m: float

    @property
    def shape(self) -> tuple[int, int]:
        return int(round(self.height_m / self.cell_m)), int(round(self.width_m / self.cell_m))

    def to_rowcol(self, east, north):
        """[east, north] metres -> fractional (row, col)."""
        east, north = np.asarray(east, float), np.asarray(north, float)
        return (self.height_m - north) / self.cell_m - 0.5, east / self.cell_m - 0.5

    @property
    def leaflet_bounds(self):
        return [[0, 0], [self.height_m, self.width_m]]


def site_grid(site: dict) -> Grid:
    """Grid from the team format (grid + extent_m)."""
    g = site["grid"]
    cell = float(g["cell_m"])
    if "extent_m" in site:
        w, h = (float(v) for v in site["extent_m"])
    else:
        w, h = g["width"] * cell, g["height"] * cell
    if (round(w / cell), round(h / cell)) != (g["width"], g["height"]):
        raise ValueError(f"layers.json disagrees with itself: extent_m {w}x{h} m but grid "
                         f"{g['width']}x{g['height']} cells of {cell} m")
    return Grid(w, h, cell)


def origin_latlon(site: dict, grid: Grid) -> list[float]:
    """SW-corner lat/lon from the site centre (local spherical approximation)."""
    if "origin_latlon" in site:
        return list(site["origin_latlon"])
    lat_c, lon_c = site["center_lat"], site["center_lon_east"]
    lat0 = lat_c - math.degrees(grid.height_m / 2 / MARS_R)
    lon0 = lon_c - math.degrees(grid.width_m / 2 / (MARS_R * math.cos(math.radians(lat_c))))
    return [round(lat0, 7), round(lon0, 7)]


class Layers:
    """Thin wrapper around the team's layers.json."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.root = self.path.parent
        self.meta = json.loads(self.path.read_text())
        self.site = self.meta["site"]
        self.grid = site_grid(self.site)
        self.origin_latlon = origin_latlon(self.site, self.grid)
        self.display = {l["id"]: l for l in self.meta.get("layers", [])}
        self.vectors_map = dict(self.meta.get("vectors", {}))
        self.data_map = dict(self.meta.get("data", {}))  # optional override: {"dtm": "x.tif"}

    # ---- data rasters --------------------------------------------------------
    def data_file(self, kind: str) -> Path | None:
        names = ([self.data_map[kind]] if kind in self.data_map else []) + DATA_FILES.get(kind, [])
        for n in names:
            p = self.root / n
            if p.exists():
                return p
        return None

    def has(self, kind: str) -> bool:
        return self.data_file(kind) is not None

    def raster(self, kind: str) -> np.ndarray:
        p = self.data_file(kind)
        if p is None:
            raise FileNotFoundError(f"No file for '{kind}' next to {self.path} (looked for {DATA_FILES.get(kind)})")
        arr = read_raster(p).astype(float)
        if arr.shape != self.grid.shape:
            raise ValueError(
                f"{p.name} is {arr.shape[1]}x{arr.shape[0]} cells, grid is {self.grid.shape[1]}x{self.grid.shape[0]}. "
                "All rasters must share one grid - ask the data person to re-crop."
            )
        arr[arr < -1e30] = np.nan  # HiRISE/ISIS nodata (-3.4e38)
        return arr

    # ---- vectors -------------------------------------------------------------
    def has_vector(self, name: str) -> bool:
        return name in self.vectors_map and (self.root / self.vectors_map[name]).exists()

    def vector(self, name: str) -> dict:
        return json.loads((self.root / self.vectors_map[name]).read_text())

    def source_of(self, kind: str) -> str:
        p = self.data_file(kind)
        notes = self.meta.get("sources_notes", {})
        return notes.get(p.name, p.name) if p else "missing"

    @property
    def simulated(self) -> bool:
        text = json.dumps([self.display, self.site, self.meta.get("sources_notes", {})]).upper()
        return "FAKE" in text or "SIMULATED" in text


def read_raster(path: Path) -> np.ndarray:
    path = Path(path)
    if rasterio is not None and path.suffix.lower() in {".tif", ".tiff", ".img", ".jp2"}:
        with rasterio.open(path) as src:
            arr = src.read(1, masked=True)
            return np.ma.filled(arr.astype(float), np.nan) if np.ma.is_masked(arr) else np.asarray(arr)
    if path.suffix.lower() in {".tif", ".tiff"}:
        a = tifffile.imread(path)
        return a if a.ndim == 2 else a[..., 0] if a.shape[-1] <= 4 else a[0]
    if path.suffix.lower() == ".npy":
        return np.load(path)
    img = np.asarray(Image.open(path).convert("L"))
    return img


def write_tif(path: Path, arr: np.ndarray, description: dict | None = None) -> None:
    tifffile.imwrite(path, arr, description=json.dumps(description or {}), compression="zlib")
