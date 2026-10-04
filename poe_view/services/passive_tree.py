"""Der Passiv-Baum: GGGs Baumdaten, der vergebene Baum eines Charakters
und was sich daraus ablesen lässt (§4.60).

Peter, 2026-10-04: "Wir sollten für den Baum auch eine Export-Funktion
integrieren um z.B. eine Einschätzung von dir zur Skillpunktvergabe holen
zu können." Er spielt Ruthless SSF ohne Guide — die Frage ist meist, wohin
die nächsten Punkte sollen. Deshalb neben dem vergebenen Baum die Liste
"Within reach": Notables, Keystones und Jewel-Sockel, die höchstens
``REACH_POINTS`` Punkte entfernt liegen, samt Weg.

**Quelle der Knotendaten:** GGGs eigenes Repo ``grindinggear/skilltree-
export``. Es trägt KEINE Lizenz — die Dateien kommen deshalb wie das
Mod-Wissen (§mod_knowledge) zur Laufzeit und werden lokal vorgehalten,
nicht ins Repo gelegt.

**Ruthless hat einen eigenen Baum** (``ruthless.json``): gleiche Knoten
und Lage, aber 118 Knoten mit anderen Werten (gemessen 2026-10-04, z. B.
Aspect of Carnage 25 statt 40 % more Damage). Für eine Einschätzung ist
der falsche Baum schlimmer als keiner; ``is_ruthless`` entscheidet.

Was die API zum Baum liefert (``/character/<name>``, Feld ``passives``):
``hashes`` (vergebene Knoten), ``hashes_ex`` (Knoten in Cluster-Jewels),
``mastery_effects``, ``jewel_data``, ``bandit_choice``,
``pantheon_major``/``_minor``. Bisher wurde das weggeworfen.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from poe_view import config

log = logging.getLogger(__name__)

_BASE_URL = "https://raw.githubusercontent.com/grindinggear/skilltree-export/master"
_FILE = {False: "data.json", True: "ruthless.json"}
_DIR_NAME = "passive-tree"
# Wie beim Mod-Wissen: Der Baum ändert sich mit Patches, nicht mit Sitzungen.
TTL_SECONDS = 7 * 24 * 3600
CACHE_VERSION = 1

# Peter, 2026-10-04: "beides passt" — vier Punkte Reichweite.
REACH_POINTS = 4


def tree_dir() -> Path:
    """Funktion statt Konstante (CLAUDE.md, "Tests")."""
    return config.APP_DATA_DIR / _DIR_NAME


def _manifest_path() -> Path:
    return tree_dir() / "manifest.json"


def is_fresh() -> bool:
    try:
        manifest = json.loads(_manifest_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if manifest.get("version") != CACHE_VERSION:
        return False
    if not all((tree_dir() / name).is_file() for name in _FILE.values()):
        return False
    return time.time() - manifest.get("fetched_at", 0) <= TTL_SECONDS


def fetch(http: httpx.Client | None = None) -> bool:
    """Beide Bäume neu laden; erst schreiben, wenn beide da sind
    (dieselbe Regel wie §mod_knowledge.fetch). Ein Fehler lässt den
    bisherigen Stand stehen."""
    owns_client = http is None
    client = http or httpx.Client(
        timeout=60.0, headers={"User-Agent": config.user_agent()}, follow_redirects=True)
    try:
        payloads: dict[str, bytes] = {}
        for name in _FILE.values():
            resp = client.get(f"{_BASE_URL}/{name}")
            if resp.status_code != 200:
                log.warning("Passiv-Baum: Download von %s fehlgeschlagen (Status %s)",
                            name, resp.status_code)
                return False
            payloads[name] = resp.content
        ziel = tree_dir()
        ziel.mkdir(parents=True, exist_ok=True)
        for name, data in payloads.items():
            tmp = ziel / f"{name}.tmp"
            tmp.write_bytes(data)
            tmp.replace(ziel / name)
        _manifest_path().write_text(
            json.dumps({"version": CACHE_VERSION, "fetched_at": time.time()}), encoding="utf-8")
        _LOADED.clear()
        log.info("Passiv-Baum: Daten neu geladen (%s).", ", ".join(_FILE.values()))
        return True
    except (httpx.HTTPError, OSError):
        log.exception("Passiv-Baum: Download fehlgeschlagen")
        return False
    finally:
        if owns_client:
            client.close()


def ensure_fresh(http: httpx.Client | None = None) -> bool:
    return True if is_fresh() else fetch(http)


# --- Baumdaten ------------------------------------------------------------ #

KEYSTONE, NOTABLE, MASTERY, JEWEL, SMALL, START = (
    "keystone", "notable", "mastery", "jewel socket", "small", "start")


@dataclass
class Node:
    id: int
    name: str
    kind: str
    stats: tuple[str, ...] = ()
    ascendancy: str = ""
    neighbours: set[int] = field(default_factory=set)
    # Mastery: Effekt-Kennung → Werte (§mastery_choices).
    effects: dict[int, tuple[str, ...]] = field(default_factory=dict)
    # Startknoten einer Klasse: Durch fremde Starts führt kein Weg.
    class_start: bool = False


@dataclass
class Tree:
    nodes: dict[int, Node]
    jewel_slots: list[int]
    ruthless: bool
    # Klasse UND jede ihrer Aszendenzen → Startknoten der Klasse; die API
    # nennt als ``class`` die Aszendenz, sobald eine gewählt ist.
    class_starts: dict[str, int] = field(default_factory=dict)


def _kind(roh: dict) -> str:
    if roh.get("isAscendancyStart") or "classStartIndex" in roh:
        return START
    if roh.get("isKeystone"):
        return KEYSTONE
    if roh.get("isMastery"):
        return MASTERY
    if roh.get("isJewelSocket"):
        return JEWEL
    if roh.get("isNotable"):
        return NOTABLE
    return SMALL


def _lines(stats) -> tuple[str, ...]:
    """Je Wert eine Zeile. Ein Zeilenumbruch IN einem Wert ist bei GGG
    mal eine zweite Eigenschaft (Divine Shield), mal nur ein Umbruch
    mitten im Satz (Untiring: "...Hits in the past\\n10 seconds is
    Regenerated..."). Zerlegen hätte den Satz zerrissen; " / " liest
    sich in beiden Fällen."""
    return tuple(" / ".join(t.strip() for t in str(zeile).split("\n") if t.strip())
                 for zeile in stats or () if str(zeile).strip())


def parse_tree(roh: dict, ruthless: bool) -> Tree:
    nodes: dict[int, Node] = {}
    for schluessel, eintrag in (roh.get("nodes") or {}).items():
        if not str(schluessel).isdigit():
            continue                       # "root"
        nodes[int(schluessel)] = Node(
            id=int(schluessel), name=str(eintrag.get("name", "")), kind=_kind(eintrag),
            stats=_lines(eintrag.get("stats")),
            ascendancy=str(eintrag.get("ascendancyName") or ""),
            effects={int(e["effect"]): _lines(e.get("stats"))
                     for e in eintrag.get("masteryEffects") or () if "effect" in e},
            class_start="classStartIndex" in eintrag)
    # Verbindungen in beide Richtungen: "out" und "in" nennen jede Kante nur
    # einmal, gegangen werden darf sie in beide.
    for schluessel, eintrag in (roh.get("nodes") or {}).items():
        if not str(schluessel).isdigit():
            continue
        a = int(schluessel)
        for b in eintrag.get("out") or ():
            b = int(b)
            if b in nodes:
                nodes[a].neighbours.add(b)
                nodes[b].neighbours.add(a)
    start_je_index = {int(e["classStartIndex"]): int(k)
                      for k, e in (roh.get("nodes") or {}).items()
                      if str(k).isdigit() and "classStartIndex" in e}
    starts: dict[str, int] = {}
    for index, klasse in enumerate(roh.get("classes") or ()):
        if index not in start_je_index:
            continue
        starts[str(klasse.get("name", ""))] = start_je_index[index]
        for aszendenz in klasse.get("ascendancies") or ():
            starts[str(aszendenz.get("name", aszendenz.get("id", "")))] = start_je_index[index]
    return Tree(nodes=nodes, jewel_slots=[int(s) for s in roh.get("jewelSlots") or ()],
                ruthless=ruthless, class_starts=starts)


# Geparst wird einmal je Datei-Stand: (Pfad, Änderungszeit) → Baum. Ein
# neuer Download oder ein anderes Datenverzeichnis (Tests) lädt neu.
_LOADED: dict[bool, tuple[Path, float, Tree]] = {}


def load(ruthless: bool) -> Tree | None:
    """Den Baum aus dem lokalen Vorrat; ``None``, solange er fehlt."""
    pfad = tree_dir() / _FILE[ruthless]
    try:
        stand = pfad.stat().st_mtime
    except OSError:
        return None
    vorrat = _LOADED.get(ruthless)
    if vorrat and vorrat[0] == pfad and vorrat[1] == stand:
        return vorrat[2]
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    _LOADED[ruthless] = (pfad, stand, parse_tree(roh, ruthless))
    return _LOADED[ruthless][2]


# --- Der Baum eines Charakters ------------------------------------------- #

_RUTHLESS_LEAGUE = re.compile(r"\bruthless\b|(^|\s)R(\s|$)", re.IGNORECASE)


def is_ruthless(passives: dict, league: str = "") -> bool:
    """Das API-Feld ``ruthless`` zuerst (``store_payload`` legt es zum Baum);
    fehlt es, der Liga-Name ("SSF R Allflame", "Ruthless Mercenaries")."""
    flag = passives.get("ruthless") if passives else None
    if isinstance(flag, bool):
        return flag
    return bool(_RUTHLESS_LEAGUE.search(league or ""))


def allocated(passives: dict) -> set[int]:
    return {int(h) for h in (passives or {}).get("hashes") or () if str(h).lstrip("-").isdigit()}


def mastery_choices(passives: dict) -> dict[int, int]:
    """Mastery-Knoten → gewählter Effekt. Laut GGG-Schema ein Objekt
    ``{"<knoten>": effekt}``; ältere Antworten (und PoB) packen beides in
    eine Zahl: ``effekt << 16 | knoten``. Beides wird verstanden."""
    roh = (passives or {}).get("mastery_effects") or {}
    if isinstance(roh, dict):
        return {int(k): int(v) for k, v in roh.items() if str(k).isdigit()}
    return {int(v) & 0xFFFF: int(v) >> 16 for v in roh if isinstance(v, int)}


@dataclass
class Reach:
    node: Node
    cost: int
    via: list[Node]          # die Knoten dazwischen, ohne das Ziel


def within_reach(tree: Tree, have: set[int], max_points: int = REACH_POINTS,
                 class_name: str = "") -> list[Reach]:
    """Notables, Keystones und Jewel-Sockel, die mit höchstens
    ``max_points`` weiteren Punkten erreichbar sind — Breitensuche von allen
    vergebenen Knoten gleichzeitig; jeder neue Knoten kostet einen Punkt.

    Nicht betreten werden: Aszendenz-Knoten (eigener Baum mit eigenen
    Punkten), Masteries (man erreicht sie über ihre Gruppe, sie liegen auf
    keinem Weg), fremde Klassen-Starts (der Baum lässt sie nicht
    durchqueren)."""
    def begehbar(n: Node) -> bool:
        return not n.ascendancy and n.kind not in (MASTERY,) and not n.class_start

    abstand: dict[int, int] = {}
    vorher: dict[int, int] = {}
    schlange: deque[int] = deque()
    quellen = set(have)
    # Der eigene Startknoten zählt als vergeben — er steht nie in ``hashes``,
    # ist aber der Anfang jedes Weges (ein frischer Charakter hat sonst
    # nichts, von dem aus man suchen könnte).
    if class_name in tree.class_starts:
        quellen.add(tree.class_starts[class_name])
    for h in quellen:
        if h in tree.nodes and not tree.nodes[h].ascendancy:
            abstand[h] = 0
            schlange.append(h)
    while schlange:
        a = schlange.popleft()
        if abstand[a] >= max_points:
            continue
        for b in sorted(tree.nodes[a].neighbours):
            if b in abstand or not begehbar(tree.nodes[b]):
                continue
            abstand[b] = abstand[a] + 1
            vorher[b] = a
            schlange.append(b)
    ergebnis = []
    for h, kosten in abstand.items():
        knoten = tree.nodes[h]
        if kosten == 0 or knoten.kind not in (NOTABLE, KEYSTONE, JEWEL):
            continue
        weg, schritt = [], vorher.get(h)
        while schritt is not None and abstand.get(schritt, 0) > 0:
            weg.append(tree.nodes[schritt])
            schritt = vorher.get(schritt)
        ergebnis.append(Reach(knoten, kosten, list(reversed(weg))))
    return sorted(ergebnis, key=lambda r: (r.cost, r.node.kind != KEYSTONE, r.node.name))


_ZAHL = re.compile(r"\d+(?:\.\d+)?")


def summed_stats(lines) -> list[str]:
    """Gleichlautende Zeilen zusammenzählen: zweimal "+10 to Strength" wird
    "+20 to Strength". Gleich heißt: gleich bis auf die Zahlen, und
    gleich viele Zahlen."""
    summen: dict[str, list[float]] = {}
    reihenfolge: list[str] = []
    for zeile in lines:
        vorlage = _ZAHL.sub("#", zeile)
        werte = [float(z) for z in _ZAHL.findall(zeile)]
        if vorlage not in summen:
            summen[vorlage] = werte
            reihenfolge.append(vorlage)
        elif len(summen[vorlage]) == len(werte):
            summen[vorlage] = [a + b for a, b in zip(summen[vorlage], werte)]
    ergebnis = []
    for vorlage in reihenfolge:
        werte = iter(summen[vorlage])
        ergebnis.append(re.sub("#", lambda _m: _zahl_text(next(werte)), vorlage))
    # Sortiert nach dem ersten Wort, nicht nach Zahl oder Vorzeichen.
    return sorted(ergebnis, key=lambda z: re.sub(r"^[^A-Za-z]+", "", _ZAHL.sub("", z)).lower())


def _zahl_text(wert: float) -> str:
    return str(int(wert)) if wert == int(wert) else f"{wert:g}"
