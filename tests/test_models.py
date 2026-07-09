"""Tests für die Datenmodelle — v. a. die Gem-Property-Extraktion
(Level/Quality haben keine festen JSON-Keys) und den rekursiven Stash-Baum.
Die JSON-Strukturen entsprechen den Beobachtungen aus dem LabVIEW-Test-VI
(docs/api-notes/labview-test-vi.md).
"""

from poe_view.api.models import (Character, Item, StashTab, dominant_category,
                                 gem_level, gem_quality, get_property_value,
                                 item_category)

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
    assert tab.colour == "#7c5436"          # API liefert Hex OHNE '#'
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


def test_stash_display_name_from_real_special_tab_structures() -> None:
    """Strukturen aus ECHTEN Rohdaten (Nutzer, 2026-07-09) — nicht aus der Doku.

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

    # Unique-Kind: völlig namenlos → Typ + Item-Anzahl (unterscheidbar)
    uniq_child = StashTab.model_validate({"id": "d", "name": "", "parent": "u1",
                                          "type": "UniqueStash",
                                          "metadata": {"items": 5}})
    assert uniq_child.display_name == "UniqueStash (5 Items)"

    bare = StashTab.model_validate({"id": "c0ffee42", "type": "UniqueStash", "metadata": {}})
    assert bare.display_name == "UniqueStash"


def test_stash_display_name_uses_stamped_category() -> None:
    """Nach dem ersten Item-Load stempelt MainWindow die dominante Kategorie
    als poeview_category — der Anzeigename nutzt sie statt des Typs."""
    tab = StashTab.model_validate({"id": "d", "name": "", "parent": "u1",
                                   "type": "UniqueStash",
                                   "metadata": {"items": 5, "poeview_category": "Ring"}})
    assert tab.display_name == "Ring (5 Items)"


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
