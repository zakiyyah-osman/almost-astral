// node basemap/web/coords.test.js
const assert = require("node:assert/strict");
const C = require("./coords.js");

const site = { width_m: 1000, height_m: 800, cell_m: 1, origin_latlon: [-4.7, 137.4], origin_source_xy: [8144000, -278600] };
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) <= eps, `${a} != ${b}`);
const nearV = (a, b, eps) => a.forEach((x, i) => near(x, b[i], eps));
let n = 0;
const test = (name, fn) => { fn(); n++; console.log("ok -", name); };

test("fit centres the site and keeps aspect", () => {
  const v = C.fit(site, 1200, 800, 0);
  near(v.s, 1); // limited by height: 800/800
  nearV(C.toScreen(v, [500, 400]), [600, 400]);
});

test("corners land where expected (north up, east right)", () => {
  const v = C.fit(site, 1000, 800, 0);
  nearV(C.toScreen(v, [0, 800]), [0, 0]);     // NW corner -> top-left
  nearV(C.toScreen(v, [1000, 0]), [1000, 800]); // SE corner -> bottom-right
});

test("toMap inverts toScreen", () => {
  let v = C.fit(site, 937, 611);
  v = C.zoomAt(C.pan(v, 37, -12), [100, 200], 3.7);
  for (const en of [[0, 0], [123.4, 567.8], [1000, 800], [-50, 900]]) nearV(C.toMap(v, C.toScreen(v, en)), en, 1e-9);
});

test("zoomAt keeps the point under the cursor fixed", () => {
  const v0 = C.fit(site, 1000, 800);
  const xy = [321, 123];
  const before = C.toMap(v0, xy);
  const v1 = C.zoomAt(v0, xy, 2.5);
  nearV(C.toMap(v1, xy), before, 1e-9);
  near(v1.s, v0.s * 2.5);
});

test("zoom limits are respected", () => {
  const v = C.zoomAt(C.fit(site, 1000, 800), [0, 0], 1e6, { min: 0.1, max: 40 });
  near(v.s, 40);
});

test("pan moves the map with the finger", () => {
  const v0 = C.fit(site, 1000, 800);
  const p = C.toScreen(v0, [300, 300]);
  const v1 = C.pan(v0, 50, -20);
  nearV(C.toScreen(v1, [300, 300]), [p[0] + 50, p[1] - 20], 1e-9);
});

test("svgTransform matches toScreen for image-metre children", () => {
  const v = C.zoomAt(C.fit(site, 900, 700), [200, 300], 2);
  const m = C.svgTransform(v, site).match(/[-\d.e]+/g).map(Number);
  const [a, , , d, tx, ty] = m;
  for (const en of [[0, 0], [250, 610], [1000, 800]]) {
    const ix = en[0], iy = site.height_m - en[1];
    nearV([a * ix + tx, d * iy + ty], C.toScreen(v, en), 1e-6);
  }
});

test("scale bar uses 1-2-5 lengths that fit", () => {
  const v = { ...C.fit(site, 1000, 800, 0), s: 0.8 };
  const sb = C.niceScaleBar(v, 140); // 175 m fits -> 100 m
  assert.equal(sb.metres, 100); near(sb.px, 80); assert.equal(sb.label, "100 m");
  assert.equal(C.niceScaleBar({ ...v, s: 0.05 }, 140).label, "2 km");
  assert.equal(C.niceScaleBar({ ...v, s: 300 }, 140).label, "20 cm");
});

test("cells: row 0 is north", () => {
  assert.deepEqual(C.toCell(site, [0.5, 799.5]), [0, 0]);
  assert.deepEqual(C.toCell(site, [999.5, 0.5]), [799, 999]);
});

test("lat/lon round trip and scale", () => {
  const en = [734.2, 512.9];
  nearV(C.latLonToEN(site, C.enToLatLon(site, en)), en, 1e-6);
  const ll = C.enToLatLon(site, [0, 1000]); // 1 km north
  near(ll[0] - -4.7, (1000 / C.MARS_RADIUS_M) * 180 / Math.PI, 1e-12);
});

test("source projection offset", () => {
  nearV(C.sourceToEN(site, [8144100, -278550]), [100, 50]);
  nearV(C.enToSource(site, [100, 50]), [8144100, -278550]);
});

console.log(`\n${n} tests passed`);
