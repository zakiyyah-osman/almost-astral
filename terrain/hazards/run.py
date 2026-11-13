"""Run the whole Person-2 pipeline.

    python -m hazards.run --layers data/layers.json --out out/
    python -m hazards.run --layers data/layers.json --tracks perseverance_tracks.geojson

Reads the team's layers.json, dem.tif and thermal_inertia.tif next to it, optional
vectors (rocks, rover_tracks, route) and config/hazards.yaml. Writes hazard.png /
hazard.tif in the agreed contract (0/1/2; red 220,50,50; yellow 240,190,40; green
transparent) plus coverage, slope, relief and diagnostics. To publish into the team
data folder, use --out <that folder> (it replaces the FAKE relief/slope/hazard PNGs).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

from . import REASON_BITS, GREEN, YELLOW, RED
from .classify import classify
from .export import contract_classes, export_all
from .io import DATA_FILES, Layers, write_tif
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
    log(f"Site: {L.site.get('name')}  grid {g.shape[1]}x{g.shape[0]} cells at {g.cell_m} m ({g.width_m:.0f} x {g.height_m:.0f} m)")

    dtm_raw = L.raster("dtm")
    dtm, gap = fill_gaps(dtm_raw)
    log(f"Terrain ({L.data_file('dtm').name}): {np.nanmin(dtm_raw):.1f} .. {np.nanmax(dtm_raw):.1f} m, no-data {gap.mean():.1%}")

    slope = slope_deg(dtm, g.cell_m)
    rough = roughness_m(dtm, g.cell_m, cfg["roughness_m"]["window_m"])
    relief = local_relief_m(dtm, g.cell_m, cfg["cliff"]["window_m"])
    d = cfg["display"]
    shade = hillshade(dtm, g.cell_m, d["hillshade_azimuth_deg"], d["hillshade_altitude_deg"])

    thermal = L.raster("thermal_inertia") if L.has("thermal_inertia") else None
    density = large = None
    if L.has_vector("rocks"):
        density, large = rock_layers(L.vector("rocks"), g, cfg["rocks"])
    if thermal is None:
        log("WARNING: thermal_inertia.tif missing - loose-sand rule skipped")
    if density is None:
        log("note: no 'rocks' vector in layers.json - rock rules skipped (slope and roughness still catch rough ground)")

    classes, reasons = classify(slope=slope, rough=rough, relief=relief, gap=gap, cfg=cfg,
                                cell_m=g.cell_m, thermal=thermal, rock_density=density, large_rocks=large)
    hz = contract_classes(classes)

    meta = {"grid": {"width": g.shape[1], "height": g.shape[0], "cell_m": g.cell_m},
            "convention": "row 0 = north, col 0 = west, [east,north] m from SW corner"}
    write_tif(out / "hazard.tif", hz, {**meta, "classes": {"0": "go", "1": "caution", "2": "no-go (incl. no terrain data)"}})
    write_tif(out / "coverage.tif", (~gap).astype(np.uint8), {**meta, "values": {"1": "terrain data", "0": "no data"}})
    write_tif(out / "reasons.tif", reasons, {**meta, "bits": REASON_BITS})
    write_tif(out / "slope.tif", np.where(gap, np.nan, slope).astype(np.float32), {**meta, "units": "deg"})
    write_tif(out / "roughness.tif", np.where(gap, np.nan, rough).astype(np.float32), {**meta, "units": "m"})
    png_layers = export_all(out, g, shade=shade, slope=slope, classes=classes, gap=gap, cfg=cfg)

    stats = {"Go": float(np.mean(classes == GREEN)), "Caution": float(np.mean(classes == YELLOW)),
             "No-go": float(np.mean(classes == RED)), "Unknown terrain coverage (no-go in hazard.tif)": float(gap.mean())}
    reason_share = {k: float(np.mean((reasons & v) > 0)) for k, v in REASON_BITS.items()}

    # ---- tracks and routes ------------------------------------------------------
    checks = []
    if tracks_path:
        checks.append(("tracks", json.loads(Path(tracks_path).read_text())))
    elif L.has_vector("rover_tracks"):
        checks.append(("tracks", L.vector("rover_tracks")))
    if L.has_vector("route"):
        checks.append(("route", L.vector("route")))
    track_report = None
    if checks:
        track_report = {"tracks": [], "passed": True}
        allf = {"type": "FeatureCollection", "features": []}
        for kind, fc in checks:
            feats = []
            for f in fc.get("features", []):
                f = dict(f)
                f["properties"] = {**(f.get("properties") or {}), "name": f"{kind}: " + str((f.get("properties") or {}).get("name", kind))}
                feats.append(f)
            rep = check_tracks({"features": feats}, g, classes, reasons, slope,
                               cfg["validation"]["max_red_fraction"], fail_on_unknown=(kind == "route"))
            for t in rep["tracks"]:
                t["kind"] = kind
            track_report["tracks"] += rep["tracks"]
            if rep["passed"] is False:
                track_report["passed"] = False
            allf["features"] += feats
        (out / "track_check.json").write_text(json.dumps(track_report, indent=2))
        _track_overlay(out, allf, g)
    else:
        log("No rover tracks or route - skipping track check (add vectors.rover_tracks or --tracks)")

    manifest = {
        "generated_by": "hazards.run (Person 2)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "site": L.site,
        "inputs": {k: L.source_of(k) for k in DATA_FILES if L.has(k)} | ({"rocks": L.vectors_map["rocks"]} if density is not None else {}),
        "config": cfg,
        "leaflet_bounds": g.leaflet_bounds,
        "png_layers": png_layers,
        "rasters": {
            "hazard.tif": "uint8 0 = go, 1 = caution, 2 = no-go (no terrain data is also 2)",
            "coverage.tif": "uint8 1 = terrain data, 0 = no data (shown as 'Unknown terrain coverage')",
            "reasons.tif": "uint16 bitmask, see reason_bits",
            "slope.tif": "float32 degrees, NaN = no data",
            "roughness.tif": "float32 metres, NaN = no data",
        },
        "reason_bits": REASON_BITS,
        "area_share": stats,
        "reason_share": reason_share,
        "track_check": None if track_report is None else {"passed": track_report["passed"], "file": "track_check.json"},
    }
    (out / "hazards_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

    log("Area: " + ", ".join(f"{k} {v:.1%}" for k, v in stats.items()))
    if track_report:
        for t in track_report["tracks"]:
            unk = t["fraction_by_class"]["Unknown terrain coverage"]
            log(f"{t['name']}: {t['length_m']:.0f} m, red {t['red_fraction_of_known']:.1%}"
                + (f", Unknown terrain coverage {unk:.1%}" if unk else "")
                + f" -> {t['status']}" + (f"  reasons {t['red_reasons']}" if t['red_reasons'] else ""))
    log(f"Done in {time.time() - t0:.1f} s -> {out}")
    return manifest


def _track_overlay(out, tracks, g):
    """hazards + tracks preview image, for eyeballing the check."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    from .validate import _lines

    img = np.asarray(Image.open(out / "relief.png"))
    hz = np.asarray(Image.open(out / "hazard.png"))
    cov = np.asarray(Image.open(out / "coverage.png"))
    ext = [0, g.width_m, 0, g.height_m]
    fig, ax = plt.subplots(figsize=(8, 8 * g.height_m / g.width_m), dpi=120)
    ax.imshow(img, extent=ext)
    ax.imshow(hz, extent=ext, alpha=0.6)
    ax.imshow(cov, extent=ext)
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
