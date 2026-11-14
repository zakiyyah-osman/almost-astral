"""export_reach.py: the reach grids, their manifest and the reference traceback."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import cost
import export_reach as er
import grid as g
import start as start_mod
import tour
from config import load_config
from conftest import config_for, with_config, write_config, write_full_site
from search import Searcher, summarise

REPO = Path(__file__).resolve().parents[2]
REAL_OUT = REPO / "data" / "out"
CFG = load_config()
SHAPE, CELL = (20, 30), 5.0
GRID = g.Grid(SHAPE[1], SHAPE[0], CELL)
START = (10, 2)
PROFILES = [name for name, _ in tour.PROFILES]
DESTS = [(10, 25), (3, 20), (17, 26), (10, 12), (0, 29), (19, 0), START]


def centre(r, c):
    return GRID.cell_centre(r, c)


def band_site(folder, fake=False):
    """Flat, a yellow band between the start and the east: the profiles choose different paths."""
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[3:17, 10:15] = 1
    hazard[17:20, 10:15] = 2                     # red to the south of the band: near-red risk too
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("start", "Start", "start", *centre(*START)), ("stop1", "A", "stop", *centre(3, 20)),
    ], fake=fake)
    return folder


def reasons_site(folder):
    """One cell for each reason code."""
    hazard = np.zeros(SHAPE, np.uint8)
    dem = np.zeros(SHAPE, np.float32)
    hazard[8, 8] = hazard[9, 9] = 2              # red, and the gap between them is sealed
    hazard[1:6, 24] = hazard[1:6, 28] = 2        # a red ring: the pocket inside is walled off
    hazard[1, 24:29] = hazard[5, 24:29] = 2
    dem[15, 20] = 10.0                           # its neighbours are over 20 deg, itself in the buffer
    dem[17, 5] = np.nan                          # no data
    write_full_site(folder, dem, hazard, CELL, [
        ("start", "Start", "start", *centre(*START)), ("stop1", "A", "stop", *centre(10, 12)),
    ])
    return folder


def export(folder, tmp_path, name="reach"):
    out = tmp_path / name
    result = er.run(folder, config_for(folder))
    for fname, data in result.files.items():
        out.mkdir(parents=True, exist_ok=True)
        (out / fname).write_bytes(data)
    return result, er.Reach.load(out)


def model_for(folder, cfg):
    site = g.load_site(folder)
    return cost.build(site.dem, site.hazard, site.slope, site.grid, cost.Params.from_config(cfg))


# ---- traceback = the in-memory search ----------------------------------------
def test_traceback_matches_the_search_path_and_totals(tmp_path):
    folder = band_site(tmp_path / "s")
    cfg = load_config(config_for(folder))
    model = model_for(folder, cfg)
    _, reach = export(folder, tmp_path)
    for name, key in tour.PROFILES:
        tree = Searcher(model, cfg.value(key), 8).tree(START)
        for dest in DESTS:
            f = reach.trace(name, *centre(*dest))
            p = f["properties"]
            assert p["reachable"], (name, dest)
            want = tree.path_to(dest)
            assert [tuple(c) for c in p["cells"]] == list(want.cells), (name, dest)
            assert f["geometry"]["coordinates"][0] == list(centre(*START))
            assert f["geometry"]["coordinates"][-1] == list(centre(*dest))
            assert p["walk_min"] == pytest.approx(want.physical_min, rel=1e-6, abs=1e-6)
            assert p["distance_m"] == pytest.approx(want.distance_m, rel=1e-6, abs=1e-6)
            assert p["risk_min"] == pytest.approx(want.risk_min, rel=1e-6, abs=1e-6)


def test_profiles_really_differ_on_the_band_site(tmp_path):
    _, reach = export(band_site(tmp_path / "s"), tmp_path)
    fast = reach.trace("fastest", *centre(10, 25))["properties"]
    safe = reach.trace("safest", *centre(10, 25))["properties"]
    assert fast["cells"] != safe["cells"]
    assert fast["walk_min"] < safe["walk_min"] and fast["risk_min"] > safe["risk_min"]


def test_time_rises_and_risk_falls_from_fastest_to_safest(tmp_path):
    _, reach = export(band_site(tmp_path / "s"), tmp_path)
    for dest in DESTS:
        t = [reach.trace(n, *centre(*dest))["properties"] for n in PROFILES]
        assert t[0]["walk_min"] <= t[1]["walk_min"] + 1e-4 <= t[2]["walk_min"] + 2e-4, dest
        assert t[0]["risk_min"] + 2e-4 >= t[1]["risk_min"] + 1e-4 >= t[2]["risk_min"], dest


def test_destination_at_the_start_is_a_zero_length_line(tmp_path):
    _, reach = export(band_site(tmp_path / "s"), tmp_path)
    f = reach.trace("balanced", *centre(*START))
    assert f["geometry"]["coordinates"] == [list(centre(*START))] * 2
    assert f["properties"]["walk_min"] == 0.0 and f["properties"]["distance_m"] == 0.0
    assert f["properties"]["cells"] == [list(START)]


@pytest.mark.skipif(not (REAL_OUT / "dem.tif").exists(), reason="data/out has no inputs")
def test_traceback_matches_the_search_on_the_real_site(tmp_path):
    result = er.run(REAL_OUT)
    out = tmp_path / "reach"
    out.mkdir()
    for name, data in result.files.items():
        (out / name).write_bytes(data)
    reach = er.Reach.load(out)
    model = model_for(REAL_OUT, CFG)
    start = tuple(result.manifest["start"]["cell"])
    dests = [(500, 1500), (1400, 1760), (1600, 500), (100, 100), (1900, 1900)]
    for name, key in tour.PROFILES:
        tree = Searcher(model, CFG.value(key), 8).tree(start)
        for xy in dests:
            p = reach.trace(name, *xy)["properties"]
            cell = model.grid.xy_to_cell(*xy)
            if not p["reachable"]:
                assert not tree.reachable(cell)
                continue
            want = tree.path_to(cell)
            assert [tuple(c) for c in p["cells"]] == list(want.cells)
            assert p["walk_min"] == pytest.approx(want.physical_min, rel=1e-6)
            assert p["distance_m"] == pytest.approx(want.distance_m, rel=1e-6)
            assert p["risk_min"] == pytest.approx(want.risk_min, rel=1e-5, abs=1e-5)


# ---- reason codes ------------------------------------------------------------
def test_unreachable_reason_codes(tmp_path):
    _, reach = export(reasons_site(tmp_path / "s"), tmp_path)
    r = reach.reason
    assert r[10, 10] == start_mod.REACHABLE
    assert r[8, 8] == start_mod.RED and r[9, 9] == start_mod.RED
    assert r[8, 9] == start_mod.SEALED and r[9, 8] == start_mod.SEALED
    assert r[14, 20] == start_mod.SLOPE and r[15, 19] == start_mod.SLOPE
    assert r[15, 20] == start_mod.BUFFER
    assert r[17, 5] == start_mod.NODATA
    assert r[3, 26] == start_mod.WALLED_OFF
    # reason 0 exactly where there is a path, and the f32 grids are NaN everywhere else
    for name in PROFILES:
        t = reach.grids[name]["time"]
        assert np.array_equal(np.isfinite(t), r == start_mod.REACHABLE)
        assert np.isnan(reach.grids[name]["dist"][r != 0]).all() and np.isnan(reach.grids[name]["risk"][r != 0]).all()
        assert (reach.grids[name]["dir"][r != 0] == er.NO_STEP).all()


def test_trace_explains_an_unreachable_destination(tmp_path):
    _, reach = export(reasons_site(tmp_path / "s"), tmp_path)
    walled = reach.trace("safest", *centre(3, 26))
    assert walled["geometry"] is None
    assert walled["properties"]["reason"] == start_mod.WALLED_OFF and "walled off" in walled["properties"]["reason_text"]
    red = reach.trace("safest", *centre(8, 8))["properties"]
    assert red["reason_name"] == "red" and red["reason_text"] == "red hazard cell"
    outside = reach.trace("safest", 5000.0, 5.0)["properties"]
    assert outside["reason"] == er.OUTSIDE and not outside["reachable"]


# ---- manifest ----------------------------------------------------------------
def test_manifest_round_trips(tmp_path):
    folder = band_site(tmp_path / "s")
    result, reach = export(folder, tmp_path)
    m = reach.manifest
    assert m == json.loads(result.files[er.MANIFEST_FILE])
    assert m["format_version"] == er.FORMAT_VERSION and m["byte_order"] == "little"
    assert m["grid"]["width"] == 30 and m["grid"]["height"] == 20 and m["grid"]["cell_m"] == 5.0
    assert m["grid"]["origin_m"] == [0.0, 0.0] and m["grid"]["crop_m"] == "full" and m["grid"]["downsample"] == 1
    assert m["start"]["xy_m"] == list(centre(*START)) and m["start"]["cell"] == list(START)
    assert {n: p["w"] for n, p in m["profiles"].items()} == {"fastest": 0.0, "balanced": 1.0, "safest": 5.0}
    assert m["fake"] is False
    assert [d["code"] for d in m["direction_codes"]] == list(range(9))
    assert [r["code"] for r in m["reason_codes"]] == list(range(7))
    n = 30 * 20
    for name, info in m["files"].items():
        data = (reach.folder / name).read_bytes()
        assert len(data) == info["bytes"] and hashlib.sha256(data).hexdigest() == info["sha256"]
        assert info["bytes"] == (4 * n if name.endswith(".f32") else n)
    assert set(m["files"]) == set(result.files) - {er.MANIFEST_FILE}
    for name in PROFILES:
        assert reach.grids[name]["time"].dtype == np.dtype("<f4") and reach.grids[name]["dir"].dtype == np.uint8
    assert m["inputs_sha256"]["dem.tif"] == hashlib.sha256((folder / "dem.tif").read_bytes()).hexdigest()


def test_fake_flag_is_copied_from_layers_json(tmp_path):
    result = er.run(band_site(tmp_path / "s", fake=True), config_for(tmp_path / "s"))
    assert result.manifest["fake"] is True


def test_config_hash_is_stable_and_follows_the_config(tmp_path):
    folder = band_site(tmp_path / "s")
    a = er.run(folder, config_for(folder)).manifest["config_sha256"]
    b = er.run(folder, config_for(folder)).manifest["config_sha256"]
    other = tmp_path / "other.toml"
    write_config(other, centre(*START), config_for(folder).read_text(encoding="utf-8").replace("value = 360\n", "value = 300\n", 1))
    c = er.run(folder, other).manifest["config_sha256"]
    assert a == b != c


def test_two_runs_give_identical_bytes(tmp_path):
    folder = band_site(tmp_path / "s")
    assert er.run(folder, config_for(folder)).files == er.run(folder, config_for(folder)).files


# ---- budget ------------------------------------------------------------------
def test_budget_rule_is_one_way_with_one_stop_at_the_destination(tmp_path):
    folder = band_site(tmp_path / "s")
    b = er.run(folder, config_for(folder)).manifest["budget"]
    assert b["usable_min"] == pytest.approx(252.0) and b["ingress_min"] == 15 and b["stop_min"] == 25
    assert b["walk_limit_min"] == pytest.approx(212.0)             # 252 - 15 - 25: no return walk
    assert "one_way_limit_min" not in b and "round_trip" not in json.dumps(b)
    assert "needed_min = time + ingress_min + stop_min" in b["rule"] and "No return walk" in b["rule"]


def test_destination_stop_switch_sets_the_stop_to_zero(tmp_path):
    folder = band_site(tmp_path / "s")
    cfg = tmp_path / "nostop.toml"
    text = config_for(folder).read_text(encoding="utf-8")
    old = "[reach.destination_stop]\nvalue = true\n"
    assert old in text
    cfg.write_text(text.replace(old, "[reach.destination_stop]\nvalue = false\n"), encoding="utf-8")
    b = er.run(folder, cfg).manifest["budget"]
    assert b["stop_min"] == 0 and b["walk_limit_min"] == pytest.approx(237.0)


def test_over_budget_flag_follows_the_walk_limit(tmp_path):
    folder = band_site(tmp_path / "s")
    tight = tmp_path / "tight.toml"
    text = config_for(folder).read_text(encoding="utf-8")
    tight.write_text(text.replace("value = 360\n", "value = 60\n", 1), encoding="utf-8")    # usable 42, limit 42 - 15 - 25 = 2
    result = er.run(folder, tight)
    out = tmp_path / "reach"
    out.mkdir()
    for name, data in result.files.items():
        (out / name).write_bytes(data)
    reach = er.Reach.load(out)
    limit = reach.manifest["budget"]["walk_limit_min"]
    assert limit == pytest.approx(2.0)
    near = reach.trace("fastest", *centre(10, 4))["properties"]
    far = reach.trace("fastest", *centre(0, 29))["properties"]
    assert near["walk_min"] < limit and near["over_budget"] is False
    assert far["walk_min"] > limit and far["over_budget"] is True
    assert far["needed_min"] == pytest.approx(far["walk_min"] + 15 + 25)      # one way: time + ingress + stop
    assert "round_trip_min" not in far
    # the flag is exactly "time + ingress_min + stop_min > usable_min"
    usable = reach.manifest["budget"]["usable_min"]
    for p in (near, far):
        assert p["over_budget"] == (p["walk_min"] + 15 + 25 > usable)


# ---- crop and resolution -----------------------------------------------------
def _config_with(folder, tmp_path, crop=None, downsample=None):
    text = config_for(folder).read_text(encoding="utf-8")
    if crop is not None:
        text = text.replace('[reach.crop_m]\nvalue = "full"\n', f"[reach.crop_m]\nvalue = {crop}\n")
    if downsample is not None:
        text = text.replace("[reach.downsample]\nvalue = 1\n", f"[reach.downsample]\nvalue = {downsample}\n")
    path = tmp_path / "variant.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_crop_exports_only_the_box_with_its_origin(tmp_path):
    folder = band_site(tmp_path / "s")
    cfg = _config_with(folder, tmp_path, crop="[0.0, 20.0, 100.0, 80.0]")
    result = er.run(folder, cfg)
    m = result.manifest
    assert (m["grid"]["width"], m["grid"]["height"]) == (20, 12) and m["grid"]["origin_m"] == [0.0, 20.0]
    assert m["start"]["cell"] == [6, 2]                         # site row 10 minus the 4 rows cut off in the north
    assert len(result.files["fastest_time.f32"]) == 4 * 20 * 12
    out = tmp_path / "reach"
    out.mkdir()
    for name, data in result.files.items():
        (out / name).write_bytes(data)
    reach = er.Reach.load(out)
    f = reach.trace("balanced", *centre(10, 15))
    assert f["properties"]["reachable"] and f["geometry"]["coordinates"][0] == list(centre(*START))
    assert f["geometry"]["coordinates"][-1] == list(centre(10, 15))
    assert reach.trace("balanced", *centre(0, 29))["properties"]["reason"] == er.OUTSIDE


def test_downsample_halves_the_grid(tmp_path):
    folder = band_site(tmp_path / "s")
    m = er.run(folder, _config_with(folder, tmp_path, downsample=2)).manifest
    assert (m["grid"]["width"], m["grid"]["height"], m["grid"]["cell_m"]) == (15, 10, 10.0)
    assert m["grid"]["downsample"] == 2 and m["start"]["cell"] == [5, 1]


def test_downsample_keeps_the_worst_hazard_and_no_data():
    dem = np.zeros((4, 4))
    dem[0, 0] = np.nan
    hazard = np.zeros((4, 4), np.uint8)
    hazard[3, 3] = 2
    hazard[2, 0] = 1
    d, h, grid = er.downsample(dem, hazard, g.Grid(4, 4, 5.0), 2)
    assert grid == g.Grid(2, 2, 10.0)
    assert np.isnan(d[0, 0]) and h[1, 1] == 2 and h[1, 0] == 1 and h[0, 1] == 0


@pytest.mark.parametrize("crop,match", [
    ("[0.0, 0.0, 5000.0, 50.0]", "outside the site grid"),
    ("[0.0, 0.0, 4.0, 4.0]", "smaller than"),
])
def test_bad_crop_fails_clearly(tmp_path, crop, match):
    folder = band_site(tmp_path / "s")
    with pytest.raises(er.config_mod.ConfigError, match=match):
        er.run(folder, _config_with(folder, tmp_path, crop=crop))


def test_crop_in_the_config_is_validated():
    import copy
    from config import Config, ConfigError
    for bad in ["half", [0, 0, 10], [10.0, 0.0, 5.0, 5.0], [0, 0, float("nan"), 5]]:
        raw = copy.deepcopy(CFG.raw)
        raw["reach"]["crop_m"]["value"] = bad
        with pytest.raises(ConfigError, match="reach.crop_m"):
            Config.from_dict(raw)
    for bad in [0, 1.5, True]:
        raw = copy.deepcopy(CFG.raw)
        raw["reach"]["downsample"]["value"] = bad
        with pytest.raises(ConfigError, match="reach.downsample"):
            Config.from_dict(raw)
    raw = copy.deepcopy(CFG.raw)
    raw["reach"]["destination_stop"]["value"] = 1
    with pytest.raises(ConfigError, match="true or false"):
        Config.from_dict(raw)


# ---- start validation and the command line -----------------------------------
def test_start_outside_the_crop_fails(tmp_path):
    folder = band_site(tmp_path / "s")
    with pytest.raises(start_mod.StartError, match="outside the exported area"):
        er.run(folder, _config_with(folder, tmp_path, crop="[50.0, 0.0, 150.0, 100.0]"))


def test_blocked_start_exits_non_zero_and_writes_nothing(tmp_path, capsys):
    folder = tmp_path / "s"
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[START] = 2
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("start", "Start", "start", *centre(*START)), ("stop1", "A", "stop", *centre(3, 20)),
    ])
    out = tmp_path / "reach"
    assert er.main([*with_config(folder), "--in", str(folder), "--out", str(out)]) == 2
    assert "red hazard cell" in capsys.readouterr().err and not out.exists()


def test_yellow_start_is_a_warning_in_the_manifest(tmp_path):
    folder = tmp_path / "s"
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[START] = 1
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("start", "Start", "start", *centre(*START)), ("stop1", "A", "stop", *centre(3, 20)),
    ])
    m = er.run(folder, config_for(folder)).manifest
    assert len(m["warnings"]) == 1 and "yellow" in m["warnings"][0]


def test_default_out_is_the_reach_folder_inside_in(tmp_path, capsys):
    folder = band_site(tmp_path / "s")
    shared = {p.name: p.stat().st_mtime_ns for p in REAL_OUT.glob("**/*")} if REAL_OUT.exists() else {}
    assert er.main([*with_config(folder), "--in", str(folder)]) == 0
    written = sorted(p.name for p in (folder / er.REACH_DIR).iterdir())
    assert er.MANIFEST_FILE in written and er.REASON_FILE in written and len(written) == 14
    assert ({p.name: p.stat().st_mtime_ns for p in REAL_OUT.glob("**/*")} if REAL_OUT.exists() else {}) == shared
    out = capsys.readouterr().out
    assert "total" in out and "bytes" in out


def test_out_option_and_defaults():
    args = er.parse_args([])
    assert args.in_dir == REAL_OUT and args.out_dir is None and args.config is None
    args = er.parse_args(["--in", "a", "--out", "b", "--config", "c"])
    assert (args.in_dir, args.out_dir, args.config) == (Path("a"), Path("b"), Path("c"))
