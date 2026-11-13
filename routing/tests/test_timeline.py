import copy
import math

import numpy as np
import pytest

import cost
import grid as g
import shelter
import timeline
import tour
from config import Config, ConfigError, load_config
from cost import Params
from tour import Waypoint

CFG = load_config()
P = Params.from_config(CFG)
CELL = 5.0
SHAPE = (20, 30)
STOP_MIN = CFG.value("timeline.stop_min_default")        # 25
INGRESS = CFG.value("timeline.ingress_min")              # 15


def cfg_with(**values):
    raw = copy.deepcopy(CFG.raw)
    for key, v in values.items():
        section, name = key.split("__")
        raw[section][name]["value"] = v
    return Config.from_dict(raw)


def wp(wid, kind, cell):
    x, y = g.Grid(SHAPE[1], SHAPE[0], CELL).cell_centre(*cell)
    return Waypoint(wid, wid, kind, x, y, cell)


class Scenario:
    def __init__(self, cfg=CFG, dem=None, hazard=None, rover_cell=(10, 2), stop_cells=((3, 20), (17, 26))):
        self.cfg = cfg
        self.dem = np.zeros(SHAPE) if dem is None else dem
        self.hazard = np.zeros(SHAPE, np.uint8) if hazard is None else hazard
        grid = g.Grid(SHAPE[1], SHAPE[0], CELL)
        slope = g.slope_deg(self.dem, CELL)
        self.cost = cost.build(self.dem, self.hazard, slope, grid, P)
        self.rover = wp("rover", "rover", rover_cell)
        self.stops = [wp(f"stop{i + 1}", "stop", c) for i, c in enumerate(stop_cells)]
        self.plan = tour.plan_routes(self.cost, self.rover, self.stops, cfg)
        self.route = self.plan.routes["balanced"]
        self.shelter = shelter.shelter_time(self.cost, self.rover.cell, cfg.value("timeline.ingress_min"), 8)
        self.rad = timeline.RadiationInfo(timeline.background_usv_h(cfg), None, (), (), timeline.solar_event(cfg))

    def timeline(self, route=None):
        return timeline.build_timeline(
            self.cost, self.dem, self.hazard, route or self.route, self.shelter, self.cfg, self.rad
        )


# ---- 5.1 legs and totals -----------------------------------------------------
def test_total_is_walk_plus_stops_plus_ingress():
    sc = Scenario()
    tl = sc.timeline()
    assert tl.walk_min == pytest.approx(sc.route.physical_min)
    assert tl.stop_min == 2 * STOP_MIN == 50
    assert tl.ingress_min == INGRESS == 15
    assert tl.total_min == pytest.approx(tl.walk_min + 50 + 15)
    assert tl.walk_min == pytest.approx(sum(l.walk_min for l in tl.legs))


def test_legs_chain_rover_to_rover():
    tl = Scenario().timeline()
    assert [(l.from_id, l.to_id) for l in tl.legs] == [("rover", "stop1"), ("stop1", "stop2"), ("stop2", "rover")]
    assert tl.legs[0].depart_min == 0.0
    for a, b in zip(tl.legs, tl.legs[1:]):
        assert b.depart_min == pytest.approx(a.arrive_min + a.stop_min)       # leaves after the stop
        assert b.from_id == a.to_id
    assert [l.stop_min for l in tl.legs] == [STOP_MIN, STOP_MIN, 0.0]         # none on the way into the rover
    for l in tl.legs:
        assert l.arrive_min == pytest.approx(l.depart_min + l.walk_min)
        assert l.distance_m > 0 and l.walk_min > 0
    last = tl.legs[-1]
    assert last.arrive_min + tl.ingress_min == pytest.approx(tl.total_min)


def test_leg_times_agree_with_the_route_clock():
    sc = Scenario()
    tl = sc.timeline()
    clock = tour.route_clock(sc.cost, sc.route, STOP_MIN)
    for leg, stop in zip(tl.legs[:-1], ("stop1", "stop2")):
        assert leg.arrive_min == pytest.approx(clock.elapsed_min[clock.arrival_index[stop]])


def test_ascent_descent_and_slope_come_from_the_dem():
    rows = np.arange(SHAPE[0])[:, None]
    cols = np.arange(SHAPE[1])[None, :]
    dem = 0.5 * cols + 0.0 * rows                         # rises 0.5 m per cell to the east, 10% slope
    sc = Scenario(dem=dem)
    tl = sc.timeline()
    out, back = tl.legs[0], tl.legs[-1]
    assert out.ascent_m > out.descent_m                   # going out to the east is uphill overall
    assert out.max_slope_deg == pytest.approx(math.degrees(math.atan(0.1)), abs=0.01)
    for leg_times, leg in zip(tl.legs, sc.route.legs):
        z = np.array([dem[c] for c in leg.path.cells])
        d = np.diff(z)
        assert leg_times.ascent_m == pytest.approx(d[d > 0].sum())
        assert leg_times.descent_m == pytest.approx(-d[d < 0].sum())
    assert back.descent_m > back.ascent_m                  # coming home from the east is downhill overall
    assert sum(l.ascent_m for l in tl.legs) == pytest.approx(sum(l.descent_m for l in tl.legs))   # a closed loop


def test_time_includes_the_slope():
    flat = Scenario().timeline()
    rows = np.arange(SHAPE[0])[:, None]
    hilly = Scenario(dem=0.5 * np.arange(SHAPE[1])[None, :] + 0.0 * rows).timeline()
    assert hilly.walk_min > flat.walk_min


# ---- 5.2 budget checks and status --------------------------------------------
def test_usable_is_252_min_for_360_and_30pct():
    tl = Scenario().timeline()
    assert tl.eva_max_min == 360 and tl.reserve_pct == 30
    assert tl.usable_min == pytest.approx(252.0)
    assert Scenario(cfg_with(timeline__eva_max_min=200, timeline__reserve_pct=10)).timeline().usable_min == pytest.approx(180.0)
    assert Scenario(cfg_with(timeline__reserve_pct=0)).timeline().usable_min == 360


def check_of(tl, cid):
    return next(c for c in tl.checks if c.id == cid)


def test_all_checks_pass_for_a_short_walk():
    tl = Scenario().timeline()
    assert [c.id for c in tl.checks] == ["reserve", "abort", "radiation"]
    assert all(c.ok for c in tl.checks) and tl.status == "ok"
    reserve = check_of(tl, "reserve")
    assert reserve.value == pytest.approx(tl.total_min) and reserve.limit == pytest.approx(252.0) and reserve.unit == "min"
    assert "within" in reserve.message and "252" in reserve.message


def test_over_reserve_flags_status():
    sc = Scenario(cfg_with(timeline__eva_max_min=100))      # usable 70 min: the walk, stops and ingress exceed it
    tl = sc.timeline()
    assert tl.total_min > 70
    reserve = check_of(tl, "reserve")
    assert not reserve.ok and "over" in reserve.message
    assert tl.status == "over_budget"
    assert check_of(tl, "radiation").ok


def test_reserve_limit_is_inclusive():
    base = Scenario().timeline()
    eva = base.total_min / 0.7                              # usable == total exactly
    tl = Scenario(cfg_with(timeline__eva_max_min=eva + 1e-6)).timeline()
    assert check_of(tl, "reserve").ok
    tl = Scenario(cfg_with(timeline__eva_max_min=eva - 1e-3)).timeline()
    assert not check_of(tl, "reserve").ok


def test_abort_check_uses_elapsed_plus_return():
    sc = Scenario(cfg_with(timeline__reserve_pct=0))
    tl = sc.timeline()
    worst = max(p.elapsed_min + p.shelter_min for p in tl.track)
    abort = check_of(tl, "abort")
    assert abort.value == pytest.approx(worst) and abort.unit == "min"
    assert abort.limit == 360 and abort.ok
    # The limit is the hard EVA limit, not the usable time: flip it just below the worst moment.
    tight = Scenario(cfg_with(timeline__reserve_pct=0, timeline__eva_max_min=worst - 0.01)).timeline()
    assert not check_of(tight, "abort").ok and tight.status == "over_budget"
    loose = Scenario(cfg_with(timeline__reserve_pct=0, timeline__eva_max_min=worst + 0.01)).timeline()
    assert check_of(loose, "abort").ok and check_of(loose, "reserve").ok


def test_abort_check_covers_the_moment_of_leaving_a_stop():
    sc = Scenario()
    tl = sc.timeline()
    abort = check_of(tl, "abort")
    leaving = []
    for t, leg in zip(tl.legs[:-1], sc.route.legs[:-1]):
        leaving.append(t.arrive_min + t.stop_min + sc.shelter.minutes[leg.path.cells[-1]])
    assert abort.value >= max(leaving) - 1e-9
    assert abort.value >= max(p.elapsed_min + p.shelter_min for p in tl.track) - 1e-9


def test_abort_value_never_exceeds_the_total():
    """The way back is never longer than finishing the route, so the worst moment is the end."""
    tl = Scenario().timeline()
    assert check_of(tl, "abort").value == pytest.approx(tl.total_min)


# ---- 5.3 radiation -----------------------------------------------------------
def test_background_dose_180_min_is_80_usv():
    rate = timeline.background_usv_h(CFG)
    assert rate == pytest.approx(26.667, abs=0.001)          # 0.64 mSv/day
    assert timeline.dose_usv(180, rate) == pytest.approx(80.0, abs=0.01)
    assert timeline.dose_usv(0, rate) == 0
    tl = Scenario().timeline()
    assert tl.radiation_dose_usv == pytest.approx(rate * tl.total_min / 60.0)
    assert check_of(tl, "radiation").value == pytest.approx(tl.radiation_dose_usv)
    assert check_of(tl, "radiation").limit == 1000


def test_radiation_over_the_limit_flags_status():
    tl = Scenario(cfg_with(radiation__limit_usv=10)).timeline()
    assert not check_of(tl, "radiation").ok and tl.status == "over_budget"
    assert check_of(tl, "reserve").ok


def test_solar_event_is_8_1_mgy_in_its_own_field():
    ev = timeline.solar_event(CFG)
    assert ev["absorbed_dose_mgy"] == 8.1
    assert ev["date"] == "2024-05-20" and "Curiosity RAD" in ev["source"]
    assert "Gy" in ev["note"] and "not added" in ev["note"]
    assert not any("sv" in k for k in ev if k != "source")    # no Sv-valued key next to the Gy value


def test_event_dose_not_added_to_sv():
    small = Scenario().timeline()
    big = Scenario(cfg_with(radiation__solar_event_dose_mgy=5000.0)).timeline()
    assert big.radiation_dose_usv == small.radiation_dose_usv
    assert timeline.solar_event(cfg_with(radiation__solar_event_dose_mgy=5000.0))["absorbed_dose_mgy"] == 5000.0
    rate = timeline.background_usv_h(CFG)
    assert small.radiation_dose_usv == pytest.approx(rate * small.total_min / 60.0)


def write_csv(path, rows, header="sol,local_hour,dose_rate_usv_h"):
    path.write_text(header + "\n" + "\n".join(f"40,{h},{v}" for h, v in rows) + "\n", encoding="utf-8")


def test_csv_baseline_matching_gives_no_warning(tmp_path):
    write_csv(tmp_path / "radiation.csv", [(h, 27) for h in range(24)])
    info = timeline.radiation_info(CFG, tmp_path)
    assert info.warnings == () and info.csv_median_usv_h == 27 and info.csv_storm_hours == ()
    assert info.background_usv_h == pytest.approx(26.667, abs=0.001)


def test_csv_baseline_mismatch_warns(tmp_path):
    write_csv(tmp_path / "radiation.csv", [(h, 60) for h in range(24)])
    info = timeline.radiation_info(CFG, tmp_path)
    assert len(info.warnings) == 1
    assert "radiation.csv" in info.warnings[0] and "60.0" in info.warnings[0] and "25%" in info.warnings[0]
    low = tmp_path / "low"
    low.mkdir()
    write_csv(low / "radiation.csv", [(h, 10) for h in range(24)])
    assert timeline.radiation_info(CFG, low).warnings


def test_csv_tolerance_comes_from_the_config(tmp_path):
    write_csv(tmp_path / "radiation.csv", [(h, 30) for h in range(24)])             # 12% above the config rate
    assert timeline.radiation_info(CFG, tmp_path).warnings == ()
    assert timeline.radiation_info(cfg_with(radiation__baseline_tolerance_pct=5), tmp_path).warnings


def test_csv_storm_hours_are_listed(tmp_path):
    rows = [(h, 27) for h in range(24)]
    rows[15], rows[16] = (15, 120), (16, 80)
    write_csv(tmp_path / "radiation.csv", rows)
    info = timeline.radiation_info(CFG, tmp_path)
    assert info.csv_storm_hours == (15, 16)
    assert info.csv_median_usv_h == 27
    assert info.warnings == ()                       # the storm hours do not move the median


def test_csv_storm_threshold_is_the_factor_times_the_median(tmp_path):
    rows = [(h, 27) for h in range(24)]
    rows[15], rows[16] = (15, 120), (16, 80)
    write_csv(tmp_path / "radiation.csv", rows)
    assert timeline.radiation_info(cfg_with(radiation__storm_detect_factor=4.0), tmp_path).csv_storm_hours == (15,)
    assert timeline.radiation_info(cfg_with(radiation__storm_detect_factor=2.0), tmp_path).csv_storm_hours == (15, 16)


def test_storm_hour_does_not_change_the_sv_dose(tmp_path):
    flat = [(h, 27) for h in range(24)]
    stormy = list(flat)
    stormy[15] = (15, 500)
    write_csv(tmp_path / "radiation.csv", stormy)
    info = timeline.radiation_info(CFG, tmp_path)
    assert info.csv_storm_hours == (15,)
    assert info.background_usv_h == timeline.background_usv_h(CFG)         # the config rate, not the csv


def test_missing_csv_is_a_warning_not_an_error(tmp_path):
    info = timeline.radiation_info(CFG, tmp_path)
    assert info.csv_median_usv_h is None and info.csv_storm_hours == ()
    assert len(info.warnings) == 1 and "radiation.csv not found" in info.warnings[0]


@pytest.mark.parametrize("text,match", [
    ("sol,hour,rate\n1,2,3\n", "numeric local_hour"),
    ("sol,local_hour,dose_rate_usv_h\n", "no data rows"),
    ("sol,local_hour,dose_rate_usv_h\n1,x,3\n", "numeric"),
    ("sol,local_hour,dose_rate_usv_h\n1,2,nan\n", "finite"),
])
def test_bad_csv_is_a_clear_error(tmp_path, text, match):
    (tmp_path / "radiation.csv").write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=match):
        timeline.radiation_info(CFG, tmp_path)


def test_csv_with_a_bom_is_read(tmp_path):
    (tmp_path / "radiation.csv").write_bytes(b"\xef\xbb\xbfsol,local_hour,dose_rate_usv_h\n1,2,27\n")
    assert timeline.radiation_info(CFG, tmp_path).csv_median_usv_h == 27


# ---- 5.4 track ---------------------------------------------------------------
def test_track_spacing():
    sc = Scenario()
    tl = sc.timeline()
    spacing = CFG.value("track.spacing_m")
    d = [p.distance_m for p in tl.track]
    assert d == sorted(d) and d[0] == 0.0
    regular = [p for p in tl.track if p.stop is None and p is not tl.track[-1]]
    for p in regular:
        nearest = round(p.distance_m / spacing) * spacing
        assert abs(p.distance_m - nearest) <= CELL * math.sqrt(2) / 2 + 1e-9
    total = sc.route.distance_m
    assert len(regular) >= int(total // spacing)
    assert tl.track[-1].distance_m == pytest.approx(total)              # ends back at the rover
    assert (tl.track[-1].x, tl.track[-1].y) == (sc.rover.x, sc.rover.y)


def test_track_includes_the_stops():
    sc = Scenario()
    tl = sc.timeline()
    stops = {p.stop: p for p in tl.track if p.stop}
    assert set(stops) == {"stop1", "stop2"}
    assert (stops["stop1"].x, stops["stop1"].y) == (sc.stops[0].x, sc.stops[0].y)


def test_elapsed_never_decreases():
    tl = Scenario().timeline()
    el = [p.elapsed_min for p in tl.track]
    assert el == sorted(el) and el[0] == 0.0
    assert all(b >= a for a, b in zip(el, el[1:]))


def test_elapsed_includes_stop_time():
    sc = Scenario()
    tl = sc.timeline()
    clock = tour.route_clock(sc.cost, sc.route, STOP_MIN)
    for p in tl.track:
        idx = int(np.argmin(np.abs(clock.distance_m - p.distance_m)))
        assert p.elapsed_min == pytest.approx(clock.elapsed_min[idx])
    last = tl.track[-1]
    assert last.elapsed_min == pytest.approx(tl.walk_min + tl.stop_min)  # all the walking and both stops
    after_first = [p for p in tl.track if p.distance_m > next(q for q in tl.track if q.stop == "stop1").distance_m]
    walked = clock.walk_min[int(np.argmin(np.abs(clock.distance_m - after_first[0].distance_m)))]
    assert after_first[0].elapsed_min == pytest.approx(walked + STOP_MIN)
    assert tl.total_min == pytest.approx(last.elapsed_min + INGRESS)


def test_track_values_are_cell_values():
    rows = np.arange(SHAPE[0])[:, None]
    dem = 0.5 * np.arange(SHAPE[1])[None, :] + 0.0 * rows
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[8:13, 10:14] = 1
    sc = Scenario(dem=dem, hazard=hazard)
    tl = sc.timeline()
    grid = sc.cost.grid
    for p in tl.track:
        cell = grid.xy_to_cell(p.x, p.y)
        assert p.elev_m == dem[cell]
        assert p.slope_deg == pytest.approx(sc.cost.slope_deg[cell])
        assert p.hazard == hazard[cell]
        assert p.shelter_min == sc.shelter.minutes[cell]
    assert {p.hazard for p in tl.track} <= {0, 1}
    assert all(not sc.cost.blocked[grid.xy_to_cell(p.x, p.y)] for p in tl.track)


def test_track_spacing_follows_the_config():
    coarse = Scenario(cfg_with(track__spacing_m=100)).timeline().track
    fine = Scenario(cfg_with(track__spacing_m=10)).timeline().track
    assert len(fine) > 2 * len(coarse)


def test_each_profile_gets_its_own_timeline():
    sc = Scenario()
    tls = {n: timeline.build_timeline(sc.cost, sc.dem, sc.hazard, r, sc.shelter, sc.cfg, sc.rad)
           for n, r in sc.plan.routes.items()}
    assert set(tls) == {"fastest", "balanced", "safest"}
    for tl in tls.values():
        assert tl.total_min == pytest.approx(tl.walk_min + tl.stop_min + tl.ingress_min)
