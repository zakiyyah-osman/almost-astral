"""export_reach.py: the reach grids of every start, their manifest and the reference traceback."""
import copy
import hashlib
import json
import warnings
from pathlib import Path

import numpy as np
import pytest

import cost
import export_reach as er
import grid as g
import start as start_mod
import tour
from config import Config, ConfigError, load_config
from conftest import config_for, with_config, write_config, write_full_site
from search import Searcher

REPO = Path(__file__).resolve().parents[2]
REAL_OUT = REPO / "data" / "out"
CFG = load_config()
SHAPE, CELL = (20, 30), 5.0
GRID = g.Grid(SHAPE[1], SHAPE[0], CELL)
STARTS = {"L1": (10, 2), "L2": (12, 20), "L3": (2, 4)}          # start id -> cell on the band site
PROFILES = [name for name, _ in tour.PROFILES]
N = SHAPE[0] * SHAPE[1]
FILES_PER_START = 3 * 4 + 1                                      # 3 profiles x (time, dist, risk, dir) + reason
BYTES_PER_START = 3 * (3 * 4 * N + N) + N                        # f32 grids are 4 bytes a cell, u8 grids 1


def centre(r, c):
    return GRID.cell_centre(r, c)


def starts_xy(cells=None):
    return {sid: centre(*cell) for sid, cell in (STARTS if cells is None else cells).items()}


def band_site(folder, fake=False, cells=None, default=None):
    """Flat, a yellow band between the west and the east: the profiles choose different paths.
    Three starts, all on green ground."""
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[3:17, 10:15] = 1
    hazard[17:20, 10:15] = 2                     # red to the south of the band: near-red risk too
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("start", "Start", "start", *centre(*STARTS["L1"])), ("stop1", "A", "stop", *centre(3, 20)),
    ], fake=fake, starts=starts_xy(cells), default=default)
    return folder


def split_site(folder):
    """A red wall splits the site in a west half and an east half: L1 and L3 west, L2 east."""
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[:, 15] = 2
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("start", "Start", "start", *centre(10, 2)), ("stop1", "A", "stop", *centre(3, 5)),
    ], starts=starts_xy({"L1": (10, 2), "L2": (10, 25), "L3": (3, 3)}))
    return folder


def reasons_site(folder):
    """One cell for each reason code, seen from the one start L1."""
    hazard = np.zeros(SHAPE, np.uint8)
    dem = np.zeros(SHAPE, np.float32)
    hazard[8, 8] = hazard[9, 9] = 2              # red, and the gap between them is sealed
    hazard[1:6, 24] = hazard[1:6, 28] = 2        # a red ring: the pocket inside is walled off
    hazard[1, 24:29] = hazard[5, 24:29] = 2
    dem[15, 20] = 10.0                           # its neighbours are over 20 deg, itself in the buffer
    dem[17, 5] = np.nan                          # no data
    write_full_site(folder, dem, hazard, CELL, [
        ("start", "Start", "start", *centre(10, 2)), ("stop1", "A", "stop", *centre(10, 12)),
    ])
    return folder


def write_result(result, out):
    out = Path(out)
    for fname, data in result.files.items():
        (out / fname).parent.mkdir(parents=True, exist_ok=True)
        (out / fname).write_bytes(data)
    return out


def export(folder, tmp_path, name="reach", config=None):
    result = er.run(folder, config_for(folder) if config is None else config)
    return result, er.Reach.load(write_result(result, tmp_path / name))


def model_for(folder, cfg):
    site = g.load_site(folder)
    return cost.build(site.dem, site.hazard, site.slope, site.grid, cost.Params.from_config(cfg))


# ---- per-start traceback = the in-memory search ------------------------------
def test_traceback_matches_the_search_path_and_totals_for_every_start(tmp_path):
    folder = band_site(tmp_path / "s")
    cfg = load_config(config_for(folder))
    model = model_for(folder, cfg)
    _, reach = export(folder, tmp_path)
    dests = [(10, 25), (3, 20), (17, 26), (10, 12), (0, 29), (19, 0), *STARTS.values()]
    assert list(reach.starts) == ["L1", "L2", "L3"]
    for sid, scell in STARTS.items():
        for name, key in tour.PROFILES:
            tree = Searcher(model, cfg.value(key), 8).tree(scell)
            for dest in dests:
                f = reach.trace(sid, name, *centre(*dest))
                p = f["properties"]
                assert p["reachable"] and p["start"] == sid, (sid, name, dest)
                want = tree.path_to(dest)
                assert [tuple(c) for c in p["cells"]] == list(want.cells), (sid, name, dest)
                assert f["geometry"]["coordinates"][0] == list(centre(*scell))
                assert f["geometry"]["coordinates"][-1] == list(centre(*dest))
                assert p["walk_min"] == pytest.approx(want.physical_min, rel=1e-6, abs=1e-6)
                assert p["distance_m"] == pytest.approx(want.distance_m, rel=1e-6, abs=1e-6)
                assert p["risk_min"] == pytest.approx(want.risk_min, rel=1e-6, abs=1e-6)


def test_the_starts_give_different_paths_to_the_same_destination(tmp_path):
    _, reach = export(band_site(tmp_path / "s"), tmp_path)
    dest = centre(0, 29)
    paths = {sid: reach.trace(sid, "balanced", *dest)["properties"]["cells"] for sid in STARTS}
    assert len({json.dumps(p) for p in paths.values()}) == 3
    assert all(p[0] == list(STARTS[sid]) and p[-1] == [0, 29] for sid, p in paths.items())


def test_profiles_really_differ_on_the_band_site(tmp_path):
    _, reach = export(band_site(tmp_path / "s"), tmp_path)
    fast = reach.trace("L1", "fastest", *centre(10, 25))["properties"]
    safe = reach.trace("L1", "safest", *centre(10, 25))["properties"]
    assert fast["cells"] != safe["cells"]
    assert fast["walk_min"] < safe["walk_min"] and fast["risk_min"] > safe["risk_min"]


def test_time_rises_and_risk_falls_from_fastest_to_safest_for_every_start(tmp_path):
    _, reach = export(band_site(tmp_path / "s"), tmp_path)
    for sid in STARTS:
        for dest in [(10, 25), (3, 20), (17, 26), (10, 12), (0, 29), (19, 0)]:
            t = [reach.trace(sid, n, *centre(*dest))["properties"] for n in PROFILES]
            assert t[0]["walk_min"] <= t[1]["walk_min"] + 1e-4 <= t[2]["walk_min"] + 2e-4, (sid, dest)
            assert t[0]["risk_min"] + 2e-4 >= t[1]["risk_min"] + 1e-4 >= t[2]["risk_min"], (sid, dest)


def test_destination_at_the_start_is_a_zero_length_line(tmp_path):
    _, reach = export(band_site(tmp_path / "s"), tmp_path)
    for sid, cell in STARTS.items():
        f = reach.trace(sid, "balanced", *centre(*cell))
        assert f["geometry"]["coordinates"] == [list(centre(*cell))] * 2
        assert f["properties"]["walk_min"] == 0.0 and f["properties"]["distance_m"] == 0.0
        assert f["properties"]["cells"] == [list(cell)]


def test_trace_rejects_an_unknown_start_or_profile(tmp_path):
    _, reach = export(band_site(tmp_path / "s"), tmp_path)
    with pytest.raises(er.ReachError, match=r"unknown start 'L9'; the starts are L1, L2, L3"):
        reach.trace("L9", "fastest", 10.0, 10.0)
    with pytest.raises(er.ReachError, match=r"unknown profile 'quick'; the profiles are fastest, balanced, safest"):
        reach.trace("L1", "quick", 10.0, 10.0)
    with pytest.raises(er.ReachError, match="unknown start"):
        er.trace(reach.folder, "L9", "fastest", 10.0, 10.0)


def test_module_trace_loads_the_folder_and_takes_a_start_id(tmp_path):
    _, reach = export(band_site(tmp_path / "s"), tmp_path)
    f = er.trace(reach.folder, "L2", "safest", *centre(0, 29))
    assert f["properties"]["start"] == "L2" and f["geometry"]["coordinates"][0] == list(centre(*STARTS["L2"]))


@pytest.mark.skipif(not (REAL_OUT / "dem.tif").exists(), reason="data/out has no inputs")
def test_traceback_matches_the_search_on_the_real_site_for_every_start(tmp_path):
    result = er.run(REAL_OUT)
    reach = er.Reach.load(write_result(result, tmp_path / "reach"))
    model = model_for(REAL_OUT, CFG)
    dests = [(500, 1500), (1400, 1760), (1600, 500), (100, 100), (1900, 1900)]
    assert [(s["id"], tuple(s["xy_m"])) for s in result.manifest["starts"]] == list(CFG.starts().items())
    for s in result.manifest["starts"]:
        cell = tuple(s["cell"])
        assert cell == model.grid.xy_to_cell(*s["xy_m"])
        for name, key in tour.PROFILES:
            tree = Searcher(model, CFG.value(key), 8).tree(cell)
            for xy in dests:
                p = reach.trace(s["id"], name, *xy)["properties"]
                dcell = model.grid.xy_to_cell(*xy)
                if not p["reachable"]:
                    assert not tree.reachable(dcell)
                    continue
                want = tree.path_to(dcell)
                assert [tuple(c) for c in p["cells"]] == list(want.cells)
                assert p["walk_min"] == pytest.approx(want.physical_min, rel=1e-6)
                assert p["distance_m"] == pytest.approx(want.distance_m, rel=1e-6)
                assert p["risk_min"] == pytest.approx(want.risk_min, rel=1e-5, abs=1e-5)


@pytest.mark.skipif(not (REAL_OUT / "dem.tif").exists(), reason="data/out has no inputs")
def test_the_starts_in_the_config_were_computed_on_the_current_data():
    """Warns, and does not fail, when dem.tif or hazard.tif in data/out changed after L1 to L3 were computed.

    A teammate's data update must not break the suite. The warning shows in the pytest summary.
    To clear it: run web/src/lib/landing.js (recommendLanding) on the new data, update [starts.*] in
    routing/config.toml, and put the sha256 of dem.tif and hazard.tif in start.dem_sha256 and
    start.hazard_sha256.
    """
    stale = start_mod.staleness_warnings(CFG, REAL_OUT)
    if stale:
        warnings.warn(
            "the landing spots L1-L3 in routing/config.toml were computed on other data than data/out now "
            "holds; recompute them with web/src/lib/landing.js. " + " | ".join(stale),
            UserWarning, stacklevel=1,
        )


# ---- reason codes, per start --------------------------------------------------
def test_unreachable_reason_codes(tmp_path):
    _, reach = export(reasons_site(tmp_path / "s"), tmp_path)
    r = reach.reason["L1"]
    assert r[10, 10] == start_mod.REACHABLE
    assert r[8, 8] == start_mod.RED and r[9, 9] == start_mod.RED
    assert r[8, 9] == start_mod.SEALED and r[9, 8] == start_mod.SEALED
    assert r[14, 20] == start_mod.SLOPE and r[15, 19] == start_mod.SLOPE
    assert r[15, 20] == start_mod.BUFFER
    assert r[17, 5] == start_mod.NODATA
    assert r[3, 26] == start_mod.WALLED_OFF
    # reason 0 exactly where there is a path, and the f32 grids are NaN everywhere else
    for name in PROFILES:
        gr = reach.grids["L1"][name]
        assert np.array_equal(np.isfinite(gr["time"]), r == start_mod.REACHABLE)
        assert np.isnan(gr["dist"][r != 0]).all() and np.isnan(gr["risk"][r != 0]).all()
        assert (gr["dir"][r != 0] == er.NO_STEP).all()


def test_reason_6_walled_off_can_differ_between_starts(tmp_path):
    _, reach = export(split_site(tmp_path / "s"), tmp_path)
    r1, r2, r3 = (reach.reason[s] for s in ("L1", "L2", "L3"))
    west, east, wall = (10, 5), (10, 25), (10, 15)
    assert r1[west] == start_mod.REACHABLE and r1[east] == start_mod.WALLED_OFF
    assert r2[east] == start_mod.REACHABLE and r2[west] == start_mod.WALLED_OFF
    assert r1[wall] == r2[wall] == start_mod.RED
    assert (r1 != r2).any() and np.array_equal(r1, r3)                 # same half: same reasons
    # only code 6 differs: the hard-mask reasons are the same for every start
    assert np.array_equal(np.where(r1 == 6, 0, r1), np.where(r2 == 6, 0, r2))
    for sid in ("L1", "L2", "L3"):                                     # each start's NaN grids follow its own reason
        t = reach.grids[sid]["fastest"]["time"]
        assert np.array_equal(np.isfinite(t), reach.reason[sid] == start_mod.REACHABLE)
    # and the trace explains it from the start that is cut off, and finds the path from the other
    cut = reach.trace("L1", "safest", *centre(*east))
    assert cut["geometry"] is None and cut["properties"]["reason"] == start_mod.WALLED_OFF
    assert "walled off" in cut["properties"]["reason_text"] and cut["properties"]["start"] == "L1"
    ok = reach.trace("L2", "safest", *centre(*east))
    assert ok["properties"]["reachable"] and ok["geometry"]["coordinates"][0] == list(centre(10, 25))
    counts = {s["id"]: s["profiles"]["fastest"]["reachable_cells"] for s in reach.manifest["starts"]}
    assert counts["L1"] == counts["L3"] == int((r1 == 0).sum())
    assert counts["L2"] == int((r2 == 0).sum()) != counts["L1"]          # the east half is smaller than the west


def test_trace_explains_an_unreachable_destination(tmp_path):
    _, reach = export(reasons_site(tmp_path / "s"), tmp_path)
    walled = reach.trace("L1", "safest", *centre(3, 26))
    assert walled["geometry"] is None
    assert walled["properties"]["reason"] == start_mod.WALLED_OFF and "walled off" in walled["properties"]["reason_text"]
    red = reach.trace("L1", "safest", *centre(8, 8))["properties"]
    assert red["reason_name"] == "red" and red["reason_text"] == "red hazard cell"
    outside = reach.trace("L1", "safest", 5000.0, 5.0)["properties"]
    assert outside["reason"] == er.OUTSIDE and not outside["reachable"]


# ---- manifest ----------------------------------------------------------------
def test_manifest_lists_all_starts_with_their_files(tmp_path):
    folder = band_site(tmp_path / "s")
    result, reach = export(folder, tmp_path)
    m = reach.manifest
    assert m["default_start"] == "L1" and [s["id"] for s in m["starts"]] == ["L1", "L2", "L3"]
    assert [s["default"] for s in m["starts"]] == [True, False, False]
    for s in m["starts"]:
        assert s["xy_m"] == list(centre(*STARTS[s["id"]])) and s["cell"] == list(STARTS[s["id"]])
        assert s["temporary"] is True and s["folder"] == s["id"] and s["warnings"] == []
        assert s["reason_file"] == f"{s['id']}/reason.u8"
        assert list(s["profiles"]) == PROFILES
        for name, p in s["profiles"].items():
            assert p["files"] == {k: f"{s['id']}/{name}_{k}.{'u8' if k == 'dir' else 'f32'}"
                                  for k in ("time", "dist", "risk", "dir")}
            assert p["reachable_cells"] == int(np.isfinite(reach.grids[s["id"]][name]["time"]).sum())
            for path in p["files"].values():
                assert (reach.folder / path).is_file() and path in m["files"]
    assert "start" not in m and "reason_file" not in m                  # the one-start layout is gone
    assert m["format_version"] == er.FORMAT_VERSION == 2
    assert len(m["files"]) == 3 * FILES_PER_START and len(result.files) == 3 * FILES_PER_START + 1


def test_default_flag_follows_the_config(tmp_path):
    folder = band_site(tmp_path / "s", default="L3")
    result, reach = export(folder, tmp_path)
    assert result.manifest["default_start"] == "L3"
    assert [s["id"] for s in result.manifest["starts"] if s["default"]] == ["L3"]
    assert reach.default_start == "L3"


def test_manifest_round_trips(tmp_path):
    folder = band_site(tmp_path / "s")
    result, reach = export(folder, tmp_path)
    m = reach.manifest
    assert m == json.loads(result.files[er.MANIFEST_FILE])
    assert m["byte_order"] == "little"
    assert m["grid"]["width"] == 30 and m["grid"]["height"] == 20 and m["grid"]["cell_m"] == 5.0
    assert m["grid"]["origin_m"] == [0.0, 0.0] and m["grid"]["crop_m"] == "full" and m["grid"]["downsample"] == 1
    assert {n: p["w"] for n, p in m["profiles"].items()} == {"fastest": 0.0, "balanced": 1.0, "safest": 5.0}
    assert m["fake"] is False
    assert [d["code"] for d in m["direction_codes"]] == list(range(9))
    assert [r["code"] for r in m["reason_codes"]] == list(range(7))
    for name, info in m["files"].items():
        data = (reach.folder / name).read_bytes()
        assert len(data) == info["bytes"] and hashlib.sha256(data).hexdigest() == info["sha256"]
        assert info["bytes"] == (4 * N if name.endswith(".f32") else N)
    assert set(m["files"]) == set(result.files) - {er.MANIFEST_FILE}
    for sid in STARTS:
        for name in PROFILES:
            gr = reach.grids[sid][name]
            assert gr["time"].dtype == np.dtype("<f4") and gr["dir"].dtype == np.uint8
    assert m["inputs_sha256"]["dem.tif"] == hashlib.sha256((folder / "dem.tif").read_bytes()).hexdigest()


def test_reading_an_old_layout_manifest_fails_clearly(tmp_path):
    out = tmp_path / "reach"
    out.mkdir()
    (out / "reach.json").write_text(json.dumps({"format_version": 1}), encoding="utf-8")
    with pytest.raises(er.ReachError, match="format_version 1, expected 2"):
        er.Reach.load(out)


def test_total_size_is_forty_grids_of_the_site_per_start_plus_the_manifest(tmp_path):
    result, _ = export(band_site(tmp_path / "s"), tmp_path)
    assert result.total_bytes == 3 * BYTES_PER_START + len(result.files[er.MANIFEST_FILE])


def test_fake_flag_is_copied_from_layers_json(tmp_path):
    result = er.run(band_site(tmp_path / "s", fake=True), config_for(tmp_path / "s"))
    assert result.manifest["fake"] is True


def test_config_hash_is_stable_and_follows_the_config(tmp_path):
    folder = band_site(tmp_path / "s")
    a = er.run(folder, config_for(folder)).manifest["config_sha256"]
    b = er.run(folder, config_for(folder)).manifest["config_sha256"]
    other = tmp_path / "other.toml"
    write_config(other, starts_xy(), config_for(folder).read_text(encoding="utf-8").replace("value = 360\n", "value = 300\n", 1))
    c = er.run(folder, other).manifest["config_sha256"]
    assert a == b != c


def test_two_runs_give_identical_bytes(tmp_path):
    folder = band_site(tmp_path / "s")
    assert er.run(folder, config_for(folder)).files == er.run(folder, config_for(folder)).files


# ---- an invalid start fails, naming it -----------------------------------------
@pytest.mark.parametrize("bad_id", ["L1", "L2", "L3"])
def test_an_invalid_start_fails_with_its_name_and_writes_nothing(tmp_path, capsys, bad_id):
    folder = tmp_path / "s"
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[STARTS[bad_id]] = 2
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("start", "Start", "start", *centre(*STARTS["L1"])), ("stop1", "A", "stop", *centre(3, 20)),
    ], starts=starts_xy())
    with pytest.raises(start_mod.StartError) as e:
        er.run(folder, config_for(folder))
    assert e.value.start_id == bad_id and f"start {bad_id!r}" in str(e.value) and "red hazard cell" in str(e.value)
    out = tmp_path / "reach"
    assert er.main([*with_config(folder), "--in", str(folder), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert f"start {bad_id!r}" in err and f"starts.{bad_id}" in err and not out.exists()


def test_a_start_outside_the_exported_area_is_named(tmp_path):
    folder = band_site(tmp_path / "s")
    text = config_for(folder).read_text(encoding="utf-8")
    cfg = tmp_path / "crop.toml"
    cfg.write_text(text.replace('[reach.crop_m]\nvalue = "full"\n', "[reach.crop_m]\nvalue = [0.0, 20.0, 110.0, 80.0]\n"),
                   encoding="utf-8")                       # L3 is at y = 87.5 m: above the box
    with pytest.raises(start_mod.StartError, match=r"start 'L3' \(22\.5, 87\.5\) m is outside the exported area"):
        er.run(folder, cfg)


def test_a_start_outside_the_site_is_named(tmp_path):
    folder = band_site(tmp_path / "s")
    cfg = write_config(tmp_path / "far.toml", {"L1": centre(10, 2), "L2": (5000.0, 10.0)},
                       text=config_for(folder).read_text(encoding="utf-8"))
    with pytest.raises(start_mod.StartError, match=r"start 'L2' \(5000, 10\) m is outside"):
        er.run(folder, cfg)


def test_yellow_start_is_a_warning_in_the_manifest_and_names_the_start(tmp_path):
    folder = tmp_path / "s"
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[STARTS["L2"]] = 1
    write_full_site(folder, np.zeros(SHAPE, np.float32), hazard, CELL, [
        ("start", "Start", "start", *centre(*STARTS["L1"])), ("stop1", "A", "stop", *centre(3, 20)),
    ], starts=starts_xy())
    m = er.run(folder, config_for(folder)).manifest
    assert len(m["warnings"]) == 1 and "start 'L2'" in m["warnings"][0] and "yellow" in m["warnings"][0]
    assert [s["warnings"] for s in m["starts"]] == [[], m["warnings"], []]


# ---- the data the starts were computed on ---------------------------------------
def test_stale_data_hashes_give_one_manifest_warning_each_and_print_once(tmp_path, capsys):
    folder = band_site(tmp_path / "s")
    stale = write_config(tmp_path / "stale.toml", starts_xy(), config_for(folder).read_text(encoding="utf-8"),
                         dem_sha="d" * 64, hazard_sha="e" * 64)
    m = er.run(folder, stale).manifest
    assert len(m["warnings"]) == 2
    assert "dem.tif is not the file the starts were computed on" in m["warnings"][0]
    assert "hazard.tif is not the file the starts were computed on" in m["warnings"][1]
    assert er.main(["--config", str(stale), "--in", str(folder), "--out", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert out.count("dem.tif is not the file the starts were computed on") == 1
    clean = er.run(folder, config_for(folder)).manifest
    assert clean["warnings"] == []


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
    _, reach = export(folder, tmp_path, config=tight)
    limit = reach.manifest["budget"]["walk_limit_min"]
    assert limit == pytest.approx(2.0)
    near = reach.trace("L1", "fastest", *centre(10, 4))["properties"]
    far = reach.trace("L1", "fastest", *centre(0, 29))["properties"]
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


def test_crop_exports_only_the_box_and_places_every_start_in_it(tmp_path):
    folder = band_site(tmp_path / "s")
    cfg = _config_with(folder, tmp_path, crop="[0.0, 0.0, 110.0, 90.0]")
    result, reach = export(folder, tmp_path, config=cfg)
    m = result.manifest
    assert (m["grid"]["width"], m["grid"]["height"]) == (22, 18) and m["grid"]["origin_m"] == [0.0, 0.0]
    assert [s["cell"] for s in m["starts"]] == [[8, 2], [10, 20], [0, 4]]    # two rows cut off in the north
    assert len(result.files["L2/fastest_time.f32"]) == 4 * 22 * 18
    for sid, cell in STARTS.items():
        f = reach.trace(sid, "balanced", *centre(10, 15))
        assert f["properties"]["reachable"] and f["geometry"]["coordinates"][0] == list(centre(*cell))
        assert f["geometry"]["coordinates"][-1] == list(centre(10, 15))
    assert reach.trace("L1", "balanced", *centre(0, 29))["properties"]["reason"] == er.OUTSIDE


def test_downsample_halves_the_grid_and_every_start_moves(tmp_path):
    folder = band_site(tmp_path / "s")
    m = er.run(folder, _config_with(folder, tmp_path, downsample=2)).manifest
    assert (m["grid"]["width"], m["grid"]["height"], m["grid"]["cell_m"]) == (15, 10, 10.0)
    assert m["grid"]["downsample"] == 2 and [s["cell"] for s in m["starts"]] == [[5, 1], [6, 10], [1, 2]]


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


# ---- the old layout and removed starts are cleaned up ------------------------------
def _old_files(folder):
    """The 13 grid files of the one-start layout."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in er.GRID_FILE_NAMES:
        (folder / name).write_bytes(b"old")
    return [folder / n for n in er.GRID_FILE_NAMES]


def test_the_export_deletes_the_old_layout_and_removed_starts_and_lists_them(tmp_path, capsys):
    site = band_site(tmp_path / "s")
    out = tmp_path / "reach"
    top = _old_files(out)                                         # the old one-start layout: 13 files
    (out / "reach.json").write_text("{}", encoding="utf-8")       # the old manifest is overwritten, not deleted
    gone = _old_files(out / "L9")                                 # a start that is no longer in the config
    kept_other = _old_files(out / "L8")
    (out / "L8" / "notes.txt").write_text("mine", encoding="utf-8")   # a folder with another file in it
    (out / "unrelated.txt").write_text("mine", encoding="utf-8")
    (out / "notes").mkdir()
    (out / "notes" / "a.txt").write_text("mine", encoding="utf-8")   # no reason.u8: not a start folder

    assert er.main([*with_config(site), "--in", str(site), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Deleted" in text
    assert len(top) == 13 and not any(p.exists() for p in top)
    assert not any(p.exists() for p in gone) and not (out / "L9").exists()
    assert not any(p.exists() for p in kept_other) and (out / "L8").is_dir()      # the folder stays: it holds notes.txt
    assert (out / "L8" / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert (out / "unrelated.txt").exists() and (out / "notes" / "a.txt").exists()
    for rel in ("balanced_time.f32", "reason.u8", "L9/reason.u8", "L9/"):
        assert rel in text.replace("\\", "/")
    for sid in STARTS:                                            # the new layout is complete
        assert (out / sid / "reason.u8").stat().st_size == N
    manifest = json.loads((out / "reach.json").read_text(encoding="utf-8"))
    assert manifest["format_version"] == 2


def test_a_second_run_deletes_nothing(tmp_path, capsys):
    site = band_site(tmp_path / "s")
    out = tmp_path / "reach"
    args = [*with_config(site), "--in", str(site), "--out", str(out)]
    assert er.main(args) == 0 and er.main(args) == 0
    assert "Deleted" not in capsys.readouterr().out.split("Wrote", 2)[2]


def test_stale_paths_lists_only_known_names(tmp_path):
    out = tmp_path / "reach"
    top = _old_files(out)
    (out / "extra.f32").write_bytes(b"x")
    _old_files(out / "L7")
    stale = er.stale_paths(out, {"L1"})
    assert set(stale) == {*top, *(out / "L7" / n for n in er.GRID_FILE_NAMES), out / "L7"}
    assert er.stale_paths(out, {"L1", "L7"}) == top
    assert er.stale_paths(tmp_path / "missing", {"L1"}) == []


# ---- the command line --------------------------------------------------------
def test_default_out_is_the_reach_folder_inside_in(tmp_path, capsys):
    folder = band_site(tmp_path / "s")
    shared = {p.name: p.stat().st_mtime_ns for p in REAL_OUT.glob("**/*")} if REAL_OUT.exists() else {}
    assert er.main([*with_config(folder), "--in", str(folder)]) == 0
    reach = folder / er.REACH_DIR
    assert sorted(p.name for p in reach.iterdir()) == ["L1", "L2", "L3", er.MANIFEST_FILE]
    assert all(len(list((reach / sid).iterdir())) == FILES_PER_START for sid in STARTS)
    assert ({p.name: p.stat().st_mtime_ns for p in REAL_OUT.glob("**/*")} if REAL_OUT.exists() else {}) == shared
    out = capsys.readouterr().out
    assert "total" in out and "MB" in out and "start L1 (default)" in out and "start L2:" in out


def test_out_option_and_defaults():
    args = er.parse_args([])
    assert args.in_dir == REAL_OUT and args.out_dir is None and args.config is None
    args = er.parse_args(["--in", "a", "--out", "b", "--config", "c"])
    assert (args.in_dir, args.out_dir, args.config) == (Path("a"), Path("b"), Path("c"))
