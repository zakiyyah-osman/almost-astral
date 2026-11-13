/*
 * MarsCoords - the ONE shared conversion between map coordinates and the screen.
 * Owner: Person 2. Everyone else calls these functions; nobody writes their own.
 *
 * Map coordinates: [east, north] in metres from the SW corner of the site grid.
 * Screen coordinates: [x, y] in CSS pixels inside the map's <svg>, y pointing down.
 *
 * A "view" is a plain object  { cx, cy, s, w, h }:
 *   cx, cy  map point (m) shown at the centre of the viewport
 *   s       zoom, in screen pixels per metre
 *   w, h    viewport size in pixels
 * Views are never mutated; every function returns a new one.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MarsCoords = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const MARS_RADIUS_M = 3396190; // IAU Mars 2000 sphere, as used by HiRISE/CTX map products

  /** Fit the whole site [width_m x height_m] into a viewport with some padding (px). */
  function fit(site, w, h, pad = 24) {
    const s = Math.min((w - 2 * pad) / site.width_m, (h - 2 * pad) / site.height_m);
    return { cx: site.width_m / 2, cy: site.height_m / 2, s, w, h };
  }

  /** [east, north] m  ->  [x, y] px */
  function toScreen(v, en) {
    return [v.w / 2 + (en[0] - v.cx) * v.s, v.h / 2 - (en[1] - v.cy) * v.s];
  }

  /** [x, y] px  ->  [east, north] m */
  function toMap(v, xy) {
    return [v.cx + (xy[0] - v.w / 2) / v.s, v.cy - (xy[1] - v.h / 2) / v.s];
  }

  /** Distance on the map (m) -> length on screen (px), and back. */
  const metresToPx = (v, m) => m * v.s;
  const pxToMetres = (v, px) => px / v.s;

  /**
   * SVG transform for a <g> whose children are drawn in "image metres":
   * x = east, y = height_m - north (so a raster with row 0 = north can be placed
   * at x=0, y=0, width=width_m, height=height_m without flipping).
   */
  function svgTransform(v, site) {
    const tx = v.w / 2 - v.cx * v.s;
    const ty = v.h / 2 - (site.height_m - v.cy) * v.s;
    return `matrix(${v.s} 0 0 ${v.s} ${tx} ${ty})`;
  }

  function clampScale(s, limits) {
    return Math.max(limits?.min ?? 0, Math.min(limits?.max ?? Infinity, s));
  }

  /** Zoom by `factor` keeping the map point under screen point `xy` fixed. */
  function zoomAt(v, xy, factor, limits) {
    const s = clampScale(v.s * factor, limits);
    const p = toMap(v, xy);
    return { ...v, s, cx: p[0] - (xy[0] - v.w / 2) / s, cy: p[1] + (xy[1] - v.h / 2) / s };
  }

  /** Pan by a screen drag of (dx, dy) px. */
  function pan(v, dx, dy) {
    return { ...v, cx: v.cx - dx / v.s, cy: v.cy + dy / v.s };
  }

  /** Keep at least `keep` px of the site on screen so it can't be lost. */
  function constrain(v, site, keep = 80) {
    const halfW = v.w / 2 / v.s, halfH = v.h / 2 / v.s, k = keep / v.s;
    const cx = Math.min(site.width_m + halfW - k, Math.max(-halfW + k, v.cx));
    const cy = Math.min(site.height_m + halfH - k, Math.max(-halfH + k, v.cy));
    return { ...v, cx, cy };
  }

  /** Resize the viewport, keeping centre and zoom. */
  const resize = (v, w, h) => ({ ...v, w, h });

  /** Longest "nice" length (1, 2, 5 x 10^k m) that fits in maxPx. */
  function niceScaleBar(v, maxPx = 140) {
    const maxM = maxPx / v.s;
    const p = Math.pow(10, Math.floor(Math.log10(maxM)));
    const m = [5, 2, 1].map((k) => k * p).find((x) => x <= maxM) ?? p;
    return { metres: m, px: m * v.s, label: m >= 1000 ? `${m / 1000} km` : m >= 1 ? `${m} m` : `${Math.round(m * 100)} cm` };
  }

  /** Grid-line spacing in metres giving lines roughly `targetPx` apart. */
  function niceGridStep(v, targetPx = 110) {
    return niceScaleBar(v, targetPx * 1.6).metres;
  }

  /** Visible map rectangle {e0, e1, n0, n1}. */
  function visibleBounds(v) {
    const [e0, n1] = toMap(v, [0, 0]);
    const [e1, n0] = toMap(v, [v.w, v.h]);
    return { e0, e1, n0, n1 };
  }

  const inSite = (site, en) => en[0] >= 0 && en[0] <= site.width_m && en[1] >= 0 && en[1] <= site.height_m;

  /** Grid cell (row, col) containing a map point; row 0 = north edge. */
  function toCell(site, en) {
    return [Math.floor((site.height_m - en[1]) / site.cell_m), Math.floor(en[0] / site.cell_m)];
  }

  /**
   * Local [east, north] <-> planetocentric lat/lon (degrees, east-positive).
   * Uses the site's SW corner `origin_latlon`. Spherical, local approximation:
   * error < 1 m across a 10 km site near the equator - fine for placing
   * Curiosity stops; use the real projection for anything larger.
   */
  function enToLatLon(site, en) {
    const [lat0, lon0] = site.origin_latlon;
    const lat = lat0 + (en[1] / MARS_RADIUS_M) * (180 / Math.PI);
    const lon = lon0 + (en[0] / (MARS_RADIUS_M * Math.cos((lat0 * Math.PI) / 180))) * (180 / Math.PI);
    return [lat, lon];
  }
  function latLonToEN(site, latlon) {
    const [lat0, lon0] = site.origin_latlon;
    const n = ((latlon[0] - lat0) * Math.PI) / 180 * MARS_RADIUS_M;
    const e = ((latlon[1] - lon0) * Math.PI) / 180 * MARS_RADIUS_M * Math.cos((lat0 * Math.PI) / 180);
    return [e, n];
  }

  /** Source-projection metres (e.g. HiRISE equirectangular x, y) <-> local [east, north]. */
  const sourceToEN = (site, xy) => [xy[0] - site.origin_source_xy[0], xy[1] - site.origin_source_xy[1]];
  const enToSource = (site, en) => [en[0] + site.origin_source_xy[0], en[1] + site.origin_source_xy[1]];

  function formatEN(en, digits = 0) {
    return `E ${en[0].toFixed(digits)} m · N ${en[1].toFixed(digits)} m`;
  }
  function formatLatLon(ll) {
    const f = (x, p, n) => `${Math.abs(x).toFixed(5)}°${x >= 0 ? p : n}`;
    return `${f(ll[0], "N", "S")} ${f(ll[1], "E", "W")}`;
  }

  return {
    MARS_RADIUS_M, fit, toScreen, toMap, metresToPx, pxToMetres, svgTransform, zoomAt, pan,
    constrain, resize, niceScaleBar, niceGridStep, visibleBounds, inSite, toCell,
    enToLatLon, latLonToEN, sourceToEN, enToSource, formatEN, formatLatLon,
  };
});
