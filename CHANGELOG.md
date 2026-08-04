# Changelog

Alle nennenswerten Änderungen an PoE-VIEW2. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.0.0/), Versionierung
nach [SemVer](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Hinzugefügt

- Hilfe-Fenster (Fragezeichen-Knopf in der Toolbar) mit elf Themen: was
  die Spalten bedeuten, wofür die Farbfilter stehen, wie Suche und
  Refresh-Modi arbeiten, warum die beiden Zähler in "Load All Tabs"
  auseinanderlaufen, was die Symbole im Item-Verlauf heißen, warum die
  Wertspalte in SSF-Ligen leer bleibt, und wo die eigenen Daten liegen.
  Das Fenster ist nicht modal — es kann offen bleiben, während man das
  Erklärte ausprobiert.
- Statuszeile zeigt jetzt "Updated HH:MM:SS" — wann der Inhalt der
  Tabelle zuletzt neu aufgebaut wurde. Damit ist auf einen Blick
  erkennbar, wie frisch das Angezeigte ist.
- Datum und Uhrzeit rechts oben in der Toolbar. Zusammen mit dem
  "Updated"-Zeitstempel der Statuszeile ist damit auch auf einem
  Screenshot allein erkennbar, wie aktuell die angezeigten Daten sind.
- Neben dem "Updated"-Zeitstempel erscheint "unchanged for 12m", wenn
  die Daten zwar weiter eintreffen, aber unverändert bleiben. Damit ist
  "wir holen nichts mehr" von "wir holen, die API liefert denselben
  Stand" zu unterscheiden — letzteres ist der Normalfall, solange im
  Spiel kein Zonenwechsel stattgefunden hat.

### Geändert

- Statuszeile aufgeräumt: Die beiden Refresh-Angaben sind zu einer
  zusammengefasst ("Single — next update in 1s · 0/94 tabs"), und der
  Hinweis zur fehlenden Zugehörigkeit zu Grinding Gear Games steht jetzt
  im Hilfe-Fenster unter "About" statt dauerhaft in der Statuszeile.

### Behoben

- Item-Eigenschaften mit Platzhaltern wurden falsch dargestellt: Statt
  "Consumes 35 of 65 Charges on use" stand dort "Consumes {0} of {1}
  Charges on use: 35" — die Platzhalter blieben stehen und der zweite
  Wert fehlte ganz. Betraf das Detail-Panel, die vergrößerte Item-
  Ansicht, den CSV-Export und den Suchindex.
- Item-Verlauf: Nach einem Programmstart tauchten dort Ereignisse auf,
  die längst vergangen waren — mit der aktuellen Uhrzeit versehen. Der
  Verlauf selbst wird nicht gespeichert, der Inventarstand der
  Charaktere schon; der erste Abruf nach dem Start verglich deshalb
  gegen einen womöglich wochenalten Stand. Protokolliert wird jetzt erst
  ab dem zweiten Abruf eines Charakters, der erste setzt nur die
  Vergleichsbasis.
- Gleiche Ursache, zweite Anzeige: Beim ersten Abruf nach dem
  Programmstart wurden Inventarzeilen türkis hervorgehoben und
  verschwundene Items grau angehängt, obwohl die Änderungen Tage
  zurücklagen. Auch die Hervorhebung vergleicht jetzt erst ab dem
  zweiten Abruf eines Charakters.

## [0.5.1] - 2026-08-04

### Behoben

- Datenverlust beim Ab- und Wieder-Anmelden: Wer sich abmeldete und
  danach erneut mit demselben Konto anmeldete, bekam seine gespeicherten
  Truhen- und Charakterdaten nicht zurück — der leere Zustand wurde
  stattdessen über die vorhandene Datei geschrieben. Beim nächsten Start
  wirkte es, als müsse alles neu geladen werden. Die Daten kommen jetzt
  nach dem erneuten Anmelden wieder von der Platte.
- Zusätzlicher Schutz gegen Datenverlust: Die lokale Datendatei wird
  nicht mehr überschrieben, wenn dabei der allergrößte Teil des
  gespeicherten Bestands verlorenginge. Im Zweifel bleibt lieber zu viel
  gespeichert — beide bisherigen Datenverluste entstanden genau so, und
  der Schutz greift unabhängig davon, welcher Programmteil das
  Speichern auslöst.

## [0.5.0] - 2026-08-03

### Hinzugefügt

- Logout: der Konto-Button in der Toolbar öffnet nach dem Login jetzt ein
  Menü mit "Log out", statt einfach nur deaktiviert zu sein. Vorher gab
  es keinen Weg, sich mit einem anderen GGG-Konto anzumelden, ohne den
  gespeicherten Eintrag von Hand aus dem Windows-Anmeldeinformations-
  manager zu löschen. Ein Logout widerruft nur lokal die Anmeldung bei
  PoE-VIEW2 — die Freigabe auf der GGG-Kontoseite bleibt davon
  unberührt, dort lässt sie sich bei Bedarf separat entziehen.
- Cache-Trennung pro Konto: jedes GGG-Konto bekommt jetzt seine eigene
  lokale Datendatei statt einer gemeinsamen. Vorher blieben Stash-Baum,
  Items und Charaktere eines vorherigen Kontos nach einem Kontowechsel
  im Speicher stehen und vermischten sich mit dem neuen. Nichts wird
  dabei gelöscht — jedes Konto behält seinen eigenen Stand, auch beim
  Zurückwechseln. Existiert die kontospezifische Datei noch nicht (z. B.
  gleich nach der Umstellung), wird die alte gemeinsame Datei automatisch
  übernommen, sofern sie zum selben Konto gehört — die alte Datei bleibt
  dabei unverändert erhalten.
- Item-Verlauf: reine Mengenänderungen (z. B. Currency-Stacks) tauchen
  jetzt als eigenes Ereignis auf und wandern dabei ganz nach oben, mit
  Vermerk, wie viel sich geändert hat (z. B. "53 (+3)"). Vorher wurden
  solche Änderungen komplett ignoriert — nur echte Neuzugänge und
  verschwundene Items landeten im Verlauf. Gilt nur für das
  Charakter-Inventar, nicht für Stash-Fächer.
- Eigenes Anwendungssymbol: PoE-VIEW2 hat jetzt ein eigenes Icon in
  Explorer, Taskleiste und Fenstertitel statt des allgemeinen
  Standardsymbols. Es steckt in sieben Größenstufen in der Datei, wobei
  die kleinen Stufen eine bewusst vereinfachte Fassung der Grafik
  verwenden — sonst würde der Runenring bei 16 Pixeln unkenntlich.
- Live-Zonenanzeige in der Toolbar: zeigt die zuletzt aus der Client.txt
  erkannte Zone an — unabhängig davon, ob danach tatsächlich ein Refresh
  folgt (Pause-Modus/Rate-Limit können das weiterhin verhindern). Auch
  eine Diagnose-Anzeige nebenbei: bleibt sie leer, war der Zonen-
  Beobachter entweder deaktiviert oder hat nichts erkannt.

### Behoben

- Der Zonenwechsel-Refresh löste in Wirklichkeit nie aus: die
  Datei-Überwachung von Qt bemerkt neue Zeilen in PoEs Client.txt nicht,
  solange das Spiel läuft. Aufgefallen ist das erst durch die neue
  Zonenanzeige, die dauerhaft leer blieb; die Daten waren trotzdem nie
  veraltet, weil der reguläre getaktete Refresh unabhängig davon
  weiterlief — der Zonenwechsel beschleunigt ihn nur. Die Erkennung
  prüft die Datei jetzt selbst im 2-Sekunden-Takt.
- Ein Liga-Wechsel im Dropdown leerte die Itemliste bisher nicht — der
  zuletzt angezeigte Fach- oder Charakterinhalt der vorherigen Liga blieb
  sichtbar stehen, obwohl keine Auswahl mehr dazu passte. Die Liste wird
  jetzt beim Liga-Wechsel geleert, bis erneut ein Tab oder Charakter
  ausgewählt wird.

## [0.4.0] - 2026-08-03

### Hinzugefügt

- CSV-Export: deutlich breiterer Spaltensatz statt bisher 10 fester
  Spalten — jetzt u. a. Position (Tab/X/Y), Kategorie, alle
  Anforderungen (Level/Str/Dex/Int), Sockets/Links, sämtliche Mod-Arten
  (Implicit/Explicit/Crafted/Enchant/Fractured/Veiled/Utility),
  Influences, Merkmale (Mirrored/Fractured/Synthesised/Veiled/Replica/
  Searing/Tangled), Notiz, Chaos-Wert und Item-ID. Optional zusätzlich
  eine `RawJSON`-Spalte mit dem vollständigen, unveränderten API-Objekt
  je Item — über einen zweiten Dateityp im Speichern-Dialog wählbar,
  bewusst nicht die Voreinstellung (Dateigröße bei großen Exporten).
- Export per Rechtsklick auf ein Item: "Export selected items" (die
  markierten Zeilen, Mehrfachauswahl per Strg-/Umschalt-Klick möglich)
  und "Export visible items" (identisch zum bisherigen Toolbar-Knopf),
  jeweils mit der Anzahl im Menütext. "Export visible items" steht jetzt
  auch im Rechtsklick-Menü des Stash-Baums (auf einem Fach, einem Ordner
  oder im leeren Bereich) und der Charakterliste (mit oder ohne
  Charakter unter dem Cursor) zur Verfügung.
- Der vorgeschlagene CSV-Dateiname nennt jetzt zusätzlich die
  exportierte Item-Anzahl und einen Zeitstempel (z. B.
  `poe-view2-Settlers-Chaos-Orb-12items-2026-08-03_1542.csv`) — vorher
  schlugen "Export selected items" und "Export visible items" aus
  derselben Ansicht denselben Namen vor.
- Mehrfachauswahl im Stash-Baum: Strg-/Umschalt-Klick auf mehrere Fächer
  oder einen Ordner (auch die "Tier N"-Gruppen im Map-Stash) zeigt deren
  Items zusammen an. Zeigt ausschließlich bereits gecachte Items — löst
  nie selbst einen Abruf aus, nicht gecachte Fächer werden in der
  Statuszeile genannt ("3 tabs selected: 2 loaded, 1 never loaded").
  Einzelauswahl eines Fachs verhält sich unverändert, inklusive
  automatischem Nachladen bei Cache-Miss.
- Das Suchfeld wird beim Auswählen eines Stash-Tabs, Ordners oder
  Charakters jetzt automatisch geleert und die globale Suche beendet —
  vorher blieb ein Suchtext stehen und filterte unbemerkt weiter, sobald
  man in eine andere Ansicht wechselte. Die globale Suche selbst bleibt
  von jeder Ansicht aus uneingeschränkt nutzbar.

## [0.3.0] - 2026-08-02

### Behoben

- Ein Spalten-Filter auf der Tab-Spalte (Header-Rechtsklick) überlebte
  bisher den Wechsel von der Charakter- zur Truhen-Ansicht (oder zwischen
  zwei Truhenfächern) — passte der Filterwert dort auf keinen einzigen
  Fach-/Slot-Namen, verschwanden alle Items kommentarlos, ohne sichtbaren
  Hinweis (die Tab-Spalte ist im Einzelfach-View automatisch ausgeblendet,
  der 🔍-Marker also unsichtbar). Ein solcher Filter wird jetzt beim
  tatsächlichen Wechsel der angezeigten Quelle automatisch entfernt.
  Filter auf anderen Spalten (Name, Base, Value, …) bleiben unverändert
  über einen View-Wechsel hinweg erhalten.
- Refresh-Modus "Stash": bereits geladene Remove-only-Fächer (können nur
  schrumpfen, nie wachsen) wurden im Rundlauf wie jedes andere gefüllte
  Fach behandelt und damit unnötig oft neu geladen. Sie kommen jetzt nur
  noch dran, wenn es sonst kein anderes gefülltes Fach gibt — die gleiche
  Nachrangigkeit, die der Auto-Refresh-Modus schon hatte.
- Preis-Anzeige: Ein poe.ninja-Abruf ohne eine einzige Preiszeile (z. B.
  ein transienter Ausrutscher) wurde bislang wie ein normaler Erfolg 6
  Stunden lang gecacht — eine Liga konnte dadurch stundenlang ohne jeden
  Preis dastehen, obwohl poe.ninja längst wieder normal antwortete. Ein
  solches Ergebnis läuft jetzt nach 1 Stunde statt 6 Stunden ab.
  Hinweis: SSF-Ligen (z. B. "Solo Self-Found") werden von poe.ninja
  grundsätzlich nicht getrackt — ohne Spieler-Handel gibt es dort keine
  Handelsaktivität, aus der sich Preise ableiten ließen. Das ist eine
  Grenze der Datenquelle, kein Fehler in PoE-VIEW2.
- "Load All Tabs" wirkte bei großen Truhen eingefroren: Der
  Fortschrittsbalken zählte Truhenfächer, die Arbeit fällt aber pro Abruf
  an. Ein Map-Stash bündelt hunderte Sektionen in einem einzigen Fach —
  die Anzeige stand dadurch über eine Stunde auf derselben Zahl. Der
  Balken läuft jetzt über die tatsächlichen Abrufe, das Label nennt
  zusätzlich das Fach ("Section 128 of 1088 · tab 3 of 519") und eine
  geschätzte Restzeit.
- Unique-Stash: Die selbst vergebenen Fach-Namen ("Ring", "Sceptre", …)
  gingen verloren, sobald das Eltern-Fach erneut geladen wurde — nach
  einem "Load All Tabs"-Lauf hießen dadurch fast alle Unterfächer wieder
  "UniqueStash". Die Namen bleiben jetzt erhalten; bereits betroffene
  Caches füllen sich beim nächsten Laden des Eltern-Fachs wieder auf,
  soweit die Items noch zwischengespeichert sind.
- Unique-Stash: Kinder eines Remove-only-Tabs zeigten nur noch
  "(Remove-only)" statt der Kategorie ("Ring (Remove-only)") — der
  GGG-Suffix im Namensfeld wurde fälschlich als vollständiger Name
  gewertet.
- Rate-Limit-Dashboard zeigt jetzt sofort "(Paused)" neben dem
  Policy-Namen, sobald der Refresh-Modus "Pause" aktiv ist.
- Rate-Limit-Dashboard: der angezeigte Verbrauch je Regel zeigt jetzt immer
  den zuletzt von GGG gemeldeten Rohwert. Reale Header-Logs zeigten, dass
  GGGs Zähler nicht gleitend pro Treffer altert, sondern in Blöcken von
  ~60 Sekunden auf einmal sinkt — die vorherige, feiner gedachte
  Interpolation traf dadurch systematisch daneben. Die tatsächliche
  Warte-Entscheidung war davon nie betroffen und bleibt unverändert
  konservativ.
- Die Refresh-Modi "Single" und "Stash" liefen nach einiger Zeit in eine
  fünfminütige Zwangspause. Ihr gleichmäßiger Takt war so berechnet, dass
  er das Rate-Limit gerade eben nicht reißt — er unterstellte dabei aber,
  der einzige Verbraucher zu sein. Klicks auf noch nicht geladene Fächer,
  Liga-Wechsel und die Abrufe direkt nach dem Programmstart füllen dasselbe
  Kontingent jedoch mit, wodurch die verbleibende Marge von einer einzigen
  Anfrage sofort aufgebraucht war. Der Takt pausiert jetzt selbsttätig,
  sobald das Fenster zu voll ist, und nennt den Grund in der Statuszeile.
- Liga-Wechsel trugen weiterhin zur 300s-Zwangspause bei: der Abruf der
  Fach-LISTE der neu gewählten Liga lief ungebremst, und eine Lücke im
  gerade erst gebauten Rate-Limit-Schutz ließ auch den Refresh-Modus-Takt
  direkt danach ungebremst durch. Beides behoben — der Listen-Abruf
  entfällt jetzt bei zu vollem Fenster (der gecachte Baum bleibt sichtbar),
  und der Refresh-Modus-Schutz greift jetzt auch unmittelbar nach einem
  Liga- oder Modus-Wechsel zuverlässig.
- "Load All Tabs", "Refresh" und der Refresh-Modus-Umschalter blieben ohne
  gültigen Login anklickbar, solange noch ein Daten-Cache aus einer
  früheren Sitzung sichtbar war — der Fortschrittsdialog von "Load All
  Tabs" öffnete sich dann, hing aber für immer bei 0 %, weil der Job vom
  Worker lautlos verworfen wurde. Diese drei Online-Funktionen sind jetzt
  gesperrt, solange kein Login besteht; Stash-Baum, Charakterliste und
  Liga-Auswahl bleiben zum Durchsuchen des Caches weiter nutzbar.

### Hinzugefügt

- Frei konfigurierbare Item-Nachschlagewerke: Über den Settings-Dialog
  (Reiter "External Tools") lassen sich eigene Seiten mit Name und
  URL-Vorlage eintragen, in der `{slug}` durch den Item-Namen ersetzt
  wird. Ein Rechtsklick auf ein Item öffnet die so hinterlegten Seiten.
  Die Liste ist **ab Werk leer** — PoE-VIEW2 bringt bewusst keine fremde
  Seite mit und kontaktiert von sich aus keine; wer einen Eintrag anlegt,
  trifft diese Entscheidung selbst. Der Slug berücksichtigt dabei, dass
  nur Uniques einen eigenständig auffindbaren Namen haben: bei allen
  anderen Seltenheiten wird der Basis-Typ verlinkt statt eines zufällig
  gewürfelten Namens.
- Charakter-Item-Verlauf: ein neues, aufziehbares Panel unterhalb der
  Item-Tabelle protokolliert die letzten 120 Items, die neu im
  Charakter-Inventar aufgetaucht oder daraus verschwunden sind (↑/↓) —
  über alle Charaktere hinweg, unabhängig davon, welcher gerade angezeigt
  wird. Damit lässt sich kurz nachschauen, was man gerade in die Truhe
  gelegt, verkauft oder gehandelt hat. Eigenes, kompaktes Spaltenformat
  (Zeit, Charakter, Ereignis, Icon, Name, Base, Stack, Value);
  standardmäßig auf eine Zeile eingeklappt, per Ziehen am Splitter
  aufziehbar. Rechtsklick/Doppelklick funktionieren wie in der
  Haupttabelle (externe Tools, vergrößerte Ansicht).
- Charakter-Ansicht: Beim Beobachten eines Charakter-Inventars (z. B. per
  Zonenwechsel-Trigger, siehe unten) werden Zeilen, die sich seit dem
  letzten Refresh geändert haben oder neu hinzugekommen sind, türkis
  hervorgehoben. Aus dem Inventar verschwundene Items werden nicht
  sofort entfernt, sondern für einen Refresh-Zyklus grau und
  durchgestrichen angezeigt.
- Optionaler Zonenwechsel-Trigger für den Live-Refresh (Settings-Dialog,
  Reiter "Zone Refresh", standardmäßig AUS): PoE-VIEW2 kann die lokale
  Client.txt des Spiels beobachten (rein lesend, Pfad muss selbst
  eingetragen werden) und lädt die offene Truhe/den Charakter sofort neu,
  sobald PoE einen Zonenwechsel meldet — GGGs Stash-API liefert neue
  Daten offenbar ohnehin erst danach, gezieltes Nachladen spart also
  Rate-Limit-Budget gegenüber reinem Zeit-Takt.
- Neuer Settings-Dialog (⚙-Button in der Toolbar) mit einem Reiter
  "Columns": welche Item-Tabellen-Spalten sichtbar sind und in welcher
  Reihenfolge lässt sich dort per Häkchen und Drag & Drop einstellen,
  zusätzlich zum bisherigen schnellen Ein/Aus-Schalter im
  Header-Rechtsklickmenü. Beide Wege teilen sich denselben gespeicherten
  Stand.
- Fenster lässt sich nicht mehr kleiner als 800x600 ziehen — darunter
  wurden Bedienelemente in der Toolbar (u. a. das Suchfeld) hinter einem
  Overflow-Pfeil versteckt.
- Doppelklick auf ein Item öffnet eine vergrößerte Ansicht: großes Icon
  und der vollständige Property-/Mod-Text ohne die Zeilen-Kürzung des
  kompakten Detail-Panels. Bei Divination Cards zeigt sie das echte
  Karten-Artwork (GGGs eigenes CDN) statt des für jede Karte identischen
  generischen Icons aus der Stash-API, mit einem dekorativen
  Pergament-Rahmen angelehnt an die bekannte Karten-Optik.
- Doppelklick auf einen Charakter öffnet eine Paperdoll: Ausrüstung als
  Puppenlayout (Helm, Waffen, Rüstung, Ringe, Gürtel, Handschuhe, Stiefel,
  Flaschen, ggf. Waffentausch-Set/Trinket) statt flacher Tabellenzeilen,
  inklusive Liste der Jewels im Passiv-Baum. Klick auf einen Slot zeigt das
  Item im Detail-Panel.
- Item-Tabelle startet jetzt voreingestellt aufsteigend nach Wert sortiert
  statt in roher API-Reihenfolge — Items mit unbekanntem oder geringem
  Preis ("wahrscheinlich Schrott") gruppieren sich dadurch von selbst oben.
  Ein Klick auf eine andere Spalte überschreibt die Voreinstellung wie
  jede normale Sortierung.
- Rate-Limit-Dashboard: jede Regel zeigt jetzt zusätzlich eine grobe
  Schätzung, wann der Zähler das nächste Mal sinkt ("12/30 · 300 s · next
  in ~2:19", immer mit "~" — GGGs Zähler sinkt blockweise statt gleitend
  pro Treffer, sobald zwei Absenkungen beobachtet wurden, ist ihr
  ungefährer Rhythmus gelernt). Kurz nach dem Start kann bauartbedingt
  minutenlang nichts sinken — ohne diese Angabe sah der stillstehende
  Zähler wie ein Hänger aus.
- "Load All Tabs" zeigt im Fortschrittsdialog einen Sekunden-Countdown bis
  zum nächsten Abruf ("Next tab in 8s") und, falls das Rate-Limit gerade
  bremst, dessen Restzeit statt scheinbaren Stillstands. Zusätzlich springt
  der Stash-Baum jeweils auf das gerade abgerufene Fach und klappt es auf.
- Neuer Refresh-Modus **Pause**: keinerlei Hintergrund-Anfragen. Manuelle
  Klicks, die ⟳-Buttons im Baum und "Load All Tabs" funktionieren
  unverändert und bekommen das volle Rate-Limit-Budget.
- Log: jede Rate-Limit-Antwort schreibt jetzt zusätzlich eine Zeile mit den
  rohen X-Rate-Limit-Werten je Regel plus dem gelernten Absenkungs-Takt.
  Diese Rohdaten haben belegt, dass GGGs Zähler blockweise statt gleitend
  sinkt, siehe FALLSTRICKE_UND_WORKAROUNDS.md #45.
- Preis-Anzeige über poe.ninja: neue **Value**-Spalte in der Item-Tabelle
  (Chaos-Wert × Stack, Anzeige in Chaos oder Divine je nach Höhe) sowie
  Gesamtwert der sichtbaren Items in der Statuszeile. Umfasst Currency,
  Fragmente, Uniques (inkl. 5-/6-Link-Preise), Gems (exakt nach
  Level/Qualität/Corrupted), Divination Cards, Scarabs, Essences, Fossils
  u. a. — bewusst ohne Rare-Item-Basispreise. Unbekannte Preise bleiben
  leer statt 0; Items unter einem Chaos werden dezent abgeblendet. Preise
  werden pro Liga bis zu 6 Stunden gecacht.
- `Item.sockets`/`Item.max_links` im Datenmodell (Grundlage der
  Link-genauen Unique-Preis-Zuordnung).
- Neue **Base**-Spalte in der Item-Tabelle (`item.baseType`, z. B. "Sun
  Plate", "Crimson Jewel") — anders als Name bei Uniques/Rares immer die
  reine Item-Basis statt eines Fantasienamens.
- Item-Detail-Panel zeigt jetzt Itemlevel, Charakter-Levelanforderung und
  Attributs-Anforderungen (Str/Dex/Int) sowie eine "Unidentified"-Markierung
  für unidentifizierte Items (neben "Corrupted").
- **Regex-Suche** (Umschalter ".*" neben dem Suchfeld, standardmäßig an):
  Die Suche versteht jetzt reguläre Ausdrücke wie PoEs eigene Truhensuche.
  Sockets stehen dafür in derselben Schreibweise im Suchindex wie im Spiel
  ("R-R-G"), sodass auf poe.re zusammengeklickte Muster unverändert
  funktionieren — etwa `r-r-g|r-g-r|g-r-r` für einen 3-Link mit zwei roten
  und einem grünen Socket oder `(-\w){5}` für 6-Links. Ein unfertiges
  Muster fällt still auf die normale Textsuche zurück.

## [0.2.0] - 2026-07-29

### Hinzugefügt

- Refresh-Modus-Dropdown (Auto / Single / Stash) in der Toolbar: Single
  hält gezielt die aktuell gewählte Zeile aktuell, Stash zyklisiert durch
  die ganze Truhe — beide in einem gleichmäßigen, aus den echten
  Rate-Limit-Regeln abgeleiteten Takt statt eines Bursts. Stash bevorzugt
  gefüllte Fächer, hängt aber nach jeder vollständigen Runde durch diese
  automatisch einen Check für das nächste noch leere Fach an (Häufigkeit
  passt sich an die Truhengröße an) — reihum der Fächerreihenfolge nach,
  sodass ein im Spiel nach vorne verschobenes Fach automatisch schneller
  wieder drankommt.
- Sichtbarer Countdown bis zum nächsten Auto-Refresh-Tick bzw. der Grund,
  warum er gerade pausiert (Rate-Limit, Token, archivierte Liga, …).
- Stash-Baum: Name-Spalte skaliert automatisch mit dem Panel, Anzahl- und
  Status-Spalte bleiben dadurch immer sichtbar.
- Stash-Baum: Kontextmenü bietet jetzt "Expand All"/"Collapse All" für
  den ganzen Baum, unabhängig vom angeklickten Fach.
- Stash-Baum: neue Pos.-Spalte zeigt die tatsächliche Position eines
  Fachs in der Truhen-Reihenfolge (leer bei Ordnern/Gruppen) — ein
  Zeilenheader-Äquivalent für Bäume, die (anders als die ItemList) keinen
  eigenen vertikalen Header kennen.
- Stash-Baum: Name-Spalte geladener Fächer wird nach Datenalter
  abgeblendet (aktuell < 1h normal, < 3h leicht, älter deutlicher),
  damit veraltete Fächer sofort auffallen. Das zuletzt aktualisierte Fach
  ist zusätzlich türkis markiert, bis das nächste Fach an der Reihe ist.
- Der Stash-Modus lädt nach jeder vollständigen Runde durch die Truhe
  zusätzlich einmal die Fach-**Liste** still nach — Umsortierungen, neue
  oder entfernte Fächer im Spiel werden dadurch automatisch erkannt, ohne
  auf einen manuellen Refresh oder Liga-Wechsel zu warten.
- Typ-Filter-Symbole (Toolbar) reagieren jetzt auf drei Gesten statt nur
  simplem An/Aus: ein Klick zeigt nur diesen einen Typ, Strg+Klick
  schaltet gezielt einen weiteren Typ dazu oder wieder raus, und
  Strg+Umschalt+Klick sowie Doppelklick zeigen wieder alle Typen.
- Summe der Stack-Größe der gerade sichtbaren (gefilterten) Items in der
  Statuszeile — reagiert live auf Suche, Spalten- und Typ-Filter. Erscheint
  nur, wenn genau ein Item-Name sichtbar ist (sonst wäre die Summe über
  verschiedene Item-Typen hinweg bedeutungslos).

### Geändert

- Oberfläche und README vollständig auf Englisch umgestellt (internationale
  Zielgruppe). Code-Kommentare und interne Doku bleiben Deutsch.
- Auto-Refresh reserviert nur noch 10 % statt 50 % des Rate-Limit-Budgets
  für manuelle Klicks.
- Ein Klick auf ein Fach im Single-/Stash-Modus löst keinen sofortigen
  Extra-Request mehr aus, sondern stellt das Fach an den Anfang der
  Abarbeitungsliste — es ist damit beim nächsten regulären Takt dran.
  Das kostet ein paar Sekunden, hält die Anfragerate aber konstant.
- "Load All Tabs" beginnt jetzt mit den ältesten bzw. noch nie geladenen
  Fächern statt mit der zufälligen Truhen-Reihenfolge — bricht man vorzeitig
  ab, sind die dringendsten Fächer schon durch.
- Stash-Baum standardmäßig breiter (340 statt 260px), damit Name-, Anzahl-,
  Status- und Pos.-Spalte ohne manuelles Nachziehen sichtbar sind;
  Fensterbreite entsprechend erhöht, damit die Toolbar-Suche nicht hinter
  "…" verschwindet.

### Behoben

- Rate-Limit-Dashboard und der Auto-Refresh-Zähler ("X von Y Stash-Tabs")
  konnten dauerhaft veraltet bzw. bei 0 hängen bleiben, obwohl im
  Hintergrund weiter aktualisiert wurde.
- Der gleichmäßige Refresh-Takt konnte kurzzeitig mit der Rate-Limit-Policy
  eines fremden Endpunkts statt der eigenen rechnen.
- Beim Programmstart lief ohne gültiges Token trotzdem eine Stash-Abfrage
  los und scheiterte mit HTTP 401. Ein solcher selbstverschuldeter 401
  verwarf zudem das gespeicherte Token, was einen erneuten Browser-Login
  erzwingen konnte.
- "Load All Tabs" lief nach rund 29 Fächern in die 300-Sekunden-
  Zwangspause. Es lädt jetzt im gleichmäßigen Takt (~11s pro Fach) einmal
  durch die ganze Truhe; der Refresh-Modus pausiert solange.
- Map- und Unique-Stash-Tabs wurden bei der Positionsnummer übergangen:
  sie selbst bekamen keine, während jede ihrer internen Sektionen eine
  eigene verbrauchte und alle folgenden Fächer verschob (in einer echten
  Truhe 923 statt 391 Positionen). Gezählt wird jetzt, was in der
  Truhen-Leiste tatsächlich einen Platz belegt.
- Derselbe Zähl-Fehler betraf auch den Auto-Refresh-Zähler in der
  Statuszeile ("X of Y stash tabs updated") — Y zeigte die aufgeblähte
  Zahl ladbarer Einheiten (939) statt der tatsächlichen Fächer-Anzahl.
- Die Reihenfolge im Stash-Baum wich sichtbar von der im Spiel ab: Fächer,
  die im Spiel in einem Ordner liegen, standen auf der obersten Ebene und
  schoben sich zwischen die echten Fächer, während die Ordner leer blieben
  (in einer echten Truhe 165 statt 44 Einträge oben). Ordner-Inhalte hängen
  jetzt in ihrem Ordner, auch ohne ihn vorher anzuklicken.
- Nach dem Öffnen eines Ordners konnten dessen Fächer doppelt im Baum
  stehen — einmal oben, einmal im Ordner (in einer Liga 47 Fächer).
- Und ein drittes Mal denselben Fehler: der Fortschrittsbalken von
  "Load All Tabs" zeigte z. B. "58/561" statt "58/391" — mehrere
  Map-/Unique-Sektionen desselben Fachs zählten als mehrere Tabs statt
  als einer.
- Der Stash-Modus konnte sich in eine endlose Kette von 300-Sekunden-
  Zwangspausen aufschaukeln: nach einer Pause feuerten zwei Requests
  direkt hintereinander, was die nächste Pause auslöste. Der Takt zählt
  jetzt ab dem Eintreffen der Antwort statt ab dem Absenden und hält
  zusätzlich einen Request Sicherheitsabstand zur Sperrschwelle.
- Die Suche fand Implicit-Mods nicht — nur explicitMods flossen in den
  Suchindex ein, obwohl implicitMods im Datenmodell längst vorhanden war.
- Die Suche filterte bei jedem Tastendruck sofort — bei einem liga-weiten
  Aggregat mit mehreren zehntausend Items (z. B. "All Tabs" oder "*")
  spürbar langsam. Der Zeilen-Filter läuft jetzt gedämpft (350ms nach dem
  letzten Tastendruck).
- Die neue Stack-Summen-Anzeige (siehe oben) konnte bei einer Suche über
  ein liga-weites Aggregat mit stark verstreuten Treffern eine
  Zwangspause von mehreren Minuten auslösen — pro betroffener Zeile lief
  eine eigene Neuberechnung über die komplette sichtbare Menge statt
  einmal pro Sucheingabe.
- Bei sehr großen Ligen (deutlich mehr Fächer/Items als üblich) baute die
  Suche beim ersten Tastendruck das komplette ungefilterte Aggregat auf,
  bevor überhaupt gefiltert wurde — je nach Größe mehrere Sekunden
  Verzögerung, die kein Dämpfer beheben konnte. Oberhalb von 50.000 Items
  läuft die Suche jetzt "on demand": Sanduhr statt Live-Filterung, das
  Ergebnis erscheint, sobald man kurz aufhört zu tippen.

## [0.1.0] - 2026-07-25

Erste veröffentlichte Version.

### Hinzugefügt

- Login per OAuth2 (PKCE) direkt gegen die offizielle GGG-API, Access-
  Token im Windows Credential Manager.
- Rate-Limit-Manager mit Live-Dashboard (Regeln, Auslastung, Sperren).
- Stash-Baum mit Ordnern, Spezial-Tabs (Map-/Unique-Stash) automatisch
  nach Sektion bzw. Kategorie gruppiert.
- Item-Tabelle mit Icon, Herkunfts-Fach, Position (Tab-Nummer und
  Gitter-Koordinate), Name, Typ, Level, Qualität, Stack-Größe, iLvl,
  Anforderungen (Level, Str, Dex, Int) und Mods.
- Spalten-Filter mit Vergleichsausdrücken per Rechtsklick auf den
  Spaltenkopf.
- Liga-weite Suche über alle geladenen Fächer und Charaktere, mit `*` als
  Platzhalter für den vollständigen Export.
- Typ-Filter für Normal, Magic, Rare, Unique, Gem, Currency, Divination
  Card und Sonstige als farbige Checkboxen.
- Charakter-Ansicht: Ausrüstung und Inventar in derselben Tabelle wie
  Stash-Items, mit eigenem Auto-Refresh und manuellem Aktualisieren.
- CSV-Export der aktuell sichtbaren, gefilterten Items.
- Automatischer Hintergrund-Refresh für das geöffnete Fach oder den
  angezeigten Charakter, ergänzt um einen langsamen Durchlauf über die
  übrigen Fächer, ohne das Rate-Limit-Budget für manuelle Abfragen
  aufzubrauchen.
- Offline-Betrieb: zeigt bei GGG-Wartung oder fehlender Verbindung den
  zuletzt bekannten Cache-Stand, sichtbar als solcher markiert.
- Erkennung archivierter Ligen, um Datenverlust durch Abrufversuche gegen
  nicht mehr erreichbare Liga-Endpunkte zu vermeiden.
- Persistenter Daten-Cache über Neustarts hinweg sowie Icon-Cache.
- Rohdaten-Viewer je Stash-Tab.

Die technischen Hintergründe einzelner Entscheidungen stehen in
[FALLSTRICKE_UND_WORKAROUNDS.md](FALLSTRICKE_UND_WORKAROUNDS.md).

[Unveröffentlicht]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/peterm2024/PoE-VIEW2/releases/tag/v0.1.0
