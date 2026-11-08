# Radiospot-Konfigurator (FastAPI)

> **Radiospot-Studio (neu, eigenständig):** Profi-Mehrspur-Editor für eingeladene Nutzer – siehe
> [Radiospot-Studio](#radiospot-studio) weiter unten. Läuft als eigener Server mit eigener Datenbank.

Bestellformular für Radiospots (Design und Ablauf nach der onaircraft-Vorlage) mit Backend:
Preisberechnung, Rabatte, Werbeabgabe, KI-Textvorschlag, Angebotsanfragen und eine
Admin-Oberfläche zum Pflegen aller Produkte.

**Ablauf im Konfigurator:** Anlass & Länge → Text (optional per KI) → Stimme & Musik (Hörbeispiel)
→ Spot & Buchung (Schaltung im Radio oder in den Streams der Energy-Gruppe – Pflicht)
→ Zusammenfassung, Rechnungs- & Kontaktdaten (Name, Firma, Adresse, Telefon, E-Mail) → Anfrage.

**Preismodell:** Text und Hörbeispiel sind gratis. Kosten entstehen nur durch
- die **Schaltung** (Sender × Zeitschiene × Ausstrahlungen) und
- optional den **Studiospot mit echtem Sprecher** (Pauschalpreis, Standard 349 € netto, unter *Einstellungen*).

**MwSt.:** Der Kunde wählt sein Rechnungsland aus einem Dropdown (ohne MwSt.-Angabe). Der Satz je Land steht im
Admin unter *Länder* (Standard: Österreich 20 %, Deutschland 19 %, übrige Länder 20 %) und erscheint in Kostenaufstellung und PDF.
Optional gibt er seine UID-Nummer an (Formatprüfung: `ATU12345678` bzw. `DE123456789`).
**Deutschland + UID → Nettorechnung** (0 % MwSt., Reverse Charge) – im Admin und PDF entsprechend gekennzeichnet.
Die Gültigkeit der UID bitte vor der Rechnungsstellung über VIES prüfen.

**PDF:** Zu jeder Anfrage gibt es eine PDF-Kostenaufstellung – für den Kunden als Download-Link direkt
nach dem Absenden (signiert, nur mit gültigem Link abrufbar), im Admin unter *Anfragen → PDF*.
Die Fußzeile (Adresse, UID …) stellst du unter *Einstellungen → Firmenangaben für das PDF* ein.

**Admin-Login:** Zugangsdaten aus `.env` (`ADMIN_USERNAME` / `ADMIN_PASSWORD`), ohne `.env`
`admin` / `admin`. Der Admin wird nur beim ersten Start angelegt – danach Passwort unter
*Mein Konto* ändern.

**Benutzer & Rollen** (Admin → *Benutzer*): weitere Zugänge anlegen, Rolle ändern, Passwort zurücksetzen, löschen.

| Rolle | Darf |
|---|---|
| **Administrator** | alles, inkl. Anfragen, Design, Rechtstexte, Einstellungen und Benutzer |
| **Verkaufsleitung** | nur Sender & Streams (Sekundenpreise), Zeitschienen, Komplettpakete, Zusatzleistungen, Rabatte, Länder & MwSt., *Preis-Einstellungen* (Studiospot, Werbeabgabe, Mindestbestellwert) und das Glücksrad – alles andere ist gesperrt, auch per direktem Link und über die JSON-API |

Jeder Benutzer kann unter *Mein Konto* sein eigenes Passwort ändern. Der letzte Administrator kann nicht
gelöscht oder herabgestuft werden.

## Installation auf dem Mac (empfohlen)

1. ZIP entpacken (z. B. in *Dokumente*).
2. **Terminal** öffnen (⌘ + Leertaste → „Terminal“), `bash ` tippen (mit Leerzeichen), die Datei
   `install-mac.command` aus dem Finder ins Terminal-Fenster ziehen und Enter drücken.
   Grund: macOS blockiert Skripte aus dem Internet beim Doppelklick („Sicherheitsbedenken“), über `bash`
   gestartet nicht. Alternative: einmal doppelklicken, dann *Systemeinstellungen → Datenschutz & Sicherheit →
   „Trotzdem öffnen“*. Das Skript hebt die Sperre für den Ordner auf – danach gehen alle `.command`-Dateien
   per Doppelklick.
3. Den Fragen im Terminal folgen – jede Frage lässt sich mit Enter überspringen.

Das Skript sucht ein passendes Python (3.10 oder neuer; das in macOS mitgelieferte 3.9 reicht nicht) und lädt
sonst Python 3.12 **ohne Admin-Passwort** in den Benutzerordner (über [uv](https://docs.astral.sh/uv/)). Dann legt es
`.venv` mit allen Paketen an, erzeugt bzw. ergänzt die `.env` (zufälliger `SECRET_KEY` und Admin-Passwort,
optional Anthropic-/ElevenLabs-Key und E-Mail-Versand), macht einen Selbsttest und legt auf Wunsch
**„Radiospot starten“** auf den Schreibtisch.

- **Starten:** Doppelklick auf „Radiospot starten“ bzw. `start-mac.command` – der Browser öffnet sich, das
  Terminal-Fenster muss offen bleiben (beenden mit Ctrl + C). Der Mac schläft währenddessen nicht ein.
- **Im Netzwerk** (Handy, andere Rechner im selben WLAN): „Radiospot im WLAN starten“ auf dem Schreibtisch bzw.
  `start-mac-netzwerk.command` – zeigt die Adresse an.
- **Update:** neuen Ordner drüberkopieren und `install-mac.command` erneut ausführen. Bestehende Werte in der
  `.env`, die Datenbank, Musik und Logos bleiben erhalten; neue Einstellungen werden am Ende der `.env` ergänzt.
- **Probleme:** Das Protokoll steht in `install.log`. Muss ein Paket übersetzt werden, fehlen evtl. die
  Apple-Entwicklerwerkzeuge: im Terminal `xcode-select --install`, danach das Skript erneut starten.

## Start (manuell, alle Systeme)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # SECRET_KEY und ADMIN_PASSWORD anpassen!
uvicorn app.main:app --reload
```

| URL | Inhalt |
|---|---|
| http://localhost:8000/ | Konfigurator (Beispiel-Frontend) |
| http://localhost:8000/admin | Admin-Oberfläche (Login aus `.env`) |
| http://localhost:8000/docs | OpenAPI / Swagger |

Tests: `pytest`

## Produkte (im Admin pflegbar)

| Bereich | Bedeutung |
|---|---|
| **Spotlängen** | auswählbare Längen in Sekunden |
| **Stimmen** | Stimmen fürs Hörbeispiel: Name, Beschreibung, optional MP3 (sonst Browser-Sprachausgabe) |
| **Musik** | Musikrichtungen (Auswahlliste) |
| **Anlässe / Tonalitäten** | Auswahllisten im Konfigurator |
| **Sprachstile** | inkl. Anweisung, die an die KI-Textgenerierung geht |
| **Sender & Streams** | Typ (Radio / Stream der Energy-Gruppe), Sekundenpreis netto, „Werbeabgabe fällt an“ (Radio ja, Streams nein) |
| **Zeitschienen** | z. B. Morning Show – Preisfaktor auf den Sekundenpreis (1,5 = +50 %) |
| **Sendegebiete** | für die Reichweiten-Karte im Konfigurator: DAB+ (leuchtende Bundesländer) oder UKW (Kreis um den Sender-Standort – per Klick auf die Karte gesetzt, Radius in km), Hinweistext für Kunden. Bei Sendern und Komplettpaketen zuordnen. Je Sender (oder Sendegebiet) eine eigene Kartenfarbe, z. B. Blau für Radio Nostalgie; gemeinsame Gebiete werden gestreift. Kartendaten: Natural Earth (gemeinfrei), `app/static/austria-map.json`, neu erzeugbar mit `scripts/build_austria_map.py` |
| **Komplettpakete** | Pakete zum Pauschalpreis (netto) mit Artikelnummer, Schaltungen und Laufzeit in Tagen (Kunde wählt nur den Beginn), optionaler Senderwahl (*Wählbare Sender*), Leistungsliste, Badge, Anzahl Ausstrahlungen, optional „Studiospot inklusive“ und max. Spotlänge; Sendezeit-Anteil als Basis der Werbeabgabe. Drei Beispielpakete werden einmalig **inaktiv** angelegt – Preise anpassen und auf „aktiv“ stellen |
| **Zusatzleistungen** | optionale Extras mit Fixpreis, z. B. Express-Produktion; „Nur mit Studiospot“ blendet sie nur bei gewähltem Studiospot ein |
| **Rabatte** | Prozent oder Fixbetrag, mit Bedingungen (s. u.) |
| **Glücksrad** | Rabatt-Glücksrad im letzten Schritt: Felder, Rabatte, Gewichtung, Gültigkeit; Ergebnis bestimmt der Server |
| **Länder** | Rechnungsländer (Dropdown im Formular) mit MwSt.-Satz und Option „mit UID Nettorechnung“ |
| **Rechtstexte** | AGB und Datenschutzerklärung – Pflicht-Häkchen im Checkout, per Klick einblendbar, eigene Seiten `/agb` und `/datenschutz`; Zustimmung (Zeitpunkt + Textversion) wird je Anfrage gespeichert |
| **Design** | Farben (Seite, Formular, Akzente) und Schriften (Google Fonts, lokal vom eigenen Server ausgeliefert, oder Systemschrift) des Konfigurators, Farbvorlagen, Layout-Varianten (Klassisch, ENERGY Neon, Studio, Kompakt) und Anordnung der Elemente mit Live-Vorschau für Desktop/Handy; Text und Größe der Überschrift, Untertitel oben rechts |
| **Logo** (unter *Design*) | Logo als PNG, JPG, WebP oder SVG hochladen (max. 2 MB), Höhe einstellen, optional auch im PDF (nur PNG/JPG/WebP). Ersetzt den Schriftzug im Konfigurator und auf AGB/Datenschutz. Alternativ das Bild einfach in den Ordner `media/logos` legen – es wird automatisch verwendet, solange im Admin kein anderes Logo gespeichert ist |
| **Preis-Einstellungen** | Preis Studiospot, Werbeabgabe, Mindestbestellwert, Währung, „Individuell“ (Buchung nach Sekunden) ein/aus, Vorlaufzeit für den Kampagnenbeginn (auch für die Verkaufsleitung) |
| **Einstellungen** | PDF-Firmenangaben, Wasserzeichen, Mastering (nur Administrator) |
| **Benutzer** | Zugänge und Rollen (nur Administrator) |
| **Anfragen** | eingegangene Angebotsanfragen inkl. Kalkulation und Status |

Inaktive Produkte verschwinden aus dem Konfigurator, bleiben aber in alten Anfragen erhalten
(jede Anfrage speichert ihre Kalkulation als Snapshot).

## Preisberechnung

```
Spot         = 0 € (Text & Hörbeispiel) bzw. Pauschalpreis Studiospot (0 €, wenn im Paket enthalten)
Paket        = Pauschalpreis des Komplettpakets (alternativ zur individuellen Schaltung)
Schaltung    = Spotlänge (s) × Sekundenpreis des Senders × Faktor der Zeitschiene × Ausstrahlungen
Zwischensumme= Spot + Paket + Schaltung + Zusatzleistungen
Netto        = Zwischensumme − Rabatte
Werbeabgabe  = 5 % × (Radio-Sendezeit nach Rabatten)  – Streams und Zusatzleistungen sind ausgenommen;
               bei Paketen auf den hinterlegten Sendezeit-Anteil (0 = ganzer Paketpreis)
MwSt.        = Satz des Rechnungslands × (Netto + Werbeabgabe)   – Einbeziehung abschaltbar
Brutto       = Netto + Werbeabgabe + MwSt.
```

Satz der Werbeabgabe und MwSt. sind unter *Einstellungen* pflegbar (Werbeabgabe 0 % = aus).
Rabatte auf den Gesamtbetrag werden für die Werbeabgabe anteilig auf Sendezeit und
Zusatzleistungen aufgeteilt.

### Rabatte

Bedingungen (alle optional, alle gesetzten müssen erfüllt sein):
Mindestanzahl Spots (über alle Positionen) · Mindestbetrag · Gutscheincode ·
nur für einen bestimmten Sender · Gültigkeitszeitraum.

Komplettpakete haben bereits einen Pauschalpreis: Für sie gelten nur Rabatte „auf den Gesamtbetrag“
(z. B. Gutscheincodes), nicht Rabatte auf Sendezeit oder einen einzelnen Sender. Die Ausstrahlungen
des Pakets zählen für die Mindestanzahl Spots.

- **Gilt für**: Gesamtbetrag, nur Studiospot oder nur Sendezeit.
  Senderbezogene Rabatte gelten immer nur für die Sendezeit dieses Senders.
- **Kombinierbar**: alle kombinierbaren Rabatte werden addiert (jeweils auf die ursprüngliche Basis).
- **Nicht kombinierbar (exklusiv)**: greift nur, wenn er allein höher ist als alle kombinierbaren zusammen.
- Der Rabatt kann nie höher als die Zwischensumme sein.

Die Logik steckt komplett in `app/pricing.py` – dort lässt sie sich gezielt anpassen.

## Hörprobe: KI-Stimme, Musik & Wasserzeichen

- **KI-Stimme (ElevenLabs):** `ELEVENLABS_API_KEY` in `.env` eintragen. Jede Stimme braucht im Admin unter
  *Stimmen* eine **ElevenLabs Voice-ID** (ElevenLabs → Voice Library → deutsche Stimme → „Add to my voices“ →
  „Copy voice ID“). Ohne Key/ID fällt der Konfigurator auf die Browser-Stimme zurück (ohne Musik).
- **Musik:** im Admin unter *Musik* MP3/WAV/OGG/FLAC hochladen (max. 20 MB, lizenzfreie Musik!). Kunden können
  jede Musik im Konfigurator vorhören. Mitgeliefert sind drei selbst erzeugte Platzhalter in `app/static/demo-music/`.
- **Musik-Lautstärke:** unter *Einstellungen → Hintergrundmusik* die Musik unter der Stimme (Standard 14 %) und im
  Intro/Outro (Standard 45 %); je Stück zusätzlich eine *Lautstärke-Korrektur* (Faktor, 1 = unverändert).
- **Mischen & Mastering:** „Hörprobe erstellen“ legt die Stimme über die Musik (1,5 s Intro, Musik unter der
  Stimme abgesenkt, 2,5 s Outro mit Ausblenden), in **48 kHz Stereo**. Danach Mastering: Kompressor → Limiter
  auf **−8 LUFS** (integriert, ITU-R BS.1770-4) bei max. **−1 dBTP** (beides unter *Einstellungen* änderbar).
  Alles auf dem Server in Python (`app/audio.py`: miniaudio, numpy, scipy – kein ffmpeg nötig).
- **Dateien:** Kunden hören die Hörprobe mit Wasserzeichen (mono, 32 kHz – klein fürs Web). Im Admin bei jeder
  Anfrage: **„Spot (WAV)“** – fertig gemastert, ohne Wasserzeichen, 48 kHz / Stereo / 24 Bit – und
  **„Nur Sprache (WAV)“** – 48 kHz / Stereo / 24 Bit, True Peak −1 dBTP, ohne Kompression.
- **Wasserzeichen:** In jede Kunden-Hörprobe wird alle 7 s der Text „Hörprobe von onaircraft“ gesprochen –
  oder eine **eigene Audiodatei** eingespielt (Jingle, Sprecher-Aufnahme; MP3/WAV/OGG/FLAC, bis 15 s, liegt unter
  `media/watermark`). Art, Text, Datei, Lautstärke und Abstand unter *Einstellungen*. Kunden bekommen nie eine
  saubere Datei – den Spot **ohne** Wasserzeichen lädt nur der Admin bei der Anfrage herunter.
- **Sprech-Dynamik:** Modell-Schalter `ELEVENLABS_MODEL` in `.env` (Standard `eleven_v4`). Mit Eleven v4/v3 steuern
  Regieanweisungen in eckigen Klammern die Sprechweise (`[excited]`, `[whispers]`, `[laughs]` …) – der
  KI-Textvorschlag setzt sie passend zur Tonalität. Mit Multilingual v2/Flash werden Klammern entfernt; dafür gibt es
  Style- und Tempo-Regler, `<break time="0.5s" />` und automatische Tempo-Anpassung an die Spotlänge.
  Regler je **Stimme** (Stabilität, Ähnlichkeit, Style, Tempo) und je **Tonalität** (Stabilität, Style,
  Tempo-Faktor, Hinweis für die KI) im Admin.
- **Geschwindigkeit:** Sprache und Wasserzeichen werden gleichzeitig bei ElevenLabs angefragt; fertige Hörproben
  liegen in `media/cache/preview` und werden bei gleicher Kombination sofort ausgeliefert. Im Server-Terminal
  steht je Spot „Spot erstellt: ElevenLabs … s, Mischen & Mastering … s“. Schnelleres ElevenLabs-Modell:
  `ELEVENLABS_MODEL=eleven_flash_v2_5` (deutlich schneller und günstiger, etwas weniger ausdrucksstark).
- **Kosten:** ElevenLabs-Ergebnisse werden in `media/cache/tts` gespeichert, gleiche Texte kosten nur einmal.
  Pro Besucher-IP max. 15 Hörproben in 10 Minuten (`TTS_RATE_LIMIT`), Text max. 1.000 Zeichen.

## Anfrage per E-Mail weiterleiten

Bei jeder Anfrage (Admin → *Anfragen* → Details) gibt es den Bereich **Per E-Mail senden**: Empfänger
(mehrere mit Komma), Betreff und Text frei wählbar, Anhänge per Häkchen – Kostenaufstellung (PDF), fertiger Spot
ohne Wasserzeichen und die Sprache allein (WAV, 48 kHz, Stereo, 24 Bit). Der Empfänger wird mit dem
*Standard-Empfänger* aus den *Einstellungen* vorausgefüllt. Jeder Versand wird bei der Anfrage protokolliert.

Versendet wird über dein eigenes Mail-Konto (SMTP) – Zugangsdaten in der `.env`:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls        # 465 → ssl
SMTP_USER=deine.adresse@gmail.com
SMTP_PASSWORD=App-Passwort     # Gmail: myaccount.google.com/apppasswords (2-Faktor-Anmeldung nötig)
SMTP_FROM=                     # leer = SMTP_USER
SMTP_FROM_NAME=onaircraft
MAIL_MAX_MB=18                 # Größe aller Anhänge zusammen
```

WAV-Dateien sind groß (ca. 0,3 MB pro Sekunde für den Spot). Bei langen Spots ggf. nur Spot **oder** Sprache
anhängen – ist die Grenze überschritten, kommt eine verständliche Meldung statt eines Versandfehlers.

## KI-Textvorschlag

„Text mit KI generieren“ läuft über `POST /api/generate-script` – der Anthropic-API-Key liegt nur
auf dem Server (`ANTHROPIC_API_KEY` in `.env`), nicht mehr im Browser wie in der Vorlage.
Ohne Key wird der Button ausgeblendet. Pro Besucher-IP sind standardmäßig 10 Vorschläge
in 10 Minuten erlaubt (`SCRIPT_RATE_LIMIT`). Modell: `ANTHROPIC_MODEL` (Standard wie in der
Vorlage `claude-sonnet-5-5`). Lehnt das Modell eine Anfrage ab, übernimmt automatisch ein
Ersatzmodell (Server-side Fallback).

## Eigenen Konfigurator einbauen

Das Frontend unter `app/static/configurator.js` ist ein lauffähiges Beispiel. Ein eigener
Konfigurator (React, Vue, WordPress-Plugin …) braucht nur drei Endpunkte:

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/catalog` | alle aktiven Produkte + MwSt./Mindestbestellwert |
| POST | `/api/quote` | Preis für eine Konfiguration berechnen |
| POST | `/api/quote-requests` | Anfrage absenden (Preis wird serverseitig neu berechnet), liefert `pdf_url` |

```json
POST /api/quote
{
  "production": {"spot_length_id": 2, "voice_id": 1, "music_style_id": 2, "studio": true},
  "items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 2, "spots": 60}],
  "addon_ids": [1],
  "promo_code": "WILLKOMMEN",
  "country": "DE",
  "vat_id": "DE123456789"
}
```

`production` und `items` (Schaltung) sind jeweils optional, eins von beiden muss angegeben sein.

Alle Beträge sind **Cent**, Prozentwerte/Faktoren **Basispunkte** (1900 = 19 %, 15000 = Faktor 1,5).

Auf einer anderen Website (z. B. WordPress) am einfachsten per iframe:

```html
<iframe src="https://konfigurator.example.at/" style="width:100%;height:1600px;border:0"></iframe>
```

Alternativ die Seite `app/templates/configurator.html` übernehmen und `data-api` am Panel auf die
Backend-URL setzen; die fremde Domain muss dann in `CORS_ORIGINS` stehen.

## Admin-API

Alle Produkte lassen sich auch per JSON pflegen: `/api/admin/{stations|time-slots|spot-lengths|addons|discounts}`
(GET/POST, GET/PUT/DELETE `/{id}`), `/api/admin/settings`, `/api/admin/quote-requests`.
Authentifizierung per Admin-Session oder HTTP Basic Auth – nur für die Rolle Administrator.

## Projektstruktur

```
app/
  main.py            App, Middleware, Startup (Tabellen + erster Admin + Demo-Daten)
  config.py          Einstellungen aus Umgebungsvariablen / .env
  models.py          SQLAlchemy-Modelle
  schemas.py         Pydantic-Schemas
  pricing.py         Preis- und Rabattberechnung
  ai.py              KI-Textvorschlag (Anthropic API)
  audio.py           ElevenLabs, Mischen mit Musik, Wasserzeichen
  pdf.py             PDF-Kostenaufstellung je Anfrage
  security.py        Passwort-Hashing, Admin-Auth, CSRF
  mailer.py          E-Mail-Versand (SMTP) für PDF und Audiodateien
  branding.py        Logo (Upload, Ordner media/logos, PDF)
  watermark.py       Wasserzeichen der Hörprobe (Text oder eigene Audiodatei)
  music_mix.py       Lautstärke der Hintergrundmusik
  static/coverage-map.js  Reichweiten-Karte (Konfigurator und Admin-Vorschau)
  routers/public.py  öffentliche Konfigurator-API
  routers/admin_api.py  JSON-Admin-API
  routers/admin_ui.py   Admin-Oberfläche (Jinja2)
  templates/, static/
tests/
```

## Vor dem Produktivbetrieb

- `SECRET_KEY` und `ADMIN_PASSWORD` setzen, `SEED_DEMO_DATA=0`
- in `app/main.py` `https_only=True` für das Session-Cookie (hinter HTTPS)
- statt SQLite z. B. PostgreSQL über `DATABASE_URL` (+ passenden Treiber installieren);
  für Schemaänderungen Alembic einführen
- E-Mail-Benachrichtigung bei neuen Anfragen ist noch nicht eingebaut
- Neue Spalten werden beim Start automatisch ergänzt (`app/database.py`); für größere Umbauten Alembic einführen
- Rate-Limiting für `/api/quote-requests` (Spam) z. B. per Reverse-Proxy


## Radiospot-Studio

Eigenständiges Profiprodukt im Ordner `studio/` – eigener Server, eigene Datenbank (`studio.db`),
eigenes Login-Cookie. Der Konfigurator bleibt davon unberührt; gemeinsam genutzt wird später nur der
Audio-Kern (`app/audio.py`).

```bash
uvicorn studio.main:app --port 8001      # Mac: Doppelklick auf start-studio-mac.command
```

**Arbeiten im Studio (Schritt 2):**
- **Dateien** (WAV, MP3, FLAC, OGG) hochladen – Button, in die Dateiliste ziehen oder direkt auf eine Spur.
  Jede Datei wird beim Hochladen geprüft (echtes Audio, max. `STUDIO_MAX_UPLOAD_MB` MB und
  `STUDIO_MAX_ASSET_MINUTES` Minuten) und zählt zum Speicherkontingent des Kontos.
- **Vier Spuren** (Sprache, Musik, SFX, Atmo): Dateien aus der Liste an die gewünschte Stelle ziehen,
  Clips frei verschieben (auch auf eine andere Spur), an den Rändern kürzen, Raster 0,05 s (Alt = frei).
  Atmo-Clips starten bei −12 dB.
- **Pro Clip** Lautstärke, Ein- und Ausblenden; **pro Spur** Lautstärke, Stumm und Solo.
- **Vorhören** direkt im Browser (Leertaste), Klick auf das Zeitlineal setzt die Position.
- Projekte speichern automatisch; mehrere Projekte pro Konto.
- **Export:** WAV, 48 kHz, Stereo, 24 Bit. Wahlweise Pegel lassen (nur Spitzen auf −1 dBTP begrenzt)
  oder auf −8 / −14 / −23 LUFS mastern (gleicher Audio-Kern wie der Konfigurator). Der True Peak liegt
  immer bei höchstens −1 dBTP. Gemessene Lautheit und Spitze stehen beim Export. Exporte werden nach
  `STUDIO_EXPORT_DAYS` Tagen gelöscht; das Exportkontingent zählt alle gestarteten Exporte.

**Bibliothek (Schritt 3):** Sammlungen von SFX, Musik und Atmos, die onaircraft pflegt
(Admin → *Bibliothek*). Dateien per Browser hochladen oder ganze Ordner per Kommandozeile übernehmen:

```bash
python -m studio.cli import-library ~/SFX/Tueren --library "onaircraft SFX" --category sfx --tags "tür"
```

Jede Sammlung hat einen Lizenzhinweis (die Nutzer sehen ihn beim Überfahren); eine Datei kann einen
eigenen haben. Sammlungen sind „für alle Konten“ oder nur für einzeln freigeschaltete Konten
(Admin → *Benutzer*, Spalte *Bibliotheken*). Im Editor: Reiter *Bibliothek* mit Suche, Kategorien und
▶ zum Vorhören, dann auf eine Spur ziehen. Bibliotheksdateien zählen nicht zum Speicher der Nutzer.
Dateien, die in Projekten stecken, lassen sich nicht löschen, nur deaktivieren (bestehende Projekte
klingen dann weiter gleich).

**Atmo, Loop & Fades:** Auf die Atmo-Spur gezogene Dateien laufen automatisch als Loop bis zum
Spotende, bei −12 dB mit 1 s weicher Ein- und Ausblendung. Loop lässt sich für jeden Clip ein- und
ausschalten; mit Loop wird ein Clip über das Dateiende hinaus verlängert (Nahtstellen mit 50 ms
Überblendung, in der Wellenform gestrichelt). Ein- und Ausblendung über die kleinen Griffe oben am
Clip oder im Clip-Panel, Kurve „weich (S-Kurve)“ oder „linear“ – Vorhören und Export klingen gleich.

**Hüllkurven & Ducking (Schritt 4):** Button *Hüllkurven* im Editor: Klick auf eine Spur setzt
einen Punkt (Lautstärke über die Zeit), Punkte ziehen, Doppelklick löscht. Spuren mit **D** werden
automatisch leiser, sobald die Sprache spricht (Stärke im Editor wählbar, Standard −10 dB; setzt
50 ms vor dem ersten Wort ein, hält 0,25 s in Sprechpausen, fährt in 0,5 s wieder hoch). In neuen
Projekten ducken Musik und Atmo. Vorhören und Export rechnen mit demselben Verfahren.

**Lautheit beim Export:** *Normalisieren* (nur Verstärkung, Dynamik bleibt – −23 LUFS EBU R128 für
die Sender-Anlieferung, −16 Web/Podcast, −14 Streaming) oder *Mastern* (Kompressor + Limiter, laut –
−8 wie Konfigurator, −11). True Peak immer max. −1 dBTP; gemessene Werte stehen beim Export.

**KI-Text & Stimme** (Button im Editor): Briefing eingeben → Claude schreibt drei Vorschläge →
übernehmen und frei bearbeiten (der Sprechtext wird mit dem Projekt gespeichert) → mit einer
freigegebenen Stimme einsprechen lassen. Die Aufnahme landet als Datei (Kennzeichen „KI“) in der
Dateiliste und kann direkt auf die Sprach-Spur gelegt, geschnitten und exportiert werden – ohne
Wasserzeichen. Es werden dieselben Funktionen und Keys wie im Konfigurator verwendet
(`ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_MODEL`); gleiche Texte mit gleicher Stimme
kommen aus dem Zwischenspeicher und kosten kein zweites Mal Guthaben.
- **Stimmen** gibt der Admin unter *KI-Stimmen* frei – aus der Liste des ElevenLabs-Kontos oder per
  Voice-ID, mit Name, Beschreibung und Klang-Einstellungen. Nutzer sehen nur freigegebene Stimmen.
- **Kontingente pro Konto und Monat** (Admin → *Benutzer*): KI-Zeichen (Standard 20 000) und
  KI-Texte (Standard 100), leer = unbegrenzt. Zusätzlich max. 10 Textanfragen bzw. 20 Aufnahmen pro
  10 Minuten. Eine Aufnahme darf bis zu 1 000 Zeichen haben – längere Texte bitte aufteilen.

**Render-Warteschlange:** Exporte laufen nie im Webprozess. Ein Worker holt die Aufträge aus der
Datenbank und rendert jeden in einem eigenen Prozess mit Zeitlimit (`STUDIO_RENDER_TIMEOUT`), höchstens
`STUDIO_RENDER_WORKERS` gleichzeitig und `STUDIO_MAX_QUEUED` wartende pro Konto. Am Mac läuft der Worker
automatisch mit (`STUDIO_WORKER=inline`), auf dem Server als eigener Dienst:

```bash
STUDIO_WORKER=external uvicorn studio.main:app --port 8001 --proxy-headers
python -m studio.worker
```

**Zugang nur mit Login.** Es gibt keine öffentliche Registrierung. Konten entstehen über einen
Einladungslink (Admin → *Benutzer*) oder auf dem Server per Kommandozeile:

```bash
python -m studio.cli invite kollege@example.com --role pro
python -m studio.cli create-user ron@onaircraft.net --role admin
python -m studio.cli set-password ron@onaircraft.net
python -m studio.cli list
```

Das erste Admin-Konto kommt aus `STUDIO_ADMIN_EMAIL` / `STUDIO_ADMIN_PASSWORD`; ohne Passwort wird
beim ersten Start eines erzeugt und einmal im Terminal angezeigt.

| Rolle | Darf |
|---|---|
| **Administrator** | Studio plus Benutzerverwaltung: einladen, Rollen, sperren, Speicher- und Exportkontingent |
| **Pro** | Studio |
| **Testzugang** | Studio; läuft nach `STUDIO_TRIAL_DAYS` Tagen (Standard 14) ab Einrichtung ab |

**Konten & Abrechnung (Schritt 5):** Admin → *Benutzer* zeigt alle Konten mit Status, Laufzeit,
Speicher, Exporten und KI-Verbrauch. Auf der Detailseite: Rolle, Sperre, Kontingente, Bibliotheken
und **Abrechnung** – Tarif, *Freigeschaltet bis* (manuell nach Zahlungseingang verlängern) und eine
interne Notiz. Abgelaufene Konten können sich anmelden, Projekte ansehen und Exporte herunterladen,
aber nichts Neues hochladen, erzeugen oder exportieren. Einladungen gehen auf Wunsch direkt per
E-Mail raus (SMTP-Einstellungen wie beim Konfigurator).

**An onaircraft schicken:** Button im Editor – das Projekt (aktueller Stand, mit Nachricht) landet
unter Admin → *Anfragen*; mit `STUDIO_SUPPORT_EMAIL` kommt zusätzlich eine E-Mail. *Als Kopie öffnen*
legt das Projekt samt Dateien in den eigenen Projekten an, zum Fertigstellen und Exportieren.

**Zwei-Faktor-Anmeldung** (optional, *Mein Konto*): QR-Code mit einer Authenticator-App scannen,
danach fragt die Anmeldung nach dem 6-stelligen Code. Ein Code gilt nur einmal. Bei verlorenem
Handy setzt der Admin sie auf der Detailseite des Kontos zurück.

**Sicherheit:** Jede Seite und jede `/api`-Route prüft die Session serverseitig (Test:
`tests/studio/test_studio_access.py` geht alle Routen durch). Sessions laufen nach
`STUDIO_SESSION_HOURS` ab; Passwortwechsel, Sperre oder Rollenänderung melden alle Geräte ab.
Nach `STUDIO_LOGIN_ATTEMPTS` Fehlversuchen (je IP und E-Mail) 15 Minuten Sperre. Einladungslinks
sind nur als Hash gespeichert, einmal verwendbar und laufen nach `STUDIO_INVITE_DAYS` ab.
API-Schreibzugriffe brauchen den Header `X-CSRF-Token` (steht im `<meta name="csrf-token">`).
Keine öffentliche API-Doku (`/docs` ist im Studio abgeschaltet).

**Produktion** (z. B. `studio.onaircraft.net` hinter nginx/Caddy mit HTTPS):
`STUDIO_HOSTS=studio.onaircraft.net`, `STUDIO_PUBLIC_URL=https://studio.onaircraft.net`,
`STUDIO_HTTPS_ONLY=1`, eigenen `STUDIO_SECRET_KEY` setzen und uvicorn mit `--proxy-headers` starten
(sonst zählt die Login-Sperre die IP des Proxys).
