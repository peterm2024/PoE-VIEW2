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

---

## 5. `MainWindow.close()` vor `app.exec()` kann mit ungeprüftem `False` von `QThread.wait()` zu hartem Prozessabsturz führen

**Problem:** Ein Offscreen-Testskript rief `win.close()` auf, bevor die Qt-Event-Loop (`app.exec()`) überhaupt gestartet war, und beendete das Skript danach direkt. Der Python-Prozess endete mit Exit-Code 9 statt 0 — ohne sichtbaren Traceback.
**Ursache:** `closeEvent` ruft `self.worker.stop()` und `self.worker.wait(3000)` auf, ignoriert aber den Rückgabewert. Läuft der `ApiWorker`-Thread zu diesem Zeitpunkt noch (z. B. weil `BootstrapJob` — Zugriff auf den Windows Credential Manager via `keyring` — noch nicht durch war), liefert `wait()` `False`, der Thread lebt beim Prozessende weiter, und Qt beendet den Prozess hart, sobald es einen noch laufenden `QThread` beim Interpreter-Shutdown bemerkt.
**Lösung:** Zwei Ebenen. (1) In Test-/Diagnose-Skripten den Worker explizit stoppen UND den Rückgabewert von `wait()` prüfen (`assert win.worker.wait(5000)`), statt sich auf `close()` allein zu verlassen. (2) `MainWindow.closeEvent` (`poe_view/ui/main_window.py`) prüft den Rückgabewert jetzt selbst: liefert `wait(3000)` `False`, wird geloggt und `terminate()` als Fallback aufgerufen, statt den Thread stillschweigend weiterlaufen zu lassen.

---

## 6. Unit-Tests, die `MainWindow()` instanziieren, lösten unbemerkt echte (authentifizierte) API-Calls aus

**Problem:** Ein Offscreen-Smoke-Test, der einen Refresh-Button-Klick simulierte, zeigte im Log einen echten `HTTP 404`-Fehler von `api.pathofexile.com` — obwohl das Skript keinerlei echte Netzwerk-Interaktion beabsichtigte. Bei näherem Hinsehen: **jeder** pytest-Test in `test_main_window_helpers.py`, der `MainWindow()` konstruiert, hatte dasselbe Problem, nur unauffälliger (kein sichtbarer Fehler, da `/profile` normalerweise erfolgreich antwortet).
**Ursache:** `MainWindow.__init__` submitted beim Start unbedingt einen `BootstrapJob`. Dieser ruft `token_store.load_token()` auf — und weil auf der Entwickler-Maschine nach dem echten interaktiven Login ein gültiges Token im Windows Credential Manager liegt, lief der komplette `_bootstrap()`-Pfad durch: `client.set_token(...)` gefolgt von einem echten `client.get_profile()`-Request. Jeder Testlauf verbrauchte damit unbemerkt reales Rate-Limit-Budget des echten Accounts und hing von einer Internetverbindung ab — ein klassisches Test-Isolations-Leck, das nur auffällt, wenn zufällig ein Request fehlschlägt oder man explizit den Netzwerkverkehr beobachtet.
**Lösung:** Autouse-Fixture in `tests/conftest.py` (`_no_real_login`), die `token_store.load_token` für die gesamte Testsession auf `lambda: None` patcht. Damit bricht `_bootstrap()` immer harmlos mit `login_required` ab, unabhängig davon, ob auf der jeweiligen Maschine ein echtes Token vorliegt. **Regel:** Tests dürfen niemals von echtem lokalem State (Credential Manager, Cache-Dateien) oder echten Netzwerk-Calls abhängen — auch nicht "zufällig, weil gerade ein Token da ist". Bei jeder Komponente, die beim Erzeugen automatisch Hintergrund-Aktionen auslöst (hier: ein QThread, der sofort einen Job submitted), prüfen, ob diese Aktionen in Tests abgeschnitten werden müssen.

---

## 7. API-Farben direkt als Textfarbe verwendet — auf dunklem Grund teilweise unlesbar

**Problem:** Nutzer-Screenshot zeigte mehrere Stash-Tab-Zeilen im Navigationsbaum, deren Text praktisch unsichtbar war (dunkler Text auf dunklem Grund im Windows-Dark-Mode), zusätzlich zu abgeschnittenen Namen ("KRN…", "Cha…").
**Ursache:** Zwei getrennte Bugs, die zusammen das Bild ergaben. (1) `StashTree._build_node` setzte `node.setForeground(0, QBrush(QColor(stash.colour)))` — die von der GGG-API gelieferte, vom User frei wählbare Tab-Farbe wurde ungeprüft als Textfarbe übernommen. Einige User wählen sehr dunkle Farben (z. B. `#000000`, `#1a1a1a`) für ihre Tabs, die im (systemweiten) Dark-Mode praktisch mit dem Zeilenhintergrund verschmelzen. (2) Der Baum hatte `setHeaderHidden(True)` — ohne sichtbaren Header lässt sich die Namensspalte nicht per Maus verbreitern, und ohne explizites `QHeaderView.ResizeMode.Stretch` blieb sie auf einer schmalen Standardbreite.
**Lösung:** (1) Die Tab-Farbe wird jetzt als kleines 12×12-Icon-Quadrat VOR dem Namen gezeichnet (`_colour_swatch()`, gerendert per `QPainter` auf ein `QPixmap`), NIE mehr als Textfarbe — der Text bleibt immer in der normalen (Theme-abhängig garantiert lesbaren) Vordergrundfarbe. **Regel:** Von einer externen API gelieferte, frei wählbare Farben nie ungeprüft als Textfarbe verwenden — nur als Hintergrund/Icon/Rahmen, wo fehlender Kontrast höchstens unschön, aber nie unlesbar ist. (2) Header eingeblendet (`setHeaderLabels(["Name", "", ""])`) und Namensspalte auf `QHeaderView.ResizeMode.Stretch` gesetzt — das behebt die Abschneidung UND gibt dem User zusätzlich einen manuellen Resize-Griff.
