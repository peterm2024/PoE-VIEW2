"""Settings-Dialog mit zwei Reitern (Peter, 2026-08-01):

- "External Tools": das konfigurierbare Rechtsklick-Menü ("Das
  Rechtsklick-Menü ist variabel... dann kann man z.B. das Wiki selber
  einbinden").
- "Columns": welche Item-Tabellen-Spalten sichtbar sind und in welcher
  Reihenfolge ("Wir haben ja alle möglichen Attribute pro Item... die
  Möglichkeit, die angezeigten Spalten einzustellen").

Bewusst schlichte Tabelle/Liste statt eigener Zeilen-Widgets — Peter ist
kein Python-Programmierer und bearbeitet hier nur Text/Häkchen/
Reihenfolge, keinen Code. Persistiert wird über ``main_window.py``
(QSettings), dieser Dialog kennt nur die reinen Datenlisten rein/raus."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from poe_view.ui.external_tools import ToolEntry

_COL_ENABLED, _COL_NAME, _COL_TEMPLATE = range(3)


class SettingsDialog(QDialog):
    def __init__(self, entries: list[ToolEntry], column_config: list[tuple[str, bool]],
                parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.resize(560, 400)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_tools_tab(entries), "External Tools")
        tabs.addTab(self._build_columns_tab(column_config), "Columns")
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
        layout.addWidget(QLabel("Rechtsklick-Menü für Items:"))

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Aktiv", "Name", "URL-Vorlage"])
        self._table.horizontalHeader().setSectionResizeMode(_COL_TEMPLATE, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for entry in entries:
            self._add_row(entry)
        layout.addWidget(self._table)

        layout.addWidget(QLabel(
            "Platzhalter {slug} wird durch den Item-Namen ersetzt "
            "(Leerzeichen -> Unterstrich), z. B. https://poedb.tw/us/{slug}"))

        row_buttons = QHBoxLayout()
        add_button = QPushButton("Hinzufügen")
        add_button.clicked.connect(lambda: self._add_row(ToolEntry("", "https://")))
        remove_button = QPushButton("Entfernen")
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
            "Sichtbare Spalten der Item-Tabelle und ihre Reihenfolge "
            "(Häkchen = sichtbar, Ziehen = Reihenfolge ändern):"))

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
