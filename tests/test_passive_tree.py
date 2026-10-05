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
