"""Convert the official challenge dataset into the format in CONTRACT.md.

Person 1: finish this on Saturday, once the official data is available.

Step 1 works now: put the official files in data/raw/official/ and run

    python data/adapters/official.py --inventory

It lists every file: rasters with size, pixel size, projection and whether the
site centre is inside; tables with their columns. Use that to decide which
official file replaces which layer.

Steps 2 to 4 (Saturday):
2. For each raster, call grid.warp_to_grid(path, site) to clip and resample it
   onto the site grid (it handles projection, cropping and resolution).
3. Write the results with the same file names as the other adapters:
   grid.save_tif("dem.tif", ...), grid.save_png("thermal.png", ...), and for
   tables tables.write_csv(...) with the contract headers.
4. Call grid.update_layers_json(...) with a real `source` for every layer.

The adapters in this folder (hirise.py, themis.py, crism.py, rems.py, rad.py)
are working examples of steps 2 to 4. Often the quickest route is to point
data/site.json at the official files and run python data/build_real.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grid  # noqa: E402

OFFICIAL = grid.RAW / "official"
RASTER_EXT = {".tif", ".tiff", ".img", ".jp2", ".vrt", ".cub"}
TABLE_EXT = {".csv", ".tab", ".txt"}


def inventory():
    if not OFFICIAL.is_dir():
        sys.exit(f"Put the official files in {OFFICIAL} first.")
    files = sorted(p for p in OFFICIAL.rglob("*") if p.is_file())
    print(f"{len(files)} file(s) in {OFFICIAL}\n")
    for p in files:
        print(f"--- {p.relative_to(OFFICIAL)} ({p.stat().st_size / 1e6:.1f} MB)")
        ext = p.suffix.lower()
        try:
            if ext in RASTER_EXT:
                import inspect_raw
                inspect_raw.main(str(p))
            elif ext in TABLE_EXT:
                import tables
                names, rows = tables.read_rows(p)
                print(f"  table: {len(rows)} rows; columns: {', '.join(names[:20])}")
            else:
                print("  (not a raster or table: open it by hand)")
        except Exception as e:
            print(f"  could not read it automatically: {e}")
        print()


def main():
    if "--inventory" in sys.argv:
        inventory()
        return
    raise NotImplementedError("TODO (Person 1, Saturday): convert the official data into data/out/. "
                              "Start with: python data/adapters/official.py --inventory")


if __name__ == "__main__":
    main()
