"""Hard mask, risk rate, time-rate and planning-cost arrays (DESIGN section 4).

Arrays have the shape of the grid (row 0 = north). Rates are in minutes per metre.

    hard mask     cells that cannot be entered (cost -1 in the arrays below)
    risk rate     risk-minutes per minute walked, the sum of three parts
    time rate     1 / v(slope): physical minutes per metre
    planning rate time rate x (1 + w x risk rate): used only to choose a path
"""
import math
from dataclasses import dataclass, replace

import numpy as np
from scipy import ndimage

from config import Config, ConfigError
from grid import HAZARD_RED, HAZARD_YELLOW, Grid, GridError
from walking import speed_m_per_min

BLOCKED = -1.0          # cost of a blocked cell; MCP_Geometric treats a negative cost as impassable
DIST_TOL_M = 1e-9       # slack when comparing a computed distance with a buffer width


@dataclass(frozen=True)
class Params:
    """The config values the cost model uses. Build with Params.from_config(cfg)."""

    v_flat_kmh: float
    tobler_k: float
    tobler_offset: float
    slope_max_deg: float
    cliff_buffer_m: float
    yellow_rate: float
    steep_onset_deg: float
    steep_rate_max: float
    near_red_radius_m: float
    near_red_rate_max: float

    def __post_init__(self):
        if not self.steep_onset_deg < self.slope_max_deg:
            raise ConfigError(
                f"risk.steep_onset_deg ({self.steep_onset_deg}) must be below "
                f"constraints.slope_max_deg ({self.slope_max_deg})"
            )

    @classmethod
    def from_config(cls, cfg: Config, **overrides):
        """Read every field from the config; `overrides` replace fields (sensitivity runs)."""
        keys = {
            "v_flat_kmh": "walking.v_flat_kmh",
            "tobler_k": "walking.tobler_k",
            "tobler_offset": "walking.tobler_offset",
            "slope_max_deg": "constraints.slope_max_deg",
            "cliff_buffer_m": "constraints.cliff_buffer_m",
            "yellow_rate": "risk.yellow_rate",
            "steep_onset_deg": "risk.steep_onset_deg",
            "steep_rate_max": "risk.steep_rate_max",
            "near_red_radius_m": "risk.near_red_radius_m",
            "near_red_rate_max": "risk.near_red_rate_max",
        }
        unknown = set(overrides) - set(keys)
        if unknown:
            raise ConfigError(f"unknown cost parameter override: {', '.join(sorted(unknown))}")
        values = {name: cfg.value(key) for name, key in keys.items()}
        values.update(overrides)
        return cls(**values)

    def with_(self, **changes):
        return replace(self, **changes)


def _check_shapes(**arrays):
    shapes = {name: a.shape for name, a in arrays.items()}
    if len(set(shapes.values())) != 1:
        raise GridError(f"arrays must have one shape, got {shapes}")


# ---- hard constraints --------------------------------------------------------
def _squeeze_cells(blocked):
    """One pass: free cells in a 2x2 block whose other diagonal is blocked and own diagonal free.

    This is the squeeze the search would otherwise allow: two free cells that touch only at a
    corner, with a blocked cell on each side. For a free cell, the other diagonal of a 2x2
    block is its two orthogonal neighbours in that block, so a cell is flagged when two
    perpendicular neighbours are both blocked and the diagonal cell between them is free.
    """
    pad = np.pad(blocked, 1, constant_values=False)
    h, w = blocked.shape
    n, s = pad[0:h, 1:w + 1], pad[2:h + 2, 1:w + 1]
    west, east = pad[1:h + 1, 0:w], pad[1:h + 1, 2:w + 2]
    nw, ne = pad[0:h, 0:w], pad[0:h, 2:w + 2]
    sw, se = pad[2:h + 2, 0:w], pad[2:h + 2, 2:w + 2]
    squeeze = (
        (n & west & ~nw) | (n & east & ~ne) | (s & west & ~sw) | (s & east & ~se)
    )
    return squeeze & ~blocked


def _seal_diagonal_gaps(blocked):
    """Cells added by sealing, repeated until no 2x2 block has one diagonal blocked and the other free.

    Sealing only adds blocked cells, so the loop ends after at most as many passes as there are
    cells. A sealed cell can create a new squeeze, which the next pass closes.
    """
    current = blocked.copy()
    while True:
        new = _squeeze_cells(current)
        if not new.any():
            return current & ~blocked
        current |= new


def hard_constraints(dem, slope_deg, hazard, cell_m, p: Params):
    """Why each cell is blocked, as a dict of boolean arrays.

    nodata  DEM or slope is NaN
    red     hazard is red
    slope   slope above constraints.slope_max_deg
    buffer  within cliff_buffer_m of a cell over the slope limit (and not itself over it)
    sealed  free cell in a 2x2 block whose other diagonal is blocked (closes corner gaps)
    """
    _check_shapes(dem=dem, slope_deg=slope_deg, hazard=hazard)
    nodata = np.isnan(dem) | np.isnan(slope_deg)
    red = hazard == HAZARD_RED
    with np.errstate(invalid="ignore"):
        over = slope_deg > p.slope_max_deg
    buffer = np.zeros_like(over)
    if p.cliff_buffer_m > 0 and over.any():
        dist = ndimage.distance_transform_edt(~over, sampling=cell_m)
        buffer = (dist <= p.cliff_buffer_m + DIST_TOL_M) & ~over
    base = nodata | red | over | buffer
    sealed = _seal_diagonal_gaps(base)
    return {"nodata": nodata, "red": red, "slope": over, "buffer": buffer, "sealed": sealed}


def hard_mask(dem, slope_deg, hazard, cell_m, p: Params):
    """True where a cell is impassable."""
    masks = hard_constraints(dem, slope_deg, hazard, cell_m, p)
    return masks["nodata"] | masks["red"] | masks["slope"] | masks["buffer"] | masks["sealed"]


# ---- soft constraints --------------------------------------------------------
def risk_components(hazard, slope_deg, cell_m, p: Params):
    """The three parts of the risk rate (risk-min per min), as a dict of arrays.

    yellow    yellow_rate on yellow cells
    steep     steep_rate_max x ramp(slope; steep_onset_deg -> slope_max_deg); NaN slope gives 0
    near_red  near_red_rate_max x (1 - distance to red / near_red_radius_m), clipped at 0
    """
    _check_shapes(hazard=hazard, slope_deg=slope_deg)
    yellow = np.where(hazard == HAZARD_YELLOW, p.yellow_rate, 0.0)

    with np.errstate(invalid="ignore"):
        ramp = np.clip((slope_deg - p.steep_onset_deg) / (p.slope_max_deg - p.steep_onset_deg), 0.0, 1.0)
    steep = p.steep_rate_max * np.nan_to_num(ramp, nan=0.0)

    red = hazard == HAZARD_RED
    if red.any():
        dist = ndimage.distance_transform_edt(~red, sampling=cell_m)
        near_red = p.near_red_rate_max * np.clip(1.0 - dist / p.near_red_radius_m, 0.0, None)
    else:
        near_red = np.zeros(hazard.shape)
    return {"yellow": yellow, "steep": steep, "near_red": near_red}


def risk_rate(hazard, slope_deg, cell_m, p: Params):
    """Total risk rate: yellow + steep + near-red."""
    parts = risk_components(hazard, slope_deg, cell_m, p)
    return parts["yellow"] + parts["steep"] + parts["near_red"]


# ---- time and planning cost --------------------------------------------------
def time_rate(slope_deg, blocked, p: Params):
    """Physical minutes per metre, 1 / v(slope); -1 where blocked."""
    out = np.full(slope_deg.shape, BLOCKED)
    ok = ~blocked
    ratio = np.tan(np.radians(slope_deg[ok]))
    out[ok] = 1.0 / speed_m_per_min(ratio, p.v_flat_kmh, p.tobler_k, p.tobler_offset)
    return out


def planning_rate(time_rate_arr, risk_rate_arr, w, blocked):
    """time rate x (1 + w x risk rate), for choosing a path; -1 where blocked."""
    if isinstance(w, bool) or not isinstance(w, (int, float, np.floating, np.integer)) \
            or not math.isfinite(w) or w < 0:
        raise ConfigError(f"w must be a finite number >= 0, got {w!r}")
    return np.where(blocked, BLOCKED, time_rate_arr * (1.0 + w * risk_rate_arr))


@dataclass(frozen=True)
class Cost:
    """Everything the search needs for one site and one set of parameters."""

    grid: Grid
    params: Params
    slope_deg: np.ndarray
    blocked: np.ndarray
    reasons: dict
    time_rate: np.ndarray       # min/m, -1 where blocked
    risk_parts: dict            # yellow / steep / near_red rates, 0 where blocked
    risk_rate: np.ndarray       # sum of the parts, 0 where blocked

    def planning_rate(self, w):
        return planning_rate(self.time_rate, self.risk_rate, w, self.blocked)


def build(dem, hazard, slope_deg, grid: Grid, p: Params):
    """Hard mask, risk rate and time rate for a site."""
    reasons = hard_constraints(dem, slope_deg, hazard, grid.cell_m, p)
    blocked = (
        reasons["nodata"] | reasons["red"] | reasons["slope"] | reasons["buffer"] | reasons["sealed"]
    )
    parts = risk_components(hazard, slope_deg, grid.cell_m, p)
    parts = {k: np.where(blocked, 0.0, v) for k, v in parts.items()}
    total = parts["yellow"] + parts["steep"] + parts["near_red"]
    return Cost(
        grid=grid, params=p, slope_deg=slope_deg, blocked=blocked, reasons=reasons,
        time_rate=time_rate(slope_deg, blocked, p), risk_parts=parts, risk_rate=total,
    )


__all__ = [
    "BLOCKED", "Params", "Cost", "build", "hard_constraints", "hard_mask", "risk_components",
    "risk_rate", "time_rate", "planning_rate",
]
