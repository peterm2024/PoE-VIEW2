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
    # Lage im Baum (§4.60.4): Gruppe, Kreisbahn, Platz darauf und die
    # daraus gerechneten Koordinaten. ``proxy``: Platzhalter für Knoten
    # eines Cluster-Jewels — im Bild nicht gezeichnet.
    group: int = -1
    orbit: int = 0
    orbit_index: int = 0
    x: float = 0.0
    y: float = 0.0
    proxy: bool = False
    # Mittelpunkt der Gruppe und Halbmesser der Bahn — für die Bögen
    # zwischen Nachbarn auf derselben Bahn (§tree_graph).
    gx: float = 0.0
    gy: float = 0.0
    radius: float = 0.0


@dataclass
class ClassInfo:
    """Eine Klasse für die Bereiche im Bild (§4.60.5)."""
    index: int
    name: str
    start: int | None
    # Die höchsten Grundwerte: Marauder ("str",), Duelist ("str", "dex"),
    # Scion () — alle gleich, kein Schwerpunkt.
    attributes: tuple[str, ...]
    ascendancies: tuple[str, ...]


@dataclass
class Tree:
    nodes: dict[int, Node]
    jewel_slots: list[int]
    ruthless: bool
    # Klasse UND jede ihrer Aszendenzen → Startknoten der Klasse; die API
    # nennt als ``class`` die Aszendenz, sobald eine gewählt ist.
    class_starts: dict[str, int] = field(default_factory=dict)
    # Name → (Klassen-Index, Aszendenz-Index; 0 = keine), wie die Planer-
    # Links sie kodieren (§encode_url); und umgekehrt.
    class_ids: dict[str, tuple[int, int]] = field(default_factory=dict)
    classes: list[ClassInfo] = field(default_factory=list)


def _attributes(klasse: dict) -> tuple[str, ...]:
    werte = {a: int(klasse.get(f"base_{a}") or 0) for a in ("str", "dex", "int")}
    if len(set(werte.values())) < 2:
        return ()
    hoch = max(werte.values())
    return tuple(a for a, w in werte.items() if w == hoch)


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


# Winkel der Plätze auf einer Kreisbahn, in Grad. Bahnen mit 16 Plätzen
# nach GGGs README (3.17.0), Bahnen mit 40 Plätzen wie in Path of
# Building: alle 10° plus die 45°-Lagen. Gegen den echten Baum geprüft
# (2026-10-05): Verbundene Knoten derselben Gruppe auf Bahn 2/3 und 4
# liegen damit in 106 von 198 Fällen exakt auf einem Strahl, mit
# gleichmäßigen 9°-Schritten nur in 40 — dort häufen sich 3°-Versätze.
_WINKEL_16 = (0, 30, 45, 60, 90, 120, 135, 150, 180, 210, 225, 240, 270, 300, 315, 330)
_WINKEL_40 = (0, 10, 20, 30, 40, 45, 50, 60, 70, 80, 90, 100, 110, 120, 130, 135, 140, 150,
              160, 170, 180, 190, 200, 210, 220, 225, 230, 240, 250, 260, 270, 280, 290, 300,
              310, 315, 320, 330, 340, 350)


def orbit_angle(plaetze: int, index: int) -> float:
    """Winkel in Grad, im Uhrzeigersinn von oben."""
    if plaetze == 16 and 0 <= index < 16:
        return float(_WINKEL_16[index])
    if plaetze == 40 and 0 <= index < 40:
        return float(_WINKEL_40[index])
    return 360.0 * index / plaetze if plaetze else 0.0


def _place(nodes: dict, roh: dict) -> None:
    import math
    konst = roh.get("constants") or {}
    plaetze = konst.get("skillsPerOrbit") or []
    radien = konst.get("orbitRadii") or []
    gruppen = roh.get("groups") or {}
    for knoten in nodes.values():
        gruppe = gruppen.get(str(knoten.group))
        if gruppe is None or knoten.orbit >= len(radien):
            continue
        winkel = math.radians(orbit_angle(plaetze[knoten.orbit] if knoten.orbit < len(plaetze)
                                          else 0, knoten.orbit_index))
        knoten.gx, knoten.gy = float(gruppe.get("x", 0)), float(gruppe.get("y", 0))
        knoten.radius = float(radien[knoten.orbit])
        knoten.x = knoten.gx + math.sin(winkel) * knoten.radius
        knoten.y = knoten.gy - math.cos(winkel) * knoten.radius


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
            class_start="classStartIndex" in eintrag,
            group=int(eintrag.get("group", -1)), orbit=int(eintrag.get("orbit", 0)),
            orbit_index=int(eintrag.get("orbitIndex", 0)),
            proxy=bool(eintrag.get("isProxy")))
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
    _place(nodes, roh)
    start_je_index = {int(e["classStartIndex"]): int(k)
                      for k, e in (roh.get("nodes") or {}).items()
                      if str(k).isdigit() and "classStartIndex" in e}
    # Die Startknoten heißen in GGGs Daten MARAUDER, WITCH … — und der
    # Scion "SEVEN" (Peter, 2026-10-05: "Wie kommst du auf Seven?"). Für
    # die Anzeige der Klassenname aus "classes".
    klassen = roh.get("classes") or ()
    for index, knoten_id in start_je_index.items():
        if 0 <= index < len(klassen) and knoten_id in nodes:
            nodes[knoten_id].name = str(klassen[index].get("name") or nodes[knoten_id].name)
    starts: dict[str, int] = {}
    ids: dict[str, tuple[int, int]] = {}
    infos: list[ClassInfo] = []
    for index, klasse in enumerate(roh.get("classes") or ()):
        ids[str(klasse.get("name", ""))] = (index, 0)
        aszendenzen = []
        for nummer, aszendenz in enumerate(klasse.get("ascendancies") or (), start=1):
            aszendenzen.append(str(aszendenz.get("name", aszendenz.get("id", ""))))
            ids[aszendenzen[-1]] = (index, nummer)
        if index in start_je_index:
            for name, (k, _a) in ids.items():
                if k == index:
                    starts[name] = start_je_index[index]
        infos.append(ClassInfo(index, str(klasse.get("name", "")), start_je_index.get(index),
                               _attributes(klasse), tuple(aszendenzen)))
    return Tree(nodes=nodes, jewel_slots=[int(s) for s in roh.get("jewelSlots") or ()],
                ruthless=ruthless, class_starts=starts, class_ids=ids, classes=infos)


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


# --- Bearbeiten per Klick (§4.60.6) ---------------------------------------- #
#
# Peter, 2026-10-05, Stufe 3: Konfigurationen im Bild bauen. Klick nimmt
# einen Knoten samt kürzestem Weg, Rechtsklick nimmt ihn zurück — samt
# allem, was danach keinen Weg mehr zum Start hätte (wie der offizielle
# Planer). Alle Funktionen geben ein NEUES ``passives`` zurück; der Rest
# (Jewels, Bandit, Pantheon) wird unverändert mitgenommen.


def _begehbar(n: Node) -> bool:
    return not n.ascendancy and n.kind != MASTERY and not n.class_start


def path_to(tree: Tree, have: set[int], target: int, class_name: str = "") -> list[int] | None:
    """Die Knoten, die für ``target`` neu dazukommen (Ziel zuletzt), auf dem
    kürzesten Weg vom vergebenen Baum aus. ``[]``: schon vergeben;
    ``None``: nicht erreichbar oder nicht auf diesem Weg zu nehmen."""
    if target in have:
        return []
    ziel = tree.nodes.get(target)
    if ziel is None or not _begehbar(ziel):
        return None
    quellen = {h for h in have if h in tree.nodes and not tree.nodes[h].ascendancy}
    if class_name in tree.class_starts:
        quellen.add(tree.class_starts[class_name])
    vorher: dict[int, int | None] = {h: None for h in quellen}
    schlange = deque(sorted(quellen))
    while schlange:
        a = schlange.popleft()
        if a == target:
            weg = []
            while a is not None and a not in quellen:
                weg.append(a)
                a = vorher[a]
            return list(reversed(weg))
        for b in sorted(tree.nodes[a].neighbours):
            if b not in vorher and _begehbar(tree.nodes[b]):
                vorher[b] = a
                schlange.append(b)
    return None


def cut_off(tree: Tree, have: set[int], node: int, class_name: str = "") -> set[int]:
    """Was mit ``node`` wegfällt: er selbst und alles im Hauptbaum, was
    danach keinen Weg mehr zum eigenen Start hat — samt Masteries, deren
    Gruppe kein Notable mehr hat."""
    weg = {node}
    start = tree.class_starts.get(class_name)
    haupt = {h for h in have if h in tree.nodes and not tree.nodes[h].ascendancy
             and tree.nodes[h].kind != MASTERY and h != node}
    if start is not None:
        gesehen, schlange = {start}, deque([start])
        while schlange:
            a = schlange.popleft()
            for b in tree.nodes[a].neighbours:
                if b in haupt and b not in gesehen:
                    gesehen.add(b)
                    schlange.append(b)
        weg |= haupt - gesehen
    bleibt = have - weg
    for h in have:
        if h in tree.nodes and tree.nodes[h].kind == MASTERY and not mastery_allowed(
                tree, bleibt, h):
            weg.add(h)
    return weg


def mastery_allowed(tree: Tree, have: set[int], mastery: int) -> bool:
    """Eine Mastery braucht ein vergebenes Notable in ihrer Gruppe (so in
    allen sechs Masteries von Peters Baum, 2026-10-05)."""
    m = tree.nodes.get(mastery)
    if m is None or m.kind != MASTERY or m.group < 0:
        return False
    return any(h in tree.nodes and tree.nodes[h].group == m.group
               and tree.nodes[h].kind == NOTABLE for h in have)


# Quest-Punkte: 24, wenn alle drei Banditen getötet wurden, sonst 23
# (poewiki.net "Passive skill": "23 points from quests, and 1 optional
# point from the quest Deal with the Bandits if all three Bandit Lords
# were killed" — seit 3.23). Peters echte Bäume bestätigen es genau,
# Standard wie Ruthless (§4.60.6).
QUEST_POINTS = 24
HELPED_BANDITS = ("Kraityn", "Alira", "Oak")


def max_points(level: int, bandit: str | None = None) -> int:
    """Höchstens verfügbare Punkte: einer je Level ab 2, dazu alle
    Quest-Punkte — einer weniger, wenn einem Banditen geholfen wurde
    (API ``bandit_choice``; "Eramir" = alle getötet, unbekannt zählt
    voll). Ob jede Quest erledigt ist, meldet die API nicht, deshalb
    "höchstens"."""
    return max(level - 1, 0) + QUEST_POINTS - (bandit in HELPED_BANDITS)


def main_points(tree: Tree, passives: dict) -> int:
    """Belegte Punkte im Hauptbaum (ohne Aszendenz und Start)."""
    return sum(1 for h in allocated(passives)
               if h in tree.nodes and not tree.nodes[h].ascendancy
               and tree.nodes[h].kind != START)


def _mit(passives: dict, have: set[int], wahl: dict[int, int]) -> dict:
    neu = dict(passives or {})
    neu["hashes"] = sorted(have)
    neu["mastery_effects"] = {str(k): v for k, v in sorted(wahl.items()) if k in have}
    return neu


def edit_allocate(tree: Tree, passives: dict, node: int, class_name: str = "") -> dict | None:
    weg = path_to(tree, allocated(passives), node, class_name)
    if weg is None:
        return None
    return _mit(passives, allocated(passives) | set(weg), mastery_choices(passives))


def edit_refund(tree: Tree, passives: dict, node: int, class_name: str = "") -> dict:
    have = allocated(passives)
    if node not in have:
        return dict(passives or {})
    return _mit(passives, have - cut_off(tree, have, node, class_name),
                mastery_choices(passives))


def edit_mastery(tree: Tree, passives: dict, mastery: int, effect: int | None) -> dict | None:
    """Effekt wählen (``None``: Mastery zurücknehmen). ``None`` als
    Ergebnis: nicht erlaubt — kein Notable in der Gruppe, oder der Effekt
    steckt schon in einer anderen Mastery (jeder nur einmal je Baum)."""
    have, wahl = allocated(passives), mastery_choices(passives)
    if effect is None:
        wahl.pop(mastery, None)
        return _mit(passives, have - {mastery}, wahl)
    m = tree.nodes.get(mastery)
    if (m is None or effect not in m.effects or not mastery_allowed(tree, have, mastery)
            or any(e == effect and k != mastery for k, e in wahl.items())):
        return None
    wahl[mastery] = effect
    return _mit(passives, have | {mastery}, wahl)


_ZAHL = re.compile(r"\d+(?:\.\d+)?")


def _totals(lines) -> dict[str, list[float]]:
    """Vorlage (Zahlen durch ``#`` ersetzt) → zusammengezählte Zahlen.
    Gleich heißt: gleich bis auf die Zahlen, und gleich viele Zahlen; eine
    Zeile ohne Zahl zählt als 1 (wie oft sie vorkommt)."""
    summen: dict[str, list[float]] = {}
    for zeile in lines:
        vorlage = _ZAHL.sub("#", zeile)
        werte = [float(z) for z in _ZAHL.findall(zeile)] or [1.0]
        if vorlage not in summen:
            summen[vorlage] = werte
        elif len(summen[vorlage]) == len(werte):
            summen[vorlage] = [a + b for a, b in zip(summen[vorlage], werte)]
    return summen


def _fill(vorlage: str, werte) -> str:
    werte = iter(werte)
    return re.sub("#", lambda _m: _zahl_text(next(werte)), vorlage)


def _by_wording(zeilen: list[str]) -> list[str]:
    # Sortiert nach dem ersten Wort, nicht nach Zahl oder Vorzeichen.
    return sorted(zeilen, key=lambda z: re.sub(r"^[^A-Za-z]+", "", _ZAHL.sub("", z)).lower())


def summed_stats(lines) -> list[str]:
    """Gleichlautende Zeilen zusammenzählen: zweimal "+10 to Strength" wird
    "+20 to Strength" (§_totals)."""
    return _by_wording([_fill(v, w) if "#" in v else v for v, w in _totals(lines).items()])


# --- Themen (§4.60.2) ----------------------------------------------------- #
#
# Peter, 2026-10-05, nach dem ersten echten Baum (über 100 Einträge
# "Within reach"): "Wir müssen unbedingt den Tree übersichtlicher
# hinbekommen." Jeder Knoten bekommt ein Thema; Baum, Summen und Reichweite
# werden danach gegliedert. Grob mit Absicht — Stichworte im Wortlaut, kein
# Verständnis der Mechanik. Ein falsch einsortierter Knoten steht dann in
# der Nachbargruppe, er verschwindet nicht.

DEFENCE, MINIONS, OFFENCE, UTILITY, OTHER = (
    "Defence", "Minions", "Offence", "Utility", "Other")
THEMES = (DEFENCE, MINIONS, OFFENCE, UTILITY, OTHER)

_MINION_WORDS = re.compile(
    r"\b(minions?|golems?|spectres?|zombies?|skeletons?|raging spirits?|offerings?)\b", re.I)
_DEFENCE_WORDS = re.compile(
    r"maximum life|\bof life\b|life regeneration|life recovery|life on kill|"
    r"energy shield|armour|evasion|resistances?\b|\bblock|recoup|damage taken|"
    r"damage reduction|\bstun|on you\b|suppress|leech|\bfortif", re.I)
_UTILITY_WORDS = re.compile(
    r"\bmana\b|strength|dexterity|intelligence|attributes|reservation|\baura|"
    r"\bcurse|\bhex|duration|movement speed|charges?\b|flask|herald|\blink|"
    r"\bbrand|\btotem|\btrap|\bmine\b|light radius|rarity|quantity", re.I)
_ENEMY_WORDS = re.compile(r"\benem(y|ies)\b", re.I)
_OFFENCE_WORDS = re.compile(
    r"damage|critical|cast speed|attack speed|penetrat|accuracy|area of effect|"
    r"\bignite|\bfreeze|\bshock|\bchill|wither|projectile|impale|bleed|poison|"
    r"\brage\b|warcr|exert|retaliation|\bstrike skills", re.I)


def line_theme(line: str) -> str:
    """Das Thema EINER Zeile. Minion-Zeilen zuerst: "Minions have +15% to
    all Elemental Resistances" ist kein Schutz für den Spieler."""
    if _MINION_WORDS.search(line):
        return MINIONS
    # Was Gegnern geschieht ("Enemies Cursed by you have 50% reduced Life
    # Regeneration Rate"), schützt nicht — das ist Angriff.
    if _ENEMY_WORDS.search(line):
        return OFFENCE
    for thema, muster in ((DEFENCE, _DEFENCE_WORDS), (UTILITY, _UTILITY_WORDS),
                          (OFFENCE, _OFFENCE_WORDS)):
        if muster.search(line):
            return thema
    return OTHER


def theme(node: Node) -> str:
    """Das Thema eines Knotens: das wichtigste seiner Zeilen, Schutz vor
    Minions vor Angriff vor Nutzen. Holy Dominion (+12% Resistenzen, 24%
    Elementarschaden) zählt damit zum Schutz — die Resistenzen sind das,
    was man dort nicht anders bekommt."""
    themen = {line_theme(z) for z in node.stats}
    return next((t for t in THEMES if t in themen), OTHER)


# --- Zwei Bäume vergleichen (§4.60.1) ------------------------------------- #

def all_stats(tree: Tree, passives: dict) -> list[str]:
    """Alle Werte eines Baums: jeder vergebene Knoten (auch Aszendenz)
    und der gewählte Effekt jeder Mastery."""
    zeilen: list[str] = []
    for h in sorted(allocated(passives)):
        knoten = tree.nodes.get(h)
        if knoten is not None and knoten.kind not in (START, MASTERY):
            zeilen += knoten.stats
    for knoten_id, effekt in mastery_choices(passives).items():
        knoten = tree.nodes.get(knoten_id)
        if knoten is not None:
            zeilen += knoten.effects.get(effekt, ())
    return zeilen


def stat_delta(tree: Tree, current: dict, target: dict) -> list[str]:
    """Was sich an Werten ändert, wenn man von ``current`` zu ``target``
    umbaut: "+38% to Fire Resistance", "-10% increased maximum Life".
    Zeilen ohne Zahl ("Deal no Non-Fire Damage") erscheinen als
    "gained: …" oder "lost: …"."""
    vorher, nachher = _totals(all_stats(tree, current)), _totals(all_stats(tree, target))
    ergebnis = []
    for vorlage in set(vorher) | set(nachher):
        a, b = vorher.get(vorlage), nachher.get(vorlage)
        if "#" not in vorlage:
            if (a or [0])[0] != (b or [0])[0]:
                ergebnis.append(("gained: " if b else "lost: ") + vorlage)
            continue
        a = a or [0.0] * len(b)
        b = b or [0.0] * len(a)
        if len(a) != len(b) or a == b:
            continue
        unterschied = [y - x for x, y in zip(a, b)]
        if vorlage.lstrip("+-").startswith("#"):
            # Das Vorzeichen der Vorlage ("+#% to X") weicht dem der
            # Änderung: "+5% to X" heißt mehr, "-5% to X" weniger.
            vorzeichen = "+" if sum(unterschied) > 0 else "-"
            ergebnis.append(vorzeichen + _fill(vorlage.lstrip("+-"),
                                               [abs(u) for u in unterschied]))
        else:
            # Beginnt die Zeile mit einem Wort ("Regenerate #% of Life"),
            # steht die Änderung an der Stelle der Zahl: "Regenerate -1% ...".
            werte = iter(unterschied)
            ergebnis.append(re.sub("#", lambda _m: f"{next(werte):+g}", vorlage))
    return _by_wording(ergebnis)


# Gold je zurückgenommenem Punkt, nach Charakterlevel (Index = Level − 1).
# Aus GGGs Spieldaten (VillageBalancePerLevelShared.dat, Spalte
# GoldRespec), übernommen aus Path of Building (src/Data/Misc.lua,
# data.goldRespecPrices), 2026-10-06. Gegengeprüft: Level 90 = 8.450, wie
# in mehreren Spielerberichten. Aszendenz-Knoten kosten das Fünffache
# (so rechnet PoB, TreeTab.lua). Peter, 2026-10-06: "Goldpreis eines
# Respecs bekommen wir bestimmt über die Patchnotes oder aus dem Netz".
# Ob Ruthless dieselbe Tabelle nutzt, ist nicht belegt.
GOLD_RESPEC = (
    4, 4, 4, 5, 5, 6, 6, 7, 8, 8, 9, 11, 12, 14, 15, 17, 18, 20, 22, 24,
    26, 28, 31, 34, 36, 39, 43, 46, 50, 54, 58, 62, 67, 72, 83, 90, 97, 105, 113, 121,
    130, 151, 161, 171, 182, 209, 222, 237, 252, 267, 295, 313, 333, 354, 376, 427, 452, 482,
    513, 546, 618, 656, 694, 733, 773, 816, 860, 892, 921, 1055, 1203, 1365, 1541, 1748, 1974,
    2221, 2490, 2770, 3073, 3400, 3752, 4131, 4538, 4976, 5444, 5967, 6526, 7126, 7766, 8450,
    9851, 11380, 13042, 14847, 16801, 18914, 21192, 23647, 26286, 29119)
ASCENDANCY_GOLD_FACTOR = 5


def respec_gold_per_point(level: int) -> int | None:
    """Gold je Punkt im Hauptbaum auf ``level``; ``None`` außerhalb 1–100."""
    return GOLD_RESPEC[level - 1] if 1 <= level <= len(GOLD_RESPEC) else None


@dataclass
class Respec:
    refund: list[Node]          # zurücknehmen
    allocate: list[Node]        # neu nehmen
    masteries: list[tuple[Node, tuple[str, ...], tuple[str, ...]]]  # Knoten, alt, neu
    stats: list[str]

    @property
    def points(self) -> int:
        """Rückzunehmende Punkte im normalen Baum — das, was Gold kostet.
        Aszendenz-Wechsel laufen über das Labyrinth, nicht über Gold."""
        return sum(1 for n in self.refund if not n.ascendancy)

    @property
    def ascendancy_points(self) -> int:
        return sum(1 for n in self.refund if n.ascendancy)   # Starts nimmt compare() nie auf

    def gold(self, level: int) -> int | None:
        """Was das Zurücknehmen auf ``level`` kostet (§4.60.7) — Hauptbaum
        zum Tabellenpreis, Aszendenz fünffach. ``None`` ohne gültiges Level."""
        preis = respec_gold_per_point(level)
        if preis is None:
            return None
        return self.points * preis + self.ascendancy_points * preis * ASCENDANCY_GOLD_FACTOR


def compare(tree: Tree, current: dict, target: dict) -> Respec:
    """Der Umbau von ``current`` zu ``target``: was zurück, was dazu, welche
    Mastery anders, und was sich an Werten ändert."""
    def knoten(ids) -> list[Node]:
        gefunden = [tree.nodes[h] for h in ids if h in tree.nodes]
        return sorted((n for n in gefunden if n.kind != START),
                      key=lambda n: (bool(n.ascendancy), n.kind != KEYSTONE,
                                     n.kind not in (NOTABLE, JEWEL), n.name))
    a, b = allocated(current), allocated(target)
    alt_wahl, neu_wahl = mastery_choices(current), mastery_choices(target)
    masteries = []
    for knoten_id in sorted(set(alt_wahl) & set(neu_wahl)):
        if alt_wahl[knoten_id] != neu_wahl[knoten_id] and knoten_id in tree.nodes:
            m = tree.nodes[knoten_id]
            masteries.append((m, m.effects.get(alt_wahl[knoten_id], ()),
                              m.effects.get(neu_wahl[knoten_id], ())))
    return Respec(refund=knoten(a - b), allocate=knoten(b - a), masteries=masteries,
                  stats=stat_delta(tree, current, target))


def _zahl_text(wert: float) -> str:
    return str(int(wert)) if wert == int(wert) else f"{wert:g}"


# --- Planer-Links (§4.60.1) ------------------------------------------------ #
#
# Der offizielle Planer und Path of Building teilen Bäume als
# ``https://www.pathofexile.com/passive-skill-tree/<code>``. ``code`` ist
# URL-sicheres Base64 über: Version (4 Byte), Klasse, Aszendenz, Anzahl
# Knoten, je Knoten 2 Byte; ab Version 5 danach Anzahl und Knoten der
# Cluster-Jewels (Kennung minus 65536), ab Version 6 Anzahl und Paare
# (Effekt, Mastery-Knoten) zu je 2 + 2 Byte. Alle Zahlen Big-Endian.

PLANNER_URL = "https://www.pathofexile.com/passive-skill-tree/"
_CLUSTER_OFFSET = 65536


class TreeLinkError(ValueError):
    """Der Text ist kein lesbarer Baum-Link."""


@dataclass
class TreeLink:
    class_index: int
    ascendancy_index: int
    passives: dict          # wie von der API: hashes, hashes_ex, mastery_effects


def encode_url(tree: Tree, passives: dict, class_name: str) -> str:
    """Der Planer-Link zu einem Baum (Version 6)."""
    import base64
    klasse, aszendenz = tree.class_ids.get(class_name, (0, 0))
    knoten = [h for h in sorted(allocated(passives))
              if h < _CLUSTER_OFFSET and (h not in tree.nodes or tree.nodes[h].kind != START)]
    cluster = sorted(int(h) for h in passives.get("hashes_ex") or () if int(h) >= _CLUSTER_OFFSET)
    wahl = sorted(mastery_choices(passives).items())
    daten = bytearray((6).to_bytes(4, "big"))
    daten += bytes([klasse, aszendenz, len(knoten)])
    for h in knoten:
        daten += h.to_bytes(2, "big")
    daten.append(len(cluster))
    for h in cluster:
        daten += (h - _CLUSTER_OFFSET).to_bytes(2, "big")
    daten.append(len(wahl))
    for knoten_id, effekt in wahl:
        daten += effekt.to_bytes(2, "big") + knoten_id.to_bytes(2, "big")
    return PLANNER_URL + base64.urlsafe_b64encode(bytes(daten)).decode("ascii")


def decode_url(text: str) -> TreeLink:
    """Einen eingefügten Link (oder nur den Code) lesen; Versionen 4–6."""
    import base64
    import binascii
    code = text.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if not code:
        raise TreeLinkError("empty link")
    try:
        daten = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
    except (binascii.Error, ValueError) as exc:
        raise TreeLinkError("not a tree link") from exc
    if len(daten) < 7:
        raise TreeLinkError("too short for a tree link")
    version = int.from_bytes(daten[:4], "big")
    if version not in (4, 5, 6):
        raise TreeLinkError(f"unknown tree link version {version}")
    # Unterste zwei Bits: die Aszendenz; Bits 2-3: eine zweite Aszendenz
    # einer Liga-Mechanik (Wildwood, 3.23) — die zählt hier nicht.
    klasse, aszendenz = daten[4], daten[5] & 3

    def u16(pos: int) -> int:
        if pos + 2 > len(daten):
            raise TreeLinkError("tree link is cut off")
        return int.from_bytes(daten[pos:pos + 2], "big")

    if version == 4:
        # Version 4: Byte 6 ist ein Vollbild-Merker, danach Knoten bis zum Ende.
        hashes = [u16(i) for i in range(7, len(daten) - 1, 2)]
        return TreeLink(klasse, aszendenz, {"hashes": hashes})
    anzahl, pos = daten[6], 7
    hashes = [u16(pos + 2 * i) for i in range(anzahl)]
    pos += 2 * anzahl
    cluster: list[int] = []
    if pos < len(daten):
        anzahl, pos = daten[pos], pos + 1
        cluster = [u16(pos + 2 * i) + _CLUSTER_OFFSET for i in range(anzahl)]
        pos += 2 * anzahl
    wahl: dict[str, int] = {}
    if version >= 6 and pos < len(daten):
        anzahl, pos = daten[pos], pos + 1
        for i in range(anzahl):
            wahl[str(u16(pos + 4 * i + 2))] = u16(pos + 4 * i)
    passives = {"hashes": hashes}
    if cluster:
        passives["hashes_ex"] = cluster
    if wahl:
        passives["mastery_effects"] = wahl
    return TreeLink(klasse, aszendenz, passives)


def class_name_of(tree: Tree, class_index: int, ascendancy_index: int) -> str:
    for name, ids in tree.class_ids.items():
        if ids == (class_index, ascendancy_index):
            return name
    return ""
