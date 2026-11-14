# Science stops

The three stops in `data/out/waypoints.geojson` are final. Yaj chose them on 14 Nov from our real layers: CRISM (MRO) minerals, THEMIS (Mars Odyssey) thermal inertia and the HiRISE-derived hazard map. All three are on green (safe) cells. Positions are x, y in metres on the site grid (`CONTRACT.md`).

The story: clay (water sat here), delta layers (a river flowed into a lake), olivine (the rock that water turns into carbonate).

The CRISM cut-offs are relative (the strongest signals in one image), so say "CRISM picks out clay here", not "this is clay". Rover sample sites below come from NASA's Perseverance waypoints on the sol each core was taken; see `minerals.md`.

## Start

- **Now:** the rover waypoint at 1000, 900 ("Start and safe haven").
- **Coming:** Tushaar's walking-only plan (PR 18) starts at a "Demo start" at 1017.5, 1112.5, the safe landing cell nearest the middle of the square. Once it is merged and Loick's map drops the rover pin, replace the rover waypoint with that start. The HUD already handles a plan that starts and ends at "start".

## Stop 1: Clay-rich delta top

- **Position:** 1562.5, 1307.5
- **What is here:** rock on top of the delta that CRISM (parameter D2300) picks out as Fe/Mg smectite clay. Published orbital work finds clay strongest in the lower, fine-grained delta layers, so this is a clay signal on the delta top, not the classic bottomset clay.
- **Nearby rover work:** Perseverance cored the Wildcat Ridge mudstone (cores Hazeltop and Bearwallow, sols 509 and 516) and Skinner Ridge (Swift Run and Skyland, sols 490 and 495) at about 1330, 920, inside our square. Wildcat Ridge likely formed as mud settled in an evaporating salty lake, and SHERLOC found organic molecules alongside sulfate minerals there (NASA/JPL, 2022).
- **Why it matters:** clay forms in water and can preserve traces of past conditions.
- **What to sample:** a small rock chip and a drill core if the rock is soft enough. Photograph any layering.
- **Photo:** `photos/stop1-clay-search-jigging-cove.jpg`, an example from Perseverance's clay search at Krokodillen, not this spot and not confirmed clay. Credit in `photos/CREDITS.md`.

## Stop 2: Delta front scarp

- **Position:** 1867.5, 972.5
- **What is here:** layers exposed where the delta front drops toward the crater floor. Mangold et al. 2021 (*Science* 374) read the inclined layers at the delta front as a delta building out into a standing lake, with boulder layers from floods on top.
- **Why it matters:** the layers show where and how the water moved.
- **What to sample:** one coarse layer and one fine layer, to compare them.
- **Photo:** `photos/stop2-kodiak-delta.jpg`, Kodiak, a delta remnant described in the same paper (an example, not this spot). Credit in `photos/CREDITS.md`.

## Stop 3: Olivine-rich crater floor

- **Position:** 992.5, 207.5
- **What is here:** crater-floor rock that CRISM (OLINDEX3) picks out as olivine. On the crater floor Perseverance found an olivine-rich rock (Séítah) that had reacted with carbonated water, with carbonate, sulfate and chloride minerals filling the olivine (Liu et al. 2022, *Science*).
- **Nearby rover work:** the Mageik delta front core (sol 579) was taken at about 1080, 450, roughly 250 m north of this stop; the Kukaklek delta core (sol 623) at about 950, 620.
- **Why it matters:** olivine is the rock that turns into carbonate when it meets carbon-dioxide-rich water, so it links the water story to the carbonates on the western rim.
- **What to sample:** loose surface material and one rock sample.
- **Photo:** none. The old Margin Unit carbonate photo was removed because this stop is olivine, not carbonate.

## Why there is no carbonate stop

Inside our 2 km square the CRISM carbonate signal is too weak to call (13 cells). The strong carbonate is in the Margin Unit about 3 to 4 km west, where Perseverance cored Turquoise Bay (sol 942) and Bunsen Peak (sol 1088, about 75% carbonate cemented by silica). It is inside the 12 km research square but outside our walk. In the pitch, mention it as "the next walk west".
