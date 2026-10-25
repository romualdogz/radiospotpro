#!/bin/bash
# =============================================================================
#  Radiospot-Konfigurator starten (Doppelklick im Finder)
#
#  Öffnet den Konfigurator im Browser. Das Terminal-Fenster muss offen bleiben,
#  solange der Server laufen soll – beenden mit Ctrl + C oder Fenster schließen.
#  Im Netzwerk erreichbar (Handy, andere Rechner): start-mac-netzwerk.command
# =============================================================================
SRC="$0"
[ -L "$SRC" ] && SRC="$(readlink "$SRC")"   # Aufruf über die Verknüpfung auf dem Schreibtisch
cd "$(dirname "$SRC")" || exit 1
DIR="$(pwd)"
VPY="$DIR/.venv/bin/python"

pause_exit() {
  printf '\nZum Schließen Enter drücken … '
  read -r _ || true
  exit "$1"
}

if [ ! -x "$VPY" ] || [ ! -f "$DIR/.env" ]; then
  echo "Radiospot ist noch nicht installiert."
  echo "Bitte zuerst im Ordner $DIR doppelt auf install-mac.command klicken."
  pause_exit 1
fi

HOST="127.0.0.1"
[ "${RADIOSPOT_NETWORK:-0}" = "1" ] && HOST="0.0.0.0"
PORT="${PORT:-8000}"

is_radiospot() {  # läuft auf dem Port bereits ein Radiospot-Server?
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$1/theme.css" 2>/dev/null)" = "200" ]
}
port_busy() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    curl -s -o /dev/null "http://127.0.0.1:$1/" 2>/dev/null
  fi
}
open_url() {
  if command -v open >/dev/null 2>&1; then open "$1"; else echo "Im Browser öffnen: $1"; fi
}
lan_ip() {  # IP-Adresse des Macs im WLAN/LAN (Schnittstelle der Standardroute, sonst en0/en1)
  local iface ip
  command -v ipconfig >/dev/null 2>&1 || return 1
  iface="$(route -n get default 2>/dev/null | awk '/interface:/ {print $2}')"
  for i in $iface en0 en1 en2; do
    ip="$(ipconfig getifaddr "$i" 2>/dev/null)" && [ -n "$ip" ] && { echo "$ip"; return 0; }
  done
  return 1
}
reachable() {  # antwortet der Server unter http://IP:PORT ?
  [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://$1:$2/theme.css" 2>/dev/null)" = "200" ]
}

IP=""
[ "$HOST" = "0.0.0.0" ] && IP="$(lan_ip)"

if is_radiospot "$PORT"; then
  if [ "$HOST" = "127.0.0.1" ]; then
    echo "Radiospot läuft bereits – der Browser wird geöffnet."
    open_url "http://127.0.0.1:$PORT/"
    exit 0
  fi
  if [ -n "$IP" ] && reachable "$IP" "$PORT"; then
    echo "Radiospot läuft bereits und ist im Netzwerk erreichbar:"
    echo "Konfigurator:  http://$IP:$PORT"
    echo "Admin:         http://$IP:$PORT/admin"
    pause_exit 0
  fi
  echo "Radiospot läuft bereits in einem anderen Terminal-Fenster – aber NUR auf diesem Mac."
  echo ""
  echo "Bitte das andere Fenster schließen (dort Ctrl + C drücken)"
  echo "und danach start-mac-netzwerk.command erneut starten."
  pause_exit 1
fi
while port_busy "$PORT"; do
  PORT=$((PORT + 1))
done

# --- Mac-Firewall: blockiert nicht signierte Programme wie Python oft ohne Rückfrage
FW="${RADIOSPOT_FW:-/usr/libexec/ApplicationFirewall/socketfilterfw}"
if [ "$HOST" = "0.0.0.0" ] && [ -x "$FW" ]; then
  REALPY="$("$VPY" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
  FW_STATE="$("$FW" --getglobalstate 2>/dev/null)"
  FW_BLOCKALL="$("$FW" --getblockall 2>/dev/null)"
  if echo "$FW_STATE" | grep -q "State = 2" \
     || { echo "$FW_BLOCKALL" | grep -qi "enabled" && ! echo "$FW_BLOCKALL" | grep -qi "disabled"; }; then
    echo "Die Mac-Firewall blockiert ALLE eingehenden Verbindungen – so ist der Server im WLAN nicht erreichbar."
    echo "Bitte ausschalten: Systemeinstellungen → Netzwerk → Firewall → Optionen →"
    echo "„Alle eingehenden Verbindungen blockieren“ ausschalten. Danach dieses Skript erneut starten."
    pause_exit 1
  elif echo "$FW_STATE" | grep -qi "enabled"; then
    if ! "$FW" --getappblocked "$REALPY" 2>/dev/null | grep -qi "permitted"; then
      echo "Die Mac-Firewall ist eingeschaltet und Python ist dort noch nicht freigegeben."
      echo "Ohne Freigabe erreichen Handy und andere Rechner den Server nicht."
      printf 'Python jetzt in der Firewall freigeben? (fragt nach deinem Mac-Passwort) [J/n] '
      read -r answer || answer=""
      case "$answer" in
        [Nn]*) echo "Nicht freigegeben – der Server läuft trotzdem, ist aber evtl. nur am Mac erreichbar." ;;
        *)
          echo "Mac-Passwort eingeben (beim Tippen ist nichts zu sehen):"
          if sudo "$FW" --add "$REALPY" >/dev/null && sudo "$FW" --unblockapp "$REALPY" >/dev/null; then
            echo "✔ Python ist in der Firewall freigegeben."
          else
            echo "Freigabe hat nicht geklappt. Von Hand: Systemeinstellungen → Netzwerk → Firewall → Optionen →"
            echo "„+“ → Programm: $REALPY → „Eingehende Verbindungen erlauben“."
          fi ;;
      esac
      echo ""
    fi
  fi
fi

clear 2>/dev/null || true
echo "Radiospot-Konfigurator"
echo "======================"
echo "Konfigurator:  http://127.0.0.1:$PORT"
echo "Admin:         http://127.0.0.1:$PORT/admin"
if [ "$HOST" = "0.0.0.0" ]; then
  echo ""
  if [ -n "$IP" ]; then
    echo "Im Netzwerk (Handy, andere Rechner im selben WLAN) – genau so eintippen, mit http://"
    echo "Konfigurator:  http://$IP:$PORT"
    echo "Admin:         http://$IP:$PORT/admin"
    echo "(Fragt macOS, ob Python Verbindungen annehmen darf: „Erlauben“ klicken.)"
  else
    echo "Keine WLAN-Adresse gefunden – ist der Mac mit dem WLAN verbunden?"
    echo "Die Adresse steht unter Systemeinstellungen → WLAN → Details → IP-Adresse."
  fi
fi
echo ""
echo "Dieses Fenster offen lassen. Beenden: Ctrl + C oder Fenster schließen."
echo ""

# Browser öffnen, sobald der Server antwortet – im Netzwerkmodus auch die WLAN-Adresse prüfen
(
  for _ in $(seq 1 60); do
    if is_radiospot "$PORT"; then
      open_url "http://127.0.0.1:$PORT/"
      if [ -n "$IP" ]; then
        sleep 1
        if reachable "$IP" "$PORT"; then
          echo ""
          echo "✔ Bereit im Netzwerk: http://$IP:$PORT  (vom Mac aus geprüft)"
          echo "  Klappt es am Handy trotzdem nicht: Handy im SELBEN WLAN (nicht Gäste-WLAN, mobile Daten und VPN aus),"
          echo "  Adresse mit http:// eintippen. Erscheint hier beim Aufruf keine Zeile mit der Handy-Adresse,"
          echo "  kommt die Anfrage nicht am Mac an (Router-Einstellung, Gastzugang, VPN oder Sicherheits-Software)."
          echo ""
        else
          echo ""
          echo "! Der Server antwortet nicht unter http://$IP:$PORT – bitte die Meldungen oben prüfen."
          echo ""
        fi
      fi
      exit 0
    fi
    sleep 0.5
  done
) &

# caffeinate: Mac schläft nicht ein, solange der Server läuft (Bildschirm darf aus)
RUN=()
command -v caffeinate >/dev/null 2>&1 && RUN=(caffeinate -i)
"${RUN[@]}" "$VPY" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
STATUS=$?
if [ "$STATUS" -ne 0 ] && [ "$STATUS" -ne 130 ]; then
  echo ""
  echo "Der Server wurde mit einem Fehler beendet (Code $STATUS) – Meldungen siehe oben."
  pause_exit "$STATUS"
fi
