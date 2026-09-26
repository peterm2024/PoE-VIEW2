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
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from poe_view import config
from poe_view.services.atomic_json import write_json
from poe_view.services.league_log import UNKNOWN
from poe_view.services.zone_watcher import is_rest_area, zone_stays

log = logging.getLogger(__name__)

# Version 3 (2026-09-27): je LIGA statt je Season (Liga-Namen tragen die
# Season in sich, und die Ligen einer Season haben verschiedene Inhalte),
# dazu Tode und Verweildauer. Ältere Versionen werden verworfen statt
# umgerechnet — sie wüssten die Liga nicht, und der Katalog baut sich aus
# der Client.txt in einem Zehntel einer Sekunde neu auf.
VERSION = 3

# Die Gruppen, ausgezählt an Peters 381 Gebieten (2026-09-26):
#
#   Story      145  "1_2_5", "1_SideArea5_3_2", "2_7_2b"
#   Map        115  "MapWorldsChateau"
#   Labyrinth   82  "3_Labyrinth_boss_2", "EndGame_Labyrinth_OH_straight"
#   Side Area    9  "MapSideArea4_2", "MapSideAreaIceForest"
#   Special      8  HeistBunker7, SanctumCellar, AbyssLeagueBoss2, ...
#   Delve        1  "Delve_Main"
#   Rest        21  "HideoutSlum", "2_8_town", "HeistHub", "MavenHub"
#
# **Side Area, Delve und Labyrinth stehen eigens da** (Peter,
# 2026-09-26): "MapSideArea sind keine eigenen Maps, das sind meistens
# Vaal-Side-Areas." Unter ``Map`` verfälschten sie die Karten-Liste —
# neun Einträge, die keine Karte sind, mit Tiers, die es nicht gibt.
# Labyrinth wiederum ist mit 82 Kennungen die mit Abstand größte Gruppe
# hinter Story und Map; in ``Special`` erschlug sie alles andere.
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
SIDE_AREA = "Side Area"
DELVE = "Delve"
LABYRINTH = "Labyrinth"
SPECIAL = "Special"
REST = "Rest"

CATEGORIES = (STORY, MAP, SIDE_AREA, DELVE, LABYRINTH, SPECIAL, REST)

# "1_2_5", "1_SideArea5_3_2", "2_7_2b" — alles, was mit Aktnummer und
# Unterstrich beginnt, gehört zur Story. Die Labyrinth-Gebiete heißen
# zwar auch so ("1_Labyrinth_OH_branch"), werden aber vorher abgefangen.
_STORY_RE = re.compile(r"^\d+_", re.IGNORECASE)
_MAP_RE = re.compile(r"^Map", re.IGNORECASE)
_SIDE_AREA_RE = re.compile(r"^MapSideArea", re.IGNORECASE)
_DELVE_RE = re.compile(r"^Delve", re.IGNORECASE)


def categorise(area_id: str) -> str:
    """Die Gruppe einer Gebiets-Kennung. Unbekanntes wird ``Special``:
    Das ist die Gruppe, in der eine neue Liga-Mechanik richtig liegt,
    solange niemand eine Regel für sie geschrieben hat.

    Die Reihenfolge der Prüfungen ist die Aussage: Ruhezonen zuerst
    (eine Stadt bleibt eine Stadt, auch wenn ihre Kennung wie Story
    aussieht), dann Labyrinth vor Story (``1_Labyrinth_…`` fängt mit
    einer Aktnummer an, ist aber Endspiel), dann Side Area vor Map
    (``MapSideArea…`` fängt mit "Map" an, ist aber keine Karte)."""
    kennung = (area_id or "").strip()
    if not kennung:
        return SPECIAL
    if is_rest_area(kennung):
        return REST
    if "labyrinth" in kennung.lower():
        return LABYRINTH
    if _DELVE_RE.match(kennung):
        return DELVE
    if _SIDE_AREA_RE.match(kennung):
        return SIDE_AREA
    if _MAP_RE.match(kennung):
        return MAP
    if _STORY_RE.match(kennung):
        return STORY
    return SPECIAL


# Ab wann ist eine Verweildauer keine Spielzeit mehr, sondern ein
# Feierabend in der offenen Instanz? Die Client.txt schreibt beim
# Beenden nichts; der Aufenthalt endet erst beim nächsten Start.
#
# Gemessen an Peters 1.108 abgeschlossenen Map-Aufenthalten: Median
# 2,4 min, 95. Perzentil 9,4 min, 99. Perzentil 21,8 min — und das
# Maximum bei 1.175 min, also 19,6 Stunden. Über einer Stunde liegen
# 7 Aufenthalte (0,6 %). Die Grenze trifft damit fast nur das, was sie
# treffen soll; ein echter, sehr langer Lauf faellt zwar aus dem
# Schnitt, bleibt aber als Besuch gezählt.
_MAX_DWELL_S = 3600.0

# Karten-Tier aus dem Gebietslevel: Tier 1 ist Level 68, Tier 16 ist 83.
# Peter, 2026-09-26: "Hier zählt natürlich nur die niedrigmöglichste Tier
# der Map" — dieselbe Karte kann über eine Season hinweg auf mehreren
# Leveln erscheinen (Atlas-Umbau, Varianten), gemeint ist die Karte
# selbst, also ihr niedrigster Wert.
_TIER_ONE_LEVEL = 67


def map_tier_from_level(level: int) -> int | None:
    """``None`` für alles außerhalb von Tier 1–17 — Story-Gebiete,
    Delve-Tiefen und Hideouts haben keine Tier, und eine ausgerechnete
    wäre schlicht erfunden."""
    if not level:
        return None
    tier = level - _TIER_ONE_LEVEL
    return tier if 1 <= tier <= 17 else None


@dataclass
class LeagueStats:
    """Was ein Gebiet in EINER Liga war. Getrennt gehalten aus zwei
    Gründen: Der Atlas baut sich mit jeder Season um (Chateau stand vor
    dem 24.07. auf 76 und danach auf 68), und die Ligen einer Season
    haben verschiedene Inhalte — Vaal-Side-Areas gibt es in Ruthless
    gar nicht. Liga-Namen tragen die Season bereits in sich ("SSF R
    Allflame"), eine Season-Ebene obendrauf wäre doppelt.

    ``seconds`` ist die Summe der Verweildauern, nicht ihr Mittel: Der
    Durchschnitt lässt sich daraus jederzeit bilden, die Summe aus dem
    Durchschnitt aber nicht wieder zusammensetzen, sobald ein Besuch
    dazukommt."""

    levels: set[int] = field(default_factory=set)
    visits: int = 0
    deaths: int = 0
    seconds: float = 0.0
    timed_visits: int = 0        # Besuche, deren Dauer in ``seconds`` steckt
    last_seen: str = ""          # ISO-Zeit, wie in der Client.txt gelesen

    @property
    def average_seconds(self) -> float:
        """Nur über Aufenthalte mit brauchbarer Dauer (§_MAX_DWELL_S) —
        sonst zöge ein einziger Feierabend den Schnitt einer Karte auf
        eine Stunde hoch."""
        return self.seconds / self.timed_visits if self.timed_visits else 0.0


@dataclass
class ZoneRecord:
    """Ein Gebiet, je Liga so oft gesehen wie es gesehen wurde.

    Innerhalb einer Liga sammelt ``levels`` trotzdem mehrere Werte:
    ``Delve_Main`` wandert mit der Tiefe, ``DeepwaterEncounter`` mit dem
    Fortschritt. Gemessen an Peters Log betrifft das 7 von 317 Gebieten
    — die Ausnahme, nicht die Regel, und genau deshalb bleibt sie
    sichtbar."""

    area_id: str
    name: str
    category: str
    leagues: dict[str, LeagueStats] = field(default_factory=dict)

    def stats(self, league: str | None) -> LeagueStats:
        """Die Zahlen einer Liga, oder — mit ``None`` — aller zusammen.
        Ein Gebiet, das in dieser Liga nie betreten wurde, liefert leere
        Zahlen statt eines Fehlers."""
        if league is not None:
            return self.leagues.get(league, LeagueStats())
        gesamt = LeagueStats()
        for eintrag in self.leagues.values():
            gesamt.levels |= eintrag.levels
            gesamt.visits += eintrag.visits
            gesamt.deaths += eintrag.deaths
            gesamt.seconds += eintrag.seconds
            gesamt.timed_visits += eintrag.timed_visits
            gesamt.last_seen = max(gesamt.last_seen, eintrag.last_seen)
        return gesamt

    def seen_in(self, league: str | None) -> bool:
        return league is None or league in self.leagues

    def level_text(self, league: str | None = None) -> str:
        """"68" oder "70–77" — was in der Spalte steht."""
        levels = self.stats(league).levels
        if not levels:
            return "?"
        tief, hoch = min(levels), max(levels)
        return str(tief) if tief == hoch else f"{tief}–{hoch}"

    def max_level(self, league: str | None = None) -> int:
        """Für die Sortierung: der höchste in dieser Liga gesehene Level."""
        levels = self.stats(league).levels
        return max(levels) if levels else 0

    def tier(self, league: str | None = None) -> int | None:
        """Die Karten-Tier, aus dem NIEDRIGSTEN gesehenen Level (Peter:
        "Hier zählt natürlich nur die niedrigmöglichste Tier der Map").
        ``None`` für alles, was keine Karte ist."""
        if self.category not in (MAP, SIDE_AREA):
            return None
        levels = self.stats(league).levels
        return map_tier_from_level(min(levels)) if levels else None


def catalog_path(account_name: str) -> Path:
    """Wie bei der Mod-Sammlung eine Datei je Konto. Als Funktion, nicht
    als Modul-Konstante: Die Testfixture patcht ``APP_DATA_DIR``, eine
    eingefrorene Konstante würde an Peters echtem Ordner hängen
    (CLAUDE.md, "Tests")."""
    sicher = re.sub(r"[^A-Za-z0-9#_-]", "_", account_name or "unknown")
    return config.APP_DATA_DIR / f"zone-catalog-{sicher}.json"


def merge_stays(records: dict[str, ZoneRecord], stays,
                league_of=None, deaths=None) -> int:
    """Aufenthalte in den Katalog einarbeiten; liefert die Zahl der
    NEUEN Gebiete. Ein Aufenthalt ohne Kennung wird übergangen — ohne
    sie ließe sich weder Gruppe noch Wiedererkennung bestimmen.

    ``league_of(zeitpunkt) -> str`` sagt, in welcher Liga damals
    gespielt wurde (``league_log.league_at``); ohne die Funktion landet
    alles unter ``UNKNOWN``. ``deaths`` ist eine sortierte Liste von
    Zeitpunkten (``zone_watcher.deaths_since``), die den Aufenthalten
    zugeordnet werden, in die sie fallen."""
    neu = 0
    todeszeiten = sorted(deaths or [])
    for stay in stays:
        if not stay.area_id:
            continue
        eintrag = records.get(stay.area_id)
        if eintrag is None:
            eintrag = ZoneRecord(area_id=stay.area_id, name=stay.name,
                                 category=categorise(stay.area_id))
            records[stay.area_id] = eintrag
            neu += 1
        liga = league_of(stay.entered) if league_of else UNKNOWN
        zahlen = eintrag.leagues.setdefault(liga or UNKNOWN, LeagueStats())
        if stay.level:
            zahlen.levels.add(stay.level)
        # Der angezeigte Name kann sich ändern (Hideout umbenannt, Sprache
        # umgestellt) — der zuletzt gesehene gewinnt.
        eintrag.name = stay.name or eintrag.name
        zahlen.visits += 1
        if 0 < stay.seconds <= _MAX_DWELL_S:
            zahlen.seconds += stay.seconds
            zahlen.timed_visits += 1
        zahlen.deaths += _deaths_within(todeszeiten, stay)
        zeit = stay.entered.isoformat(timespec="seconds")
        if zeit > zahlen.last_seen:
            zahlen.last_seen = zeit
    return neu


def _deaths_within(todeszeiten: list, stay) -> int:
    """Wie viele Tode fallen in diesen Aufenthalt? Der laufende
    Aufenthalt (``left is None``) bekommt keine — er ist nach oben
    offen, und ein Tod danach gehörte zur nächsten Zone."""
    if stay.left is None or not todeszeiten:
        return 0
    links = bisect_left(todeszeiten, stay.entered)
    rechts = bisect_left(todeszeiten, stay.left)
    return rechts - links


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
                leagues={
                    str(name): LeagueStats(
                        levels={int(x) for x in (werte.get("levels") or [])},
                        visits=int(werte.get("visits") or 0),
                        deaths=int(werte.get("deaths") or 0),
                        seconds=float(werte.get("seconds") or 0.0),
                        timed_visits=int(werte.get("timed_visits") or 0),
                        last_seen=str(werte.get("last_seen") or ""))
                    for name, werte in (zeile.get("leagues") or {}).items()
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
             "leagues": {
                 name: {"levels": sorted(werte.levels), "visits": werte.visits,
                        "deaths": werte.deaths, "seconds": round(werte.seconds, 1),
                        "timed_visits": werte.timed_visits,
                        "last_seen": werte.last_seen}
                 for name, werte in sorted(r.leagues.items())}}
            for r in sorted(records.values(), key=lambda r: r.area_id)
        ],
    })


def _fingerabdruck(records: dict[str, ZoneRecord]) -> str:
    return json.dumps([(r.area_id, sorted(r.leagues), r.stats(None).visits,
                        r.stats(None).deaths, sorted(r.stats(None).levels))
                       for r in sorted(records.values(), key=lambda r: r.area_id)])


def refresh_from_log(log_path: Path, account_name: str,
                     league_of=None, deaths=None) -> dict[str, ZoneRecord]:
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
                league_of, deaths)
    nachher = _fingerabdruck(records)
    if nachher != vorher:
        try:
            save(pfad, records)
        except OSError as fehler:
            log.warning("Zonen-Katalog nicht speicherbar (%s): %s", pfad, fehler)
    return records


def _newest(records: dict[str, ZoneRecord]) -> str:
    return max((werte.last_seen for r in records.values()
                for werte in r.leagues.values()), default="")
