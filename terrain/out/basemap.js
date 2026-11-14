/*
 * MartialBaseMap - the SVG base map (Person 2).
 *
 *   const map = MartialBaseMap.create(containerEl, config, { onCursor, onViewChange });
 *   map.setLayerVisible("hazards", true); map.setLayerOpacity("hazards", 0.6);
 *   map.addOverlay("routes", (g, view, C) => { ...draw in screen px with C.toScreen(view, en)... });
 *   map.flyTo([east, north], pxPerMetre); map.fit();
 *
 * `config` is map_config.json. Raster layers are drawn in image metres inside one
 * transformed <g>, so they stay crisp and aligned. Everything else (markers, labels,
 * north arrow, scale bar) is redrawn in screen pixels on every view change, so symbols
 * stay the same size at any zoom. Teammates add their own overlays with addOverlay().
 */
(function (root) {
  "use strict";
  const C = root.MarsCoords;
  const NS = "http://www.w3.org/2000/svg";

  function el(name, attrs = {}, parent) {
    const e = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }

  function create(container, config, opts = {}) {
    const site = config.site;
    const svg = el("svg", { class: "mm-svg", role: "img", "aria-label": `Map of ${site.name}` }, container);
    el("rect", { class: "mm-space", width: "100%", height: "100%" }, svg);
    const world = el("g", { class: "mm-world" }, svg);
    const screen = el("g", { class: "mm-screen" }, svg);
    const chrome = el("g", { class: "mm-chrome" }, svg);

    // ---- raster layers, in image metres -------------------------------------
    const layerEls = {};
    const state = {};
    for (const L of config.layers) {
      state[L.id] = { visible: !!L.visible, opacity: L.opacity ?? 1 };
      if (L.kind !== "image") continue;
      const img = el("image", {
        href: L.href, x: 0, y: 0, width: site.width_m, height: site.height_m,
        preserveAspectRatio: "none", class: `mm-layer mm-layer-${L.id}`,
      }, world);
      layerEls[L.id] = img;
    }
    el("rect", { x: 0, y: 0, width: site.width_m, height: site.height_m, class: "mm-site-edge", "vector-effect": "non-scaling-stroke" }, world);

    // ---- overlays drawn in screen px -----------------------------------------
    const overlays = []; // {id, g, draw}
    function addOverlay(id, draw, { layerId = id } = {}) {
      const g = el("g", { class: `mm-overlay mm-overlay-${id}` }, screen);
      overlays.push({ id, layerId, g, draw });
      redraw();
      return g;
    }

    let view = C.fit(site, container.clientWidth || 800, container.clientHeight || 600);
    const zoomLimits = () => ({ min: C.fit(site, view.w, view.h).s * 0.5, max: config.max_px_per_m ?? 24 });

    function applyLayerState() {
      for (const L of config.layers) {
        const st = state[L.id];
        const target = layerEls[L.id] || overlays.find((o) => o.layerId === L.id)?.g;
        if (!target) continue;
        target.style.display = st.visible ? "" : "none";
        target.style.opacity = st.opacity;
      }
    }

    function redraw() {
      world.setAttribute("transform", C.svgTransform(view, site));
      // crisp pixels once zoomed past 1 screen px per data cell
      world.classList.toggle("mm-pixelated", view.s / site.cell_m > 2);
      for (const o of overlays) {
        o.g.replaceChildren();
        o.draw(o.g, view, C, el);
      }
      drawChrome();
      applyLayerState();
      opts.onViewChange?.(view);
    }

    // ---- north arrow, scale bar, attribution ----------------------------------
    function drawChrome() {
      chrome.replaceChildren();
      const pad = 16;
      // north arrow (grid north = map up; the site grid is north-aligned)
      const na = el("g", { class: "mm-north", transform: `translate(${view.w - pad - 22}, ${pad + 30})` }, chrome);
      el("circle", { r: 24, class: "mm-chip" }, na);
      el("path", { d: "M0,-17 L7,6 L0,1 L-7,6 Z", class: "mm-north-head" }, na);
      el("path", { d: "M0,1 L7,6 L0,15 L-7,6 Z", class: "mm-north-tail" }, na);
      const nl = el("text", { x: 0, y: 32 + 10, "text-anchor": "middle", class: "mm-small" }, na);
      nl.textContent = "N";

      // scale bar: alternating segments, nice length
      const sb = C.niceScaleBar(view, Math.min(180, view.w * 0.3));
      const g = el("g", { class: "mm-scale", transform: `translate(${pad}, ${view.h - pad - 10})` }, chrome);
      el("rect", { x: -10, y: -26, width: sb.px + 112, height: 42, rx: 8, class: "mm-chip" }, g);
      for (let i = 0; i < 4; i++) {
        el("rect", { x: (i * sb.px) / 4, y: 0, width: sb.px / 4, height: 6, class: i % 2 ? "mm-sb-light" : "mm-sb-dark" }, g);
      }
      el("rect", { x: 0, y: 0, width: sb.px, height: 6, class: "mm-sb-frame" }, g);
      const t0 = el("text", { x: 0, y: -8, class: "mm-small" }, g); t0.textContent = "0";
      const t1 = el("text", { x: sb.px, y: -8, "text-anchor": "middle", class: "mm-small" }, g); t1.textContent = sb.label;
      const t2 = el("text", { x: sb.px + 12, y: 7, class: "mm-small mm-dim" }, g);
      t2.textContent = `1 px ≈ ${fmtLen(1 / view.s)}`;
    }

    function fmtLen(m) {
      return m >= 1 ? `${m.toFixed(m >= 10 ? 0 : 1)} m` : `${Math.round(m * 100)} cm`;
    }

    // ---- interaction: drag, wheel, pinch, keyboard ---------------------------
    const pointers = new Map();
    let pinch = null;
    svg.addEventListener("pointerdown", (e) => {
      svg.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, [e.offsetX, e.offsetY]);
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), s: view.s };
      }
    });
    svg.addEventListener("pointermove", (e) => {
      const xy = [e.offsetX, e.offsetY];
      opts.onCursor?.(C.toMap(view, xy), view);
      if (!pointers.has(e.pointerId)) return;
      const prev = pointers.get(e.pointerId);
      pointers.set(e.pointerId, xy);
      if (pointers.size === 1) {
        setView(C.pan(view, xy[0] - prev[0], xy[1] - prev[1]));
      } else if (pointers.size === 2 && pinch) {
        const [a, b] = [...pointers.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        setView(C.zoomAt(view, mid, (pinch.s * d) / pinch.d / view.s, zoomLimits()));
      }
    });
    const up = (e) => { pointers.delete(e.pointerId); if (pointers.size < 2) pinch = null; };
    svg.addEventListener("pointerup", up);
    svg.addEventListener("pointercancel", up);
    svg.addEventListener("pointerleave", () => opts.onCursor?.(null, view));
    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      setView(C.zoomAt(view, [e.offsetX, e.offsetY], Math.exp(-e.deltaY * 0.0015), zoomLimits()));
    }, { passive: false });
    svg.tabIndex = 0;
    svg.addEventListener("keydown", (e) => {
      const step = 60, c = [view.w / 2, view.h / 2];
      const k = { ArrowLeft: () => C.pan(view, step, 0), ArrowRight: () => C.pan(view, -step, 0),
        ArrowUp: () => C.pan(view, 0, step), ArrowDown: () => C.pan(view, 0, -step),
        "+": () => C.zoomAt(view, c, 1.4, zoomLimits()), "=": () => C.zoomAt(view, c, 1.4, zoomLimits()),
        "-": () => C.zoomAt(view, c, 1 / 1.4, zoomLimits()), "0": () => C.fit(site, view.w, view.h) }[e.key];
      if (k) { e.preventDefault(); setView(k()); }
    });

    function setView(v) {
      view = C.constrain(v, site);
      redraw();
    }

    new ResizeObserver(() => {
      const w = container.clientWidth, h = container.clientHeight;
      if (w && h && (w !== view.w || h !== view.h)) setView(C.resize(view, w, h));
    }).observe(container);

    redraw();

    return {
      get view() { return view; },
      site,
      coords: C,
      toScreen: (en) => C.toScreen(view, en),
      toMap: (xy) => C.toMap(view, xy),
      setView,
      fit: () => setView(C.fit(site, view.w, view.h)),
      zoomBy: (f) => setView(C.zoomAt(view, [view.w / 2, view.h / 2], f, zoomLimits())),
      flyTo: (en, s = view.s) => setView({ ...view, cx: en[0], cy: en[1], s }),
      setLayerVisible: (id, on) => { state[id].visible = on; applyLayerState(); },
      setLayerOpacity: (id, op) => { state[id].opacity = op; applyLayerState(); },
      layerState: (id) => ({ ...state[id] }),
      addOverlay,
      redraw,
      svg,
    };
  }

  // ---- standard overlays the base map provides --------------------------------
  const overlaysLib = {
    /** Labelled coordinate grid every "nice" interval. */
    grid(site) {
      return (g, v, C, el) => {
        const step = C.niceGridStep(v);
        const b = C.visibleBounds(v);
        const e0 = Math.max(0, Math.ceil(b.e0 / step) * step), e1 = Math.min(site.width_m, b.e1);
        const n0 = Math.max(0, Math.ceil(b.n0 / step) * step), n1 = Math.min(site.height_m, b.n1);
        const [, yTop] = C.toScreen(v, [0, Math.min(site.height_m, b.n1)]);
        const [, yBot] = C.toScreen(v, [0, Math.max(0, b.n0)]);
        const [xL] = C.toScreen(v, [Math.max(0, b.e0), 0]);
        const [xR] = C.toScreen(v, [Math.min(site.width_m, b.e1), 0]);
        for (let e = e0; e <= e1 + 1e-9; e += step) {
          const [x] = C.toScreen(v, [e, 0]);
          el("line", { x1: x, x2: x, y1: yTop, y2: yBot, class: "mm-grid" }, g);
          const t = el("text", { x: x + 3, y: Math.max(yTop, 0) + 12, class: "mm-grid-label" }, g);
          t.textContent = `E${Math.round(e)}`;
        }
        for (let n = n0; n <= n1 + 1e-9; n += step) {
          const [, y] = C.toScreen(v, [0, n]);
          el("line", { x1: xL, x2: xR, y1: y, y2: y, class: "mm-grid" }, g);
          const t = el("text", { x: Math.max(xL, 64) + 3, y: y - 3, class: "mm-grid-label" }, g);
          t.textContent = `N${Math.round(n)}`;
        }
      };
    },

    /** Landmarks: crosshair + label. Used to check that every layer lines up. */
    landmarks(features) {
      return (g, v, C, el) => {
        for (const f of features) {
          const [x, y] = C.toScreen(v, f.geometry.coordinates);
          if (x < -50 || y < -50 || x > v.w + 50 || y > v.h + 50) continue;
          const m = el("g", { transform: `translate(${x},${y})`, class: "mm-landmark" }, g);
          el("circle", { r: 9, class: "mm-landmark-ring" }, m);
          el("path", { d: "M-15,0H-5M5,0H15M0,-15V-5M0,5V15", class: "mm-landmark-cross" }, m);
          const t = el("text", { x: 13, y: -11, class: "mm-landmark-label" }, m);
          t.textContent = f.properties.name;
          el("title", {}, m).textContent = `${f.properties.name}\n${C.formatEN(f.geometry.coordinates, 1)}`;
        }
      };
    },

    /** Polylines (e.g. rover tracks). */
    lines(features, cls = "mm-track") {
      return (g, v, C, el) => {
        for (const f of features) {
          const gt = f.geometry?.type;
          const parts = gt === "LineString" ? [f.geometry.coordinates] : gt === "MultiLineString" ? f.geometry.coordinates : [];
          for (const p of parts) {
            const d = p.map((en, i) => (i ? "L" : "M") + C.toScreen(v, en).map((n) => n.toFixed(1)).join(",")).join("");
            el("path", { d, class: `${cls}-casing` }, g);
            el("path", { d, class: cls }, g);
          }
        }
      };
    },
  };

  root.MartialBaseMap = { create, overlays: overlaysLib };
})(typeof self !== "undefined" ? self : this);
