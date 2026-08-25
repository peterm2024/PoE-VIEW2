"""Das Album: durch die Mod-Sammlung blättern (§4.52, Stufe 3).

Peter, 2026-08-24: "Ich finde die Idee mit der eigenen Datenbank am
besten, hat etwas von einer Briefmarkensammlung: Einfach mal jedes Objekt
in der Hand gehalten zu haben und von PoE-VIEW kategorisiert und
eingetragen. Kann ja auch Spaß machen ;-)"

Die ersten beiden Stufen der Sammlung (aufschreiben, am Item anzeigen)
beantworten "wie gut ist DIESER Roll". Dieses Fenster beantwortet die
andere Frage, die eine Sammlung erst zur Sammlung macht: "was habe ich
eigentlich alles?" — durchsuchbar nach Text und Art, mit den vollen
Spannen je Liga und Rarität für den markierten Eintrag.

**Ein Schnappschuss, keine Live-Ansicht.** Die Sammlung wächst nebenbei
weiter, während das Fenster offen ist; es zeigt den Stand vom Öffnen. Ein
Fenster, das sich unter der Maus neu sortiert, wäre für Durchblättern
schlechter als eines, das sich beim nächsten Öffnen einfach neu befüllt.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPlainTextEdit, QSplitter,
                               QTableView, QVBoxLayout, QWidget)

from poe_view.api.models import (ENCHANT_MOD_FIELD, EXTRA_MOD_FIELDS,
                                 FRAME_TYPE_NAMES)
from poe_view.services.mod_collection import (LEGACY_LEAGUE, MAP_RARITY,
                                              UNKNOWN_RARITY, ModCollection,
                                              ModRecord, RaritySpan)

# Anzeigenamen der Mod-Arten. Eigene Tabelle statt einer aus
# ``csv_export.py`` übernommenen — die dortige ist auf Spaltenüberschriften
# zugeschnitten (``CraftedMods``), hier sind es Werte in einer Filter-Box.
KIND_LABELS = {
    "explicitMods": "Explicit",
    "implicitMods": "Implicit",
    ENCHANT_MOD_FIELD: "Enchant",
    "utilityMods": "Flask",
    "craftedMods": "Crafted",
    "fracturedMods": "Fractured",
    "veiledMods": "Veiled",
    "scourgeMods": "Scourge",
    "crucibleMods": "Crucible",
    "logbookMods": "Logbook",
    "ultimatumMods": "Ultimatum",
}
# Reihenfolge des Filter-Menüs: die häufigen zuerst (siehe ARCHITEKTUR
# §4.52, gemessen an Peters Bestand), Rest alphabetisch über EXTRA_MOD_FIELDS.
KIND_ORDER = ("explicitMods", "implicitMods", ENCHANT_MOD_FIELD, *EXTRA_MOD_FIELDS)


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def rarity_label(rarity: int) -> str:
    """Menschenlesbarer Name eines Raritäts-Topfs — inklusive der beiden
    Sonderwerte der Sammlung, die kein ``frameType`` sind."""
    if rarity == MAP_RARITY:
        return "Map"
    if rarity == UNKNOWN_RARITY:
        return "Unknown rarity"
    return FRAME_TYPE_NAMES.get(rarity, f"frameType {rarity}")


def league_label(league: str) -> str:
    return "Permanent leagues (Standard, SSF, …)" if league == LEGACY_LEAGUE else league


def _fmt_num(value: float) -> str:
    """``96.0`` -> ``"96"``, ``18.5`` -> ``"18.5"`` — ``g`` streicht
    genau die Nullen, die im Spiel auch nicht dastehen."""
    return f"{value:g}"


def format_span(span: RaritySpan) -> str:
    """Eine Spanne als Zeile: Sichtungen, Werte, Item-Stufen.

    Mehrere Zahlen (``Adds # to # Lightning Damage``) bekommen mehrere
    Teilspannen, in der Reihenfolge, in der sie in der Zeile stehen —
    dieselbe Reihenfolge, die ``mod_values`` liest."""
    teile = []
    for lo, hi in span.spread:
        teile.append(_fmt_num(lo) if lo == hi else f"{_fmt_num(lo)}–{_fmt_num(hi)}")
    werte = ", ".join(teile) if teile else "(no numbers)"
    zeile = f"seen {span.count}× — {werte}"
    if span.ilvl_high:
        zeile += f"  (iLvl {span.ilvl_low}–{span.ilvl_high})"
    return zeile


def format_record_detail(record: ModRecord) -> str:
    """Der volle Steckbrief eines Eintrags, für das Detail-Feld."""
    zeilen = [record.example or record.identity,
             f"{kind_label(record.kind)}  ·  seen {record.count}× in total",
             ""]
    for league in record.leagues:
        for rarity in sorted(record.spans[league]):
            span = record.spans[league][rarity]
            zeilen.append(f"{league_label(league)}  ·  {rarity_label(rarity)}")
            zeilen.append(f"    {format_span(span)}")
    return "\n".join(zeilen)


IDENTITY_COL, KIND_COL, COUNT_COL, EXAMPLE_COL = range(4)
COLUMNS = ("Mod", "Kind", "Seen", "Example")


class ModAlbumModel(QAbstractTableModel):
    """Reine Anzeige einer bereits fertigen Liste — die Sammlung selbst
    bleibt dumm gegenüber Qt (§mod_collection.py)."""

    def __init__(self, records: list[ModRecord]) -> None:
        super().__init__()
        self._records = records

    def record_at(self, row: int) -> ModRecord | None:
        return self._records[row] if 0 <= row < len(self._records) else None

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        record = self._records[index.row()]
        col = index.column()
        if col == IDENTITY_COL:
            return record.identity
        if col == KIND_COL:
            return kind_label(record.kind)
        if col == COUNT_COL:
            return record.count
        if col == EXAMPLE_COL:
            return record.example
        return None


class ModAlbumProxy(QSortFilterProxyModel):
    """Textsuche über ``setFilterFixedString`` (läuft gegen die
    Mod-Spalte), plus ein zweiter, unabhängiger Filter nach Art — zwei
    Bedingungen, die beide gelten müssen, deshalb kein einfacher
    ``setFilterKeyColumn`` allein."""

    def __init__(self) -> None:
        super().__init__()
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(IDENTITY_COL)
        self._kind = ""

    def set_kind_filter(self, kind: str) -> None:
        # begin/endFilterChange statt invalidateFilter — Letzteres ist seit
        # Qt 6.10 deprecated (Warnung in jedem Testlauf, siehe item_table.py).
        self.beginFilterChange()
        self._kind = kind
        self.endFilterChange()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        if self._kind:
            model = self.sourceModel()
            record = model.record_at(row)
            if record is None or record.kind != self._kind:
                return False
        return super().filterAcceptsRow(row, parent)


class ModAlbumDialog(QDialog):
    def __init__(self, collection: ModCollection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mod Collection")
        self.resize(760, 520)

        records = sorted(collection.records(), key=lambda r: r.identity)
        self._model = ModAlbumModel(records)
        self._proxy = ModAlbumProxy()
        self._proxy.setSourceModel(self._model)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        self._search.textChanged.connect(self._update_count_label)

        self._kind_combo = QComboBox()
        self._kind_combo.addItem("All kinds", "")
        seen_kinds = {record.kind for record in records}
        for kind in KIND_ORDER:
            if kind in seen_kinds:
                self._kind_combo.addItem(kind_label(kind), kind)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)

        self._count_label = QLabel()

        top_row = QHBoxLayout()
        top_row.addWidget(self._search, stretch=1)
        top_row.addWidget(self._kind_combo)
        top_row.addWidget(self._count_label)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(IDENTITY_COL, Qt.SortOrder.AscendingOrder)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        # Feste Startbreiten fuer Mod/Kind/Seen, der Rest geht an Example.
        # ``resizeColumnsToContents`` waere hier die falsche Wahl: Die
        # laengste Identitaet in Peters Bestand ist 381 Zeichen lang, und
        # danach richtet sich sonst die ganze Spalte.
        header.resizeSection(IDENTITY_COL, 260)
        header.resizeSection(KIND_COL, 70)
        header.resizeSection(COUNT_COL, 50)
        header.setSectionResizeMode(EXAMPLE_COL, QHeaderView.ResizeMode.Stretch)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("Select a mod to see every rarity and league "
                                        "it has been seen on.")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._table)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(splitter, stretch=1)

        self._update_count_label()

    def _on_kind_changed(self) -> None:
        self._proxy.set_kind_filter(self._kind_combo.currentData() or "")
        self._update_count_label()

    def _update_count_label(self) -> None:
        total = self._model.rowCount()
        shown = self._proxy.rowCount()
        self._count_label.setText(f"{shown} of {total}" if shown != total else str(total))

    def _on_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self._detail.setPlainText("")
            return
        record = self._model.record_at(self._proxy.mapToSource(current).row())
        self._detail.setPlainText(format_record_detail(record) if record else "")
