"""A plain Dijkstra written only from the edge rule in manifest.json / DESIGN section 15.

It stands in for the browser's search: no skimage, no routing modules. If it reproduces the
paths and totals of export_landing.route (MCP_Geometric), a JavaScript copy of it will too.
"""
import heapq
import math

NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def search(time_rate, risk_rate, mask, cell_m, w, start, goal=None):
    """(g, prev): cumulative planning cost and predecessor of every settled cell.

    Rule: p = time_rate * (1 + w * risk_rate); a step of length L costs L * (p_from + p_to) / 2,
    with L = cell_m straight and sqrt(cell_m * cell_m + cell_m * cell_m) diagonal; a neighbour is
    relaxed only when the new cost is strictly lower; mask != 0 is never entered.
    """
    h, w_ = len(mask), len(mask[0])
    straight = cell_m
    diagonal = math.sqrt(cell_m * cell_m + cell_m * cell_m)
    p = [[time_rate[r][c] * (1.0 + w * risk_rate[r][c]) for c in range(w_)] for r in range(h)]
    g = {start: 0.0}
    prev = {start: None}
    done = set()
    heap = [(0.0, start)]
    while heap:
        gc, cell = heapq.heappop(heap)
        if cell in done:
            continue
        done.add(cell)
        if cell == goal:
            break
        r, c = cell
        pc = p[r][c]
        for dr, dc in NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < h and 0 <= cc < w_) or mask[rr][cc] != 0 or (rr, cc) in done:
                continue
            L = diagonal if dr and dc else straight
            ng = gc + L * (pc + p[rr][cc]) / 2.0
            if ng < g.get((rr, cc), math.inf):
                g[(rr, cc)] = ng
                prev[(rr, cc)] = cell
                heapq.heappush(heap, (ng, (rr, cc)))
    return g, prev, done


def path_and_totals(time_rate, risk_rate, mask, cell_m, w, start, goal):
    """(cells, distance_m, walk_min, risk_min), or None when the goal cannot be reached."""
    if mask[goal[0]][goal[1]] != 0 or mask[start[0]][start[1]] != 0:
        return None
    g, prev, done = search(time_rate, risk_rate, mask, cell_m, w, start, goal)
    if goal not in done:
        return None
    cells = [goal]
    while prev[cells[-1]] is not None:
        cells.append(prev[cells[-1]])
    cells.reverse()
    diag = cell_m * math.sqrt(2.0)
    d = t = k = 0.0
    for (ra, ca), (rb, cb) in zip(cells, cells[1:]):
        L = diag if (ra != rb and ca != cb) else cell_m
        ta, tb = time_rate[ra][ca], time_rate[rb][cb]
        d += L
        t += L * (ta + tb) / 2.0
        k += L * (ta * risk_rate[ra][ca] + tb * risk_rate[rb][cb]) / 2.0
    return cells, d, t, k
