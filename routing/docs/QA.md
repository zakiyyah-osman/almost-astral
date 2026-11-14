# routing/ QA plan

Independent checks for the route planner. They are derived only from `routing/CLAUDE.md`, `CONTRACT.md` and `DESIGN.md`, not from the code or from `CHECKLIST.md`, so they test what was asked for and not what was built.

Most checks read the planner's output files and recompute the answer a second way. The tool that does this is in Appendix A. It imports nothing from `routing/`.

## How to use this file

- Groups A to J can each run as soon as the part they test exists ("Run when"). Section "Full run" lists the order for running everything at the end.
- Write `P` or `F` in the last column. A check that cannot run yet stays empty.
- Any `F` in groups C, D, F or G blocks a merge into `main`.
- Default config values are assumed unless a row says otherwise. Rows that change a parameter use a temporary copy of the config, passed with `--config`. Never edit `routing/config.toml` for a check.

### Options and assumptions

- **Command-line options** are those in DESIGN section 2. `plan_route.py` takes `--in DIR`, `--out DIR` and `--config FILE`. `analysis.py` takes `--in DIR`, `--config FILE` and `--reports DIR`. Every synthetic-site check passes `--in` and `--out`, so `data/out/` is written only in group H.
- **Slope method.** Nahla's slope method is still an open question (DESIGN section 12). The audit uses central differences and allows 1° over the limit, so a method difference at the edge of a steep band does not give a false failure.

### Setup (once per session, PowerShell, from the repository root)

```powershell
.venv\Scripts\Activate.ps1
$QA = "$env:TEMP\aa-qa"
New-Item -ItemType Directory -Force $QA | Out-Null

# extract Appendix A to $QA\qa_tools.py
python -c "import re,pathlib; f=chr(96)*3; t=pathlib.Path('routing/docs/QA.md').read_text(encoding='utf-8'); pathlib.Path(r'$QA\qa_tools.py').write_text(re.findall(f+'python\n(.*?)'+f,t,re.S)[-1],encoding='utf-8')"

# build the synthetic sites
foreach ($k in "flat","plane10","yellow_all","yellow_patch","wall","ridge","ring","red_stop") {
  python $QA\qa_tools.py site $k $QA\sites\$k
}

# The starts always come from the config ([starts.L1], [starts.L2], [starts.L3]; L1 is the default),
# so the QA runs use a copy of routing/config.toml with the three starts on the QA sites: all in the
# west, clear of every feature. Every Cfg copy is made from it. The copy still holds the hashes of the
# real data/out files, so every QA plan has two "not the file the starts were computed on" warnings:
# that is expected and not a failure.
python $QA\qa_tools.py config $QA\cfg\base1.toml starts.L1 "[26.25, 101.25]"
python $QA\qa_tools.py config $QA\cfg\base2.toml starts.L2 "[26.25, 76.25]"  $QA\cfg\base1.toml
python $QA\qa_tools.py config $QA\cfg\base.toml  starts.L3 "[26.25, 126.25]" $QA\cfg\base2.toml
$CFG = "$QA\cfg\base.toml"
function Plan($site, $tag = $site, $cfg = $CFG)  { python routing/plan_route.py --in $QA\sites\$site --out $QA\out\$tag --config $cfg; "exit code $LASTEXITCODE" }
function Audit($site, $tag = $site, $cfg = $CFG) { python $QA\qa_tools.py audit $QA\sites\$site $QA\out\$tag $cfg }
function Hash($tag)                              { python $QA\qa_tools.py hash $QA\out\$tag }
# Cfg writes $QA\cfg\<tag>.toml, a copy of $CFG with one value changed, and returns its path
function Cfg($tag, $key, $value)                 { python $QA\qa_tools.py config $QA\cfg\$tag.toml $key $value $CFG }
```

A parameter check is written `Plan flat a5 (Cfg a5 walking.v_flat_kmh 4.7)`: build the changed copy, then run site `flat` into `$QA\out\a5` with it. `routing/config.toml` is only read (to make `$CFG`).

`Audit` prints one `PASS` or `FAIL` line per check ID (`G01`, `H04`, ...) and ends with `ALL PASS` or the number failed. The tables below say which IDs matter in each group.

### The synthetic sites

All are 120 x 80 cells of 2.5 m (300 m x 200 m): not square, not 400, not 5. Start (waypoint kind `start`, and `starts.L1`, the default, in `$CFG`) at `[26.25, 101.25]`, `stop1` "QA East" at `[276.25, 101.25]`, `stop2` "QA North-East" at `[276.25, 151.25]`. The round trip on open flat ground is 570.7 m on an 8-neighbour grid.

| Site | Terrain | Hazard | Tests |
| --- | --- | --- | --- |
| `flat` | flat | all green | walking speed, timeline, radiation |
| `plane10` | 10% slope everywhere | all green | slope factor |
| `yellow_all` | flat | all yellow | planning cost against physical time |
| `yellow_patch` | flat | yellow block, x 100–200 m, y 60–140 m, across the direct line | profile ordering |
| `wall` | flat | red wall with a stretch of cells that touch only at corners; real gap only in the southern 12.5 m | red cells, diagonal squeeze |
| `ridge` | 30° scarp at x 137.5–162.5 m; gentle ramp only in the northern 25 m | all green | slope limit and buffer, without help from red cells |
| `ring` | flat | `stop2` enclosed by red | unreachable stop |
| `red_stop` | flat | `stop1` on a red cell | blocked stop |

---

## A. Config, gravity and static checks

**Run when:** `config.toml` and config loading exist. A4 to A7 need a full run.

| ID | How to run | Expected | P/F |
| --- | --- | --- | --- |
| A1 | Open `routing/config.toml`. | Every parameter is a table with `value`, `unit`, `type`, `source`. `type` is `observation`, `proxy` or `scenario`. No empty `source`. Values match DESIGN section 10. | |
| A2 | `Select-String -Path routing\*.py -Pattern '\b(400\|2000\|9\.81?\|6371\|3396190)\b\|haversine\|Jezero\|Gale'` | No match in code. Grid size, cell size, Earth gravity, planet radii and site names do not appear. Matches in comments about sources are fine. | |
| A3 | `Select-String -Path routing\*.py -Pattern '\b(2\.7\|3\.4\|3\.5\|0\.05\|3\.71\|0\.9\|0\.64\|8\.1\|360\|252\|1000\|15\|20\|25\|30)\b'` | No parameter value is typed into code (no magic numbers). Each match is either a unit conversion (60, 1000, 24) or needs an explanation. | |
| A4 | By hand: `sqrt(0.5 × 3.71 × 0.9)` | 1.292 m/s = 4.65 km/h. If the planner prints or stores its limit, it shows the same number. | |
| A5 | `Plan flat a5 (Cfg a5 walking.v_flat_kmh 4.7)` | Non-zero exit. Message names `v_flat` and the 4.65 km/h limit. `$QA\out\a5` is empty or missing. | |
| A6 | `Plan flat a6 (Cfg a6 sensitivity.v_flat_kmh '[2.7, 4.7]')` | Refused in the same way: a sensitivity value over the limit also stops the run. | |
| A7 | `Plan flat a7 (Cfg a7 walking.v_flat_kmh 4.6)` | Runs (4.6 is under 4.65). `profiles.fastest.walk_min` is 7.4. | |
| A8 | `Plan ridge a8 (Cfg a8 walking.gravity_m_s2 3.0)`, then `Plan ridge` with the default. `Hash a8` and `Hash ridge`. | The three route files and `shelter_time.png` have the same hashes in both. Gravity enters only through the walking-speed check and never relaxes the slope limit. `plan.json` differs only inside `assumptions`. | |
| A9 | `pytest routing/tests -q` | All pass, none skipped without a stated reason. | |

## B. Grid and coordinates

**Run when:** route files are written. Run `Plan flat; Audit flat`, then `Plan wall; Audit wall`.

| ID | How to run | Expected | P/F |
| --- | --- | --- | --- |
| B1 | Audit lines `C01`, `C02` | Rasters are `height x width` as in `layers.json`; `plan.json` `inputs.grid` repeats 120, 80, 2.5. | |
| B2 | Audit lines `G01`, `G02` | Each route file is a `FeatureCollection` with one `LineString`; every vertex lies inside 0–300 m by 0–200 m. | |
| B3 | Audit line `G03` | Every vertex is a cell centre: `x = (c + 0.5) × 2.5`, `y = (80 − r − 0.5) × 2.5`. | |
| B4 | Audit lines `G04`, `G06` | The line starts and ends at the start cell and visits `stop1` then `stop2`. A swapped x and y, or a north–south flip, fails here: the site is not square and the stops are not mirror images. | |
| B5 | Audit line `G05` | Every segment runs along one of the 8 grid directions (dropping vertices on straight runs must not change the line). | |
| B6 | On `wall`: read the y values in `route.geojson`. | Some vertex has `y < 12.5` (the gap is at the **south** edge). If the route goes to `y > 187.5` instead, rows are read upside down. | |
| B7 | `Audit flat`, lines `S01`, `S05` | `shelter_time.png` is 120 x 80 RGBA; track hazard classes equal `hazard.tif` at the same cell. | |
| B8 | On `flat`: `profiles.fastest.distance_m` | 571 (± 1). 250 m east, 50 m north, then 20 diagonal and 80 straight steps back. Proves distances are grid metres, not degrees. | |

## C. Hard constraints

**Run when:** the hard mask and search exist. Run `Plan` and `Audit` on `wall`, `ridge`, and later on the real site (H3). All three route files are checked each time.

| ID | How to run | Expected | P/F |
| --- | --- | --- | --- |
| C1 | `Audit wall`, line `H01` | 0 red cells on every route. | |
| C2 | `Audit wall`, line `H04`; `profiles.*.walk_min` | 0 diagonal moves between two blocked cells. Every profile's `walk_min` is above 16. A value near 12.9 means a route slipped through the corner-touching stretch. | |
| C3 | `Audit ridge`, line `H02` | Highest terrain slope on any route is at most 20° (the audit allows 21°). | |
| C4 | `Audit ridge`, line `H03` | 0 route cells within `cliff_buffer_m` (5 m) of an over-limit cell. | |
| C5 | On `ridge`: in each route file, list vertices with `132.5 < x < 167.5`. | All have `y > 180`: the scarp is crossed only on the northern ramp. Hazard is all green here, so this is the routing slope limit acting on its own. | |
| C6 | `$c = Cfg c6 constraints.cliff_buffer_m 0; Plan ridge c6 $c; Audit ridge c6 $c`. Then `Plan ridge c6b (Cfg c6b constraints.cliff_buffer_m 12.5)`. | With 0: still passes `H02`. With 12.5: the crossing moves further north (smallest crossing `y` is larger than in C5) or the run fails naming a stop. The buffer changes the mask; it is not decoration. | |
| C7 | `Plan ridge c7 (Cfg c7 constraints.slope_max_deg 3)` | Non-zero exit naming `stop1` as unreachable: the northern ramp is 4.1°, so it is now blocked too. Shows the limit comes from config. | |
| C8 | `Audit` on any site, line `S06` | Storm return paths also avoid every blocked cell. | |

## D. Planning cost against physical time, and profiles

**Run when:** the three profiles and the sweep exist.

| ID | How to run | Expected | P/F |
| --- | --- | --- | --- |
| D1 | `Plan yellow_all; Audit yellow_all`. Read `profiles` in `plan.json`. | All three profiles: `distance_m` 571, `walk_min` 12.7, `risk_min` 12.7. Uniform risk cannot change the path, so the time must not move with w. `walk_min` of 25.4 (balanced) or 76.1 (safest) means planning cost leaked into a reported time. | |
| D2 | Same run: `totals`, `sweep`, track point at `stop1`. | `totals.walk_min` 13, `totals.total_min` 78, every sweep row has `walk_min` 12.7. The track point at `[276.25, 101.25]` has `shelter_min` 20.6 (15 + 250 m at 45 m/min): the back-to-start map uses w = 0. | |
| D3 | `Plan yellow_all d3 (Cfg d3 profiles.w_safest 50)`. Compare with D1. | `route_safest.geojson` has the same coordinates, `distance_m` and `walk_min`; only `w` differs. `totals`, `legs`, `track` and `radiation_dose_usv` are unchanged. | |
| D4 | Any audit, lines `T01`, `T02` | Distance and physical minutes recomputed from the route coordinates alone (no w involved) equal the reported values for each profile. | |
| D5 | Any audit, lines `T03`, `T04`, `T05` | `yellow_min` matches the recomputation; `yellow_min + steep_min + near_red_min = risk_min`; `steep_min` is 0.0; each file's `w` equals its config value. | |
| D6 | Any audit, line `B02` | `totals.walk_min` and the leg sums equal the balanced profile's physical `walk_min`. | |
| D7 | `Plan yellow_patch; Audit yellow_patch`, lines `P01`, `P02` | `walk_min`: fastest ≤ balanced ≤ safest. `risk_min`: safest ≤ balanced ≤ fastest. | |
| D8 | Same run, read the numbers. | Fastest: 571 m, 12.7 min, risk 2.2 (straight through the yellow). Balanced and safest: about 604 m, 13.4 min, risk 0.0 (round the corner). The ordering in D7 is strict here, so the profiles really differ. | |
| D9 | Any audit, line `P03` | Two profiles with identical coordinates report identical time and distance. | |
| D10 | Any audit, lines `P04`, `P05` | Down the sweep, `walk_min` never falls and `risk_min` never rises as w grows. The rows for w = 0, 1 and 5 equal the three profiles. | |
| D11 | `Plan plane10`. Read `profiles.fastest.walk_min`. | 18.0 (12.68 min ÷ `exp(−0.35)` = 0.705). Same speed uphill and downhill. | |
| D12 | `Plan flat d12 (Cfg d12 walking.v_flat_kmh 3.4)` | `walk_min` 10.1 (570.7 m at 56.7 m/min). Same coordinates as the 2.7 km/h run. | |
| D13 | `Plan wall; python routing/analysis.py --in $QA\sites\wall --config $CFG --reports $QA\reports\wall`. Open `sweep.csv` and `sensitivity.csv` there. | Sweep: one row per value in `profiles.sweep_w`, equal to `sweep` in `$QA\out\wall\plan.json` (which `plan_route.py` wrote). Sensitivity: 18 rows (2 x 3 x 3); each has walk, total and risk minutes and a budget status, or `infeasible` with a stop id. Rows with `slope_max_deg` 15 never have a shorter walk than the matching rows with 25. | |

## E. Back-to-start map and storm re-plan

**Run when:** back-to-start map and storm paths exist.

| ID | How to run | Expected | P/F |
| --- | --- | --- | --- |
| E1 | `Audit flat`, lines `S03`, `S04` | The first track point is at the start with `shelter_min` 15.0 (ingress only). Everywhere, `15 ≤ shelter_min ≤ elapsed_min + 15`. | |
| E2 | On `flat`: track point at `stop1`. | `shelter_min` 20.6. | |
| E3 | `Audit wall`, line `S02`; open `$QA\out\wall\shelter_time.png`. | Red cells are fully transparent. Colours get "later" away from the start, with a visible jump across the wall, and contour lines every 10 min. | |
| E4 | On `ring`'s inputs with `stop2` moved outside the ring (edit its coordinates to `[276.25, 51.25]`), `Plan ring e4`; open the PNG. | The inside of the ring is transparent (unreachable cells have no value). | |
| E5 | Any audit, lines `S06`, `S07` | Each storm point's path ends at the start, `return_min` is at least 15 and no worse than walking back the way they came; `worst` indexes the largest `return_min`. | |
| E6 | `plan.json` `shelter_map` | `includes_ingress` true, `contour_interval_min` 10, `colour_max_min` 60, and a list of colour stops. | |

## F. Timeline, budgets and radiation units

**Run when:** `plan.json` is complete. Base run: `Plan flat; Audit flat`.

| ID | How to run | Expected | P/F |
| --- | --- | --- | --- |
| F1 | Audit lines `B01`, `B03`, `B04` | Legs chain start → stop1 → stop2 → start (the start's id is always `start`, whatever id `waypoints.geojson` uses). `total_min = walk_min + stop_min + ingress_min`. On `flat`: walk 13, stops 50, ingress 15, total 78. | |
| F2 | Audit lines `B05`, `B06` | `usable_min` = 360 × (1 − 30/100) = 252. Checks `reserve`, `abort`, `radiation` are all present with value and limit. | |
| F3 | Audit lines `B07`, `B08` | Each check's `ok` equals the audit's own recomputation. `status` is `ok`. Exit code 0. | |
| F4 | `$c = Cfg f4 timeline.eva_max_min 100; Plan flat f4 $c; Audit flat f4 $c` | Exit code 0. All five files written. A warning is printed. `status` `over_budget`. `reserve` fails (77.7 > 70); `abort` still passes. `B07` and `B08` pass. | |
| F5 | `$c = Cfg f5 timeline.eva_max_min 60; Plan flat f5 $c; Audit flat f5 $c` | `abort` now fails as well (62.7 elapsed + 15 back > 60; `elapsed_min` includes time spent at stops, DESIGN section 8). Exit code 0, files written. | |
| F6 | `Plan flat f6 (Cfg f6 radiation.limit_usv 30)` | `radiation` check fails (dose 34 or 35 > 30); `status` `over_budget`; exit code 0. | |
| F7 | By hand: 0.64 mSv/day ÷ 24. Audit lines `R01`, `R02`. | 26.7 µSv/h. A 180 min EVA gives 80 µSv. On `flat`: 77.7 min gives 34.5, reported as 34 or 35 µSv. `radiation.background_usv_h` is 26.7. | |
| F8 | Audit lines `R03`, `R04` | `solar_event.absorbed_dose_mgy` is 8.1, labelled Gy. No Sv-named field inside `solar_event`. | |
| F9 | `Plan flat f9 (Cfg f9 radiation.solar_event_dose_mgy 8100)` | `radiation_dose_usv` and the `radiation` check are exactly as in the base run. Gy is never added to Sv. | |
| F10 | Audit line `R05`. The fixture's `radiation.csv` has 80 µSv/h at hours 15 and 16. | `csv_median_usv_h` 27, `csv_storm_hours` [15, 16]. `radiation_dose_usv` is still 34 or 35: storm hours are listed, not added. | |
| F11 | In `$QA\sites\flat\radiation.csv` change every 27 to 60. `Plan flat f11`. Change back. | A warning that the CSV median differs from the config rate by more than 25%. The dose is unchanged (config rate is used). | |
| F12 | Audit lines `A01`, `A02`, `A03`, `A04` | `assumptions` is the whole of the config file the run used; no top-level `fake` key; `inputs_fake` is true for the synthetic sites. | |
| F13 | `plan.json`: contract fields. | `crew`, `legs[].from/to/distance_m/walk_min`, `totals.walk_min/stop_min/total_min`, `budgets.eva_max_min/radiation_limit_usv`, `radiation_dose_usv` all present, whole numbers, names unchanged. Added fields use one decimal. No timestamp anywhere. | |

## G. Failures that must stop the run

**Run when:** waypoint checks exist. For each row, first copy a good result into the output folder so "nothing written" can be seen: `Copy-Item $QA\out\flat $QA\out\g -Recurse -Force; Hash g`, run the row with tag `g`, then `Hash g` again.

| ID | How to run | Expected | P/F |
| --- | --- | --- | --- |
| G1 | `Plan ring g` | Non-zero exit. The message contains `stop2`, `QA North-East`, the coordinates `276.25, 151.25` and the word unreachable (or an equal reason). It does not blame `stop1`. Hashes unchanged. No traceback. | |
| G2 | `Plan red_stop g` | Non-zero exit. The message contains `stop1`, `QA East`, `276.25, 101.25` and says the cell is red. Hashes unchanged. | |
| G3 | In `$QA\sites\ridge\waypoints.geojson` move `stop1` to `[151.25, 101.25]` (on the scarp). `Plan ridge g`. Move it back. | Non-zero exit naming `stop1`, reason slope over the limit or inside the buffer. | |
| G4 | In a copy of `flat`, set `stop1`'s `kind` to `"start"` (two starts) and run. Undo, then set the start's `kind` to `"rover"` (the old name) and run. Then run with `--config (Cfg g4 starts.L1 "[151.25, 101.25]")` on `ridge` (the default start on the scarp). | Two starts: non-zero exit, "at most one" start, nothing written. `"rover"`: exit 0, `plan.json` `warnings` says the kind is deprecated, and `legs`, `start.id` and the route files never contain the word `rover` (the id is `start`). Start on the scarp: non-zero exit, the message gives the start, its coordinates and the reason (slope over the limit or the buffer). Nothing written. | |
| G4b | `Plan ridge g (Cfg g4b starts.L3 "[151.25, 101.25]")` (L3, which is not the default, on the scarp). | Non-zero exit. The message names `start 'L3'` and its coordinates, and the reason (slope over the limit or the buffer); it does not name L1 or L2. Nothing written: every start is checked, not only the default. | |
| G5 | In a copy of `flat`, delete `hazard.tif`. Then restore it and set `site.grid.width` to `100` in `layers.json`. | Each: non-zero exit with a message naming the file or the size mismatch. Nothing written. No traceback. | |
| G6 | `Plan flat g` | Back to exit code 0: the good case still works after the failure tests. | |

## H. Contract and `validate.py`, on the shared data

**Run when:** the planner runs end to end. This is the only group that writes to `data/out/`.

| ID | How to run | Expected | P/F |
| --- | --- | --- | --- |
| H1 | `python data/make_fake.py`, then `Get-FileHash data\out\* \| Out-File $QA\before.txt`. `python routing/plan_route.py`. `Get-FileHash data\out\* \| Out-File $QA\after.txt`. `Compare-Object (gc $QA\before.txt) (gc $QA\after.txt)` | Exit code 0. Only `route.geojson`, `plan.json`, `shelter_time.png` changed, and `route_fastest.geojson`, `route_safest.geojson` are new. No input file was touched. | |
| H2 | `python data/validate.py` | Exit code 0, ends with `OK`. The "still uses fake data" warnings for `route.geojson` and `plan.json` are gone. | |
| H3 | `python $QA\qa_tools.py audit data/out data/out` | `ALL PASS`. If only `T02`, `H02` or `H03` fail by a small margin on real terrain, compare slope methods with Nahla before calling it a failure. | |
| H4 | `git status --short` | Changes only in `routing/` and the five routing files in `data/out/`. `CONTRACT.md`, `requirements.txt` and other folders are untouched. | |
| H5 | Compare `route.geojson` with `profiles.balanced` in `plan.json`. | `route.geojson` is the balanced profile (`profile: "balanced"`, `w` 1) and has a `source`. | |
| H6 | `python data/validate.py --strict` | Record the result. It is expected to fail until the input layers are real, and the `shelter_time` layer's `source` in `layers.json` is Yaj's to change (DESIGN section 12). Any strict failure caused by a routing file is an `F`. | |
| H7 | `cd web; npm run build` | Builds without errors. | |

## I. Site-agnostic run and determinism

**Run when:** the planner runs end to end.

| ID | How to run | Expected | P/F |
| --- | --- | --- | --- |
| I1 | Every `Plan` on a synthetic site above. | They ran on a 120 x 80 grid of 2.5 m cells with no code or config change. `Audit` lines `C02`, `S01` pass. `inputs.site` is the fixture's name, not Jezero. | |
| I2 | `Plan wall i2a; Plan wall i2b; Hash i2a; Hash i2b` | All five hashes are equal between the two runs. | |
| I3 | `$env:PYTHONHASHSEED = "12345"; Plan wall i2c; Remove-Item Env:PYTHONHASHSEED; Hash i2c` | Same five hashes as I2. | |
| I4 | Run `python routing/plan_route.py` twice on `data/out/`, hashing after each (`python $QA\qa_tools.py hash data/out`). | Same hashes both times. | |
| I5 | Search `plan.json` for a date, time or host name. | None, apart from the fixed solar-event date `2024-05-20`. | |
| I6 | `Copy-Item $QA\sites\flat $QA\sites\i6 -Recurse`. Hash `data\out\*` as in H1. `python routing/plan_route.py --in $QA\sites\i6 --config $CFG`. Hash `data\out\*` again. | With `--in` set and `--out` not set, the five outputs appear in `$QA\sites\i6`. Nothing in `data/out/` changed. | |
| I7 | Hash `data\out\*` and `routing\reports\*`. `python routing/analysis.py --in $QA\sites\wall --config (Cfg i7 profiles.w_safest 7) --reports $QA\reports\i7`. Hash both again. | `$QA\reports\i7` holds CSV files only (`sweep.csv`, `sensitivity.csv`). `data/out/`, `routing/reports/` and `$QA\sites\wall` are unchanged. `python routing/analysis.py --help` lists no `--out`. | |
| I8 | Run the I7 command twice, into `$QA\reports\i8a` and `$QA\reports\i8b`. `Get-FileHash` both folders. | The CSV files are identical between the two runs. | |

## J. Web app, by eye

**Run when:** after H1. `cd web; npm run dev`, open the page. This reads the app; it does not change Loick's or Zakiyyah's folders. Report problems to them.

| ID | Look at | Expected | P/F |
| --- | --- | --- | --- |
| J1 | Route line against the waypoint markers | The line starts and ends on the start marker and passes each stop marker within half a cell diagonal (about 3.5 m at 5 m cells). Not mirrored, not rotated: a transposed line means `latLng(x, y)` was used in place of `latLng(y, x)`. | |
| J2 | Route over the hazard layer, zoomed in | The line never crosses a red area and never cuts between two red areas that touch at a corner. | |
| J3 | Route over the slope layer | The line avoids the steepest colour and keeps a visible margin from it. | |
| J4 | Back-to-start layer | Aligned with the hazard layer (red areas are holes). Lowest colour at the start, growing outward, with contour lines. The legend matches `plan.json` `shelter_map`. | |
| J5 | Three routes, if the app shows them | Fastest is the most direct, safest stays furthest from yellow and red. Balanced is the default. | |
| J6 | Timeline and totals | Walk, stop, ingress and total minutes equal `plan.json` `totals`. Total includes ingress. | |
| J7 | Budget and status display | Shows usable time 252 of 360 min and the `status`. With the F4 config on real data it shows the over-budget warning, not a blank map. | |
| J8 | Radiation display | Background dose in µSv. The solar-event figure, if shown, is labelled mGy and is not summed with the µSv figure. | |
| J9 | Slope profile or HUD track | Distance runs from 0 to the route length, elapsed time rises steadily, minutes back to the start are 15 at both ends. | |
| J10 | Browser console | No 404 for `route_fastest.geojson`, `route_safest.geojson`, `plan.json` or `shelter_time.png`; no errors reading added `plan.json` fields. | |

---

## Full run

Run everything in this order at the end, about 30 minutes:

1. Setup.
2. `A1`–`A3`, `A9` (no planner run needed).
3. Base runs: `foreach ($k in "flat","plane10","yellow_all","yellow_patch","wall","ridge") { Plan $k; Audit $k }`. All six end with `ALL PASS`. This covers every row that says "audit line".
4. Read-the-number rows: `B6`, `B8`, `C2`, `C5`, `D1`, `D2`, `D8`, `D11`, `E2`, `E6`, `F1`, `F7`, `F13`.
5. Config-change rows, each with its own `Cfg` copy: `A5`–`A8`, `C6`, `C7`, `D3`, `D12`, `F4`–`F6`, `F9`. Then `F11`. Finish with `git diff routing/config.toml`: no difference, because no check edits it.
6. Group G.
7. Group I, then group H, then group J.

Sign-off: date, commit hash, who ran it, count of `P`, `F` and empty rows.

## What this plan does not prove

- That the model is right for Mars. It checks the code against the design; the design's open assumptions (DESIGN section 11) stay open.
- That real-terrain slopes agree with `terrain/`. See assumption 3.
- The hard-mask validation against the Perseverance traverse, which waits on Yaj's data.
- `stop_order: optimise`. Add a check when Zakiyyah decides whether routing may reorder stops.
- The audit's tolerances are 1 m on distance, the larger of 0.2 min or 3% on time, and 1° on slope.

## Appendix A: `qa_tools.py`

Extracted by the setup step. Needs only `numpy`, `rasterio` and `pillow` from `requirements.txt`. Run it from the repository root: `routing/config.toml` is the default config for `audit` and the source for `config`.

```python
"""Independent QA tools for routing/. Reads files only; imports nothing from routing/.

    python qa_tools.py site  <kind> <folder>     build a synthetic input site
    python qa_tools.py audit <in> <out> [config] check planner outputs against the inputs
    python qa_tools.py hash  <out>               print SHA-256 of every routing output
    python qa_tools.py config <dest> <key> <value> [<source config>]
                                                 copy routing/config.toml to <dest> with one value changed
"""
import csv, hashlib, json, math, re, sys, tomllib
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin

W, H, CELL = 120, 80, 2.5            # QA grid: not square, not 400, not 5
ROUTES = {"fastest": "route_fastest.geojson", "balanced": "route.geojson",
          "safest": "route_safest.geojson"}
OUTPUTS = [*ROUTES.values(), "plan.json", "shelter_time.png"]
TYPES = {"observation", "proxy", "scenario"}


# ---------------------------------------------------------------- fixtures
def centre(r, c, rows=H, cell=CELL):
    return [(c + 0.5) * cell, (rows - r - 0.5) * cell]


def make_site(kind, folder):
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    dem = np.zeros((H, W), np.float32)
    haz = np.zeros((H, W), np.uint8)
    start_rc, stop1, stop2 = (39, 10), (39, 110), (19, 110)
    if kind == "plane10":                       # 10 % slope everywhere, rising east
        dem += (np.arange(W) * CELL * 0.10).astype(np.float32)
    elif kind == "yellow_all":
        haz[:] = 1
    elif kind == "yellow_patch":                # x 100-200 m, y 60-140 m
        haz[24:56, 40:80] = 1
    elif kind == "wall":                        # red wall, diagonal stretch, gap in the south
        haz[0:40, 60] = 2
        for i in range(10):
            haz[40 + i, 60 + i] = 2             # cells touch only at corners
        haz[50:75, 69] = 2                      # rows 75-79 stay open
    elif kind == "ridge":                       # 30 deg scarp, gentle ramp in the north rows
        rise = 25 * math.tan(math.radians(30))
        x = np.arange(W)
        dem[10:, :] = (np.clip((x - 55) / 10, 0, 1) * rise).astype(np.float32)
        dem[:10, :] = (np.clip((x - 20) / 80, 0, 1) * rise).astype(np.float32)
    elif kind == "ring":                        # stop2 walled in by red
        haz[14:25, 105:116] = 2
        haz[15:24, 106:115] = 0
    elif kind == "red_stop":
        haz[stop1] = 2
    elif kind != "flat":
        sys.exit(f"unknown kind {kind}")

    for name, arr in (("dem.tif", dem), ("hazard.tif", haz)):
        with rasterio.open(out / name, "w", driver="GTiff", width=W, height=H, count=1,
                           dtype=arr.dtype, transform=from_origin(0, H * CELL, CELL, CELL)) as d:
            d.write(arr, 1)

    def wp(i, name, kind_, rc):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": centre(*rc)},
                "properties": {"id": i, "name": name, "kind": kind_, "why": "QA fixture", "photo": None}}
    feats = [wp("start", "QA Start", "start", start_rc), wp("stop1", "QA East", "stop", stop1),
             wp("stop2", "QA North-East", "stop", stop2)]
    (out / "waypoints.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))

    src = "FAKE: QA synthetic fixture, not mission data"
    layers = {"site": {"name": f"QA site ({kind})", "grid": {"width": W, "height": H, "cell_m": CELL},
                       "extent_m": [W * CELL, H * CELL]},
              "layers": [{"id": "hazard", "title": "Hazards", "file": "hazard.png", "source": src,
                          "default": True, "opacity": 0.7},
                         {"id": "shelter_time", "title": "Minutes back to start", "file": "shelter_time.png",
                          "source": src, "default": False, "opacity": 0.7}],
              "vectors": {"route": "route.geojson", "waypoints": "waypoints.geojson"},
              "tables": {"weather": "weather.csv", "radiation": "radiation.csv"}, "plan": "plan.json"}
    (out / "layers.json").write_text(json.dumps(layers, indent=2))
    with open(out / "radiation.csv", "w", newline="") as f:      # hours 15 and 16 are a storm
        w = csv.writer(f)
        w.writerow(["sol", "local_hour", "dose_rate_usv_h"])
        for h in range(24):
            w.writerow([1, h, 80 if h in (15, 16) else 27])
    print(f"wrote {kind} site ({W} x {H} cells of {CELL} m) to {out}")


# ---------------------------------------------------------------- audit
class Report:
    def __init__(self):
        self.failed = 0

    def __call__(self, cid, ok, detail=""):
        self.failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {cid:<5} {detail}")


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def audit(src, out, config="routing/config.toml"):
    src, out = Path(src), Path(out)
    rep = Report()
    grid = read_json(src / "layers.json")["site"]["grid"]
    cols, rows, cell = grid["width"], grid["height"], grid["cell_m"]
    with rasterio.open(src / "dem.tif") as d:
        dem = d.read(1).astype(float)
    with rasterio.open(src / "hazard.tif") as d:
        haz = d.read(1)
    missing = [n for n in OUTPUTS if not (out / n).exists()]
    rep("G00", not missing, f"all five routing outputs exist in {out}; missing: {missing or 'none'}")
    if missing:
        print("\nFAILED: the remaining checks need every output file")
        return 1
    plan = read_json(out / "plan.json")
    cfg ={k: v["value"] for k, v in plan.get("assumptions", {}).items()}
    wps = {f["properties"]["id"]: f for f in read_json(src / "waypoints.geojson")["features"]}
    start_wp = next(f for f in wps.values() if f["properties"]["kind"] in ("start", "rover"))

    def rc(x, y):                                # contract: row 0 is the north edge
        return rows - 1 - int(y // cell), int(x // cell)

    # independent terrain slope (central differences) and hard mask
    gy, gx = np.gradient(dem, cell)
    rise = np.hypot(gx, gy)
    deg = np.degrees(np.arctan(rise))
    smax, buf = cfg.get("constraints.slope_max_deg", 20), cfg.get("constraints.cliff_buffer_m", 5)
    over = deg > smax + 1.0                      # 1 deg allowance: slope method is not fixed yet
    near = np.zeros_like(over)
    n = int(buf // cell)
    for dr in range(-n, n + 1):
        for dc in range(-n, n + 1):
            if math.hypot(dr, dc) * cell <= buf:
                sh = np.zeros_like(over)
                sh[max(dr, 0):rows + min(dr, 0), max(dc, 0):cols + min(dc, 0)] = \
                    over[max(-dr, 0):rows + min(-dr, 0), max(-dc, 0):cols + min(-dc, 0)]
                near |= sh
    blocked = (haz == 2) | near

    v_flat = cfg.get("walking.v_flat_kmh", 2.7) * 1000 / 60          # m/min
    rate = 1 / (v_flat * np.exp(-cfg.get("walking.tobler_k", 3.5) * rise))   # min/m

    rep("C01", (dem.shape, haz.shape) == ((rows, cols), (rows, cols)), f"rasters are {rows} x {cols}")
    g2 = plan.get("inputs", {}).get("grid", {})
    rep("C02", (g2.get("width"), g2.get("height"), g2.get("cell_m")) == (cols, rows, cell),
        f"plan.inputs.grid = {g2}")

    walked = {}
    for prof, name in ROUTES.items():
        gj = read_json(out / name)
        feats = gj.get("features", [])
        ok = gj.get("type") == "FeatureCollection" and len(feats) == 1 \
            and feats[0]["geometry"]["type"] == "LineString"
        rep("G01", ok, f"{name}: one LineString")
        if not ok:
            continue
        xy, props = feats[0]["geometry"]["coordinates"], feats[0]["properties"]
        inside = all(0 <= x <= cols * cell and 0 <= y <= rows * cell for x, y in xy)
        rep("G02", inside, f"{name}: every vertex inside 0..{cols * cell} x 0..{rows * cell} m")
        on_centre = all(abs((x / cell) % 1 - 0.5) < 1e-6 and abs((y / cell) % 1 - 0.5) < 1e-6 for x, y in xy)
        rep("G03", on_centre, f"{name}: vertices are cell centres")
        home = rc(*start_wp["geometry"]["coordinates"])
        rep("G04", rc(*xy[0]) == home and rc(*xy[-1]) == home, f"{name}: starts and ends at the start cell")

        cells, straight = [rc(*xy[0])], True
        for a, b in zip(xy, xy[1:]):
            (r0, c0), (r1, c1) = rc(*a), rc(*b)
            dr, dc = r1 - r0, c1 - c0
            k = max(abs(dr), abs(dc))
            if k == 0 or (dr and dc and abs(dr) != abs(dc)):
                straight = False
                continue
            cells += [(r0 + dr // k * i, c0 + dc // k * i) for i in range(1, k + 1)]
        rep("G05", straight, f"{name}: every segment runs along one of 8 directions")

        order = plan.get("stop_order", {}).get("order", [])
        pos, visited = 0, True
        for sid in order:
            target = rc(*wps[sid]["geometry"]["coordinates"])
            try:
                pos = cells.index(target, pos)
            except ValueError:
                visited = False
        rep("G06", visited and len(order) == len(wps) - 1, f"{name}: visits every stop in order {order}")

        rr, cc = np.array(cells).T
        rep("H01", not (haz[rr, cc] == 2).any(), f"{name}: red cells on route = {int((haz[rr, cc] == 2).sum())}")
        rep("H02", not over[rr, cc].any(), f"{name}: max terrain slope on route {deg[rr, cc].max():.1f} deg, limit {smax}")
        rep("H03", not near[rr, cc].any(), f"{name}: cells inside the {buf} m buffer = {int(near[rr, cc].sum())}")
        squeeze = sum(1 for (r0, c0), (r1, c1) in zip(cells, cells[1:])
                      if r0 != r1 and c0 != c1 and blocked[r0, c1] and blocked[r1, c0])
        rep("H04", squeeze == 0, f"{name}: diagonal moves between two blocked cells = {squeeze}")

        dist = mins = yellow = 0.0
        for (r0, c0), (r1, c1) in zip(cells, cells[1:]):
            step = cell * math.hypot(r1 - r0, c1 - c0)
            dist += step
            mins += step * (rate[r0, c0] + rate[r1, c1]) / 2
            yellow += step * (rate[r0, c0] * (haz[r0, c0] == 1) + rate[r1, c1] * (haz[r1, c1] == 1)) / 2
        walked[prof] = dict(xy=xy, dist=dist, mins=mins, yellow=yellow, props=props)
        p = plan.get("profiles", {}).get(prof, {})
        rep("T01", abs(dist - props.get("distance_m", -1)) <= 1 and abs(dist - p.get("distance_m", -1)) <= 1,
            f"{name}: recomputed {dist:.1f} m, file {props.get('distance_m')}, plan {p.get('distance_m')}")
        tol = max(0.2, 0.03 * mins)
        rep("T02", abs(mins - p.get("walk_min", -1)) <= tol and abs(mins - props.get("walk_min", -1)) <= tol,
            f"{name}: recomputed physical {mins:.2f} min, plan {p.get('walk_min')}, file {props.get('walk_min')}")
        rep("T03", abs(yellow - p.get("yellow_min", -1)) <= tol,
            f"{name}: recomputed yellow {yellow:.2f} min, plan {p.get('yellow_min')}")
        parts = sum(p.get(k, 0) for k in ("yellow_min", "steep_min", "near_red_min"))
        rep("T04", abs(parts - p.get("risk_min", -1)) <= 0.2, f"{name}: risk parts {parts:.1f} vs risk_min {p.get('risk_min')}")
        rep("T05", props.get("w") == p.get("w") == cfg.get(f"profiles.w_{prof}"), f"{name}: w = {props.get('w')}")

    pr = plan.get("profiles", {})
    if len(pr) == 3:
        t = [pr[k]["walk_min"] for k in ROUTES]
        r = [pr[k]["risk_min"] for k in ROUTES]
        rep("P01", t[0] <= t[1] + 0.05 and t[1] <= t[2] + 0.05, f"walk_min fastest/balanced/safest = {t}")
        rep("P02", r[2] <= r[1] + 0.05 and r[1] <= r[0] + 0.05, f"risk_min fastest/balanced/safest = {r}")
        same = [(a, b) for a in walked for b in walked if a < b and walked[a]["xy"] == walked[b]["xy"]]
        rep("P03", all(pr[a]["walk_min"] == pr[b]["walk_min"] and pr[a]["distance_m"] == pr[b]["distance_m"]
                       for a, b in same), f"identical paths report identical time and distance: {same or 'no identical paths'}")
    sw = sorted(plan.get("sweep", []), key=lambda s: s["w"])
    rep("P04", len(sw) > 1 and all(a["walk_min"] <= b["walk_min"] + 0.05 and b["risk_min"] <= a["risk_min"] + 0.05
                                   for a, b in zip(sw, sw[1:])),
        "sweep: walk_min never falls and risk_min never rises as w grows: "
        + ", ".join(f"w{s['w']}:{s['walk_min']}/{s['risk_min']}" for s in sw))
    for s in sw:
        for k, prof in ((cfg.get("profiles.w_fastest"), "fastest"), (cfg.get("profiles.w_balanced"), "balanced"),
                        (cfg.get("profiles.w_safest"), "safest")):
            if s["w"] == k and prof in pr:
                rep("P05", s["walk_min"] == pr[prof]["walk_min"] and s["risk_min"] == pr[prof]["risk_min"],
                    f"sweep row w={k} equals the {prof} profile")

    tt, bb = plan["totals"], plan["budgets"]
    legs = plan["legs"]
    rep("B01", legs[0]["from"] == "start" == legs[-1]["to"]
        and all(a["to"] == b["from"] for a, b in zip(legs, legs[1:])), "legs chain start -> stops -> start")
    bal = pr.get("balanced", {})
    rep("B02", abs(tt["walk_min"] - bal.get("walk_min", -9)) <= 0.5
        and abs(sum(l["walk_min"] for l in legs) - tt["walk_min"]) <= len(legs) / 2,
        f"totals.walk_min {tt['walk_min']} = balanced physical walk {bal.get('walk_min')} (not the planning cost)")
    ing = cfg.get("timeline.ingress_min")
    rep("B03", tt.get("ingress_min") == ing and abs(tt["total_min"] - (tt["walk_min"] + tt["stop_min"] + ing)) <= 1,
        f"total {tt['total_min']} = walk {tt['walk_min']} + stops {tt['stop_min']} + ingress {tt.get('ingress_min')}")
    rep("B04", tt["stop_min"] == cfg.get("timeline.stop_min_default", 0) * (len(wps) - 1), f"stop_min = {tt['stop_min']}")
    usable = bb["eva_max_min"] * (1 - bb.get("reserve_pct", -1) / 100)
    rep("B05", abs(bb.get("usable_min", -1) - usable) <= 0.5, f"usable_min {bb.get('usable_min')} = {usable:.1f}")
    checks = {c["id"]: c for c in plan.get("checks", [])}
    rep("B06", set(checks) >= {"reserve", "abort", "radiation"}, f"checks present: {sorted(checks)}")
    exact = bal.get("total_min", tt["total_min"])
    truth = {"reserve": exact <= usable + 0.05,
             "radiation": plan["radiation_dose_usv"] <= bb["radiation_limit_usv"],
             "abort": all(p["elapsed_min"] + p["shelter_min"] <= bb["eva_max_min"] + 0.05 for p in plan.get("track", [{}]))
             if plan.get("track") else None}
    rep("B07", all(checks.get(k, {}).get("ok") == v for k, v in truth.items()),
        f"check results match recomputation: {truth}")
    rep("B08", plan.get("status") == ("ok" if all(truth.values()) else "over_budget"), f"status = {plan.get('status')}")

    rate_h = cfg.get("radiation.background_dose_rate_msv_day", 0) * 1000 / 24
    dose = rate_h * exact / 60
    rep("R01", abs(plan["radiation_dose_usv"] - dose) <= 1,
        f"radiation_dose_usv {plan['radiation_dose_usv']} = {rate_h:.1f} uSv/h x {exact} min = {dose:.1f}")
    rad = plan.get("radiation", {})
    rep("R02", abs(rad.get("background_usv_h", -1) - rate_h) <= 0.05, f"background_usv_h = {rad.get('background_usv_h')}")
    ev = rad.get("solar_event", {})
    rep("R03", ev.get("absorbed_dose_mgy") == cfg.get("radiation.solar_event_dose_mgy"),
        f"solar event stays in Gy: {ev.get('absorbed_dose_mgy')} mGy")
    sv_keys = [k for k in ev if "sv" in k.lower()]
    rep("R04", not sv_keys and plan["radiation_dose_usv"] < dose + 1,
        f"no Sv field inside solar_event {sv_keys}; Sv dose holds background only")
    rows_csv = list(csv.DictReader(open(src / "radiation.csv")))
    vals = sorted(float(r["dose_rate_usv_h"]) for r in rows_csv)
    med = float(np.median(vals))
    storm = sorted({int(r["local_hour"]) for r in rows_csv
                    if float(r["dose_rate_usv_h"]) >= cfg.get("radiation.storm_detect_factor", 2) * med})
    rep("R05", abs(rad.get("csv_median_usv_h", -1) - med) <= 0.05 and sorted(rad.get("csv_storm_hours", [-1])) == storm,
        f"csv median {med}, storm hours {storm}; plan {rad.get('csv_median_usv_h')}, {rad.get('csv_storm_hours')}")

    img = Image.open(out / "shelter_time.png")
    rep("S01", img.size == (cols, rows) and img.mode == "RGBA", f"shelter_time.png {img.size} {img.mode}")
    alpha = np.array(img.convert("RGBA"))[..., 3]
    rep("S02", not alpha[haz == 2].any(), "red cells are fully transparent in shelter_time.png")
    track = plan.get("track", [])
    rep("S03", bool(track) and abs(track[0]["shelter_min"] - ing) < 0.05 and track[0]["elapsed_min"] == 0,
        f"track starts at the start with shelter_min = ingress = {ing}")
    rep("S04", bool(track) and all(p["shelter_min"] >= ing - 0.05 for p in track)
        and all(p["shelter_min"] <= p["elapsed_min"] + ing + 0.15 for p in track),
        "every track point: ingress <= shelter_min <= elapsed_min + ingress")
    rep("S05", bool(track) and all(p["hazard"] == int(haz[rc(p["x"], p["y"])]) for p in track)
        and all(a["elapsed_min"] <= b["elapsed_min"] for a, b in zip(track, track[1:])),
        "track hazard classes match hazard.tif and elapsed time never goes back")
    pts = plan.get("storm_replan", {}).get("points", [])
    ok = bool(pts)
    for p in pts:
        path = [rc(*q) for q in p["path"]]
        full = [path[0]]
        for (r0, c0), (r1, c1) in zip(path, path[1:]):
            k = max(abs(r1 - r0), abs(c1 - c0)) or 1
            full += [(r0 + (r1 - r0) // k * i, c0 + (c1 - c0) // k * i) for i in range(1, k + 1)]
        ok &= path[-1] == rc(*start_wp["geometry"]["coordinates"]) and not any(blocked[c] for c in full)
        ok &= p["return_min"] >= ing and p["return_min"] <= p["elapsed_min"] + ing + 0.15
    rep("S06", ok, f"{len(pts)} storm return paths end at the start, avoid blocked cells, beat walking back the way they came")
    worst = plan.get("storm_replan", {}).get("worst")
    rep("S07", bool(pts) and worst is not None and pts[worst]["return_min"] == max(p["return_min"] for p in pts),
        f"storm_replan.worst = {worst}")

    asm = plan.get("assumptions", {})
    rep("A01", bool(asm) and all(set(v) >= {"value", "unit", "type", "source"} and v["type"] in TYPES and v["source"]
                                 for v in asm.values()), f"{len(asm)} assumptions, each with value, unit, type, source")
    cand = Path(config)                         # the file the run was given with --config
    flat = {f"{sec}.{key}": entry
            for sec, body in tomllib.loads(cand.read_text(encoding="utf-8")).items()
            for key, entry in body.items()} if cand.exists() else None
    rep("A02", flat == asm, f"plan.json assumptions equal {cand}" + ("" if flat else " (file not found)"))
    rep("A03", "fake" not in plan and all("fake" not in w["props"] for w in walked.values()),
        "no top-level fake key in plan.json or the route files")
    fake_in = any("FAKE" in l.get("source", "") for l in read_json(src / "layers.json")["layers"])
    rep("A04", plan.get("inputs", {}).get("inputs_fake") == fake_in, f"inputs_fake = {fake_in}")

    print(f"\n{'ALL PASS' if not rep.failed else str(rep.failed) + ' FAILED'}")
    return rep.failed


def hashes(out):
    for name in OUTPUTS:
        p = Path(out) / name
        print(hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING".ljust(64), name)


def make_config(dest, key, value, source="routing/config.toml"):
    """Copy the config with the `value` of table [key] replaced. The source is only read."""
    text = Path(source).read_text(encoding="utf-8")
    pattern = rf"(?m)^(\[{re.escape(key)}\][^\n]*\n(?:(?!\[)[^\n]*\n)*?value[ \t]*=[ \t]*)[^\n]*$"
    new, n = re.subn(pattern, lambda m: m.group(1) + value, text, count=1)
    if n != 1:
        sys.exit(f"no [{key}] table with a value line in {source}")
    tomllib.loads(new)                            # fail here, not in the planner, on a bad value
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(new, encoding="utf-8")
    print(dest)


if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "site" and len(args) == 2:
        make_site(*args)
    elif cmd == "audit" and len(args) in (2, 3):
        sys.exit(1 if audit(*args) else 0)
    elif cmd == "hash" and len(args) == 1:
        hashes(*args)
    elif cmd == "config" and len(args) in (3, 4):
        make_config(*args)
    else:
        sys.exit(__doc__)
```
