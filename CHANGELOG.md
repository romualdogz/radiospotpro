# Changelog – Radiospot-Konfigurator

Alle Änderungen am Konfigurator und am Admin, neueste zuerst.
Einträge vor dem 24.10.2026 (nachmittags) wurden nachträglich aus dem Projektverlauf zusammengestellt.

**Beim Aktualisieren gilt immer:** Projektordner aus der ZIP drüberkopieren, `.env` und `radiospot.db`
bleiben erhalten, Server neu starten. Neue Datenbank-Spalten werden beim Start automatisch ergänzt.

---

## 25.10.2026

### Neu
- **Reichweiten-Karte DAB+ vs. UKW:** Im Konfigurator (Schritt „Buchung“) zeigt eine Österreich-Karte das
  Sendegebiet der aktuellen Auswahl – DAB+ lässt die Bundesländer in der Akzentfarbe aufleuchten, UKW-Sender
  leuchten als Kreis um den Standort. Dazu Liste mit Reichweiten-Texten, Legende und die Erklärung
  „DAB+ oder UKW – was ist der Unterschied?“. Streams werden als „online – überall empfangbar“ angezeigt.
- **Sendegebiete im Admin** (*Schaltung → Sendegebiete*): Name, Technik (DAB+/UKW), Bundesländer, Sender-Standort
  per Klick auf die Karte, Radius in km, Hinweistext. Bei Sendern und Komplettpaketen per Häkchen zuordenbar;
  auch für die Verkaufsleitung. Beispiele „DAB+ National“, „UKW Wien“, „UKW Salzburg“, „UKW Innsbruck“ werden
  einmalig angelegt (Radien sind Richtwerte – bitte prüfen).
- Das Sendegebiet steht in der Zusammenfassung, in der Kalkulation und im PDF.
- Kartendaten: Natural Earth (gemeinfrei), als kleine Datei mitgeliefert – keine externen Dienste nötig.
- **Lautstärke der Hintergrundmusik einstellbar** (*Einstellungen → Hintergrundmusik*): Musik unter der
  Stimme (bisher fest 14 %) und ohne Stimme im Intro/Outro (bisher fest 45 %) per Regler. Zusätzlich je
  Musikstück eine **Lautstärke-Korrektur** (*Musik*, Faktor 0,2–3), um laute und leise Tracks anzugleichen.
  Gilt für Hörprobe und fertigen Spot; bestehende Spots klingen ohne Änderung wie bisher.
- **Eigenes Wasserzeichen als Audiodatei** (*Einstellungen → Wasserzeichen der Hörprobe*): Jingle oder
  gesprochenes „onaircraft“ hochladen (MP3, WAV, OGG, FLAC, bis 15 s / 5 MB), im Admin vorhören, entfernen.
  Wahl zwischen „Gesprochener Text“ und „Eigene Audiodatei“, Lautstärke-Regler (Standard 40 %).
  Mit eigener Datei ist die Hörprobe schneller fertig (kein zweiter ElevenLabs-Aufruf).
- **Installation auf dem Mac per Doppelklick:** `install-mac.command` sucht bzw. lädt Python (ohne
  Admin-Passwort), installiert alle Pakete, legt die `.env` an oder ergänzt fehlende Einträge (bestehende
  Werte bleiben), fragt optional Anthropic-/ElevenLabs-Key und E-Mail-Versand ab, macht einen Selbsttest
  und legt „Radiospot starten“ auf den Schreibtisch. Gefahrlos wiederholbar, z. B. nach Updates.
- **`start-mac.command`:** startet den Server, öffnet den Browser, nimmt automatisch einen freien Port und
  verhindert den Ruhezustand, solange der Server läuft.
- Erster Start über das Terminal (`bash install-mac.command`), weil macOS den Doppelklick bei Dateien
  aus dem Internet blockiert; danach funktionieren alle `.command`-Dateien per Doppelklick.
- **`start-mac-netzwerk.command`:** wie oben, aber im lokalen Netzwerk erreichbar (zeigt die Adresse an).

### Behoben
- Sehr kurze Hörproben (unter 2 Sekunden) bekamen kein Wasserzeichen – jetzt liegt es dann in der Mitte.
- **Im WLAN nicht erreichbar:** Lief noch das normale Fenster (nur am Mac erreichbar), wich
  `start-mac-netzwerk.command` unbemerkt auf Port 8001 aus. Jetzt kommt ein klarer Hinweis, das andere
  Fenster zu schließen.
- `start-mac-netzwerk.command` prüft die Mac-Firewall: Python wird auf Wunsch freigegeben (Mac-Passwort),
  bei „Alle eingehenden Verbindungen blockieren“ gibt es eine Anleitung. Nach dem Start wird geprüft, ob
  der Server unter der WLAN-Adresse antwortet; die WLAN-Adresse wird zuverlässiger ermittelt.
- Hinweise im Netzwerkfenster, woran es liegt, wenn das Handy den Server nicht erreicht (gleiches WLAN,
  Gastzugang, VPN, Sicherheits-Software). Der zwischenzeitliche Hinweis auf „Lokales Netzwerk“ wurde wieder
  entfernt – diese macOS-Sperre gilt nicht für Programme aus dem Terminal.

---

## 24.10.2026

### Neu
- **Anfrage per E-Mail senden:** Bei jeder Anfrage PDF, fertigen Spot (ohne Wasserzeichen) und
  Sprachdatei mit eigenem Betreff und Text an beliebige Adressen schicken. Versand über das eigene
  Mail-Konto (SMTP, Zugangsdaten in der `.env`), Standard-Empfänger unter *Einstellungen*,
  Versandprotokoll je Anfrage, Größenprüfung der Anhänge (`MAIL_MAX_MB`, Standard 18 MB).
  Status „E-Mail-Versand eingerichtet“ auf dem Dashboard.
- **Logo als Bild:** Upload unter *Design → Logo* (PNG, JPG, WebP, SVG, max. 2 MB), Höhe per Regler,
  optional im PDF (nur PNG/JPG/WebP). Alternativ Bild in den Ordner `media/logos` legen – wird
  automatisch verwendet. Energy-Logo liegt unter `media/logos/energy-logo.svg`.
- **Komplettpakete zum Pauschalpreis** (*Preise → Komplettpakete*): Name, Badge, Leistungsliste,
  Ausstrahlungen, max. Spotlänge, „Studiospot inklusive“, Sendezeit-Anteil für die Werbeabgabe.
  Im Konfigurator Wahl zwischen „Komplettpaket“ und „Individuell zusammenstellen“. Drei
  Beispielpakete werden einmalig **inaktiv** angelegt. Auch im PDF und in der Anfrage sichtbar.
- **Benutzer & Rollen** (*Benutzer*): weitere Zugänge anlegen, Rolle ändern, Passwort zurücksetzen,
  löschen. Rolle **Verkaufsleitung** darf nur Sender & Streams, Zeitschienen, Komplettpakete,
  Zusatzleistungen, Rabatte, Länder & MwSt. und Preis-Einstellungen bearbeiten.
- **Mein Konto:** jeder Benutzer ändert dort sein eigenes Passwort.
- **Preis-Einstellungen** als eigene Seite (Studiospot-Preis, Werbeabgabe, Mindestbestellwert, Währung).

### Geändert
- Der Tipp zu Regieanweisungen in eckigen Klammern unter dem Spot-Textfeld wurde entfernt
  (die Funktion selbst bleibt).
- *Einstellungen* enthält nur noch PDF-Firmenangaben, Wasserzeichen, Mastering und den
  Standard-E-Mail-Empfänger; Passwort ändern ist unter *Mein Konto*.
- Die JSON-Admin-API steht nur noch Administratoren zur Verfügung.

### Behoben
- Farbflächen unter *Design* waren in Safari leer – eigene Farbfelder, die in jedem Browser
  die aktuelle Farbe zeigen.
- Logo/Schriftzug und Slogan im Kopf standen weiter außen als die Überschrift.
- Preise mit Tausenderpunkt („1.990,00“) werden im Admin akzeptiert.
- `SEED_DEMO_DATA` versteht auch `true`/`ja` statt nur `1`.
- Anfrage nur mit Komplettpaket (ohne Einzelbuchung) wurde abgelehnt.

---

## 23.10.2026

### Neu
- **Rechtstexte:** AGB und Datenschutz im Admin pflegbar, Pflicht-Häkchen im Checkout, Texte
  einblendbar, eigene Seiten `/agb` und `/datenschutz`; Zustimmung (Zeitpunkt + Textversion) wird
  je Anfrage gespeichert und im PDF vermerkt.
- **Design:** Farben und Schriften (Google Fonts oder Systemschrift) im Admin, Farbvorlagen, Vorschau.
- **Länder & MwSt.:** Länder-Dropdown im Checkout (ohne MwSt.-Anzeige), Satz je Land im Admin,
  Reverse Charge mit UID-Nummer → Nettorechnung.
- **Sprech-Dynamik:** Eleven v4 mit Regieanweisungen, Modell umschaltbar über `ELEVENLABS_MODEL`;
  Stabilität/Style/Tempo je Stimme und Tonalität.
- **Audio für den Admin:** fertiger Spot auf −8 LUFS, Stereo, 48 kHz, 24 Bit, ohne Wasserzeichen,
  plus Sprache als eigene Datei.
- **ElevenLabs-Stimmen, Musik mit Vorhören, Mischen und Wasserzeichen** in der Kunden-Hörprobe.
- **KI-Textvorschlag** (Anthropic) mit verständlichen Fehlermeldungen.
- **PDF-Kostenaufstellung** zu jeder Anfrage.
- Kundendaten: Name, Firma, Straße, PLZ, Ort, Land, UID, Telefon, E-Mail.

### Geändert
- Text und Hörbeispiel sind gratis; kostenpflichtig sind nur Schaltung und optional der Studiospot
  (349 € netto).
- Werbeabgabe 5 % nur auf Radio-Sendezeit (nicht auf Streams und Zusatzleistungen).
- Sender: Radio Energy Österreich an erster, Radio Nostalgie an zweiter Stelle; Schaltung nur im
  Radio oder in den Streams der Energy-Gruppe.
- Express-Produktion nur bei Studiospot sichtbar; „Zusätzliche Korrekturschleife“ entfernt.
- Größeres Spot-Textfeld ohne Scrollen; mehrere Einleitungssätze und „Bei Firmen angeben“ entfernt.

### Behoben
- `.env`-Werte mit doppeltem Namen (`NAME=NAME=wert`) oder Anführungszeichen werden toleriert.
- Hinweis auf dem Dashboard, wenn Stimmen keine ElevenLabs-Voice-ID haben.

---

## Erste Version
- FastAPI-Konfigurator nach der onaircraft-HTML-Vorlage (5 Schritte: Anlass, Text, Stimme,
  Buchung, Anfrage) mit Admin für Produkte, Preise und Rabatte, JSON-Admin-API und Tests.
