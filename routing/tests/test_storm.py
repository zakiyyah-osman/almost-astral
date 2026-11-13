import math

import numpy as np
import pytest

import cost
import grid as g
import shelter
import storm
import tour
from config import load_config
from cost import Params
from tour import Waypoint

CFG = load_config()
P = Params.from_config(CFG)
CELL = 5.0
STOP_MIN = CFG.value("timeline.stop_min_default")
INGRESS = CFG.value("timeline.ingress_min")
SPACING = CFG.value("storm.sample_spacing_m")


def make_cost(hazard=None, shape=(20, 30)):
    hazard = np.zeros(shape, np.uint8) if hazard is None else hazard
    return cost.build(np.zeros(shape), hazard, np.zeros(shape), g.Grid(shape[1], shape[0], CELL), P)


def wp(wid, kind, cell, shape=(20, 30)):
    x, y = g.Grid(shape[1], shape[0], CELL).cell_centre(*cell)
    return Waypoint(wid, wid, kind, x, y, cell)


def scenario(hazard=None):
    c = make_cost(hazard)
    rover = wp("rover", "rover", (10, 2))
    stops = [wp("stop1", "stop", (3, 20)), wp("stop2", "stop", (17, 26))]
    plan = tour.plan_routes(c, rover, stops, CFG)
    sh = shelter.shelter_time(c, rover.cell, INGRESS, 8)
    route = plan.routes["balanced"]
    return c, rover, stops, route, sh, storm.storm_replan(c, route, sh, SPACING, STOP_MIN)


def test_samples_include_every_stop():
    c, rover, stops, route, sh, rep = scenario()
    by_stop = {p.stop: p for p in rep.points if p.stop}
    assert set(by_stop) == {"stop1", "stop2"}
    for s in stops:
        assert by_stop[s.id].cell == s.cell
        assert (by_stop[s.id].x, by_stop[s.id].y) == (s.x, s.y)
    # The rover at the start is sampled too.
    assert rep.points[0].cell == rover.cell and rep.points[0].route_distance_m == 0.0


def test_samples_are_spaced_along_the_route():
    c, rover, stops, route, sh, rep = scenario()
    clock = tour.route_clock(c, route, STOP_MIN)
    spaced = [p for p in rep.points if p.stop is None]
    d = [p.route_distance_m for p in rep.points]
    assert d == sorted(d) and len(set(d)) == len(d)
    for k, p in enumerate(spaced):                 # each is within half a step of a multiple of the spacing
        nearest = round(p.route_distance_m / SPACING) * SPACING
        assert abs(p.route_distance_m - nearest) <= CELL * math.sqrt(2) / 2 + 1e-9
    assert rep.sample_spacing_m == SPACING
    assert len(rep.points) >= int(clock.distance_m[-1] // SPACING)


def test_return_path_ends_at_rover():
    c, rover, stops, route, sh, rep = scenario()
    for p in rep.points:
        assert p.path[0] == p.cell and p.path[-1] == rover.cell
        assert not any(c.blocked[rc] for rc in p.path)
        steps = np.abs(np.diff(np.array(p.path), axis=0)) if len(p.path) > 1 else np.zeros((0, 2))
        assert (steps.max(initial=0) <= 1)


def test_return_min_equals_shelter_time():
    c, rover, stops, route, sh, rep = scenario()
    for p in rep.points:
        assert p.return_min == sh.minutes[p.cell]
        back = tour_path_minutes(c, p.path)
        assert p.return_min == pytest.approx(back + INGRESS)
    assert rep.points[0].return_min == INGRESS


def tour_path_minutes(c, cells):
    from search import summarise
    return summarise(c, cells).physical_min


def test_return_distance_matches_the_path():
    c, rover, stops, route, sh, rep = scenario()
    from search import summarise
    for p in rep.points:
        assert p.return_distance_m == pytest.approx(summarise(c, p.path).distance_m)


def test_worst_point_is_maximum():
    c, rover, stops, route, sh, rep = scenario()
    mins = [p.return_min for p in rep.points]
    assert mins[rep.worst] == max(mins)
    assert rep.worst == mins.index(max(mins))              # the first one on a tie
    assert max(mins) > INGRESS + 2                          # the far points really are a walk from the rover


def test_elapsed_includes_the_time_spent_at_earlier_stops():
    c, rover, stops, route, sh, rep = scenario()
    clock = tour.route_clock(c, route, STOP_MIN)
    el = [p.elapsed_min for p in rep.points]
    assert el == sorted(el)
    assert rep.points[0].elapsed_min == 0.0
    arrival1 = next(p for p in rep.points if p.stop == "stop1")
    after = [p for p in rep.points if p.route_distance_m > arrival1.route_distance_m]
    assert arrival1.elapsed_min == pytest.approx(clock.walk_min[clock.arrival_index["stop1"]])   # arrival: not yet
    nxt = after[0]
    walked = nxt.elapsed_min - arrival1.elapsed_min
    assert walked >= STOP_MIN                              # leaving the stop costs the stop time
    final = [p for p in rep.points if p.route_distance_m > next(q for q in rep.points if q.stop == "stop2").route_distance_m]
    if final:
        assert final[-1].elapsed_min >= 2 * STOP_MIN


def test_return_path_goes_round_a_red_wall():
    hazard = np.zeros((20, 30), np.uint8)
    hazard[2:16, 12] = 2                                   # wall with gaps at the top and bottom
    c, rover, stops, route, sh, rep = scenario(hazard)
    far = next(p for p in rep.points if p.stop == "stop1")
    assert far.return_distance_m > math.hypot(far.cell[0] - rover.cell[0], far.cell[1] - rover.cell[1]) * CELL
    assert all(hazard[rc] != 2 for p in rep.points for rc in p.path)


def test_spacing_changes_the_number_of_samples():
    c, rover, stops, route, sh, _ = scenario()
    fine = storm.storm_replan(c, route, sh, 25.0, STOP_MIN)
    coarse = storm.storm_replan(c, route, sh, 200.0, STOP_MIN)
    assert len(fine.points) > len(coarse.points) >= 3       # coarse still has the start and both stops
    assert {p.stop for p in coarse.points} >= {"stop1", "stop2"}


def test_sample_indices_snap_to_the_nearest_cell():
    d = np.array([0.0, 5.0, 12.07, 17.07, 22.07, 27.07])
    assert storm.sample_indices(d, 10.0).tolist() == [0, 2, 4]          # targets 0, 10, 20
    assert storm.sample_indices(d, 100.0).tolist() == [0]


def test_no_shelter_value_is_nan_on_the_route():
    c, rover, stops, route, sh, rep = scenario()
    assert all(np.isfinite(p.return_min) for p in rep.points)
