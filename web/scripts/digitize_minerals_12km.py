"""Traces the mineral cells from the team research note's map into a map overlay.

Input:  Jezero_minerals_12km_research.pdf ("Minerals in a 12 km x 12 km square around our
        Jezero site", Almost Astral, 2026-11-14). Page 1 holds the map as one embedded image.
Output: web/src/assets/minerals_12km.png, 600 x 600 cells of 20 m (the note's own grid),
        north up, covering the 12 km square centred on our site (18.46 N, 77.40 E).
        Each cell is one of the note's five colours, or transparent.

How: the note's map is drawn with flat colours (no blending), so every mineral pixel has the
legend colour exactly. The axes run from 0 to 12 km between the black frame lines (found at
columns 232 and 1314 and rows 45 and 1127 of the 1860 x 1260 image). Each 20 m cell takes the
colour that covers most of its footprint. Then, following the note:
  - hydrated (light grey) needs patches of at least 4 cells (1,600 m2): the note's minimum patch,
    and it keeps the grey hillshade underneath from being read as hydrated cells;
  - olivine north of 10.5 km is dropped: the note says the faint green dashes near the top edge
    are left over from a bad scan line and are not olivine.
Labels and symbols drawn on top of the map hide a few cells, so traced areas come out a little
smaller than the note's table. This is a trace of a picture, not the CRISM data: positions are
good to about one cell (20 m) plus the picture's own resolution (about 11 m per pixel).

Run:  python web/scripts/digitize_minerals_12km.py path/to/Jezero_minerals_12km_research.pdf
Needs numpy and Pillow only.
"""
import base64
import re
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

CLASSES = [  # name, legend colour (exact in the note's figure)
    ("augite", (224, 85, 154)),
    ("olivine", (120, 200, 70)),
    ("hydrated", (216, 216, 216)),
    ("clay", (70, 170, 230)),
    ("carbonate", (235, 140, 55)),
]
FRAME = {"x0": 232, "x1": 1314, "y_top": 45, "y_bottom": 1127}  # pixel rows/columns of 0 and 12 km
KM = 12.0
CELL_M = 20
N = int(KM * 1000 / CELL_M)  # 600
OLIVINE_MAX_NORTH_KM = 10.5
MIN_PATCH_CELLS = 4

OUT = Path(__file__).resolve().parents[1] / "src" / "assets" / "minerals_12km.png"


def map_image(pdf_path):
    """The note's map: the one RGB image XObject in the PDF (ASCII85 + Flate)."""
    data = Path(pdf_path).read_bytes()
    for m in re.finditer(rb"(\d+) 0 obj(.*?)endobj", data, re.S):
        head, _, rest = m.group(2).partition(b"stream")
        if b"/Subtype /Image" not in head or b"DeviceRGB" not in head:
            continue
        w = int(re.search(rb"/Width (\d+)", head).group(1))
        h = int(re.search(rb"/Height (\d+)", head).group(1))
        raw = rest.lstrip(b"\r\n")
        if b"ASCII85Decode" in head:
            raw = base64.a85decode(raw.split(b"~>")[0].strip(), adobe=False)
        px = zlib.decompress(raw)
        return np.frombuffer(px[: w * h * 3], dtype=np.uint8).reshape(h, w, 3)
    raise SystemExit("No RGB map image found in the PDF.")


def components(mask):
    """Labels 8-connected regions of a boolean grid. Returns (labels, sizes)."""
    labels = np.zeros(mask.shape, dtype=np.int32)
    sizes = [0]
    h, w = mask.shape
    for sy, sx in zip(*np.nonzero(mask)):
        if labels[sy, sx]:
            continue
        k = len(sizes)
        labels[sy, sx] = k
        stack = [(sy, sx)]
        n = 0
        while stack:
            y, x = stack.pop()
            n += 1
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not labels[yy, xx]:
                        labels[yy, xx] = k
                        stack.append((yy, xx))
        sizes.append(n)
    return labels, np.array(sizes)


def main(pdf_path):
    img = map_image(pdf_path).astype(int)
    plot = img[FRAME["y_top"] + 1 : FRAME["y_bottom"], FRAME["x0"] + 1 : FRAME["x1"]]
    ph, pw = plot.shape[:2]

    # Which class each picture pixel shows (-1 for none).
    cls = np.full((ph, pw), -1, dtype=np.int8)
    for k, (_, c) in enumerate(CLASSES):
        cls[(plot == np.array(c)).all(2)] = k

    # Majority class over each 20 m cell's footprint (row 0 = north).
    grid = np.full((N, N), -1, dtype=np.int8)
    ys = np.linspace(0, ph, N + 1)
    xs = np.linspace(0, pw, N + 1)
    for r in range(N):
        y0, y1 = int(ys[r]), max(int(ys[r + 1]), int(ys[r]) + 1)
        for c in range(N):
            x0, x1 = int(xs[c]), max(int(xs[c + 1]), int(xs[c]) + 1)
            block = cls[y0:y1, x0:x1].ravel()
            hit = block[block >= 0]
            if hit.size * 2 >= block.size:
                grid[r, c] = np.bincount(hit, minlength=len(CLASSES)).argmax()

    names = [n for n, _ in CLASSES]
    oli = names.index("olivine")
    north_rows = int((KM - OLIVINE_MAX_NORTH_KM) * 1000 / CELL_M)
    grid[:north_rows][grid[:north_rows] == oli] = -1

    hyd = names.index("hydrated")
    labels, sizes = components(grid == hyd)
    small = np.isin(labels, np.nonzero(sizes < MIN_PATCH_CELLS)[0]) & (labels > 0)
    grid[small] = -1

    rgba = np.zeros((N, N, 4), dtype=np.uint8)
    for k, (_, c) in enumerate(CLASSES):
        rgba[grid == k] = (*c, 255)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(OUT, optimize=True)

    cell_km2 = (CELL_M / 1000) ** 2
    print(f"Wrote {OUT} ({N} x {N} cells of {CELL_M} m)")
    for k, name in enumerate(names):
        print(f"  {name:10s} {(grid == k).sum() * cell_km2:.2f} km2")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
