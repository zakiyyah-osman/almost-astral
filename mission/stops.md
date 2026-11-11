# Science stops

DRAFT for the Mount Sharp boxwork site. The coordinates go into `data/out/waypoints.geojson`. The real positions depend on the official data, which arrives on Saturday, so the positions below are **placeholders**: they are the fake site's current coordinates, so Tushaar can keep testing the route. Replace them once we can see the real terrain.

Items marked **(check)** are from memory and need a source.

## Stop 1

- **Name:** Clay outcrop
- **Position (x, y in metres):** 500, 1500 (placeholder)
- **What is here:** a patch of rock whose minerals the CRISM instrument reads as clay. **(check: find the real patch in the CRISM layer)**
- **Why it matters:** clay minerals form in the presence of water and can preserve traces of it.
- **What to sample:** a small rock chip and a drill core if the rock is soft enough. Photograph the layers.
- **Photo:** none yet. To find: a Curiosity Mastcam image of clay-bearing rock, credited to NASA/JPL-Caltech/MSSS. Save in `photos/`.

## Stop 2

- **Name:** Boxwork ridges
- **Position (x, y in metres):** 1400, 1760 (placeholder)
- **What is here:** a web of low ridges that make a box-like pattern. **(check)**
- **Why it matters:** the ridges are thought to be cracks that groundwater filled and hardened, so they show where water moved through the rock.
- **What to sample:** a ridge sample and a sample of the softer rock between the ridges, to compare them.
- **Photo:** none yet. To find: a Curiosity image of the boxwork area, credited to NASA/JPL-Caltech. Save in `photos/`.

## Stop 3

- **Name:** Sulfate or carbonate patch
- **Position (x, y in metres):** 1600, 500 (placeholder)
- **What is here:** a mineral patch that the mineral layer picks out from the rock around it. **(check what the real data shows here)**
- **Why it matters:** salts like these form as water dries up, so they record how the water left.
- **What to sample:** loose surface material and one rock sample.
- **Photo:** none yet. Save in `photos/` with the credit.

## Choosing the real stops (Saturday)

1. Pick each stop on the mineral layer first, then check the hazard layer so it is not in a red cell.
2. Keep every stop reachable and the whole outing well inside the 360 min limit.
3. Make sure the three stops tell one story: clay (early water), ridges (water moving), salts (water leaving).
4. Update `waypoints.geojson`, run `python data/validate.py`, and tell Tushaar.
