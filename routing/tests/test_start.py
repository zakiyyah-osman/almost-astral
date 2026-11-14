"""The fixed start (start.xy_m in config.toml), its validation, and the old 'rover' kind."""
import copy
import json
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import cost
import grid as g
import plan_route
import tour
from config import Config, ConfigError, load_config
from conftest import config_for, run_site, with_config, write_full_site, write_waypoints
from start import (
    BUFFER, NODATA, RED, REACHABLE, SEALED, SLOPE, StartError, block_code, block_codes, check_start,
    start_cell, start_xy,
)

CFG = load_config()
P = cost.Params.from_config(CFG)
SHAPE, CELL = (20, 30), 5.0
GRID = g.Grid(SHAPE[1], SHAPE[0], CELL)


def centre(r, c):
    return GRID.cell_centre(r, c)


def make_cost(hazard=None, dem=None, slope=None, p=P):
    hazard = np.zeros(SHAPE, np.uint8) if hazard is None else hazard
    dem = np.zeros(SHAPE) if dem is None else dem
    slope = g.slope_deg(dem, CELL) if slope is None else slope
    return cost.build(dem, hazard, slope, GRID, p)


def cfg_with_start(xy):
    raw = copy.deepcopy(CFG.raw)
    raw["start"]["xy_m"]["value"] = [float(xy[0]), float(xy[1])]
    return Config.from_dict(raw)


# ---- the config value --------------------------------------------------------
def test_start_is_landing_spot_l1_in_the_shipped_config():
    assert start_xy(CFG) == (1387.5, 712.5)
    assert "L1" in CFG.raw["start"]["xy_m"]["source"] and "temporary" in CFG.raw["start"]["xy_m"]["source"]


@pytest.mark.parametrize("bad", [[1.0], [1.0, 2.0, 3.0], [], [-1.0, 5.0], "here", [1.0, True]])
def test_start_must_be_two_non_negative_numbers(bad):
    raw = copy.deepcopy(CFG.raw)
    raw["start"]["xy_m"]["value"] = bad
    with pytest.raises(ConfigError, match="start.xy_m"):
        Config.from_dict(raw)


# ---- validation: every blocked reason fails with its own message -------------
def test_valid_start_has_no_warnings():
    c = make_cost()
    cell = start_cell(GRID, centre(10, 2))
    assert cell == (10, 2)
    assert check_start(c, cell, centre(10, 2), np.zeros(SHAPE, np.uint8)) == ()


def test_start_outside_the_grid_fails():
    with pytest.raises(StartError, match=r"start \(500, 50\) m is outside the site grid.*start\.xy_m"):
        start_cell(GRID, (500.0, 50.0))


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
        check_start(c, cell, xy)
    msg = str(e.value)
    assert text in msg and f"{xy[0]:g}" in msg and "start.xy_m" in msg
    assert e.value.waypoint_id == "start"


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


# ---- resolve_start: the config wins over the waypoint ------------------------
def test_config_start_wins_and_far_waypoint_warns(caplog):
    c = make_cost()
    wp = tour.Waypoint("base", "Base", "start", *centre(5, 5), (5, 5))
    with caplog.at_level(logging.WARNING, logger="tour"):
        start, warnings = tour.resolve_start(cfg_with_start(centre(10, 2)), c, None, wp)
    assert start.cell == (10, 2) and (start.x, start.y) == centre(10, 2)
    assert start.id == "start" and start.name == "Start" and start.kind == "start"   # never the waypoint's id
    assert len(warnings) == 1 and "more than half a cell" in warnings[0] and "config value is used" in warnings[0]
    assert "more than half a cell" in caplog.text


def test_waypoint_within_half_a_cell_gives_no_warning():
    x, y = centre(10, 2)
    wp = tour.Waypoint("s", "S", "start", x + 2.0, y - 1.0, (10, 2))
    start, warnings = tour.resolve_start(cfg_with_start((x, y)), make_cost(), None, wp)
    assert warnings == () and start.id == "start"


def test_no_start_waypoint_uses_the_id_start():
    start, warnings = tour.resolve_start(cfg_with_start(centre(10, 2)), make_cost())
    assert (start.id, start.name, start.cell) == ("start", "Start", (10, 2)) and warnings == ()


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
    assert wp.id == "rover" and [s.id for s in stops] == ["stop1"]      # the file's own id, only compared
    start, _ = tour.resolve_start(cfg_with_start(centre(10, 2)), make_cost(), None, wp)
    assert start.id == "start"                                          # never "rover" in what is used


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


# ---- plan_route.py measures everything from the config start -----------------
def _site(folder, kind="start", start_cell_=(10, 2), config_cell=None):
    waypoints = [
        ("base", "Base", kind, *centre(*start_cell_)),
        ("stop1", "North stop", "stop", *centre(3, 20)),
    ]
    start = None if config_cell is None else centre(*config_cell)
    write_full_site(folder, np.zeros(SHAPE, np.float32), np.zeros(SHAPE, np.uint8), CELL, waypoints, start=start)
    return folder


def test_plan_starts_at_the_config_start_and_warns_about_the_waypoint(tmp_path):
    folder = _site(tmp_path / "s", config_cell=(12, 4))
    result = run_site(folder)
    plan = json.loads(result.files["plan.json"])
    assert plan["start"]["xy_m"] == list(centre(12, 4)) and plan["start"]["cell"] == [12, 4]
    assert plan["start"]["id"] == "start"
    assert [leg["from"] for leg in plan["legs"]] == ["start", "stop1"] and plan["legs"][-1]["to"] == "start"
    assert any("more than half a cell" in w for w in plan["warnings"])
    coords = json.loads(result.files["route.geojson"])["features"][0]["geometry"]["coordinates"]
    assert coords[0] == coords[-1] == list(centre(12, 4))
    assert plan["track"][0]["shelter_min"] == 15            # minutes back to start: only ingress at the start
    assert plan["shelter_map"]["label"] == "Minutes back to start"


def test_rover_kind_warning_reaches_plan_json(tmp_path):
    plan = json.loads(run_site(_site(tmp_path / "s", kind="rover")).files["plan.json"])
    assert any("kind 'rover', which is deprecated" in w for w in plan["warnings"])


def test_yellow_start_is_a_warning_in_plan_json(tmp_path):
    folder = _site(tmp_path / "s")
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[10, 2] = 1
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("base", "Base", "start", *centre(10, 2)), ("stop1", "North stop", "stop", *centre(3, 20)),
    ])
    plan = json.loads(run_site(folder).files["plan.json"])
    assert plan["status"] == "ok" and any("yellow" in w for w in plan["warnings"])


def test_blocked_config_start_stops_plan_route_and_writes_nothing(tmp_path, capsys):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[10, 2] = 2
    folder = tmp_path / "s"
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("base", "Base", "start", *centre(10, 2)), ("stop1", "North stop", "stop", *centre(3, 20)),
    ])
    assert plan_route.main([*with_config(folder), "--in", str(folder)]) == 2
    assert "red hazard cell" in capsys.readouterr().err
    assert not (folder / "plan.json").exists()


def test_config_start_outside_the_grid_stops_plan_route(tmp_path, capsys):
    folder = _site(tmp_path / "s")
    assert plan_route.main(["--in", str(folder)]) == 2      # the shipped config: L1 is outside this small site
    assert "outside the site grid" in capsys.readouterr().err
    assert config_for(folder).exists()


# ---- the start's id is always "start" ----------------------------------------
def _rover_site(folder):
    """A site whose waypoint file uses the old kind and id, 'rover', at the config start."""
    write_full_site(folder, np.zeros(SHAPE, np.float32), np.zeros(SHAPE, np.uint8), CELL, [
        ("rover", "Rover", "rover", *centre(10, 2)), ("stop1", "North stop", "stop", *centre(3, 20)),
    ])
    return folder


def test_outputs_never_use_the_rover_id(tmp_path):
    result = run_site(_rover_site(tmp_path / "s"))
    plan = json.loads(result.files["plan.json"])
    assert plan["start"]["id"] == "start" and plan["start"]["name"] == "Start"
    assert [(l["from"], l["to"]) for l in plan["legs"]] == [("start", "stop1"), ("stop1", "start")]
    # everything except the deprecation warning, which has to name the old kind
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
    far = tmp_path / "far.toml"
    here, there = (repr([float(v) for v in centre(*c)]) for c in ((10, 2), (12, 4)))
    text = config_for(folder).read_text(encoding="utf-8")
    old = "[start.xy_m]\nvalue = " + here
    assert old in text
    far.write_text(text.replace(old, "[start.xy_m]\nvalue = " + there, 1), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "plan_route.py"
    run = subprocess.run([sys.executable, "-B", str(script), "--config", str(far), "--in", str(folder)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    text = run.stdout + run.stderr
    assert text.count("uses kind 'rover', which is deprecated") == 1
    assert text.count("more than half a cell from start.xy_m") == 1
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    assert sum("uses kind 'rover'" in w for w in plan["warnings"]) == 1
    assert sum("more than half a cell" in w for w in plan["warnings"]) == 1
