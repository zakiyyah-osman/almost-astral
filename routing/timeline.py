"""Legs, totals, track samples, budget checks and radiation (DESIGN section 8).

Times are physical minutes: risk never inflates a reported time. The clock starts when the
crew leaves the rover (egress is not counted); legs run rover -> stops -> rover.

    walk_min    = sum of physical minutes over legs
    stop_min    = timeline.stop_min_default for each stop
    ingress_min = timeline.ingress_min
    total_min   = walk_min + stop_min + ingress_min
"""
import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config import Config, ConfigError
from cost import Cost
from grid import RADIATION_FILE
from shelter import Shelter
from tour import Route, route_clock, sample_indices

CHECK_RESERVE, CHECK_ABORT, CHECK_RADIATION = "reserve", "abort", "radiation"
HOURS_PER_DAY = 24.0
USV_PER_MSV = 1000.0

# Facts about the cited solar-energetic-particle event. The dose itself is the config value
# radiation.solar_event_dose_mgy; these two strings only say which event it is.
SOLAR_EVENT_DATE = "2024-05-20"
SOLAR_EVENT_SOURCE = "Curiosity RAD (MSL), NASA"


@dataclass(frozen=True)
class LegTimes:
    from_id: str
    to_id: str
    distance_m: float
    walk_min: float
    risk_min: float
    ascent_m: float
    descent_m: float
    max_slope_deg: float
    depart_min: float
    arrive_min: float
    stop_min: float             # time spent at the destination (0 for the return to the rover)


@dataclass(frozen=True)
class TrackPoint:
    distance_m: float
    x: float
    y: float
    elev_m: float
    slope_deg: float
    hazard: int
    elapsed_min: float          # clock time, including time spent at stops already visited
    shelter_min: float          # minutes back to the rover, ingress included
    stop: object = None         # stop id when this is the arrival at a stop


@dataclass(frozen=True)
class Check:
    id: str
    ok: bool
    value: float
    limit: float
    unit: str
    message: str


@dataclass(frozen=True)
class Timeline:
    legs: tuple
    walk_min: float
    stop_min: float
    ingress_min: float
    total_min: float
    eva_max_min: float
    reserve_pct: float
    usable_min: float
    radiation_dose_usv: float
    track: tuple
    checks: tuple
    status: str                 # "ok" or "over_budget"


@dataclass(frozen=True)
class RadiationInfo:
    background_usv_h: float
    csv_median_usv_h: object    # None when radiation.csv is not available
    csv_storm_hours: tuple
    warnings: tuple
    solar_event: dict


# ---- radiation ---------------------------------------------------------------
def background_usv_h(cfg: Config):
    """Background dose rate in uSv per hour, from the config value in mSv per day."""
    return cfg.value("radiation.background_dose_rate_msv_day") * USV_PER_MSV / HOURS_PER_DAY


def dose_usv(total_min, rate_usv_h):
    """Dose for an EVA of total_min minutes at a constant rate. Sieverts only."""
    return rate_usv_h * total_min / 60.0


def solar_event(cfg: Config):
    """The solar-event dose, kept in Gy and never converted to Sv or added to the EVA dose."""
    return {
        "absorbed_dose_mgy": cfg.value("radiation.solar_event_dose_mgy"),
        "date": SOLAR_EVENT_DATE,
        "source": SOLAR_EVENT_SOURCE,
        "note": "Whole-event absorbed dose if unsheltered. In Gy; not added to radiation_dose_usv.",
    }


def read_radiation_csv(path):
    """(local_hour, dose_rate_usv_h) rows of radiation.csv."""
    path = Path(path)
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"{path.name} cannot be read ({path}): {e}") from None
    try:
        out = [(float(r["local_hour"]), float(r["dose_rate_usv_h"])) for r in rows]
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"{path.name}: needs numeric local_hour and dose_rate_usv_h columns ({e!r})") from None
    if not out:
        raise ConfigError(f"{path.name} has no data rows")
    if not all(math.isfinite(h) and math.isfinite(v) for h, v in out):
        raise ConfigError(f"{path.name}: values must be finite numbers")
    return out


def radiation_info(cfg: Config, folder):
    """Background rate, the radiation.csv cross-check and the demo's storm hours.

    radiation.csv is read for two things only: its median is compared with the config rate,
    and hours at or above storm_detect_factor x the median are listed as storm hours.
    """
    rate = background_usv_h(cfg)
    warnings, median, storm_hours = [], None, ()
    path = Path(folder) / RADIATION_FILE
    try:
        rows = read_radiation_csv(path)
    except FileNotFoundError:
        warnings.append(f"{RADIATION_FILE} not found: the background-rate cross-check was skipped")
        rows = None
    if rows:
        median = statistics.median(v for _, v in rows)
        tolerance = cfg.value("radiation.baseline_tolerance_pct")
        if rate > 0 and abs(median - rate) / rate * 100.0 > tolerance:
            warnings.append(
                f"{RADIATION_FILE} median {median:.1f} uSv/h differs from the configured background "
                f"{rate:.1f} uSv/h by more than {tolerance:g}%"
            )
        threshold = cfg.value("radiation.storm_detect_factor") * median
        hours = sorted({h for h, v in rows if v >= threshold})
        storm_hours = tuple(int(h) if float(h).is_integer() else h for h in hours)
    return RadiationInfo(rate, median, storm_hours, tuple(warnings), solar_event(cfg))


# ---- legs --------------------------------------------------------------------
def build_legs(cost: Cost, dem, route: Route, stop_min):
    """Legs with times, ascent and descent (from cell elevations) and the steepest slope."""
    legs, clock = [], 0.0
    last = len(route.legs) - 1
    for i, leg in enumerate(route.legs):
        rows = np.array([c[0] for c in leg.path.cells])
        cols = np.array([c[1] for c in leg.path.cells])
        dz = np.diff(dem[rows, cols])
        stay = stop_min if i < last else 0.0
        depart = clock
        arrive = depart + leg.path.physical_min
        legs.append(LegTimes(
            from_id=leg.from_id, to_id=leg.to_id,
            distance_m=leg.path.distance_m, walk_min=leg.path.physical_min, risk_min=leg.path.risk_min,
            ascent_m=float(dz[dz > 0].sum()), descent_m=float(-dz[dz < 0].sum()),
            max_slope_deg=float(np.max(cost.slope_deg[rows, cols])),
            depart_min=depart, arrive_min=arrive, stop_min=stay,
        ))
        clock = arrive + stay
    return tuple(legs)


# ---- track -------------------------------------------------------------------
def build_track(cost: Cost, dem, hazard, route: Route, shelter: Shelter, spacing_m, stop_min):
    """The route sampled every spacing_m, plus the arrival at each stop and the final cell.

    A sample sits on the route cell nearest to the wanted distance, so every value is the
    exact value of one cell.
    """
    clock = route_clock(cost, route, stop_min)
    stop_at = {idx: sid for sid, idx in clock.arrival_index.items()}
    wanted = set(sample_indices(clock.distance_m, spacing_m).tolist()) | set(stop_at) | {len(route.cells) - 1}
    points = []
    for idx in sorted(wanted):
        cell = route.cells[idx]
        x, y = cost.grid.cell_centre(*cell)
        points.append(TrackPoint(
            distance_m=float(clock.distance_m[idx]), x=x, y=y,
            elev_m=float(dem[cell]), slope_deg=float(cost.slope_deg[cell]), hazard=int(hazard[cell]),
            elapsed_min=float(clock.elapsed_min[idx]), shelter_min=float(shelter.minutes[cell]),
            stop=stop_at.get(idx),
        ))
    return tuple(points)


# ---- budgets and status ------------------------------------------------------
def _abort_check(track, legs, shelter: Shelter, route: Route, eva_max_min):
    """Worst of (elapsed + way back) over every track point and the moment of leaving each stop."""
    worst, where = -math.inf, ""
    for p in track:
        v = p.elapsed_min + p.shelter_min
        if v > worst:
            worst = v
            where = f"at {p.distance_m:.0f} m along the route" + (f" (arriving at {p.stop})" if p.stop else "")
    for leg_times, leg in zip(legs[:-1], route.legs[:-1]):   # leaving a stop: the clock includes its stop time
        v = leg_times.arrive_min + leg_times.stop_min + float(shelter.minutes[leg.path.cells[-1]])
        if v > worst:
            worst, where = v, f"leaving {leg.to_id}"
    ok = worst <= eva_max_min
    verb = "within" if ok else "over"
    return Check(
        CHECK_ABORT, ok, worst, eva_max_min, "min",
        f"At its worst, {where}, elapsed time plus the way back to shelter is {worst:.1f} min, "
        f"{verb} the {eva_max_min:g} min limit.",
    )


def build_timeline(cost: Cost, dem, hazard, route: Route, shelter: Shelter, cfg: Config,
                   rad: RadiationInfo):
    """Legs, totals, track, budget checks and status for one route."""
    stop_each = cfg.value("timeline.stop_min_default")
    ingress = cfg.value("timeline.ingress_min")
    eva_max = cfg.value("timeline.eva_max_min")
    reserve_pct = cfg.value("timeline.reserve_pct")
    limit_usv = cfg.value("radiation.limit_usv")

    legs = build_legs(cost, dem, route, stop_each)
    walk = float(sum(l.walk_min for l in legs))
    stops = stop_each * (len(route.legs) - 1)
    total = walk + stops + ingress
    usable = eva_max * (1.0 - reserve_pct / 100.0)
    track = build_track(cost, dem, hazard, route, shelter, cfg.value("track.spacing_m"), stop_each)
    dose = dose_usv(total, rad.background_usv_h)

    reserve_ok = total <= usable
    checks = (
        Check(
            CHECK_RESERVE, reserve_ok, total, usable, "min",
            f"Total {total:.1f} min is {'within' if reserve_ok else 'over'} the usable {usable:.1f} min "
            f"({eva_max:g} min minus a {reserve_pct:g}% reserve).",
        ),
        _abort_check(track, legs, shelter, route, eva_max),
        Check(
            CHECK_RADIATION, dose <= limit_usv, dose, limit_usv, "uSv",
            f"Dose {dose:.1f} uSv is {'within' if dose <= limit_usv else 'over'} the limit of {limit_usv:g} uSv.",
        ),
    )
    status = "ok" if all(c.ok for c in checks) else "over_budget"
    return Timeline(
        legs=legs, walk_min=walk, stop_min=float(stops), ingress_min=float(ingress), total_min=total,
        eva_max_min=float(eva_max), reserve_pct=float(reserve_pct), usable_min=usable,
        radiation_dose_usv=dose, track=track, checks=checks, status=status,
    )
