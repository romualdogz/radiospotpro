// Radiospot-Studio – Mehrspur-Editor (Schritt 2): Dateien, Clips verschieben/kürzen, Vorhören, Export.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const TRACKS = ["voice", "music", "sfx", "atmo"];
  const MIN_CLIP = 0.05;          // kürzeste Cliplänge (s)
  const SNAP = 0.05;              // Raster (s), mit Alt aus
  const DEFAULT_GAIN = { atmo: -12 };  // Atmo startet leise
  const ATMO_FADE = 1.0;              // Atmo: weich ein- und ausblenden

  const state = {
    me: null, assets: new Map(), library: new Map(), libCats: {}, libFilter: "", peaks: new Map(), projects: [],
    project: null, selected: null, saveTimer: null, saving: null, dirty: false, exportPoll: null,
  };

  // ------------------------------------------------------------------ Helfer
  async function api(method, url, body, extra = {}) {
    const headers = { "X-CSRF-Token": CSRF, ...(extra.headers || {}) };
    let payload = body;
    if (body !== undefined && !(body instanceof Blob)) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
    if (res.status === 401) { location.href = "/login"; throw new Error("Bitte neu anmelden."); }
    if (!res.ok) {
      let msg = `Fehler ${res.status}`;
      try { const j = await res.json(); if (j.detail) msg = typeof j.detail === "string" ? j.detail : msg; } catch (_) { /* kein JSON */ }
      throw new Error(msg);
    }
    return res.status === 204 ? null : res.json();
  }

  let toastTimer;
  function toast(msg, isError = false) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.toggle("error", isError);
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, isError ? 6000 : 2500);
  }

  const fmtTime = (s) => {
    s = Math.max(0, s);
    const m = Math.floor(s / 60), sec = s - m * 60;
    return `${String(m).padStart(2, "0")}:${sec.toFixed(1).padStart(4, "0")}`;
  };
  const fmtDur = (s) => (s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")} min`);
  const fmtMB = (b) => `${(b / 1048576).toFixed(b < 10485760 ? 1 : 0)} MB`;
  const dbToLin = (db) => Math.pow(10, db / 20);
  const snap = (t, free) => +(free ? t : Math.round(t / SNAP) * SNAP).toFixed(4);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const uid = () => "c" + Math.random().toString(36).slice(2, 10);
  const data = () => state.project.data;
  const clipById = (id) => data().clips.find((c) => c.id === id);
  // Quelle eines Clips: eigene Datei (a12) oder Bibliothek (l7)
  const keyOf = (clip) => (clip.lib_id != null ? `l${clip.lib_id}` : `a${clip.asset_id}`);
  function source(key) {
    const lib = key[0] === "l", id = Number(key.slice(1));
    const item = lib ? state.library.get(id) : state.assets.get(id);
    const base = lib ? `/api/library/${id}` : `/api/assets/${id}`;
    return { name: item?.name, duration: item?.duration, audio: `${base}/audio`, peaks: `${base}/peaks`, lib };
  }
  function storageGet(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function storageSet(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* privat */ } }

  // ------------------------------------------------------------------ Laden
  async function init() {
    state.me = await api("GET", "/api/me");
    updateUsage();
    await Promise.all([loadAssets(), loadLibrary()]);
    state.projects = await api("GET", "/api/projects");
    if (!state.projects.length) {
      const p = await api("POST", "/api/projects", { name: "Mein erster Spot", length: 30 });
      state.projects = [p];
    }
    const remembered = Number(storageGet("studio.project"));
    const pick = state.projects.find((p) => p.id === remembered) || state.projects[0];
    await openProject(pick.id);
  }

  async function loadAssets() {
    const list = await api("GET", "/api/assets");
    state.assets = new Map(list.map((a) => [a.id, a]));
    renderAssets();
  }

  async function loadLibrary() {
    try {
      const lib = await api("GET", "/api/library");
      state.library = new Map(lib.items.map((i) => [i.id, i]));
      state.libCats = lib.categories;
      renderLibrary();
    } catch (e) { toast(e.message, true); }
  }

  let previewAudio = null, previewBtn = null;
  function preview(url, btn) {
    if (previewAudio && previewBtn === btn) { stopPreview(); return; }
    stopPreview();
    previewAudio = new Audio(url);
    previewBtn = btn; btn.textContent = "■"; btn.setAttribute("aria-label", "Vorhören stoppen");
    previewAudio.addEventListener("ended", stopPreview);
    previewAudio.play().catch(() => stopPreview());
  }
  function stopPreview() {
    if (previewAudio) previewAudio.pause();
    if (previewBtn) { previewBtn.textContent = "▶"; previewBtn.setAttribute("aria-label", "Vorhören"); }
    previewAudio = null; previewBtn = null;
  }

  function renderLibrary() {
    const cats = $("lib-cats");
    if (!cats.childElementCount) {
      for (const [k, label] of [["", "Alle"], ...Object.entries(state.libCats)]) {
        const b = document.createElement("button");
        b.className = "chip"; b.textContent = label; b.dataset.cat = k;
        b.setAttribute("aria-pressed", String(k === state.libFilter));
        b.addEventListener("click", () => {
          state.libFilter = k;
          cats.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.cat === k)));
          renderLibrary();
        });
        cats.appendChild(b);
      }
    }
    const q = $("lib-search").value.trim().toLowerCase();
    const items = [...state.library.values()].filter((i) => (!state.libFilter || i.category === state.libFilter)
      && (!q || `${i.name} ${i.tags}`.toLowerCase().includes(q)));
    const ul = $("lib-list");
    if (!items.length) {
      const li = document.createElement("li"); li.className = "empty small muted";
      li.textContent = state.library.size ? "Nichts gefunden." : "Noch keine Bibliothek freigeschaltet.";
      ul.replaceChildren(li);
      return;
    }
    ul.replaceChildren(...items.slice(0, 300).map((i) => {
      const li = document.createElement("li");
      li.className = "asset lib-item"; li.draggable = true;
      li.title = [i.tags && `Stichworte: ${i.tags}`, i.license_note && `Lizenz: ${i.license_note}`, "Auf eine Spur ziehen"].filter(Boolean).join("\n");
      const play = document.createElement("button"); play.className = "mini play"; play.textContent = "▶";
      play.setAttribute("aria-label", "Vorhören");
      play.addEventListener("click", () => preview(`/api/library/${i.id}/audio`, play));
      const name = document.createElement("span"); name.className = "asset-name"; name.textContent = i.name;
      const meta = document.createElement("span"); meta.className = "small muted"; meta.textContent = `${state.libCats[i.category] || ""} · ${fmtDur(i.duration)}`;
      li.append(play, name, meta);
      li.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("application/x-studio-lib", String(i.id));
        e.dataTransfer.effectAllowed = "copy";
      });
      return li;
    }));
  }

  async function refreshMe() {
    try { state.me = await api("GET", "/api/me"); updateUsage(); } catch (_) { /* egal */ }
  }

  function updateUsage() {
    const used = state.me.used_bytes, quota = state.me.quota_mb * 1048576;
    $("usage-fill").style.width = `${Math.min(100, (used / Math.max(quota, 1)) * 100)}%`;
    $("usage-text").textContent = `${fmtMB(used)} von ${state.me.quota_mb} MB belegt`;
  }

  async function peaksFor(key) {
    if (!state.peaks.has(key)) {
      state.peaks.set(key, fetch(source(key).peaks, { credentials: "same-origin" })
        .then((r) => (r.ok ? r.json() : [])).then((a) => Uint8Array.from(a)).catch(() => new Uint8Array()));
    }
    return state.peaks.get(key);
  }

  // ------------------------------------------------------------------ Projekte
  function renderProjectSelect() {
    const sel = $("project-select");
    sel.replaceChildren(...state.projects.map((p) => {
      const o = document.createElement("option");
      o.value = p.id; o.textContent = p.name;
      o.selected = state.project && p.id === state.project.id;
      return o;
    }));
  }

  async function openProject(id) {
    await flushSave();
    stopPlayback(true);
    state.project = await api("GET", `/api/projects/${id}`);
    state.selected = null;
    storageSet("studio.project", String(id));
    $("project-name").value = state.project.name;
    $("spot-length").value = String(data().length);
    if ($("spot-length").value !== String(data().length)) {  // Länge nicht in der Liste → ergänzen
      const o = document.createElement("option");
      o.value = data().length; o.textContent = `${data().length} s`;
      $("spot-length").appendChild(o); $("spot-length").value = String(data().length);
    }
    renderProjectSelect();
    $("ai-script").value = data().script || "";
    $("duck-amount").value = String(Math.round(data().ducking?.amount_db ?? 10));
    updateScriptInfo();
    renderTracks();
    renderAll();
    setSaveState("Gespeichert");
    loadExports();
  }

  function setSaveState(text, error = false) {
    const el = $("save-state");
    el.textContent = text;
    el.classList.toggle("error-text", error);
  }

  function changed({ replay = true } = {}) {
    state.dirty = true;
    setSaveState("Ungespeichert …");
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(saveNow, 700);
    if (replay && player.playing) player.restart();
  }

  async function saveNow() {
    clearTimeout(state.saveTimer);
    if (!state.dirty || !state.project) return state.saving;
    state.dirty = false;
    const p = state.project;
    setSaveState("Speichert …");
    state.saving = api("PUT", `/api/projects/${p.id}`, { name: p.name, data: p.data })
      .then((res) => {
        const entry = state.projects.find((x) => x.id === p.id);
        if (entry) entry.name = res.name;
        renderProjectSelect();
        if (!state.dirty) setSaveState("Gespeichert");
      })
      .catch((e) => { state.dirty = true; setSaveState("Nicht gespeichert", true); toast(e.message, true); throw e; })
      .finally(() => { state.saving = null; });
    return state.saving;
  }

  async function flushSave() {
    if (state.dirty) await saveNow();
    else if (state.saving) await state.saving;
  }

  // ------------------------------------------------------------------ Dateien (Bibliothek)
  function renderAssets() {
    const ul = $("asset-list");
    if (!state.assets.size) {
      const li = document.createElement("li");
      li.className = "empty small muted";
      li.textContent = "Noch keine Dateien.";
      ul.replaceChildren(li);
      return;
    }
    ul.replaceChildren(...[...state.assets.values()].map((a) => {
      const li = document.createElement("li");
      li.className = "asset";
      li.draggable = true;
      li.dataset.asset = a.id;
      li.title = "Auf eine Spur ziehen";
      const name = document.createElement("span"); name.className = "asset-name"; name.textContent = a.name;
      if (a.origin === "ai") { const b = document.createElement("span"); b.className = "ai-badge"; b.textContent = "KI"; name.prepend(b); }
      const meta = document.createElement("span"); meta.className = "small muted"; meta.textContent = fmtDur(a.duration);
      const del = document.createElement("button"); del.className = "mini"; del.textContent = "×";
      del.title = "Datei löschen"; del.setAttribute("aria-label", `${a.name} löschen`);
      del.addEventListener("click", () => deleteAsset(a));
      li.append(name, meta, del);
      li.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("application/x-studio-asset", String(a.id));
        e.dataTransfer.effectAllowed = "copy";
      });
      return li;
    }));
  }

  async function deleteAsset(a) {
    if (!confirm(`„${a.name}“ löschen?`)) return;
    try {
      await api("DELETE", `/api/assets/${a.id}`);
      state.assets.delete(a.id);
      renderAssets(); refreshMe();
    } catch (e) { toast(e.message, true); }
  }

  async function upload(files) {
    const done = [];
    for (const file of files) {
      toast(`Lade „${file.name}“ hoch …`);
      try {
        const a = await api("POST", "/api/assets", file, { headers: { "X-Filename": encodeURIComponent(file.name) } });
        state.assets = new Map([[a.id, a], ...state.assets]);
        done.push(a);
      } catch (e) { toast(`${file.name}: ${e.message}`, true); }
    }
    renderAssets();
    refreshMe();
    if (done.length) toast(done.length === 1 ? `„${done[0].name}“ hochgeladen` : `${done.length} Dateien hochgeladen`);
    return done;
  }

  // ------------------------------------------------------------------ Zeitleiste
  const lanes = () => [...document.querySelectorAll(".lane[data-track]")];
  const laneOf = (track) => document.querySelector(`.lane[data-track="${track}"]`);
  const pxPerSec = () => $("ruler").clientWidth / data().length;

  function timeAt(clientX, el) {
    const r = el.getBoundingClientRect();
    return clamp(((clientX - r.left) / r.width) * data().length, 0, data().length);
  }

  function renderRuler() {
    const ruler = $("ruler"), seconds = data().length;
    ruler.querySelectorAll(".tick").forEach((t) => t.remove());
    const step = seconds <= 20 ? 1 : seconds <= 45 ? 5 : seconds <= 90 ? 10 : 15;
    const minor = seconds <= 60 ? 1 : 5;
    for (let s = 0; s <= seconds; s += minor) {
      const tick = document.createElement("span");
      tick.className = s % step === 0 ? "tick major" : "tick";
      tick.style.left = `${(s / seconds) * 100}%`;
      if (s % step === 0 && s < seconds) tick.dataset.label = `${s}s`;
      ruler.appendChild(tick);
    }
  }

  function renderTracks() {
    for (const head of document.querySelectorAll(".track-head[data-track]")) {
      const t = data().tracks[head.dataset.track];
      head.querySelector('[data-act="mute"]').setAttribute("aria-pressed", String(t.mute));
      head.querySelector('[data-act="solo"]').setAttribute("aria-pressed", String(t.solo));
      head.querySelector('[data-act="duck"]')?.setAttribute("aria-pressed", String(!!t.duck));
      head.querySelector('[data-act="gain"]').value = t.gain_db;
      head.querySelector("[data-db]").textContent = `${t.gain_db > 0 ? "+" : ""}${t.gain_db} dB`;
    }
  }

  function renderAll() {
    renderRuler();
    for (const lane of lanes()) lane.querySelectorAll(".clip").forEach((c) => c.remove());
    for (const clip of data().clips) laneOf(clip.track).appendChild(buildClip(clip));
    for (const lane of lanes()) lane.classList.toggle("has-clips", !!lane.querySelector(".clip"));
    renderInspector();
    const ruler = $("ruler"), last = lanes().at(-1);
    $("playhead").style.height = `${last.offsetTop + last.offsetHeight - ruler.offsetTop}px`;
    renderEnvelopes();
    drawPlayhead(player.position());
  }

  function buildClip(clip) {
    const el = document.createElement("div");
    el.className = "clip";
    el.dataset.clip = clip.id;
    el.tabIndex = 0;
    const canvas = document.createElement("canvas");
    const label = document.createElement("span");
    label.className = "clip-label";
    label.textContent = (clip.loop ? "⟳ " : "") + (source(keyOf(clip)).name || "Datei fehlt");
    const hl = document.createElement("span"); hl.className = "handle left"; hl.dataset.mode = "left";
    const hr = document.createElement("span"); hr.className = "handle right"; hr.dataset.mode = "right";
    const fi = document.createElement("span"); fi.className = "fade-handle in"; fi.dataset.mode = "fadein"; fi.title = "Einblenden ziehen";
    const fo = document.createElement("span"); fo.className = "fade-handle out"; fo.dataset.mode = "fadeout"; fo.title = "Ausblenden ziehen";
    el.append(canvas, label, hl, hr, fi, fo);
    placeClip(el, clip);
    return el;
  }

  function placeClip(el, clip) {
    const L = data().length;
    el.style.left = `${(clip.start / L) * 100}%`;
    el.style.width = `${(clip.duration / L) * 100}%`;
    el.classList.toggle("selected", state.selected === clip.id);
    el.querySelector(".fade-handle.in").style.left = `${(clip.fade_in / clip.duration) * 100}%`;
    el.querySelector(".fade-handle.out").style.right = `${(clip.fade_out / clip.duration) * 100}%`;
    el.querySelector(".clip-label").textContent = (clip.loop ? "⟳ " : "") + (source(keyOf(clip)).name || "Datei fehlt");
    requestAnimationFrame(() => drawWave(el, clip));
  }

  async function drawWave(el, clip) {
    const canvas = el.querySelector("canvas");
    const peaks = await peaksFor(keyOf(clip));
    const srcDur = source(keyOf(clip)).duration || peaks.length / 50;
    const dpr = window.devicePixelRatio || 1;
    const W = Math.max(1, Math.round(el.clientWidth * dpr)), H = Math.max(1, Math.round(el.clientHeight * dpr));
    canvas.width = W; canvas.height = H;
    const g = canvas.getContext("2d");
    g.clearRect(0, 0, W, H);
    const color = getComputedStyle(el).getPropertyValue("--c").trim() || "#888";
    const gain = Math.min(1.6, dbToLin(clip.gain_db));
    g.fillStyle = color;
    const mid = H / 2, perPx = clip.duration / W;
    for (let x = 0; x < W; x++) {
      let t0 = clip.offset + x * perPx;
      if (clip.loop && srcDur > 0) t0 %= srcDur;
      const t1 = t0 + perPx;
      let i = Math.floor(t0 * 50), end = Math.max(i + 1, Math.ceil(t1 * 50)), p = 0;
      for (; i < end && i < peaks.length; i++) p = Math.max(p, peaks[i]);
      const local = x * perPx;
      const env = gain * fadeGain(clip, local);
      const h = Math.min(1, (p / 255) * env) * (H / 2 - 2 * dpr);
      g.fillRect(x, mid - h, 1, Math.max(1, h * 2));
    }
    // Fades als Kurve
    g.strokeStyle = color; g.lineWidth = 1.5 * dpr; g.globalAlpha = 0.9;
    g.beginPath();
    for (let x = 0; x <= W; x += 2) g[x ? "lineTo" : "moveTo"](x, 1 + (H - 2) * (1 - fadeGain(clip, x * perPx)));
    g.stroke();
    // Nahtstellen eines Loops
    if (clip.loop && srcDur > 0) {
      g.globalAlpha = 0.5; g.setLineDash([4 * dpr, 4 * dpr]);
      for (let t = srcDur - (clip.offset % srcDur); t < clip.duration; t += srcDur) {
        const x = (t / clip.duration) * W;
        g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke();
      }
      g.setLineDash([]);
    }
  }

  // Fade-Verlauf (0…1) an Stelle t im Clip – identisch zum Rendern auf dem Server
  const curveFn = (x, curve) => (curve === "linear" ? x : 0.5 - 0.5 * Math.cos(Math.PI * x));
  function fadeGain(clip, t) {
    let v = 1;
    if (clip.fade_in > 0) v *= curveFn(clamp(t / clip.fade_in, 0, 1), clip.fade_curve);
    if (clip.fade_out > 0) v *= curveFn(clamp((clip.duration - t) / clip.fade_out, 0, 1), clip.fade_curve);
    return v;
  }

  function select(id) {
    state.selected = id;
    document.querySelectorAll(".clip").forEach((c) => c.classList.toggle("selected", c.dataset.clip === id));
    renderInspector();
  }

  function renderInspector() {
    const clip = state.selected && clipById(state.selected);
    $("inspector").hidden = !clip;
    if (!clip) return;
    $("insp-name").textContent = source(keyOf(clip)).name || "Clip";
    $("insp-curve").value = clip.fade_curve || "linear";
    $("insp-loop").checked = !!clip.loop;
    $("insp-gain").value = clip.gain_db;
    $("insp-gain-val").textContent = `${clip.gain_db > 0 ? "+" : ""}${clip.gain_db} dB`;
    $("insp-fade-in").value = clip.fade_in;
    $("insp-fade-out").value = clip.fade_out;
    $("insp-pos").textContent = `${fmtTime(clip.start)} – ${fmtTime(clip.start + clip.duration)}`;
  }

  // item: eigene Datei oder Bibliotheksdatei; lib = true für Bibliothek
  function addClip(item, track, start, lib = false) {
    start = Math.max(0, start);
    const atmo = track === "atmo";
    // Atmo: als Loop bis zum Spotende, weich ein- und ausgeblendet
    const duration = atmo ? Math.max(item.duration, data().length - start) : item.duration;
    const fade = atmo ? Math.min(ATMO_FADE, duration / 2) : 0;
    const clip = {
      id: uid(), asset_id: lib ? null : item.id, lib_id: lib ? item.id : null, track, start, offset: 0,
      duration: +duration.toFixed(4), gain_db: DEFAULT_GAIN[track] || 0, fade_in: fade, fade_out: fade,
      fade_curve: "smooth", loop: atmo && duration > item.duration,
    };
    data().clips.push(clip);
    laneOf(track).appendChild(buildClip(clip));
    laneOf(track).classList.add("has-clips");
    select(clip.id);
    changed();
  }

  function removeClip(id) {
    const d = data();
    d.clips = d.clips.filter((c) => c.id !== id);
    document.querySelector(`.clip[data-clip="${id}"]`)?.remove();
    for (const lane of lanes()) lane.classList.toggle("has-clips", !!lane.querySelector(".clip"));
    if (state.selected === id) select(null);
    changed();
  }

  function fitFades(clip) {
    const sum = clip.fade_in + clip.fade_out;
    if (sum > clip.duration) {
      const k = clip.duration / sum;
      clip.fade_in = Math.floor(clip.fade_in * k * 100) / 100;
      clip.fade_out = Math.floor(clip.fade_out * k * 100) / 100;
    }
  }

  // Clips verschieben und kürzen (Pointer-Events, auch Touch)
  let drag = null;
  function onPointerDown(e) {
    const el = e.target.closest(".clip");
    if (!el || e.button !== 0) return;
    e.preventDefault();
    const clip = clipById(el.dataset.clip);
    select(clip.id);
    el.focus({ preventScroll: true });
    drag = { el, clip, mode: e.target.dataset.mode || "move", x0: e.clientX, pps: pxPerSec(),
             s0: clip.start, o0: clip.offset, d0: clip.duration, track0: clip.track, moved: false,
             fi0: clip.fade_in, fo0: clip.fade_out };
    el.classList.add("dragging");
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp, { once: true });
    window.addEventListener("pointercancel", onPointerUp, { once: true });
  }

  function onPointerMove(e) {
    if (!drag) return;
    const { clip, el } = drag;
    const dx = (e.clientX - drag.x0) / drag.pps;
    if (!drag.moved && Math.abs(e.clientX - drag.x0) < 3) return;
    drag.moved = true;
    const free = e.altKey;
    const assetDur = source(keyOf(clip)).duration ?? drag.o0 + drag.d0;
    const maxLen = state.me?.limits?.max_length_s || 120;
    if (drag.mode === "move") {
      clip.start = clamp(snap(drag.s0 + dx, free), 0, data().length - MIN_CLIP);
      const lane = document.elementFromPoint(e.clientX, e.clientY)?.closest(".lane[data-track]");
      if (lane && lane.dataset.track !== clip.track) {
        clip.track = lane.dataset.track;
        lane.appendChild(el);
      }
    } else if (drag.mode === "fadein") {
      clip.fade_in = clamp(snap(drag.fi0 + dx, free), 0, clip.duration - clip.fade_out);
    } else if (drag.mode === "fadeout") {
      clip.fade_out = clamp(snap(drag.fo0 - dx, free), 0, clip.duration - clip.fade_in);
    } else if (drag.mode === "left") {
      const end = drag.s0 + drag.d0;
      // mit Loop darf der Anfang nicht vor den Dateianfang, sonst wie ohne
      const start = clamp(snap(drag.s0 + dx, free), Math.max(0, drag.s0 - drag.o0), end - MIN_CLIP);
      clip.start = start;
      clip.offset = drag.o0 + (start - drag.s0);
      clip.duration = end - start;
    } else {
      const longest = clip.loop ? maxLen : assetDur - drag.o0;
      const end = clamp(snap(drag.s0 + drag.d0 + dx, free), drag.s0 + MIN_CLIP, drag.s0 + longest);
      clip.duration = end - drag.s0;
    }
    clip.start = +clip.start.toFixed(4); clip.offset = +clip.offset.toFixed(4); clip.duration = +clip.duration.toFixed(4);
    clip.fade_in = +clip.fade_in.toFixed(4); clip.fade_out = +clip.fade_out.toFixed(4);
    fitFades(clip);
    placeClip(el, clip);
    $("insp-pos").textContent = `${fmtTime(clip.start)} – ${fmtTime(clip.start + clip.duration)}`;
  }

  function onPointerUp() {
    window.removeEventListener("pointermove", onPointerMove);
    if (!drag) return;
    drag.el.classList.remove("dragging");
    for (const lane of lanes()) lane.classList.toggle("has-clips", !!lane.querySelector(".clip"));
    if (drag.moved) { renderInspector(); changed(); }
    drag = null;
  }

  // ------------------------------------------------------------------ Wiedergabe (Web Audio)
  const player = {
    ctx: null, playing: false, t0: 0, from: 0, paused: 0, nodes: [], trackGains: {}, buffers: new Map(), raf: 0,

    position() { return this.playing ? this.from + (this.ctx.currentTime - this.t0) : this.paused; },

    buffer(id) {
      if (!this.buffers.has(id)) {
        this.buffers.set(id, fetch(source(id).audio, { credentials: "same-origin" })
          .then((r) => { if (!r.ok) throw new Error("Datei nicht ladbar"); return r.arrayBuffer(); })
          .then((b) => this.ctx.decodeAudioData(b))
          .catch((e) => { this.buffers.delete(id); throw e; }));
      }
      return this.buffers.get(id);
    },

    audible(track) {
      const tracks = data().tracks, anySolo = TRACKS.some((k) => tracks[k].solo), t = tracks[track];
      return !(t.mute || (anySolo && !t.solo));
    },

    async play() {
      if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      await this.ctx.resume();
      const from = this.paused >= data().length ? 0 : this.paused;
      $("play").disabled = true;
      try {
        await Promise.all([...new Set(data().clips.map(keyOf))].map((k) => this.buffer(k)));
      } catch (e) { toast(e.message, true); $("play").disabled = false; return; }
      $("play").disabled = false;
      this.start(from);
    },

    async start(from) {
      const token = (this.token = (this.token || 0) + 1);
      let curves;
      try { curves = await trackCurves(); } catch (e) { toast(e.message, true); return; }
      if (token !== this.token) return;  // inzwischen neu gestartet
      this.stopNodes();
      const ctx = this.ctx, now = ctx.currentTime + 0.05, L = data().length;
      for (const k of TRACKS) {
        const g = ctx.createGain();
        if (!this.audible(k)) g.gain.value = 0;
        else {
          // Spurlautstärke × Hüllkurve × Ducking ab der Startposition
          const i0 = Math.floor(from * FPS), src = curves[k];
          const vals = new Float32Array(Math.max(2, src.length - i0));
          for (let i = 0; i < vals.length; i++) vals[i] = dbToLin(src[Math.min(i0 + i, src.length - 1)]);
          g.gain.setValueAtTime(vals[0], now);
          if (L - from > 0.01) g.gain.setValueCurveAtTime(vals, now + 0.0001, (vals.length - 1) / FPS);
        }
        g.connect(ctx.destination);
        this.trackGains[k] = g;
      }
      for (const clip of data().clips) {
        const local = Math.max(0, from - clip.start);
        const dur = clip.duration - local;
        if (dur <= 0 || clip.start >= data().length) continue;
        let buf;
        try { buf = await this.buffer(keyOf(clip)); } catch (_) { continue; }
        const src = ctx.createBufferSource();
        src.buffer = buf;
        let offset = clip.offset + local;
        if (clip.loop) { src.loop = true; src.loopStart = 0; src.loopEnd = buf.duration; offset %= buf.duration; }
        const g = ctx.createGain();
        const when = now + Math.max(0, clip.start - from);
        scheduleEnvelope(g.gain, clip, local, when, dbToLin(clip.gain_db));
        src.connect(g).connect(this.trackGains[clip.track]);
        src.start(when, offset, dur);
        this.nodes.push(src, g);
      }
      this.t0 = now; this.from = from; this.playing = true;
      $("play").textContent = "❚❚"; $("play").setAttribute("aria-label", "Pause");
      cancelAnimationFrame(this.raf);
      const tick = () => {
        if (!this.playing) return;
        const pos = this.position();
        if (pos >= data().length) { this.stop(false); this.paused = 0; drawPlayhead(0); return; }
        drawPlayhead(Math.max(from, pos));
        this.raf = requestAnimationFrame(tick);
      };
      this.raf = requestAnimationFrame(tick);
    },

    restart() { if (this.playing) this.start(this.position()); },

    stopNodes() {
      for (const n of this.nodes) { try { n.stop?.(); } catch (_) { /* schon gestoppt */ } n.disconnect(); }
      for (const g of Object.values(this.trackGains)) g.disconnect();
      this.nodes = []; this.trackGains = {};
    },

    stop(keepPosition = true) {
      if (this.playing) this.paused = keepPosition ? Math.min(this.position(), data().length) : 0;
      this.playing = false;
      cancelAnimationFrame(this.raf);
      this.stopNodes();
      $("play").textContent = "▶"; $("play").setAttribute("aria-label", "Abspielen");
    },
  };

  // Lautstärkeverlauf eines Clips planen: Fades als Kurve (wie beim Rendern), dazwischen konstant
  function scheduleEnvelope(param, clip, local, when, base) {
    const d = clip.duration, fi = clip.fade_in, fo = clip.fade_out;
    const env = (t) => base * fadeGain(clip, t);
    const curve = (t0, t1) => {
      const n = Math.max(2, Math.ceil((t1 - t0) * 200));
      const arr = new Float32Array(n);
      for (let i = 0; i < n; i++) arr[i] = env(t0 + ((t1 - t0) * i) / (n - 1));
      return arr;
    };
    // Kurven-Ereignisse dürfen sich mit keinem anderen Ereignis überschneiden
    let t = local, busyUntil = -1;
    const fadeOutStart = fo > 0 ? Math.max(local, d - fo) : d;
    if (fi > 0 && t < fi) {
      const end = Math.min(fi, fadeOutStart);
      param.setValueCurveAtTime(curve(t, end), when, end - t);
      busyUntil = when + (end - t);
      t = end;
    } else if (!(fo > 0 && fadeOutStart <= local)) {
      param.setValueAtTime(env(t), when);
    }
    if (fo > 0 && fadeOutStart < d) {
      const start = Math.max(when + (fadeOutStart - local), busyUntil + 0.0005);
      param.setValueCurveAtTime(curve(fadeOutStart, d), start, Math.max(0.001, when + (d - local) - start));
    }
  }

  function stopPlayback(reset) {
    if (!state.project) return;
    player.stop(!reset);
    if (reset) player.paused = 0;
    drawPlayhead(player.paused);
  }

  function drawPlayhead(pos) {
    if (!state.project) return;
    $("playhead").style.left = `${(clamp(pos, 0, data().length) / data().length) * 100}%`;
    $("playhead-time").textContent = fmtTime(pos);
  }

  function seek(t) {
    if (player.playing) player.start(t);
    else { player.paused = t; drawPlayhead(t); }
  }

  // ------------------------------------------------------------------ Export
  async function loadExports() {
    if (!state.project) return;
    const list = await api("GET", `/api/projects/${state.project.id}/exports`).catch(() => []);
    renderExports(list);
    clearTimeout(state.exportPoll);
    if (list.some((e) => e.status === "queued" || e.status === "running")) {
      state.exportPoll = setTimeout(loadExports, 1500);
    } else if (state.exportWasPending) {
      state.exportWasPending = false;
      refreshMe();
    }
    if (list.some((e) => e.status === "queued" || e.status === "running")) state.exportWasPending = true;
  }

  const STATUS = { queued: "wartet", running: "wird gerendert …", done: "fertig", failed: "fehlgeschlagen", expired: "gelöscht" };

  function renderExports(list) {
    const ul = $("export-list");
    if (!list.length) {
      const li = document.createElement("li"); li.className = "small muted"; li.textContent = "Noch keine Exporte für dieses Projekt.";
      ul.replaceChildren(li);
      return;
    }
    ul.replaceChildren(...list.map((e) => {
      const li = document.createElement("li");
      const when = new Date(e.created_at).toLocaleString("de-AT", { dateStyle: "short", timeStyle: "short" });
      const title = document.createElement("span"); title.textContent = `${e.name} · ${when}`;
      const badge = document.createElement("span"); badge.className = `badge ${e.status}`; badge.textContent = STATUS[e.status] || e.status;
      const info = document.createElement("span"); info.className = "small muted";
      if (e.status === "done") {
        const how = e.loudness == null ? "Pegel gelassen" : `${e.mode === "normalize" ? "normalisiert" : "gemastert"} auf ${e.loudness} LUFS`;
        info.textContent = `${how} · gemessen ${e.measured_lufs ?? "–"} LUFS, ${e.measured_peak ?? "–"} dBTP · ${fmtMB(e.size_bytes)}`;
      } else if (e.status === "failed") { info.textContent = e.error; info.className = "small error-text"; }
      li.append(title, badge, info);
      if (e.status === "done") {
        const a = document.createElement("a"); a.href = `/api/exports/${e.id}/download`; a.textContent = "Herunterladen"; a.className = "button-like";
        li.append(a);
      }
      if (e.status !== "queued" && e.status !== "running" && e.status !== "expired") {
        const del = document.createElement("button"); del.className = "link"; del.textContent = "Löschen";
        del.addEventListener("click", async () => {
          try { await api("DELETE", `/api/exports/${e.id}`); loadExports(); refreshMe(); } catch (err) { toast(err.message, true); }
        });
        li.append(del);
      }
      return li;
    }));
  }

  async function startExport() {
    const btn = $("export");
    btn.disabled = true;
    try {
      await flushSave();
      const [mode, target] = ($("export-loudness").value || "master:").split(":");
      await api("POST", `/api/projects/${state.project.id}/exports`, { mode, loudness: target ? Number(target) : null });
      toast("Export gestartet");
      loadExports();
    } catch (e) { toast(e.message, true); } finally { btn.disabled = false; }
  }

  // ------------------------------------------------------------------ Ereignisse
  function bind() {
    $("timeline").addEventListener("pointerdown", onPointerDown);
    $("timeline").addEventListener("click", (e) => {
      if (!e.target.closest(".clip") && e.target.closest(".lane")) select(null);
    });
    $("ruler").addEventListener("click", (e) => seek(timeAt(e.clientX, $("ruler"))));

    for (const lane of lanes()) {
      lane.addEventListener("dragover", (e) => {
        if ([...e.dataTransfer.types].some((t) => t === "application/x-studio-asset" || t === "application/x-studio-lib" || t === "Files")) {
          e.preventDefault(); lane.classList.add("drop");
        }
      });
      lane.addEventListener("dragleave", () => lane.classList.remove("drop"));
      lane.addEventListener("drop", async (e) => {
        e.preventDefault(); lane.classList.remove("drop");
        let start = snap(timeAt(e.clientX, lane), e.altKey);
        const id = Number(e.dataTransfer.getData("application/x-studio-asset"));
        if (id && state.assets.has(id)) { addClip(state.assets.get(id), lane.dataset.track, start); return; }
        const libId = Number(e.dataTransfer.getData("application/x-studio-lib"));
        if (libId && state.library.has(libId)) { stopPreview(); addClip(state.library.get(libId), lane.dataset.track, start, true); return; }
        if (e.dataTransfer.files.length) {
          for (const a of await upload([...e.dataTransfer.files])) {
            addClip(a, lane.dataset.track, start);
            start = Math.min(data().length - MIN_CLIP, start + a.duration);
          }
        }
      });
    }

    const lib = $("library");
    lib.addEventListener("dragover", (e) => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); lib.classList.add("drop"); } });
    lib.addEventListener("dragleave", () => lib.classList.remove("drop"));
    lib.addEventListener("drop", (e) => { e.preventDefault(); lib.classList.remove("drop"); if (e.dataTransfer.files.length) upload([...e.dataTransfer.files]); });
    $("upload-input").addEventListener("change", (e) => { upload([...e.target.files]); e.target.value = ""; });

    for (const head of document.querySelectorAll(".track-head[data-track]")) {
      const k = head.dataset.track;
      head.addEventListener("click", (e) => {
        const act = e.target.dataset.act;
        if (act !== "mute" && act !== "solo" && act !== "duck") return;
        data().tracks[k][act] = !data().tracks[k][act];
        renderTracks(); changed();
      });
      head.querySelector('[data-act="gain"]').addEventListener("input", (e) => {
        data().tracks[k].gain_db = Number(e.target.value);
        renderTracks(); renderEnvelopes(); changed();
      });
    }

    $("insp-gain").addEventListener("input", (e) => {
      const clip = clipById(state.selected); if (!clip) return;
      clip.gain_db = Number(e.target.value);
      renderInspector(); placeClip(document.querySelector(`.clip[data-clip="${clip.id}"]`), clip); changed();
    });
    for (const [id, key] of [["insp-fade-in", "fade_in"], ["insp-fade-out", "fade_out"]]) {
      $(id).addEventListener("change", (e) => {
        const clip = clipById(state.selected); if (!clip) return;
        const other = key === "fade_in" ? clip.fade_out : clip.fade_in;
        clip[key] = clamp(Math.round((Number(e.target.value) || 0) * 100) / 100, 0, Math.max(0, clip.duration - other));
        renderInspector(); placeClip(document.querySelector(`.clip[data-clip="${clip.id}"]`), clip); changed();
      });
    }
    $("insp-delete").addEventListener("click", () => state.selected && removeClip(state.selected));
    $("insp-curve").addEventListener("change", (e) => {
      const clip = clipById(state.selected); if (!clip) return;
      clip.fade_curve = e.target.value;
      placeClip(document.querySelector(`.clip[data-clip="${clip.id}"]`), clip); changed();
    });
    $("insp-loop").addEventListener("change", (e) => {
      const clip = clipById(state.selected); if (!clip) return;
      clip.loop = e.target.checked;
      const srcDur = source(keyOf(clip)).duration;
      if (!clip.loop && srcDur && clip.offset + clip.duration > srcDur) {  // ohne Loop auf Dateilänge kürzen
        clip.duration = +(srcDur - clip.offset).toFixed(4);
        fitFades(clip);
      }
      renderInspector(); placeClip(document.querySelector(`.clip[data-clip="${clip.id}"]`), clip); changed();
    });

    for (const [tab, panel, other, otherPanel] of [["tab-files", "panel-files", "tab-lib", "panel-lib"], ["tab-lib", "panel-lib", "tab-files", "panel-files"]]) {
      $(tab).addEventListener("click", () => {
        $(tab).setAttribute("aria-selected", "true"); $(other).setAttribute("aria-selected", "false");
        $(panel).hidden = false; $(otherPanel).hidden = true;
        if (tab === "tab-files") stopPreview();
      });
    }
    $("lib-search").addEventListener("input", renderLibrary);

    $("play").addEventListener("click", () => (player.playing ? player.stop() : player.play()));
    $("stop").addEventListener("click", () => stopPlayback(true));
    $("export").addEventListener("click", startExport);

    $("spot-length").addEventListener("change", (e) => {
      data().length = Number(e.target.value);
      if (player.paused > data().length) player.paused = 0;
      renderAll(); changed();
    });
    $("project-name").addEventListener("input", (e) => {
      const v = e.target.value.trim();
      if (v) { state.project.name = v; changed({ replay: false }); }
    });
    $("project-select").addEventListener("change", (e) => openProject(Number(e.target.value)).catch((err) => toast(err.message, true)));
    $("project-new").addEventListener("click", async () => {
      const name = prompt("Name des neuen Projekts:", "Neuer Spot");
      if (!name || !name.trim()) return;
      try {
        const p = await api("POST", "/api/projects", { name: name.trim(), length: data().length });
        state.projects.unshift(p);
        await openProject(p.id);
      } catch (e) { toast(e.message, true); }
    });
    $("project-delete").addEventListener("click", async () => {
      if (!confirm(`Projekt „${state.project.name}“ wirklich löschen? Die Dateien bleiben erhalten.`)) return;
      try {
        clearTimeout(state.saveTimer); state.dirty = false;
        await api("DELETE", `/api/projects/${state.project.id}`);
        state.projects = state.projects.filter((p) => p.id !== state.project.id);
        state.project = null;
        if (!state.projects.length) state.projects = [await api("POST", "/api/projects", { name: "Neuer Spot", length: 30 })];
        await openProject(state.projects[0].id);
      } catch (e) { toast(e.message, true); }
    });

    document.addEventListener("keydown", (e) => {
      if (e.target.closest("input, select, textarea")) return;
      if (e.code === "Space" && !e.target.closest("button")) {
        e.preventDefault(); player.playing ? player.stop() : player.play();
      } else if ((e.key === "Delete" || e.key === "Backspace") && state.selected) {
        e.preventDefault(); removeClip(state.selected);
      }
    });

    let resizeTimer;
    window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderAll, 150); });
    window.addEventListener("beforeunload", (e) => { if (state.dirty) { saveNow(); e.preventDefault(); } });
  }



  // ------------------------------------------------------------------ Hüllkurven & Ducking (wie studio/automation.py)
  const FPS = 100, DUCK_THRESHOLD_DB = -45, DUCK_HOLD_S = 0.25, DUCK_LOOKAHEAD_S = 0.05, DUCK_ATTACK_S = 0.1;
  const ENV_TOP = 12, ENV_BOTTOM = -36;   // Darstellungsbereich der Hüllkurve (dB)
  let envMode = false, envTrack = null, lastEnvDown = null;

  function envDbAt(points, t) {
    if (!points || !points.length) return 0;
    if (t <= points[0].t) return points[0].db;
    for (let i = 1; i < points.length; i++) {
      if (t <= points[i].t) {
        const a = points[i - 1], b = points[i];
        return b.t === a.t ? b.db : a.db + ((b.db - a.db) * (t - a.t)) / (b.t - a.t);
      }
    }
    return points[points.length - 1].db;
  }

  function duckDb(voiceDb, amount, release) {
    const n = voiceDb.length, hold = Math.round(DUCK_HOLD_S * FPS), ahead = Math.round(DUCK_LOOKAHEAD_S * FPS);
    const spread = new Int32Array(n + 1);
    for (let i = 0; i < n; i++) if (voiceDb[i] > DUCK_THRESHOLD_DB) {
      spread[clamp(i - ahead, 0, n)] += 1; spread[clamp(i + hold + 1, 0, n)] -= 1;
    }
    const down = Math.exp(-3 / (DUCK_ATTACK_S * FPS)), up = Math.exp(-3 / (release * FPS));
    const out = new Float64Array(n);
    let acc = 0, g = 0;
    for (let i = 0; i < n; i++) {
      acc += spread[i];
      const target = acc > 0 ? -amount : 0;
      const k = target < g ? down : up;
      g = target + (g - target) * k;
      out[i] = g;
    }
    return out;
  }

  // Pegel der Sprach-Spur pro 10 ms – offline gerendert (16 kHz genügt für die Erkennung)
  async function voiceLevels(n) {
    const d = data(), t = d.tracks.voice;
    const anySolo = TRACKS.some((k) => d.tracks[k].solo);
    const clips = d.clips.filter((c) => c.track === "voice");
    const out = new Float64Array(n).fill(-120);
    if (!clips.length || t.mute || (anySolo && !t.solo)) return out;
    const SR = 16000, len = Math.ceil(d.length * SR);
    const off = new OfflineAudioContext(1, len, SR);
    for (const clip of clips) {
      let buf; try { buf = await player.buffer(keyOf(clip)); } catch (_) { continue; }
      const src = off.createBufferSource(); src.buffer = buf;
      let offset = clip.offset;
      if (clip.loop) { src.loop = true; src.loopStart = 0; src.loopEnd = buf.duration; offset %= buf.duration; }
      const g = off.createGain();
      scheduleEnvelope(g.gain, clip, 0, clip.start, dbToLin(clip.gain_db));
      src.connect(g).connect(off.destination);
      src.start(clip.start, offset, Math.min(clip.duration, d.length - clip.start));
    }
    const rendered = (await off.startRendering()).getChannelData(0), hop = SR / FPS;
    for (let i = 0; i < n; i++) {
      let p = 0; const a = i * hop;
      if (a + hop > rendered.length) break;
      for (let j = a; j < a + hop; j++) p += rendered[j] * rendered[j];
      // Server misst Stereo gemittelt: Mono-Spur ergibt denselben Wert
      out[i] = 10 * Math.log10(Math.max(p / hop, 1e-12)) + t.gain_db + envDbAt(t.envelope, i / FPS);
    }
    return out;
  }

  // Lautstärke jeder Spur pro Frame (dB): Spurregler + Hüllkurve (+ Ducking)
  async function trackCurves() {
    const d = data(), n = Math.ceil(d.length * FPS) + 1;
    const needDuck = TRACKS.some((k) => k !== "voice" && d.tracks[k].duck && d.clips.some((c) => c.track === k));
    const duck = needDuck ? duckDb(await voiceLevels(n), d.ducking?.amount_db ?? 10, d.ducking?.release_s ?? 0.5) : null;
    const curves = {};
    for (const k of TRACKS) {
      const t = d.tracks[k], arr = new Float64Array(n);
      for (let i = 0; i < n; i++) arr[i] = t.gain_db + envDbAt(t.envelope, i / FPS) + (duck && k !== "voice" && t.duck ? duck[i] : 0);
      curves[k] = arr;
    }
    return curves;
  }

  // Zeichnen und Bearbeiten
  const dbToY = (db, H) => ((ENV_TOP - clamp(db, ENV_BOTTOM, ENV_TOP)) / (ENV_TOP - ENV_BOTTOM)) * H;
  const yToDb = (y, H) => Math.round((ENV_TOP - (y / H) * (ENV_TOP - ENV_BOTTOM)) * 2) / 2;
  const SVG = "http://www.w3.org/2000/svg";

  function renderEnvelopes() {
    if (!state.project) return;
    for (const lane of lanes()) {
      const k = lane.dataset.track, pts = data().tracks[k].envelope || [];
      let svg = lane.querySelector("svg.env");
      if (!svg) { svg = document.createElementNS(SVG, "svg"); svg.classList.add("env"); lane.appendChild(svg); }
      const W = lane.clientWidth, H = lane.clientHeight, L = data().length;
      svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      svg.replaceChildren();
      lane.classList.toggle("has-env", pts.length > 0);
      if (!pts.length && !envMode) continue;
      const line = document.createElementNS(SVG, "polyline");
      const coords = pts.length ? [[0, pts[0].db], ...pts.map((p) => [p.t, p.db]), [L, pts[pts.length - 1].db]] : [[0, 0], [L, 0]];
      line.setAttribute("points", coords.map(([t, db]) => `${(t / L) * W},${dbToY(db, H)}`).join(" "));
      svg.appendChild(line);
      pts.forEach((p, i) => {
        const c = document.createElementNS(SVG, "circle");
        c.setAttribute("cx", (p.t / L) * W); c.setAttribute("cy", dbToY(p.db, H)); c.setAttribute("r", 5);
        c.dataset.idx = i;
        const title = document.createElementNS(SVG, "title"); title.textContent = `${fmtTime(p.t)} · ${p.db > 0 ? "+" : ""}${p.db} dB`;
        c.appendChild(title);
        svg.appendChild(c);
      });
    }
  }

  function setEnvMode(on) {
    envMode = on;
    $("env-mode").setAttribute("aria-pressed", String(on));
    $("timeline").classList.toggle("env-mode", on);
    $("hint-env").hidden = !on; $("hint-clips").hidden = on;
    if (on) select(null);
    renderEnvelopes();
  }

  function envPointer(e) {
    if (!envMode) return;
    const lane = e.target.closest(".lane[data-track]");
    if (!lane || e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    const k = lane.dataset.track; envTrack = k;
    const track = data().tracks[k];
    track.envelope = track.envelope || [];
    const rect = lane.getBoundingClientRect(), L = data().length;
    const at = (ev) => ({ t: +clamp(snap(((ev.clientX - rect.left) / rect.width) * L, ev.altKey), 0, L).toFixed(3),
                          db: clamp(yToDb(ev.clientY - rect.top, rect.height), -60, 12) });
    let idx = e.target.dataset?.idx != null ? Number(e.target.dataset.idx) : -1;
    let point;
    if (idx >= 0) {
      // Doppelklick auf einen Punkt löscht ihn (eigene Erkennung: die Punkte werden beim Ziehen neu gezeichnet)
      const nowMs = performance.now();
      if (lastEnvDown && lastEnvDown.point === track.envelope[idx] && nowMs - lastEnvDown.time < 400) {
        track.envelope.splice(idx, 1);
        lastEnvDown = null;
        renderEnvelopes(); changed();
        return;
      }
      point = track.envelope[idx];
      lastEnvDown = { point, time: nowMs };
    } else {
      point = at(e);
      track.envelope.push(point);
      track.envelope.sort((a, b) => a.t - b.t);
      lastEnvDown = null;
      renderEnvelopes();
    }
    let moved = false;
    const move = (ev) => {
      moved = true;
      const p = at(ev);
      point.t = p.t; point.db = p.db;
      track.envelope.sort((a, b) => a.t - b.t);
      renderEnvelopes();
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      if (moved || idx < 0) changed();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  }

  function bindEnvelopes() {
    $("env-mode").addEventListener("click", () => setEnvMode(!envMode));
    $("timeline").addEventListener("pointerdown", envPointer, true);
    $("env-clear").addEventListener("click", () => {
      if (!envTrack) { toast("Zuerst auf die Spur klicken, deren Hüllkurve gelöscht werden soll."); return; }
      data().tracks[envTrack].envelope = [];
      renderEnvelopes(); changed();
    });
    $("duck-amount").addEventListener("change", (e) => {
      data().ducking = { ...(data().ducking || { release_s: 0.5 }), amount_db: Number(e.target.value) };
      changed();
    });
  }

  // ------------------------------------------------------------------ KI: Text & Stimme
  const ai = { status: null, lastAsset: null };

  function updateScriptInfo() {
    const text = $("ai-script").value;
    const spoken = text.replace(/\[[^\]\n]{1,40}\]/g, " ").replace(/<break[^>]*>/g, " ");
    const words = spoken.split(/\s+/).filter(Boolean).length;
    const max = ai.status?.max_chars || 1000;
    // gezählt wird wie auf dem Server: Regieanweisungen zählen mit, wenn das Modell sie versteht
    const chars = (ai.status?.tags_supported ? text : spoken).replace(/\s+/g, " ").trim().length;
    const info = $("ai-script-info");
    info.textContent = `${chars} Zeichen · ca. ${Math.round(words / 2.5)} s gesprochen` + (chars > max ? ` · zu lang für eine Aufnahme (max. ${max})` : "");
    info.classList.toggle("error-text", chars > max);
  }

  function renderUsage() {
    const st = ai.status; if (!st) return;
    const u = st.usage, l = st.limits;
    const part = (used, limit, label) => `${label}: ${used.toLocaleString("de-AT")}${limit == null ? "" : ` von ${limit.toLocaleString("de-AT")}`}`;
    $("ai-usage").textContent = `Diesen Monat – ${part(u.voice_chars, l.voice_chars, "KI-Stimme (Zeichen)")} · ${part(u.scripts, l.scripts, "KI-Texte")}`;
  }

  async function openAi() {
    try { ai.status = await api("GET", "/api/ai"); } catch (e) { toast(e.message, true); return; }
    const st = ai.status;
    $("ai-text-off").hidden = st.text_enabled;
    $("ai-brief").querySelectorAll("input, textarea, select, button").forEach((el) => { el.disabled = !st.text_enabled; });
    $("ai-tags-row").hidden = !st.tags_supported;
    const ton = $("ai-tonality");
    if (!ton.options.length) ton.replaceChildren(...st.tonalities.map((t) => new Option(t[0].toUpperCase() + t.slice(1), t)));
    $("ai-seconds").value = data().length;
    const voiceOff = !st.voice_enabled ? "Die KI-Stimme ist nicht eingerichtet (ELEVENLABS_API_KEY fehlt)."
      : !st.voices.length ? "Es ist noch keine Stimme freigegeben – Administrator: Menü „KI-Stimmen“." : "";
    $("ai-voice-off").textContent = voiceOff;
    $("ai-voice-off").hidden = !voiceOff;
    $("ai-voice-box").hidden = !!voiceOff;
    const sel = $("ai-voice"), current = sel.value;
    sel.replaceChildren(...st.voices.map((v) => new Option(v.name, v.id)));
    if (current) sel.value = current;
    showVoiceDesc();
    updateScriptInfo();
    renderUsage();
    $("ai-dialog").showModal();
  }

  function showVoiceDesc() {
    const v = ai.status?.voices.find((x) => String(x.id) === $("ai-voice").value);
    $("ai-voice-desc").textContent = v?.description || "";
  }

  async function generateScripts(e) {
    e.preventDefault();
    const f = new FormData($("ai-brief"));
    const btn = $("ai-generate");
    btn.disabled = true; btn.textContent = "Schreibt …";
    try {
      const res = await api("POST", "/api/ai/script", {
        occasion: f.get("occasion"), firma: f.get("firma"), botschaft: f.get("botschaft"), cta: f.get("cta"),
        tonality: f.get("tonality"), seconds: Number(f.get("seconds")) || data().length, audio_tags: f.get("audio_tags") === "on",
      });
      ai.status.usage = res.usage; renderUsage();
      $("ai-suggestions").replaceChildren(...res.scripts.map((text, i) => {
        const card = document.createElement("div"); card.className = "ai-suggestion";
        const p = document.createElement("p"); p.textContent = text;
        const b = document.createElement("button"); b.textContent = `Vorschlag ${i + 1} übernehmen`;
        b.addEventListener("click", () => {
          $("ai-script").value = text; updateScriptInfo();
          data().script = text; changed({ replay: false });
          $("ai-script").focus();
        });
        card.append(p, b);
        return card;
      }));
    } catch (err) { toast(err.message, true); } finally { btn.disabled = false; btn.textContent = "3 Vorschläge erstellen"; }
  }

  async function speak() {
    const text = $("ai-script").value.trim();
    if (!text) { toast("Bitte zuerst einen Sprechtext eingeben.", true); return; }
    const btn = $("ai-speak");
    btn.disabled = true; btn.textContent = "Spricht ein …";
    try {
      const res = await api("POST", "/api/ai/voice", { voice_id: Number($("ai-voice").value), text });
      const a = res.asset;
      state.assets = new Map([[a.id, a], ...state.assets]);
      renderAssets(); refreshMe();
      ai.status.usage = res.usage; renderUsage();
      ai.lastAsset = a;
      $("ai-audio").src = `/api/assets/${a.id}/audio`;
      $("ai-result").hidden = false;
      toast(`„${a.name}“ liegt in den Dateien`);
    } catch (err) { toast(err.message, true); } finally { btn.disabled = false; btn.textContent = "Stimme erzeugen"; }
  }

  function bindAi() {
    $("ai-open").addEventListener("click", openAi);
    $("ai-brief").addEventListener("submit", generateScripts);
    $("ai-voice").addEventListener("change", showVoiceDesc);
    $("ai-speak").addEventListener("click", speak);
    $("ai-script").addEventListener("input", () => { data().script = $("ai-script").value; updateScriptInfo(); changed({ replay: false }); });
    $("ai-place").addEventListener("click", () => {
      if (!ai.lastAsset) return;
      addClip(ai.lastAsset, "voice", Math.min(player.paused, data().length - MIN_CLIP));
      $("ai-audio").pause();
      $("ai-dialog").close();
      toast("Auf die Sprach-Spur gelegt");
    });
    $("ai-dialog").addEventListener("close", () => $("ai-audio").pause());
  }

  bind();
  bindAi();
  bindEnvelopes();
  init().catch((e) => toast(e.message, true));
})();
