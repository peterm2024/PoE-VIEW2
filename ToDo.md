# ToDo — Weg zur Veröffentlichung

Arbeitsliste aus der Bestandsaufnahme vom 2026-07-28. Reihenfolge ist die
Abarbeitungsreihenfolge, nicht Priorität — Punkt 1 ist trivial, Punkt 5
braucht alle anderen fertig.

- [x] `.gitignore`: `.claude/` ergänzt
- [x] Implicit-Mods in der Item-Suche berücksichtigt (`item_table.py`
      durchsuchte bisher nur `explicitMods`)
- [x] Summe der Stack-Größe über die sichtbaren (gefilterten) Items in der
      Statuszeile ergänzt
- [ ] CHANGELOG `[Unveröffentlicht]` zu `[0.2.0]` abschließen (Datum
      setzen, Vergleichs-/Release-Links), Version in
      `poe_view/__init__.py` auf `0.2.0`
- [ ] Tag `v0.2.0` setzen, `.exe` per `PoE-VIEW2.spec` bauen, GitHub
      Release anlegen (Ablauf in `RELEASING.md`)
- [ ] unidentifizierte Items als "unidentifiziert" markieren
- [ ] Im "Ansichtsfenster" fehlen Itemlevel und Req. Level und Req. Stats
- [ ] Eigene Spalte für die Art des Gegenstands, z.B. "Sun Plate" oder "Crimson Jewel"
- [ ] Red, Blue und Green Filter irgendwie integrieren (Gems, Jewels)
- [ ] Dynamische Spalten? Welche Attribute anzeigen? Welche sind wichtig?
- [ ] Wert eines Items schätzen? Schrott-Items finden
- [ ] Legacy Items finden und einschätzen


## Zurückgestellt, kein Blocker

- Preise/Wert-Anzeige (poe.ninja-Anbindung) — großer Scope, vorher
  entscheiden ob Nicht-Ziel und im README so benennen
- Sockets/Links im Datenmodell (für "6-Link"-Suche)
- Client-ID-Modell (`poeview` gehört Peter, alle .exe-Nutzer laufen
  darüber) — kein Fix nötig, nur bewusst

