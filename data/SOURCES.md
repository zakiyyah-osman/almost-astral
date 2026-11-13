# Where to get the real data

Download into `data/raw/` (Git ignores it), point `data/site.json` at the file, then run `python data/build_real.py`. Use the venv: `.venv\Scripts\python` on Windows. Check every raster first with `python data/inspect_raw.py <file>`: it tells you whether the site centre is inside the file.

**Site:** Jezero crater, western delta front. The centre in `data/site.json` (18.46 N, 77.40 E) is approximate: check it on the HiRISE image with `inspect_raw.py` and move it so the 2 km square sits on the delta front.

| Layer | Best source | Folder | site.json block |
| --- | --- | --- | --- |
| Terrain (`dem.tif`) | USGS Mars 2020 TRN HiRISE DTM mosaic, or a single HiRISE DTM | `raw/hirise/` | `hirise.dtm` |
| Image (`hirise.png`) | USGS Mars 2020 TRN HiRISE orthomosaic, 25 cm | `raw/hirise/` | `hirise.image` |
| Thermal (`thermal.png`) | THEMIS quantitative thermal inertia mosaic, 100 m | `raw/themis/` | `themis.file` |
| Minerals (`minerals.png`) | CRISM MTRDR summary parameters | `raw/crism/` | `crism.minerals` |
| Weather (`weather.csv`) | Perseverance MEDA derived data (PDS) | `raw/meda/` | `meda` |
| Radiation (`radiation.csv`) | Estimate from Curiosity RAD's published average (no download) | none | `rad.estimate` |
| Solar storms (`space_weather.csv`) | NASA DONKI API (no download) | none | `donki` |

## Terrain and image (HiRISE, Mars Reconnaissance Orbiter)

- **Easiest for Jezero:** USGS made a HiRISE terrain mosaic and orthomosaic of the landing area for Mars 2020's Terrain Relative Navigation. They cover the delta front. [DTM mosaic](https://www.usgs.gov/data/mars-2020-terrain-relative-navigation-hirise-dtm-mosaic) (DOI 10.5066/P9REJ9JN) and [orthomosaic, 25 cm](https://astrogeology.usgs.gov/search/map/Mars/Mars2020/JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first) (DOI 10.5066/P9QJDP48). Both are large.
- **Single HiRISE products:** the [HiRISE DTM list](https://www.uahirise.org/dtm/) has Jezero stereo pairs (`DTEEC_..._.IMG` is the terrain, `..._RED_..._ORTHO.JP2` the image). Use one if the mosaic is too big.
- Settings: `hirise.dtm` and `hirise.image`. The mosaic is in an equirectangular projection; `inspect_raw.py` tells you whether the site centre is inside it.

## Thermal (THEMIS, Mars Odyssey)

- USGS has 100 m/pixel THEMIS thermal inertia mosaics in 30° x 60° tiles. Jezero (18.5 N, 77.4 E) is in the tile covering 0-30 N, 60-120 E; by the naming pattern that is `00N060E` (check on the USGS site). Prefer the **quantitative** version (real thermal inertia values), for example the pattern of the [quantitative 30S060E tile](https://astrogeology.usgs.gov/search/map/themis_thermal_inertia_mosaic_quantitative_30s060e_100mpp).
- If only the qualitative or night-IR version is available, set `"kind": "night_ir"`. The map still shows sand against rock, but there are no real values for Nahla's thresholds.
- 100 m pixels are 20 grid cells wide, so this layer looks blurry at site scale. That is expected; say so in the demo.

## Minerals (CRISM, Mars Reconnaissance Orbiter)

- Use the map-projected **MTRDR** products (they come with summary parameter files, `*_su*.img`). Search by location in the [PDS Orbital Data Explorer](https://ode.rsl.wustl.edu/mars/); the [MTRDR primer](https://ode.rsl.wustl.edu/mars/pagehelp/Content/Missions_Instruments/Mars%20Reconnaissance%20Orbiter/CRISM/CRISM%20Product%20Primer/CRISM%20MTRDR.htm) explains the files. Jezero is one of CRISM's most-imaged targets, so several will cover the delta.
- Useful parameters for the delta: `D2300` (Fe/Mg clays), `BD1900_2` (hydrated minerals), and for carbonates `BD2500_2` or `MIN2295_2480` (check which names your file has). Update `crism.minerals` in `site.json` to match.
- Run `python data/inspect_raw.py` on the file to see its band names. If the names don't show, find the band number in the `.lbl` label and use `"band": N` instead of `"band_name"`.
- The thresholds in `site.json` are starting values. Adjust them until the map matches what CRISM browse images show, and say they were tuned by eye.
- CRISM targeted images are small (about 10 km), so one may cover only part of the site. Uncovered cells stay transparent.

## Weather (MEDA, Perseverance)

- The [PDS Atmospheres Node Perseverance area](https://pds-atmospheres.nmsu.edu/data_and_services/atmospheres_data/PERSEVERANCE/) (the PDS4 bundle is `mars2020_meda`) has MEDA data per sol. Use the **derived** (`DER`) files. Each sol and each sensor is its own CSV: air temperature (`ATS`) and pressure (`PS`) are separate. The `.xml` label next to each file describes the columns.
- Pick 1-3 sols when Perseverance was at the delta front (the delta front campaign started on sol 415). Put the files in `raw/meda/`, run `python data/tables.py <file>` on one of each to see the columns, and set `meda.temp_files`, `meda.pressure_files` (wildcards work), the column names and `meda.sols`.
- The sol is read from the file name (`WE__0420...`). Temperatures are in kelvin unless the label says otherwise.
- `dust_tau` is a single estimate in `site.json`, and `layers.json` says so.
- The `rems` block (Curiosity, Gale) is no longer used. Leave its file null.

## Radiation (estimate)

- Perseverance has no instrument that measures radiation dose, so there is no Jezero measurement to download. `rad.estimate` in `site.json` uses Curiosity RAD's published surface average at Gale (Hassler et al. 2014, *Science*: 0.64 mSv/day, about 27 uSv/h) as a constant for every hour of `rad.sols`. Run `python data/build_real.py rad`.
- Jezero is about 2 km higher than Gale crater's floor, with less atmosphere overhead, so the real dose is probably somewhat higher. `layers.json` labels the file as an estimate, and the app must say so too.
- If you later find RAD data you want to use directly, set `rad.file` (it takes priority over the estimate); see the older Curiosity notes in the Git history of this file.

## Solar storms (DONKI)

- No download: `python data/build_real.py donki` calls the [DONKI web service](https://ccmc.gsfc.nasa.gov/tools/DONKI) for the dates in `site.json`. No API key is needed. (DONKI moved from api.nasa.gov to ccmc.gsfc.nasa.gov in September 2026.)
- The output, `space_weather.csv`, is a **new** file listed under `tables.space_weather` in `layers.json`. Tell Tushaar (storm re-planning) and Zakiyyah (storm demo) it exists.

## Credit

Add each real dataset to the **Data sources** table in the main README, with the mission and instrument, when you switch it on.
