// Radiospot-Studio – Arbeitsfläche (Schritt 1: Zeitleiste zeichnen, noch ohne Audio)
(() => {
  const ruler = document.getElementById("ruler");
  const select = document.getElementById("spot-length");
  if (!ruler || !select) return;

  function drawRuler() {
    const seconds = Number(select.value) || 30;
    ruler.replaceChildren();
    ruler.style.setProperty("--seconds", seconds);
    const step = seconds <= 20 ? 1 : seconds <= 45 ? 5 : 10;
    for (let s = 0; s <= seconds; s += 1) {
      const tick = document.createElement("span");
      tick.className = s % step === 0 ? "tick major" : "tick";
      tick.style.left = `${(s / seconds) * 100}%`;
      if (s % step === 0) tick.dataset.label = `${s}s`;
      ruler.appendChild(tick);
    }
  }
  select.addEventListener("change", drawRuler);
  drawRuler();
})();
