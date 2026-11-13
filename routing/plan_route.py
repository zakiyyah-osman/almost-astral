"""Plan the walk and write the route files, the shelter-time map and the EVA plan.

    python routing/plan_route.py                      # reads and writes data/out
    python routing/plan_route.py --in DIR             # reads DIR, writes DIR
    python routing/plan_route.py --in DIR --out DIR2  # reads DIR, writes DIR2
    python routing/plan_route.py --config FILE        # another parameter file

Writes route.geojson, route_fastest.geojson, route_safest.geojson, shelter_time.png and
plan.json. With --in and no --out the outputs go to the --in folder, never to data/out, so a
run pointed at a test folder cannot overwrite the shared data by accident.

A blocked or unreachable stop, or a malformed input, stops the run with a message and a
non-zero exit code, and nothing is written. A plan that goes over a budget is still written,
with status "over_budget" and a warning.
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import analysis
import config as config_mod
import cost
import grid as grid_mod
import outputs
import shelter
import storm
import timeline
import tour

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "data" / "out"


@dataclass(frozen=True)
class RunResult:
    files: dict             # file name -> bytes, not yet written
    plan: dict              # the plan.json content
    warnings: tuple


def run(in_dir, config_path=None):
    """Compute every output from the inputs in `in_dir`. Writes nothing."""
    cfg = config_mod.load_config(config_path)
    site = grid_mod.load_site(in_dir)
    layers, grid, dem, hazard = site.layers, site.grid, site.dem, site.hazard
    model = cost.build(dem, hazard, site.slope, grid, cost.Params.from_config(cfg))

    rover, stops = tour.split_waypoints(tour.load_waypoints(in_dir, grid))
    tour_plan = tour.plan_routes(model, rover, stops, cfg)

    connectivity = cfg.value("search.connectivity")
    sheltered = shelter.shelter_time(model, rover.cell, cfg.value("timeline.ingress_min"), connectivity)
    rad = timeline.radiation_info(cfg, in_dir)
    timelines = {
        name: timeline.build_timeline(model, dem, hazard, route, sheltered, cfg, rad)
        for name, route in tour_plan.routes.items()
    }
    replan = storm.storm_replan(
        model, tour_plan.routes["balanced"], sheltered,
        cfg.value("storm.sample_spacing_m"), cfg.value("timeline.stop_min_default"),
    )
    sweep_rows = analysis.sweep(model, rover, tour_plan.order, cfg)
    legend = shelter.legend(
        cfg.value("shelter_map.colour_max_min"), cfg.value("shelter_map.contour_interval_min")
    )
    warnings = [*tour_plan.warnings, *rad.warnings]
    files = outputs.render_outputs(
        cfg, grid, layers, tour_plan, timelines, replan, sheltered.minutes, legend, rad, warnings, sweep_rows
    )
    plan = outputs.build_plan(cfg, grid, layers, tour_plan, timelines, replan, legend, rad, warnings, sweep_rows)
    return RunResult(files, plan, tuple(warnings))


def summary_lines(result: RunResult):
    plan = result.plan
    totals, lines = plan["totals"], []
    lines.append(
        f"{plan['inputs']['site']}: status {plan['status']}, total {totals['total_min']} min "
        f"(walk {totals['walk_min']} + stops {totals['stop_min']} + ingress {totals['ingress_min']}), "
        f"dose {plan['radiation_dose_usv']} uSv"
    )
    lines.append("stop order: " + " -> ".join(["rover", *plan["stop_order"]["order"], "rover"]))
    for name, p in plan["profiles"].items():
        lines.append(
            f"  {name:<8} w={p['w']:g}  walk {p['walk_min']} min  {p['distance_m']} m  "
            f"risk {p['risk_min']} min  total {p['total_min']} min  {p['status']}"
        )
    for w in result.warnings:
        lines.append(f"WARNING {w}")
    if plan["status"] != "ok":
        for c in plan["checks"]:
            if not c["ok"]:
                lines.append(f"WARNING over budget: {c['message']}")
    if plan["inputs"]["inputs_fake"]:
        lines.append("NOTE the inputs still contain fake data")
    return lines


def parse_args(argv):
    p = argparse.ArgumentParser(description="Plan the walk: routes, shelter-time map and EVA plan.")
    p.add_argument("--in", dest="in_dir", type=Path, default=DEFAULT_IN,
                   help="folder the inputs are read from (default: data/out)")
    p.add_argument("--out", dest="out_dir", type=Path, default=None,
                   help="folder the outputs are written to (default: the --in folder)")
    p.add_argument("--config", dest="config", type=Path, default=None,
                   help="parameter file (default: routing/config.toml)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out_dir = args.out_dir if args.out_dir is not None else args.in_dir
    try:
        result = run(args.in_dir, args.config)
    except config_mod.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    written = outputs.write_files(out_dir, result.files)
    print(f"Wrote {', '.join(p.name for p in written)} to {out_dir}")
    for line in summary_lines(result):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
