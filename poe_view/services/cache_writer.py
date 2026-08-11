"""Den Daten-Cache schreiben, ohne die Oberfläche anzuhalten.

Anlass (Peter, 2026-08-12): "Gibt es eine Möglichkeit, die kurzzeitigen
Freezes beim Updaten der Fächer zu umgehen? Evtl. in den Hintergrund
auslagern." Gemessen an seinem echten Bestand (58.432 Stash-Items,
76 MB) dauert ein Speichervorgang 1,4 Sekunden — und er lief bei JEDEM
eintreffenden Fach im GUI-Thread. Bei "Load All Tabs" mit mehreren
hundert Abschnitten summiert sich das zu Minuten reiner Starre.

Die Aufteilung in einen billigen und einen teuren Teil steckt in
``data_cache.Snapshot``; dieses Modul kümmert sich nur darum, den teuren
Teil aus dem GUI-Thread herauszuhalten.

**Zusammenfassen statt takten.** Es gibt hier bewusst KEINEN
Verzögerungs-Timer mit einer ausgedachten Wartezeit. Der Schreiber hält
genau einen wartenden Snapshot; trifft ein neuer ein, während noch
geschrieben wird, ERSETZT er den wartenden. Mehrere Anforderungen in
schneller Folge fallen damit von selbst zu einer zusammen, und zwar zur
jeweils aktuellsten — ein älterer Stand würde ohnehin nur überschrieben.
Ein Timer müsste dasselbe leisten, bräuchte dafür aber eine Zahl, die
niemand begründen kann.

**Warum ein Thread trotz GIL etwas bringt.** Das Umwandeln der Items ist
reines Python und gibt die GIL nur alle paar Millisekunden ab (Pythons
Umschaltintervall). Der GUI-Thread kommt dadurch regelmäßig zum Zug,
statt 1,4 Sekunden am Stück zu stehen: Aus einem harten Einfrieren wird
eine kurze Phase, in der es etwas zäher läuft. Ein eigener Prozess wäre
die einzige Möglichkeit, auch das noch loszuwerden — dafür müssten
dieselben 76 MB durch eine Pipe, was mehr kostet als es spart.

**Was beim Beenden passiert.** ``flush()`` wartet, bis der laufende und
der wartende Snapshot geschrieben sind. Ohne diesen Aufruf ginge beim
Schließen genau die letzte Änderung verloren — der Thread läuft als
Daemon und wird mit dem Prozess beendet.
"""

from __future__ import annotations

import logging
import threading
import time

from poe_view.services.data_cache import Snapshot

log = logging.getLogger(__name__)


class CacheWriter:
    """Schreibt ``data_cache.Snapshot``s der Reihe nach in einem eigenen
    Thread. Nicht wiederverwendbar über mehrere Konten hinweg nötig — der
    Zielpfad steckt im Snapshot selbst."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Snapshot | None = None
        self._thread: threading.Thread | None = None

    def request(self, snapshot: Snapshot) -> None:
        """Reiht ``snapshot`` ein und kehrt sofort zurück. Ein bereits
        wartender Snapshot wird verworfen (siehe Modul-Docstring)."""
        with self._lock:
            replaced = self._pending is not None
            self._pending = snapshot
            if self._thread is not None and self._thread.is_alive():
                if replaced:
                    log.debug("Daten-Cache: wartender Speicherstand durch einen "
                              "neueren ersetzt")
                return
            self._thread = threading.Thread(target=self._run, name="cache-writer",
                                            daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                snapshot = self._pending
                self._pending = None
                if snapshot is None:
                    # Ende der Schleife INNERHALB des Locks: Sonst könnte
                    # zwischen "nichts mehr da" und dem Thread-Ende ein
                    # request() hereinkommen, das den noch lebenden Thread
                    # sieht und deshalb keinen neuen startet — der
                    # Snapshot bliebe für immer liegen.
                    self._thread = None
                    return
            started = time.monotonic()
            try:
                snapshot.write()
            except Exception:
                # Absichtlich ALLES abfangen, nicht nur OSError (den
                # behandelt ``Snapshot.write`` bereits selbst). Was hier
                # sonst noch hochkommen könnte, ist unbekannt — und genau
                # deshalb darf es den Thread nicht mitnehmen: Ohne ihn
                # würde ab da still nichts mehr gespeichert, während die
                # Anwendung munter weiterläuft und der Nutzer glaubt,
                # seine Daten seien auf der Platte. Eine Zeile im Log ist
                # das Mindeste, was der nächste Fehlerbericht braucht.
                log.exception("Daten-Cache: Speichern im Hintergrund "
                              "fehlgeschlagen — der nächste Versuch läuft "
                              "wie gewohnt weiter")
            else:
                log.debug("Daten-Cache im Hintergrund gespeichert (%.2f s)",
                          time.monotonic() - started)

    def flush(self, timeout_s: float = 10.0) -> bool:
        """Wartet, bis nichts mehr aussteht. ``True``, wenn das gelungen
        ist; ``False`` bei Zeitüberschreitung — dann ist der letzte Stand
        nicht auf der Platte, und der Aufrufer soll das protokollieren
        statt es zu verschweigen."""
        deadline = time.monotonic() + timeout_s
        while True:
            with self._lock:
                thread = self._thread
                if thread is None and self._pending is None:
                    return True
            rest = deadline - time.monotonic()
            if rest <= 0:
                return False
            if thread is not None:
                thread.join(rest)
            else:
                # Kein Thread, aber etwas wartet: Das kann nur die
                # Winzigkeit zwischen request() und dem Thread-Start sein.
                time.sleep(0.01)
