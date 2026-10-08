"""Leveling-Plan: welcher Passivpunkt als nächster dran ist (§4.60.14).

Peter, 2026-10-08: "Was nice wäre, wäre ein 'Leveling-Mode'. Das
Programm überwacht ja eh schon den Char-Level und zeigt dann den zu
vergebenden Skill-Punkt im Tree an. D.h. wir brauchen eine
Node-ID-Liste die abgearbeitet wird." Entschieden: Reihenfolge
automatisch aus einer Kette von Konfigurationen (Pohx: "Lvl 01-30" →
"Lvl 31-40" → …), umstellbar durch Anklicken in Wunschreihenfolge.

Ein Plan ist eine Folge von Abschnitten (je ein Ziel-Baum) und eine
Vorrangliste von Knoten. Die Schritte werden nicht gespeichert, sondern
immer frisch aus dem echten Baum gerechnet: Wer abweicht, bekommt den
nächsten sinnvollen Punkt vom Stand aus, auf dem er wirklich ist.

Im Abschnitt geht es nur über Knoten dieses Abschnitts: zuerst zum
vorrangigen Ziel (Vorrangliste), sonst zum nächstgelegenen Notable,
Keystone oder Jewel-Sockel, samt Weg; übrige kleine Knoten zuletzt.
Eine Mastery folgt, sobald ihr Notable steht. Ist ein Abschnitt fertig,
geht die Liste im nächsten weiter. Knoten, die der Abschnitt nicht mehr
hat (Pohx' "RF Start" baut den Anfang um), sind "zurückzunehmen" —
wann, entscheidet der Spieler (Gold, Respec-Punkte).

Die Aszendenz bleibt draußen: Ihre Punkte kommen aus dem Labyrinth,
nicht aus Leveln (§4.60.8, Variante 1).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from poe_view.services import passive_tree
from poe_view.services.passive_tree import (JEWEL, KEYSTONE, MASTERY, NOTABLE, START, Node,
                                            Tree)

ALLOCATE, MASTERY_STEP = "allocate", "mastery"
# Ziele eines Abschnitts: dorthin führt ein Weg, der Rest liegt darauf.
_ZIEL_ARTEN = (KEYSTONE, NOTABLE, JEWEL)


@dataclass
class Stage:
    name: str
    passives: dict


@dataclass
class Step:
    """Ein Punkt: ``node`` vergeben (bei einer Mastery mit ``effect``) —
    auf dem Weg zu ``target``, im Abschnitt ``stage``."""
    node: int
    kind: str
    stage: int
    target: int
    effect: int | None = None


@dataclass
class Plan:
    stages: list[Stage]
    # Vom Spieler angeklickte Ziele, in dieser Reihenfolge zuerst.
    priority: list[int] = field(default_factory=list)


def _haupt(tree: Tree, ids) -> set[int]:
    """Knoten des Hauptbaums ohne Starts (die stehen nie in ``hashes``)."""
    return {h for h in ids if h in tree.nodes and not tree.nodes[h].ascendancy
            and tree.nodes[h].kind != START}


def stage_index(tree: Tree, plan: Plan, have: set[int]) -> int:
    """Der Abschnitt, in dem der Spieler steht: der, zu dem sein Baum am
    besten passt (übereinstimmende minus fehlende Knoten; bei Gleichstand
    der spätere). Ist der fertig, der nächste.

    Nicht "der erste, dem etwas fehlt": Baut ein späterer Abschnitt um
    (Pohx' "RF Start" gibt Knoten aus "Lvl 01-30" zurück), fehlt dem
    früheren nach dem Umbau immer etwas — man landete wieder vorn (im
    Test gefunden)."""
    if not plan.stages:
        return 0
    bester, wert = 0, None
    for i, stage in enumerate(plan.stages):
        ziel = _haupt(tree, passive_tree.allocated(stage.passives))
        punkte = len(ziel & have) - len(ziel - have)
        if wert is None or punkte >= wert:
            bester, wert = i, punkte
    ziel = _haupt(tree, passive_tree.allocated(plan.stages[bester].passives))
    if not ziel - have and bester < len(plan.stages) - 1:
        return bester + 1
    return bester


def _abstaende(tree: Tree, quellen: set[int], erlaubt: set[int]) -> tuple[dict, dict]:
    """Breitensuche von ``quellen`` aus, nur über ``erlaubt`` (und
    begehbare Knoten): Abstand und Vorgänger je erreichtem Knoten."""
    abstand = {h: 0 for h in quellen}
    vorher: dict[int, int | None] = {h: None for h in quellen}
    schlange = deque(sorted(quellen))
    while schlange:
        a = schlange.popleft()
        for b in sorted(tree.nodes[a].neighbours):
            if b in vorher or b not in erlaubt:
                continue
            n = tree.nodes[b]
            if n.ascendancy or n.kind == MASTERY or n.class_start:
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


def next_steps(tree: Tree, plan: Plan, have_passives: dict, class_name: str,
               limit: int | None = None) -> list[Step]:
    """Die nächsten Schritte vom echten Baum aus, über alle restlichen
    Abschnitte hinweg (höchstens ``limit``)."""
    if not plan.stages:
        return []
    have = _haupt(tree, passive_tree.allocated(have_passives))
    gewaehlt = dict(passive_tree.mastery_choices(have_passives))
    start = tree.class_starts.get(class_name)
    schritte: list[Step] = []

    def voll() -> bool:
        return limit is not None and len(schritte) >= limit

    for index in range(stage_index(tree, plan, have), len(plan.stages)):
        stage = plan.stages[index]
        ziel_baum = _haupt(tree, passive_tree.allocated(stage.passives))
        wahl = passive_tree.mastery_choices(stage.passives)
        erlaubt = ziel_baum | ({start} if start is not None else set())
        while not voll():
            # Masteries, deren Notable schon steht — auch ein Wechsel des
            # Effekts in einem sonst fertigen Abschnitt (im Test gefunden).
            schritte += _masteries(tree, have, ziel_baum, wahl, gewaehlt, index, -1,
                                   limit - len(schritte) if limit is not None else None)
            offen = {h for h in ziel_baum - have if tree.nodes[h].kind != MASTERY}
            if not offen or voll():
                break
            quellen = (have & erlaubt) | ({start} if start is not None else set())
            abstand, vorher = _abstaende(tree, quellen, erlaubt)
            erreichbar = {h for h in offen if h in abstand}
            if not erreichbar:
                break                  # Rest hängt nicht am Baum (Abschnitt baut um)
            ziele = [h for h in plan.priority if h in erreichbar]
            if not ziele:
                ziele = sorted((h for h in erreichbar if tree.nodes[h].kind in _ZIEL_ARTEN),
                               key=lambda h: (abstand[h], h))
            if not ziele:
                ziele = sorted(erreichbar, key=lambda h: (abstand[h], h))
            ziel = ziele[0]
            for h in _weg(vorher, quellen, ziel):
                if voll():
                    break
                schritte.append(Step(h, ALLOCATE, index, ziel))
                have.add(h)
            schritte += _masteries(tree, have, ziel_baum, wahl, gewaehlt, index, ziel,
                                   limit - len(schritte) if limit is not None else None)
        if voll():
            break
    return schritte


def _masteries(tree: Tree, have: set[int], ziel_baum: set[int], wahl: dict[int, int],
               gewaehlt: dict[int, int], index: int, ziel: int,
               rest: int | None) -> list[Step]:
    """Masteries des Abschnitts, die jetzt gehen (ihr Notable steht) und
    noch nicht mit diesem Effekt gewählt sind."""
    schritte = []
    for m in sorted(h for h in ziel_baum if tree.nodes[h].kind == MASTERY):
        if rest is not None and len(schritte) >= rest:
            break
        effekt = wahl.get(m)
        if effekt is None or gewaehlt.get(m) == effekt:
            continue
        if not passive_tree.mastery_allowed(tree, have, m):
            continue
        schritte.append(Step(m, MASTERY_STEP, index, ziel, effect=effekt))
        gewaehlt[m] = effekt
        have.add(m)
    return schritte


def to_refund(tree: Tree, plan: Plan, have_passives: dict) -> list[Node]:
    """Was der aktuelle Abschnitt nicht mehr hat — zurückzunehmen, wann es
    passt."""
    if not plan.stages:
        return []
    have = _haupt(tree, passive_tree.allocated(have_passives))
    stage = plan.stages[stage_index(tree, plan, have)]
    weg = have - _haupt(tree, passive_tree.allocated(stage.passives))
    return sorted((tree.nodes[h] for h in weg), key=lambda n: (n.kind != KEYSTONE,
                                                               n.kind != NOTABLE, n.name))


def assumed_done(level_now: int, level_api: int) -> int:
    """Wie viele Schritte der Spieler seit dem letzten API-Stand vermutlich
    schon vergeben hat (§4.60.14 — die API kennt den neuen Baum erst nach
    dem nächsten Abruf, meist beim nächsten Zonenwechsel). Auf dem Level
    des API-Stands ist Schritt 1 der nächste; der erste Aufstieg bringt den
    Punkt dafür — er ist dann dran, nicht erledigt. Erst jeder weitere
    Aufstieg heißt: der vorige ist vergeben. Quest-Punkte sieht niemand;
    die zählen nicht."""
    return max(level_now - level_api - 1, 0)
