#!/bin/bash
# =============================================================================
#  Radiospot-Konfigurator – Installation auf dem Mac
#
#  Beim ersten Mal im Terminal starten:  bash  (Leerzeichen) und diese Datei ins Fenster ziehen, Enter.
#  (Ein Doppelklick wird von macOS bei Dateien aus dem Internet blockiert – danach geht er.)
#
#  Was passiert:
#   1. passendes Python suchen (3.10 oder neuer) – falls keines da ist, wird es
#      ohne Admin-Passwort in den eigenen Benutzerordner geladen (über „uv“)
#   2. eigene Python-Umgebung im Projektordner anlegen (.venv) und Pakete laden
#   3. .env anlegen (sicherer SECRET_KEY, Admin-Passwort) bzw. bei Updates nur
#      fehlende Einträge ergänzen – bestehende Werte bleiben unverändert
#   4. optional API-Keys und E-Mail-Versand abfragen
#   5. Selbsttest und Verknüpfung „Radiospot starten“ auf dem Schreibtisch
#
#  Erneut ausführen ist jederzeit gefahrlos (z. B. nach einem Update).
#  Datenbank (radiospot.db), Musik und Logos werden nie gelöscht.
#  Optionen:  --yes  ohne Rückfragen (Standardantworten)
# =============================================================================
set -u

cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"
LOG="$DIR/install.log"
VENV="$DIR/.venv"
VPY="$VENV/bin/python"

INTERACTIVE=1
[ -t 0 ] || INTERACTIVE=0
[ "${RADIOSPOT_INTERACTIVE:-}" = "1" ] && INTERACTIVE=1
for arg in "$@"; do
  case "$arg" in
    -y|--yes) INTERACTIVE=0 ;;
  esac
done

: > "$LOG"
exec 3>&1 4>&2                      # ursprüngliche Ausgabe merken (für den Start am Ende)
exec > >(tee -a "$LOG") 2>&1

if [ -t 1 ] || [ "$INTERACTIVE" = "1" ]; then
  B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; N=""
fi

step() { printf '\n%s▶ %s%s\n' "$B" "$1" "$N"; }
ok()   { printf '  %s✔%s %s\n' "$G" "$N" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
info() { printf '    %s\n' "$1"; }

finish() {
  if [ "$INTERACTIVE" = "1" ]; then
    printf '\nZum Schließen Enter drücken … '
    read -r _ || true
  fi
  exit "$1"
}

fail() {
  printf '\n  %s✘ %s%s\n' "$R" "$1" "$N"
  shift
  for line in "$@"; do info "$line"; done
  info ""
  info "Das vollständige Protokoll steht in: $LOG"
  finish 1
}

# ask "Frage" "Standard" → Antwort in $REPLY
ask() {
  REPLY="$2"
  [ "$INTERACTIVE" = "1" ] || return 0
  printf '  %s ' "$1"
  read -r REPLY || REPLY=""
  [ -n "$REPLY" ] || REPLY="$2"
}

# ask_secret "Frage" → Antwort in $REPLY (Eingabe wird nicht angezeigt)
ask_secret() {
  REPLY=""
  [ "$INTERACTIVE" = "1" ] || return 0
  printf '  %s ' "$1"
  if [ -t 0 ]; then
    read -r -s REPLY || REPLY=""
    printf '\n'
  else
    read -r REPLY || REPLY=""
  fi
}

yes_no() {  # yes_no "Frage" J|N → Rückgabe 0 = ja
  local default="$2" hint="[J/n]"
  [ "$default" = "N" ] && hint="[j/N]"
  ask "$1 $hint" "$default"
  case "$REPLY" in
    [JjYy]*) return 0 ;;
    *) return 1 ;;
  esac
}

mask() {  # Key gekürzt anzeigen, damit man sieht, ob das Einfügen geklappt hat
  local v="$1"
  if [ "${#v}" -gt 12 ]; then printf '%s…%s' "${v:0:6}" "${v: -4}"; else printf '(%s Zeichen)' "${#v}"; fi
}

env_get() { "$VPY" "$DIR/scripts/mac_env.py" get "$1"; }
env_set() { "$VPY" "$DIR/scripts/mac_env.py" set "$@"; }

printf '%s\n' "${B}Radiospot-Konfigurator – Installation${N}"
printf 'Ordner: %s\n' "$DIR"

if [ "$(uname -s)" != "Darwin" ]; then
  warn "Dieses Skript ist für macOS gedacht – es läuft trotzdem weiter."
fi
[ -f "$DIR/requirements.txt" ] && [ -d "$DIR/app" ] \
  || fail "Hier fehlt der Projektordner." "Bitte das Skript im entpackten Ordner „radiospot“ starten."

# Download-Sperre („aus dem Internet geladen“) für die Projektdateien aufheben,
# damit „Radiospot starten“ später ohne Rückfrage per Doppelklick geht
if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$DIR" 2>/dev/null || true
fi
chmod +x "$DIR"/*.command 2>/dev/null || true

# ----------------------------------------------------------------------------- 1. Python
step "1/5  Python suchen"

py_ok() {  # Python 3.10 oder neuer?
  "$1" -c 'import sys, venv; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
  local c p
  for c in python3.13 python3.12 python3.11 python3.14 python3.10 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3 python3; do
    p="$(command -v "$c" 2>/dev/null)" || continue
    # /usr/bin/python3 ohne Entwicklerwerkzeuge öffnet nur einen Installationsdialog – überspringen
    if [ "$p" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then
      continue
    fi
    if py_ok "$p"; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

find_uv() {
  local c
  for c in uv "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if command -v "$c" >/dev/null 2>&1; then
      command -v "$c"
      return 0
    fi
  done
  return 1
}

PY=""
if [ -x "$VPY" ] && py_ok "$VPY"; then
  ok "Vorhandene Umgebung .venv wird weiterverwendet ($("$VPY" --version 2>&1))"
else
  PY="$(find_python)" || PY=""
  if [ -n "$PY" ]; then
    ok "Gefunden: $("$PY" --version 2>&1) ($PY)"
  else
    warn "Kein passendes Python (3.10 oder neuer) gefunden – wird jetzt geladen."
    info "Das geschieht nur in deinem Benutzerordner, ohne Admin-Passwort (Werkzeug „uv“ von astral.sh)."
    UV="$(find_uv)" || UV=""
    if [ -z "$UV" ]; then
      command -v curl >/dev/null 2>&1 || fail "curl fehlt – ohne curl kann Python nicht geladen werden."
      UV_INSTALLER="$(mktemp -t uv-install.XXXXXX)"
      # erst herunterladen, dann ausführen – so wird ein Download-Fehler sicher erkannt
      if ! curl -LsSf https://astral.sh/uv/install.sh -o "$UV_INSTALLER"; then
        rm -f "$UV_INSTALLER"
        fail "uv konnte nicht geladen werden." "Bitte Internetverbindung prüfen und das Skript erneut starten." \
             "Alternativ Python von https://www.python.org/downloads/macos/ installieren und erneut starten."
      fi
      env UV_NO_MODIFY_PATH=1 sh "$UV_INSTALLER" || { rm -f "$UV_INSTALLER"; fail "uv konnte nicht installiert werden."; }
      rm -f "$UV_INSTALLER"
      UV="$(find_uv)" || fail "uv wurde installiert, aber nicht gefunden." "Bitte das Skript erneut starten."
    fi
    # --no-bin: kein zusätzliches „python3.12“ im Benutzerordner (ältere uv-Versionen kennen das nicht)
    "$UV" python install --no-bin 3.12 2>/dev/null || "$UV" python install 3.12 \
      || fail "Python 3.12 konnte nicht geladen werden." "Bitte Internetverbindung prüfen."
    PY="$("$UV" python find 3.12)" || fail "Python 3.12 wurde geladen, aber nicht gefunden."
    py_ok "$PY" || fail "Das geladene Python funktioniert nicht: $PY"
    ok "Python geladen: $("$PY" --version 2>&1)"
  fi
fi

# ----------------------------------------------------------------------------- 2. Umgebung & Pakete
step "2/5  Python-Umgebung und Pakete"
if [ -n "$PY" ]; then
  if [ -d "$VENV" ]; then
    warn "Die alte Umgebung .venv passt nicht mehr und wird neu angelegt."
    rm -rf "$VENV"
  fi
  "$PY" -m venv "$VENV" || fail "Die Python-Umgebung (.venv) konnte nicht angelegt werden."
  ok "Umgebung angelegt: .venv"
fi

info "Pakete werden geladen – das dauert beim ersten Mal 1–3 Minuten …"
"$VPY" -m pip install --upgrade pip --quiet --disable-pip-version-check \
  || fail "pip konnte nicht aktualisiert werden." "Bitte Internetverbindung prüfen und erneut starten."
if ! "$VPY" -m pip install -r "$DIR/requirements.txt" --quiet --disable-pip-version-check; then
  if grep -qiE "xcrun|clang|compiler|command line tools" "$LOG"; then
    fail "Ein Paket musste übersetzt werden, dafür fehlen die Apple-Entwicklerwerkzeuge." \
         "Bitte im Terminal  xcode-select --install  ausführen, die Installation abwarten" \
         "und dieses Skript danach erneut starten."
  fi
  fail "Die Pakete konnten nicht installiert werden." "Bitte Internetverbindung prüfen und erneut starten."
fi
ok "Alle Pakete installiert"

# ----------------------------------------------------------------------------- 3. .env
step "3/5  Einstellungen (.env)"
HAD_DB=0
[ -f "$DIR/radiospot.db" ] && HAD_DB=1
RESULT="$("$VPY" "$DIR/scripts/mac_env.py" ensure)" || fail ".env konnte nicht angelegt werden."
case "$RESULT" in
  created)
    ok ".env neu angelegt (mit zufälligem SECRET_KEY und Admin-Passwort)" ;;
  updated:0)
    ok "Vorhandene .env bleibt unverändert" ;;
  updated:*)
    ok "Vorhandene .env bleibt erhalten – ${RESULT#updated:} neue Einträge am Ende ergänzt" ;;
esac

# ----------------------------------------------------------------------------- 4. Zugänge
step "4/5  API-Keys und E-Mail (Enter = später eintragen)"
if [ "$INTERACTIVE" != "1" ]; then
  info "Ohne Rückfragen – Keys können jederzeit in der Datei .env nachgetragen werden."
else
  if [ -z "$(env_get ANTHROPIC_API_KEY)" ]; then
    info "KI-Textvorschlag: Key von https://console.anthropic.com → API Keys (beginnt mit sk-ant-)"
    ask_secret "Anthropic-API-Key:"
    REPLY="$(printf '%s' "$REPLY" | tr -d '[:space:]')"
    [ -n "$REPLY" ] && env_set "ANTHROPIC_API_KEY=$REPLY" && ok "Anthropic-Key gespeichert ($(mask "$REPLY"))"
  else
    ok "Anthropic-Key ist schon eingetragen"
  fi

  if [ -z "$(env_get ELEVENLABS_API_KEY)" ]; then
    info "KI-Stimme: Key von https://elevenlabs.io → Profil → API Keys"
    ask_secret "ElevenLabs-API-Key:"
    REPLY="$(printf '%s' "$REPLY" | tr -d '[:space:]')"
    [ -n "$REPLY" ] && env_set "ELEVENLABS_API_KEY=$REPLY" && ok "ElevenLabs-Key gespeichert ($(mask "$REPLY"))"
  else
    ok "ElevenLabs-Key ist schon eingetragen"
  fi

  if [ -z "$(env_get SMTP_HOST)" ]; then
    info "E-Mail-Versand (PDF + Audiodateien einer Anfrage verschicken)"
    ask "Absender-Adresse (z. B. name@gmail.com):" ""
    MAIL="$REPLY"
    if [ -n "$MAIL" ]; then
      case "$MAIL" in
        *@gmail.com|*@googlemail.com)
          SMTP_HOST="smtp.gmail.com"; SMTP_PORT="587"; SMTP_SECURITY="starttls"
          info "Gmail braucht ein App-Passwort: https://myaccount.google.com/apppasswords"
          info "(dafür muss die Bestätigung in zwei Schritten aktiv sein)" ;;
        *)
          ask "SMTP-Server deines Mail-Anbieters (z. B. smtp.world4you.com):" ""
          SMTP_HOST="$REPLY"
          ask "Port [587]:" "587"
          SMTP_PORT="$REPLY"
          SMTP_SECURITY="starttls"
          [ "$SMTP_PORT" = "465" ] && SMTP_SECURITY="ssl" ;;
      esac
      ask_secret "Passwort für $MAIL:"
      # Gmail zeigt App-Passwörter mit Leerzeichen an („abcd efgh ijkl mnop“) – die gehören nicht dazu
      [ "$SMTP_HOST" = "smtp.gmail.com" ] && REPLY="$(printf '%s' "$REPLY" | tr -d '[:space:]')"
      if [ -n "$SMTP_HOST" ] && [ -n "$REPLY" ]; then
        env_set "SMTP_HOST=$SMTP_HOST" "SMTP_PORT=$SMTP_PORT" "SMTP_SECURITY=$SMTP_SECURITY" \
                "SMTP_USER=$MAIL" "SMTP_PASSWORD=$REPLY" "SMTP_FROM=$MAIL"
        ok "E-Mail-Versand eingerichtet ($SMTP_HOST)"
      else
        warn "Unvollständig – E-Mail-Versand bitte später in der .env eintragen."
      fi
    fi
  else
    ok "E-Mail-Versand ist schon eingerichtet"
  fi
fi

# ----------------------------------------------------------------------------- 5. Test & Verknüpfung
step "5/5  Selbsttest"
if ! (cd "$DIR" && "$VPY" -c "import app.main" >/dev/null); then
  fail "Der Selbsttest ist fehlgeschlagen." "Bitte das Protokoll an den Entwickler schicken: $LOG"
fi
ok "Der Konfigurator lässt sich starten"

DESKTOP="$HOME/Desktop"

# desktop_link "Name auf dem Schreibtisch" Skript – legt eine Verknüpfung an bzw. setzt sie auf diesen Ordner
desktop_link() {
  local name="$1" target="$DIR/$2" link="$DESKTOP/$1.command"
  [ -d "$DESKTOP" ] && [ -f "$target" ] || return 0
  if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
    ok "Verknüpfung „$name“ auf dem Schreibtisch ist vorhanden"
  elif yes_no "Verknüpfung „$name“ auf dem Schreibtisch anlegen?" J; then
    rm -f "$link"
    ln -s "$target" "$link" && ok "Verknüpfung „$name“ auf dem Schreibtisch angelegt"
  fi
}
desktop_link "Radiospot starten" start-mac.command
desktop_link "Radiospot im WLAN starten" start-mac-netzwerk.command

# ----------------------------------------------------------------------------- Fertig
printf '\n%s%s✔ Installation abgeschlossen%s\n\n' "$B" "$G" "$N"
info "Starten:   Doppelklick auf „Radiospot starten“ (Schreibtisch) oder start-mac.command"
info "Im WLAN (z. B. fürs Handy):  „Radiospot im WLAN starten“ (Schreibtisch) oder start-mac-netzwerk.command"
info "Konfigurator:  http://127.0.0.1:8000"
info "Admin:         http://127.0.0.1:8000/admin"
if [ "$HAD_DB" = "1" ]; then
  info "Admin-Login:   dein bisheriger Benutzer und dein bisheriges Passwort (unverändert)"
else
  info "Admin-Login:   Benutzer $(env_get ADMIN_USERNAME)  ·  Passwort $(env_get ADMIN_PASSWORD)"
  info "               (steht auch in der Datei .env – bitte nach dem ersten Login unter „Mein Konto“ ändern)"
fi
info ""
info "API-Keys und E-Mail kannst du jederzeit in der Datei .env ändern (danach Server neu starten)."
info "Die .env ist im Finder versteckt: im Projektordner Cmd + Shift + Punkt drücken."

if [ "$INTERACTIVE" = "1" ] && [ -f "$DIR/start-mac.command" ]; then
  if yes_no "Radiospot jetzt starten?" J; then
    exec 1>&3 2>&4                  # Server-Meldungen nicht ins Installationsprotokoll
    exec "$DIR/start-mac.command"
  fi
fi
finish 0
