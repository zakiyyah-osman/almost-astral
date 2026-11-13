"""Minutes back to the rover from every cell, and its PNG layer (DESIGN section 6).

The map is one MCP_Geometric run from the rover cell on the physical time rate (w = 0 is
the time rate itself, so it is searched directly and does not go through a profile route).
shelter_min = walk minutes + timeline.ingress_min. Blocked and unreachable cells have no
value (NaN) and are fully transparent in the PNG.
"""
from dataclasses import dataclass

import numpy as np
from PIL import Image

from cost import Cost
from search import Tree, build_tree

# Colour ramp, short to long way back (ColorBrewer YlOrRd, 5 classes), spread evenly over
# 0 .. shelter_map.colour_max_min. Longer times take the last colour.
RAMP_RGB = (
    (255, 255, 178),
    (254, 204, 92),
    (253, 141, 60),
    (240, 59, 32),
    (189, 0, 38),
)
CELL_ALPHA = 210                    # coloured cells let the relief show through a little
CONTOUR_RGBA = (30, 30, 30, 255)    # burned-in contour lines
TRANSPARENT = (0, 0, 0, 0)


@dataclass(frozen=True)
class Shelter:
    minutes: np.ndarray         # walk + ingress, NaN where blocked or unreachable
    walk_min: np.ndarray        # physical walk minutes only, same NaN cells
    ingress_min: float
    rover_cell: tuple
    tree: Tree                  # rover-rooted search on time_rate, for return paths


def shelter_time(cost: Cost, rover_cell, ingress_min, connectivity):
    """Fastest physical walk back to the rover from every cell, plus the ingress time."""
    tree = build_tree(cost, cost.time_rate, rover_cell, connectivity)
    walk = np.where(np.isfinite(tree.planning_cost) & ~cost.blocked, tree.planning_cost, np.nan)
    return Shelter(
        minutes=walk + ingress_min,
        walk_min=walk,
        ingress_min=float(ingress_min),
        rover_cell=(int(rover_cell[0]), int(rover_cell[1])),
        tree=tree,
    )


# ---- PNG ---------------------------------------------------------------------
def ramp_stops(colour_max_min):
    """The colour stops as [{'min': minutes, 'rgba': [r, g, b, a]}], evenly spaced."""
    n = len(RAMP_RGB) - 1
    return [
        {"min": float(colour_max_min) * i / n, "rgba": [*rgb, CELL_ALPHA]}
        for i, rgb in enumerate(RAMP_RGB)
    ]


def colour_at(minutes, colour_max_min):
    """Ramp colour (r, g, b, a) for an array of minutes, linear between stops, clipped at both ends."""
    t = np.clip(np.asarray(minutes, dtype=float) / colour_max_min, 0.0, 1.0) * (len(RAMP_RGB) - 1)
    lo = np.minimum(np.floor(t).astype(int), len(RAMP_RGB) - 2)
    frac = (t - lo)[..., None]
    ramp = np.array(RAMP_RGB, dtype=float)
    rgb = ramp[lo] * (1.0 - frac) + ramp[lo + 1] * frac
    alpha = np.full(rgb.shape[:-1] + (1,), CELL_ALPHA, dtype=float)
    return np.concatenate([rgb, alpha], axis=-1)


def contour_mask(minutes, interval_min):
    """Cells to burn: those whose contour band is higher than a neighbour's.

    Band = floor(minutes / interval). Each pair of horizontally or vertically adjacent cells
    that fall in different bands marks the one in the higher band, so a line is one cell wide.
    Cells without a value never start a line.
    """
    finite = np.isfinite(minutes)
    band = np.full(minutes.shape, np.nan)
    band[finite] = np.floor(minutes[finite] / interval_min)
    mask = np.zeros(minutes.shape, dtype=bool)
    for a, b in (
        (np.s_[:, :-1], np.s_[:, 1:]),      # a cell and its eastern neighbour
        (np.s_[:-1, :], np.s_[1:, :]),      # a cell and its southern neighbour
    ):
        both = finite[a] & finite[b]
        higher_a = both & (band[a] > band[b])
        higher_b = both & (band[b] > band[a])
        mask[a] |= higher_a
        mask[b] |= higher_b
    return mask


def render_png(minutes, colour_max_min, interval_min):
    """RGBA uint8 image, one pixel per cell, row 0 = north edge (the array's row order)."""
    finite = np.isfinite(minutes)
    img = np.zeros(minutes.shape + (4,), dtype=np.uint8)
    img[finite] = np.rint(colour_at(minutes[finite], colour_max_min)).astype(np.uint8)
    img[~finite] = TRANSPARENT
    img[contour_mask(minutes, interval_min)] = CONTOUR_RGBA
    return img


def write_png(path, minutes, colour_max_min, interval_min):
    Image.fromarray(render_png(minutes, colour_max_min, interval_min), mode="RGBA").save(path)


def legend(colour_max_min, interval_min, file="shelter_time.png"):
    """The plan.json shelter_map block: the web app cannot read minutes back out of a picture."""
    return {
        "file": file,
        "includes_ingress": True,
        "contour_interval_min": interval_min,
        "colour_max_min": colour_max_min,
        "contour_rgba": list(CONTOUR_RGBA),
        "stops": ramp_stops(colour_max_min),
    }
