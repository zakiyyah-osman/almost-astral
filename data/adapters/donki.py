"""NASA DONKI solar storms -> out/space_weather.csv (a new, extra table).

Lists solar flares (FLR), coronal mass ejections (CME) and solar energetic
particle events (SEP) in the date range in data/site.json, and flags the ones
DONKI links to Mars:
  - CME: a WSA-ENLIL model run lists Mars in its impact list (with arrival time).
  - SEP: one of the detecting instruments is at Mars (MAVEN or Curiosity RAD).
Flares have no Mars flag: they are what can trigger the other two.

Needs internet, but no API key. DONKI moved in September 2026 from
api.nasa.gov to the CCMC web service below; the old kauai address is tried
as a backup.

Run alone with:  python data/adapters/donki.py
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grid  # noqa: E402
import tables  # noqa: E402

BASES = [
    "https://ccmc.gsfc.nasa.gov/DONKI/WS/get",
    "https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get",
]
HEADER = ["event_id", "type", "start_utc", "detail", "mars_impact", "mars_arrival_utc", "link"]
MARS_WORDS = ("MAVEN", "MSL", "MARS")


def get(kind, start, stop):
    """Try each DONKI address in turn; return the parsed JSON list."""
    problems = []
    for base in BASES:
        url = f"{base}/{kind}?startDate={start}&endDate={stop}"
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                body = resp.read().decode("utf-8").strip()
            return json.loads(body) if body else []
        except urllib.error.HTTPError as e:
            problems.append(f"{base}: HTTP {e.code}")
        except urllib.error.URLError as e:
            problems.append(f"{base}: {e.reason}")
        except json.JSONDecodeError:
            problems.append(f"{base}: reply was not JSON")
    raise RuntimeError(f"DONKI {kind} {start}..{stop} failed. " + "; ".join(problems))


def fetch(kind, start, end):
    """Get one DONKI endpoint, 30 days at a time."""
    events, day = [], start
    while day <= end:
        stop = min(day + timedelta(days=29), end)
        events += get(kind, day, stop)
        day = stop + timedelta(days=1)
        time.sleep(0.5)
    return events


def flare_rows(events):
    return [[e.get("flrID"), "FLR", e.get("beginTime"), f"class {e.get('classType')}",
             False, "", e.get("link", "")] for e in events]


def cme_rows(events):
    rows = []
    for e in events:
        analyses = e.get("cmeAnalyses") or []
        best = next((a for a in analyses if a.get("isMostAccurate")), analyses[0] if analyses else {})
        speed = best.get("speed")
        arrivals = []
        for a in analyses:
            for run in a.get("enlilList") or []:
                for hit in run.get("impactList") or []:
                    if str(hit.get("location", "")).upper().startswith("MARS"):
                        arrivals.append(hit.get("arrivalTime") or "")
        rows.append([e.get("activityID"), "CME", e.get("startTime"),
                     f"{speed:.0f} km/s" if isinstance(speed, (int, float)) else "speed unknown",
                     bool(arrivals), min([a for a in arrivals if a], default=""), e.get("link", "")])
    return rows


def sep_rows(events):
    rows = []
    for e in events:
        names = [i.get("displayName", "") for i in e.get("instruments") or []]
        at_mars = any(w in n.upper() for n in names for w in MARS_WORDS)
        rows.append([e.get("sepID"), "SEP", e.get("eventTime"), "; ".join(names),
                     at_mars, e.get("eventTime") if at_mars else "", e.get("link", "")])
    return rows


def run(site):
    cfg = site.get("donki", {})
    if not cfg.get("start"):
        return []
    start, end = date.fromisoformat(cfg["start"]), date.fromisoformat(cfg["end"])
    rows = (flare_rows(fetch("FLR", start, end))
            + cme_rows(fetch("CME", start, end))
            + sep_rows(fetch("SEP", start, end)))
    rows.sort(key=lambda r: r[2] or "")
    tables.write_csv(grid.OUT / "space_weather.csv", HEADER, rows)
    grid.update_layers_json(
        table=("space_weather", "space_weather.csv"),
        extra={"space_weather.csv": f"{cfg.get('label', 'NASA DONKI')}, {start} to {end}. "
                                    "mars_impact comes from DONKI's own model runs and instrument lists."},
    )
    mars = sum(1 for r in rows if r[4])
    counts = {t: sum(1 for r in rows if r[1] == t) for t in ("FLR", "CME", "SEP")}
    return [f"space_weather.csv: {counts['FLR']} flares, {counts['CME']} CMEs, {counts['SEP']} SEP events; "
            f"{mars} flagged as reaching Mars"]


if __name__ == "__main__":
    for line in run(grid.load_site()) or ["nothing to do: set donki.start and donki.end in data/site.json"]:
        print(line)
