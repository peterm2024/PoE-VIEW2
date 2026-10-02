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

**Eine Zone hat keine Stufe — ein Besuch hat eine** (seit 2026-09-27,
VERSION 4). Peters Karten sind nummerierte Items ("Map (Tier 4)") mit
dem Text *"Travel to a Map of this tier or lower"*: Der Gebietslevel
kommt vom Karten-Item, das Ziel wird aus dieser Stufe oder darunter
gezogen. Dieselbe Zone erscheint deshalb je nach eingelegter Karte mit
verschiedenen Leveln — Bazaar mit Tier 4 auf 71, mit Tier 5 auf 72.
Besuche, Tode und Verweildauer werden darum je Level gezählt
(§LevelStats), nicht je Liga.

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
from poe_view.services.zone_watcher import is_rest_area, kill_readings, zone_stays

log = logging.getLogger(__name__)

# Version 3 (2026-09-27): je LIGA statt je Season (Liga-Namen tragen die
# Season in sich, und die Ligen einer Season haben verschiedene Inhalte),
# dazu Tode und Verweildauer. Ältere Versionen werden verworfen statt
# umgerechnet — sie wüssten die Liga nicht, und der Katalog baut sich aus
# der Client.txt in einem Zehntel einer Sekunde neu auf.
#
# Version 5 (2026-10-01): "Visits" zählt KARTEN (eine je Seed), die neue
# Zahl ``entries`` die Eintritte — vorher war jeder Gang zum Händler und
# zurück ein eigener Besuch (§LevelStats). Aus gespeicherten Zahlen
# lässt sich das nicht nachrechnen; der Katalog baut sich neu aus der
# Client.txt auf, was dort schon gekürzt ist, geht verloren.
VERSION = 5

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


# Gruppen, in denen eine Kartenstufe überhaupt eine Bedeutung hat. Ein
# Story-Gebiet hat keine, und eine ausgerechnete wäre erfunden.
TIER_CATEGORIES = (MAP, SIDE_AREA)


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
    if is_rest_area(kennung):        # ohne Level: die Minen-Basis
        # bleibt in der Delve-Gruppe, wo sie hingehört — die
        # Tabelle trennt sie ohnehin als eigene Zeile (§LevelStats).
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


# Schlüssel für Aufenthalte OHNE Gebietslevel. Die Client.txt schreibt
# die Zeile ``Generating level N area`` nur als DEBUG-Eintrag; fehlt sie,
# gibt es trotzdem einen Besuch zu zählen. Er landet unter 0 und bleibt
# damit aus jeder Level-Anzeige heraus, ohne verloren zu gehen.
NO_LEVEL = 0

# Seeds, die nichts über den einzelnen Besuch sagen: Hideout und Städte
# haben einen festen Grundriss und stehen immer auf Seed 1 (an Peters
# Log: der einzige Seed, der über mehr als sechs Stunden wiederkehrt,
# bei 13 Ruhezonen). Dort bleibt jeder Eintritt ein Besuch — eine
# Rückkehr ins Hideout IST ein neuer Aufenthalt, kein Teil des alten.
# Leer heißt: Die Client.txt nannte keinen.
_FIXED_SEEDS = frozenset({"", "1"})


@dataclass
class LevelStats:
    """Was ein Gebiet bei EINEM Gebietslevel war.

    **Die Ebene, die erst 2026-09-27 dazukam** — und der Grund dafür ist
    eine Messung an Peters Truhe. Seine Karten sind keine benannten
    Karten, sondern nummerierte Items ("Map (Tier 4)") mit dem Text
    *"Travel to a Map of this tier or lower"*. Der Gebietslevel hängt
    damit am KARTEN-ITEM, nicht an der Zone: Bazaar erschien mit einer
    Tier-4-Karte auf Level 71 und mit einer Tier-5-Karte auf Level 72.

    Eine Zone hat also keine Stufe, ein Besuch hat eine. Tode und
    Verweildauer über beide Stufen zu mitteln löscht genau das, wonach
    gefragt war (Peter: "zählen für jeden Tier getrennt") — eine
    Tier-1-Runde und eine Tier-9-Runde sind zwei verschiedene Inhalte,
    die zufällig denselben Namen tragen.

    ``seconds`` ist die Summe der Verweildauern, nicht ihr Mittel: Der
    Durchschnitt lässt sich daraus jederzeit bilden, die Summe aus dem
    Durchschnitt aber nicht wieder zusammensetzen, sobald ein Besuch
    dazukommt.

    **Ein Besuch ist eine Karte, nicht ein Eintritt** (seit 2026-10-01,
    VERSION 5). Peter: "wird hier jeder Besuch gezählt (auch
    Händlerbesuche) oder die gesamte Map?" — bis dahin jeder Eintritt.
    An seinem Log: 1.130 Karten-Eintritte für 359 tatsächlich gelaufene
    Karten, Faktor 3,15; nur 81 Karten liefen in einem Rutsch durch.
    Der Schnitt "2,5 Minuten pro Map" war damit die Zeit pro Eintritt.
    Erkannt wird dieselbe Karte an ihrem Seed (§zone_watcher._AREA_LINE):
    Ein neuer Besuch beginnt, sobald der Seed ein anderer ist als beim
    letzten Eintritt auf dieser Stufe. ``entries`` zählt weiterhin jeden
    Eintritt — viele Eintritte je Karte heißen viele Händlergänge oder
    viele Tode, auch das ist eine Auskunft.

    ``last_seed`` und ``last_seed_timed`` sind das Gedächtnis dafür über
    den Neustart hinweg: Der Katalog arbeitet die Client.txt in Stücken
    ein (§refresh_from_log), und eine Karte, die über zwei Stücke reicht,
    zählte sonst doppelt."""

    visits: int = 0              # Karten (eine je Seed, §_FIXED_SEEDS)
    deaths: int = 0
    seconds: float = 0.0
    timed_visits: int = 0        # Besuche, deren Dauer in ``seconds`` steckt
    last_seen: str = ""          # ISO-Zeit, wie in der Client.txt gelesen
    entries: int = 0             # jeder einzelne Eintritt
    last_seed: str = ""
    last_seed_timed: bool = False
    # /kills (§attribute_kills): getötete Monster und die Zeit in dieser
    # Stufe, über die sie gezählt sind. Eine RATE, kein Zähler je Besuch —
    # eine Ablesung mitten in der Map deckt nur einen Teil davon ab.
    kills: int = 0
    kill_seconds: float = 0.0

    @property
    def average_seconds(self) -> float:
        """Nur über Aufenthalte mit brauchbarer Dauer (§_MAX_DWELL_S) —
        sonst zöge ein einziger Feierabend den Schnitt einer Karte auf
        eine Stunde hoch."""
        return self.seconds / self.timed_visits if self.timed_visits else 0.0

    @property
    def kills_per_minute(self) -> float:
        return self.kills * 60 / self.kill_seconds if self.kill_seconds else 0.0

    @property
    def monsters_per_visit(self) -> float:
        """Hochgerechnet: Tempo × durchschnittliche Dauer eines Besuchs.
        0, wenn eins von beiden fehlt."""
        return self.kills_per_minute * self.average_seconds / 60


@dataclass
class LeagueStats:
    """Was ein Gebiet in EINER Liga war, aufgeschlüsselt nach
    Gebietslevel. Getrennt gehalten aus zwei Gründen: Der Atlas baut
    sich mit jeder Season um (Chateau stand vor dem 24.07. auf 76 und
    danach auf 68), und die Ligen einer Season haben verschiedene
    Inhalte — Vaal-Side-Areas gibt es in Ruthless gar nicht. Liga-Namen
    tragen die Season bereits in sich ("SSF R Allflame"), eine
    Season-Ebene obendrauf wäre doppelt.

    Die Summen darüber stehen als Eigenschaften bereit, damit die
    Aufrufer nicht wissen müssen, dass darunter mehrere Stufen liegen."""

    by_level: dict[int, LevelStats] = field(default_factory=dict)

    def at(self, level: int) -> LevelStats:
        """Die Zahlen einer Stufe — anlegen, falls es sie noch nicht
        gibt."""
        return self.by_level.setdefault(level, LevelStats())

    @property
    def levels(self) -> set[int]:
        """Die gesehenen Gebietslevel, ohne den Sammeleintrag für
        Aufenthalte ohne Angabe (§NO_LEVEL)."""
        return {lv for lv in self.by_level if lv != NO_LEVEL}

    @property
    def visits(self) -> int:
        return sum(w.visits for w in self.by_level.values())

    @property
    def deaths(self) -> int:
        return sum(w.deaths for w in self.by_level.values())

    @property
    def seconds(self) -> float:
        return sum(w.seconds for w in self.by_level.values())

    @property
    def timed_visits(self) -> int:
        return sum(w.timed_visits for w in self.by_level.values())

    @property
    def entries(self) -> int:
        return sum(w.entries for w in self.by_level.values())

    @property
    def last_seen(self) -> str:
        return max((w.last_seen for w in self.by_level.values()), default="")

    @property
    def average_seconds(self) -> float:
        return self.seconds / self.timed_visits if self.timed_visits else 0.0

    @property
    def kills(self) -> int:
        return sum(w.kills for w in self.by_level.values())

    @property
    def kill_seconds(self) -> float:
        return sum(w.kill_seconds for w in self.by_level.values())

    @property
    def kills_per_minute(self) -> float:
        return self.kills * 60 / self.kill_seconds if self.kill_seconds else 0.0

    @property
    def monsters_per_visit(self) -> float:
        return self.kills_per_minute * self.average_seconds / 60


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
            for level, werte in eintrag.by_level.items():
                ziel = gesamt.at(level)
                ziel.visits += werte.visits
                ziel.entries += werte.entries
                ziel.deaths += werte.deaths
                ziel.seconds += werte.seconds
                ziel.timed_visits += werte.timed_visits
                ziel.kills += werte.kills
                ziel.kill_seconds += werte.kill_seconds
                ziel.last_seen = max(ziel.last_seen, werte.last_seen)
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
        """Die NIEDRIGSTE gesehene Karten-Tier — die Zahl, nach der
        sortiert wird. ``None`` für alles, was keine Karte ist."""
        if self.category not in TIER_CATEGORIES:
            return None
        levels = self.stats(league).levels
        return map_tier_from_level(min(levels)) if levels else None

    def tier_text(self, league: str | None = None) -> str:
        """"4" oder "4–5" — was in der Spalte steht.

        Peter hatte ursprünglich nur die niedrigste Stufe bestellt
        ("Hier zählt natürlich nur die niedrigmöglichste Tier der Map"),
        unter der Annahme, eine Karte HABE eine feste Stufe. Die Messung
        an seiner Truhe hat das widerlegt (§LevelStats): Der Gebietslevel
        kommt vom Karten-Item, dieselbe Zone erscheint auf mehreren
        Stufen. Eine einzelne Zahl wäre damit die Antwort auf eine Frage,
        die so nicht mehr steht — die Spanne sagt, was wirklich vorkam."""
        if self.category not in TIER_CATEGORIES:
            return ""
        stufen = sorted({t for lv in self.stats(league).levels
                         if (t := map_tier_from_level(lv)) is not None})
        if not stufen:
            return ""
        return str(stufen[0]) if len(stufen) == 1 else f"{stufen[0]}–{stufen[-1]}"


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
        # Jeder Besuch zählt unter SEINEM Gebietslevel (§LevelStats) —
        # ohne Angabe unter ``NO_LEVEL``, damit er nicht verschwindet.
        stufe = zahlen.at(stay.level or NO_LEVEL)
        # Der angezeigte Name kann sich ändern (Hideout umbenannt, Sprache
        # umgestellt) — der zuletzt gesehene gewinnt.
        eintrag.name = stay.name or eintrag.name
        seed = getattr(stay, "seed", "")
        stufe.entries += 1
        if seed in _FIXED_SEEDS or seed != stufe.last_seed:
            stufe.visits += 1
            stufe.last_seed_timed = False
        stufe.last_seed = seed
        if 0 < stay.seconds <= _MAX_DWELL_S:
            stufe.seconds += stay.seconds
            # Gezählt wird die KARTE mit messbarer Dauer, nicht jeder
            # Eintritt — sonst hieße "Avg. time" wieder Zeit pro Eintritt.
            if not stufe.last_seed_timed:
                stufe.timed_visits += 1
                stufe.last_seed_timed = True
        stufe.deaths += _deaths_within(todeszeiten, stay)
        zeit = stay.entered.isoformat(timespec="seconds")
        if zeit > stufe.last_seen:
            stufe.last_seen = zeit
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
                    str(name): LeagueStats(by_level={
                        int(level): LevelStats(
                            visits=int(w.get("visits") or 0),
                            deaths=int(w.get("deaths") or 0),
                            seconds=float(w.get("seconds") or 0.0),
                            timed_visits=int(w.get("timed_visits") or 0),
                            last_seen=str(w.get("last_seen") or ""),
                            entries=int(w.get("entries") or 0),
                            last_seed=str(w.get("last_seed") or ""),
                            last_seed_timed=bool(w.get("last_seed_timed")),
                            kills=int(w.get("kills") or 0),
                            kill_seconds=float(w.get("kill_seconds") or 0.0))
                        for level, w in (werte.get("levels") or {}).items()})
                    for name, werte in (zeile.get("leagues") or {}).items()
                },
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return records


def save(path: Path, records: dict[str, ZoneRecord], kills_until: str = "") -> None:
    # Wie die Mod-Sammlung: Der Ordner kann beim allerersten Speichern
    # noch fehlen (``config.ensure_dirs`` lief nur für den echten Start,
    # nicht für einen Test mit gepatchtem APP_DATA_DIR).
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {
        "version": VERSION,
        # Bis wohin die /kills-Ablesungen eingearbeitet sind (§attribute_
        # kills). Ein neues Feld ohne Versionssprung: Fehlt es, werden
        # einfach alle Ablesungen der Datei einmal eingearbeitet.
        "kills_until": kills_until,
        "zones": [
            {"area_id": r.area_id, "name": r.name, "category": r.category,
             "leagues": {
                 name: {"levels": {
                     str(level): {"visits": w.visits, "deaths": w.deaths,
                                  "seconds": round(w.seconds, 1),
                                  "timed_visits": w.timed_visits,
                                  "last_seen": w.last_seen,
                                  "entries": w.entries,
                                  "last_seed": w.last_seed,
                                  "last_seed_timed": w.last_seed_timed,
                                  "kills": w.kills,
                                  "kill_seconds": round(w.kill_seconds, 1)}
                     for level, w in sorted(werte.by_level.items())}}
                 for name, werte in sorted(r.leagues.items())}}
            for r in sorted(records.values(), key=lambda r: r.area_id)
        ],
    })


def _fingerabdruck(records: dict[str, ZoneRecord]) -> str:
    return json.dumps([(r.area_id, sorted(r.leagues), r.stats(None).visits,
                        r.stats(None).entries, r.stats(None).deaths,
                        r.stats(None).kills, sorted(r.stats(None).levels))
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
    kills_bis = _load_kills_until(pfad) if records else ""
    vorher = _fingerabdruck(records)
    # Der Katalog zählt Besuche ab dem Beginn der Datei; ohne Grenze
    # würde jeder Aufruf dieselben Aufenthalte erneut zählen. Deshalb
    # zählt er nur, was seit dem letzten Lauf dazugekommen ist.
    #
    # Der LAUFENDE Aufenthalt bleibt draußen, bis er endet. Vorher wurde
    # er mitgezählt — mit 0 Sekunden und ohne Tode, denn beides steht erst
    # fest, wenn er vorbei ist —, und weil er danach vor der Grenze lag,
    # wurde er nie nachgetragen. Wer die Tabelle mitten in einer Map
    # öffnete, verlor deren Dauer und Tode für immer.
    seit = _newest(records)
    alle = zone_stays(log_path, datetime.min)
    merge_stays(records, [s for s in alle
                          if s.left is not None
                          and s.entered.isoformat(timespec="seconds") > seit],
                league_of, deaths)
    kills_neu = attribute_kills(records, alle, kill_readings(log_path),
                                league_of, kills_bis)
    nachher = _fingerabdruck(records)
    if nachher != vorher or kills_neu != kills_bis:
        try:
            save(pfad, records, kills_neu)
        except OSError as fehler:
            log.warning("Zonen-Katalog nicht speicherbar (%s): %s", pfad, fehler)
    return records


# Wie lange darf eine zweite Karte in einem Ablese-Abschnitt stehen, ohne
# ihn unbrauchbar zu machen? Wer der Erinnerung folgt (§kills_reminder),
# liest ein paar Sekunden nach dem Betreten der NEUEN Map ab — der
# Abschnitt enthält dann die ganze vorige Map und diese paar Sekunden.
# In ihnen fällt kaum ein Monster; sie fallen weg, statt den Abschnitt
# zu verwerfen.
_KILL_GRACE_S = 30.0


def _load_kills_until(path: Path) -> str:
    try:
        roh = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    wert = roh.get("kills_until") if isinstance(roh, dict) else ""
    return wert if isinstance(wert, str) else ""


def attribute_kills(records: dict[str, ZoneRecord], stays, readings,
                    league_of=None, since: str = "") -> str:
    """Die ``/kills``-Ablesungen den Karten zuordnen, zwischen denen sie
    liegen; liefert den Zeitpunkt der letzten eingearbeiteten Ablesung.

    Je zwei aufeinanderfolgende Ablesungen derselben Anmeldung bilden
    einen Abschnitt; ihr Unterschied sind die Monster darin. Zählen darf
    ein Abschnitt nur, wenn in ihm genau EINE Karte gespielt wurde —
    erkannt an Kennung, Stufe und Seed, Hideout und Städte zählen nicht
    mit (§is_rest_area). Bei zwei Karten ließe sich nicht sagen, welche
    wie viele hatte; der Abschnitt fällt weg. Eine Karte mit weniger als
    ``_KILL_GRACE_S`` im Abschnitt zählt dabei nicht als zweite.

    Gezählt werden Monster UND die Zeit in der Karte innerhalb des
    Abschnitts. Daraus wird ein Tempo, kein Wert je Besuch: Wer mitten in
    der Map abliest, deckt nur einen Teil von ihr ab, und eine Summe je
    Besuch wäre dann zu klein. Ein negativer Unterschied (ein anderer
    Charakter ohne erkannte Anmeldung dazwischen) wird übergangen.

    ``since`` ist die zuletzt eingearbeitete Ablesung (ISO): Abschnitte,
    die davor endeten, sind schon gezählt."""
    letzte = since
    kampf = [s for s in stays if s.area_id and not is_rest_area(s.area_id, s.level)]
    for vorher, nachher in zip(readings, readings[1:]):
        ende = nachher.at.isoformat(timespec="seconds")
        if ende <= since:
            continue
        letzte = max(letzte, ende)
        if vorher.session != nachher.session:
            continue
        unterschied = nachher.total - vorher.total
        if unterschied < 0:
            continue
        anteile: dict[tuple, list] = {}
        for stay in kampf:
            bis = stay.left or nachher.at
            beginn, schluss = max(stay.entered, vorher.at), min(bis, nachher.at)
            dauer = (schluss - beginn).total_seconds()
            if dauer <= 0:
                continue
            schluessel = (stay.area_id, stay.level, getattr(stay, "seed", ""))
            eintrag = anteile.setdefault(schluessel, [0.0, stay])
            eintrag[0] += dauer
        karten = {k: v for k, v in anteile.items() if v[0] >= _KILL_GRACE_S}
        if len(karten) != 1:
            continue
        # Ein Aufenthalt über ``_MAX_DWELL_S`` ist eine Pause, kein Spiel —
        # dieselbe Regel wie für die Durchschnittszeit. An Peters Log:
        # Underground Sea mit 11 Kills/min über 2,8 Stunden.
        if any(stay.seconds > _MAX_DWELL_S for stay in kampf
               if stay.left is not None and stay.entered < nachher.at
               and stay.left > vorher.at
               and (stay.area_id, stay.level, getattr(stay, "seed", "")) in karten):
            continue
        (area_id, level, _seed), (sekunden, stay) = next(iter(karten.items()))
        eintrag = records.get(area_id)
        if eintrag is None:
            continue
        liga = (league_of(stay.entered) if league_of else UNKNOWN) or UNKNOWN
        stufe = eintrag.leagues.setdefault(liga, LeagueStats()).at(level or NO_LEVEL)
        stufe.kills += unterschied
        stufe.kill_seconds += sekunden
    return letzte


def _newest(records: dict[str, ZoneRecord]) -> str:
    return max((werte.last_seen for r in records.values()
                for werte in r.leagues.values()), default="")
