"""Phase 7: checks on the real outputs in data/out/ (written by python routing/plan_route.py)
and a run on a differently sized grid. These are the only tests that read data/out/."""
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import grid as g
import plan_route
from config import load_config
from conftest import write_full_site

REAL_OUT = Path(__file__).resolve().parents[2] / "data" / "out"
CFG = load_config()
ROUTE_FILES = ["route.geojson", "route_fastest.geojson", "route_safest.geojson"]
OUTPUT_FILES = [*ROUTE_FILES, "shelter_time.png", "plan.json"]
NOT_BUILT = "run python routing/plan_route.py first"


def skip_unless_planner_outputs_exist():
    """Skip when data/out has no routing output yet, or still has the fake plan from make_fake.py."""
    missing = [n for n in OUTPUT_FILES if not (REAL_OUT / n).is_file()]
    if missing:
        pytest.skip(f"{NOT_BUILT} (missing from data/out: {', '.join(missing)})")
    try:
        plan = json.loads((REAL_OUT / "plan.json").read_text(encoding="utf-8"))
    except ValueError:
        pytest.skip(f"{NOT_BUILT} (data/out/plan.json is not valid JSON)")
    if not isinstance(plan, dict) or "profiles" not in plan:
        pytest.skip(f"{NOT_BUILT} (data/out/plan.json is still the fake plan)")


def load_json(name):
    return json.loads((REAL_OUT / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real():
    skip_unless_planner_outputs_exist()
    grid = g.read_grid(REAL_OUT)
    dem = g.load_dem(REAL_OUT, grid)
    return {
        "grid": grid,
        "dem": dem,
        "hazard": g.load_hazard(REAL_OUT, grid),
        "slope": g.slope_deg(dem, grid.cell_m),
        "plan": load_json("plan.json"),
    }


def route_cells(grid, name):
    """Every cell the route passes through, stepping along each straight run between vertices."""
    coords = load_json(name)["features"][0]["geometry"]["coordinates"]
    vertices = [grid.xy_to_cell(x, y) for x, y in coords]
    cells = [vertices[0]]
    for (r0, c0), (r1, c1) in zip(vertices, vertices[1:]):
        dr, dc = int(np.sign(r1 - r0)), int(np.sign(c1 - c0))
        assert abs(r1 - r0) == abs(c1 - c0) or r1 == r0 or c1 == c0, "vertices must be on a straight run"
        r, c = r0, c0
        while (r, c) != (r1, c1):
            r, c = r + dr, c + dc
            cells.append((r, c))
    return cells


@pytest.mark.parametrize("name", ROUTE_FILES)
def test_no_route_touches_red(real, name):
    """No route cell is red. A diagonal step past a red corner is allowed."""
    cells = route_cells(real["grid"], name)
    assert len(cells) > 2
    red = [c for c in cells if real["hazard"][c] == g.HAZARD_RED]
    assert red == []


@pytest.mark.parametrize("name", ROUTE_FILES)
def test_route_slope_under_limit(real, name):
    limit = CFG.value("constraints.slope_max_deg")
    slopes = np.array([real["slope"][c] for c in route_cells(real["grid"], name)])
    assert np.isfinite(slopes).all()
    assert slopes.max() <= limit
    assert max(leg["max_slope_deg"] for leg in real["plan"]["legs"]) <= limit


def test_plan_status_ok(real):
    plan = real["plan"]
    assert plan["status"] == "ok"
    assert all(c["ok"] for c in plan["checks"])
    assert all(p["status"] == "ok" for p in plan["profiles"].values())
    assert plan["warnings"] == []


def test_runs_on_120x80_grid(wide_site, tmp_path):
    """A 120 x 80 grid with 10 m cells: nothing in the code assumes 400 x 400 at 5 m."""
    grid = g.Grid(120, 80, 10.0)
    hazard = np.zeros((80, 120), np.uint8)
    hazard[20:60, 60] = 2                                  # a wall with gaps at the top and bottom
    dem = (0.05 * np.arange(120)[None, :] + np.zeros((80, 1))).astype(np.float32)
    waypoints = [
        ("rover", "Rover", "rover", *grid.cell_centre(40, 10)),
        ("stop1", "East", "stop", *grid.cell_centre(10, 100)),
        ("stop2", "South", "stop", *grid.cell_centre(70, 90)),
    ]
    folder = tmp_path / "wide"
    write_full_site(folder, dem, hazard, 10.0, waypoints)
    result = plan_route.run(folder)
    plan = json.loads(result.files["plan.json"])
    assert plan["inputs"]["grid"] == {"width": 120, "height": 80, "cell_m": 10.0}
    assert plan["status"] == "ok"
    img = Image.open(BytesIO(result.files["shelter_time.png"]))
    assert img.size == (120, 80) and img.mode == "RGBA"
    for name in ROUTE_FILES:
        coords = json.loads(result.files[name])["features"][0]["geometry"]["coordinates"]
        assert all(0 <= x <= 1200 and 0 <= y <= 800 for x, y in coords)
        assert coords[0] == coords[-1] == list(grid.cell_centre(40, 10))
        for x, y in coords:
            assert hazard[grid.xy_to_cell(x, y)] != 2
    assert plan["legs"][0]["distance_m"] > 90 * 10.0       # about 90 cells of 10 m to the east stop
