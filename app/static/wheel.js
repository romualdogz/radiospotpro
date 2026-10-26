/* Rabatt-Glücksrad (SVG) – genutzt im Konfigurator und in der Vorschau unter Admin → Glücksrad.
 *
 * const w = DiscountWheel.render(host, segments)   segments: [{label, percent}]
 * await w.spinTo(index)                            dreht mehrere Runden und hält auf dem Feld an
 * Wo das Rad hält, entscheidet immer der Server (/api/wheel/spin) – diese Datei zeichnet nur.
 */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const SIZE = 320, R = 150, C = SIZE / 2;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const STYLE = `
.wheel-svg { display: block; width: 100%; max-width: 340px; height: auto; margin: 0 auto; overflow: visible; }
.wheel-rotor { transform-origin: ${C}px ${C}px; }
.wheel-seg { stroke: #fff; stroke-width: 2; }
.wheel-win-a { fill: var(--accent, #e4002b); }
.wheel-win-b { fill: color-mix(in srgb, var(--accent, #e4002b) 70%, #000); }
.wheel-jackpot { fill: #ffd23f; }
.wheel-miss { fill: #f1f1f1; }
.wheel-label { font-family: var(--head, system-ui, sans-serif); font-weight: 800; fill: #fff; paint-order: stroke;
  stroke: rgba(0,0,0,.25); stroke-width: 2px; }
.wheel-label-jackpot { fill: #5a3d00; stroke: none; }
.wheel-label-miss { fill: #777; stroke: none; font-weight: 700; }
.wheel-rim { fill: none; stroke: #141414; stroke-width: 8; }
.wheel-bulb { fill: #ffd23f; }
.wheel-bulb.alt { fill: #fff; }
.wheel-svg.spinning .wheel-bulb { animation: wheel-blink .3s steps(1) infinite; }
.wheel-svg.spinning .wheel-bulb.alt { animation-delay: .15s; }
@keyframes wheel-blink { 50% { fill: #ff7bac; } }
.wheel-hub { fill: #141414; stroke: #ffd23f; stroke-width: 4; }
.wheel-hub-text { fill: #ffd23f; font: 800 20px var(--head, system-ui, sans-serif); }
.wheel-pointer { fill: #141414; stroke: #ffd23f; stroke-width: 3; stroke-linejoin: round;
  filter: drop-shadow(0 3px 3px rgba(0,0,0,.35)); }
`;

  function injectStyle() {
    if (document.getElementById("discount-wheel-style")) return;
    const s = document.createElement("style");
    s.id = "discount-wheel-style";
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }
  const point = (angle, r) => [C + r * Math.sin(angle), C - r * Math.cos(angle)];  // 0 = oben, im Uhrzeigersinn

  function render(host, segments) {
    injectStyle();
    const n = segments.length, step = (2 * Math.PI) / n;
    const best = Math.max(...segments.map((s) => s.percent));
    const svg = el("svg", { viewBox: `0 0 ${SIZE} ${SIZE + 14}`, class: "wheel-svg", role: "img",
      "aria-label": "Glücksrad: " + segments.map((s) => s.label).join(", ") });
    const rotor = el("g", { class: "wheel-rotor" }, svg);
    segments.forEach((s, i) => {
      const a0 = i * step, a1 = (i + 1) * step;
      const [x0, y0] = point(a0, R), [x1, y1] = point(a1, R);
      const kind = s.percent === 0 ? "miss" : s.percent === best ? "jackpot" : i % 2 ? "win-b" : "win-a";
      el("path", { d: `M${C},${C} L${x0},${y0} A${R},${R} 0 ${step > Math.PI ? 1 : 0} 1 ${x1},${y1} Z`,
        class: `wheel-seg wheel-${kind}` }, rotor);
      // Beschriftung entlang des Radius, außen beginnend
      const mid = (a0 + a1) / 2, deg = (mid * 180) / Math.PI;
      // Schrift so groß, dass die Beschriftung zwischen Rand und Mitte passt (Platz ca. 100 px)
      const size = Math.max(8, Math.min(17, (R - 50) / (Math.max(3, s.label.length) * 0.6), (step * R) / 2.4));
      const t = el("text", { x: C, y: C - R + 16, "font-size": size.toFixed(1), class: `wheel-label wheel-label-${kind}`,
        transform: `rotate(${deg} ${C} ${C}) rotate(90 ${C} ${C - R + 16})`, "text-anchor": "start",
        "dominant-baseline": "middle" }, rotor);
      t.textContent = s.label;
    });
    el("circle", { cx: C, cy: C, r: R, class: "wheel-rim" }, rotor);
    for (let i = 0; i < n * 2; i++) {  // Lämpchen am Rand
      const [x, y] = point((i * step) / 2, R - 1);
      el("circle", { cx: x, cy: y, r: 3.2, class: "wheel-bulb" + (i % 2 ? " alt" : "") }, svg);
    }
    el("circle", { cx: C, cy: C, r: 26, class: "wheel-hub" }, svg);
    el("text", { x: C, y: C + 1, class: "wheel-hub-text", "text-anchor": "middle", "dominant-baseline": "middle" }, svg)
      .textContent = "%";
    el("path", { d: `M${C - 15},2 L${C + 15},2 L${C},34 Z`, class: "wheel-pointer" }, svg);  // Zeiger oben
    host.replaceChildren(svg);

    let turned = 0;
    return {
      svg,
      spinTo(index) {
        const jitter = (Math.random() - 0.5) * step * 0.6;  // nicht immer exakt in der Feldmitte
        const target = 360 - ((index + 0.5) * step + jitter) * 180 / Math.PI;
        turned += 360 * 6 + ((target - turned) % 360 + 360) % 360;
        rotor.style.transition = reduceMotion ? "none" : "transform 5s cubic-bezier(.12,.72,.12,1)";
        rotor.style.transform = `rotate(${turned}deg)`;
        svg.classList.add("spinning");
        return new Promise((resolve) => setTimeout(() => { svg.classList.remove("spinning"); resolve(); },
          reduceMotion ? 50 : 5100));
      },
    };
  }

  window.DiscountWheel = { render };
})();
