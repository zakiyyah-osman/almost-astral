"""Bad inputs for grid.py: file errors, odd transforms, hazard values, no-data and infinite DEM cells."""
import json
import warnings

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin

import grid as g
from grid import Grid, GridError

SAME = from_origin(0, 100, 5, 5)        # the transform flat_site writes for both files


def _write_tif(path, arr, dtype, transform=SAME, nodata=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with rasterio.open(
            path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
            dtype=dtype, transform=transform, nodata=nodata,
        ) as dst:
            dst.write(arr.astype(dtype), 1)


# ---- slope with no-data and infinite cells -----------------------------------
def test_nan_dem_cell_has_nan_slope_in_the_interior():
    dem = np.zeros((9, 9))
    dem[4, 4] = np.nan
    slope = g.slope_deg(dem, 5.0)
    assert np.isnan(slope[4, 4])
    assert {tuple(rc) for rc in np.argwhere(np.isnan(slope))} == {(4, 4), (3, 4), (5, 4), (4, 3), (4, 5)}


def test_infinite_dem_value_gives_nan_slope_not_90_degrees():
    for bad in (np.inf, -np.inf):
        dem = np.zeros((9, 9))
        dem[4, 4] = bad
        slope = g.slope_deg(dem, 5.0)
        assert np.isnan(slope[4, 4])
        for rc in [(3, 4), (5, 4), (4, 3), (4, 5)]:
            assert np.isnan(slope[rc]), (bad, rc)
        assert np.isnan(slope).sum() == 5
        assert not (slope > 89).any()


def test_no_data_cell_on_the_edge_has_nan_slope():
    dem = np.zeros((6, 6))
    dem[0, 0] = np.nan
    slope = g.slope_deg(dem, 5.0)
    assert np.isnan(slope[0, 0])


def test_slope_does_not_change_its_input():
    dem = np.zeros((5, 5))
    dem[2, 2] = np.inf
    g.slope_deg(dem, 5.0)
    assert np.isinf(dem[2, 2])


# ---- layers.json errors ------------------------------------------------------
def test_missing_layers_json_names_the_file(tmp_path):
    with pytest.raises(GridError, match="layers.json not found"):
        g.read_grid(tmp_path)


def test_unreadable_layers_json_names_the_file(tmp_path):
    (tmp_path / "layers.json").mkdir()
    with pytest.raises(GridError, match=r"layers\.json cannot be read"):
        g.read_grid(tmp_path)


def test_invalid_json_names_the_file(tmp_path):
    (tmp_path / "layers.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(GridError, match=r"layers\.json is not valid JSON"):
        g.read_grid(tmp_path)


def test_non_utf8_layers_json_names_the_file(tmp_path):
    (tmp_path / "layers.json").write_bytes(b"\xff\xfe\x00{}")
    with pytest.raises(GridError, match=r"layers\.json"):
        g.read_grid(tmp_path)


@pytest.mark.parametrize("text", ["[]", "3", '"x"', "null"])
def test_layers_json_must_be_an_object(tmp_path, text):
    (tmp_path / "layers.json").write_text(text, encoding="utf-8")
    with pytest.raises(GridError, match=r"layers\.json must be a JSON object"):
        g.read_grid(tmp_path)


@pytest.mark.parametrize("site", [None, "x", [1, 2], 5])
def test_layers_json_site_must_be_an_object(site):
    with pytest.raises(GridError, match="site.grid"):
        g.grid_from_layers({"site": site})


@pytest.mark.parametrize("width,height", [(1, 20), (20, 1), (1, 1)])
def test_grid_needs_at_least_2_rows_and_columns(width, height):
    layers = {"site": {"grid": {"width": width, "height": height, "cell_m": 5.0}}}
    with pytest.raises(GridError, match=r"layers\.json.*at least 2 rows and 2 columns"):
        g.grid_from_layers(layers)
    layers["site"]["grid"].update(width=2, height=2)
    assert g.grid_from_layers(layers) == Grid(2, 2, 5.0)


def test_grid_error_is_found_through_read_grid(tmp_path):
    (tmp_path / "layers.json").write_text(
        json.dumps({"site": {"grid": {"width": 1, "height": 5, "cell_m": 5}}}), encoding="utf-8"
    )
    with pytest.raises(GridError, match="at least 2"):
        g.read_grid(tmp_path)


# ---- raster file errors ------------------------------------------------------
def test_missing_dem_names_the_file(flat_site):
    (flat_site.folder / "dem.tif").unlink()
    with pytest.raises(GridError, match=r"dem\.tif not found"):
        g.load_dem(flat_site.folder, g.read_grid(flat_site.folder))


def test_missing_hazard_names_the_file(flat_site):
    (flat_site.folder / "hazard.tif").unlink()
    with pytest.raises(GridError, match=r"hazard\.tif not found"):
        g.load_hazard(flat_site.folder, g.read_grid(flat_site.folder))


def test_garbage_dem_names_the_file(flat_site):
    (flat_site.folder / "dem.tif").write_bytes(b"this is not a tiff")
    with pytest.raises(GridError, match=r"dem\.tif cannot be read"):
        g.load_dem(flat_site.folder, g.read_grid(flat_site.folder))


def test_garbage_hazard_is_named_when_loading_the_dem(flat_site):
    """The agreement check opens the other file too, so its failure must name it."""
    (flat_site.folder / "hazard.tif").write_bytes(b"this is not a tiff")
    with pytest.raises(GridError, match=r"hazard\.tif cannot be read"):
        g.load_dem(flat_site.folder, g.read_grid(flat_site.folder))


# ---- geotransform ------------------------------------------------------------
def test_tiff_without_a_geotransform_has_its_own_message(flat_site):
    grid = g.read_grid(flat_site.folder)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with rasterio.open(
            flat_site.folder / "dem.tif", "w", driver="GTiff", height=20, width=20, count=1,
            dtype="float32",
        ) as dst:
            dst.write(np.zeros((20, 20), dtype="float32"), 1)
    with pytest.raises(GridError, match=r"dem\.tif has no geotransform") as e:
        g.load_dem(flat_site.folder, grid)
    assert "south-up" not in str(e.value)


def test_x_only_pixel_size_error(flat_site):
    grid = g.read_grid(flat_site.folder)
    for load, name, dtype in ((g.load_dem, "dem.tif", "float32"), (g.load_hazard, "hazard.tif", "uint8")):
        _write_tif(flat_site.folder / name, np.zeros((20, 20)), dtype, from_origin(0, 100, 10, 5))
        with pytest.raises(GridError, match=rf"{name.replace('.', r'[.]')} has pixel size 10.0 x 5.0"):
            load(flat_site.folder, grid)
        _write_tif(flat_site.folder / name, np.zeros((20, 20)), dtype)


def test_hazard_shifted_north_south_fails(flat_site):
    grid = g.read_grid(flat_site.folder)
    for y_top in (105.0, 95.0):                      # one cell north, one cell south
        _write_tif(flat_site.folder / "hazard.tif", np.zeros((20, 20)), "uint8", from_origin(0, y_top, 5, 5))
        for load in (g.load_dem, g.load_hazard):
            with pytest.raises(GridError, match=r"dem\.tif and hazard\.tif.*different geotransforms"):
                load(flat_site.folder, grid)


@pytest.mark.parametrize(
    "transform",
    [Affine(5.0, 0.5, 0.0, 0.0, -5.0, 100.0), Affine(5.0, 0.0, 0.0, 0.5, -5.0, 100.0)],
    ids=["x-shear-b", "y-shear-d"],
)
def test_each_rotation_term_alone_is_rejected(flat_site, transform):
    grid = g.read_grid(flat_site.folder)
    _write_tif(flat_site.folder / "dem.tif", np.zeros((20, 20)), "float32", transform)
    with pytest.raises(GridError, match=r"dem\.tif is rotated"):
        g.load_dem(flat_site.folder, grid)


# ---- hazard values -----------------------------------------------------------
@pytest.mark.parametrize("bad", [0.5, -1.0, 2.5, 3.0, np.nan])
def test_non_integer_or_negative_hazard_values_rejected(flat_site, bad):
    grid = g.read_grid(flat_site.folder)
    arr = np.zeros((20, 20), dtype=np.float32)
    arr[7, 3] = bad
    _write_tif(flat_site.folder / "hazard.tif", arr, "float32")
    with pytest.raises(GridError, match="hazard.tif has values outside 0-2"):
        g.load_hazard(flat_site.folder, grid)


def test_hazard_values_0_1_2_load(flat_site):
    grid = g.read_grid(flat_site.folder)
    arr = np.zeros((20, 20), dtype=np.uint8)
    arr[0, 0], arr[1, 1] = 1, 2
    _write_tif(flat_site.folder / "hazard.tif", arr, "uint8")
    out = g.load_hazard(flat_site.folder, grid)
    assert out.dtype == np.uint8 and out[0, 0] == 1 and out[1, 1] == 2


# ---- xy_to_cell input --------------------------------------------------------
@pytest.mark.parametrize("bad", ["5", None, True, [1], (1, 2), b"1"])
def test_xy_to_cell_rejects_non_numeric_input(bad):
    grid = Grid(20, 20, 5.0)
    with pytest.raises(GridError, match="must be a number"):
        grid.xy_to_cell(bad, 10.0)
    with pytest.raises(GridError, match="must be a number"):
        grid.xy_to_cell(10.0, bad)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_xy_to_cell_rejects_non_finite_input(bad):
    grid = Grid(20, 20, 5.0)
    with pytest.raises(GridError, match="finite"):
        grid.xy_to_cell(bad, 10.0)
    with pytest.raises(GridError, match="finite"):
        grid.xy_to_cell(10.0, bad)


def test_xy_to_cell_accepts_numpy_numbers():
    grid = Grid(20, 20, 5.0)
    assert grid.xy_to_cell(np.float64(52.5), np.int64(5)) == (18, 10)
    assert grid.xy_to_cell(np.float32(2.5), np.float32(97.5)) == (0, 0)


# ---- a byte-order mark -------------------------------------------------------
def test_layers_json_with_a_utf8_bom_is_accepted(tmp_path):
    text = json.dumps({"site": {"grid": {"width": 20, "height": 20, "cell_m": 5}}})
    (tmp_path / "layers.json").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    assert g.read_grid(tmp_path) == Grid(20, 20, 5.0)


def test_layers_json_without_a_bom_still_works(tmp_path):
    (tmp_path / "layers.json").write_text(
        json.dumps({"site": {"grid": {"width": 20, "height": 20, "cell_m": 5}}}), encoding="utf-8"
    )
    assert g.read_grid(tmp_path) == Grid(20, 20, 5.0)
