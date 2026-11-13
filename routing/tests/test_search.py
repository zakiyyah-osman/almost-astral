import math

import numpy as np
import pytest

import cost
import grid as g
from config import ConfigError, load_config
from cost import Params
from search import NoPath, Searcher, fully_connected, summarise

CFG = load_config()
P = Params.from_config(CFG)
CELL = 5.0


def make_cost(hazard=None, slope=None, shape=(9, 9), cell=CELL, p=P):
    hazard = np.zeros(shape, np.uint8) if hazard is None else hazard
    slope = np.zeros(shape) if slope is None else slope
    grid = g.Grid(shape[1], shape[0], cell)
    return cost.build(np.zeros(shape), hazard, slope, grid, p)


def test_straight_on_open_flat_grid():
    c = make_cost()
    path = Searcher(c, 1.0).path((4, 0), (4, 8))
    assert list(path.cells) == [(4, col) for col in range(9)]
    assert path.distance_m == pytest.approx(40.0)


def test_flat_5m_step_is_0_111_min():
    path = Searcher(make_cost(), 0.0).path((4, 3), (4, 4))
    assert path.distance_m == pytest.approx(5.0)
    assert path.physical_min == pytest.approx(5.0 / 45.0)
    assert path.physical_min == pytest.approx(0.111, abs=0.0005)


def test_diagonal_is_root2_longer():
    s = Searcher(make_cost(), 0.0)
    straight, diagonal = s.path((4, 3), (4, 4)), s.path((3, 3), (4, 4))
    assert list(diagonal.cells) == [(3, 3), (4, 4)]
    assert diagonal.distance_m == pytest.approx(math.sqrt(2) * straight.distance_m)
    assert diagonal.physical_min == pytest.approx(math.sqrt(2) * straight.physical_min)


def test_goes_round_red_wall(red_wall_site):
    grid = g.read_grid(red_wall_site.folder)
    dem = g.load_dem(red_wall_site.folder, grid)
    c = cost.build(dem, g.load_hazard(red_wall_site.folder, grid), g.slope_deg(dem, grid.cell_m), grid, P)
    path = Searcher(c, 1.0).path((5, 5), (5, 15))
    assert path.distance_m > 10 * grid.cell_m                    # longer than the straight line
    for rc in path.cells:
        assert not c.blocked[rc]
        assert red_wall_site.hazard[rc] != 2
    crossing = [rc for rc in path.cells if rc[1] == 10]
    assert crossing and all(r >= 15 for r, _ in crossing)        # through the gap below the wall


def test_unreachable_reported():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[:, 4] = 2                                             # a wall across the whole grid
    c = make_cost(hazard)
    s = Searcher(c, 1.0)
    assert not s.tree((4, 0)).reachable((4, 8))
    assert math.isinf(s.planning_cost((4, 0), (4, 8)))
    with pytest.raises(NoPath, match="cannot be reached"):
        s.path((4, 0), (4, 8))
    assert s.path((4, 0), (0, 3)).cells[-1] == (0, 3)            # the same side is fine


def test_blocked_start_and_end_reported():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[4, 4] = 2
    s = Searcher(make_cost(hazard), 1.0)
    with pytest.raises(NoPath, match="blocked"):
        s.path((4, 4), (0, 0))
    with pytest.raises(NoPath, match="blocked"):
        s.path((0, 0), (4, 4))
    with pytest.raises(NoPath, match="outside"):
        s.tree((20, 20))


def corridor():
    """A 1-wide corridor along row 2 with a yellow stretch in the middle, walls of red."""
    hazard = np.full((5, 12), 2, np.uint8)
    hazard[2, :] = 0
    hazard[2, 4:7] = 1
    return make_cost(hazard, shape=(5, 12))


def test_time_not_changed_by_w_on_same_path():
    c = corridor()
    paths = [Searcher(c, w).path((2, 0), (2, 11)) for w in (0.0, 1.0, 5.0, 50.0)]
    assert all(p.cells == paths[0].cells for p in paths)         # the corridor forces one path
    assert all(p.physical_min == paths[0].physical_min for p in paths)
    assert all(p.risk_min == paths[0].risk_min for p in paths)
    assert paths[0].yellow_min > 0
    # The same path summarised again gives the same numbers whatever w the search used.
    assert summarise(c, paths[0].cells) == paths[0]


def test_planning_cost_equals_physical_plus_w_times_risk():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[2:7, 3:5] = 1
    hazard[8, 0] = 2
    c = make_cost(hazard)
    for w in (0.0, 0.5, 1.0, 5.0):
        s = Searcher(c, w)
        path = s.path((4, 0), (4, 8))
        planned = s.planning_cost((4, 0), (4, 8))
        assert planned == pytest.approx(path.physical_min + w * path.risk_min, rel=1e-12)


def test_risk_parts_add_up():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[3:6, 3:5] = 1
    hazard[0, 6] = 2
    c = make_cost(hazard)
    path = Searcher(c, 3.0).path((4, 0), (0, 8))
    assert path.risk_min == pytest.approx(path.yellow_min + path.steep_min + path.near_red_min)
    assert path.steep_min == 0.0                                 # the steep term is off by default


def test_physical_time_follows_slope():
    slope = np.full((9, 9), math.degrees(math.atan(0.1)))
    path = Searcher(make_cost(slope=slope), 0.0).path((4, 3), (4, 4))
    assert path.physical_min == pytest.approx(5.0 / (45.0 * math.exp(-0.35)))


def test_same_cell_path_is_empty():
    path = Searcher(make_cost(), 1.0).path((4, 4), (4, 4))
    assert path.cells == ((4, 4),) and path.distance_m == 0 and path.physical_min == 0


def test_trees_are_cached():
    s = Searcher(make_cost(), 1.0)
    assert s.tree((1, 1)) is s.tree((1, 1))
    assert s.tree((1, 1)) is not s.tree((1, 2))


def test_four_connected_search_uses_manhattan_steps():
    s8, s4 = Searcher(make_cost(), 0.0, 8), Searcher(make_cost(), 0.0, 4)
    assert s8.path((0, 0), (4, 4)).distance_m == pytest.approx(4 * math.sqrt(2) * CELL)
    assert s4.path((0, 0), (4, 4)).distance_m == pytest.approx(8 * CELL)


@pytest.mark.parametrize("bad", [5, 6, 0, None, "8", 8.5])
def test_bad_connectivity_rejected(bad):
    with pytest.raises(ConfigError, match="connectivity"):
        fully_connected(bad)


def test_summary_rejects_a_bad_path():
    c = make_cost(np.where(np.arange(81).reshape(9, 9) == 40, 2, 0).astype(np.uint8))
    with pytest.raises(ValueError, match="neighbouring"):
        summarise(c, [(0, 0), (0, 2)])
    with pytest.raises(ValueError, match="neighbouring"):
        summarise(c, [(0, 0), (0, 0)])
    with pytest.raises(ValueError, match="blocked"):
        summarise(c, [(4, 3), (4, 4)])
    with pytest.raises(ValueError, match="at least one"):
        summarise(c, [])


def test_search_uses_the_cell_size_in_metres():
    path = Searcher(make_cost(cell=10.0), 0.0).path((4, 3), (4, 4))
    assert path.distance_m == pytest.approx(10.0)
    assert path.physical_min == pytest.approx(10.0 / 45.0)


def test_wide_site_search(wide_site):
    grid = g.read_grid(wide_site.folder)
    dem = g.load_dem(wide_site.folder, grid)
    c = cost.build(dem, g.load_hazard(wide_site.folder, grid), g.slope_deg(dem, grid.cell_m), grid, P)
    path = Searcher(c, 1.0).path((40, 0), (40, 119))
    assert path.distance_m == pytest.approx(119 * 10.0)


def test_edge_cost_averages_the_two_cells():
    """Each step costs L x (rate_a + rate_b) / 2, so a path that starts yellow and ends green
    counts half of each end cell, not all of one."""
    hazard = np.zeros((9, 9), np.uint8)
    hazard[4, 3] = 1
    c = make_cost(hazard, p=P.with_(near_red_rate_max=0.0))
    tr = 1 / 45.0
    forward = Searcher(c, 0.0).path((4, 3), (4, 4))
    backward = Searcher(c, 0.0).path((4, 4), (4, 3))
    assert forward.yellow_min == pytest.approx(5.0 * (tr * 1.0 + 0.0) / 2)
    assert backward.yellow_min == pytest.approx(forward.yellow_min)          # same either way round
    assert forward.risk_min == pytest.approx(forward.yellow_min)


def test_edge_cost_averages_cells_with_different_slopes():
    slope = np.zeros((9, 9))
    slope[4, 4] = math.degrees(math.atan(0.2))
    path = Searcher(make_cost(slope=slope), 0.0).path((4, 3), (4, 4))
    flat, steep = 1 / 45.0, 1 / (45.0 * math.exp(-0.7))
    assert path.physical_min == pytest.approx(5.0 * (flat + steep) / 2)
