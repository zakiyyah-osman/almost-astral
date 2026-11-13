# Requirements

Built from the wording of the challenge text, not from our task list. Each row says what the challenge asks for, which task covers it, and where it stands. Update the **Status** column as work lands.

The challenge uses "may", "might" and "if possible" for most things, so only the first table is strictly asked for. Anything with no task is a gap.

Last updated: 12 Nov 2026 (before the official data arrives).

## Core: what the challenge asks for

| # | Requirement | Task and owner | Status |
| --- | --- | --- | --- |
| 1 | A map, tool or interface an astronaut could use on a surface mission | Web app (Loick), helmet HUD (Zakiyyah) | Built |
| 2 | A layered, integrated view using data from **multiple NASA missions** | Data layers (Yaj) | Layout works, data is **fake** until Saturday |
| 3 | Hyperlocal: the scale of one spacewalk, not a global or regional map | 2 km site and grid (Yaj) | Grid works, **real site not chosen** |
| 4 | Helps plan and carry out a Marswalk with new science: a science goal and a location | Mission brief and stops (Zakiyyah) | Drafts, facts marked "(check)" |

## Strongly signalled: "consider", and safety is NASA's first priority

| # | Signal in the challenge | Task and owner | Status |
| --- | --- | --- | --- |
| 5 | At least three kinds of data (optical, thermal, spectral, topographic, radiation and so on) | Layers (Yaj) | Relief, thermal, minerals exist but are fake |
| 6 | Safety information such as radiation or space weather | Radiation table (Yaj), dose and storm alert (Zakiyyah) | Alert and dose built, dose numbers fake and, at Jezero, modelled not measured. HUD shows **real** NASA DONKI storm data (`space_weather.csv`) |
| 7 | A route that avoids large rock formations and other obstacles | Hazard map (Nahla), route planner (Tushaar) | Fake straight route, code still stubs |
| 8 | Mobility in a spacesuit with equipment | Walking speed (Tushaar), brief and HUD pace (Zakiyyah) | HUD shows pace from the plan. **Gap**: a sourced suit and kit slowdown, in Tushaar's model |

## Optional: "you may"

| Idea in the challenge | Status |
| --- | --- |
| Format: HUD, tablet or habitat display | HUD built, with a full-screen visor view |
| Point-of-view photos so the crew knows what to expect | Not started |
| Rovers or crew working in pairs | Rover and two crew in the plan |
| Choose a time frame, or none | **Not decided** (the fake data uses sol 40) |
| A tool that makes maps for other sites | The file format allows it, nobody is building it |

## Open decisions

- The site: **Jezero crater** (team decision, 12 Nov). Radiation there is modelled, not measured, because Perseverance has no RAD equivalent: say so on screen.  Yaj's `data/site.json` now points at the Jezero delta front.
- The time frame, or "none".
- The limits in `mission/brief.md` (360 min outing, 1000 µSv dose): they are our assumptions.

## Not covered here

The judging criteria are not in the challenge text. Check the event page before the pitch.

## Extras that are not requirements

Large-text mode for projectors and the astronaut dot on the main map help the demo. They come after everything above.
