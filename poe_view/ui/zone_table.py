"""Die Zonen-Tabelle: jedes je betretene Gebiet mit seinem Monsterlevel.

Peter, 2026-09-26: "Außerdem hätte ich gerne dann einen Menüpunkt
'Zones', wo eine Tabelle öffnet, unterteilt nach Story, Map und
Special-Maps, wo alle Zonen aufgeführt werden und deren Monster-Level.
[...] Die Zonen sollte man auch als csv exportieren können."

Die Daten kommen aus ``services/zone_catalog`` (dort steht, warum aus
der Client.txt und nicht aus einer mitgelieferten Liste). Diese Datei
ist nur die Anzeige.

**Warum eine Gruppen-Box und keine vier Abschnitte untereinander:** Eine
sortierbare Tabelle verträgt keine Zwischenüberschriften — der erste
Klick auf einen Spaltenkopf würde sie zerreißen. Die Gruppe steht
deshalb als eigene Spalte (mitsortierbar) und zusätzlich als Filter über
der Tabelle. Voreinstellung ist "All", damit die Tabelle beim Öffnen
zeigt, was sie hat.
"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import (QModelIndex, QSortFilterProxyModel, Qt,
                            QAbstractTableModel)
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableView, QVBoxLayout, QWidget)

from poe_view.services.csv_export import sanitize_filename
from poe_view.services.experience import experience_multiplier
from poe_view.services.zone_catalog import CATEGORIES, ZoneRecord

# Spalten. "Monster Level" trägt bewusst den Namen, unter dem Peter
# gefragt hat, obwohl in der Client.txt "area level" steht: Für
# gewöhnliche Monster ist es dasselbe, und "Gebietslevel" beantwortet die
# Frage nicht, die jemand hat, der auf die Spalte schaut.
COLUMNS = ("Group", "Zone", "Monster Level", "Visits", "Last seen", "Area id")
_GROUP_COL, _NAME_COL, _LEVEL_COL, _VISITS_COL, _SEEN_COL, _ID_COL = range(6)

# Sortierrolle wie in der Item-Tabelle: "70–77" ist als Text sinnlos
# sortierbar, als Zahl (höchster gesehener Level) nicht.
NUMERIC_SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class ZoneTableModel(QAbstractTableModel):
    def __init__(self, records: list[ZoneRecord],
                 character_level: int = 0) -> None:
        super().__init__()
        self._records = records
        self._character_level = character_level

    def set_character_level(self, level: int) -> None:
        """Färbt die Level-Spalte danach ein, was dort noch zu holen ist
        — ohne Charakter bleibt sie ungefärbt."""
        if level == self._character_level:
            return
        self._character_level = level
        if self._records:
            self.dataChanged.emit(self.index(0, _LEVEL_COL),
                                  self.index(len(self._records) - 1, _LEVEL_COL))

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole \
                and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def record_at(self, row: int) -> ZoneRecord | None:
        return self._records[row] if 0 <= row < len(self._records) else None

    def data(self, index: QModelIndex, role):
        record = self._records[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return (record.category, record.name or "–", record.level_text,
                    str(record.visits), record.last_seen.replace("T", " "),
                    record.area_id)[col]
        if role == NUMERIC_SORT_ROLE:
            if col == _LEVEL_COL:
                return record.max_level
            if col == _VISITS_COL:
                return record.visits
            return self.data(index, Qt.ItemDataRole.DisplayRole).lower()
        if role == Qt.ItemDataRole.ToolTipRole and col == _LEVEL_COL:
            return self._level_tooltip(record)
        return None

    def _level_tooltip(self, record: ZoneRecord) -> str | None:
        """Alle gesehenen Level einzeln, plus was der Charakter dort noch
        bekäme. Die Zelle zeigt nur die Spanne — bei ``Delve_Main`` mit 34
        Werten ist das die einzig lesbare Form, die Einzelwerte sind aber
        genau das, was man bei einer Spanne wissen will."""
        if not record.levels:
            return None
        zeilen = ["Levels seen: " + ", ".join(str(x) for x in sorted(record.levels))]
        if self._character_level:
            anteil = experience_multiplier(self._character_level, record.max_level)
            zeilen.append(f"At character level {self._character_level}, level "
                          f"{record.max_level} yields {anteil:.1%} experience")
        return "\n".join(zeilen)


class ZoneFilterProxy(QSortFilterProxyModel):
    """Freitext über alle Spalten plus Gruppen-Vorwahl."""

    def __init__(self) -> None:
        super().__init__()
        self.setSortRole(NUMERIC_SORT_ROLE)
        self._group = ""
        # Den Suchtext selbst halten statt ihn aus
        # ``filterRegularExpression().pattern()`` zurückzulesen: Qt
        # maskiert dort jedes Sonderzeichen, aus "blood aqueduct" wird
        # "blood\ aqueduct" — und die Aufteilung in Wörter fände damit
        # nichts mehr. Dieselbe Lösung wie in ``ItemFilterProxy``.
        self._words: list[str] = []

    def setFilterFixedString(self, text: str) -> None:  # noqa: N802 (Qt-API)
        self._words = text.lower().split()
        super().setFilterFixedString(text)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        """Nach Gruppe sortieren heißt: Story, Map, Special, Rest — in
        DIESER Reihenfolge und innerhalb jeder Gruppe nach Level.

        Peter hat die Tabelle "unterteilt nach Story, Map und
        Special-Maps" bestellt. Eine sortierbare Tabelle verträgt keine
        Zwischenüberschriften (der erste Klick auf einen Spaltenkopf
        würde sie zerreißen), aber genau so sieht sie beim Öffnen aus.
        Alphabetisch sortiert stünde stattdessen "Map, Rest, Special,
        Story" da — richtig sortiert und trotzdem verkehrt herum."""
        if left.column() != _GROUP_COL:
            return super().lessThan(left, right)
        model = self.sourceModel()
        eins, zwei = model.record_at(left.row()), model.record_at(right.row())
        if eins is None or zwei is None:
            return super().lessThan(left, right)
        return self._group_key(eins) < self._group_key(zwei)

    @staticmethod
    def _group_key(record: ZoneRecord) -> tuple[int, int, str]:
        reihenfolge = (CATEGORIES.index(record.category)
                       if record.category in CATEGORIES else len(CATEGORIES))
        return (reihenfolge, record.max_level, record.name.lower())

    def set_group(self, group: str) -> None:
        # begin/endFilterChange statt invalidateFilter — Letzteres ist
        # seit Qt 6.10 deprecated und warnt in jedem Testlauf (dieselbe
        # Stelle wie in ``ItemFilterProxy.set_column_filter``).
        self.beginFilterChange()
        self._group = group
        self.endFilterChange()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        model = self.sourceModel()
        record = model.record_at(row)
        if record is None:
            return False
        if self._group and record.category != self._group:
            return False
        if not self._words:
            return True
        heuhaufen = f"{record.name} {record.area_id} {record.category} " \
                    f"{record.level_text}".lower()
        return all(wort in heuhaufen for wort in self._words)


def export_zones(path: str, records: list[ZoneRecord]) -> None:
    """Die Zonen als CSV — Semikolon und UTF-8-BOM wie beim Item-Export
    (``services/csv_export``), damit Excel sie unter deutscher Locale
    ohne Text-Import öffnet.

    Anders als die Anzeige schreibt die Datei die Level EINZELN
    (``68;70;77``) statt als Spanne: Eine Tabellenkalkulation soll damit
    rechnen können, und "70–77" ist dort Text."""
    with open(path, "w", encoding="utf-8-sig", newline="") as datei:
        schreiber = csv.writer(datei, delimiter=";")
        schreiber.writerow(["Group", "Zone", "Area id", "Monster level (min)",
                            "Monster level (max)", "All levels seen",
                            "Visits", "Last seen"])
        for record in records:
            schreiber.writerow([
                record.category, record.name, record.area_id,
                min(record.levels) if record.levels else "",
                record.max_level or "",
                " ".join(str(x) for x in sorted(record.levels)),
                record.visits, record.last_seen.replace("T", " "),
            ])


class ZoneTableDialog(QDialog):
    def __init__(self, records: list[ZoneRecord], parent: QWidget | None = None,
                 character_level: int = 0, account_name: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Zones")
        self.resize(820, 560)
        # Wie beim Mod-Album: Ein QDialog bekommt unter Windows sonst
        # keinen Maximieren-Knopf, und 381 Zeilen wollen Platz.
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinimizeButtonHint)
        self._account_name = account_name

        self._model = ZoneTableModel(records, character_level)
        self._proxy = ZoneFilterProxy()
        self._proxy.setSourceModel(self._model)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search zones…")
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        self._search.textChanged.connect(self._update_count)

        self._group_combo = QComboBox()
        self._group_combo.addItem("All groups", "")
        for gruppe in CATEGORIES:
            self._group_combo.addItem(gruppe, gruppe)
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)

        self._count_label = QLabel()
        self._export_button = QPushButton("💾 Export CSV")
        self._export_button.setToolTip(
            "Save the zones currently shown (filtered) as CSV")
        self._export_button.clicked.connect(self._export)

        kopf = QHBoxLayout()
        kopf.addWidget(self._group_combo)
        kopf.addWidget(self._search, 1)
        kopf.addWidget(self._count_label)
        kopf.addWidget(self._export_button)

        self._view = QTableView()
        self._view.setModel(self._proxy)
        self._view.setSortingEnabled(True)
        # Beim Öffnen die bestellte Unterteilung (siehe
        # ``ZoneFilterProxy.lessThan``); jeder Spaltenkopf schaltet um.
        self._view.sortByColumn(_GROUP_COL, Qt.SortOrder.AscendingOrder)
        self._view.verticalHeader().setVisible(False)
        self._view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        kopfzeile = self._view.horizontalHeader()
        kopfzeile.setSectionResizeMode(_NAME_COL, QHeaderView.ResizeMode.Stretch)
        kopfzeile.setSectionResizeMode(_ID_COL, QHeaderView.ResizeMode.Stretch)
        for spalte in (_GROUP_COL, _LEVEL_COL, _VISITS_COL, _SEEN_COL):
            kopfzeile.setSectionResizeMode(spalte,
                                           QHeaderView.ResizeMode.ResizeToContents)

        aufbau = QVBoxLayout(self)
        aufbau.addLayout(kopf)
        aufbau.addWidget(self._view)
        self._update_count()

    def _on_group_changed(self) -> None:
        self._proxy.set_group(self._group_combo.currentData() or "")
        self._update_count()

    def _update_count(self) -> None:
        sichtbar = self._proxy.rowCount()
        gesamt = self._model.rowCount()
        self._count_label.setText(
            f"{sichtbar} zones" if sichtbar == gesamt
            else f"{sichtbar} of {gesamt} zones")

    def visible_records(self) -> list[ZoneRecord]:
        """Was gerade in der Tabelle steht, in der Reihenfolge der
        Anzeige — der Export soll das speichern, was man sieht (dieselbe
        Regel wie beim Item-Export)."""
        gefunden = []
        for zeile in range(self._proxy.rowCount()):
            quelle = self._proxy.mapToSource(self._proxy.index(zeile, 0))
            record = self._model.record_at(quelle.row())
            if record is not None:
                gefunden.append(record)
        return gefunden

    def _export(self) -> None:
        vorschlag = sanitize_filename(f"zones-{self._account_name}", "zones")
        pfad, _ = QFileDialog.getSaveFileName(
            self, "Export zones as CSV", str(Path.home() / f"{vorschlag}.csv"),
            "CSV files (*.csv)")
        if not pfad:
            return
        try:
            export_zones(pfad, self.visible_records())
        except OSError as fehler:
            QMessageBox.warning(self, "Export failed", str(fehler))
