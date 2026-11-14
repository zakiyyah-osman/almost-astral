"""The starts (the [starts.*] of config.toml), their validation, the default start, and the old 'rover' kind."""
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
from conftest import (
    config_for, config_text, run_site, sha256_of, with_config, write_config, write_full_site, write_waypoints,
)
from start import (
    BUFFER, NODATA, RED, REACHABLE, SEALED, SLOPE, StartError, block_code, block_codes, check_start,
    default_start, staleness_warnings, start_cell, starts, validate_starts,
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


def cfg_with(starts_xy, default=None):
    """The shipped config with its starts replaced: {id: (x, y)}, default the first unless given."""
    return Config.from_dict(
        __import__("tomllib").loads(config_text(starts_xy, default=default))
    )


def cfg_with_start(xy):
    return cfg_with({"L1": xy})


# ---- the config --------------------------------------------------------------
def test_the_shipped_config_has_three_temporary_landing_spots():
    assert CFG.starts() == {"L1": (1112.5, 607.5), "L2": (1007.5, 367.5), "L3": (1187.5, 1227.5)}
    assert list(CFG.starts()) == ["L1", "L2", "L3"]                      # config order
    assert CFG.default_start_id() == "L1"
    for sid in ("L1", "L2", "L3"):
        source = CFG.raw["starts"][sid]["source"]
        assert sid in source and "landing.js" in source and "temporary" in source.lower()
    assert [s.id for s in starts(CFG)] == ["L1", "L2", "L3"] and default_start(CFG).xy == (1112.5, 607.5)


@pytest.mark.parametrize("bad", [[1.0], [1.0, 2.0, 3.0], [], [-1.0, 5.0], "here", [1.0, True]])
def test_a_start_must_be_two_non_negative_numbers(bad):
    raw = copy.deepcopy(CFG.raw)
    raw["starts"]["L2"]["value"] = bad
    with pytest.raises(ConfigError, match=r"starts\.L2"):
        Config.from_dict(raw)


@pytest.mark.parametrize("sid", ["1L", "L 2", "L.2", "-L", "", "L/2"])
def test_a_bad_start_id_is_rejected(sid):
    raw = copy.deepcopy(CFG.raw)
    raw["starts"][sid] = copy.deepcopy(raw["starts"]["L2"])
    with pytest.raises(ConfigError, match="start id|must be"):
        Config.from_dict(raw)


def test_the_default_must_name_a_start():
    raw = copy.deepcopy(CFG.raw)
    raw["start"]["default"]["value"] = "L9"
    with pytest.raises(ConfigError, match=r"start\.default = 'L9' is not one of the starts: L1, L2, L3"):
        Config.from_dict(raw)
    for bad in (3, None, ["L1"], ""):
        raw["start"]["default"]["value"] = bad
        with pytest.raises(ConfigError, match=r"start\.default"):
            Config.from_dict(raw)


def test_at_least_one_start_is_needed():
    raw = copy.deepcopy(CFG.raw)
    del raw["starts"]
    with pytest.raises(ConfigError, match="no starts"):
        Config.from_dict(raw)
    raw = copy.deepcopy(CFG.raw)
    raw["starts"] = {}
    with pytest.raises(ConfigError, match="no starts"):
        Config.from_dict(raw)


def test_starts_can_be_added_and_the_default_changed():
    cfg = cfg_with({"A": (10.0, 20.0), "B-2": (30.0, 40.0), "C_3": (50.0, 60.0)}, default="B-2")
    assert cfg.starts() == {"A": (10.0, 20.0), "B-2": (30.0, 40.0), "C_3": (50.0, 60.0)}
    assert default_start(cfg).id == "B-2" and default_start(cfg).xy == (30.0, 40.0)


def test_the_hash_parameters_must_be_sha256_text():
    for key in ("dem_sha256", "hazard_sha256"):
        for bad in ("abc", "G" * 64, 5, None):
            raw = copy.deepcopy(CFG.raw)
            raw["start"][key]["value"] = bad
            with pytest.raises(ConfigError, match=rf"start\.{key}"):
                Config.from_dict(raw)


# ---- validation: every blocked reason fails with its own message, naming the start ------
def test_valid_start_has_no_warnings():
    c = make_cost()
    cell = start_cell(GRID, centre(10, 2))
    assert cell == (10, 2)
    assert check_start(c, cell, centre(10, 2), np.zeros(SHAPE, np.uint8)) == ()


def test_start_outside_the_grid_fails():
    with pytest.raises(StartError, match=r"start \(500, 50\) m is outside the site grid.*Set the start"):
        start_cell(GRID, (500.0, 50.0))
    with pytest.raises(StartError, match=r"start 'L2' \(500, 50\) m is outside the site grid.*starts\.L2") as e:
        start_cell(GRID, (500.0, 50.0), name="L2")
    assert e.value.start_id == "L2"


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
        check_start(c, cell, xy, name="L2")
    msg = str(e.value)
    assert text in msg and f"{xy[0]:g}" in msg and "start 'L2'" in msg and "starts.L2" in msg
    assert e.value.waypoint_id == "start" and e.value.start_id == "L2"
    with pytest.raises(StartError, match="Set the start in routing/config.toml"):
        check_start(c, cell, xy)                       # without a name the message still works


def test_block_codes_match_block_code_everywhere():
    c, _ = _blocked_case("slope")
    codes = block_codes(c)
    for cell in np.ndindex(SHAPE):
        assert codes[cell] == block_code(c, cell)
    assert (codes == REACHABLE).sum() == (~c.blocked).sum()


# ---- validate_starts: every start is checked, the failing one is named ---------
def test_validate_starts_checks_all_and_returns_their_cells():
    cfg = cfg_with({"A": centre(10, 2), "B": centre(3, 20), "C": centre(17, 26)})
    infos = validate_starts(cfg, make_cost(), np.zeros(SHAPE, np.uint8))
    assert list(infos) == ["A", "B", "C"]
    assert [i.cell for i in infos.values()] == [(10, 2), (3, 20), (17, 26)]
    assert all(i.warnings == () for i in infos.values())


@pytest.mark.parametrize("bad_id", ["A", "B", "C"])
def test_an_invalid_start_fails_with_its_own_name(bad_id):
    hazard = np.zeros(SHAPE, np.uint8)
    cells = {"A": (10, 2), "B": (3, 20), "C": (17, 26)}
    hazard[cells[bad_id]] = 2
    cfg = cfg_with({k: centre(*v) for k, v in cells.items()})
    with pytest.raises(StartError) as e:
        validate_starts(cfg, make_cost(hazard), hazard)
    assert e.value.start_id == bad_id and f"start {bad_id!r}" in str(e.value)
    assert "red hazard cell" in str(e.value) and f"starts.{bad_id}" in str(e.value)
    for other in set(cells) - {bad_id}:
        assert f"start {other!r}" not in str(e.value)


def test_a_start_outside_the_grid_is_named():
    cfg = cfg_with({"A": centre(10, 2), "B": (5000.0, 10.0)})
    with pytest.raises(StartError, match=r"start 'B' \(5000, 10\) m is outside"):
        validate_starts(cfg, make_cost())


def test_validate_starts_collects_a_warning_per_careful_start():
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[10, 2] = 1
    hazard[3, 20] = 1
    cfg = cfg_with({"A": centre(10, 2), "B": centre(3, 20), "C": centre(17, 26)})
    infos = validate_starts(cfg, make_cost(hazard), hazard)
    assert [len(i.warnings) for i in infos.values()] == [1, 1, 0]
    assert "start 'A'" in infos["A"].warnings[0] and "yellow" in infos["A"].warnings[0]


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


# ---- resolve_start: the default start, the config wins over the waypoint ------
def test_config_start_wins_and_far_waypoint_warns(caplog):
    c = make_cost()
    wp = tour.Waypoint("base", "Base", "start", *centre(5, 5), (5, 5))
    with caplog.at_level(logging.WARNING, logger="tour"):
        start, warnings = tour.resolve_start(cfg_with_start(centre(10, 2)), c, None, wp)
    assert start.cell == (10, 2) and (start.x, start.y) == centre(10, 2)
    assert start.id == "start" and start.name == "Start" and start.kind == "start"   # never the waypoint's id
    assert start.landing_id == "L1"
    assert len(warnings) == 1 and "more than half a cell from the default start 'L1'" in warnings[0]
    assert "the config value is used" in warnings[0]
    assert "more than half a cell" in caplog.text


def test_waypoint_within_half_a_cell_gives_no_warning():
    x, y = centre(10, 2)
    wp = tour.Waypoint("s", "S", "start", x + 2.0, y - 1.0, (10, 2))
    start, warnings = tour.resolve_start(cfg_with_start((x, y)), make_cost(), None, wp)
    assert warnings == () and start.id == "start"


def test_no_start_waypoint_uses_the_id_start():
    start, warnings = tour.resolve_start(cfg_with_start(centre(10, 2)), make_cost())
    assert (start.id, start.name, start.cell) == ("start", "Start", (10, 2)) and warnings == ()


def test_the_default_start_is_the_one_resolved():
    cfg = cfg_with({"L1": centre(10, 2), "L2": centre(3, 20), "L3": centre(17, 26)}, default="L2")
    start, _ = tour.resolve_start(cfg, make_cost())
    assert start.landing_id == "L2" and start.cell == (3, 20) and (start.x, start.y) == centre(3, 20)
    assert start.id == "start"                                  # the id in outputs stays "start"


def test_resolve_start_checks_every_start_not_only_the_default():
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[17, 26] = 2
    cfg = cfg_with({"L1": centre(10, 2), "L2": centre(3, 20), "L3": centre(17, 26)})   # L1 is the default
    with pytest.raises(StartError, match=r"start 'L3'.*red hazard cell") as e:
        tour.resolve_start(cfg, make_cost(hazard), hazard)
    assert e.value.start_id == "L3"


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


# ---- plan_route.py plans from the default start only --------------------------
def _site(folder, kind="start", start_cell_=(10, 2), config_cell=None, **kw):
    waypoints = [
        ("base", "Base", kind, *centre(*start_cell_)),
        ("stop1", "North stop", "stop", *centre(3, 20)),
    ]
    start = None if config_cell is None else centre(*config_cell)
    write_full_site(folder, np.zeros(SHAPE, np.float32), np.zeros(SHAPE, np.uint8), CELL, waypoints,
                    start=start, **kw)
    return folder


def test_plan_starts_at_the_config_start_and_warns_about_the_waypoint(tmp_path):
    folder = _site(tmp_path / "s", config_cell=(12, 4))
    result = run_site(folder)
    plan = json.loads(result.files["plan.json"])
    assert plan["start"]["xy_m"] == list(centre(12, 4)) and plan["start"]["cell"] == [12, 4]
    assert plan["start"]["id"] == "start" and plan["start"]["landing_id"] == "L1"
    assert [leg["from"] for leg in plan["legs"]] == ["start", "stop1"] and plan["legs"][-1]["to"] == "start"
    assert any("more than half a cell" in w for w in plan["warnings"])
    coords = json.loads(result.files["route.geojson"])["features"][0]["geometry"]["coordinates"]
    assert coords[0] == coords[-1] == list(centre(12, 4))
    assert plan["track"][0]["shelter_min"] == 15            # minutes back to start: only ingress at the start
    assert plan["shelter_map"]["label"] == "Minutes back to start"


def test_plan_route_uses_the_default_start_and_records_it(tmp_path):
    spots = {"L1": centre(10, 2), "L2": centre(12, 6), "L3": centre(5, 4)}
    plans = {}
    for default in ("L1", "L2", "L3"):
        folder = _site(tmp_path / default, starts=spots, default=default)
        plan = json.loads(run_site(folder).files["plan.json"])
        plans[default] = plan
        assert plan["start"]["landing_id"] == default and plan["start"]["id"] == "start"
        assert plan["start"]["xy_m"] == list(spots[default])
        coords = json.loads(run_site(folder).files["route.geojson"])["features"][0]["geometry"]["coordinates"]
        assert coords[0] == coords[-1] == list(spots[default])
        assert plan["start"]["source"].endswith("(a landing spot, temporary)") and default in plan["start"]["source"]
    # the three plans differ only through the start
    assert len({json.dumps(p["legs"]) for p in plans.values()}) == 3


def test_plan_json_keys_are_unchanged_apart_from_the_start_record(tmp_path):
    plan = json.loads(run_site(_site(tmp_path / "s")).files["plan.json"])
    assert set(plan["start"]) == {"id", "name", "landing_id", "xy_m", "cell", "source"}
    for key in ("crew", "legs", "totals", "budgets", "radiation_dose_usv", "status", "checks", "stop_order",
                "profiles", "sweep", "track", "storm_replan", "shelter_map", "radiation", "assumptions",
                "inputs", "warnings"):
        assert key in plan


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
    assert plan["status"] == "ok" and any("start 'L1'" in w and "yellow" in w for w in plan["warnings"])


def test_blocked_config_start_stops_plan_route_and_writes_nothing(tmp_path, capsys):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[10, 2] = 2
    folder = tmp_path / "s"
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("base", "Base", "start", *centre(10, 2)), ("stop1", "North stop", "stop", *centre(3, 20)),
    ])
    assert plan_route.main([*with_config(folder), "--in", str(folder)]) == 2
    err = capsys.readouterr().err
    assert "start 'L1'" in err and "red hazard cell" in err
    assert not (folder / "plan.json").exists()


def test_a_bad_start_that_is_not_the_default_still_stops_plan_route(tmp_path, capsys):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[17, 26] = 2
    folder = tmp_path / "s"
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("base", "Base", "start", *centre(10, 2)), ("stop1", "North stop", "stop", *centre(3, 20)),
    ], starts={"L1": centre(10, 2), "L2": centre(3, 5), "L3": centre(17, 26)})
    assert plan_route.main([*with_config(folder), "--in", str(folder)]) == 2
    err = capsys.readouterr().err
    assert "start 'L3'" in err and "red hazard cell" in err and "start 'L2'" not in err
    assert not (folder / "plan.json").exists()


def test_config_start_outside_the_grid_stops_plan_route(tmp_path, capsys):
    folder = _site(tmp_path / "s")
    assert plan_route.main(["--in", str(folder)]) == 2      # the shipped config: L1 is outside this small site
    err = capsys.readouterr().err
    assert "start 'L1'" in err and "outside the site grid" in err and "starts.L1" in err
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
    old = "[starts.L1]\nvalue = " + here
    assert old in text
    far.write_text(text.replace(old, "[starts.L1]\nvalue = " + there, 1), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "plan_route.py"
    run = subprocess.run([sys.executable, "-B", str(script), "--config", str(far), "--in", str(folder)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    text = run.stdout + run.stderr
    assert text.count("uses kind 'rover', which is deprecated") == 1
    assert text.count("more than half a cell from the default start 'L1'") == 1
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    assert sum("uses kind 'rover'" in w for w in plan["warnings"]) == 1
    assert sum("more than half a cell" in w for w in plan["warnings"]) == 1


# ---- the data the starts were computed on ------------------------------------
def test_staleness_warns_when_the_data_is_not_the_data_the_starts_were_computed_on(tmp_path):
    folder = _site(tmp_path / "s")
    cfg = load_config(config_for(folder))
    assert staleness_warnings(cfg, folder) == ()                    # write_full_site wrote this site's hashes
    other = tmp_path / "other.toml"
    write_config(other, {"L1": centre(10, 2)}, text=config_for(folder).read_text(encoding="utf-8"),
                 dem_sha="a" * 64)
    warnings = staleness_warnings(load_config(other), folder)
    assert len(warnings) == 1 and "dem.tif is not the file the starts were computed on" in warnings[0]
    assert "start.dem_sha256" in warnings[0] and sha256_of(folder / "dem.tif")[:12] in warnings[0]
    write_config(other, {"L1": centre(10, 2)}, text=other.read_text(encoding="utf-8"), hazard_sha="b" * 64)
    both = staleness_warnings(load_config(other), folder)
    assert len(both) == 2 and "hazard.tif" in both[1] and "start.hazard_sha256" in both[1]


def test_staleness_reaches_plan_json(tmp_path):
    folder = _site(tmp_path / "s")
    other = tmp_path / "stale.toml"
    write_config(other, {"L1": centre(10, 2)}, text=config_for(folder).read_text(encoding="utf-8"),
                 dem_sha="c" * 64)
    import plan_route as pr
    plan = json.loads(pr.run(folder, other).files["plan.json"])
    assert sum("dem.tif is not the file the starts were computed on" in w for w in plan["warnings"]) == 1
    clean = json.loads(run_site(folder).files["plan.json"])
    assert not any("computed on" in w for w in clean["warnings"])
