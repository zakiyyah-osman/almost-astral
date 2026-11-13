"""Helpers for the table adapters (REMS weather, RAD radiation).

Reads a CSV or PDS .TAB file, picks the columns named in data/site.json, and
averages them into one row per sol and local hour, as CONTRACT.md expects.

To see what columns a file has before setting them in site.json:

    python data/tables.py data/raw/rems/yourfile.csv
"""
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?")


def read_rows(path):
    """Return (column_names, rows). Files without a header get names 1, 2, 3..."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise ValueError(f"{Path(path).name} is empty")
    delimiter = "," if lines[0].count(",") else None
    if delimiter:
        rows = [[c.strip().strip('"') for c in r] for r in csv.reader(lines, delimiter=",")]
    else:
        rows = [ln.split() for ln in lines]
    first = rows[0]
    if any(not _looks_like_value(c) for c in first):
        return [c.strip() for c in first], rows[1:]
    return [str(i) for i in range(1, len(first) + 1)], rows


def _looks_like_value(cell):
    return _number(cell) is not None or bool(TIME.search(cell)) or cell in ("", "UNK", "NULL", "NaN")


def _number(cell):
    try:
        x = float(cell)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and abs(x) < 1e30 else None


def local_hour(cell):
    """Accept '13:45:10', 'LTST 13:45', 'M13:45' or a decimal hour like 13.75."""
    m = TIME.search(cell or "")
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3) or 0) / 3600
    return _number(cell)


def column_index(names, wanted, what):
    wanted = str(wanted)
    upper = [n.upper() for n in names]
    if wanted.upper() in upper:
        return upper.index(wanted.upper())
    raise ValueError(f"Column '{wanted}' (for {what}) not found. Columns are: {', '.join(names)}")


def hourly_means(path, columns, sols, values):
    """Average chosen columns per (sol, whole local hour).

    columns: mapping from role to column name, must include "sol" and "ltst".
    values:  mapping from output name to (role, convert_function).
    Returns a sorted list of (sol, hour, {output_name: mean}).
    """
    names, rows = read_rows(path)
    i_sol = column_index(names, columns["sol"], "sol")
    i_lt = column_index(names, columns["ltst"], "local time")
    idx = {out: (column_index(names, columns[role], role), fn) for out, (role, fn) in values.items()}
    lo, hi = sols

    sums = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if len(r) <= max([i_sol, i_lt] + [i for i, _ in idx.values()]):
            continue
        sol = _number(r[i_sol])
        hour = local_hour(r[i_lt])
        if sol is None or hour is None or not lo <= sol <= hi:
            continue
        key = (int(sol), int(hour) % 24)
        for out, (i, fn) in idx.items():
            x = _number(r[i])
            if x is not None:
                sums[key][out].append(fn(x))

    result = []
    for key in sorted(sums):
        means = {out: sum(v) / len(v) for out, v in sums[key].items() if v}
        if len(means) == len(values):
            result.append((key[0], key[1], means))
    if not result:
        raise ValueError(f"No usable rows in {Path(path).name} for sols {lo} to {hi}. "
                         "Check the sol range and column names in data/site.json.")
    return result


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python data/tables.py path/to/file.csv")
    names, rows = read_rows(sys.argv[1])
    print(f"{len(rows)} rows. Columns and first values:")
    for i, n in enumerate(names):
        sample = [r[i] for r in rows[:3] if i < len(r)]
        print(f"  {n!r:28} {sample}")
