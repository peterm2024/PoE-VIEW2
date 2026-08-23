"""Den XP-Verlauf über einen Programmstart hinweg aufheben (§4.44).

Peter, 2026-08-15: "Mit jeder neuen Version die ich teste beginnen die
XP-Daten wieder von vorne. Könnten wir uns das nicht merken?"

**Was hier aufgehoben wird und was ausdrücklich nicht.** Der Graph zeigt
abgeschlossene Abschnitte: je einer mit seinem Zeitpunkt, seiner Dauer
und der daraus gerechneten Rate. Das sind fertige Messungen — sie wieder
anzuzeigen erfindet nichts. Die Beobachtungs-BASIS des ``_XpWatch``
(seit wann, mit welchem Erfahrungsstand) bleibt dagegen sitzungslokal,
und zwar aus dem Grund, der dort im Docstring steht: Ein Levelaufstieg
während einer Pause vor dem Sitzungsstart würde als absurd hohe Rate
ausgewiesen. Der Verlauf ist Vergangenheit, die Basis wäre eine
Behauptung über die Gegenwart.

**Warum die Zeitstempel umgerechnet werden.** Im Programm laufen die
Punkte auf ``time.monotonic()`` — einer Uhr, die beim Start bei einem
beliebigen Wert beginnt und deren Nullpunkt sich mit jedem Neustart
verschiebt. Gespeichert wird deshalb die Wanduhrzeit, geladen wird
zurückgerechnet. Beides braucht beide Uhren zum selben Augenblick,
darum stehen sie als Parameter da statt im Modul zu stecken: So ist die
Umrechnung ohne laufende Uhr prüfbar.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol, Sequence

from poe_view import config
from poe_view.services.atomic_json import write_json
from poe_view.services.csv_export import sanitize_filename

log = logging.getLogger(__name__)

# Erhöhen, sobald sich der Aufbau einer Zeile ändert. Ein alter Stand
# wird dann verworfen statt falsch gedeutet — der Verlauf ist Komfort,
# kein Datenbestand, für den sich eine Migration lohnte.
#
# 2 (2026-08-23): ``level`` je Zeile, damit der Schnitt im Graphen beim
# letzten Levelaufstieg enden kann (``xp_graph.average_window``). Ein
# Stand ohne die Stufe würde den Zeitraum über einen Aufstieg hinweg
# ziehen — lieber einmal ohne Verlauf starten.
VERSION = 2

# Zeitstempel, die weiter als das in der Zukunft liegen, gelten als
# kaputt (Sommerzeit, gestellte Uhr, kopierte Datei von einem anderen
# Rechner). Lieber verwerfen als einen Balken zeichnen, der noch nicht
# passiert ist.
_FUTURE_TOLERANCE_S = 60.0


class _Point(Protocol):
    """Was dieses Modul von einem Verlaufspunkt braucht.

    Bewusst ein Protokoll statt eines Imports von ``ui.xp_graph``: Die
    Dienstschicht soll die Oberfläche nicht kennen, und für die
    Speicherung sind es ohnehin nur vier Zahlen."""

    at: float
    seconds: float
    rate: float
    instance: str
    level: int


def path_for(account_name: str) -> Path:
    """Je Konto eine Datei, wie beim Daten-Cache.

    Als Funktion und nicht als Modul-Konstante, damit der Testschutz in
    ``tests/conftest.py`` greift (dieselbe Falle wie bei ``cache_backup``
    und ``LOG_DIR``)."""
    safe = sanitize_filename(account_name, fallback="account")
    return config.APP_DATA_DIR / f"xp-history-{safe}.json"


def to_payload(histories: dict[str, Sequence[_Point]], *,
               now_mono: float, now_wall: float) -> dict:
    """Verläufe in die speicherbare Form bringen (Wanduhrzeit)."""
    characters: dict[str, list[dict]] = {}
    for name, points in histories.items():
        zeilen = [{"at": now_wall - (now_mono - p.at),
                   "seconds": p.seconds,
                   "rate": p.rate,
                   "instance": p.instance,
                   "level": p.level}
                  for p in points]
        if zeilen:
            characters[name] = zeilen
    return {"version": VERSION, "saved_at": now_wall, "characters": characters}


def from_payload(payload: dict, *, now_mono: float, now_wall: float,
                 span_s: float) -> dict[str, list[dict]]:
    """Gespeicherte Verläufe zurückrechnen und auf das Graph-Fenster kürzen.

    Was älter ist als das Fenster, wäre im Graphen ohnehin unsichtbar und
    fliegt hier schon raus — sonst wüchse die Datei über Wochen mit
    Punkten, die niemand je wieder sieht."""
    if not isinstance(payload, dict) or payload.get("version") != VERSION:
        return {}
    characters = payload.get("characters")
    if not isinstance(characters, dict):
        return {}

    wiederhergestellt: dict[str, list[dict]] = {}
    for name, zeilen in characters.items():
        if not isinstance(name, str) or not isinstance(zeilen, list):
            continue
        punkte = [p for p in (_restore_row(z, now_mono, now_wall, span_s)
                              for z in zeilen) if p is not None]
        punkte.sort(key=lambda p: p["at"])
        if punkte:
            wiederhergestellt[name] = punkte
    return wiederhergestellt


def _restore_row(row: object, now_mono: float, now_wall: float,
                 span_s: float) -> dict | None:
    if not isinstance(row, dict):
        return None
    try:
        wall_at = float(row["at"])
        seconds = float(row["seconds"])
        rate = float(row["rate"])
    except (KeyError, TypeError, ValueError):
        return None
    alter = now_wall - wall_at
    if alter >= span_s or alter < -_FUTURE_TOLERANCE_S:
        return None
    instance = row.get("instance", "")
    level = row.get("level", 0)
    return {"at": now_mono - alter,
            "seconds": seconds,
            "rate": rate,
            "instance": instance if isinstance(instance, str) else "",
            "level": level if isinstance(level, int) else 0}


def save(histories: dict[str, Sequence[_Point]], path: Path, *,
         now_mono: float, now_wall: float) -> None:
    """Verläufe ablegen. Klein genug, um bei jedem neuen Punkt zu laufen:
    Bei rund acht Veröffentlichungen pro Stunde (§4.35) sind drei Stunden
    zwei Dutzend Zeilen je Charakter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, to_payload(histories, now_mono=now_mono, now_wall=now_wall))


def load(path: Path, *, now_mono: float, now_wall: float,
         span_s: float) -> dict[str, list[dict]]:
    """Verläufe holen. Ein unlesbarer Stand ist kein Fehlerfall, sondern
    einfach kein Verlauf — der Graph startet dann leer wie bisher."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        log.warning("XP-Verlauf %s nicht lesbar — Graph startet leer.",
                    path, exc_info=True)
        return {}
    return from_payload(payload, now_mono=now_mono, now_wall=now_wall,
                        span_s=span_s)
