#!/bin/bash
# =============================================================================
#  Admin-Zugang zurücksetzen (Doppelklick im Finder oder im Terminal)
#
#  Für den Konfigurator (/admin) oder das Radiospot-Studio: neues Passwort setzen,
#  Konto entsperren, Zwei-Faktor-Anmeldung abschalten. Fehlt das Konto, wird es angelegt.
#  Weitere Optionen:  bash admin-zuruecksetzen.command --help
# =============================================================================
SRC="$0"
[ -L "$SRC" ] && SRC="$(readlink "$SRC")"
cd "$(dirname "$SRC")" || exit 1
VPY="$(pwd)/.venv/bin/python"
if [ ! -x "$VPY" ]; then
  echo "Radiospot ist noch nicht installiert – bitte zuerst install-mac.command ausführen."
  read -r -p "Enter zum Schließen … " _
  exit 1
fi
"$VPY" scripts/admin_reset.py "$@"
STATUS=$?
if [ -t 0 ] && [ $# -eq 0 ]; then
  echo ""
  read -r -p "Enter zum Schließen … " _
fi
exit $STATUS
