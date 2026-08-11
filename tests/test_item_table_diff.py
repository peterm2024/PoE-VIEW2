"""Tests für die Charakter-Refresh-Diff-Hervorhebung der ItemTableModel
(Peter 2026-08-01: geänderte Zeilen türkis, verschwundene Items grau und
durchgestrichen — ARCHITEKTUR.md §4.20)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from poe_view.api.models import Item
from poe_view.ui.item_table import _NAME_COL, ItemTableModel


def _item(item_id: str = "abc", name: str = "Chaos Orb") -> Item:
    return Item.model_validate({"id": item_id, "typeLine": name, "frameType": 5})


def test_unaffected_row_has_no_background_and_no_strikeout(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item()])
    idx = model.index(0, _NAME_COL)
    assert model.data(idx, Qt.ItemDataRole.BackgroundRole) is None
    assert model.data(idx, Qt.ItemDataRole.FontRole) is None
    assert model.data(idx, Qt.ItemDataRole.ForegroundRole) is not None  # normale Rarity-Farbe


def test_changed_row_gets_a_turquoise_background(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("abc")], changed_ids=frozenset({"abc"}))
    idx = model.index(0, _NAME_COL)
    assert model.data(idx, Qt.ItemDataRole.BackgroundRole) is not None


def test_a_gem_level_up_gets_green_instead_of_turquoise(qapp) -> None:
    """Peter, 2026-08-11: "die Markierungsfarbe für gelevelte Gems auf
    Grün ändern, dann erkennt man sofort dass ein Gem eine Stufe
    aufgestiegen ist." Anlass war eine Runde, in der Waffe und Schildhand
    als einzige Ausrüstung aufleuchteten — zu Recht, aber ohne dass man
    das der Farbe ansehen konnte."""
    model = ItemTableModel()
    model.set_items([_item("abc")], changed_ids=frozenset({"abc"}),
                    leveled_ids=frozenset({"abc"}))
    green = model.data(model.index(0, _NAME_COL), Qt.ItemDataRole.BackgroundRole)

    model.set_items([_item("abc")], changed_ids=frozenset({"abc"}))
    turquoise = model.data(model.index(0, _NAME_COL), Qt.ItemDataRole.BackgroundRole)

    assert green is not None and turquoise is not None
    assert green.color() != turquoise.color()


def test_removed_row_is_greyed_and_struck_through(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("abc")], removed_ids=frozenset({"abc"}))
    idx = model.index(0, _NAME_COL)
    font = model.data(idx, Qt.ItemDataRole.FontRole)
    assert isinstance(font, QFont) and font.strikeOut()
    # Grau statt der sonst hier greifenden Rarity-Farbe (Currency = "#b3a06a")
    brush = model.data(idx, Qt.ItemDataRole.ForegroundRole)
    assert brush is not None and brush.color().name() != "#b3a06a"


def test_removed_row_greying_applies_to_every_column_not_just_name(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("abc")], removed_ids=frozenset({"abc"}))
    from poe_view.ui.item_table import BASE_COL
    idx = model.index(0, BASE_COL)
    assert model.data(idx, Qt.ItemDataRole.ForegroundRole) is not None
    assert model.data(idx, Qt.ItemDataRole.FontRole).strikeOut()


def test_items_without_id_are_never_highlighted(qapp) -> None:
    """Ohne stabile Kennung lässt sich "geändert"/"verschwunden" nicht
    zuverlässig bestimmen (siehe MainWindow._diff_character_items) —
    das Model markiert so ein Item daher nie, selbst wenn sein (fehlender)
    Schlüssel zufällig in einer der Mengen auftauchen sollte."""
    model = ItemTableModel()
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})
    assert item.id is None
    model.set_items([item], changed_ids=frozenset({None}), removed_ids=frozenset({None}))
    idx = model.index(0, _NAME_COL)
    assert model.data(idx, Qt.ItemDataRole.BackgroundRole) is None
    assert model.data(idx, Qt.ItemDataRole.FontRole) is None


def test_resetting_items_without_diff_args_clears_previous_highlighting(qapp) -> None:
    """Beim Wechsel zurück zur Stash-Ansicht (set_items ohne changed_ids/
    removed_ids) darf keine Charakter-Diff-Färbung hängen bleiben."""
    model = ItemTableModel()
    model.set_items([_item("abc")], changed_ids=frozenset({"abc"}),
                    leveled_ids=frozenset({"abc"}))
    model.set_items([_item("abc")])
    idx = model.index(0, _NAME_COL)
    assert model.data(idx, Qt.ItemDataRole.BackgroundRole) is None
