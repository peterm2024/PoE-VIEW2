"""Tests für den Passiv-Baum: Baumdaten, Reichweite, Verlauf und den
Abschnitt im Charakterbogen (§4.60)."""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from poe_view.api.models import Character, Item
from poe_view.services import passive_tree as pt
from poe_view.services import tree_history as th
from poe_view.ui.character_sheet import build_character_sheet, tree_section

# tests/conftest.py stubbt pt.fetch() global weg (kein Test soll 13 MB von
# GitHub laden); die Tests hier prüfen die echte Logik.
_real_fetch = pt.fetch


def _knoten(name, out=(), **extra) -> dict:
    return {"name": name, "out": [str(o) for o in out], "in": [], **extra}


# Ein winziger Baum in GGGs Format:
#
#   [Start Marauder 1] - 10 - 11 - 12(Notable "Iron Heart") - 13(Keystone)
#                          \- 20 - 21(Jewel)        \- 14 - 15(Notable "Far Away")
#   10 - 30(Start Witch) - 31(Notable "Behind Witch")   ← Witch-Start versperrt
#   1 - 50(Aszendenz-Start Juggernaut) - 51(Asz.-Notable)
#   Mastery 40 hängt an nichts.
_ROH = {
    "classes": [{"name": "Scion", "ascendancies": []},
                {"name": "Marauder", "ascendancies": [{"id": "Juggernaut", "name": "Juggernaut"}]},
                {"name": "Witch", "ascendancies": []}],
    "jewelSlots": [21],
    "nodes": {
        "root": {"out": ["1", "30"]},
        "1": _knoten("MARAUDER", (10, 50), classStartIndex=1),
        "10": _knoten("Strength", (11, 20, 30), stats=["+10 to Strength"]),
        "11": _knoten("Strength", (12,), stats=["+10 to Strength"]),
        "12": _knoten("Iron Heart", (13, 14), isNotable=True,
                      stats=["+20 to maximum Life", "Regenerate 1%\nof Life per second"]),
        "13": _knoten("Iron Will", (), isKeystone=True, stats=["Strength's bonus applies"]),
        "14": _knoten("Life", (15,), stats=["5% increased maximum Life"]),
        "15": _knoten("Far Away", (), isNotable=True, stats=["+5% to Fire Resistance"]),
        "20": _knoten("Life", (21,), stats=["5% increased maximum Life"]),
        "21": _knoten("Basic Jewel Socket", (), isJewelSocket=True),
        "30": _knoten("WITCH", (31,), classStartIndex=3),
        "31": _knoten("Behind Witch", (), isNotable=True, stats=["+30 to Intelligence"]),
        "40": _knoten("Life Mastery", (), isMastery=True, masteryEffects=[
            {"effect": 777, "stats": ["+50 to maximum Life"]},
            {"effect": 778, "stats": ["10% reduced Mana Cost"]}]),
        "50": _knoten("Juggernaut", (51,), ascendancyName="Juggernaut", isAscendancyStart=True),
        "51": _knoten("Unstoppable", (), ascendancyName="Juggernaut", isNotable=True,
                      stats=["Action Speed cannot be slowed"]),
    },
}


@pytest.fixture()
def baum() -> pt.Tree:
    return pt.parse_tree(_ROH, ruthless=True)


# --- Baumdaten ------------------------------------------------------------ #

def test_parsing_knows_kinds_both_directions_and_class_starts(baum) -> None:
    n = baum.nodes
    assert (n[12].kind, n[13].kind, n[21].kind, n[40].kind, n[11].kind) == (
        pt.NOTABLE, pt.KEYSTONE, pt.JEWEL, pt.MASTERY, pt.SMALL)
    assert n[1].kind == n[50].kind == pt.START
    assert 10 in n[11].neighbours and 11 in n[10].neighbours     # Kante in beide Richtungen
    assert baum.class_starts["Marauder"] == baum.class_starts["Juggernaut"] == 1
    assert n[40].effects[777] == ("+50 to maximum Life",)
    assert baum.jewel_slots == [21]


def test_a_line_break_inside_a_value_stays_one_line(baum) -> None:
    """GGG bricht auch mitten im Satz um — kein Zerreißen."""
    assert baum.nodes[12].stats == ("+20 to maximum Life", "Regenerate 1% / of Life per second")


# --- Reichweite ----------------------------------------------------------- #

def _reach(baum, have, **kw):
    return {r.node.name: (r.cost, [v.name for v in r.via])
            for r in pt.within_reach(baum, set(have), **kw)}


def test_reach_counts_new_points_and_names_the_way(baum) -> None:
    assert _reach(baum, {10, 11}) == {
        "Iron Heart": (1, []), "Iron Will": (2, ["Iron Heart"]),
        "Far Away": (3, ["Iron Heart", "Life"]), "Basic Jewel Socket": (2, ["Life"])}


def test_reach_stops_at_the_limit(baum) -> None:
    assert _reach(baum, {10, 11}, max_points=2) == {
        "Iron Heart": (1, []), "Iron Will": (2, ["Iron Heart"]),
        "Basic Jewel Socket": (2, ["Life"])}


def test_a_fresh_character_starts_from_its_class_start(baum) -> None:
    """Ohne einen einzigen Punkt; die Aszendenz nennt denselben Start."""
    assert _reach(baum, set(), class_name="Juggernaut")["Iron Heart"] == (3, ["Strength", "Strength"])
    assert _reach(baum, set()) == {}


def test_no_way_through_another_class_start_or_into_the_ascendancy(baum) -> None:
    gefunden = _reach(baum, {10, 11, 1}, max_points=6)
    assert "Behind Witch" not in gefunden
    assert "Unstoppable" not in gefunden


# --- Charakterdaten ------------------------------------------------------- #

@pytest.mark.parametrize("passives, league, erwartet", [
    ({"ruthless": True}, "Standard", True),
    ({"ruthless": False}, "SSF R Allflame", False),     # das API-Feld gewinnt
    ({}, "SSF R Allflame", True),
    ({}, "Ruthless Mercenaries", True),
    ({}, "Standard", False),
    ({}, "Rare Hardcore", False),
])
def test_ruthless_from_the_api_field_else_the_league_name(passives, league, erwartet) -> None:
    assert pt.is_ruthless(passives, league) is erwartet


def test_mastery_choices_as_object_and_packed_numbers() -> None:
    assert pt.mastery_choices({"mastery_effects": {"40": 777}}) == {40: 777}
    assert pt.mastery_choices({"mastery_effects": [777 << 16 | 40]}) == {40: 777}


def test_small_passives_are_summed_by_wording() -> None:
    assert pt.summed_stats(["+10 to Strength", "5% increased maximum Life", "+10 to Strength",
                            "+1.5 to Strength", "5% increased maximum Life"]) == [
        "10% increased maximum Life", "+21.5 to Strength"]


# --- Download ------------------------------------------------------------- #

def _mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_writes_both_trees_and_load_picks_the_right_one(monkeypatch) -> None:
    monkeypatch.setattr(pt, "fetch", _real_fetch)
    inhalte = {"data.json": {"nodes": {"1": _knoten("Normal")}},
               "ruthless.json": {"nodes": {"1": _knoten("Ruthless")}}}

    def handler(request):
        return httpx.Response(200, content=json.dumps(inhalte[request.url.path.rsplit("/", 1)[-1]]))

    assert pt.fetch(_mock(handler)) is True
    assert pt.is_fresh()
    assert pt.load(False).nodes[1].name == "Normal"
    assert pt.load(True).nodes[1].name == "Ruthless"


def test_a_failed_download_keeps_what_was_there(monkeypatch) -> None:
    monkeypatch.setattr(pt, "fetch", _real_fetch)
    pt.tree_dir().mkdir(parents=True)
    (pt.tree_dir() / "data.json").write_text("{}", encoding="utf-8")

    def handler(request):
        if request.url.path.endswith("ruthless.json"):
            return httpx.Response(404)
        return httpx.Response(200, content=b'{"nodes": {}}')

    assert pt.fetch(_mock(handler)) is False
    assert (pt.tree_dir() / "data.json").read_text(encoding="utf-8") == "{}"
    assert not (pt.tree_dir() / "ruthless.json").exists()


def test_without_tree_data_load_gives_none() -> None:
    pt._LOADED.clear()
    assert pt.load(True) is None


# --- Verlauf -------------------------------------------------------------- #

_P1 = {"hashes": [11, 10], "bandit_choice": "Kraityn"}


def test_a_new_tree_is_recorded_once() -> None:
    zeichen: dict = {}
    assert th.record(zeichen, "WitchOfPeter", _P1, level=30, ruthless=True,
                     now=datetime(2026, 10, 4, 19, 0))
    assert not th.record(zeichen, "WitchOfPeter", {"hashes": [10, 11], "bandit_choice": "Kraityn"},
                         level=30, ruthless=True)
    assert len(zeichen["WitchOfPeter"]["history"]) == 1
    assert th.current(zeichen, "WitchOfPeter")["at"] == "2026-10-04T19:00:00"


def test_a_level_up_without_new_points_updates_but_adds_no_history() -> None:
    zeichen: dict = {}
    th.record(zeichen, "WitchOfPeter", _P1, level=30, ruthless=True)
    assert th.record(zeichen, "WitchOfPeter", _P1, level=31, ruthless=True)
    assert th.current(zeichen, "WitchOfPeter")["level"] == 31
    assert [e["level"] for e in zeichen["WitchOfPeter"]["history"]] == [30]


def test_a_changed_tree_adds_to_the_history_and_an_empty_one_changes_nothing() -> None:
    zeichen: dict = {}
    th.record(zeichen, "WitchOfPeter", _P1, level=30, ruthless=True)
    assert not th.record(zeichen, "WitchOfPeter", {}, level=30, ruthless=True)
    assert th.record(zeichen, "WitchOfPeter", {"hashes": [10, 11, 12]}, level=31, ruthless=True)
    assert len(zeichen["WitchOfPeter"]["history"]) == 2


def test_the_history_is_capped(monkeypatch) -> None:
    monkeypatch.setattr(th, "MAX_HISTORY", 3)
    zeichen: dict = {}
    for n in range(5):
        th.record(zeichen, "WitchOfPeter", {"hashes": [n]}, level=n, ruthless=False)
    assert [e["level"] for e in zeichen["WitchOfPeter"]["history"]] == [2, 3, 4]


def test_save_and_load_round_trip_and_a_wrong_version_is_ignored() -> None:
    pfad = th.path_for("TestAccount#1234")
    zeichen: dict = {}
    th.record(zeichen, "WitchOfPeter", _P1, level=30, ruthless=True)
    th.save(pfad, zeichen)
    assert th.load(pfad) == zeichen
    pfad.write_text(json.dumps({"version": 99, "characters": zeichen}), encoding="utf-8")
    assert th.load(pfad) == {}


# --- Charakterbogen ------------------------------------------------------- #

def _eintrag(hashes, **passives):
    return {"level": 30, "ruthless": True, "passives": {"hashes": hashes, **passives}}


def test_the_sheet_section_lists_nodes_masteries_sums_and_reach(baum) -> None:
    text = "\n".join(tree_section(
        _eintrag([10, 11, 12, 51], mastery_effects={"40": 777}, bandit_choice="Kraityn"),
        baum, character_class="Juggernaut"))
    assert "Ruthless tree · 3 points allocated · 1 ascendancy points" in text
    assert "Level 30 gives 29 points from levels" in text
    assert "Bandit: Kraityn" in text
    assert "### Ascendancy (Juggernaut)\n\n- **Unstoppable** — Action Speed cannot be slowed" in text
    assert "- **Iron Heart** — +20 to maximum Life; Regenerate 1% / of Life per second" in text
    assert "- **Life Mastery** — +50 to maximum Life" in text
    assert "### Small passives (2), summed\n\n- +20 to Strength" in text
    assert "- **Iron Will** (keystone, 1 point) — Strength's bonus applies" in text
    assert "- **Basic Jewel Socket** (jewel socket, 2 points; via Life) — empty socket" in text


def test_the_sheet_section_without_tree_or_without_data(baum) -> None:
    assert "Not known yet" in "\n".join(tree_section(None, baum, character_class="Juggernaut"))
    ohne = "\n".join(tree_section(_eintrag([10, 11]), None, character_class="Juggernaut"))
    assert "2 nodes allocated" in ohne and "not been downloaded" in ohne


def test_nodes_missing_from_the_tree_data_are_counted(baum) -> None:
    text = "\n".join(tree_section(_eintrag([10, 99999]), baum, character_class="Juggernaut"))
    assert "1 allocated nodes are missing" in text


def test_the_whole_sheet_ends_with_the_tree_and_its_jewels(baum) -> None:
    char = Character.model_validate({"name": "WitchOfPeter", "class": "Juggernaut", "level": 30})
    jewel = Item.model_validate({"typeLine": "Crimson Jewel", "baseType": "Crimson Jewel",
                                 "inventoryId": "PassiveJewels", "explicitMods": ["+8% to Fire Resistance"]})
    text = build_character_sheet(char, [jewel], tree_entry=_eintrag([10, 11, 20, 21]), tree=baum)
    assert text.index("## Gems") < text.index("## Passive tree")
    assert "### Jewels (1 sockets allocated)\n\n- **Crimson Jewel** — +8% to Fire Resistance" in text


def test_a_jewel_swap_updates_the_current_tree_without_history() -> None:
    zeichen: dict = {}
    th.record(zeichen, "WitchOfPeter", {**_P1, "jewel_data": {"0": "a"}}, level=30, ruthless=True)
    assert th.record(zeichen, "WitchOfPeter", {**_P1, "jewel_data": {"0": "b"}}, level=30,
                     ruthless=True)
    assert th.current(zeichen, "WitchOfPeter")["passives"]["jewel_data"] == {"0": "b"}
    assert zeichen["WitchOfPeter"]["history"][0]["passives"]["jewel_data"] == {"0": "a"}
