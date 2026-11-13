"""Terrain and hazard layers for the Mars EVA planner (Person 2)."""

GREEN, YELLOW, RED, UNKNOWN = 0, 1, 2, 3
CLASS_NAMES = {GREEN: "Go", YELLOW: "Caution", RED: "No-go", UNKNOWN: "Unknown terrain coverage"}
CLASS_COLORS = {GREEN: "#3fae5a", YELLOW: "#f0be28", RED: "#dc3232", UNKNOWN: "#8a8a8a"}

# Team contract for hazard.png / hazard.tif:
#   hazard.tif holds ONLY 0, 1, 2. Cells with no terrain data are written as 2 (no-go),
#   so no route can cross ground we know nothing about; coverage.tif says which those are.
#   hazard.png: red (220,50,50), yellow (240,190,40), green fully transparent.
CONTRACT_CLASSES = (GREEN, YELLOW, RED)
CONTRACT_RGBA = {GREEN: (0, 0, 0, 0), YELLOW: (240, 190, 40, 255), RED: (220, 50, 50, 255)}

# Bits in reasons.tif, so the app can say *why* a cell is yellow/red.
REASON_BITS = {
    "no_data": 1,
    "slope_caution": 2,
    "slope_nogo": 4,
    "rough_caution": 8,
    "rough_nogo": 16,
    "loose_ground": 32,
    "very_loose_ground": 64,
    "rock_density_caution": 128,
    "rock_density_nogo": 256,
    "large_rock": 512,
    "cliff_edge": 1024,
    "safety_buffer": 2048,
}
