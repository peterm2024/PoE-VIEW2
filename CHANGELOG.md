# Changelog

Alle nennenswerten Änderungen an PoE-VIEW2. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.0.0/), Versionierung
nach [SemVer](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Behoben

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

[Unveröffentlicht]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/peterm2024/PoE-VIEW2/releases/tag/v0.1.0
