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
    assert "### 👑 Ascendancy (Juggernaut)\n\n- **Unstoppable** — Action Speed cannot be slowed" in text
    assert "- **Iron Heart** — +20 to maximum Life; Regenerate 1% / of Life per second" in text
    assert "- **Life Mastery** — +50 to maximum Life" in text
    assert "### Notables (1): 1 Defence" in text and "#### 🛡 Defence (1)" in text
    assert "### 📊 Totals (all 4 allocated nodes)" in text
    assert "#### ✦ Utility (1)\n\n- +20 to Strength" in text
    assert "2 small passives — their values are in the totals." in text
    assert "### 🧭 Within reach (up to 4 more points): 1 Keystones, 1 Jewel sockets, 1 Defence" in text
    assert "#### 🔑 Keystones (1)" in text
    assert "- **Iron Will** · 1 point — Strength's bonus applies" in text
    assert "- **Basic Jewel Socket** · 2 points via Life — empty socket" in text
    assert "- **Far Away** · 2 points via Life — +5% to Fire Resistance" in text


def test_without_reach_the_section_ends_before_it(baum) -> None:
    text = "\n".join(tree_section(_eintrag([10, 11, 12]), baum, character_class="Juggernaut",
                                  include_reach=False))
    assert "Iron Heart" in text and "Within reach" not in text


@pytest.mark.parametrize("zeile, thema", [
    ("Minions have +15% to all Elemental Resistances", pt.MINIONS),
    ("+12% to all Elemental Resistances", pt.DEFENCE),
    ("Enemies Cursed by you have 50% reduced Life Regeneration Rate", pt.OFFENCE),
    ("24% increased Elemental Damage", pt.OFFENCE),
    ("20% increased Mana Reservation Efficiency of Skills", pt.UTILITY),
    ("+30 to Intelligence", pt.UTILITY),
    ("+10 to Maximum Rage", pt.OFFENCE),
    ("Your Offering Skills do not require a Corpse", pt.MINIONS),
    ("+30 to maximum Valour", pt.OTHER),
])
def test_each_line_gets_a_theme(zeile, thema) -> None:
    assert pt.line_theme(zeile) == thema


def test_a_node_takes_its_most_important_theme() -> None:
    """Holy Dominion: Resistenzen schlagen Elementarschaden; Retribution:
    Minions schlagen eigenen Schaden."""
    holy = pt.Node(1, "Holy Dominion", pt.NOTABLE,
                   ("+12% to all Elemental Resistances", "24% increased Elemental Damage"))
    vergeltung = pt.Node(2, "Retribution", pt.NOTABLE,
                         ("15% increased Damage", "Minions deal 15% increased Damage"))
    assert (pt.theme(holy), pt.theme(vergeltung)) == (pt.DEFENCE, pt.MINIONS)


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
    assert "### 💎 Jewels (1 sockets allocated)\n\n- **Crimson Jewel** — +8% to Fire Resistance" in text


def test_a_jewel_swap_updates_the_current_tree_without_history() -> None:
    zeichen: dict = {}
    th.record(zeichen, "WitchOfPeter", {**_P1, "jewel_data": {"0": "a"}}, level=30, ruthless=True)
    assert th.record(zeichen, "WitchOfPeter", {**_P1, "jewel_data": {"0": "b"}}, level=30,
                     ruthless=True)
    assert th.current(zeichen, "WitchOfPeter")["passives"]["jewel_data"] == {"0": "b"}
    assert zeichen["WitchOfPeter"]["history"][0]["passives"]["jewel_data"] == {"0": "a"}


# --- Vergleich zweier Bäume (§4.60.1) ------------------------------------- #

def test_compare_lists_refund_allocate_and_mastery_changes(baum) -> None:
    umbau = pt.compare(baum, {"hashes": [10, 11, 12, 51], "mastery_effects": {"40": 777}},
                       {"hashes": [10, 11, 20, 21], "mastery_effects": {"40": 778}})
    assert [n.name for n in umbau.refund] == ["Iron Heart", "Unstoppable"]
    assert [n.name for n in umbau.allocate] == ["Basic Jewel Socket", "Life"]
    assert umbau.points == 1                        # die Aszendenz kostet kein Gold
    assert [(m.name, alt, neu) for m, alt, neu in umbau.masteries] == [
        ("Life Mastery", ("+50 to maximum Life",), ("10% reduced Mana Cost",))]


def test_stat_delta_adds_up_and_signs_the_change(baum) -> None:
    """Iron Heart weg (+20 Life, Regeneration), Life + Far Away + Life dazu."""
    delta = pt.stat_delta(baum, {"hashes": [10, 11, 12]}, {"hashes": [10, 11, 14, 15, 20]})
    assert sorted(delta) == sorted(["+5% to Fire Resistance", "-20 to maximum Life",
                                    "+10% increased maximum Life",
                                    "Regenerate -1% / of Life per second"])


def test_lines_without_numbers_are_gained_or_lost(baum) -> None:
    assert pt.stat_delta(baum, {"hashes": [10]}, {"hashes": [10, 13]}) == [
        "gained: Strength's bonus applies"]
    assert pt.stat_delta(baum, {"hashes": [10, 13]}, {"hashes": [10]}) == [
        "lost: Strength's bonus applies"]


def test_stat_delta_of_the_same_tree_is_empty(baum) -> None:
    assert pt.stat_delta(baum, {"hashes": [10, 12]}, {"hashes": [12, 10]}) == []


# --- Planer-Links --------------------------------------------------------- #

def _code(daten: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(daten).decode()


def test_a_link_survives_the_round_trip(baum) -> None:
    passives = {"hashes": [10, 11, 12, 51], "hashes_ex": [65600], "mastery_effects": {"40": 777}}
    link = pt.decode_url(pt.encode_url(baum, passives, "Juggernaut"))
    assert (link.class_index, link.ascendancy_index) == (1, 1)
    assert pt.allocated(link.passives) == {10, 11, 12, 51}
    assert link.passives["hashes_ex"] == [65600]
    assert pt.mastery_choices(link.passives) == {40: 777}
    assert pt.class_name_of(baum, 1, 1) == "Juggernaut"


def test_start_nodes_are_left_out_of_the_link(baum) -> None:
    link = pt.decode_url(pt.encode_url(baum, {"hashes": [1, 50, 10]}, "Juggernaut"))
    assert pt.allocated(link.passives) == {10}


def test_version_6_layout_byte_by_byte() -> None:
    """Wie GGG und PoB: Mastery als (Effekt, Knoten); Bits 2–3 des
    Aszendenz-Bytes sind eine Liga-Zweitaszendenz und zählen nicht."""
    daten = (bytes([0, 0, 0, 6, 4, 0b1101, 2]) + (300).to_bytes(2, "big") + (7).to_bytes(2, "big")
             + bytes([1]) + (64).to_bytes(2, "big")
             + bytes([1]) + (999).to_bytes(2, "big") + (300).to_bytes(2, "big"))
    link = pt.decode_url("https://www.pathofexile.com/fullscreen-passive-skill-tree/"
                         + _code(daten) + "?accountName=TestAccount")
    assert (link.class_index, link.ascendancy_index) == (4, 1)
    assert link.passives == {"hashes": [300, 7], "hashes_ex": [65600],
                             "mastery_effects": {"300": 999}}


def test_older_versions_4_and_5() -> None:
    v4 = bytes([0, 0, 0, 4, 2, 1, 0]) + (5).to_bytes(2, "big") + (6).to_bytes(2, "big")
    assert pt.decode_url(_code(v4)).passives == {"hashes": [5, 6]}
    v5 = bytes([0, 0, 0, 5, 2, 1, 1]) + (5).to_bytes(2, "big") + bytes([0])
    assert pt.decode_url(_code(v5)).passives == {"hashes": [5]}


@pytest.mark.parametrize("text", ["", "hello world", _code(bytes([0, 0, 0, 9, 1, 1, 0])),
                                  _code(bytes([0, 0, 0, 6, 1, 1, 5, 0, 1]))])
def test_broken_links_are_refused(text) -> None:
    with pytest.raises(pt.TreeLinkError):
        pt.decode_url(text)


# --- Konfigurationen ------------------------------------------------------ #

def test_configs_can_be_saved_renamed_and_deleted() -> None:
    zeichen: dict = {}
    th.save_config(zeichen, "WitchOfPeter", " Max fire res ", {"hashes": [1]}, level=30,
                   ruthless=True, source="link", now=datetime(2026, 10, 4, 20, 0))
    assert th.configs(zeichen, "WitchOfPeter")["Max fire res"]["source"] == "link"
    th.save_config(zeichen, "WitchOfPeter", "Burst", {"hashes": [2]}, level=30,
                   ruthless=True, source="current")
    assert not th.rename_config(zeichen, "WitchOfPeter", "Burst", "Max fire res")
    assert th.rename_config(zeichen, "WitchOfPeter", "Burst", "Boss burst")
    assert th.delete_config(zeichen, "WitchOfPeter", "Max fire res")
    assert list(th.configs(zeichen, "WitchOfPeter")) == ["Boss burst"]
    with pytest.raises(ValueError):
        th.save_config(zeichen, "WitchOfPeter", "  ", {}, level=1, ruthless=True, source="x")


def test_configs_survive_new_trees_and_saving() -> None:
    zeichen: dict = {}
    th.save_config(zeichen, "WitchOfPeter", "Burst", {"hashes": [2]}, level=30,
                   ruthless=True, source="current")
    th.record(zeichen, "WitchOfPeter", {"hashes": [3]}, level=31, ruthless=True)
    pfad = th.path_for("TestAccount#1234")
    th.save(pfad, zeichen)
    assert "Burst" in th.configs(th.load(pfad), "WitchOfPeter")


# --- Respec-Liste im Text ------------------------------------------------- #

def test_the_respec_text_is_a_worklist(baum) -> None:
    from poe_view.ui.character_sheet import respec_section
    text = "\n".join(respec_section(baum, {"hashes": [10, 11, 12]},
                                    {"hashes": [10, 11, 14, 15]}, title="Respec: a → b"))
    assert "## Respec: a → b" in text
    assert "1 point to refund in the main tree" in text
    assert "### ↩ Refund (1)\n\n- **Iron Heart** (notable)" in text
    assert "### ＋ Allocate (2)\n\n- **Far Away** (notable) — +5% to Fire Resistance" in text
    gewinne = text[text.index("### ▲ Gains"):text.index("### ▼ Losses")]
    verluste = text[text.index("### ▼ Losses"):text.index("### ↩ Refund")]
    assert "- +5% to Fire Resistance" in gewinne and "- +5% increased maximum Life" in gewinne
    assert "- -20 to maximum Life" in verluste
    assert "- Regenerate -1% / of Life per second" in verluste
    umgekehrt = "\n".join(respec_section(baum, {"hashes": [10, 11, 14, 15]},
                                         {"hashes": [10, 11, 12]}, title="b → a"))
    assert "- Regenerate +1% / of Life per second" in umgekehrt[umgekehrt.index("### ▲ Gains"):
                                                                umgekehrt.index("### ▼ Losses")]
    gleich = "\n".join(respec_section(baum, {"hashes": [10]}, {"hashes": [10]}, title="x"))
    assert "Same tree" in gleich


# --- Das Fenster "Passive tree" ------------------------------------------- #

def _fenster(qapp, baum, *, mit_baum=True, gespeichert=None):
    from poe_view.ui.passive_tree_dialog import PassiveTreeDialog
    zeichen: dict = {}
    th.record(zeichen, "WitchOfPeter", {"hashes": [10, 11]}, level=29, ruthless=True,
              now=datetime(2026, 10, 4, 18, 0))
    th.record(zeichen, "WitchOfPeter", {"hashes": [10, 11, 12]}, level=30, ruthless=True,
              now=datetime(2026, 10, 4, 19, 0))
    aufrufe = gespeichert if gespeichert is not None else []
    dialog = PassiveTreeDialog("WitchOfPeter", "Juggernaut", zeichen, baum if mit_baum else None,
                               on_change=lambda: aufrufe.append(1))
    return dialog, zeichen, aufrufe


def _eintraege(dialog) -> list[str]:
    return [dialog.list.item(i).text().strip() for i in range(dialog.list.count())]


def test_the_window_lists_current_configurations_and_history(qapp, baum) -> None:
    from poe_view.ui.passive_tree_dialog import CURRENT
    dialog, zeichen, _ = _fenster(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Max fire res", {"hashes": [10, 14, 15]}, level=30,
                   ruthless=True, source="link")
    dialog.refresh()
    assert _eintraege(dialog) == ["Current tree", "Configurations", "Max fire res", "History",
                                  "2026-10-04 19:00 · Level 30 · +1 / −0",
                                  "2026-10-04 18:00 · Level 29 · first seen"]
    assert dialog._selected() == (CURRENT, None)
    assert "Iron Heart" in dialog.text.toPlainText()
    dialog.close()


def test_a_configuration_shows_the_respec_from_the_current_tree(qapp, baum) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG, HISTORY
    dialog, zeichen, _ = _fenster(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Max fire res", {"hashes": [10, 11, 14, 15]},
                   level=30, ruthless=True, source="link")
    text = dialog.markdown_for((CONFIG, "Max fire res"))
    assert text.startswith("## Respec: current tree → Max fire res")
    assert "### ↩ Refund (1)\n\n- **Iron Heart**" in text
    assert "## Configuration: Max fire res" in text
    verlauf = dialog.markdown_for((HISTORY, 1))
    assert verlauf.startswith("## Changes from the tree before")
    assert "### ＋ Allocate (1)\n\n- **Iron Heart**" in verlauf
    dialog.close()


def test_save_current_as_a_configuration(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    monkeypatch.setattr(modul.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Mapping", True)))
    dialog._save_current()
    assert th.configs(zeichen, "WitchOfPeter")["Mapping"]["passives"] == {"hashes": [10, 11, 12]}
    assert gespeichert == [1]
    assert dialog._selected() == (modul.CONFIG, "Mapping")
    # Ein vorhandener Name wird nur nach Rückfrage ersetzt.
    monkeypatch.setattr(modul.QMessageBox, "question",
                        staticmethod(lambda *a, **k: modul.QMessageBox.StandardButton.No))
    dialog._save_current()
    assert gespeichert == [1]
    dialog.close()


def test_import_a_planner_link(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    link = pt.encode_url(baum, {"hashes": [10, 11, 14, 15]}, "Juggernaut")
    antworten = iter([(link, True), ("Max fire res", True)])
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(lambda *a, **k: next(antworten)))
    dialog._import_link()
    gespeichert_als = th.configs(zeichen, "WitchOfPeter")["Max fire res"]
    assert pt.allocated(gespeichert_als["passives"]) == {10, 11, 14, 15}
    assert gespeichert_als["source"] == "link"
    assert gespeichert == [1]
    dialog.close()


def test_a_broken_link_or_another_class_is_not_imported_silently(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    warnungen = []
    monkeypatch.setattr(modul.QMessageBox, "warning", staticmethod(lambda *a, **k: warnungen.append(a)))
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(lambda *a, **k: ("nonsense", True)))
    dialog._import_link()
    assert len(warnungen) == 1 and gespeichert == []
    hexe = pt.encode_url(baum, {"hashes": [31]}, "Witch")
    fragen = []
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(lambda *a, **k: (hexe, True)))
    monkeypatch.setattr(modul.QMessageBox, "question", staticmethod(
        lambda *a, **k: fragen.append(a[2]) or modul.QMessageBox.StandardButton.No))
    dialog._import_link()
    assert "for a Witch, not a Juggernaut" in fragen[0]
    assert gespeichert == [] and th.configs(zeichen, "WitchOfPeter") == {}
    dialog.close()


def test_rename_and_delete_a_configuration(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    for name in ("Burst", "Fire"):
        th.save_config(zeichen, "WitchOfPeter", name, {"hashes": [10]}, level=30,
                       ruthless=True, source="current")
    dialog.refresh((modul.CONFIG, "Burst"))
    assert dialog.rename_button.isEnabled() and dialog.delete_button.isEnabled()
    warnungen = []
    monkeypatch.setattr(modul.QMessageBox, "warning", staticmethod(lambda *a, **k: warnungen.append(a)))
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Fire", True)))
    dialog._rename()
    assert warnungen and sorted(th.configs(zeichen, "WitchOfPeter")) == ["Burst", "Fire"]
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Boss", True)))
    dialog._rename()
    assert sorted(th.configs(zeichen, "WitchOfPeter")) == ["Boss", "Fire"]
    monkeypatch.setattr(modul.QMessageBox, "question",
                        staticmethod(lambda *a, **k: modul.QMessageBox.StandardButton.Yes))
    dialog._delete()
    assert list(th.configs(zeichen, "WitchOfPeter")) == ["Fire"]
    assert gespeichert == [1, 1]
    dialog.refresh((modul.CURRENT, None))
    assert not dialog.rename_button.isEnabled() and not dialog.delete_button.isEnabled()
    dialog.close()


def test_links_and_text_go_to_the_clipboard(qapp, baum) -> None:
    from PySide6.QtGui import QGuiApplication
    from poe_view.ui.passive_tree_dialog import CURRENT
    dialog, _zeichen, _ = _fenster(qapp, baum)
    dialog._copy_link()
    link = QGuiApplication.clipboard().text()
    assert link.startswith(pt.PLANNER_URL)
    assert pt.allocated(pt.decode_url(link).passives) == {10, 11, 12}
    dialog._copy_text()
    assert QGuiApplication.clipboard().text() == dialog.markdown_for((CURRENT, None))
    dialog.close()


def test_without_tree_data_the_window_says_so(qapp, baum) -> None:
    dialog, _zeichen, _ = _fenster(qapp, baum, mit_baum=False)
    assert "not been downloaded" in dialog.text.toPlainText()
    assert not dialog.planner_button.isEnabled() and not dialog.import_button.isEnabled()
    dialog.close()


def test_the_query_after_the_code_is_cut_off() -> None:
    """Geteilte Links tragen "?accountName=…&characterName=…". Buchstaben
    darin schaden nicht (Base64 überliest sie, der Rest hängt hinten an);
    ein "/" im Anhang aber ließe den Code beim letzten "/" beginnen."""
    daten = bytes([0, 0, 0, 6, 1, 1, 1]) + (300).to_bytes(2, "big") + bytes([0, 0])
    link = pt.decode_url(f"https://www.pathofexile.com/passive-skill-tree/{_code(daten)}"
                         "?accountName=TestAccount&from=/forum/view-thread/1")
    assert link.passives == {"hashes": [300]}


def test_the_respec_tab_shows_only_for_a_configuration(qapp, baum) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG, CURRENT
    dialog, zeichen, _ = _fenster(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Fire", {"hashes": [10, 11, 14, 15]}, level=30,
                   ruthless=True, source="link")
    dialog.refresh((CONFIG, "Fire"))
    assert dialog.tabs.isTabVisible(0) and dialog.tabs.currentIndex() == 0
    assert "Refund (1)" in dialog.respec_text.toPlainText()
    dialog.refresh((CURRENT, None))
    assert not dialog.tabs.isTabVisible(0) and dialog.tabs.currentIndex() == 1
    assert "Within reach" not in dialog.text.toPlainText()
    dialog.close()


def _gruppen(dialog) -> dict[str, list[str]]:
    ergebnis = {}
    for i in range(dialog.reach.topLevelItemCount()):
        g = dialog.reach.topLevelItem(i)
        if not g.isHidden():
            ergebnis[g.text(0)] = [g.child(j).text(0) for j in range(g.childCount())
                                   if not g.child(j).isHidden()]
    return ergebnis


def test_within_reach_is_a_grouped_table_with_a_filter(qapp, baum) -> None:
    dialog, _zeichen, _ = _fenster(qapp, baum)
    assert _gruppen(dialog) == {"🔑 Keystones (1)": ["Iron Will"],
                                "💎 Jewel sockets (1)": ["Basic Jewel Socket"],
                                "🛡 Defence (1)": ["Far Away"]}
    zeile = dialog.reach.topLevelItem(2).child(0)
    assert (zeile.text(1), zeile.text(3)) == ("2", "Life")
    dialog.reach_filter.setText("fire res")
    assert _gruppen(dialog) == {"🛡 Defence (1 of 1)": ["Far Away"]}
    # Jedes Wort muss passen: "fire" steht bei Far Away, "strength" bei
    # Iron Will — zusammen bei keinem.
    dialog.reach_filter.setText("fire strength")
    assert _gruppen(dialog) == {}
    dialog.reach_filter.setText("")
    assert len(_gruppen(dialog)) == 3
    dialog.close()



# --- Bericht: Summen, Farben, Reihenfolge (§4.60.3) ----------------------- #

def test_the_totals_add_up_every_allocated_node_with_the_key_values_first(baum) -> None:
    """Peter: "eine Summary oben mit den Insgesamtwerten" — kleine Knoten,
    Notables, Keystones, Aszendenz und gewählte Masteries zusammen."""
    from poe_view.ui import tree_report
    bloecke = tree_report.totals_blocks(baum, {"hashes": [10, 11, 12, 14, 13, 51],
                                               "mastery_effects": {"40": 777}})
    nach_thema = {b.title: [i.text for i in b.items] for b in bloecke}
    # Iron Heart +20 und die Mastery +50 ergeben +70 Life; Life vor Regeneration.
    assert nach_thema == {
        "Defence (3)": ["5% increased maximum Life", "+70 to maximum Life",
                        "Regenerate 1% / of Life per second"],
        "Utility (2)": ["Strength's bonus applies", "+20 to Strength"],
        "Other (1)": ["Action Speed cannot be slowed"]}
    assert all(b.columns == 3 for b in bloecke)


def test_the_window_html_is_coloured_per_theme_and_mode(baum) -> None:
    from poe_view.ui import tree_report
    bloecke = tree_report.tree_blocks(_eintrag([10, 11, 12]), baum,
                                      character_class="Juggernaut")
    dunkel = tree_report.to_html(bloecke, dark=True)
    hell = tree_report.to_html(bloecke, dark=False)
    assert tree_report.colour(pt.DEFENCE, True) in dunkel
    assert tree_report.colour(pt.DEFENCE, False) in hell
    assert tree_report.colour(pt.DEFENCE, True) not in hell
    assert "🛡 Defence" in dunkel and "<b" in dunkel


def test_gains_put_the_key_values_first(baum) -> None:
    from poe_view.ui import tree_report
    umbau = tree_report.respec_blocks(baum, {"hashes": [10, 11, 12]},
                                      {"hashes": [10, 11, 14, 15, 20]}, title="x")
    gewinne = next(b for b in umbau if b.key == "gain")
    assert [i.text for i in gewinne.items][0] == "+10% increased maximum Life"


def test_gains_are_ranked_not_alphabetical(baum) -> None:
    """Alphabetisch stünde "gained: Strength's bonus applies" vor "+5% to
    Fire Resistance" — die Resistenz ist aber das, worauf es ankommt."""
    from poe_view.ui import tree_report
    umbau = tree_report.respec_blocks(baum, {"hashes": [10]}, {"hashes": [10, 13, 15]}, title="x")
    gewinne = next(b for b in umbau if b.key == "gain")
    assert [i.text for i in gewinne.items] == ["+5% to Fire Resistance",
                                               "gained: Strength's bonus applies"]


def test_the_theme_heading_itself_is_coloured(baum) -> None:
    from poe_view.ui import tree_report
    html_text = tree_report.to_html(tree_report.tree_blocks(
        _eintrag([10, 11, 12]), baum, character_class="Juggernaut"), dark=True)
    assert f"color:{tree_report.colour(pt.DEFENCE, True)};'>🛡 Defence" in html_text


# --- Der Baum als Bild (§4.60.4) ----------------------------------------- #

def test_orbit_angles_follow_ggg_and_pob() -> None:
    assert pt.orbit_angle(16, 2) == 45 and pt.orbit_angle(16, 4) == 90
    assert pt.orbit_angle(40, 5) == 45 and pt.orbit_angle(40, 6) == 50
    assert pt.orbit_angle(6, 1) == 60 and pt.orbit_angle(72, 36) == 180


def test_nodes_get_their_place_from_group_orbit_and_index() -> None:
    roh = {"constants": {"skillsPerOrbit": [1, 6, 16], "orbitRadii": [0, 82, 162]},
           "groups": {"7": {"x": 1000, "y": 500}},
           "nodes": {"1": _knoten("A", group=7, orbit=2, orbitIndex=4),      # 90°: rechts
                     "2": _knoten("B", group=7, orbit=1, orbitIndex=0),      # 0°: oben
                     "3": _knoten("C", group=7, orbit=0, orbitIndex=0)}}
    b = pt.parse_tree(roh, False)
    assert (round(b.nodes[1].x), round(b.nodes[1].y)) == (1162, 500)
    assert (round(b.nodes[2].x), round(b.nodes[2].y)) == (1000, 418)
    assert (b.nodes[3].x, b.nodes[3].y) == (1000, 500)


def _bild_baum():
    roh = {"constants": {"skillsPerOrbit": [1, 6, 16], "orbitRadii": [0, 82, 162]},
           "classes": [{"name": "Scion", "ascendancies": []},
                       {"name": "Marauder", "ascendancies": []}],
           "groups": {"1": {"x": 0, "y": 0}, "2": {"x": 2000, "y": 0}},
           "nodes": {"1": _knoten("MARAUDER", (10,), classStartIndex=1, group=1),
                     "10": _knoten("Life", (11, 12), group=2, orbit=2, orbitIndex=0,
                                   stats=["+10 to maximum Life"]),
                     "11": _knoten("Life", (), group=2, orbit=2, orbitIndex=4,
                                   stats=["+10 to maximum Life"]),
                     "12": _knoten("Fire Heart", (), isNotable=True, group=2, orbit=1,
                                   orbitIndex=3, stats=["+20% to Fire Resistance"]),
                     "50": _knoten("Asc", (), ascendancyName="Juggernaut", group=1,
                                   orbit=1)}}
    return pt.parse_tree(roh, True)


def test_the_graph_draws_nodes_arcs_and_states(qapp) -> None:
    from PySide6.QtGui import QPainterPath
    from poe_view.ui.tree_graph import ALLOCATED, DIM, TreeGraph
    g = TreeGraph()
    b = _bild_baum()
    g.set_tree(b)
    assert set(g._items) == {1, 10, 11, 12}                # keine Aszendenz
    bogen = next(w for a, c, w in g._edges if {a, c} == {10, 11})
    gerade = next(w for a, c, w in g._edges if {a, c} == {10, 12})
    assert bogen.elementCount() > 2                        # Bogen: mehrere Kurvenstücke
    assert gerade.elementCount() == 2 and isinstance(gerade, QPainterPath)
    g.show_tree({"hashes": [10]}, "Marauder")
    assert g.states[10] == ALLOCATED and g.states[1] == ALLOCATED   # eigener Start
    assert g.states[11] == DIM and not g.comparing
    assert g.reach_ids == {12}
    g.highlight("fire res")
    assert g.search_ids == {12}


def test_the_graph_compares_two_trees(qapp) -> None:
    from poe_view.ui.tree_graph import ALLOCATE, ALLOCATED, REFUND, TreeGraph
    g = TreeGraph()
    g.set_tree(_bild_baum())
    g.show_tree({"hashes": [10, 12]}, "Marauder", compare_to={"hashes": [10, 11]})
    assert (g.states[10], g.states[12], g.states[11]) == (ALLOCATED, ALLOCATE, REFUND)
    assert g.comparing and g.reach_ids == set()


def test_the_window_has_a_tree_tab_that_follows_the_selection(qapp, baum) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG, CURRENT
    dialog, zeichen, _ = _fenster(qapp, baum)
    assert dialog.tabs.tabText(3) == "Tree"
    th.save_config(zeichen, "WitchOfPeter", "Fire", {"hashes": [10, 11, 14, 15]}, level=30,
                   ruthless=True, source="link")
    dialog.refresh((CONFIG, "Fire"))
    assert dialog.graph.comparing and not dialog.graph_reach.isEnabled()
    assert "green: allocate" in dialog.graph_legend.text().lower()
    dialog.refresh((CURRENT, None))
    assert not dialog.graph.comparing and dialog.graph_reach.isEnabled()
    dialog.close()


def test_no_reach_rings_while_comparing_and_search_needs_every_word(qapp) -> None:
    """Beim Vergleich lenkten Reichweiten-Ringe von Grün/Rot ab; die Suche
    verlangt jedes Wort ("fire life" passt auf keinen Knoten)."""
    from poe_view.ui.tree_graph import TreeGraph
    g = TreeGraph()
    g.set_tree(_bild_baum())
    g.show_tree({"hashes": [10]}, "Marauder", compare_to={"hashes": [10, 11]})
    assert g.reach_ids == set()             # ohne Vergleich wäre Fire Heart drin
    g.highlight("fire life")
    assert g.search_ids == set()


def test_class_starts_show_the_class_name_not_ggg_internal_names() -> None:
    """GGG nennt den Scion-Start "SEVEN" (Peter: "Wie kommst du auf Seven?")."""
    roh = {"classes": [{"name": "Scion", "ascendancies": []}],
           "nodes": {"58833": _knoten("SEVEN", (), classStartIndex=0)}}
    assert pt.parse_tree(roh, False).nodes[58833].name == "Scion"


def test_the_tooltip_comes_from_the_node_under_the_mouse(qapp) -> None:
    """Sofort statt nach Qts Verzögerung — der Text kommt aus ``tooltip_at``."""
    from poe_view.ui.tree_graph import TreeGraph
    g = TreeGraph()
    g.resize(400, 400)
    g.set_tree(_bild_baum())
    g.show_tree({"hashes": [10]}, "Marauder")
    g.centerOn(g._items[12].sceneBoundingRect().center())
    mitte = g.mapFromScene(g._items[12].sceneBoundingRect().center())
    assert g.tooltip_at(mitte).startswith("Fire Heart (Notable)")
    assert g.items(mitte) and all(not i.toolTip() for i in g.items(mitte))
    assert g.tooltip_at(mitte + type(mitte)(150, 150)) is None


def test_the_tree_window_can_be_maximised(qapp, baum) -> None:
    from PySide6.QtCore import Qt
    dialog, _z, _ = _fenster(qapp, baum)
    assert dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
    dialog.close()


def _klassen_baum():
    """Drei Klassen am Rand (Witch oben, Shadow bei 60°, Ranger bei 120°)
    und der Scion in der Mitte — wie im echten Baum, nur weniger."""
    import math
    lage = {0: (0, 0), 3: (0, -3000), 6: (60, 3000), 2: (120, 3000)}
    gruppen, knoten = {}, {}
    for index, (w, d) in lage.items():
        if index == 3:
            x, y = 0, -3000
        elif index == 0:
            x, y = 0, 0
        else:
            x, y = math.sin(math.radians(w)) * d, -math.cos(math.radians(w)) * d
        gruppen[str(index + 1)] = {"x": x, "y": y}
        knoten[str(100 + index)] = _knoten("START", (), classStartIndex=index, group=index + 1)
    knoten["200"] = _knoten("Far", (), group=4, orbit=0)        # irgendein Knoten
    gruppen["99"] = {"x": 0, "y": 6000}
    knoten["300"] = _knoten("Outer", (), group=99, orbit=0)     # bestimmt den Rand
    roh = {"constants": {"skillsPerOrbit": [1], "orbitRadii": [0]},
           "classes": [{"name": "Scion", "base_str": 20, "base_dex": 20, "base_int": 20,
                        "ascendancies": [{"name": "Ascendant"}]},
                       {"name": "Marauder", "base_str": 32, "base_dex": 14, "base_int": 14},
                       {"name": "Ranger", "base_str": 14, "base_dex": 32, "base_int": 14,
                        "ascendancies": [{"name": "Warden"}, {"name": "Deadeye"}]},
                       {"name": "Witch", "base_str": 14, "base_dex": 14, "base_int": 32,
                        "ascendancies": [{"name": "Occultist"}, {"name": "Elementalist"},
                                         {"name": "Necromancer"}]},
                       {"name": "Duelist", "base_str": 23, "base_dex": 23, "base_int": 14},
                       {"name": "Templar", "base_str": 23, "base_dex": 14, "base_int": 23},
                       {"name": "Shadow", "base_str": 14, "base_dex": 23, "base_int": 23,
                        "ascendancies": [{"name": "Assassin"}]}],
           "groups": gruppen, "nodes": knoten}
    return pt.parse_tree(roh, False)


def test_classes_know_their_main_attributes_and_ascendancies() -> None:
    """Grundlage der Bereiche (§4.60.5): höchste Grundwerte, Scion keiner."""
    b = _klassen_baum()
    attr = {c.name: c.attributes for c in b.classes}
    assert attr == {"Scion": (), "Marauder": ("str",), "Ranger": ("dex",), "Witch": ("int",),
                    "Duelist": ("str", "dex"), "Templar": ("str", "int"),
                    "Shadow": ("dex", "int")}
    witch = next(c for c in b.classes if c.name == "Witch")
    assert witch.ascendancies == ("Occultist", "Elementalist", "Necromancer")
    assert witch.start == 103 and witch.index == 3


def test_class_areas_lie_around_their_start_and_leave_the_centre_free() -> None:
    from poe_view.ui.tree_graph import class_areas
    bereiche, innen, aussen = class_areas(_klassen_baum())
    lage = {c.name: (round(w), round(von) % 360, round(bis) % 360)
            for c, w, von, bis in bereiche}
    # Grenzen mittig zwischen den Nachbarn; ohne Scion (Mitte).
    assert lage == {"Witch": (0, 240, 30), "Shadow": (60, 30, 90), "Ranger": (120, 90, 240)}
    assert innen == pytest.approx(1500) and aussen == pytest.approx(6300)


def _bereich_pixel(g, x, y):
    from PySide6.QtCore import QPointF
    bild = g.grab().toImage()
    p = g.mapFromScene(QPointF(x, y))
    return bild.pixelColor(p.x(), p.y()).name()


def test_the_graph_tints_class_areas_and_stripes_hybrids(qapp) -> None:
    """Witch blau, Ranger grün, Shadow gestreift aus beiden — das gemalte
    Pixel, nicht der gesetzte Wert; die Mitte bleibt ungetönt."""
    import math
    from poe_view.ui.tree_graph import _TOENUNG, TreeGraph
    g = TreeGraph()
    g.resize(500, 500)
    g.set_tree(_klassen_baum())
    g.show_tree({"hashes": []}, "Necromancer", dark=True)
    g.resetTransform()
    g.scale(0.04, 0.04)
    g.centerOn(0, 0)
    t = _TOENUNG[True]
    assert _bereich_pixel(g, -800, -4500) == t["int"]                 # Witch
    w = math.radians(120)
    assert _bereich_pixel(g, math.sin(w) * 4500, -math.cos(w) * 4500) == t["dex"]   # Ranger
    assert _bereich_pixel(g, 0, 700) not in t.values()               # Mitte
    # Shadow: eine Reihe Pixel quer durch die Streifen enthält beide Farben.
    from PySide6.QtCore import QPointF
    bild = g.grab().toImage()
    w = math.radians(60)
    p = g.mapFromScene(QPointF(math.sin(w) * 4000, -math.cos(w) * 4000))
    farben = {bild.pixelColor(p.x() + i, p.y()).name() for i in range(-12, 12)}
    assert {t["dex"], t["int"]} <= farben


def test_the_graph_names_classes_at_the_edge_and_marks_your_own(qapp) -> None:
    from PySide6.QtWidgets import QGraphicsItem
    from poe_view.services.passive_tree import ClassInfo
    from poe_view.ui import tree_report
    from poe_view.ui.tree_graph import TreeGraph
    g = TreeGraph()
    g.set_tree(_klassen_baum())
    g.show_tree({"hashes": []}, "Necromancer", dark=True)
    texte = {k.name: t for t, k, _w in g.labels}
    assert set(texte) == {"Witch", "Shadow", "Ranger"}               # Scion: Mitte
    gold = tree_report.colour("keystone", True)
    witch = texte["Witch"].toHtml()
    assert witch.count(gold) == 2                                    # Klasse + Necromancer
    import re

    def stil(name):          # Stil des Spans, in dem der Name steht
        return re.search(r'<span style="([^"]*)">[^<]*' + name, witch).group(1)
    assert gold in stil("Necromancer") and "font-weight:700" in stil("Necromancer")
    assert gold not in stil("Occultist") and "#b0b0b0" in stil("Occultist")
    assert gold not in texte["Ranger"].toHtml() and "Deadeye" in texte["Ranger"].toHtml()
    t = texte["Witch"]
    assert t.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    # Außen am Rand: über dem obersten Punkt des Kreises, mittig.
    unterkante = t.pos().y() + t.transform().dy() + t.boundingRect().height()
    assert t.pos().y() == pytest.approx(-6300) and unterkante < t.pos().y()
    assert t.transform().dx() == pytest.approx(-t.boundingRect().width() / 2)
    assert isinstance(next(iter(g.labels))[1], ClassInfo)


# --- Bearbeiten per Klick (§4.60.6) ---------------------------------------- #

def _mastery_baum() -> pt.Tree:
    """Der kleine Baum, Iron Heart (12) und zwei Masteries in Gruppe 5;
    beide Masteries bieten den Effekt 777 an (gleichnamige Masteries teilen
    sich im echten Baum die Effekt-Kennungen)."""
    import copy
    roh = copy.deepcopy(_ROH)
    roh["nodes"]["12"]["group"] = 5
    roh["nodes"]["40"]["group"] = 5
    roh["nodes"]["11"]["group"] = 5          # ein kleiner Knoten reicht nicht
    # Im echten Baum haben 315 von 353 Masteries Verbindungen — durch sie
    # führt trotzdem kein Weg (hier wäre 11 → 40 → 15 eine Abkürzung).
    roh["nodes"]["40"]["out"] = ["11", "15"]
    roh["nodes"]["41"] = _knoten("Life Mastery", (), isMastery=True, group=5, masteryEffects=[
        {"effect": 777, "stats": ["+50 to maximum Life"]},
        {"effect": 779, "stats": ["Regenerate 1 Life per second"]}])
    return pt.parse_tree(roh, ruthless=True)


def test_path_to_takes_the_shortest_way_and_respects_blocked_nodes(baum) -> None:
    have = {10, 11}
    assert pt.path_to(baum, have, 15, "Marauder") == [12, 14, 15]
    assert pt.path_to(baum, have, 13, "Marauder") == [12, 13]
    assert pt.path_to(baum, set(), 11, "Marauder") == [10, 11]       # vom eigenen Start
    assert pt.path_to(baum, have, 11, "Marauder") == []              # schon vergeben
    assert pt.path_to(baum, have, 31, "Marauder") is None            # hinter fremdem Start
    assert pt.path_to(baum, have, 51, "Marauder") is None            # Aszendenz
    assert pt.path_to(baum, have, 40, "Marauder") is None            # Mastery: per Menü


def test_refund_takes_everything_that_would_be_cut_off(baum) -> None:
    have = {10, 11, 12, 14, 15, 50, 51}
    assert pt.cut_off(baum, have, 15, "Marauder") == {15}
    assert pt.cut_off(baum, have, 11, "Marauder") == {11, 12, 14, 15}
    # Die Aszendenz hängt nicht am Hauptbaum und bleibt.
    assert pt.cut_off(baum, have, 10, "Marauder") == {10, 11, 12, 14, 15}


def test_edits_return_a_new_tree_and_keep_jewels_and_bandit(baum) -> None:
    alt = {"hashes": [10, 11], "jewel_data": {"21": {"type": "X"}}, "bandit_choice": "Alira"}
    neu = pt.edit_allocate(baum, alt, 15, "Marauder")
    assert neu["hashes"] == [10, 11, 12, 14, 15]
    assert neu["jewel_data"] == alt["jewel_data"] and neu["bandit_choice"] == "Alira"
    assert alt["hashes"] == [10, 11]                                 # Vorlage unverändert
    assert pt.edit_allocate(baum, alt, 31, "Marauder") is None
    zurueck = pt.edit_refund(baum, neu, 12, "Marauder")
    assert zurueck["hashes"] == [10, 11]
    assert pt.main_points(baum, {"hashes": [1, 10, 11, 50, 51]}) == 2   # ohne Start/Aszendenz


def test_masteries_need_a_notable_and_each_effect_only_once() -> None:
    b = _mastery_baum()
    ohne = {"hashes": [10, 11]}
    assert pt.path_to(b, {10, 11}, 15, "Marauder") == [12, 14, 15]
    assert not pt.mastery_allowed(b, pt.allocated(ohne), 40)
    assert pt.edit_mastery(b, ohne, 40, 777) is None
    mit = pt.edit_allocate(b, ohne, 12, "Marauder")
    gewaehlt = pt.edit_mastery(b, mit, 40, 777)
    assert 40 in gewaehlt["hashes"] and gewaehlt["mastery_effects"] == {"40": 777}
    assert pt.edit_mastery(b, gewaehlt, 41, 777) is None             # 777 schon vergeben
    assert pt.edit_mastery(b, gewaehlt, 41, 779)["mastery_effects"] == {"40": 777, "41": 779}
    assert pt.edit_mastery(b, gewaehlt, 40, 999) is None             # kein Effekt davon
    # Ohne Notable fällt die Mastery mit weg.
    weg = pt.edit_refund(b, gewaehlt, 12, "Marauder")
    assert weg["hashes"] == [10, 11] and weg["mastery_effects"] == {}
    leer = pt.edit_mastery(b, gewaehlt, 40, None)
    assert 40 not in leer["hashes"] and leer["mastery_effects"] == {}


def test_clicking_in_the_tree_starts_a_draft_and_stays_on_the_tree_tab(qapp, baum) -> None:
    from poe_view.ui.passive_tree_dialog import DRAFT
    dialog, zeichen, aufrufe = _fenster(qapp, baum)
    dialog.tabs.setCurrentIndex(3)
    assert dialog._click_hint(15) == "Click: allocate (2 points)"
    assert dialog._click_hint(11) == "Right-click: refund (2 points)"
    assert dialog._click_hint(31) == "Not reachable from your tree"
    dialog.graph.node_clicked.emit(15, False)
    assert dialog._selected() == (DRAFT, None) and _eintraege(dialog)[0] == "✎ Unsaved changes"
    assert dialog.tabs.currentIndex() == 3                       # nicht zum Respec gesprungen
    assert dialog.graph.comparing              # Entwurf gegen den aktuellen Baum
    assert "Unsaved changes: 5 points (current tree 3)" in dialog.hint.text()
    assert "respec: 0 points to refund" in dialog.hint.text()
    assert dialog.undo_button.isVisibleTo(dialog) and not dialog.undo_button.isEnabled()
    dialog.graph.node_clicked.emit(13, False)
    assert dialog.undo_button.isEnabled()
    dialog.graph.node_clicked.emit(11, True)                     # 11 samt allem dahinter
    assert pt.allocated(dialog._draft) == {10}
    assert "respec: 2 points to refund" in dialog.hint.text()
    dialog._undo_edit()
    dialog._undo_edit()
    assert pt.allocated(dialog._draft) == {10, 11, 12, 14, 15}
    assert aufrufe == []                                         # nichts gespeichert
    assert th.configs(zeichen, "WitchOfPeter") == {}
    dialog._draft = None
    dialog.close()


def test_a_draft_is_saved_as_a_configuration(qapp, baum, monkeypatch) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, aufrufe = _fenster(qapp, baum)
    dialog.graph.node_clicked.emit(15, False)
    assert dialog.save_button.text() == "Save as…"
    assert not dialog.overwrite_button.isVisibleTo(dialog)      # Entwurf aus dem aktuellen Baum
    monkeypatch.setattr(dialog, "_ask_name", lambda *_a: "Far")
    dialog.save_button.click()
    konfig = th.configs(zeichen, "WitchOfPeter")["Far"]
    assert pt.allocated(konfig["passives"]) == {10, 11, 12, 14, 15}
    assert konfig["source"] == "edited" and aufrufe == [1]
    assert dialog._draft is None and dialog._selected() == (CONFIG, "Far")
    assert "✎ Unsaved changes" not in _eintraege(dialog)
    # Weiterbauen an der Konfiguration: "Save to “Far”" überschreibt sie.
    dialog.graph.node_clicked.emit(13, False)
    assert dialog.overwrite_button.isVisibleTo(dialog)
    assert dialog.overwrite_button.text() == "Save to “Far”"
    dialog.overwrite_button.click()
    assert 13 in pt.allocated(th.configs(zeichen, "WitchOfPeter")["Far"]["passives"])
    assert dialog._draft is None and aufrufe == [1, 1]
    dialog.close()


def test_unreachable_clicks_explain_and_lost_drafts_are_asked_for(qapp, baum,
                                                                  monkeypatch) -> None:
    from poe_view.ui.passive_tree_dialog import CURRENT, DRAFT, HISTORY
    dialog, _z, _ = _fenster(qapp, baum)
    dialog.graph.node_clicked.emit(31, False)
    assert dialog._draft is None and "Behind Witch: not reachable" in dialog.hint.text()
    dialog.graph.node_clicked.emit(15, False)
    fragen = []
    monkeypatch.setattr(dialog, "_ask", lambda t, x: fragen.append(x) or False)
    # Neuer Klick aus einem anderen Eintrag: erst fragen, bei "Nein" bleibt alles.
    dialog.refresh((HISTORY, 0))
    dialog.graph.node_clicked.emit(13, False)
    assert len(fragen) == 1 and pt.allocated(dialog._draft) == {10, 11, 12, 14, 15}
    # Schließen fragt ebenso; "Nein" lässt das Fenster offen.
    dialog.show()
    dialog.reject()
    assert len(fragen) == 2 and dialog.isVisible()
    monkeypatch.setattr(dialog, "_ask", lambda t, x: True)
    dialog.refresh((DRAFT, None))
    dialog.discard_button.click()
    assert dialog._draft is None and dialog._selected() == (CURRENT, None)
    dialog.close()


def test_mastery_click_offers_the_effects(qapp, monkeypatch) -> None:
    from poe_view.ui.passive_tree_dialog import PassiveTreeDialog
    b = _mastery_baum()
    zeichen: dict = {}
    th.record(zeichen, "WitchOfPeter", {"hashes": [10, 11, 12]}, level=30, ruthless=True)
    dialog = PassiveTreeDialog("WitchOfPeter", "Marauder", zeichen, b, on_change=lambda: None)
    angeboten = []

    def waehle(node, wahl):
        angeboten.append((node, dict(wahl)))
        return 777
    monkeypatch.setattr(dialog, "_choose_effect", waehle)
    assert dialog._click_hint(40) == "Click: choose an effect"
    dialog.graph.node_clicked.emit(40, False)
    assert angeboten == [(40, {})]
    assert pt.mastery_choices(dialog._draft) == {40: 777}
    dialog.graph.node_clicked.emit(40, True)
    assert pt.mastery_choices(dialog._draft) == {} and 40 not in pt.allocated(dialog._draft)
    dialog._draft = None
    dialog.close()


def test_a_click_selects_a_node_but_a_drag_does_not(qapp) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from poe_view.ui.tree_graph import TreeGraph
    g = TreeGraph()
    g.resize(400, 400)
    g.set_tree(_bild_baum())
    g.show_tree({"hashes": [10]}, "Marauder")
    g.show()
    g.centerOn(g._items[12].sceneBoundingRect().center())
    qapp.processEvents()
    mitte = g.mapFromScene(g._items[12].sceneBoundingRect().center())
    geklickt = []
    g.node_clicked.connect(lambda h, rechts: geklickt.append((h, rechts)))
    QTest.mouseClick(g.viewport(), Qt.MouseButton.LeftButton, pos=mitte)
    QTest.mouseClick(g.viewport(), Qt.MouseButton.RightButton, pos=mitte)
    assert geklickt == [(12, False), (12, True)]
    QTest.mousePress(g.viewport(), Qt.MouseButton.LeftButton, pos=mitte)
    QTest.mouseMove(g.viewport(), mitte + QPoint(40, 0))
    QTest.mouseRelease(g.viewport(), Qt.MouseButton.LeftButton, pos=mitte + QPoint(40, 0))
    assert len(geklickt) == 2
    g.click_hint = lambda h: "Click: allocate (1 point)"
    assert "Click: allocate (1 point)" in g.tooltip_at(mitte).splitlines()
    g.close()


def test_hovering_a_node_rings_it_and_changes_the_cursor(qapp) -> None:
    """Peter: "den Cursor ändern wenn der Mauscursor über der Node ist und
    evtl auch die Node hovern"."""
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtTest import QTest
    from poe_view.ui.tree_graph import TreeGraph
    g = TreeGraph()
    g.resize(400, 400)
    g.set_tree(_bild_baum())
    g.show_tree({"hashes": [10]}, "Marauder")
    g.show()
    g.centerOn(g._items[12].sceneBoundingRect().center())
    qapp.processEvents()
    mitte = g.mapFromScene(g._items[12].sceneBoundingRect().center())
    form = lambda: g.viewport().cursor().shape()                # noqa: E731

    def bewege(punkt):
        # Direkt ans Bild: QTest.mouseMove meldet nichts, wenn die Maus aus
        # einem früheren Test schon dort steht (fiel nur im Gesamtlauf).
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent
        g.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(punkt),
                                     QPointF(g.viewport().mapToGlobal(punkt)),
                                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                     Qt.KeyboardModifier.NoModifier))
    # Nur ansehen (kein click_hint): kein Ring, Zeiger fürs Verschieben.
    bewege(mitte)
    assert g.hovered == 12 and g._hover_ring is None and form() == Qt.CursorShape.OpenHandCursor
    bewege(mitte + QPoint(150, 150))
    g.click_hint = lambda h: ("Click: allocate (1 point)", True)
    bewege(mitte)
    assert g.hovered == 12 and form() == Qt.CursorShape.PointingHandCursor
    ring = g._hover_ring.rect()
    assert ring.center() == g._items[12].rect().center()
    assert ring.width() > g._items[12].rect().width()
    bewege(mitte + QPoint(150, 150))
    assert g.hovered is None and g._hover_ring is None
    assert form() == Qt.CursorShape.OpenHandCursor               # nicht der Pfeil
    g.click_hint = lambda h: ("Not reachable from your tree", False)
    g._hover_info = None
    bewege(mitte)
    assert form() == Qt.CursorShape.ForbiddenCursor
    # Maus verlässt das Bild: Ring weg.
    g.leaveEvent(QEvent(QEvent.Type.Leave))
    assert g.hovered is None and g._hover_ring is None
    # Nach einem Klick (das Verschieben setzt den Zeiger zurück) zeigt der
    # Knoten wieder die Hand.
    g.click_hint = lambda h: ("Click: allocate (1 point)", True)
    g._hover_info = None
    QTest.mouseClick(g.viewport(), Qt.MouseButton.LeftButton, pos=mitte)
    assert g.hovered == 12 and form() == Qt.CursorShape.PointingHandCursor
    g.close()


def test_the_click_cost_is_recomputed_after_an_edit(qapp, baum) -> None:
    """Die Info wird je Knoten zwischengespeichert — nach einem Klick muss
    sie neu gerechnet werden, sonst stünde noch "allocate" am Knoten."""
    dialog, _z, _ = _fenster(qapp, baum)
    assert dialog.graph._click_info(31) == ("Not reachable from your tree", False)
    assert dialog.graph._click_info(15) == ("Click: allocate (2 points)", True)   # gemerkt
    dialog.graph.node_clicked.emit(15, False)
    assert dialog.graph._click_info(15) == ("Right-click: refund (1 point)", True)
    dialog._draft = None
    dialog.close()


def test_long_tooltips_wrap_and_show_the_node_id() -> None:
    """Peter: "Einige sind zu lang, da müssten wir den Text umbrechen" —
    Wind Dancer stand in einer Zeile über die halbe Bildschirmbreite."""
    from poe_view.ui.tree_graph import TOOLTIP_BREITE, TreeGraph
    lang = ("20% less Attack Damage taken if you haven't been Hit by an Attack Recently / "
            "10% more chance to Evade Attacks if you have been Hit by an Attack Recently / "
            "20% more Attack Damage taken if you have been Hit by an Attack Recently")
    text = TreeGraph._tooltip(pt.Node(23455, "Wind Dancer", pt.KEYSTONE, (lang,)))
    zeilen = text.splitlines()
    assert zeilen[:2] == ["Wind Dancer (Keystone)", "ID 23455"]
    assert len(zeilen) >= 4 and all(len(z) <= TOOLTIP_BREITE for z in zeilen)
    assert " ".join(z.strip() for z in zeilen[2:]) == lang        # nichts verloren


def test_ctrl_c_copies_the_hovered_node(qapp) -> None:
    """Strg+C: Name und ID; Strg+Umschalt+C: dazu die Werte. Ohne Knoten
    unter der Maus bleibt die Zwischenablage, wie sie ist."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from poe_view.ui.tree_graph import TreeGraph
    g = TreeGraph()
    g.set_tree(_bild_baum())
    g.show_tree({"hashes": [10]}, "Marauder")
    ablage = QGuiApplication.clipboard()
    ablage.setText("vorher")
    QTest.keyClick(g, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert ablage.text() == "vorher"
    g.hover(12)
    QTest.keyClick(g, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert ablage.text() == "Fire Heart (ID 12)"
    QTest.keyClick(g, Qt.Key.Key_C,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert ablage.text() == "Fire Heart (ID 12)\n+20% to Fire Resistance"
    QTest.keyClick(g, Qt.Key.Key_C)                               # ohne Strg: nichts
    assert ablage.text() == "Fire Heart (ID 12)\n+20% to Fire Resistance"
    g.close()


def test_the_tree_takes_focus_when_the_mouse_enters(qapp) -> None:
    """Sonst landete Strg+C im Suchfeld, das den Fokus noch hatte."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget
    from poe_view.ui.tree_graph import TreeGraph
    rahmen = QWidget()
    feld, g = QLineEdit(), TreeGraph()
    aufbau = QVBoxLayout(rahmen)
    aufbau.addWidget(feld)
    aufbau.addWidget(g)
    rahmen.show()
    feld.setFocus()
    assert rahmen.focusWidget() is feld
    g.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    assert rahmen.focusWidget() is g
    rahmen.close()


def test_search_finds_a_node_by_its_id_and_jumps_there(qapp) -> None:
    """Peter: "Wir könnten noch die ID in die Suche integrieren"."""
    from poe_view.ui.tree_graph import TreeGraph
    g = TreeGraph()
    g.resize(400, 400)
    g.set_tree(_bild_baum())
    g.show_tree({"hashes": [10]}, "Marauder")
    g.show()
    qapp.processEvents()
    g.highlight("12")
    assert g.search_ids == {12}                    # "12" steht in keinem Wert
    g.highlight("fire 12")
    assert g.search_ids == {12}                    # ID und Wort zusammen
    g.highlight("1")                               # die ganze ID, kein Teilstück von 12
    assert g.search_ids == {1, 10, 11}             # Start 1; "+10" im Text von 10 und 11
    g.centerOn(g._items[11].sceneBoundingRect().center())
    mitte = g.viewport().rect().center()
    g.highlight("12")                              # Neuzeichnen: kein Sprung
    assert (g.mapToScene(mitte) - g._items[11].sceneBoundingRect().center()).manhattanLength() < 5
    g.highlight("12", center=True)
    ziel = g._items[12].sceneBoundingRect().center()
    assert (g.mapToScene(mitte) - ziel).manhattanLength() < 20
    g.close()


def test_typing_an_id_in_the_search_field_jumps_to_the_node(qapp) -> None:
    from PySide6.QtCore import QPointF
    from poe_view.ui.passive_tree_dialog import PassiveTreeDialog
    zeichen: dict = {}
    th.record(zeichen, "WitchOfPeter", {"hashes": [10]}, level=30, ruthless=True)
    dialog = PassiveTreeDialog("WitchOfPeter", "Marauder", zeichen, _bild_baum(),
                               on_change=lambda: None)
    dialog.show()
    dialog.tabs.setCurrentIndex(3)
    qapp.processEvents()
    g = dialog.graph
    g.resetTransform()                 # hineingezoomt: der kleine Baum passt sonst ganz hinein
    g.centerOn(QPointF(0, 0))
    dialog.graph_search.setText("12")
    mitte = g.mapToScene(g.viewport().rect().center())
    assert g.search_ids == {12}
    assert (mitte - g._items[12].sceneBoundingRect().center()).manhattanLength() < 20
    dialog.close()


# --- Goldpreis eines Respecs (§4.60.7) -------------------------------------- #

def test_the_gold_table_is_gggs_per_level_table() -> None:
    """Aus GGGs Spieldaten über Path of Building; Level 90 = 8.450, wie in
    Spielerberichten. Steigt nie, ein Wert je Level 1–100."""
    assert len(pt.GOLD_RESPEC) == 100
    assert pt.respec_gold_per_point(1) == 4
    assert pt.respec_gold_per_point(81) == 3752
    assert pt.respec_gold_per_point(90) == 8450
    assert pt.respec_gold_per_point(100) == 29119
    assert all(a <= b for a, b in zip(pt.GOLD_RESPEC, pt.GOLD_RESPEC[1:]))
    assert pt.respec_gold_per_point(0) is None and pt.respec_gold_per_point(101) is None


def test_respec_gold_counts_ascendancy_five_times(baum) -> None:
    """So rechnet PoB: Hauptbaum zum Tabellenpreis, Aszendenz fünffach,
    der Aszendenz-Start zählt nicht."""
    vorher = {"hashes": [10, 11, 12, 14, 15, 50, 51]}
    nachher = {"hashes": [10, 11, 12]}           # 50 ist der Aszendenz-Start
    umbau = pt.compare(baum, vorher, nachher)
    assert (umbau.points, umbau.ascendancy_points) == (2, 1)
    assert umbau.gold(90) == 2 * 8450 + 5 * 8450
    assert umbau.gold(0) is None


def test_the_respec_list_names_the_gold_at_the_current_level(baum) -> None:
    from poe_view.ui import tree_report
    vorher, nachher = {"hashes": [10, 11, 12, 14, 15]}, {"hashes": [10, 11, 12]}
    kopf = tree_report.respec_blocks(baum, vorher, nachher, title="R", level=90)[0]
    assert kopf.paragraphs == ["2 points to refund in the main tree · about 16,900 gold "
                               "at level 90"]
    ohne = tree_report.respec_blocks(baum, vorher, nachher, title="R")[0]
    assert ohne.paragraphs == ["2 points to refund in the main tree"]
    # Nur nehmen kostet nichts — dann kein Goldpreis.
    nur_nehmen = tree_report.respec_blocks(baum, nachher, vorher, title="R", level=90)[0]
    assert "gold" not in nur_nehmen.paragraphs[0]
    # Ein Mastery-Wechsel ist nicht belegt bepreist — das steht dabei.
    mit = tree_report.respec_blocks(
        baum, {"hashes": [10, 11, 12, 14, 15, 40], "mastery_effects": {"40": 777}},
        {"hashes": [10, 11, 12, 40], "mastery_effects": {"40": 778}}, title="R", level=90)[0]
    assert mit.paragraphs[0].endswith("(mastery changes not priced)")


def test_the_window_shows_the_gold_for_configurations_and_drafts(qapp, baum) -> None:
    """Level 30 im Fenster: 54 Gold je Punkt. Der Verlauf bekommt keinen
    Preis — der Umbau liegt in der Vergangenheit."""
    from poe_view.ui.passive_tree_dialog import CONFIG, HISTORY
    dialog, zeichen, _ = _fenster(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Kurz", {"hashes": [10]}, level=30,
                   ruthless=True, source="edited")
    dialog.refresh((CONFIG, "Kurz"))
    assert "about 108 gold at level 30" in dialog.respec_text.toPlainText()
    # Ein Verlaufsschritt MIT Rücknahme — sonst gäbe es ohnehin keinen Preis.
    th.record(zeichen, "WitchOfPeter", {"hashes": [10]}, level=30, ruthless=True,
              now=datetime(2026, 10, 4, 20, 0))
    dialog.refresh((HISTORY, 2))
    assert "2 points to refund" in dialog.respec_text.toPlainText()
    assert "gold" not in dialog.respec_text.toPlainText()
    dialog.refresh((CONFIG, "Kurz"))
    dialog.graph.node_clicked.emit(10, True)          # Entwurf: alles zurück (aktuell ist jetzt [10])
    assert "respec: 1 point to refund · about 54 gold at level 30" in dialog.hint.text()
    dialog._draft = None
    dialog.close()


def test_the_node_tooltip_stays_while_the_mouse_rests(qapp, monkeypatch) -> None:
    """Peter: "Können wir die Anzeigedauer des Tooltips bei den Nodes auf
    unendlich stellen?" Qt blendet sonst nach 10 s aus (ohne echte Maus
    gemessen: Standard 10,0 s, mit TOOLTIP_MS nach 40 s noch da)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from poe_view.ui import tree_graph
    from poe_view.ui.tree_graph import TOOLTIP_MS, TreeGraph
    gezeigt = []
    monkeypatch.setattr(tree_graph.QToolTip, "showText",
                        lambda *args: gezeigt.append(args))
    monkeypatch.setattr(tree_graph.QToolTip, "hideText", lambda: gezeigt.append("weg"))
    g = TreeGraph()
    g.resize(400, 400)
    g.set_tree(_bild_baum())
    g.show_tree({"hashes": [10]}, "Marauder")
    g.show()
    g.centerOn(g._items[12].sceneBoundingRect().center())
    qapp.processEvents()

    def bewege(punkt):
        g.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(punkt),
                                     QPointF(g.viewport().mapToGlobal(punkt)),
                                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                     Qt.KeyboardModifier.NoModifier))
    mitte = g.mapFromScene(g._items[12].sceneBoundingRect().center())
    bewege(mitte)
    assert gezeigt[-1][1].startswith("Fire Heart") and gezeigt[-1][-1] == TOOLTIP_MS
    # Länger als jede Sitzung, aber im Wertebereich von Qt (int).
    assert 24 * 3600 * 1000 < TOOLTIP_MS < 2**31
    bewege(mitte + type(mitte)(150, 150))
    assert gezeigt[-1] == "weg"                     # Maus weg: Tooltip weg
    g.close()


def test_qts_own_tooltip_event_does_not_erase_the_node_tooltip(qapp) -> None:
    """Peter: "Wenn es aktiv ist und ich geh drüber verschwindet der
    Tooltip nach 1s." Qt schickt im aktiven Fenster nach ~0,7 s ein
    eigenes Tooltip-Ereignis; die Szene fand keinen Item-Tooltip und
    blendete unseren 0,3 s später aus. Echter QToolTip, eine Sekunde."""
    import time
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QHelpEvent, QMouseEvent
    from PySide6.QtWidgets import QApplication, QToolTip
    from poe_view.ui.tree_graph import TreeGraph
    g = TreeGraph()
    g.resize(400, 400)
    g.set_tree(_bild_baum())
    g.show_tree({"hashes": [10]}, "Marauder")
    g.show()
    g.centerOn(g._items[12].sceneBoundingRect().center())
    qapp.processEvents()
    p = g.mapFromScene(g._items[12].sceneBoundingRect().center())
    glob = g.viewport().mapToGlobal(p)
    g.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(p), QPointF(glob),
                                 Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                 Qt.KeyboardModifier.NoModifier))
    qapp.processEvents()
    assert QToolTip.isVisible() and QToolTip.text().startswith("Fire Heart")
    QApplication.sendEvent(g.viewport(), QHelpEvent(QEvent.Type.ToolTip, p, glob))
    ende = time.time() + 1.0
    while time.time() < ende:
        qapp.processEvents()
        time.sleep(0.01)
    assert QToolTip.isVisible()
    QToolTip.hideText()
    g.close()


def test_a_mastery_tooltip_lists_its_effects_for_planning(qapp) -> None:
    """Peter: "Bei den Masterys sollten wir zumindest hinschreiben was
    möglich ist zum Planen." ✓ der gewählte Effekt; einer, der schon in
    einer anderen Mastery steckt, ist als vergeben markiert."""
    from poe_view.ui.tree_graph import TreeGraph
    b = _mastery_baum()
    m = b.nodes[40]
    frei = TreeGraph._tooltip(m).splitlines()
    assert frei[2:] == ["Choose one:", "• +50 to maximum Life", "• 10% reduced Mana Cost"]
    gewaehlt = TreeGraph._tooltip(m, {40: 778}).splitlines()
    assert gewaehlt[2:] == ["Effects:", "• +50 to maximum Life", "✓ 10% reduced Mana Cost"]
    vergeben = TreeGraph._tooltip(m, {41: 777}).splitlines()
    assert vergeben[3] == "• +50 to maximum Life (taken in another mastery)"
    assert TreeGraph._tooltip(b.nodes[12], {40: 778}).count("Effects") == 0   # kein Mastery
    # Das Bild kennt die Wahl des gezeigten Baums, und Strg+Umschalt+C nimmt
    # die Effekte mit.
    g = TreeGraph()
    g.set_tree(b)
    g.show_tree({"hashes": [10, 11, 12, 40], "mastery_effects": {"40": 778}}, "Marauder")
    assert g.choices == {40: 778}
    assert g.copy_text(40, full=True).splitlines() == [
        "Life Mastery (ID 40)", "Effects:", "• +50 to maximum Life", "✓ 10% reduced Mana Cost"]
    g.close()
