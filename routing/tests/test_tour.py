import itertools
import json
import math

import numpy as np
import pytest

import cost
import grid as g
import tour
from config import ConfigError, load_config
from conftest import write_site, write_waypoints
from cost import Params
from search import Searcher
from tour import RouteError, Waypoint

CFG = load_config()
P = Params.from_config(CFG)
CELL = 5.0


def make_cost(hazard=None, slope=None, shape=(20, 30), cell=CELL, p=P, dem=None):
    hazard = np.zeros(shape, np.uint8) if hazard is None else hazard
    slope = np.zeros(shape) if slope is None else slope
    dem = np.zeros(shape) if dem is None else dem
    return cost.build(dem, hazard, slope, g.Grid(shape[1], shape[0], cell), p)


def wp(wid, kind, cell, shape=(20, 30), cell_m=CELL, name=None):
    grid = g.Grid(shape[1], shape[0], cell_m)
    x, y = grid.cell_centre(*cell)
    return Waypoint(wid, name or f"Name of {wid}", kind, x, y, cell)


def rover_at(cell, **kw):
    return wp("rover", "rover", cell, **kw)


# ---- loading -----------------------------------------------------------------
def test_waypoints_load_in_file_order_and_snap_to_cells(flat_site):
    grid = g.read_grid(flat_site.folder)
    write_waypoints(flat_site.folder, [
        ("rover", "Rover", "rover", 52.5, 52.5),
        ("stop1", "First", "stop", 5.0, 95.0),            # on cell edges: lower edge belongs to the cell
        ("stop2", "Second", "stop", 97.5, 2.5),
    ])
    ws = tour.load_waypoints(flat_site.folder, grid)
    assert [w.id for w in ws] == ["rover", "stop1", "stop2"]
    assert ws[0].cell == (9, 10)
    assert ws[1].cell == (0, 1)
    assert ws[2].cell == (19, 19)
    rover, stops = tour.split_waypoints(ws)
    assert rover.id == "rover" and [s.id for s in stops] == ["stop1", "stop2"]


def bad_feature(**props):
    base = {"id": "s", "name": "S", "kind": "stop"}
    base.update(props)
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10, 10]}, "properties": base}


@pytest.mark.parametrize("content,match", [
    ("{not json", "not valid JSON"),
    ("[]", "FeatureCollection"),
    ('{"features": 3}', "FeatureCollection"),
    (json.dumps({"features": [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": []},
                                "properties": {"id": "a", "kind": "stop"}}]}), "must be a Point"),
    (json.dumps({"features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": ["x", 1]},
                                "properties": {"id": "a", "kind": "stop"}}]}), "coordinates"),
    (json.dumps({"features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]},
                                "properties": {"kind": "stop"}}]}), "needs a text id"),
    (json.dumps({"features": [bad_feature(kind="base")]}), "kind must be"),
    (json.dumps({"features": [bad_feature(), bad_feature()]}), "appears twice"),
    (json.dumps({"features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [5000, 5]},
                                "properties": {"id": "far", "name": "Far", "kind": "stop"}}]}), "'far'.*outside the site"),
])
def test_bad_waypoint_files_fail_clearly(flat_site, content, match):
    (flat_site.folder / "waypoints.geojson").write_text(content, encoding="utf-8")
    with pytest.raises(RouteError, match=match):
        tour.load_waypoints(flat_site.folder, g.read_grid(flat_site.folder))


def test_missing_waypoints_file_named(flat_site):
    with pytest.raises(RouteError, match=r"waypoints\.geojson not found"):
        tour.load_waypoints(flat_site.folder, g.read_grid(flat_site.folder))


def test_needs_exactly_one_rover():
    stops = [wp("a", "stop", (5, 5)), wp("b", "stop", (5, 9))]
    with pytest.raises(RouteError, match="exactly one.*found 0"):
        tour.split_waypoints(stops)
    with pytest.raises(RouteError, match="exactly one.*found 2"):
        tour.split_waypoints([rover_at((1, 1)), wp("r2", "rover", (2, 2)), *stops])
    with pytest.raises(RouteError, match="at least one.*stop"):
        tour.split_waypoints([rover_at((1, 1))])
    rover, got = tour.split_waypoints([stops[0], rover_at((1, 1)), stops[1]])
    assert rover.id == "rover" and got == stops


# ---- blocked and unreachable stops -------------------------------------------
def test_stop_on_red_names_stop():
    hazard = np.zeros((20, 30), np.uint8)
    hazard[10, 15] = 2
    c = make_cost(hazard)
    rover, stop = rover_at((10, 2)), wp("stop2", "stop", (10, 15), name="Crater rim")
    with pytest.raises(RouteError) as e:
        tour.check_waypoints(c, rover, [stop], Searcher(c, 1.0))
    msg = str(e.value)
    assert "stop2" in msg and "Crater rim" in msg and "red hazard cell" in msg
    assert f"{stop.x:g}" in msg and f"{stop.y:g}" in msg


def test_rover_on_a_blocked_cell_names_the_rover():
    hazard = np.zeros((20, 30), np.uint8)
    hazard[10, 2] = 2
    c = make_cost(hazard)
    with pytest.raises(RouteError, match="rover 'rover'.*red hazard cell"):
        tour.check_waypoints(c, rover_at((10, 2)), [wp("s", "stop", (10, 9))], Searcher(c, 1.0))


@pytest.mark.parametrize("setup,reason", [
    ("slope", "slope over the limit"),
    ("buffer", "buffer around over-limit slopes"),
    ("nodata", "no DEM data"),
])
def test_block_reason_is_named(setup, reason):
    shape = (20, 30)
    slope = np.zeros(shape)
    dem = np.zeros(shape)
    if setup == "slope":
        slope[10, 15] = 25.0
    elif setup == "buffer":
        slope[10, 14] = 25.0                       # the stop is one cell away from the steep cell
    elif setup == "nodata":
        dem[10, 15] = np.nan
    c = make_cost(slope=slope, dem=dem, p=P.with_(cliff_buffer_m=5.0))
    assert reason in tour.block_reason(c, (10, 15))


def test_sealed_cell_reason_is_named():
    hazard = np.zeros((20, 30), np.uint8)
    hazard[9, 14] = hazard[10, 15] = 2             # blocked cells touching at a corner
    c = make_cost(hazard, p=P.with_(cliff_buffer_m=0))
    assert "sealed gap" in tour.block_reason(c, (9, 15))
    assert "red hazard cell" in tour.block_reason(c, (10, 15))
    assert tour.block_reason(c, (0, 0)) is None


def test_unreachable_stop_names_stop():
    hazard = np.zeros((20, 30), np.uint8)
    hazard[:, 15] = 2                              # a wall across the whole site
    c = make_cost(hazard)
    rover, stop = rover_at((10, 2)), wp("stop3", "stop", (10, 25), name="Far dune")
    with pytest.raises(RouteError) as e:
        tour.check_waypoints(c, rover, [stop], Searcher(c, 1.0))
    msg = str(e.value)
    assert "stop3" in msg and "Far dune" in msg and "cannot be reached" in msg


def test_plan_routes_fails_before_building_anything_on_a_bad_stop():
    hazard = np.zeros((20, 30), np.uint8)
    hazard[10, 15] = 2
    c = make_cost(hazard)
    with pytest.raises(RouteError, match="stop2"):
        tour.plan_routes(c, rover_at((10, 2)), [wp("stop1", "stop", (5, 9)), wp("stop2", "stop", (10, 15))], CFG)


# ---- stop order --------------------------------------------------------------
def line_site():
    """Flat 20 x 30 grid; rover at the west end of row 10; stops A, B, C further east."""
    c = make_cost()
    rover = rover_at((10, 0))
    a, b, mid = wp("A", "stop", (10, 20)), wp("B", "stop", (10, 5)), wp("C", "stop", (10, 12))
    return c, rover, [a, b, mid]


def brute_force_costs(searcher, rover, stops):
    return {
        tuple(s.id for s in perm): tour._tour_cost(searcher, rover, list(perm))
        for perm in itertools.permutations(stops)
    }


def test_as_listed_keeps_file_order():
    c, rover, stops = line_site()
    s = Searcher(c, 1.0)
    assert [x.id for x in tour.stop_order(s, rover, stops, "as_listed")] == ["A", "B", "C"]
    plan = tour.plan_routes(c, rover, stops, CFG, mode="as_listed")
    assert plan.mode == "as_listed" and [x.id for x in plan.order] == ["A", "B", "C"]
    assert all(r.order == ("A", "B", "C") for r in plan.routes.values())


def test_optimise_minimises_balanced_cost():
    c, rover, stops = line_site()
    s = Searcher(c, CFG.value("profiles.w_balanced"))
    costs = brute_force_costs(s, rover, stops)
    order = tuple(x.id for x in tour.stop_order(s, rover, stops, "optimise"))
    # Out along the line and back is optimal either way round; the two tie, so file order wins.
    assert costs[("A", "C", "B")] == pytest.approx(costs[("B", "C", "A")])
    assert order == ("A", "C", "B")
    assert costs[order] == pytest.approx(min(costs.values()))
    assert costs[order] < costs[("A", "B", "C")] - 1.0              # file order is clearly worse
    plan = tour.plan_routes(c, rover, stops, CFG, mode="optimise")
    assert plan.order and tuple(x.id for x in plan.order) == order
    assert all(r.order == order for r in plan.routes.values())      # one order for all three profiles


def test_optimise_uses_the_balanced_cost_not_distance():
    """A yellow patch makes the order that is shorter in metres worse in planning cost."""
    hazard = np.zeros((20, 30), np.uint8)
    hazard[3:17, 10:15] = 1
    c = make_cost(hazard)
    rover = rover_at((10, 2))
    stops = [wp("far", "stop", (10, 27)), wp("near", "stop", (2, 8))]
    s = Searcher(c, CFG.value("profiles.w_balanced"))
    costs = brute_force_costs(s, rover, stops)
    order = tuple(x.id for x in tour.stop_order(s, rover, stops, "optimise"))
    assert costs[order] == pytest.approx(min(costs.values()))


def test_tie_follows_file_order():
    c = make_cost()
    rover = rover_at((10, 15))
    left, right = wp("L", "stop", (10, 5)), wp("R", "stop", (10, 25))
    s = Searcher(c, 1.0)
    costs = brute_force_costs(s, rover, [left, right])
    assert costs[("L", "R")] == pytest.approx(costs[("R", "L")])     # a genuine tie
    assert [x.id for x in tour.stop_order(s, rover, [left, right], "optimise")] == ["L", "R"]
    assert [x.id for x in tour.stop_order(s, rover, [right, left], "optimise")] == ["R", "L"]


def test_three_way_tie_keeps_file_order():
    c = make_cost(shape=(21, 21))
    rover = rover_at((10, 10), shape=(21, 21))
    stops = [wp(i, "stop", cell, shape=(21, 21)) for i, cell in (("n", (4, 10)), ("e", (10, 16)), ("w", (10, 4)))]
    s = Searcher(c, 1.0)
    order = tour.stop_order(s, rover, stops, "optimise")
    costs = brute_force_costs(s, rover, stops)
    assert tour._tour_cost(s, rover, order) == pytest.approx(min(costs.values()))
    ties = [k for k, v in costs.items() if v == pytest.approx(min(costs.values()))]
    assert tuple(x.id for x in order) == min(ties, key=lambda k: [("n", "e", "w").index(i) for i in k])


def test_unknown_order_mode_rejected():
    c, rover, stops = line_site()
    with pytest.raises(ConfigError, match="stop order mode"):
        tour.stop_order(Searcher(c, 1.0), rover, stops, "random")


# ---- the three profile routes ------------------------------------------------
def yellow_band_site():
    """Rover west, stop east, a yellow band between them with green detours north and south."""
    hazard = np.zeros((20, 30), np.uint8)
    hazard[3:17, 10:15] = 1
    return make_cost(hazard), rover_at((10, 2)), [wp("stop1", "stop", (10, 27))]


def test_route_is_rover_to_rover_through_all_stops():
    c, rover, _ = yellow_band_site()
    stops = [wp("stop1", "stop", (10, 27)), wp("stop2", "stop", (2, 20)), wp("stop3", "stop", (17, 6))]
    plan = tour.plan_routes(c, rover, stops, CFG, mode="optimise")
    assert set(plan.routes) == {"fastest", "balanced", "safest"}
    for name, route in plan.routes.items():
        assert route.cells[0] == rover.cell and route.cells[-1] == rover.cell, name
        by_id = {s.id: s.cell for s in stops}
        at = -1
        for sid in route.order:                                     # stops come in the stated order
            at = route.cells.index(by_id[sid], at + 1)
        assert sorted(route.order) == sorted(by_id)
        assert [leg.from_id for leg in route.legs] == ["rover", *route.order]
        assert [leg.to_id for leg in route.legs] == [*route.order, "rover"]
        assert not any(c.blocked[rc] for rc in route.cells)
        steps = np.abs(np.diff(np.array(route.cells), axis=0))
        assert steps.max() == 1 and steps.sum(axis=1).min() >= 1     # neighbouring cells, no repeats
        assert route.distance_m == pytest.approx(sum(leg.path.distance_m for leg in route.legs))


def test_time_fastest_le_balanced_le_safest():
    c, rover, stops = yellow_band_site()
    r = tour.plan_routes(c, rover, stops, CFG).routes
    eps = 1e-9
    assert r["fastest"].physical_min <= r["balanced"].physical_min + eps
    assert r["balanced"].physical_min <= r["safest"].physical_min + eps
    assert r["fastest"].physical_min < r["safest"].physical_min - 0.1       # a real trade-off here


def test_risk_fastest_ge_balanced_ge_safest():
    c, rover, stops = yellow_band_site()
    r = tour.plan_routes(c, rover, stops, CFG).routes
    eps = 1e-9
    assert r["fastest"].risk_min >= r["balanced"].risk_min - eps
    assert r["balanced"].risk_min >= r["safest"].risk_min - eps
    assert r["fastest"].risk_min > r["safest"].risk_min + 0.1
    assert r["fastest"].yellow_min > 0 and r["safest"].yellow_min == 0.0


def test_profiles_use_the_configured_weights():
    c, rover, stops = yellow_band_site()
    r = tour.plan_routes(c, rover, stops, CFG).routes
    assert [r[n].w for n in ("fastest", "balanced", "safest")] == [0.0, 1.0, 5.0]
    assert [r[n].profile for n in ("fastest", "balanced", "safest")] == ["fastest", "balanced", "safest"]


def test_route_totals_sum_the_legs_and_split_risk():
    c, rover, stops = yellow_band_site()
    route = tour.plan_routes(c, rover, stops, CFG).routes["balanced"]
    assert route.physical_min == pytest.approx(sum(leg.path.physical_min for leg in route.legs))
    assert route.risk_min == pytest.approx(route.yellow_min + route.steep_min + route.near_red_min)


def test_plan_routes_from_files(red_wall_site):
    grid = g.read_grid(red_wall_site.folder)
    write_waypoints(red_wall_site.folder, [
        ("rover", "Rover", "rover", *grid.cell_centre(5, 5)),
        ("stop1", "East side", "stop", *grid.cell_centre(5, 15)),
    ])
    dem = g.load_dem(red_wall_site.folder, grid)
    c = cost.build(dem, g.load_hazard(red_wall_site.folder, grid), g.slope_deg(dem, grid.cell_m), grid, P)
    rover, stops = tour.split_waypoints(tour.load_waypoints(red_wall_site.folder, grid))
    plan = tour.plan_routes(c, rover, stops, CFG)
    for route in plan.routes.values():
        assert route.cells[0] == (5, 5) and (5, 15) in route.cells
        assert all(red_wall_site.hazard[rc] != 2 for rc in route.cells)


def test_wide_site_routes(wide_site):
    grid = g.read_grid(wide_site.folder)
    write_waypoints(wide_site.folder, [
        ("rover", "Rover", "rover", *grid.cell_centre(40, 10)),
        ("stop1", "A", "stop", *grid.cell_centre(10, 100)),
    ])
    dem = g.load_dem(wide_site.folder, grid)
    c = cost.build(dem, g.load_hazard(wide_site.folder, grid), g.slope_deg(dem, grid.cell_m), grid, P)
    rover, stops = tour.split_waypoints(tour.load_waypoints(wide_site.folder, grid))
    plan = tour.plan_routes(c, rover, stops, CFG)
    assert plan.routes["balanced"].distance_m > 90 * 10.0
    assert math.isclose(plan.routes["fastest"].distance_m, plan.routes["balanced"].distance_m)


def random_site(seed):
    rng = np.random.RandomState(seed)
    hazard = np.zeros((20, 30), np.uint8)
    for _ in range(5):
        r, col = rng.randint(2, 16), rng.randint(2, 26)
        hazard[r:r + rng.randint(3, 7), col:col + rng.randint(3, 7)] = 1
    cells = [(int(rng.randint(0, 20)), int(rng.randint(0, 30))) for _ in range(4)]
    return make_cost(hazard), cells


def test_stop_order_is_chosen_on_the_balanced_weight():
    """On this site the best order at w = 0 differs from the best at w = 1 (the balanced weight)."""
    c, cells = random_site(25)
    rover = rover_at(cells[0])
    stops = [wp("A", "stop", cells[1]), wp("B", "stop", cells[2]), wp("C", "stop", cells[3])]
    fastest_s, balanced_s = Searcher(c, 0.0), Searcher(c, CFG.value("profiles.w_balanced"))
    o_fast = tuple(s.id for s in tour.stop_order(fastest_s, rover, stops, "optimise"))
    o_bal = tuple(s.id for s in tour.stop_order(balanced_s, rover, stops, "optimise"))
    assert o_fast != o_bal
    costs = brute_force_costs(balanced_s, rover, stops)
    assert costs[o_bal] == pytest.approx(min(costs.values()))
    assert costs[o_fast] > costs[o_bal] + 1e-6                      # the fastest order is worse here
    plan = tour.plan_routes(c, rover, stops, CFG, mode="optimise")
    assert tuple(s.id for s in plan.order) == o_bal
    assert all(r.order == o_bal for r in plan.routes.values())


def test_waypoint_without_a_name_uses_its_id(flat_site):
    grid = g.read_grid(flat_site.folder)
    feature = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [12.5, 12.5]},
               "properties": {"id": "stopX", "kind": "stop"}}
    (flat_site.folder / "waypoints.geojson").write_text(json.dumps({"features": [feature]}), encoding="utf-8")
    (wp_loaded,) = tour.load_waypoints(flat_site.folder, grid)
    assert wp_loaded.name == "stopX"


# ---- one search per waypoint -------------------------------------------------
@pytest.fixture
def search_counter(monkeypatch):
    import search

    real = search.MCP_Geometric
    count = {"n": 0}

    class Counting(real):
        def __init__(self, *args, **kwargs):
            count["n"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(search, "MCP_Geometric", Counting)
    return count


def spread_stops(n, shape=(20, 30)):
    cells = [(2, 3), (15, 8), (4, 20), (17, 26), (9, 14), (1, 27), (18, 2), (11, 6), (6, 9), (13, 22)]
    return [wp(f"s{i}", "stop", cells[i], shape=shape) for i in range(n)]


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6])
def test_optimise_runs_one_search_per_waypoint(search_counter, n):
    c = make_cost()
    rover, stops = rover_at((10, 0)), spread_stops(n)
    s = Searcher(c, 1.0)
    tour.stop_order(s, rover, stops, "optimise")
    assert search_counter["n"] == n + 1                      # rover and every stop, once each, not once per order
    tour.stop_order(s, rover, stops, "optimise")
    assert search_counter["n"] == n + 1                      # and cached afterwards


def test_plan_routes_search_count_is_one_per_waypoint_per_profile(search_counter):
    c = make_cost()
    rover, stops = rover_at((10, 0)), spread_stops(5)
    tour.plan_routes(c, rover, stops, CFG, mode="optimise")
    assert search_counter["n"] == 3 * 6                      # three profiles x (rover + 5 stops)


def test_cost_matrix_matches_the_individual_costs():
    c = make_cost()
    rover, stops = rover_at((10, 0)), spread_stops(3)
    s = Searcher(c, 1.0)
    m = tour.cost_matrix(s, [rover, *stops])
    ws = [rover, *stops]
    for i, a in enumerate(ws):
        for j, b in enumerate(ws):
            assert m[i][j] == s.planning_cost(a.cell, b.cell)
    assert all(m[i][i] == 0 for i in range(4))
    assert m[0][1] == pytest.approx(m[1][0])


# ---- the optimise limit ------------------------------------------------------
def cfg_with(**values):
    import copy
    from config import Config
    raw = copy.deepcopy(CFG.raw)
    for key, v in values.items():
        section, name = key.split("__")
        raw[section][name]["value"] = v
    return Config.from_dict(raw)


def test_optimise_over_the_limit_falls_back_to_as_listed_with_a_warning():
    c = make_cost()
    rover, stops = rover_at((10, 0)), spread_stops(4)
    cfg = cfg_with(timeline__optimise_max_stops=3)
    plan = tour.plan_routes(c, rover, stops, cfg, mode="optimise")
    assert plan.mode == "as_listed" and plan.requested_mode == "optimise"
    assert [s.id for s in plan.order] == ["s0", "s1", "s2", "s3"]
    assert len(plan.warnings) == 1
    assert "optimise" in plan.warnings[0] and "4 stops" in plan.warnings[0] and "limit of 3" in plan.warnings[0]
    assert all(r.order == ("s0", "s1", "s2", "s3") for r in plan.routes.values())


def test_optimise_at_the_limit_still_optimises():
    c = make_cost()
    rover, stops = rover_at((10, 0)), spread_stops(4)
    cfg = cfg_with(timeline__optimise_max_stops=4)
    plan = tour.plan_routes(c, rover, stops, cfg, mode="optimise")
    assert plan.mode == "optimise" and plan.warnings == ()
    balanced = Searcher(c, 1.0)
    costs = brute_force_costs(balanced, rover, stops)
    assert costs[tuple(s.id for s in plan.order)] == pytest.approx(min(costs.values()))


def test_as_listed_over_the_limit_has_no_warning():
    c = make_cost()
    rover, stops = rover_at((10, 0)), spread_stops(4)
    plan = tour.plan_routes(c, rover, stops, cfg_with(timeline__optimise_max_stops=2), mode="as_listed")
    assert plan.mode == "as_listed" and plan.requested_mode == "as_listed" and plan.warnings == ()


def test_the_default_limit_is_8_and_9_stops_fall_back(search_counter):
    c = make_cost()
    rover = rover_at((10, 0))
    assert CFG.value("timeline.optimise_max_stops") == 8
    plan9 = tour.plan_routes(c, rover, spread_stops(9), CFG, mode="optimise")
    assert plan9.mode == "as_listed" and plan9.warnings and "limit of 8" in plan9.warnings[0]
    plan8 = tour.plan_routes(c, rover, spread_stops(8), CFG, mode="optimise")
    assert plan8.mode == "optimise" and plan8.warnings == ()


def test_the_plan_mode_defaults_to_the_config_and_records_it():
    c = make_cost()
    plan = tour.plan_routes(c, rover_at((10, 0)), spread_stops(3), CFG)
    assert plan.mode == "as_listed" and plan.requested_mode == "as_listed" and plan.warnings == ()
