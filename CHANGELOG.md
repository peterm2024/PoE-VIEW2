# Changelog

Alle nennenswerten Änderungen an PoE-VIEW2. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.0.0/), Versionierung
nach [SemVer](https://semver.org/lang/de/).

## [Unveröffentlicht]

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
- Stash-Baum: neue Pos.-Spalte zeigt die tatsächliche Position eines
  Fachs in der Truhen-Reihenfolge (leer bei Ordnern/Gruppen) — ein
  Zeilenheader-Äquivalent für Bäume, die (anders als die ItemList) keinen
  eigenen vertikalen Header kennen.
- Stash-Baum: Name-Spalte geladener Fächer wird nach Datenalter
  abgeblendet (aktuell < 1h normal, < 3h leicht, älter deutlicher),
  damit veraltete Fächer sofort auffallen. Das zuletzt aktualisierte Fach
  ist zusätzlich türkis markiert, bis das nächste Fach an der Reihe ist.

### Geändert

- Oberfläche und README vollständig auf Englisch umgestellt (internationale
  Zielgruppe). Code-Kommentare und interne Doku bleiben Deutsch.
- Auto-Refresh reserviert nur noch 10 % statt 50 % des Rate-Limit-Budgets
  für manuelle Klicks.

### Behoben

- Rate-Limit-Dashboard und der Auto-Refresh-Zähler ("X von Y Stash-Tabs")
  konnten dauerhaft veraltet bzw. bei 0 hängen bleiben, obwohl im
  Hintergrund weiter aktualisiert wurde.
- Der gleichmäßige Refresh-Takt konnte kurzzeitig mit der Rate-Limit-Policy
  eines fremden Endpunkts statt der eigenen rechnen.

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

[Unveröffentlicht]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/peterm2024/PoE-VIEW2/releases/tag/v0.1.0
