import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import grid as g
from grid import Grid, GridError


def test_grid_comes_from_layers_json(wide_site):
    grid = g.read_grid(wide_site.folder)
    assert (grid.width, grid.height, grid.cell_m) == (120, 80, 10.0)
    assert grid.shape == (80, 120)
    assert grid.extent_m == (1200.0, 800.0)
    assert g.load_dem(wide_site.folder, grid).shape == (80, 120)
    assert g.load_hazard(wide_site.folder, grid).shape == (80, 120)


def test_cell_centre_matches_contract():
    grid = Grid(width=400, height=400, cell_m=5.0)
    assert grid.cell_centre(0, 0) == (2.5, 1997.5)
    assert grid.cell_centre(399, 399) == (1997.5, 2.5)


def test_xy_cell_round_trip():
    grid = Grid(width=120, height=80, cell_m=10.0)
    for row, col in [(0, 0), (0, 119), (79, 0), (79, 119), (37, 64)]:
        x, y = grid.cell_centre(row, col)
        assert grid.xy_to_cell(x, y) == (row, col)
    # The far edges belong to the last cell, and points outside fail.
    assert grid.xy_to_cell(1200.0, 0.0) == (79, 119)
    with pytest.raises(GridError):
        grid.xy_to_cell(-1.0, 10.0)
    with pytest.raises(GridError):
        grid.xy_to_cell(10.0, 800.1)


def _write_tif(path, arr, dtype):
    with rasterio.open(
        path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
        dtype=dtype, transform=from_origin(0, arr.shape[0], 1, 1),
    ) as dst:
        dst.write(arr.astype(dtype), 1)


def test_shape_mismatch_fails(flat_site):
    grid = g.read_grid(flat_site.folder)
    _write_tif(flat_site.folder / "hazard.tif", np.zeros((10, 20)), "uint8")
    with pytest.raises(GridError, match="hazard.tif"):
        g.load_hazard(flat_site.folder, grid)
    _write_tif(flat_site.folder / "dem.tif", np.zeros((20, 10)), "float32")
    with pytest.raises(GridError, match="dem.tif"):
        g.load_dem(flat_site.folder, grid)


def test_bad_hazard_value_fails(flat_site):
    grid = g.read_grid(flat_site.folder)
    bad = np.zeros((20, 20))
    bad[3, 4] = 3
    _write_tif(flat_site.folder / "hazard.tif", bad, "uint8")
    with pytest.raises(GridError, match="outside 0-2"):
        g.load_hazard(flat_site.folder, grid)


def test_slope_of_10pct_plane_is_5_71_deg(tilted_site):
    grid = g.read_grid(tilted_site.folder)
    dem = g.load_dem(tilted_site.folder, grid)
    slope = g.slope_deg(dem, grid.cell_m)
    assert np.allclose(slope, 5.71, atol=0.01)


def test_flat_slope_is_zero_and_nodata_is_nan(flat_site):
    grid = g.read_grid(flat_site.folder)
    dem = g.load_dem(flat_site.folder, grid)
    assert np.all(g.slope_deg(dem, grid.cell_m) == 0)
    dem[5, 5] = np.nan
    slope = g.slope_deg(dem, grid.cell_m)
    # Central differences: the four neighbours of a no-data cell are NaN. The cell
    # itself is found from the DEM (cost.py blocks every NaN DEM cell directly).
    assert np.isnan(slope[4, 5]) and np.isnan(slope[6, 5])
    assert np.isnan(slope[5, 4]) and np.isnan(slope[5, 6])
