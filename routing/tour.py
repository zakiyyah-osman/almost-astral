"""Waypoints, stop order and the three profile routes (DESIGN sections 4.6 and 4.7).

The tour is rover -> stops -> rover. The stop order is chosen once, on the balanced planning
cost, and used for all three profiles; the profiles differ only in the risk weight w.
"""
import itertools
import json
import math
import numbers
from dataclasses import dataclass
from pathlib import Path

from config import Config, ConfigError
from cost import Cost
from grid import WAYPOINTS_FILE, Grid, GridError
from search import NoPath, PathSummary, Searcher

KIND_ROVER, KIND_STOP = "rover", "stop"
ORDER_MODES = ("as_listed", "optimise")
PROFILES = (
    ("fastest", "profiles.w_fastest"),
    ("balanced", "profiles.w_balanced"),
    ("safest", "profiles.w_safest"),
)
TIE_TOL = 1e-9          # relative slack when two stop orders cost the same


class RouteError(ConfigError):
    """The waypoints cannot be turned into a tour (bad file, blocked or unreachable stop)."""


@dataclass(frozen=True)
class Waypoint:
    id: str
    name: str
    kind: str
    x: float
    y: float
    cell: tuple             # (row, col) of the cell containing (x, y)

    def describe(self):
        return f"{self.kind} {self.id!r} ({self.name}) at ({self.x:g}, {self.y:g}) m"


@dataclass(frozen=True)
class Leg:
    from_id: str
    to_id: str
    path: PathSummary


@dataclass(frozen=True)
class Route:
    """One profile's route: rover -> stops -> rover."""

    profile: str
    w: float
    order: tuple            # stop ids in visiting order
    legs: tuple
    cells: tuple            # whole route as cells, rover to rover, no repeated joints

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
    rover: Waypoint
    order: tuple            # stops in visiting order (Waypoint objects)
    mode: str
    routes: dict            # profile name -> Route


# ---- waypoints ---------------------------------------------------------------
def _number(v):
    return isinstance(v, numbers.Real) and not isinstance(v, bool) and math.isfinite(v)


def load_waypoints(folder, grid: Grid):
    """All waypoints in file order, each snapped to its cell. Exactly one must be the rover."""
    path = Path(folder) / WAYPOINTS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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
        if props.get("kind") not in (KIND_ROVER, KIND_STOP):
            raise RouteError(f"{where} ({wid!r}): kind must be 'rover' or 'stop', got {props.get('kind')!r}")
        if wid in seen:
            raise RouteError(f"{WAYPOINTS_FILE}: id {wid!r} appears twice")
        seen.add(wid)
        name = props.get("name")
        name = name if isinstance(name, str) and name else wid
        x, y = float(xy[0]), float(xy[1])
        try:
            cell = grid.xy_to_cell(x, y)
        except GridError as e:
            raise RouteError(f"{props['kind']} {wid!r} ({name}): {e}") from None
        waypoints.append(Waypoint(wid, name, props["kind"], x, y, cell))
    return waypoints


def split_waypoints(waypoints):
    """(rover, stops). Exactly one rover and at least one stop are required."""
    rovers = [w for w in waypoints if w.kind == KIND_ROVER]
    stops = [w for w in waypoints if w.kind == KIND_STOP]
    if len(rovers) != 1:
        raise RouteError(f"exactly one waypoint of kind 'rover' is required, found {len(rovers)}")
    if not stops:
        raise RouteError("at least one waypoint of kind 'stop' is required, found none")
    return rovers[0], stops


def block_reason(cost: Cost, cell):
    """Why a cell is blocked, in words, or None if it is passable."""
    if not cost.blocked[cell]:
        return None
    r = cost.reasons
    for key, text in (
        ("nodata", "no DEM data"),
        ("red", "red hazard cell"),
        ("slope", f"slope over the limit ({cost.params.slope_max_deg:g} deg)"),
        ("buffer", f"inside the {cost.params.cliff_buffer_m:g} m buffer around over-limit slopes"),
        ("sealed", "sealed gap between blocked cells"),
    ):
        if r[key][cell]:
            return text
    return "blocked"


def check_waypoints(cost: Cost, rover: Waypoint, stops, searcher: Searcher):
    """Fail by name if the rover or a stop is on a blocked cell, or a stop cannot be reached."""
    for wp in [rover, *stops]:
        reason = block_reason(cost, wp.cell)
        if reason:
            raise RouteError(f"{wp.describe()} is on a blocked cell: {reason}")
    tree = searcher.tree(rover.cell)
    for wp in stops:
        if not tree.reachable(wp.cell):
            raise RouteError(f"{wp.describe()} cannot be reached from the rover: no passable path")


# ---- stop order --------------------------------------------------------------
def _tour_cost(searcher: Searcher, rover, order):
    chain = [rover, *order, rover]
    return sum(searcher.planning_cost(a.cell, b.cell) for a, b in zip(chain, chain[1:]))


def stop_order(searcher: Searcher, rover: Waypoint, stops, mode):
    """Stops in visiting order. `searcher` carries the balanced risk weight.

    as_listed keeps the file order. optimise tries every order and keeps the cheapest tour on
    the balanced planning cost; a tie goes to the order that comes first in file order.
    """
    if mode not in ORDER_MODES:
        raise ConfigError(f"stop order mode must be one of {', '.join(ORDER_MODES)}, got {mode!r}")
    stops = list(stops)
    if mode == "as_listed":
        return stops
    best, best_cost = stops, math.inf
    for perm in itertools.permutations(range(len(stops))):       # file order comes first
        order = [stops[i] for i in perm]
        c = _tour_cost(searcher, rover, order)
        if c < best_cost and (not math.isfinite(best_cost) or best_cost - c > TIE_TOL * max(1.0, best_cost)):
            best, best_cost = order, c
    return best


# ---- routes ------------------------------------------------------------------
def build_route(searcher: Searcher, rover: Waypoint, order, profile):
    """The route rover -> order -> rover at the searcher's risk weight."""
    chain = [rover, *order, rover]
    legs, cells = [], []
    for a, b in zip(chain, chain[1:]):
        try:
            path = searcher.path(a.cell, b.cell)
        except NoPath as e:
            raise RouteError(f"no route from {a.id!r} to {b.id!r}: {e}") from None
        legs.append(Leg(a.id, b.id, path))
        cells.extend(path.cells if not cells else path.cells[1:])
    return Route(profile, searcher.w, tuple(s.id for s in order), tuple(legs), tuple(cells))


def plan_routes(cost: Cost, rover: Waypoint, stops, cfg: Config, mode=None):
    """The three profile routes, sharing one stop order chosen on the balanced cost."""
    mode = cfg.value("timeline.stop_order") if mode is None else mode
    connectivity = cfg.value("search.connectivity")
    searchers = {
        name: Searcher(cost, cfg.value(key), connectivity) for name, key in PROFILES
    }
    check_waypoints(cost, rover, stops, searchers["balanced"])
    order = stop_order(searchers["balanced"], rover, stops, mode)
    routes = {name: build_route(s, rover, order, name) for name, s in searchers.items()}
    return TourPlan(rover=rover, order=tuple(order), mode=mode, routes=routes)
