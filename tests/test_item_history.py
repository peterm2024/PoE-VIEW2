"""Tests für ItemHistoryModel — das kompakte Log kürzlich durchs
Charakter-Inventar gewanderter Items (Peter, 2026-08-02, ARCHITEKTUR.md §4.21)."""

from datetime import datetime, timezone

from PySide6.QtCore import Qt

from poe_view.api.models import Item
from poe_view.api.ninja import PriceIndex
from poe_view.ui.item_history import (BASE_COL, CHARACTER_COL, EVENT_COL,
                                      ICON_COL, NAME_COL, STACK_COL,
                                      TIME_COL, VALUE_COL, HistoryEntry,
                                      ItemHistoryModel)


def _item(name: str = "Chaos Orb", item_id: str = "1", stack: int | None = None,
         frame_type: int = 5) -> Item:
    payload = {"id": item_id, "typeLine": name, "baseType": name, "frameType": frame_type}
    if stack is not None:
        payload["stackSize"] = stack
    return Item.model_validate(payload)


def _entry(event="added", character="WitchOfPeter", **kwargs) -> HistoryEntry:
    return HistoryEntry(datetime(2026, 8, 2, 14, 30, 0, tzinfo=timezone.utc), event, character,
                        _item(**kwargs))


def test_columns_show_time_character_event_name_base_stack(qapp) -> None:
    model = ItemHistoryModel()
    model.set_entries([_entry(event="added", character="WitchOfPeter", stack=9)])

    def text(col: int) -> str:
        return model.data(model.index(0, col), Qt.ItemDataRole.DisplayRole)

    assert text(TIME_COL) == datetime(2026, 8, 2, 14, 30, tzinfo=timezone.utc)\
        .astimezone().strftime("%H:%M:%S")
    assert text(CHARACTER_COL) == "WitchOfPeter"
    assert text(EVENT_COL) == "↑"
    assert text(NAME_COL) == "Chaos Orb"
    assert text(BASE_COL) == "Chaos Orb"
    assert text(STACK_COL) == "9"


def test_removed_event_shows_the_down_arrow(qapp) -> None:
    model = ItemHistoryModel()
    model.set_entries([_entry(event="removed")])
    assert model.data(model.index(0, EVENT_COL), Qt.ItemDataRole.DisplayRole) == "↓"


def test_stack_column_shows_dash_for_non_stackable_items(qapp) -> None:
    model = ItemHistoryModel()
    model.set_entries([_entry(stack=None)])
    assert model.data(model.index(0, STACK_COL), Qt.ItemDataRole.DisplayRole) == "–"


def test_value_column_is_empty_without_a_price_index(qapp) -> None:
    model = ItemHistoryModel()
    model.set_entries([_entry()])
    assert model.data(model.index(0, VALUE_COL), Qt.ItemDataRole.DisplayRole) == ""


def test_value_column_uses_the_price_index_once_set(qapp) -> None:
    model = ItemHistoryModel()
    model.set_entries([_entry(stack=2)])
    index = PriceIndex()
    index._simple["Chaos Orb"] = 1.0
    model.set_price_index(index)
    assert model.data(model.index(0, VALUE_COL), Qt.ItemDataRole.DisplayRole) == "2.0c"


def test_newest_entry_first_matches_the_order_given(qapp) -> None:
    """Die Anzeige-Reihenfolge liegt beim Aufrufer (MainWindow hängt neue
    Einträge per ``appendleft`` vorn an) — das Model zeigt nur, was ihm
    übergeben wird."""
    model = ItemHistoryModel()
    newest = _entry(item_id="new")
    oldest = _entry(item_id="old")
    model.set_entries([newest, oldest])
    assert model.entry_at(0).item.id == "new"
    assert model.entry_at(1).item.id == "old"


def test_entry_at_returns_none_out_of_range(qapp) -> None:
    model = ItemHistoryModel()
    assert model.entry_at(0) is None


def test_icon_requester_is_called_for_entries_missing_a_pixmap(qapp) -> None:
    requested = []
    model = ItemHistoryModel(icon_requester=requested.append)
    item = _item()
    item.icon = "http://example/icon.png"
    model.set_entries([HistoryEntry(datetime.now(timezone.utc), "added", "Char", item)])
    assert requested == ["http://example/icon.png"]


def test_set_icon_updates_the_pixmap_cache(qapp) -> None:
    from PySide6.QtGui import QPixmap
    model = ItemHistoryModel()
    item = _item()
    item.icon = "http://example/icon.png"
    model.set_entries([HistoryEntry(datetime.now(timezone.utc), "added", "Char", item)])
    pixmap = QPixmap(4, 4)
    model.set_icon("http://example/icon.png", pixmap)
    assert model.pixmap_for(item) is not None


def test_row_count_matches_entry_count(qapp) -> None:
    model = ItemHistoryModel()
    model.set_entries([_entry(item_id="1"), _entry(item_id="2")])
    assert model.rowCount() == 2
