"""Waypoints, stop order and the three profile routes (DESIGN sections 4.6 and 4.7).

The tour is start -> stops -> start. The start is the default one of the [starts.<id>] in
routing/config.toml (see start.py) and its id is always "start", whatever the waypoint file calls it; a waypoint of
kind 'start' in waypoints.geojson is only compared with it. The old kind 'rover' is still read
as 'start', with a deprecation warning. The stop order is chosen
once, on the balanced planning cost, and used for all three profiles; the profiles differ only
in the risk weight w.
"""
import itertools
import json
import logging
import math
import numbers
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config import Config, ConfigError
from cost import Cost
from grid import WAYPOINTS_FILE, Grid, GridError
from search import NoPath, PathSummary, Searcher, path_profile
import start as start_mod

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())       # no stderr fallback: the command line prints each warning once

KIND_START, KIND_STOP = "start", "stop"
KIND_ROVER = "rover"            # deprecated name for KIND_START, still accepted
KINDS = (KIND_START, KIND_STOP, KIND_ROVER)
START_NAME = "Start"
ORDER_MODES = ("as_listed", "optimise")
PROFILES = (
    ("fastest", "profiles.w_fastest"),
    ("balanced", "profiles.w_balanced"),
    ("safest", "profiles.w_safest"),
)
TIE_TOL = 1e-9          # relative slack when two stop orders cost the same


class RouteError(ConfigError):
    """The waypoints cannot be turned into a tour (bad file, blocked or unreachable stop).

    `waypoint_id` names the start or stop that failed, when the failure is about one.
    """

    def __init__(self, message, waypoint_id=None):
        super().__init__(message)
        self.waypoint_id = waypoint_id


@dataclass(frozen=True)
class Waypoint:
    id: str
    name: str
    kind: str
    x: float
    y: float
    cell: tuple             # (row, col) of the cell containing (x, y)
    deprecated_kind: object = None      # 'rover' when the file used the old kind name
    landing_id: object = None           # the id of the start in the config ('L1'), for the start only

    def describe(self):
        return f"{self.kind} {self.id!r} ({self.name}) at ({self.x:g}, {self.y:g}) m"


@dataclass(frozen=True)
class Leg:
    from_id: str
    to_id: str
    path: PathSummary


@dataclass(frozen=True)
class Route:
    """One profile's route: start -> stops -> start."""

    profile: str
    w: float
    order: tuple            # stop ids in visiting order
    legs: tuple
    cells: tuple            # whole route as cells, start to start, no repeated joints

    def _sum(self, field):
        return float(sum(getattr(leg.path, field) for leg in self.legs))

    distance_m = property(lambda self: self._sum("distance_m"))
    physical_min = property(lambda self: self._sum("physical_min"))
    risk_min = property(lambda self: self._sum("risk_min"))
    yellow_min = property(lambda self: self._sum("yellow_min"))
    steep_min = property(lambda self: self._sum("steep_min"))
    near_red_min = property(lambda self: self._sum("near_red_min"))


@dataclass(frozen=True)
class TourPlan:
    start: Waypoint
    order: tuple            # stops in visiting order (Waypoint objects)
    mode: str               # the mode actually used
    routes: dict            # profile name -> Route
    requested_mode: str = ""    # the mode asked for; differs from `mode` after a fallback
    warnings: tuple = ()        # recorded in plan.json (stop_order.warnings)


@dataclass(frozen=True)
class OrderChoice:
    order: tuple
    mode: str
    requested_mode: str
    warnings: tuple


# ---- waypoints ---------------------------------------------------------------
def _number(v):
    return isinstance(v, numbers.Real) and not isinstance(v, bool) and math.isfinite(v)


def load_waypoints(folder, grid: Grid):
    """All waypoints in file order, each snapped to its cell.

    Kind 'rover' is read as 'start' and logs a deprecation warning (see deprecation_warnings).
    """
    path = Path(folder) / WAYPOINTS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise RouteError(f"{WAYPOINTS_FILE} not found in {Path(folder)}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise RouteError(f"{WAYPOINTS_FILE} cannot be read ({path}): {e}") from None
    except json.JSONDecodeError as e:
        raise RouteError(f"{WAYPOINTS_FILE} is not valid JSON: {e}") from None
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        raise RouteError(f"{WAYPOINTS_FILE} must be a FeatureCollection with a features list")

    waypoints, seen = [], set()
    for i, f in enumerate(features):
        where = f"{WAYPOINTS_FILE} feature {i}"
        geom = f.get("geometry") if isinstance(f, dict) else None
        props = f.get("properties") if isinstance(f, dict) else None
        if not isinstance(geom, dict) or geom.get("type") != "Point":
            raise RouteError(f"{where}: must be a Point")
        xy = geom.get("coordinates")
        if not (isinstance(xy, (list, tuple)) and len(xy) >= 2 and _number(xy[0]) and _number(xy[1])):
            raise RouteError(f"{where}: coordinates must be [x, y] in metres")
        if not isinstance(props, dict) or not isinstance(props.get("id"), str) or not props["id"]:
            raise RouteError(f"{where}: needs a text id")
        wid = props["id"]
        kind = props.get("kind")
        if kind not in KINDS:
            raise RouteError(
                f"{where} ({wid!r}): kind must be 'start' or 'stop' (or the old 'rover'), got {kind!r}"
            )
        if wid in seen:
            raise RouteError(f"{WAYPOINTS_FILE}: id {wid!r} appears twice")
        if kind == KIND_STOP and wid == start_mod.START_ID:
            raise RouteError(
                f"{where}: a stop cannot use the id {wid!r}, which is the id of the start; give it another id"
            )
        seen.add(wid)
        name = props.get("name")
        name = name if isinstance(name, str) and name else wid
        x, y = float(xy[0]), float(xy[1])
        try:
            cell = grid.xy_to_cell(x, y)
        except GridError as e:
            raise RouteError(f"{kind} {wid!r} ({name}): {e}") from None
        deprecated = None
        if kind == KIND_ROVER:
            deprecated, kind = KIND_ROVER, KIND_START
            log.warning(_deprecation_message(wid))
        waypoints.append(Waypoint(wid, name, kind, x, y, cell, deprecated))
    return waypoints


def _deprecation_message(wid):
    return (
        f"{WAYPOINTS_FILE}: waypoint {wid!r} uses kind 'rover', which is deprecated; "
        "it is read as 'start'. Please change it to 'start'."
    )


def deprecation_warnings(waypoints):
    """One message per waypoint that used a deprecated kind (for plan.json warnings)."""
    return tuple(_deprecation_message(w.id) for w in waypoints if w.deprecated_kind)


def split_waypoints(waypoints):
    """(start waypoint or None, stops). At most one start and at least one stop are required.

    The start waypoint is optional: the start itself is the default [starts.<id>] of config.toml
    (resolve_start).
    """
    starts = [w for w in waypoints if w.kind == KIND_START]
    stops = [w for w in waypoints if w.kind == KIND_STOP]
    if len(starts) > 1:
        raise RouteError(
            f"at most one waypoint of kind 'start' (or the old 'rover') is allowed, found {len(starts)}"
        )
    if not stops:
        raise RouteError("at least one waypoint of kind 'stop' is required, found none")
    return (starts[0] if starts else None), stops


def resolve_start(cfg: Config, cost: Cost, hazard=None, waypoint=None):
    """(the start Waypoint, warnings): the default start of the config, after checking every start.

    All the configured starts are checked (start.validate_starts), so a bad L3 is found even
    though only the default one is planned from; the first bad start raises a StartError that
    names it. The id of the returned start is always "start" and `landing_id` is the config id
    ('L1'). A start waypoint from waypoints.geojson is only compared with the default start: if
    it lies more than half a cell from it, a warning says so and the config value is used.
    Starts on careful ground give warnings.
    """
    infos = start_mod.validate_starts(cfg, cost, hazard)
    spec = start_mod.default_start(cfg)
    info = infos[spec.id]
    warnings = [w for i in infos.values() for w in i.warnings]
    xy = info.xy
    if waypoint is not None:
        if not start_mod.is_near((waypoint.x, waypoint.y), xy, cost.grid.cell_m):
            msg = (
                f"{WAYPOINTS_FILE} puts its start waypoint at ({waypoint.x:g}, {waypoint.y:g}) m, "
                f"more than half a cell from the default start {spec.id!r} ({xy[0]:g}, {xy[1]:g}) m "
                "in routing/config.toml; the config value is used"
            )
            log.warning(msg)
            warnings.append(msg)
    return Waypoint(
        start_mod.START_ID, START_NAME, KIND_START, xy[0], xy[1], info.cell, landing_id=spec.id,
    ), tuple(warnings)


def block_reason(cost: Cost, cell):
    """Why a cell is blocked, in words, or None if it is passable."""
    code = start_mod.block_code(cost, cell)
    return None if code == start_mod.REACHABLE else start_mod.reason_text(code, cost.params)


def check_waypoints(cost: Cost, start: Waypoint, stops, searcher: Searcher):
    """Fail by name if the start or a stop is on a blocked cell, or a stop cannot be reached.

    A blocked start raises start.StartError; a stop problem raises RouteError naming the stop.
    """
    start_mod.check_start(cost, start.cell, (start.x, start.y), name=start.landing_id)
    for wp in stops:
        reason = block_reason(cost, wp.cell)
        if reason:
            raise RouteError(f"{wp.describe()} is on a blocked cell: {reason}", wp.id)
    tree = searcher.tree(start.cell)
    for wp in stops:
        if not tree.reachable(wp.cell):
            raise RouteError(f"{wp.describe()} cannot be reached from the start: no passable path", wp.id)


# ---- stop order --------------------------------------------------------------
def _tour_cost(searcher: Searcher, start, order):
    chain = [start, *order, start]
    return sum(searcher.planning_cost(a.cell, b.cell) for a, b in zip(chain, chain[1:]))


def cost_matrix(searcher: Searcher, waypoints):
    """Planning minutes between every pair of waypoints, from one search per waypoint."""
    cells = [w.cell for w in waypoints]
    trees = [searcher.tree(cell) for cell in cells]
    return [[float(tree.planning_cost[cell]) for cell in cells] for tree in trees]


def stop_order(searcher: Searcher, start: Waypoint, stops, mode):
    """Stops in visiting order. `searcher` carries the balanced risk weight.

    as_listed keeps the file order. optimise tries every order and keeps the cheapest tour on
    the balanced planning cost; a tie goes to the order that comes first in file order. The
    pairwise costs are computed once (one search per waypoint) and every order is summed from
    them. There is no limit on the number of stops here: choose_order applies it.
    """
    if mode not in ORDER_MODES:
        raise ConfigError(f"stop order mode must be one of {', '.join(ORDER_MODES)}, got {mode!r}")
    stops = list(stops)
    if mode == "as_listed":
        return stops
    matrix = cost_matrix(searcher, [start, *stops])      # index 0 is the start, i + 1 is stops[i]
    best, best_cost = stops, math.inf
    for perm in itertools.permutations(range(len(stops))):       # file order comes first
        order = [stops[i] for i in perm]
        chain = [0, *(i + 1 for i in perm), 0]
        c = sum(matrix[a][b] for a, b in zip(chain, chain[1:]))
        if c < best_cost and (not math.isfinite(best_cost) or best_cost - c > TIE_TOL * max(1.0, best_cost)):
            best, best_cost = order, c
    return best


def choose_order(searcher: Searcher, start: Waypoint, stops, mode, max_stops):
    """stop_order with the stop limit: optimise over more than `max_stops` stops uses as_listed."""
    if mode not in ORDER_MODES:
        raise ConfigError(f"stop order mode must be one of {', '.join(ORDER_MODES)}, got {mode!r}")
    stops = list(stops)
    used, warnings = mode, ()
    if mode == "optimise" and len(stops) > max_stops:
        used = "as_listed"
        warnings = (
            f"stop order 'optimise' skipped: {len(stops)} stops is more than the limit of "
            f"{max_stops}; the order in waypoints.geojson is used",
        )
    return OrderChoice(tuple(stop_order(searcher, start, stops, used)), used, mode, warnings)


# ---- clock along a route -----------------------------------------------------
@dataclass(frozen=True)
class RouteClock:
    """Distance and time at every cell of a route (arrays are indexed like route.cells)."""

    distance_m: np.ndarray      # cumulative distance from the start
    walk_min: np.ndarray        # cumulative physical walking minutes
    elapsed_min: np.ndarray     # clock since leaving the start: walking + time at stops already done
    arrival_index: dict         # stop id -> index of the route cell where the crew arrives


def route_clock(cost: Cost, route: "Route", stop_min):
    """The clock along a route. Time at a stop counts from the cell after the arrival cell."""
    distance, walk = path_profile(cost, route.cells)
    arrivals, at = {}, 0
    for leg in route.legs[:-1]:                      # the last leg returns to the start
        at += len(leg.path.cells) - 1
        arrivals[leg.to_id] = at
    done = np.zeros(len(route.cells))
    for idx in arrivals.values():
        done[idx + 1:] += 1.0
    return RouteClock(distance, walk, walk + stop_min * done, arrivals)


def sample_indices(distance_m, spacing_m):
    """Route-cell indices nearest to 0, spacing, 2 x spacing ... up to the route length."""
    total = float(distance_m[-1])
    targets = np.arange(0.0, total + 1e-9, spacing_m)
    right = np.clip(np.searchsorted(distance_m, targets), 0, len(distance_m) - 1)
    left = np.clip(right - 1, 0, len(distance_m) - 1)
    pick_left = np.abs(distance_m[left] - targets) <= np.abs(distance_m[right] - targets)
    return np.where(pick_left, left, right)


# ---- routes ------------------------------------------------------------------
def build_route(searcher: Searcher, start: Waypoint, order, profile):
    """The route start -> order -> start at the searcher's risk weight."""
    chain = [start, *order, start]
    legs, cells = [], []
    for a, b in zip(chain, chain[1:]):
        try:
            path = searcher.path(a.cell, b.cell)
        except NoPath as e:
            raise RouteError(f"no route from {a.id!r} to {b.id!r}: {e}", b.id) from None
        legs.append(Leg(a.id, b.id, path))
        cells.extend(path.cells if not cells else path.cells[1:])
    return Route(profile, searcher.w, tuple(s.id for s in order), tuple(legs), tuple(cells))


def plan_routes(cost: Cost, start: Waypoint, stops, cfg: Config, mode=None):
    """The three profile routes, sharing one stop order chosen on the balanced cost."""
    mode = cfg.value("timeline.stop_order") if mode is None else mode
    connectivity = cfg.value("search.connectivity")
    searchers = {
        name: Searcher(cost, cfg.value(key), connectivity) for name, key in PROFILES
    }
    check_waypoints(cost, start, stops, searchers["balanced"])
    choice = choose_order(
        searchers["balanced"], start, stops, mode, cfg.value("timeline.optimise_max_stops")
    )
    routes = {name: build_route(s, start, choice.order, name) for name, s in searchers.items()}
    return TourPlan(
        start=start, order=choice.order, mode=choice.mode, routes=routes,
        requested_mode=choice.requested_mode, warnings=choice.warnings,
    )
