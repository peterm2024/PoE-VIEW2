"""Zeitgestempelte Sicherungen des Daten-Caches (Peter, 2026-08-06).

Anlass war ein realer Schaden am selben Abend: Eine Änderung am
Datenmodell filterte GGGs Färbungs-Markup schon im Feld statt erst in der
Anzeige, die Anwendung lief einmal, und beim nächsten Speichern trug die
Cache-Datei den gefilterten Stand — 976 von 976 Karten ohne Farbangabe
(FALLSTRICKE #66). Wiederherstellbar war das nur durch einen vollen
Neuabruf über die API.

Es ist der dritte Fall dieser Art. #62 löschte den Bestand beim Ab- und
Wieder-Anmelden, #65 beschrieb, wie zwei Instanzen einander die Datei
überschreiben. Beide wurden mit einem gezielten Wächter behoben, jeder
gegen genau seinen Fehler. Eine Sicherung ist die allgemeine Antwort: Sie
greift auch gegen den Fehler, den noch niemand vorhergesehen hat.

**Gesichert wird beim Start**, bevor die laufende Sitzung irgendetwas
schreiben kann. Das ist der einzige Zeitpunkt, an dem die Datei
garantiert den Stand der VORIGEN Sitzung trägt — und damit genau das, was
man zurückhaben will, wenn diese Sitzung etwas kaputt macht.

**gzip statt Kopie**, an der echten Datei gemessen (67,5 MB, 2026-08-06):

===========  ========  =========
Verfahren    Dauer     Größe
===========  ========  =========
kopieren     0,02 s    67,5 MB
gzip -1      0,12 s    12,4 MB
gzip -6      0,33 s     7,5 MB
gzip -9      0,51 s     7,7 MB
===========  ========  =========

``-6`` ist die Wahl: neunmal kleiner für ein Drittel einer Sekunde. ``-9``
ist hier langsamer UND größer, das ist kein Tippfehler — bei Daten mit
sehr vielen Wiederholungen kann die größere Fenstersuche schlechter
abschneiden. Erst durch die Kompression wird Peters 24-Stunden-Regel
bezahlbar: ein Tag voller Sicherungen kostet Megabytes statt Gigabytes.

Zurückgespielt wird von Hand über den Explorer, es gibt bewusst keinen
Knopf dafür — dieselbe Überlegung wie beim fehlenden Löschen-Knopf (Peter,
2026-08-04: "zu gefährlich"). Eine ``.json.gz`` öffnet jedes Packprogramm;
der entpackte Inhalt muss nur den Namen der Cache-Datei tragen.
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from poe_view import config

log = logging.getLogger(__name__)

BACKUP_DIR = config.APP_DATA_DIR / "backups"

# Peters Vorgabe: "ein Backup mit Timestamp, das erst nach 24h gelöscht
# werden darf."
MAX_AGE = timedelta(hours=24)

# Rückfallgrenze für den Fall, den die Altersregel allein nicht abdeckt:
# Wer die Anwendung im Minutentakt neu startet und dazwischen jeweils
# etwas abruft, erzeugt binnen eines Tages beliebig viele Sicherungen.
# Vierundzwanzig sind grob eine je Stunde des Aufbewahrungsfensters, bei
# ~7,5 MB also unter 200 MB. Die Altersregel bleibt die eigentliche Regel;
# das hier ist nur eine Obergrenze.
MAX_COUNT = 24

_SUFFIX = ".json.gz"
_STAMP_FORMAT = "%Y%m%d-%H%M%S"
_STAMP_PATTERN = re.compile(r"\.(\d{8}-\d{6})" + re.escape(_SUFFIX) + r"$")


def _stamp_of(path: Path) -> datetime | None:
    """Zeitpunkt aus dem Dateinamen, ``None`` bei fremden Dateien.

    Bewusst aus dem NAMEN und nicht aus der mtime: Was wir nicht als
    unsere eigene Sicherung erkennen, wird nie gelöscht. Ein
    Verzeichnis, in dem der Nutzer auch eigene Kopien ablegen kann, darf
    nicht stillschweigend aufgeräumt werden."""
    match = _STAMP_PATTERN.search(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), _STAMP_FORMAT)
    except ValueError:
        return None


def backups_for(source: Path) -> list[Path]:
    """Vorhandene Sicherungen dieser Cache-Datei, neueste zuerst."""
    if not BACKUP_DIR.is_dir():
        return []
    found = [(stamp, path) for path in BACKUP_DIR.glob(f"{source.stem}.*{_SUFFIX}")
             if (stamp := _stamp_of(path)) is not None]
    return [path for _stamp, path in sorted(found, reverse=True)]


def create(source: Path, now: datetime | None = None) -> Path | None:
    """Sichert ``source`` gepackt und gibt den Pfad zurück.

    ``None``, wenn nichts zu tun war — es gibt keine Quelldatei, oder seit
    der letzten Sicherung hat sich nichts geändert.

    Die Unverändert-Prüfung vergleicht die mtime der Quelle mit dem
    Zeitstempel der neuesten Sicherung. Ohne sie legte jeder Neustart eine
    weitere identische Kopie an — wer die Anwendung dreimal hintereinander
    startet, ohne dazwischen etwas abzurufen, bekäme dreimal dieselben
    7,5 MB und verdrängte damit ältere, tatsächlich verschiedene Stände.
    """
    if not source.is_file():
        return None
    now = now or datetime.now()

    existing = backups_for(source)
    if existing:
        newest = _stamp_of(existing[0])
        source_changed = datetime.fromtimestamp(source.stat().st_mtime)
        if newest is not None and newest >= source_changed:
            log.debug("Cache-Backup: unverändert seit %s, übersprungen", newest)
            return None

    target = BACKUP_DIR / f"{source.stem}.{now.strftime(_STAMP_FORMAT)}{_SUFFIX}"
    # Nebendatei mit Prozess-ID, dann verschieben — dieselbe Überlegung
    # wie in atomic_json: Ein Abbruch mitten im Packen darf kein halbes
    # Archiv hinterlassen, das später wie eine gültige Sicherung aussieht.
    # Der Name steht VOR dem try, sonst griffe das Aufräumen im
    # Fehlerfall auf eine noch nicht zugewiesene Variable zu — und die
    # daraus entstehende Ausnahme käme aus genau dem Zweig, der
    # Ausnahmen abfangen soll.
    staging = target.with_name(f"{target.name}.{os.getpid()}.part")
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as raw, gzip.open(staging, "wb", compresslevel=6) as packed:
            shutil.copyfileobj(raw, packed, length=1 << 20)
        os.replace(staging, target)
    except OSError:
        log.exception("Cache-Backup: Anlegen fehlgeschlagen")
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    log.info("Cache-Backup: %s (%.1f MB gepackt aus %.1f MB)", target.name,
             target.stat().st_size / 1e6, source.stat().st_size / 1e6)
    return target


def prune(source: Path, now: datetime | None = None) -> int:
    """Löscht Sicherungen älter als ``MAX_AGE`` und gibt deren Zahl zurück.

    **Die neueste bleibt immer stehen**, auch wenn sie älter als einen Tag
    ist. Sonst stünde man nach zwei Wochen Pause ohne jede Sicherung da —
    also genau dann, wenn man am wenigsten weiß, was der letzte gute Stand
    war.

    Wird NACH ``create`` aufgerufen, nie davor: Bräche das Anlegen ab,
    wären sonst die alten schon weg und die neue noch nicht da.
    """
    now = now or datetime.now()
    existing = backups_for(source)
    doomed = [path for path in existing[1:]
             if (stamp := _stamp_of(path)) is not None and now - stamp > MAX_AGE]
    doomed += existing[max(MAX_COUNT, 1):]

    removed = 0
    for path in dict.fromkeys(doomed):  # Reihenfolge egal, Dubletten schon
        try:
            path.unlink()
            removed += 1
        except OSError:
            log.exception("Cache-Backup: %s ließ sich nicht löschen", path.name)
    if removed:
        log.info("Cache-Backup: %d alte Sicherung(en) entfernt", removed)
    return removed


def run(source: Path, now: datetime | None = None) -> Path | None:
    """Sichern und aufräumen, in dieser Reihenfolge. Der Aufruf beim Start."""
    created = create(source, now)
    prune(source, now)
    return created
