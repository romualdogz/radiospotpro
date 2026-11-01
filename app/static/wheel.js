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

  // ------------------------------------------------------------------ Variante „Analog-Radio“
  // Röhrenradio mit Senderskala: jedes Feld ist ein „Sender“. Drehen (oder Antippen) am Sendersuchknopf
  // ruft opts.onTune() auf; spinTo(index) lässt den Zeiger suchen und beim Sender anhalten.
  const RADIO_STYLE = `
.radio { --wood1: #7a4a26; --wood2: #4e2c14; position: relative; max-width: 460px; margin: 0 auto; padding: 16px 16px 18px;
  border-radius: 26px 26px 18px 18px; color: #2b1a0c; user-select: none; -webkit-user-select: none;
  background: repeating-linear-gradient(95deg, rgba(255,255,255,.05) 0 3px, transparent 3px 9px),
    linear-gradient(160deg, var(--wood1), var(--wood2));
  box-shadow: inset 0 2px 0 rgba(255,255,255,.25), inset 0 -4px 8px rgba(0,0,0,.35), 0 12px 28px rgba(0,0,0,.35); }
.radio-front { display: grid; grid-template-columns: 1fr auto; gap: 14px; align-items: center; }
.radio-grille { grid-column: 1 / -1; height: 54px; border-radius: 12px; position: relative;
  background: radial-gradient(circle, #3a2a1c 1.4px, transparent 1.6px) 0 0 / 7px 7px, linear-gradient(#d9c7a3, #c4ad84);
  box-shadow: inset 0 2px 6px rgba(0,0,0,.45); display: grid; place-items: center; }
.radio-brand { font: italic 700 0.95rem Georgia, serif; color: #f6e7c4; text-shadow: 0 1px 2px rgba(0,0,0,.6);
  background: rgba(60,35,15,.75); padding: 2px 12px; border-radius: 999px; letter-spacing: .04em; }
.radio-dial { position: relative; height: 112px; border-radius: 10px; overflow: hidden;
  background: linear-gradient(180deg, #fff6d8, #f3dc9c); border: 4px solid #2b1a0c;
  box-shadow: inset 0 0 18px rgba(255,170,40,.55), 0 0 0 2px #b88a45; }
.radio-dial.glow { animation: radio-flicker .18s steps(2) infinite; }
@keyframes radio-flicker { 50% { box-shadow: inset 0 0 26px rgba(255,190,60,.9), 0 0 0 2px #b88a45; } }
.radio-mhz { position: absolute; left: 0; right: 0; top: 4px; height: 18px; font: 600 9px/1 system-ui, sans-serif; color: #7a5a2a; }
.radio-mhz span { position: absolute; transform: translateX(-50%); }
.radio-ticks { position: absolute; left: 6%; right: 6%; top: 18px; height: 10px;
  background: repeating-linear-gradient(90deg, #7a5a2a 0 1px, transparent 1px 2.5%); opacity: .7; }
.radio-station { position: absolute; transform: translateX(-50%); font: 800 11px/1.1 var(--head, system-ui, sans-serif);
  white-space: nowrap; color: #8b1a10; text-align: center; }
.radio-station::before { content: ""; display: block; width: 1px; height: 7px; margin: 0 auto 2px; background: currentColor; opacity: .6; }
.radio-station.miss { color: #8d7a5c; font-weight: 600; }
.radio-station.jackpot { color: #b0002a; }
.radio-station.jackpot::after { content: " ★"; color: #d48a00; }
.radio-station.row2 { top: 64px !important; }
.radio-station.hit { animation: radio-hit .5s ease-in-out 3; }
@keyframes radio-hit { 50% { color: #fff; background: #b0002a; border-radius: 4px; } }
.radio-needle { position: absolute; top: 0; bottom: 0; width: 3px; margin-left: -1.5px; left: 6%;
  background: linear-gradient(#d0141a, #8f0a0f); box-shadow: 0 0 6px rgba(208,20,26,.6); }
.radio-side { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.radio-eye { width: 22px; height: 22px; border-radius: 50%; background: radial-gradient(circle, #2c4a1e 30%, #0f1a0a 72%);
  box-shadow: 0 0 0 3px #2b1a0c, inset 0 0 4px #000; transition: background .3s, box-shadow .3s; }
.radio-eye.on { background: radial-gradient(circle, #d8ffb0 10%, #5fe03a 45%, #1d5a10 75%);
  box-shadow: 0 0 0 3px #2b1a0c, 0 0 16px #6eff40; }
.radio-knob { width: 86px; height: 86px; border-radius: 50%; border: 0; padding: 0; cursor: grab; position: relative; touch-action: none;
  background: radial-gradient(circle at 35% 30%, #fbe7c0 0 8%, transparent 9%),
    repeating-conic-gradient(#3a2414 0 6deg, #5b3a20 6deg 12deg);
  box-shadow: 0 0 0 4px #2b1a0c, 0 0 0 7px #c9a15a, 0 8px 14px rgba(0,0,0,.45), inset 0 -6px 10px rgba(0,0,0,.45); }
.radio-knob:active { cursor: grabbing; }
.radio-knob:focus-visible { outline: 3px solid #ffd23f; outline-offset: 6px; }
.radio-knob::after { content: ""; position: absolute; left: 50%; top: 8px; width: 4px; height: 18px; margin-left: -2px; border-radius: 2px;
  background: #fbe7c0; box-shadow: 0 0 4px rgba(0,0,0,.5); }
.radio-knob-cap { position: absolute; inset: 22px; border-radius: 50%; background: radial-gradient(circle at 40% 35%, #8a5a32, #3a2414);
  box-shadow: inset 0 2px 3px rgba(255,255,255,.2); pointer-events: none; }
.radio-knob.wiggle { animation: radio-wiggle 2.8s ease-in-out infinite; }
@keyframes radio-wiggle { 0%, 70%, 100% { rotate: 0deg; } 78% { rotate: -14deg; } 86% { rotate: 12deg; } 93% { rotate: -5deg; } }
.radio-knob-label { font: 700 0.7rem system-ui, sans-serif; color: #f6e7c4; text-transform: uppercase; letter-spacing: .08em; }
.radio-feet { display: flex; justify-content: space-between; padding: 0 30px; margin-top: -2px; }
.radio-feet i { width: 34px; height: 8px; border-radius: 0 0 8px 8px; background: #2b1a0c; }
@media (prefers-reduced-motion: reduce) { .radio-dial.glow, .radio-knob.wiggle, .radio-station.hit { animation: none; } }
@media (max-width: 480px) {  /* Handy: Skala über die volle Breite, Knopf darunter */
  .radio-front { grid-template-columns: 1fr; }
  .radio-side { flex-direction: row; justify-content: center; gap: 14px; }
  .radio-knob { width: 72px; height: 72px; } .radio-knob-cap { inset: 18px; }
  .radio-station { font-size: 10px; } .radio-grille { height: 40px; }
}
`;

  function renderRadio(host, segments, opts = {}) {
    if (!document.getElementById("discount-radio-style")) {
      const s = document.createElement("style");
      s.id = "discount-radio-style";
      s.textContent = RADIO_STYLE;
      document.head.appendChild(s);
    }
    const div = (cls, text) => { const d = document.createElement("div"); d.className = cls; if (text != null) d.textContent = text; return d; };
    const n = segments.length;
    const best = Math.max(...segments.map((s) => s.percent));
    const pos = (i) => 10 + (80 * (i + 0.5)) / n;  // Position des Senders auf der Skala in %
    const radio = div("radio");
    const front = div("radio-front");
    const grille = div("radio-grille");
    grille.append(div("radio-brand", opts.brand || "Radio"));
    const dial = div("radio-dial");
    dial.setAttribute("role", "img");
    dial.setAttribute("aria-label", "Senderskala: " + segments.map((s) => s.label).join(", "));
    const mhz = div("radio-mhz");
    [88, 92, 96, 100, 104, 108].forEach((f, i) => { const s = document.createElement("span"); s.textContent = f;
      s.style.left = `${6 + i * 17.6}%`; mhz.append(s); });
    dial.append(mhz, div("radio-ticks"));
    const stations = segments.map((s, i) => {
      const st = div("radio-station" + (s.percent === 0 ? " miss" : s.percent === best ? " jackpot" : "") + (i % 2 ? " row2" : ""), s.label);
      st.style.left = pos(i) + "%";
      st.style.top = "34px";
      dial.append(st);
      return st;
    });
    const needle = div("radio-needle");
    dial.append(needle);
    const side = div("radio-side");
    const eye = div("radio-eye");
    const knob = document.createElement("button");
    knob.type = "button";
    knob.className = "radio-knob wiggle";
    knob.setAttribute("aria-label", "Sendersuchknopf drehen – startet die Sendersuche");
    knob.append(div("radio-knob-cap"));
    side.append(eye, knob, div("radio-knob-label", "Sendersuche"));
    front.append(grille, dial, side);
    const feet = div("radio-feet");
    feet.append(document.createElement("i"), document.createElement("i"));
    radio.append(front, feet);
    host.replaceChildren(radio);

    // Knopf drehen: Ziehen im Kreis (ab ca. 40° startet die Suche) oder Antippen / Enter
    let knobAngle = 0, dragging = null, busy = false, moved = 0;
    const setKnob = (deg) => { knobAngle = deg; knob.style.transform = `rotate(${deg}deg)`; };
    const angleAt = (e) => { const r = knob.getBoundingClientRect();
      return Math.atan2(e.clientY - (r.top + r.height / 2), e.clientX - (r.left + r.width / 2)) * 180 / Math.PI; };
    const fire = () => { if (busy || knob.disabled) return; knob.classList.remove("wiggle"); opts.onTune && opts.onTune(); };
    knob.addEventListener("pointerdown", (e) => { if (busy) return; dragging = angleAt(e); moved = 0; knob.setPointerCapture(e.pointerId); });
    knob.addEventListener("pointermove", (e) => {
      if (dragging == null) return;
      const a = angleAt(e); let d = a - dragging; if (d > 180) d -= 360; if (d < -180) d += 360;
      dragging = a; moved += Math.abs(d); setKnob(knobAngle + d);
      if (moved > 40) { dragging = null; fire(); }
    });
    knob.addEventListener("pointerup", () => { if (dragging != null && moved < 6) fire(); dragging = null; });
    knob.addEventListener("keydown", (e) => { if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); fire(); } });
    knob.addEventListener("click", (e) => { if (e.detail === 0) fire(); });  // Tastatur (Enter/Leertaste)

    let current = 6;  // Zeigerposition in %
    function noise(ms) {  // leises Rauschen beim Suchen (nur nach Nutzeraktion, daher erlaubt)
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const buf = ctx.createBuffer(1, ctx.sampleRate * ms / 1000, ctx.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (0.5 + 0.5 * Math.sin(i / 900));
        const src = ctx.createBufferSource(), gain = ctx.createGain(), filter = ctx.createBiquadFilter();
        filter.type = "bandpass"; filter.frequency.value = 1800;
        gain.gain.setValueAtTime(0.0001, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.05, ctx.currentTime + 0.2);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + ms / 1000);
        src.buffer = buf; src.connect(filter).connect(gain).connect(ctx.destination); src.start();
        setTimeout(() => ctx.close(), ms + 200);
      } catch (e) { /* ohne Ton */ }
    }
    return {
      el: radio,
      setBusy(v) { busy = v; knob.disabled = v; },
      spinTo(index) {
        busy = true; knob.disabled = true;
        const target = pos(index) + (Math.random() - 0.5) * (40 / n);
        // Suchlauf: zweimal über die ganze Skala, dann langsam auf den Sender
        const path = [current, 94, 6, 94, Math.max(6, target - 18), Math.min(94, target + 6), target];
        const ms = reduceMotion ? 50 : 4600;
        if (!reduceMotion) { dial.classList.add("glow"); noise(ms - 600); }
        const anim = needle.animate(path.map((p, i) => ({ left: p + "%", offset: [0, .16, .34, .52, .72, .88, 1][i] })),
          { duration: ms, easing: "cubic-bezier(.3,.1,.3,1)", fill: "forwards" });
        const knobAnim = knob.animate([{ transform: `rotate(${knobAngle}deg)` }, { transform: `rotate(${knobAngle + 900}deg)` }],
          { duration: ms, easing: "cubic-bezier(.3,.1,.3,1)", fill: "forwards" });
        return anim.finished.then(() => {
          current = target; knobAngle += 900; knobAnim.cancel(); setKnob(knobAngle);
          dial.classList.remove("glow");
          stations[index].classList.add("hit");
          if (segments[index].percent > 0) eye.classList.add("on");
        });
      },
    };
  }

  // ------------------------------------------------------------------ Variante „Spielautomat“
  // Drei Walzen mit Gewinnlinie und Hebel. Gewinn = dreimal dasselbe Feld auf der Linie,
  // Niete = gemischte Symbole. Hebel ziehen (oder antippen) ruft opts.onTune() auf.
  const SLOT_STYLE = `
.slot { position: relative; max-width: 420px; margin: 0 auto; padding: 0 44px 0 0; user-select: none; -webkit-user-select: none; }
.slot-cabinet { position: relative; border-radius: 22px 22px 14px 14px; padding: 14px 14px 16px;
  background: linear-gradient(180deg, #e8233a, #9c0f22); border: 4px solid #2a0a10;
  box-shadow: inset 0 3px 0 rgba(255,255,255,.35), inset 0 -6px 12px rgba(0,0,0,.35), 0 14px 30px rgba(0,0,0,.4); }
.slot-marquee { position: relative; margin: -2px 0 12px; padding: 8px 10px; border-radius: 12px; text-align: center;
  background: #1a0610; border: 3px solid #ffd23f; box-shadow: inset 0 0 14px rgba(255,210,63,.35); }
.slot-marquee b { font: 400 1rem/1.2 'Press Start 2P', var(--head, system-ui), monospace; color: #ffd23f; letter-spacing: .06em;
  text-shadow: 0 0 8px rgba(255,210,63,.8), 2px 2px 0 #b0002a; }
.slot-bulbs { position: absolute; inset: 3px; pointer-events: none; border-radius: 9px;
  background: radial-gradient(circle, #fff6b0 2px, transparent 2.6px) 0 0 / 16px 100%;
  -webkit-mask: linear-gradient(#000 0 4px, transparent 4px calc(100% - 4px), #000 calc(100% - 4px));
          mask: linear-gradient(#000 0 4px, transparent 4px calc(100% - 4px), #000 calc(100% - 4px)); }
.slot.spinning .slot-bulbs, .slot.won .slot-bulbs { animation: slot-chase .25s steps(2) infinite; }
@keyframes slot-chase { 50% { background-position: 8px 0; } }
.slot-window { position: relative; display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 8px;
  border-radius: 10px; background: #2a0a10; box-shadow: inset 0 4px 10px rgba(0,0,0,.7); }
.slot-reel { position: relative; height: 162px; overflow: hidden; border-radius: 6px;
  background: linear-gradient(#bdbdbd, #fff 22%, #fff 78%, #bdbdbd); }
.slot-strip { position: absolute; left: 0; right: 0; top: 0; will-change: transform; }
.slot-cell { height: 54px; display: grid; place-items: center; font: 800 15px/1 var(--head, system-ui, sans-serif);
  color: #b0002a; white-space: nowrap; padding: 0 4px; text-align: center; }
.slot-cell.emoji { font-size: 28px; }
.slot-cell.miss { color: #8a8a8a; font-size: 12px; font-weight: 700; }
.slot-cell.jackpot { color: #c47a00; }
.slot-cell.jackpot::after { content: "★"; margin-left: 3px; }
.slot-payline { position: absolute; left: 4px; right: 4px; top: 50%; height: 3px; margin-top: -1.5px; pointer-events: none;
  background: rgba(208,20,26,.75); box-shadow: 0 0 6px rgba(208,20,26,.8); }
.slot-payline::before, .slot-payline::after { content: ""; position: absolute; top: -7px; border: 8px solid transparent; }
.slot-payline::before { left: -6px; border-left-color: #ffd23f; }
.slot-payline::after { right: -6px; border-right-color: #ffd23f; }
.slot.won .slot-payline { animation: slot-flash .3s steps(2) 6; }
@keyframes slot-flash { 50% { background: #ffd23f; box-shadow: 0 0 14px #ffd23f; } }
.slot-tray { margin-top: 12px; height: 18px; border-radius: 0 0 10px 10px; background: linear-gradient(#2a0a10, #4a1520);
  box-shadow: inset 0 4px 6px rgba(0,0,0,.6); }
.slot-lever { position: absolute; right: 0; top: 70px; width: 44px; height: 170px; border: 0; padding: 0; background: none;
  cursor: grab; touch-action: none; }
.slot-lever:focus-visible { outline: 3px solid #ffd23f; outline-offset: 4px; border-radius: 8px; }
.slot-lever-base { position: absolute; left: 0; bottom: 18px; width: 22px; height: 46px; border-radius: 0 10px 10px 0;
  background: linear-gradient(90deg, #8a8a8a, #e6e6e6, #8a8a8a); }
.slot-lever-arm { position: absolute; left: 14px; bottom: 38px; width: 10px; height: 118px; border-radius: 5px;
  transform-origin: 50% 100%; background: linear-gradient(90deg, #9a9a9a, #f4f4f4, #9a9a9a); transition: transform .12s; }
.slot-lever-arm::after { content: ""; position: absolute; left: 50%; top: -16px; width: 32px; height: 32px; margin-left: -16px;
  border-radius: 50%; background: radial-gradient(circle at 35% 30%, #ff8a9a, #d0141a 55%, #6d0610);
  box-shadow: 0 4px 8px rgba(0,0,0,.4); }
.slot-lever.wiggle .slot-lever-arm { animation: slot-hint 3s ease-in-out infinite; }
@keyframes slot-hint { 0%, 75%, 100% { transform: rotateX(0); } 82% { transform: scaleY(.82); } 90% { transform: scaleY(1.03); } }
.slot-lever.pulled .slot-lever-arm { transform: scaleY(-.55); }
@media (prefers-reduced-motion: reduce) { .slot-bulbs, .slot-payline, .slot-lever-arm { animation: none !important; } }
@media (max-width: 420px) { .slot { padding-right: 38px; } .slot-cell { font-size: 13px; } .slot-cell.miss { font-size: 10px; }
  .slot-marquee b { font-size: .8rem; } }
`;
  const FILLERS = ["🍒", "📻", "🔔", "⭐", "🎵", "🍋"];

  function renderSlot(host, segments, opts = {}) {
    if (!document.getElementById("discount-slot-style")) {
      const s = document.createElement("style");
      s.id = "discount-slot-style";
      s.textContent = SLOT_STYLE;
      document.head.appendChild(s);
    }
    const div = (cls, text) => { const d = document.createElement("div"); d.className = cls; if (text != null) d.textContent = text; return d; };
    const best = Math.max(...segments.map((s) => s.percent));
    const CELL = 54;
    const slot = div("slot");
    const cab = div("slot-cabinet");
    const marquee = div("slot-marquee");
    const title = document.createElement("b"); title.textContent = opts.title || "JACKPOT";
    marquee.append(div("slot-bulbs"), title);
    const win = div("slot-window");
    win.setAttribute("role", "img");
    win.setAttribute("aria-label", "Spielautomat mit drei Walzen: " + segments.map((s) => s.label).join(", "));
    const wins = segments.map((s, i) => ({ ...s, i })).filter((s) => s.percent > 0);
    // Walzen-Inhalt: alle Gewinnfelder + Füllsymbole, gemischt, je Walze anders
    const cellFor = (sym) => {
      if (typeof sym === "string") return div("slot-cell emoji", sym);
      return div("slot-cell" + (sym.percent === best ? " jackpot" : ""), sym.label);
    };
    const reels = [0, 1, 2].map((r) => {
      const base = [...wins, ...FILLERS].sort(() => Math.random() - 0.5);
      const reel = div("slot-reel");
      const strip = div("slot-strip");
      reel.append(strip);
      win.append(reel);
      return { reel, strip, base, pos: Math.floor(Math.random() * base.length), r };
    });
    const fill = (rl, items) => { rl.strip.replaceChildren(...items.map(cellFor)); };
    reels.forEach((rl) => {  // Startbild: drei Zeilen sichtbar
      const n = rl.base.length;
      fill(rl, [rl.base[(rl.pos + n - 1) % n], rl.base[rl.pos], rl.base[(rl.pos + 1) % n]]);
    });
    win.append(div("slot-payline"));
    cab.append(marquee, win, div("slot-tray"));
    const lever = document.createElement("button");
    lever.type = "button";
    lever.className = "slot-lever wiggle";
    lever.setAttribute("aria-label", "Hebel ziehen – startet den Spielautomaten");
    const arm = div("slot-lever-arm");
    lever.append(div("slot-lever-base"), arm);
    slot.append(cab, lever);
    host.replaceChildren(slot);

    let busy = false, startY = null;
    const fire = () => {
      if (busy) return;
      lever.classList.remove("wiggle"); lever.classList.add("pulled");
      setTimeout(() => lever.classList.remove("pulled"), 380);
      opts.onTune && opts.onTune();
    };
    lever.addEventListener("pointerdown", (e) => { if (!busy) { startY = e.clientY; lever.setPointerCapture(e.pointerId); } });
    lever.addEventListener("pointermove", (e) => {
      if (startY == null) return;
      const d = Math.max(0, Math.min(90, e.clientY - startY));
      arm.style.transform = `scaleY(${1 - d / 60})`;
      if (d > 45) { startY = null; arm.style.transform = ""; fire(); }
    });
    lever.addEventListener("pointerup", () => { if (startY != null) { arm.style.transform = ""; startY = null; fire(); } });
    lever.addEventListener("keydown", (e) => { if (e.key === "ArrowDown") { e.preventDefault(); fire(); } });
    lever.addEventListener("click", (e) => { if (e.detail === 0) fire(); });  // Enter/Leertaste

    return {
      el: slot,
      setBusy(v) { busy = v; lever.disabled = v; },
      spinTo(index) {
        busy = true; lever.disabled = true;
        slot.classList.remove("won"); slot.classList.add("spinning");
        const seg = segments[index];
        // Ergebnis auf der Gewinnlinie: Gewinn → 3× dasselbe Feld, Niete → drei verschiedene Füllsymbole
        const shuffled = [...FILLERS].sort(() => Math.random() - 0.5);
        const targets = seg.percent > 0 ? [0, 1, 2].map(() => wins.find((w) => w.i === index)) : shuffled.slice(0, 3);
        const done = reels.map((rl, k) => {
          const loops = reduceMotion ? 0 : 8 + k * 4;
          const items = [];
          for (let i = 0; i < loops; i++) items.push(rl.base[(rl.pos + i) % rl.base.length]);
          items.push(targets[k], rl.base[(rl.pos + loops + 3) % rl.base.length]);
          const prev = rl.base[(rl.pos + rl.base.length - 1) % rl.base.length];
          fill(rl, [prev, ...items]);
          rl.pos = (rl.pos + loops + 1) % rl.base.length;
          const dist = (items.length - 2) * CELL;  // Ziel landet in der mittleren Zeile
          const ms = reduceMotion ? 50 : 1900 + k * 650;
          const anim = rl.strip.animate([
            { transform: "translateY(0)" },
            { transform: `translateY(${-dist - 10}px)`, offset: 0.92 },
            { transform: `translateY(${-dist}px)` },
          ], { duration: ms, easing: "cubic-bezier(.25,.1,.25,1)", fill: "forwards" });
          return anim.finished;
        });
        return Promise.all(done).then(() => {
          slot.classList.remove("spinning");
          if (seg.percent > 0) slot.classList.add("won");
        });
      },
    };
  }

  // ------------------------------------------------------------------ Variante „Rubbellos“
  // Los mit drei Feldern unter einer Silberschicht. Erstes Rubbeln ruft opts.onTune() auf (Server lost aus),
  // spinTo(index) legt das Ergebnis unter die Schicht und ist erledigt, sobald gut die Hälfte freigerubbelt ist
  // (oder „Aufdecken“ gedrückt wurde). Gewinn = dreimal dasselbe Feld, Niete = gemischte Symbole.
  const SCRATCH_STYLE = `
.scratch { position: relative; max-width: 420px; margin: 0 auto; padding: 16px 18px 18px; border-radius: 14px; color: #3b1d00;
  background: radial-gradient(circle at 0 50%, transparent 9px, #ffd84d 10px) left / 51% 100% no-repeat,
    radial-gradient(circle at 100% 50%, transparent 9px, #ffd84d 10px) right / 51% 100% no-repeat;
  filter: drop-shadow(0 10px 18px rgba(0,0,0,.28)); user-select: none; -webkit-user-select: none; }
.scratch::before { content: ""; position: absolute; inset: 7px; border: 2px dashed rgba(120,60,0,.35); border-radius: 10px; pointer-events: none; }
.scratch-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; position: relative; }
.scratch-title { font: 900 1.25rem/1 var(--head, system-ui, sans-serif); letter-spacing: .08em; color: #c2410c;
  text-shadow: 2px 2px 0 #fff; }
.scratch-no { font: 600 .7rem ui-monospace, monospace; color: #8a5a00; }
.scratch-area { position: relative; height: 104px; border-radius: 10px; overflow: hidden; background: #fffaf0;
  box-shadow: inset 0 0 0 2px #e0a800; touch-action: none; }
.scratch-symbols { position: absolute; inset: 0; display: grid; grid-template-columns: repeat(3, 1fr); }
.scratch-cell { display: grid; place-items: center; font: 800 1.35rem var(--head, system-ui, sans-serif); color: #b0002a; }
.scratch-cell + .scratch-cell { border-left: 2px dotted #f0c040; }
.scratch-cell.emoji { font-size: 2.1rem; }
.scratch-cell.jackpot::after { content: "★"; color: #d48a00; margin-left: 3px; }
.scratch.won .scratch-cell { animation: scratch-win .45s ease-in-out 4; }
@keyframes scratch-win { 50% { transform: scale(1.18); color: #e4002b; } }
.scratch canvas { position: absolute; inset: 0; width: 100%; height: 100%; cursor: grab; transition: opacity .6s; }
.scratch canvas.gone { opacity: 0; pointer-events: none; }
.scratch-foot { position: relative; display: flex; justify-content: space-between; align-items: center; margin-top: 10px;
  font: 600 .72rem system-ui, sans-serif; color: #8a5a00; }
.scratch-reveal { border: 0; background: #c2410c; color: #fff; border-radius: 999px; padding: 6px 14px;
  font: 700 .75rem system-ui, sans-serif; cursor: pointer; }
.scratch-reveal:disabled { opacity: .5; cursor: default; }
@media (prefers-reduced-motion: reduce) { .scratch.won .scratch-cell { animation: none; } }
`;

  function renderScratch(host, segments, opts = {}) {
    if (!document.getElementById("discount-scratch-style")) {
      const s = document.createElement("style");
      s.id = "discount-scratch-style";
      s.textContent = SCRATCH_STYLE;
      document.head.appendChild(s);
    }
    const div = (cls, text) => { const d = document.createElement("div"); d.className = cls; if (text != null) d.textContent = text; return d; };
    const best = Math.max(...segments.map((s) => s.percent));
    const wins = segments.map((s, i) => ({ ...s, i })).filter((s) => s.percent > 0);
    const ticket = div("scratch");
    const head = div("scratch-head");
    head.append(div("scratch-title", opts.title || "RUBBELLOS"),
      div("scratch-no", "Nr. " + String(Math.floor(Math.random() * 900000) + 100000)));
    const area = div("scratch-area");
    area.setAttribute("role", "img");
    area.setAttribute("aria-label", "Rubbellos mit drei Feldern – Gewinne: " + wins.map((w) => w.label).join(", "));
    const symbols = div("scratch-symbols");
    const cells = [0, 1, 2].map(() => div("scratch-cell emoji", "❔"));
    symbols.append(...cells);
    const canvas = document.createElement("canvas");
    area.append(symbols, canvas);
    const foot = div("scratch-foot");
    const reveal = document.createElement("button");
    reveal.type = "button"; reveal.className = "scratch-reveal"; reveal.textContent = "Aufdecken";
    foot.append(div(null, "Drei Gleiche gewinnen"), reveal);
    ticket.append(head, area, foot);
    host.replaceChildren(ticket);

    // Silberschicht zeichnen (nach dem Einfügen, damit die Größe bekannt ist)
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    function paintCover() {
      const r = area.getBoundingClientRect();
      canvas.width = Math.max(1, r.width * dpr); canvas.height = Math.max(1, r.height * dpr);
      const g = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
      g.addColorStop(0, "#b8b8b8"); g.addColorStop(.45, "#e9e9e9"); g.addColorStop(.55, "#cfcfcf"); g.addColorStop(1, "#a9a9a9");
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = g; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "rgba(255,255,255,.35)";
      for (let x = 0; x < canvas.width; x += 26 * dpr) for (let y = 0; y < canvas.height; y += 26 * dpr) {
        ctx.beginPath(); ctx.arc(x + ((y / (26 * dpr)) % 2) * 13 * dpr, y, 3 * dpr, 0, 7); ctx.fill();
      }
      ctx.fillStyle = "#6b6b6b"; ctx.font = `800 ${15 * dpr}px system-ui, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("✦ HIER RUBBELN ✦", canvas.width / 2, canvas.height / 2);
    }
    requestAnimationFrame(paintCover);

    let started = false, busy = false, result = null, finish = null, wantReveal = false, last = null, checks = 0;
    const start = () => { if (!started && !busy) { started = true; opts.onTune && opts.onTune(); } };
    function scratchAt(x, y) {
      const r = canvas.getBoundingClientRect();
      const px = (x - r.left) * dpr, py = (y - r.top) * dpr;
      ctx.globalCompositeOperation = "destination-out";
      ctx.lineWidth = 34 * dpr; ctx.lineCap = "round";
      ctx.beginPath();
      if (last) { ctx.moveTo(last[0], last[1]); ctx.lineTo(px, py); } else { ctx.arc(px, py, 17 * dpr, 0, 7); ctx.fill(); }
      ctx.stroke();
      last = [px, py];
      if (++checks % 6 === 0) checkDone();
    }
    function cleared() {  // Anteil freigerubbelt (Stichprobe)
      const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let clear = 0, n = 0;
      for (let i = 3; i < d.length; i += 4 * 37) { n++; if (d[i] < 40) clear++; }
      return n ? clear / n : 0;
    }
    function done() {
      canvas.classList.add("gone"); reveal.style.display = "none";
      if (result && result.percent > 0) ticket.classList.add("won");
      const f = finish; finish = null; f && f();
    }
    function checkDone() { if (result && finish && cleared() > 0.5) done(); }
    canvas.addEventListener("pointerdown", (e) => { if (canvas.classList.contains("gone")) return; start();
      canvas.setPointerCapture(e.pointerId); last = null; scratchAt(e.clientX, e.clientY); });
    canvas.addEventListener("pointermove", (e) => { if (e.buttons || e.pointerType === "touch") { if (last || e.buttons) scratchAt(e.clientX, e.clientY); } });
    canvas.addEventListener("pointerup", () => { last = null; checkDone(); });
    reveal.addEventListener("click", () => { wantReveal = true; reveal.disabled = true; start(); if (result && finish) done(); });

    return {
      el: ticket,
      setBusy(v) { busy = v; if (!v) { started = false; reveal.disabled = false; } },
      spinTo(index) {
        const seg = segments[index];
        const fillers = ["🍒", "📻", "🔔", "⭐", "🎵", "🍋"].sort(() => Math.random() - 0.5);
        const labels = seg.percent > 0 ? [seg, seg, seg] : fillers.slice(0, 3);
        cells.forEach((c, k) => {
          const s = labels[k];
          c.className = "scratch-cell" + (typeof s === "string" ? " emoji" : s.percent === best ? " jackpot" : "");
          c.textContent = typeof s === "string" ? s : s.label;
        });
        result = seg;
        return new Promise((resolve) => {
          finish = resolve;
          if (wantReveal || reduceMotion) done(); else checkDone();
        });
      },
    };
  }

  window.DiscountWheel = {
    render(host, segments, opts = {}) {
      if (opts.style === "radio") return renderRadio(host, segments, opts);
      if (opts.style === "slot") return renderSlot(host, segments, opts);
      if (opts.style === "scratch") return renderScratch(host, segments, opts);
      return render(host, segments);
    },
  };
})();
