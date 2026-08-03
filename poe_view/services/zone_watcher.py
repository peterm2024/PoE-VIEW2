"""Beobachtet PoEs eigene ``Client.txt`` auf Zonenwechsel, um den
Live-Refresh gezielter zu takten (Peter, 2026-08-01: "Erst nach
Zonenwechsel gibt es einen Refresh" — live an einem Beobachtungsskript
gegen Peters echte Client.txt bestätigt, siehe FALLSTRICKE #58). GGGs
Stash-API liefert neue Daten offenbar erst, nachdem der Server einen
Zonenwechsel committet hat; Polling dazwischen ändert nichts.

Reines LESEN einer Text-Logdatei — von GGG ausdrücklich erlaubt, anders
als Speicherzugriffe auf den laufenden Client-Prozess (das wäre ein
Bann-Risiko).

Ursprünglich rein ereignisgesteuert über ``QFileSystemWatcher`` (Peters
Vorschlag, 2026-08-01: "Wir könnten auch den Windows-Watcher benutzen").
Das erwies sich am 2026-08-03 als NICHT ausreichend: Qts Datei-
Benachrichtigung feuert für PoEs Client.txt auf Windows nicht (Details
und Nachweis in FALLSTRICKE #61). Seitdem ist ein Poll-Timer die
verlässliche Grundlage, der Watcher bleibt nur als beschleunigende
Zugabe daneben stehen. Beide Wege münden in dasselbe ``check_now()``,
das ohne neue Bytes sofort zurückkehrt — doppeltes Auslösen ist damit
folgenlos.

Der Datei-Pfad kommt von Peter selbst (Settings-Dialog, Reiter "Zone
Refresh") — entweder direkt die Client.txt oder nur der
PoE-Installationsordner, siehe ``resolve_client_log_path()``. Das
Feature ist standardmäßig AUS und muss aktiv eingeschaltet werden.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

log = logging.getLogger(__name__)

# Takt des Poll-Fallbacks. 2 s ist für den Zweck reichlich schnell (der
# Zonenwechsel-Refresh spart ohnehin Minuten gegenüber dem getakteten
# Poll) und praktisch kostenlos: ein ``stat()`` plus das Lesen NUR der
# neu angehängten Bytes, kein erneutes Einlesen der mehrere MB großen
# Datei.
_POLL_INTERVAL_MS = 2000

# Reales Format aus Client.txt (live geprüft, 2026-08-01):
# "2026/07/31 00:59:32 15376062 cffb0658 [INFO Client 18604] : You have
# entered Lioneye's Watch."
_ZONE_LINE = re.compile(r": You have entered (.+)\.\s*$")


def resolve_client_log_path(configured_path: str) -> Path | None:
    """Peter darf entweder direkt die Client.txt angeben oder nur den
    PoE-Installationsordner — beides wird akzeptiert (erst die Datei
    selbst versucht, dann ``<Ordner>/logs/Client.txt``, dann
    ``<Ordner>/Client.txt`` für den Fall, dass gleich der logs-Ordner
    angegeben wurde). ``None``, wenn sich daraus keine existierende Datei
    ergibt — der Aufrufer entscheidet, was das für die Anzeige bedeutet."""
    text = configured_path.strip()
    if not text:
        return None
    path = Path(text)
    if path.is_file():
        return path
    if path.is_dir():
        for candidate in (path / "logs" / "Client.txt", path / "Client.txt"):
            if candidate.is_file():
                return candidate
    return None


class ZoneWatcher(QObject):
    """Meldet jeden erkannten Zonenwechsel über ``zone_changed(zone_name)``.

    Startet am AKTUELLEN Dateiende — Zeilen von vor dem Start interessieren
    nicht, und ein mehrere MB großes Log von Beginn an einzulesen wäre
    unnötig teuer.

    Zwei Auslöser für dieselbe Prüfung (§Modul-Docstring): ein Poll-Timer
    als verlässliche Grundlage und Qts Datei-Benachrichtigung als
    beschleunigende Zugabe, falls sie auf dem System doch feuert."""

    zone_changed = Signal(str)

    def __init__(self, log_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._log_path = log_path
        self._position = log_path.stat().st_size
        self._watcher = QFileSystemWatcher([str(log_path)], self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        # Der eigentliche Motor (FALLSTRICKE #61): Qts Benachrichtigung
        # feuert für die Client.txt nicht, der Timer schon.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.check_now)
        self._poll_timer.start()
        # Peter, 2026-08-03: "Überwachen wir überhaupt? Oder überwachen wir
        # die falsche Datei?" — bisher gab es dafür keinerlei Log-Spur.
        # `addPath()` (auch über den Konstruktor) kann auf manchen Systemen
        # stillschweigend fehlschlagen (Berechtigungen, OS-Limit für
        # gleichzeitig beobachtete Dateien); ohne diesen Check sähe man das
        # nie. Nur noch eine Randnotiz, seit das Polling die Erkennung
        # ohnehin unabhängig davon trägt.
        log.info("Zonen-Beobachtung gestartet: %s (Startposition %d Bytes, "
                 "Poll-Takt %d ms, Qt-Watcher aktiv: %s)",
                 log_path, self._position, _POLL_INTERVAL_MS,
                 str(log_path) in self._watcher.files())

    def _on_file_changed(self, path: str) -> None:
        log.debug("Client.txt-Änderung gemeldet: %s", path)
        self.check_now()
        # PoE ersetzt die Datei nie (nur Anhängen), aber manche
        # Watch-Implementierungen verlieren den Pfad nach einem Schreib-
        # Ereignis sicherheitshalber neu eintragen, statt stumm blind zu
        # werden.
        if str(self._log_path) not in self._watcher.files():
            log.warning("Watch-Pfad nach Änderung verloren, erneut eingetragen: %s",
                        self._log_path)
            self._watcher.addPath(str(self._log_path))

    def check_now(self) -> None:
        """Liest alle seit dem letzten Aufruf neu angehängten Zeilen und
        meldet jeden Zonenwechsel darin. Öffentlich (nicht nur intern über
        das Datei-Ereignis erreichbar), damit Tests ohne ein echtes,
        zeitlich unvorhersehbares Betriebssystem-Ereignis auskommen."""
        try:
            size = self._log_path.stat().st_size
        except OSError:
            log.warning("Client.txt nicht lesbar: %s", self._log_path)
            return
        if size < self._position:
            # Datei wurde ersetzt/gekürzt (z. B. frische Client.txt nach
            # PoE-Neustart) — von vorn beobachten statt mit einer
            # Position jenseits des Dateiendes hängen zu bleiben.
            self._position = 0
        if size == self._position:
            return
        with self._log_path.open("rb") as f:
            f.seek(self._position)
            new_bytes = f.read()
            self._position = f.tell()
        for line in new_bytes.decode("utf-8", errors="replace").splitlines():
            match = _ZONE_LINE.search(line)
            if match:
                log.info("Zonenwechsel erkannt: %s", match.group(1))
                self.zone_changed.emit(match.group(1))
