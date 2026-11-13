"""Build map_config.json (the shared map contract) and the base-map viewer.

    python -m basemap.build --layers data/layers.json --hazards out --out out

Writes to --out:
  map_config.json      projection, origin, bounds, layer list - the file teammates read
  imagery.png          base imagery on the site grid (real orthoimage, or a placeholder)
  index.html + js/css  viewer that loads map_config.json (serve the folder over http)
  martial_map.html     the same viewer as ONE file with everything inlined (just open it)
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import shutil
from pathlib import Path

import numpy as np
from matplotlib import colormaps
from matplotlib.colors import to_hex
from PIL import Image

from hazards.io import Layers, read_raster

WEB = Path(__file__).resolve().parent / "web"
TITLE = "Interplanetary Survival Guide: Martial Map"


def _ramp_css(cmap: str, n=7):
    return [to_hex(colormaps[cmap](i / (n - 1))) for i in range(n)]


def imagery_png(L: Layers, hz_dir: Path, out: Path) -> dict:
    """Real orthoimage if layers.json has one, else the shaded relief as a placeholder."""
    if L.has("ortho"):
        arr = read_raster(L.file("ortho")).astype(float)
        if arr.shape[:2] != L.grid.shape:
            raise ValueError(f"ortho is {arr.shape[:2]}, grid is {L.grid.shape}; run basemap.prepare_imagery first")
        valid = np.isfinite(arr) & (arr > 0)
        lo, hi = np.percentile(arr[valid], [0.5, 99.5]) if valid.any() else (0, 1)
        g = np.clip((np.nan_to_num(arr) - lo) / max(hi - lo, 1e-9), 0, 1)
        rgba = np.dstack([g, g, g, valid.astype(float)])
        Image.fromarray((rgba * 255).astype(np.uint8), "RGBA").save(out / "imagery.png", optimize=True)
        return {"title": "Orbital imagery", "source": L.by_id["ortho"].get("source", "ortho layer"), "placeholder": False}
    shutil.copyfile(hz_dir / "shaded_relief.png", out / "imagery.png")
    return {"title": "Placeholder imagery (shaded relief from terrain)",
            "source": "Computed from the terrain model until real orbital imagery is loaded", "placeholder": True}


def build_config(layers_json: Path, hz_dir: Path, out: Path, title=TITLE) -> dict:
    L = Layers(layers_json)
    site = dict(L.meta["site"])
    manifest = json.loads((hz_dir / "hazards_manifest.json").read_text())
    pngs = {p["id"]: p for p in manifest["png_layers"]}
    im = imagery_png(L, hz_dir, out)

    def img(id_, title_, file, visible, opacity, legend=None, units=None, source=None):
        return {"id": id_, "kind": "image", "title": title_, "file": file, "visible": visible,
                "opacity": opacity, "legend": legend, "units": units, "source": source}

    layers = [img("imagery", im["title"], "imagery.png", True, 1.0, source=im["source"])]
    if not im["placeholder"]:
        layers.append(img("shaded_relief", "Shaded relief", "shaded_relief.png", False, 0.5, source=pngs["shaded_relief"]["source"]))
    for id_, vis, op in (("slope", False, 0.8), ("thermal_inertia", False, 0.7), ("minerals", False, 0.65), ("hazards", True, 0.45)):
        if id_ not in pngs:
            continue
        p = pngs[id_]
        lg = dict(p["legend"]) if p["legend"] else None
        if lg and lg.get("type") == "ramp":
            lg["css_stops"] = _ramp_css(lg["cmap"])
        layers.append(img(id_, p["title"], p["file"], vis, op, lg, p["units"], p["source"]))
    for f in ("shaded_relief.png", "slope.png", "thermal.png", "minerals.png", "hazards.png"):
        if (hz_dir / f).exists() and hz_dir.resolve() != out.resolve():
            shutil.copyfile(hz_dir / f, out / f)

    layers.append({"id": "grid", "kind": "grid", "title": "Coordinate grid (m)", "visible": False})
    if L.has("rover_tracks"):
        layers.append({"id": "rover_tracks", "kind": "lines", "title": "Rover tracks", "visible": True,
                       "features": L.vector("rover_tracks")["features"], "source": L.by_id["rover_tracks"].get("source")})
    if L.has("landmarks"):
        layers.append({"id": "landmarks", "kind": "landmarks", "title": "Landmarks", "visible": True,
                       "features": L.vector("landmarks")["features"], "source": L.by_id["landmarks"].get("source")})

    sources = " ".join(str(l.get("source", "")) for l in L.meta["layers"])
    simulated = bool(site.get("simulated")) or "SIMULATED" in sources.upper() or im["placeholder"]
    config = {
        "title": title,
        "simulated": simulated,
        "simulated_note": ("SIMULATED DATA — stand-in terrain, imagery and layers for testing. "
                           "Not real Mars measurements; replaced when the NASA dataset arrives.") if simulated else None,
        "site": {k: site[k] for k in ("name", "width_m", "height_m", "cell_m", "origin_latlon") if k in site}
                | {"origin_source_xy": site.get("origin_source_xy")},
        "projection": {
            "map_coordinates": "[east, north] metres from the SW corner of the site grid",
            "raster_rows": "row 0 = north edge, col 0 = west edge",
            "source_crs": site.get("source_crs"),
            "origin_source_xy": site.get("origin_source_xy"),
            "leaflet_crs_simple_bounds": [[0, 0], [site["height_m"], site["width_m"]]],
        },
        "max_px_per_m": 24,
        "layers": layers,
    }
    (out / "map_config.json").write_text(json.dumps(config, indent=2))
    return config


def _data_uri(path: Path, max_px=2048) -> str:
    im = Image.open(path)
    if max(im.size) > max_px:
        im.thumbnail((max_px, max_px), Image.Resampling.NEAREST if "hazard" in path.name or "minerals" in path.name
                     else Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build_viewer(config: dict, out: Path):
    for f in ("index.html", "viewer.css", "coords.js", "basemap.js", "app.js"):
        shutil.copyfile(WEB / f, out / f)
    # dev viewer: files reference each other; needs `python -m http.server` in out/
    cfg_files = json.loads(json.dumps(config))
    for l in cfg_files["layers"]:
        if l["kind"] == "image":
            l["href"] = l["file"]
    (out / "map_config.json").write_text(json.dumps(cfg_files, indent=2))

    # single file: inline everything
    cfg_inline = json.loads(json.dumps(config))
    for l in cfg_inline["layers"]:
        if l["kind"] == "image":
            l["href"] = _data_uri(out / l["file"])
    html = (WEB / "index.html").read_text()
    css = (WEB / "viewer.css").read_text()
    js = "\n".join((WEB / f).read_text() for f in ("coords.js", "basemap.js", "app.js"))
    html = re.sub(r"<!--CSS-->.*?<!--/CSS-->", lambda m: f"<style>\n{css}\n</style>", html, flags=re.S)
    cfg_js = json.dumps(cfg_inline).replace("</", "<\\/")
    html = re.sub(r"<!--CONFIG-->.*?<!--/CONFIG-->", lambda m: f"<script>window.MM_CONFIG = {cfg_js};</script>", html, flags=re.S)
    html = re.sub(r"<!--JS-->.*?<!--/JS-->", lambda m: f"<script>\n{js.replace('</script', '<\\/script')}\n</script>", html, flags=re.S)
    (out / "martial_map.html").write_text(html)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--layers", default="data/layers.json")
    p.add_argument("--hazards", default="out", help="folder written by hazards.run")
    p.add_argument("--out", default="out")
    p.add_argument("--title", default=TITLE)
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = build_config(Path(a.layers), Path(a.hazards), out, a.title)
    build_viewer(cfg, out)
    size = (out / "martial_map.html").stat().st_size / 1e6
    print(f"map_config.json + viewer written to {out}/  (martial_map.html {size:.1f} MB)")


if __name__ == "__main__":
    main()
