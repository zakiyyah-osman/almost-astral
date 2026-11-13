"""Terrain and hazard layers for the Mars EVA planner (Person 2)."""

GREEN, YELLOW, RED, UNKNOWN = 0, 1, 2, 3
CLASS_NAMES = {GREEN: "Go", YELLOW: "Caution", RED: "No-go", UNKNOWN: "Unknown terrain coverage"}
CLASS_COLORS = {GREEN: "#3fae5a", YELLOW: "#f2c230", RED: "#d63a2f", UNKNOWN: "#8a8a8a"}

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
