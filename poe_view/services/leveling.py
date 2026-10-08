"""Leveling-Plan: welcher Passivpunkt als nächster dran ist (§4.60.14).

Peter, 2026-10-08: "Der aktuell dargestellte Tree soll das Endziel sein.
Man startet am Klassenstart und es wird jeweils der nächste zu nehmende
Skillpunkt angezeigt. Mit jedem Level kommt, angefangen bei Stufe 1, ein
Skillpunkt dazu. Zusätzlich noch zwei Buttons um einen Skillpunkt bei
Questabschluss manuell hinzuzufügen bzw. bei einem Fehlklick wieder zu
entfernen."

Ein Plan ist ein Ziel-Baum (eine Konfiguration) und eine Vorrangliste
angeklickter Knoten. Daraus entsteht EINE feste Reihenfolge vom
Klassenstart bis zum fertigen Ziel (``sequence``); jeder Schritt liegt
neben einem früheren oder dem Start. Wie weit der Spieler ist, sagt nur
die Zahl seiner Punkte: Level − 1 plus die von Hand gezählten
Quest-Punkte (``points_earned``) — nicht sein echter Baum.

Reihenfolge (Peter: "Priorität am Anfang hat natürlich Schaden und dann
abwechselnd Defensive"): zuerst das vorrangige Ziel (Vorrangliste), sonst
das nächstgelegene Notable, Keystone oder Jewel-Sockel des fälligen
Themas — Schaden, Schutz, Schaden, … —, jeweils samt Weg. Gibt es keins
des fälligen Themas mehr, das nächstgelegene überhaupt. Kleine Knoten,
die auf keinem Weg lagen, zuletzt. Eine Mastery, sobald ihr Notable
steht.

Die Aszendenz bleibt draußen: Ihre Punkte kommen aus dem Labyrinth,
nicht aus Leveln (§4.60.8, Variante 1).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from poe_view.services import passive_tree
from poe_view.services.passive_tree import (JEWEL, KEYSTONE, MASTERY, NOTABLE, START, Tree)

ALLOCATE, MASTERY_STEP = "allocate", "mastery"
# Ziele: dorthin führt ein Weg, der Rest liegt darauf.
_ZIEL_ARTEN = (KEYSTONE, NOTABLE, JEWEL)
# Die Themen, zwischen denen die Reihenfolge wechselt.
DAMAGE, DEFENCE, OTHER = "damage", "defence", "other"


@dataclass
class Step:
    """Ein Punkt: ``node`` vergeben (bei einer Mastery mit ``effect``) —
    auf dem Weg zu ``target``."""
    node: int
    kind: str
    target: int
    effect: int | None = None


@dataclass
class Plan:
    target: dict                        # passives des Ziel-Baums
    # Vom Spieler angeklickte Ziele, in dieser Reihenfolge zuerst.
    priority: list[int] = field(default_factory=list)


def _haupt(tree: Tree, ids) -> set[int]:
    """Knoten des Hauptbaums ohne Starts (die stehen nie in ``hashes``)."""
    return {h for h in ids if h in tree.nodes and not tree.nodes[h].ascendancy
            and tree.nodes[h].kind != START}


def topic(tree: Tree, node: int) -> str:
    """Schaden, Schutz oder anderes — aus dem Thema, nach dem der Baum
    seine Knoten färbt (``passive_tree.theme``). Minion-Knoten sind der
    Schaden eines Minion-Builds."""
    thema = passive_tree.theme(tree.nodes[node])
    if thema in (passive_tree.OFFENCE, passive_tree.MINIONS):
        return DAMAGE
    return DEFENCE if thema == passive_tree.DEFENCE else OTHER


def _abstaende(tree: Tree, quellen: set[int], erlaubt: set[int]) -> tuple[dict, dict]:
    """Breitensuche von ``quellen`` aus, nur über ``erlaubt`` (ohne
    Masteries — durch sie führt kein Weg): Abstand und Vorgänger je
    erreichtem Knoten. Aszendenz und fremde Starts stehen nie in
    ``erlaubt`` (``_haupt``)."""
    abstand = {h: 0 for h in quellen}
    vorher: dict[int, int | None] = {h: None for h in quellen}
    schlange = deque(sorted(quellen))
    while schlange:
        a = schlange.popleft()
        for b in sorted(tree.nodes[a].neighbours):
            if b in vorher or b not in erlaubt or tree.nodes[b].kind == MASTERY:
                continue
            vorher[b] = a
            abstand[b] = abstand[a] + 1
            schlange.append(b)
    return abstand, vorher


def _weg(vorher: dict, quellen: set[int], ziel: int) -> list[int]:
    weg, a = [], ziel
    while a is not None and a not in quellen:
        weg.append(a)
        a = vorher[a]
    return list(reversed(weg))


def sequence(tree: Tree, plan: Plan, class_name: str) -> list[Step]:
    """Alle Schritte vom Klassenstart bis zum fertigen Ziel-Baum. Was vom
    Start aus nicht erreichbar ist (hinter einem fremden Start, ohne
    Verbindung), fehlt."""
    start = tree.class_starts.get(class_name)
    if start is None:
        return []
    ziel_baum = _haupt(tree, passive_tree.allocated(plan.target))
    wahl = passive_tree.mastery_choices(plan.target)
    erlaubt = ziel_baum | {start}
    have: set[int] = set()
    gewaehlt: dict[int, int] = {}
    schritte: list[Step] = []
    faellig = DAMAGE
    while True:
        offen = {h for h in ziel_baum - have if tree.nodes[h].kind != MASTERY}
        quellen = have | {start}
        abstand, vorher = _abstaende(tree, quellen, erlaubt)
        erreichbar = {h for h in offen if h in abstand}
        if not erreichbar:
            break
        ziel = next((h for h in plan.priority if h in erreichbar), None)
        if ziel is None:
            gross = [h for h in erreichbar if tree.nodes[h].kind in _ZIEL_ARTEN]
            if gross:
                ziel = min(gross, key=lambda h: (topic(tree, h) != faellig, abstand[h], h))
                if topic(tree, ziel) == faellig:
                    faellig = DEFENCE if faellig == DAMAGE else DAMAGE
            else:
                ziel = min(erreichbar, key=lambda h: (abstand[h], h))
        for h in _weg(vorher, quellen, ziel):
            schritte.append(Step(h, ALLOCATE, ziel))
            have.add(h)
        schritte += _masteries(tree, have, ziel_baum, wahl, gewaehlt, ziel)
    return schritte


def _masteries(tree: Tree, have: set[int], ziel_baum: set[int], wahl: dict[int, int],
               gewaehlt: dict[int, int], ziel: int) -> list[Step]:
    """Masteries des Ziels, die jetzt gehen (ihr Notable steht)."""
    schritte = []
    for m in sorted(h for h in ziel_baum if tree.nodes[h].kind == MASTERY):
        effekt = wahl.get(m)
        if effekt is None or m in gewaehlt:
            continue
        if not passive_tree.mastery_allowed(tree, have, m):
            continue
        schritte.append(Step(m, MASTERY_STEP, ziel, effect=effekt))
        gewaehlt[m] = effekt
        have.add(m)
    return schritte


def points_earned(level: int, quest_points: int = 0) -> int:
    """Punkte bisher: einer je Level ab Stufe 2, dazu die von Hand
    gezählten Quest-Punkte (die sieht weder Log noch API)."""
    return max(level - 1, 0) + max(quest_points, 0)
