"""Build map_config.json (the shared map contract) and the base-map viewer from the
team's layers.json.

    python -m basemap.build --layers data/layers.json --hazards out --out out

Display layers come from layers.json "layers" in their order (default -> visible).
Each PNG is taken from --hazards (files Person 2 generates: relief, slope, hazard,
coverage) or else from next to layers.json (hirise, thermal, minerals, shelter_time...).
Missing files are skipped with a warning. Vectors: route, rover_tracks (lines),
waypoints and landmarks (markers).

Writes to --out:
  map_config.json      site, projection, origin, bounds, layer list - what teammates read
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
import sys
from pathlib import Path

from matplotlib import colormaps
from matplotlib.colors import to_hex
from PIL import Image

from hazards.io import Layers

WEB = Path(__file__).resolve().parent / "web"
TITLE = "Interplanetary Survival Guide: Martial Map"
GENERATED = {"relief", "slope", "hazard", "coverage"}


def _ramp_css(cmap: str, n=7):
    return [to_hex(colormaps[cmap](i / (n - 1))) for i in range(n)]


def build_config(layers_json: Path, hz_dir: Path, out: Path, title=TITLE, warn=print) -> dict:
    L = Layers(layers_json)
    g = L.grid
    manifest_p = hz_dir / "hazards_manifest.json"
    generated = {p["id"]: p for p in json.loads(manifest_p.read_text())["png_layers"]} if manifest_p.exists() else {}

    team_layers = list(L.meta.get("layers", []))
    if not any(l["id"] == "coverage" for l in team_layers) and "coverage" in generated:
        at = next((i + 1 for i, l in enumerate(team_layers) if l["id"] == "hazard"), len(team_layers))
        team_layers.insert(at, {"id": "coverage", "title": "Unknown terrain coverage", "file": "coverage.png",
                                "default": True, "opacity": 0.9, "source": generated["coverage"]["source"]})

    layers = []
    for tl in team_layers:
        src = None
        for folder in ((hz_dir, L.root) if tl["id"] in GENERATED else (L.root, hz_dir)):
            if (folder / tl["file"]).exists():
                src = folder / tl["file"]
                break
        if src is None:
            warn(f"  skip layer '{tl['id']}': {tl['file']} not found")
            continue
        if src.resolve() != (out / tl["file"]).resolve():
            shutil.copyfile(src, out / tl["file"])
        gen = generated.get(tl["id"], {})
        legend = None
        if tl.get("legend"):  # team legend: [{label, color, ...}]
            legend = {"type": "classes", "items": [{"name": i["label"], "color": i["color"]} for i in tl["legend"]]}
        elif gen.get("legend"):
            legend = dict(gen["legend"])
            if legend["type"] == "ramp":
                legend["css_stops"] = _ramp_css(legend["cmap"])
        if tl["id"] == "hazard":
            legend = {"type": "classes", "transparent_as": "Go",
                      "items": [{"name": "Go (clear)", "color": "transparent"},
                                {"name": "Caution", "color": "#f0be28"}, {"name": "No-go", "color": "#dc3232"}]}
        source = tl.get("source", "")
        if tl["id"] in GENERATED and gen:
            source = gen["source"] + (" — on SIMULATED terrain" if L.simulated else "")
        layers.append({"id": tl["id"], "kind": "image", "title": tl.get("title", tl["id"]), "file": tl["file"],
                       "visible": bool(tl.get("default")), "opacity": tl.get("opacity", 1.0),
                       "legend": legend, "units": gen.get("units"), "source": source, "note": tl.get("note")})

    layers.append({"id": "grid", "kind": "grid", "title": "Coordinate grid (m)", "visible": False})
    for name, kind, vtitle, vis in (("rover_tracks", "lines", "Rover tracks", True), ("route", "lines", "Planned route", True),
                                   ("waypoints", "landmarks", "Science stops", True), ("landmarks", "landmarks", "Landmarks", True)):
        if L.has_vector(name):
            layers.append({"id": name, "kind": kind, "title": vtitle, "visible": vis,
                           "features": [f for f in L.vector(name)["features"]
                                        if (f.get("geometry") or {}).get("type") in
                                        (("LineString", "MultiLineString") if kind == "lines" else ("Point",))],
                           "source": L.vectors_map[name]})
            for f in layers[-1]["features"]:
                f.setdefault("properties", {})
                f["properties"].setdefault("name", f["properties"].get("title") or f["properties"].get("id") or vtitle)

    config = {
        "title": title,
        "simulated": L.simulated,
        "simulated_note": ("SIMULATED DATA — some layers are stand-ins (marked FAKE). "
                           "Not real Mars measurements until the NASA dataset replaces them.") if L.simulated else None,
        "site": {"name": L.site.get("name", "Site"), "width_m": g.width_m, "height_m": g.height_m, "cell_m": g.cell_m,
                 "origin_latlon": L.origin_latlon, "origin_source_xy": L.site.get("origin_source_xy"),
                 "center_latlon": [L.site.get("center_lat"), L.site.get("center_lon_east")]},
        "projection": {
            "map_coordinates": "[east, north] metres from the SW corner of the site grid",
            "raster_rows": "row 0 = north edge, col 0 = west edge",
            "source_crs": L.site.get("source_crs"),
            "origin_source_xy": L.site.get("origin_source_xy"),
            "leaflet_crs_simple_bounds": g.leaflet_bounds,
        },
        "max_px_per_m": 24,
        "layers": layers,
    }
    return config


def _data_uri(path: Path, max_px=2048) -> str:
    im = Image.open(path)
    if max(im.size) > max_px:
        im.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build_viewer(config: dict, out: Path):
    for f in ("index.html", "viewer.css", "coords.js", "basemap.js", "app.js"):
        shutil.copyfile(WEB / f, out / f)
    cfg_files = json.loads(json.dumps(config))
    for l in cfg_files["layers"]:
        if l["kind"] == "image":
            l["href"] = l["file"]
    (out / "map_config.json").write_text(json.dumps(cfg_files, indent=2))

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
    html = re.sub(r"<!--JS-->.*?<!--/JS-->", lambda m: f"<script>\n{js.replace('</script', '<' + chr(92) + '/script')}\n</script>", html, flags=re.S)
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
    cfg = build_config(Path(a.layers), Path(a.hazards), out, a.title, warn=lambda m: print(m, file=sys.stderr))
    build_viewer(cfg, out)
    size = (out / "martial_map.html").stat().st_size / 1e6
    print(f"map_config.json + viewer written to {out}/  (martial_map.html {size:.1f} MB)")


if __name__ == "__main__":
    main()
