"""Charakterliste links oben (docs/ARCHITEKTUR.md §5) — bewusst kein Tree.

Charaktere haben keine Unterstruktur, ein flacher QListWidget spart eine
Baum-Ebene und die zugehörigen Auf-/Zuklapp-Klicks (Nutzer-Feedback).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from poe_view.api.models import Character

_DATA_ROLE = Qt.ItemDataRole.UserRole


class CharacterList(QListWidget):
    character_selected = Signal(object)  # Character

    def __init__(self) -> None:
        super().__init__()
        self.itemClicked.connect(self._on_click)

    def set_characters(self, characters: list[Character]) -> None:
        """Flache Liste, absteigend nach Level. Erwartet bereits liga-gefilterte Charaktere."""
        self.clear()
        for char in sorted(characters, key=lambda c: (-c.level, c.name)):
            label = f"{char.name} ({char.class_} {char.level})"
            item = QListWidgetItem(label)
            item.setData(_DATA_ROLE, char)
            self.addItem(item)

    def _on_click(self, item: QListWidgetItem) -> None:
        self.character_selected.emit(item.data(_DATA_ROLE))
