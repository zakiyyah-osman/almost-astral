"""The start of a walk and why a cell is blocked (DESIGN section 4.9).

The start is not configured: plan_route.py and analysis.py take it from the command line
(--start x,y) or, without it, use the demo start, the safe landing cell nearest the grid centre
(landing.py). In the browser the start is the landing spot the user chose.

A start the route cannot use is an error that says why: outside the grid, no DEM data, a red
cell, slope over the limit, inside the cliff buffer, or a sealed gap. A start on careful ground
(yellow, or slope above risk.steep_onset_deg) is allowed and only gives a warning.

The blocked-reason codes here are the ones written to landing/mask.u8 (codes 1 to 5).
"""
import math

import numpy as np

from config import ConfigError
from cost import Cost
from grid import DEM_FILE, HAZARD_FILE, HAZARD_YELLOW, Grid, GridError

START_ID = "start"          # the id of the start in plan.json legs

# Reason codes, one per cell in landing/mask.u8 (WALLED_OFF only in route() results). A cell blocked for several reasons gets the first
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
    """The start cannot be used.

    `waypoint_id` is 'start', for the sensitivity table. `start_id` names where the start came
    from ('--start' or 'demo start'), when known.
    """

    def __init__(self, message, waypoint_id=START_ID, start_id=None):
        super().__init__(message)
        self.waypoint_id = waypoint_id
        self.start_id = start_id


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


def _label(name, xy):
    x, y = xy
    return f"{name} ({x:g}, {y:g}) m" if name else f"start ({x:g}, {y:g}) m"


def start_cell(grid: Grid, xy, origin_m=(0.0, 0.0), where="the site grid", name=None):
    """The (row, col) of the start on `grid`, whose south-west corner is at `origin_m`."""
    x, y = xy
    try:
        return grid.xy_to_cell(x - origin_m[0], y - origin_m[1])
    except GridError as e:
        raise StartError(
            f"{_label(name, xy)} is outside {where}: {e}. Choose a start inside it (--start x,y).",
            start_id=name,
        ) from None


def check_start(cost: Cost, cell, xy, hazard=None, name=None):
    """Raise StartError if the start cell is blocked; return warnings for careful ground.

    `name` says which start it is (for example 'demo start'); it is put in every message. `hazard` (the hazard
    array on the same grid as `cost`) is only needed for the yellow warning; without it only the
    slope part of the warning is checked.
    """
    code = block_code(cost, cell)
    if code != REACHABLE:
        raise StartError(
            f"{_label(name, xy)}, cell {tuple(int(v) for v in cell)}, is on a blocked cell: "
            f"{reason_text(code, cost.params)}. Choose a start on passable ground (--start x,y).",
            start_id=name,
        )
    warnings = []
    slope = float(cost.slope_deg[cell])
    onset = cost.params.steep_onset_deg
    yellow = hazard is not None and int(hazard[cell]) == HAZARD_YELLOW
    if yellow or slope > onset:
        what = "a yellow (careful) hazard cell" if yellow else "careful ground"
        warnings.append(
            f"{_label(name, xy)} is on {what}: slope {slope:.1f} deg "
            f"(careful above {onset:g} deg). Allowed, but check the landing site."
        )
    return tuple(warnings)

