"""Item-Tabelle: Model/View mit Sortierung und Live-Filter.

LabVIEW-Äquivalent: Multicolumn Listbox — hier sauberer als
QAbstractTableModel + QSortFilterProxyModel (Sortieren/Filtern kostenlos).

Icons werden asynchron nachgeladen: das Model meldet fehlende URLs über den
``icon_requester``-Callback (MainWindow → FetchIconJob) und bekommt die
fertigen Pixmaps via ``set_icon`` zurück. In Aggregat-Ansichten (liga-weite
Suche, "Alle Tabs laden") passiert das LAZY erst beim Painten der Zeile —
eifriges Anfordern würde die Worker-Queue mit zigtausend Icon-Jobs fluten.

Die Tab-Spalte trägt den Namen des Herkunfts-Tabs pro Item. Bei Auswahl
eines einzelnen Tabs ist sie redundant und wird vom MainWindow automatisch
ausgeblendet; in Aggregat-Ansichten ("Alle Tabs laden", Klick auf einen
Spezial-Tab-Elternknoten, liga-weite Suche) wird sie automatisch
eingeblendet — dort ordnet sie Items ihrem Fach zu ("Map (Tier 1)").

Anf.Lvl/Str/Dex/Int kommen aus dem requirements-Array der GGG-API — die
Daten waren dank ``extra="allow"`` längst im Cache, wurden nur nie gezeigt
(Nutzer-Feedback; PoEDB o. Ä. ist damit unnötig).

Die Mods-Spalte zeigt die explicitMods (v. a. Map-Modifikatoren);
der Live-Filter durchsucht sie mit. Zusätzlich kann jede Spalte einen
eigenen Filter-Ausdruck tragen (">=20", "<45", "=Text", Teilstring) —
gesetzt über das Header-Rechtsklick-Menü, markiert mit 🔍 im Header.
"""

from __future__ import annotations

import re
from typing import Callable

from PySide6.QtCore import (QAbstractTableModel, QModelIndex,
                            QSortFilterProxyModel, Qt)
from PySide6.QtGui import QBrush, QColor, QPixmap

from poe_view.api.models import (Item, gem_level, gem_quality, req_attribute,
                                 req_level)
from poe_view.ui.theme import RARITY_COLORS

COLUMNS = ("Icon", "Tab", "Name", "Typ", "Level", "Qual.", "Stack", "iLvl",
           "Anf.Lvl", "Str", "Dex", "Int", "Mods")
ICON_COL = 0
TAB_COL = 1
_NAME_COL = 2
_NUMERIC_FROM_COL = 4  # Level, Qual., Stack, iLvl, Anf.Lvl, Str, Dex, Int
MODS_COL = 12          # Mods (v. a. Maps) — linksbündig, nicht numerisch

# Sortierung/Vergleich über echte Zahlen statt Anzeigetext — sonst sortiert
# "113" vor "56" (Stringvergleich). Der Proxy nutzt diese Rolle als sortRole.
NUMERIC_SORT_ROLE = Qt.ItemDataRole.UserRole

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _first_number(text: str) -> float | None:
    """Erste Zahl im Anzeigetext ("+20%" → 20.0, "–" → None)."""
    m = _NUM_RE.search(text)
    return float(m.group().replace(",", ".")) if m else None


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

    def set_items(self, items: list[Item], sources: list[str] | None = None,
                  request_icons: bool = True) -> None:
        """``sources[i]`` ist der Tab-Name von ``items[i]``. Ohne Angabe leer.

        ``request_icons=False`` für große Aggregate (liga-weite Suche,
        "Alle Tabs laden"): Icons werden dann lazy in ``data()`` angefordert,
        sobald Qt die Zeile tatsächlich malt — nur Sichtbares kostet Jobs.
        """
        self.beginResetModel()
        self._items = items
        self._sources = sources if sources is not None else [""] * len(items)
        self._rows = [self._precompute(item) for item in items]
        self.endResetModel()
        if request_icons and self._icon_requester:
            for item in items:
                self._request_icon(item)

    def _request_icon(self, item: Item) -> None:
        if self._icon_requester and item.icon \
                and item.icon not in self._pixmaps and item.icon not in self._requested:
            self._requested.add(item.icon)
            self._icon_requester(item.icon)

    @staticmethod
    def _precompute(item: Item) -> tuple:
        return (item.display_name, item.rarity, gem_level(item) or "–",
                gem_quality(item) or "–",
                str(item.stackSize) if item.stackSize else "–",
                str(item.ilvl) if item.ilvl else "–",
                req_level(item) or "–",
                req_attribute(item, "Str") or "–",
                req_attribute(item, "Dex") or "–",
                req_attribute(item, "Int") or "–",
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

    def display_text(self, row: int, col: int) -> str:
        """Anzeigetext einer Zelle — auch Basis der Spalten-Filter im Proxy."""
        if col == TAB_COL:
            return self._sources[row] or "–"
        if col > TAB_COL:
            return self._rows[row][col - 2]
        return ""

    def data(self, index: QModelIndex, role):
        item = self._items[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole and col >= TAB_COL:
            return self.display_text(index.row(), col)
        if role == NUMERIC_SORT_ROLE:
            # Numerische Spalten als Zahl sortieren ("–" ganz nach unten),
            # alle anderen weiterhin als (kleingeschriebener) Text.
            text = self.display_text(index.row(), col)
            if _NUMERIC_FROM_COL <= col < MODS_COL:
                number = _first_number(text)
                return number if number is not None else float("-inf")
            return text.lower()
        if role == Qt.ItemDataRole.ToolTipRole and col == MODS_COL:
            # Mods können lang werden — Tooltip zeigt sie zeilenweise komplett.
            return "\n".join(item.explicitMods) or None
        if role == Qt.ItemDataRole.DecorationRole and col == ICON_COL:
            pm = self._pixmaps.get(item.icon)
            if pm:
                return pm.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            self._request_icon(item)  # lazy: erst wenn die Zeile sichtbar wird
        if role == Qt.ItemDataRole.ForegroundRole and col == _NAME_COL:
            colour = RARITY_COLORS.get(item.frameType)
            if colour:
                return QBrush(QColor(colour))
        if role == Qt.ItemDataRole.TextAlignmentRole and _NUMERIC_FROM_COL <= col < MODS_COL:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


# Vergleichsoperator am Anfang eines Spalten-Filter-Ausdrucks
_OP_RE = re.compile(r"^\s*(<=|>=|!=|<>|<|>|=)\s*(.+)$")


def _expression_matches(expr: str, cell_text: str) -> bool:
    """Excel-artige Mini-Ausdrücke: ">=20", "<45", "=Beach Map", sonst
    Teilstring. Numerisch wird verglichen, sobald Operand UND Zelle eine
    Zahl hergeben ("+20%" zählt als 20) — sonst Textvergleich; Zellen ohne
    Zahl ("–") fallen bei <,>,<=,>= bewusst raus (wie in Excel)."""
    m = _OP_RE.match(expr)
    if not m:
        return expr.lower() in cell_text.lower()
    op, operand = m.group(1), m.group(2).strip()
    operand_num = _first_number(operand)
    cell_num = _first_number(cell_text)
    if op in ("=", "!=", "<>"):
        if operand_num is not None and cell_num is not None:
            equal = cell_num == operand_num
        else:
            equal = cell_text.strip().lower() == operand.lower()
        return equal if op == "=" else not equal
    if operand_num is None or cell_num is None:
        return False
    return {"<": cell_num < operand_num, "<=": cell_num <= operand_num,
            ">": cell_num > operand_num, ">=": cell_num >= operand_num}[op]


class ItemFilterProxy(QSortFilterProxyModel):
    """Filtert lokal über Name + Typ + Tab + Mods + Properties — kostet
    bewusst keine API-Calls. Zusätzlich je Spalte ein optionaler
    Filter-Ausdruck (Header-Rechtsklick), UND-verknüpft mit dem globalen
    Suchfeld. "*" im Suchfeld zeigt bewusst ALLES (Komplett-Export)."""

    def __init__(self) -> None:
        super().__init__()
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortRole(NUMERIC_SORT_ROLE)
        self._column_filters: dict[int, str] = {}
        self._search_text = ""

    def setFilterFixedString(self, text: str) -> None:  # noqa: N802 (Qt-API)
        """Rohtext selbst merken statt über das (regex-escapte!) Pattern von
        Qt zurückzulesen — sonst würde "*" als "\\*" ankommen und nie als
        Wildcard erkannt werden."""
        self._search_text = text or ""
        super().setFilterFixedString(text)

    # --- Spalten-Filter -------------------------------------------------- #

    def set_column_filter(self, col: int, expr: str) -> None:
        expr = (expr or "").strip()
        # begin/endFilterChange statt invalidateFilter — Letzteres ist seit
        # Qt 6.10 deprecated (Warnung in jedem Testlauf).
        self.beginFilterChange()
        if expr:
            self._column_filters[col] = expr
        else:
            self._column_filters.pop(col, None)
        self.endFilterChange()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, col, col)

    def column_filter(self, col: int) -> str:
        return self._column_filters.get(col, "")

    def filtered_columns(self) -> set[int]:
        return set(self._column_filters)

    def clear_column_filters(self) -> None:
        cols = list(self._column_filters)
        self.beginFilterChange()
        self._column_filters.clear()
        self.endFilterChange()
        for col in cols:
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, col, col)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        value = super().headerData(section, orientation, role)
        if (role == Qt.ItemDataRole.DisplayRole
                and orientation == Qt.Orientation.Horizontal
                and section in self._column_filters and value):
            return f"{value} 🔍"  # aktiver Spalten-Filter sichtbar im Header
        return value

    # --- Zeilen-Filter ---------------------------------------------------- #

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        model: ItemTableModel = self.sourceModel()
        item = model.item_at(row)
        if item is None:
            return True
        for col, expr in self._column_filters.items():
            if not _expression_matches(expr, model.display_text(row, col)):
                return False
        text = self._search_text.strip()
        if not text:
            return True
        if text == "*":
            # Wildcard: gesamten (bereits geladenen) Inhalt zeigen — z. B. um
            # eine komplette Truhe/Liga in einem Rutsch als CSV zu exportieren.
            return True
        # Properties (z. B. "Item Quantity: +23%") sind KEINE explicitMods —
        # ohne sie fände die Suche Maps mit Quantity/Rarity/Pack Size/Drop
        # Chance nie (Nutzer-Feedback: "nach Quantity gesucht, nur Chisel
        # gefunden" — die Chisel-Beschreibung nennt "Item Quantity" im Mod-
        # Text, die Maps selbst tragen den Wert nur als Property).
        prop_text = " ".join(f"{p.name} {p.display_value or ''}" for p in item.properties)
        haystack = (f"{item.display_name} {item.typeLine} {item.baseType} "
                   f"{item.rarity} {model.source_at(row)} "
                   f"{' '.join(item.explicitMods)} {prop_text}")
        return text.lower() in haystack.lower()
