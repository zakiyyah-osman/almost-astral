"""The w-sweep and the sensitivity runs (DESIGN section 4.8).

    python routing/analysis.py                                  # reads data/out, writes routing/reports
    python routing/analysis.py --in DIR --config FILE --reports DIR --start X,Y

The start is --start, or the demo start (the safe landing cell nearest the grid centre), as in
plan_route.py.

As a script this writes CSV files into --reports and nothing else: it has no --out and never
writes to data/out. plan_route.py calls `sweep` for the `sweep` block of plan.json, and this
script writes the same rows to sweep.csv, so the two cannot disagree.

This module must not import plan_route.py.
"""
import argparse
import csv
import itertools
import sys
from pathlib import Path

import config as config_mod
import cost as cost_mod
import grid as grid_mod
import shelter as shelter_mod
import start as start_mod
import timeline as timeline_mod
import tour as tour_mod
from outputs import r1
from search import Searcher

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "data" / "out"
DEFAULT_REPORTS = ROOT / "routing" / "reports"

SWEEP_FIELDS = ("w", "distance_m", "walk_min", "risk_min", "yellow_min", "steep_min", "near_red_min")
SENSITIVITY_FIELDS = (
    "v_flat_kmh", "slope_max_deg", "w", "status", "walk_min", "total_min", "risk_min",
    "failed_stop", "reason",
)
OK, OVER_BUDGET, INFEASIBLE = "ok", "over_budget", "infeasible"


# ---- the w-sweep -------------------------------------------------------------
def sweep(model: cost_mod.Cost, start, order, cfg, ws=None):
    """One row per w in profiles.sweep_w: the route for that weight over the given stop order.

    Rows have the distance, the physical walk minutes and the risk minutes with its three
    parts, rounded to one decimal. Walk minutes rise and risk minutes fall as w grows.
    """
    ws = cfg.value("profiles.sweep_w") if ws is None else ws
    connectivity = cfg.value("search.connectivity")
    rows = []
    for w in ws:
        route = tour_mod.build_route(Searcher(model, w, connectivity), start, order, f"w={w:g}")
        rows.append({
            "w": float(w),
            "distance_m": r1(route.distance_m),
            "walk_min": r1(route.physical_min),
            "risk_min": r1(route.risk_min),
            "yellow_min": r1(route.yellow_min),
            "steep_min": r1(route.steep_min),
            "near_red_min": r1(route.near_red_min),
        })
    return rows


# ---- sensitivity -------------------------------------------------------------
def _infeasible(v, slope_max, w, error):
    return {
        "v_flat_kmh": v, "slope_max_deg": slope_max, "w": float(w), "status": INFEASIBLE,
        "walk_min": None, "total_min": None, "risk_min": None,
        "failed_stop": error.waypoint_id, "reason": str(error),
    }


def sensitivity(site: grid_mod.Site, start, stops, cfg, rad: timeline_mod.RadiationInfo):
    """Every combination of v_flat, slope limit and w (config section [sensitivity]).

    One row each: walk, total and risk minutes and the budget status, or `infeasible` with the
    stop that could not be reached or stands on a blocked cell. The stop order is chosen as in
    the plan (timeline.stop_order, on the balanced weight) for each v_flat and slope limit.
    """
    connectivity = cfg.value("search.connectivity")
    w_balanced = cfg.value("profiles.w_balanced")
    ws = cfg.value("sensitivity.w")
    rows = []
    for v, slope_max in itertools.product(
        cfg.value("sensitivity.v_flat_kmh"), cfg.value("sensitivity.slope_max_deg")
    ):
        params = cost_mod.Params.from_config(cfg, v_flat_kmh=v, slope_max_deg=slope_max)
        model = cost_mod.build(site.dem, site.hazard, site.slope, site.grid, params)
        balanced = Searcher(model, w_balanced, connectivity)
        try:
            tour_mod.check_waypoints(model, start, stops, balanced)
            order = tour_mod.choose_order(
                balanced, start, stops, cfg.value("timeline.stop_order"),
                cfg.value("timeline.optimise_max_stops"),
            ).order
        except (tour_mod.RouteError, start_mod.StartError) as e:
            rows.extend(_infeasible(v, slope_max, w, e) for w in ws)
            continue
        sheltered = shelter_mod.shelter_time(model, start.cell, cfg.value("timeline.ingress_min"), connectivity)
        for w in ws:
            try:
                route = tour_mod.build_route(Searcher(model, w, connectivity), start, order, f"w={w:g}")
            except tour_mod.RouteError as e:
                rows.append(_infeasible(v, slope_max, w, e))
                continue
            tl = timeline_mod.build_timeline(model, site.dem, site.hazard, route, sheltered, cfg, rad)
            rows.append({
                "v_flat_kmh": v, "slope_max_deg": slope_max, "w": float(w), "status": tl.status,
                "walk_min": r1(tl.walk_min), "total_min": r1(tl.total_min), "risk_min": r1(route.risk_min),
                "failed_stop": None, "reason": None,
            })
    return rows


# ---- reports -----------------------------------------------------------------
def write_csv(path, fields, rows):
    """A CSV with a header row; None is written as an empty cell."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row[k] is None else row[k]) for k in fields})
    return path


def run(in_dir, config_path=None, start_xy=None):
    """(sweep rows, sensitivity rows) for the site in `in_dir`. Writes nothing."""
    cfg = config_mod.load_config(config_path)
    site = grid_mod.load_site(in_dir)
    start_wp, stops = tour_mod.split_waypoints(tour_mod.load_waypoints(in_dir, site.grid))
    model = cost_mod.build(site.dem, site.hazard, site.slope, site.grid, cost_mod.Params.from_config(cfg))
    start, _ = tour_mod.choose_start(cfg, site, model, start_xy, start_wp)
    plan = tour_mod.plan_routes(model, start, stops, cfg)
    rad = timeline_mod.radiation_info(cfg, in_dir)
    return sweep(model, start, plan.order, cfg), sensitivity(site, start, stops, cfg, rad)


def write_reports(reports_dir, sweep_rows, sensitivity_rows):
    reports_dir = Path(reports_dir)
    return [
        write_csv(reports_dir / "sweep.csv", SWEEP_FIELDS, sweep_rows),
        write_csv(reports_dir / "sensitivity.csv", SENSITIVITY_FIELDS, sensitivity_rows),
    ]


def _parse_xy(text):
    """'x,y' in metres -> (x, y), for --start (the same rule as plan_route.parse_xy)."""
    try:
        x, y = (float(v) for v in str(text).split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"--start must be x,y in metres, got {text!r}") from None
    return (x, y)


def parse_args(argv):
    p = argparse.ArgumentParser(description="Run the w-sweep and the sensitivity runs; write CSV reports.")
    p.add_argument("--in", dest="in_dir", type=Path, default=DEFAULT_IN,
                   help="folder the inputs are read from (default: data/out)")
    p.add_argument("--config", dest="config", type=Path, default=None,
                   help="parameter file (default: routing/config.toml)")
    p.add_argument("--reports", dest="reports", type=Path, default=DEFAULT_REPORTS,
                   help="folder the CSV reports are written to (default: routing/reports)")
    p.add_argument("--start", dest="start", type=_parse_xy, default=None, metavar="X,Y",
                   help="start of the walk in metres (default: the demo start)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        sweep_rows, sens_rows = run(args.in_dir, args.config, args.start)
    except config_mod.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    written = write_reports(args.reports, sweep_rows, sens_rows)
    print(f"Wrote {', '.join(p.name for p in written)} to {args.reports}")
    infeasible = [r for r in sens_rows if r["status"] == INFEASIBLE]
    over = [r for r in sens_rows if r["status"] == OVER_BUDGET]
    print(f"sweep: {len(sweep_rows)} rows; sensitivity: {len(sens_rows)} runs, "
          f"{len(over)} over budget, {len(infeasible)} infeasible")
    return 0


if __name__ == "__main__":
    sys.exit(main())
