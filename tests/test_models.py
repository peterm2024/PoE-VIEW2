"""Tests für die Datenmodelle — v. a. die Gem-Property-Extraktion
(Level/Quality haben keine festen JSON-Keys) und den rekursiven Stash-Baum.
Die JSON-Strukturen entsprechen den Beobachtungen aus dem LabVIEW-Test-VI
(docs/api-notes/labview-test-vi.md).
"""

from poe_view.api.models import (Character, Item, StashTab, gem_level,
                                 gem_quality, get_property_value)

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
