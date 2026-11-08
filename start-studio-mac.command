#!/bin/bash
# =============================================================================
#  Radiospot-Studio starten (Doppelklick im Finder) – läuft unabhängig vom
#  Konfigurator auf Port 8001. Terminal-Fenster offen lassen, beenden mit Ctrl + C.
#  Voraussetzung: einmal install-mac.command ausgeführt (legt .venv und .env an).
# =============================================================================
SRC="$0"
[ -L "$SRC" ] && SRC="$(readlink "$SRC")"
cd "$(dirname "$SRC")" || exit 1
VPY="$(pwd)/.venv/bin/python"
if [ ! -x "$VPY" ]; then
  echo "Bitte zuerst install-mac.command ausführen."
  read -r -p "Enter zum Schließen … " _
  exit 1
fi
PORT="${STUDIO_PORT:-8001}"
echo "Radiospot-Studio: http://127.0.0.1:$PORT"
echo "Beim ersten Start ohne STUDIO_ADMIN_PASSWORD steht das Admin-Passwort unten im Terminal."
echo ""
( sleep 2; command -v open >/dev/null && open "http://127.0.0.1:$PORT/" ) &
RUN=()
command -v caffeinate >/dev/null 2>&1 && RUN=(caffeinate -i)
"${RUN[@]}" "$VPY" -m uvicorn studio.main:app --host 127.0.0.1 --port "$PORT"
