"""Replace fake files in data/out/ with real data, one source at a time.

    python data/build_real.py                 # every source set in data/site.json
    python data/build_real.py themis rems     # only these sources
    python data/build_real.py --list          # show what is set and what is still fake

Sources left unset (null) in site.json are skipped, so their fake files stay
and nobody is blocked. Run `python data/make_fake.py` first if data/out/ is
empty, and `python data/validate.py` after.
"""
import json
import sys
import traceback

import grid
from adapters import crism, donki, hirise, rad, rems, themis

SOURCES = {"hirise": hirise, "themis": themis, "crism": crism, "rems": rems, "rad": rad, "donki": donki}


def is_set(site, name):
    cfg = site.get(name, {})
    return {
        "hirise": bool(cfg.get("dtm") or cfg.get("image")),
        "themis": bool(cfg.get("file")),
        "crism": bool(cfg.get("minerals")),
        "rems": bool(cfg.get("file")),
        "rad": bool(cfg.get("file")),
        "donki": bool(cfg.get("start")),
    }[name]


def check_grid(site):
    index = json.loads((grid.OUT / "layers.json").read_text(encoding="utf-8"))
    g = index["site"]["grid"]
    w, h, cell = grid.grid_size(site)
    if (g["width"], g["height"], float(g["cell_m"])) != (w, h, cell):
        sys.exit(f"data/site.json grid ({w}x{h}, {cell} m) differs from layers.json "
                 f"({g['width']}x{g['height']}, {g['cell_m']} m). Change both, and make_fake.py, together.")


def main():
    site = grid.load_site()
    if not (grid.OUT / "layers.json").is_file():
        sys.exit("data/out/layers.json is missing. Run: python data/make_fake.py")
    check_grid(site)

    if "--list" in sys.argv:
        for name in SOURCES:
            print(f"  {name:7} {'set' if is_set(site, name) else 'not set (fake data stays)'}")
        return 0

    chosen = [a for a in sys.argv[1:] if not a.startswith("--")] or list(SOURCES)
    unknown = [c for c in chosen if c not in SOURCES]
    if unknown:
        sys.exit(f"Unknown source(s): {', '.join(unknown)}. Choose from: {', '.join(SOURCES)}")

    grid.set_site_name(site)
    failed = 0
    for name in chosen:
        if not is_set(site, name):
            print(f"SKIP  {name}: not set in data/site.json, fake data stays")
            continue
        try:
            for line in SOURCES[name].run(site):
                print(f"OK    {name}: {line}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
            if "--debug" in sys.argv:
                traceback.print_exc()

    print("\nNext: python data/validate.py")
    if "hirise" in chosen and is_set(site, "hirise"):
        print("dem.tif changed: tell Nahla to rerun terrain/hazards.py (relief, slope, hazards).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
