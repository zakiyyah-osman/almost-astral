# Where to get the real data

Download into `data/raw/` (Git ignores it), point `data/site.json` at the file, then run `python data/build_real.py`. Check every raster first with `python data/inspect_raw.py <file>`: it tells you whether the site centre is inside the file.

**Before downloading anything:** get the final site centre from Zakiyyah and put it in `data/site.json` (`center_lat`, `center_lon_east`). The current value is a placeholder near Curiosity's 2025 boxwork area.

| Layer | Best source | Folder | site.json block |
| --- | --- | --- | --- |
| Terrain (`dem.tif`) | MSL Gale merged DEM, 1 m, or a single HiRISE DTM | `raw/hirise/` | `hirise.dtm` |
| Image (`hirise.png`) | MSL Gale merged orthophoto, 25 cm, or a HiRISE ORTHO | `raw/hirise/` | `hirise.image` |
| Thermal (`thermal.png`) | THEMIS quantitative thermal inertia mosaic, 100 m | `raw/themis/` | `themis.file` |
| Minerals (`minerals.png`) | CRISM MTRDR summary parameters | `raw/crism/` | `crism.minerals` |
| Weather (`weather.csv`) | Curiosity REMS reduced data (PDS) | `raw/rems/` | `rems` |
| Radiation (`radiation.csv`) | Curiosity RAD reduced data (PDS) | `raw/rad/` | `rad` |
| Solar storms (`space_weather.csv`) | NASA DONKI API (no download) | none | `donki` |

## Terrain and image (HiRISE, Mars Reconnaissance Orbiter)

- **Easiest for Gale:** USGS publishes the MSL team's merged products: [MSL Gale Merged DEM 1m](https://astrogeology.usgs.gov/search/map/mars_msl_gale_merged_dem_1m) and [MSL Gale Merged Orthophoto Mosaic 25cm](https://astrogeology.usgs.gov/search/map/mars_msl_gale_merged_orthophoto_mosaic_25cm). Check the coverage map on each page reaches the site. The orthophoto is very large; if it is too big to download, use a single HiRISE ORTHO instead.
- **Single HiRISE products:** the [HiRISE DTM list](https://www.uahirise.org/dtm/) has stereo terrain models with matching orthoimages (`DTEEC_..._.IMG` is the terrain, `..._RED_..._ORTHO.JP2` the image). Pick one whose footprint covers the site.
- Settings: `hirise.dtm` and `hirise.image`.

## Thermal (THEMIS, Mars Odyssey)

- USGS has 100 m/pixel THEMIS thermal inertia mosaics in 60°-wide tiles. Gale (about 5°S, 137°E) is in the tile covering 0–30°S, 120–180°E. Prefer the **quantitative** version (real thermal inertia values); for example, this is the [quantitative tile for 30S060E](https://astrogeology.usgs.gov/search/map/themis_thermal_inertia_mosaic_quantitative_30s060e_100mpp). Search the same site for the 120E tile.
- If only the qualitative or night-IR version is available, set `"kind": "night_ir"`. The map still shows sand against rock, but there are no real values for Nahla's thresholds.
- 100 m pixels are 20 grid cells wide, so this layer looks blurry at site scale. That is expected; say so in the demo.

## Minerals (CRISM, Mars Reconnaissance Orbiter)

- Use the map-projected **MTRDR** products (they come with summary parameter files, `*_su*.img`). Search by location in the [PDS Orbital Data Explorer](https://ode.rsl.wustl.edu/mars/); the [MTRDR primer](https://ode.rsl.wustl.edu/mars/pagehelp/Content/Missions_Instruments/Mars%20Reconnaissance%20Orbiter/CRISM/CRISM%20Product%20Primer/CRISM%20MTRDR.htm) explains the files.
- Useful parameters for a boxwork and sulfate site: `SINDEX2` (sulfates), `BD1900_2` (hydrated minerals), `D2300` (Fe/Mg clays).
- Run `python data/inspect_raw.py` on the file to see its band names. If the names don't show, find the band number in the `.lbl` label and use `"band": N` instead of `"band_name"`.
- The thresholds in `site.json` are starting values. Adjust them until the map matches what CRISM browse images show, and say they were tuned by eye.
- CRISM targeted images are small (about 10 km), so one may cover only part of the site. Uncovered cells stay transparent.

## Weather (REMS, Curiosity)

- The [PDS Atmospheres Node REMS page](https://pds-atmospheres.nmsu.edu/data_and_services/atmospheres_data/MARS/curiosity/rems.html) has reduced data per sol. The `MODRDR` files have temperatures in kelvin and pressure in pascals; the `.lbl` label next to each file lists the column names.
- Pick 1–3 sols when Curiosity was near the site, combine their rows into one CSV, then run `python data/tables.py <file>` to see the columns. Set `rems.columns`, `rems.sols` and `rems.temp_units` to match.
- REMS does not measure dust opacity, so `dust_tau` is the single estimate in `site.json`, and `layers.json` says so.

## Radiation (RAD, Curiosity)

- RAD reduced data is at the [PDS PPI Node](https://pds-ppi.igpp.ucla.edu/) (search "MSL RAD"). The files are complex; you need a dose-rate column with a sol and local time. Build a small CSV with `sol, ltst, dose_rate` and set the units in `rad.dose_units`.
- If the PDS files are too slow to work with before Wednesday, a fair fallback is the published surface average from RAD (Hassler et al. 2014, *Science*: about 0.21 mGy/day, 0.64 mSv/day, roughly 27 µSv/h). Use it as a constant, and label it in the app as an average rather than a measurement.
- The gray-to-sievert conversion uses one average quality factor (`rad.quality_factor`). It is an approximation, and `layers.json` says so.

## Solar storms (DONKI)

- No download: `python data/build_real.py donki` calls the [DONKI web service](https://ccmc.gsfc.nasa.gov/tools/DONKI) for the dates in `site.json`. No API key is needed. (DONKI moved from api.nasa.gov to ccmc.gsfc.nasa.gov in September 2026.)
- The output, `space_weather.csv`, is a **new** file listed under `tables.space_weather` in `layers.json`. Tell Tushaar (storm re-planning) and Zakiyyah (storm demo) it exists.

## Credit

Add each real dataset to the **Data sources** table in the main README, with the mission and instrument, when you switch it on.
