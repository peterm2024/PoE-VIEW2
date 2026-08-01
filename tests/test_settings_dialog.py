"""Tests für den Settings-Dialog: Reiter "External Tools" (Peter,
2026-08-01: "Rechtsklick-Menü ist variabel... Settings-Dialog, in dem man
u.a. das Menü konfigurieren kann") und Reiter "Columns" (Peter,
2026-08-01: "die Möglichkeit, die angezeigten Spalten einzustellen")."""

from PySide6.QtCore import Qt

from poe_view.ui.external_tools import ToolEntry
from poe_view.ui.settings_dialog import SettingsDialog

_NO_COLUMNS: list[tuple[str, bool]] = []


def test_loads_the_given_entries_into_the_table(qapp) -> None:
    entries = [ToolEntry("PoEDB", "https://poedb.tw/us/{slug}"),
              ToolEntry("PoE Wiki", "https://www.poewiki.net/wiki/{slug}", enabled=False)]
    dialog = SettingsDialog(entries, _NO_COLUMNS)
    assert dialog.result_entries() == entries


def test_add_button_appends_an_empty_row_that_is_skipped_until_filled(qapp) -> None:
    dialog = SettingsDialog([], _NO_COLUMNS)
    dialog._add_row(ToolEntry("", "https://"))
    assert dialog.result_entries() == []


def test_remove_button_deletes_the_selected_row(qapp) -> None:
    entries = [ToolEntry("PoEDB", "https://poedb.tw/us/{slug}"),
              ToolEntry("PoE Wiki", "https://www.poewiki.net/wiki/{slug}")]
    dialog = SettingsDialog(entries, _NO_COLUMNS)
    dialog._table.selectRow(0)
    dialog._remove_selected_row()
    remaining = dialog.result_entries()
    assert len(remaining) == 1
    assert remaining[0].name == "PoE Wiki"


def test_unchecking_the_checkbox_disables_the_entry(qapp) -> None:
    dialog = SettingsDialog([ToolEntry("PoEDB", "https://poedb.tw/us/{slug}", enabled=True)],
                            _NO_COLUMNS)
    dialog._table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.result_entries()[0].enabled is False


def test_editing_name_and_template_cells_is_reflected_in_the_result(qapp) -> None:
    dialog = SettingsDialog([ToolEntry("Old Name", "https://old.test/{slug}")], _NO_COLUMNS)
    dialog._table.item(0, 1).setText("New Name")
    dialog._table.item(0, 2).setText("https://new.test/{slug}")
    result = dialog.result_entries()
    assert result[0].name == "New Name"
    assert result[0].url_template == "https://new.test/{slug}"


# --- Reiter "Columns": Sichtbarkeit + Reihenfolge (Peter, 2026-08-01) ---

def test_loads_the_given_column_config_into_the_list(qapp) -> None:
    config = [("Name", True), ("Type", False), ("Value", True)]
    dialog = SettingsDialog([], config)
    assert dialog.result_column_config() == config


def test_unchecking_a_column_hides_it_without_changing_order(qapp) -> None:
    dialog = SettingsDialog([], [("Name", True), ("Type", True)])
    dialog._column_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.result_column_config() == [("Name", True), ("Type", False)]


def test_reordering_the_list_changes_the_result_order(qapp) -> None:
    """Simuliert das Ergebnis eines Drag&Drop-Umsortierens: die Reihenfolge
    der QListWidgetItems bestimmt direkt die Ergebnis-Reihenfolge, ganz
    ohne die Drag-Geste selbst nachzubilden."""
    dialog = SettingsDialog([], [("Name", True), ("Type", True), ("Value", True)])
    item = dialog._column_list.takeItem(2)  # "Value"
    dialog._column_list.insertItem(0, item)
    assert dialog.result_column_config() == [("Value", True), ("Name", True), ("Type", True)]
