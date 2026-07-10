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
**Lösung:** Autouse-Fixture in `tests/conftest.py` (`_isolated_local_state`), die `token_store.load_token` für die gesamte Testsession auf `lambda: None` patcht (später um denselben Trick für `data_cache._CACHE_FILE` erweitert, siehe unten). Damit bricht `_bootstrap()` immer harmlos mit `login_required` ab, unabhängig davon, ob auf der jeweiligen Maschine ein echtes Token vorliegt. **Regel:** Tests dürfen niemals von echtem lokalem State (Credential Manager, Cache-Dateien) oder echten Netzwerk-Calls abhängen — auch nicht "zufällig, weil gerade ein Token da ist". Bei jeder Komponente, die beim Erzeugen automatisch Hintergrund-Aktionen auslöst (hier: ein QThread, der sofort einen Job submitted), prüfen, ob diese Aktionen in Tests abgeschnitten werden müssen.

---

## 7. API-Farben direkt als Textfarbe verwendet — auf dunklem Grund teilweise unlesbar

**Problem:** Nutzer-Screenshot zeigte mehrere Stash-Tab-Zeilen im Navigationsbaum, deren Text praktisch unsichtbar war (dunkler Text auf dunklem Grund im Windows-Dark-Mode), zusätzlich zu abgeschnittenen Namen ("KRN…", "Cha…").
**Ursache:** Zwei getrennte Bugs, die zusammen das Bild ergaben. (1) `StashTree._build_node` setzte `node.setForeground(0, QBrush(QColor(stash.colour)))` — die von der GGG-API gelieferte, vom User frei wählbare Tab-Farbe wurde ungeprüft als Textfarbe übernommen. Einige User wählen sehr dunkle Farben (z. B. `#000000`, `#1a1a1a`) für ihre Tabs, die im (systemweiten) Dark-Mode praktisch mit dem Zeilenhintergrund verschmelzen. (2) Der Baum hatte `setHeaderHidden(True)` — ohne sichtbaren Header lässt sich die Namensspalte nicht per Maus verbreitern, und ohne explizites `QHeaderView.ResizeMode.Stretch` blieb sie auf einer schmalen Standardbreite.
**Lösung:** (1) Die Tab-Farbe wird jetzt als kleines 12×12-Icon-Quadrat VOR dem Namen gezeichnet (`_colour_swatch()`, gerendert per `QPainter` auf ein `QPixmap`), NIE mehr als Textfarbe — der Text bleibt immer in der normalen (Theme-abhängig garantiert lesbaren) Vordergrundfarbe. **Regel:** Von einer externen API gelieferte, frei wählbare Farben nie ungeprüft als Textfarbe verwenden — nur als Hintergrund/Icon/Rahmen, wo fehlender Kontrast höchstens unschön, aber nie unlesbar ist. (2) Header eingeblendet (`setHeaderLabels(["Name", "", ""])`) und Namensspalte auf `QHeaderView.ResizeMode.Stretch` gesetzt. **Das war noch nicht die vollständige Lösung** — siehe #9: `Stretch` füllt zwar automatisch den Platz, verhindert aber laut Qt-Doku genau das manuelle Ziehen, das eigentlich das Ziel war.

---

## 8. Genereller Status-Text wurde von einem generischen "Bereit" sofort überschrieben

**Problem:** Nutzer-Feedback: Nach dem Laden eines Stash-Tabs AUS DEM INTERNET stand der Tab-Name inkl. Item-Anzahl nicht mehr in der Info-Leiste — erst nach erneutem Anklicken (Cache-Treffer) blieb der Text stehen.
**Ursache:** `ApiWorker._dispatch()` emittierte am Ende JEDES Jobs unbedingt `self.status.emit("Bereit")` — auch direkt nach `stash_items_loaded`, dessen UI-Handler (`_show_items`) gerade erst die spezifische Meldung "Currency 1: 45 Items" gesetzt hatte. Cross-Thread-Qt-Signale werden FIFO in Absende-Reihenfolge auf dem Main-Thread verarbeitet — das "Bereit" kam garantiert als Letztes an und gewann. Bei einem Cache-Treffer (Klick auf einen bereits geladenen Tab) läuft dagegen gar kein Job, also auch kein nachträgliches "Bereit" — der Text blieb dort korrekt stehen, was die Diagnose zunächst verschleierte ("nur beim ersten Laden kaputt, beim zweiten Klick nicht" wirkte zufällig statt systematisch).
**Lösung:** Zwei Signale statt einem. `busy_changed(bool)` (neu) steuert ausschließlich den Statusleisten-Spinner, emittiert in `run()` per `try/finally` rund um JEDEN Job — unabhängig vom Ergebnis. `status(str)` bleibt reiner Verlaufstext; das abschließende `"Bereit"` gibt es nur noch in den Fällen, deren Ergebnis-Handler in der UI selbst KEINEN spezifischeren Text setzt. **Regel:** Ein einzelnes Signal für zwei unterschiedliche Zwecke (hier: "zeig Text an" + "ist noch was am Laufen") führt fast zwangsläufig zu genau dieser Art Race — sobald ein Konsument den generischen Teil ("Bereit"/"idle") als Fallback nutzt, überschreibt er jeden spezifischeren Konsumenten, der dasselbe Signal für Inhalte nutzt.

---

## 9. `QHeaderView.ResizeMode.Stretch` verhindert manuelles Spalten-Resizing

**Problem:** Nutzer-Feedback nach dem Fix aus #7: "Die Spalten lassen sich leider immer noch nicht verbreitern" — obwohl der Header jetzt sichtbar war.
**Ursache:** Laut Qt-Dokumentation zu `QHeaderView::ResizeMode`: Bei `Stretch` "the size cannot be changed by the user or programmatically" — die Spalte füllt zwar automatisch den verfügbaren Platz, lässt sich aber explizit NICHT mehr per Maus (oder Code) verbreitern/verschmälern. Das war exakt das Gegenteil dessen, was in #7 beabsichtigt war.
**Lösung:** Namensspalte auf `QHeaderView.ResizeMode.Interactive` umgestellt (das ist der Modus, der Maus-Dragging erlaubt) mit einer großzügigen initialen Breite (`setColumnWidth`). Verzicht auf automatisches Auto-Fill-Verhalten zugunsten von User-Kontrolle — deckt sich mit dem expliziten Nutzerwunsch. **Regel:** `Stretch` und "vom User verbreiterbar" schließen sich in Qt gegenseitig aus — vor der Wahl des Resize-Modes klären, ob Auto-Fill oder manuelle Kontrolle wichtiger ist, beides gleichzeitig geht pro Spalte nicht.

---

## 10. Hintergrund-Auto-Refresh hätte Ergebnisse der FALSCHEN Liga zuordnen können

**Problem:** Beim Bau des Hintergrund-Auto-Refreshers (lädt periodisch einen veralteten Stash-Tab neu, ohne dass der Nutzer etwas tut) fiel auf: `MainWindow._on_stash_items` ordnete das Ergebnis eines `FetchStashItemsJob` bisher immer `self._current_league` zu — also der Liga, die im UI GERADE aktiv ist, nicht der Liga, für die der Job ursprünglich gestartet wurde. Solange jeder Job aus einem direkten Nutzerklick entstand, fiel das nie auf (Klick → Job → Ergebnis, alles quasi synchron, die Liga wechselt dazwischen praktisch nie). Ein Hintergrund-Job kann aber problemlos mehrere Sekunden im Rate-Limit-Warteschlangen hängen — genug Zeit, damit der Nutzer zwischenzeitlich die Liga im Dropdown wechselt. Das Ergebnis wäre dann in den Item-/Zeitstempel-Cache der NEUEN (inzwischen aktiven) Liga geschrieben worden, obwohl es zur ALTEN Liga gehört.
**Ursache:** `FetchStashItemsJob` trug die Ziel-Liga zwar schon immer als Feld (`job.league`), aber das `stash_items_loaded`-Signal reichte sie nie an den Main-Thread durch — der Handler musste sich auf den impliziten, zum Empfangszeitpunkt aktuellen `self._current_league` verlassen.
**Lösung:** Signal-Signatur um `league` erweitert (`stash_items_loaded = Signal(str, str, str, object, bool)` — league, stash_id, name, items, silent). `_on_stash_items` schreibt Items/Zeitstempel jetzt immer unter der aus dem Signal übergebenen `league` in den Cache, aktualisiert die sichtbare Baum-/Tabellen-Anzeige aber nur noch, wenn diese `league` mit der GERADE aktiven übereinstimmt. **Regel:** Ergebnis-Signale, deren zugehöriger Job Zeit im Hintergrund verbringen kann (Queue, Rate-Limit-Wartezeit), dürfen sich beim "wohin gehört das Ergebnis"-Routing nie auf veränderlichen UI-Zustand zum Empfangszeitpunkt verlassen — die Zuordnung muss immer aus dem Job/Signal selbst kommen, der zum Startzeitpunkt eingefroren wurde.

---

## 11. Zwei Spalten für "geladen?" und "neu laden" waren redundant — die Zustände schließen sich aus

**Problem:** Nutzer-Feedback: "eigentlich benötigen wir im Stash-Tree nur entweder das Download-Symbol oder das Refresh-Symbol." Der Baum hatte bis dahin zwei Spalten: einen ⬇-Marker ("noch nicht geladen") und daneben IMMER einen ⟳-Button, unabhängig vom Ladezustand.
**Ursache:** Die beiden Spalten waren beim ursprünglichen Bau unabhängig voneinander entstanden (der Marker kam zuerst, der Button wurde später ergänzt), ohne zu bemerken, dass ein Tab nie beide Informationen gleichzeitig braucht: entweder er wurde noch nie geladen (⬇ reicht als Hinweis) oder er wurde geladen (dann ist "neu laden" die einzig sinnvolle Aktion).
**Lösung:** Beide Spalten zu einer verschmolzen (`stash_tree.py::_set_status`). Nie geladen → reiner ⬇-Text. Mindestens einmal geladen → ⟳-Button, dessen Beschriftung zugleich das Alter der Daten trägt ("⟳ heute" / "⟳ vor 3d", `format_age()`) — das war gleichzeitig der Aufhänger für den in #10 beschriebenen Hintergrund-Auto-Refresher, der genau dieses Alter als Auswahlkriterium nutzt.

---

## 13. Spezial-Tabs wirkten kaputt: alter "0 Items"-Cache-Eintrag blockierte die Kinder-Entdeckung dauerhaft

**Problem:** Nach dem Ausrollen der Spezial-Tab-Unterstützung (MapStash/UniqueStash → Unter-Tabs): "Der Map-Stash funktioniert noch nicht, der Unique-Stash funktioniert bei einigen." Der Nutzer fand selbst heraus, dass ein manueller Klick auf den ⟳-Button des Tabs das Problem behob ("musste erst aktualisieren").
**Ursache:** Dieselbe Klasse Fehler wie #12 — ein neues Feature stolpert über Bestandsdaten aus der Zeit davor. Spezial-Tabs, die VOR dem Feature schon einmal angeklickt worden waren, hatten einen Item-Cache-Eintrag mit 0 Items (damals wurden `children` schlicht ignoriert und die leere `items`-Liste gecacht). Ein Klick auf so einen Tab war damit ein permanenter Cache-Treffer (`_on_stash_selected` zeigt "0 Items" und fetcht nie) — der Abruf, der die Kinder überhaupt erst entdecken würde, fand auf normalem Weg NIE statt. Nur der Refresh-Button (bewusst am Cache vorbei) durchbrach den Kreis, deshalb "half aktualisieren".
**Lösung:** Dreifach. (1) Klick auf einen Spezial-Tab (`type` in `MainWindow.SPECIAL_TAB_TYPES`) ohne bekannte Kinder ignoriert den Item-Cache grundsätzlich und fetcht immer — es gibt bei diesen Tabs nichts, was ein Item-Cache-Treffer legitim beantworten könnte. Sind die Kinder bereits bekannt, zeigt der Klick nur den Hinweis "N Unter-Tabs" (kein Request). (2) `_on_stash_children` löscht einen evtl. vorhandenen alten Item-Eintrag des Eltern-Tabs aus dem Cache. (3) "Alle Tabs laden" nimmt unentdeckte Spezial-Tabs trotz Cache-Eintrag mit. **Regel:** Verhaltensänderungen, die die BEDEUTUNG bereits gecachter Daten ändern ("leere Item-Liste" hieß früher "Tab ist leer", heute "falsch abgefragt"), brauchen wie Schema-Änderungen (#12) eine Migrations-/Bypass-Strategie für Bestandsdaten — Tests mit jungfräulichem Zustand decken das systematisch nicht ab.

---

## 14. Die echten Spezial-Tab-Strukturen weichen von der API-Doku ab (name-Feld ist Müll oder Suffix)

**Problem:** Die erste Implementierung der Unter-Tab-Anzeigenamen basierte auf der offiziellen GGG-Doku (angenommen: Map-Kinder ohne `name`, dafür `metadata.map.{name, tier}`). Echte Rohdaten (via Rohdaten-Viewer #9 vom Nutzer geliefert!) zeigten dreifach anderes Verhalten: (a) Map-Kinder HABEN ein `name`-Feld, aber es ist wertlos ("1") ODER nur ein Suffix mit führendem Leerzeichen (" (Remove-only)"); (b) ein separates `tier`-Feld gibt es nicht — der Tier steckt bereits in `map.name` ("Map (Tier 6)"); (c) Unique-Kinder sind KOMPLETT namenlos (kein `name`, kein `metadata.map`, nur `metadata.items` = Anzahl).
**Ursache:** Doku und Realität der GGG-API driften auseinander; ohne echte Antwortdaten war das nicht zu sehen. Genau dafür war der Rohdaten-Viewer gebaut worden — der erste echte Einsatz hat sofort drei Abweichungen aufgedeckt.
**Lösung:** `StashTab.display_name` an die Realität angepasst: `map.name` gewinnt; das `name`-Feld wird nur angehängt, wenn es ein echtes Suffix ist (erkennbar am führenden Leerzeichen, z. B. " (Remove-only)"); namenlose Unique-Kinder zeigen Typ + Item-Anzahl ("UniqueStash (5 Items)"). Die echten Strukturen sind als Ground Truth in docs/api-notes/labview-test-vi.md festgehalten. **Regel:** API-Verhalten, das nur aus Doku (statt aus beobachteten Antworten) implementiert wurde, als solches markieren und beim ersten echten Datenkontakt gegenprüfen — der Rohdaten-Viewer ist dafür das Werkzeug der Wahl.

---

## 12. Neues Persistenz-Feld ohne Migration — Bestandsdaten blieben dauerhaft im "nie passiert"-Zustand

**Problem:** Direkt nach dem Deployment der Alters-Anzeige/des Auto-Refreshs (#10/#11) meldete der Nutzer: Im Stash-Tree erscheint IMMER nur der ⬇-Pfeil ("nie geladen"), auch bei Tabs, deren Items sichtbar aus dem Cache angezeigt werden. Zusätzlich tat der Auto-Refresher auf der echten Maschine schlicht nichts — obwohl alle 65 Tests grün waren und ein End-to-End-Smoke-Test das Feature bestätigt hatte.
**Ursache:** Das Feature hängte alles an das neue Cache-Feld `last_loaded` (Zeitstempel je Tab), das nur bei einem NEUEN Ladevorgang geschrieben wird. Die bereits existierende `data-cache.json` des Nutzers stammte von vor dem Feature und enthielt das Feld nicht — alle vorhandenen Tabs galten damit als "nie geladen". Fatal daran: Ein Klick auf so einen Tab ist ein Cache-Treffer (`_on_stash_selected` zeigt die Items an, OHNE zu fetchen) — es gab also keinen Weg, auf dem Bestands-Tabs jemals einen Zeitstempel bekommen hätten. Gleiches Loch beim Auto-Refresher: `_pick_auto_refresh_candidate` betrachtet nur Tabs MIT Zeitstempel als Kandidaten → auf Bestandsdaten null Kandidaten → Feature de facto tot. Die Tests haben das nicht erwischt, weil sie ausnahmslos Daten im NEUEN Format konstruierten — der einzige real existierende Altbestand lag auf der Nutzer-Maschine.
**Lösung:** Migrations-Backfill in `data_cache.load()` (`_backfill_last_loaded`): Tabs mit gecachten Items, aber ohne Zeitstempel, bekommen die mtime der Cache-Datei als Zeitstempel — die Daten sind höchstens so alt wie deren letzter Schreibvorgang, das ist als konservative Schätzung genau richtig. Zusätzlich zeigt jetzt ein Zähler in der Statusleiste ("Auto-Refresh: X von Y Stash-Tabs aktualisiert") sichtbar an, ob und wieviel der Hintergrund-Refresher tatsächlich arbeitet. **Regel:** Wenn ein neues Persistenz-Feld eingeführt wird, dessen FEHLEN die Logik als "ist nie passiert" interpretiert, braucht es zwingend (a) eine Migration für Bestandsdaten und (b) mindestens einen Test, der eine Datei im ALTEN Format lädt — "alte Datei crasht nicht" (das war bereits getestet) reicht nicht, sie muss auch semantisch korrekt interpretiert werden.

---

## 15. Icons "luden nicht aus dem Cache" — in Wahrheit stauten sich zigtausend Icon-Jobs in der Worker-Queue

**Problem:** Beobachtung des Nutzers: Grafiken schienen "jedesmal neu aus dem Netz geladen" zu werden (später selbst relativiert: "Ich glaube beim Icon-Cache täusche ich mich"). Der Icon-Datei-Cache arbeitete nachweislich korrekt (2.653 Dateien auf Platte, Cache-Treffer im Log) — die gefühlte Verzögerung war real, hatte aber eine andere Ursache.
**Ursache:** `ItemTableModel.set_items()` forderte beim Setzen der Items EIFRIG für JEDES Item mit unbekanntem Icon einen `FetchIconJob` an. In Einzelfach-Ansichten (≤ einige hundert Items) unauffällig — in Aggregat-Ansichten ("Alle Tabs laden", und erst recht die neue liga-weite Suche mit ~15.000 Items) landeten schlagartig tausende Jobs in der SEQUENZIELLEN Worker-Queue. Jeder manuelle Klick (Tab laden, Refresh) reihte sich HINTER diesen Icon-Jobs ein; selbst Cache-Treffer wirkten dadurch zäh, weil das `set_icon` erst ankam, wenn die Queue das Icon abgearbeitet hatte.
**Lösung:** Lazy-Icon-Loading für Aggregate: `set_items(…, request_icons=False)` fordert gar nichts an; stattdessen fordert `data()` ein fehlendes Icon erst an, wenn Qt die Zeile TATSÄCHLICH malt (DecorationRole wird nur für sichtbare Zellen abgefragt — Scrollen lädt nach). Einzelfach-Ansichten bleiben eifrig (dort ist Vorladen erwünscht und billig). **Regel:** Bei Model/View skaliert alles, was `set_items` pro Zeile an Nebenwirkungen auslöst, mit der Zeilenzahl der GRÖSSTEN Ansicht — Nebenwirkungen gehören für große Datenmengen in den Paint-Pfad (`data()`), der von Qt automatisch auf das Sichtbare begrenzt wird.
