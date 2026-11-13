"""THEMIS thermal map -> out/thermal.png (+ out/thermal_inertia.tif).

Thermal inertia says how fast the ground heats and cools. Loose sand and dust
have low values (they change temperature fast); bedrock has high values. That
is why Nahla's hazard map uses it for "soft ground".

Settings: the "themis" block in data/site.json.
Run alone with:  python data/adapters/themis.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402

import grid  # noqa: E402

# Dark blue (loose, low inertia) -> sand -> orange -> white (rocky, high inertia).
RAMP = [[40, 50, 120], [200, 170, 110], [230, 120, 40], [255, 245, 230]]


def run(site):
    cfg = site.get("themis", {})
    path = grid.raw_file(cfg.get("file"))
    if not path:
        return []
    kind = cfg.get("kind", "thermal_inertia")

    arr, info = grid.warp_to_grid(path, site, resampling="bilinear")
    nan = np.isnan(arr)

    if kind == "thermal_inertia":
        # Real values, so Nahla's thresholds (in the same SI units) apply directly.
        # NaN = no data, so "below threshold" tests never flag missing cells.
        grid.save_tif("thermal_inertia.tif", arr, "float32", site)
        v = np.clip((arr - 50) / (800 - 50), 0, 1)  # fixed scale so maps compare
        title, extra = "Thermal inertia", "Values in J m^-2 K^-1 s^-1/2 are in thermal_inertia.tif (NaN = no data)."
    else:
        v = grid.stretch(arr)
        title, extra = "Night-time temperature (THEMIS)", "Qualitative brightness only: warm at night = rocky."

    grid.save_png("thermal.png", grid.colour_ramp(v, RAMP, 150, nan))
    grid.update_layers_json(layer={
        "id": "thermal", "title": title, "file": "thermal.png",
        "source": f"{cfg.get('label', 'THEMIS (Mars Odyssey)')}: {path.name}",
        "native_resolution_m": info["native_resolution_m"],
        "note": f"{extra} Native pixels are much larger than the 5 m grid, so edges look soft.",
    })
    lines = [f"thermal.png from {path.name} ({kind}, covers {info['coverage']:.0%} of the site)"]
    if kind == "thermal_inertia":
        finite = arr[~nan]
        if finite.size:
            lines.append(f"thermal_inertia.tif: {finite.min():.0f} to {finite.max():.0f} SI units "
                         "(tell Nahla, her thresholds use these)")
    return lines


if __name__ == "__main__":
    for line in run(grid.load_site()) or ["nothing to do: set themis.file in data/site.json"]:
        print(line)
