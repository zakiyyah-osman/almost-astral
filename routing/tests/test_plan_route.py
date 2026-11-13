import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import plan_route
from conftest import write_full_site

REPO = Path(__file__).resolve().parents[2]
REAL_OUT = REPO / "data" / "out"
SCRIPT = REPO / "routing" / "plan_route.py"
VALIDATE = REPO / "data" / "validate.py"
OUTPUTS = ["route.geojson", "route_fastest.geojson", "route_safest.geojson", "shelter_time.png", "plan.json"]
SHAPE, CELL = (20, 30), 5.0


def centre(r, c):
    return ((c + 0.5) * CELL, (SHAPE[0] - r - 0.5) * CELL)


def make_site(folder, hazard=None, stop2=(17, 26)):
    hazard = np.zeros(SHAPE, np.uint8) if hazard is None else hazard
    dem = np.zeros(SHAPE, np.float32)
    waypoints = [
        ("rover", "Rover", "rover", *centre(10, 2)),
        ("stop1", "North stop", "stop", *centre(3, 20)),
        ("stop2", "South stop", "stop", *centre(*stop2)),
    ]
    write_full_site(folder, dem, hazard, CELL, waypoints)
    return folder


def digest(folder, names=None):
    folder = Path(folder)
    files = sorted(p for p in folder.iterdir() if p.is_file()) if names is None else [folder / n for n in names]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


# ---- command line ------------------------------------------------------------
def test_defaults_read_data_out_and_write_where_they_read():
    args = plan_route.parse_args([])
    assert args.in_dir == REAL_OUT and args.out_dir is None and args.config is None
    args = plan_route.parse_args(["--in", "x", "--out", "y", "--config", "c.toml"])
    assert (args.in_dir, args.out_dir, args.config) == (Path("x"), Path("y"), Path("c.toml"))


def test_in_only_writes_to_the_in_folder(tmp_path, capsys):
    site = make_site(tmp_path / "site")
    before = digest(REAL_OUT) if REAL_OUT.exists() else {}
    assert plan_route.main(["--in", str(site)]) == 0
    assert set(OUTPUTS) <= {p.name for p in site.iterdir()}
    assert json.loads((site / "plan.json").read_text(encoding="utf-8"))["status"] == "ok"
    assert (digest(REAL_OUT) if REAL_OUT.exists() else {}) == before      # data/out untouched
    out = capsys.readouterr().out
    assert "Wrote" in out and "status ok" in out


def test_out_writes_elsewhere_and_leaves_the_inputs_alone(tmp_path):
    site = make_site(tmp_path / "site")
    before = digest(site)
    out = tmp_path / "elsewhere"
    assert plan_route.main(["--in", str(site), "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == sorted(OUTPUTS)
    assert digest(site) == before
    assert (out / "plan.json").read_bytes() == plan_route.run(site).files["plan.json"]


def test_in_out_config_options(tmp_path):
    """Runs on a temp copy of data/out: the shared folder is never written to."""
    if not (REAL_OUT / "dem.tif").exists():
        pytest.skip("data/out has no inputs to copy")
    shared_before = digest(REAL_OUT)
    copy = tmp_path / "copy"
    shutil.copytree(REAL_OUT, copy)
    for name in OUTPUTS:                                          # only the inputs matter, not old outputs
        (copy / name).unlink(missing_ok=True)
    copy_before = digest(copy)

    # --in with --out: the copy is read and left as it was; the outputs land elsewhere.
    out = tmp_path / "out"
    assert plan_route.main(["--in", str(copy), "--out", str(out)]) == 0
    assert set(OUTPUTS) <= {p.name for p in out.iterdir()}
    assert digest(copy) == copy_before

    # --in alone: outputs go into the copy, still not into data/out.
    assert plan_route.main(["--in", str(copy)]) == 0
    assert digest(copy, OUTPUTS) == digest(out, OUTPUTS)

    # --config: another parameter file changes the result.
    text = (REPO / "routing" / "config.toml").read_text(encoding="utf-8")
    assert "value = 360\n" in text
    tight = tmp_path / "tight.toml"
    tight.write_text(text.replace("value = 360\n", "value = 100\n", 1), encoding="utf-8")
    out2 = tmp_path / "out2"
    assert plan_route.main(["--in", str(copy), "--out", str(out2), "--config", str(tight)]) == 0
    assert json.loads((out2 / "plan.json").read_text(encoding="utf-8"))["status"] == "over_budget"
    assert json.loads((out / "plan.json").read_text(encoding="utf-8"))["status"] == "ok"

    assert digest(REAL_OUT) == shared_before                      # data/out untouched throughout


# ---- over budget and failures ------------------------------------------------
def test_over_budget_is_still_written_with_a_warning(tmp_path, capsys):
    site = make_site(tmp_path / "site")
    text = (REPO / "routing" / "config.toml").read_text(encoding="utf-8")
    cfg = tmp_path / "tight.toml"
    cfg.write_text(text.replace("value = 360\n", "value = 100\n", 1), encoding="utf-8")
    assert plan_route.main(["--in", str(site), "--config", str(cfg)]) == 0
    plan = json.loads((site / "plan.json").read_text(encoding="utf-8"))
    assert plan["status"] == "over_budget" and [c["ok"] for c in plan["checks"]][0] is False
    out = capsys.readouterr().out
    assert "WARNING over budget" in out and "usable" in out
    for p in plan["profiles"].values():
        assert p["status"] == "over_budget"


def test_blocked_stop_fails_by_name_and_writes_nothing(tmp_path, capsys):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[17, 26] = 2
    site = make_site(tmp_path / "site", hazard=hazard)
    out = tmp_path / "out"
    assert plan_route.main(["--in", str(site), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "stop2" in err and "South stop" in err and "red hazard cell" in err
    assert not out.exists()                                        # nothing written
    assert not any((site / n).exists() for n in OUTPUTS)


def test_unreachable_stop_fails_and_overwrites_nothing(tmp_path, capsys):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[:, 15] = 2
    site = make_site(tmp_path / "site", hazard=hazard)
    (site / "plan.json").write_text('{"old": true}', encoding="utf-8")
    assert plan_route.main(["--in", str(site)]) == 2
    assert "cannot be reached" in capsys.readouterr().err
    assert (site / "plan.json").read_text(encoding="utf-8") == '{"old": true}'


@pytest.mark.parametrize("breakage,match", [
    ("no_waypoints", "waypoints.geojson not found"),
    ("no_dem", "dem.tif not found"),
    ("bad_layers", "layers.json is not valid JSON"),
    ("two_rovers", "exactly one"),
])
def test_malformed_inputs_exit_non_zero_with_a_message(tmp_path, capsys, breakage, match):
    site = make_site(tmp_path / "site")
    if breakage == "no_waypoints":
        (site / "waypoints.geojson").unlink()
    elif breakage == "no_dem":
        (site / "dem.tif").unlink()
    elif breakage == "bad_layers":
        (site / "layers.json").write_text("{nope", encoding="utf-8")
    elif breakage == "two_rovers":
        data = json.loads((site / "waypoints.geojson").read_text(encoding="utf-8"))
        data["features"][1]["properties"]["kind"] = "rover"
        (site / "waypoints.geojson").write_text(json.dumps(data), encoding="utf-8")
    assert plan_route.main(["--in", str(site)]) == 2
    assert match in capsys.readouterr().err
    assert not any((site / n).exists() for n in OUTPUTS)


def test_bad_config_exits_non_zero(tmp_path, capsys):
    site = make_site(tmp_path / "site")
    cfg = tmp_path / "broken.toml"
    cfg.write_text("[walking.v_flat_kmh\n", encoding="utf-8")
    assert plan_route.main(["--in", str(site), "--config", str(cfg)]) == 2
    assert "broken.toml" in capsys.readouterr().err
    assert not (site / "plan.json").exists()
    assert plan_route.main(["--in", str(tmp_path / "missing_folder")]) == 2
    assert "layers.json not found" in capsys.readouterr().err


# ---- the script and validate.py ----------------------------------------------
def test_script_runs_and_validate_passes_without_warnings(tmp_path):
    site = make_site(tmp_path / "site")
    run = subprocess.run([sys.executable, "-B", str(SCRIPT), "--in", str(site)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert set(OUTPUTS) <= {p.name for p in site.iterdir()}
    val = subprocess.run([sys.executable, "-B", str(VALIDATE), str(site), "--strict"], capture_output=True, text=True)
    assert val.returncode == 0, val.stdout
    assert val.stdout.startswith("OK") and "WARNING" not in val.stdout and "ERROR" not in val.stdout


def test_validate_warns_only_about_fake_layers_not_plan_or_routes(tmp_path):
    site = tmp_path / "site"
    write_full_site(site, np.zeros(SHAPE, np.float32), np.zeros(SHAPE, np.uint8), CELL,
                    [("rover", "Rover", "rover", *centre(10, 2)), ("stop1", "A", "stop", *centre(3, 20))], fake=True)
    assert plan_route.main(["--in", str(site)]) == 0
    val = subprocess.run([sys.executable, "-B", str(VALIDATE), str(site)], capture_output=True, text=True)
    assert val.returncode == 0
    assert "plan.json" not in val.stdout and "route.geojson" not in val.stdout


def test_summary_mentions_fake_inputs(tmp_path, capsys):
    site = tmp_path / "site"
    write_full_site(site, np.zeros(SHAPE, np.float32), np.zeros(SHAPE, np.uint8), CELL,
                    [("rover", "Rover", "rover", *centre(10, 2)), ("stop1", "A", "stop", *centre(3, 20))], fake=True)
    plan_route.main(["--in", str(site)])
    assert "fake data" in capsys.readouterr().out
