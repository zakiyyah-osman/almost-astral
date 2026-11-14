import math

import numpy as np
import pytest
from PIL import Image

import cost
import grid as g
import shelter
from config import load_config
from cost import Params

CFG = load_config()
P = Params.from_config(CFG)
CELL = 5.0
INGRESS = CFG.value("timeline.ingress_min")
CMAX = CFG.value("shelter_map.colour_max_min")
INTERVAL = CFG.value("shelter_map.contour_interval_min")


def make_cost(hazard=None, shape=(20, 20), cell=CELL, p=P):
    hazard = np.zeros(shape, np.uint8) if hazard is None else hazard
    return cost.build(np.zeros(shape), hazard, np.zeros(shape), g.Grid(shape[1], shape[0], cell), p)


def shelter_for(c, start=(10, 10), ingress=INGRESS):
    return shelter.shelter_time(c, start, ingress, 8)


# ---- 4.1 the array -----------------------------------------------------------
def test_start_cell_equals_ingress():
    s = shelter_for(make_cost())
    assert s.minutes[10, 10] == INGRESS == 15
    assert s.walk_min[10, 10] == 0
    assert shelter_for(make_cost(), ingress=7.5).minutes[10, 10] == 7.5


def test_flat_matches_distance_over_speed():
    s = shelter_for(make_cost(), start=(10, 10))
    speed = 45.0                                        # m/min at 2.7 km/h
    for dr, dc in [(0, 1), (0, 6), (3, 0), (3, 4), (5, 5), (-2, 7), (-9, -9)]:
        steps_diag = min(abs(dr), abs(dc))
        steps_straight = abs(abs(dr) - abs(dc))
        metres = CELL * (steps_straight + steps_diag * math.sqrt(2))
        assert s.minutes[10 + dr, 10 + dc] == pytest.approx(metres / speed + INGRESS), (dr, dc)
        assert s.walk_min[10 + dr, 10 + dc] == pytest.approx(metres / speed)


def test_blocked_cells_are_nan():
    hazard = np.zeros((20, 20), np.uint8)
    hazard[5, 5] = 2
    hazard[:, 15] = 2                                   # a wall: the cells beyond it are unreachable
    c = make_cost(hazard)
    s = shelter_for(c)
    assert np.isnan(s.minutes[5, 5])
    assert np.isnan(s.minutes[:, 15]).all()
    assert np.isnan(s.minutes[:, 16:]).all()            # cut off from the start
    assert np.isnan(s.walk_min[c.blocked]).all()
    assert np.isfinite(s.minutes[~c.blocked & (np.arange(20)[None, :] < 15)]).all()


def test_the_map_is_the_time_rate_not_a_risk_weighted_cost():
    """Yellow cells and red neighbours change planning cost but not the way back in minutes."""
    plain = shelter_for(make_cost())
    hazard = np.zeros((20, 20), np.uint8)
    hazard[8:13, 12:16] = 1
    risky = shelter_for(make_cost(hazard))
    free = ~np.isnan(risky.minutes)
    assert np.allclose(risky.minutes[free], plain.minutes[free])


def test_slope_slows_the_way_back():
    slope = np.full((20, 20), math.degrees(math.atan(0.1)))
    c = cost.build(np.zeros((20, 20)), np.zeros((20, 20), np.uint8), slope, g.Grid(20, 20, CELL), P)
    s = shelter_for(c)
    assert s.walk_min[10, 11] == pytest.approx(5.0 / (45.0 * math.exp(-0.35)))


def test_wide_site_uses_its_own_cell_size(wide_site):
    grid = g.read_grid(wide_site.folder)
    dem = g.load_dem(wide_site.folder, grid)
    c = cost.build(dem, g.load_hazard(wide_site.folder, grid), g.slope_deg(dem, grid.cell_m), grid, P)
    s = shelter.shelter_time(c, (40, 60), INGRESS, 8)
    assert s.minutes.shape == (80, 120)
    assert s.minutes[40, 119] == pytest.approx(59 * 10.0 / 45.0 + INGRESS)


def test_return_path_comes_from_the_start_tree():
    s = shelter_for(make_cost())
    path = s.tree.path_to((10, 15))
    assert path.cells[0] == (10, 10) and path.cells[-1] == (10, 15)
    assert path.physical_min == pytest.approx(s.walk_min[10, 15])


# ---- 4.2 the PNG -------------------------------------------------------------
def test_png_is_grid_sized_rgba(wide_site, tmp_path):
    grid = g.read_grid(wide_site.folder)
    dem = g.load_dem(wide_site.folder, grid)
    c = cost.build(dem, g.load_hazard(wide_site.folder, grid), g.slope_deg(dem, grid.cell_m), grid, P)
    s = shelter.shelter_time(c, (40, 60), INGRESS, 8)
    path = tmp_path / "shelter_time.png"
    shelter.write_png(path, s.minutes, CMAX, INTERVAL)
    img = Image.open(path)
    assert img.mode == "RGBA"
    assert img.size == (120, 80)                         # width x height, not the other way round
    arr = np.array(img)
    assert arr.shape == (80, 120, 4) and arr.dtype == np.uint8
    assert np.array_equal(arr, shelter.render_png(s.minutes, CMAX, INTERVAL))


def test_row_0_is_the_north_edge():
    minutes = np.full((6, 8), np.nan)
    minutes[0, :] = 1.0                                  # only the top (north) row has a value
    img = shelter.render_png(minutes, CMAX, INTERVAL)
    assert (img[0, :, 3] > 0).all() and (img[1:, :, 3] == 0).all()


def test_blocked_cells_transparent():
    hazard = np.zeros((20, 20), np.uint8)
    hazard[5, 5] = 2
    hazard[:, 15] = 2
    c = make_cost(hazard)
    s = shelter_for(c)
    img = shelter.render_png(s.minutes, CMAX, INTERVAL)
    assert (img[np.isnan(s.minutes)] == 0).all()         # fully transparent, all four channels
    assert (img[np.isfinite(s.minutes)][:, 3] > 0).all()


def test_colours_follow_the_ramp_and_clip_at_the_maximum():
    minutes = np.array([[0.0, 15.0, 30.0, 45.0, 60.0, 90.0, 600.0]])
    img = shelter.render_png(minutes, 60.0, 1000.0)       # interval too large for any contour
    expected = [(*rgb, shelter.CELL_ALPHA) for rgb in shelter.RAMP_RGB]
    assert [tuple(img[0, i]) for i in range(5)] == expected
    assert tuple(img[0, 5]) == expected[-1] and tuple(img[0, 6]) == expected[-1]
    mid = shelter.render_png(np.array([[7.5]]), 60.0, 1000.0)[0, 0]
    halfway = [(a + b) / 2 for a, b in zip(shelter.RAMP_RGB[0], shelter.RAMP_RGB[1])]
    assert np.allclose(mid[:3].astype(float), halfway, atol=0.5)


def test_contours_at_interval():
    minutes = np.tile(2.0 * np.arange(30), (6, 1))        # 0, 2, 4 ... 58 min across the columns
    img = shelter.render_png(minutes, 60.0, 10.0)
    burned = np.all(img == np.array(shelter.CONTOUR_RGBA), axis=-1)
    cols = sorted(set(np.argwhere(burned)[:, 1].tolist()))
    assert cols == [5, 10, 15, 20, 25]                    # the first cell of each 10-minute band
    assert burned.sum() == 5 * 6                           # one cell wide, every row
    assert not np.all(img[:, 4] == np.array(shelter.CONTOUR_RGBA), axis=-1).any()


def test_contours_burn_where_neighbours_differ_in_band():
    c = make_cost(shape=(41, 41), cell=20.0)                # 20 m cells: the walk back spans past 20 min
    s = shelter_for(c, start=(20, 20))
    interval = 10.0
    img = shelter.render_png(s.minutes, 60.0, interval)
    burned = np.all(img == np.array(shelter.CONTOUR_RGBA), axis=-1)
    band = np.floor(s.minutes / interval)
    expect = np.zeros_like(burned)
    for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        shifted = np.full_like(band, np.nan)
        rs, cs = slice(max(0, -dr), 41 - max(0, dr)), slice(max(0, -dc), 41 - max(0, dc))
        rt, ct = slice(max(0, dr), 41 - max(0, -dr)), slice(max(0, dc), 41 - max(0, -dc))
        shifted[rs, cs] = band[rt, ct]
        expect |= band > shifted
    assert np.array_equal(burned, expect)
    assert burned.any()
    # No contour inside a band: a burned cell always has a neighbour in a lower band.
    assert not (burned & (s.minutes < interval)).any()


def test_contour_interval_follows_the_argument():
    minutes = np.tile(1.0 * np.arange(40), (3, 1))
    for interval, expected in ((10.0, [10, 20, 30]), (15.0, [15, 30]), (7.0, [7, 14, 21, 28, 35])):
        img = shelter.render_png(minutes, 60.0, interval)
        burned = np.all(img == np.array(shelter.CONTOUR_RGBA), axis=-1)
        assert sorted(set(np.argwhere(burned)[:, 1].tolist())) == expected


def test_no_contour_against_a_cell_without_a_value():
    minutes = np.array([[5.0, np.nan, 25.0], [5.0, np.nan, 25.0]])
    img = shelter.render_png(minutes, 60.0, 10.0)
    assert not np.all(img == np.array(shelter.CONTOUR_RGBA), axis=-1).any()


def test_legend_matches_the_rendered_colours():
    leg = shelter.legend(CMAX, INTERVAL)
    assert leg["file"] == "shelter_time.png" and leg["includes_ingress"] is True
    assert leg["contour_interval_min"] == 10 and leg["colour_max_min"] == 60
    assert [s["min"] for s in leg["stops"]] == [0, 15, 30, 45, 60]
    minutes = np.array([[s["min"] for s in leg["stops"]]], dtype=float)
    img = shelter.render_png(minutes, CMAX, 1000.0)
    assert [list(px) for px in img[0]] == [s["rgba"] for s in leg["stops"]]
    assert leg["contour_rgba"] == list(shelter.CONTOUR_RGBA)
