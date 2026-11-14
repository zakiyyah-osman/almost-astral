import ast
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import analysis
import cost
import grid as g
import plan_route
import timeline
import tour
from config import load_config
from conftest import config_for, run_site, with_config, write_full_site

REPO = Path(__file__).resolve().parents[2]
REAL_OUT = REPO / "data" / "out"
REPO_REPORTS = REPO / "routing" / "reports"
CFG = load_config()
SHAPE, CELL = (20, 30), 5.0


def centre(r, c):
    return g.Grid(SHAPE[1], SHAPE[0], CELL).cell_centre(r, c)


def make_site(folder, hazard=None, dem=None, stop1=(3, 20), stop2=(17, 26)):
    hazard = np.zeros(SHAPE, np.uint8) if hazard is None else hazard
    dem = np.zeros(SHAPE, np.float32) if dem is None else dem
    waypoints = [
        ("start", "Start", "start", *centre(10, 2)),
        ("stop1", "North stop", "stop", *centre(*stop1)),
        ("stop2", "South stop", "stop", *centre(*stop2)),
    ]
    write_full_site(folder, dem, hazard, CELL, waypoints)
    return folder


def band_hazard():
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[3:17, 10:15] = 1                       # yellow band: shorter through, longer round
    return hazard


def prepared(folder, cfg=CFG):
    site = g.load_site(folder)
    start, stops = tour.split_waypoints(tour.load_waypoints(folder, site.grid))
    model = cost.build(site.dem, site.hazard, site.slope, site.grid, cost.Params.from_config(cfg))
    rad = timeline.radiation_info(cfg, folder)
    return site, start, stops, model, rad


def digest(folder):
    folder = Path(folder)
    if not folder.exists():
        return {}
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---- 6.1 the w-sweep ---------------------------------------------------------
def test_sweep_time_rises_risk_falls(tmp_path):
    site, start, stops, model, _ = prepared(make_site(tmp_path / "s", hazard=band_hazard()))
    plan = tour.plan_routes(model, start, stops, CFG)
    rows = analysis.sweep(model, start, plan.order, CFG)
    assert [r["w"] for r in rows] == CFG.value("profiles.sweep_w") == [0.0, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
    assert set(rows[0]) == set(analysis.SWEEP_FIELDS)
    walk = [r["walk_min"] for r in rows]
    risk = [r["risk_min"] for r in rows]
    assert walk == sorted(walk) and risk == sorted(risk, reverse=True)       # time rises, risk falls
    assert walk[-1] > walk[0] + 0.05 and risk[0] > risk[-1] + 0.05            # a real trade-off on this site
    assert risk[-1] == 0.0                                                     # a high enough w avoids yellow
    for r in rows:
        assert r["risk_min"] == pytest.approx(r["yellow_min"] + r["steep_min"] + r["near_red_min"], abs=0.11)
        assert r["distance_m"] > 0 and r["steep_min"] == 0.0
    by_w = {r["w"]: r for r in rows}
    balanced = plan.routes["balanced"]
    assert by_w[1.0]["walk_min"] == pytest.approx(balanced.physical_min, abs=0.05)
    assert by_w[0.0]["walk_min"] == pytest.approx(plan.routes["fastest"].physical_min, abs=0.05)


def test_sweep_uses_the_given_weights_and_the_given_order(tmp_path):
    site, start, stops, model, _ = prepared(make_site(tmp_path / "s", hazard=band_hazard()))
    rows = analysis.sweep(model, start, stops, CFG, ws=[0, 3])
    assert [r["w"] for r in rows] == [0.0, 3.0]
    reverse = analysis.sweep(model, start, list(reversed(stops)), CFG, ws=[0])
    assert reverse[0]["distance_m"] != 0 and reverse[0]["w"] == 0.0


def test_plan_json_sweep_has_the_seven_rows(tmp_path):
    folder = make_site(tmp_path / "s", hazard=band_hazard())
    plan = json.loads(run_site(folder).files["plan.json"])
    assert len(plan["sweep"]) == 7
    assert [r["w"] for r in plan["sweep"]] == CFG.value("profiles.sweep_w")
    assert list(plan["sweep"][0]) == list(analysis.SWEEP_FIELDS)
    keys = list(plan)
    assert keys.index("sweep") == keys.index("profiles") + 1


def test_sweep_csv_has_the_same_rows_as_plan_json(tmp_path):
    folder = make_site(tmp_path / "s", hazard=band_hazard())
    plan = json.loads(run_site(folder).files["plan.json"])
    reports = tmp_path / "reports"
    assert analysis.main([*with_config(folder), "--in", str(folder), "--reports", str(reports)]) == 0
    rows = read_csv(reports / "sweep.csv")
    assert len(rows) == 7
    assert list(rows[0]) == list(analysis.SWEEP_FIELDS)
    for csv_row, plan_row in zip(rows, plan["sweep"]):
        assert {k: float(v) for k, v in csv_row.items()} == plan_row


def test_in_config_reports_options(tmp_path, capsys):
    """Runs on a temp copy: data/out and routing/reports are never touched."""
    folder = make_site(tmp_path / "site", hazard=band_hazard())
    site_before, shared_before, repo_reports_before = digest(folder), digest(REAL_OUT), digest(REPO_REPORTS)
    reports = tmp_path / "my_reports"

    assert analysis.main([*with_config(folder), "--in", str(folder), "--reports", str(reports)]) == 0
    assert sorted(p.name for p in reports.iterdir()) == ["sensitivity.csv", "sweep.csv"]
    assert len(read_csv(reports / "sweep.csv")) == 7 and len(read_csv(reports / "sensitivity.csv")) == 18

    # --config changes what is run.
    text = config_for(folder).read_text(encoding="utf-8")
    old = "value = [0.0, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]\n"
    assert old in text
    cfg_file = tmp_path / "short_sweep.toml"
    cfg_file.write_text(text.replace(old, "value = [0.0, 2.0]\n", 1), encoding="utf-8")
    reports2 = tmp_path / "reports2"
    assert analysis.main([*with_config(folder), "--in", str(folder), "--config", str(cfg_file), "--reports", str(reports2)]) == 0
    assert [r["w"] for r in read_csv(reports2 / "sweep.csv")] == ["0.0", "2.0"]
    assert len(read_csv(reports2 / "sensitivity.csv")) == 18

    assert digest(folder) == site_before                         # the inputs folder gets no output
    assert digest(REAL_OUT) == shared_before                     # data/out untouched
    assert digest(REPO_REPORTS) == repo_reports_before           # routing/reports untouched
    assert "Wrote sweep.csv, sensitivity.csv" in capsys.readouterr().out


def test_bad_input_or_config_writes_no_reports(tmp_path, capsys):
    folder = make_site(tmp_path / "site")
    (folder / "waypoints.geojson").unlink()
    reports = tmp_path / "reports"
    assert analysis.main([*with_config(folder), "--in", str(folder), "--reports", str(reports)]) == 2
    assert "waypoints.geojson" in capsys.readouterr().err and not reports.exists()
    ok = make_site(tmp_path / "ok")
    bad = tmp_path / "bad.toml"
    bad.write_text("[x\n", encoding="utf-8")
    assert analysis.main([*with_config(ok), "--in", str(ok), "--config", str(bad), "--reports", str(reports)]) == 2
    assert not reports.exists()


def test_analysis_never_imports_plan_route():
    tree = ast.parse((REPO / "routing" / "analysis.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert "plan_route" not in names


def test_analysis_has_no_out_option():
    parser_args = analysis.parse_args(["--in", "a", "--reports", "b", "--config", "c"])
    assert not hasattr(parser_args, "out_dir") and parser_args.reports == Path("b")
    with pytest.raises(SystemExit):
        analysis.parse_args(["--out", "x"])
    assert analysis.parse_args([]).reports == REPO_REPORTS and analysis.parse_args([]).in_dir == REAL_OUT


# ---- 6.2 sensitivity ---------------------------------------------------------
def sens(folder, cfg=CFG):
    site, start, stops, _, rad = prepared(folder, cfg)
    return analysis.sensitivity(site, start, stops, cfg, rad)


def test_sensitivity_has_18_rows_in_config_order(tmp_path):
    rows = sens(make_site(tmp_path / "s", hazard=band_hazard()))
    assert len(rows) == 18 == 2 * 3 * 3
    assert set(rows[0]) == set(analysis.SENSITIVITY_FIELDS)
    combos = [(r["v_flat_kmh"], r["slope_max_deg"], r["w"]) for r in rows]
    assert len(set(combos)) == 18
    assert combos[0] == (2.7, 15, 0.0) and combos[-1] == (3.4, 25, 5.0)
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["failed_stop"] is None and r["reason"] is None for r in rows)
    for r in rows:
        assert r["total_min"] == pytest.approx(r["walk_min"] + 2 * 25 + 15, abs=0.11)


def test_faster_v_flat_shortens_walk(tmp_path):
    rows = sens(make_site(tmp_path / "s"))                      # flat terrain: time scales exactly with 1 / v
    by = {(r["v_flat_kmh"], r["slope_max_deg"], r["w"]): r for r in rows}
    for slope_max in (15, 20, 25):
        for w in (0.0, 1.0, 5.0):
            slow, fast = by[(2.7, slope_max, w)], by[(3.4, slope_max, w)]
            assert fast["walk_min"] < slow["walk_min"]
            assert fast["total_min"] < slow["total_min"]
            assert fast["walk_min"] == pytest.approx(slow["walk_min"] * 2.7 / 3.4, abs=0.11)


def test_faster_v_flat_shortens_walk_with_a_risky_band(tmp_path):
    rows = sens(make_site(tmp_path / "s", hazard=band_hazard()))
    by = {(r["v_flat_kmh"], r["slope_max_deg"], r["w"]): r for r in rows}
    for slope_max in (15, 20, 25):
        for w in (0.0, 1.0, 5.0):
            assert by[(3.4, slope_max, w)]["walk_min"] < by[(2.7, slope_max, w)]["walk_min"]


def test_a_tighter_slope_limit_makes_a_stop_infeasible_by_name(tmp_path):
    cols = np.arange(SHAPE[1], dtype=float)
    ramp = np.tan(np.radians(17.0)) * CELL * np.clip(cols - 20, 0, None)       # 17 degrees from column 20 east
    dem = (np.zeros((SHAPE[0], 1)) + ramp[None, :]).astype(np.float32)
    rows = sens(make_site(tmp_path / "s", dem=dem, stop1=(3, 12), stop2=(10, 25)))             # stop2 stands on the 17 degree ramp
    limit15 = [r for r in rows if r["slope_max_deg"] == 15]
    assert len(limit15) == 6 and all(r["status"] == "infeasible" for r in limit15)
    for r in limit15:
        assert r["failed_stop"] == "stop2" and "stop2" in r["reason"] and "slope" in r["reason"]
        assert r["walk_min"] is None and r["total_min"] is None and r["risk_min"] is None
    for r in rows:
        if r["slope_max_deg"] in (20, 25):
            assert r["status"] == "ok" and r["failed_stop"] is None and r["walk_min"] > 0


def test_unreachable_stop_is_infeasible_for_every_run(tmp_path):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[:, 15] = 2
    rows = sens(make_site(tmp_path / "s", hazard=hazard))
    assert all(r["status"] == "infeasible" and r["failed_stop"] == "stop1" for r in rows)
    assert all("cannot be reached" in r["reason"] for r in rows)


def test_over_budget_status_is_reported(tmp_path):
    import copy
    from config import Config
    raw = copy.deepcopy(CFG.raw)
    raw["timeline"]["eva_max_min"]["value"] = 100
    rows = sens(make_site(tmp_path / "s"), Config.from_dict(raw))
    assert all(r["status"] == "over_budget" for r in rows)
    assert all(r["total_min"] > 70 for r in rows)


def test_sensitivity_csv_has_18_rows_and_blank_cells_for_infeasible_runs(tmp_path):
    cols = np.arange(SHAPE[1], dtype=float)
    ramp = np.tan(np.radians(17.0)) * CELL * np.clip(cols - 20, 0, None)
    dem = (np.zeros((SHAPE[0], 1)) + ramp[None, :]).astype(np.float32)
    folder = make_site(tmp_path / "s", dem=dem, stop1=(3, 12), stop2=(10, 25))
    reports = tmp_path / "reports"
    assert analysis.main([*with_config(folder), "--in", str(folder), "--reports", str(reports)]) == 0
    rows = read_csv(reports / "sensitivity.csv")
    assert len(rows) == 18 and list(rows[0]) == list(analysis.SENSITIVITY_FIELDS)
    infeasible = [r for r in rows if r["status"] == "infeasible"]
    assert len(infeasible) == 6 and all(r["walk_min"] == "" and r["failed_stop"] == "stop2" for r in infeasible)
    ok = [r for r in rows if r["status"] == "ok"]
    assert len(ok) == 12 and all(float(r["walk_min"]) > 0 and r["failed_stop"] == "" for r in ok)


def test_write_csv_round_trips(tmp_path):
    path = analysis.write_csv(tmp_path / "x" / "t.csv", ("a", "b"), [{"a": 1.5, "b": None}, {"a": 2, "b": "x, y"}])
    assert read_csv(path) == [{"a": "1.5", "b": ""}, {"a": "2", "b": "x, y"}]
    assert path.read_text(encoding="utf-8").startswith("a,b\n")
