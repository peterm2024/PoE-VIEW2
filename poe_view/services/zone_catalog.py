"""Alle je betretenen Zonen mit ihrem Monsterlevel (§4.56).

Peter, 2026-09-26: "Außerdem hätte ich gerne dann einen Menüpunkt
'Zones', wo eine Tabelle öffnet, unterteilt nach Story, Map und
Special-Maps, wo alle Zonen aufgeführt werden und deren Monster-Level."

**Woher die Daten kommen — und warum nicht von woanders.** Es gibt keine
offene Datenquelle für PoEs Gebietsliste: RePoE (das Fundament der
Mod-Datenbank, §4.53) liefert Mods, Basistypen und Gems, aber keine
``world_areas``; GGGs API kennt Zonen überhaupt nicht. Was es gibt, ist
die Client.txt, und die ist für diesen Zweck besser als eine
mitgelieferte Liste: Sie nennt zu jeder betretenen Zone den tatsächlich
generierten Gebietslevel, also auch den der eingelegten Karte, der
Delve-Tiefe und des gerade laufenden Ligamechanismus. Eine statische
Tabelle könnte das nicht.

**Deshalb wächst der Katalog mit.** Die Client.txt wird von PoE
irgendwann gekürzt; der Katalog liegt daneben in ``APP_DATA_DIR`` und
behält, was einmal gesehen wurde. Peters Log reichte beim Bau 5,5 Monate
zurück und enthielt 381 Gebiete — genug, um die Tabelle vom ersten
Öffnen an voll zu haben, aber eben nicht für immer.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from poe_view import config
from poe_view.services.atomic_json import write_json
from poe_view.services.zone_watcher import is_rest_area, zone_stays

log = logging.getLogger(__name__)

VERSION = 1

# Die drei Gruppen, die Peter genannt hat, plus eine vierte für die
# Zonen ohne Monster — ausgezählt an seinen 381 Gebieten (2026-09-26):
#
#   Story    145  "1_2_5", "1_SideArea5_3_2", "2_7_2b"
#   Map      124  "MapWorldsChateau", "MapSideArea4_2"
#   Special   96  Labyrinth, Delve_Main, HeistBunker7, SanctumCellar,
#                 AbyssLeagueBoss2, DeepwaterEncounter, ...
#   Rest      16  "HideoutSlum", "2_8_town", "HeistHub", "MavenHub", ...
#
# **Die Ruhezonen kommen aus ``zone_watcher.is_rest_area``**, nicht aus
# einer eigenen Regel. Das ist dieselbe Unterscheidung, mit der die
# XP-Rate ihren Nenner bildet (§4.34), an denselben 381 Kennungen
# ausgezählt — sie zweimal zu treffen hieße, sie zweimal falsch treffen
# zu können. Deshalb steht Sarn Encampment hier neben dem Hideout und
# nicht bei der Story, obwohl seine Kennung wie eine Story-Kennung
# aussieht: Was zählt, ist "hier fallen keine Monster".
STORY = "Story"
MAP = "Map"
SPECIAL = "Special"
REST = "Rest"

CATEGORIES = (STORY, MAP, SPECIAL, REST)

# "1_2_5", "1_SideArea5_3_2", "2_7_2b" — alles, was mit Aktnummer und
# Unterstrich beginnt, gehört zur Story. Ausgenommen sind die
# Labyrinth-Gebiete, die zwar so heißen ("1_Labyrinth_OH_branch"), aber
# Endspiel-Inhalt sind.
_STORY_RE = re.compile(r"^\d+_(?!Labyrinth)", re.IGNORECASE)
_MAP_RE = re.compile(r"^Map", re.IGNORECASE)


def categorise(area_id: str) -> str:
    """Die Gruppe einer Gebiets-Kennung. Unbekanntes wird ``Special``:
    Das ist die Gruppe, in der eine neue Liga-Mechanik richtig liegt,
    solange niemand eine Regel für sie geschrieben hat."""
    kennung = (area_id or "").strip()
    if not kennung:
        return SPECIAL
    if is_rest_area(kennung):
        return REST
    if _MAP_RE.match(kennung):
        return MAP
    if _STORY_RE.match(kennung):
        return STORY
    return SPECIAL


@dataclass
class ZoneRecord:
    """Ein Gebiet, so oft gesehen wie es gesehen wurde.

    ``levels`` sammelt ALLE beobachteten Gebietslevel, nicht nur den
    letzten: Bei Karten hängt der Level an der eingelegten Karte, bei
    Delve an der Tiefe. Eine einzelne Zahl wäre dort schlicht falsch."""

    area_id: str
    name: str
    category: str
    levels: set[int] = field(default_factory=set)
    visits: int = 0
    last_seen: str = ""          # ISO-Zeit, wie in der Client.txt gelesen

    @property
    def level_text(self) -> str:
        """"68" oder "70–77" — was in der Spalte steht."""
        if not self.levels:
            return "?"
        tief, hoch = min(self.levels), max(self.levels)
        return str(tief) if tief == hoch else f"{tief}–{hoch}"

    @property
    def max_level(self) -> int:
        """Für die Sortierung: der höchste je gesehene Level."""
        return max(self.levels) if self.levels else 0


def catalog_path(account_name: str) -> Path:
    """Wie bei der Mod-Sammlung eine Datei je Konto. Als Funktion, nicht
    als Modul-Konstante: Die Testfixture patcht ``APP_DATA_DIR``, eine
    eingefrorene Konstante würde an Peters echtem Ordner hängen
    (CLAUDE.md, "Tests")."""
    sicher = re.sub(r"[^A-Za-z0-9#_-]", "_", account_name or "unknown")
    return config.APP_DATA_DIR / f"zone-catalog-{sicher}.json"


def merge_stays(records: dict[str, ZoneRecord], stays) -> int:
    """Aufenthalte in den Katalog einarbeiten; liefert die Zahl der
    NEUEN Gebiete. Ein Aufenthalt ohne Kennung wird übergangen — ohne
    sie ließe sich weder Gruppe noch Wiedererkennung bestimmen."""
    neu = 0
    for stay in stays:
        if not stay.area_id:
            continue
        eintrag = records.get(stay.area_id)
        if eintrag is None:
            eintrag = ZoneRecord(area_id=stay.area_id, name=stay.name,
                                 category=categorise(stay.area_id))
            records[stay.area_id] = eintrag
            neu += 1
        if stay.level:
            eintrag.levels.add(stay.level)
        # Der angezeigte Name kann sich ändern (Hideout umbenannt, Sprache
        # umgestellt) — der zuletzt gesehene gewinnt.
        eintrag.name = stay.name or eintrag.name
        eintrag.visits += 1
        zeit = stay.entered.isoformat(timespec="seconds")
        if zeit > eintrag.last_seen:
            eintrag.last_seen = zeit
    return neu


def load(path: Path) -> dict[str, ZoneRecord]:
    """Gespeicherten Katalog lesen. Jede Unstimmigkeit endet mit einem
    leeren Katalog statt einer Ausnahme: Er lässt sich aus der
    Client.txt jederzeit neu aufbauen, das ist ein milderer Verlust als
    ein Programm, das nicht mehr startet."""
    try:
        rohdaten = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(rohdaten, dict) or rohdaten.get("version") != VERSION:
        return {}
    records: dict[str, ZoneRecord] = {}
    for zeile in rohdaten.get("zones") or []:
        try:
            area_id = str(zeile["area_id"])
            records[area_id] = ZoneRecord(
                area_id=area_id,
                name=str(zeile.get("name") or ""),
                category=str(zeile.get("category") or categorise(area_id)),
                levels={int(x) for x in (zeile.get("levels") or [])},
                visits=int(zeile.get("visits") or 0),
                last_seen=str(zeile.get("last_seen") or ""),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return records


def save(path: Path, records: dict[str, ZoneRecord]) -> None:
    # Wie die Mod-Sammlung: Der Ordner kann beim allerersten Speichern
    # noch fehlen (``config.ensure_dirs`` lief nur für den echten Start,
    # nicht für einen Test mit gepatchtem APP_DATA_DIR).
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {
        "version": VERSION,
        "zones": [
            {"area_id": r.area_id, "name": r.name, "category": r.category,
             "levels": sorted(r.levels), "visits": r.visits,
             "last_seen": r.last_seen}
            for r in sorted(records.values(), key=lambda r: r.area_id)
        ],
    })


def refresh_from_log(log_path: Path, account_name: str) -> dict[str, ZoneRecord]:
    """Katalog laden, die Client.txt einarbeiten, speichern, zurückgeben.

    Die volle Datei wird gelesen, nicht nur der neue Rest: Der Katalog
    soll auch beim ersten Mal vollständig sein, und ``zone_stays``
    braucht für Peters 11-MB-Log unter einer Sekunde. Gespeichert wird
    nur, wenn sich etwas geändert hat."""
    pfad = catalog_path(account_name)
    records = load(pfad)
    vorher = json.dumps([(r.area_id, sorted(r.levels), r.visits)
                         for r in sorted(records.values(), key=lambda r: r.area_id)])
    # Der Katalog zählt Besuche ab dem Beginn der Datei; ohne Grenze
    # würde jeder Aufruf dieselben Aufenthalte erneut zählen. Deshalb
    # zählt er nur, was seit dem letzten Lauf dazugekommen ist.
    seit = _newest(records)
    merge_stays(records, [s for s in zone_stays(log_path, datetime.min)
                          if s.entered.isoformat(timespec="seconds") > seit])
    nachher = json.dumps([(r.area_id, sorted(r.levels), r.visits)
                          for r in sorted(records.values(), key=lambda r: r.area_id)])
    if nachher != vorher:
        try:
            save(pfad, records)
        except OSError as fehler:
            log.warning("Zonen-Katalog nicht speicherbar (%s): %s", pfad, fehler)
    return records


def _newest(records: dict[str, ZoneRecord]) -> str:
    return max((r.last_seen for r in records.values()), default="")
