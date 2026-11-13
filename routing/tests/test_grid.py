import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin

import grid as g
from config import ConfigError
from conftest import write_site
from grid import Grid, GridError


def _write_tif(path, arr, dtype, transform, nodata=None):
    with rasterio.open(
        path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
        dtype=dtype, transform=transform, nodata=nodata,
    ) as dst:
        dst.write(arr.astype(dtype), 1)


def _layers(width=20, height=20, cell_m=5.0, extent="auto"):
    site = {"name": "t", "grid": {"width": width, "height": height, "cell_m": cell_m}}
    if extent == "auto":
        extent = [width * cell_m, height * cell_m]
    if extent is not None:
        site["extent_m"] = extent
    return {"site": site}


# ---- layers.json -------------------------------------------------------------
def test_grid_comes_from_layers_json(wide_site):
    grid = g.read_grid(wide_site.folder)
    assert (grid.width, grid.height, grid.cell_m) == (120, 80, 10.0)
    assert grid.shape == (80, 120)
    assert grid.extent_m == (1200.0, 800.0)
    assert g.load_dem(wide_site.folder, grid).shape == (80, 120)
    assert g.load_hazard(wide_site.folder, grid).shape == (80, 120)


def test_grid_without_extent_is_accepted():
    assert g.grid_from_layers(_layers(extent=None)) == Grid(20, 20, 5.0)


@pytest.mark.parametrize("width", [400.7, 0, -5, "400", True, None])
def test_bad_width_rejected(width):
    with pytest.raises(ConfigError, match="width"):
        g.grid_from_layers(_layers(width=width, extent=None))


@pytest.mark.parametrize("height", [80.5, 0, -1, "80", False])
def test_bad_height_rejected(height):
    with pytest.raises(ConfigError, match="height"):
        g.grid_from_layers(_layers(height=height, extent=None))


@pytest.mark.parametrize("cell_m", [0, -5.0, "5", True, None])
def test_bad_cell_m_rejected(cell_m):
    with pytest.raises(ConfigError, match="cell_m"):
        g.grid_from_layers(_layers(cell_m=cell_m, extent=None))


def test_missing_grid_rejected():
    with pytest.raises(ConfigError, match="site.grid"):
        g.grid_from_layers({"site": {"name": "t"}})


def test_whole_number_float_width_accepted():
    assert g.grid_from_layers(_layers(width=20.0, extent=None)).width == 20


@pytest.mark.parametrize("extent", [[100.0, 101.0], [101.0, 100.0], [100.0], "x", [100.0, "100"]])
def test_extent_must_match_grid(extent):
    with pytest.raises(ConfigError, match="extent_m"):
        g.grid_from_layers(_layers(extent=extent))


def test_extent_within_tolerance_accepted():
    g.grid_from_layers(_layers(extent=[100.0 + 1e-7, 100.0 - 1e-7]))
    with pytest.raises(ConfigError):
        g.grid_from_layers(_layers(extent=[100.0 + 1e-5, 100.0]))


# ---- cell <-> metre ----------------------------------------------------------
def test_cell_centre_matches_contract():
    grid = Grid(width=400, height=400, cell_m=5.0)
    assert grid.cell_centre(0, 0) == (2.5, 1997.5)
    assert grid.cell_centre(399, 399) == (1997.5, 2.5)


def test_xy_cell_round_trip():
    grid = Grid(width=120, height=80, cell_m=10.0)
    for row, col in [(0, 0), (0, 119), (79, 0), (79, 119), (37, 64)]:
        x, y = grid.cell_centre(row, col)
        assert grid.xy_to_cell(x, y) == (row, col)
    with pytest.raises(GridError):
        grid.xy_to_cell(-1.0, 10.0)
    with pytest.raises(GridError):
        grid.xy_to_cell(10.0, 800.1)


def test_boundary_snapping_is_half_open_from_south_west():
    grid = Grid(width=20, height=20, cell_m=5.0)
    # x: lower edge belongs to the cell.
    assert grid.xy_to_cell(52.5, 52.5)[1] == 10
    assert grid.xy_to_cell(5.0, 52.5)[1] == 1
    assert grid.xy_to_cell(4.999, 52.5)[1] == 0
    assert grid.xy_to_cell(0.0, 52.5)[1] == 0
    # y: also measured from the south edge, lower edge belongs to the cell.
    assert grid.xy_to_cell(52.5, 5.0)[0] == 18      # y = 5 -> second row from the south
    assert grid.xy_to_cell(52.5, 4.999)[0] == 19
    assert grid.xy_to_cell(52.5, 0.0)[0] == 19      # south edge
    assert grid.xy_to_cell(52.5, 95.0)[0] == 0      # y = 95 -> top row (cell 19 from the south)
    assert grid.xy_to_cell(52.5, 94.999)[0] == 1
    # The far north and east edges belong to the last cell.
    assert grid.xy_to_cell(100.0, 100.0) == (0, 19)
    assert grid.xy_to_cell(0.0, 0.0) == (19, 0)


# ---- rasters -----------------------------------------------------------------
def test_shape_mismatch_fails(flat_site):
    grid = g.read_grid(flat_site.folder)
    _write_tif(flat_site.folder / "hazard.tif", np.zeros((10, 20)), "uint8", from_origin(0, 50, 5, 5))
    with pytest.raises(GridError, match="hazard.tif"):
        g.load_hazard(flat_site.folder, grid)
    _write_tif(flat_site.folder / "dem.tif", np.zeros((20, 10)), "float32", from_origin(0, 100, 5, 5))
    with pytest.raises(GridError, match="dem.tif"):
        g.load_dem(flat_site.folder, grid)


def test_bad_hazard_value_fails(flat_site):
    grid = g.read_grid(flat_site.folder)
    bad = np.zeros((20, 20))
    bad[3, 4] = 3
    _write_tif(flat_site.folder / "hazard.tif", bad, "uint8", from_origin(0, 100, 5, 5))
    with pytest.raises(GridError, match="outside 0-2"):
        g.load_hazard(flat_site.folder, grid)


def test_wrong_pixel_size_fails(flat_site):
    grid = g.read_grid(flat_site.folder)
    _write_tif(flat_site.folder / "dem.tif", np.zeros((20, 20)), "float32", from_origin(0, 200, 10, 10))
    with pytest.raises(GridError, match=r"dem\.tif.*pixel size.*cell_m = 5"):
        g.load_dem(flat_site.folder, grid)
    # Right on one axis only.
    _write_tif(flat_site.folder / "hazard.tif", np.zeros((20, 20)), "uint8", from_origin(0, 100, 5, 10))
    with pytest.raises(GridError, match=r"hazard\.tif.*pixel size"):
        g.load_hazard(flat_site.folder, grid)


def test_south_up_raster_fails(flat_site):
    grid = g.read_grid(flat_site.folder)
    south_up = Affine(5.0, 0.0, 0.0, 0.0, 5.0, 0.0)
    _write_tif(flat_site.folder / "dem.tif", np.zeros((20, 20)), "float32", south_up)
    with pytest.raises(GridError, match=r"dem\.tif.*south-up"):
        g.load_dem(flat_site.folder, grid)


def test_rotated_raster_fails(flat_site):
    grid = g.read_grid(flat_site.folder)
    rotated = Affine(5.0, 0.5, 0.0, 0.5, -5.0, 100.0)
    _write_tif(flat_site.folder / "hazard.tif", np.zeros((20, 20)), "uint8", rotated)
    with pytest.raises(GridError, match=r"hazard\.tif.*rotated"):
        g.load_hazard(flat_site.folder, grid)


def test_north_up_raster_with_matching_pixels_loads(flat_site):
    grid = g.read_grid(flat_site.folder)
    assert g.load_dem(flat_site.folder, grid).shape == (20, 20)


# ---- orientation -------------------------------------------------------------
def test_dem_rising_north_keeps_high_values_in_row_0(tmp_path):
    """A DEM that rises northward: the stored array must have its highest values in row 0."""
    rows, cols, cell = 20, 20, 5.0
    north_up = Affine(cell, 0.0, 0.0, 0.0, -cell, rows * cell)
    dem_file = np.tile(np.arange(rows, 0, -1, dtype=np.float32)[:, None], (1, cols))  # row 0 = 20 m
    assert dem_file[0, 0] == 20 and dem_file[-1, 0] == 1
    folder = tmp_path / "north"
    write_site(folder, np.zeros((rows, cols), np.float32), np.zeros((rows, cols), np.uint8), cell)
    _write_tif(folder / "dem.tif", dem_file, "float32", north_up)

    grid = g.read_grid(folder)
    dem = g.load_dem(folder, grid)
    assert np.array_equal(dem, dem_file.astype(np.float64))
    assert dem[0].min() > dem[-1].max()
    # The north edge is row 0; the south edge is the last row.
    assert grid.xy_to_cell(52.5, rows * cell) == (0, 10)
    assert grid.xy_to_cell(52.5, 0.0) == (rows - 1, 10)
    # Elevation read at the northern cell centre is the high one.
    r, c = grid.xy_to_cell(*grid.cell_centre(0, 3))
    assert dem[r, c] == 20.0
    # Slope magnitude is the same either way, but the plane really rises to the north.
    assert np.allclose(g.slope_deg(dem, cell)[1:-1], np.degrees(np.arctan(1.0 / cell)))


# ---- slope -------------------------------------------------------------------
def test_slope_of_10pct_plane_is_5_71_deg(tmp_path):
    """A plane tilted on both axes: dz/dx = 0.06 and dz/dy = 0.08 give atan(0.1) = 5.71 deg."""
    cell = 10.0
    grid = Grid(width=30, height=20, cell_m=cell)
    dem = np.zeros(grid.shape, dtype=np.float32)
    for r in range(grid.height):
        for c in range(grid.width):
            x, y = grid.cell_centre(r, c)
            dem[r, c] = 0.06 * x + 0.08 * y
    site = write_site(tmp_path / "plane", dem, np.zeros(grid.shape, np.uint8), cell)
    loaded = g.load_dem(site.folder, g.read_grid(site.folder))
    slope = g.slope_deg(loaded, cell)
    assert np.allclose(slope, np.degrees(np.arctan(0.1)), atol=0.01)
    assert np.allclose(slope, 5.71, atol=0.01)
    # Each axis alone would give a different answer.
    assert not np.isclose(np.degrees(np.arctan(0.06)), 5.71, atol=0.5)
    assert not np.isclose(np.degrees(np.arctan(0.08)), 5.71, atol=0.5)


def test_flat_terrain_has_zero_slope_and_nodata_blocks_neighbours(tmp_path):
    folder = tmp_path / "nodata"
    cell = 5.0
    site = write_site(folder, np.zeros((20, 20), np.float32), np.zeros((20, 20), np.uint8), cell)
    grid = g.read_grid(folder)

    flat = g.load_dem(folder, grid)
    assert np.all(g.slope_deg(flat, cell) == 0)

    dem_file = np.zeros((20, 20), dtype=np.float32)
    dem_file[5, 5] = -9999.0
    _write_tif(folder / "dem.tif", dem_file, "float32", from_origin(0, 100, cell, cell), nodata=-9999.0)
    dem = g.load_dem(folder, grid)
    assert np.isnan(dem[5, 5])
    assert np.isfinite(dem).sum() == dem.size - 1
    slope = g.slope_deg(dem, cell)
    for rc in [(4, 5), (6, 5), (5, 4), (5, 6)]:
        assert np.isnan(slope[rc]), rc
    # Cells further away stay finite and flat.
    assert slope[10, 10] == 0
    assert slope[3, 3] == 0
