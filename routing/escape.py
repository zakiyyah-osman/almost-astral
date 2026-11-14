"""Walking out of a red zone: the escape rates and the reference escape (DESIGN section 17).

A Team outing may start inside blocked ground. The browser (web/src/lib/escape.js) then walks the crew
out of that red zone first and plans the normal route from the exit. This module gives it the rates and
is the reference its search must reproduce.

    escape_time_rate  min/m: the walking model (cost.time_rate, same formula and parameters) at the cell's
                      slope, NOT clipped by constraints.slope_max_deg, in cells whose mask code is in
                      escape.zone_codes and whose slope is <= escape.max_slope_deg; -1 everywhere else
                      (other codes, passable cells, steeper cells, NaN slope, no data)
    escape_risk_rate  risk-min per min walked: escape.risk_rate in those same cells, 0 elsewhere

Emergency estimate only: speeds on slopes over the normal limit extrapolate the walking model beyond the
range it was meant for (team assumption).

The rule (escape.js with the start_too_steep fix):

    zone     the 8-connected region of cells with a zone code that holds the start
    phase 1  Dijkstra from the start inside the zone (DESIGN 15.2 step rule; escape rates in the zone,
             the normal rates on the exit cells). A zone cell with escape_time_rate < 0 is never entered.
             An exit is a passable cell next to the zone: entered in one step, never expanded further.
             If the start cell itself has escape_time_rate < 0: no exit, reason "start_too_steep".
    exit     the lowest escape walk cost (w = 0, i.e. physical minutes) among exits in the destination's
             passable region (8-connected); exact ties go to the lowest total planning cost for the
             profile (escape at w plus the normal search from the exit).
    phase 2  the normal search (export_landing.Surface.route) from the exit, which never enters blocked
             ground, the zone included.
"""
import heapq
import math

import numpy as np
from scipy import ndimage

import cost as cost_mod

NO_EXIT = "no_exit"
START_TOO_STEEP = "start_too_steep"
NOT_IN_ZONE = "not_in_zone"
EIGHT = np.ones((3, 3), dtype=bool)
NEIGH = ((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (-1, -1, 1), (-1, 1, 1), (1, -1, 1), (1, 1, 1))

RULE = (
    "zone = the 8-connected region of cells whose mask code is in zone_codes that holds the start. "
    "Phase 1: Dijkstra from the start inside the zone with the edge rule of search.edge_rule, using "
    "escape_time_rate / escape_risk_rate in zone cells and time_rate / risk_rate on exit cells; a zone cell "
    "with escape_time_rate < 0 is never entered; an exit is a passable cell (mask 0) next to the zone, entered "
    "in one step and never expanded. If the start cell has escape_time_rate < 0 the result is no_exit with "
    "reason start_too_steep. Exit = the lowest escape walk cost at w = 0 among exits in the destination's "
    "8-connected passable region (none: no_exit); exact ties go to the lowest total planning cost for the "
    "profile (escape at w + normal search from the exit). Phase 2: the normal search from the exit, never "
    "entering blocked ground."
)
NOTE = (
    "Team assumption (Tushaar), emergency estimate only: escape speeds apply the walking model to slopes "
    "above constraints.slope_max_deg, beyond the range it was meant for, so escape times are rough. "
    "risk_rate and max_slope_deg are team assumptions, not sourced values."
)


def params(cfg):
    return {"zone_codes": [int(c) for c in cfg.value("escape.zone_codes")],
            "risk_rate": float(cfg.value("escape.risk_rate")),
            "max_slope_deg": float(cfg.value("escape.max_slope_deg"))}


def eligible(slope_deg, mask, esc):
    """Zone-code cells with a known slope at or below escape.max_slope_deg."""
    with np.errstate(invalid="ignore"):
        return np.isin(mask, esc["zone_codes"]) & ~np.isnan(slope_deg) & (slope_deg <= esc["max_slope_deg"])


def rates(slope_deg, mask, cost_params: cost_mod.Params, esc):
    """(escape_time_rate, escape_risk_rate), float64: cost.time_rate unclipped in eligible cells."""
    ok = eligible(slope_deg, mask, esc)
    time = cost_mod.time_rate(slope_deg, ~ok, cost_params)
    risk = np.where(ok, esc["risk_rate"], 0.0)
    return time, risk


def zone_of(mask, codes, start):
    """Boolean array of the start's red zone, or None when the start is not in one."""
    inz = np.isin(mask, codes) & (mask != 0)
    if not inz[start]:
        return None
    lab, _ = ndimage.label(inz, structure=EIGHT)
    return lab == lab[start]


def passable_regions(mask):
    """8-connected labels of passable cells; 0 where blocked."""
    lab, _ = ndimage.label(mask == 0, structure=EIGHT)
    return lab


class Escape:
    """The reference escape on an exported surface plus the two escape grids."""

    def __init__(self, surface, esc_time, esc_risk, esc):
        self.s = surface
        self.codes = list(esc["zone_codes"])
        self.zone_time, self.zone_risk = esc_time, esc_risk
        self.regions = passable_regions(surface.mask)

    def _rates(self, zone):
        t = np.where(zone, self.zone_time, self.s.time_rate)
        r = np.where(zone, self.zone_risk, self.s.risk_rate)
        return t, r

    def search(self, zone, start, t, r, w):
        """Phase 1: (g, prev, exits in pop order). Exits are entered, not expanded."""
        H, W = zone.shape
        cm = self.s.cell_m
        L = (cm, math.sqrt(cm * cm + cm * cm))
        p = t * (1.0 + w * r)
        g = np.full(zone.shape, math.inf)
        prev = {}
        done = np.zeros(zone.shape, bool)
        blocked = self.s.mask != 0
        g[start] = 0.0
        heap, seq = [(0.0, 0, start)], 1
        exits = []
        while heap:
            gi, _, i = heapq.heappop(heap)
            if done[i]:
                continue
            done[i] = True
            if not zone[i]:
                exits.append(i)
                continue
            ri, ci = i
            for dr, dc, diag in NEIGH:
                j = (ri + dr, ci + dc)
                if not (0 <= j[0] < H and 0 <= j[1] < W) or done[j]:
                    continue
                if zone[j]:
                    if self.zone_time[j] < 0:
                        continue                    # too steep even in an emergency
                elif blocked[j]:
                    continue
                ng = g[i] + L[diag] * (float(p[i]) + float(p[j])) / 2.0
                if ng < g[j]:
                    g[j] = ng
                    prev[j] = i
                    heapq.heappush(heap, (ng, seq, j))
                    seq += 1
        return g, prev, exits

    def plan(self, start_xy, dest_xy, profile):
        """The escape and the route for one profile, as a dict (see DESIGN 17.3)."""
        s = self.s
        a, z = s.cell_of(*start_xy), s.cell_of(*dest_xy)
        out = {"profile": profile, "w": s.weights[profile]}
        if a is None or z is None:
            return {**out, "ok": False, "status": "outside", "reason": "outside"}
        zone = zone_of(s.mask, self.codes, a)
        if zone is None:
            return {**out, "ok": False, "status": NOT_IN_ZONE, "reason": NOT_IN_ZONE}
        out["zone_cells"] = int(zone.sum())
        if self.zone_time[a] < 0:
            return {**out, "ok": False, "status": NO_EXIT, "reason": START_TOO_STEEP}
        if s.mask[z] != 0:
            return {**out, "ok": False, "status": "dest_blocked", "reason": int(s.mask[z])}
        target = self.regions[z]
        t, r = self._rates(zone)
        g, prev, exits = self.search(zone, a, t, r, 0.0)
        valid = [e for e in exits if self.regions[e] == target]
        out["exits_found"] = len(exits)
        if not valid:
            return {**out, "ok": False, "status": NO_EXIT, "reason": NO_EXIT}
        best = min(g[e] for e in valid)
        tied = [e for e in valid if g[e] == best]
        out["tie"] = len(tied) > 1
        if len(tied) > 1:
            w = s.weights[profile]
            gw, _, _ = self.search(zone, a, t, r, w)

            def total(e):
                _, cum = s._tree(e, profile)
                return gw[e] + cum[z]
            pick = tied[0]
            for e in tied[1:]:
                if total(e) < total(pick):
                    pick = e
            tied = [pick]
        exit_ = tied[0]
        cells = [exit_]
        while cells[-1] in prev:
            cells.append(prev[cells[-1]])
        cells.reverse()
        d, tm, rk = totals(s.cell_m, t, r, cells)
        route = s.route(s.centre(*exit_), dest_xy, profile)["properties"]
        b = s.budget
        tw = tm + route["walk_min"]
        return {
            **out, "ok": True, "status": "ok", "reason": 0,
            "escape": {"exit_cell": list(exit_), "exit_xy_m": list(s.centre(*exit_)),
                       "cells": [list(c) for c in cells], "distance_m": d, "walk_min": tm, "risk_min": rk},
            "route": {k: route[k] for k in ("distance_m", "walk_min", "risk_min", "cells")},
            "total": {"distance_m": d + route["distance_m"], "walk_min": tw, "risk_min": rk + route["risk_min"],
                      "needed_min": tw + b["ingress_min"] + b["stop_min"], "over_budget": tw > b["walk_limit_min"]},
        }


def totals(cell_m, t, r, cells):
    """DESIGN 15.3 totals with the given rates (escape rates in the zone)."""
    diag = cell_m * math.sqrt(2.0)
    d = tm = rk = 0.0
    for (ra, ca), (rb, cb) in zip(cells, cells[1:]):
        L = diag if (ra != rb and ca != cb) else cell_m
        ta, tb = float(t[ra, ca]), float(t[rb, cb])
        d += L
        tm += L * (ta + tb) / 2.0
        rk += L * (ta * float(r[ra, ca]) + tb * float(r[rb, cb])) / 2.0
    return d, tm, rk


def golden(surface, esc_time, esc_risk, esc, landing_map):
    """golden_escape_cases.json content: up to 5 real starts inside red zones, every profile.

    Deterministic choices. Destination: the safe landing cell nearest the window centre. Starts:
    escape1-3  in the three largest zones that have a valid exit, the eligible cell deepest inside the
               zone (largest distance to non-zone ground; first in row-major order on ties)
    start_too_steep  the deepest zone cell steeper than escape.max_slope_deg, if any
    no_exit    the destination is a passable cell in a pocket walled off from the main ground (the largest
               passable region); the start is the deepest eligible cell of the largest zone that does not
               border that pocket, if the data has such a pocket
    """
    ref = Escape(surface, esc_time, esc_risk, esc)
    H, W = surface.mask.shape
    dest = (int(landing_map.near_rows[H // 2, W // 2]), int(landing_map.near_cols[H // 2, W // 2]))
    inz = np.isin(surface.mask, esc["zone_codes"]) & (surface.mask != 0)
    lab, _ = ndimage.label(inz, structure=EIGHT)
    sizes = np.bincount(lab.ravel())
    order = [int(k) for k in np.argsort(-sizes[1:], kind="stable") + 1]
    depth = ndimage.distance_transform_edt(inz)
    cases, skipped = [], []

    def deepest(cellmask):
        d = np.where(cellmask, depth, -1.0)
        return tuple(int(v) for v in np.unravel_index(int(np.argmax(d)), d.shape))

    def add(cid, start, z, note):
        sxy, dxy = surface.centre(*start), surface.centre(*z)
        case = {"id": cid, "note": note, "start_xy_m": list(sxy), "start_cell": list(start),
                "start_mask_code": int(surface.mask[start]),
                "start_escape_time_rate": float(esc_time[start]),
                "dest_xy_m": list(dxy), "dest_cell": list(z),
                "results": {p: ref.plan(sxy, dxy, p) for p in surface.weights}}
        cases.append(case)
        return case

    found = 0
    for k in order:
        if found == 3:
            break
        good = (lab == k) & (esc_time > 0)
        if not good.any():
            continue
        start = deepest(good)
        if ref.plan(surface.centre(*start), surface.centre(*dest), "fastest")["ok"]:
            found += 1
            add(f"escape{found}", start, dest,
                f"zone {found} by size with a valid exit ({int(sizes[k])} cells): its deepest eligible cell")
    if found < 3:
        skipped.append(f"escape: only {found} zones with a valid exit")

    steep = inz & (esc_time < 0)                    # zone cells have a slope (NaN is code 1)
    if steep.any():
        add("start_too_steep", deepest(steep), dest, "start on the deepest zone cell steeper than escape.max_slope_deg")
    else:
        skipped.append("start_too_steep: no zone cell is steeper than escape.max_slope_deg")

    regions = ref.regions
    counts = np.bincount(regions.ravel())
    counts[0] = 0
    main = int(np.argmax(counts))
    pockets = [int(k) for k in np.argsort(-counts, kind="stable") if k not in (0, main) and counts[k] > 0]
    done = False
    for pk in pockets:
        pocket = regions == pk
        ring = ndimage.binary_dilation(pocket, structure=EIGHT)
        for k in order:
            good = (lab == k) & (esc_time > 0)
            if not good.any() or (ring & (lab == k)).any():
                continue
            start, z = deepest(good), tuple(int(v) for v in np.argwhere(pocket)[0])
            case = add("no_exit", start, z,
                       f"destination in a walled-off pocket of {int(counts[pk])} passable cells; the start's zone "
                       f"({int(sizes[k])} cells) does not border it, so no exit reaches the destination")
            assert all(r["reason"] == NO_EXIT for r in case["results"].values())
            done = True
            break
        if done:
            break
    if not done:
        skipped.append("no_exit: every zone has an exit into the destination's region (no walled-off pocket "
                       "that some zone does not border)")
    return cases, skipped
