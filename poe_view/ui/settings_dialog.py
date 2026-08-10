"""Settings-Dialog mit drei Reitern (Peter, 2026-08-01):

- "External Tools": das konfigurierbare Rechtsklick-Menü ("Das
  Rechtsklick-Menü ist variabel... dann kann man z.B. das Wiki selber
  einbinden").
- "Columns": welche Item-Tabellen-Spalten sichtbar sind und in welcher
  Reihenfolge ("Wir haben ja alle möglichen Attribute pro Item... die
  Möglichkeit, die angezeigten Spalten einzustellen").
- "Zone Refresh": ob und über welchen Pfad PoE-VIEW2 Peters eigene
  Client.txt beobachtet, um beim Zonenwechsel gezielt die gerade offene
  Ansicht neu zu laden ("Erst nach Zonenwechsel gibt es einen Refresh").
  Standardmäßig AUS, Pfad muss Peter selbst eintragen — kein Rätselraten
  über Installationsorte.

Bewusst schlichte Tabelle/Liste statt eigener Zeilen-Widgets — Peter ist
kein Python-Programmierer und bearbeitet hier nur Text/Häkchen/
Reihenfolge, keinen Code. Persistiert wird über ``main_window.py``
(QSettings), dieser Dialog kennt nur die reinen Datenlisten/-werte
rein/raus.

**Texte auf Englisch**, wie die gesamte Oberfläche und die README —
Kommentare und Projektdoku bleiben deutsch (bewusste Trennung, siehe
README/ARCHITEKTUR, gleiche Regel wie in ``help_dialog.py``). Dieser
Dialog war bis 2026-08-05 die einzige Ausnahme: Reiter englisch, Titel
und sämtliche Beschriftungen deutsch. Aufgefallen ist das beim
Spielertest — für die Zielgruppe wäre der Dialog damit über weite
Strecken unlesbar gewesen. Ein Test hält die Grenze jetzt fest, sonst
verrutscht sie beim nächsten neuen Feld wieder."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from poe_view.services.zone_watcher import resolve_client_log_path
from poe_view.ui.external_tools import ToolEntry

_COL_ENABLED, _COL_NAME, _COL_TEMPLATE = range(3)


class SettingsDialog(QDialog):
    def __init__(self, entries: list[ToolEntry], column_config: list[tuple[str, bool]],
                zone_watcher_enabled: bool, zone_watcher_path: str,
                parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PoE-VIEW2 — Settings")
        self.resize(560, 400)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_tools_tab(entries), "External Tools")
        tabs.addTab(self._build_columns_tab(column_config), "Columns")
        tabs.addTab(self._build_zone_refresh_tab(zone_watcher_enabled, zone_watcher_path),
                    "Zone Refresh")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- Reiter "External Tools" ------------------------------------- #

    def _build_tools_tab(self, entries: list[ToolEntry]) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(
            "Right-click menu for items — add your own reference sites "
            "here.\nThe list is empty out of the box: PoE-VIEW2 "
            "deliberately ships without any third-party site."))

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Active", "Name", "URL template"])
        self._table.horizontalHeader().setSectionResizeMode(_COL_TEMPLATE, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for entry in entries:
            self._add_row(entry)
        layout.addWidget(self._table)

        layout.addWidget(QLabel(
            "The {slug} placeholder is replaced with the item name "
            "(spaces become underscores),\nfor example "
            "https://<your-site>/wiki/{slug}"))

        row_buttons = QHBoxLayout()
        add_button = QPushButton("Add")
        add_button.clicked.connect(lambda: self._add_row(ToolEntry("", "https://")))
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_selected_row)
        row_buttons.addWidget(add_button)
        row_buttons.addWidget(remove_button)
        row_buttons.addStretch(1)
        layout.addLayout(row_buttons)
        return tab

    def _add_row(self, entry: ToolEntry) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        checkbox_item = QTableWidgetItem()
        checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                               | Qt.ItemFlag.ItemIsSelectable)
        checkbox_item.setCheckState(Qt.CheckState.Checked if entry.enabled else Qt.CheckState.Unchecked)
        self._table.setItem(row, _COL_ENABLED, checkbox_item)
        self._table.setItem(row, _COL_NAME, QTableWidgetItem(entry.name))
        self._table.setItem(row, _COL_TEMPLATE, QTableWidgetItem(entry.url_template))

    def _remove_selected_row(self) -> None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        for row in sorted(rows, reverse=True):
            self._table.removeRow(row)

    def result_entries(self) -> list[ToolEntry]:
        """Nur Zeilen mit ausgefülltem Namen UND Vorlage — leere
        Neu-Zeilen (z. B. "Hinzufügen" geklickt, dann doch nicht befüllt)
        werden stillschweigend übersprungen statt kaputte Menüeinträge zu
        erzeugen."""
        entries = []
        for row in range(self._table.rowCount()):
            name = self._table.item(row, _COL_NAME).text().strip()
            template = self._table.item(row, _COL_TEMPLATE).text().strip()
            if not name or not template:
                continue
            enabled = self._table.item(row, _COL_ENABLED).checkState() == Qt.CheckState.Checked
            entries.append(ToolEntry(name, template, enabled))
        return entries

    # --- Reiter "Columns" ---------------------------------------------- #

    def _build_columns_tab(self, column_config: list[tuple[str, bool]]) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(
            "Columns of the item table and their order "
            "(tick = visible, drag to reorder):"))

        self._column_list = QListWidget()
        self._column_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for name, visible in column_config:
            item = QListWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked)
            self._column_list.addItem(item)
        layout.addWidget(self._column_list)
        return tab

    def result_column_config(self) -> list[tuple[str, bool]]:
        return [
            (self._column_list.item(row).text(),
             self._column_list.item(row).checkState() == Qt.CheckState.Checked)
            for row in range(self._column_list.count())
        ]

    # --- Reiter "Zone Refresh" ------------------------------------------ #

    def _build_zone_refresh_tab(self, enabled: bool, path: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(
            "Path of Exile records every zone change in its own Client.txt, "
            "along with vendor sales\nand item identification. PoE-VIEW2 only "
            "reads that file, which GGG permits. Watching it\nrefreshes the "
            "open stash tab or character at the moment new data actually "
            "appears,\ninstead of polling and hoping. Off by default — the "
            "path is yours to point at."))

        self._zone_enabled_check = QCheckBox(
            "Refresh the current view on zone changes, vendor sales and "
            "identifying")
        self._zone_enabled_check.setChecked(enabled)
        layout.addWidget(self._zone_enabled_check)

        path_row = QHBoxLayout()
        self._zone_path_edit = QLineEdit(path)
        self._zone_path_edit.setPlaceholderText(
            r"e.g. D:\SteamLibrary\steamapps\common\Path of Exile "
            r"(or the Client.txt itself)")
        self._zone_path_edit.textChanged.connect(self._update_zone_path_status)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_for_poe_folder)
        path_row.addWidget(self._zone_path_edit, stretch=1)
        path_row.addWidget(browse_button)
        layout.addLayout(path_row)

        self._zone_path_status = QLabel()
        layout.addWidget(self._zone_path_status)
        self._update_zone_path_status(path)

        layout.addStretch(1)
        return tab

    def _browse_for_poe_folder(self) -> None:
        start_dir = self._zone_path_edit.text().strip() or ""
        chosen = QFileDialog.getExistingDirectory(
            self, "Select the Path of Exile folder", start_dir)
        if chosen:
            self._zone_path_edit.setText(chosen)

    def _update_zone_path_status(self, path: str) -> None:
        resolved = resolve_client_log_path(path)
        if resolved is not None:
            self._zone_path_status.setText(f"✓ Found: {resolved}")
        elif path.strip():
            self._zone_path_status.setText("✗ No Client.txt found at this path")
        else:
            self._zone_path_status.setText("")

    def result_zone_watcher_config(self) -> tuple[bool, str]:
        return self._zone_enabled_check.isChecked(), self._zone_path_edit.text().strip()
