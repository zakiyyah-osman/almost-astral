# mission/ (Person 5: Science, helmet HUD and pitch)

You decide where the crew goes and why, and you tell the story.

## Your job

1. **Mission brief** ([brief.md](brief.md)): science goals, crew setup, limits. One page.
2. **Science stops** ([stops.md](stops.md)): 3 to 5 stops with coordinates and a reason for each. **Give them to Person 3 by Wednesday** by writing them into `data/out/waypoints.geojson`.
3. **Photos:** a Perseverance ground-level photo for each stop, saved in `photos/` (credit the source).
4. **HUD view:** build it in `web/src/hud/`. Heading, distance to the next stop, time back to shelter, oxygen and battery, radiation dose rate, alerts.
5. **"Simulate EVA" demo:** an astronaut walks the route, a solar storm hits, and the plan switches to the return route.
6. **On Saturday:** write the demo script ([demo-script.md](demo-script.md)) and the slides in `slides/`, and run rehearsals.

## Folders

- `photos/`: images for the stops.
- `slides/`: the pitch slides.

## Hands over

`waypoints.geojson` by Wednesday, and the HUD as a component inside Person 4's app.
