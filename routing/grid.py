"""The site grid: read it from layers.json, load dem.tif and hazard.tif, convert
between cells and metres, and compute terrain slope.

Contract constants (file names, hazard codes) live here. Grid size and cell size are
never hard-coded: they always come from layers.json (site.grid).
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio

from config import ConfigError

# ---- contract constants (CONTRACT.md) --------------------------------------
LAYERS_FILE = "layers.json"
DEM_FILE = "dem.tif"
HAZARD_FILE = "hazard.tif"
WAYPOINTS_FILE = "waypoints.geojson"
RADIATION_FILE = "radiation.csv"
ROUTE_FILE = "route.geojson"
SHELTER_FILE = "shelter_time.png"
PLAN_FILE = "plan.json"

HAZARD_GREEN, HAZARD_YELLOW, HAZARD_RED = 0, 1, 2


class GridError(ConfigError):
    """An input file does not match the grid or the contract."""


@dataclass(frozen=True)
class Grid:
    width: int       # columns
    height: int      # rows
    cell_m: float    # metres per cell

    @property
    def shape(self):
        """(rows, columns), the shape of every raster."""
        return (self.height, self.width)

    @property
    def extent_m(self):
        return (self.width * self.cell_m, self.height * self.cell_m)

    def cell_centre(self, row, col):
        """Centre of cell (row, col) as (x, y) in metres. Row 0 is the north edge."""
        return ((col + 0.5) * self.cell_m, (self.height - row - 0.5) * self.cell_m)

    def xy_to_cell(self, x, y):
        """The (row, col) of the cell containing the point (x, y), in metres.

        Raises GridError if the point lies outside the site.
        """
        ex, ey = self.extent_m
        if not (0 <= x <= ex and 0 <= y <= ey):
            raise GridError(f"point ({x}, {y}) m is outside the site ({ex} x {ey} m)")
        # Half-open cells measured from the south-west corner: the lower edge belongs
        # to the cell. The far north and east edges belong to the last cell.
        col = min(int(math.floor(x / self.cell_m)), self.width - 1)
        row_from_south = min(int(math.floor(y / self.cell_m)), self.height - 1)
        return self.height - 1 - row_from_south, col


def read_layers(folder):
    """The parsed layers.json in `folder`."""
    path = Path(folder) / LAYERS_FILE
    if not path.exists():
        raise GridError(f"{path} not found")
    return json.loads(path.read_text(encoding="utf-8"))


EXTENT_TOL_M = 1e-6


def _positive_int(label, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise GridError(f"layers.json site.grid.{label} must be a positive integer, got {v!r}")
    if isinstance(v, float) and not v.is_integer():
        raise GridError(f"layers.json site.grid.{label} must be a whole number, got {v!r}")
    if v <= 0:
        raise GridError(f"layers.json site.grid.{label} must be positive, got {v!r}")
    return int(v)


def grid_from_layers(layers):
    try:
        g = layers["site"]["grid"]
        width_v, height_v, cell_v = g["width"], g["height"], g["cell_m"]
    except (KeyError, TypeError) as e:
        raise GridError(f"layers.json has no usable site.grid: {e!r}") from None
    width = _positive_int("width", width_v)
    height = _positive_int("height", height_v)
    if isinstance(cell_v, bool) or not isinstance(cell_v, (int, float)) or not cell_v > 0:
        raise GridError(f"layers.json site.grid.cell_m must be a positive number, got {cell_v!r}")
    grid = Grid(width=width, height=height, cell_m=float(cell_v))
    extent = layers["site"].get("extent_m")
    if extent is not None:
        ok = (
            isinstance(extent, (list, tuple)) and len(extent) == 2
            and all(isinstance(e, (int, float)) and not isinstance(e, bool) for e in extent)
            and all(abs(e - want) <= EXTENT_TOL_M for e, want in zip(extent, grid.extent_m))
        )
        if not ok:
            raise GridError(
                f"layers.json site.extent_m {extent!r} does not equal width/height x cell_m "
                f"{list(grid.extent_m)}"
            )
    return grid


def read_grid(folder):
    """The Grid described by layers.json in `folder`."""
    return grid_from_layers(read_layers(folder))


GEOTRANSFORM_TOL = 1e-6


def _check_geotransform(path, t, grid):
    """Pixel size must equal cell_m on both axes and the raster must be north-up."""
    name = Path(path).name
    if abs(t.b) > GEOTRANSFORM_TOL or abs(t.d) > GEOTRANSFORM_TOL:
        raise GridError(f"{name} is rotated (geotransform {tuple(t)[:6]}); it must be north-up")
    if t.e > 0:
        raise GridError(f"{name} is south-up (positive y pixel size); row 0 must be the north edge")
    if abs(t.a - grid.cell_m) > GEOTRANSFORM_TOL or abs(-t.e - grid.cell_m) > GEOTRANSFORM_TOL:
        raise GridError(
            f"{name} has pixel size {t.a} x {abs(t.e)} m, layers.json says cell_m = {grid.cell_m}"
        )


def _check_rasters_agree(path):
    """dem.tif and hazard.tif must share one geotransform (origin, pixel size, orientation)."""
    folder = Path(path).parent
    dem, haz = folder / DEM_FILE, folder / HAZARD_FILE
    if not (dem.exists() and haz.exists()):
        return
    with rasterio.open(dem) as a, rasterio.open(haz) as b:
        ta, tb = tuple(a.transform)[:6], tuple(b.transform)[:6]
    if any(abs(x - y) > GEOTRANSFORM_TOL for x, y in zip(ta, tb)):
        raise GridError(
            f"{DEM_FILE} and {HAZARD_FILE} have different geotransforms: "
            f"{DEM_FILE} {ta}, {HAZARD_FILE} {tb}"
        )


def _read_band(path, grid):
    with rasterio.open(path) as src:
        if (src.height, src.width) != grid.shape:
            raise GridError(
                f"{Path(path).name} is {src.width} x {src.height} cells, "
                f"layers.json says {grid.width} x {grid.height}"
            )
        _check_geotransform(path, src.transform, grid)
        _check_rasters_agree(path)
        arr = src.read(1)
        nodata = src.nodata
    return arr, nodata


def load_dem(folder, grid):
    """Terrain height in metres as float64, shape (rows, cols). No-data cells are NaN."""
    arr, nodata = _read_band(Path(folder) / DEM_FILE, grid)
    dem = arr.astype(np.float64)
    if nodata is not None and not np.isnan(nodata):
        dem[arr == nodata] = np.nan
    dem[~np.isfinite(dem)] = np.nan
    return dem


def load_hazard(folder, grid):
    """Hazard codes as uint8, shape (rows, cols); every value must be 0, 1 or 2."""
    arr, _ = _read_band(Path(folder) / HAZARD_FILE, grid)
    bad = ~np.isin(arr, (HAZARD_GREEN, HAZARD_YELLOW, HAZARD_RED))
    if bad.any():
        values = sorted(set(np.unique(arr[bad]).tolist()))
        raise GridError(f"{HAZARD_FILE} has values outside 0-2: {values}")
    return arr.astype(np.uint8)


def slope_deg(dem, cell_m):
    """Steepest terrain slope at each cell, in degrees (central differences).

    Cells next to a NaN in the DEM come out NaN.
    """
    dz_dy, dz_dx = np.gradient(dem, cell_m)
    return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
