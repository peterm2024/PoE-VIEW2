"""Tests für die Tab-Herkunftsspalte der ItemTableModel."""

from PySide6.QtCore import Qt

from poe_view.api.models import Item
from poe_view.ui.item_table import ItemTableModel


def make_item(name: str) -> Item:
    return Item.model_validate({"typeLine": name})


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
