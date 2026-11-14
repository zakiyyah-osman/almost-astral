# Lets the terrain tests import basemap/, hazards/ and hazard_map.py whether pytest runs from the
# repo root (python -m pytest terrain/tests, as in terrain/README.md) or from inside terrain/.
import sys
from pathlib import Path

TERRAIN = Path(__file__).resolve().parents[1]
if str(TERRAIN) not in sys.path:
    sys.path.insert(0, str(TERRAIN))
