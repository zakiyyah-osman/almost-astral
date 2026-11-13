"""Perseverance MEDA weather -> out/weather.csv (sol,local_hour,temp_c,pressure_pa,dust_tau).

Input: MEDA files from the PDS Atmospheres Node (see data/SOURCES.md). MEDA
puts one sol in each CSV and each sensor in its own file, so air temperature
(ATS) and pressure (PS) come from separate files. List them in the "meda"
block of data/site.json; wildcards such as "raw/meda/*_ATS_*.CSV" work.

The sol is read from the file name (WE__0420...) unless a sol column is set.
Readings are averaged per sol and local hour, and an hour is kept only when
both temperature and pressure have readings.

dust_tau is NOT measured here: it is the single estimate set in site.json,
and layers.json says so.

Run alone with:  python data/adapters/meda.py
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grid  # noqa: E402
import tables  # noqa: E402

HEADER = ["sol", "local_hour", "temp_c", "pressure_pa", "dust_tau"]
SOL_IN_NAME = re.compile(r"WE_+(\d{4})", re.IGNORECASE)


def expand(patterns):
    """Turn a path or list of paths/wildcards (relative to data/) into files."""
    if isinstance(patterns, str):
        patterns = [patterns]
    files = []
    for p in patterns or []:
        if any(c in p for c in "*?["):
            found = sorted(grid.DATA.glob(p))
            if not found:
                raise FileNotFoundError(f"{p} in data/site.json matches no files")
            files += found
        else:
            files.append(grid.raw_file(p))
    return files


def hourly(files, cols, convert, sols):
    """Mean of one value column per (sol, local hour) across several files."""
    lo, hi = sols
    sums = defaultdict(list)
    for path in files:
        names, rows = tables.read_rows(path)
        i_lt = tables.column_index(names, cols["ltst"], "local time")
        i_val = tables.column_index(names, cols["value"], "value")
        i_sol = tables.column_index(names, cols["sol"], "sol") if cols.get("sol") else None
        m = SOL_IN_NAME.search(path.name)
        file_sol = int(m.group(1)) if m else None
        if i_sol is None and file_sol is None:
            raise ValueError(f"No sol in the name of {path.name} and no sol column set in data/site.json")
        for r in rows:
            if len(r) <= max(i_lt, i_val, i_sol or 0):
                continue
            sol = tables._number(r[i_sol]) if i_sol is not None else file_sol
            hour = tables.local_hour(r[i_lt])
            x = tables._number(r[i_val])
            if sol is None or hour is None or x is None or not lo <= sol <= hi:
                continue
            sums[(int(sol), int(hour) % 24)].append(convert(x))
    return {k: sum(v) / len(v) for k, v in sums.items()}


def run(site):
    cfg = site.get("meda", {})
    temp_files = expand(cfg.get("temp_files"))
    pres_files = expand(cfg.get("pressure_files"))
    if not temp_files or not pres_files:
        return []
    sols = cfg["sols"]
    to_c = (lambda t: t - 273.15) if cfg.get("temp_units", "K").upper() == "K" else (lambda t: t)
    temp = hourly(temp_files, cfg["temp_columns"], to_c, sols)
    pres = hourly(pres_files, cfg["pressure_columns"], float, sols)
    keys = sorted(set(temp) & set(pres))
    if not keys:
        raise ValueError(f"No hour has both temperature and pressure for sols {sols[0]} to {sols[1]}. "
                         "Check the sols, file lists and column names in data/site.json "
                         "(python data/tables.py <file> shows the columns).")
    for (sol, h) in keys:
        if not -150 < temp[(sol, h)] < 50:
            raise ValueError(f"Sol {sol} hour {h}: temperature {temp[(sol, h)]:.0f} C is not plausible. "
                             "Check meda.temp_units and the temperature column.")

    tau = cfg.get("dust_tau_estimate", 0.6)
    rows = [[sol, h, round(temp[(sol, h)], 1), round(pres[(sol, h)], 1), tau] for sol, h in keys]
    tables.write_csv(grid.OUT / "weather.csv", HEADER, rows)
    names = sorted({p.name for p in temp_files + pres_files})
    grid.update_layers_json(extra={
        "weather.csv": f"{cfg.get('label', 'MEDA (Perseverance)')}: {len(names)} file(s), sols {sols[0]}-{sols[1]}, "
                       f"hourly means of air temperature and pressure. dust_tau is an estimate ({tau}), "
                       "not a MEDA measurement.",
    })
    missing = 24 * (sols[1] - sols[0] + 1) - len(rows)
    note = f" ({missing} hour(s) had no readings)" if missing > 0 else ""
    return [f"weather.csv: {len(rows)} hourly rows from {len(names)} MEDA file(s){note}"]


if __name__ == "__main__":
    for line in run(grid.load_site()) or ["nothing to do: set meda.temp_files and meda.pressure_files in data/site.json"]:
        print(line)
