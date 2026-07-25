# Changelog

Alle nennenswerten Änderungen an PoE-VIEW2. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.0.0/), Versionierung
nach [SemVer](https://semver.org/lang/de/).

## [Unveröffentlicht]

## [0.1.0] - 2026-07-25

Erste veröffentlichte Version.

### Hinzugefügt

- Login per OAuth2 (PKCE) direkt gegen die offizielle GGG-API, Access-
  Token im Windows Credential Manager.
- Rate-Limit-Manager mit Live-Dashboard (Regeln, Auslastung, Sperren).
- Stash-Baum mit Ordnern, Spezial-Tabs (Map-/Unique-Stash) automatisch
  nach Sektion bzw. Kategorie gruppiert.
- Item-Tabelle: Icon, Herkunfts-Fach, Position (Tab + Gitter-Koordinate),
  Name, Typ, Level, Qualität, Stack-Größe, iLvl, Anforderungen
  (Level/Str/Dex/Int), Mods.
- Excel-artige Spalten-Filter per Rechtsklick auf einen Spaltenkopf.
- Liga-weite Suche über alle geladenen Fächer *und* Charaktere
  gleichzeitig, inkl. `*`-Wildcard für den Komplett-Export.
- Typ-Filter (Normal/Magic/Rare/Unique/Gem/Currency/Divination Card/
  Sonstige) als farbige Checkboxen.
- Charakter-Ansicht: Ausrüstung + Inventar in derselben Tabelle wie ein
  Stash-Fach, inkl. eigenem Auto-Refresh und manuellem Aktualisieren.
- CSV-Export der gerade sichtbaren (gefilterten) Items.
- Automatischer Hintergrund-Refresh für das gerade geöffnete Fach bzw.
  den gerade angezeigten Charakter, plus langsamer Sweep über den Rest
  der Truhe — ohne das Rate-Limit für eigene Klicks zu verbrauchen.
- Offline-Modus: zeigt bei GGG-Wartung oder Netzausfall automatisch den
  letzten bekannten Cache-Stand, deutlich als solcher markiert.
- Erkennung archivierter (beendeter) Ligen — kein Datenverlust durch
  Abrufversuche gegen nicht mehr erreichbare Liga-Endpunkte.
- Persistenter Daten-Cache (übersteht einen Neustart) und Icon-Cache.
- Rohdaten-Mini-Viewer je Stash-Tab.

Details zu jeder gelösten technischen Hürde und jedem gefundenen
GGG-API-Sonderfall: [FALLSTRICKE_UND_WORKAROUNDS.md](FALLSTRICKE_UND_WORKAROUNDS.md).

[Unveröffentlicht]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/peterm2024/PoE-VIEW2/releases/tag/v0.1.0
