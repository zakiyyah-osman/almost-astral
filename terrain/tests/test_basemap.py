"""Base map + dataset-day tools (Person 2)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile

from basemap import align, imagery
from hazards.io import Layers
from hazards.terrain import fill_gaps, hillshade

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mock(tmp_path_factory):
    d = tmp_path_factory.mktemp("mock")
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_mock_data.py"), "--out", str(d), "--size", "400"],
                   check=True, cwd=ROOT, capture_output=True)
    return d


def fake_orbital_product(mock: Path, dest: Path, err_e=0.0, err_n=0.0, pad=60, cell=1.0):
    """A 'HiRISE-like' image of the mock site in source-projection metres, larger than
    the site, lit from a different sun, with a world file that is wrong by (err_e, err_n)."""
    L = Layers(mock / "layers.json")
    dtm, _ = fill_gaps(L.raster("dtm"))
    big = np.pad(dtm, pad, mode="reflect")
    img = hillshade(big, cell, azimuth_deg=250, altitude_deg=30)
    img = 40 + 180 * img + np.random.default_rng(1).normal(0, 4, img.shape)
    tifffile.imwrite(dest, img.astype(np.float32))
    x0, y0 = L.meta["site"]["origin_source_xy"]
    H = L.grid.height_m
    # pixel centre of the big image's (0, 0): pad cells west and north of the site's NW corner
    c = x0 - pad * cell + cell / 2 + err_e
    f = y0 + H + pad * cell - cell / 2 + err_n
    dest.with_suffix(".tfw").write_text(f"{cell}\n0\n0\n{-cell}\n{c}\n{f}\n")
    return img


def test_world_file_affine(tmp_path):
    p = tmp_path / "a.tif"
    tifffile.imwrite(p, np.zeros((4, 4), np.float32))
    p.with_suffix(".tfw").write_text("2\n0\n0\n-2\n100\n500\n")
    A = imagery.read_affine(p)
    assert np.allclose(A @ [0, 0, 1], [100, 500]) and np.allclose(A @ [1, 1, 1], [102, 498])


def test_geotiff_tiepoint_is_pixel_corner(tmp_path):
    p = tmp_path / "g.tif"
    tifffile.imwrite(p, np.zeros((4, 4), np.float32),
                     extratags=[(33550, "d", 3, (2.0, 2.0, 0.0), False), (33922, "d", 6, (0, 0, 0, 100.0, 500.0, 0), False)])
    A = imagery.read_affine(p)
    assert np.allclose(A @ [0, 0, 1], [101, 499])  # centre of the first pixel


def test_resample_correct_georef_is_aligned(mock, tmp_path):
    d = tmp_path / "data"
    shutil.copytree(mock, d)
    fake_orbital_product(d, tmp_path / "hirise.tif")
    imagery.main(["resample", str(tmp_path / "hirise.tif"), "--layers", str(d / "layers.json"),
                  "--out", str(d / "ortho.tif"), "--id", "ortho", "--source", "test"])
    rep = align.run(d / "layers.json", tmp_path / "o", quiet=True)
    assert rep["layers"]["ortho"]["offset_m"] < 0.5
    assert rep["passed"]
    assert (tmp_path / "o" / "landmark_chips.png").exists()


def test_misregistration_is_measured(mock, tmp_path):
    d = tmp_path / "data"
    shutil.copytree(mock, d)
    fake_orbital_product(d, tmp_path / "hirise.tif", err_e=3.0, err_n=2.0)
    imagery.main(["resample", str(tmp_path / "hirise.tif"), "--layers", str(d / "layers.json"),
                  "--out", str(d / "ortho.tif"), "--id", "ortho"])
    rep = align.run(d / "layers.json", tmp_path / "o", quiet=True)
    o = rep["layers"]["ortho"]
    # features drawn 3 m east / 2 m north of truth -> move the layer 3 m west, 2 m south
    assert o["shift_to_apply_east_m"] == pytest.approx(-3.0, abs=0.3)
    assert o["shift_to_apply_north_m"] == pytest.approx(-2.0, abs=0.3)
    assert not rep["passed"]


def test_define_site(tmp_path):
    lj = tmp_path / "layers.json"
    imagery.main(["define-site", "--layers", str(lj), "--center-xy", "8144000", "-278000", "--size", "2000", "1000"])
    s = json.loads(lj.read_text())["site"]
    assert s["origin_source_xy"] == [8143000.0, -278500.0]
    assert s["width_m"] == 2000 and s["height_m"] == 1000
    lat, lon = s["origin_latlon"]
    assert lat == pytest.approx(np.degrees(-278500 / imagery.MARS_R), abs=1e-6)
    assert lon == pytest.approx(np.degrees(8143000 / imagery.MARS_R), abs=1e-6)


def test_build_and_viewer(mock, tmp_path):
    from basemap.build import build_config, build_viewer
    from hazards.run import run
    out = tmp_path / "o"
    run(mock / "layers.json", out, quiet=True)
    cfg = build_config(mock / "layers.json", out, out)
    build_viewer(cfg, out)
    assert cfg["simulated"] is True
    ids = [l["id"] for l in cfg["layers"]]
    assert ids[0] == "imagery" and "hazards" in ids and "landmarks" in ids
    assert cfg["projection"]["leaflet_crs_simple_bounds"] == [[0, 0], [400.0, 400.0]]
    html = (out / "martial_map.html").read_text()
    assert "window.MM_CONFIG" in html and "data:image/png;base64," in html and "<!--JS-->" not in html


def test_coords_js():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(["node", str(ROOT / "basemap" / "web" / "coords.test.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
