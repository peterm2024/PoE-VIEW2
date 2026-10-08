"""Leveling-Plan (§4.60.14): welcher Passivpunkt als nächster dran ist.

Der Testbaum (tests/test_passive_tree.py, ``_ROH``)::

    [Start Marauder 1] - 10 - 11 - 12(Notable) - 13(Keystone)
                           \\- 20 - 21(Jewel)  \\- 14 - 15(Notable)
    10 - 30(Start Witch) - 31(Notable hinter dem fremden Start)
"""

from __future__ import annotations

import pytest

from poe_view.services import leveling as lv
from poe_view.services import passive_tree as pt
from tests.test_passive_tree import _ROH, _mastery_baum


@pytest.fixture
def baum() -> pt.Tree:
    return pt.parse_tree(_ROH, ruthless=True)


def _plan(*stufen, priority=()):
    return lv.Plan([lv.Stage(f"S{i}", {"hashes": list(h)}) for i, h in enumerate(stufen)],
                   priority=list(priority))


def _knoten(schritte):
    return [s.node for s in schritte]


def test_steps_go_to_the_nearest_notable_first_with_their_path(baum) -> None:
    """Vom Start aus: Iron Heart (12) und der Jewel-Sockel (21) sind gleich
    weit — der kleinere Kennung zuerst, jeweils samt Weg."""
    plan = _plan([10, 11, 12, 20, 21])
    schritte = lv.next_steps(baum, plan, {"hashes": []}, "Marauder")
    assert _knoten(schritte) == [10, 11, 12, 20, 21]
    assert [s.target for s in schritte] == [12, 12, 12, 21, 21]
    assert {s.kind for s in schritte} == {lv.ALLOCATE} and {s.stage for s in schritte} == {0}


def test_the_players_order_comes_first(baum) -> None:
    """Peter: Reihenfolge umstellbar durch Anklicken — der Jewel-Sockel vor
    Iron Heart."""
    plan = _plan([10, 11, 12, 20, 21], priority=[21])
    assert _knoten(lv.next_steps(baum, plan, {"hashes": []}, "Marauder")) == [10, 20, 21, 11, 12]
    # Ein Vorrang-Ziel außerhalb des Abschnitts zählt nicht.
    plan = _plan([10, 11, 12], priority=[21])
    assert _knoten(lv.next_steps(baum, plan, {"hashes": []}, "Marauder")) == [10, 11, 12]


def test_the_plan_starts_where_the_player_really_is(baum) -> None:
    """Immer vom echten Baum aus: Wer abweicht, bekommt den nächsten
    sinnvollen Punkt von dort."""
    plan = _plan([10, 11, 12, 20, 21])
    assert _knoten(lv.next_steps(baum, plan, {"hashes": [10, 20]}, "Marauder")) == [21, 11, 12]
    assert lv.next_steps(baum, plan, {"hashes": [10, 11, 12, 20, 21]}, "Marauder") == []


def test_stages_follow_each_other_and_dropped_nodes_are_to_refund(baum) -> None:
    """Pohx' Abschnitte: nach "Lvl 01-30" geht es in "RF Start" weiter, das
    den Anfang umbaut — was dort fehlt, ist zurückzunehmen."""
    plan = _plan([10, 11, 12, 20, 21], [10, 11, 12, 13, 14, 15])
    frisch = lv.next_steps(baum, plan, {"hashes": []}, "Marauder")
    assert _knoten(frisch) == [10, 11, 12, 20, 21, 13, 14, 15]
    assert [s.stage for s in frisch] == [0] * 5 + [1] * 3
    fertig1 = {"hashes": [10, 11, 12, 20, 21]}
    assert lv.stage_index(baum, plan, {10, 11, 12, 20, 21}) == 1
    assert _knoten(lv.next_steps(baum, plan, fertig1, "Marauder")) == [13, 14, 15]
    assert [n.id for n in lv.to_refund(baum, plan, fertig1)] == [21, 20]   # Sockel zuerst
    # Alles fertig: letzter Abschnitt, nichts mehr zu tun.
    alles = {"hashes": [10, 11, 12, 13, 14, 15]}
    assert lv.stage_index(baum, plan, {10, 11, 12, 13, 14, 15}) == 1
    assert lv.next_steps(baum, plan, alles, "Marauder") == []
    assert lv.to_refund(baum, plan, alles) == []


def test_a_mastery_follows_its_notable(baum) -> None:
    b = _mastery_baum()
    plan = lv.Plan([lv.Stage("S", {"hashes": [10, 11, 12, 40],
                                   "mastery_effects": {"40": 778}})])
    schritte = lv.next_steps(b, plan, {"hashes": []}, "Marauder")
    assert [(s.node, s.kind, s.effect) for s in schritte] == [
        (10, lv.ALLOCATE, None), (11, lv.ALLOCATE, None), (12, lv.ALLOCATE, None),
        (40, lv.MASTERY_STEP, 778)]
    # Schon mit diesem Effekt gewählt: kein Schritt; mit einem anderen: wechseln.
    assert lv.next_steps(b, plan, {"hashes": [10, 11, 12, 40],
                                   "mastery_effects": {"40": 778}}, "Marauder") == []
    wechsel = lv.next_steps(b, plan, {"hashes": [10, 11, 12, 40],
                                      "mastery_effects": {"40": 777}}, "Marauder")
    assert [(s.node, s.effect) for s in wechsel] == [(40, 778)]


def test_unreachable_nodes_stop_the_stage_and_limit_cuts_the_list(baum) -> None:
    """31 liegt hinter dem fremden Witch-Start — kein Weg; der Rest des
    Abschnitts kommt trotzdem."""
    plan = _plan([10, 11, 12, 31])
    assert _knoten(lv.next_steps(baum, plan, {"hashes": []}, "Marauder")) == [10, 11, 12]
    plan = _plan([10, 11, 12, 20, 21], [10, 11, 12, 13, 14, 15])
    assert _knoten(lv.next_steps(baum, plan, {"hashes": []}, "Marauder", limit=4)) == [10, 11, 12, 20]
    assert lv.next_steps(baum, lv.Plan([]), {"hashes": []}, "Marauder") == []


def test_ascendancy_is_not_planned(baum) -> None:
    """Aszendenz-Punkte kommen aus dem Labyrinth, nicht aus Leveln."""
    plan = _plan([10, 11, 50, 51])
    assert _knoten(lv.next_steps(baum, plan, {"hashes": []}, "Marauder")) == [10, 11]
    assert lv.to_refund(baum, _plan([10]), {"hashes": [10, 51]}) == []


@pytest.mark.parametrize("jetzt, api, erledigt", [(30, 30, 0), (31, 30, 0), (32, 30, 1),
                                                  (35, 30, 4), (29, 30, 0)])
def test_points_assumed_spent_since_the_last_api_tree(jetzt, api, erledigt) -> None:
    """Auf dem API-Level ist Schritt 1 dran; der erste Aufstieg bringt den
    Punkt dafür, erst jeder weitere heißt: der vorige ist vergeben."""
    assert lv.assumed_done(jetzt, api) == erledigt


def test_the_stage_is_the_one_the_tree_fits_best(baum) -> None:
    """Mitten im umbauenden Abschnitt (20, 21 schon zurückgenommen, 13
    genommen): Abschnitt 2 — nicht wieder 1, dem ja 20 und 21 fehlen."""
    plan = _plan([10, 11, 12, 20, 21], [10, 11, 12, 13, 14, 15])
    assert lv.stage_index(baum, plan, {10, 11, 12, 13}) == 1
    assert _knoten(lv.next_steps(baum, plan, {"hashes": [10, 11, 12, 13]}, "Marauder")) == [14, 15]
    assert lv.stage_index(baum, plan, {10, 11}) == 0              # frisch unterwegs
    assert lv.stage_index(baum, plan, set()) == 0
    # Abschnitte, die aufeinander aufbauen (Pohx ab "Lvl 41-60"): bei
    # Gleichstand der spätere.
    aufbau = _plan([10, 11], [10, 11, 12, 13])
    assert lv.stage_index(baum, aufbau, {10, 11, 12}) == 1


def test_the_way_stays_on_the_stages_nodes(baum) -> None:
    """Der Abschnitt bestimmt den Weg — nicht die kürzeste Verbindung: Eine
    Abkürzung 1 → 60 → 12 über einen fremden Knoten wird nicht genommen."""
    import copy
    from tests.test_passive_tree import _knoten as roh_knoten
    roh = copy.deepcopy(_ROH)
    roh["nodes"]["1"]["out"].append("60")
    roh["nodes"]["60"] = roh_knoten("Shortcut", (12,), stats=["+5 to Dexterity"])
    b = pt.parse_tree(roh, ruthless=True)
    assert pt.path_to(b, set(), 12, "Marauder") == [60, 12]       # kürzer
    assert _knoten(lv.next_steps(b, _plan([10, 11, 12]), {"hashes": []}, "Marauder")) == [
        10, 11, 12]


def test_on_a_tie_the_later_stage_wins_even_if_the_earlier_is_unfinished(baum) -> None:
    plan = _plan([10, 11, 20], [10, 11, 12, 13, 14])
    # Abschnitt 1: 2 passen, 1 fehlt → 1; Abschnitt 2: 3 passen, 2 fehlen → 1.
    assert lv.stage_index(baum, plan, {10, 11, 12}) == 1
