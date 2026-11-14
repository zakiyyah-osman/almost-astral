"""The fixed start of every walk, and why a cell is blocked (DESIGN section 4.9).

The start comes from routing/config.toml (start.xy_m), in metres on the site grid. For now it
is landing spot L1 (see the comment in config.toml). plan_route.py and export_reach.py both
start from it, so the outing plan, the minutes-back-to-start map and the reach grids all
measure from the same cell.

A start the route cannot use is an error that says why: outside the grid, no DEM data, a red
cell, slope over the limit, inside the cliff buffer, or a sealed gap. A start on careful ground
(yellow, or slope above risk.steep_onset_deg) is allowed and only gives a warning.

The blocked-reason codes here are the ones written to reach/reason.u8.
"""
import math

import numpy as np

from config import Config, ConfigError
from cost import Cost
from grid import HAZARD_YELLOW, Grid, GridError

START_ID = "start"

# Reason codes, one per cell in reason.u8. A cell blocked for several reasons gets the first
# one in BLOCK_ORDER (the same order block_reason has always used).
REACHABLE, NODATA, RED, SLOPE, BUFFER, SEALED, WALLED_OFF = range(7)
REASON_NAMES = {
    REACHABLE: "reachable",
    NODATA: "nodata",
    RED: "red",
    SLOPE: "slope",
    BUFFER: "buffer",
    SEALED: "sealed",
    WALLED_OFF: "walled_off",
}
BLOCK_ORDER = (NODATA, RED, SLOPE, BUFFER, SEALED)


class StartError(ConfigError):
    """The configured start cannot be used. `waypoint_id` is 'start', for the sensitivity table."""

    def __init__(self, message, waypoint_id=START_ID):
        super().__init__(message)
        self.waypoint_id = waypoint_id


def reason_text(code, params):
    """The reason for a code, in words. `params` is a cost.Params (for the limits)."""
    return {
        REACHABLE: "reachable",
        NODATA: "no DEM data",
        RED: "red hazard cell",
        SLOPE: f"slope over the limit ({params.slope_max_deg:g} deg)",
        BUFFER: f"inside the {params.cliff_buffer_m:g} m buffer around over-limit slopes",
        SEALED: "sealed gap between blocked cells",
        WALLED_OFF: "passable, but walled off from the start by blocked cells",
    }[code]


def block_code(cost: Cost, cell):
    """The first reason a cell is blocked, or REACHABLE (0) if it is passable."""
    for code in BLOCK_ORDER:
        if cost.reasons[REASON_NAMES[code]][cell]:
            return code
    return REACHABLE


def block_codes(cost: Cost):
    """block_code for every cell, as a uint8 array (0 where passable)."""
    out = np.zeros(cost.blocked.shape, dtype=np.uint8)
    for code in reversed(BLOCK_ORDER):           # the first reason in BLOCK_ORDER is written last and wins
        out[cost.reasons[REASON_NAMES[code]]] = code
    return out


def start_xy(cfg: Config):
    """The configured start (x, y) in metres."""
    x, y = cfg.value("start.xy_m")
    return float(x), float(y)


def start_cell(grid: Grid, xy, origin_m=(0.0, 0.0), where="the site grid"):
    """The (row, col) of the start on `grid`, whose south-west corner is at `origin_m`."""
    x, y = xy
    try:
        return grid.xy_to_cell(x - origin_m[0], y - origin_m[1])
    except GridError as e:
        raise StartError(
            f"start ({x:g}, {y:g}) m is outside {where}: {e}. Set start.xy_m in routing/config.toml "
            "to a point inside it."
        ) from None


def check_start(cost: Cost, cell, xy, hazard=None):
    """Raise StartError if the start cell is blocked; return warnings for careful ground.

    `hazard` (the hazard array on the same grid as `cost`) is only needed for the yellow
    warning; without it only the slope part of the warning is checked.
    """
    x, y = xy
    code = block_code(cost, cell)
    if code != REACHABLE:
        raise StartError(
            f"start ({x:g}, {y:g}) m, cell {tuple(int(v) for v in cell)}, is on a blocked cell: "
            f"{reason_text(code, cost.params)}. Move start.xy_m in routing/config.toml to passable ground."
        )
    warnings = []
    slope = float(cost.slope_deg[cell])
    onset = cost.params.steep_onset_deg
    yellow = hazard is not None and int(hazard[cell]) == HAZARD_YELLOW
    if yellow or slope > onset:
        what = "a yellow (careful) hazard cell" if yellow else "careful ground"
        warnings.append(
            f"start ({x:g}, {y:g}) m is on {what}: slope {slope:.1f} deg "
            f"(careful above {onset:g} deg). Allowed, but check the landing site."
        )
    return tuple(warnings)


def is_near(a, b, cell_m):
    """True when two points are at most half a cell apart."""
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= cell_m / 2.0
