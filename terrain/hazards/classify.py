"""Combine terrain derivatives into green / yellow / red / unknown classes."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from . import GREEN, YELLOW, RED, UNKNOWN, REASON_BITS as B
from .terrain import _disk


def classify(
    *,
    slope: np.ndarray,
    rough: np.ndarray,
    relief: np.ndarray,
    gap: np.ndarray,
    cfg: dict,
    cell_m: float,
    thermal: np.ndarray | None = None,
    rock_density: np.ndarray | None = None,
    large_rocks: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (hazard classes uint8, reasons bitmask uint16).

    Rules (all thresholds from config/hazards.yaml):
      red    : slope >= red, very rough, very loose sand, dense rocks,
               large rocks (+clearance), cliff edges, plus a safety buffer
      yellow : slope >= yellow, rough, loose sand, moderately dense rocks
      green  : everything else that has terrain data
      unknown: no terrain data (coverage gap) - never treated as safe
    """
    reasons = np.zeros(slope.shape, np.uint16)

    def flag(mask, name):
        reasons[mask] |= B[name]

    s, r = cfg["slope_deg"], cfg["roughness_m"]
    flag(slope >= s["yellow"], "slope_caution")
    flag(slope >= s["red"], "slope_nogo")
    flag(rough >= r["yellow"], "rough_caution")
    flag(rough >= r["red"], "rough_nogo")
    flag(relief >= cfg["cliff"]["drop_m"], "cliff_edge")

    if thermal is not None:
        t = cfg["thermal_inertia_tiu"]
        valid = np.isfinite(thermal)
        flag(valid & (thermal < t["loose"]), "loose_ground")
        flag(valid & (thermal < t["very_loose"]), "very_loose_ground")
    if rock_density is not None:
        k = cfg["rocks"]
        flag(rock_density >= k["density_yellow"], "rock_density_caution")
        flag(rock_density >= k["density_red"], "rock_density_nogo")
    if large_rocks is not None:
        flag(large_rocks, "large_rock")

    red_bits = B["slope_nogo"] | B["rough_nogo"] | B["very_loose_ground"] | B["rock_density_nogo"] | B["large_rock"] | B["cliff_edge"]
    yellow_bits = B["slope_caution"] | B["rough_caution"] | B["loose_ground"] | B["rock_density_caution"]

    red = (reasons & red_bits) > 0
    buf = cfg.get("safety_buffer_m", 0) / cell_m
    if buf > 0 and red.any():
        grown = ndimage.binary_dilation(red, structure=_disk(buf).astype(bool))
        flag(grown & ~red, "safety_buffer")
        red = grown

    classes = np.full(slope.shape, GREEN, np.uint8)
    classes[(reasons & yellow_bits) > 0] = YELLOW
    classes[red] = RED
    classes[gap] = UNKNOWN
    reasons[gap] = B["no_data"]
    return classes, reasons
