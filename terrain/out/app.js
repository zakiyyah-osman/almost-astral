/* Page wiring for the base-map viewer: header, layer panel, readout, landmarks.
 * The map itself lives in basemap.js; the maths in coords.js. */
(async function () {
  "use strict";
  const C = window.MarsCoords;
  const config = window.MM_CONFIG || (await fetch("map_config.json").then((r) => r.json()));
  const site = config.site;
  const $ = (s) => document.querySelector(s);

  document.title = config.title;
  $("#mm-title").innerHTML = config.title.replace(/:(.*)$/, ":<span>$1</span>");
  $("#mm-site").textContent = site.name;
  const banner = $("#mm-banner");
  banner.hidden = !config.simulated;
  banner.textContent = config.simulated_note || "SIMULATED DATA — not real Mars measurements. Replaced when the NASA dataset arrives.";

  // ---- sample class layers under the cursor (hazards, minerals) --------------
  const samplers = {};
  for (const L of config.layers) {
    if (L.kind !== "image" || L.legend?.type !== "classes") continue;
    const img = new Image();
    img.onload = () => {
      const cv = document.createElement("canvas");
      cv.width = img.naturalWidth; cv.height = img.naturalHeight;
      const ctx = cv.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const items = L.legend.items.filter((it) => /^#[0-9a-f]{6}/i.test(it.color)).map((it) => ({ ...it, rgb: hexRgb(it.color) }));
      const single = L.legend.items.length === 1 ? L.legend.items[0].name : null;
      samplers[L.id] = (en) => {
        const px = Math.floor((en[0] / site.width_m) * cv.width);
        const py = Math.floor(((site.height_m - en[1]) / site.height_m) * cv.height);
        if (px < 0 || py < 0 || px >= cv.width || py >= cv.height) return null;
        const d = ctx.getImageData(px, py, 1, 1).data;
        if (d[3] < 20) return L.legend.transparent_as || null;
        if (single) return single;
        let best = null, bd = Infinity;
        for (const it of items) {
          const dist = (it.rgb[0] - d[0]) ** 2 + (it.rgb[1] - d[1]) ** 2 + (it.rgb[2] - d[2]) ** 2;
          if (dist < bd) { bd = dist; best = it; }
        }
        return bd < 60 ** 2 ? best.name : null;
      };
    };
    img.src = L.href;
  }
  function hexRgb(h) {
    const m = h.replace("#", "");
    return [0, 2, 4].map((i) => parseInt(m.slice(i, i + 2), 16));
  }

  // ---- map ---------------------------------------------------------------
  const readout = $("#mm-readout");
  const map = window.MartialBaseMap.create($("#mm-map"), config, {
    onCursor(en) {
      if (!en) { readout.innerHTML = `<span class="mm-dimtext">Move over the map for coordinates</span>`; return; }
      const inside = C.inSite(site, en);
      const ll = C.enToLatLon(site, en);
      const lines = [`<b>${C.formatEN(en, 1)}</b>`, C.formatLatLon(ll)];
      if (inside) {
        const [r, c] = C.toCell(site, en);
        lines.push(`<span class="mm-dimtext">cell row ${r}, col ${c}</span>`);
        for (const L of config.layers) {
          if (samplers[L.id] && map.layerState(L.id).visible) {
            const v = samplers[L.id](en);
            if (v) lines.push(`${L.title}: <b>${v}</b>`);
          }
        }
      } else lines.push(`<span class="mm-dimtext">outside the mapped site</span>`);
      readout.innerHTML = lines.join("<br>");
    },
  });
  map.svg.dispatchEvent(new Event("pointerleave"));

  // vector overlays shipped inside the config
  const B = window.MartialBaseMap.overlays;
  for (const L of config.layers) {
    if (L.kind === "grid") map.addOverlay(L.id, B.grid(site));
    if (L.kind === "lines") map.addOverlay(L.id, B.lines(L.features, L.id === "route" ? "mm-route" : "mm-track"));
    if (L.kind === "landmarks") map.addOverlay(L.id, B.landmarks(L.features));
  }

  // ---- layer panel ---------------------------------------------------------
  const list = $("#mm-layers");
  for (const L of [...config.layers].reverse()) {
    const box = document.createElement("div");
    box.className = "mm-layer";
    const id = `chk-${L.id}`;
    box.innerHTML = `
      <label class="mm-toggle" for="${id}"><input id="${id}" type="checkbox" ${L.visible ? "checked" : ""}> ${L.title}</label>
      ${L.kind === "image" ? `<div class="mm-opacity">Opacity <input type="range" min="0" max="1" step="0.05" value="${L.opacity ?? 1}" aria-label="${L.title} opacity"></div>` : ""}
      ${legendHtml(L.legend, L.units)}
      ${L.source ? `<div class="mm-source">Source: ${escapeHtml(L.source)}</div>` : ""}
      ${L.note ? `<div class="mm-source">${escapeHtml(L.note)}</div>` : ""}`;
    box.querySelector("input[type=checkbox]").addEventListener("change", (e) => map.setLayerVisible(L.id, e.target.checked));
    box.querySelector("input[type=range]")?.addEventListener("input", (e) => map.setLayerOpacity(L.id, +e.target.value));
    list.appendChild(box);
  }

  function legendHtml(lg, units) {
    if (!lg) return "";
    if (lg.type === "classes") {
      return `<div class="mm-legend">${lg.items.map((it) => `<span><i class="sw${it.color === "transparent" ? " sw-clear" : ""}" style="background:${it.color}"></i>${escapeHtml(it.name)}</span>`).join("")}</div>`;
    }
    if (lg.type === "ramp") {
      const stops = (lg.css_stops || []).join(",");
      const marks = (lg.marks || []).map((m) => `${m}`).join(" · ");
      return `<div class="mm-ramp" style="background:linear-gradient(90deg,${stops})"></div>
        <div class="mm-ramp-labels"><span>${lg.min}</span><span>${marks ? "limits " + marks : ""}</span><span>${lg.max} ${units || ""}</span></div>`;
    }
    return "";
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  // ---- landmarks ------------------------------------------------------------
  const lmBox = $("#mm-landmarks");
  const lm = config.layers.find((l) => l.id === "landmarks") || config.layers.find((l) => l.kind === "landmarks");
  if (lm) {
    for (const f of lm.features) {
      const b = document.createElement("button");
      b.innerHTML = `${escapeHtml(f.properties.name)}<small>${C.formatEN(f.geometry.coordinates, 1)}</small>`;
      b.addEventListener("click", () => {
        map.setLayerVisible(lm.id, true);
        $(`#chk-${lm.id}`).checked = true;
        map.flyTo(f.geometry.coordinates, Math.max(map.view.s, 3));
      });
      lmBox.appendChild(b);
    }
  } else lmBox.closest("section").hidden = true;

  // ---- projection / origin / bounds (what Person 2 shares with the team) -----
  const p = config.projection;
  $("#mm-proj").innerHTML = `
    <b>Map coordinates:</b> [east, north] m from the SW corner<br>
    <b>Bounds:</b> E 0 – ${site.width_m} m, N 0 – ${site.height_m} m · cell ${site.cell_m} m<br>
    <b>Origin (SW corner):</b> ${C.formatLatLon(site.origin_latlon)}<br>
    <b>Source projection:</b> ${escapeHtml(p.source_crs || "not set")}<br>
    <b>Origin in source projection:</b> ${p.origin_source_xy ? p.origin_source_xy.map((x) => x.toFixed(1)).join(", ") + " m" : "not set"}<br>
    <b>Leaflet CRS.Simple bounds:</b> [[0, 0], [${site.height_m}, ${site.width_m}]]`;

  // ---- zoom buttons ------------------------------------------------------------
  $("#mm-zin").addEventListener("click", () => map.zoomBy(1.5));
  $("#mm-zout").addEventListener("click", () => map.zoomBy(1 / 1.5));
  $("#mm-zfit").addEventListener("click", () => map.fit());

  window.martialMap = map; // for teammates' overlays and for debugging
})();
