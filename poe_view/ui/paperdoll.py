"""Charakter-Paperdoll: Doppelklick auf einen Charakter zeigt seine
Ausrüstung als Puppenlayout statt als flache Tabellenzeilen (ToDo.md:
"Doppelklick auf einen Char 'beleuchtet' diesen").

Reine Anzeige der bereits geladenen Charakter-Items (Ausrüstung + Inventar
kommen ohnehin über ``FetchCharacterItemsJob``, siehe ARCHITEKTUR.md
§4.13) — kein eigener Datenabruf, kein Netzzugriff. Icons kommen über
einen injizierten ``pixmap_for``-Callback (üblicherweise
``MainWindow.table_model.pixmap_for``), damit dieses Modul nichts vom
Worker/Icon-Cache wissen muss.

Drei Lesbarkeitsmängel wurden am 2026-08-06 behoben, alle an Peters
echten Charakteren gemessen: Die Hälfte der Namen war abgeschnitten (87
von 171 — vier Flaschen lasen sich allesamt als "Flagell…"), die
Rarity-Farbe der Item-Tabelle fehlte, und die Juwelen waren als einzige
Items im Fenster nicht anklickbar. Nach der Änderung: 0 von 204
gekürzt.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QGridLayout, QGroupBox, QHBoxLayout,
                               QSplitter, QToolButton, QVBoxLayout, QWidget)

from poe_view.api.models import Character, Item
from poe_view.ui.item_detail import ItemDetail
from poe_view.ui.theme import RARITY_COLORS

# GGGs inventoryId-Werte für Ausrüstungs-Slots (real geprüft, Peters
# Stash-Cache, 2026-07-31) — "Helm" nicht "Helmet", "Offhand"/"Offhand2"
# statt "Shield"/"Shield2".
#
# Die Anordnung folgt PoEs eigenem Inventar-Fenster. Sie stand vorher nach
# meiner Erinnerung im Code und war an zwei Stellen falsch (Peter schickte
# am 2026-08-07 einen Screenshot seines laufenden Spiels): Die Ringe
# flankieren die RÜSTUNG, nicht den Gürtel, und das Amulett sitzt RECHTS
# NEBEN DEM HELM, nicht zwischen den Waffen. Handschuhe, Gürtel und
# Stiefel liegen auf einer Höhe.
#
#        c0        c1        c2        c3        c4
#   r0             ·        Helm     Amulet       ·
#   r1   Weapon   Ring      Body     Ring2     Off Hand
#   r2      ·    Gloves     Belt     Boots        ·
#
# Im Spiel sind Waffe und Zweithand vier Felder hoch und die Rüstung drei;
# mit gleich großen Plätzen lässt sich das nicht nachbauen, wohl aber ihre
# Lage zueinander — und darum geht es hier.
#
# Die letzte Spalte ist die sichtbare Beschriftung des leeren Platzes und
# deshalb ENGLISCH (Oberfläche englisch, Kommentare deutsch — dieselbe
# Trennung wie in ``help_dialog.py``/``settings_dialog.py``). Bewusst die
# Slot-Namen aus dem Spiel selbst, nicht die der API: Ein Spieler kennt
# "Off Hand", nicht "Offhand2".
DOLL_SLOTS = (
    (0, 2, "Helm", "Helmet"),
    (0, 3, "Amulet", "Amulet"),
    (1, 0, "Weapon", "Weapon"),
    (1, 1, "Ring", "Ring"),
    (1, 2, "BodyArmour", "Body Armour"),
    (1, 3, "Ring2", "Ring"),
    (1, 4, "Offhand", "Off Hand"),
    (2, 1, "Gloves", "Gloves"),
    (2, 2, "Belt", "Belt"),
    (2, 3, "Boots", "Boots"),
)

# Nur gezeigt, wenn der Charakter tatsächlich etwas darin trägt — ein
# Waffentausch-Set oder ein Trinket (Ritual-/Necropolis-Liga-Feature) hat
# nicht jeder Charakter. Ihre Beschriftung ist deshalb nie zu sehen: Sie
# erscheint nur an einem LEEREN Platz, und leer wird hier keiner angelegt.
# Trotzdem englisch gehalten wie alles andere — der Tag, an dem diese
# Plätze doch dauerhaft stehen, soll nicht überraschen.
SWAP_SLOTS = (("Weapon2", "Weapon (swap)"), ("Offhand2", "Off Hand (swap)"))
TRINKET_SLOT = ("Trinket", "Trinket")

# Alle ``inventoryId``-Werte, die ein Charakter tatsächlich TRÄGT statt im
# Rucksack ("MainInventory") zu haben — die Puppe oben plus Flaschen (eigener
# Slot "Flask", nicht Teil der Puppe, siehe ``_build_flasks``), Zweitwaffe
# und Trinket. Öffentlich, weil ``main_window.py`` dieselbe Unterscheidung
# für die Diagnose der ToDo-Meldung "angelegte Items werden nach einem
# Zonenwechsel fälschlich als frisch erkannt" braucht — eine zweite,
# eigene Liste hätte bei einer künftigen Slot-Änderung leicht auseinanderlaufen
# können. ``DOLL_SLOTS``/``SWAP_SLOTS``/``TRINKET_SLOT`` sind aus demselben
# Grund öffentlich: ``character_sheet.py`` braucht dieselbe Reihenfolge und
# dieselben Beschriftungen fürs Ausrüstungskapitel des Exports.
EQUIPPED_SLOTS: frozenset[str] = frozenset(
    {slot_id for _, _, slot_id, _ in DOLL_SLOTS}
    | {slot_id for slot_id, _ in SWAP_SLOTS}
    | {TRINKET_SLOT[0], "Flask"}
)


# Ein Platz ist so breit, dass die üblichen Basis-Namen in zwei Zeilen
# passen. Vorher waren es 88 px bei EINER Zeile — an Peters echten
# Charakteren gemessen wurden dadurch 87 von 171 Ausrüstungsteilen
# abgeschnitten, also die Hälfte. Vier Flaschen lasen sich allesamt als
# "Flagell…" und waren nicht auseinanderzuhalten.
_SLOT_WIDTH = 104
_SLOT_HEIGHT = 104
_ICON_SIZE = 48
_NAME_LINES = 2

# So breit wie die Ausrüstungspuppe darüber (fünf Plätze), damit das
# Juwelen-Raster nicht aus dem Fenster ragt.
_JEWELS_PER_ROW = 5


def _fit_name(text: str, metrics: QFontMetrics, width: int) -> str:
    """Namen auf höchstens ``_NAME_LINES`` Zeilen umbrechen, an
    Wortgrenzen; passt das letzte Wort nicht mehr, wird nur DIESE Zeile
    gekürzt.

    Qts ``QToolButton`` kann nicht selbst umbrechen — es kürzt einzeilig
    mit Auslassungspunkten. Ein manuell eingefügter Zeilenumbruch wird
    dagegen gezeichnet."""
    words = text.split()
    if not words:
        return text
    lines: list[str] = [words[0]]
    for word in words[1:]:
        probe = f"{lines[-1]} {word}"
        if metrics.horizontalAdvance(probe) <= width:
            lines[-1] = probe
        elif len(lines) < _NAME_LINES:
            lines.append(word)
        else:
            lines[-1] = probe  # passt nicht mehr, wird unten gekürzt
    lines[-1] = metrics.elidedText(lines[-1], Qt.TextElideMode.ElideRight, width)
    return "\n".join(lines)


class _SlotButton(QToolButton):
    """Ein Ausrüstungsplatz: Icon + Name, leer bleibt ein deaktivierter
    Platzhalter (kein Item zum Anzeigen)."""

    picked = Signal(object)  # Item

    def __init__(self, empty_label: str) -> None:
        super().__init__()
        self.setFixedSize(_SLOT_WIDTH, _SLOT_HEIGHT)
        self.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
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
            self.setStyleSheet("")
            return
        self.setEnabled(True)
        # Beschriftet wird mit lookup_name, nicht display_name: Der
        # gewürfelte Fantasiename eines Rares ("Vortex Bane") sagt nichts,
        # seine Basis ("Gutting Knife") schon — und die Affix-Kette eines
        # Magic-Items passt hier ohnehin nie hin. Der vollständige Name
        # steht im Tooltip und beim Klick im Detail-Panel.
        self.setText(_fit_name(item.lookup_name, self.fontMetrics(),
                              _SLOT_WIDTH - 10))
        self.setToolTip(item.display_name)
        self.setIcon(QIcon(pixmap) if pixmap else QIcon())
        # Rarity-Farbe wie in der Item-Tabelle — sonst sieht man der Puppe
        # nicht an, welches Teil das Unique ist.
        colour = RARITY_COLORS.get(item.frameType)
        self.setStyleSheet(f"QToolButton {{ color: {colour}; }}" if colour else "")

    def _on_clicked(self) -> None:
        if self._item is not None:
            self.picked.emit(self._item)


class PaperdollDialog(QDialog):
    def __init__(self, char: Character, items: list[Item],
                pixmap_for: Callable[[Item], QPixmap | None],
                parent: QWidget | None = None,
                mark_for: Callable[[Item], Callable[[str, str], str]] | None = None,
                tail_for: Callable[[Item], Callable[[str, str], str]] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{char.name} — {char.class_} {char.level}")
        self._pixmap_for = pixmap_for
        # Die Marken der Mod-Sammlung (§4.52) und die Tier-Etiketten der
        # Mod-Datenbank (§4.53.4). Als Fabrik je Item, weil der Vergleich
        # die Rarität braucht — und optional, damit die Paperdoll ohne
        # Sammlung prüfbar bleibt.
        self._mark_for = mark_for
        self._tail_for = tail_for

        by_slot: dict[str, list[Item]] = {}
        for item in items:
            by_slot.setdefault(item.inventoryId, []).append(item)

        self.detail = ItemDetail()

        doll_box = QGroupBox("Equipment")
        doll_grid = QGridLayout(doll_box)
        for row, col, slot_id, label in DOLL_SLOTS:
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
        for slot_id, label in SWAP_SLOTS + (TRINKET_SLOT,):
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

        # Juwelen wie jeder andere Platz: anklickbar, mit Icon und
        # Rarity-Farbe. Vorher standen sie als reine Textliste in einem
        # Rollbereich darunter — die einzigen Items im Fenster, die auf
        # einen Klick nicht reagierten, und die Liste schnitt regelmäßig
        # mitten in einer Zeile ab. Ein Raster wächst stattdessen nach
        # unten; ein Charakter trägt selten mehr als eine Handvoll.
        jewels = by_slot.get("PassiveJewels", [])
        if jewels:
            jewel_box = QGroupBox(f"Jewels in the passive tree ({len(jewels)})")
            jewel_grid = QGridLayout(jewel_box)
            for index, jewel in enumerate(jewels):
                btn = _SlotButton("Jewel")
                btn.set_item(jewel, pixmap_for(jewel))
                btn.picked.connect(self._show_detail)
                jewel_grid.addWidget(btn, index // _JEWELS_PER_ROW,
                                    index % _JEWELS_PER_ROW)
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
        extras = {}
        if self._mark_for is not None:
            extras["mark"] = self._mark_for(item)
        if self._tail_for is not None:
            extras["tail"] = self._tail_for(item)
        self.detail.show_item(item, self._pixmap_for(item), **extras)
