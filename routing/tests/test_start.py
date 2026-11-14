"""The start of the walk: --start or the demo start, the start checks, and the old 'rover' kind.

There are no configured starts (no [starts.*] in config.toml). plan_route.py and analysis.py take
--start x,y, or use the demo start: the safe landing cell nearest the grid centre.
"""
import json
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import cost
import grid as g
import landing
import plan_route
import tour
from config import load_config
from conftest import REPO_CONFIG, run_site, with_start, write_full_site, write_waypoints
from start import (
    BUFFER, NODATA, RED, REACHABLE, SEALED, SLOPE, StartError, block_code, block_codes, check_start, start_cell,
)

CFG = load_config()
P = cost.Params.from_config(CFG)
SHAPE, CELL = (20, 30), 5.0
GRID = g.Grid(SHAPE[1], SHAPE[0], CELL)
DEMO_CELL = (9, 15)                 # the cell of the grid centre (75, 50) m; safe on a flat green site


def centre(r, c):
    return GRID.cell_centre(r, c)


def make_cost(hazard=None, dem=None, slope=None, p=P):
    hazard = np.zeros(SHAPE, np.uint8) if hazard is None else hazard
    dem = np.zeros(SHAPE) if dem is None else dem
    slope = g.slope_deg(dem, CELL) if slope is None else slope
    return cost.build(dem, hazard, slope, GRID, p)


def site_of(hazard=None, dem=None):
    hazard = np.zeros(SHAPE, np.uint8) if hazard is None else hazard
    dem = np.zeros(SHAPE) if dem is None else dem
    return g.Site({}, GRID, dem, hazard, g.slope_deg(dem, CELL))


# ---- the config has no starts --------------------------------------------------
def test_the_config_has_no_starts_and_no_landing_spot_coordinates():
    assert not any(k.startswith(("start.", "starts.", "reach.")) for k in CFG.assumptions())
    text = REPO_CONFIG.read_text(encoding="utf-8")
    for gone in ("[starts.", "[start.", "L1", "L2", "L3", "1112.5", "landing.js"):
        assert gone not in text


def test_start_outside_the_grid_fails():
    with pytest.raises(StartError, match=r"start \(500, 50\) m is outside the site grid.*--start"):
        start_cell(GRID, (500.0, 50.0))
    with pytest.raises(StartError, match=r"demo start \(500, 50\) m is outside") as e:
        start_cell(GRID, (500.0, 50.0), name="demo start")
    assert e.value.start_id == "demo start"


def test_valid_start_has_no_warnings():
    c = make_cost()
    assert start_cell(GRID, centre(10, 2)) == (10, 2)
    assert check_start(c, (10, 2), centre(10, 2), np.zeros(SHAPE, np.uint8)) == ()


# ---- validation: every blocked reason fails with its own message ------------
def _blocked_case(kind):
    """(cost, cell) where the cell is blocked for exactly the reason `kind`."""
    hazard = np.zeros(SHAPE, np.uint8)
    dem = np.zeros(SHAPE)
    if kind == "red":
        hazard[10, 10] = 2
        return make_cost(hazard), (10, 10)
    if kind == "nodata":
        dem[10, 10] = np.nan
        return make_cost(dem=dem), (10, 10)
    if kind == "slope":
        dem[10, 10] = 10.0                     # its four neighbours get atan(10 / 10) = 45 deg
        return make_cost(dem=dem), (9, 10)
    if kind == "buffer":
        dem[10, 10] = 10.0                     # the spike itself is flat, but 5 m from a 45 deg cell
        return make_cost(dem=dem), (10, 10)
    if kind == "sealed":
        hazard[8, 8] = hazard[9, 9] = 2        # corner-touching red cells seal (8, 9) and (9, 8)
        return make_cost(hazard), (8, 9)
    raise ValueError(kind)


@pytest.mark.parametrize("kind,code,text", [
    ("red", RED, "red hazard cell"),
    ("nodata", NODATA, "no DEM data"),
    ("slope", SLOPE, "slope over the limit (20 deg)"),
    ("buffer", BUFFER, "inside the 5 m buffer around over-limit slopes"),
    ("sealed", SEALED, "sealed gap between blocked cells"),
])
def test_blocked_start_fails_and_says_why(kind, code, text):
    c, cell = _blocked_case(kind)
    assert block_code(c, cell) == code
    xy = centre(*cell)
    with pytest.raises(StartError) as e:
        check_start(c, cell, xy, name="demo start")
    msg = str(e.value)
    assert text in msg and f"{xy[0]:g}" in msg and "demo start" in msg and "--start" in msg
    assert e.value.waypoint_id == "start" and e.value.start_id == "demo start"
    with pytest.raises(StartError, match=r"start \(.*--start"):
        check_start(c, cell, xy)                       # without a name the message still works


def test_block_codes_match_block_code_everywhere():
    c, _ = _blocked_case("slope")
    codes = block_codes(c)
    for cell in np.ndindex(SHAPE):
        assert codes[cell] == block_code(c, cell)
    assert (codes == REACHABLE).sum() == (~c.blocked).sum()


# ---- careful ground is a warning, not a failure ------------------------------
def test_start_on_yellow_ground_only_warns():
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[10, 2] = 1
    warnings = check_start(make_cost(hazard), (10, 2), centre(10, 2), hazard)
    assert len(warnings) == 1 and "yellow" in warnings[0] and "careful above 10 deg" in warnings[0]


def test_start_on_slope_over_the_onset_only_warns():
    slope = np.zeros(SHAPE)
    slope[10, 2] = 12.0
    warnings = check_start(make_cost(slope=slope), (10, 2), centre(10, 2))
    assert len(warnings) == 1 and "slope 12.0 deg" in warnings[0]


# ---- the old kind 'rover' ----------------------------------------------------
def test_rover_kind_is_still_accepted_with_a_deprecation_warning(flat_site, caplog):
    write_waypoints(flat_site.folder, [
        ("rover", "Rover", "rover", 52.5, 52.5),
        ("stop1", "First", "stop", 5.0, 95.0),
    ])
    with caplog.at_level(logging.WARNING, logger="tour"):
        ws = tour.load_waypoints(flat_site.folder, g.read_grid(flat_site.folder))
    assert ws[0].kind == "start" and ws[0].deprecated_kind == "rover"
    assert "kind 'rover', which is deprecated" in caplog.text
    msgs = tour.deprecation_warnings(ws)
    assert len(msgs) == 1 and "'rover'" in msgs[0] and "change it to 'start'" in msgs[0]
    wp, stops = tour.split_waypoints(ws)
    assert wp.id == "rover" and [s.id for s in stops] == ["stop1"]      # the file's own id
    start, warnings = tour.choose_start(CFG, site_of(), make_cost(), centre(10, 2), wp)
    assert start.id == "start" and (start.x, start.y) == centre(10, 2)  # never the rover's position or id
    assert any("'rover'" in w and "ignored" in w for w in warnings)


def test_start_kind_gives_no_deprecation_warning(flat_site, caplog):
    write_waypoints(flat_site.folder, [("s", "Start", "start", 52.5, 52.5), ("a", "A", "stop", 5.0, 95.0)])
    with caplog.at_level(logging.WARNING, logger="tour"):
        ws = tour.load_waypoints(flat_site.folder, g.read_grid(flat_site.folder))
    assert tour.deprecation_warnings(ws) == () and "deprecated" not in caplog.text


def test_start_and_rover_together_are_two_starts(flat_site):
    write_waypoints(flat_site.folder, [
        ("s", "S", "start", 52.5, 52.5), ("r", "R", "rover", 12.5, 12.5), ("a", "A", "stop", 5.0, 95.0),
    ])
    ws = tour.load_waypoints(flat_site.folder, g.read_grid(flat_site.folder))
    with pytest.raises(tour.RouteError, match="at most one.*found 2"):
        tour.split_waypoints(ws)


# ---- choose_start: --start or the demo start --------------------------------
def test_cli_start_is_used_as_given():
    start, warnings = tour.choose_start(CFG, site_of(), make_cost(), centre(10, 2))
    assert (start.id, start.name, start.kind, start.start_kind) == ("start", "Start", "start", "cli")
    assert start.cell == (10, 2) and (start.x, start.y) == centre(10, 2) and start.landing_id is None
    # (10, 2) is closer to the edge than the 30 m clearance: allowed for walking, but a warning says
    # that it is not a safe landing spot.
    assert start.landing_status == "outside_coverage"
    assert len(warnings) == 1 and "not a safe landing spot" in warnings[0]


def test_cli_start_on_a_safe_cell_gives_no_warning():
    start, warnings = tour.choose_start(CFG, site_of(), make_cost(), centre(*DEMO_CELL))
    assert start.landing_status == "safe" and warnings == ()


def test_demo_start_is_the_safe_cell_nearest_the_grid_centre():
    start, warnings = tour.choose_start(CFG, site_of(), make_cost())
    assert start.start_kind == "demo" and start.name == "Demo start" and start.label == "demo start"
    assert start.cell == DEMO_CELL and (start.x, start.y) == centre(*DEMO_CELL)
    assert start.landing_status == "safe"
    assert any("demo start" in w and "nearest the grid centre" in w for w in warnings)


def test_demo_start_moves_off_an_unsafe_centre_and_is_deterministic():
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[9, 15] = 1                              # a yellow cell at the centre: every pad over it fails
    c = make_cost(hazard)
    a, _ = tour.choose_start(CFG, site_of(hazard), c)
    b, _ = tour.choose_start(CFG, site_of(hazard), c)
    assert a.cell == b.cell and a.landing_status == "safe"
    rules = landing.Rules.from_config(CFG)
    dem = np.zeros(SHAPE)
    codes = landing.classify(landing.measure(dem, g.slope_deg(dem, CELL), hazard, c, rules), rules)
    safe = np.argwhere(codes == landing.SAFE)
    best = min(np.hypot(*(safe - np.array(DEMO_CELL)).T))
    assert np.hypot(a.cell[0] - 9, a.cell[1] - 15) == pytest.approx(best)


def test_no_safe_cell_and_no_start_is_a_clear_error():
    hazard = np.ones(SHAPE, np.uint8)              # all yellow: no pad is green
    with pytest.raises(landing.LandingError, match="no safe landing cell"):
        tour.choose_start(CFG, site_of(hazard), make_cost(hazard))
    start, _ = tour.choose_start(CFG, site_of(hazard), make_cost(hazard), centre(10, 10))
    assert start.cell == (10, 10)                  # with --start the plan still works


def test_blocked_cli_start_fails_and_says_why():
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[10, 2] = 2
    with pytest.raises(StartError, match=r"start \(--start\).*red hazard cell"):
        tour.choose_start(CFG, site_of(hazard), make_cost(hazard), centre(10, 2))


def test_a_start_waypoint_is_ignored_with_a_warning(caplog):
    wp = tour.Waypoint("base", "Base", "start", *centre(5, 5), (5, 5))
    with caplog.at_level(logging.WARNING, logger="tour"):
        start, warnings = tour.choose_start(CFG, site_of(), make_cost(), centre(10, 2), wp)
    assert start.cell == (10, 2)
    assert any("start waypoint 'base'" in w and "ignored" in w for w in warnings)
    assert "ignored" in caplog.text


# ---- plan_route.py -------------------------------------------------------------
def _site(folder, kind="start", start=None, hazard=None, waypoint_cell=(10, 2)):
    waypoints = [
        ("base", "Base", kind, *centre(*waypoint_cell)),
        ("stop1", "North stop", "stop", *centre(3, 20)),
    ]
    hazard = np.zeros(SHAPE, np.uint8) if hazard is None else hazard
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, waypoints, start=start)
    return folder


def test_plan_route_with_start(tmp_path):
    folder = _site(tmp_path / "s", start=centre(12, 4))
    plan = json.loads(run_site(folder).files["plan.json"])
    assert plan["start"]["xy_m"] == list(centre(12, 4)) and plan["start"]["cell"] == [12, 4]
    assert plan["start"]["id"] == "start" and plan["start"]["kind"] == "cli"
    assert plan["start"]["source"] == "command line: plan_route.py --start x,y"
    assert [leg["from"] for leg in plan["legs"]] == ["start", "stop1"] and plan["legs"][-1]["to"] == "start"
    assert plan["track"][0]["shelter_min"] == 15
    assert plan["shelter_map"]["label"] == "Minutes back to start"


def test_plan_route_command_line_start(tmp_path, capsys):
    folder = _site(tmp_path / "s")
    x, y = centre(12, 4)
    assert plan_route.main(["--in", str(folder), "--start", f"{x},{y}"]) == 0
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    assert plan["start"]["cell"] == [12, 4]
    assert "start (--start) at (22.5, 37.5) m" in capsys.readouterr().out


def test_plan_route_with_the_demo_start(tmp_path, capsys):
    folder = _site(tmp_path / "s")
    assert plan_route.main(["--in", str(folder)]) == 0             # no --start
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    s = plan["start"]
    assert s["kind"] == "demo" and s["name"] == "Demo start" and s["landing_status"] == "safe"
    assert s["cell"] == list(DEMO_CELL) and s["source"].startswith("demo start:")
    assert "demo start at (77.5, 52.5) m" in capsys.readouterr().out
    coords = json.loads((folder / "route.geojson").read_text(encoding="utf-8"))["features"][0]["geometry"]["coordinates"]
    assert coords[0] == coords[-1] == list(centre(*DEMO_CELL))


@pytest.mark.parametrize("bad", ["12", "a,b", "1,2,3", "nan,1"])
def test_a_bad_start_argument_is_refused(bad, capsys):
    with pytest.raises(SystemExit):
        plan_route.parse_args(["--start", bad])
    assert "--start" in capsys.readouterr().err


def test_plan_json_keys_are_unchanged_apart_from_the_start_record(tmp_path):
    plan = json.loads(run_site(_site(tmp_path / "s")).files["plan.json"])
    assert set(plan["start"]) == {"id", "name", "landing_id", "xy_m", "cell", "source", "kind", "landing_status"}
    assert plan["start"]["landing_id"] is None
    for key in ("crew", "legs", "totals", "budgets", "radiation_dose_usv", "status", "checks", "stop_order",
                "profiles", "sweep", "track", "storm_replan", "shelter_map", "radiation", "assumptions",
                "inputs", "warnings"):
        assert key in plan


def test_plan_json_warns_that_the_stops_are_unverified(tmp_path):
    plan = json.loads(run_site(_site(tmp_path / "s")).files["plan.json"])
    assert sum("unverified" in w for w in plan["warnings"]) == 1


def test_rover_kind_warning_reaches_plan_json(tmp_path):
    plan = json.loads(run_site(_site(tmp_path / "s", kind="rover")).files["plan.json"])
    assert any("kind 'rover', which is deprecated" in w for w in plan["warnings"])


def test_yellow_start_is_a_warning_in_plan_json(tmp_path):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[10, 2] = 1
    plan = json.loads(run_site(_site(tmp_path / "s", hazard=hazard)).files["plan.json"])
    assert plan["status"] == "ok" and any("start (--start)" in w and "yellow" in w for w in plan["warnings"])


def test_blocked_start_stops_plan_route_and_writes_nothing(tmp_path, capsys):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[10, 2] = 2
    folder = _site(tmp_path / "s", hazard=hazard)
    assert plan_route.main([*with_start(folder), "--in", str(folder)]) == 2
    err = capsys.readouterr().err
    assert "start (--start)" in err and "red hazard cell" in err
    assert not (folder / "plan.json").exists()


def test_start_outside_the_grid_stops_plan_route(tmp_path, capsys):
    folder = _site(tmp_path / "s")
    assert plan_route.main(["--in", str(folder), "--start", "5000,10"]) == 2
    assert "outside the site grid" in capsys.readouterr().err
    assert not (folder / "plan.json").exists()


# ---- the start's id is always "start" ----------------------------------------
def _rover_site(folder):
    """A site whose waypoint file uses the old kind and id, 'rover'."""
    write_full_site(folder, np.zeros(SHAPE, np.float32), np.zeros(SHAPE, np.uint8), CELL, [
        ("rover", "Rover", "rover", *centre(10, 2)), ("stop1", "North stop", "stop", *centre(3, 20)),
    ])
    return folder


def test_outputs_never_use_the_rover_id(tmp_path):
    result = run_site(_rover_site(tmp_path / "s"))
    plan = json.loads(result.files["plan.json"])
    assert plan["start"]["id"] == "start" and plan["start"]["name"] == "Start"
    assert [(l["from"], l["to"]) for l in plan["legs"]] == [("start", "stop1"), ("stop1", "start")]
    # everything except the warnings, which have to name the old kind and the ignored waypoint
    assert "rover" not in json.dumps({k: v for k, v in plan.items() if k != "warnings"}).lower()
    assert any("kind 'rover', which is deprecated" in w for w in plan["warnings"])
    for name, data in result.files.items():
        if name.endswith(".geojson"):
            assert b"rover" not in data.lower()


def test_a_stop_cannot_take_the_id_start(flat_site):
    write_waypoints(flat_site.folder, [("start", "Odd stop", "stop", 52.5, 52.5), ("a", "A", "stop", 5.0, 95.0)])
    with pytest.raises(tour.RouteError, match="a stop cannot use the id 'start'"):
        tour.load_waypoints(flat_site.folder, g.read_grid(flat_site.folder))


# ---- each warning prints once ------------------------------------------------
def test_start_warnings_print_once_on_the_command_line(tmp_path):
    """Run the real script: pytest's own log handler would hide a doubled message."""
    folder = _rover_site(tmp_path / "s")
    script = Path(__file__).resolve().parents[1] / "plan_route.py"
    run = subprocess.run([sys.executable, "-B", str(script), "--in", str(folder), "--start", "22.5,37.5"],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    text = run.stdout + run.stderr
    assert text.count("uses kind 'rover', which is deprecated") == 1
    assert text.count("start waypoint 'rover'") == 1
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    assert sum("uses kind 'rover'" in w for w in plan["warnings"]) == 1
    assert sum("start waypoint 'rover'" in w for w in plan["warnings"]) == 1
