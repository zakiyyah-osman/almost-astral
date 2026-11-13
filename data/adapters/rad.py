"""Curiosity RAD radiation -> out/radiation.csv (sol,local_hour,dose_rate_usv_h).

Input: a CSV with a sol column, a local-time column and a dose-rate column
(see data/SOURCES.md for where the numbers come from). Set the file, sol
range, column names and units in the "rad" block of data/site.json.

With no file, a constant published average (rad.estimate) is written for every
hour of the sol range instead. That is what the Jezero site uses: Perseverance
has no dose instrument, so the dose is an estimate from Curiosity's RAD at Gale,
and layers.json says so.

RAD measures absorbed dose (gray). The contract asks for dose equivalent
(sievert), which also depends on the particle mix. We multiply by an average
quality factor from site.json and say so in layers.json.

Run alone with:  python data/adapters/rad.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grid  # noqa: E402
import tables  # noqa: E402

HEADER = ["sol", "local_hour", "dose_rate_usv_h"]


def converter(units, qf):
    units = units.lower()
    if units == "ugy_per_day":
        return lambda x: x / 24 * qf
    if units == "ugy_per_h":
        return lambda x: x * qf
    if units == "usv_per_h":
        return lambda x: x
    raise ValueError(f"rad.dose_units must be ugy_per_day, ugy_per_h or usv_per_h, not {units!r}")


def run_estimate(cfg):
    est = cfg["estimate"]
    usv_h = float(est["usv_per_day"]) / 24
    lo, hi = cfg["sols"]
    rows = [[sol, h, round(usv_h, 2)] for sol in range(lo, hi + 1) for h in range(24)]
    tables.write_csv(grid.OUT / "radiation.csv", HEADER, rows)
    grid.update_layers_json(extra={"radiation.csv": f"ESTIMATE, not a measurement at this site: {est['source']}"})
    return [f"radiation.csv: constant estimate {usv_h:.1f} uSv/h for sols {lo}-{hi} ({len(rows)} rows)"]


def run(site):
    cfg = site.get("rad", {})
    path = grid.raw_file(cfg.get("file"))
    if not path:
        return run_estimate(cfg) if cfg.get("estimate") else []
    qf = float(cfg.get("quality_factor", 3.05))
    to_usv_h = converter(cfg.get("dose_units", "ugy_per_day"), qf)
    hours = tables.hourly_means(path, cfg["columns"], cfg["sols"], {"dose": ("dose", to_usv_h)})
    rows = [[sol, h, round(v["dose"], 2)] for sol, h, v in hours]
    tables.write_csv(grid.OUT / "radiation.csv", HEADER, rows)

    converted = "" if cfg.get("dose_units") == "usv_per_h" else \
        f" Converted from gray to sievert with an average quality factor of {qf} (an approximation)."
    grid.update_layers_json(extra={
        "radiation.csv": f"{cfg.get('label', 'RAD (Curiosity)')}: {path.name}, sols "
                         f"{cfg['sols'][0]}-{cfg['sols'][1]}, hourly means.{converted}",
    })
    mean = sum(r[2] for r in rows) / len(rows)
    return [f"radiation.csv: {len(rows)} hourly rows, mean {mean:.1f} uSv/h "
            "(Hassler et al. 2014 surface average is about 27 uSv/h)"]


if __name__ == "__main__":
    for line in run(grid.load_site()) or ["nothing to do: set rad.file or rad.estimate in data/site.json"]:
        print(line)
