#!/usr/bin/env bash
# Person 2, one command:  ./run_all.sh data/layers.json out
# Hazards -> alignment check -> base map + viewer. Keeps going if a check fails,
# then tells you which one, so you always get a viewer to look at.
LAYERS=${1:-data/layers.json}
OUT=${2:-out}
cd "$(dirname "$0")"
status=0
python3 -m hazards.run   --layers "$LAYERS" --out "$OUT"                  || { echo ">> rover-track check FAILED - see $OUT/track_check.png"; status=1; }
python3 -m basemap.align --layers "$LAYERS" --out "$OUT"                  || { echo ">> alignment check FAILED - see $OUT/alignment_report.json"; status=1; }
python3 -m basemap.build --layers "$LAYERS" --hazards "$OUT" --out "$OUT" || exit 2
echo "Open $OUT/martial_map.html"
exit $status
