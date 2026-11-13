"""Run the whole Person-2 pipeline.

    python -m hazards.run --layers data/layers.json --out out/
    python -m hazards.run --layers data/layers.json --tracks data/curiosity_tracks.geojson

Reads only layers.json (+ the files it lists) and config/hazards.yaml.
Optional layers are skipped with a warning if missing: thermal_inertia, minerals, rocks.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

from . import CLASS_NAMES, REASON_BITS, GREEN, YELLOW, RED, UNKNOWN
from .classify import classify
from .export import export_all
from .io import Layers, write_tif
from .terrain import fill_gaps, hillshade, local_relief_m, rock_layers, roughness_m, slope_deg
from .validate import check_tracks

ROOT = Path(__file__).resolve().parent.parent


def run(layers_path, out_dir, config_path=None, tracks_path=None, quiet=False) -> dict:
    t0 = time.time()
    log = (lambda *a: None) if quiet else (lambda *a: print(*a, file=sys.stderr))
    cfg = yaml.safe_load(Path(config_path or ROOT / "config" / "hazards.yaml").read_text())
    L = Layers(layers_path)
    g = L.grid
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log(f"Grid {g.shape[1]}x{g.shape[0]} cells at {g.cell_m} m  ({g.width_m} x {g.height_m} m)")

    dtm_raw = L.raster("dtm")
    dtm, gap = fill_gaps(dtm_raw)
    log(f"DTM: {np.nanmin(dtm_raw):.1f} .. {np.nanmax(dtm_raw):.1f} m, coverage gaps {gap.mean():.1%}")

    slope = slope_deg(dtm, g.cell_m)
    rough = roughness_m(dtm, g.cell_m, cfg["roughness_m"]["window_m"])
    relief = local_relief_m(dtm, g.cell_m, cfg["cliff"]["window_m"])
    d = cfg["display"]
    shade = hillshade(dtm, g.cell_m, d["hillshade_azimuth_deg"], d["hillshade_altitude_deg"])

    thermal = L.raster("thermal_inertia") if L.has("thermal_inertia") else None
    minerals = L.raster("minerals") if L.has("minerals") else None
    density = large = None
    if L.has("rocks"):
        density, large = rock_layers(L.vector("rocks"), g, cfg["rocks"])
    for name, val in (("thermal_inertia", thermal), ("minerals", minerals), ("rocks", density)):
        if val is None:
            log(f"WARNING: layer '{name}' missing - hazards computed without it")

    classes, reasons = classify(slope=slope, rough=rough, relief=relief, gap=gap, cfg=cfg,
                                cell_m=g.cell_m, thermal=thermal, rock_density=density, large_rocks=large)

    # --- rasters for Person 3 (cost map, routing) -------------------------------
    meta = {"grid": {"width_m": g.width_m, "height_m": g.height_m, "cell_m": g.cell_m},
            "convention": "row 0 = north, col 0 = west, [east,north] m from SW corner"}
    write_tif(out / "hazard.tif", classes, {**meta, "classes": CLASS_NAMES})
    write_tif(out / "reasons.tif", reasons, {**meta, "bits": REASON_BITS})
    write_tif(out / "slope.tif", np.where(gap, np.nan, slope).astype(np.float32), {**meta, "units": "deg"})
    write_tif(out / "roughness.tif", np.where(gap, np.nan, rough).astype(np.float32), {**meta, "units": "m"})

    # --- PNGs + manifest for Person 4 (front end) ------------------------------
    png_layers = export_all(out, g, shade=shade, slope=slope, classes=classes, gap=gap, cfg=cfg,
                            thermal=thermal, minerals=minerals)

    stats = {CLASS_NAMES[k]: float(np.mean(classes == k)) for k in (GREEN, YELLOW, RED, UNKNOWN)}
    reason_share = {k: float(np.mean((reasons & v) > 0)) for k, v in REASON_BITS.items()}

    # --- rover-track check ------------------------------------------------------
    tracks = None
    if tracks_path:
        tracks = json.loads(Path(tracks_path).read_text())
    elif L.has("rover_tracks"):
        tracks = L.vector("rover_tracks")
    track_report = None
    if tracks is not None:
        track_report = check_tracks(tracks, g, classes, reasons, slope, cfg["validation"]["max_red_fraction"])
        (out / "track_check.json").write_text(json.dumps(track_report, indent=2))
        _track_overlay(out, classes, tracks, g)
    else:
        log("No rover tracks given - skipping track check (add a 'rover_tracks' layer or --tracks)")

    manifest = {
        "generated_by": "hazards.run (Person 2)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "site": L.meta["site"],
        "inputs": {lid: L.by_id[lid].get("source", L.by_id[lid]["file"]) for lid in L.by_id if L.has(lid)},
        "config": cfg,
        "leaflet_bounds": g.leaflet_bounds,
        "png_layers": png_layers,
        "rasters": {
            "hazard.tif": "uint8 classes: " + ", ".join(f"{k}={v}" for k, v in CLASS_NAMES.items()),
            "reasons.tif": "uint16 bitmask, see reason_bits",
            "slope.tif": "float32 degrees, NaN = no data",
            "roughness.tif": "float32 metres, NaN = no data",
        },
        "class_names": CLASS_NAMES,
        "reason_bits": REASON_BITS,
        "area_share": stats,
        "reason_share": reason_share,
        "track_check": None if track_report is None else {"passed": track_report["passed"], "file": "track_check.json"},
    }
    (out / "hazards_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

    log("Area: " + ", ".join(f"{k} {v:.1%}" for k, v in stats.items()))
    if track_report:
        for t in track_report["tracks"]:
            log(f"Track '{t['name']}': {t['length_m']:.0f} m, red {t['red_fraction_of_known']:.1%} "
                f"-> {'PASS' if t['passed'] else 'FAIL'}" + (f"  reasons {t['red_reasons']}" if t['red_reasons'] else ""))
    log(f"Done in {time.time() - t0:.1f} s -> {out}")
    return manifest


def _track_overlay(out, classes, tracks, g):
    """hazards + tracks preview image, for eyeballing the check."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    from .validate import _lines

    img = np.asarray(Image.open(out / "shaded_relief.png"))
    hz = np.asarray(Image.open(out / "hazards.png"))
    ext = [0, g.width_m, 0, g.height_m]
    fig, ax = plt.subplots(figsize=(8, 8 * g.height_m / g.width_m), dpi=120)
    ax.imshow(img, extent=ext)
    ax.imshow(hz, extent=ext, alpha=0.55)
    colours = ["#1f4e9c", "#7a1fa2", "#000000", "#00838f"]
    for i, (name, c) in enumerate(_lines(tracks)):
        ax.plot(c[:, 0], c[:, 1], lw=3, color="white")
        ax.plot(c[:, 0], c[:, 1], lw=1.5, color=colours[i % len(colours)], label=name)
    ax.set_xlabel("east (m)")
    ax.set_ylabel("north (m)")
    ax.set_title("Rover tracks over hazard classes")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "track_check.png")
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--layers", default="data/layers.json")
    p.add_argument("--out", default="out")
    p.add_argument("--config", default=None, help="default: config/hazards.yaml")
    p.add_argument("--tracks", default=None, help="GeoJSON of real rover tracks in [east,north] m")
    a = p.parse_args(argv)
    m = run(a.layers, a.out, a.config, a.tracks)
    tc = m["track_check"]
    return 1 if tc and tc["passed"] is False else 0


if __name__ == "__main__":
    sys.exit(main())
