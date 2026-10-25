/* Reichweiten-Karte Österreich: DAB+ (Bundesländer) und UKW (Kreis um den Sender).
 *
 * CoverageMap.render(host, areas, { onPick(lat, lon) })
 *   areas: [{ id, name, technology: "dab"|"ukw", states: [...], center_lat, center_lon, radius_km, reach_text, color }]
 *   color: "#rrggbb" (Sender- bzw. Gebietsfarbe) oder leer = Akzentfarbe
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
.coverage-map .cm-glow { fill: none; stroke-width: 2.4; }
.coverage-map .cm-ring { fill: none; stroke-width: 2; stroke-dasharray: 6 5; }
.coverage-map .cm-pulse { fill: none; stroke-width: 2; opacity: 0;
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

    // Akzentfarbe aus dem Design auslesen – var() in SVG-Attributen versteht nicht jeder Browser
    const ACCENT = getComputedStyle(host).getPropertyValue("--accent").trim() || "#e4002b";
    const colorOf = (a) => (/^#[0-9a-fA-F]{6}$/.test(a.color || "") ? a.color : ACCENT);
    // je Bundesland die Farben, in denen es leuchtet (DAB+ vor UKW, jede Farbe nur einmal)
    const layers = new Map();
    const hasCircle = (a) => a.center_lat != null && a.center_lon != null && a.radius_km > 0;
    for (const a of areas) {
      // UKW mit Sender-Standort: nur der Kreis – das ganze Bundesland einzufärben würde zu viel versprechen
      if (a.technology === "ukw" && hasCircle(a)) continue;
      for (const key of a.states || []) {
        const list = layers.get(key) || [];
        const color = colorOf(a), found = list.find((l) => l.color === color);
        if (!found) list.push({ color, tech: a.technology });
        else if (a.technology === "dab") found.tech = "dab";
        layers.set(key, list);
      }
    }

    const id = ++uid;
    const svg = el("svg", { viewBox: map.viewBox.join(" "), role: "img",
      "aria-label": areas.length ? "Sendegebiet: " + areas.map((a) => a.name).join(", ") : "Österreich-Karte" });
    const defs = el("defs", {}, svg);
    const glow = el("filter", { id: `cm-glow-${id}`, x: "-20%", y: "-20%", width: "140%", height: "140%" }, defs);
    el("feGaussianBlur", { stdDeviation: "5" }, glow);
    const gradients = new Map();
    const gradientFor = (color) => {  // Verlauf für UKW-Kreise, einer je Farbe
      if (!gradients.has(color)) {
        const gid = `cm-grad-${id}-${gradients.size}`;
        const grad = el("radialGradient", { id: gid }, defs);
        el("stop", { offset: "0%", "stop-color": color, "stop-opacity": ".85" }, grad);
        el("stop", { offset: "65%", "stop-color": color, "stop-opacity": ".4" }, grad);
        el("stop", { offset: "100%", "stop-color": color, "stop-opacity": "0" }, grad);
        gradients.set(color, gid);
      }
      return gradients.get(color);
    };

    // Streifenmuster für Bundesländer, die in mehreren Farben leuchten (z. B. Energy + Nostalgie)
    const patterns = new Map();
    const stripesFor = (colors) => {
      const key = colors.join(",");
      if (!patterns.has(key)) {
        const pid = `cm-stripes-${id}-${patterns.size}`, w = 9;
        const pat = el("pattern", { id: pid, width: w * colors.length, height: 10, patternUnits: "userSpaceOnUse",
          patternTransform: "rotate(45)" }, defs);
        colors.forEach((c, i) => el("rect", { x: i * w, y: 0, width: w, height: 10, fill: c }, pat));
        patterns.set(key, pid);
      }
      return patterns.get(key);
    };

    // Bundesländer: Grundfläche, darüber die leuchtende Fläche – bei mehreren Farben gestreift
    const byColor = new Map();
    for (const s of map.states) {
      const list = layers.get(s.key) || [];
      const path = el("path", { d: s.d, class: "cm-state" }, svg);
      const techs = [...new Set(list.map((l) => (l.tech === "dab" ? "DAB+" : "UKW")))];
      title(path, s.name + (techs.length ? " – " + techs.join(" & ") : ""));
      if (list.length) {
        const opacity = list.some((l) => l.tech === "dab") ? 0.62 : 0.38;
        const fill = list.length > 1 ? `url(#${stripesFor(list.map((l) => l.color))})` : list[0].color;
        el("path", { d: s.d, fill, "fill-opacity": opacity, "pointer-events": "none" }, svg);
      }
      for (const l of list) {
        if (!byColor.has(l.color)) byColor.set(l.color, []);
        byColor.get(l.color).push(s);
      }
    }
    // Leuchtender Rand um die gewählten Bundesländer – in der jeweiligen Farbe
    for (const [color, states] of byColor) {
      const g = el("g", { filter: `url(#cm-glow-${id})`, "pointer-events": "none" }, svg);
      for (const s of states) el("path", { d: s.d, class: "cm-glow", stroke: color }, g);
      const crisp = el("g", { "pointer-events": "none", opacity: ".9" }, svg);
      for (const s of states) el("path", { d: s.d, class: "cm-glow", stroke: color, "stroke-width": "1.2" }, crisp);
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

    // UKW-Sender: Kreis mit Verlauf, gestrichelter Rand, pulsierender Ring, Beschriftung (je Gebiet einmal)
    const labels = new Set(), sameSpot = new Map();
    for (const a of areas) {
      if (a.center_lat == null || a.center_lon == null || !(a.radius_km > 0)) continue;
      const [x, y] = project(a.center_lat, a.center_lon);
      // mehrere Sender am selben Standort: Kreise ineinander, damit jede Farbe sichtbar bleibt
      const spot = `${x.toFixed(0)}|${y.toFixed(0)}|${a.radius_km}`;
      const n = sameSpot.get(spot) || 0;
      sameSpot.set(spot, n + 1);
      const r = a.radius_km * kmToPx * (1 - 0.22 * n);
      const color = colorOf(a);
      const g = el("g", {}, svg);
      title(g, `${a.name}${a.reach_text ? " – " + a.reach_text : ""} (ca. ${a.radius_km} km um den Sender)`);
      el("circle", { cx: x, cy: y, r, fill: `url(#${gradientFor(color)})` }, g);
      el("circle", { cx: x, cy: y, r, class: "cm-ring", stroke: color }, g);
      el("circle", { cx: x, cy: y, r, class: "cm-pulse", stroke: color }, g);
      el("circle", { cx: x, cy: y, r: 4.5, class: "cm-dot" }, g);
      const key = `${a.name}|${x.toFixed(0)}|${y.toFixed(0)}`;
      if (!labels.has(key)) {
        labels.add(key);
        const t = el("text", { x, y: y - Math.min(r, 60) - 8, class: "cm-label", "text-anchor": "middle" }, g);
        t.textContent = a.name;
      }
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
