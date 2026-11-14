// The team research note "Minerals in a 12 km × 12 km square around our Jezero site"
// (Almost Astral, NASA Space Apps 2026, 2026-11-14, Jezero_minerals_12km_research.pdf).
// Everything here is transcribed from that note: nothing is added. Positions are km east and north
// of the south-west corner of the 12 km square, which is centred on our site (18.46°N, 77.40°E).
//
// CRISM colours are RELATIVE orbital signals, not confirmed detections. Tonnage is not known:
// CRISM sees only the top surface, with no depth or concentration.
import { xyToLatLon, lon180 } from './geo.js'

export const RESEARCH = {
  title: 'Minerals in a 12 km × 12 km square around our Jezero site',
  author: 'Almost Astral',
  date: '2026-11-14',
  file: 'Jezero_minerals_12km_research.pdf',
  sizeKm: 12,
  mapFile: 'crater/minerals_12km.png', // the colour layer, from the data lead (not in data/out yet)
  caption:
    'CRISM (MRO) MTRDR summary parameters FRT00005C5E (18 m) and HRL000040FF (36 m), NASA PDS; terrain CTX DEM (USGS). Shown: each parameter’s strongest 2% of pixels, above zero and above the team threshold, in patches of at least 4 cells (1,600 m²); where two pass, the stronger wins. Relative signals, not confirmed detections. Sample sites from NASA’s Perseverance waypoints on the sol each core was taken.',
  noTonnage:
    'Tonnage is not known. CRISM measures a relative signal from the top surface only (no depth, no concentration), so no amount can be worked out from orbit.',
}

// The mineral classes on the map, largest mapped area first.
export const MINERAL_CLASSES = [
  { id: 'augite', name: 'High-calcium pyroxene (augite)', parameter: 'HCPINDEX2', areaKm2: 1.81, color: '#e0559a', about: 'A dark mineral common in volcanic rock (basalt).' },
  { id: 'olivine', name: 'Olivine', parameter: 'OLINDEX3', areaKm2: 1.4, color: '#78c846', about: 'A green volcanic mineral. With carbon-dioxide-rich water it can turn into carbonate.' },
  { id: 'hydrated', name: 'Hydrated minerals (type not identified)', parameter: 'BD1900_2', areaKm2: 1.19, color: '#d8d8d8', about: 'Any mineral holding water in its structure; CRISM sees the water band but not which mineral.' },
  { id: 'carbonate', name: 'Mg-carbonate (magnesium carbonate)', parameter: 'MIN2295_2480', areaKm2: 1.12, color: '#eb8c37', about: "Forms when water with dissolved carbon dioxide reacts with rock; can record the water's chemistry." },
  { id: 'clay', name: 'Fe/Mg smectite clay', parameter: 'D2300', areaKm2: 0.71, color: '#46aae6', about: 'A clay that forms in water; good at preserving traces of past conditions.' },
]
export const NO_DATA = { name: 'No CRISM data', color: '#555555', percent: 8, about: 'Neither CRISM image covers these places, so mineral presence is unknown there.' }
export const CHECKED_UNMAPPED = 'Low-calcium pyroxene (LCPINDEX2) was checked; no positive signal.'

export const REFERENCES = {
  ref_01: { label: 'NASA PDS: CRISM map-projected targeted products (MTRDR)', url: 'https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/mtrdr/' },
  ref_02: { label: 'NASA Perseverance waypoints (rover position per sol)', url: 'https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json' },
  ref_03: { label: 'NASA: Mars rock samples (sols, sample types)', url: 'https://science.nasa.gov/mission/mars-2020-perseverance/mars-rock-samples' },
  ref_04: { label: 'Weiss et al. 2024, Oriented bedrock samples (sample sols)', url: 'https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2023EA003322' },
  ref_05: { label: 'Herd et al., LPSC 2023, sampling overview', url: 'https://ntrs.nasa.gov/api/citations/20230000371/downloads/Herd_M2020_LPSC23_RSS_overview_final.pdf' },
  ref_06: { label: 'Simon et al. 2023, Samples collected from the floor of Jezero crater', url: 'https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2022JE007474' },
  ref_07: { label: 'Sun et al. 2023, First science campaign on the crater floor', url: 'https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2022JE007613' },
  ref_08: { label: 'NASA: A Tale of Turquoise Bay', url: 'https://science.nasa.gov/missions/mars-2020-perseverance/a-tale-of-turquoise-bay-sampling-unique-bedrock-at-the-margin-unit/' },
  ref_09: { label: 'JPL: Bunsen Peak sample (PIA26313)', url: 'https://www.jpl.nasa.gov/images/pia26313-perseverances-bunsen-peak-sample/' },
  ref_10: { label: 'NASA: Sapphire Canyon, sample 25', url: 'https://science.nasa.gov/resource/meet-the-mars-samples-sapphire-canyon-sample-25/' },
  ref_11: { label: 'NASA/JPL: potential biosignature at Cheyava Falls', url: 'https://www.jpl.nasa.gov/news/nasa-says-mars-rover-discovered-potential-biosignature-last-year/' },
  ref_12: { label: 'Liu et al. 2022, An olivine cumulate outcrop (Séítah)', url: 'https://carnegiescience.edu/olivine-cumulate-outcrop-floor-jezero-crater-mars-1' },
  ref_13: { label: 'NASA/JPL: Wildcat Ridge organics and sulfates', url: 'https://www.jpl.nasa.gov/news/nasas-perseverance-rover-investigates-geologically-rich-mars-terrain/' },
  ref_14: { label: 'Berkeley: crater-floor samples and salts', url: 'https://vcresearch.berkeley.edu/news/perseverance-rover-retrieves-key-clues-mars-geologic-and-water-history' },
  ref_15: { label: 'PNAS: Sampling Mars, geologic context of the samples', url: 'https://www.pnas.org/doi/10.1073/pnas.2404255121' },
}

// Rover sample groups from the note. refs: the note's references whose titles name that sample.
export const SAMPLE_GROUPS = {
  wildcat_and_skinner_ridge: {
    title: 'Wildcat Ridge & Skinner Ridge',
    cores: 'Hazeltop, Bearwallow (Wildcat Ridge); Swift Run, Skyland (Skinner Ridge)',
    sols: 'Sols 490–516',
    where: 'Inside our 2 km walk',
    finding: 'Delta mudstone from an evaporating salty lake; organic molecules found alongside sulfate minerals.',
    refs: ['ref_13', 'ref_03'],
  },
  mageik_and_kukaklek: {
    title: 'Mageik & Kukaklek',
    cores: 'Mageik (sol 579), Kukaklek (sol 623)',
    sols: 'Sols 579 and 623',
    where: 'Inside our 2 km walk',
    finding: 'Delta front sedimentary cores.',
    refs: ['ref_03', 'ref_05'],
  },
  montdenier: {
    title: 'Montdenier (Rochette)',
    cores: 'Montdenier',
    sols: 'Sol 190',
    where: '2.5 km east, 1.7 km south of our site',
    finding: 'Máaz basalt: feldspar, pyroxene (augite), iron-titanium oxides; salts (sulfates, perchlorates) in pores.',
    refs: ['ref_06', 'ref_14'],
  },
  quartier: {
    title: 'Quartier outcrop (Séítah)',
    cores: 'Quartier',
    sols: 'Sol 294',
    where: '2.3 km east, 1.6 km south of our site',
    finding: 'Olivine rock (olivine cumulate) that reacted with carbonated water.',
    refs: ['ref_12', 'ref_06'],
  },
  turquoise_bay: {
    title: 'Turquoise Bay (Margin Unit)',
    cores: 'Turquoise Bay',
    sols: 'Sol 942',
    where: '3.0 km west, 1.7 km north of our site',
    finding: 'Margin Unit core that NASA says may contain carbonate minerals.',
    refs: ['ref_08'],
  },
  bunsen_peak: {
    title: 'Bunsen Peak',
    cores: 'Bunsen Peak',
    sols: 'Sol 1088',
    where: '4.1 km west, 1.9 km north of our site',
    finding: 'About 75% carbonate minerals cemented by almost pure silica.',
    refs: ['ref_09'],
  },
  sapphire_canyon: {
    title: 'Sapphire Canyon (Cheyava Falls)',
    cores: 'Sapphire Canyon',
    sols: 'Sol 1215',
    where: '5.3 km west, 2.2 km north of our site (no CRISM coverage there)',
    finding: 'Tiny spots rich in iron phosphate and iron sulfide, likely vivianite and greigite: a potential biosignature, not proof of life.',
    refs: ['ref_10', 'ref_11'],
  },
}

// The markers on the note's map. method: 'table' = from the offsets the note reports (exact to its
// rounding); 'figure' = read off the map axes, about ±0.1 km.
export const MARKERS = [
  { group: 'sapphire_canyon', label: 'Cheyava Falls · likely vivianite + greigite', kind: 'star', east: 0.7, north: 8.2, method: 'table' },
  { group: 'bunsen_peak', label: 'Bunsen Peak · ~75% carbonate + silica', kind: 'star', east: 1.9, north: 7.9, method: 'table' },
  { group: 'turquoise_bay', label: 'Turquoise Bay · Margin Unit, may contain carbonate', kind: 'star', east: 3.0, north: 7.7, method: 'table' },
  { group: 'wildcat_and_skinner_ridge', label: 'Wildcat Ridge & Skinner Ridge · delta mudstone, sulfates + organics', kind: 'star', east: 6.3, north: 5.9, method: 'figure' },
  { group: 'mageik_and_kukaklek', label: 'Kukaklek · delta core', kind: 'star', east: 5.9, north: 5.6, method: 'figure' },
  { group: 'mageik_and_kukaklek', label: 'Mageik · delta front core', kind: 'star', east: 6.1, north: 5.5, method: 'figure' },
  { group: null, label: 'Perseverance landing site', kind: 'landing', east: 8.9, north: 5.1, method: 'figure' },
  { group: 'quartier', label: 'Séítah · olivine rock altered to carbonate', kind: 'star', east: 8.3, north: 4.4, method: 'table' },
  { group: 'montdenier', label: 'Montdenier · Máaz basalt: augite (pyroxene), feldspar', kind: 'star', east: 8.5, north: 4.3, method: 'table' },
]

// Site grid metres for a point given in km from the 12 km square's south-west corner.
// The square and our site share a centre.
export function squareToXY(eastKm, northKm, site) {
  const [w, h] = site.extent_m
  const half = (RESEARCH.sizeKm * 1000) / 2
  return { x: w / 2 - half + eastKm * 1000, y: h / 2 - half + northKm * 1000 }
}

// Latitude / longitude (longitude -180..180, for Leaflet) of a point in the square.
export function squareToLatLon(eastKm, northKm, site) {
  const { x, y } = squareToXY(eastKm, northKm, site)
  const ll = xyToLatLon(x, y, site)
  return { lat: ll.lat, lon: lon180(ll.lon) }
}

// The 12 km square as { south, west, north, east }.
export function squareBounds(site) {
  const sw = squareToLatLon(0, 0, site)
  const ne = squareToLatLon(RESEARCH.sizeKm, RESEARCH.sizeKm, site)
  return { south: sw.lat, west: sw.lon, north: ne.lat, east: ne.lon }
}

// The mineral class whose legend colour is closest to an RGB pixel, or null when nothing is close
// (transparent or a colour the legend does not use).
export function classForPixel(r, g, b, a = 255, tolerance = 40) {
  if (a < 32) return null
  let best = null
  let bestD = Infinity
  for (const c of [...MINERAL_CLASSES, { ...NO_DATA, id: 'nodata' }]) {
    const n = parseInt(c.color.slice(1), 16)
    const d = Math.hypot(r - ((n >> 16) & 255), g - ((n >> 8) & 255), b - (n & 255))
    if (d < bestD) {
      bestD = d
      best = c
    }
  }
  return bestD <= tolerance ? best : null
}
