# Mission brief

DRAFT. Items marked **(check)** are from memory and need a source before we say them in the pitch. Items marked **(assumption)** are our own choices.

## Science goal

Where did a river once flow into this lake, and which stops give a two-person crew the most evidence of that water in one safe outing?

## Site

- **Jezero Crater, eastern lobe of the delta front**, where Perseverance works. Our 2 km square is centred at 18.46°N, 77.40°E (`data/site.json`), about 3 km west of Perseverance's landing site, Octavia E. Butler Landing (about 18.44°N, 77.45°E). We picked the centre by eye on the USGS HiRISE mosaic; it is our choice, not a published point. **In the pitch say "Jezero crater, about 3 km west of where Perseverance landed"** and do not quote the crater-centre figure (18.38°N, 77.58°E): it appears only on Wikipedia, and a search on 14 Nov found no NASA page that gives it.
- Why: Jezero held a lake and a river delta billions of years ago. Perseverance's first peer-reviewed results (Mangold et al. 2021, *Science* 374) read the inclined layers at the delta front as a delta building out into a standing lake, topped by boulder layers left by floods. NASA/JPL and Mars 2020 papers also describe thin Fe/Mg clay-bearing layers along the delta front, and carbonate-rich rock in the Margin Unit along the crater's western rim. **The Margin Unit is not in our 2 km square:** the CRISM layer finds carbonate in only 13 of 160,000 cells (checked 14 Nov). It lies 3 to 4 km west, where Perseverance cored Turquoise Bay and Bunsen Peak (see `minerals.md` and `stops.md`).
- Data: HiRISE terrain (MRO), CRISM minerals (MRO), THEMIS thermal (Mars Odyssey), Perseverance weather (MEDA). Which of these cover our 2 km square is confirmed once the official data arrives.
- **Radiation is modelled, not measured here.** Curiosity's RAD instrument measures the dose at Gale; Perseverance carries no equivalent. We estimate the surface dose from published Curiosity figures and say so on screen. Perseverance's MEDA measures solar radiation (UV, visible, infrared), not ionizing dose. **(checked in a web search 13 Nov: no Perseverance dose instrument found. Still worth asking the mentor)**
- Local grid: 2000 m x 2000 m, 5 m per cell (see `CONTRACT.md`).

## Crew setup

- Two astronauts walk together. The rover stays parked at the start and is the shelter.
- Everyone carries the helmet HUD from `web/src/hud/`: heading, next stop, time back to the rover, oxygen, battery, radiation.
- Mission control (the planning view) picks stops and checks the route before the crew leaves.

## Limits

All **(assumption)** until the team agrees them. They sit in `plan.json` under `budgets`.

| Limit | Value | Note |
| --- | --- | --- |
| Total outing | 360 min | `eva_max_min` |
| Planned walk plus sampling | about 165 min with 3 stops | leaves a large safety margin |
| Radiation dose for the outing | 1000 µSv | `radiation_limit_usv`. Dose rate is a modelled estimate at Jezero (see Site); the fake data currently uses about 27 µSv/h |
| Slope | set in `terrain/thresholds.toml` | Nahla owns this |
| Distance from the rover | the whole site, 2 km square | worst case about 1.5 km from shelter |
| Gravity used in maths | 3.71 m/s² | Mars value |
| Walking pace | from `plan.json` (leg distance over walking time) | Shown live in the HUD. **(assumption)** Whether suit and kit slow the pace is Tushaar's model: agree a sourced figure and add it to `plan.json` as `mobility.note` |

Oxygen and battery are not in the data. The HUD simulates them from the 360 min limit.

## What could go wrong

- **Solar storm:** the dose rate jumps. The crew stops sampling and takes the fastest way back to the rover. The route planner computes that path from every point on the route (`storm_replan` in `plan.json`) over ground that avoids the hazards, and the HUD follows it with the planner's minutes. Without that data the HUD turns round on the planned route. The HUD shows a red alert and the new dose. The real DONKI storm data in `space_weather.csv` is about the Sun, so it applies at Jezero as it does anywhere on Mars.
- **Dust:** visibility and solar power drop. The route stays on the planned path and the crew turns back early if the time limit gets close. **(assumption)**
- **Suit fault or injury:** the crew turns back at once. The "time back to shelter" number is always on screen so they know how long it takes.
- **Hazard on the route:** red cells (too steep, loose sand or rock) are never on the route. Checked on the real hazard map (14 Nov): 3% of the square is red and 13% yellow, mostly the delta scarps and the rims of mesas and craters. All three stops are on green cells, and the planned route crosses no red cells. The rover waypoint (1000, 900) sits on a yellow cell at the foot of the delta scarp; Tushaar's walking-only plan (PR 18) moves the start to a safe cell at 1017.5, 1112.5.
