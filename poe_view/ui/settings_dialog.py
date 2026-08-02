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
rein/raus."""

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
        self.setWindowTitle("Einstellungen")
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
            "Rechtsklick-Menü für Items — hier eigene Nachschlagewerke "
            "eintragen.\nAb Werk ist die Liste leer: PoE-VIEW2 bringt "
            "bewusst keine fremde Seite mit."))

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
            "(Leerzeichen -> Unterstrich),\nz. B. "
            "https://<deine-seite>/wiki/{slug}"))

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

    # --- Reiter "Zone Refresh" ------------------------------------------ #

    def _build_zone_refresh_tab(self, enabled: bool, path: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(
            "PoE schreibt Zonenwechsel in seine eigene Client.txt (rein "
            "lesend, von GGG erlaubt). Damit lässt sich die gerade "
            "geöffnete Truhe/der Charakter gezielt neu laden, statt auf "
            "gut Glück zu pollen."))

        self._zone_enabled_check = QCheckBox("Bei Zonenwechsel die aktuelle Ansicht neu laden")
        self._zone_enabled_check.setChecked(enabled)
        layout.addWidget(self._zone_enabled_check)

        path_row = QHBoxLayout()
        self._zone_path_edit = QLineEdit(path)
        self._zone_path_edit.setPlaceholderText(
            r"z. B. D:\SteamLibrary\steamapps\common\Path of Exile (oder direkt ...\logs\Client.txt)")
        self._zone_path_edit.textChanged.connect(self._update_zone_path_status)
        browse_button = QPushButton("Durchsuchen…")
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
        chosen = QFileDialog.getExistingDirectory(self, "Path-of-Exile-Ordner wählen", start_dir)
        if chosen:
            self._zone_path_edit.setText(chosen)

    def _update_zone_path_status(self, path: str) -> None:
        resolved = resolve_client_log_path(path)
        if resolved is not None:
            self._zone_path_status.setText(f"✓ Gefunden: {resolved}")
        elif path.strip():
            self._zone_path_status.setText("✗ Keine Client.txt an diesem Pfad gefunden")
        else:
            self._zone_path_status.setText("")

    def result_zone_watcher_config(self) -> tuple[bool, str]:
        return self._zone_enabled_check.isChecked(), self._zone_path_edit.text().strip()
