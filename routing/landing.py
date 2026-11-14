"""Landing safety: is a lander pad centred on each cell safe, and where is the nearest safe one (DESIGN section 14).

The user clicks anywhere to choose a landing zone. Every cell gets a safety code for a circular
pad of radius landing.pad_radius_m centred on it, using the real layers only:

    code  name                 the pad ...
    0     safe                 passes every rule
    1     marginal             passes, but is within landing.marginal_pct of at least one limit
    2     outside_coverage     (or its clearance circle) does not fit inside the grid
    3     no_data              has a cell with no DEM or slope value
    4     hazard_or_clearance  has a cell that is not green or is blocked for walking, or a red,
                               over-limit-slope or cliff-buffer cell lies within
                               landing.hazard_clearance_m of the pad centre
    5     too_steep            best-fit plane tilts more than landing.max_pad_slope_deg
    6     height_range         highest minus lowest cell about that plane exceeds landing.max_height_range_m
    7     too_rough            RMS about that plane exceeds landing.max_roughness_m

When several failures apply, the lowest code wins (2 is the most serious, 7 the least). A pad
that is "safe" is always on a cell that can be walked from: blocked cells fail rule 4.

Thermal inertia (THEMIS) is a warning only, never a rule: bit 1 of the warning grid is set when a
pad cell is below landing.ti_warn_below (loose ground), bit 2 when a pad cell has no thermal
inertia value. It is only checked while layers.json marks the thermal layer as real.

Every limit is in metres or degrees. The pad and the clearance are turned into cells from cell_m,
so the same config works on any grid.
"""
import math
from dataclasses import dataclass, replace

import numpy as np
from scipy import ndimage

import grid as grid_mod
from config import Config, ConfigError
from cost import Cost
from grid import HAZARD_GREEN, Grid, GridError

SAFE, MARGINAL, OUTSIDE, NODATA, HAZARD, STEEP, RANGE, ROUGH = range(8)
CODE_NAMES = {
    SAFE: "safe",
    MARGINAL: "marginal",
    OUTSIDE: "outside_coverage",
    NODATA: "no_data",
    HAZARD: "hazard_or_clearance",
    STEEP: "too_steep",
    RANGE: "height_range",
    ROUGH: "too_rough",
}
FAIL_ORDER = (OUTSIDE, NODATA, HAZARD, STEEP, RANGE, ROUGH)      # most serious first
ACCEPTED = (SAFE, MARGINAL)                                         # a click here is not moved

WARN_LOW_TI, WARN_NO_TI = 1, 2                                      # bits of the warning grid
WARN_NAMES = {WARN_LOW_TI: "low_thermal_inertia", WARN_NO_TI: "no_thermal_inertia_data"}

THERMAL_LAYER_ID, THERMAL_FILE = "thermal", "thermal_inertia.tif"
ROUGHNESS_LAYER_ID, ROUGHNESS_FILE = "roughness", "roughness.tif"
DIST_TOL_M = 1e-9


class LandingError(ConfigError):
    """No safe landing cell, or a landing input cannot be used."""


@dataclass(frozen=True)
class Rules:
    """The [landing] thresholds of the config. Build with Rules.from_config(cfg)."""

    pad_radius_m: float
    max_pad_slope_deg: float
    max_roughness_m: float
    max_height_range_m: float
    hazard_clearance_m: float
    marginal_pct: float
    ti_warn_below: float

    KEYS = {
        "pad_radius_m": "landing.pad_radius_m",
        "max_pad_slope_deg": "landing.max_pad_slope_deg",
        "max_roughness_m": "landing.max_roughness_m",
        "max_height_range_m": "landing.max_height_range_m",
        "hazard_clearance_m": "landing.hazard_clearance_m",
        "marginal_pct": "landing.marginal_pct",
        "ti_warn_below": "landing.ti_warn_below",
    }

    @classmethod
    def from_config(cls, cfg: Config, **overrides):
        unknown = set(overrides) - set(cls.KEYS)
        if unknown:
            raise ConfigError(f"unknown landing rule override: {', '.join(sorted(unknown))}")
        values = {name: float(cfg.value(key)) for name, key in cls.KEYS.items()}
        values.update(overrides)
        return cls(**values)

    def with_(self, **changes):
        return replace(self, **changes)


def code_text(code, rules: Rules):
    """A code in words, with the limit it refers to."""
    return {
        SAFE: "safe: the pad passes every rule",
        MARGINAL: f"marginal: passes, but within {rules.marginal_pct:g}% of at least one limit",
        OUTSIDE: f"outside coverage: the {max(rules.pad_radius_m, rules.hazard_clearance_m):g} m circle "
                 "around this point does not fit inside the data",
        NODATA: "no data: a pad cell has no DEM or slope value",
        HAZARD: f"hazard: a pad cell is not green or cannot be walked on, or a red, over-limit-slope or "
                f"cliff-buffer cell is within {rules.hazard_clearance_m:g} m",
        STEEP: f"too steep: the pad tilts more than {rules.max_pad_slope_deg:g} deg",
        RANGE: f"height range: more than {rules.max_height_range_m:g} m between the highest and lowest "
               "point once the tilt is removed",
        ROUGH: f"too rough: more than {rules.max_roughness_m:g} m RMS about the pad's best-fit plane",
    }[code]


# ---- the pad -----------------------------------------------------------------
def disk_offsets(radius_m, cell_m):
    """(row, col) offsets of the cells whose centre is within radius_m of the centre cell's centre."""
    rc = int(math.floor(radius_m / cell_m + DIST_TOL_M))
    out = [
        (dr, dc)
        for dr in range(-rc, rc + 1)
        for dc in range(-rc, rc + 1)
        if math.hypot(dr, dc) * cell_m <= radius_m + DIST_TOL_M
    ]
    return np.array(out, dtype=int).reshape(-1, 2)


def _shifted(arr, pad, fill, dr, dc):
    """arr[r + dr, c + dc] for every (r, c), from a copy padded by `pad` cells of `fill`."""
    h, w = arr.shape
    return pad[fill][pad["n"] + dr: pad["n"] + dr + h, pad["n"] + dc: pad["n"] + dc + w]


@dataclass(frozen=True)
class Measures:
    """Per-cell pad measures (NaN where the pad has no data or does not fit)."""

    tilt_deg: np.ndarray
    roughness_m: np.ndarray
    height_range_m: np.ndarray
    clearance_m: np.ndarray        # distance from the cell centre to the nearest red / over-limit / buffer cell
    outside: np.ndarray            # bool: the pad or clearance circle does not fit in the grid
    nodata: np.ndarray             # bool: a pad cell has no DEM or slope value
    hazard: np.ndarray             # bool: a pad cell is not green or is blocked for walking

    def crop(self, sl):
        return Measures(**{k: getattr(self, k)[sl] for k in self.__dataclass_fields__})


def measure(dem, slope_deg, hazard, cost: Cost, rules: Rules, roughness_layer=None):
    """The pad measures of every cell. `roughness_layer` is terrain's per-cell roughness (m) when
    layers.json lists it as a real layer; the pad roughness is then its maximum over the pad."""
    dem = np.asarray(dem, dtype=np.float64)
    h, w = dem.shape
    cell_m = cost.grid.cell_m
    offs = disk_offsets(rules.pad_radius_m, cell_m)
    n = len(offs)
    reach = int(math.floor(max(rules.pad_radius_m, rules.hazard_clearance_m) / cell_m + DIST_TOL_M))
    rows, cols = np.indices((h, w))
    outside = (rows < reach) | (cols < reach) | (rows > h - 1 - reach) | (cols > w - 1 - reach)

    rp = int(np.abs(offs).max())
    finite = np.isfinite(dem)
    ref = float(dem[finite].mean()) if finite.any() else 0.0        # heights near 0 keep the sums exact
    z = dem - ref
    bad = (hazard != HAZARD_GREEN) | cost.blocked
    pad = {
        "n": rp,
        "z": np.pad(z, rp, constant_values=np.nan),
        "s": np.pad(np.asarray(slope_deg, dtype=np.float64), rp, constant_values=np.nan),
        "bad": np.pad(bad, rp, constant_values=True),
    }
    if roughness_layer is not None:
        pad["rough"] = np.pad(np.asarray(roughness_layer, dtype=np.float64), rp, constant_values=np.nan)

    # Least-squares plane z = a + b x + c y over the pad (x east, y north, metres from the centre).
    X = offs[:, 1] * cell_m
    Y = -offs[:, 0] * cell_m
    P = np.linalg.pinv(np.c_[np.ones(n), X, Y])          # 3 x n
    a = np.zeros((h, w))
    b = np.zeros((h, w))
    c = np.zeros((h, w))
    nodata = np.zeros((h, w), dtype=bool)
    hazard_bad = np.zeros((h, w), dtype=bool)
    rough_max = np.full((h, w), -np.inf) if roughness_layer is not None else None
    for i, (dr, dc) in enumerate(offs):
        zi = _shifted(z, pad, "z", dr, dc)
        a += P[0, i] * zi
        b += P[1, i] * zi
        c += P[2, i] * zi
        nodata |= ~np.isfinite(zi) | ~np.isfinite(_shifted(z, pad, "s", dr, dc))
        hazard_bad |= _shifted(z, pad, "bad", dr, dc)
        if rough_max is not None:
            ri = _shifted(z, pad, "rough", dr, dc)
            nodata |= ~np.isfinite(ri)
            rough_max = np.fmax(rough_max, ri)
    sumsq = np.zeros((h, w))
    emax = np.full((h, w), -np.inf)
    emin = np.full((h, w), np.inf)
    for i, (dr, dc) in enumerate(offs):
        e = _shifted(z, pad, "z", dr, dc) - (a + b * X[i] + c * Y[i])
        sumsq += e * e
        emax = np.fmax(emax, e)
        emin = np.fmin(emin, e)
    nodata &= ~outside
    missing = nodata | outside
    tilt = np.degrees(np.arctan(np.hypot(b, c)))
    rms = np.sqrt(sumsq / n) if rough_max is None else rough_max
    rng = emax - emin
    for arr in (tilt, rms, rng):
        arr[missing] = np.nan

    r = cost.reasons
    near = r["red"] | r["slope"] | r["buffer"]
    if near.any():
        clearance = ndimage.distance_transform_edt(~near, sampling=cell_m)
    else:
        clearance = np.full((h, w), np.inf)
    return Measures(tilt, rms, rng, clearance, outside, nodata, hazard_bad & ~outside)


def failures(m: Measures, rules: Rules):
    """{code: bool array} for each failure rule (several can hold for one cell)."""
    with np.errstate(invalid="ignore"):
        return {
            OUTSIDE: m.outside,
            NODATA: m.nodata,
            HAZARD: m.hazard | (m.clearance_m < rules.hazard_clearance_m - DIST_TOL_M),
            STEEP: m.tilt_deg > rules.max_pad_slope_deg,
            RANGE: m.height_range_m > rules.max_height_range_m,
            ROUGH: m.roughness_m > rules.max_roughness_m,
        }


def marginal_reasons(m: Measures, rules: Rules):
    """{name: bool array}: the limits a cell is within marginal_pct of (whether or not it passes)."""
    f = rules.marginal_pct / 100.0
    with np.errstate(invalid="ignore"):
        return {
            "too_steep": m.tilt_deg > (1 - f) * rules.max_pad_slope_deg,
            "height_range": m.height_range_m > (1 - f) * rules.max_height_range_m,
            "too_rough": m.roughness_m > (1 - f) * rules.max_roughness_m,
            "hazard_or_clearance": m.clearance_m < (1 + f) * rules.hazard_clearance_m,
        }


def classify(m: Measures, rules: Rules):
    """The safety code of every cell (uint8), the most serious failure winning."""
    codes = np.full(m.outside.shape, SAFE, dtype=np.uint8)
    near_limit = np.zeros(m.outside.shape, dtype=bool)
    for v in marginal_reasons(m, rules).values():
        near_limit |= v
    codes[near_limit] = MARGINAL
    fails = failures(m, rules)
    for code in reversed(FAIL_ORDER):                   # the first in FAIL_ORDER is written last and wins
        codes[fails[code]] = code
    return codes


def warnings_grid(ti, offs_radius_m, cell_m, rules: Rules, shape):
    """Bit flags per cell from thermal inertia over the pad (0 everywhere when ti is None)."""
    out = np.zeros(shape, dtype=np.uint8)
    if ti is None:
        return out
    ti = np.asarray(ti, dtype=np.float64)
    offs = disk_offsets(offs_radius_m, cell_m)
    rp = int(np.abs(offs).max())
    pad = {"n": rp, "ti": np.pad(ti, rp, constant_values=np.inf)}       # beyond the grid: neither flag
    low = np.zeros(shape, dtype=bool)
    none = np.zeros(shape, dtype=bool)
    for dr, dc in offs:
        t = _shifted(ti, pad, "ti", dr, dc)
        low |= t < rules.ti_warn_below
        none |= np.isnan(t)
    out[low] |= WARN_LOW_TI
    out[none] |= WARN_NO_TI
    return out


# ---- nearest safe cell -------------------------------------------------------
def nearest_safe(codes, cell_m):
    """(rows, cols, distance_m): for every cell, the nearest cell with code 0 (safe) and the distance
    between the two cell centres. Ties go to the cell scipy's distance transform returns."""
    safe = codes == SAFE
    if not safe.any():
        raise LandingError(
            "no safe landing cell: every cell fails a [landing] rule in routing/config.toml "
            f"(codes present: {', '.join(CODE_NAMES[int(c)] for c in np.unique(codes))})"
        )
    dist, (rows, cols) = ndimage.distance_transform_edt(~safe, sampling=cell_m, return_indices=True)
    return rows, cols, dist


# ---- inputs ------------------------------------------------------------------
def _real_layer(layers, layer_id):
    for layer in layers.get("layers", []):
        if layer.get("id") == layer_id:
            return "FAKE" not in str(layer.get("source", ""))
    return False


def load_optional_layer(folder, layers, grid: Grid, layer_id, file_name):
    """(array or None, note): the raster `file_name` when layers.json lists `layer_id` as a real layer."""
    from pathlib import Path
    path = Path(folder) / file_name
    if not _real_layer(layers, layer_id):
        return None, f"not used: layers.json has no real '{layer_id}' layer"
    if not path.exists():
        return None, f"not used: {file_name} not found"
    arr, nodata = grid_mod._read_band(path, grid)
    out = arr.astype(np.float64)
    if nodata is not None and not np.isnan(nodata):
        out[arr == nodata] = np.nan
    out[~np.isfinite(out)] = np.nan
    return out, f"{file_name} (layer '{layer_id}' in layers.json)"


# ---- the map -----------------------------------------------------------------
@dataclass(frozen=True)
class LandingMap:
    """Safety codes, warnings and nearest safe cells on one grid (a window of the site).

    `grid` is the window's grid and `origin_m` its south-west corner in site metres. `measures`
    is present when the map was computed here, and absent when it was read back from files.
    """

    grid: Grid
    origin_m: tuple
    rules: Rules
    codes: np.ndarray
    warn: np.ndarray
    near_rows: np.ndarray
    near_cols: np.ndarray
    near_dist_m: np.ndarray
    measures: object = None

    def cell_of(self, x, y):
        """(row, col) holding (x, y) in site metres, or None outside the grid."""
        try:
            return self.grid.xy_to_cell(x - self.origin_m[0], y - self.origin_m[1])
        except GridError:
            return None

    def centre(self, row, col):
        cx, cy = self.grid.cell_centre(row, col)
        return (self.origin_m[0] + cx, self.origin_m[1] + cy)

    def reasons_at(self, cell):
        """Every failure that applies at a cell (the stored code only, without measures)."""
        code = int(self.codes[cell])
        if self.measures is None:
            return [] if code in ACCEPTED else [CODE_NAMES[code]]
        if code == SAFE:
            return []
        if code == MARGINAL:
            return [f"near_{k}" for k, v in marginal_reasons(self.measures.crop(np.s_[cell[0]:cell[0] + 1, cell[1]:cell[1] + 1]), self.rules).items() if v[0, 0]]
        sl = np.s_[cell[0]:cell[0] + 1, cell[1]:cell[1] + 1]
        fails = failures(self.measures.crop(sl), self.rules)
        return [CODE_NAMES[c] for c in FAIL_ORDER if fails[c][0, 0]]

    def landing_check(self, x, y):
        """Judge a clicked landing point.

        Returns {status, reasons, chosen_xy_m, moved_m} plus code details. A safe or marginal point
        stays where it is (moved_m 0). Any other point moves to the centre of the nearest safe cell,
        straight line, since a lander comes down from above; moved_m is measured from the click.
        A click outside the grid is not moved: status "outside", no chosen point.
        """
        cell = self.cell_of(x, y)
        if cell is None:
            return {"status": "outside", "reasons": ["outside the data"], "chosen_xy_m": None,
                    "moved_m": None, "code": None, "code_name": None, "cell": None, "chosen_cell": None,
                    "warnings": []}
        code = int(self.codes[cell])
        out = {"code": code, "code_name": CODE_NAMES[code], "cell": [int(cell[0]), int(cell[1])],
               "reasons": self.reasons_at(cell)}
        if code in ACCEPTED:
            chosen_cell, chosen, moved = cell, (float(x), float(y)), 0.0
            out["status"] = CODE_NAMES[code]
        else:
            chosen_cell = (int(self.near_rows[cell]), int(self.near_cols[cell]))
            chosen = self.centre(*chosen_cell)
            moved = math.hypot(chosen[0] - x, chosen[1] - y)
            out["status"] = "moved"
        bits = int(self.warn[chosen_cell])
        out.update({
            "chosen_xy_m": [chosen[0], chosen[1]],
            "moved_m": moved,
            "chosen_cell": [int(chosen_cell[0]), int(chosen_cell[1])],
            "warnings": [name for bit, name in WARN_NAMES.items() if bits & bit],
        })
        return out

    def nearest_safe_to(self, x, y):
        """The centre (x, y) and cell of the safe cell nearest to the point (x, y) inside the grid."""
        cell = self.cell_of(x, y)
        if cell is None:
            raise LandingError(f"({x:g}, {y:g}) m is outside the landing grid")
        rc = (int(self.near_rows[cell]), int(self.near_cols[cell]))
        return self.centre(*rc), rc


def assess(dem, slope_deg, hazard, cost: Cost, rules: Rules, ti=None, roughness_layer=None,
           box=None, origin_m=(0.0, 0.0)):
    """The landing map. Codes are computed on the whole grid; `box` (row0, row1, col0, col1) then
    cuts out a window, and the nearest safe cells are computed on that whole window."""
    m = measure(dem, slope_deg, hazard, cost, rules, roughness_layer)
    codes = classify(m, rules)
    warn = warnings_grid(ti, rules.pad_radius_m, cost.grid.cell_m, rules, codes.shape)
    grid = cost.grid
    if box is not None:
        r0, r1, c0, c1 = box
        sl = np.s_[r0:r1, c0:c1]
        codes, warn, m = codes[sl], warn[sl], m.crop(sl)
        grid = Grid(c1 - c0, r1 - r0, grid.cell_m)
    rows, cols, dist = nearest_safe(codes, grid.cell_m)
    return LandingMap(grid, tuple(float(v) for v in origin_m), rules, codes, warn, rows, cols, dist, m)


def assess_site(site, cost: Cost, cfg: Config, folder=None, box=None, origin_m=(0.0, 0.0)):
    """assess() on a loaded site, reading the optional thermal-inertia and roughness layers from
    `folder` when layers.json marks them real. Returns (LandingMap, notes)."""
    rules = Rules.from_config(cfg)
    ti, ti_note = (None, "not used: no input folder") if folder is None else load_optional_layer(
        folder, site.layers, site.grid, THERMAL_LAYER_ID, THERMAL_FILE)
    rough, rough_note = (None, "") if folder is None else load_optional_layer(
        folder, site.layers, site.grid, ROUGHNESS_LAYER_ID, ROUGHNESS_FILE)
    if rough is None:
        rough_note = "computed from dem.tif: RMS about the best-fit plane over the pad"
    lm = assess(site.dem, site.slope, site.hazard, cost, rules, ti, rough, box, origin_m)
    return lm, {"thermal_inertia": ti_note, "roughness": rough_note, "ti_checked": ti is not None}
