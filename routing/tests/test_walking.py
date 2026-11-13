import math

import numpy as np
import pytest

from config import load_config
from walking import speed_factor, speed_kmh, speed_m_per_min

CFG = load_config()
V = CFG.value("walking.v_flat_kmh")
K = CFG.value("walking.tobler_k")
S0 = CFG.value("walking.tobler_offset")


def test_flat_speed_is_v_flat():
    assert speed_kmh(0.0, V, K, S0) == pytest.approx(2.7)
    assert speed_kmh(0.0, 3.4, K, S0) == pytest.approx(3.4)
    assert speed_m_per_min(0.0, V, K, S0) == pytest.approx(45.0)      # 2.7 km/h
    assert speed_factor(0.0, K, S0) == pytest.approx(1.0)


def test_uphill_equals_downhill():
    for s in (0.05, 0.1, 0.36, 1.0):
        assert speed_kmh(s, V, K, S0) == speed_kmh(-s, V, K, S0)
    both = speed_kmh(np.array([-0.2, 0.2]), V, K, S0)
    assert both[0] == both[1]


def test_10pct_slope_factor_is_0_705():
    assert speed_factor(0.1, K, S0) == pytest.approx(math.exp(-0.35), rel=1e-12)
    assert speed_factor(0.1, K, S0) == pytest.approx(0.705, abs=0.0005)
    assert speed_kmh(0.1, V, K, S0) == pytest.approx(1.90, abs=0.005)


def test_speed_falls_with_steepness_and_stays_positive():
    s = np.linspace(0, 1.5, 50)
    v = speed_kmh(s, V, K, S0)
    assert np.all(np.diff(v) < 0)
    assert np.all(v > 0)


def test_offset_cancels_after_normalising():
    for s0 in (0.0, 0.05, 0.3):
        assert speed_factor(0.2, K, s0) == pytest.approx(math.exp(-K * 0.2))


def test_works_on_arrays_and_scales_with_v_flat():
    s = np.array([[0.0, 0.1], [0.2, 0.3]])
    out = speed_kmh(s, V, K, S0)
    assert out.shape == (2, 2)
    assert np.allclose(speed_kmh(s, 2 * V, K, S0), 2 * out)


def test_nan_slope_gives_nan_speed():
    assert np.isnan(speed_kmh(np.nan, V, K, S0))

def test_steepness_constant_comes_from_the_argument_not_a_fixed_value():
    assert speed_factor(0.1, 2.0, S0) == pytest.approx(math.exp(-0.2))
    assert speed_factor(0.1, 5.0, S0) == pytest.approx(math.exp(-0.5))
