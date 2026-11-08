// Radiospot-Studio – Mehrspur-Editor (Schritt 2): Dateien, Clips verschieben/kürzen, Vorhören, Export.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const TRACKS = ["voice", "music", "sfx", "atmo"];
  const MIN_CLIP = 0.05;          // kürzeste Cliplänge (s)
  const SNAP = 0.05;              // Raster (s), mit Alt aus
  const DEFAULT_GAIN = { atmo: -12 };  // Atmo startet leise

  const state = {
    me: null, assets: new Map(), peaks: new Map(), projects: [],
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
  function storageGet(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function storageSet(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* privat */ } }

  // ------------------------------------------------------------------ Laden
  async function init() {
    state.me = await api("GET", "/api/me");
    updateUsage();
    await loadAssets();
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

  async function refreshMe() {
    try { state.me = await api("GET", "/api/me"); updateUsage(); } catch (_) { /* egal */ }
  }

  function updateUsage() {
    const used = state.me.used_bytes, quota = state.me.quota_mb * 1048576;
    $("usage-fill").style.width = `${Math.min(100, (used / Math.max(quota, 1)) * 100)}%`;
    $("usage-text").textContent = `${fmtMB(used)} von ${state.me.quota_mb} MB belegt`;
  }

  async function peaksFor(id) {
    if (!state.peaks.has(id)) {
      state.peaks.set(id, fetch(`/api/assets/${id}/peaks`, { credentials: "same-origin" })
        .then((r) => (r.ok ? r.json() : [])).then((a) => Uint8Array.from(a)).catch(() => new Uint8Array()));
    }
    return state.peaks.get(id);
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
    label.textContent = state.assets.get(clip.asset_id)?.name || "Datei fehlt";
    const hl = document.createElement("span"); hl.className = "handle left"; hl.dataset.mode = "left";
    const hr = document.createElement("span"); hr.className = "handle right"; hr.dataset.mode = "right";
    el.append(canvas, label, hl, hr);
    placeClip(el, clip);
    return el;
  }

  function placeClip(el, clip) {
    const L = data().length;
    el.style.left = `${(clip.start / L) * 100}%`;
    el.style.width = `${(clip.duration / L) * 100}%`;
    el.classList.toggle("selected", state.selected === clip.id);
    requestAnimationFrame(() => drawWave(el, clip));
  }

  async function drawWave(el, clip) {
    const canvas = el.querySelector("canvas");
    const peaks = await peaksFor(clip.asset_id);
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
      const t0 = clip.offset + x * perPx, t1 = t0 + perPx;
      let i = Math.floor(t0 * 50), end = Math.max(i + 1, Math.ceil(t1 * 50)), p = 0;
      for (; i < end && i < peaks.length; i++) p = Math.max(p, peaks[i]);
      const local = x * perPx;
      let env = gain;
      if (clip.fade_in > 0) env *= Math.min(1, local / clip.fade_in);
      if (clip.fade_out > 0) env *= Math.min(1, (clip.duration - local) / clip.fade_out);
      const h = Math.min(1, (p / 255) * env) * (H / 2 - 2 * dpr);
      g.fillRect(x, mid - h, 1, Math.max(1, h * 2));
    }
    // Fades als Linie
    g.strokeStyle = color; g.lineWidth = 1.5 * dpr; g.globalAlpha = 0.9;
    const fx = (s) => (s / clip.duration) * W;
    g.beginPath();
    g.moveTo(0, clip.fade_in > 0 ? H : 1);
    if (clip.fade_in > 0) g.lineTo(fx(clip.fade_in), 1);
    g.lineTo(W - fx(clip.fade_out), 1);
    g.lineTo(W, clip.fade_out > 0 ? H : 1);
    g.stroke();
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
    $("insp-name").textContent = state.assets.get(clip.asset_id)?.name || "Clip";
    $("insp-gain").value = clip.gain_db;
    $("insp-gain-val").textContent = `${clip.gain_db > 0 ? "+" : ""}${clip.gain_db} dB`;
    $("insp-fade-in").value = clip.fade_in;
    $("insp-fade-out").value = clip.fade_out;
    $("insp-pos").textContent = `${fmtTime(clip.start)} – ${fmtTime(clip.start + clip.duration)}`;
  }

  function addClip(asset, track, start) {
    const clip = {
      id: uid(), asset_id: asset.id, track, start: Math.max(0, start), offset: 0,
      duration: asset.duration, gain_db: DEFAULT_GAIN[track] || 0, fade_in: 0, fade_out: 0,
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
             s0: clip.start, o0: clip.offset, d0: clip.duration, track0: clip.track, moved: false };
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
    const assetDur = state.assets.get(clip.asset_id)?.duration ?? drag.o0 + drag.d0;
    if (drag.mode === "move") {
      clip.start = clamp(snap(drag.s0 + dx, free), 0, data().length - MIN_CLIP);
      const lane = document.elementFromPoint(e.clientX, e.clientY)?.closest(".lane[data-track]");
      if (lane && lane.dataset.track !== clip.track) {
        clip.track = lane.dataset.track;
        lane.appendChild(el);
      }
    } else if (drag.mode === "left") {
      const end = drag.s0 + drag.d0;
      const start = clamp(snap(drag.s0 + dx, free), Math.max(0, drag.s0 - drag.o0), end - MIN_CLIP);
      clip.start = start;
      clip.offset = drag.o0 + (start - drag.s0);
      clip.duration = end - start;
    } else {
      const end = clamp(snap(drag.s0 + drag.d0 + dx, free), drag.s0 + MIN_CLIP, drag.s0 + assetDur - drag.o0);
      clip.duration = end - drag.s0;
    }
    clip.start = +clip.start.toFixed(4); clip.offset = +clip.offset.toFixed(4); clip.duration = +clip.duration.toFixed(4);
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
        this.buffers.set(id, fetch(`/api/assets/${id}/audio`, { credentials: "same-origin" })
          .then((r) => { if (!r.ok) throw new Error("Datei nicht ladbar"); return r.arrayBuffer(); })
          .then((b) => this.ctx.decodeAudioData(b))
          .catch((e) => { this.buffers.delete(id); throw e; }));
      }
      return this.buffers.get(id);
    },

    trackLevel(track) {
      const tracks = data().tracks, anySolo = TRACKS.some((k) => tracks[k].solo), t = tracks[track];
      if (t.mute || (anySolo && !t.solo)) return 0;
      return dbToLin(t.gain_db);
    },

    updateTrackGains() {
      for (const k of TRACKS) if (this.trackGains[k]) this.trackGains[k].gain.setTargetAtTime(this.trackLevel(k), this.ctx.currentTime, 0.02);
    },

    async play() {
      if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      await this.ctx.resume();
      const from = this.paused >= data().length ? 0 : this.paused;
      $("play").disabled = true;
      try {
        await Promise.all([...new Set(data().clips.map((c) => c.asset_id))].map((id) => this.buffer(id)));
      } catch (e) { toast(e.message, true); $("play").disabled = false; return; }
      $("play").disabled = false;
      this.start(from);
    },

    async start(from) {
      this.stopNodes();
      const ctx = this.ctx, now = ctx.currentTime + 0.05;
      for (const k of TRACKS) {
        const g = ctx.createGain();
        g.gain.value = this.trackLevel(k);
        g.connect(ctx.destination);
        this.trackGains[k] = g;
      }
      for (const clip of data().clips) {
        const local = Math.max(0, from - clip.start);
        const dur = clip.duration - local;
        if (dur <= 0 || clip.start >= data().length) continue;
        let buf;
        try { buf = await this.buffer(clip.asset_id); } catch (_) { continue; }
        const src = ctx.createBufferSource();
        src.buffer = buf;
        const g = ctx.createGain();
        const when = now + Math.max(0, clip.start - from);
        const base = dbToLin(clip.gain_db), fi = clip.fade_in, fo = clip.fade_out, d = clip.duration;
        const env = (t) => base * (fi > 0 ? Math.min(1, t / fi) : 1) * (fo > 0 ? Math.min(1, (d - t) / fo) : 1);
        g.gain.setValueAtTime(env(local), when);
        if (fi > 0 && local < fi) g.gain.linearRampToValueAtTime(base, when + (fi - local));
        if (fo > 0) {
          const foStart = Math.max(local, d - fo);
          g.gain.setValueAtTime(env(foStart), when + (foStart - local));
          g.gain.linearRampToValueAtTime(0, when + dur);
        }
        src.connect(g).connect(this.trackGains[clip.track]);
        src.start(when, clip.offset + local, dur);
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
        info.textContent = `${e.measured_lufs ?? "–"} LUFS · ${e.measured_peak ?? "–"} dBTP · ${fmtMB(e.size_bytes)}`;
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
      const v = $("export-loudness").value;
      await api("POST", `/api/projects/${state.project.id}/exports`, { loudness: v === "" ? null : Number(v) });
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
        if ([...e.dataTransfer.types].some((t) => t === "application/x-studio-asset" || t === "Files")) {
          e.preventDefault(); lane.classList.add("drop");
        }
      });
      lane.addEventListener("dragleave", () => lane.classList.remove("drop"));
      lane.addEventListener("drop", async (e) => {
        e.preventDefault(); lane.classList.remove("drop");
        let start = snap(timeAt(e.clientX, lane), e.altKey);
        const id = Number(e.dataTransfer.getData("application/x-studio-asset"));
        if (id && state.assets.has(id)) { addClip(state.assets.get(id), lane.dataset.track, start); return; }
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
        if (act !== "mute" && act !== "solo") return;
        data().tracks[k][act] = !data().tracks[k][act];
        renderTracks(); player.updateTrackGains(); changed({ replay: false });
      });
      head.querySelector('[data-act="gain"]').addEventListener("input", (e) => {
        data().tracks[k].gain_db = Number(e.target.value);
        renderTracks(); player.updateTrackGains(); changed({ replay: false });
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

  bind();
  init().catch((e) => toast(e.message, true));
})();
