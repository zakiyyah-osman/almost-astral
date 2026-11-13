"""Dataset day: verify that landmarks line up across layers.

    python -m basemap.align --layers data/layers.json --out out

Two checks:
1. Measured offset - orbital imagery is compared with the terrain rendered under the image's own lighting
   (sub-pixel phase correlation). Any offset larger than
   --tolerance cells is flagged with its direction in metres, so you know which
   way to shift the origin.
2. Landmark chips - a small crop from every layer around each landmark, with a
   crosshair, in one image (landmark_chips.png). Eyeball it: the crater rim or ridge
   should sit at the same place in every column.

Writes alignment_report.json and landmark_chips.png. Exit code 1 if any layer is off.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage
from skimage.registration import phase_cross_correlation

from hazards.io import Layers
from hazards.terrain import fill_gaps, hillshade

# Only orbital images are compared numerically with the terrain. Thermal (THEMIS ~100 m),
# minerals (CRISM ~18 m, class colours) and derived layers get the visual chips only.
CORRELATE_IDS = {"hirise", "ortho", "imagery", "ctx"}
SKIP_IDS = {"relief", "slope", "hazard", "coverage", "shelter_time"}  # derived from the DEM itself


def _on_grid(path: Path, shape) -> np.ndarray:
    """Display PNG -> grey float array on the grid (block-averaged if finer)."""
    from PIL import Image
    im = Image.open(path).convert("LA")
    a = np.asarray(im, float)
    g, alpha = a[..., 0], a[..., 1]
    g[alpha < 10] = np.nan
    if g.shape != shape:
        fy, fx = g.shape[0] / shape[0], g.shape[1] / shape[1]
        if abs(fy - round(fy)) < 1e-6 and abs(fx - round(fx)) < 1e-6 and fy >= 1:
            fy, fx = int(round(fy)), int(round(fx))
            g = np.nanmean(g.reshape(shape[0], fy, shape[1], fx), axis=(1, 3))
        else:
            g = np.asarray(Image.fromarray(np.nan_to_num(g).astype(np.float32)).resize(shape[::-1], Image.BILINEAR), float)
    return g




def shading_like(dtm: np.ndarray, image: np.ndarray, cell_m: float) -> np.ndarray:
    """Render the terrain lit the way the image is lit.

    Brightness of a sunlit slope is close to a + b*dz/dx + c*dz/dy, so a least-squares
    fit of the image against the terrain gradients recovers the (unknown) sun direction.
    Comparing the image with plain shaded relief from a different sun would bias the
    measured offset by about a metre."""
    z = ndimage.gaussian_filter(dtm, 1.0)
    gy, gx = np.gradient(z, cell_m)
    ok = np.isfinite(image)
    X = np.column_stack([np.ones(ok.sum()), gx[ok], gy[ok]])
    coef, *_ = np.linalg.lstsq(X, image[ok], rcond=None)
    return coef[0] + coef[1] * gx + coef[2] * gy


def measure_offset(dtm: np.ndarray, image: np.ndarray, cell_m: float, max_px=1024):
    """Shift (east_m, north_m) to ADD to the image's position so it matches the terrain.
    Uses the central window (<= max_px) for speed."""
    h, w = dtm.shape
    k = min(max_px, h, w)
    r0, c0 = (h - k) // 2, (w - k) // 2
    sl = (slice(r0, r0 + k), slice(c0, c0 + k))
    img = image[sl].astype(float)
    ref = shading_like(dtm[sl], img, cell_m)
    img = np.where(np.isfinite(img), img, np.nanmean(img))
    norm = lambda a: (a - a.mean()) / (a.std() + 1e-12)
    win = np.outer(np.hanning(k), np.hanning(k))
    shift, err, _ = phase_cross_correlation(norm(ref) * win, norm(img) * win, upsample_factor=20, normalization=None)
    drow, dcol = shift  # image shifted by (drow, dcol) matches the terrain
    return float(dcol * cell_m), float(-drow * cell_m), float(err)


def chips(L: Layers, rasters: dict, landmarks: list, out: Path, half_m=60):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = L.grid
    names = list(rasters)
    fig, axs = plt.subplots(len(landmarks), len(names), figsize=(2.3 * len(names), 2.3 * len(landmarks)),
                            dpi=90, squeeze=False)
    hc = int(half_m / g.cell_m)
    for i, f in enumerate(landmarks):
        e, n = f["geometry"]["coordinates"][:2]
        r, c = (int(round(float(v))) for v in g.to_rowcol(e, n))
        for j, name in enumerate(names):
            ax = axs[i, j]
            a = rasters[name]
            r0, r1, c0, c1 = max(0, r - hc), min(a.shape[0], r + hc), max(0, c - hc), min(a.shape[1], c + hc)
            crop = a[r0:r1, c0:c1]
            ax.imshow(crop, cmap="gray", interpolation="nearest",
                      extent=[(c0 - c) * g.cell_m, (c1 - c) * g.cell_m, (r - r1) * g.cell_m, (r - r0) * g.cell_m])
            for lw, col in ((2.4, "black"), (1.1, "#ff7a2f")):
                ax.axhline(0, color=col, lw=lw)
                ax.axvline(0, color=col, lw=lw)
            ax.set_xticks([])
            ax.set_yticks([])
            if i == 0:
                ax.set_title(name, fontsize=9)
            if j == 0:
                ax.set_ylabel(f["properties"].get("name", f"#{i}"), fontsize=8)
    fig.suptitle(f"Landmark chips ±{half_m} m - features should sit on the crosshair in every column", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "landmark_chips.png")
    plt.close(fig)


def run(layers_json, out_dir, tolerance_cells=1.5, quiet=False):
    L = Layers(layers_json)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log = (lambda *a: None) if quiet else print
    dtm, gap = fill_gaps(L.raster("dtm"))
    shade = hillshade(dtm, L.grid.cell_m)
    shade[gap] = np.nan
    rasters = {"terrain (shaded)": shade}
    report = {"tolerance_m": tolerance_cells * L.grid.cell_m, "layers": {}, "passed": True}

    if L.has("thermal_inertia"):
        rasters["thermal_inertia"] = L.raster("thermal_inertia")
        report["layers"]["thermal_inertia"] = {"note": "visual check only (landmark_chips.png)"}
    for lid, meta in L.display.items():
        if lid in SKIP_IDS or lid == "thermal" and "thermal_inertia" in rasters:
            continue
        f = L.root / meta["file"]
        if not f.exists():
            continue
        arr = _on_grid(f, L.grid.shape)
        rasters[lid] = arr
        if lid in CORRELATE_IDS or meta.get("check_alignment"):
            de, dn, err = measure_offset(dtm, arr, L.grid.cell_m)
            off = float(np.hypot(de, dn))
            ok = off <= tolerance_cells * L.grid.cell_m
            report["layers"][lid] = {"shift_to_apply_east_m": round(de, 2), "shift_to_apply_north_m": round(dn, 2),
                                     "offset_m": round(off, 2), "match_error": round(err, 3), "passed": ok}
            report["passed"] &= ok
            log(f"{lid:>16}: offset {off:6.2f} m (move it E {de:+.2f} m, N {dn:+.2f} m) -> {'OK' if ok else 'MISALIGNED'}")
        else:
            report["layers"][lid] = {"note": "visual check only (landmark_chips.png)"}

    lms = []
    for name in ("landmarks", "waypoints"):
        if L.has_vector(name):
            lms += [f for f in L.vector(name)["features"] if (f.get("geometry") or {}).get("type") == "Point"]
    for f in lms:
        f.setdefault("properties", {}).setdefault("name", f["properties"].get("title") or f["properties"].get("id") or "point")
    if lms:
        chips(L, rasters, lms[:8], out, half_m=max(60, 12 * L.grid.cell_m))
        log(f"landmark chips -> {out / 'landmark_chips.png'}")
    else:
        log("no landmarks/waypoints - add vectors.landmarks (crater centres, rover sites) to get chips")
    (out / "alignment_report.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--layers", default="data/layers.json")
    p.add_argument("--out", default="out")
    p.add_argument("--tolerance-cells", type=float, default=1.5)
    a = p.parse_args(argv)
    rep = run(a.layers, a.out, a.tolerance_cells)
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
