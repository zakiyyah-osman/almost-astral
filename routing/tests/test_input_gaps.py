"""Gaps found by mutation probing: non-finite DEM files, plain-value parameters, Grid construction."""
import copy
import warnings

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import grid as g
from config import Config, ConfigError, load_config
from grid import Grid, GridError


def test_load_dem_turns_nan_and_inf_in_the_file_into_nan(flat_site):
    arr = np.zeros((20, 20), dtype=np.float32)
    arr[2, 3] = np.nan
    arr[4, 5] = np.inf
    arr[6, 7] = -np.inf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with rasterio.open(
            flat_site.folder / "dem.tif", "w", driver="GTiff", height=20, width=20, count=1,
            dtype="float32", transform=from_origin(0, 100, 5, 5),
        ) as dst:
            dst.write(arr, 1)
    dem = g.load_dem(flat_site.folder, g.read_grid(flat_site.folder))
    assert np.isnan(dem[2, 3]) and np.isnan(dem[4, 5]) and np.isnan(dem[6, 7])
    assert np.isnan(dem).sum() == 3
    assert np.isfinite(dem[0, 0])


@pytest.mark.parametrize("bad", [2.7, "2.7", [2.7], None])
def test_parameter_given_as_a_plain_value_is_a_config_error(bad):
    raw = copy.deepcopy(load_config().raw)
    raw["walking"]["v_flat_kmh"] = bad
    with pytest.raises(ConfigError, match=r"walking\.v_flat_kmh: must be a table"):
        Config.from_dict(raw)


@pytest.mark.parametrize("width,height", [(1, 20), (20, 1), (0, 0), (-3, 20), (20.0, 20), (True, 20), ("20", 20), (None, 20)])
def test_grid_constructor_checks_size(width, height):
    with pytest.raises(GridError, match=r"Grid (width|height)"):
        Grid(width, height, 5.0)


@pytest.mark.parametrize("cell_m", [0, -1.0, float("nan"), float("inf"), -float("inf"), "5", None, True])
def test_grid_constructor_checks_cell_size(cell_m):
    with pytest.raises(GridError, match="Grid cell_m"):
        Grid(20, 20, cell_m)


def test_grid_constructor_accepts_valid_sizes():
    assert Grid(2, 2, 0.5).shape == (2, 2)
    assert Grid(np.int64(20), 30, np.float32(5.0)).shape == (30, 20)


def test_infinite_cell_m_in_layers_json_is_rejected():
    layers = {"site": {"grid": {"width": 20, "height": 20, "cell_m": float("inf")}}}
    with pytest.raises(GridError, match="cell_m"):
        g.grid_from_layers(layers)
