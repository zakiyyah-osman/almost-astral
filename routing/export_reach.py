"""Reach grids: the best path from each start to every cell, for each profile (DESIGN section 13).

    python routing/export_reach.py                       # reads data/out, writes data/out/reach
    python routing/export_reach.py --in DIR              # reads DIR, writes DIR/reach
    python routing/export_reach.py --in DIR --out DIR2   # reads DIR, writes DIR2
    python routing/export_reach.py --config FILE         # another parameter file

The user picks a start (a landing spot, L1 to L3 for now), clicks a destination on the map and the
app shows three paths from that start to it (fastest, balanced, safest), each with distance,
walking time and risk. One search per profile and start (the [starts.<id>] of config.toml) gives
the answer for every cell at once. Per start, in a folder named by its id:

    <id>/{profile}_time.f32   walking minutes from the start along that profile's best path
    <id>/{profile}_dist.f32   metres along that path
    <id>/{profile}_risk.f32   risk-minutes along that path
    <id>/{profile}_dir.u8     the step from each cell back toward the start (0 = start or no path)
    <id>/reason.u8            0 reachable, otherwise why not (6, walled off, depends on the start)

and one reach.json next to the folders: the grid, the encodings, the list of starts (id, xy_m, cell,
default flag, warnings, file paths), the profile weights, the budget rule and the hashes. The front
end reads the landing spots from that list instead of computing them.

The cost model and the search are cost.py and search.py, unchanged. The direction grid is the
search's own traceback, so following it gives exactly the path search.Tree.path_to returns.
`trace` is the reference for the front end: DESIGN section 13 describes it step by step.

Everything is built in memory first, so a run that fails writes nothing. The manifest is
written last. There is no timestamp: the same inputs give the same bytes. After writing, the
files of the old one-start layout and the folders of starts that are no longer in the config are
deleted (only files with the names of this export's grids), and listed.
"""
import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

import config as config_mod
import cost as cost_mod
import grid as grid_mod
import outputs
import start as start_mod
import tour
from search import Searcher

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "data" / "out"
REACH_DIR = "reach"

FORMAT_VERSION = 2
MANIFEST_FILE = "reach.json"
REASON_FILE = "reason.u8"          # inside each start's folder
BYTE_ORDER = "little"
DTYPES = {"f32": np.dtype("<f4"), "u8": np.dtype("u1")}
# Per-profile grids: key -> (file suffix, dtype key, unit)
PROFILE_GRIDS = {
    "time": ("time.f32", "f32", "min"),
    "dist": ("dist.f32", "f32", "m"),
    "risk": ("risk.f32", "f32", "risk-min"),
    "dir": ("dir.u8", "u8", "direction code"),
}
# Direction code -> (name, row change, column change): the step from a cell to the previous
# cell on its best path, toward the start. Row 0 is the north edge, so north is row - 1.
DIRECTIONS = {
    1: ("N", -1, 0),
    2: ("NE", -1, 1),
    3: ("E", 0, 1),
    4: ("SE", 1, 1),
    5: ("S", 1, 0),
    6: ("SW", 1, -1),
    7: ("W", 0, -1),
    8: ("NW", -1, -1),
}
NO_STEP = 0                 # the start cell itself, or a cell with no path
OUTSIDE = "outside"         # trace(): the point is outside the exported area


def _profile_file(profile, key):
    return f"{profile}_{PROFILE_GRIDS[key][0]}"


# ---- area and resolution -----------------------------------------------------
def downsample(dem, hazard, grid: grid_mod.Grid, factor):
    """(dem, hazard, grid) at `factor` site cells per export cell.

    The DEM is the block mean (a block with any no-data cell has no data); the hazard is the
    block's worst class, so a red cell is never lost (FR-16). Rows left over at the north edge
    and columns left over at the east edge are dropped, so the south-west origin stays (0, 0).
    """
    if factor == 1:
        return dem, hazard, grid
    h, w = grid.height // factor, grid.width // factor
    if h < grid_mod.MIN_CELLS or w < grid_mod.MIN_CELLS:
        raise config_mod.ConfigError(
            f"reach.downsample = {factor} leaves a {w} x {h} grid; at least "
            f"{grid_mod.MIN_CELLS} x {grid_mod.MIN_CELLS} cells are needed"
        )
    top = grid.height - h * factor
    blocks = lambda a: a[top:, : w * factor].reshape(h, factor, w, factor)      # noqa: E731
    coarse_dem = blocks(np.asarray(dem, dtype=np.float64)).mean(axis=(1, 3))
    coarse_hazard = blocks(hazard).max(axis=(1, 3)).astype(hazard.dtype)
    return coarse_dem, coarse_hazard, grid_mod.Grid(w, h, grid.cell_m * factor)


def crop_box(spec, grid: grid_mod.Grid):
    """(row0, row1, col0, col1), half-open, and the south-west origin (x, y) in metres.

    "full" is the whole grid. [x0, y0, x1, y1] is snapped outward to whole cells.
    """
    if spec == config_mod.CROP_FULL:
        return (0, grid.height, 0, grid.width), (0.0, 0.0)
    x0, y0, x1, y1 = (float(v) for v in spec)
    ex, ey = grid.extent_m
    tol = 1e-9 * max(ex, ey)
    if x1 > ex + tol or y1 > ey + tol:
        raise config_mod.ConfigError(
            f"reach.crop_m {list(spec)} reaches outside the site grid ({ex:g} x {ey:g} m)"
        )
    c = grid.cell_m
    col0 = int(math.floor(x0 / c + 1e-9))
    col1 = min(int(math.ceil(x1 / c - 1e-9)), grid.width)
    south0 = int(math.floor(y0 / c + 1e-9))                 # rows counted from the south edge
    south1 = min(int(math.ceil(y1 / c - 1e-9)), grid.height)
    if col1 - col0 < grid_mod.MIN_CELLS or south1 - south0 < grid_mod.MIN_CELLS:
        raise config_mod.ConfigError(
            f"reach.crop_m {list(spec)} is smaller than {grid_mod.MIN_CELLS} x {grid_mod.MIN_CELLS} "
            f"cells of {c:g} m"
        )
    row0, row1 = grid.height - south1, grid.height - south0
    return (row0, row1, col0, col1), (col0 * c, south0 * c)


def crop_cost(model: cost_mod.Cost, box):
    """The cost restricted to the box. The mask and risk were built on the whole grid first, so
    the cliff buffer and the near-red term see cells just outside the box."""
    row0, row1, col0, col1 = box
    sl = np.s_[row0:row1, col0:col1]
    return replace(
        model,
        grid=grid_mod.Grid(col1 - col0, row1 - row0, model.grid.cell_m),
        slope_deg=model.slope_deg[sl],
        blocked=model.blocked[sl],
        reasons={k: v[sl] for k, v in model.reasons.items()},
        time_rate=model.time_rate[sl],
        risk_parts={k: v[sl] for k, v in model.risk_parts.items()},
        risk_rate=model.risk_rate[sl],
    )


# ---- the grids ---------------------------------------------------------------
def direction_codes(tree):
    """The search's traceback as direction codes (uint8): 0 at the start and where unreachable."""
    lookup = {(dr, dc): code for code, (_, dr, dc) in DIRECTIONS.items()}
    # offsets[i] is the move from the previous cell into this one; the code points back along it.
    table = np.array([lookup[(-int(dr), -int(dc))] for dr, dc in tree.offsets], dtype=np.uint8)
    steps = tree.steps
    out = np.zeros(steps.shape, dtype=np.uint8)
    has = steps >= 0
    out[has] = table[steps[has]]
    return out


def accumulate(model: cost_mod.Cost, tree):
    """(time, dist, risk) along the best path to every cell, NaN where unreachable.

    Each cell adds one step to its predecessor's totals, with the edge formula of search.py:
    a step of length L between cells a and b adds L x (rate_a + rate_b) / 2. Predecessors have
    a strictly lower planning cost, so visiting cells by rising planning cost fills every
    predecessor first.
    """
    h, w = model.grid.shape
    cell_m = model.grid.cell_m
    pc = tree.planning_cost.ravel()
    steps = tree.steps.ravel()
    idx = np.flatnonzero(np.isfinite(pc) & (steps >= 0))             # reachable, not the start
    dr = tree.offsets[steps[idx], 0]
    dc = tree.offsets[steps[idx], 1]
    rows, cols = np.divmod(idx, w)
    pred = (rows - dr) * w + (cols - dc)
    length = cell_m * np.where((dr != 0) & (dc != 0), math.sqrt(2.0), 1.0)
    tr = model.time_rate.ravel()
    rk = (model.time_rate * model.risk_rate).ravel()
    e_time = length * (tr[idx] + tr[pred]) / 2.0
    e_risk = length * (rk[idx] + rk[pred]) / 2.0

    time = np.full(h * w, np.nan)
    dist = np.full(h * w, np.nan)
    risk = np.full(h * w, np.nan)
    s = tree.start[0] * w + tree.start[1]
    time[s] = dist[s] = risk[s] = 0.0
    order = np.argsort(pc[idx], kind="stable")
    t, d, r = time.tolist(), dist.tolist(), risk.tolist()
    for i, p, et, el, er in zip(
        idx[order].tolist(), pred[order].tolist(),
        e_time[order].tolist(), length[order].tolist(), e_risk[order].tolist(),
    ):
        t[i] = t[p] + et
        d[i] = d[p] + el
        r[i] = r[p] + er
    shape = (h, w)
    return np.array(t).reshape(shape), np.array(d).reshape(shape), np.array(r).reshape(shape)


def reason_grid(model: cost_mod.Cost, reachable):
    """Reason codes: why each cell has no path from one start (0 where it has one).

    Code 6 (walled off) depends on the start: a cell that is passable but cut off from this start
    by blocked cells may be reachable from another start.
    """
    codes = start_mod.block_codes(model)
    codes[(codes == start_mod.REACHABLE) & ~reachable] = start_mod.WALLED_OFF
    return codes


# ---- manifest ----------------------------------------------------------------
def budget(cfg):
    """The over-budget rule, for a one-way path from the start to the destination. A destination
    is over budget when the walk there, getting inside (ingress) and one stop (unless
    reach.destination_stop is false) take longer than the usable EVA time. No return walk is
    counted: the user only gets the path from the start to the destination."""
    eva = cfg.value("timeline.eva_max_min")
    reserve = cfg.value("timeline.reserve_pct")
    usable = eva * (1.0 - reserve / 100.0)
    ingress = cfg.value("timeline.ingress_min")
    stop = cfg.value("timeline.stop_min_default") if cfg.value("reach.destination_stop") else 0
    return {
        "eva_max_min": eva,
        "reserve_pct": reserve,
        "usable_min": round(usable, 6),
        "ingress_min": ingress,
        "stop_min": stop,
        "destination_stop": cfg.value("reach.destination_stop"),
        "walk_limit_min": round(usable - ingress - stop, 6),
        "rule": (
            "one way only: needed_min = time + ingress_min + stop_min; over budget when needed_min > "
            "usable_min, i.e. when time > walk_limit_min. No return walk is counted."
        ),
    }


def config_sha256(cfg):
    text = json.dumps(cfg.raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


file_sha256 = start_mod.file_sha256


@dataclass(frozen=True)
class ExportResult:
    files: dict             # path relative to the reach folder ("L1/fastest_time.f32") -> bytes, manifest last
    manifest: dict
    warnings: tuple         # every warning: the data hashes and each start's own

    @property
    def total_bytes(self):
        return sum(len(v) for v in self.files.values())


def run(in_dir, config_path=None):
    """Compute every reach file, for every start, from the inputs in `in_dir`. Writes nothing."""
    cfg = config_mod.load_config(config_path)
    site = grid_mod.load_site(in_dir)
    factor = cfg.value("reach.downsample")
    dem, hazard, coarse = downsample(site.dem, site.hazard, site.grid, factor)
    slope = site.slope if factor == 1 else grid_mod.slope_deg(dem, coarse.cell_m)
    full = cost_mod.build(dem, hazard, slope, coarse, cost_mod.Params.from_config(cfg))
    box, origin = crop_box(cfg.value("reach.crop_m"), coarse)
    model = crop_cost(full, box)
    hazard = hazard[box[0]:box[1], box[2]:box[3]]
    export = model.grid

    # Every start is checked before anything is searched; the first bad one is named in the error.
    where = "the exported area (reach.crop_m, reach.downsample)"
    infos = start_mod.validate_starts(cfg, model, hazard, origin, where)
    default_id = cfg.default_start_id()

    connectivity = cfg.value("search.connectivity")
    weights = {name: float(cfg.value(key)) for name, key in tour.PROFILES}
    searchers = {name: Searcher(model, w, connectivity) for name, w in weights.items()}
    files, starts_out = {}, []
    for sid, info in infos.items():
        sprofiles, reachable = {}, None
        for name in weights:
            tree = searchers[name].tree(info.cell)
            time, dist, risk = accumulate(model, tree)
            grids = {"time": time, "dist": dist, "risk": risk, "dir": direction_codes(tree)}
            paths = {}
            for gkey, arr in grids.items():
                paths[gkey] = _path(sid, _profile_file(name, gkey))
                files[paths[gkey]] = arr.astype(DTYPES[PROFILE_GRIDS[gkey][1]]).tobytes(order="C")
            here = np.isfinite(time)
            reachable = here if reachable is None else reachable
            assert np.array_equal(here, reachable), "profiles share one hard mask, so one reachable set"
            sprofiles[name] = {"files": paths, "reachable_cells": int(here.sum())}
        reason_path = _path(sid, REASON_FILE)
        files[reason_path] = reason_grid(model, reachable).tobytes(order="C")
        starts_out.append({
            "id": sid,
            "xy_m": [info.xy[0], info.xy[1]],
            "cell": [int(info.cell[0]), int(info.cell[1])],
            "default": sid == default_id,
            "temporary": True,
            "folder": sid,
            "reason_file": reason_path,
            "profiles": sprofiles,
            "warnings": list(info.warnings),
        })

    warnings = [*start_mod.staleness_warnings(cfg, in_dir), *(w for s in starts_out for w in s["warnings"])]
    manifest = build_manifest(cfg, site, export, factor, box, origin, starts_out, weights, default_id,
                              warnings, in_dir, files)
    files[MANIFEST_FILE] = outputs.dumps(manifest).encode("utf-8")
    return ExportResult(files, manifest, tuple(warnings))


def _path(start_id, name):
    return f"{start_id}/{name}"


def build_manifest(cfg, site, export, factor, box, origin, starts_out, weights, default_id, warnings,
                   in_dir, files):
    params = cost_mod.Params.from_config(cfg)
    return {
        "format_version": FORMAT_VERSION,
        "generated_by": "routing/export_reach.py",
        "site": site.layers.get("site", {}).get("name"),
        "fake": outputs.inputs_fake(site.layers),
        "fake_rule": "true while any layer source in layers.json contains FAKE (same as plan.json inputs_fake)",
        "grid": {
            "width": export.width,
            "height": export.height,
            "cell_m": export.cell_m,
            "origin_m": [origin[0], origin[1]],
            "extent_m": [export.width * export.cell_m, export.height * export.cell_m],
            "crop_m": cfg.value("reach.crop_m"),
            "crop_cells": {"row0": box[0], "row1": box[1], "col0": box[2], "col1": box[3]},
            "downsample": factor,
            "site_grid": {"width": site.grid.width, "height": site.grid.height, "cell_m": site.grid.cell_m},
        },
        "layout": {
            "folders": "one folder per start, named by its id, next to this file: <id>/<profile>_<grid> and <id>/reason.u8",
            "order": "row-major, row 0 = north edge, index = row * width + col",
            "header": "none: raw values only",
            "cell_of_point": "col = floor((x - origin_x) / cell_m), row = height - 1 - floor((y - origin_y) / cell_m)",
            "cell_centre": "x = origin_x + (col + 0.5) * cell_m, y = origin_y + (height - row - 0.5) * cell_m",
        },
        "byte_order": BYTE_ORDER,
        "dtypes": {"f32": "float32", "u8": "uint8"},
        "nodata": "NaN in the f32 grids wherever the start's reason != 0",
        "units": {k: v[2] for k, v in PROFILE_GRIDS.items()},
        "default_start": default_id,
        "starts_note": (
            "The selectable starts (landing spots, temporary): the front end reads them from here instead of "
            "computing them. Reason 6 (walled off) depends on the start, so each start has its own reason grid."
        ),
        "starts": starts_out,
        "profiles": {name: {"w": w} for name, w in weights.items()},
        "reason_codes": [
            {"code": code, "name": start_mod.REASON_NAMES[code], "text": start_mod.reason_text(code, params)}
            for code in sorted(start_mod.REASON_NAMES)
        ],
        "direction_meaning": "the step from this cell to the previous cell on its best path, toward the start",
        "direction_codes": [{"code": NO_STEP, "name": None, "drow": 0, "dcol": 0, "meaning": "the start cell, or no path"}]
        + [{"code": code, "name": n, "drow": dr, "dcol": dc} for code, (n, dr, dc) in DIRECTIONS.items()],
        "budget": budget(cfg),
        "config_sha256": config_sha256(cfg),
        "inputs_sha256": {
            name: file_sha256(Path(in_dir) / name) for name in (grid_mod.DEM_FILE, grid_mod.HAZARD_FILE)
        },
        "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        },
        "warnings": list(warnings),
    }


# ---- files left by an older layout or a start that is gone -------------------
# Every grid file name an export has ever written. Only these names are ever deleted.
GRID_FILE_NAMES = tuple(_profile_file(p, k) for p, _ in tour.PROFILES for k in PROFILE_GRIDS) + (REASON_FILE,)


def stale_paths(out_dir, start_ids):
    """What an earlier export left in `out_dir` that this one does not write, as a list of paths.

    - the grid files of the old layout, directly in `out_dir` (the names in GRID_FILE_NAMES);
    - the grid files in a folder next to `reach.json` that looks like a start folder (it holds a
      reason.u8) but whose name is not one of `start_ids`, and the folder itself.

    Nothing else is listed: other files, and a folder with other files in it, are left alone.
    """
    out_dir = Path(out_dir)
    stale = []
    if not out_dir.is_dir():
        return stale
    stale += [out_dir / n for n in GRID_FILE_NAMES if (out_dir / n).is_file()]
    for child in sorted(out_dir.iterdir()):
        if child.is_dir() and child.name not in start_ids and (child / REASON_FILE).is_file():
            stale += [child / n for n in GRID_FILE_NAMES if (child / n).is_file()]
            stale.append(child)
    return stale


def remove_stale(paths):
    """Delete the files in `paths`, and each listed folder if it is empty by then.

    Returns what was removed, as paths with a trailing "/" for folders, relative to nothing: the
    caller shows them as they are.
    """
    removed = []
    for path in paths:
        if path.is_file():
            path.unlink()
            removed.append(str(path))
        elif path.is_dir():
            try:
                path.rmdir()                    # only if empty: a folder with other files stays
            except OSError:
                continue
            removed.append(str(path) + "/")
    return removed


# ---- reading back and the reference traceback ---------------------------------
class ReachError(ValueError):
    """The reach folder is missing a file or does not match its manifest, or a start is unknown."""


class Reach:
    """An exported reach folder, read back. `trace` is the reference the front end copies."""

    def __init__(self, folder, manifest, reason, grids):
        self.folder = Path(folder)
        self.manifest = manifest
        self.reason = reason        # start id -> reason grid
        self.grids = grids          # start id -> profile -> {"time", "dist", "risk", "dir"}
        g = manifest["grid"]
        self.width, self.height, self.cell_m = g["width"], g["height"], g["cell_m"]
        self.origin = tuple(g["origin_m"])
        self.starts = {s["id"]: s for s in manifest["starts"]}
        self.default_start = manifest["default_start"]
        self.steps = {d["code"]: (d["drow"], d["dcol"]) for d in manifest["direction_codes"] if d["code"] != NO_STEP}
        self.reason_by_code = {r["code"]: r for r in manifest["reason_codes"]}

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        try:
            manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ReachError(f"{MANIFEST_FILE} not found in {folder}") from None
        if manifest.get("format_version") != FORMAT_VERSION:
            raise ReachError(
                f"{MANIFEST_FILE} has format_version {manifest.get('format_version')!r}, expected {FORMAT_VERSION}"
            )
        if manifest.get("byte_order") != BYTE_ORDER:
            raise ReachError(f"unsupported byte order {manifest.get('byte_order')!r}")
        g = manifest["grid"]
        shape = (g["height"], g["width"])

        def read(name, dkey):
            path = folder / name
            if not path.exists():
                raise ReachError(f"{name} not found in {folder}")
            arr = np.fromfile(path, dtype=DTYPES[dkey])
            if arr.size != shape[0] * shape[1]:
                raise ReachError(f"{name} has {arr.size} values, the manifest says {shape[0]} x {shape[1]}")
            return arr.reshape(shape)

        reason, grids = {}, {}
        for s in manifest["starts"]:
            reason[s["id"]] = read(s["reason_file"], "u8")
            grids[s["id"]] = {
                name: {key: read(fname, PROFILE_GRIDS[key][1]) for key, fname in p["files"].items()}
                for name, p in s["profiles"].items()
            }
        return cls(folder, manifest, reason, grids)

    def cell_of(self, x, y):
        """(row, col) of the export cell holding (x, y) in site metres, or None outside."""
        col = math.floor((x - self.origin[0]) / self.cell_m)
        row = self.height - 1 - math.floor((y - self.origin[1]) / self.cell_m)
        if 0 <= row < self.height and 0 <= col < self.width:
            return row, col
        return None

    def centre(self, row, col):
        return (
            self.origin[0] + (col + 0.5) * self.cell_m,
            self.origin[1] + (self.height - row - 0.5) * self.cell_m,
        )

    def trace(self, start_id, profile, x, y):
        """The best path from start `start_id` to (x, y) for `profile`, as a GeoJSON Feature.

        Coordinates are [x, y] metres from the start to the destination cell centre. Totals are
        the grid values at the destination. When there is no path the geometry is null and
        `reason` says why (`"outside"` for a point outside the exported area).
        """
        if start_id not in self.starts:
            raise ReachError(f"unknown start {start_id!r}; the starts are {', '.join(self.starts)}")
        if profile not in self.manifest["profiles"]:
            raise ReachError(f"unknown profile {profile!r}; the profiles are {', '.join(self.manifest['profiles'])}")
        g = self.grids[start_id][profile]
        start_cell = self.starts[start_id]["cell"]
        budget_ = self.manifest["budget"]
        props = {"start": start_id, "profile": profile, "w": self.manifest["profiles"][profile]["w"]}
        cell = self.cell_of(x, y)
        if cell is None:
            return _feature(None, {**props, "reachable": False, "reason": OUTSIDE,
                                   "reason_text": "outside the exported area"})
        code = int(self.reason[start_id][cell])
        if code != start_mod.REACHABLE:
            r = self.reason_by_code[code]
            return _feature(None, {**props, "reachable": False, "reason": code, "reason_name": r["name"],
                                   "reason_text": r["text"], "cell": list(cell)})
        cells = [cell]
        for _ in range(self.width * self.height):           # guard: a path never visits a cell twice
            d = int(g["dir"][cells[-1]])
            if d == NO_STEP:
                break
            dr, dc = self.steps[d]
            cells.append((cells[-1][0] + dr, cells[-1][1] + dc))
        else:
            raise ReachError(f"direction grid for {start_id}/{profile} loops at cell {cells[-1]}")
        if list(cells[-1]) != start_cell:
            raise ReachError(
                f"direction grid for {start_id}/{profile} stops at {cells[-1]}, not at the start {start_cell}"
            )
        cells.reverse()                                     # start -> destination
        coords = [list(self.centre(*c)) for c in cells]
        if len(coords) == 1:                                # destination is the start cell
            coords = coords * 2                             # a LineString needs two positions
        walk = float(g["time"][cell])
        needed = walk + budget_["ingress_min"] + budget_["stop_min"]
        return _feature(coords, {
            **props,
            "reachable": True,
            "reason": start_mod.REACHABLE,
            "distance_m": float(g["dist"][cell]),
            "walk_min": walk,
            "risk_min": float(g["risk"][cell]),
            "needed_min": needed,
            "over_budget": walk > budget_["walk_limit_min"],
            "cells": [list(c) for c in cells],
        })


def _feature(coords, props):
    geometry = None if coords is None else {"type": "LineString", "coordinates": coords}
    return {"type": "Feature", "geometry": geometry, "properties": props}


def trace(folder, start_id, profile, x, y):
    """Reference traceback: load the reach folder and trace one destination (see Reach.trace)."""
    return Reach.load(folder).trace(start_id, profile, x, y)


# ---- command line ------------------------------------------------------------
def parse_args(argv):
    p = argparse.ArgumentParser(description="Export reach grids from every start for the three profiles.")
    p.add_argument("--in", dest="in_dir", type=Path, default=DEFAULT_IN,
                   help="folder the inputs are read from (default: data/out)")
    p.add_argument("--out", dest="out_dir", type=Path, default=None,
                   help="folder the reach files are written to (default: <--in>/reach)")
    p.add_argument("--config", dest="config", type=Path, default=None,
                   help="parameter file (default: routing/config.toml)")
    return p.parse_args(argv)


def summary_lines(result: ExportResult):
    m = result.manifest
    g = m["grid"]
    lines = [
        f"{m['site']}: {g['width']} x {g['height']} cells of {g['cell_m']:g} m, origin {g['origin_m']}",
    ]
    for s in m["starts"]:
        size = sum(m["files"][p]["bytes"] for p in m["files"] if p.startswith(s["folder"] + "/"))
        reach_cells = ", ".join(f"{n} {p['reachable_cells']}" for n, p in s["profiles"].items())
        lines.append(
            f"  start {s['id']}{' (default)' if s['default'] else ''}: ({s['xy_m'][0]:g}, {s['xy_m'][1]:g}) m, "
            f"cell {s['cell']}, {size:,} bytes, reachable cells: {reach_cells}"
        )
    lines.append(f"  {MANIFEST_FILE}: {len(result.files[MANIFEST_FILE]):,} bytes")
    lines.append(f"  total: {result.total_bytes:,} bytes ({result.total_bytes / 1e6:.2f} MB) in {len(result.files)} files")
    b = m["budget"]
    lines.append(
        f"over budget (one way) when time + ingress_min + stop_min > usable_min {b['usable_min']:g}, "
        f"i.e. beyond {b['walk_limit_min']:g} min of walking"
    )
    for w in result.warnings:
        lines.append(f"WARNING {w}")
    if m["fake"]:
        lines.append("NOTE the inputs still contain fake data")
    return lines


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out_dir = args.out_dir if args.out_dir is not None else args.in_dir / REACH_DIR
    try:
        result = run(args.in_dir, args.config)
    except config_mod.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    outputs.write_files(out_dir, result.files)
    print(f"Wrote {len(result.files)} files to {out_dir}")
    for line in summary_lines(result):
        print(line)
    removed = remove_stale(stale_paths(out_dir, {s["id"] for s in result.manifest["starts"]}))
    if removed:
        print(f"Deleted {len(removed)} old files and folders that this layout no longer uses:")
        for path in removed:
            print("  " + Path(path).relative_to(out_dir).as_posix() + ("/" if path.endswith("/") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
