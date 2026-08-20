"""Charakterliste links oben (docs/ARCHITEKTUR.md §5) — bewusst kein Tree.

Charaktere haben keine Unterstruktur, ein flacher QListWidget spart eine
Baum-Ebene und die zugehörigen Auf-/Zuklapp-Klicks.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu

from poe_view.api.models import Character

_DATA_ROLE = Qt.ItemDataRole.UserRole


class CharacterList(QListWidget):
    character_selected = Signal(object)           # Character
    character_refresh_requested = Signal(object)   # Character — Rechtsklick "Aktualisieren"
    character_paperdoll_requested = Signal(object)  # Character — Doppelklick
    character_sheet_requested = Signal(object)     # Character — Rechtsklick "Export character sheet…"
    export_visible_requested = Signal()            # Rechtsklick-Kontextmenü, wie StashTree

    def __init__(self) -> None:
        super().__init__()
        self.itemClicked.connect(self._on_click)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

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

    def _on_double_click(self, item: QListWidgetItem) -> None:
        self.character_paperdoll_requested.emit(item.data(_DATA_ROLE))

    def _on_context_menu(self, pos) -> None:
        """Analog StashTree._on_context_menu: manuelles Neuladen, da es (anders
        als bei Stash-Tabs) keinen Auto-Refresh-Sweep für Charaktere gibt —
        das aktuell angezeigte Inventar hält sich selbst aktuell, alle
        anderen brauchen einen expliziten Weg. "Export visible items"
        (Peter, 2026-08-03: "Sollen wir das in der Character-Liste auch in
        den Rechtsklick mit aufnehmen?") steht — wie schon im Stash-Baum —
        IMMER zur Verfügung, auch im leeren Bereich ohne Charakter unter
        dem Cursor: es bezieht sich auf das aktuell in der Item-Tabelle
        Sichtbare, unabhängig vom angeklickten Eintrag."""
        item = self.itemAt(pos)
        menu = QMenu(self)
        if item is not None:
            char: Character = item.data(_DATA_ROLE)
            action = menu.addAction("⟳ Refresh")
            action.triggered.connect(lambda: self.character_refresh_requested.emit(char))
            sheet_action = menu.addAction("📜 Export character sheet…")
            sheet_action.triggered.connect(lambda: self.character_sheet_requested.emit(char))
            menu.addSeparator()
        menu.addAction("💾 Export visible items").triggered.connect(
            self.export_visible_requested.emit)
        menu.exec(self.viewport().mapToGlobal(pos))
