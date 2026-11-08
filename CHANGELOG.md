# Changelog – Radiospot-Konfigurator

Alle Änderungen am Konfigurator und am Admin, neueste zuerst.
Einträge vor dem 24.10.2026 (nachmittags) wurden nachträglich aus dem Projektverlauf zusammengestellt.

**Beim Aktualisieren gilt immer:** Projektordner aus der ZIP drüberkopieren, `.env` und `radiospot.db`
bleiben erhalten, Server neu starten. Neue Datenbank-Spalten werden beim Start automatisch ergänzt.

---

## 08.11.2026

### Neu
- **Radiospot-Studio, Schritt 1:** eigenständige App (`uvicorn studio.main:app --port 8001`) mit
  eigener Datenbank und eigenem Login. Rollen Administrator / Pro / Testzugang, keine öffentliche
  Registrierung, Einladungslinks (einmalig, ablaufend), Benutzerverwaltung mit Speicher- und
  Exportkontingent, Sperre nach Fehlversuchen, Sessions mit Ablauf, Kommandozeile `python -m studio.cli`.
  Leere Mehrspur-Arbeitsfläche (Sprache, Musik, SFX, Atmo) als Grundlage für Schritt 2.
- **Radiospot-Studio, Schritt 2 – Mehrspur-Editor mit Upload und Export:** eigene Dateien hochladen
  (WAV/MP3/FLAC/OGG, mit Wellenform), per Drag & Drop auf vier Spuren legen, frei verschieben und
  kürzen, Clip-Lautstärke und Fades, Spur-Lautstärke/Stumm/Solo, Vorhören im Browser, Projekte mit
  automatischem Speichern. Export als WAV (48 kHz, 24 Bit) über eine Render-Warteschlange mit eigenem
  Prozess und Zeitlimit pro Auftrag, wahlweise auf −8/−14/−23 LUFS gemastert, True Peak max. −1 dBTP.
  Speicher- und Exportkontingent werden jetzt durchgesetzt, alte Exporte automatisch gelöscht.

---

## 03.11.2026

### Neu
- **Design-Variante „Black Friday“** (monochrom, mit Farbvorlage): Schwarz-Weiß mit diagonalen Streifen, laufendem Band
  „BLACK FRIDAY ✦ NUR FÜR KURZE ZEIT ✦ …“, „AKTION“-Plakette, riesiger Schrift „Anton“, umrandetem „SALE“, „SALE“-Schild
  an den Paketpreisen, eckigen schwarzen Knöpfen (beim Drüberfahren invertiert) und Karte in Graustufen.
- **Zeitplan für Designs** (*Design → „Zeitplan – Designs automatisch umschalten“*): Zeiträume mit Von/Bis (Ortszeit Wien),
  Variante und optional deren Farben anlegen. Im Zeitraum sieht jeder Besucher automatisch dieses Design, danach wieder
  das normale – ohne dass etwas umgestellt werden muss. Status „geplant / aktiv / abgelaufen“, Löschen per Klick,
  Knopf „Black Friday eintragen“ füllt Black Friday bis Cyber Monday (z. B. 27.–30.11.) vor.

### Behoben
- Am Handy konnte im Schritt „Buchung“ ein Feld (Zeitraum, Komplettpaket/Individuell) seitlich über den Rand ragen.
- **Drei KI-Textvorschläge statt einem:** „Text mit KI generieren“ liefert drei unterschiedliche Varianten – „Direkt &
  klar“, „Mit kleiner Szene“ und „Mit Augenzwinkern“ – in einer einzigen KI-Anfrage (keine Mehrkosten). Vorschlag 1
  steht sofort im Textfeld, die anderen als Karten darüber; ein Klick übernimmt einen anderen (bei eigenen Änderungen
  mit Rückfrage). Die Vorschläge bleiben beim Zurück- und Weiterblättern erhalten.

---

## 01.11.2026

### Neu
- **Zwei lustige Gaming-Varianten** (*Design → Layout-Varianten*, je mit eigener Farbvorlage):
  - **„Jump & Run“** – Plattform-Spiel: blauer Himmel mit Wolken, grüne Hügel, Ziegelboden, hüpfender „?“-Block, Münzen
    über der Überschrift, Schritte als Münzen (die aktuelle dreht sich), dicke Knöpfe zum „Draufhüpfen“, Schrift „Bungee“.
  - **„Candy Pop“** – bonbonbuntes Handyspiel: rosa-lila Verlauf mit aufsteigenden Seifenblasen, Bonbon-Rahmen,
    bunte Auswahl-Bubbles (Mint, Zitrone, Himmelblau, Flieder), Wackelpudding-Knöpfe, gestreifte Schritt-Bonbons,
    Schrift „Fredoka“, „Weiter 🍭“.
  Beide mit Spielmodus; auch als Stil einzeln wählbar. Schriften lokal mitgeliefert (OFL).

---

## 26.10.2026

### Neu
- **Felder „Firma / Marke“ und „Call-to-Action“ ausblendbar** (*Design → Texte & Überschrift*, je ein Häkchen): Im
  Schritt „Text“ fallen die Felder weg (ohne Firma stehen Tonalität und Sprachstil nebeneinander), sie sind dann auch
  für den KI-Vorschlag keine Pflicht mehr. Die KI schreibt ohne Firma neutral (erfindet keinen Namen) und formuliert
  ohne Call-to-Action selbst eine passende Handlungsaufforderung. Die Firma für die Rechnung fragt weiterhin der
  letzte Schritt ab. Die Einstellung bleibt beim Wechsel der Layout-Variante erhalten.
- **Level-Namen im Spielmodus selbst einstellbar** (*Design → Texte & Überschrift → „Spielmodus: Namen der 4 Level“*,
  mit Komma getrennt). Standard jetzt: Newcomer → **Sound-Talent** (statt „Jingle-Profi“) → Studio-Star → Radiolegende.
- **Design-Variante „Energy Gaming“** (*Design → Layout-Varianten*, mit Farbvorlage „Energy Gaming“): E-Sport-Look in
  Energy-Rot und Schwarz mit **anderer Anordnung** – links eine Spieler-Seitenleiste (Level, XP-Balken, nächste Mission,
  Abzeichen und die fünf Schritte als Missionsliste mit Status „Abgeschlossen / Aktiv / Bereit / Gesperrt“), rechts das
  Spielfeld. Große schräge Überschrift in „Oswald“ mit „SEASON 01“-Plakette und „ON AIR“-Schriftzug, abgeschrägte Ecken,
  schräge Knöpfe und Auswahl-Kacheln, „WEITER »“. Am Handy alles untereinander. Auch als Stil „E-Sport“ einzeln wählbar.
- **Nach Updates keine alten Dateien mehr im Browser:** JS- und CSS-Dateien werden mit einer Versionskennung geladen
  (`?v=…`), die sich bei jeder Änderung ändert. Vorher konnte der Browser z. B. noch die alte Glücksrad-Datei zeigen
  (Rad statt Spielautomat), bis man den Zwischenspeicher leerte.
- **Glücksrad als Spielautomat** (*Glücksrad → Darstellung → „Spielautomat“*): roter Automat mit „JACKPOT“-Leuchtschild
  und Lauflichtern, drei Walzen mit Gewinnlinie und Hebel. Der Kunde zieht am Hebel (nach unten ziehen oder antippen),
  die Walzen laufen und stoppen nacheinander. Gewinn = dreimal dasselbe Feld auf der Linie (z. B. „5 % | 5 % | 5 %“,
  Gewinnlinie blinkt), Niete = gemischte Symbole (🍒 📻 🔔 ⭐ 🎵 🍋). Passt besonders zum Design „Arcade“ (Pixelschrift
  im Leuchtschild). Eingebettet und als Pop-up („🎰 Glücksautomat“), Auslosung weiter beim Server.
- **Design-Entwurf „Arcade“** (*Design → Layout-Varianten → Arcade*, mit Farbvorlage „Arcade“): Retro-Computerspiel
  mit Pixelschrift „Press Start 2P“ (lokal mitgeliefert, OFL), Sternenhimmel und Neon-Raster, Röhrenbildschirm-Effekt
  (Zeilen, dunkle Ecken), blinkendem „▶ PRESS START“, Spielfeld mit Pixelrahmen und harten Schatten, eckigen Chips mit
  ▶-Markierung, Arcade-Tasten, die beim Klick einrasten, grünem „WEITER ▶“, Level-Kästchen statt Punkten und Preisen
  in Pixelschrift. Spielmodus im Automaten-Look: SCORE-Anzeige, Blockbalken, eckige Abzeichen und Meldungen.
  Auch einzeln wählbar als Stil „Arcade“.

### Behoben
- Admin-Live-Vorschau lädt jetzt auch Schriften, die nur die Vorschau braucht (vorher fehlte z. B. die Pixelschrift).
- **Glücksrad im Analog-Radio-Design** (*Glücksrad → Darstellung → „Analog-Radio“*): Röhrenradio aus Holz mit
  Lautsprecher-Stoff, beleuchteter Senderskala (88–108 MHz) und Sendersuchknopf. Die Felder des Rads sind die
  „Sender“ auf der Skala (höchster Rabatt mit ★). Der Kunde dreht am Knopf (mit Maus oder Finger im Kreis ziehen)
  oder tippt ihn an – der Zeiger sucht mit leisem Rauschen über die Skala und bleibt beim gewonnenen Sender stehen,
  das „magische Auge“ leuchtet grün. Funktioniert eingebettet und als Pop-up, auch mit Tastatur. Die Auslosung
  bleibt beim Server. Admin-Vorschau mit Probedrehen in beiden Darstellungen.
- **Spielmodus:** Der geheime Erfolg „Sparfuchs“ wurde entfernt – es gibt jetzt sieben Erfolge (700 XP); die Level
  bleiben gleich (Radiolegende ab 600 XP).
- **Glücksrad als Pop-up** (*Glücksrad → Anzeige*): wahlweise eingebettet im letzten Schritt (wie bisher) oder als
  Pop-up beim Start, bei „Buchung“ oder bei „Anfrage“. Das Pop-up kommt einmal pro Besuch, lässt sich mit ×, Esc
  oder Klick daneben schließen; dann bleibt unten links ein kleiner „🎡 Glücksrad“-Knopf zum Wiederöffnen. Nach dem
  Drehen „Weiter“ – ein Gewinn wird sofort im Preis abgezogen und steht auch im letzten Schritt.
- **Rabatt-Glücksrad** (*Preise → Glücksrad*, auch für die Verkaufsleitung; standardmäßig aus): Im letzten
  Schritt dreht der Kunde einmal am Rad und gewinnt ggf. einen Rabatt auf den Gesamtbetrag (auch bei
  Komplettpaketen). Bis zu 12 Felder mit Beschriftung, Rabatt (0–50 %, 0 = Niete) und Gewichtung; der Admin zeigt
  die Chance je Feld, die Gewinnchance und den durchschnittlichen Rabatt pro Dreh, dazu eine Vorschau mit
  „Probedrehen“. Einstellbar: Gültigkeit des Gewinns (Standard 72 Stunden) und ob er mit anderen Rabatten
  kombinierbar ist (Standard: nein – der bessere Rabatt gilt).
- **Fälschungssicher:** Wo das Rad stehen bleibt, entscheidet der Server; der Gewinn ist ein signiertes Token, das bei
  der Preisberechnung geprüft wird. Neu laden hilft nicht – dieselbe IP-Adresse bekommt 24 Stunden lang dasselbe
  Ergebnis (die IP liegt dafür nur im Arbeitsspeicher, nicht in der Datenbank). Wird das Rad abgeschaltet oder das
  gewonnene Feld entfernt, verfällt der Gewinn. Der Rabatt erscheint als „Glücksrad-Rabatt … %“ in Preis,
  Anfrage und PDF. Im Spielmodus gibt es Konfetti, und der geheime Erfolg „Sparfuchs“ wird freigeschaltet.
- **Spielmodus mit mehr Action:** Erfolge als große Abzeichen (60 px, am Handy 50 px) mit Namen darunter und
  farbigem Ring; gesperrte grau und gestrichelt, sie wackeln beim Drüberfahren. Beim Freischalten springt das
  Abzeichen auf, ein Funkenkranz sprüht, „+XP“ steigt auf und es leuchtet ein paar Sekunden. Dazu ein dickerer
  XP-Balken mit Glanzeffekt, größeres Level-Abzeichen, schwebendes Icon bei „Nächste Mission“ und größere
  Erfolgsmeldungen. Am Handy vier Abzeichen pro Reihe.
- **Gutscheincode einblendbar:** Im letzten Schritt steht statt des Eingabefelds nur der Link „Gutscheincode
  eingeben?“ – ein Klick blendet das Feld ein (Cursor steht gleich drin). Ist schon ein Code eingetragen,
  bleibt das Feld offen, auch beim Zurück- und Weiterblättern.
- **Pakete ohne Werbespot** (*Komplettpakete → „Studiospot zubuchbar“*): ausschalten bei Paketen, für die kein
  Spot produziert wird (z. B. Gewinnspiel, Sponsoring, Moderation). Der Kunde sieht dann nur „Spot-Text &
  Hörbeispiel – für dieses Paket wird kein Studiospot benötigt“; Extras „nur mit Studiospot“ sind ausgeblendet,
  der Server lehnt einen Studiospot zu diesem Paket ab. Wechselt der Kunde zu einem anderen Paket oder zu
  „Individuell“, gilt seine vorherige Studiospot-Wahl wieder. Bestehende Pakete: weiterhin zubuchbar.
- **Spielmodus (optional)** – neue Variante **„Spielerisch“** bzw. *Anordnung → Spielmodus*: Über dem Konfigurator
  eine Punkteleiste mit Level (Newcomer → Jingle-Profi → Studio-Star → Radiolegende), XP-Balken, „Nächste
  Mission“ und acht Erfolgen zum Freischalten (u. a. „Wortakrobat“, „Erste Hörprobe“, „Sendeplan steht“,
  geheimer Erfolg „Sparfuchs“ bei einem Rabatt, „ON AIR!“ beim Absenden). Erfolgs- und Level-Meldungen,
  Konfetti bei Hörprobe und Anfrage, verspielte Animationen. Läuft nur im Browser, speichert nichts;
  bei „Bewegung reduzieren“ ohne Animationen. Standard: aus.
- **„Zurück zur Startseite“** nach dem Absenden der Anfrage (neben „Kostenaufstellung als PDF“): öffnet den
  Konfigurator leer ab Schritt 1 – die abgeschickte Anfrage bleibt gespeichert.
- **Startseite für die Verkaufsleitung:** Nach dem Login landet die Verkaufsleitung nicht mehr direkt in den
  Preis-Einstellungen, sondern auf einer eigenen Übersicht: Kacheln für alle ihre Bereiche (mit Anzahl aktiv/
  inaktiv und kurzer Erklärung), „Zu erledigen“ (kein aktives Paket, Sender/Pakete ohne Sendegebiet), Tabelle
  der aktiven Komplettpakete (Art.-Nr., Preis, Schaltungen, Laufzeit, empfohlene Laufzeit), „Preise auf einen
  Blick“ und die aktiven Rabatte. Erreichbar auch über „Radiospot Admin“ oben links.
- **Fortschrittsanzeige beim Erstellen der Hörprobe:** Balken mit Prozent und wechselnden, lustigen Texten
  passend zum Arbeitsschritt – „Jetzt wird mal eingesprochen …“, „Es wird gemixt …“, „Es wird gemastert …“,
  „Gleich ist es soweit …“ (ohne Musik: „Es wird geschnitten …“). Dauert es länger, kommen Sprüche wie
  „Der Tontechniker holt noch Kaffee …“. Am Ende kurz „Fertig – Bühne frei für Ihren Spot!“, dann startet
  der Player. Die Anzeige richtet sich nach der Textlänge (der Server meldet keinen Zwischenstand).
- **Layout-Designer** (*Design → Layout-Varianten*): vier fertige Bildschirm-Designs zum Wechseln –
  **Klassisch** (wie bisher), **ENERGY Neon** (dunkel, Magenta-Leuchtrahmen, Raster, zentrierte Großbuchstaben,
  breit – nach dem Ad-Boost-Mockup, mit passender Farbvorlage), **Studio** (breit, Schritte als Seitenleiste)
  und **Kompakt** (kleiner Kopfbereich, Punkte-Navigation). Je Variante ein Mini-Schema, „Ansehen“ (nur
  Vorschau) und „Übernehmen“.
- **Anordnung im Detail** frei kombinierbar: Stil (Klassisch/Neon/Flach), Breite, Überschrift (groß links,
  zentriert, klein, ausgeblendet), Schritt-Navigation (Senderskala, nummerierte Punkte, Seitenleiste),
  Kopfzeile (Logo links oder zentriert), Großbuchstaben, Wellen-Animation.
- **Live-Vorschau** mit Umschalter **Desktop/Handy**: Änderungen erscheinen sofort, ohne zu speichern
  (nur für eingeloggte Admins sichtbar). Am Handy wird die Seitenleiste automatisch zur Punkte-Leiste.
- Farbvorlage **„ENERGY Neon“**.
- **Empfohlene Laufzeit bei Paketen** (*Komplettpakete → „Empfohlene Laufzeit (Tage)“*): Empfehlung für den
  Verkauf, getrennt von der festen Laufzeit. Wird gespeichert und im Admin sowie in der Admin-API angezeigt,
  im Konfigurator noch nicht verwendet – Grundlage für eine spätere Funktion.

### Datenschutz
- **Schriften lokal statt von Google (DSGVO):** Alle 22 Schriften der Auswahl liegen jetzt im Projekt
  (`app/static/fonts`, je mit Lizenzdatei OFL) und werden über `/fonts.css` vom eigenen Server ausgeliefert.
  Besucher des Konfigurators und der Seiten AGB/Datenschutz haben keine Verbindung mehr zu Google
  (keine IP-Übertragung). Das Aussehen bleibt gleich.
- Eine „andere Google-Font“ im *Design* wird beim Speichern einmalig vom Server heruntergeladen und unter
  `media/fonts` abgelegt; gibt es sie nicht, erscheint eine Fehlermeldung und nichts wird geändert.

---

## 25.10.2026

### Neu
- **Kampagnenzeitraum mit Datumswähler** (Schritt „Buchung“): bei Paketen mit Laufzeit nur der Beginn – das Ende
  wird berechnet –, sonst Beginn und Ende; dazu „Laufzeit … Tage · ca. … Schaltungen pro Tag“. Pflicht für die
  Anfrage; erscheint in Zusammenfassung, Anfrage, PDF und E-Mail-Vorschlag. Der Server prüft Vorlaufzeit,
  Ende ≥ Beginn und berechnet das Ende bei Paketen selbst.
- **Pakete: Schaltungen und Laufzeit** (*Komplettpakete → „Schaltungen“ und „Laufzeit (Tage)“*; 0 = Zeitraum frei).
- **Vorlaufzeit** (*Preis-Einstellungen*, Standard 3 Tage): frühester Kampagnenbeginn.
- **Artikelnummer bei Komplettpaketen** (*Komplettpakete → Artikelnummer*): erscheint in der Paketliste im Admin,
  in der Anfrage, im PDF („Art.-Nr. …“) und damit auch im E-Mail-Versand.
- **„Individuell“ abschaltbar** (*Preis-Einstellungen → Buchungsarten*, auch für die Verkaufsleitung):
  ausgeschaltet sehen Kunden nur die Komplettpakete, der Umschalter verschwindet; Einzelbuchungen werden auch
  serverseitig abgelehnt. Gibt es kein aktives Paket, bleibt „Individuell“ verfügbar, damit Kunden buchen können.
- **Pakete mit mehreren Sendern zugleich** (*Komplettpakete → Senderwahl → „Alle angehakten Sender sind im Paket
  enthalten“*): keine Auswahl, die Paketkarte zeigt „Enthalten: ● Radio Energy ● Radio Nostalgie“, die Karte jeden
  Sender in seiner Farbe (gemeinsame Gebiete rot/blau gestreift). Kalkulation und PDF nennen alle Sender.
  Standard bleibt „Kunde wählt einen der angehakten Sender“.
- **Zweite Schreibtisch-Verknüpfung „Radiospot im WLAN starten“:** `install-mac.command` legt sie neben
  „Radiospot starten“ an (startet `start-mac-netzwerk.command`, erreichbar für Handy und andere Rechner im WLAN).
- **Senderwahl bei Komplettpaketen** (*Komplettpakete → Wählbare Sender*): Der Kunde wählt im Paket den Sender,
  z. B. Radio Energy oder Radio Nostalgie – Karte (in der Senderfarbe), Kalkulation, Zusammenfassung, PDF und
  Anfrage zeigen den gewählten Sender. Pauschalpreis bleibt gleich. Pakete ohne angehakte Sender haben wie bisher
  einen festen Sendeumfang (z. B. Kombi).
- **Eigene Kartenfarbe je Sender** (*Sender & Streams → Farbe auf der Karte*), z. B. Blau für Radio Nostalgie –
  dessen Sendegebiete leuchten dann blau. Auch Sendegebiete können eine eigene Farbe haben (für Pakete).
  Nutzen zwei gewählte Sender dasselbe Gebiet, wird es rot/blau gestreift, UKW-Kreise am selben Standort liegen
  ineinander; die Liste zeigt je Gebiet farbige Punkte mit den Sendern. Radio Nostalgie bekommt einmalig Blau
  (#0057b8), falls noch keine Farbe gesetzt ist. Farbauswahl mit Vorlagen (Energy-Rot, Nostalgie-Blau …).
- **„Spot & Buchung“ mit weniger Scrollen:** Am Computer links die Schaltung (Komplettpaket / Individuell),
  Extras und Preis, rechts daneben die Reichweiten-Karte, die beim Scrollen sichtbar bleibt. Kompaktere
  Paketkarten (Name und Preis in einer Zeile, Leistungen als kurze Zeile), Umschalter als zwei gleich breite
  Knöpfe. Etwa 40 % weniger Höhe; am Handy Reihenfolge Auswahl → Karte → Preis.
- **Überschrift und Untertitel im Admin einstellbar** (*Design → Texte & Überschrift*): Text der großen
  Überschrift („Ihr Radiospot, angehört, bevor er läuft.“), Untertitel oben rechts (auch im PDF) und die
  Größe der Überschrift per Regler (60–170 %). Leer = Standardtext; Farbvorlagen lassen die Texte unverändert.
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
- **UKW einheitlich als Kreis:** Hat ein UKW-Sendegebiet einen Sender-Standort, zeigt die Karte nur den Kreis um den
  Sender – auch wenn Bundesländer angehakt sind (vorher leuchtete z. B. ganz Tirol, Salzburg aber nicht).
  Bundesländer leuchten bei UKW nur noch ohne Standort.
- Legende der Karte: „DAB+ – ganz Österreich“ statt „DAB+ – ganzes Bundesland“ (bei einem regionalen DAB+-Gebiet
  steht „DAB+ – leuchtende Bundesländer“).
- **Karte blieb bei Paketen mit Senderwahl dunkel**, wenn die Sendegebiete beim Paket statt beim Sender angehakt
  waren. Jetzt gelten die Sendegebiete des Pakets (in der Farbe des gewählten Senders, z. B. Blau für Nostalgie),
  sonst die des Senders. Das Dashboard zeigt Sender und Pakete ohne Sendegebiet an.
- **Eigener Spot-Text:** Wer in Schritt 2 den Text selbst schreibt, kann jetzt weiterklicken – Firma,
  Kernbotschaft und Call-to-Action sind nur noch für den KI-Vorschlag nötig. Ist „Weiter“ gesperrt, steht
  darunter ein Hinweis, was fehlt.
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
