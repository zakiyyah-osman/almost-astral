# Science stops

DRAFT for the Jezero delta site. The coordinates go into `data/out/waypoints.geojson`. The real positions depend on the official data, so the positions below are **placeholders**: they are the fake site's current coordinates, so Tushaar can keep testing the route. Replace them once we can see the real terrain.

Items marked **(check)** are from memory and need a source.

## Stop 1

- **Name:** Clay-bearing outcrop
- **Position (x, y in metres):** 500, 1500 (placeholder)
- **What is here:** a patch of rock whose minerals the CRISM instrument reads as clay. NASA papers describe Fe/Mg clay layers at the base of the delta front. **(check: find the real patch in the CRISM layer)**
- **Why it matters:** clay minerals form in the presence of water and can preserve traces of it.
- **What to sample:** a small rock chip and a drill core if the rock is soft enough. Photograph the layers.
- **Photo:** `photos/stop1-clay-search-jigging-cove.jpg`, an example from the clay search at Krokodillen (not confirmed clay). Credit and source in `photos/CREDITS.md`.

## Stop 2

- **Name:** Delta front layers
- **Position (x, y in metres):** 1400, 1760 (placeholder)
- **What is here:** tilted layers of sediment at the edge of the old delta. **(check)**
- **Why it matters:** the layers are thought to be sand and mud laid down by a river flowing into the lake, so they show where and how the water moved.
- **What to sample:** a sample of coarse layers and one of fine layers, to compare them.
- **Photo:** `photos/stop2-kodiak-delta.jpg`, Kodiak, a delta remnant. Credit and source in `photos/CREDITS.md`.

## Stop 3

- **Name:** Carbonate margin
- **Position (x, y in metres):** 1600, 500 (placeholder)
- **What is here:** a band of rock that the mineral layer picks out as carbonate. In the real Margin Unit, scientists still debate whether it is a lake shoreline or another kind of deposit, so say "may record" in the pitch. **(check what the real data shows here)**
- **Why it matters:** carbonates form when carbon-dioxide-rich water reacts with rock such as olivine, and they can trap evidence of past conditions. They record the water's chemistry.
- **What to sample:** loose surface material and one rock sample.
- **Photo:** `photos/stop3-margin-core-turquoise-bay.jpg`, a Margin Unit core that NASA says may contain carbonate. Credit and source in `photos/CREDITS.md`.

## Choosing the real stops

1. Pick each stop on the mineral layer first, then check the hazard layer so it is not in a red cell.
2. Keep every stop reachable and the whole outing well inside the 360 min limit.
3. Make sure the three stops tell one story: clay (early water), delta layers (water flowing in), carbonates (the water's chemistry).
4. Update `waypoints.geojson`, run `python data/validate.py`, and tell Tushaar.
