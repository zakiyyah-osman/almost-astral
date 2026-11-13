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
    bad = {"features": [{"geometry": {"type": "LineString", "coordinates": [[5, 30], [55, 30]]}, "properties": {"name": "b"}}]}
    assert check_tracks(good, g, c, r, s, 0.01)["passed"] is True
    assert check_tracks(bad, g, c, r, s, 0.01)["passed"] is False


def test_coordinate_convention():
    g = Grid(100, 50, 1.0)
    r, c = g.to_rowcol(0.5, 49.5)   # NW corner cell centre
    assert (r, c) == (0, 0)
    r, c = g.to_rowcol(99.5, 0.5)   # SE corner cell centre
    assert (r, c) == (49, 99)


def test_end_to_end(tmp_path):
    import subprocess, sys
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_mock_data.py"), "--out", str(tmp_path / "d"), "--size", "300"],
                   check=True, cwd=ROOT)
    from hazards.run import run
    m = run(tmp_path / "d" / "layers.json", tmp_path / "o", quiet=True)
    for f in ["hazard.tif", "reasons.tif", "slope.tif", "roughness.tif", "hazards.png", "slope.png",
              "shaded_relief.png", "thermal.png", "minerals.png", "hazards_manifest.json"]:
        assert (tmp_path / "o" / f).exists(), f
    assert abs(sum(m["area_share"].values()) - 1) < 1e-9
    json.loads((tmp_path / "o" / "hazards_manifest.json").read_text())
