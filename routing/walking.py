"""Walking speed as a function of slope (DESIGN section 5).

    v(S) = v_flat * exp(-k * (|S| + s0)) / exp(-k * s0)

S is slope as rise over run (not degrees). Tobler's hiking function supplies only the
slope shape; it is normalised to 1 on flat ground, so v(0) = v_flat. The speed is the
same uphill and downhill. Gravity enters only through the walk-run check in config.py.
"""
import numpy as np


def speed_factor(slope_ratio, k, offset):
    """Speed relative to flat ground, in (0, 1]: exp(-k * (|S| + s0)) / exp(-k * s0)."""
    s = np.abs(np.asarray(slope_ratio, dtype=np.float64))
    return np.exp(-k * (s + offset)) / np.exp(-k * offset)


def speed_kmh(slope_ratio, v_flat_kmh, k, offset):
    """Walking speed in km/h on slope S (rise over run)."""
    return v_flat_kmh * speed_factor(slope_ratio, k, offset)


def speed_m_per_min(slope_ratio, v_flat_kmh, k, offset):
    """Walking speed in metres per minute on slope S (rise over run)."""
    return speed_kmh(slope_ratio, v_flat_kmh, k, offset) * 1000.0 / 60.0
