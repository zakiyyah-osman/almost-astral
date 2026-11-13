"""Writers for the route GeoJSON files and plan.json (DESIGN section 9).

Everything is built in memory first (`render_*`), so a run that fails part-way writes nothing.
There is no timestamp, so the same inputs give the same bytes.

Contract fields keep their names and meaning. Contract times and distances are whole minutes
and metres; added fields use one decimal. Coordinates are [x, y] in metres on the site grid.
"""
import io
import json
import re
from pathlib import Path

from PIL import Image

from config import Config
from grid import PLAN_FILE, ROUTE_FILE, SHELTER_FILE, Grid
from shelter import render_png
from storm import StormReplan
from timeline import RadiationInfo, Timeline
from tour import PROFILES, Route, TourPlan

ROUTE_FILES = {
    "fastest": "route_fastest.geojson",
    "balanced": ROUTE_FILE,
    "safest": "route_safest.geojson",
}
ROUTE_SOURCE = "routing model over dem.tif and hazard.tif"
COORD_DECIMALS = 3          # metres; cell centres can be fractions of a metre on a fine grid


def r1(x):
    """One decimal, as a plain float (None stays None)."""
    return None if x is None else round(float(x), 1)


def whole(x):
    return int(round(float(x)))


def xy(point):
    return [round(float(point[0]), COORD_DECIMALS), round(float(point[1]), COORD_DECIMALS)]


def drop_collinear(cells):
    """Cells with the vertices on a straight run removed; the first and last always stay."""
    cells = [tuple(c) for c in cells]
    if len(cells) <= 2:
        return cells
    out = [cells[0]]
    for prev, cur, nxt in zip(cells, cells[1:], cells[2:]):
        if (cur[0] - prev[0], cur[1] - prev[1]) != (nxt[0] - cur[0], nxt[1] - cur[1]):
            out.append(cur)
    out.append(cells[-1])
    return out


def cells_to_xy(grid: Grid, cells):
    return [xy(grid.cell_centre(r, c)) for r, c in drop_collinear(cells)]


# ---- route files -------------------------------------------------------------
def route_geojson(route: Route, grid: Grid):
    """A FeatureCollection with one LineString: the whole walk, rover to stops and back."""
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": cells_to_xy(grid, route.cells)},
            "properties": {
                "profile": route.profile,
                "w": route.w,
                "distance_m": r1(route.distance_m),
                "walk_min": r1(route.physical_min),
                "risk_min": r1(route.risk_min),
                "source": ROUTE_SOURCE,
            },
        }],
    }


# ---- plan.json ---------------------------------------------------------------
def _leg(t):
    return {
        "from": t.from_id, "to": t.to_id,
        "distance_m": whole(t.distance_m), "walk_min": whole(t.walk_min),
        "risk_min": r1(t.risk_min), "ascent_m": r1(t.ascent_m), "descent_m": r1(t.descent_m),
        "max_slope_deg": r1(t.max_slope_deg),
        "depart_min": r1(t.depart_min), "arrive_min": r1(t.arrive_min), "stop_min": r1(t.stop_min),
    }


def _check(c):
    return {"id": c.id, "ok": c.ok, "value": r1(c.value), "limit": r1(c.limit), "unit": c.unit,
            "message": c.message}


def _track(p):
    d = {
        "distance_m": r1(p.distance_m), "x": xy((p.x, p.y))[0], "y": xy((p.x, p.y))[1],
        "elev_m": r1(p.elev_m), "slope_deg": r1(p.slope_deg), "hazard": p.hazard,
        "elapsed_min": r1(p.elapsed_min), "shelter_min": r1(p.shelter_min),
    }
    if p.stop is not None:
        d["stop"] = p.stop
    return d


def _storm(rep: StormReplan, grid: Grid):
    points = []
    for p in rep.points:
        d = {
            "x": xy((p.x, p.y))[0], "y": xy((p.x, p.y))[1],
            "route_distance_m": r1(p.route_distance_m), "elapsed_min": r1(p.elapsed_min),
            "return_min": r1(p.return_min), "return_distance_m": r1(p.return_distance_m),
            "path": cells_to_xy(grid, p.path),
        }
        if p.stop is not None:
            d["stop"] = p.stop
        points.append(d)
    return {"sample_spacing_m": rep.sample_spacing_m, "points": points, "worst": rep.worst}


def build_plan(cfg: Config, grid: Grid, layers: dict, tour: TourPlan, timelines: dict,
               storm: StormReplan, legend: dict, rad: RadiationInfo, warnings):
    """The plan.json dictionary. `timelines` maps profile name to Timeline; balanced is the plan."""
    tl: Timeline = timelines["balanced"]
    walk, stop, ingress = whole(tl.walk_min), whole(tl.stop_min), whole(tl.ingress_min)
    profiles = {}
    for name, _ in PROFILES:
        route, t = tour.routes[name], timelines[name]
        profiles[name] = {
            "w": route.w, "file": ROUTE_FILES[name],
            "distance_m": r1(route.distance_m), "walk_min": r1(route.physical_min),
            "risk_min": r1(route.risk_min), "yellow_min": r1(route.yellow_min),
            "steep_min": r1(route.steep_min), "near_red_min": r1(route.near_red_min),
            "total_min": r1(t.total_min), "status": t.status,
        }
    fake = any("FAKE" in str(layer.get("source", "")) for layer in layers.get("layers", []))
    return {
        "crew": cfg.value("crew.size"),
        "legs": [_leg(t) for t in tl.legs],
        "totals": {"walk_min": walk, "stop_min": stop, "total_min": walk + stop + ingress,
                   "ingress_min": ingress},
        "budgets": {
            "eva_max_min": cfg.value("timeline.eva_max_min"),
            "radiation_limit_usv": cfg.value("radiation.limit_usv"),
            "reserve_pct": cfg.value("timeline.reserve_pct"),
            "usable_min": r1(tl.usable_min),
        },
        "radiation_dose_usv": whole(tl.radiation_dose_usv),
        "status": tl.status,
        "checks": [_check(c) for c in tl.checks],
        "stop_order": {
            "mode": tour.mode, "requested": tour.requested_mode,
            "order": [s.id for s in tour.order], "warnings": list(tour.warnings),
        },
        "profiles": profiles,
        "track": [_track(p) for p in tl.track],
        "storm_replan": _storm(storm, grid),
        "shelter_map": legend,
        "radiation": {
            "background_usv_h": r1(rad.background_usv_h),
            "csv_median_usv_h": r1(rad.csv_median_usv_h),
            "csv_storm_hours": list(rad.csv_storm_hours),
            "solar_event": rad.solar_event,
        },
        "assumptions": cfg.assumptions(),
        "inputs": {
            "site": layers.get("site", {}).get("name"),
            "grid": {"width": grid.width, "height": grid.height, "cell_m": grid.cell_m},
            "inputs_fake": fake,
        },
        "warnings": list(warnings),
    }


# ---- bytes and files ---------------------------------------------------------
_NUMBER_ARRAY = re.compile(r"\[\s*(-?\d[\d.eE+\-,\s]*?)\s*\]")


def dumps(obj):
    """Stable JSON text: fixed key order, two-space indent, no NaN, trailing newline.

    Arrays that hold only numbers, such as [x, y] points, stay on one line to keep the file small.
    """
    text = json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False)
    text = _NUMBER_ARRAY.sub(lambda m: "[" + re.sub(r"\s*,\s*", ", ", m.group(1).strip()) + "]", text)
    return text + "\n"


def png_bytes(minutes, colour_max_min, interval_min):
    buf = io.BytesIO()
    Image.fromarray(render_png(minutes, colour_max_min, interval_min), mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def render_outputs(cfg: Config, grid: Grid, layers: dict, tour: TourPlan, timelines: dict,
                   storm: StormReplan, shelter_minutes, legend: dict, rad: RadiationInfo, warnings):
    """Every output file as {file name: bytes}. Nothing is written here."""
    files = {
        name: dumps(route_geojson(tour.routes[profile], grid)).encode("utf-8")
        for profile, name in ROUTE_FILES.items()
    }
    files[SHELTER_FILE] = png_bytes(
        shelter_minutes, cfg.value("shelter_map.colour_max_min"), cfg.value("shelter_map.contour_interval_min")
    )
    files[PLAN_FILE] = dumps(
        build_plan(cfg, grid, layers, tour, timelines, storm, legend, rad, warnings)
    ).encode("utf-8")
    return files


def write_files(out_dir, files):
    """Write the rendered files into out_dir (created if needed)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out_dir / name).write_bytes(data)
    return [out_dir / name for name in files]
