"""Storm re-plan: the fastest way back to the rover from sampled points of the route (DESIGN section 7).

Samples are placed on the balanced route every storm.sample_spacing_m and at every stop. A
sample sits on the route cell whose distance along the route is nearest to the wanted
distance, so its position, its shelter time and its return path all refer to one cell.
The return path is the traceback of the rover-rooted search of the shelter map: the fastest
physical way back, ignoring risk weights, never crossing a blocked cell.
"""
from dataclasses import dataclass

import numpy as np

from cost import Cost
from shelter import Shelter
from tour import Route, route_clock, sample_indices


@dataclass(frozen=True)
class StormPoint:
    cell: tuple
    x: float
    y: float
    route_distance_m: float     # distance along the route to this sample
    elapsed_min: float          # clock on arrival, including time at stops already done
    return_min: float           # walk back plus ingress
    return_distance_m: float
    path: tuple                 # return path as cells, from this sample to the rover
    stop: object = None         # stop id when the sample is the arrival at a stop


@dataclass(frozen=True)
class StormReplan:
    sample_spacing_m: float
    points: tuple
    worst: int                  # index into points of the largest return_min (first on a tie)


def storm_replan(cost: Cost, route: Route, shelter: Shelter, spacing_m, stop_min):
    """Return table for the route's samples. `stop_min` is the time spent at each stop."""
    grid = cost.grid
    clock = route_clock(cost, route, stop_min)
    stop_at = {idx: sid for sid, idx in clock.arrival_index.items()}
    wanted = set(sample_indices(clock.distance_m, spacing_m).tolist()) | set(stop_at)
    points = []
    for idx in sorted(wanted):
        cell = route.cells[idx]
        back = shelter.tree.path_to(cell)                       # rover -> cell
        return_cells = tuple(reversed(back.cells))              # cell -> rover
        x, y = grid.cell_centre(*cell)
        points.append(StormPoint(
            cell=cell, x=x, y=y,
            route_distance_m=float(clock.distance_m[idx]),
            elapsed_min=float(clock.elapsed_min[idx]),
            return_min=float(shelter.minutes[cell]),
            return_distance_m=back.distance_m,
            path=return_cells,
            stop=stop_at.get(idx),
        ))
    worst = int(np.argmax([p.return_min for p in points]))
    return StormReplan(float(spacing_m), tuple(points), worst)
