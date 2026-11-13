"""HiRISE terrain model -> out/dem.tif, and HiRISE image -> out/hirise.png.

Settings: the "hirise" block in data/site.json.
Run alone with:  python data/adapters/hirise.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402

import grid  # noqa: E402


def run(site):
    cfg = site.get("hirise", {})
    done = []

    dtm_path = grid.raw_file(cfg.get("dtm"))
    if dtm_path:
        dem, info = grid.warp_to_grid(dtm_path, site, resampling="bilinear")
        dem = grid.require_full_coverage(dem, "HiRISE terrain model")
        grid.save_tif("dem.tif", dem, "float32", site)
        grid.update_layers_json(extra={"dem.tif": f"{cfg.get('label', 'HiRISE (MRO)')}: {dtm_path.name}"})
        relief = np.ptp(dem)
        done.append(f"dem.tif from {dtm_path.name} (height range {relief:.0f} m, "
                    f"native {info['native_resolution_m'] or '?'} m/px)")

    img_path = grid.raw_file(cfg.get("image"))
    if img_path:
        img, info = grid.warp_to_grid(img_path, site, resampling="average")
        grey = 255 * grid.stretch(img, 0.5, 99.5)
        nan = np.isnan(img)
        rgba = np.dstack([grey, grey, grey, np.where(nan, 0, 255)])
        grid.save_png("hirise.png", rgba)
        grid.update_layers_json(
            layer={
                "id": "hirise", "title": "HiRISE image", "file": "hirise.png",
                "source": f"{cfg.get('label', 'HiRISE (MRO)')}: {img_path.name}",
                "default": False, "opacity": 1.0,
                "native_resolution_m": info["native_resolution_m"],
            },
            insert_after="relief",
        )
        done.append(f"hirise.png from {img_path.name} (covers {info['coverage']:.0%} of the site)")

    return done


if __name__ == "__main__":
    for line in run(grid.load_site()) or ["nothing to do: set hirise.dtm or hirise.image in data/site.json"]:
        print(line)
