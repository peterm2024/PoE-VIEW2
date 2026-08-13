"""Beobachtet PoEs eigene ``Client.txt`` auf die Ereignisse, nach denen
GGG neue Item-Daten hat, um den Live-Refresh gezielter zu takten (Peter,
2026-08-01: "Erst nach Zonenwechsel gibt es einen Refresh" — live an
einem Beobachtungsskript gegen Peters echte Client.txt bestätigt, siehe
FALLSTRICKE #58). GGGs Stash-API liefert neue Daten offenbar erst,
nachdem der Server einen Zonenwechsel committet hat; Polling dazwischen
ändert nichts. Seit 2026-08-10 zählen auch Händler-Verkauf und
Identifizieren dazu (§``_INVENTORY_LINES``, Peters zweite Beobachtung).

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

# Die Kennung der Gebiets-INSTANZ, ein paar Zeilen vor jedem "You have
# entered". Real geprüft am 2026-08-13 an Peters Client.txt:
#
#   17:23:10 Client-Safe Instance ID = 2308728564
#   17:23:10 Generating level 80 area "MapWorldsBrambleValley" with seed 711400918
#   17:23:11 : You have entered Bramble Valley.
#   ... 6 Minuten Map, kurz ins Hideout, zurück ...
#   17:30:09 Client-Safe Instance ID = 2308728564   ← DIESELBE
#   17:30:09 Generating level 80 area "MapWorldsBrambleValley" with seed 711400918
#   17:30:10 : You have entered Bramble Valley.
#
# Damit ist "zurück in dieselbe Map" von "nächste Map gleichen Namens"
# unterscheidbar — am Namen allein ist es das NICHT, und genau diese
# Unterscheidung braucht die Gruppierung im XP-Graphen (§4.40).
#
# Es ist eine DEBUG-Zeile. Fehlt sie (anderer Log-Umfang), bleibt die
# Kennung leer und alles verhält sich wie zuvor: jeder Aufenthalt zählt
# für sich.
_INSTANCE_LINE = re.compile(r"Client-Safe Instance ID = (\d+)")

# Peter, 2026-08-10: "Die Interaktion mit einem Händler, Verkaufen,
# Identifizieren, ... triggert auch das Senden der neuesten Items von
# GGG-Seite. Gibt es dabei einen Clients.txt-Eintrag?" — ja, beide. In
# Peters echter Client.txt nachgezählt (81.639 Zeilen): "Trade accepted."
# 1028x, "N Items identified" 821x, "1 Item identified" 78x. Das ist
# derselbe Gedanke wie beim Zonenwechsel: nicht öfter fragen, sondern zu
# den Zeitpunkten fragen, an denen GGG überhaupt etwas Neues zu liefern
# hat.
#
# "Trade accepted." deckt den Verkauf an einen NPC UND den Handel mit
# Spielern ab — beides ändert das Inventar, für den Refresh macht die
# Unterscheidung also keinen Unterschied. Das ebenfalls vorhandene
# "Trade cancelled." (60x) ausdrücklich NICHT: dabei ändert sich nichts,
# ein Abruf darauf wäre reine Rate-Limit-Verschwendung.
_INVENTORY_LINES = (
    re.compile(r": (Trade accepted)\.\s*$"),
    re.compile(r": (\d+ Items? identified)\s*$"),
)


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
    """Meldet jeden erkannten Zonenwechsel über ``zone_changed(zone_name)``
    und jedes andere Ereignis, nach dem GGG neue Item-Daten hat, über
    ``inventory_event(beschreibung)`` (§``_INVENTORY_LINES``).

    Getrennte Signale statt eines gemeinsamen: Der Zonenwechsel füttert
    zusätzlich die Zonen-Anzeige und die Messungen aus §_PublishWatch, ein
    Händler-Verkauf hat dort nichts verloren. Der Refresh selbst ist für
    beide derselbe.

    Startet am AKTUELLEN Dateiende — Zeilen von vor dem Start interessieren
    nicht, und ein mehrere MB großes Log von Beginn an einzulesen wäre
    unnötig teuer.

    Zwei Auslöser für dieselbe Prüfung (§Modul-Docstring): ein Poll-Timer
    als verlässliche Grundlage und Qts Datei-Benachrichtigung als
    beschleunigende Zugabe, falls sie auf dem System doch feuert."""

    zone_changed = Signal(str)
    inventory_event = Signal(str)

    def __init__(self, log_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Kennung der zuletzt betretenen Instanz (§_INSTANCE_LINE).
        # Bewusst ein Attribut statt eines zweiten Signal-Arguments: Die
        # Zeile steht IMMER vor dem "You have entered", der Wert ist beim
        # Emittieren also schon gesetzt, und alle vorhandenen Anschlüsse
        # an ``zone_changed`` bleiben unverändert.
        self.last_instance_id = ""
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
            instance = _INSTANCE_LINE.search(line)
            if instance:
                self.last_instance_id = instance.group(1)
                continue
            match = _ZONE_LINE.search(line)
            if match:
                log.info("Zonenwechsel erkannt: %s", match.group(1))
                self.zone_changed.emit(match.group(1))
                continue
            for pattern in _INVENTORY_LINES:
                match = pattern.search(line)
                if match:
                    log.info("Inventar-Ereignis erkannt: %s", match.group(1))
                    self.inventory_event.emit(match.group(1))
                    break
