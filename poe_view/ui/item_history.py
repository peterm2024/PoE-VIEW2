"""Kompaktes Log kürzlich durchs Charakter-Inventar gewanderter Items
(Peter, 2026-08-02: "eine Liste mit den letzten 120 Items, ... damit du
nochmal kurz nachschauen kannst, was du gerade in die Truhe getan hast
oder verkauft hast oder gehandelt hast").

Bewusst ein EIGENES, schlankes Spaltenformat statt Wiederverwendung von
``ItemTableModel`` — ein Log-Eintrag hat andere Bedürfnisse als eine
Bestandsanzeige (Zeitpunkt, Ereignistyp und Charakter sind Pflicht,
Tab/Position dagegen bedeutungslos, siehe ARCHITEKTUR.md §4.21). Die
Diff-Erkennung selbst (welches Item ist neu/verschwunden) liegt in
``MainWindow._diff_character_items`` — dieses Modul kennt nur fertige
``HistoryEntry``-Objekte und wie man sie anzeigt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QPixmap

from poe_view.api.models import Item
from poe_view.api.ninja import PriceIndex
from poe_view.ui.item_table import format_chaos_value
from poe_view.ui.theme import RARITY_COLORS

HistoryEventType = Literal["added", "removed", "changed"]

_EVENT_SYMBOLS: dict[HistoryEventType, str] = {"added": "↑", "removed": "↓", "changed": "±"}


@dataclass(frozen=True)
class HistoryEntry:
    timestamp: datetime
    event: HistoryEventType
    character: str
    item: Item
    # Nur bei event="changed" gesetzt: Differenz der Stack-Groesse seit dem
    # letzten Ladevorgang (Peter, 2026-08-03: "sobald sich Currency aendert,
    # wandert diese wieder ganz oben ... mit Vermerk, wieviel sich geaendert
    # hat"). Vorzeichenbehaftet, damit Zu-/Abnahme unterscheidbar bleibt.
    stack_delta: int | None = None


COLUMNS = ("Time", "Character", "Event", "Icon", "Name", "Base", "Stack", "Value")
TIME_COL = 0
CHARACTER_COL = 1
EVENT_COL = 2
ICON_COL = 3
NAME_COL = 4
BASE_COL = 5
STACK_COL = 6
VALUE_COL = 7


class ItemHistoryModel(QAbstractTableModel):
    """Zeigt die neuesten Einträge zuerst (Zeile 0 = zuletzt passiert) —
    beim standardmäßig auf eine Zeile kollabierten Panel soll genau das
    jüngste Ereignis sichtbar sein, nicht das älteste im 120er-Fenster."""

    def __init__(self, icon_requester: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self._entries: list[HistoryEntry] = []
        self._pixmaps: dict[str, QPixmap] = {}
        self._requested: set[str] = set()
        self._icon_requester = icon_requester
        self._price_index: PriceIndex | None = None

    def set_entries(self, entries: list[HistoryEntry]) -> None:
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()
        if self._icon_requester:
            for entry in entries:
                self._request_icon(entry.item)

    def _request_icon(self, item: Item) -> None:
        if self._icon_requester and item.icon \
                and item.icon not in self._pixmaps and item.icon not in self._requested:
            self._requested.add(item.icon)
            self._icon_requester(item.icon)

    def set_price_index(self, index: PriceIndex | None) -> None:
        self._price_index = index
        if self._entries:
            top_left = self.index(0, VALUE_COL)
            bottom_right = self.index(len(self._entries) - 1, VALUE_COL)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])

    def set_icon(self, url: str, pixmap: QPixmap) -> None:
        self._pixmaps[url] = pixmap
        for row, entry in enumerate(self._entries):
            if entry.item.icon == url:
                idx = self.index(row, ICON_COL)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    def pixmap_for(self, item: Item) -> QPixmap | None:
        return self._pixmaps.get(item.icon)

    def entry_at(self, row: int) -> HistoryEntry | None:
        return self._entries[row] if 0 <= row < len(self._entries) else None

    # --- Qt-Model-API --------------------------------------------------- #

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return "" if section == ICON_COL else COLUMNS[section]
        return None

    def _value_text(self, item: Item) -> str:
        if self._price_index is None:
            return ""
        unit_price = self._price_index.price_for(item)
        if unit_price is None:
            return ""
        return format_chaos_value(unit_price * (item.stackSize or 1), self._price_index)

    def data(self, index: QModelIndex, role):
        entry = self._entries[index.row()]
        col = index.column()
        item = entry.item
        if role == Qt.ItemDataRole.DisplayRole:
            if col == TIME_COL:
                return entry.timestamp.astimezone().strftime("%H:%M:%S")
            if col == CHARACTER_COL:
                return entry.character
            if col == EVENT_COL:
                return _EVENT_SYMBOLS[entry.event]
            if col == NAME_COL:
                return item.display_name
            if col == BASE_COL:
                return item.baseType or "–"
            if col == STACK_COL:
                if entry.event == "changed" and entry.stack_delta:
                    sign = "+" if entry.stack_delta > 0 else ""
                    return f"{item.stackSize} ({sign}{entry.stack_delta})"
                return str(item.stackSize) if item.stackSize else "–"
            if col == VALUE_COL:
                return self._value_text(item)
        if role == Qt.ItemDataRole.DecorationRole and col == ICON_COL:
            pm = self._pixmaps.get(item.icon)
            if pm:
                return pm.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            self._request_icon(item)  # lazy nachfordern, falls noch nicht im Cache
        if role == Qt.ItemDataRole.ForegroundRole and col == NAME_COL:
            colour = RARITY_COLORS.get(item.frameType)
            if colour:
                return QBrush(QColor(colour))
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{entry.character}: {item.display_name}"
        return None
