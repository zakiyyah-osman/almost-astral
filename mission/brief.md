# Mission brief

DRAFT. Items marked **(check)** are from memory and need a source before we say them in the pitch. Items marked **(assumption)** are our own choices.

## Science goal

Where in this walkable area did groundwater once flow, and which stops give a two-person crew the most evidence of it in one safe outing?

## Site

- **Mount Sharp (Aeolis Mons), Gale Crater**, the challenge's own example area, with the boxwork ridges. **(check: exact boxwork location and which unit it sits in)**
- Why: a crew could study ancient water here in one place. Boxwork ridges are thought to be rock cracks that groundwater once cemented. Curiosity has ground-level photos of nearby terrain. **(check)**
- Data: HiRISE terrain (MRO), CRISM minerals (MRO), THEMIS thermal (Mars Odyssey), Curiosity weather (REMS) and radiation (RAD). Which of these cover our 2 km square is confirmed on Saturday when the official data arrives.
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
| Radiation dose for the outing | 1000 µSv | `radiation_limit_usv`; baseline surface rate in our data is about 27 µSv/h |
| Slope | set in `terrain/thresholds.toml` | Nahla owns this |
| Distance from the rover | the whole site, 2 km square | worst case about 1.5 km from shelter |
| Gravity used in maths | 3.71 m/s² | Mars value |
| Walking pace | from `plan.json` (leg distance over walking time) | Shown live in the HUD. **(assumption)** Whether suit and kit slow the pace is Tushaar's model: agree a sourced figure and add it to `plan.json` as `mobility.note` |

Oxygen and battery are not in the data. The HUD simulates them from the 360 min limit.

## What could go wrong

- **Solar storm:** the dose rate jumps. The crew stops sampling and takes the shorter way back to the rover along the planned route, which already avoids the hazards. The HUD shows a red alert and the new dose.
- **Dust:** visibility and solar power drop. The route stays on the planned path and the crew turns back early if the time limit gets close. **(assumption)**
- **Suit fault or injury:** the crew turns back at once. The "time back to shelter" number is always on screen so they know how long it takes.
- **Hazard on the route:** red cells (too steep, loose sand or rock) are never on the route. If the real data shows one on the path, Tushaar re-plans.
