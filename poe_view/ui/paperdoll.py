"""Charakter-Paperdoll: Doppelklick auf einen Charakter zeigt seine
Ausrüstung als Puppenlayout statt als flache Tabellenzeilen (ToDo.md:
"Doppelklick auf einen Char 'beleuchtet' diesen").

Reine Anzeige der bereits geladenen Charakter-Items (Ausrüstung + Inventar
kommen ohnehin über ``FetchCharacterItemsJob``, siehe ARCHITEKTUR.md
§4.13) — kein eigener Datenabruf, kein Netzzugriff. Icons kommen über
einen injizierten ``pixmap_for``-Callback (üblicherweise
``MainWindow.table_model.pixmap_for``), damit dieses Modul nichts vom
Worker/Icon-Cache wissen muss.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QScrollArea, QSplitter, QToolButton,
                               QVBoxLayout, QWidget)

from poe_view.api.models import Character, Item
from poe_view.ui.item_detail import ItemDetail

# GGGs inventoryId-Werte für Ausrüstungs-Slots (real geprüft, Peters
# Stash-Cache, 2026-07-31) — "Helm" nicht "Helmet", "Offhand"/"Offhand2"
# statt "Shield"/"Shield2". Position im Grid folgt dem klassischen
# PoE-Charakterbogen-Layout.
#
# Die zweite Spalte ist die sichtbare Beschriftung des leeren Platzes und
# deshalb ENGLISCH (Oberfläche englisch, Kommentare deutsch — dieselbe
# Trennung wie in ``help_dialog.py``/``settings_dialog.py``). Bewusst die
# Slot-Namen aus dem Spiel selbst, nicht die der API: Ein Spieler kennt
# "Off Hand", nicht "Offhand2".
_DOLL_SLOTS = (
    (0, 1, "Helm", "Helmet"),
    (1, 0, "Weapon", "Weapon"),
    (1, 1, "Amulet", "Amulet"),
    (1, 2, "Offhand", "Off Hand"),
    (2, 1, "BodyArmour", "Body Armour"),
    (3, 0, "Ring", "Ring"),
    (3, 1, "Belt", "Belt"),
    (3, 2, "Ring2", "Ring"),
    (4, 0, "Gloves", "Gloves"),
    (4, 2, "Boots", "Boots"),
)

# Nur gezeigt, wenn der Charakter tatsächlich etwas darin trägt — ein
# Waffentausch-Set oder ein Trinket (Ritual-/Necropolis-Liga-Feature) hat
# nicht jeder Charakter. Ihre Beschriftung ist deshalb nie zu sehen: Sie
# erscheint nur an einem LEEREN Platz, und leer wird hier keiner angelegt.
# Trotzdem englisch gehalten wie alles andere — der Tag, an dem diese
# Plätze doch dauerhaft stehen, soll nicht überraschen.
_SWAP_SLOTS = (("Weapon2", "Weapon (swap)"), ("Offhand2", "Off Hand (swap)"))
_TRINKET_SLOT = ("Trinket", "Trinket")


class _SlotButton(QToolButton):
    """Ein Ausrüstungsplatz: Icon + Name, leer bleibt ein deaktivierter
    Platzhalter (kein Item zum Anzeigen)."""

    picked = Signal(object)  # Item

    def __init__(self, empty_label: str) -> None:
        super().__init__()
        self.setFixedSize(88, 88)
        self.setIconSize(QSize(48, 48))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self._empty_label = empty_label
        self.clicked.connect(self._on_clicked)
        self.set_item(None, None)

    def set_item(self, item: Item | None, pixmap: QPixmap | None) -> None:
        self._item = item
        if item is None:
            self.setText(f"({self._empty_label})")
            self.setIcon(QIcon())
            self.setEnabled(False)
            self.setToolTip("")
            return
        self.setEnabled(True)
        self.setText(item.display_name)
        self.setToolTip(item.display_name)
        self.setIcon(QIcon(pixmap) if pixmap else QIcon())

    def _on_clicked(self) -> None:
        if self._item is not None:
            self.picked.emit(self._item)


class PaperdollDialog(QDialog):
    def __init__(self, char: Character, items: list[Item],
                pixmap_for: Callable[[Item], QPixmap | None],
                parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{char.name} — {char.class_} {char.level}")
        self._pixmap_for = pixmap_for

        by_slot: dict[str, list[Item]] = {}
        for item in items:
            by_slot.setdefault(item.inventoryId, []).append(item)

        self.detail = ItemDetail()

        doll_box = QGroupBox("Equipment")
        doll_grid = QGridLayout(doll_box)
        for row, col, slot_id, label in _DOLL_SLOTS:
            slot_items = by_slot.get(slot_id)
            btn = _SlotButton(label)
            btn.set_item(slot_items[0] if slot_items else None,
                        pixmap_for(slot_items[0]) if slot_items else None)
            btn.picked.connect(self._show_detail)
            doll_grid.addWidget(btn, row, col)

        flasks = sorted(by_slot.get("Flask", []), key=lambda i: i.x or 0)
        flask_row = QHBoxLayout()
        for flask in flasks:
            btn = _SlotButton("Flask")
            btn.set_item(flask, pixmap_for(flask))
            btn.picked.connect(self._show_detail)
            flask_row.addWidget(btn)
        flask_row.addStretch()

        extra_row = QHBoxLayout()
        for slot_id, label in _SWAP_SLOTS + (_TRINKET_SLOT,):
            slot_items = by_slot.get(slot_id)
            if not slot_items:
                continue  # nicht jeder Charakter hat ein Tausch-Set/Trinket
            btn = _SlotButton(label)
            btn.set_item(slot_items[0], pixmap_for(slot_items[0]))
            btn.picked.connect(self._show_detail)
            extra_row.addWidget(btn)
        extra_row.addStretch()

        left = QVBoxLayout()
        left.addWidget(doll_box)
        if flasks:
            left.addLayout(flask_row)
        if extra_row.count() > 1:  # mehr als nur der abschließende Stretch
            left.addLayout(extra_row)

        jewels = by_slot.get("PassiveJewels", [])
        if jewels:
            jewel_box = QGroupBox(f"Jewels in the passive tree ({len(jewels)})")
            jewel_layout = QVBoxLayout(jewel_box)
            jewel_list = QLabel("\n".join(j.display_name for j in jewels))
            jewel_list.setWordWrap(True)
            scroll = QScrollArea()
            scroll.setWidget(jewel_list)
            scroll.setWidgetResizable(True)
            scroll.setMaximumHeight(120)
            jewel_layout.addWidget(scroll)
            left.addWidget(jewel_box)

        left_widget = QWidget()
        left_widget.setLayout(left)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(1, 1)

        outer = QVBoxLayout(self)
        outer.addWidget(splitter)

    def _show_detail(self, item: Item) -> None:
        self.detail.show_item(item, self._pixmap_for(item))
