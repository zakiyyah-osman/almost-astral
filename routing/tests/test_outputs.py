import copy
import json
import math

import numpy as np
import pytest

import grid as g
import outputs
import plan_route
from config import load_config
from conftest import run_site, write_full_site

CFG = load_config()
SHAPE = (20, 30)
CELL = 5.0


def centre(r, c):
    return g.Grid(SHAPE[1], SHAPE[0], CELL).cell_centre(r, c)


def make_site(folder, fake=False, hazard=None, dem=None):
    hazard = np.zeros(SHAPE, np.uint8) if hazard is None else hazard
    if dem is None:
        dem = (0.2 * np.arange(SHAPE[1])[None, :] + np.zeros((SHAPE[0], 1))).astype(np.float32)
    waypoints = [
        ("start", "Start", "start", *centre(10, 2)),
        ("stop1", "North stop", "stop", *centre(3, 20)),
        ("stop2", "South stop", "stop", *centre(17, 26)),
    ]
    write_full_site(folder, dem, hazard, CELL, waypoints, fake=fake)
    return folder


@pytest.fixture
def result(tmp_path):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[3:17, 10:15] = 1
    return run_site(make_site(tmp_path / "site", hazard=hazard))


def load(result, name):
    return json.loads(result.files[name].decode("utf-8"))


# ---- drop_collinear ----------------------------------------------------------
def test_drop_collinear_removes_vertices_on_straight_runs():
    row = [(4, c) for c in range(8)]
    assert outputs.drop_collinear(row) == [(4, 0), (4, 7)]
    diagonal = [(i, i) for i in range(6)]
    assert outputs.drop_collinear(diagonal) == [(0, 0), (5, 5)]
    bent = [(0, 0), (0, 1), (0, 2), (1, 3), (2, 4), (2, 5)]
    assert outputs.drop_collinear(bent) == [(0, 0), (0, 2), (2, 4), (2, 5)]


def test_drop_collinear_keeps_short_paths_and_closed_loops():
    assert outputs.drop_collinear([(1, 1)]) == [(1, 1)]
    assert outputs.drop_collinear([(1, 1), (1, 2)]) == [(1, 1), (1, 2)]
    loop = [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0), (0, 0)]
    kept = outputs.drop_collinear(loop)
    assert kept == [(0, 0), (0, 2), (2, 2), (2, 0), (0, 0)]


def test_dropping_vertices_does_not_change_the_line():
    cells = [(0, 0), (0, 1), (0, 2), (1, 3), (2, 4), (2, 5), (2, 6), (3, 6), (4, 6)]
    kept = outputs.drop_collinear(cells)
    pts = lambda cs: np.array([(c, -r) for r, c in cs], dtype=float)
    full, short = pts(cells), pts(kept)
    # Every dropped point lies on the segment between its kept neighbours.
    for p in full:
        on = any(
            abs((b - a)[0] * (p - a)[1] - (b - a)[1] * (p - a)[0]) < 1e-9 and np.dot(p - a, p - b) <= 1e-9
            for a, b in zip(short, short[1:])
        )
        assert on


# ---- 5.5 route files ---------------------------------------------------------
@pytest.mark.parametrize("name", ["route.geojson", "route_fastest.geojson", "route_safest.geojson"])
def test_single_linestring_inside_extent(result, name):
    data = load(result, name)
    assert data["type"] == "FeatureCollection" and len(data["features"]) == 1
    geom = data["features"][0]["geometry"]
    assert geom["type"] == "LineString"
    coords = geom["coordinates"]
    assert len(coords) >= 2 and all(len(p) == 2 for p in coords)
    ex, ey = SHAPE[1] * CELL, SHAPE[0] * CELL
    assert all(0 <= x <= ex and 0 <= y <= ey for x, y in coords)
    assert coords[0] == coords[-1] == list(centre(10, 2))              # start to start, [x, y] in metres
    for stop_cell in ((3, 20), (17, 26)):
        assert list(centre(*stop_cell)) in coords                        # through every stop


def test_route_vertices_are_corners_only(result):
    coords = np.array(load(result, "route.geojson")["features"][0]["geometry"]["coordinates"])
    d = np.diff(coords, axis=0)
    for a, b in zip(d, d[1:]):
        assert abs(a[0] * b[1] - a[1] * b[0]) > 1e-9                      # no three vertices on one straight line


def test_no_fake_property(result):
    for name in ("route.geojson", "route_fastest.geojson", "route_safest.geojson"):
        data = load(result, name)
        assert "fake" not in data
        for f in data["features"]:
            assert "fake" not in f and "fake" not in f["properties"]


def test_route_properties(result):
    props = load(result, "route.geojson")["features"][0]["properties"]
    assert set(props) == {"profile", "w", "distance_m", "walk_min", "risk_min", "source"}
    assert props["profile"] == "balanced" and props["w"] == 1.0
    assert props["source"] == "routing model over dem.tif and hazard.tif"
    assert load(result, "route_fastest.geojson")["features"][0]["properties"]["profile"] == "fastest"
    assert load(result, "route_safest.geojson")["features"][0]["properties"]["w"] == 5.0
    assert props["distance_m"] == result.plan["profiles"]["balanced"]["distance_m"]


# ---- 5.6 plan.json -----------------------------------------------------------
def test_all_contract_keys_present(result):
    plan = load(result, "plan.json")
    for key in ("crew", "legs", "totals", "budgets", "radiation_dose_usv"):
        assert key in plan
    assert plan["crew"] == 2
    for leg in plan["legs"]:
        for key in ("from", "to", "distance_m", "walk_min"):
            assert key in leg
        assert isinstance(leg["distance_m"], int) and isinstance(leg["walk_min"], int)   # whole units
    for key in ("walk_min", "stop_min", "total_min"):
        assert isinstance(plan["totals"][key], int)
    assert {"eva_max_min", "radiation_limit_usv"} <= set(plan["budgets"])
    assert isinstance(plan["radiation_dose_usv"], int)
    assert [(l["from"], l["to"]) for l in plan["legs"]] == [
        ("start", "stop1"), ("stop1", "stop2"), ("stop2", "start")]


def test_totals_add_up_and_include_ingress(result):
    t = load(result, "plan.json")["totals"]
    assert t["ingress_min"] == 15 and t["stop_min"] == 50
    assert t["total_min"] == t["walk_min"] + t["stop_min"] + t["ingress_min"]


def test_added_fields_use_one_decimal(result):
    plan = load(result, "plan.json")
    leg = plan["legs"][0]
    for key in ("risk_min", "ascent_m", "descent_m", "max_slope_deg", "depart_min", "arrive_min", "stop_min"):
        assert leg[key] == round(leg[key], 1)
    for p in plan["track"]:
        assert p["distance_m"] == round(p["distance_m"], 1) and p["elapsed_min"] == round(p["elapsed_min"], 1)
    assert plan["profiles"]["balanced"]["total_min"] == round(plan["profiles"]["balanced"]["total_min"], 1)


def test_assumptions_match_config(result):
    plan = load(result, "plan.json")
    # the site's own config sets the starts and the data hashes; everything else is the shipped config
    def rest(a):
        return {k: v for k, v in a.items() if not k.startswith(("start.", "starts."))}
    expected = rest(CFG.assumptions())
    assert rest(plan["assumptions"]) == expected
    assert plan["assumptions"]["start.default"]["value"] == "L1"
    assert plan["assumptions"]["starts.L1"]["value"] == list(centre(10, 2))
    assert [k for k in plan["assumptions"] if k.startswith("starts.")] == ["starts.L1"]
    assert plan["assumptions"]["walking.v_flat_kmh"] == {
        "value": 2.7, "unit": "km/h", "type": "scenario",
        "source": "NASA Apollo planning value for walkbacks over 1 hour",
    }
    assert len(plan["assumptions"]) == len(expected) + 4      # start.default, the two hashes, starts.L1


def test_two_runs_identical(tmp_path):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[3:17, 10:15] = 1
    a = run_site(make_site(tmp_path / "a", hazard=hazard))
    b = run_site(make_site(tmp_path / "b", hazard=hazard))
    again = run_site(tmp_path / "a")
    assert a.files.keys() == b.files.keys()
    for name in a.files:
        assert a.files[name] == b.files[name], name
        assert a.files[name] == again.files[name], name


def test_plan_has_no_top_level_fake_key_and_tracks_fake_inputs(tmp_path):
    real = run_site(make_site(tmp_path / "real"))
    fake = run_site(make_site(tmp_path / "fake", fake=True))
    for r, flag in ((real, False), (fake, True)):
        plan = json.loads(r.files["plan.json"])
        assert "fake" not in plan
        assert plan["inputs"]["inputs_fake"] is flag
        assert plan["inputs"]["site"] == "Synthetic test site"
        assert plan["inputs"]["grid"] == {"width": 30, "height": 20, "cell_m": 5.0}


def test_plan_sections(result):
    plan = load(result, "plan.json")
    assert plan["status"] == "ok" and plan["warnings"] == []
    assert [c["id"] for c in plan["checks"]] == ["reserve", "abort", "radiation"]
    for c in plan["checks"]:
        assert set(c) == {"id", "ok", "value", "limit", "unit", "message"} and c["ok"] is True
    assert plan["stop_order"] == {"mode": "as_listed", "requested": "as_listed",
                                  "order": ["stop1", "stop2"], "warnings": []}
    assert set(plan["profiles"]) == {"fastest", "balanced", "safest"}
    fastest, safest = plan["profiles"]["fastest"], plan["profiles"]["safest"]
    assert fastest["file"] == "route_fastest.geojson" and plan["profiles"]["balanced"]["file"] == "route.geojson"
    assert fastest["w"] == 0.0 and safest["w"] == 5.0
    assert fastest["walk_min"] <= safest["walk_min"] and fastest["risk_min"] >= safest["risk_min"]
    for p in plan["profiles"].values():
        assert set(p) == {"w", "file", "distance_m", "walk_min", "risk_min", "yellow_min", "steep_min",
                          "near_red_min", "total_min", "status"}
    assert plan["budgets"] == {"eva_max_min": 360, "radiation_limit_usv": 1000, "reserve_pct": 30, "usable_min": 252.0}
    assert plan["radiation"]["solar_event"]["absorbed_dose_mgy"] == 8.1
    assert plan["radiation"]["background_usv_h"] == 26.7 and plan["radiation"]["csv_median_usv_h"] == 27.0
    exact = 26.6667 * plan["profiles"]["balanced"]["total_min"] / 60          # from the unrounded total
    assert abs(plan["radiation_dose_usv"] - exact) <= 0.55 and isinstance(plan["radiation_dose_usv"], int)


def test_track_storm_and_back_to_start_blocks(result):
    plan = load(result, "plan.json")
    track = plan["track"]
    assert track[0]["distance_m"] == 0 and track[0]["elapsed_min"] == 0
    assert set(track[0]) >= {"distance_m", "x", "y", "elev_m", "slope_deg", "hazard", "elapsed_min", "shelter_min"}
    assert track[-1]["shelter_min"] == 15 and {p["stop"] for p in track if "stop" in p} == {"stop1", "stop2"}
    storm = plan["storm_replan"]
    assert storm["sample_spacing_m"] == 100
    assert 0 <= storm["worst"] < len(storm["points"])
    worst = storm["points"][storm["worst"]]
    assert worst["return_min"] == max(p["return_min"] for p in storm["points"])
    for p in storm["points"]:
        assert set(p) >= {"x", "y", "route_distance_m", "elapsed_min", "return_min", "return_distance_m", "path"}
        assert p["path"][-1] == list(centre(10, 2)) and p["path"][0] == [p["x"], p["y"]]
    sm = plan["shelter_map"]
    assert sm["file"] == "shelter_time.png" and sm["includes_ingress"] is True
    assert sm["contour_interval_min"] == 10 and sm["colour_max_min"] == 60 and len(sm["stops"]) == 5
    assert plan["track"][0]["shelter_min"] == 15


def test_a_blocked_start_of_storm_path_is_not_present_when_walls_exist(tmp_path):
    hazard = np.zeros(SHAPE, np.uint8)
    hazard[2:16, 12] = 2
    res = run_site(make_site(tmp_path / "wall", hazard=hazard))
    plan = json.loads(res.files["plan.json"])
    for name in ("route.geojson", "route_fastest.geojson", "route_safest.geojson"):
        for x, y in json.loads(res.files[name])["features"][0]["geometry"]["coordinates"]:
            r, c = g.Grid(30, 20, 5.0).xy_to_cell(x, y)
            assert hazard[r, c] != 2
    for p in plan["storm_replan"]["points"]:
        for x, y in p["path"]:
            r, c = g.Grid(30, 20, 5.0).xy_to_cell(x, y)
            assert hazard[r, c] != 2


def test_back_to_start_png_bytes_are_a_grid_sized_rgba_image(result):
    from io import BytesIO
    from PIL import Image
    img = Image.open(BytesIO(result.files["shelter_time.png"]))
    assert img.mode == "RGBA" and img.size == (30, 20)


# ---- dumps -------------------------------------------------------------------
def test_dumps_keeps_number_arrays_on_one_line_and_round_trips():
    obj = {"pts": [[1.5, 2.5], [3, -4.25]], "empty": [], "words": ["a", "b"], "note": "x [1, 2] y",
           "nested": {"v": [0.0, 25, 1e-07]}, "flag": [True, False]}
    text = outputs.dumps(obj)
    assert json.loads(text) == obj
    assert "[1.5, 2.5]" in text and "[3, -4.25]" in text and '"empty": []' in text
    assert text.endswith("\n") and text.count("\n\n") == 0
    assert outputs.dumps(json.loads(text)) == text


def test_dumps_rejects_nan():
    with pytest.raises(ValueError):
        outputs.dumps({"x": float("nan")})
    with pytest.raises(ValueError):
        outputs.dumps({"x": [1.0, float("inf")]})


def test_rounding_helpers():
    assert outputs.r1(12.345) == 12.3 and outputs.r1(None) is None and outputs.r1(2) == 2.0
    assert outputs.whole(12.5) == 12 and outputs.whole(13.5) == 14 and isinstance(outputs.whole(3.2), int)
    assert outputs.xy((1002.5, 902.5)) == [1002.5, 902.5]
    assert outputs.xy((1 / 3, 2 / 3)) == [0.333, 0.667]
