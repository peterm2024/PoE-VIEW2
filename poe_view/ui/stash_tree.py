"""Navigations-Baum links: Charaktere + Stash-Tabs (docs/ARCHITEKTUR.md §5).

Jeder Stash-Tab-Knoten hat zwei Zusatzspalten: eine Status-Spalte (⬇ = Items
noch nicht geladen, leer = bereits im Speicher-Cache) und ein Refresh-Button,
über den genau dieser Tab neu geladen werden kann (bewusst am Cache vorbei).

LabVIEW-Äquivalent: Tree Control mit rekursivem Laden der children;
die Tab-Farbe (metadata.colour, hex ohne '#') wird als Vordergrundfarbe gesetzt
(≙ Hex→U32-Wandlung im Original).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QToolButton, QTreeWidget, QTreeWidgetItem

from poe_view.api.models import Character, StashTab

_KIND_ROLE = Qt.ItemDataRole.UserRole
_DATA_ROLE = Qt.ItemDataRole.UserRole + 1

_COL_NAME, _COL_STATUS, _COL_REFRESH = 0, 1, 2
_UNLOADED_MARK = "⬇"


class StashTree(QTreeWidget):
    stash_selected = Signal(str, str)          # stash_id, name
    stash_refresh_requested = Signal(str, str)  # stash_id, name
    character_selected = Signal(object)        # Character

    def __init__(self) -> None:
        super().__init__()
        self.setColumnCount(3)
        self.setHeaderHidden(True)
        self.header().setStretchLastSection(False)
        self.setColumnWidth(_COL_STATUS, 20)
        self.setColumnWidth(_COL_REFRESH, 26)
        self._char_root = QTreeWidgetItem(["Charaktere"])
        self._stash_root = QTreeWidgetItem(["Stash"])
        self.addTopLevelItem(self._char_root)
        self.addTopLevelItem(self._stash_root)
        self._stash_nodes: dict[str, QTreeWidgetItem] = {}  # stash_id → Knoten
        self.itemClicked.connect(self._on_click)

    def set_characters(self, characters: list[Character]) -> None:
        """Flache Liste, absteigend nach Level. Erwartet bereits liga-gefilterte Charaktere."""
        self._char_root.takeChildren()
        for char in sorted(characters, key=lambda c: (-c.level, c.name)):
            label = f"{char.name} ({char.class_} {char.level})"
            node = QTreeWidgetItem([label])
            node.setData(0, _KIND_ROLE, "character")
            node.setData(0, _DATA_ROLE, char)
            self._char_root.addChild(node)

    def set_stashes(self, stashes: list[StashTab], loaded_ids: frozenset[str] = frozenset()) -> None:
        """Zeigt den Stash-Baum an — startet zugeklappt (auch Unterordner).

        ``loaded_ids`` sind Stash-IDs, deren Items bereits im Speicher-Cache
        liegen (MainWindow._items_cache) — sie bekommen keinen ⬇-Marker.
        """
        self._stash_root.takeChildren()
        self._stash_nodes.clear()
        for stash in stashes:
            self._stash_root.addChild(self._build_node(stash))
        # Refresh-Buttons erst NACH dem Einhängen setzen — setItemWidget
        # wirkt nur auf Items, die bereits Teil des Baums sind.
        for stash_id, node in self._stash_nodes.items():
            self._set_status(node, loaded=stash_id in loaded_ids)
            self._add_refresh_button(node, stash_id, node.data(0, _DATA_ROLE).name)

    def mark_loaded(self, stash_id: str) -> None:
        """Blendet den ⬇-Marker aus, sobald ein Tab tatsächlich geladen wurde."""
        node = self._stash_nodes.get(stash_id)
        if node is not None:
            self._set_status(node, loaded=True)

    def _build_node(self, stash: StashTab) -> QTreeWidgetItem:
        """Rekursiv: Ordner enthalten children (beliebig tief)."""
        prefix = "📁 " if stash.is_folder else ""
        node = QTreeWidgetItem([f"{prefix}{stash.name}"])
        if not stash.is_folder:
            node.setData(0, _KIND_ROLE, "stash")
            node.setData(0, _DATA_ROLE, stash)
            self._stash_nodes[stash.id] = node
        if stash.colour:
            node.setForeground(0, QBrush(QColor(stash.colour)))
        for child in stash.children:
            node.addChild(self._build_node(child))
        return node

    def _set_status(self, node: QTreeWidgetItem, loaded: bool) -> None:
        node.setText(_COL_STATUS, "" if loaded else _UNLOADED_MARK)
        node.setToolTip(_COL_STATUS, "Bereits geladen" if loaded else "Noch nicht geladen")

    def _add_refresh_button(self, node: QTreeWidgetItem, stash_id: str, name: str) -> None:
        button = QToolButton()
        button.setText("⟳")
        button.setAutoRaise(True)
        button.setFixedSize(20, 20)
        button.setToolTip(f"'{name}' neu laden")
        button.clicked.connect(lambda: self.stash_refresh_requested.emit(stash_id, name))
        self.setItemWidget(node, _COL_REFRESH, button)

    def _on_click(self, item: QTreeWidgetItem) -> None:
        kind = item.data(0, _KIND_ROLE)
        if kind == "stash":
            stash: StashTab = item.data(0, _DATA_ROLE)
            self.stash_selected.emit(stash.id, stash.name)
        elif kind == "character":
            self.character_selected.emit(item.data(0, _DATA_ROLE))
