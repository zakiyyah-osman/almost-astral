import numpy as np
import pytest

import cost
import grid as g
from config import ConfigError, load_config
from cost import BLOCKED, Params

CFG = load_config()
P = Params.from_config(CFG)
CELL = 5.0


def mask(hazard=None, slope=None, dem=None, p=P, shape=(9, 9), cell=CELL):
    hazard = np.zeros(shape, np.uint8) if hazard is None else hazard
    slope = np.zeros(shape) if slope is None else slope
    dem = np.zeros(shape) if dem is None else dem
    return cost.hard_mask(dem, slope, hazard, cell, p)


def blocked_cells(m):
    return {tuple(rc) for rc in np.argwhere(m).tolist()}


# ---- parameters --------------------------------------------------------------
def test_params_come_from_the_config():
    assert P.slope_max_deg == 20 and P.cliff_buffer_m == 5 and P.v_flat_kmh == 2.7
    assert P.steep_rate_max == 0.0 and P.yellow_rate == 1.0
    assert P.with_(slope_max_deg=25).slope_max_deg == 25
    assert Params.from_config(CFG, v_flat_kmh=3.4).v_flat_kmh == 3.4
    with pytest.raises(ConfigError):
        Params.from_config(CFG, v_flat=3.4)


def test_steep_onset_must_be_below_the_slope_limit():
    with pytest.raises(ConfigError, match="steep_onset_deg"):
        P.with_(steep_onset_deg=20)
    with pytest.raises(ConfigError, match="steep_onset_deg"):
        P.with_(slope_max_deg=8)


# ---- hard mask ---------------------------------------------------------------
def test_red_blocked():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[2, 3] = 2
    hazard[6, 6] = 1                              # yellow is not blocked
    m = mask(hazard, p=P.with_(cliff_buffer_m=0))
    assert blocked_cells(m) == {(2, 3)}


def test_over_limit_slope_blocked():
    slope = np.zeros((9, 9))
    slope[4, 4] = 20.5
    slope[1, 1] = 20.0                            # exactly at the limit is allowed
    m = mask(slope=slope, p=P.with_(cliff_buffer_m=0))
    assert blocked_cells(m) == {(4, 4)}
    assert not mask(slope=slope, p=P.with_(cliff_buffer_m=0, slope_max_deg=25)).any()


def test_buffer_ring_blocked():
    slope = np.zeros((9, 9))
    slope[4, 4] = 30.0
    # One cell wide (buffer = cell size): the four cells at 5 m, not the diagonals at 7.07 m.
    m = mask(slope=slope, p=P.with_(cliff_buffer_m=5.0))
    assert blocked_cells(m) == {(4, 4), (3, 4), (5, 4), (4, 3), (4, 5)}
    # 10 m: adds the diagonals (7.07 m) and the cells two steps away in line (10 m), not (2, 1) at 11.2 m.
    m = mask(slope=slope, p=P.with_(cliff_buffer_m=10.0))
    assert (3, 3) in blocked_cells(m) and (2, 4) in blocked_cells(m) and (4, 6) in blocked_cells(m)
    assert (2, 3) not in blocked_cells(m) and (2, 5) not in blocked_cells(m)
    # The buffer follows cell_m, not the cell count.
    m = mask(slope=slope, p=P.with_(cliff_buffer_m=10.0), cell=10.0)
    assert blocked_cells(m) == {(4, 4), (3, 4), (5, 4), (4, 3), (4, 5)}


def test_buffer_below_cell_size_has_no_effect():
    slope = np.zeros((9, 9))
    slope[4, 4] = 30.0
    m = mask(slope=slope, p=P.with_(cliff_buffer_m=4.9))
    assert blocked_cells(m) == {(4, 4)}


def test_buffer_zero_disables():
    slope = np.zeros((9, 9))
    slope[4, 4] = 30.0
    m = mask(slope=slope, p=P.with_(cliff_buffer_m=0))
    assert blocked_cells(m) == {(4, 4)}


def test_buffer_does_nothing_without_steep_cells():
    assert not mask(p=P.with_(cliff_buffer_m=50.0)).any()


def test_buffer_reasons_are_separate():
    slope = np.zeros((9, 9))
    slope[4, 4] = 30.0
    r = cost.hard_constraints(np.zeros((9, 9)), slope, np.zeros((9, 9), np.uint8), CELL, P)
    assert blocked_cells(r["slope"]) == {(4, 4)}
    assert blocked_cells(r["buffer"]) == {(3, 4), (5, 4), (4, 3), (4, 5)}


def test_diagonal_gap_sealed():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[4, 4] = 2
    hazard[5, 5] = 2                              # blocked cells touching at a corner
    m = mask(hazard, p=P.with_(cliff_buffer_m=0))
    assert blocked_cells(m) == {(4, 4), (5, 5), (4, 5), (5, 4)}
    r = cost.hard_constraints(np.zeros((9, 9)), np.zeros((9, 9)), hazard, CELL, P.with_(cliff_buffer_m=0))
    assert blocked_cells(r["sealed"]) == {(4, 5), (5, 4)}
    # The other diagonal too.
    hazard = np.zeros((9, 9), np.uint8)
    hazard[4, 5] = 2
    hazard[5, 4] = 2
    assert blocked_cells(mask(hazard, p=P.with_(cliff_buffer_m=0))) == {(4, 4), (5, 5), (4, 5), (5, 4)}


def test_single_blocked_cell_and_straight_walls_are_not_sealed():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[4, 4] = 2
    assert blocked_cells(mask(hazard, p=P.with_(cliff_buffer_m=0))) == {(4, 4)}
    hazard[:, 6] = 2                               # a straight wall
    assert blocked_cells(mask(hazard, p=P.with_(cliff_buffer_m=0))) == {(4, 4)} | {(r, 6) for r in range(9)}


def test_sealing_is_not_applied_twice():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[2, 2] = hazard[3, 3] = hazard[4, 4] = 2    # a diagonal line of three
    m = blocked_cells(mask(hazard, p=P.with_(cliff_buffer_m=0)))
    assert m == {(2, 2), (3, 3), (4, 4), (2, 3), (3, 2), (3, 4), (4, 3)}


def test_one_wide_corridor_with_a_bend_is_not_cut():
    hazard = np.full((7, 7), 2, np.uint8)
    for rc in [(5, 1), (4, 1), (3, 1), (3, 2), (3, 3), (2, 3), (1, 3)]:
        hazard[rc] = 0
    m = mask(hazard, p=P.with_(cliff_buffer_m=0), shape=(7, 7))
    for rc in [(5, 1), (4, 1), (3, 1), (3, 2), (3, 3), (2, 3), (1, 3)]:
        assert not m[rc], rc


def test_nan_dem_cell_is_blocked_even_when_slope_is_finite():
    dem = np.zeros((9, 9))
    dem[4, 4] = np.nan
    m = mask(dem=dem, slope=np.zeros((9, 9)), p=P.with_(cliff_buffer_m=0))
    assert blocked_cells(m) == {(4, 4)}


def test_nan_slope_cell_is_blocked_even_when_dem_is_finite():
    slope = np.zeros((9, 9))
    slope[2, 6] = np.nan
    m = mask(dem=np.zeros((9, 9)), slope=slope, p=P.with_(cliff_buffer_m=0))
    assert blocked_cells(m) == {(2, 6)}


def test_nan_cells_from_a_real_dem_are_blocked_with_their_neighbours(tmp_path):
    """The DEM no-data cell and the four neighbours whose slope is NaN are all blocked."""
    dem = np.zeros((9, 9), np.float32)
    dem[4, 4] = np.nan
    site = __import__("conftest").write_site(tmp_path / "nan", dem, np.zeros((9, 9), np.uint8), CELL)
    grid = g.read_grid(site.folder)
    d = g.load_dem(site.folder, grid)
    s = g.slope_deg(d, grid.cell_m)
    c = cost.build(d, g.load_hazard(site.folder, grid), s, grid, P.with_(cliff_buffer_m=0))
    # The plus shape only: a diagonal cell such as (3, 3) has a blocked cell on its own
    # diagonal ((4, 4)), so there is no gap to squeeze through and it stays free.
    assert blocked_cells(c.blocked) == {(4, 4), (3, 4), (5, 4), (4, 3), (4, 5)}
    assert c.reasons["nodata"].sum() == 5
    assert not np.isnan(c.time_rate).any()


def test_array_shapes_must_agree():
    with pytest.raises(g.GridError, match="one shape"):
        cost.hard_mask(np.zeros((4, 4)), np.zeros((4, 5)), np.zeros((4, 4), np.uint8), CELL, P)


# ---- risk rate ---------------------------------------------------------------
def risk(hazard=None, slope=None, p=P, shape=(9, 9), cell=CELL):
    hazard = np.zeros(shape, np.uint8) if hazard is None else hazard
    slope = np.zeros(shape) if slope is None else slope
    return cost.risk_components(hazard, slope, cell, p)


def test_yellow_rate():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[3, 3] = 1
    parts = risk(hazard)
    assert parts["yellow"][3, 3] == 1.0 and parts["yellow"].sum() == 1.0
    assert risk(hazard, p=P.with_(yellow_rate=2.5))["yellow"][3, 3] == 2.5
    assert cost.risk_rate(hazard, np.zeros((9, 9)), CELL, P)[3, 3] == 1.0


def test_steep_ramp_zero_at_onset_full_at_limit():
    p = P.with_(steep_rate_max=0.8)                # the config default is 0, so set one here
    slope = np.array([[0.0, 5.0, 10.0, 12.5, 15.0, 17.5, 20.0, 25.0, np.nan]])
    steep = risk(np.zeros((1, 9), np.uint8), slope, p, shape=(1, 9))["steep"][0]
    assert steep[:3] == pytest.approx([0.0, 0.0, 0.0])          # up to the onset
    assert steep[3] == pytest.approx(0.8 * 0.25)
    assert steep[4] == pytest.approx(0.8 * 0.5)
    assert steep[5] == pytest.approx(0.8 * 0.75)
    assert steep[6] == pytest.approx(0.8)                        # full at the limit
    assert steep[7] == pytest.approx(0.8)                        # clipped above it
    assert steep[8] == 0.0                                       # NaN slope: blocked elsewhere


def test_steep_term_is_off_by_default():
    slope = np.full((9, 9), 15.0)
    assert not risk(slope=slope)["steep"].any()


def test_steep_ramp_follows_the_limit():
    p = P.with_(steep_rate_max=1.0, slope_max_deg=30)
    steep = risk(slope=np.full((9, 9), 20.0), p=p)["steep"]
    assert steep[0, 0] == pytest.approx(0.5)


def test_near_red_zero_at_radius():
    hazard = np.zeros((1, 9), np.uint8)
    hazard[0, 0] = 2
    near = risk(hazard, shape=(1, 9))["near_red"][0]
    # cell 5 m, radius 15 m, rate 1: d = 0, 5, 10, 15, 20 m
    assert near[0] == pytest.approx(1.0)
    assert near[1] == pytest.approx(1 - 5 / 15)
    assert near[2] == pytest.approx(1 - 10 / 15)
    assert near[3] == 0.0                                        # exactly at the radius
    assert near[4:].tolist() == [0.0] * 5
    assert risk(hazard, p=P.with_(near_red_rate_max=0.5), shape=(1, 9))["near_red"][0, 1] == pytest.approx(0.5 * 2 / 3)


def test_near_red_uses_metres_not_cells():
    hazard = np.zeros((1, 9), np.uint8)
    hazard[0, 0] = 2
    near = risk(hazard, shape=(1, 9), cell=10.0)["near_red"][0]
    assert near[1] == pytest.approx(1 - 10 / 15)
    assert near[2] == 0.0


def test_near_red_is_zero_without_red_cells():
    assert not risk()["near_red"].any()


def test_risk_parts_add():
    hazard = np.zeros((1, 9), np.uint8)
    hazard[0, 0] = 2
    hazard[0, 1] = 1
    r = cost.risk_rate(hazard, np.zeros((1, 9)), CELL, P)
    assert r[0, 1] == pytest.approx(1.0 + (1 - 5 / 15))


# ---- time rate and planning cost ---------------------------------------------
def make_cost(hazard=None, slope=None, p=P, shape=(9, 9)):
    hazard = np.zeros(shape, np.uint8) if hazard is None else hazard
    slope = np.zeros(shape) if slope is None else slope
    return cost.build(np.zeros(shape), hazard, slope, g.Grid(shape[1], shape[0], CELL), p)


def test_flat_rate_is_0_0222_min_per_m():
    c = make_cost()
    assert c.time_rate[4, 4] == pytest.approx(1 / 45.0)
    assert c.time_rate[4, 4] == pytest.approx(0.0222, abs=0.00005)
    assert np.all(c.time_rate == c.time_rate[0, 0])


def test_rate_on_a_slope_uses_the_walking_model():
    slope = np.full((9, 9), np.degrees(np.arctan(0.1)))
    c = make_cost(slope=slope)
    assert c.time_rate[4, 4] == pytest.approx(1 / (45.0 * np.exp(-0.35)))


def test_blocked_cells_are_negative():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[4, 4] = 2
    hazard[1, 1] = 1
    c = make_cost(hazard)
    assert c.time_rate[4, 4] == BLOCKED < 0
    assert c.planning_rate(1.0)[4, 4] == BLOCKED
    assert c.planning_rate(0.0)[4, 4] == BLOCKED
    free = ~c.blocked
    assert (c.time_rate[free] > 0).all() and (c.planning_rate(5.0)[free] > 0).all()
    assert c.time_rate[1, 1] > 0                                 # yellow is passable
    assert (c.risk_rate[c.blocked] == 0).all()


def test_w_zero_cost_equals_time_rate():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[2:5, 2:5] = 1
    hazard[7, 7] = 2
    c = make_cost(hazard)
    assert np.array_equal(c.planning_rate(0.0), c.time_rate)


def test_planning_rate_adds_weighted_risk():
    hazard = np.zeros((9, 9), np.uint8)
    hazard[3, 3] = 1
    c = make_cost(hazard)
    assert c.planning_rate(1.0)[3, 3] == pytest.approx(c.time_rate[3, 3] * 2.0)
    assert c.planning_rate(5.0)[3, 3] == pytest.approx(c.time_rate[3, 3] * 6.0)
    assert c.planning_rate(5.0)[0, 0] == pytest.approx(c.time_rate[0, 0])    # green: no risk
    assert c.time_rate[3, 3] == c.time_rate[0, 0]                            # physical time unchanged


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), None, "1", True])
def test_planning_rate_rejects_bad_w(bad):
    with pytest.raises(ConfigError, match="w must be"):
        make_cost().planning_rate(bad)


def test_build_from_a_site_with_a_red_wall(red_wall_site):
    grid = g.read_grid(red_wall_site.folder)
    dem = g.load_dem(red_wall_site.folder, grid)
    c = cost.build(dem, g.load_hazard(red_wall_site.folder, grid), g.slope_deg(dem, grid.cell_m), grid, P)
    assert c.blocked[0:15, 10].all()
    assert not c.blocked[15:, 10].any()
    assert c.reasons["red"].sum() == 15
    assert c.time_rate.shape == grid.shape
    assert not np.isnan(c.time_rate).any() and not np.isnan(c.risk_rate).any()


def test_build_on_the_wide_site_uses_its_cell_size(wide_site):
    grid = g.read_grid(wide_site.folder)
    dem = g.load_dem(wide_site.folder, grid)
    c = cost.build(dem, g.load_hazard(wide_site.folder, grid), g.slope_deg(dem, grid.cell_m), grid, P)
    assert c.time_rate.shape == (80, 120)
    assert not c.blocked.any()

def test_time_rate_follows_the_configured_steepness_and_speed():
    slope = np.full((9, 9), np.degrees(np.arctan(0.1)))
    c = make_cost(slope=slope, p=P.with_(tobler_k=2.0, v_flat_kmh=3.6))
    assert c.time_rate[4, 4] == pytest.approx(1 / (60.0 * np.exp(-0.2)))
