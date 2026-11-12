"""Quick look at a downloaded raster before using it.

    python data/inspect_raw.py data/raw/hirise/somefile.IMG

Prints its size, pixel size, projection, bands, and whether the site centre
in data/site.json falls inside it. Use it on every new file, and on Saturday
for each file in the official dataset.
"""
import sys

import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform

import grid


def main(path):
    site = grid.load_site()
    with rasterio.open(path) as src:
        print(f"File:        {path}")
        print(f"Size:        {src.width} x {src.height} pixels, {src.count} band(s), {src.dtypes[0]}")
        print(f"Pixel size:  {src.res[0]:g} x {src.res[1]:g} (projection units)")
        print(f"No-data:     {src.nodata}")
        if src.crs is None:
            print("Projection:  NONE. This file is not map-projected and cannot be aligned.")
            return
        print(f"Projection:  {src.crs.to_proj4() or src.crs.to_wkt()[:200]}")
        for i, d in enumerate(src.descriptions, start=1):
            if d:
                print(f"  band {i}: {d}")
        try:
            xs, ys = transform(CRS.from_proj4(grid.site_proj4(site)), src.crs, [0], [0])
            row, col = src.index(xs[0], ys[0])
            inside = 0 <= row < src.height and 0 <= col < src.width
            print(f"Site centre: {'INSIDE' if inside else 'OUTSIDE'} this file (pixel row {row}, col {col})")
        except Exception as e:  # odd projections: report instead of crashing
            print(f"Site centre: could not check ({e})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python data/inspect_raw.py path/to/raster")
    main(sys.argv[1])
