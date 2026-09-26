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
from poe_view.services.season_log import season_at
from poe_view.services.zone_watcher import is_rest_area, zone_stays

log = logging.getLogger(__name__)

# Version 2 (2026-09-26): Die Level stehen jetzt je Season getrennt
# (§season_log). Version 1 wird verworfen statt umgerechnet — die
# alten Eintraege wuessten nicht, welcher Level zu welcher Season
# gehoert, und der Katalog baut sich aus der Client.txt in einem
# Zehntel einer Sekunde neu auf.
VERSION = 2

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
class SeasonStats:
    """Was ein Gebiet in EINER Season war. Getrennt gehalten, weil der
    Atlas sich mit jeder Season umbaut: Chateau stand vor dem 24.07. auf
    76 und danach auf 68 (§season_log). Zusammengeworfen ergäbe das eine
    Spanne "68–76", die es nie gab."""

    levels: set[int] = field(default_factory=set)
    visits: int = 0
    last_seen: str = ""          # ISO-Zeit, wie in der Client.txt gelesen


@dataclass
class ZoneRecord:
    """Ein Gebiet, je Season so oft gesehen wie es gesehen wurde.

    Innerhalb einer Season sammelt ``levels`` trotzdem mehrere Werte:
    ``Delve_Main`` wandert mit der Tiefe, ``DeepwaterEncounter`` mit dem
    Fortschritt. Gemessen an Peters Log betrifft das 7 von 317 Gebieten
    — die Ausnahme, nicht die Regel, und genau deshalb bleibt sie
    sichtbar."""

    area_id: str
    name: str
    category: str
    seasons: dict[str, SeasonStats] = field(default_factory=dict)

    def stats(self, season: str | None) -> SeasonStats:
        """Die Zahlen einer Season, oder — mit ``None`` — aller
        zusammen. Ein Gebiet, das in dieser Season nie betreten wurde,
        liefert leere Zahlen statt eines Fehlers."""
        if season is not None:
            return self.seasons.get(season, SeasonStats())
        gesamt = SeasonStats()
        for eintrag in self.seasons.values():
            gesamt.levels |= eintrag.levels
            gesamt.visits += eintrag.visits
            gesamt.last_seen = max(gesamt.last_seen, eintrag.last_seen)
        return gesamt

    def seen_in(self, season: str | None) -> bool:
        return season is None or season in self.seasons

    def level_text(self, season: str | None = None) -> str:
        """"68" oder "70–77" — was in der Spalte steht."""
        levels = self.stats(season).levels
        if not levels:
            return "?"
        tief, hoch = min(levels), max(levels)
        return str(tief) if tief == hoch else f"{tief}–{hoch}"

    def max_level(self, season: str | None = None) -> int:
        """Für die Sortierung: der höchste in dieser Season gesehene Level."""
        levels = self.stats(season).levels
        return max(levels) if levels else 0


def catalog_path(account_name: str) -> Path:
    """Wie bei der Mod-Sammlung eine Datei je Konto. Als Funktion, nicht
    als Modul-Konstante: Die Testfixture patcht ``APP_DATA_DIR``, eine
    eingefrorene Konstante würde an Peters echtem Ordner hängen
    (CLAUDE.md, "Tests")."""
    sicher = re.sub(r"[^A-Za-z0-9#_-]", "_", account_name or "unknown")
    return config.APP_DATA_DIR / f"zone-catalog-{sicher}.json"


def merge_stays(records: dict[str, ZoneRecord], stays,
                seasons: list | None = None) -> int:
    """Aufenthalte in den Katalog einarbeiten; liefert die Zahl der
    NEUEN Gebiete. Ein Aufenthalt ohne Kennung wird übergangen — ohne
    sie ließe sich weder Gruppe noch Wiedererkennung bestimmen.

    ``seasons`` ist die Historie aus ``season_log``; jeder Aufenthalt
    wird über SEINEN Zeitpunkt einsortiert, nicht über die heute
    laufende Season. Ohne Historie landet alles unter ``EARLIER`` — das
    ist der Zustand vor dem ersten Liga-Abruf und keine Fehlangabe: Wir
    wissen dann schlicht nicht, welche Season lief."""
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
        season = season_at(stay.entered, seasons or [])
        zahlen = eintrag.seasons.setdefault(season, SeasonStats())
        if stay.level:
            zahlen.levels.add(stay.level)
        # Der angezeigte Name kann sich ändern (Hideout umbenannt, Sprache
        # umgestellt) — der zuletzt gesehene gewinnt.
        eintrag.name = stay.name or eintrag.name
        zahlen.visits += 1
        zeit = stay.entered.isoformat(timespec="seconds")
        if zeit > zahlen.last_seen:
            zahlen.last_seen = zeit
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
                seasons={
                    str(name): SeasonStats(
                        levels={int(x) for x in (werte.get("levels") or [])},
                        visits=int(werte.get("visits") or 0),
                        last_seen=str(werte.get("last_seen") or ""))
                    for name, werte in (zeile.get("seasons") or {}).items()
                },
            )
        except (AttributeError, KeyError, TypeError, ValueError):
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
             "seasons": {
                 name: {"levels": sorted(werte.levels), "visits": werte.visits,
                        "last_seen": werte.last_seen}
                 for name, werte in sorted(r.seasons.items())}}
            for r in sorted(records.values(), key=lambda r: r.area_id)
        ],
    })


def _fingerabdruck(records: dict[str, ZoneRecord]) -> str:
    return json.dumps([(r.area_id, sorted(r.seasons), r.stats(None).visits,
                        sorted(r.stats(None).levels))
                       for r in sorted(records.values(), key=lambda r: r.area_id)])


def refresh_from_log(log_path: Path, account_name: str,
                     seasons: list | None = None) -> dict[str, ZoneRecord]:
    """Katalog laden, die Client.txt einarbeiten, speichern, zurückgeben.

    Die volle Datei wird gelesen, nicht nur der neue Rest: Der Katalog
    soll auch beim ersten Mal vollständig sein, und ``zone_stays``
    braucht für Peters 11-MB-Log unter einer Sekunde. Gespeichert wird
    nur, wenn sich etwas geändert hat."""
    pfad = catalog_path(account_name)
    records = load(pfad)
    vorher = _fingerabdruck(records)
    # Der Katalog zählt Besuche ab dem Beginn der Datei; ohne Grenze
    # würde jeder Aufruf dieselben Aufenthalte erneut zählen. Deshalb
    # zählt er nur, was seit dem letzten Lauf dazugekommen ist.
    seit = _newest(records)
    merge_stays(records, [s for s in zone_stays(log_path, datetime.min)
                          if s.entered.isoformat(timespec="seconds") > seit],
                seasons)
    nachher = _fingerabdruck(records)
    if nachher != vorher:
        try:
            save(pfad, records)
        except OSError as fehler:
            log.warning("Zonen-Katalog nicht speicherbar (%s): %s", pfad, fehler)
    return records


def _newest(records: dict[str, ZoneRecord]) -> str:
    return max((werte.last_seen for r in records.values()
                for werte in r.seasons.values()), default="")
