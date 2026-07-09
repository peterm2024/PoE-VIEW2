# Entwicklungs-Logbuch: Gelöste Fallstricke & Workarounds

Dieses Dokument dokumentiert die technischen Hürden, die während der Entwicklung von PoE-VIEW2 aufgetreten sind, sowie die erarbeiteten Lösungen und Best Practices.

---

## 1. Rate-Limit-Header: Regel und Verbrauch dürfen nicht per Array-Position gematcht werden

**Problem:** Im LabVIEW-Original (PoE-VIEW) wurden `X-Rate-Limit-Account` (Regeln, `Max:Fenster:Sperre`) und `X-Rate-Limit-Account-State` (Verbrauch, `Aktuell:Fenster:RestSperre`) anhand ihrer Position im jeweiligen komma-getrennten Array einander zugeordnet. Das führte zu falschem Current/Max-Mapping, sobald GGG die Reihenfolge der Einträge zwischen den beiden Headern unterschiedlich sendet.
**Ursache:** Die Reihenfolge der Regeln in beiden Headern ist von der API nicht garantiert identisch — nur die Fenstergröße (2. Feld) ist der stabile gemeinsame Schlüssel.
**Lösung:** In `poe_view/api/rate_limiter.py::_parse_group` wird der State-String zuerst nach Fenstergröße indexiert (`usage_by_window: dict[int, tuple[current, lock_rest]]`), dann werden die Regeln über genau diesen Schlüssel nachgeschlagen — nie über Listenposition. Regressionstest: `tests/test_rate_limiter.py::test_parse_matches_state_by_window` sendet die State-Einträge absichtlich in vertauschter Reihenfolge.

---

## 2. Liga-Namen mit Leerzeichen brechen unkodierte URL-Pfade

**Problem:** Liga-IDs wie `SSF Ruthless` enthalten ein Leerzeichen. Ein roh eingesetzter Pfad (`/stash/SSF Ruthless`) ist eine ungültige bzw. von manchen HTTP-Stacks anders interpretierte URL.
**Ursache:** Das LabVIEW-Test-VI hängte den Liganamen unkodiert an die URL — funktionierte zufällig, war aber fragil.
**Lösung:** `PoeApiClient.get_stashes`/`get_stash` encodieren Liga-Namen und Stash-IDs grundsätzlich per `urllib.parse.quote`, bevor sie in den Pfad eingesetzt werden.

---

## 3. Private Kontakt-E-Mail landete in einer Doku-Datei und wurde gepusht

**Problem:** Beim Dokumentieren der aus dem LabVIEW-Test-VI extrahierten API-Notizen (`docs/api-notes/labview-test-vi.md`) wurde der im VI sichtbare User-Agent-String `PoE-VIEW (Contact: <private E-Mail>)` unreflektiert übernommen und mitsamt Commit gepusht — noch bevor auffiel, dass die Adresse damit dauerhaft in der öffentlich einsehbaren Git-Historie steht.
**Ursache:** Quellmaterial (Screenshot/Notizen) wurde direkt in eine committete Datei übertragen, ohne vorher personenbezogene Daten durch Platzhalter zu ersetzen.
**Lösung:**
1. Datei bereinigt (E-Mail durch `<kontakt-e-mail>`-Platzhalter ersetzt), der betroffene Commit per `git reset --soft HEAD~1` + Neu-Commit ersetzt und mit `git push --force-with-lease` überschrieben.
2. Verifikation über die komplette Historie: `git log --all -p | grep <lokaler-teil-der-e-mail>` muss 0 Treffer liefern — das ist jetzt fester Schritt vor jedem Push, wenn Personenbezug im Spiel sein könnte.
3. **Regel:** Kontaktdaten (E-Mail etc.) werden nie direkt in Dateien geschrieben, sondern ausschließlich als `<platzhalter>` dokumentiert und zur Laufzeit aus der lokalen, gitignorten `.env` gelesen (`config.CONTACT_EMAIL`, siehe `poe_view/config.py`).

---

## 4. `QT_QPA_PLATFORM=offscreen` für automatisierte Smoke-Tests unter Windows

**Problem:** Ein Skript, das `MainWindow` instanziiert und ohne sichtbares Fenster wieder beendet (z. B. für CI oder einen schnellen Start-Check), scheitert auf einem System ohne aktive Desktop-Session bzw. würde sonst ein echtes Fenster aufploppen lassen.
**Lösung:** Umgebungsvariable `QT_QPA_PLATFORM=offscreen` vor dem Start setzen (PowerShell: `$env:QT_QPA_PLATFORM = "offscreen"`). Qt rendert dann ohne echtes Display; `QApplication`, Worker-Start/-Stop und Signal-Verdrahtung lassen sich so ohne Klick-Interaktion prüfen. Zusätzlich `PYTHONPATH` auf das Projektverzeichnis setzen, wenn das Test-Skript außerhalb des Projekts liegt (z. B. im Scratchpad-Ordner) — sonst schlägt `import poe_view` mit `ModuleNotFoundError` fehl.
