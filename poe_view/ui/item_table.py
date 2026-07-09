"""Item-Tabelle: Model/View mit Sortierung und Live-Filter.

LabVIEW-Äquivalent: Multicolumn Listbox — hier sauberer als
QAbstractTableModel + QSortFilterProxyModel (Sortieren/Filtern kostenlos).

Icons werden asynchron nachgeladen: das Model meldet fehlende URLs über den
``icon_requester``-Callback (MainWindow → FetchIconJob) und bekommt die
fertigen Pixmaps via ``set_icon`` zurück.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (QAbstractTableModel, QModelIndex,
                            QSortFilterProxyModel, Qt)
from PySide6.QtGui import QBrush, QColor, QPixmap

from poe_view.api.models import Item, gem_level, gem_quality
from poe_view.ui.theme import RARITY_COLORS

COLUMNS = ("", "Name", "Typ", "Level", "Qual.", "Stack", "iLvl")
_ICON_COL = 0
_NAME_COL = 1


class ItemTableModel(QAbstractTableModel):
    def __init__(self, icon_requester: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self._items: list[Item] = []
        self._rows: list[tuple] = []          # vorgerechnete Anzeigewerte
        self._pixmaps: dict[str, QPixmap] = {}
        self._requested: set[str] = set()
        self._icon_requester = icon_requester

    # --- Daten setzen -------------------------------------------------- #

    def set_items(self, items: list[Item]) -> None:
        self.beginResetModel()
        self._items = items
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
                str(item.ilvl) if item.ilvl else "–")

    def item_at(self, row: int) -> Item | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def set_icon(self, url: str, pixmap: QPixmap) -> None:
        self._pixmaps[url] = pixmap
        for row, item in enumerate(self._items):
            if item.icon == url:
                idx = self.index(row, _ICON_COL)
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
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role):
        item = self._items[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole and col > _ICON_COL:
            return self._rows[index.row()][col - 1]
        if role == Qt.ItemDataRole.DecorationRole and col == _ICON_COL:
            pm = self._pixmaps.get(item.icon)
            if pm:
                return pm.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        if role == Qt.ItemDataRole.ForegroundRole and col == _NAME_COL:
            colour = RARITY_COLORS.get(item.frameType)
            if colour:
                return QBrush(QColor(colour))
        if role == Qt.ItemDataRole.TextAlignmentRole and col >= 3:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class ItemFilterProxy(QSortFilterProxyModel):
    """Filtert lokal über Name + Typ — kostet bewusst keine API-Calls."""

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
        haystack = f"{item.display_name} {item.typeLine} {item.baseType} {item.rarity}"
        return pattern.lower() in haystack.lower()
