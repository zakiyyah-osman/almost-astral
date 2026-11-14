"""export_landing.py: the cost surface, the edge rule, golden cases, the manifest, tiles and the window."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
from skimage.graph import MCP_Geometric

import config as config_mod
import cost
import export_landing as E
import grid as g
import landing as L
import replay
import search
import start as start_mod
from conftest import REPO_CONFIG, write_full_site

CFG = config_mod.load_config()
REAL_LANDING = Path(__file__).resolve().parents[2] / "data" / "out" / "landing"
SHAPE, CELL = (44, 64), 5.0
REL = 1e-9


def synthetic_arrays():
    """Gently tilted ground with smooth bumps (no equal-cost ties), a red wall with a gap, a yellow
    band, and a red ring that walls off a pocket in the south-east."""
    rng = np.random.default_rng(7)
    r, c = np.indices(SHAPE)
    dem = 0.02 * c * CELL + 0.15 * np.sin(r / 3.0) * np.cos(c / 4.0) + 0.01 * rng.standard_normal(SHAPE)
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[0:30, 32] = 2                          # wall, open in the south
    hazard[10:20, 12:16] = 1                      # yellow band
    hazard[33:43, 50] = hazard[33:43, 62] = 2     # ring round rows 34-42, cols 51-61
    hazard[33, 50:63] = hazard[43, 50:63] = 2
    return dem.astype(np.float32), hazard


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    folder = tmp_path_factory.mktemp("landing") / "site"
    dem, hazard = synthetic_arrays()
    write_full_site(folder, dem, hazard, CELL, [("a", "A", "stop", 50.0, 50.0)])
    return folder


def cfg_text(**values):
    """routing/config.toml with some [landing] values replaced (value lines only)."""
    text = REPO_CONFIG.read_text(encoding="utf-8")
    for key, value in values.items():
        head = f"[landing.{key}]\nvalue = "
        a = text.index(head) + len(head)
        b = text.index("\n", a)
        text = text[:a] + json.dumps(value) + text[b:]
    return text


def write_cfg(tmp_path, name="c.toml", **values):
    path = tmp_path / name
    path.write_text(cfg_text(**values), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def exported(site, tmp_path_factory):
    out = tmp_path_factory.mktemp("out") / "landing"
    result = E.run(site)
    from outputs import write_files
    write_files(out, result.files)
    return result, out, E.Landing.load(out)


def model_of(folder):
    s = g.load_site(folder)
    return s, cost.build(s.dem, s.hazard, s.slope, s.grid, cost.Params.from_config(CFG))


# ---- the surface is exactly cost.build ----------------------------------------
def test_exported_surface_is_identical_to_cost_build(site, exported):
    _, _, back = exported
    _, model = model_of(site)
    s = back.surface
    assert s.time_rate.dtype == np.float64 and s.risk_rate.dtype == np.float64
    assert np.array_equal(s.time_rate, model.time_rate)            # bit for bit, -1 where blocked
    assert np.array_equal(s.risk_rate, model.risk_rate)
    assert np.array_equal(s.mask, start_mod.block_codes(model))
    assert np.array_equal(s.mask != 0, model.blocked)
    for w in (0.0, 1.0, 5.0):
        assert np.array_equal(s.planning_rate(w), model.planning_rate(w))


def test_the_edge_rule_reproduces_mcp_cumulative_costs_bit_for_bit(exported):
    _, _, back = exported
    s = back.surface
    tr, rr, mask = s.time_rate.tolist(), s.risk_rate.tolist(), s.mask.tolist()
    start = (5, 5)
    for profile, w in s.weights.items():
        mcp = MCP_Geometric(s.planning_rate(w), fully_connected=True, sampling=(CELL, CELL))
        cum, _ = mcp.find_costs([start])
        gmap, _, _ = replay.search(tr, rr, mask, CELL, w, start)
        reach = np.argwhere(np.isfinite(cum))
        assert len(reach) == len(gmap)
        for r, c in reach:
            assert gmap[(int(r), int(c))] == cum[r, c], (profile, r, c)


def test_route_follows_search_py_on_the_original_cost(site, exported):
    _, _, back = exported
    _, model = model_of(site)
    a, z = (5, 5), (40, 20)
    for profile, w in back.surface.weights.items():
        f = back.route(back.surface.centre(*a), back.surface.centre(*z), profile)
        ref = search.Searcher(model, w, 8).path(a, z)
        assert [tuple(c) for c in f["properties"]["cells"]] == list(ref.cells)
        p = f["properties"]
        assert p["distance_m"] == pytest.approx(ref.distance_m, rel=REL)
        assert p["walk_min"] == pytest.approx(ref.physical_min, rel=REL)
        assert p["risk_min"] == pytest.approx(ref.risk_min, rel=REL)


def _check_replay(surface, case_like, budget_):
    tr, rr, mask = surface.time_rate.tolist(), surface.risk_rate.tolist(), surface.mask.tolist()
    a, z = tuple(case_like["landing_cell"]), tuple(case_like["dest_cell"])
    for profile, res in case_like["results"].items():
        got = replay.path_and_totals(tr, rr, mask, surface.cell_m, surface.weights[profile], a, z)
        if not res["reachable"]:
            assert got is None
            continue
        cells, d, t, k = got
        assert [list(c) for c in cells] == res["cells"], profile
        assert d == pytest.approx(res["distance_m"], rel=REL)
        assert t == pytest.approx(res["walk_min"], rel=REL)
        assert k == pytest.approx(res["risk_min"], rel=REL, abs=1e-12)
        assert res["needed_min"] == pytest.approx(t + budget_["ingress_min"] + budget_["stop_min"], rel=REL)
        assert res["over_budget"] == (t > budget_["walk_limit_min"])


def test_replay_reproduces_the_golden_cases_on_the_synthetic_site(exported):
    result, _, back = exported
    golden = json.loads(result.files[E.GOLDEN_FILE])
    for case in golden["cases"]:
        _check_replay(back.surface, case, case.get("budget", golden["budget"]))


def test_replay_reproduces_the_golden_cases_on_the_real_site():
    """The file Loick's tests read: data/out/landing/golden_cases.json, against data/out/landing's grids."""
    if not (REAL_LANDING / E.MANIFEST_FILE).exists():
        pytest.skip("run python routing/export_landing.py first")
    back = E.Landing.load(REAL_LANDING)
    golden = json.loads((REAL_LANDING / E.GOLDEN_FILE).read_text(encoding="utf-8"))
    assert len(golden["cases"]) == 10
    for case in golden["cases"]:
        _check_replay(back.surface, case, case.get("budget", golden["budget"]))


# ---- golden cases ------------------------------------------------------------
def test_golden_cases_cover_pairs_an_unreachable_and_an_over_budget_destination(exported):
    result, _, back = exported
    golden = json.loads(result.files[E.GOLDEN_FILE])
    cases = {c["id"]: c for c in golden["cases"]}
    assert len(cases) == 10 and set(golden["profiles"]) == {"fastest", "balanced", "safest"}
    for case in golden["cases"]:
        assert set(case["results"]) == {"fastest", "balanced", "safest"}
        assert back.map.codes[tuple(case["landing_cell"])] == L.SAFE
    un = cases["unreachable"]
    assert all(not r["reachable"] and r["reason"] == start_mod.WALLED_OFF for r in un["results"].values())
    over = cases["over_budget"]
    assert over["budget"]["eva_max_min"] < golden["budget"]["eva_max_min"]
    b = over["budget"]
    assert b["walk_limit_min"] == pytest.approx(b["usable_min"] - b["ingress_min"] - b["stop_min"])
    assert b["usable_min"] == pytest.approx(b["eva_max_min"] * (1 - b["reserve_pct"] / 100))
    assert all(r["over_budget"] for r in over["results"].values())
    ordinary = [c for k, c in cases.items() if k.startswith("pair")]
    assert len(ordinary) == 8 and not any(r["over_budget"] for c in ordinary for r in c["results"].values())
    # the same pair under the normal budget is not over budget
    same = next(c for c in ordinary if c["landing_cell"] == over["landing_cell"] and c["dest_cell"] == over["dest_cell"])
    assert [r["cells"] for r in same["results"].values()] == [r["cells"] for r in over["results"].values()]


def test_route_explains_no_path(exported):
    _, _, back = exported
    s = back.surface
    land = s.centre(5, 5)
    f = back.route(land, s.centre(10, 32), "safest")                # on the red wall
    assert f["geometry"] is None and f["properties"]["reason"] == start_mod.RED
    f = back.route(land, (-10.0, 5.0), "fastest")
    assert f["properties"]["reason"] == E.OUTSIDE
    f = back.route(land, land, "balanced")                          # destination = landing: a zero-length line
    assert f["properties"]["walk_min"] == 0.0 and len(f["geometry"]["coordinates"]) == 2
    with pytest.raises(ValueError, match="unknown profile"):
        back.route(land, land, "scenic")


# ---- manifest ----------------------------------------------------------------
def test_manifest_round_trips(site, exported):
    result, out, back = exported
    m = json.loads((out / E.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert m == result.manifest and back.manifest == m
    assert m["format_version"] == E.FORMAT_VERSION and m["byte_order"] == "little"
    g_ = m["grid"]
    assert (g_["width"], g_["height"], g_["cell_m"], g_["origin_m"], g_["row0"]) == (64, 44, 5.0, [0.0, 0.0], "north edge")
    assert {k: v["dtype"] for k, v in m["grids"].items()} == {
        "landing_safety": "uint8", "landing_warn": "uint8", "nearest_safe": "uint16",
        "nearest_safe_dist": "float32", "time_rate": "float64", "risk_rate": "float64", "mask": "uint8"}
    assert [c["code"] for c in m["safety_codes"]] == list(range(8))
    assert [c["code"] for c in m["mask_codes"]] == list(range(7))
    assert m["profiles"] == {"fastest": {"w": 0.0}, "balanced": {"w": 1.0}, "safest": {"w": 5.0}}
    assert m["budget"]["walk_limit_min"] == 212 and "one way only" in m["budget"]["rule"]
    assert {k: v["value"] for k, v in m["thresholds"].items()} == {
        "pad_radius_m": 25, "max_pad_slope_deg": 5, "max_roughness_m": 0.25, "max_height_range_m": 1.0,
        "hazard_clearance_m": 30, "marginal_pct": 20, "ti_warn_below": 150}
    assert all(v["type"] == "assumption" for v in m["thresholds"].values())
    assert "25 m" in m["roughness_note"] and "50 m" in m["roughness_note"] and "1 m data" in m["roughness_note"]
    assert "team assumption" in m["height_range_note"]
    assert m["fake"] is False
    assert m["inputs_sha256"]["dem.tif"] == hashlib.sha256((site / "dem.tif").read_bytes()).hexdigest()
    assert m["inputs_sha256"]["hazard.tif"] == hashlib.sha256((site / "hazard.tif").read_bytes()).hexdigest()
    for path, info in m["files"].items():
        data = (out / path).read_bytes()
        assert len(data) == info["bytes"] and hashlib.sha256(data).hexdigest() == info["sha256"]
    assert "edge_rule" in m["search"] and "L * (p_from + p_to) / 2" in m["search"]["edge_rule"]["step_cost"]
    # the read-back map is the computed one
    s, model = model_of(site)
    lm, _ = L.assess_site(s, model, CFG, site)
    assert np.array_equal(back.map.codes, lm.codes) and np.array_equal(back.map.warn, lm.warn)
    assert np.array_equal(back.map.near_rows, lm.near_rows) and np.array_equal(back.map.near_cols, lm.near_cols)
    assert np.allclose(back.map.near_dist_m, lm.near_dist_m, rtol=1e-6)


def test_landing_check_on_the_files_matches_the_computed_map(site, exported):
    _, _, back = exported
    s, model = model_of(site)
    lm, _ = L.assess_site(s, model, CFG, site)
    for x, y in ((12.0, 7.0), (160.0, 110.0), (60.0, 150.0), (290.0, 30.0)):
        a, b = back.landing_check(x, y), lm.landing_check(x, y)
        for k in ("status", "chosen_xy_m", "moved_m", "code"):
            assert a[k] == b[k]


def test_one_tile_size_and_total(exported):
    result, _, _ = exported
    m = result.manifest
    assert len(m["tiles"]) == 1 and m["tiles"][0]["shape"] == [44, 64] and m["tile_cells"] == 1024
    cells = 44 * 64
    grids = cells * (1 + 1 + 4 + 4 + 8 + 8 + 1)
    assert sum(v["bytes"] for k, v in m["files"].items() if k.startswith("tiles/")) == grids


def test_two_runs_give_identical_bytes(site, exported):
    result, _, _ = exported
    assert E.run(site).files == result.files


# ---- tiles -------------------------------------------------------------------
def test_tiles_stitch_back_to_the_single_tile_export(site, exported, tmp_path):
    _, _, one = exported
    cfg = write_cfg(tmp_path, tile_size_m=50)                       # 10 cells: 5 x 7 tiles
    res = E.run(site, cfg)
    from outputs import write_files
    out = tmp_path / "tiled"
    write_files(out, res.files)
    tiles = res.manifest["tiles"]
    assert len(tiles) == 5 * 7 and res.manifest["tile_cells"] == 10
    assert tiles[-1]["shape"] == [4, 4] and tiles[-1]["index"] == [4, 6]
    seen = np.zeros(SHAPE, int)
    for t in tiles:
        seen[t["row0"]:t["row0"] + t["shape"][0], t["col0"]:t["col0"] + t["shape"][1]] += 1
        x0 = t["col0"] * CELL
        y0 = (SHAPE[0] - t["row0"] - t["shape"][0]) * CELL
        assert t["origin_m"] == [x0, y0]
    assert (seen == 1).all()
    many = E.Landing.load(out)
    for a, b in ((many.map.codes, one.map.codes), (many.map.near_rows, one.map.near_rows),
                 (many.map.near_cols, one.map.near_cols), (many.surface.time_rate, one.surface.time_rate),
                 (many.surface.mask, one.surface.mask)):
        assert np.array_equal(a, b)
    # nearest_safe points across tile edges: some cell's nearest safe cell is in another tile
    rows = np.indices(SHAPE)[0]
    assert ((rows // 10) != (many.map.near_rows // 10)).any()
    assert json.loads(res.files[E.GOLDEN_FILE])["cases"] == json.loads(E.run(site).files[E.GOLDEN_FILE])["cases"]


@pytest.mark.parametrize("bad", [7, 12.5])
def test_a_tile_size_that_is_not_whole_cells_fails(site, tmp_path, bad):
    with pytest.raises(config_mod.ConfigError, match="tile_size_m"):
        E.run(site, write_cfg(tmp_path, tile_size_m=bad))


# ---- window ------------------------------------------------------------------
def test_a_window_exports_only_that_box_in_site_metres(site, exported, tmp_path):
    _, _, one = exported
    res = E.run(site, write_cfg(tmp_path, window_centre_m=[160.0, 110.0], window_size_m=[200.0, 150.0]))
    m = res.manifest
    assert (m["grid"]["width"], m["grid"]["height"]) == (40, 30)
    assert m["grid"]["origin_m"] == [60.0, 35.0]
    assert m["grid"]["window"]["site_rows"] == [7, 37] and m["grid"]["window"]["site_cols"] == [12, 52]
    from outputs import write_files
    out = tmp_path / "win"
    write_files(out, res.files)
    win = E.Landing.load(out)
    # codes are the whole-site codes cut out (the pad sees cells beyond the window edge)
    assert np.array_equal(win.map.codes, one.map.codes[7:37, 12:52])
    # nearest safe is computed on the window: always inside it
    assert win.map.near_rows.max() < 30 and win.map.near_cols.max() < 40
    x, y = 150.0, 100.0
    assert win.landing_check(x, y)["code"] == one.landing_check(x, y)["code"]
    f = win.route(win.surface.centre(2, 2), (5.0, 5.0), "fastest")   # outside the window
    assert f["properties"]["reason"] == E.OUTSIDE


@pytest.mark.parametrize("values,match", [
    ({"window_centre_m": [10.0, 10.0], "window_size_m": [100.0, 100.0]}, "outside the site grid"),
    ({"window_centre_m": [100.0, 100.0]}, "must be \"site\""),
])
def test_a_bad_window_fails_clearly(site, tmp_path, values, match):
    with pytest.raises(config_mod.ConfigError, match=match):
        E.run(site, write_cfg(tmp_path, **values))


# ---- command line ------------------------------------------------------------
def test_default_out_is_the_landing_folder_inside_in(site, tmp_path, capsys):
    import shutil
    copy = tmp_path / "copy"
    shutil.copytree(site, copy)
    assert E.main(["--in", str(copy)]) == 0
    assert (copy / "landing" / E.MANIFEST_FILE).exists() and (copy / "landing" / E.GOLDEN_FILE).exists()
    out = capsys.readouterr().out
    assert "1 tile(s)" in out and "total:" in out


def test_an_open_site_with_nothing_blocked_skips_the_unreachable_case(tmp_path):
    folder = tmp_path / "open"
    write_full_site(folder, np.zeros((40, 60), np.float32), np.zeros((40, 60), np.uint8), CELL,
                    [("a", "A", "stop", 50.0, 50.0)])
    res = E.run(folder)
    golden = json.loads(res.files[E.GOLDEN_FILE])
    ids = [c["id"] for c in golden["cases"]]
    assert "unreachable" not in ids and "over_budget" in ids
    assert len(golden["skipped"]) == 1 and "unreachable" in golden["skipped"][0]
    assert any("golden case skipped" in w for w in res.manifest["warnings"])


def test_no_safe_cell_fails_and_writes_nothing(tmp_path, capsys):
    folder = tmp_path / "s"
    write_full_site(folder, np.zeros((20, 20), np.float32), np.ones((20, 20), np.uint8), CELL,
                    [("a", "A", "stop", 50.0, 50.0)])
    assert E.main(["--in", str(folder)]) == 2
    assert "no safe landing cell" in capsys.readouterr().err
    assert not (folder / "landing").exists()
