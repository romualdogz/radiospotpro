#!/bin/bash
# Radiospot starten und im lokalen Netzwerk erreichbar machen (Handy, andere Rechner im selben WLAN).
# Nur in vertrauenswürdigen Netzen verwenden – alle Geräte im Netz sehen dann auch die Admin-Anmeldung.
SRC="$0"
[ -L "$SRC" ] && SRC="$(readlink "$SRC")"
RADIOSPOT_NETWORK=1 exec "$(dirname "$SRC")/start-mac.command"
