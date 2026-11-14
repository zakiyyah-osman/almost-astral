"""Landing safety: the codes and their priority, the marginal band, nearest_safe, landing_check, warnings."""
import json

import numpy as np
import pytest

import cost
import grid as g
import landing as L
from config import load_config
from conftest import write_full_site

CFG = load_config()
P = cost.Params.from_config(CFG)
CELL = 5.0
SHAPE = (31, 31)
MID = (15, 15)
RULES = L.Rules.from_config(CFG)            # pad 25 m (5 cells), clearance 30 m (6 cells)


def build(dem=None, hazard=None, shape=SHAPE, rules=RULES, ti=None):
    dem = np.zeros(shape) if dem is None else np.asarray(dem, dtype=float)
    hazard = np.zeros(shape, np.uint8) if hazard is None else hazard
    slope = g.slope_deg(dem, CELL)
    grid = g.Grid(shape[1], shape[0], CELL)
    c = cost.build(dem, hazard, slope, grid, P)
    m = L.measure(dem, slope, hazard, c, rules)
    return L.classify(m, rules), m, c


def plane(slope_ratio, shape=SHAPE):
    """Heights rising `slope_ratio` m per m towards the east."""
    return np.tile(np.arange(shape[1]) * CELL * slope_ratio, (shape[0], 1)).astype(float)


# ---- the rules from the config -----------------------------------------------
def test_rules_come_from_the_config_in_metres():
    assert RULES == L.Rules(25.0, 5.0, 0.25, 1.0, 30.0, 20.0, 150.0)
    offs = L.disk_offsets(25.0, 5.0)
    assert len(offs) == 81 and np.abs(offs).max() == 5             # 5 cells of 5 m
    assert len(L.disk_offsets(25.0, 2.5)) > len(offs)              # the same metres give more cells on a finer grid
    assert np.abs(L.disk_offsets(25.0, 2.5)).max() == 10


# ---- every reason ------------------------------------------------------------
def test_flat_green_ground_is_safe_and_the_edges_are_outside_coverage():
    codes, m, _ = build()
    assert codes[MID] == L.SAFE
    assert m.tilt_deg[MID] == pytest.approx(0.0, abs=1e-9) and m.roughness_m[MID] == pytest.approx(0.0, abs=1e-9)
    reach = 6                                                       # max(25, 30) m / 5 m
    assert (codes[:reach] == L.OUTSIDE).all() and (codes[:, -reach:] == L.OUTSIDE).all()
    assert codes[reach, reach] == L.SAFE


def test_no_data_on_the_pad():
    dem = np.zeros(SHAPE)
    dem[MID[0] + 3, MID[1]] = np.nan                               # 15 m from the centre, on the pad
    codes, _, _ = build(dem)
    assert codes[MID] == L.NODATA


def test_a_yellow_cell_on_the_pad_fails():
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[MID[0], MID[1] + 4] = 1                                  # 20 m away: on the 25 m pad
    codes, _, _ = build(hazard=hazard)
    assert codes[MID] == L.HAZARD


def test_red_within_the_clearance_fails_and_beyond_it_passes():
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[MID[0], MID[1] + 6] = 2                                  # 30 m: exactly the clearance, allowed
    codes, m, _ = build(hazard=hazard)
    assert m.clearance_m[MID] == pytest.approx(30.0)
    assert codes[MID] in (L.SAFE, L.MARGINAL)
    assert codes[MID[0], MID[1] + 1] == L.HAZARD                    # 25 m from that red cell


def test_too_steep():
    codes, m, _ = build(plane(0.10))                                # 5.71 deg
    assert m.tilt_deg[MID] == pytest.approx(5.71, abs=0.01)
    assert codes[MID] == L.STEEP


def test_height_range_from_one_step():
    dem = np.zeros(SHAPE)
    dem[MID[0] + 2, MID[1] + 2] = 1.5                               # one 1.5 m block on the pad
    hazard = np.zeros(SHAPE, np.uint8)                              # (the hazard map would not see it)
    codes, m, _ = build(dem, hazard)
    assert m.height_range_m[MID] > 1.0 and m.roughness_m[MID] < 0.25
    assert codes[MID] == L.RANGE


def test_too_rough_on_a_checkerboard():
    r, c = np.indices(SHAPE)
    dem = np.where((r + c) % 2 == 0, 0.3, -0.3)                     # RMS 0.3 m, range 0.6 m, slope 0
    codes, m, _ = build(dem)
    assert m.roughness_m[MID] == pytest.approx(0.3, abs=0.01) and m.height_range_m[MID] < 1.0
    assert codes[MID] == L.ROUGH


def test_a_blocked_cell_on_the_pad_fails_so_safe_cells_can_always_be_walked_from():
    codes, _, c = build(plane(0.10) * 0 + np.where(np.indices(SHAPE)[1] == 30, 50.0, 0.0))
    assert (codes[c.blocked] != L.SAFE).all() and (codes[c.blocked] != L.MARGINAL).all()


# ---- priority ----------------------------------------------------------------
def _measures(**over):
    base = dict(tilt_deg=1.0, roughness_m=0.0, height_range_m=0.0, clearance_m=100.0,
                outside=False, nodata=False, hazard=False)
    base.update(over)
    return L.Measures(**{k: np.array([[v]]) for k, v in base.items()})


@pytest.mark.parametrize("over,code", [
    ({}, L.SAFE),
    ({"roughness_m": 0.3}, L.ROUGH),
    ({"roughness_m": 0.3, "height_range_m": 2.0}, L.RANGE),
    ({"roughness_m": 0.3, "height_range_m": 2.0, "tilt_deg": 9.0}, L.STEEP),
    ({"roughness_m": 0.3, "tilt_deg": 9.0, "clearance_m": 10.0}, L.HAZARD),
    ({"tilt_deg": 9.0, "hazard": True}, L.HAZARD),
    ({"hazard": True, "nodata": True}, L.NODATA),
    ({"nodata": True, "outside": True, "hazard": True, "tilt_deg": 9.0}, L.OUTSIDE),
])
def test_the_most_serious_reason_wins(over, code):
    assert int(L.classify(_measures(**over), RULES)[0, 0]) == code


def test_the_order_is_documented_by_the_codes():
    assert L.FAIL_ORDER == (L.OUTSIDE, L.NODATA, L.HAZARD, L.STEEP, L.RANGE, L.ROUGH) == tuple(range(2, 8))


# ---- marginal band -----------------------------------------------------------
@pytest.mark.parametrize("over,code", [
    ({"tilt_deg": 3.9}, L.SAFE), ({"tilt_deg": 4.1}, L.MARGINAL), ({"tilt_deg": 5.0}, L.MARGINAL),
    ({"tilt_deg": 5.01}, L.STEEP),
    ({"roughness_m": 0.19}, L.SAFE), ({"roughness_m": 0.21}, L.MARGINAL),
    ({"height_range_m": 0.79}, L.SAFE), ({"height_range_m": 0.81}, L.MARGINAL),
    ({"clearance_m": 36.1}, L.SAFE), ({"clearance_m": 35.0}, L.MARGINAL), ({"clearance_m": 29.0}, L.HAZARD),
])
def test_marginal_band_is_within_20_percent_of_a_limit(over, code):
    assert int(L.classify(_measures(**over), RULES)[0, 0]) == code


def test_marginal_on_real_geometry():
    codes, m, _ = build(plane(0.08))                                # 4.57 deg: passes, but within 20% of 5
    assert codes[MID] == L.MARGINAL
    codes, _, _ = build(plane(0.05))                                # 2.86 deg
    assert codes[MID] == L.SAFE


# ---- nearest safe ------------------------------------------------------------
def test_nearest_safe_matches_brute_force():
    rng = np.random.default_rng(3)
    codes = np.where(rng.random((25, 35)) < 0.05, L.SAFE, L.STEEP).astype(np.uint8)
    rows, cols, dist = L.nearest_safe(codes, 5.0)
    safe = np.argwhere(codes == L.SAFE)
    for cell in np.ndindex(codes.shape):
        d = np.hypot(*(safe - np.array(cell)).T) * 5.0
        assert dist[cell] == pytest.approx(d.min())
        assert codes[rows[cell], cols[cell]] == L.SAFE
        assert np.hypot(rows[cell] - cell[0], cols[cell] - cell[1]) * 5.0 == pytest.approx(d.min())
    assert (dist[codes == L.SAFE] == 0).all()
    assert (rows[codes == L.SAFE] == np.argwhere(codes == L.SAFE)[:, 0]).all()


def test_nearest_safe_tie_is_one_of_the_tied_cells_and_repeatable():
    codes = np.full((5, 5), L.ROUGH, np.uint8)
    codes[2, 0] = codes[2, 4] = L.SAFE                              # (2, 2) is 10 m from both
    a = L.nearest_safe(codes, 5.0)
    b = L.nearest_safe(codes, 5.0)
    pick = (int(a[0][2, 2]), int(a[1][2, 2]))
    assert pick in {(2, 0), (2, 4)} and a[2][2, 2] == pytest.approx(10.0)
    assert all(np.array_equal(x, y) for x, y in zip(a, b))


def test_marginal_cells_are_not_targets_of_nearest_safe():
    codes = np.full((3, 3), L.MARGINAL, np.uint8)
    codes[0, 0] = L.SAFE
    rows, cols, _ = L.nearest_safe(codes, 5.0)
    assert (rows == 0).all() and (cols == 0).all()


def test_no_safe_cell_is_a_clear_error():
    with pytest.raises(L.LandingError, match="no safe landing cell.*too_steep"):
        L.nearest_safe(np.full((4, 4), L.STEEP, np.uint8), 5.0)


# ---- landing_check -----------------------------------------------------------
@pytest.fixture
def lmap():
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[MID] = 1                                                 # the middle is unsafe
    dem = np.zeros(SHAPE)
    slope = g.slope_deg(dem, CELL)
    c = cost.build(dem, hazard, slope, g.Grid(SHAPE[1], SHAPE[0], CELL), P)
    return L.assess(dem, slope, hazard, c, RULES)


def test_a_safe_click_stays_where_it_is(lmap):
    x, y = 33.3, 121.7                                              # inside a safe cell, off its centre
    cell = lmap.cell_of(x, y)
    assert lmap.codes[cell] == L.SAFE
    r = lmap.landing_check(x, y)
    assert r["status"] == "safe" and r["reasons"] == [] and r["chosen_xy_m"] == [x, y] and r["moved_m"] == 0.0


def test_an_unsafe_click_moves_to_the_nearest_safe_cell(lmap):
    x, y = lmap.grid.cell_centre(*MID)
    r = lmap.landing_check(x + 1.0, y - 0.5)
    assert r["status"] == "moved" and r["code_name"] == "hazard_or_clearance"
    assert "hazard_or_clearance" in r["reasons"]
    chosen = tuple(r["chosen_cell"])
    assert lmap.codes[chosen] == L.SAFE
    assert r["chosen_xy_m"] == list(lmap.centre(*chosen))
    assert r["moved_m"] == pytest.approx(np.hypot(r["chosen_xy_m"][0] - (x + 1.0), r["chosen_xy_m"][1] - (y - 0.5)))
    safe = np.argwhere(lmap.codes == L.SAFE)
    assert np.hypot(*(np.array(chosen) - np.array(MID))) == pytest.approx(np.hypot(*(safe - np.array(MID)).T).min())


def test_a_marginal_click_stays_and_says_which_limit():
    codes, m, c = build(plane(0.08))                    # every pad is marginal: no safe cell at all
    codes = codes.copy()
    codes[6, 6] = L.SAFE                                # one safe target, so nearest_safe has an answer
    rows, cols, dist = L.nearest_safe(codes, CELL)
    lm = L.LandingMap(c.grid, (0.0, 0.0), RULES, codes, np.zeros(SHAPE, np.uint8), rows, cols, dist, m)
    r = lm.landing_check(*lm.centre(*MID))
    assert r["status"] == "marginal" and r["moved_m"] == 0.0 and r["reasons"] == ["near_too_steep"]


def test_a_click_outside_the_grid(lmap):
    r = lmap.landing_check(-5.0, 10.0)
    assert r["status"] == "outside" and r["chosen_xy_m"] is None


def test_a_window_keeps_site_coordinates():
    hazard = np.zeros(SHAPE, np.uint8)
    dem = np.zeros(SHAPE)
    slope = g.slope_deg(dem, CELL)
    c = cost.build(dem, hazard, slope, g.Grid(SHAPE[1], SHAPE[0], CELL), P)
    lm = L.assess(dem, slope, hazard, c, RULES, box=(5, 25, 8, 28), origin_m=(40.0, 30.0))
    assert lm.codes.shape == (20, 20)
    x, y = 77.5, 77.5
    r = lm.landing_check(x, y)
    site_cell = g.Grid(SHAPE[1], SHAPE[0], CELL).xy_to_cell(x, y)
    full = L.assess(dem, slope, hazard, c, RULES)
    assert r["code"] == int(full.codes[site_cell])


# ---- thermal inertia warnings ------------------------------------------------
def test_low_and_missing_thermal_inertia_are_warning_bits_only():
    ti = np.full(SHAPE, 300.0)
    ti[MID[0], MID[1] + 2] = 120.0                                  # loose ground on the pad
    ti[MID[0] + 8, MID[1]] = np.nan                                 # no value 40 m south
    warn = L.warnings_grid(ti, RULES.pad_radius_m, CELL, RULES, SHAPE)
    assert warn[MID] == L.WARN_LOW_TI
    assert warn[MID[0] + 8, MID[1]] & L.WARN_NO_TI and not warn[MID[0] + 8, MID[1]] & L.WARN_LOW_TI
    assert warn[0, 0] == 0
    assert (L.warnings_grid(None, 25.0, CELL, RULES, SHAPE) == 0).all()


@pytest.mark.parametrize("fake,checked", [(False, True), (True, False)])
def test_thermal_inertia_is_only_used_when_the_layer_is_real(tmp_path, fake, checked):
    folder = tmp_path / "s"
    write_full_site(folder, np.zeros(SHAPE, np.float32), np.zeros(SHAPE, np.uint8), CELL,
                    [("a", "A", "stop", 50.0, 50.0)])
    site = g.load_site(folder)
    layers = json.loads((folder / "layers.json").read_text(encoding="utf-8"))
    layers["layers"].append({"id": "thermal", "title": "TI", "file": "thermal.png",
                             "source": "FAKE thermal" if fake else "THEMIS (Mars Odyssey)"})
    (folder / "layers.json").write_text(json.dumps(layers), encoding="utf-8")
    import rasterio
    from rasterio.transform import from_origin
    ti = np.full(SHAPE, 100.0, np.float32)
    with rasterio.open(folder / "thermal_inertia.tif", "w", driver="GTiff", height=SHAPE[0], width=SHAPE[1],
                       count=1, dtype="float32", transform=from_origin(0, SHAPE[0] * CELL, CELL, CELL)) as dst:
        dst.write(ti, 1)
    site = g.load_site(folder)
    c = cost.build(site.dem, site.hazard, site.slope, site.grid, P)
    lm, notes = L.assess_site(site, c, CFG, folder)
    assert notes["ti_checked"] is checked
    assert bool((lm.warn & L.WARN_LOW_TI).any()) is checked
    assert (lm.codes[MID] == L.SAFE)                               # a warning never changes the code
