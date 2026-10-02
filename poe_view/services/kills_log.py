"""Was ``/kills`` sagt — die Rohdaten zur Monsterdichte.

Peter, 2026-10-02: "Die Anzahl der gekillten Monster kann ich mittels
/kills im Game ermitteln. Daraus und aus der Dauer der Map könnten wir
schon ein paar Werte holen." Und dazu: "Ich benötige aber eine Erinnerung
von dir wenn ich eine Killzone betrete" (§ui/kills_reminder.py).

Der Befehl schreibt eine Zeile in die Client.txt, mit dem Zähler über die
ganze Lebenszeit des Charakters — nicht je Map:

    2026/10/02 21:32:08 36346140 cffb065b [INFO Client 21176] : You have killed 131.404 monsters.

Der Tausenderpunkt kommt vom deutschen Windows (im August standen
dieselben Zeilen mit Punkt da); ein englisches schriebe ein Komma. Gezählt
werden deshalb nur die Ziffern.

**Beobachten, nicht bewerten** — wie die Beute-Mitschrift
(§zone_loot_log): Eine Zeile je Ablesung, mit dem Unterschied zur
vorigen und den Kampfzonen dazwischen. Ob daraus Kills je Map, je Minute
oder je XP eine brauchbare Kennzahl wird, entscheidet die Auswertung,
nicht diese Datei ("Idee 2 schauen wir uns erst noch näher an").
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from poe_view import config

log = logging.getLogger(__name__)

# "monster" in der Einzahl ist nur geraten — ein Charakter mit genau einem
# Kill ist kein Fall, der vorkommt, aber er soll die Zeile nicht verfehlen.
_KILLS_LINE = re.compile(r": You have killed ([\d.,  ]+) monsters?\.\s*$")


def parse_kills(line: str) -> int | None:
    """Der Zähler aus einer Client.txt-Zeile, sonst ``None``."""
    treffer = _KILLS_LINE.search(line)
    if not treffer:
        return None
    ziffern = re.sub(r"\D", "", treffer.group(1))
    return int(ziffern) if ziffern else None


def log_path() -> Path:
    """Funktion statt Konstante — ``config.LOG_DIR`` wird in den Tests
    umgebogen (CLAUDE.md, "Tests"), wie bei ``zone_loot_log.log_path``."""
    return config.LOG_DIR / "kills-log.csv"


FIELDS = ("time", "character", "kills_total", "kills_since_last",
          "seconds_since_last", "zones_since_last", "current_zone",
          "area_level")


@dataclass
class Reading:
    """Eine Ablesung. ``kills_since_last``/``seconds_since_last`` sind
    leer bei der ersten Ablesung einer Sitzung — gegen einen Stand aus
    einer früheren Sitzung zu rechnen, mischte alles hinein, was
    dazwischen gespielt wurde. ``zones_since_last`` sind die Kampfzonen,
    die der Unterschied abdeckt (die gerade betretene nicht: Wer der
    Erinnerung folgt, liest am Anfang der neuen Map ab, und deren Kills
    gehören zur nächsten Zeile)."""
    at: datetime
    character: str
    total: int
    since_last: int | None
    seconds: float | None
    zones: list[str]
    current_zone: str
    area_level: int


def append(reading: Reading, path: Path | None = None) -> None:
    """Eine Zeile anhängen; Kopfzeile, wenn die Datei neu ist. Ein
    Schreibfehler wird geloggt und verschluckt — die Mitschrift ist eine
    Zugabe, kein Grund für einen Absturz mitten im Spiel."""
    pfad = path or log_path()
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        neu = not pfad.exists()
        with pfad.open("a", newline="", encoding="utf-8") as f:
            schreiber = csv.writer(f)
            if neu:
                schreiber.writerow(FIELDS)
            schreiber.writerow([
                reading.at.isoformat(timespec="seconds"),
                reading.character,
                reading.total,
                "" if reading.since_last is None else reading.since_last,
                "" if reading.seconds is None else round(reading.seconds),
                " | ".join(reading.zones),
                reading.current_zone,
                reading.area_level or "",
            ])
    except OSError:
        log.exception("Kill-Mitschrift: Zeile nicht geschrieben (%s)", pfad)
