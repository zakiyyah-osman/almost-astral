"""Curiosity REMS weather -> out/weather.csv (sol,local_hour,temp_c,pressure_pa,dust_tau).

Input: a CSV or PDS .TAB of REMS readings (see data/SOURCES.md). Set the file,
the sol range and the column names in the "rems" block of data/site.json.
Readings are averaged per sol and local hour.

dust_tau is NOT measured by REMS: it is the single estimate set in site.json,
and layers.json says so.

Run alone with:  python data/adapters/rems.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grid  # noqa: E402
import tables  # noqa: E402

HEADER = ["sol", "local_hour", "temp_c", "pressure_pa", "dust_tau"]


def run(site):
    cfg = site.get("rems", {})
    path = grid.raw_file(cfg.get("file"))
    if not path:
        return []
    to_c = (lambda t: t - 273.15) if cfg.get("temp_units", "K").upper() == "K" else (lambda t: t)
    hours = tables.hourly_means(path, cfg["columns"], cfg["sols"], {
        "temp_c": ("temp", to_c),
        "pressure_pa": ("pressure", float),
    })
    tau = cfg.get("dust_tau_estimate", 0.6)
    rows = [[sol, h, round(v["temp_c"], 1), round(v["pressure_pa"], 1), tau] for sol, h, v in hours]
    tables.write_csv(grid.OUT / "weather.csv", HEADER, rows)
    grid.update_layers_json(extra={
        "weather.csv": f"{cfg.get('label', 'REMS (Curiosity)')}: {path.name}, sols {cfg['sols'][0]}-{cfg['sols'][1]}, "
                       f"hourly means. dust_tau is an estimate ({tau}), not a REMS measurement.",
    })
    missing = 24 * (cfg["sols"][1] - cfg["sols"][0] + 1) - len(rows)
    note = f" ({missing} hour(s) had no readings)" if missing > 0 else ""
    return [f"weather.csv: {len(rows)} hourly rows from {path.name}{note}"]


if __name__ == "__main__":
    for line in run(grid.load_site()) or ["nothing to do: set rems.file in data/site.json"]:
        print(line)
