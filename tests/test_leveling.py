"""Leveling-Plan (§4.60.14): die Reihenfolge vom Klassenstart zum Ziel und
wie weit der Spieler darin ist.

Der Testbaum (tests/test_passive_tree.py, ``_ROH``)::

    [Start Marauder 1] - 10 - 11 - 12(Notable) - 13(Keystone)
                           \\- 20 - 21(Jewel)  \\- 14 - 15(Notable)
    10 - 30(Start Witch) - 31(Notable hinter dem fremden Start)

``_schaden_baum`` hängt Schadens-Notables an: 22 und 23 hinter 20, 16
hinter 15.
"""

from __future__ import annotations

import copy

import pytest

from poe_view.services import leveling as lv
from poe_view.services import passive_tree as pt
from poe_view.services import tree_history as th
from tests.test_passive_tree import _ROH, _knoten as roh_knoten, _mastery_baum


@pytest.fixture
def baum() -> pt.Tree:
    return pt.parse_tree(_ROH, ruthless=True)


def _schaden_baum() -> pt.Tree:
    roh = copy.deepcopy(_ROH)
    roh["nodes"]["20"]["out"].append("22")
    roh["nodes"]["22"] = roh_knoten("Heavy Hitter", (23,), isNotable=True,
                                    stats=["20% increased Melee Damage"])
    roh["nodes"]["23"] = roh_knoten("Brute Force", (), isNotable=True,
                                    stats=["15% increased Attack Speed"])
    roh["nodes"]["15"]["out"].append("16")
    roh["nodes"]["16"] = roh_knoten("Brutal Blade", (), isNotable=True,
                                    stats=["30% increased Physical Damage"])
    return pt.parse_tree(roh, ruthless=True)


def _plan(hashes, priority=(), **extra):
    return lv.Plan({"hashes": list(hashes), **extra}, priority=list(priority))


def _knoten(schritte):
    return [s.node for s in schritte]


def _nebeneinander(b, schritte, klasse="Marauder") -> bool:
    """Jeder Schritt liegt neben dem Start oder einem früheren (Mastery
    ausgenommen: Die hängt am Notable ihrer Gruppe, nicht an einer Kante)."""
    bekannt = {b.class_starts[klasse]}
    for s in schritte:
        if s.kind == lv.ALLOCATE and not set(b.nodes[s.node].neighbours) & bekannt:
            return False
        bekannt.add(s.node)
    return True


def test_from_the_class_start_every_step_is_next_to_an_earlier_one(baum) -> None:
    """Peter: "Man startet am Klassenstart … ausgehend vom Startpunkt jeder
    Node in der richtigen Reihenfolge (benachbart)." Ohne Schadens-Notable
    das nächstgelegene; Iron Heart und der Sockel sind gleich weit — die
    kleinere Kennung zuerst, jeweils samt Weg."""
    schritte = lv.sequence(baum, _plan([10, 11, 12, 20, 21]), "Marauder")
    assert _knoten(schritte) == [10, 11, 12, 20, 21]
    assert [s.target for s in schritte] == [12, 12, 12, 21, 21]
    assert _nebeneinander(baum, schritte)


def test_damage_first_then_defence_and_damage_by_turns() -> None:
    """Peter: "Priorität am Anfang hat natürlich Schaden und dann
    abwechselnd Defensive." Heavy Hitter (Schaden) vor dem gleich weiten
    Iron Heart; danach Iron Heart (Schutz) vor dem näheren Brute Force."""
    b = _schaden_baum()
    schritte = lv.sequence(b, _plan([10, 11, 12, 14, 15, 16, 20, 22, 23]), "Marauder")
    assert _knoten(schritte) == [10, 20, 22, 11, 12, 23, 14, 15, 16]
    assert [b.nodes[s.target].name for s in schritte if s.node == s.target] == [
        "Heavy Hitter", "Iron Heart", "Brute Force", "Far Away", "Brutal Blade"]
    assert _nebeneinander(b, schritte)


def test_topics_minions_are_damage(baum) -> None:
    b = _schaden_baum()
    assert (lv.topic(b, 22), lv.topic(b, 12), lv.topic(b, 13), lv.topic(b, 21)) == (
        lv.DAMAGE, lv.DEFENCE, lv.OTHER, lv.OTHER)
    roh = copy.deepcopy(_ROH)
    roh["nodes"]["11"]["stats"] = ["Minions deal 10% increased Damage"]
    assert lv.topic(pt.parse_tree(roh, ruthless=True), 11) == lv.DAMAGE


def test_the_players_order_comes_first(baum) -> None:
    """Peter: "Wenn dies nicht hinhaut, muss der Plan von Hand angelegt
    werden" — angeklickte Ziele gehen vor, samt Weg."""
    plan = _plan([10, 11, 12, 20, 21], priority=[21])
    assert _knoten(lv.sequence(baum, plan, "Marauder")) == [10, 20, 21, 11, 12]
    # Ein Vorrang-Ziel außerhalb des Ziel-Baums zählt nicht.
    plan = _plan([10, 11, 12], priority=[21])
    assert _knoten(lv.sequence(baum, plan, "Marauder")) == [10, 11, 12]


def test_the_order_does_not_depend_on_the_real_tree(baum) -> None:
    """Wie weit der Spieler ist, sagt die Zahl seiner Punkte, nicht sein
    Baum — die Reihenfolge ist fest."""
    plan = _plan([10, 11, 12, 20, 21])
    assert lv.sequence(baum, plan, "Marauder") == lv.sequence(baum, plan, "Juggernaut")


def test_a_mastery_follows_its_notable() -> None:
    b = _mastery_baum()
    plan = _plan([10, 11, 12, 40], mastery_effects={"40": 778})
    schritte = lv.sequence(b, plan, "Marauder")
    assert [(s.node, s.kind, s.effect) for s in schritte] == [
        (10, lv.ALLOCATE, None), (11, lv.ALLOCATE, None), (12, lv.ALLOCATE, None),
        (40, lv.MASTERY_STEP, 778)]


def test_the_tree_after_some_steps_for_the_preview() -> None:
    b = _mastery_baum()
    schritte = lv.sequence(b, _plan([10, 11, 12, 40], mastery_effects={"40": 778}), "Marauder")
    assert lv.passives_after(schritte, 2) == {"hashes": [10, 11], "mastery_effects": {}}
    assert lv.passives_after(schritte, 9) == {"hashes": [10, 11, 12, 40],
                                              "mastery_effects": {"40": 778}}
    assert lv.passives_after(schritte, -1) == {"hashes": [], "mastery_effects": {}}


def test_unreachable_ascendancy_and_unknown_class_are_left_out(baum) -> None:
    """31 liegt hinter dem fremden Witch-Start — kein Weg; die Aszendenz
    kommt aus dem Labyrinth, nicht aus Leveln."""
    assert _knoten(lv.sequence(baum, _plan([10, 11, 12, 31]), "Marauder")) == [10, 11, 12]
    assert _knoten(lv.sequence(baum, _plan([10, 11, 50, 51]), "Marauder")) == [10, 11]
    assert lv.sequence(baum, _plan([10, 11]), "Nobody") == []
    assert lv.sequence(baum, _plan([]), "Marauder") == []


def test_the_way_stays_on_the_targets_nodes(baum) -> None:
    """Das Ziel bestimmt den Weg — nicht die kürzeste Verbindung: Eine
    Abkürzung 1 → 60 → 12 über einen fremden Knoten wird nicht genommen."""
    roh = copy.deepcopy(_ROH)
    roh["nodes"]["1"]["out"].append("60")
    roh["nodes"]["60"] = roh_knoten("Shortcut", (12,), stats=["+5 to Dexterity"])
    b = pt.parse_tree(roh, ruthless=True)
    assert pt.path_to(b, set(), 12, "Marauder") == [60, 12]       # kürzer
    assert _knoten(lv.sequence(b, _plan([10, 11, 12]), "Marauder")) == [10, 11, 12]


@pytest.mark.parametrize("level, quest, punkte", [(1, 0, 0), (2, 0, 1), (30, 0, 29),
                                                  (30, 2, 31), (5, -1, 4), (0, 0, 0)])
def test_one_point_per_level_from_level_two_plus_quests(level, quest, punkte) -> None:
    """Peter: "Mit jedem Level kommt, angefangen bei Stufe 1, ein
    Skillpunkt dazu" — auf Stufe 1 noch keiner."""
    assert lv.points_earned(level, quest) == punkte


def test_the_plan_names_its_target_and_old_chains_become_their_last_stage() -> None:
    zeichen: dict = {}
    th.save_config(zeichen, "WitchOfPeter", "S1", {"hashes": [10]}, level=1, ruthless=True,
                   source="pob")
    th.set_leveling(zeichen, "WitchOfPeter", "S1")
    assert th.leveling(zeichen, "WitchOfPeter") == {"target": "S1", "priority": []}
    assert th.rename_config(zeichen, "WitchOfPeter", "S1", "Endgame")
    assert th.leveling(zeichen, "WitchOfPeter")["target"] == "Endgame"
    # Die erste, nie veröffentlichte Fassung: eine Kette von Abschnitten.
    zeichen["WitchOfPeter"]["leveling"] = {"stages": ["A", "B"], "priority": [5], "title": "x"}
    assert th.leveling(zeichen, "WitchOfPeter") == {"target": "B", "priority": [5]}


def test_quest_points_belong_to_the_character() -> None:
    zeichen: dict = {}
    assert th.quest_points(zeichen, "WitchOfPeter") == 0
    th.set_quest_points(zeichen, "WitchOfPeter", 3)
    th.set_leveling(zeichen, "WitchOfPeter", "Other target")
    th.clear_leveling(zeichen, "WitchOfPeter")
    assert th.quest_points(zeichen, "WitchOfPeter") == 3
    th.set_quest_points(zeichen, "WitchOfPeter", -2)
    assert th.quest_points(zeichen, "WitchOfPeter") == 0
