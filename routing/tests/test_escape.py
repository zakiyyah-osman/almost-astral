"""Escape rates for walking out of a red zone, and golden_escape_cases.json (DESIGN section 17)."""
import hashlib
import heapq
import json
import math
from pathlib import Path

import numpy as np
import pytest

import config as config_mod
import cost
import escape as X
import export_landing as E
import grid as g
import replay
import walking
from conftest import REPO_CONFIG

CFG = config_mod.load_config()
ESC = X.params(CFG)
P = cost.Params.from_config(CFG)
REAL_OUT = Path(__file__).resolve().parents[2] / "data" / "out"
REAL_LANDING = REAL_OUT / "landing"
REL = 1e-9
OLD_FILES = ("golden_cases.json", "landing_zones.png", *(f"tiles/0_0/{f}" for k, (f, *_) in E.GRIDS.items()
                                                       if k not in E.ESCAPE_GRIDS))


def expected_time_rate(slope_deg):
    """The walking model written out: 1 / v(tan(slope)) in min/m."""
    return 1.0 / walking.speed_m_per_min(np.tan(np.radians(slope_deg)), P.v_flat_kmh, P.tobler_k, P.tobler_offset)


@pytest.fixture(scope="module")
def real():
    if not (REAL_LANDING / E.MANIFEST_FILE).is_file() or not (REAL_LANDING / E.GOLDEN_ESCAPE_FILE).is_file():
        pytest.skip("data/out/landing has no escape export yet (run python routing/export_landing.py)")
    back = E.Landing.load(REAL_LANDING)
    site = g.load_site(REAL_OUT)
    return back, site


# ---- config ------------------------------------------------------------------
def test_escape_config_is_three_team_assumptions():
    for key in ("escape.zone_codes", "escape.risk_rate", "escape.max_slope_deg"):
        assert CFG.assumptions()[key]["type"] == "assumption"
    assert ESC == {"zone_codes": [2, 3, 4, 5], "risk_rate": 1.0, "max_slope_deg": 35.0}


@pytest.mark.parametrize("bad", [[1, 2], [], [2, 2], [6], [2.0], [True]])
def test_zone_codes_never_include_no_data_or_unknown_codes(bad):
    raw = config_mod.load_config().raw
    raw["escape"]["zone_codes"]["value"] = bad
    with pytest.raises(config_mod.ConfigError, match="escape.zone_codes"):
        config_mod.Config(raw)


@pytest.mark.parametrize("key,bad", [("risk_rate", -0.1), ("max_slope_deg", 0), ("max_slope_deg", 90)])
def test_escape_numbers_are_in_range(key, bad):
    raw = config_mod.load_config().raw
    raw["escape"][key]["value"] = bad
    with pytest.raises(config_mod.ConfigError, match=f"escape.{key}"):
        config_mod.Config(raw)


# ---- the rates on a hand-made grid ----------------------------------------------
def small():
    slope = np.array([[5.0, 25.0, 34.9, 35.0],
                      [35.1, 50.0, np.nan, 10.0],
                      [12.0, 22.0, 30.0, 40.0]])
    mask = np.array([[0, 2, 3, 4],
                     [2, 5, 1, 0],
                     [2, 1, 4, 3]], dtype=np.uint8)
    return slope, mask


def test_zone_cells_get_finite_positive_rates_and_everything_else_minus_one_and_zero():
    slope, mask = small()
    t, r = X.rates(slope, mask, P, ESC)
    want = np.array([[0, 1, 1, 1], [0, 0, 0, 0], [1, 0, 1, 0]], bool)      # zone code, slope <= 35
    assert t.dtype == np.float64 and r.dtype == np.float64
    assert np.all(t[want] > 0) and np.all(np.isfinite(t[want]))
    assert np.all(t[~want] == -1.0)
    assert np.all(r[want] == ESC["risk_rate"]) and np.all(r[~want] == 0.0)


def test_cells_above_max_slope_are_minus_one():
    slope, mask = small()
    t, _ = X.rates(slope, mask, P, ESC)
    assert t[0, 3] > 0                                   # exactly 35 deg: allowed (<=)
    assert t[1, 0] == -1 and t[1, 1] == -1 and t[2, 3] == -1
    tighter = {**ESC, "max_slope_deg": 30.0}
    t2, r2 = X.rates(slope, mask, P, tighter)
    assert t2[0, 2] == -1 and r2[0, 2] == 0 and t2[2, 2] > 0


def test_time_rate_is_the_walking_model_at_that_slope_unclipped():
    slope, mask = small()
    t, _ = X.rates(slope, mask, P, ESC)
    ok = t > 0
    assert np.array_equal(t[ok], expected_time_rate(slope[ok]))
    # The same function as the normal rate: where both exist, they agree bit for bit.
    normal = cost.time_rate(slope, np.zeros(slope.shape, bool) | np.isnan(slope), P)
    assert np.array_equal(t[ok], normal[ok])


def test_zone_codes_from_the_config_are_honoured():
    slope, mask = small()
    t, _ = X.rates(slope, mask, P, {**ESC, "zone_codes": [2]})
    assert np.all((t > 0) == ((mask == 2) & (slope <= 35)))


# ---- the export on the synthetic site ----------------------------------------------
@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    from test_export_landing import synthetic_arrays
    from conftest import write_full_site
    from outputs import write_files
    folder = tmp_path_factory.mktemp("esc") / "site"
    dem, hazard = synthetic_arrays()
    write_full_site(folder, dem, hazard, 5.0, [("a", "A", "stop", 50.0, 50.0)])
    result = E.run(folder)
    out = folder.parent / "landing"
    write_files(out, result.files)
    return folder, result, out, E.Landing.load(out)


def test_manifest_round_trips_with_the_escape_block(exported):
    _, result, out, back = exported
    m = json.loads((out / E.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert m == result.manifest == back.manifest
    e = m["escape"]
    assert (e["zone_codes"], e["risk_rate"], e["max_slope_deg"]) == ([2, 3, 4, 5], 1.0, 35.0)
    assert e["rule"] == X.RULE and "emergency estimate" in e["note"] and "assumption" in e["note"]
    assert "beyond" in e["note"] and e["golden_cases"] == E.GOLDEN_ESCAPE_FILE
    for key in E.ESCAPE_GRIDS:
        gr = m["grids"][key]
        assert gr["dtype"] == "float64" and gr["values_per_cell"] == 1 and gr["unit"]
        assert m["tiles"][0]["files"][key] in m["files"]
    assert "-1" in m["grids"]["escape_time_rate"]["minus_one"]
    assert E.GOLDEN_ESCAPE_FILE in m["files"]
    assert back.escape is not None
    assert np.array_equal(back.escape.zone_time, result_arrays(exported)[0])


def result_arrays(exported):
    folder, *_ = exported
    s = g.load_site(folder)
    model = cost.build(s.dem, s.hazard, s.slope, s.grid, P)
    from start import block_codes
    return X.rates(model.slope_deg, block_codes(model), P, ESC)


def test_an_older_folder_without_escape_grids_still_loads(exported, tmp_path):
    import shutil
    _, _, out, _ = exported
    old = tmp_path / "old"
    shutil.copytree(out, old)
    m = json.loads((old / E.MANIFEST_FILE).read_text(encoding="utf-8"))
    for key in E.ESCAPE_GRIDS:
        del m["grids"][key]
        for t in m["tiles"]:
            (old / t["files"].pop(key)).unlink()
    del m["escape"]
    (old / E.MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    back = E.Landing.load(old)
    assert back.escape is None and back.surface.time_rate.shape == (44, 64)


def test_escape_settings_never_change_the_existing_files(exported, tmp_path):
    """Other escape values change only the escape grids, the escape golden file and the manifest."""
    folder, result, _, _ = exported
    text = REPO_CONFIG.read_text(encoding="utf-8")
    for key, new in (("zone_codes", "[2]"), ("risk_rate", "3.0"), ("max_slope_deg", "21")):
        head = f"[escape.{key}]\nvalue = "
        a = text.index(head) + len(head)
        text = text[:a] + new + text[text.index("\n", a):]
    cfg = tmp_path / "c.toml"
    cfg.write_text(text, encoding="utf-8")
    other = E.run(folder, cfg).files
    escape_files = {f for f in result.files if any(f.endswith(E.GRIDS[k][0]) for k in E.ESCAPE_GRIDS)}
    new = escape_files | {E.GOLDEN_ESCAPE_FILE, E.MANIFEST_FILE}
    assert set(other) == set(result.files)
    for name in set(result.files) - new:
        assert other[name] == result.files[name], name


# ---- the real export ---------------------------------------------------------------
def test_real_escape_rates_follow_the_rule(real):
    back, site = real
    s, ref = back.surface, back.escape
    slope = site.slope
    zone = np.isin(s.mask, ESC["zone_codes"])
    ok = zone & (slope <= ESC["max_slope_deg"])
    assert np.all(ref.zone_time[ok] > 0) and np.all(ref.zone_time[~ok] == -1)
    assert np.all(ref.zone_risk[ok] == ESC["risk_rate"]) and np.all(ref.zone_risk[~ok] == 0)
    assert np.array_equal(ref.zone_time[ok], expected_time_rate(slope[ok]))
    assert np.all(ref.zone_time[zone & (slope > ESC["max_slope_deg"])] == -1)
    c = back.manifest["escape"]["cell_counts"]
    assert c["finite"] == int(ok.sum()) and c["excluded_by_max_slope"] == int((zone & ~ok).sum())


def test_real_existing_files_match_the_manifest_and_a_fresh_run(real, tmp_path):
    """The files on disk are what the manifest lists, and a run with other escape settings writes the
    same bytes for every existing grid, golden_cases.json and landing_zones.png."""
    back, _ = real
    files = back.manifest["files"]
    for name in OLD_FILES:
        assert hashlib.sha256((REAL_LANDING / name).read_bytes()).hexdigest() == files[name]["sha256"], name
    text = REPO_CONFIG.read_text(encoding="utf-8").replace(
        "[escape.max_slope_deg]\nvalue = 35", "[escape.max_slope_deg]\nvalue = 25")
    cfg = tmp_path / "c.toml"
    cfg.write_text(text, encoding="utf-8")
    other = E.run(REAL_OUT, cfg).files
    for name in OLD_FILES:
        assert other[name] == (REAL_LANDING / name).read_bytes(), name


# ---- golden escape cases: an independent replay of the rule -----------------------
def replay_escape(tr, rr, mask, et, er, codes, cell_m, start):
    """Phase 1 from the rule text only: plain Dijkstra, 8 neighbours, lists of lists."""
    H, W = len(mask), len(mask[0])
    inz = [[mask[r][c] != 0 and mask[r][c] in codes for c in range(W)] for r in range(H)]
    zone, todo = {start}, [start]
    while todo:
        r, c = todo.pop()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                q = (r + dr, c + dc)
                if 0 <= q[0] < H and 0 <= q[1] < W and q not in zone and inz[q[0]][q[1]]:
                    zone.add(q)
                    todo.append(q)
    if et[start[0]][start[1]] < 0:
        return None
    rate = lambda q: et[q[0]][q[1]] if q in zone else tr[q[0]][q[1]]      # noqa: E731  (w = 0)
    diag = math.sqrt(cell_m * cell_m + cell_m * cell_m)
    best, prev, done, exits = {start: 0.0}, {}, set(), []
    heap = [(0.0, start)]
    while heap:
        gi, i = heapq.heappop(heap)
        if i in done:
            continue
        done.add(i)
        if i not in zone:
            exits.append(i)
            continue
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                j = (i[0] + dr, i[1] + dc)
                if (dr, dc) == (0, 0) or not (0 <= j[0] < H and 0 <= j[1] < W) or j in done:
                    continue
                if j in zone:
                    if et[j[0]][j[1]] < 0:
                        continue
                elif mask[j[0]][j[1]] != 0:
                    continue
                L = diag if dr and dc else cell_m
                ng = gi + L * (rate(i) + rate(j)) / 2
                if ng < best.get(j, math.inf):
                    best[j], prev[j] = ng, i
                    heapq.heappush(heap, (ng, j))
    return best, prev, exits, zone


def test_golden_escape_cases_have_the_expected_kinds(real):
    golden = json.loads((REAL_LANDING / E.GOLDEN_ESCAPE_FILE).read_text(encoding="utf-8"))
    ids = [c["id"] for c in golden["cases"]]
    assert 3 <= len(ids) <= 5 and ids[:3] == ["escape1", "escape2", "escape3"]
    assert "start_too_steep" in ids and "no_exit" in ids and golden["skipped"] == []
    for c in golden["cases"]:
        assert c["start_mask_code"] in ESC["zone_codes"]
        assert set(c["results"]) == {"fastest", "balanced", "safest"}
    by = {c["id"]: c for c in golden["cases"]}
    assert by["start_too_steep"]["start_escape_time_rate"] == -1
    assert all(r["status"] == "no_exit" and r["reason"] == "start_too_steep" for r in by["start_too_steep"]["results"].values())
    assert all(r["status"] == "no_exit" and r["reason"] == "no_exit" for r in by["no_exit"]["results"].values())


def test_replay_reproduces_the_golden_escape_cases(real):
    back, _ = real
    s, ref = back.surface, back.escape
    golden = json.loads((REAL_LANDING / E.GOLDEN_ESCAPE_FILE).read_text(encoding="utf-8"))
    tr, rr, mask = s.time_rate.tolist(), s.risk_rate.tolist(), s.mask.tolist()
    et, er = ref.zone_time.tolist(), ref.zone_risk.tolist()
    regions = X.passable_regions(s.mask)
    for case in golden["cases"]:
        a, z = tuple(case["start_cell"]), tuple(case["dest_cell"])
        got = replay_escape(tr, rr, mask, et, er, ESC["zone_codes"], s.cell_m, a)
        for profile, res in case["results"].items():
            if got is None:
                assert res["reason"] == "start_too_steep", case["id"]
                continue
            best, prev, exits, zone = got
            valid = [e for e in exits if regions[e] == regions[z]]
            if not valid:
                assert res["reason"] == "no_exit", case["id"]
                continue
            m = min(best[e] for e in valid)
            assert sum(best[e] == m for e in valid) == 1 and res["tie"] is False   # no ties in the real cases
            exit_ = next(e for e in valid if best[e] == m)
            cells = [exit_]
            while cells[-1] in prev:
                cells.append(prev[cells[-1]])
            cells.reverse()
            esc = res["escape"]
            assert esc["exit_cell"] == list(exit_) and esc["cells"] == [list(c) for c in cells], case["id"]
            assert esc["exit_xy_m"] == list(s.centre(*exit_))
            zt = [[et[r][c] if (r, c) in zone else tr[r][c] for c in range(len(tr[0]))] for r in range(len(tr))]
            zr = [[er[r][c] if (r, c) in zone else rr[r][c] for c in range(len(tr[0]))] for r in range(len(tr))]
            d, tm, rk = X.totals(s.cell_m, np.asarray(zt), np.asarray(zr), cells)
            assert esc["distance_m"] == pytest.approx(d, rel=REL)
            assert esc["walk_min"] == pytest.approx(tm, rel=REL) and esc["walk_min"] > 0
            assert esc["risk_min"] == pytest.approx(rk, rel=REL)
            route = replay.path_and_totals(tr, rr, mask, s.cell_m, s.weights[profile], exit_, z)
            rcells, rd, rt, rk2 = route
            assert res["route"]["cells"] == [list(c) for c in rcells]
            assert res["route"]["walk_min"] == pytest.approx(rt, rel=REL)
            tot = res["total"]
            assert tot["distance_m"] == pytest.approx(d + rd, rel=REL)
            assert tot["walk_min"] == pytest.approx(tm + rt, rel=REL)
            assert tot["risk_min"] == pytest.approx(rk + rk2, rel=REL)
            b = golden["budget"]
            assert tot["needed_min"] == pytest.approx(tm + rt + b["ingress_min"] + b["stop_min"], rel=REL)
            assert tot["over_budget"] == (tm + rt > b["walk_limit_min"])


def test_escape_risk_counts_every_zone_minute(real):
    """With risk_rate 1 every zone cell's risk equals its time, so risk_min - walk_min comes only from the
    last half-step onto the exit cell (passable ground, its normal risk rate): L * t_exit * (r_exit - 1) / 2."""
    back, _ = real
    assert ESC["risk_rate"] == 1.0
    golden = json.loads((REAL_LANDING / E.GOLDEN_ESCAPE_FILE).read_text(encoding="utf-8"))
    s = back.surface
    for case in golden["cases"]:
        res = case["results"]["fastest"]
        if not res["ok"]:
            continue
        e = res["escape"]
        (pr, pc), (xr, xc) = [tuple(c) for c in e["cells"][-2:]]
        L = s.cell_m * math.sqrt(2.0) if (pr != xr and pc != xc) else s.cell_m
        t_x, r_x = float(s.time_rate[xr, xc]), float(s.risk_rate[xr, xc])
        assert s.mask[xr, xc] == 0
        assert e["risk_min"] - e["walk_min"] == pytest.approx(L * t_x * (r_x - 1.0) / 2.0, rel=1e-6, abs=1e-12)
