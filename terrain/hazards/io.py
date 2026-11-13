"""Reading layers.json and the rasters/vectors it lists.

Grid convention (shared with the whole team):
  * row 0 is the NORTH edge, column 0 is the WEST edge;
  * coordinates are [east, north] in metres, with (0, 0) at the SW corner;
  * cell (row, col) has its centre at
        east  = (col + 0.5) * cell_m
        north = height_m - (row + 0.5) * cell_m
  * Leaflet CRS.Simple bounds for every PNG: [[0, 0], [height_m, width_m]]
    (Leaflet uses [north, east] order).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:  # rasterio is optional; plain TIFF/PNG work without it
    import rasterio  # type: ignore
except ImportError:  # pragma: no cover
    rasterio = None
import tifffile
from PIL import Image


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

    def cell_centres(self):
        rows, cols = self.shape
        east = (np.arange(cols) + 0.5) * self.cell_m
        north = self.height_m - (np.arange(rows) + 0.5) * self.cell_m
        return np.meshgrid(east, north)

    @property
    def leaflet_bounds(self):
        return [[0, 0], [self.height_m, self.width_m]]


class Layers:
    """Thin wrapper around layers.json."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.root = self.path.parent
        self.meta = json.loads(self.path.read_text())
        s = self.meta["site"]
        self.grid = Grid(s["width_m"], s["height_m"], s["cell_m"])
        self.by_id = {l["id"]: l for l in self.meta["layers"]}

    def has(self, layer_id: str) -> bool:
        return layer_id in self.by_id and (self.root / self.by_id[layer_id]["file"]).exists()

    def file(self, layer_id: str) -> Path:
        return self.root / self.by_id[layer_id]["file"]

    def raster(self, layer_id: str, dtype=float) -> np.ndarray:
        arr = read_raster(self.file(layer_id)).astype(dtype)
        if arr.shape != self.grid.shape:
            raise ValueError(
                f"Layer '{layer_id}' is {arr.shape}, grid is {self.grid.shape}. "
                "All rasters must share one grid (layers.json rule) - ask Person 1 to re-crop."
            )
        nodata = self.by_id[layer_id].get("nodata")
        if nodata is not None and np.issubdtype(arr.dtype, np.floating):
            arr[arr == nodata] = np.nan
        return arr

    def vector(self, layer_id: str) -> dict:
        return json.loads(self.file(layer_id).read_text())


def read_raster(path: Path) -> np.ndarray:
    path = Path(path)
    if rasterio is not None and path.suffix.lower() in {".tif", ".tiff", ".img", ".jp2"}:
        with rasterio.open(path) as src:
            arr = src.read(1, masked=True)
            return np.ma.filled(arr.astype(float), np.nan) if np.ma.is_masked(arr) else np.asarray(arr)
    if path.suffix.lower() in {".tif", ".tiff"}:
        return tifffile.imread(path)
    if path.suffix.lower() == ".npy":
        return np.load(path)
    img = np.asarray(Image.open(path))
    return img if img.ndim == 2 else img[..., 0]


def write_tif(path: Path, arr: np.ndarray, description: dict | None = None) -> None:
    tifffile.imwrite(path, arr, description=json.dumps(description or {}), compression="zlib")
