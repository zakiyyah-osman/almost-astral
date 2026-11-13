"""Route search: a thin wrapper over skimage.graph.MCP_Geometric (DESIGN sections 4.3 and 4.5).

MCP_Geometric takes one cost per cell and charges a move of length L between neighbouring
cells a and b the amount L x (cost_a + cost_b) / 2, with L from `sampling` (metres here).
A negative cost is impassable. It is Dijkstra-based, so it finds the same optimum A* would.

A path is chosen on the planning rate. Time and risk are then summed along the chosen path
with the same edge formula, so planning cost = physical minutes + w x risk minutes holds
exactly, and only the physical minutes are ever reported as time.
"""
import math
from dataclasses import dataclass

import numpy as np
from skimage.graph import MCP_Geometric

from config import ConfigError
from cost import Cost

CONNECTIVITY = {4: False, 8: True}      # neighbours -> MCP fully_connected


class NoPath(ConfigError):
    """There is no route between two cells."""


@dataclass(frozen=True)
class PathSummary:
    """A path as cells, with its length and the time and risk summed along it."""

    cells: tuple            # ((row, col), ...) from start to end
    distance_m: float
    physical_min: float
    risk_min: float
    yellow_min: float
    steep_min: float
    near_red_min: float


def fully_connected(connectivity):
    try:
        return CONNECTIVITY[connectivity]
    except (KeyError, TypeError):
        raise ConfigError(
            f"search.connectivity must be 4 or 8, got {connectivity!r}"
        ) from None


def summarise(cost: Cost, cells):
    """Distance, physical minutes and risk minutes along a path, with MCP's edge formula."""
    cells = tuple((int(r), int(c)) for r, c in cells)
    if not cells:
        raise ValueError("a path needs at least one cell")
    rows = np.fromiter((r for r, _ in cells), dtype=int, count=len(cells))
    cols = np.fromiter((c for _, c in cells), dtype=int, count=len(cells))
    if cost.blocked[rows, cols].any():
        raise ValueError("path crosses a blocked cell")
    dr, dc = np.diff(rows), np.diff(cols)
    if (np.abs(dr) > 1).any() or (np.abs(dc) > 1).any() or ((dr == 0) & (dc == 0)).any():
        raise ValueError("path steps must go to a neighbouring cell")
    length = cost.grid.cell_m * np.where((dr != 0) & (dc != 0), math.sqrt(2.0), 1.0)

    def along(values):
        v = values[rows, cols]
        return float(np.sum(length * (v[:-1] + v[1:]) / 2.0))

    tr = cost.time_rate
    yellow = along(tr * cost.risk_parts["yellow"])
    steep = along(tr * cost.risk_parts["steep"])
    near_red = along(tr * cost.risk_parts["near_red"])
    return PathSummary(
        cells=cells,
        distance_m=float(length.sum()),
        physical_min=along(tr),
        risk_min=yellow + steep + near_red,
        yellow_min=yellow,
        steep_min=steep,
        near_red_min=near_red,
    )


class Tree:
    """Cheapest planning cost from one start cell to every cell, and the paths that give it."""

    def __init__(self, cost: Cost, mcp, start, planning_cost):
        self.cost = cost
        self.start = start
        self.planning_cost = planning_cost      # cumulative planning minutes, inf if unreachable
        self._mcp = mcp

    def reachable(self, end):
        return bool(np.isfinite(self.planning_cost[end]))

    def path_to(self, end):
        """The cheapest path to `end` with its time and risk, or NoPath."""
        end = (int(end[0]), int(end[1]))
        if self.cost.blocked[end]:
            raise NoPath(f"cell {end} is blocked")
        if not self.reachable(end):
            raise NoPath(f"cell {end} cannot be reached from cell {self.start}")
        return summarise(self.cost, self._mcp.traceback(end))


class Searcher:
    """Searches one site at one risk weight w. Trees are cached by start cell."""

    def __init__(self, cost: Cost, w, connectivity=8):
        self.cost = cost
        self.w = w
        self.planning = cost.planning_rate(w)
        self._full = fully_connected(connectivity)
        self._trees = {}

    def tree(self, start):
        start = (int(start[0]), int(start[1]))
        if start not in self._trees:
            if not (0 <= start[0] < self.cost.grid.height and 0 <= start[1] < self.cost.grid.width):
                raise NoPath(f"cell {start} is outside the grid")
            if self.cost.blocked[start]:
                raise NoPath(f"cell {start} is blocked")
            cell_m = self.cost.grid.cell_m
            mcp = MCP_Geometric(self.planning, fully_connected=self._full, sampling=(cell_m, cell_m))
            cumulative, _ = mcp.find_costs([start])
            self._trees[start] = Tree(self.cost, mcp, start, cumulative)
        return self._trees[start]

    def planning_cost(self, a, b):
        """Cheapest planning minutes from cell a to cell b (inf if unreachable)."""
        return float(self.tree(a).planning_cost[int(b[0]), int(b[1])])

    def path(self, a, b):
        return self.tree(a).path_to(b)
