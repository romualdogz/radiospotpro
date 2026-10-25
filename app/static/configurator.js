/*
 * Radiospot-Konfigurator (onaircraft) – Ablauf und Design nach der HTML-Vorlage,
 * Produkte, Preise und Absenden über das FastAPI-Backend:
 *
 *   GET  /api/catalog          Anlässe, Längen, Stimmen, Musik, Sender … (im Admin pflegbar)
 *   POST /api/generate-script  KI-Textvorschlag (API-Key bleibt auf dem Server)
 *   POST /api/quote            Preis berechnen
 *   POST /api/quote-requests   Anfrage absenden
 */
(function () {
  "use strict";

  const root = document.getElementById("radiospot-configurator");
  if (!root) return;
  const API = (root.dataset.api || "").replace(/\/$/, "");

  const STEPS = ["Anlass", "Text", "Stimme", "Buchung", "Anfrage"];
  const WORDS_PER_SECOND = 2.5;

  let C = null; // Katalog
  const state = {
    step: 0, maxReached: 0,
    occasionId: null, lengthId: null,
    firma: "", tonalityId: null, styleId: null, botschaft: "", cta: "", script: "",
    voiceId: null, musicId: null, addonIds: new Set(),
    studio: false, items: [], bookingMode: "individual", packageId: null,
    promo: "", country: "AT", vatId: "",
    name: "", company: null, street: "", zip: "", city: "", email: "", phone: "", nachricht: "",
    acceptTerms: false, acceptPrivacy: false,
    quote: null, sent: null, demo: null,
  };

  // ------------------------------------------------------------------ Helpers
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "class") el.className = v;
      else if (k === "value") el.value = v;
      else if (v === true) el.setAttribute(k, "");
      else if (v !== false && v != null) el.setAttribute(k, v);
    }
    for (const c of children.flat(Infinity)) if (c != null && c !== false) el.append(c);
    return el;
  }
  const byId = (list, id) => list.find((x) => x.id === id);
  const money = (cent) => new Intl.NumberFormat("de-AT", { style: "currency", currency: C?.currency || "EUR" }).format(cent / 100);
  const pct = (bp) => (bp / 100).toLocaleString("de-AT") + " %";

  async function api(path, body) {
    const res = await fetch(API + path, body
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : undefined);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      const msg = Array.isArray(d) ? d.map((x) => x.msg.replace(/^Value error, /, "")).join(", ") : d;
      const err = new Error(msg || `Fehler ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  const field = (label, control, extra) => h("div", { class: "field" }, h("label", {}, label), control, extra);

  function select(list, value, onChange, labelFn = (x) => x.name) {
    return h("select", { onchange: (e) => onChange(Number(e.target.value)) },
      list.map((x) => h("option", { value: x.id, selected: x.id === value }, labelFn(x))));
  }

  function chips(list, value, onPick, labelFn = (x) => x.name) {
    return h("div", { class: "chips" }, list.map((x) => h("button", {
      type: "button", class: "chip" + (x.id === value ? " sel" : ""), onclick: () => onPick(x.id),
    }, labelFn(x))));
  }

  // Spot-Textfeld wächst mit dem Inhalt mit, damit darin nicht gescrollt werden muss
  function autoGrow(el) {
    el.style.height = "auto";
    el.style.height = el.scrollHeight + 2 + "px";
  }

  function input(key, attrs = {}) {
    const grow = attrs.class === "script-box";
    const el = h(attrs.multiline ? "textarea" : "input", {
      type: attrs.multiline ? null : attrs.type || "text", placeholder: attrs.placeholder, value: state[key],
      class: attrs.class, autocomplete: attrs.autocomplete,
      oninput: (e) => { state[key] = e.target.value; if (grow) autoGrow(el); attrs.onInput?.(); refreshNav(); },
    });
    if (grow) requestAnimationFrame(() => autoGrow(el));  // nach dem Einfügen ins Formular
    return el;
  }

  // ------------------------------------------------------------------ Hero-Welle & Tuner-Navigation
  const wave = document.getElementById("wave");
  if (wave) for (let i = 0; i < 28; i++) {
    const bar = document.createElement("i");
    bar.style.height = 14 + Math.random() * 32 + "px";
    bar.style.animationDelay = (Math.random() * 1.4).toFixed(2) + "s";
    wave.appendChild(bar);
  }

  const dialRow = document.getElementById("dialRow");
  const needle = document.getElementById("needle");
  const stepHost = document.getElementById("stepHost");
  const btnBack = document.getElementById("btnBack");
  const btnNext = document.getElementById("btnNext");

  STEPS.forEach((name, i) => {
    dialRow.append(h("button", { type: "button", class: "freq", onclick: () => { if (i <= state.maxReached) goTo(i); } },
      `Schritt ${i + 1} von ${STEPS.length}`, h("span", { class: "fname" }, name)));
  });

  function renderDial() {
    [...dialRow.children].forEach((b, i) => {
      b.classList.toggle("active", i === state.step);
      b.classList.toggle("done", i < state.step);
      b.disabled = i > state.maxReached || !!state.sent;
    });
    needle.style.left = (state.step / (STEPS.length - 1)) * 100 + "%";
  }

  function goTo(i) {
    stopAudio();
    state.step = i;
    state.maxReached = Math.max(state.maxReached, i);
    render();
    root.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function canAdvance() {
    // Eigener Spot-Text reicht – Firma, Kernbotschaft und Call-to-Action braucht nur der KI-Vorschlag
    if (state.step === 1) return !!(state.script.trim() || (state.firma.trim() && state.botschaft.trim() && state.cta.trim()));
    if (state.step === 3 && state.bookingMode === "package") return packageFits(selectedPackage());
    if (state.step === 4) {
      return !state.sent && ["name", "street", "zip", "city", "phone", "email"].every((k) => state[k].trim())
        && state.acceptTerms && state.acceptPrivacy;
    }
    return true;
  }

  function refreshNav() {
    btnNext.disabled = !canAdvance();
    const hint = document.getElementById("textHint");
    if (hint) hint.hidden = !btnNext.disabled;
  }

  // ------------------------------------------------------------------ Komplettpakete
  const selectedPackage = () => state.bookingMode === "package" ? byId(C.packages, state.packageId) : null;
  const packageFits = (p) => !!p && (!p.max_seconds || byId(C.spot_lengths, state.lengthId).seconds <= p.max_seconds);
  // Studiospot gewählt oder im gewählten Paket enthalten
  const studioActive = () => state.studio || !!selectedPackage()?.includes_studio;

  // ------------------------------------------------------------------ Preis
  function configuration() {
    const pkg = selectedPackage();
    return {
      production: { spot_length_id: state.lengthId, voice_id: state.voiceId, music_style_id: state.musicId,
        studio: state.studio && !pkg?.includes_studio },
      package_id: pkg ? pkg.id : null,
      items: pkg ? [] : state.items.map((i) => ({ ...i, spot_length_id: state.lengthId })),
      addon_ids: [...state.addonIds],
      promo_code: state.promo.trim() || null,
      country: state.country,
      vat_id: state.vatId.trim() || null,
    };
  }

  let quoteTimer = null, quoteSeq = 0;
  function scheduleQuote() {
    clearTimeout(quoteTimer);
    quoteTimer = setTimeout(updateQuote, 250);
  }
  async function updateQuote() {
    const seq = ++quoteSeq;
    let q;
    try { q = await api("/api/quote", configuration()); } catch (e) { q = { error: e.message }; }
    if (seq !== quoteSeq) return;
    state.quote = q;
    document.querySelectorAll("[data-price]").forEach((el) => el.replaceChildren(priceBlock()));
  }

  function priceBlock() {
    const q = state.quote;
    if (!q) return h("p", { class: "muted" }, "Preis wird berechnet …");
    if (q.error) return h("p", { class: "error-text" }, q.error);
    const row = (label, value, cls, sub) => h("tr", { class: cls || "" },
      h("td", {}, label, sub ? h("small", {}, sub) : null), h("td", {}, value));
    const p = q.production;
    const promoMsg = { applied: "Gutscheincode angewendet ✔",
      invalid: "Gutscheincode ungültig oder Bedingungen nicht erfüllt",
      superseded: "Gutscheincode gültig – ein besserer Rabatt wurde automatisch gewählt" }[q.promo_code_status];
    return h("div", {},
      h("table", { class: "price-table" },
        q.package ? row(`Komplettpaket „${q.package.name}“`, money(q.package.price_cent), "",
          [q.package.spots ? `${q.package.spots} Ausstrahlungen` : "", "Pauschalpreis"].filter(Boolean).join(" · ")) : null,
        p ? (p.studio
          ? row("Studiospot mit echtem Sprecher", p.in_package ? "inklusive" : money(p.total_cent), "", `${p.seconds} Sek.`)
          : row("Spot-Text & Hörbeispiel", "gratis", "", `${p.seconds} Sek.`)) : null,
        q.lines.map((l) => row(`${l.spots} × ${l.station}`, money(l.total_cent), "", `${l.kind === "stream" ? "Stream · " : ""}${l.time_slot} · à ${money(l.unit_price_cent)}`)),
        q.addons.map((a) => row(a.name, money(a.price_cent))),
        q.discounts.map((d) => row(d.name, "− " + money(d.amount_cent), "discount")),
        row("Netto", money(q.net_cent), "sum"),
        q.ad_tax_cent ? row(`Werbeabgabe ${pct(q.ad_tax_rate_bp)}`, money(q.ad_tax_cent), "",
          `auf ${money(q.ad_tax_base_cent)} Radio-Sendezeit`) : null,
        q.reverse_charge
          ? row("MwSt. 0 % – Nettorechnung", money(0), "", "Reverse Charge: Steuerschuld geht auf den Leistungsempfänger über")
          : row(`MwSt. ${pct(q.vat_rate_bp)} (${q.country_name})`, money(q.vat_cent)),
      ),
      h("p", { class: "price" }, money(q.gross_cent), h("small", {},
        q.reverse_charge ? "Gesamt netto (Reverse Charge) · unverbindlich" : "Gesamt inkl. Steuern · unverbindlich")),
      promoMsg ? h("p", { class: q.promo_code_status === "invalid" ? "error-text" : "muted" }, promoMsg) : null,
      !q.meets_minimum_order ? h("p", { class: "error-text" }, `Mindestbestellwert: ${money(q.min_order_cent)} netto`) : null,
    );
  }

  // ------------------------------------------------------------------ Vorschau
  // Browser-Sprachausgabe: Stimmen werden asynchron geladen (Chrome), daher vorab laden und aktualisieren
  const synth = "speechSynthesis" in window ? window.speechSynthesis : null;
  let germanVoices = [];
  function loadVoices() {
    germanVoices = synth.getVoices().filter((x) => x.lang && x.lang.toLowerCase().startsWith("de"));
  }
  if (synth) {
    loadVoices();
    synth.addEventListener?.("voiceschanged", loadVoices);
  }
  const pickGermanVoice = () => ["de-at", "de-de"].map((l) => germanVoices.find((x) => x.lang.toLowerCase() === l))
    .find(Boolean) || germanVoices[0] || null;

  function previewVoice(voiceId, statusEl) {
    const v = byId(C.voices, voiceId);
    const say = (msg, error) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = error ? "var(--danger)" : ""; } };
    if (!v) return;
    if (v.sample_url) {
      new Audio(v.sample_url).play().then(() => say("Hörprobe läuft …"))
        .catch(() => say("Hörprobe konnte nicht abgespielt werden.", true));
      return;
    }
    if (!synth) { say("Ihr Browser unterstützt keine Sprachausgabe – bitte Chrome, Edge oder Safari verwenden.", true); return; }
    if (!germanVoices.length) loadVoices();
    const voice = pickGermanVoice();
    const script = state.script.replace(/\[[^\]\n]{1,40}\]|<break[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    const text = (script || `Hallo, hier spricht ${v.name} — so könnte Ihr Spot klingen.`).slice(0, 1200);
    // In Sätze teilen: Chrome bricht lange Einzel-Ausgaben nach ca. 15 Sekunden ab
    const parts = text.match(/[^.!?]+[.!?]*/g)?.map((t) => t.trim()).filter(Boolean) || [text];
    const utterances = parts.map((part) => {
      const u = new SpeechSynthesisUtterance(part);
      u.lang = voice ? voice.lang : "de-DE";
      if (voice) u.voice = voice;
      u.pitch = v.pitch_bp / 10000;
      u.rate = v.rate_bp / 10000;
      return u;
    });
    utterances[0].onstart = () => say(voice ? "Hörprobe läuft …"
      : "Hörprobe läuft – auf diesem Gerät ist keine deutsche Stimme installiert, daher klingt sie evtl. fremd.");
    utterances[utterances.length - 1].onend = () => say("");
    utterances.forEach((u) => { u.onerror = (e) => { if (e.error !== "interrupted" && e.error !== "canceled") say(`Hörprobe fehlgeschlagen (${e.error}).`, true); }; });
    if (synth.speaking || synth.pending) synth.cancel();
    // kurze Pause nach cancel(), sonst verwirft Chrome die neue Ausgabe teilweise
    setTimeout(() => {
      utterances.forEach((u) => synth.speak(u));
      setTimeout(() => { if (!synth.speaking && !synth.pending) say("Keine Ton-Ausgabe – bitte Lautstärke und Ton-Freigabe des Browsers prüfen.", true); }, 1500);
    }, 60);
  }

  function previewButton(voiceId) {
    const status = h("span", { class: "gen-status" });
    return [h("button", { type: "button", class: "btn small ghost",
      onclick: () => previewVoice(voiceId ?? state.voiceId, status) }, "Vorschau anhören"), status];
  }

  // ------------------------------------------------------------------ Schritte
  function stepAnlass() {
    return [
      h("h2", {}, "Worum geht's?"),
      h("p", { class: "hint" }, "Anlass und Spotlänge bestimmen Ton und Aufbau des Skripts."),
      field("Anlass", chips(C.occasions, state.occasionId, (id) => { state.occasionId = id; render(); })),
      field("Spotlänge", chips(C.spot_lengths, state.lengthId, (id) => { state.lengthId = id; render(); scheduleQuote(); },
        (l) => l.label || `${l.seconds} Sek.`)),
    ];
  }

  function stepText() {
    const status = h("span", { class: "gen-status" });
    const est = h("p", { class: "est" });
    const length = byId(C.spot_lengths, state.lengthId);
    const updateEst = () => {
      // Regieanweisungen [excited] und Pausen <break …/> werden nicht gesprochen
      const words = state.script.replace(/\[[^\]\n]{1,40}\]|<break[^>]*>/g, " ").trim().split(/\s+/).filter(Boolean).length;
      est.textContent = words
        ? `≈ ${words} Wörter, ca. ${Math.round(words / WORDS_PER_SECOND)} Sek. gesprochen (Ziel: ${length.seconds} Sek.)` : "";
    };
    const scriptBox = input("script", { multiline: true, class: "script-box",
      placeholder: "Hier erscheint der Vorschlag — oder selbst schreiben.", onInput: updateEst });
    updateEst();

    async function generate(btn) {
      if (!state.firma.trim() || !state.botschaft.trim() || !state.cta.trim()) {
        status.textContent = "Bitte zuerst Firma, Kernbotschaft und Call-to-Action ausfüllen.";
        status.style.color = "var(--danger)";
        return;
      }
      btn.disabled = true;
      status.style.color = "var(--accent-2)";
      status.textContent = "Das KI-Gehirn arbeitet …";
      try {
        const res = await api("/api/generate-script", {
          occasion_id: state.occasionId, spot_length_id: state.lengthId, tonality_id: state.tonalityId,
          language_style_id: state.styleId, firma: state.firma, botschaft: state.botschaft, cta: state.cta,
        });
        state.script = res.script;
        scriptBox.value = res.script;
        autoGrow(scriptBox);
        updateEst();
        status.textContent = "Vorschlag eingefügt — gerne direkt im Feld anpassen.";
      } catch (e) {
        status.textContent = e.message;
        status.style.color = "var(--danger)";
      }
      btn.disabled = false;
    }

    return [
      h("h2", {}, "Angaben zum Spot"),
      h("p", { class: "hint" }, C.ai_enabled
        ? "Kurz die Eckpunkte eintragen — der Text lässt sich danach mit einem Klick vorschlagen und frei bearbeiten."
        : "Kurz die Eckpunkte eintragen und den Spot-Text selbst formulieren — wir feilen gerne noch daran."),
      h("div", { class: "two-col" },
        field("Firma / Marke", input("firma", { autocomplete: "organization" })),
        field("Tonalität", select(C.tonalities, state.tonalityId, (id) => { state.tonalityId = id; }))),
      field("Sprachstil", select(C.language_styles, state.styleId, (id) => { state.styleId = id; })),
      field("Kernbotschaft / Angebot", input("botschaft", { multiline: true,
        placeholder: "z. B. 20% auf alle Meerwasser-Sets, nur diese Woche" })),
      field("Call-to-Action", input("cta", { placeholder: "z. B. Jetzt vorbeischauen in der Filiale Neusiedl" })),
      C.ai_enabled ? h("div", { class: "gen-row" },
        h("button", { type: "button", class: "btn", onclick: (e) => generate(e.currentTarget) }, "Text mit KI generieren"),
        status) : null,
      field("Spot-Text", scriptBox),
      est,
      h("p", { class: "hint", id: "textHint", hidden: true },
        "Zum Weiterklicken: Spot-Text selbst schreiben – oder Firma, Kernbotschaft und Call-to-Action ausfüllen " +
        "und den Text mit KI erstellen lassen."),
    ];
  }

  // ------------------------------------------------------------------ Audio (Stimmprobe, Musik, Hörprobe)
  let currentAudio = null;
  let currentButton = null;
  function stopAudio() {
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    if (currentButton) { currentButton.textContent = currentButton.dataset.label; currentButton = null; }
    if (synth && (synth.speaking || synth.pending)) synth.cancel();
  }
  // Spielt eine URL ab; erneuter Klick auf denselben Button stoppt
  function toggleAudio(url, button, say) {
    if (currentButton === button) { stopAudio(); return; }
    stopAudio();
    button.dataset.label = button.dataset.label || button.textContent;
    const a = new Audio(url);
    currentAudio = a; currentButton = button;
    button.textContent = "■ Stopp";
    a.onended = () => { if (currentAudio === a) stopAudio(); };
    a.play().catch(() => { stopAudio(); say?.("Wiedergabe nicht möglich.", true); });
  }

  async function fetchAudio(path, body) {
    const res = await fetch(API + path, body
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : `Fehler ${res.status}`);
    }
    return URL.createObjectURL(await res.blob());
  }

  const voiceSampleCache = {};
  function voiceSampleButton(v) {
    const status = h("span", { class: "gen-status" });
    const say = (msg, error) => { status.textContent = msg; status.style.color = error ? "var(--danger)" : ""; };
    const btn = h("button", { type: "button", class: "btn small ghost", onclick: async () => {
      if (v.sample_url) { toggleAudio(v.sample_url, btn, say); return; }
      if (!(C.tts_enabled && v.has_tts)) { stopAudio(); previewVoice(v.id, status); return; }
      if (currentButton === btn) { stopAudio(); return; }
      try {
        if (!voiceSampleCache[v.id]) {
          say("Stimmprobe wird erzeugt …");
          voiceSampleCache[v.id] = await fetchAudio(`/api/voices/${v.id}/sample`);
        }
        say("");
        toggleAudio(voiceSampleCache[v.id], btn, say);
      } catch (e) { say(e.message, true); }
    } }, "Stimme anhören");
    return [btn, status];
  }

  function musicCards() {
    return h("div", { class: "voices" }, C.music_styles.map((m) => {
      const sel = m.id === state.musicId;
      let playBtn = null;
      if (m.audio_url) {
        playBtn = h("button", { type: "button", class: "btn small ghost",
          onclick: () => toggleAudio(API + m.audio_url, playBtn) }, "▶ Vorhören");
      }
      return h("div", { class: "voice" + (sel ? " sel" : "") },
        h("div", { class: "voice-top" }, h("div", { class: "voice-name" }, m.name)),
        h("div", { class: "voice-actions" }, playBtn,
          h("button", { type: "button", class: "btn small" + (sel ? "" : " ghost"),
            onclick: () => { state.musicId = m.id; render(); scheduleQuote(); } }, sel ? "Gewählt" : "Wählen")));
    }));
  }

  // Hörprobe = Spot-Text + KI-Stimme + Musik, serverseitig gemischt, mit Wasserzeichen
  const demoKey = () => JSON.stringify([state.voiceId, state.musicId, state.tonalityId, state.lengthId, state.script.trim()]);
  function demoBlock() {
    const v = byId(C.voices, state.voiceId);
    const box = h("div", { class: "summary-box demo" });
    const status = h("span", { class: "gen-status" });
    const say = (msg, error) => { status.textContent = msg; status.style.color = error ? "var(--danger)" : ""; };
    const player = h("div", {});
    const showPlayer = (url) => player.replaceChildren(h("audio", {
      controls: true, src: url, controlslist: "nodownload noplaybackrate", oncontextmenu: (e) => e.preventDefault() }));

    if (!(C.tts_enabled && v?.has_tts)) {
      box.append(h("b", {}, "Hörprobe"),
        h("p", { class: "est" }, "Die KI-Stimme ist für diese Stimme nicht eingerichtet – Vorschau über die Sprachausgabe Ihres Browsers (ohne Musik)."),
        h("div", { class: "gen-row" }, previewButton()));
      return box;
    }
    const fresh = state.demo && state.demo.key === demoKey();
    const btn = h("button", { type: "button", class: "btn", disabled: !state.script.trim(), onclick: async () => {
      btn.disabled = true; stopAudio();
      say("Hörprobe wird erstellt … das dauert ein paar Sekunden.");
      try {
        const url = await fetchAudio("/api/demo-audio",
          { voice_id: state.voiceId, music_style_id: state.musicId, script: state.script.trim(),
            tonality_id: state.tonalityId, spot_length_id: state.lengthId });
        if (state.demo) URL.revokeObjectURL(state.demo.url);
        state.demo = { key: demoKey(), url };
        showPlayer(url);
        player.querySelector("audio").play().catch(() => {});
        say("");
      } catch (e) { say(e.message, true); }
      btn.disabled = false;
    } }, fresh ? "Hörprobe neu erstellen" : "Hörprobe erstellen");
    if (fresh) showPlayer(state.demo.url);
    box.append(
      h("b", {}, "Ihre Hörprobe"),
      h("p", { class: "est" }, state.script.trim()
        ? `${v.name} spricht Ihren Text${byId(C.music_styles, state.musicId)?.audio_url ? " mit der gewählten Musik" : ""}. `
          + "Die Hörprobe enthält ein akustisches Wasserzeichen – den fertigen Spot ohne Wasserzeichen erhalten Sie nach Ihrer Buchung."
        : "Bitte zuerst in Schritt 2 einen Spot-Text eingeben."),
      h("div", { class: "gen-row" }, btn, status),
      player);
    return box;
  }

  function stepStimme() {
    const voices = h("div", { class: "voices" }, C.voices.map((v) => {
      const sel = v.id === state.voiceId;
      return h("div", { class: "voice" + (sel ? " sel" : "") },
        h("div", { class: "voice-top" },
          h("div", {}, h("div", { class: "voice-name" }, v.name), h("div", { class: "voice-tag" }, v.tag)),
          v.tier ? h("div", { class: "voice-badge" }, v.tier) : null),
        h("div", { class: "voice-actions" },
          voiceSampleButton(v),
          h("button", { type: "button", class: "btn small" + (sel ? "" : " ghost"),
            onclick: () => { state.voiceId = v.id; render(); scheduleQuote(); } }, sel ? "Gewählt" : "Wählen")));
    }));
    return [
      h("h2", {}, "Stimme & Musik"),
      h("p", { class: "hint" }, "Wählen Sie Stimme und Musik und hören Sie Ihren Spot kostenlos als Hörprobe."),
      field("Stimme", voices),
      C.music_styles.length ? field("Musik", musicCards()) : null,
      demoBlock(),
    ];
  }

  // Extras mit „Nur mit Studiospot“ erscheinen erst, wenn der Studiospot gewählt ist
  const visibleAddons = () => C.addons.filter((a) => !a.requires_studio || studioActive());

  // Sender-Auswahl gruppiert nach Radio / Streams der Energy-Gruppe
  const CHANNEL_GROUPS = [["radio", "Radio"], ["stream", "Streams der Energy-Gruppe"]];
  function stationSelect(item) {
    const opt = (s) => h("option", { value: s.id, selected: s.id === item.station_id },
      s.region ? `${s.name} (${s.region})` : s.name);
    const groups = CHANNEL_GROUPS.map(([kind, label]) => [label, C.stations.filter((s) => s.kind === kind)])
      .filter(([, list]) => list.length);
    return h("select", { onchange: (e) => { item.station_id = Number(e.target.value); scheduleQuote(); refreshCoverage(); } },
      groups.length > 1 ? groups.map(([label, list]) => h("optgroup", { label }, list.map(opt))) : C.stations.map(opt));
  }

  // ------------------------------------------------------------------ Reichweiten-Karte (DAB+ vs. UKW)
  function selectedCoverage() {
    const pkg = selectedPackage();
    const ids = new Set(), streams = [];
    if (pkg) {
      (pkg.coverage_ids || []).forEach((id) => ids.add(id));
    } else {
      for (const item of state.items) {
        const st = byId(C.stations, item.station_id);
        if (!st) continue;
        (st.coverage_ids || []).forEach((id) => ids.add(id));
        if (st.kind === "stream" && !streams.includes(st.name)) streams.push(st.name);
      }
    }
    const areas = (C.coverage_areas || []).filter((a) => ids.has(a.id));
    // DAB+ zuerst (großflächig), dann UKW
    areas.sort((a, b) => (a.technology === "dab" ? 0 : 1) - (b.technology === "dab" ? 0 : 1));
    return { areas, streams };
  }

  const TECH = { dab: ["DAB+", "digital · landesweit"], ukw: ["UKW", "analog · regional"] };

  function coverageBlock() {
    if (!(C.coverage_areas || []).length || !window.CoverageMap) return null;
    return h("div", { class: "coverage", "data-coverage": "" });
  }

  function refreshCoverage() {
    const hosts = document.querySelectorAll("[data-coverage]");
    if (!hosts.length) return;
    const { areas, streams } = selectedCoverage();
    hosts.forEach((host) => {
      const mapHost = h("div", { class: "coverage-mapbox" });
      const items = [
        ...areas.map((a) => h("li", {},
          h("span", { class: "tech tech-" + a.technology }, TECH[a.technology]?.[0] || a.technology),
          h("span", {}, h("b", {}, a.name), a.reach_text ? h("small", {}, " – " + a.reach_text) : null))),
        ...streams.map((name) => h("li", {},
          h("span", { class: "tech tech-stream" }, "Stream"),
          h("span", {}, h("b", {}, name), h("small", {}, " – online über App & Web, überall empfangbar")))),
      ];
      host.replaceChildren(
        h("h3", { class: "sub" }, "Ihr Sendegebiet"),
        mapHost,
        items.length ? h("ul", { class: "coverage-list" }, items)
          : h("p", { class: "muted" }, "Für diese Auswahl ist noch kein Sendegebiet hinterlegt."),
        h("div", { class: "coverage-legend" },
          h("span", {}, h("i", { class: "sw sw-dab" }), "DAB+ – ganzes Bundesland"),
          h("span", {}, h("i", { class: "sw sw-ukw" }), "UKW – rund um den Sender")),
        h("details", { class: "coverage-help" },
          h("summary", {}, "DAB+ oder UKW – was ist der Unterschied?"),
          h("p", {}, h("b", {}, "UKW"), " ist das klassische Radio. Jeder Sender strahlt von einem Standort aus – Ihr Spot ist " +
            "in der Stadt und der Umgebung rund um den Sender zu hören, z. B. im Großraum Wien."),
          h("p", {}, h("b", {}, "DAB+"), " ist digitales Radio. Ein Programm wird über ein landesweites Sendernetz " +
            "ausgestrahlt – Ihr Spot ist damit in ganz Österreich zu hören, in bester Qualität. Empfang mit DAB+-Radios, " +
            "die in fast allen neuen Autos und vielen Küchen- und Smart-Radios eingebaut sind."),
          h("p", {}, h("b", {}, "Beides zusammen"), " verbindet die starke regionale Reichweite von UKW mit der " +
            "österreichweiten Präsenz über DAB+.")),
        h("p", { class: "est" }, "Vereinfachte Darstellung – der tatsächliche Empfang hängt von Gelände und Empfangsgerät ab."),
      );
      CoverageMap.render(mapHost, areas);
    });
  }

  function dropStudioAddons() {
    if (!studioActive()) C.addons.filter((a) => a.requires_studio).forEach((a) => state.addonIds.delete(a.id));
  }

  function packageCards() {
    const seconds = byId(C.spot_lengths, state.lengthId).seconds;
    return h("div", { class: "packages" }, C.packages.map((p) => {
      const fits = packageFits(p);
      const sel = fits && p.id === state.packageId;
      const lines = (p.description || "").split("\n").map((l) => l.trim()).filter(Boolean);
      return h("div", { class: "voice option package" + (sel ? " sel" : "") + (fits ? "" : " disabled"),
        role: "button", tabindex: fits ? "0" : "-1", "aria-disabled": fits ? "false" : "true", "aria-pressed": sel ? "true" : "false",
        onclick: () => { if (!fits) return; state.packageId = p.id; dropStudioAddons(); render(); scheduleQuote(); },
        onkeydown: (e) => { if (fits && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); e.currentTarget.click(); } } },
        h("div", { class: "package-head" },
          h("span", { class: "package-radio", "aria-hidden": "true" }),
          h("span", { class: "voice-name" }, p.name, p.badge ? h("span", { class: "voice-badge" }, p.badge) : null),
          h("span", { class: "package-price" }, money(p.price_cent), h("small", {}, "netto pauschal"))),
        lines.length ? h("div", { class: "package-lines" }, lines.join(" · ")) : null,
        fits ? null : h("div", { class: "voice-tag" }, `Nur für Spots bis ${p.max_seconds} Sek. – Ihr Spot hat ${seconds} Sek.`));
    }));
  }

  function stepBuchung() {
    const newItem = () => ({ station_id: C.stations[0].id, time_slot_id: C.time_slots[0].id, spots: 20 });
    const option = (studio, title, tag, badge) => {
      const sel = state.studio === studio;
      return h("div", { class: "voice option" + (sel ? " sel" : ""), role: "button", tabindex: "0",
        onclick: () => {
          state.studio = studio;
          dropStudioAddons();
          render(); scheduleQuote();
        } },
        h("div", { class: "voice-top" },
          h("div", {}, h("div", { class: "voice-name" }, title), h("div", { class: "voice-tag" }, tag)),
          h("div", { class: "voice-badge" }, badge)));
    };
    const rows = state.items.map((item, idx) => h("div", { class: "booking-row" },
      field("Sender / Stream", stationSelect(item)),
      field("Zeitschiene", select(C.time_slots, item.time_slot_id, (id) => { item.time_slot_id = id; scheduleQuote(); },
        (t) => t.start_time ? `${t.name} (${t.start_time}–${t.end_time})` : t.name)),
      field("Ausstrahlungen", h("input", { type: "number", min: 1, max: 10000, value: item.spots,
        oninput: (e) => { item.spots = Math.max(1, parseInt(e.target.value, 10) || 1); scheduleQuote(); } })),
      h("button", { type: "button", class: "btn small ghost", title: "Entfernen", disabled: state.items.length === 1,
        onclick: () => { state.items.splice(idx, 1); render(); scheduleQuote(); } }, "×"),
    ));
    const pkg = selectedPackage();
    const modes = [{ id: "package", name: "Komplettpaket" }, { id: "individual", name: "Individuell" }];
    const individual = [
      rows,
      h("div", { class: "gen-row" }, h("button", { type: "button", class: "btn small ghost",
        onclick: () => { state.items.push(newItem()); render(); scheduleQuote(); } }, "+ Weiteren Sender / Stream")),
    ];
    const extras = visibleAddons().length ? field("Extras", h("div", { class: "checks" }, visibleAddons().map((a) => h("label", { class: "check" },
      h("input", { type: "checkbox", checked: state.addonIds.has(a.id), onchange: (e) => {
        e.target.checked ? state.addonIds.add(a.id) : state.addonIds.delete(a.id); scheduleQuote();
      } }),
      h("span", {}, `${a.name} – ${money(a.price_cent)}`, a.description ? h("small", {}, a.description) : null))))) : null;
    return [
      h("h2", {}, "Spot & Buchung"),
      h("p", { class: "hint" }, "Ihr Spot läuft im Radio oder in den Streams der Energy-Gruppe. Text und Hörbeispiel sind kostenlos — Sie zahlen nur die Schaltung und optional den Studiospot."),
      pkg?.includes_studio
        ? field("Ihr Spot", h("div", { class: "voices spot-choice" }, h("div", { class: "voice option sel" },
            h("div", { class: "voice-top" },
              h("div", {}, h("div", { class: "voice-name" }, "Studiospot mit echtem Sprecher"),
                h("div", { class: "voice-tag" }, "Professionell im Studio produziert, zur Freigabe vor Ausstrahlung")),
              h("div", { class: "voice-badge" }, "im Paket inklusive")))))
        : field("Ihr Spot", h("div", { class: "voices spot-choice" },
            option(false, "Spot-Text & Hörbeispiel", "So wie konfiguriert", "gratis"),
            option(true, "Studiospot mit echtem Sprecher", "Professionell im Studio produziert, zur Freigabe vor Ausstrahlung",
              money(C.studio_price_cent) + " netto"))),
      h("div", { class: "booking-layout" + (coverageBlock() ? "" : " no-map") },
        h("div", { class: "booking-main" },
          h("h3", { class: "sub" }, "Schaltung"),
          C.packages.length ? h("div", { class: "booking-mode" }, chips(modes, state.bookingMode, (mode) => {
            state.bookingMode = mode;
            if (mode === "package" && !packageFits(byId(C.packages, state.packageId))) {
              state.packageId = C.packages.find(packageFits)?.id ?? null;
            }
            dropStudioAddons(); render(); scheduleQuote();
          })) : null,
          state.bookingMode === "package" ? packageCards() : individual,
          extras),
        coverageBlock() ? h("div", { class: "booking-side" }, coverageBlock()) : null,
        h("div", { class: "booking-price" },
          h("div", { class: "summary-box", "data-price": "" }, priceBlock()),
          h("p", { class: "est" }, "Rechnungsland und UID-Nummer geben Sie im letzten Schritt an."))),
    ];
  }

  const VAT_ID_EXAMPLES = { AT: "ATU12345678", DE: "DE123456789", CH: "CHE-123.456.789 MWST", GR: "EL123456789" };
  function countryField() {
    const current = C.countries.find((c) => c.code === state.country);
    const countries = field("Land *", h("select", {
      autocomplete: "country",
      onchange: (e) => { state.country = e.target.value; render(); scheduleQuote(); },
    }, C.countries.map((c) => h("option", { value: c.code, selected: c.code === state.country }, c.name))));
    const vatId = field("UID-Nummer (optional)",
      input("vatId", { placeholder: VAT_ID_EXAMPLES[state.country] || `${state.country}…`, onInput: scheduleQuote }),
      current?.reverse_charge
        ? h("small", { class: "muted" }, "Mit gültiger UID-Nummer erhalten Sie eine Nettorechnung (Reverse Charge).")
        : null);
    return h("div", { class: "two-col" }, countries, vatId);
  }

  // ------------------------------------------------------------------ AGB & Datenschutz
  async function showLegal(key) {
    let text;
    try { text = await api(`/api/legal/${key}`); } catch (e) { text = { title: "Hinweis", body: e.message }; }
    const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    const overlay = h("div", { class: "legal-overlay", onclick: (e) => { if (e.target === overlay) close(); } },
      h("div", { class: "legal-dialog", role: "dialog", "aria-modal": "true", "aria-label": text.title },
        h("div", { class: "legal-head" },
          h("h2", {}, text.title),
          h("button", { type: "button", class: "btn small ghost", onclick: close, "aria-label": "Schließen" }, "✕")),
        h("div", { class: "legal-body" }, text.body),
        h("div", { class: "legal-foot" }, h("button", { type: "button", class: "btn", onclick: close }, "Schließen"))));
    document.addEventListener("keydown", onKey);
    root.append(overlay);
    overlay.querySelector(".legal-dialog button").focus();
  }

  function consentBox() {
    const link = (key, label) => h("a", { href: `/${key}`, class: "legal-link",
      onclick: (e) => { e.preventDefault(); showLegal(key); } }, label);
    const box = (key, ...label) => h("label", { class: "check" },
      h("input", { type: "checkbox", checked: state[key], onchange: (e) => { state[key] = e.target.checked; refreshNav(); } }),
      h("span", {}, ...label));
    return h("div", { class: "checks consent" },
      box("acceptTerms", "Ich akzeptiere die ", link("agb", "Allgemeinen Geschäftsbedingungen"), ". *"),
      box("acceptPrivacy", "Ich habe die ", link("datenschutz", "Datenschutzerklärung"),
        " gelesen und stimme der Verarbeitung meiner Daten zur Bearbeitung der Anfrage zu. *"));
  }

  function stepAnfrage() {
    if (state.company === null) state.company = state.firma;
    if (state.sent) {
      return [
        h("h2", {}, "Vielen Dank!"),
        h("div", { class: "confirm show" },
          `Danke, ${state.name}! Ihre Anfrage Nr. ${state.sent.id} ist bei onaircraft eingegangen — inklusive Skript, Stimmwahl und Kontaktdaten. `,
          studioActive() ? "Sie erhalten den Studiospot zur Freigabe, bevor er läuft." : "Wir melden uns in Kürze bei Ihnen."),
        h("div", { class: "gen-row", style: "margin-top:16px" },
          h("a", { class: "btn", href: API + state.sent.pdf_url, target: "_blank", rel: "noopener" },
            "Kostenaufstellung als PDF")),
      ];
    }
    const v = byId(C.voices, state.voiceId);
    const m = byId(C.music_styles, state.musicId);
    const occ = byId(C.occasions, state.occasionId);
    const len = byId(C.spot_lengths, state.lengthId);
    const kv = (label, value) => [h("b", {}, label + ": "), h("span", { class: "muted" }, value)];
    const promoInput = h("input", { type: "text", value: state.promo, placeholder: "optional",
      oninput: (e) => { state.promo = e.target.value; scheduleQuote(); } });
    return [
      h("h2", {}, "Zusammenfassung & Anfrage"),
      h("p", { class: "hint" }, "Unverbindliche Anfrage — wir melden uns mit allen Details, bevor etwas gebucht wird."),
      h("div", { class: "summary-box" },
        h("div", {}, kv("Anlass", occ?.name || "—"), " · ", kv("Länge", `${len.seconds} Sek.`)),
        h("div", {}, kv("Spot", studioActive() ? "Studiospot mit echtem Sprecher" : "Text & Hörbeispiel (gratis)")),
        h("div", {}, kv("Hörbeispiel-Stimme", v?.name || "—"), " · ", kv("Musik", m?.name || "keine")),
        h("div", {}, kv("Firma", state.firma || "—"), " · ",
          kv("Rechnungsland", C.countries.find((c) => c.code === state.country)?.name || state.country),
          state.vatId.trim() ? [" · ", kv("UID", state.vatId.trim().toUpperCase())] : null),
        h("div", {}, kv("Schaltung", selectedPackage() ? `Komplettpaket „${selectedPackage().name}“`
          : state.items.map((i) => `${i.spots}× ${byId(C.stations, i.station_id).name}`).join(", "))),
        selectedCoverage().areas.length
          ? h("div", {}, kv("Sendegebiet", selectedCoverage().areas.map((a) => a.name).join(" · "))) : null,
        h("div", { "data-price": "", style: "margin-top:12px" }, priceBlock()),
      ),
      h("div", { class: "promo-row" }, field("Gutscheincode", promoInput)),
      h("div", { style: "height:20px" }),
      field("Spot-Text (final)", input("script", { multiline: true, class: "script-box" })),
      demoBlock(),
      h("h3", { class: "sub" }, "Rechnungs- & Kontaktdaten"),
      h("div", { class: "two-col" },
        field("Name *", input("name", { autocomplete: "name" })),
        field("Firma", input("company", { autocomplete: "organization" }))),
      field("Straße & Hausnummer *", input("street", { autocomplete: "street-address" })),
      h("div", { class: "zip-city" },
        field("PLZ *", input("zip", { autocomplete: "postal-code" })),
        field("Ort *", input("city", { autocomplete: "address-level2" }))),
      countryField(),
      h("div", { class: "two-col" },
        field("Telefon *", input("phone", { type: "tel", autocomplete: "tel" })),
        field("E-Mail *", input("email", { type: "email", autocomplete: "email" }))),
      field("Nachricht (optional)", input("nachricht", { multiline: true, placeholder: "Wunschtermin, Sendedaten, Sonstiges" })),
      consentBox(),
      h("p", { class: "error-text", id: "sendError" }),
    ];
  }

  async function submit() {
    const errBox = document.getElementById("sendError");
    if (state.quote && !state.quote.error && !state.quote.meets_minimum_order) {
      errBox.textContent = "Der Mindestbestellwert ist noch nicht erreicht.";
      return;
    }
    btnNext.disabled = true;
    btnNext.textContent = "Wird gesendet …";
    try {
      const occ = byId(C.occasions, state.occasionId);
      state.sent = await api("/api/quote-requests", {
        configuration: configuration(),
        brief: {
          occasion: occ?.name || "", firma: state.firma, botschaft: state.botschaft, cta: state.cta,
          tonality: byId(C.tonalities, state.tonalityId)?.name || "",
          language_style: byId(C.language_styles, state.styleId)?.name || "",
          script: state.script,
        },
        customer_name: state.name, company: state.company ?? state.firma, email: state.email, phone: state.phone,
        accept_terms: state.acceptTerms, accept_privacy: state.acceptPrivacy,
        street: state.street, zip_code: state.zip, city: state.city,
        message: state.nachricht,
      });
      render();
    } catch (e) {
      errBox.textContent = e.status === 422 && /email/i.test(e.message)
        ? "Bitte eine gültige E-Mail-Adresse angeben." : e.message;
      btnNext.textContent = "Anfrage senden";
      refreshNav();
    }
  }

  // ------------------------------------------------------------------ Render
  function render() {
    renderDial();
    const builders = [stepAnlass, stepText, stepStimme, stepBuchung, stepAnfrage];
    stepHost.replaceChildren(h("div", { class: "step" }, builders[state.step]()));
    refreshCoverage();
    btnBack.style.visibility = state.step === 0 || state.sent ? "hidden" : "visible";
    btnNext.style.visibility = state.sent ? "hidden" : "visible";
    btnNext.textContent = state.step === STEPS.length - 1 ? "Anfrage senden" : "Weiter";
    refreshNav();
  }

  btnBack.addEventListener("click", () => { if (state.step > 0) goTo(state.step - 1); });
  btnNext.addEventListener("click", () => {
    if (!canAdvance()) return;
    if (state.step === STEPS.length - 1) submit();
    else goTo(state.step + 1);
  });

  // ------------------------------------------------------------------ Start
  (async () => {
    try {
      C = await api("/api/catalog");
    } catch (e) {
      stepHost.replaceChildren(h("div", { class: "step" }, h("p", { class: "error-text" }, "Konfigurator konnte nicht geladen werden: " + e.message)));
      btnNext.disabled = true;
      return;
    }
    if (!C.spot_lengths.length || !C.voices.length) {
      stepHost.replaceChildren(h("div", { class: "step" }, h("p", { class: "hint" }, "Aktuell sind keine Produkte buchbar.")));
      btnNext.disabled = true;
      return;
    }
    const first = (list) => list[0]?.id ?? null;
    state.occasionId = first(C.occasions);
    state.lengthId = (C.spot_lengths.find((l) => l.seconds === 20) || C.spot_lengths[0]).id;
    state.tonalityId = first(C.tonalities);
    state.styleId = first(C.language_styles);
    state.voiceId = first(C.voices);
    state.musicId = first(C.music_styles);
    if (!C.stations.length || !C.time_slots.length) {
      stepHost.replaceChildren(h("div", { class: "step" }, h("p", { class: "hint" }, "Aktuell sind keine Sender buchbar.")));
      btnNext.disabled = true;
      return;
    }
    state.items.push({ station_id: C.stations[0].id, time_slot_id: C.time_slots[0].id, spots: 20 });
    C.packages = C.packages || [];
    if (C.packages.length) {  // Komplettpakete zuerst anbieten
      state.bookingMode = "package";
      state.packageId = C.packages.find(packageFits)?.id ?? C.packages[0].id;
    }
    render();
    updateQuote();
  })();
})();
