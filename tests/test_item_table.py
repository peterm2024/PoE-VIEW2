"""Tests für die Tab-Herkunfts- und Mods-Spalte der ItemTableModel."""

from PySide6.QtCore import Qt

from poe_view.api.models import Item
from poe_view.ui.item_table import MODS_COL, ItemFilterProxy, ItemTableModel


def make_item(name: str, mods: list[str] | None = None) -> Item:
    return Item.model_validate({"typeLine": name, "explicitMods": mods or []})


def test_tab_column_shows_given_source(qapp) -> None:
    model = ItemTableModel()
    model.set_items([make_item("Chaos Orb"), make_item("Divine Orb")],
                    ["Currency 1", "Currency 2"])
    assert model.source_at(0) == "Currency 1"
    assert model.source_at(1) == "Currency 2"
    idx = model.index(0, 1)  # Tab-Spalte
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "Currency 1"


def test_missing_source_falls_back_to_dash(qapp) -> None:
    model = ItemTableModel()
    model.set_items([make_item("Chaos Orb")])  # sources=None
    idx = model.index(0, 1)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "–"


def test_name_column_unaffected_by_tab_column_insertion(qapp) -> None:
    model = ItemTableModel()
    model.set_items([make_item("Chaos Orb")], ["Currency 1"])
    idx = model.index(0, 2)  # Name-Spalte
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "Chaos Orb"


def test_mods_column_joins_explicit_mods(qapp) -> None:
    """Nutzer-Feedback: gerade bei Maps sind die Modifikatoren interessant."""
    model = ItemTableModel()
    map_item = make_item("Beach Map", mods=["Monsters deal 90% extra Damage as Fire",
                                            "Players are Cursed with Vulnerability"])
    model.set_items([map_item, make_item("Chaos Orb")], ["Maps", "Currency"])

    idx = model.index(0, MODS_COL)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == \
        "Monsters deal 90% extra Damage as Fire · Players are Cursed with Vulnerability"
    # Tooltip zeigt die Mods zeilenweise komplett (Spalte kann abschneiden)
    assert model.data(idx, Qt.ItemDataRole.ToolTipRole) == \
        "Monsters deal 90% extra Damage as Fire\nPlayers are Cursed with Vulnerability"
    assert model.data(model.index(1, MODS_COL), Qt.ItemDataRole.DisplayRole) == ""


def test_filter_matches_explicit_mods(qapp) -> None:
    model = ItemTableModel()
    model.set_items([make_item("Beach Map", mods=["Area is Beyond-touched"]),
                     make_item("Dunes Map")], ["Maps", "Maps"])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)

    proxy.setFilterFixedString("beyond")

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 2), Qt.ItemDataRole.DisplayRole) == "Beach Map"
