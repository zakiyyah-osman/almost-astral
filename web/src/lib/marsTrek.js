// Base imagery for the crater map, bottom to top. Ids, formats, zoom ranges and bounding boxes are
// from each layer's WMTSCapabilities.xml (checked 14 Nov 2026):
//   https://trek.nasa.gov/tiles/Mars/EQ/<id>/1.0.0/WMTSCapabilities.xml
// Missing tiles (404 or 400) mean no coverage: the map shows them as blank (see SiteMap.jsx).
// `options` go straight to L.tileLayer. Map zooms are Leaflet EPSG4326 zooms (zoom 0 = 2 x 1 tiles of 256 px).

const TREK = 'https://trek.nasa.gov/tiles/Mars/EQ'
const trek = (id, ext) => `${TREK}/${id}/1.0.0/default/default028mm/{z}/{y}/{x}.${ext}`

// Global CTX (Mars Trek id CTX_beta01_uncontrolled_5m_Caltech, "MRO CTX, Mosaic Global Uncontrolled
// (Caltech)"). Mars Trek's capabilities point the tiles at Esri's server, which uses 512 px tiles:
// its level L has the same grid as Leaflet zoom L + 1, hence tileSize 512 and zoomOffset -1.
// Its deepest level is 12 (about 5 m per pixel). Level 11 is faulty over Jezero (14 Nov: tiles come
// back cut short and repeated), so it is never requested: one layer stops at level 10 and stays
// underneath as a fallback, the other draws level 12 from map zoom 12 up.
const CTX_GLOBAL = 'https://astro.arcgis.com/arcgis/rest/services/OnMars/CTX/MapServer/tile/{z}/{y}/{x}'
const ESRI_512 = { tileSize: 512, zoomOffset: -1 }

export const TREK_LAYERS = [
  {
    id: 'viking',
    title: 'Viking colour mosaic (global, 232 m)',
    url: trek('Mars_Viking_MDIM21_ClrMosaic_global_232m', 'jpg'),
    options: { maxNativeZoom: 7, bounds: [[-90, -180], [90, 180]] },
  },
  {
    id: 'ctx_global_overview',
    title: 'CTX global mosaic, uncontrolled (Caltech Murray Lab), up to level 10',
    url: CTX_GLOBAL,
    options: { ...ESRI_512, maxNativeZoom: 11, bounds: [[-90, -180], [90, 180]] },
  },
  {
    id: 'ctx_global_detail',
    title: 'CTX global mosaic, uncontrolled (Caltech Murray Lab), level 12 (about 5 m)',
    url: CTX_GLOBAL,
    options: { ...ESRI_512, minZoom: 12, minNativeZoom: 13, maxNativeZoom: 13, bounds: [[-90, -180], [90, 180]] },
  },
  {
    id: 'ctx_jezero',
    title: 'CTX Jezero mosaic, controlled (6 m)',
    url: trek('JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0', 'png'),
    options: { maxNativeZoom: 13, bounds: [[18.2110274, 77.1604655], [18.7211945, 77.6991776]] },
  },
  {
    id: 'hirise_jezero',
    title: 'HiRISE Jezero mosaic, controlled (25 cm)',
    url: trek('JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd', 'png'),
    options: { maxNativeZoom: 17, bounds: [[18.3067994, 77.2229331], [18.669315, 77.583964]] },
  },
]

export const TREK_ATTRIBUTION =
  'Imagery: NASA/JPL Mars Trek (CTX, HiRISE, Viking); global CTX mosaic: NASA/JPL/MSSS/Caltech Murray Lab/Esri'

// Jezero crater: about 45 km across (NASA), centred near 18.4 N, 77.5 E.
export const CRATER = { lat: 18.4, lon: 77.5, diameterKm: 45 }
