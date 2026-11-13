# Mission brief

DRAFT. Items marked **(check)** are from memory and need a source before we say them in the pitch. Items marked **(assumption)** are our own choices.

## Science goal

Where did a river once flow into this lake, and which stops give a two-person crew the most evidence of that water in one safe outing?

## Site

- **Jezero Crater, delta area**, where Perseverance works. Crater centre about 18.38°N, 77.58°E; the landing site (Octavia E. Butler Landing) is about 18.44°N, 77.45°E. **(check: these come from Wikipedia, confirm on a NASA page; the exact 2 km square is still to choose)**
- Why: Jezero held a lake and a river delta billions of years ago. NASA/JPL and Mars 2020 papers describe thin Fe/Mg clay-bearing layers along the delta front, and carbonate-rich rock in the Margin Unit along the crater's western rim, so one crew could read the history of the water in one place. **(source: NASA/JPL news and Mars 2020 abstracts; where the unit sits relative to our 2 km square is still to check)**
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

- **Solar storm:** the dose rate jumps. The crew stops sampling and takes the shorter way back to the rover along the planned route, which already avoids the hazards. The HUD shows a red alert and the new dose. The real DONKI storm data in `space_weather.csv` is about the Sun, so it applies at Jezero as it did at Gale.
- **Dust:** visibility and solar power drop. The route stays on the planned path and the crew turns back early if the time limit gets close. **(assumption)**
- **Suit fault or injury:** the crew turns back at once. The "time back to shelter" number is always on screen so they know how long it takes.
- **Hazard on the route:** red cells (too steep, loose sand or rock) are never on the route. Jezero has boulder fields and steep delta scarps, so check them on the real data. If one lands on the path, Tushaar re-plans. **(check)**
