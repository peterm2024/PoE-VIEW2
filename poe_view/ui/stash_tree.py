"""Navigations-Baum links: Charaktere + Stash-Tabs (docs/ARCHITEKTUR.md §5).

LabVIEW-Äquivalent: Tree Control mit rekursivem Laden der children;
die Tab-Farbe (metadata.colour, hex ohne '#') wird als Vordergrundfarbe gesetzt
(≙ Hex→U32-Wandlung im Original).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from poe_view.api.models import Character, StashTab

_KIND_ROLE = Qt.ItemDataRole.UserRole
_DATA_ROLE = Qt.ItemDataRole.UserRole + 1


class StashTree(QTreeWidget):
    stash_selected = Signal(str, str)      # stash_id, name
    character_selected = Signal(object)    # Character

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self._char_root = QTreeWidgetItem(["Charaktere"])
        self._stash_root = QTreeWidgetItem(["Stash"])
        self.addTopLevelItem(self._char_root)
        self.addTopLevelItem(self._stash_root)
        self.itemClicked.connect(self._on_click)

    def set_characters(self, characters: list[Character]) -> None:
        self._char_root.takeChildren()
        for char in characters:
            label = f"{char.name} ({char.class_} {char.level})"
            node = QTreeWidgetItem([label])
            node.setData(0, _KIND_ROLE, "character")
            node.setData(0, _DATA_ROLE, char)
            self._char_root.addChild(node)
        self._char_root.setExpanded(True)

    def set_stashes(self, stashes: list[StashTab]) -> None:
        self._stash_root.takeChildren()
        for stash in stashes:
            self._stash_root.addChild(self._build_node(stash))
        self._stash_root.setExpanded(True)

    def _build_node(self, stash: StashTab) -> QTreeWidgetItem:
        """Rekursiv: Ordner enthalten children (beliebig tief)."""
        prefix = "📁 " if stash.is_folder else ""
        node = QTreeWidgetItem([f"{prefix}{stash.name}"])
        if not stash.is_folder:
            node.setData(0, _KIND_ROLE, "stash")
            node.setData(0, _DATA_ROLE, stash)
        if stash.colour:
            node.setForeground(0, QBrush(QColor(stash.colour)))
        for child in stash.children:
            node.addChild(self._build_node(child))
        return node

    def _on_click(self, item: QTreeWidgetItem) -> None:
        kind = item.data(0, _KIND_ROLE)
        if kind == "stash":
            stash: StashTab = item.data(0, _DATA_ROLE)
            self.stash_selected.emit(stash.id, stash.name)
        elif kind == "character":
            self.character_selected.emit(item.data(0, _DATA_ROLE))
