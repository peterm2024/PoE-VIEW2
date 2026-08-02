"""Tests für den Settings-Dialog: Reiter "External Tools" (frei
konfigurierbare Nachschlagewerke, ab Werk leer — Peter, 2026-08-02),
"Columns" (Peter, 2026-08-01: "die Möglichkeit, die angezeigten Spalten
einzustellen") und "Zone Refresh" (Peter, 2026-08-01: "Erst nach
Zonenwechsel gibt es einen Refresh")."""

from PySide6.QtCore import Qt

from poe_view.ui.external_tools import ToolEntry
from poe_view.ui.settings_dialog import SettingsDialog


def _dialog(entries=None, columns=None, zone_enabled=False, zone_path=""):
    return SettingsDialog(entries or [], columns or [], zone_enabled, zone_path)


def test_loads_the_given_entries_into_the_table(qapp) -> None:
    entries = [ToolEntry("Wiki A", "https://a.example.test/{slug}"),
              ToolEntry("Wiki B", "https://b.example.test/{slug}", enabled=False)]
    dialog = _dialog(entries=entries)
    assert dialog.result_entries() == entries


def test_add_button_appends_an_empty_row_that_is_skipped_until_filled(qapp) -> None:
    dialog = _dialog()
    dialog._add_row(ToolEntry("", "https://"))
    assert dialog.result_entries() == []


def test_remove_button_deletes_the_selected_row(qapp) -> None:
    entries = [ToolEntry("Wiki A", "https://a.example.test/{slug}"),
              ToolEntry("Wiki B", "https://b.example.test/{slug}")]
    dialog = _dialog(entries=entries)
    dialog._table.selectRow(0)
    dialog._remove_selected_row()
    remaining = dialog.result_entries()
    assert len(remaining) == 1
    assert remaining[0].name == "Wiki B"


def test_unchecking_the_checkbox_disables_the_entry(qapp) -> None:
    dialog = _dialog(entries=[ToolEntry("Wiki A", "https://a.example.test/{slug}", enabled=True)])
    dialog._table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.result_entries()[0].enabled is False


def test_editing_name_and_template_cells_is_reflected_in_the_result(qapp) -> None:
    dialog = _dialog(entries=[ToolEntry("Old Name", "https://old.test/{slug}")])
    dialog._table.item(0, 1).setText("New Name")
    dialog._table.item(0, 2).setText("https://new.test/{slug}")
    result = dialog.result_entries()
    assert result[0].name == "New Name"
    assert result[0].url_template == "https://new.test/{slug}"


# --- Reiter "Columns": Sichtbarkeit + Reihenfolge (Peter, 2026-08-01) ---

def test_loads_the_given_column_config_into_the_list(qapp) -> None:
    config = [("Name", True), ("Type", False), ("Value", True)]
    dialog = _dialog(columns=config)
    assert dialog.result_column_config() == config


def test_unchecking_a_column_hides_it_without_changing_order(qapp) -> None:
    dialog = _dialog(columns=[("Name", True), ("Type", True)])
    dialog._column_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.result_column_config() == [("Name", True), ("Type", False)]


def test_reordering_the_list_changes_the_result_order(qapp) -> None:
    """Simuliert das Ergebnis eines Drag&Drop-Umsortierens: die Reihenfolge
    der QListWidgetItems bestimmt direkt die Ergebnis-Reihenfolge, ganz
    ohne die Drag-Geste selbst nachzubilden."""
    dialog = _dialog(columns=[("Name", True), ("Type", True), ("Value", True)])
    item = dialog._column_list.takeItem(2)  # "Value"
    dialog._column_list.insertItem(0, item)
    assert dialog.result_column_config() == [("Value", True), ("Name", True), ("Type", True)]


# --- Reiter "Zone Refresh": Peter gibt den Pfad explizit an ------------- #

def test_loads_the_given_enabled_flag_and_path(qapp) -> None:
    dialog = _dialog(zone_enabled=True, zone_path=r"C:\PoE")
    assert dialog.result_zone_watcher_config() == (True, r"C:\PoE")


def test_defaults_to_disabled_with_an_empty_path(qapp) -> None:
    dialog = _dialog()
    assert dialog.result_zone_watcher_config() == (False, "")


def test_toggling_the_checkbox_is_reflected_in_the_result(qapp) -> None:
    dialog = _dialog(zone_enabled=False)
    dialog._zone_enabled_check.setChecked(True)
    assert dialog.result_zone_watcher_config()[0] is True


def test_editing_the_path_field_is_reflected_in_the_result(qapp) -> None:
    dialog = _dialog()
    dialog._zone_path_edit.setText(r"D:\Games\Path of Exile")
    assert dialog.result_zone_watcher_config()[1] == r"D:\Games\Path of Exile"


def test_status_label_confirms_a_resolvable_path(qapp, tmp_path) -> None:
    log = tmp_path / "Client.txt"
    log.write_text("", encoding="utf-8")
    dialog = _dialog()
    dialog._zone_path_edit.setText(str(tmp_path))
    assert "Gefunden" in dialog._zone_path_status.text()


def test_status_label_flags_an_unresolvable_path(qapp) -> None:
    dialog = _dialog()
    dialog._zone_path_edit.setText(r"Z:\does\not\exist")
    assert "Keine Client.txt" in dialog._zone_path_status.text()


def test_status_label_is_empty_for_an_empty_path(qapp) -> None:
    dialog = _dialog(zone_path=r"C:\PoE")
    dialog._zone_path_edit.setText("")
    assert dialog._zone_path_status.text() == ""
