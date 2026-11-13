import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from hazards import GREEN, YELLOW, RED, UNKNOWN, REASON_BITS
from hazards.classify import classify
from hazards.io import Grid
from hazards.terrain import fill_gaps, hillshade, local_relief_m, rock_layers, roughness_m, slope_deg
from hazards.validate import check_tracks

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config" / "hazards.yaml").read_text())


def plane(deg, n=60, cell=1.0, facing="east"):
    yy, xx = np.mgrid[0:n, 0:n] * cell
    t = np.tan(np.radians(deg))
    return t * xx if facing == "east" else -t * yy  # 'north' => rises to the north (row 0)


@pytest.mark.parametrize("deg", [0, 10, 20, 30])
def test_slope_of_plane(deg):
    s = slope_deg(plane(deg), 1.0)
    assert np.allclose(s[5:-5, 5:-5], deg, atol=1e-6)


def test_slope_respects_cell_size():
    z = plane(20, cell=2.0)
    assert np.allclose(slope_deg(z, 2.0)[5:-5, 5:-5], 20, atol=1e-6)


def test_plane_is_not_rough():
    assert roughness_m(plane(20), 1.0, 5).max() < 1e-6  # float noise only, incl. map edges


def test_bumps_are_rough():
    z = plane(5) + np.random.default_rng(0).normal(0, 0.5, (60, 60))
    assert np.median(roughness_m(z, 1.0, 5)) > 0.3


def test_hillshade_lights_slopes_facing_the_sun():
    # sun from the NW (315): a slope rising toward the NW (facing SE) is in shadow,
    # a slope rising to the SE (facing NW) is lit.
    yy, xx = np.mgrid[0:60, 0:60].astype(float)
    faces_nw = 0.5 * (xx + yy)    # rows run south, so this rises to the SE -> faces NW
    faces_se = -0.5 * (xx + yy)   # rises to the NW -> faces SE
    lit = hillshade(faces_nw, 1.0, 315, 45)[10:-10, 10:-10].mean()
    dark = hillshade(faces_se, 1.0, 315, 45)[10:-10, 10:-10].mean()
    assert lit > dark + 0.3


def test_fill_gaps():
    z = plane(10)
    z[10:20, 10:20] = np.nan
    f, gap = fill_gaps(z)
    assert gap.sum() == 100 and np.isfinite(f).all()


def _classes(z, **kw):
    f, gap = fill_gaps(z)
    return classify(slope=slope_deg(f, 1.0), rough=roughness_m(f, 1.0, 5),
                    relief=local_relief_m(f, 1.0, 3), gap=gap, cfg=CFG, cell_m=1.0, **kw)


@pytest.mark.parametrize("deg,expected", [(5, GREEN), (18, YELLOW), (30, RED)])
def test_slope_classes(deg, expected):
    c, _ = _classes(plane(deg))
    assert (c[10:-10, 10:-10] == expected).all()


def test_gap_is_unknown_never_green():
    z = plane(5)
    z[20:30, 20:30] = np.nan
    c, r = _classes(z)
    assert (c[20:30, 20:30] == UNKNOWN).all()
    assert (r[20:30, 20:30] == REASON_BITS["no_data"]).all()


def test_cliff_is_red_with_buffer():
    z = plane(2)
    z[:, 30:] += 5.0  # 5 m step
    c, r = _classes(z)
    assert (c[:, 29:31] == RED).all()
    assert (c[:, 26] == RED).all()  # within the safety buffer
    assert ((r & REASON_BITS["cliff_edge"]) > 0)[:, 30].all()


def test_thermal_inertia():
    ti = np.full((60, 60), 500.0)
    ti[:, :20] = 150   # loose
    ti[:, 40:] = 50    # very loose
    c, _ = _classes(plane(3), thermal=ti)
    assert (c[:, 2:15] == YELLOW).all()
    assert (c[:, 45:] == RED).all()
    assert (c[:, 25:35] == GREEN).all()


def test_rocks():
    g = Grid(60, 60, 1.0)
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.5, 30.5]},
              "properties": {"diameter_m": 1.5}}]
    density, large = rock_layers({"features": feats}, g, CFG["rocks"])
    # rock centre is cell (29, 30); radius 0.75 m + 1.0 m clearance = 1.75 m
    assert large[29, 30] and large[29, 31] and large[28, 30] and large[28, 31]
    assert not large[29, 32] and not large[29, 36]
    assert density.sum() * 1.0 == pytest.approx(1.0, rel=0.05)


def test_track_check_flags_red_crossing():
    g = Grid(60, 60, 1.0)
    z = plane(2)
    z[:, 30:] += 5.0
    c, r = _classes(z)
    s = slope_deg(z, 1.0)
    good = {"features": [{"geometry": {"type": "LineString", "coordinates": [[5, 5], [5, 55]]}, "properties": {"name": "g"}}]}
    z2 = z.copy(); z2[:, 50:] = np.nan
    c2, r2 = _classes(z2)
    gapline = {"features": [{"geometry": {"type": "LineString", "coordinates": [[5, 30], [58, 30]]}, "properties": {"name": "x"}}]}
    assert check_tracks(gapline, g, c2, r2, s, 1.0, fail_on_unknown=True)["tracks"][0]["status"] == "Unknown terrain coverage"
    assert check_tracks(gapline, g, c2, r2, s, 1.0, fail_on_unknown=False)["passed"] is True
    bad = {"features": [{"geometry": {"type": "LineString", "coordinates": [[5, 30], [55, 30]]}, "properties": {"name": "b"}}]}
    assert check_tracks(good, g, c, r, s, 0.01)["passed"] is True
    assert check_tracks(bad, g, c, r, s, 0.01)["passed"] is False


def test_coordinate_convention():
    g = Grid(100, 50, 1.0)
    r, c = g.to_rowcol(0.5, 49.5)   # NW corner cell centre
    assert (r, c) == (0, 0)
    r, c = g.to_rowcol(99.5, 0.5)   # SE corner cell centre
    assert (r, c) == (49, 99)


def test_team_layers_json_parses():
    from hazards.io import Layers
    L = Layers(ROOT / "tests" / "fixtures" / "team_layers.json")
    assert L.grid.shape == (400, 400) and L.grid.cell_m == 5.0 and L.grid.width_m == 2000.0
    lat0, lon0 = L.origin_latlon  # SW corner is 1 km south and 1 km west of the centre
    assert lat0 == pytest.approx(18.46 - np.degrees(1000 / 3396190), abs=1e-6)
    assert lon0 < 77.4 and L.simulated
    assert L.vectors_map["route"] == "route.geojson"


def test_inconsistent_grid_is_rejected():
    from hazards.io import site_grid
    with pytest.raises(ValueError):
        site_grid({"grid": {"width": 400, "height": 400, "cell_m": 5.0}, "extent_m": [1000, 2000]})


def test_coarse_grid_cliff_and_buffer():
    """5 m cells: a gentle 10 deg slope is not a cliff, a 30 m wall is, and the buffer is >= 1 cell."""
    yy, xx = np.mgrid[0:60, 0:60] * 5.0
    z = np.tan(np.radians(10)) * xx
    z[:, 30:] += 30.0
    f, gap = fill_gaps(z)
    c, r = classify(slope=slope_deg(f, 5.0), rough=roughness_m(f, 5.0, 5), relief=local_relief_m(f, 5.0, 3),
                    gap=gap, cfg=CFG, cell_m=5.0)
    assert (c[:, 5:20] == GREEN).all()
    assert (c[:, 29:31] == RED).all() and ((r & REASON_BITS["cliff_edge"]) > 0)[:, 30].all()
    assert ((r & REASON_BITS["safety_buffer"]) > 0).any()


def test_end_to_end_contract(tmp_path):
    import subprocess, sys
    from PIL import Image
    import tifffile
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_mock_data.py"), "--out", str(tmp_path / "d")],
                   check=True, cwd=ROOT, capture_output=True)
    from hazards.run import run
    m = run(tmp_path / "d" / "layers.json", tmp_path / "o", quiet=True)
    o = tmp_path / "o"
    for f in ["hazard.tif", "hazard.png", "coverage.tif", "coverage.png", "relief.png", "slope.png",
              "reasons.tif", "slope.tif", "roughness.tif", "hazards_manifest.json", "track_check.json"]:
        assert (o / f).exists(), f
    # --- the team contract ---
    hz = tifffile.imread(o / "hazard.tif")
    assert hz.dtype == np.uint8 and hz.shape == (400, 400)
    assert set(np.unique(hz).tolist()) <= {0, 1, 2}
    png = np.asarray(Image.open(o / "hazard.png").convert("RGBA"))
    colours = {tuple(c) for c in np.unique(png.reshape(-1, 4), axis=0).tolist()}
    assert colours <= {(0, 0, 0, 0), (240, 190, 40, 255), (220, 50, 50, 255)}
    lut = {(0, 0, 0, 0): 0, (240, 190, 40, 255): 1, (220, 50, 50, 255): 2}
    assert all(lut[tuple(png[r, c])] == hz[r, c] for r in range(0, 400, 7) for c in range(0, 400, 7))
    cov = tifffile.imread(o / "coverage.tif")
    assert (cov == 0).any() and (hz[cov == 0] == 2).all()  # no data -> no-go, never go
    # route through the gap is reported, not passed
    t = json.loads((o / "track_check.json").read_text())["tracks"]
    route = next(x for x in t if x["kind"] == "route")
    assert route["status"] == "Unknown terrain coverage" and not route["passed"]
    drive = next(x for x in t if "simulated rover drive" in x["name"])
    assert drive["passed"]
