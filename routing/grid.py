"""The site grid: read it from layers.json, load dem.tif and hazard.tif, convert
between cells and metres, and compute terrain slope.

Contract constants (file names, hazard codes) live here. Grid size and cell size are
never hard-coded: they always come from layers.json (site.grid).
"""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio

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


class GridError(ValueError):
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
        col = min(int(x // self.cell_m), self.width - 1)
        row = min(int((ey - y) // self.cell_m), self.height - 1)
        return row, col


def read_layers(folder):
    """The parsed layers.json in `folder`."""
    path = Path(folder) / LAYERS_FILE
    if not path.exists():
        raise GridError(f"{path} not found")
    return json.loads(path.read_text(encoding="utf-8"))


def grid_from_layers(layers):
    try:
        g = layers["site"]["grid"]
        return Grid(width=int(g["width"]), height=int(g["height"]), cell_m=float(g["cell_m"]))
    except (KeyError, TypeError, ValueError) as e:
        raise GridError(f"layers.json has no usable site.grid: {e}") from None


def read_grid(folder):
    """The Grid described by layers.json in `folder`."""
    return grid_from_layers(read_layers(folder))


def _read_band(path, grid):
    with rasterio.open(path) as src:
        if (src.height, src.width) != grid.shape:
            raise GridError(
                f"{Path(path).name} is {src.width} x {src.height} cells, "
                f"layers.json says {grid.width} x {grid.height}"
            )
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
