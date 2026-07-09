"""Item-Tabelle: Model/View mit Sortierung und Live-Filter.

LabVIEW-Äquivalent: Multicolumn Listbox — hier sauberer als
QAbstractTableModel + QSortFilterProxyModel (Sortieren/Filtern kostenlos).

Icons werden asynchron nachgeladen: das Model meldet fehlende URLs über den
``icon_requester``-Callback (MainWindow → FetchIconJob) und bekommt die
fertigen Pixmaps via ``set_icon`` zurück.

Die Tab-Spalte trägt den Namen des Herkunfts-Tabs pro Item. Bei Auswahl
eines einzelnen Tabs ist sie redundant und wird vom MainWindow automatisch
ausgeblendet; in Aggregat-Ansichten ("Alle Tabs laden", Klick auf einen
Spezial-Tab-Elternknoten) wird sie automatisch eingeblendet — dort ordnet
sie Items ihrem Fach zu ("Map (Tier 1)", Nutzer-Feedback).

Die Mods-Spalte zeigt die explicitMods (v. a. Map-Modifikatoren,
Nutzer-Feedback); der Live-Filter durchsucht sie mit. Alle übrigen Spalten
sind per Rechtsklick auf den Header an-/abwählbar (MainWindow), "Typ" ist
standardmäßig aus — die Rarity steckt bereits in der Namensfarbe.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (QAbstractTableModel, QModelIndex,
                            QSortFilterProxyModel, Qt)
from PySide6.QtGui import QBrush, QColor, QPixmap

from poe_view.api.models import Item, gem_level, gem_quality
from poe_view.ui.theme import RARITY_COLORS

COLUMNS = ("Icon", "Tab", "Name", "Typ", "Level", "Qual.", "Stack", "iLvl", "Mods")
ICON_COL = 0
TAB_COL = 1
_NAME_COL = 2
_NUMERIC_FROM_COL = 4  # Level, Qual., Stack, iLvl
MODS_COL = 8           # Mods (v. a. Maps) — linksbündig, nicht numerisch


class ItemTableModel(QAbstractTableModel):
    def __init__(self, icon_requester: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self._items: list[Item] = []
        self._sources: list[str] = []         # Tab-Name pro Item (parallel zu _items)
        self._rows: list[tuple] = []          # vorgerechnete Anzeigewerte
        self._pixmaps: dict[str, QPixmap] = {}
        self._requested: set[str] = set()
        self._icon_requester = icon_requester

    # --- Daten setzen -------------------------------------------------- #

    def set_items(self, items: list[Item], sources: list[str] | None = None) -> None:
        """``sources[i]`` ist der Tab-Name von ``items[i]``. Ohne Angabe leer."""
        self.beginResetModel()
        self._items = items
        self._sources = sources if sources is not None else [""] * len(items)
        self._rows = [self._precompute(item) for item in items]
        self.endResetModel()
        if self._icon_requester:
            for item in items:
                if item.icon and item.icon not in self._pixmaps \
                        and item.icon not in self._requested:
                    self._requested.add(item.icon)
                    self._icon_requester(item.icon)

    @staticmethod
    def _precompute(item: Item) -> tuple:
        return (item.display_name, item.rarity, gem_level(item) or "–",
                gem_quality(item) or "–",
                str(item.stackSize) if item.stackSize else "–",
                str(item.ilvl) if item.ilvl else "–",
                " · ".join(item.explicitMods))  # v. a. Map-Modifikatoren

    def item_at(self, row: int) -> Item | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def source_at(self, row: int) -> str:
        return self._sources[row] if 0 <= row < len(self._sources) else ""

    def set_icon(self, url: str, pixmap: QPixmap) -> None:
        self._pixmaps[url] = pixmap
        for row, item in enumerate(self._items):
            if item.icon == url:
                idx = self.index(row, ICON_COL)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    def pixmap_for(self, item: Item) -> QPixmap | None:
        return self._pixmaps.get(item.icon)

    # --- Qt-Model-API --------------------------------------------------- #

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return "" if section == ICON_COL else COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role):
        item = self._items[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == TAB_COL:
                return self._sources[index.row()] or "–"
            if col > TAB_COL:
                return self._rows[index.row()][col - 2]
        if role == Qt.ItemDataRole.ToolTipRole and col == MODS_COL:
            # Mods können lang werden — Tooltip zeigt sie zeilenweise komplett.
            return "\n".join(item.explicitMods) or None
        if role == Qt.ItemDataRole.DecorationRole and col == ICON_COL:
            pm = self._pixmaps.get(item.icon)
            if pm:
                return pm.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        if role == Qt.ItemDataRole.ForegroundRole and col == _NAME_COL:
            colour = RARITY_COLORS.get(item.frameType)
            if colour:
                return QBrush(QColor(colour))
        if role == Qt.ItemDataRole.TextAlignmentRole and _NUMERIC_FROM_COL <= col < MODS_COL:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class ItemFilterProxy(QSortFilterProxyModel):
    """Filtert lokal über Name + Typ + Tab — kostet bewusst keine API-Calls."""

    def __init__(self) -> None:
        super().__init__()
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        pattern = self.filterRegularExpression().pattern()
        if not pattern:
            return True
        model: ItemTableModel = self.sourceModel()
        item = model.item_at(row)
        if item is None:
            return True
        haystack = (f"{item.display_name} {item.typeLine} {item.baseType} "
                   f"{item.rarity} {model.source_at(row)} "
                   f"{' '.join(item.explicitMods)}")  # Maps nach Mods filtern
        return pattern.lower() in haystack.lower()
