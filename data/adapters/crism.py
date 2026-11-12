"""CRISM mineral maps -> out/minerals.png.

CRISM "summary parameters" are numbers per pixel that go up when a mineral's
absorption feature is present (e.g. SINDEX2 for sulfates). For each mineral
listed in data/site.json we colour the cells where its parameter is above a
threshold. Later entries are drawn on top of earlier ones.

Use map-projected products (MTRDR); the plain targeted products have no map
projection and cannot be aligned. To see which bands a file has:

    python data/inspect_raw.py data/raw/crism/yourfile_su.img

Run alone with:  python data/adapters/crism.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402

import grid  # noqa: E402


def band_number(path, entry):
    """Find the band to read: 'band' (1-based) wins, else match 'band_name'."""
    if entry.get("band"):
        return int(entry["band"])
    import rasterio

    with rasterio.open(path) as src:
        names = [(d or "").upper() for d in src.descriptions]
    want = entry["band_name"].upper()
    for i, name in enumerate(names, start=1):
        if want == name or want in name.split():
            return i
    raise ValueError(f"No band called {entry['band_name']} in {path.name}. Run "
                     f"python data/inspect_raw.py on it and set \"band\" to a number instead.")


def run(site):
    cfg = site.get("crism", {})
    minerals = cfg.get("minerals") or []
    if not minerals:
        return []
    w, h, _ = grid.grid_size(site)
    img = np.zeros((h, w, 4))
    legend, lines, files = [], [], set()

    for entry in minerals:
        path = grid.raw_file(entry["file"])
        band = band_number(path, entry)
        arr, info = grid.warp_to_grid(path, site, band=band, resampling="bilinear")
        hit = np.nan_to_num(arr, nan=-np.inf) > entry["threshold"]
        img[hit] = [*entry["color"], 170]
        legend.append({"label": entry["label"], "color": "#%02x%02x%02x" % tuple(entry["color"]),
                       "parameter": entry.get("band_name", f"band {band}"), "threshold": entry["threshold"]})
        files.add(path.name)
        lines.append(f"{entry['label']}: {hit.mean():.1%} of the site above {entry['threshold']} "
                     f"(file covers {info['coverage']:.0%})")

    grid.save_png("minerals.png", img)
    grid.update_layers_json(layer={
        "id": "minerals", "title": "Minerals", "file": "minerals.png",
        "source": f"{cfg.get('label', 'CRISM (MRO)')}: {', '.join(sorted(files))}",
        "legend": legend,
        "note": "Coloured where a CRISM summary parameter passes our threshold. Thresholds were tuned by eye.",
    })
    return ["minerals.png written"] + lines


if __name__ == "__main__":
    for line in run(grid.load_site()) or ["nothing to do: add entries to crism.minerals in data/site.json"]:
        print(line)
