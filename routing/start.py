"""The starts of a walk, and why a cell is blocked (DESIGN section 4.9).

The starts come from routing/config.toml ([starts.<id>], in metres on the site grid). For now
they are landing spots L1, L2 and L3 (see the comment in config.toml), and start.default says
which one plan_route.py plans the full outing from, so the outing plan and the
minutes-back-to-start map measure from the same cell. export_reach.py exports one set of reach
grids per start.

A start the route cannot use is an error that names the start and says why: outside the grid, no
DEM data, a red cell, slope over the limit, inside the cliff buffer, or a sealed gap. A start on
careful ground (yellow, or slope above risk.steep_onset_deg) is allowed and only gives a warning.

The blocked-reason codes here are the ones written to reach/<start id>/reason.u8.
"""
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config import Config, ConfigError
from cost import Cost
from grid import DEM_FILE, HAZARD_FILE, HAZARD_YELLOW, Grid, GridError

START_ID = "start"          # the id of the start in plan.json legs, whichever landing spot it is

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
    """A configured start cannot be used.

    `waypoint_id` is 'start', for the sensitivity table. `start_id` is the id of the start in the
    config (for example 'L2'), when the error is about one.
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


# ---- the configured starts ---------------------------------------------------
@dataclass(frozen=True)
class StartSpec:
    id: str                     # the id in the config, for example "L1"
    xy: tuple                   # (x, y) in metres on the site grid


@dataclass(frozen=True)
class StartInfo:
    """A start that passed the checks: where it is on the grid it was checked on, and its warnings."""

    id: str
    xy: tuple
    cell: tuple                 # (row, col)
    warnings: tuple


def starts(cfg: Config):
    """Every configured start, in config order."""
    return [StartSpec(sid, xy) for sid, xy in cfg.starts().items()]


def default_start(cfg: Config) -> StartSpec:
    sid = cfg.default_start_id()
    return StartSpec(sid, cfg.starts()[sid])


def _label(name, xy):
    x, y = xy
    return f"start {name!r} ({x:g}, {y:g}) m" if name else f"start ({x:g}, {y:g}) m"


def _fix(name):
    return f"Set starts.{name} in routing/config.toml" if name else "Set the start in routing/config.toml"


def start_cell(grid: Grid, xy, origin_m=(0.0, 0.0), where="the site grid", name=None):
    """The (row, col) of the start on `grid`, whose south-west corner is at `origin_m`."""
    x, y = xy
    try:
        return grid.xy_to_cell(x - origin_m[0], y - origin_m[1])
    except GridError as e:
        raise StartError(
            f"{_label(name, xy)} is outside {where}: {e}. {_fix(name)} to a point inside it.",
            start_id=name,
        ) from None


def check_start(cost: Cost, cell, xy, hazard=None, name=None):
    """Raise StartError if the start cell is blocked; return warnings for careful ground.

    `name` is the start's id in the config; it is put in every message. `hazard` (the hazard
    array on the same grid as `cost`) is only needed for the yellow warning; without it only the
    slope part of the warning is checked.
    """
    code = block_code(cost, cell)
    if code != REACHABLE:
        raise StartError(
            f"{_label(name, xy)}, cell {tuple(int(v) for v in cell)}, is on a blocked cell: "
            f"{reason_text(code, cost.params)}. {_fix(name)} to passable ground.",
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


def validate_starts(cfg: Config, cost: Cost, hazard=None, origin_m=(0.0, 0.0), where="the site grid"):
    """Check every configured start on `cost`'s grid; {id: StartInfo} in config order.

    The first start that fails raises a StartError that names it. `origin_m` and `where` are for
    an export grid that does not start at (0, 0) (reach.crop_m).
    """
    out = {}
    for spec in starts(cfg):
        cell = start_cell(cost.grid, spec.xy, origin_m, where, spec.id)
        out[spec.id] = StartInfo(spec.id, spec.xy, cell, check_start(cost, cell, spec.xy, hazard, spec.id))
    return out


def is_near(a, b, cell_m):
    """True when two points are at most half a cell apart."""
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= cell_m / 2.0


# ---- the data the starts were computed on -------------------------------------
def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def staleness_warnings(cfg: Config, folder):
    """A warning for each input file that is not the one the landing spots were computed on.

    start.dem_sha256 and start.hazard_sha256 in the config hold the hashes of dem.tif and
    hazard.tif of that run. A different file means L1, L2 and L3 may no longer be what
    web/src/lib/landing.js recommends, or may no longer be flat and clear.
    """
    out = []
    for name, key in ((DEM_FILE, "start.dem_sha256"), (HAZARD_FILE, "start.hazard_sha256")):
        path = Path(folder) / name
        if not path.exists():
            continue                                    # loading the site reports a missing file
        now, then = file_sha256(path), cfg.value(key)
        if now != then:
            out.append(
                f"{name} is not the file the starts were computed on (sha256 {now[:12]}..., the config has "
                f"{then[:12]}... in {key}): recompute the landing spots with web/src/lib/landing.js, put "
                f"them in the [starts.*] tables and the new hash in {key} in routing/config.toml"
            )
    return tuple(out)
