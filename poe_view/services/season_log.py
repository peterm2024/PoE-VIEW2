"""Welche Season lief wann? (§4.56.3)

Peter, 2026-09-26: "bei den Maps musst du bedenken, dass die Zonen hier
auch von der aktuellen Season abhängen. Die Map-Zuordnung ändert sich
hier mit jeder Season."

**Gemessen, nicht geglaubt.** An Peters Client.txt, die vom 12.04. bis
26.09. reicht und damit den Wechsel zur Allflame-Season am 24.07.
einschließt: Von 233 Gebieten, die auf beiden Seiten des Wechsels
vorkommen, tragen **44 danach einen anderen Level** — Chateau 76 → 68,
Atoll 70 → 77, Gardens 80 → 71. Innerhalb der neuen Season sind es
dagegen nur 7 von 317, und das sind die von Natur aus wandernden
(``Delve_Main`` nach Tiefe, ``DeepwaterEncounter``, Labyrinth-Prüfungen)
plus drei Karten mit einem Level Unterschied. Ohne Season-Trennung zeigt
die Zonen-Tabelle deshalb Spannen, die gar keine sind.

**Woher die Zeiten kommen.** ``/account/leagues`` nennt zu jeder Liga
``startAt`` und markiert die laufende Season über
``category.current``. Maßgeblich ist die KATEGORIE ("Allflame"), nicht
die einzelne Liga: Allflame, HC Allflame und SSF R Allflame sind
dieselbe Season mit demselben Atlas.

**Was die API NICHT hergibt: die Vergangenheit.** Beendete Ligen
verschwinden aus der Liste, ``endAt`` steht bei allen auf ``null``. Die
Historie lässt sich deshalb nur vorwärts aufbauen — jeder Liga-Abruf
schreibt die laufende Season mit ihrem Startdatum fest, das Ende einer
Season ist der Beginn der nächsten. Alles vor der ältesten bekannten
Season heißt ``EARLIER``.

Der naheliegende Umweg, die Vergangenheit über die eigenen Charaktere zu
benennen, führt in die Irre und wurde verworfen: Peters Charaktere aus
der Mirage-Season stehen heute allesamt in "SSF Ruthless". Nach dem
Season-Ende wandern sie in die permanente Liga, ihre Liga-Angabe sagt
also, wo sie JETZT sind, nicht wo sie gespielt wurden.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from poe_view import config
from poe_view.services.atomic_json import write_json

log = logging.getLogger(__name__)

VERSION = 1

# Der Zeitraum vor der ältesten Season, deren Start wir kennen. Kein
# erfundener Name: "Mirage" wäre geraten, und die Tabelle soll nicht
# behaupten, was sie nicht belegen kann.
EARLIER = "earlier"


class Season(NamedTuple):
    """Eine Season mit ihrem Beginn in LOKALER Zeit — die Client.txt
    schreibt lokale Zeitstempel, und verglichen wird gegen die."""

    id: str
    start: datetime


def seasons_path() -> Path:
    """Als Funktion, nicht als Modul-Konstante: Die Testfixture patcht
    ``APP_DATA_DIR`` (CLAUDE.md, "Tests"). Kontounabhängig — Seasons
    sind für alle Konten dieselben."""
    return config.APP_DATA_DIR / "seasons.json"


def _local(iso: str) -> datetime | None:
    """"2026-07-24T20:00:00Z" → lokale naive Zeit."""
    try:
        wert = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if wert.tzinfo is None:
        return wert
    return wert.astimezone().replace(tzinfo=None)


def current_season(leagues_raw: dict) -> Season | None:
    """Die laufende Season aus der Antwort von ``/account/leagues``.

    ``None``, wenn keine Liga sich als laufend ausweist oder keine einen
    Start nennt — dann bleibt die Historie, wie sie ist, statt einen
    Platzhalter zu bekommen."""
    for eintrag in (leagues_raw or {}).get("leagues") or []:
        kategorie = eintrag.get("category") or {}
        if not kategorie.get("current"):
            continue
        name = str(kategorie.get("id") or "").strip()
        start = _local(eintrag.get("startAt"))
        if name and start:
            return Season(name, start)
    return None


def load(path: Path | None = None) -> list[Season]:
    """Die bekannten Seasons, älteste zuerst. Jede Unstimmigkeit endet
    mit einer leeren Liste: Die Zonen-Tabelle zeigt dann alles unter
    ``EARLIER``, was unschön, aber nicht falsch ist."""
    pfad = path or seasons_path()
    try:
        rohdaten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rohdaten, dict) or rohdaten.get("version") != VERSION:
        return []
    gefunden: list[Season] = []
    for zeile in rohdaten.get("seasons") or []:
        try:
            start = datetime.fromisoformat(str(zeile["start"]))
        except (KeyError, TypeError, ValueError):
            continue
        name = str(zeile.get("id") or "").strip()
        if name:
            gefunden.append(Season(name, start))
    return sorted(gefunden, key=lambda s: s.start)


def save(seasons: list[Season], path: Path | None = None) -> None:
    pfad = path or seasons_path()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    write_json(pfad, {
        "version": VERSION,
        "seasons": [{"id": s.id, "start": s.start.isoformat(timespec="seconds")}
                    for s in sorted(seasons, key=lambda s: s.start)],
    })


def record_current(leagues_raw: dict, path: Path | None = None) -> list[Season]:
    """Die laufende Season in die Historie aufnehmen und alles
    zurückgeben. Eine bereits bekannte Season wird NICHT überschrieben:
    Ihr Start steht fest, und ein späterer Abruf soll ihn nicht
    verschieben."""
    bekannt = load(path)
    laufend = current_season(leagues_raw)
    if laufend is None or any(s.id == laufend.id for s in bekannt):
        return bekannt
    bekannt.append(laufend)
    try:
        save(bekannt, path)
        log.info("Season festgehalten: %s seit %s", laufend.id, laufend.start)
    except OSError as fehler:
        log.warning("Season-Historie nicht speicherbar: %s", fehler)
    return sorted(bekannt, key=lambda s: s.start)


def season_at(moment: datetime, seasons: list[Season]) -> str:
    """Welche Season lief zu diesem Zeitpunkt? ``EARLIER`` für alles vor
    der ältesten bekannten."""
    name = EARLIER
    for season in sorted(seasons, key=lambda s: s.start):
        if moment >= season.start:
            name = season.id
    return name


def newest(seasons: list[Season]) -> str:
    """Die jüngste bekannte Season — die Vorauswahl der Zonen-Tabelle.
    Wer sie öffnet, meint den Atlas, den er gerade spielt."""
    return max(seasons, key=lambda s: s.start).id if seasons else EARLIER
