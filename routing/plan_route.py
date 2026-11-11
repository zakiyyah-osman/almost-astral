"""Plan the walk and write the route, the shelter-time map and the EVA plan.

Person 3: fill this in. See routing/README.md and CONTRACT.md.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "out"


def walking_speed(slope_deg):
    """Return the speed in m/min of a suited astronaut on this slope.

    TODO: Tobler's hiking function with a penalty for the suit and the load.
    """
    raise NotImplementedError


def find_route(hazard, start, stops):
    """Return the cheapest path from start through every stop and back, as a list of (x, y) in metres.

    TODO: A* on the cost grid. Red hazard cells (value 2) are not allowed.
    """
    raise NotImplementedError


def main():
    raise NotImplementedError("TODO (Person 3): route.geojson, shelter_time.png and plan.json")


if __name__ == "__main__":
    main()
