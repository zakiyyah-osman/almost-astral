import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hazards as hz  # noqa: E402

THR = hz.load_thresholds()
CELL = 5.0


def classify(dem, ti=None):
    slope = hz.compute_slope(dem, CELL)
    rough = hz.compute_roughness(dem, int(THR["roughness"]["window_cells"]))
    return hz.classify(slope, rough, ti, THR)


def test_flat_ground_is_green():
    assert (classify(np.zeros((40, 40), np.float32)) == hz.GREEN).all()


def test_slope_angle_uses_cell_size():
    rise_per_cell = CELL * np.tan(np.radians(15))
    dem = np.tile(np.arange(40) * rise_per_cell, (40, 1)).astype(np.float32)
    slope = hz.compute_slope(dem, CELL)
    assert np.allclose(slope, 15, atol=0.01)  # also at the edges: no false border


def test_ramp_yellow_and_red():
    def ramp(deg):
        return np.tile(np.arange(40) * CELL * np.tan(np.radians(deg)), (40, 1)).astype(np.float32)
    assert (classify(ramp(15))[5:-5, 5:-5] == hz.YELLOW).all()
    assert (classify(ramp(25))[5:-5, 5:-5] == hz.RED).all()


def test_boulder_raises_roughness():
    dem = np.zeros((40, 40), np.float32)
    dem[20, 20] = 6.0  # a 6 m spike
    assert classify(dem)[20, 20] >= hz.YELLOW


def test_nan_is_never_green():
    dem = np.zeros((40, 40), np.float32)
    dem[10:14, 10:14] = np.nan
    haz = classify(dem)
    assert (haz[10:14, 10:14] != hz.GREEN).all()


def test_sand_alone_is_only_yellow():
    dem = np.zeros((40, 40), np.float32)
    ti = np.full((40, 40), 50.0, np.float32)  # very low thermal inertia
    assert (classify(dem, ti) == hz.YELLOW).all()


def test_sand_on_a_slope_is_red():
    dem = np.tile(np.arange(40) * CELL * np.tan(np.radians(15)), (40, 1)).astype(np.float32)
    ti = np.full((40, 40), 50.0, np.float32)
    assert (classify(dem, ti)[5:-5, 5:-5] == hz.RED).all()


def test_route_shares_follow_cells():
    haz = np.zeros((10, 10), np.uint8)
    haz[:, 5:] = hz.RED
    shares = hz.route_hazard([[0.5, 5.0], [49.5, 5.0]], haz, 5.0)
    assert 0.45 < shares["green"] < 0.55 and 0.45 < shares["red"] < 0.55


def test_smooth_ramp_has_zero_roughness_even_at_edges():
    dem = np.tile(np.arange(40) * CELL * np.tan(np.radians(15)), (40, 1)).astype(np.float32)
    assert np.allclose(hz.compute_roughness(dem, 5), 0, atol=1e-3)
