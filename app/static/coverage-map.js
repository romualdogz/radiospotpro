/* Reichweiten-Karte Österreich: DAB+ (Bundesländer) und UKW (Kreis um den Sender).
 *
 * CoverageMap.render(host, areas, { onPick(lat, lon) })
 *   areas: [{ id, name, technology: "dab"|"ukw", states: [...], center_lat, center_lon, radius_km, reach_text }]
 *   onPick: optional – Klick auf die Karte liefert Breiten-/Längengrad (Admin: Sender-Standort setzen)
 * Kartendaten: /static/austria-map.json (Natural Earth, gemeinfrei). Farbe der Leuchtflächen: --accent.
 */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const KM_PER_DEG_LAT = 111.2;
  let dataPromise = null;
  let uid = 0;

  const STYLE = `
.coverage-map { position: relative; background: #141416; border-radius: 14px; padding: 10px;
  --map-base: #26262b; --map-line: #3a3a41; --map-text: #c9c9d1; }
.coverage-map svg { display: block; width: 100%; height: auto; }
.coverage-map .cm-state { fill: var(--map-base); stroke: var(--map-line); stroke-width: 1.2; transition: fill .4s, fill-opacity .4s; }
.coverage-map .cm-lit { fill: var(--accent, #e4002b); }
.coverage-map .cm-dab { fill-opacity: .62; }
.coverage-map .cm-ukw { fill-opacity: .38; }
.coverage-map .cm-glow { fill: none; stroke: var(--accent, #e4002b); stroke-width: 2.4; }
.coverage-map .cm-ring { fill: none; stroke: var(--accent, #e4002b); stroke-width: 2; stroke-dasharray: 6 5; }
.coverage-map .cm-pulse { fill: none; stroke: var(--accent, #e4002b); stroke-width: 2; opacity: 0;
  transform-box: fill-box; transform-origin: center; animation: cm-pulse 2.6s ease-out infinite; }
@keyframes cm-pulse { 0% { opacity: .7; transform: scale(.35); } 100% { opacity: 0; transform: scale(1.08); } }
@media (prefers-reduced-motion: reduce) { .coverage-map .cm-pulse { animation: none; } }
.coverage-map .cm-dot { fill: #fff; }
.coverage-map .cm-city { fill: var(--map-text); font: 500 var(--cm-city, 15px) system-ui, sans-serif; opacity: .75; }
.coverage-map .cm-label { fill: #fff; font: 700 var(--cm-label, 17px) system-ui, sans-serif; paint-order: stroke;
  stroke: rgba(0,0,0,.65); stroke-width: 4px; stroke-linejoin: round; }
.coverage-map .cm-loading { color: var(--map-text); padding: 40px; text-align: center; font-size: .9rem; }
`;

  function injectStyle() {
    if (document.getElementById("coverage-map-style")) return;
    const s = document.createElement("style");
    s.id = "coverage-map-style";
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  function load() {
    if (!dataPromise) {
      dataPromise = fetch("/static/austria-map.json").then((r) => {
        if (!r.ok) throw new Error("Karte konnte nicht geladen werden");
        return r.json();
      });
    }
    return dataPromise;
  }

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }

  function title(node, text) {
    el("title", {}, node).textContent = text;
  }

  async function render(host, areas, opts = {}) {
    injectStyle();
    host.classList.add("coverage-map");
    let map;
    try {
      map = await load();
    } catch (e) {
      host.innerHTML = '<div class="cm-loading">Karte konnte nicht geladen werden.</div>';
      return;
    }
    const p = map.projection;
    const project = (lat, lon) => [p.pad + (lon - p.lon_min) * p.kx * p.scale, p.pad + (p.lat_max - lat) * p.scale];
    const unproject = (x, y) => [p.lat_max - (y - p.pad) / p.scale, p.lon_min + (x - p.pad) / (p.kx * p.scale)];
    const kmToPx = p.scale / KM_PER_DEG_LAT;

    const dab = new Set(), ukw = new Set();
    for (const a of areas) for (const s of a.states || []) (a.technology === "dab" ? dab : ukw).add(s);

    const id = ++uid;
    const svg = el("svg", { viewBox: map.viewBox.join(" "), role: "img",
      "aria-label": areas.length ? "Sendegebiet: " + areas.map((a) => a.name).join(", ") : "Österreich-Karte" });
    const defs = el("defs", {}, svg);
    const grad = el("radialGradient", { id: `cm-grad-${id}` }, defs);
    el("stop", { offset: "0%", "stop-color": "var(--accent, #e4002b)", "stop-opacity": ".85" }, grad);
    el("stop", { offset: "65%", "stop-color": "var(--accent, #e4002b)", "stop-opacity": ".4" }, grad);
    el("stop", { offset: "100%", "stop-color": "var(--accent, #e4002b)", "stop-opacity": "0" }, grad);
    const glow = el("filter", { id: `cm-glow-${id}`, x: "-20%", y: "-20%", width: "140%", height: "140%" }, defs);
    el("feGaussianBlur", { stdDeviation: "5" }, glow);

    // Bundesländer
    const lit = [];
    for (const s of map.states) {
      const tech = dab.has(s.key) ? "dab" : ukw.has(s.key) ? "ukw" : "";
      const path = el("path", { d: s.d, class: "cm-state" + (tech ? ` cm-lit cm-${tech}` : "") }, svg);
      title(path, s.name + (tech ? (tech === "dab" ? " – DAB+" : " – UKW") : ""));
      if (tech) lit.push(s);
    }
    // Leuchtender Rand um die gewählten Bundesländer
    if (lit.length) {
      const g = el("g", { filter: `url(#cm-glow-${id})`, "pointer-events": "none" }, svg);
      for (const s of lit) el("path", { d: s.d, class: "cm-glow" }, g);
      const crisp = el("g", { "pointer-events": "none", opacity: ".9" }, svg);
      for (const s of lit) el("path", { d: s.d, class: "cm-glow", "stroke-width": "1.2" }, crisp);
    }

    // Städte zur Orientierung (dezent)
    const shown = ["Wien", "Graz", "Linz", "Salzburg", "Innsbruck", "Klagenfurt", "Bregenz"];
    const labelled = new Set(areas.filter((a) => a.center_lat != null).map((a) => a.name));
    for (const c of map.cities.filter((c) => shown.includes(c.name))) {
      el("circle", { cx: c.xy[0], cy: c.xy[1], r: 2.6, class: "cm-dot", opacity: ".6" }, svg);
      if (![...labelled].some((n) => n.includes(c.name))) {
        el("text", { x: c.xy[0] + 6, y: c.xy[1] - 6, class: "cm-city" }, svg).textContent = c.name;
      }
    }

    // UKW-Sender: Kreis mit Verlauf, gestrichelter Rand, pulsierender Ring, Beschriftung
    for (const a of areas) {
      if (a.center_lat == null || a.center_lon == null || !(a.radius_km > 0)) continue;
      const [x, y] = project(a.center_lat, a.center_lon);
      const r = a.radius_km * kmToPx;
      const g = el("g", {}, svg);
      title(g, `${a.name}${a.reach_text ? " – " + a.reach_text : ""} (ca. ${a.radius_km} km um den Sender)`);
      el("circle", { cx: x, cy: y, r, fill: `url(#cm-grad-${id})` }, g);
      el("circle", { cx: x, cy: y, r, class: "cm-ring" }, g);
      el("circle", { cx: x, cy: y, r, class: "cm-pulse" }, g);
      el("circle", { cx: x, cy: y, r: 4.5, class: "cm-dot" }, g);
      const t = el("text", { x, y: y - Math.min(r, 60) - 8, class: "cm-label", "text-anchor": "middle" }, g);
      t.textContent = a.name;
    }

    if (opts.onPick) {
      svg.style.cursor = "crosshair";
      svg.addEventListener("click", (ev) => {
        const pt = svg.createSVGPoint();
        pt.x = ev.clientX; pt.y = ev.clientY;
        const loc = pt.matrixTransform(svg.getScreenCTM().inverse());
        const [lat, lon] = unproject(loc.x, loc.y);
        opts.onPick(lat, lon);
      });
    }
    host.replaceChildren(svg);
    // Schrift auf schmalen Bildschirmen mitskalieren (Karte wird als Ganzes verkleinert)
    const factor = Math.max(1, Math.min(2.6, 640 / Math.max(host.clientWidth, 1)));
    host.style.setProperty("--cm-city", `${(15 * factor).toFixed(1)}px`);
    host.style.setProperty("--cm-label", `${(17 * factor).toFixed(1)}px`);
  }

  window.CoverageMap = { render, load };
})();
