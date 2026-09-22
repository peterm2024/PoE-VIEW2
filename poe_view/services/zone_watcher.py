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
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

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

# Die technische Gebiets-Kennung, unmittelbar vor jedem "You have
# entered" (dieselbe Stelle wie ``_INSTANCE_LINE``):
#
#   22:29:52 Client-Safe Instance ID = 1656541918
#   22:29:52 Generating level 70 area "MapWorldsCage" with seed 2136429196
#   22:29:53 : You have entered Cage.
#
# Sie ist das, woran sich eine Zone OHNE Erfahrung (Hideout, Stadt)
# erkennen lässt — am angezeigten Namen nicht, der ist lokalisiert und
# bei Hideouts frei benannt. In Peters Client.txt hatte jeder der 514
# Eintritte seit dem 01.09. eine frische Kennung davor.
_AREA_LINE = re.compile(r'Generating level \d+ area "([^"]+)" with seed')

# Woran eine Ruhezone zu erkennen ist — ausgezählt an Peters Client.txt
# (alle vorkommenden Kennungen, 2026-09-22):
#
#   HideoutSlum, HideoutRacetrack, HideoutShapersRealm, HideoutTemplarLab
#   1_1_town … 2_9_town, 2_11_endgame_town
#   HeistHub (Rogue Harbour), DeepwaterHub, MavenHub, Menagerie_Hub
#   Labyrinth_Airlock (Aspirants' Plaza), KalguuranSettlersLeague
#
# Ausdrücklich NICHT pauschal alles mit "Labyrinth": Die Labyrinth-
# Gebiete selbst (``3_Labyrinth_*``, ``EndGame_Labyrinth_*``) sind
# Kampfzonen, nur die Vorhalle ist es nicht.
_REST_AREA_PREFIXES = ("hideout",)
_REST_AREA_SUFFIXES = ("_town", "hub")
_REST_AREA_IDS = ("labyrinth_airlock", "kalguuransettlersleague")


def is_rest_area(area_id: str) -> bool:
    """Eine Zone, in der es keine Erfahrung zu holen gibt (§_AREA_LINE).

    Ohne Kennung (leerer String) gilt eine Zone als Kampfzone: Das ist
    das Verhalten von vor dieser Unterscheidung, und eine übersehene
    Kampfzone verfälscht die XP-Rate stärker als eine mitgezählte
    Ruhepause — in einer Ruhezone steht die Erfahrung ohnehin still, die
    Veröffentlichung davor gehört also der Zone davor."""
    kennung = area_id.strip().lower()
    if not kennung:
        return False
    return (kennung.startswith(_REST_AREA_PREFIXES)
            or kennung.endswith(_REST_AREA_SUFFIXES)
            or kennung in _REST_AREA_IDS)


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

# Tod des Charakters. Reales Format aus Peters Client.txt (2026-09-13):
# "2026/09/13 19:25:16 28758625 cffb065b [INFO Client 19976] :
# KRN_LZ_COTA has been slain." — der Name steht in der Zeile selbst,
# damit ist das Ereignis je Charakter zählbar (in einer Gruppe erscheinen
# auch die Tode der Mitspieler in derselben Form; der Anzeige-Code filtert
# ohnehin nach dem gerade gezeigten Charakter, fremde Namen stören nicht).
# Anlass: Aus den XP-Deltas sind Tode NICHT zuverlässig ablesbar — ein
# Tod in einem langen Messfenster verschwindet im Netto, real beobachtet
# am 2026-09-13 (Tod 19:39:09 in einem 11,5-Minuten-Fenster mit netto
# +1,9 Mio. XP). Die Client.txt ist die einzige verlässliche Quelle.
_DEATH_LINE = re.compile(r": (.+) has been slain\.\s*$")

# Zeitstempel am Zeilenanfang, lokale Zeit des Spiel-Clients.
_LINE_STAMP = "%Y/%m/%d %H:%M:%S"


def _line_time(line: str) -> datetime | None:
    """Zeitpunkt aus dem Zeilenanfang — None bei fremdem Format (naiv,
    lokale Zeit, wie PoE sie schreibt)."""
    try:
        return datetime.strptime(line[:19], _LINE_STAMP)
    except ValueError:
        return None


def deaths_since(log_path: Path, cutoff: datetime) -> dict[str, list[datetime]]:
    """Alle "has been slain"-Zeilen ab ``cutoff``: Charaktername → Zeitpunkte.

    Rollierendes Fenster statt Kalendertag (Peter, 2026-09-14: "Die
    meisten Gamer zocken über Mitternacht hinaus und das ist dann blöd,
    wenn das zurückgesetzt wird") — der Aufrufer gibt typischerweise
    "jetzt minus 24 h" mit.

    Volle Durchsicht der Datei statt Tail — der Todes-Zähler soll einen
    App-Neustart überstehen, und die Client.txt hält die Historie ohnehin
    vor (PoE hängt nur an; eine frische Datei nach einem PoE-Update
    bedeutet schlicht: keine älteren Tode mehr belegbar). ~10 MB mit dem
    billigen Substring-Filter vor der Regex sind einmalig beim Start
    kein Thema."""
    gefunden: dict[str, list[datetime]] = {}
    try:
        raw = log_path.read_bytes()
    except OSError:
        log.warning("Todes-Zähler: Client.txt nicht lesbar: %s", log_path)
        return gefunden
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if " has been slain." not in line:
            continue
        match = _DEATH_LINE.search(line)
        zeit = _line_time(line)
        if match and zeit is not None and zeit >= cutoff:
            gefunden.setdefault(match.group(1), []).append(zeit)
    return gefunden


class ZoneStay(NamedTuple):
    """Ein Aufenthalt in einer Zone: betreten, verlassen (``None`` =
    noch drin), angezeigter Name, Gebiets-Kennung und Instanz.

    Zeiten sind naive lokale ``datetime`` wie in der Client.txt."""

    entered: datetime
    left: datetime | None
    name: str
    area_id: str
    instance: str

    @property
    def seconds(self) -> float:
        """Verweildauer; 0, solange der Aufenthalt noch läuft."""
        return (self.left - self.entered).total_seconds() if self.left else 0.0

    @property
    def resting(self) -> bool:
        return is_rest_area(self.area_id)


def zone_stays(log_path: Path, since: datetime) -> list[ZoneStay]:
    """Alle Zonen-Aufenthalte, die nach ``since`` noch andauerten.

    Das Gegenstück zu ``deaths_since`` für die XP-Rechnung: Wie lange
    war der Charakter WIRKLICH in Gebieten, in denen Erfahrung fällt?
    Die Client.txt weiß das auf die Sekunde, auch für die Zeit, bevor
    PoE-VIEW2 überhaupt lief (Peter, 2026-09-22: "vor allem die
    client.txt beachten, da diese 100% zuverlässig die Verweildauer in
    den Maps zurückliefert").

    Ein Aufenthalt, der vor ``since`` begann und danach endete, ist
    dabei — der Aufrufer schneidet ihn auf sein Fenster zu. Der letzte
    Aufenthalt bleibt offen (``left is None``): Er läuft noch.

    Volle Durchsicht der Datei mit billigem Substring-Filter vor jeder
    Regex, dieselbe Begründung wie bei ``deaths_since``."""
    try:
        raw = log_path.read_bytes()
    except OSError:
        log.warning("Zonen-Verlauf: Client.txt nicht lesbar: %s", log_path)
        return []
    stays: list[ZoneStay] = []
    offen: ZoneStay | None = None
    area = instance = ""
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if "Client-Safe Instance ID = " in line:
            treffer = _INSTANCE_LINE.search(line)
            if treffer:
                instance = treffer.group(1)
            continue
        if "Generating level " in line:
            treffer = _AREA_LINE.search(line)
            if treffer:
                area = treffer.group(1)
            continue
        if " You have entered " not in line:
            continue
        treffer = _ZONE_LINE.search(line)
        zeit = _line_time(line)
        if treffer is None or zeit is None:
            continue
        if offen is not None:
            stays.append(offen._replace(left=zeit))
        offen = ZoneStay(entered=zeit, left=None, name=treffer.group(1),
                         area_id=area, instance=instance)
        # Kennung und Instanz gelten für GENAU diesen einen Eintritt.
        # Stehen sie beim nächsten nicht in der Datei, ist sie unbekannt
        # — dann lieber leer als von der Zone davor geerbt.
        area = instance = ""
    if offen is not None:
        stays.append(offen)
    return [s for s in stays if s.left is None or s.left > since]


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
    # Tod eines Charakters: (Name, Zeitpunkt aus der Log-Zeile). ``object``
    # statt eines Qt-Datentyps, damit das naive lokale datetime unverändert
    # durchgereicht wird (§_DEATH_LINE).
    death_seen = Signal(str, object)

    def __init__(self, log_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Kennung der zuletzt betretenen Instanz (§_INSTANCE_LINE).
        # Bewusst ein Attribut statt eines zweiten Signal-Arguments: Die
        # Zeile steht IMMER vor dem "You have entered", der Wert ist beim
        # Emittieren also schon gesetzt, und alle vorhandenen Anschlüsse
        # an ``zone_changed`` bleiben unverändert.
        self.last_instance_id = ""
        # Dasselbe für die Gebiets-Kennung (§_AREA_LINE): Sie sagt, ob
        # die gerade betretene Zone überhaupt Erfahrung bringen kann.
        self.last_area_id = ""
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
            area = _AREA_LINE.search(line)
            if area:
                self.last_area_id = area.group(1)
                continue
            match = _ZONE_LINE.search(line)
            if match:
                log.info("Zonenwechsel erkannt: %s", match.group(1))
                self.zone_changed.emit(match.group(1))
                continue
            match = _DEATH_LINE.search(line)
            if match:
                zeit = _line_time(line) or datetime.now()
                log.info("Tod erkannt: %s (%s)", match.group(1), zeit)
                self.death_seen.emit(match.group(1), zeit)
                continue
            for pattern in _INVENTORY_LINES:
                match = pattern.search(line)
                if match:
                    log.info("Inventar-Ereignis erkannt: %s", match.group(1))
                    self.inventory_event.emit(match.group(1))
                    break
