"""Tests für die Value-Spalte der ItemTableModel — Preis-Anzeige, Sortierung
und die "Schrott"-Abdimmung (ARCHITEKTUR.md §4.13)."""

from PySide6.QtCore import Qt

from poe_view.api.models import Item
from poe_view.api.ninja import PriceIndex
from poe_view.ui.item_table import (VALUE_COL, ItemTableModel,
                                    NUMERIC_SORT_ROLE, format_chaos_value)


def _item(name: str, stack: int | None = None) -> Item:
    payload = {"typeLine": name, "frameType": 5}
    if stack is not None:
        payload["stackSize"] = stack
    return Item.model_validate(payload)


def _index_with(**prices: float) -> PriceIndex:
    index = PriceIndex()
    index._simple.update(prices)
    return index


# --- format_chaos_value ---------------------------------------------------- #

def test_format_small_amount_as_chaos_with_one_decimal() -> None:
    assert format_chaos_value(0.3, None) == "0.3c"


def test_format_larger_amount_as_chaos_without_decimals() -> None:
    assert format_chaos_value(842, None) == "842c"


def test_format_switches_to_divine_once_worth_at_least_one() -> None:
    index = _index_with(**{"Divine Orb": 200.0})
    assert format_chaos_value(199.0, index) == "199c"
    assert format_chaos_value(200.0, index) == "1.0div"
    assert format_chaos_value(4_000.0, index) == "20div"


def test_format_without_price_index_stays_in_chaos_even_for_large_amounts() -> None:
    assert format_chaos_value(50_000, None) == "50,000c"


# --- ItemTableModel.value_at ------------------------------------------------ #

def test_value_at_multiplies_unit_price_by_stack_size(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Chaos Orb", stack=100)])
    model.set_price_index(_index_with(**{"Chaos Orb": 1.0}))
    assert model.value_at(0) == 100.0


def test_value_at_treats_missing_stack_as_one(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Headhunter")])
    model.set_price_index(_index_with(Headhunter=15_000.0))
    assert model.value_at(0) == 15_000.0


def test_value_at_none_when_no_price_index_set(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Chaos Orb")])
    assert model.value_at(0) is None


def test_value_at_none_when_item_has_no_known_price(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Some Rare Nobody Prices")])
    model.set_price_index(_index_with(**{"Chaos Orb": 1.0}))
    assert model.value_at(0) is None


# --- Display/Sort über data() ----------------------------------------------- #

def test_value_column_display_text_empty_when_unknown(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Unbekannt")])
    idx = model.index(0, VALUE_COL)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == ""


def test_value_column_shows_formatted_price(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Chaos Orb", stack=50)])
    model.set_price_index(_index_with(**{"Chaos Orb": 1.0}))
    idx = model.index(0, VALUE_COL)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "50c"


def test_value_column_sort_role_is_the_raw_number_not_the_formatted_text(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Divine Orb", stack=1), _item("Chaos Orb", stack=1)])
    model.set_price_index(_index_with(**{"Divine Orb": 200.0, "Chaos Orb": 1.0}))
    divine_sort = model.data(model.index(0, VALUE_COL), NUMERIC_SORT_ROLE)
    chaos_sort = model.data(model.index(1, VALUE_COL), NUMERIC_SORT_ROLE)
    assert divine_sort == 200.0
    assert chaos_sort == 1.0
    assert divine_sort > chaos_sort


def test_value_column_unknown_price_sorts_as_negative_infinity(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Unbekannt")])
    idx = model.index(0, VALUE_COL)
    assert model.data(idx, NUMERIC_SORT_ROLE) == float("-inf")


def test_set_price_index_updates_already_loaded_rows(qapp) -> None:
    """Preise treffen meist ASYNCHRON nach set_items() ein — die Spalte
    muss sich nachträglich befüllen, ohne die Items neu zu laden."""
    model = ItemTableModel()
    model.set_items([_item("Chaos Orb", stack=10)])
    assert model.value_at(0) is None

    model.set_price_index(_index_with(**{"Chaos Orb": 1.0}))

    assert model.value_at(0) == 10.0


def test_set_price_index_emits_data_changed_for_value_column(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Chaos Orb")])
    changed: list[tuple[int, int]] = []
    model.dataChanged.connect(lambda tl, br, roles: changed.append((tl.column(), br.column())))

    model.set_price_index(_index_with(**{"Chaos Orb": 1.0}))

    assert changed == [(VALUE_COL, VALUE_COL)]


# --- Junk-Dimming ------------------------------------------------------------ #

def test_low_value_item_gets_a_dimmed_foreground(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Portal Scroll")])
    model.set_price_index(_index_with(**{"Portal Scroll": 0.1}))
    idx = model.index(0, VALUE_COL)
    assert model.data(idx, Qt.ItemDataRole.ForegroundRole) is not None


def test_high_value_item_has_no_dimmed_foreground(qapp) -> None:
    model = ItemTableModel()
    model.set_items([_item("Headhunter")])
    model.set_price_index(_index_with(Headhunter=15_000.0))
    idx = model.index(0, VALUE_COL)
    assert model.data(idx, Qt.ItemDataRole.ForegroundRole) is None


def test_unknown_value_item_has_no_dimmed_foreground(qapp) -> None:
    """Leer heißt unbekannt, nicht wertlos — keine Einfärbung ohne Preis."""
    model = ItemTableModel()
    model.set_items([_item("Unbekannt")])
    idx = model.index(0, VALUE_COL)
    assert model.data(idx, Qt.ItemDataRole.ForegroundRole) is None
