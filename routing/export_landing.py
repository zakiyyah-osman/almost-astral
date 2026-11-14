"""Export the landing-safety grids and the cost surface for the browser (DESIGN sections 14 and 15).

    python routing/export_landing.py                       # reads data/out, writes data/out/landing
    python routing/export_landing.py --in DIR              # reads DIR, writes DIR/landing
    python routing/export_landing.py --in DIR --out DIR2   # reads DIR, writes DIR2
    python routing/export_landing.py --config FILE         # another parameter file

The user clicks anywhere to choose a landing zone. The browser reads the safety code of that cell;
if it is not safe it moves the lander to the nearest safe cell (straight line). From the landing
spot the user clicks a destination and the browser runs its own Dijkstra on the exported cost
surface for three profiles (fastest, balanced, safest). Exported, for one window of the site
(landing.window_centre_m, landing.window_size_m), cut into square tiles of landing.tile_size_m:

    tiles/<ti>_<tj>/landing_safety.u8      safety code per cell (landing.py)
    tiles/<ti>_<tj>/landing_warn.u8        warning bits (thermal inertia)
    tiles/<ti>_<tj>/nearest_safe.u16       row, col of the nearest safe cell, in window rows/cols
    tiles/<ti>_<tj>/nearest_safe_dist.f32  distance to it in metres
    tiles/<ti>_<tj>/time_rate.f64          physical minutes per metre, -1 where blocked (cost.build)
    tiles/<ti>_<tj>/risk_rate.f64          risk-minutes per minute walked, 0 where blocked (cost.build)
    tiles/<ti>_<tj>/mask.u8                0 passable, else the blocked reason 1-5 (start.py)
    golden_cases.json                      reference paths and totals for the browser's tests
    manifest.json                          the grid, tiles, encodings, rules, budget and hashes

The safety codes and the cost are computed on the whole site grid, and the nearest safe cell on
the whole window, before tiling, so both are right across tile edges. `route` is the reference the
browser must reproduce; its search is MCP_Geometric exactly as search.py runs it.

Everything is built in memory first and the manifest is written last, so a failed run writes
nothing. There is no timestamp: the same inputs give the same bytes.
"""
import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from skimage.graph import MCP_Geometric

import config as config_mod
import cost as cost_mod
import grid as grid_mod
import landing as landing_mod
import outputs
import start as start_mod
import tour
from search import fully_connected

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "data" / "out"
LANDING_DIR = "landing"
FORMAT_VERSION = 1
MANIFEST_FILE = "manifest.json"
GOLDEN_FILE = "golden_cases.json"
TILES_DIR = "tiles"
BYTE_ORDER = "little"
OUTSIDE = "outside"
GOLDEN_LATTICE = (1 / 6, 1 / 2, 5 / 6)     # golden landing spots: nearest safe cells to a 3 x 3 lattice

# key -> (file name, numpy dtype, values per cell, unit / meaning)
GRIDS = {
    "landing_safety": ("landing_safety.u8", np.dtype("u1"), 1, "safety code (safety_codes)"),
    "landing_warn": ("landing_warn.u8", np.dtype("u1"), 1, "warning bits (warning_bits)"),
    "nearest_safe": ("nearest_safe.u16", np.dtype("<u2"), 2, "row, col of the nearest safe cell, window rows/cols"),
    "nearest_safe_dist": ("nearest_safe_dist.f32", np.dtype("<f4"), 1, "m, cell centre to cell centre"),
    "time_rate": ("time_rate.f64", np.dtype("<f8"), 1, "min/m, -1 where blocked"),
    "risk_rate": ("risk_rate.f64", np.dtype("<f8"), 1, "risk-min per min walked, 0 where blocked"),
    "mask": ("mask.u8", np.dtype("u1"), 1, "0 passable, else the blocked reason (mask_codes)"),
}
U16_MAX = np.iinfo(np.uint16).max

EDGE_RULE = {
    "neighbours": "8 (search.connectivity); a neighbour outside the window or with mask != 0 is never entered",
    "step_length_m": "straight: cell_m; diagonal: sqrt(cell_m * cell_m + cell_m * cell_m)",
    "planning_rate": "p = time_rate * (1 + w * risk_rate), float64, in that order",
    "step_cost": "L * (p_from + p_to) / 2, float64, in that order",
    "update": "relax a neighbour only when g + step_cost < its current g (strictly less)",
    "totals": (
        "along the found path, from the landing cell, summed in path order in float64: "
        "distance_m += step_m; walk_min += step_m * (time_rate_a + time_rate_b) / 2; "
        "risk_min += step_m * (time_rate_a * risk_rate_a + time_rate_b * risk_rate_b) / 2; "
        "where step_m is cell_m straight and cell_m * sqrt(2) diagonal"
    ),
    "sealed_gaps": "already closed in the mask (cost.py), so no corner check is needed",
    "see": "routing/docs/DESIGN.md section 15",
}


# ---- window and tiles --------------------------------------------------------
def window_box(cfg, grid: grid_mod.Grid):
    """(row0, row1, col0, col1) of the window on the site grid, half-open, and its south-west origin."""
    size = cfg.value(config_mod.WINDOW_SIZE)
    centre = cfg.value(config_mod.WINDOW_CENTRE)
    ex, ey = grid.extent_m
    if size == config_mod.FULL_WINDOW:
        if centre != config_mod.SITE_CENTRE:
            raise config_mod.ConfigError(
                f'{config_mod.WINDOW_CENTRE} must be "{config_mod.SITE_CENTRE}" while '
                f'{config_mod.WINDOW_SIZE} is "{config_mod.FULL_WINDOW}"'
            )
        return (0, grid.height, 0, grid.width), (0.0, 0.0)
    cx, cy = (ex / 2.0, ey / 2.0) if centre == config_mod.SITE_CENTRE else (float(centre[0]), float(centre[1]))
    w, h = (float(v) for v in size)
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    tol = 1e-9 * max(ex, ey)
    if x0 < -tol or y0 < -tol or x1 > ex + tol or y1 > ey + tol:
        raise config_mod.ConfigError(
            f"the landing window ({x0:g}, {y0:g}) to ({x1:g}, {y1:g}) m reaches outside the site grid "
            f"({ex:g} x {ey:g} m); change {config_mod.WINDOW_CENTRE} or {config_mod.WINDOW_SIZE}"
        )
    c = grid.cell_m
    col0 = max(int(math.floor(x0 / c + 1e-9)), 0)
    col1 = min(int(math.ceil(x1 / c - 1e-9)), grid.width)
    s0 = max(int(math.floor(y0 / c + 1e-9)), 0)
    s1 = min(int(math.ceil(y1 / c - 1e-9)), grid.height)
    if col1 - col0 < grid_mod.MIN_CELLS or s1 - s0 < grid_mod.MIN_CELLS:
        raise config_mod.ConfigError(f"the landing window is smaller than {grid_mod.MIN_CELLS} x {grid_mod.MIN_CELLS} cells")
    return (grid.height - s1, grid.height - s0, col0, col1), (col0 * c, s0 * c)


def tile_cells(cfg, cell_m):
    """Tile side in cells: landing.tile_size_m must be a whole number of cells."""
    size = cfg.value("landing.tile_size_m")
    n = size / cell_m
    if abs(n - round(n)) > 1e-9 or round(n) < 1:
        raise config_mod.ConfigError(
            f"landing.tile_size_m = {size:g} m is not a whole number of {cell_m:g} m cells"
        )
    return int(round(n))


def tile_layout(height, width, n):
    """[(ti, tj, row0, row1, col0, col1)] in window rows/cols, row 0 = north, tiles of n x n cells."""
    return [
        (ti, tj, r0, min(r0 + n, height), c0, min(c0 + n, width))
        for ti, r0 in enumerate(range(0, height, n))
        for tj, c0 in enumerate(range(0, width, n))
    ]


def crop_cost(model: cost_mod.Cost, box):
    """The cost on the window. Mask and risk were built on the whole grid first."""
    from dataclasses import replace
    r0, r1, c0, c1 = box
    sl = np.s_[r0:r1, c0:c1]
    return replace(
        model,
        grid=grid_mod.Grid(c1 - c0, r1 - r0, model.grid.cell_m),
        slope_deg=model.slope_deg[sl], blocked=model.blocked[sl],
        reasons={k: v[sl] for k, v in model.reasons.items()},
        time_rate=model.time_rate[sl],
        risk_parts={k: v[sl] for k, v in model.risk_parts.items()},
        risk_rate=model.risk_rate[sl],
    )


# ---- budget ------------------------------------------------------------------
def budget(cfg, eva_max_min=None):
    """The one-way over-budget rule (unchanged from the old reach export, DESIGN section 13.4).
    `eva_max_min` replaces the config value, for the over-budget golden case only."""
    eva = cfg.value("timeline.eva_max_min") if eva_max_min is None else eva_max_min
    reserve = cfg.value("timeline.reserve_pct")
    usable = eva * (1.0 - reserve / 100.0)
    ingress = cfg.value("timeline.ingress_min")
    stop = cfg.value("timeline.stop_min_default") if cfg.value("budget.destination_stop") else 0
    return {
        "eva_max_min": eva,
        "reserve_pct": reserve,
        "usable_min": round(usable, 6),
        "ingress_min": ingress,
        "stop_min": stop,
        "destination_stop": cfg.value("budget.destination_stop"),
        "walk_limit_min": round(usable - ingress - stop, 6),
        "rule": (
            "one way only: needed_min = walk_min + ingress_min + stop_min; over budget when needed_min > "
            "usable_min, i.e. when walk_min > walk_limit_min. No return walk is counted."
        ),
    }


# ---- the surface and the reference route -------------------------------------
class Surface:
    """The exported window, in memory: what the browser has after loading every tile."""

    def __init__(self, width, height, cell_m, origin_m, time_rate, risk_rate, mask, weights, connectivity, budget_):
        self.grid = grid_mod.Grid(width, height, cell_m)
        self.cell_m = cell_m
        self.origin = (float(origin_m[0]), float(origin_m[1]))
        self.time_rate, self.risk_rate, self.mask = time_rate, risk_rate, mask
        self.weights = dict(weights)
        self.connectivity = connectivity
        self.budget = budget_
        self._trees = {}

    def cell_of(self, x, y):
        col = math.floor((x - self.origin[0]) / self.cell_m)
        row = self.grid.height - 1 - math.floor((y - self.origin[1]) / self.cell_m)
        if 0 <= row < self.grid.height and 0 <= col < self.grid.width:
            return int(row), int(col)
        return None

    def centre(self, row, col):
        return (self.origin[0] + (col + 0.5) * self.cell_m, self.origin[1] + (self.grid.height - row - 0.5) * self.cell_m)

    def planning_rate(self, w):
        return np.where(self.mask != 0, cost_mod.BLOCKED, self.time_rate * (1.0 + w * self.risk_rate))

    def _tree(self, cell, profile):
        key = (cell, profile)
        if key not in self._trees:
            rate = self.planning_rate(self.weights[profile])
            mcp = MCP_Geometric(rate, fully_connected=fully_connected(self.connectivity),
                                sampling=(self.cell_m, self.cell_m))
            cum, _ = mcp.find_costs([cell])
            self._trees = {key: (mcp, cum)}                 # keep one tree: memory stays flat
        return self._trees[key]

    def totals(self, cells):
        """distance_m, walk_min, risk_min summed in path order (EDGE_RULE "totals")."""
        diag = self.cell_m * math.sqrt(2.0)
        d = t = r = 0.0
        for (ra, ca), (rb, cb) in zip(cells, cells[1:]):
            L = diag if (ra != rb and ca != cb) else self.cell_m
            ta, tb = float(self.time_rate[ra, ca]), float(self.time_rate[rb, cb])
            d += L
            t += L * (ta + tb) / 2.0
            r += L * (ta * float(self.risk_rate[ra, ca]) + tb * float(self.risk_rate[rb, cb])) / 2.0
        return d, t, r

    def route(self, landing_xy, dest_xy, profile, budget_=None):
        """One profile's path from the landing spot to the destination, as a GeoJSON Feature.

        Properties: profile, w, reachable, reason (0 or a mask code, 6 walled off, "outside", or
        "landing_blocked"), reason_text, distance_m, walk_min, risk_min, needed_min, over_budget,
        landing_cell, dest_cell and cells ([row, col] in window cells, landing first).
        """
        if profile not in self.weights:
            raise ValueError(f"unknown profile {profile!r}; the profiles are {', '.join(self.weights)}")
        b = self.budget if budget_ is None else budget_
        props = {"profile": profile, "w": self.weights[profile]}
        a, z = self.cell_of(*landing_xy), self.cell_of(*dest_xy)
        if a is None or z is None:
            return _feature(None, {**props, "reachable": False, "reason": OUTSIDE,
                                   "reason_text": ("the landing spot" if a is None else "the destination") + " is outside the exported window"})
        props.update({"landing_cell": list(a), "dest_cell": list(z)})
        if self.mask[a] != 0:
            return _feature(None, {**props, "reachable": False, "reason": "landing_blocked",
                                   "reason_text": "the landing cell cannot be walked on"})
        if self.mask[z] != 0:
            code = int(self.mask[z])
            return _feature(None, {**props, "reachable": False, "reason": code, "reason_text": MASK_TEXT[code]})
        mcp, cum = self._tree(a, profile)
        if not np.isfinite(cum[z]):
            return _feature(None, {**props, "reachable": False, "reason": start_mod.WALLED_OFF,
                                   "reason_text": MASK_TEXT[start_mod.WALLED_OFF]})
        cells = [tuple(int(v) for v in c) for c in mcp.traceback(z)]
        d, t, r = self.totals(cells)
        needed = t + b["ingress_min"] + b["stop_min"]
        coords = [list(self.centre(*c)) for c in cells]
        if len(coords) == 1:
            coords = coords * 2
        return _feature(coords, {
            **props, "reachable": True, "reason": 0, "reason_text": "reachable",
            "distance_m": d, "walk_min": t, "risk_min": r, "needed_min": needed,
            "over_budget": t > b["walk_limit_min"], "cells": [list(c) for c in cells],
        })


MASK_TEXT = {}          # filled from the config's limits by build(); words for mask codes and code 6


def _feature(coords, props):
    geometry = None if coords is None else {"type": "LineString", "coordinates": coords}
    return {"type": "Feature", "geometry": geometry, "properties": props}


# ---- golden cases ------------------------------------------------------------
def _result(feature):
    p = feature["properties"]
    keep = ("reachable", "reason", "distance_m", "walk_min", "risk_min", "needed_min", "over_budget", "cells")
    return {k: p[k] for k in keep if k in p}


def golden_cases(surface: Surface, lm: landing_mod.LandingMap, cfg):
    """About 10 landing/destination pairs between safe cells across the window, each for every
    profile: 8 ordinary pairs, one unreachable destination and one over budget (its own budget)."""
    H, W = lm.codes.shape
    spots = []
    for fy in GOLDEN_LATTICE:
        for fx in GOLDEN_LATTICE:
            r, c = min(int(fy * H), H - 1), min(int(fx * W), W - 1)
            cell = (int(lm.near_rows[r, c]), int(lm.near_cols[r, c]))
            if cell not in spots:
                spots.append(cell)
    if len(spots) < 2:
        raise landing_mod.LandingError("golden cases need at least two distinct safe cells")
    n = len(spots)
    pairs = [(spots[k], spots[(k + n // 2) % n]) for k in range(min(n, 8))]
    cases = []

    def add(cid, a, z, note, budget_=None):
        case = {"id": cid, "note": note,
                "landing_xy_m": list(surface.centre(*a)), "landing_cell": list(a),
                "dest_xy_m": list(surface.centre(*z)), "dest_cell": list(z)}
        if budget_ is not None:
            case["budget"] = budget_
        case["results"] = {p: _result(surface.route(case["landing_xy_m"], case["dest_xy_m"], p, budget_))
                           for p in surface.weights}
        cases.append(case)
        return case

    for k, (a, z) in enumerate(pairs):
        add(f"pair{k + 1}", a, z, "between two safe cells")

    # Unreachable: a passable cell walled off from the first landing spot, or else a blocked cell.
    a = spots[0]
    _, cum = surface._tree(a, "fastest")
    walled = np.argwhere((surface.mask == 0) & ~np.isfinite(cum))
    blocked = np.argwhere(surface.mask != 0)
    skipped = []
    if len(walled):
        add("unreachable", a, tuple(int(v) for v in walled[0]), "unreachable: passable but walled off (reason 6)")
    elif len(blocked):
        add("unreachable", a, tuple(int(v) for v in blocked[0]), "unreachable: blocked destination")
    else:
        skipped.append("unreachable: every cell of the window can be reached, so there is no such case")

    # Over budget: the longest reachable ordinary pair, with an EVA limit that leaves about half its walk.
    reachable = [c for c in cases[:len(pairs)] if all(r["reachable"] for r in c["results"].values())
                 and c["landing_cell"] != c["dest_cell"]]
    if not reachable:
        skipped.append("over_budget: no reachable pair to build it from")
        return cases, skipped
    longest = max(reachable, key=lambda c: c["results"]["fastest"]["walk_min"])
    walk = min(r["walk_min"] for r in longest["results"].values())
    base = budget(cfg)
    reserve = base["reserve_pct"] / 100.0
    eva = math.ceil((walk / 2 + base["ingress_min"] + base["stop_min"]) / (1.0 - reserve))
    small = budget(cfg, eva_max_min=eva)
    small["note"] = "test budget for this case only (same rule, smaller eva_max_min)"
    over = add("over_budget", tuple(longest["landing_cell"]), tuple(longest["dest_cell"]),
               "over budget under its own test budget", small)
    assert all(r["over_budget"] for r in over["results"].values())
    return cases, skipped


# ---- run ---------------------------------------------------------------------
@dataclass(frozen=True)
class ExportResult:
    files: dict             # path relative to the landing folder -> bytes, manifest last
    manifest: dict
    warnings: tuple

    @property
    def total_bytes(self):
        return sum(len(v) for v in self.files.values())


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config_sha256(cfg):
    text = json.dumps(cfg.raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(in_dir, config_path=None):
    """Compute every landing file from the inputs in `in_dir`. Writes nothing."""
    cfg = config_mod.load_config(config_path)
    site = grid_mod.load_site(in_dir)
    params = cost_mod.Params.from_config(cfg)
    full = cost_mod.build(site.dem, site.hazard, site.slope, site.grid, params)
    box, origin = window_box(cfg, site.grid)
    model = crop_cost(full, box)
    win = model.grid
    if max(win.width, win.height) - 1 > U16_MAX:
        raise config_mod.ConfigError(f"the window is {win.width} x {win.height} cells; nearest_safe.u16 holds at most {U16_MAX + 1}")
    lm, notes = landing_mod.assess_site(site, full, cfg, in_dir, box, origin)
    MASK_TEXT.clear()
    MASK_TEXT.update({code: start_mod.reason_text(code, params) for code in start_mod.REASON_NAMES})

    weights = {name: float(cfg.value(key)) for name, key in tour.PROFILES}
    surface = Surface(win.width, win.height, win.cell_m, origin, model.time_rate, model.risk_rate,
                      start_mod.block_codes(model), weights, cfg.value("search.connectivity"), budget(cfg))
    arrays = {
        "landing_safety": lm.codes,
        "landing_warn": lm.warn,
        "nearest_safe": np.stack([lm.near_rows, lm.near_cols], axis=-1),
        "nearest_safe_dist": lm.near_dist_m,
        "time_rate": surface.time_rate,
        "risk_rate": surface.risk_rate,
        "mask": surface.mask,
    }
    n = tile_cells(cfg, win.cell_m)
    files, tiles = {}, []
    for ti, tj, r0, r1, c0, c1 in tile_layout(win.height, win.width, n):
        folder = f"{TILES_DIR}/{ti}_{tj}"
        paths = {}
        for key, (fname, dtype, _, _) in GRIDS.items():
            path = f"{folder}/{fname}"
            files[path] = np.ascontiguousarray(arrays[key][r0:r1, c0:c1]).astype(dtype).tobytes(order="C")
            paths[key] = path
        tiles.append({
            "index": [ti, tj], "row0": r0, "col0": c0, "shape": [r1 - r0, c1 - c0],
            "origin_m": [origin[0] + c0 * win.cell_m, origin[1] + (win.height - r1) * win.cell_m],
            "files": paths,
        })
    cases, skipped = golden_cases(surface, lm, cfg)
    files[GOLDEN_FILE] = outputs.dumps({
        "format_version": FORMAT_VERSION,
        "note": ("Reference paths from routing/export_landing.py (skimage MCP_Geometric on the exported surface). "
                 "A browser Dijkstra that follows manifest.json search.edge_rule must give the same cells, and "
                 "the same totals within 1e-9 relative."),
        "grid": {"width": win.width, "height": win.height, "cell_m": win.cell_m, "origin_m": list(origin)},
        "budget": surface.budget,
        "profiles": {k: {"w": w} for k, w in weights.items()},
        "cases": cases,
        "skipped": skipped,
    }).encode("utf-8")

    warnings = [f"golden case skipped: {s}" for s in skipped]
    if not notes["ti_checked"]:
        warnings.append(f"thermal inertia {notes['thermal_inertia']}; landing_warn.u8 is all zero")
    manifest = build_manifest(cfg, site, win, box, origin, n, tiles, lm, notes, weights, surface.budget,
                              in_dir, files, warnings)
    files[MANIFEST_FILE] = outputs.dumps(manifest).encode("utf-8")
    return ExportResult(files, manifest, tuple(warnings))


ROUGHNESS_NOTE = (
    "Scale caveat: terrain's roughness (terrain/thresholds.toml [roughness], terrain/hazard_map.py) is the RMS "
    "about the local mean in a 5 x 5 cell (25 m) window on the 5 m grid; the older terrain/hazards pipeline "
    "(terrain/config/hazards.yaml) used a 5 m window on 1 m data. Ours is the RMS about one best-fit plane over "
    "the whole pad (50 m across) on the 5 m grid, so the numbers are not directly comparable. The limit is a "
    "team assumption pending Nahla."
)
HEIGHT_RANGE_NOTE = (
    "landing.max_height_range_m (1.0 m by default) is a team assumption, not a sourced lander clearance: the "
    "highest minus the lowest pad cell after removing the best-fit plane."
)


def build_manifest(cfg, site, win, box, origin, n, tiles, lm, notes, weights, budget_, in_dir, files, warnings):
    rules = lm.rules
    inputs = {name: file_sha256(Path(in_dir) / name) for name in (grid_mod.DEM_FILE, grid_mod.HAZARD_FILE)}
    if notes["ti_checked"]:
        inputs[landing_mod.THERMAL_FILE] = file_sha256(Path(in_dir) / landing_mod.THERMAL_FILE)
    counts = {landing_mod.CODE_NAMES[int(c)]: int(k) for c, k in zip(*np.unique(lm.codes, return_counts=True))}
    return {
        "format_version": FORMAT_VERSION,
        "generated_by": "routing/export_landing.py",
        "site": site.layers.get("site", {}).get("name"),
        "fake": outputs.inputs_fake(site.layers),
        "fake_rule": "true while any layer source in layers.json contains FAKE (same as plan.json inputs_fake)",
        "grid": {
            "width": win.width, "height": win.height, "cell_m": win.cell_m,
            "origin_m": [origin[0], origin[1]],
            "extent_m": [win.width * win.cell_m, win.height * win.cell_m],
            "row0": "north edge",
            "window": {
                "centre_m": cfg.value(config_mod.WINDOW_CENTRE), "size_m": cfg.value(config_mod.WINDOW_SIZE),
                "site_rows": [box[0], box[1]], "site_cols": [box[2], box[3]],
            },
            "site_grid": {"width": site.grid.width, "height": site.grid.height, "cell_m": site.grid.cell_m},
        },
        "layout": {
            "order": "row-major inside each tile, row 0 = north edge, index = row * tile_width + col",
            "header": "none: raw values only",
            "window_cell_of_point": "col = floor((x - origin_x) / cell_m), row = height - 1 - floor((y - origin_y) / cell_m)",
            "window_cell_centre": "x = origin_x + (col + 0.5) * cell_m, y = origin_y + (height - row - 0.5) * cell_m",
            "tile_of_cell": "the tile whose row0 <= row < row0 + shape[0] and col0 <= col < col0 + shape[1]",
            "nearest_safe": "two uint16 per cell: [2 * i] = row, [2 * i + 1] = col, in WINDOW rows/cols (not tile rows/cols)",
            "search_bound": "paths never leave the window: the browser only searches inside it",
        },
        "byte_order": BYTE_ORDER,
        "grids": {k: {"file": f, "dtype": str(d.name), "values_per_cell": v, "meaning": m}
                  for k, (f, d, v, m) in GRIDS.items()},
        "tile_size_m": cfg.value("landing.tile_size_m"),
        "tile_cells": n,
        "tiles": tiles,
        "safety_codes": [{"code": c, "name": landing_mod.CODE_NAMES[c], "text": landing_mod.code_text(c, rules)}
                         for c in sorted(landing_mod.CODE_NAMES)],
        "safety_order": "the lowest failure code wins: " + " > ".join(landing_mod.CODE_NAMES[c] for c in landing_mod.FAIL_ORDER),
        "safety_counts": counts,
        "warning_bits": [{"bit": b, "name": nme} for b, nme in landing_mod.WARN_NAMES.items()],
        "landing_rule": (
            "a click on a safe (0) or marginal (1) cell stays where it is; any other click moves to the centre of "
            "nearest_safe, a straight-line move (the lander comes down from above)"
        ),
        "thresholds": {k: cfg.assumptions()[key] for k, key in landing_mod.Rules.KEYS.items()},
        "roughness_source": notes["roughness"],
        "roughness_note": ROUGHNESS_NOTE,
        "height_range_note": HEIGHT_RANGE_NOTE,
        "thermal_inertia": {"checked": notes["ti_checked"], "source": notes["thermal_inertia"]},
        "mask_codes": [{"code": c, "name": start_mod.REASON_NAMES[c], "text": MASK_TEXT[c]}
                       for c in sorted(start_mod.REASON_NAMES)],
        "mask_note": "codes 1-5 are stored; 0 reachable and 6 walled off are results of a search, never stored",
        "profiles": {name: {"w": w} for name, w in weights.items()},
        "search": {"connectivity": cfg.value("search.connectivity"), "edge_rule": EDGE_RULE},
        "budget": budget_,
        "golden_cases": GOLDEN_FILE,
        "config_sha256": config_sha256(cfg),
        "inputs_sha256": inputs,
        "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()},
        "warnings": list(warnings),
    }


# ---- reading back ------------------------------------------------------------
class LandingFolderError(ValueError):
    """The landing folder is missing a file or does not match its manifest."""


@dataclass(frozen=True)
class Landing:
    """An exported landing folder read back and stitched: what the browser has."""

    manifest: dict
    map: landing_mod.LandingMap
    surface: Surface

    @classmethod
    def load(cls, folder, cfg=None):
        folder = Path(folder)
        try:
            m = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise LandingFolderError(f"{MANIFEST_FILE} not found in {folder}") from None
        if m.get("format_version") != FORMAT_VERSION or m.get("byte_order") != BYTE_ORDER:
            raise LandingFolderError(f"{MANIFEST_FILE}: unsupported format_version or byte_order")
        g = m["grid"]
        H, W = g["height"], g["width"]
        full = {}
        for key, (_, dtype, per, _) in GRIDS.items():
            shape = (H, W, per) if per > 1 else (H, W)
            full[key] = np.zeros(shape, dtype=dtype.newbyteorder("=") if dtype.itemsize > 1 else dtype)
        for t in m["tiles"]:
            h, w = t["shape"]
            for key, path in t["files"].items():
                dtype, per = GRIDS[key][1], GRIDS[key][2]
                p = folder / path
                if not p.exists():
                    raise LandingFolderError(f"{path} not found in {folder}")
                arr = np.fromfile(p, dtype=dtype)
                if arr.size != h * w * per:
                    raise LandingFolderError(f"{path} has {arr.size} values, the manifest says {h} x {w} x {per}")
                arr = arr.reshape((h, w, per) if per > 1 else (h, w))
                full[key][t["row0"]:t["row0"] + h, t["col0"]:t["col0"] + w] = arr
        th = {k: v["value"] for k, v in m["thresholds"].items()}
        rules = landing_mod.Rules(**{k: float(v) for k, v in th.items()})
        grid = grid_mod.Grid(W, H, g["cell_m"])
        lmap = landing_mod.LandingMap(
            grid, tuple(g["origin_m"]), rules, full["landing_safety"], full["landing_warn"],
            full["nearest_safe"][..., 0].astype(int), full["nearest_safe"][..., 1].astype(int),
            full["nearest_safe_dist"].astype(np.float64),
        )
        MASK_TEXT.update({c["code"]: c["text"] for c in m["mask_codes"]})
        weights = {k: v["w"] for k, v in m["profiles"].items()}
        surface = Surface(W, H, g["cell_m"], g["origin_m"], full["time_rate"].astype(np.float64),
                          full["risk_rate"].astype(np.float64), full["mask"], weights,
                          m["search"]["connectivity"], m["budget"])
        return cls(m, lmap, surface)

    def landing_check(self, x, y):
        return self.map.landing_check(x, y)

    def route(self, landing_xy, dest_xy, profile, budget_=None):
        return self.surface.route(landing_xy, dest_xy, profile, budget_)


_LOADED = {}


def _default(folder):
    folder = Path(DEFAULT_IN / LANDING_DIR if folder is None else folder).resolve()
    if folder not in _LOADED:
        _LOADED.clear()
        _LOADED[folder] = Landing.load(folder)
    return _LOADED[folder]


def landing_check(x, y, folder=None):
    """Reference: judge a clicked landing point on an exported folder (default data/out/landing)."""
    return _default(folder).landing_check(x, y)


def route(landing_xy, dest_xy, profile, folder=None, budget_=None):
    """Reference: the path the browser must find, on an exported folder (default data/out/landing)."""
    return _default(folder).route(landing_xy, dest_xy, profile, budget_)


# ---- command line ------------------------------------------------------------
def parse_args(argv):
    p = argparse.ArgumentParser(description="Export landing-safety grids and the cost surface for the browser.")
    p.add_argument("--in", dest="in_dir", type=Path, default=DEFAULT_IN,
                   help="folder the inputs are read from (default: data/out)")
    p.add_argument("--out", dest="out_dir", type=Path, default=None,
                   help="folder the files are written to (default: <--in>/landing)")
    p.add_argument("--config", dest="config", type=Path, default=None,
                   help="parameter file (default: routing/config.toml)")
    return p.parse_args(argv)


def summary_lines(result: ExportResult):
    m = result.manifest
    g = m["grid"]
    lines = [
        f"{m['site']}: window {g['width']} x {g['height']} cells of {g['cell_m']:g} m, origin {g['origin_m']}, "
        f"{len(m['tiles'])} tile(s) of up to {m['tile_cells']} cells",
        "  safety: " + ", ".join(f"{k} {v}" for k, v in m["safety_counts"].items()),
        f"  total: {result.total_bytes:,} bytes ({result.total_bytes / 1e6:.2f} MB) in {len(result.files)} files",
    ]
    for w in result.warnings:
        lines.append(f"WARNING {w}")
    if m["fake"]:
        lines.append("NOTE the inputs still contain fake data")
    return lines


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out_dir = args.out_dir if args.out_dir is not None else args.in_dir / LANDING_DIR
    try:
        result = run(args.in_dir, args.config)
    except config_mod.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    outputs.write_files(out_dir, result.files)
    print(f"Wrote {len(result.files)} files to {out_dir}")
    for line in summary_lines(result):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
