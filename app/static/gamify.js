/* Spielmodus des Konfigurators (Admin → Design → Anordnung → „Spielmodus“).
 *
 * Hört auf das Ereignis „radiospot:update“ aus configurator.js und vergibt dafür Punkte (XP), Level und
 * Erfolge – mit Punkteleiste über dem Konfigurator, Erfolgs-Meldungen und Konfetti. Rein im Browser,
 * nichts wird gespeichert oder an den Server geschickt.
 */
(function () {
  const ACHIEVEMENTS = [
    { id: "start", icon: "🎯", title: "Mission gestartet", task: "Anlass und Spotlänge wählen", xp: 50,
      test: (s) => s.maxReached >= 1 },
    { id: "text", icon: "✍️", title: "Wortakrobat", task: "Einen Spot-Text mit mindestens 40 Zeichen schreiben", xp: 100,
      test: (s) => s.scriptLength >= 40 },
    { id: "voice", icon: "🎙️", title: "Casting erledigt", task: "Stimme und Musik auswählen", xp: 50,
      test: (s) => s.maxReached >= 3 },
    { id: "demo", icon: "🎧", title: "Erste Hörprobe", task: "Eine Hörprobe erstellen", xp: 150, party: true,
      test: (s) => s.demo },
    { id: "plan", icon: "📡", title: "Sendeplan steht", task: "Sender, Paket und Zeitraum festlegen", xp: 100,
      test: (s) => s.maxReached >= 4 },
    { id: "deal", icon: "🦊", title: "Sparfuchs", task: "Einen Rabatt ergattern (geheimer Erfolg)", xp: 75, secret: true,
      test: (s) => s.discounts > 0 },
    { id: "contact", icon: "📇", title: "Fast on air", task: "Kontaktdaten eintragen", xp: 50,
      test: (s) => s.contact },
    { id: "onair", icon: "🔴", title: "ON AIR!", task: "Anfrage absenden", xp: 200, party: true,
      test: (s) => s.sent },
  ];
  const LEVELS = [
    { xp: 0, name: "Newcomer" }, { xp: 150, name: "Jingle-Profi" },
    { xp: 350, name: "Studio-Star" }, { xp: 600, name: "Radiolegende" },
  ];
  const MAX_XP = ACHIEVEMENTS.reduce((sum, a) => sum + a.xp, 0);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const unlocked = new Set();
  let xp = 0, shownXp = 0, first = true;

  const panel = document.getElementById("radiospot-configurator");
  if (!panel) return;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  // ---------------------------------------------------------------- Punkteleiste
  const hud = el("div", "game-hud");
  const level = el("div", "game-level");
  const levelNo = el("span", "game-level-no"), levelName = el("b", "game-level-name");
  level.append(levelNo, levelName);
  const meter = el("div", "game-meter");
  const fill = el("span", "game-meter-fill");
  meter.append(fill);
  meter.setAttribute("role", "progressbar");
  meter.setAttribute("aria-label", "Erfahrungspunkte");
  meter.setAttribute("aria-valuemin", "0");
  meter.setAttribute("aria-valuemax", String(MAX_XP));
  const xpText = el("span", "game-xp");
  const mission = el("div", "game-mission");
  const badges = el("div", "game-badges");
  const badgeEls = {};
  for (const a of ACHIEVEMENTS) {
    const b = el("span", "game-badge locked", a.secret ? "❔" : a.icon);
    b.title = a.secret ? "Geheimer Erfolg" : `${a.title} – ${a.task} (+${a.xp} XP)`;
    badgeEls[a.id] = b;
    badges.append(b);
  }
  const top = el("div", "game-hud-top");
  top.append(level, xpText);
  hud.append(top, meter, el("div", "game-hud-bottom"));
  hud.lastChild.append(mission, badges);
  panel.prepend(hud);
  const toasts = el("div", "game-toasts");
  toasts.setAttribute("aria-live", "polite");
  document.body.append(toasts);

  // Schritte heißen im Spielmodus „Level“
  const relabel = () => document.querySelectorAll("#dialRow .fstep").forEach((n, i) => { n.textContent = `Level ${i + 1}`; });

  function levelFor(points) {
    let idx = 0;
    LEVELS.forEach((l, i) => { if (points >= l.xp) idx = i; });
    return idx;
  }

  function paint() {
    const idx = levelFor(xp);
    levelNo.textContent = `Lvl ${idx + 1}`;
    levelName.textContent = LEVELS[idx].name;
    fill.style.width = (xp / MAX_XP) * 100 + "%";
    meter.setAttribute("aria-valuenow", String(xp));
    const next = LEVELS[idx + 1];
    countUp();
    xpText.title = next ? `noch ${next.xp - xp} XP bis „${next.name}“` : "Höchstes Level erreicht!";
    const todo = ACHIEVEMENTS.find((a) => !a.secret && !unlocked.has(a.id));
    mission.replaceChildren(el("span", "game-mission-label", todo ? "Nächste Mission:" : "Alle Missionen erfüllt"),
      todo ? ` ${todo.icon} ${todo.task}` : " 🏆");
  }

  function countUp() {  // XP-Zahl zählt hoch statt zu springen
    const target = xp;
    const step = () => {
      shownXp = Math.min(target, shownXp + Math.max(1, Math.ceil((target - shownXp) / 8)));
      xpText.textContent = `${shownXp} / ${MAX_XP} XP`;
      if (shownXp < target) requestAnimationFrame(step);
    };
    if (reduceMotion) { shownXp = target; xpText.textContent = `${shownXp} / ${MAX_XP} XP`; } else step();
  }

  // Meldungen nacheinander zeigen, damit bei mehreren Erfolgen auf einmal kein Stapel entsteht
  const queue = [];
  let showing = false;
  function toast(a, levelUp) {
    queue.push([a, levelUp]);
    if (!showing) nextToast();
  }
  function nextToast() {
    const item = queue.shift();
    if (!item) { showing = false; return; }
    showing = true;
    showToast(...item);
    setTimeout(nextToast, queue.length > 2 ? 700 : 1400);
  }
  function showToast(a, levelUp) {
    const t = el("div", "game-toast" + (levelUp ? " level-up" : ""));
    t.append(el("span", "game-toast-icon", levelUp ? "⬆️" : a.icon),
      el("span", "game-toast-text"));
    t.lastChild.append(el("small", null, levelUp ? "Level aufgestiegen!" : "Erfolg freigeschaltet"),
      el("b", null, levelUp ? levelUp : a.title), levelUp ? "" : el("span", "game-toast-xp", `+${a.xp} XP`));
    toasts.append(t);
    setTimeout(() => t.classList.add("out"), 3200);
    setTimeout(() => t.remove(), 3800);
  }

  function unlock(a, silent) {
    unlocked.add(a.id);
    const before = levelFor(xp);
    xp += a.xp;
    const b = badgeEls[a.id];
    b.textContent = a.icon;
    b.title = `${a.title} – erledigt (+${a.xp} XP)`;
    b.classList.remove("locked");
    if (silent) return;
    b.classList.add("pop");
    hud.classList.remove("bump"); void hud.offsetWidth; hud.classList.add("bump");
    toast(a);
    const after = levelFor(xp);
    if (after > before) toast(null, `Level ${after + 1}: ${LEVELS[after].name}`);
    if (a.party) confetti(a.id === "onair" ? 220 : 90);
  }

  document.addEventListener("radiospot:update", (e) => {
    relabel();
    const s = e.detail;
    for (const a of ACHIEVEMENTS) if (!unlocked.has(a.id) && a.test(s)) unlock(a, first);
    first = false;
    hud.classList.toggle("finished", s.sent);
    paint();
  });

  // ---------------------------------------------------------------- Konfetti (ohne Bibliothek)
  function confetti(count) {
    if (reduceMotion) return;
    const canvas = el("canvas", "game-confetti");
    document.body.append(canvas);
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width = innerWidth * dpr, hgt = canvas.height = innerHeight * dpr;
    const accent = getComputedStyle(panel).getPropertyValue("--accent").trim() || "#e4002b";
    const colors = [accent, "#ffd23f", "#3bceac", "#4d9de0", "#ffffff", "#ff7bac"];
    const parts = Array.from({ length: count }, () => ({
      x: w / 2 + (Math.random() - 0.5) * w * 0.3, y: hgt * 0.35,
      vx: (Math.random() - 0.5) * 22 * dpr, vy: (-Math.random() * 18 - 6) * dpr,
      size: (6 + Math.random() * 7) * dpr, rot: Math.random() * 6, vr: (Math.random() - 0.5) * 0.4,
      color: colors[Math.floor(Math.random() * colors.length)],
    }));
    const start = performance.now();
    (function frame(now) {
      const t = now - start;
      ctx.clearRect(0, 0, w, hgt);
      for (const p of parts) {
        p.vy += 0.55 * dpr; p.vx *= 0.985; p.x += p.vx; p.y += p.vy; p.rot += p.vr;
        ctx.save();
        ctx.globalAlpha = Math.max(0, 1 - t / 2600);
        ctx.translate(p.x, p.y); ctx.rotate(p.rot);
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
        ctx.restore();
      }
      if (t < 2600) requestAnimationFrame(frame); else canvas.remove();
    })(start);
  }

  paint();
})();
