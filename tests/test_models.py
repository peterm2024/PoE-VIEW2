"""Tests für die Datenmodelle — v. a. die Gem-Property-Extraktion
(Level/Quality haben keine festen JSON-Keys) und den rekursiven Stash-Baum.
Die JSON-Strukturen entsprechen den in docs/api-notes/ggg-api.md
festgehaltenen Beobachtungen.
"""

from poe_view.api.models import (Character, Item, StashTab, dominant_category,
                                 gem_level, gem_quality, get_property_value,
                                 item_category)


def test_max_links_is_the_largest_socket_group() -> None:
    item = Item.model_validate({"sockets": [
        {"group": 0, "attr": "I", "sColour": "B"},
        {"group": 0, "attr": "S", "sColour": "R"},
        {"group": 1, "attr": "D", "sColour": "G"},
    ]})
    assert item.max_links == 2


def test_max_links_is_zero_without_sockets() -> None:
    assert Item.model_validate({}).max_links == 0


def test_max_links_six_link() -> None:
    item = Item.model_validate({"sockets": [{"group": 0} for _ in range(6)]})
    assert item.max_links == 6

GEM_JSON = {
    "id": "abc123",
    "name": "",
    "typeLine": "Awakened Multistrike Support",
    "icon": "https://web.poecdn.com/gen/image/x.png",
    "frameType": 4,
    "corrupted": True,
    "properties": [
        {"name": "Level", "values": [["5 (Max)", 0]]},
        {"name": "Quality", "values": [["+20%", 1]]},
        {"name": "Mana Multiplier", "values": [["150%", 0]]},
    ],
}


def test_gem_properties_from_nested_array() -> None:
    item = Item.model_validate(GEM_JSON)
    assert gem_level(item) == "5"
    assert gem_quality(item) == "+20%"
    assert get_property_value(item, "Mana Multiplier") == "150%"
    assert get_property_value(item, "gibt es nicht") is None


def test_display_name_falls_back_to_typeline() -> None:
    item = Item.model_validate(GEM_JSON)
    assert item.display_name == "Awakened Multistrike Support"
    assert item.rarity == "Gem"


def test_stash_tree_recursive_with_colour() -> None:
    data = {
        "id": "7dd8293e2a", "name": "Map", "type": "Folder", "index": 1,
        "metadata": {"folder": True, "colour": "7c5436"},
        "children": [
            {"id": "5980220058", "folder": "7dd8293e2a", "name": "$",
             "type": "CurrencyStash", "index": 2, "metadata": {"colour": "ffaa00"}},
        ],
    }
    tab = StashTab.model_validate(data)
    assert tab.is_folder
    assert tab.colour == "#7c5436"          # API liefert Hex ohne '#'
    assert tab.children[0].type == "CurrencyStash"
    assert tab.children[0].folder == "7dd8293e2a"
    assert not tab.children[0].is_folder


def test_character_class_alias() -> None:
    char = Character.model_validate(
        {"name": "WitchOfPeter", "class": "Occultist", "level": 91, "league": "Settlers"})
    assert char.class_ == "Occultist"


def test_unknown_fields_are_kept() -> None:
    """extra='allow': API-Erweiterungen dürfen nichts kaputt machen."""
    item = Item.model_validate({**GEM_JSON, "brandNewField": {"x": 1}})
    assert item.brandNewField == {"x": 1}


def test_explicit_mods_normalizes_description_objects() -> None:
    """Regression (Allflame-Liga): GGG liefert bei manchen
    Items (u. a. Currency-Beschreibungstexten) Mod-Einträge nicht mehr als
    reinen String, sondern als {"description": "..."}-Objekt — sonst würde
    der ganze Stash-Tab mit einem pydantic-ValidationError abbrechen."""
    item = Item.model_validate({
        "typeLine": "Orb of Transmutation",
        "frameType": 5,
        "explicitMods": [{"description": "Upgrades a normal item to a random rarity"}],
        "implicitMods": ["Ganz normaler String-Mod"],
    })
    assert item.explicitMods == ["Upgrades a normal item to a random rarity"]
    assert item.implicitMods == ["Ganz normaler String-Mod"]


def test_explicit_mods_plain_strings_still_work() -> None:
    item = Item.model_validate({"typeLine": "Map", "frameType": 0,
                                "explicitMods": ["Area contains an additional Boss"]})
    assert item.explicitMods == ["Area contains an additional Boss"]


def test_stash_display_name_from_real_special_tab_structures() -> None:
    """Strukturen aus echten Rohdaten (Nutzer, 2026-07-09) — nicht aus der Doku.

    Map-Kinder: map.name enthält den Tier bereits ("Map (Tier 6)"), das
    name-Feld ist entweder wertlos ("1") oder ein GGG-Suffix mit führendem
    Leerzeichen (" (Remove-only)"). Unique-Kinder: gar kein Name, nur
    metadata.items (Anzahl).
    """
    # Normaler Tab: name gewinnt, metadata.map wäre irreführend
    named = StashTab.model_validate({"id": "a", "name": "Currency 1", "type": "CurrencyStash",
                                     "metadata": {}})
    assert named.display_name == "Currency 1"

    # Map-Kind der aktiven Liga: name="1" ist wertlos → nur map.name
    map_child = StashTab.model_validate({"id": "b", "name": "1", "parent": "m1",
                                         "type": "MapStash",
                                         "metadata": {"items": 8,
                                                      "map": {"section": "tier6",
                                                              "name": "Map (Tier 6)",
                                                              "index": 0}}})
    assert map_child.display_name == "Map (Tier 6)"
    assert map_child.parent == "m1"

    # Map-Kind einer Remove-only-Liga: name=" (Remove-only)" ist Suffix → anhängen
    ro_child = StashTab.model_validate({"id": "c", "name": " (Remove-only)", "parent": "m1",
                                        "type": "MapStash",
                                        "metadata": {"items": 2,
                                                     "map": {"section": "unique",
                                                             "name": "Death and Taxes",
                                                             "index": 0}}})
    assert ro_child.display_name == "Death and Taxes (Remove-only)"

    # Unique-Kind: völlig namenlos → Typ (Item-Anzahl steht in der eigenen
    # Baum-Spalte, nicht mehr im Namen)
    uniq_child = StashTab.model_validate({"id": "d", "name": "", "parent": "u1",
                                          "type": "UniqueStash",
                                          "metadata": {"items": 5}})
    assert uniq_child.display_name == "UniqueStash"

    bare = StashTab.model_validate({"id": "c0ffee42", "type": "UniqueStash", "metadata": {}})
    assert bare.display_name == "UniqueStash"


def test_stash_display_name_uses_stamped_category() -> None:
    """Nach dem ersten Item-Load stempelt MainWindow die dominante Kategorie
    als poeview_category — der Anzeigename nutzt sie statt des Typs."""
    tab = StashTab.model_validate({"id": "d", "name": "", "parent": "u1",
                                   "type": "UniqueStash",
                                   "metadata": {"items": 5, "poeview_category": "Ring"}})
    assert tab.display_name == "Ring"


def _item(base_type: str, properties: list | None = None) -> Item:
    return Item.model_validate({"typeLine": base_type, "baseType": base_type,
                                "frameType": 3, "properties": properties or []})


def test_item_category_weapon_from_first_property() -> None:
    """Waffen: Die API nennt die Item-Klasse als erste Property (ohne Werte)."""
    axe = _item("Vaal Axe", properties=[
        {"name": "Two Handed Axe", "values": []},
        {"name": "Quality", "values": [["+20%", 1]]},
    ])
    assert item_category(axe) == "Two Handed Axe"


def test_item_category_from_basetype_suffix() -> None:
    assert item_category(_item("Amethyst Ring")) == "Ring"
    assert item_category(_item("Divine Life Flask")) == "Flask"
    assert item_category(_item("Stygian Vise")) == "Belt"
    assert item_category(_item("Rustic Sash")) == "Belt"
    assert item_category(_item("Titan Greaves")) == "Boots"
    assert item_category(_item("Hubris Circlet")) == "Helmet"
    assert item_category(_item("Pinnacle Tower Shield")) == "Shield"
    assert item_category(_item("Large Cluster Jewel")) == "Jewel"


def test_item_category_ringmail_is_body_armour_not_ring() -> None:
    """endswith statt Substring: "Full Ringmail" enthält "Ring", IST aber keiner."""
    ringmail = _item("Full Ringmail", properties=[
        {"name": "Armour", "values": [["104", 0]]},
    ])
    assert item_category(ringmail) == "Body Armour"


def test_item_category_unknown_returns_none() -> None:
    assert item_category(_item("Mirror of Kalandra")) is None


def test_dominant_category_majority_vote() -> None:
    items = [_item("Amethyst Ring"), _item("Two-Stone Ring"), _item("Divine Life Flask")]
    assert dominant_category(items) == "Ring"
    assert dominant_category([]) is None
    assert dominant_category([_item("Mirror of Kalandra")]) is None


# --- requirements: Anf.Lvl / Str / Dex / Int ------------- #

def test_req_level_and_attributes_from_real_structure() -> None:
    """Echte API-Struktur (Cache-Analyse 2026-07-10, "Vortex Bane"):
    Level/Dex/Int im requirements-Array — GGG liefert das längst mit,
    PoEDB o. Ä. ist unnötig."""
    from poe_view.api.models import req_attribute, req_level
    item = Item.model_validate({"typeLine": "Gutting Knife", "requirements": [
        {"name": "Level", "values": [["56", 0]], "displayMode": 0, "type": 62},
        {"name": "Dex", "values": [["113", 0]], "displayMode": 1, "type": 64},
        {"name": "Int", "values": [["78", 0]], "displayMode": 1, "type": 65},
    ]})
    assert req_level(item) == "56"
    assert req_attribute(item, "Dex") == "113"
    assert req_attribute(item, "Int") == "78"
    assert req_attribute(item, "Str") is None


def test_req_attribute_accepts_long_names() -> None:
    """Die API nennt Attribute mal "Str", mal "Strength" — beides beobachtet
    (Vaal Greaves: "Strength", Lunaris Circlet: "Intelligence")."""
    from poe_view.api.models import req_attribute
    item = Item.model_validate({"typeLine": "Vaal Greaves", "requirements": [
        {"name": "Strength", "values": [["117", 0]], "displayMode": 1},
    ]})
    assert req_attribute(item, "Str") == "117"


def test_req_level_ignores_heist_job_level() -> None:
    """Heist-Ausrüstung trägt "Level {0} in {1}" ("Level 2 in Any Job") —
    das ist ein Job-Level, kein Charakter-Level (exakter Namensvergleich)."""
    from poe_view.api.models import req_level
    item = Item.model_validate({"typeLine": "Focal Stone", "requirements": [
        {"name": "Level {0} in {1}", "values": [["2", 0], ["Any Job", 0]],
         "displayMode": 3},
    ]})
    assert req_level(item) is None


def test_item_without_requirements_returns_none() -> None:
    from poe_view.api.models import req_attribute, req_level
    item = Item.model_validate({"typeLine": "Chaos Orb"})
    assert req_level(item) is None
    assert req_attribute(item, "Str") is None
