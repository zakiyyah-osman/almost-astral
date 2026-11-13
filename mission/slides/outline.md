# Slide outline

DRAFT. One idea per slide, about 6 slides for a 2 to 3 minute pitch. *(Brackets)* change when the real data is in. Replace every placeholder claim before presenting.

## 1. Title

**Martian Map: a safe walk on Jezero.** Almost Astral, NASA Space Apps 2026, Interplanetary Survival Guide.
One line: "A layered map and helmet display that plan and guide a two-person Marswalk."

## 2. The problem

- A Marswalk outing has to balance science, distance, time, and radiation, far from shelter.
- Today that information sits in separate NASA datasets from different missions.
- Our question: where did a river once flow into this lake, and what is the safest way to see the evidence in one outing?

## 3. One map, many missions

Screenshot of the Planning view with layers on.
- Terrain: HiRISE (MRO). Minerals: CRISM (MRO). Thermal: THEMIS (Mars Odyssey). Weather: MEDA (Perseverance). Solar storms: DONKI.
- Everything on one 2 km grid at 5 m per cell, so layers line up.
- *(Say plainly which layers are real and which are still placeholders.)*

## 4. Safe route and science stops

Screenshot of the route and stops, with the Plan card visible.
- Three stops tell one story: clay (early water), delta layers (water flowing in), carbonates (the water's chemistry).
- The route stays out of no-go cells, and the app checks that itself and reports it.
- Total time against the 360 minute allowance, walking distance, radiation dose.

## 5. The crew's view

Screenshot of the HUD mid-walk.
- Heading, distance to the next stop, time back to the rover, oxygen, battery, radiation.
- Solar storm: the HUD turns red and the crew takes the shorter way back.
- Storm data on the HUD is real NASA DONKI data.

## 6. What is real and what is estimated

The slide that earns trust.
- Real: NASA mission data for each layer, DONKI solar storms. *(update when the files load)*
- Estimated, and labelled on screen: radiation dose at Jezero (Perseverance has no dose instrument, so we scale published Curiosity RAD figures), the 360 min and 1000 µSv limits, walking pace, oxygen and battery.
- AI tools helped us build it. We checked every number and claim ourselves (see `docs/ai-use.md`).

## 7. Close

- What it does: plan, check and carry out a Marswalk from one view.
- Next: more sites, real suit and kit data, point-of-view photos.
- Thank you, and where to find the app and code. *(Add the link.)*
