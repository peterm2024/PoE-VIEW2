"""Beobachtete Stapelgrößen neben den Gem-Balken (§4.45).

Peter, 2026-08-15: "Oft gibt es Items, deren Stapelgröße ich gerne
beobachten würde, z.B. Lifeforce. ... So weiß ich auf einen Blick,
wieviel ich von z.B. 'Wild Crystallised Lifeforce' besitze."

Gezählt wird über alles, was von der aktuellen Liga geladen ist —
Truhenfächer und Charaktere. Ein beobachtetes Item, von dem gerade
nichts da ist, zeigt ``0``: Genau das ist eine Aussage, und eine
verschwindende Zeile wäre keine.

**Die Summe ist nur so vollständig wie der Cache.** Ist noch nicht jedes
Fach der Liga geladen, kann irgendwo mehr liegen. Die Zeile trägt dann
ein ``≥`` — die Zahl bleibt brauchbar, behauptet aber nicht, alles zu
sein. Ohne dieses Zeichen sähe eine halb geladene Liga wie ein
Bestandsverlust aus.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (QHeaderView, QMenu, QSizePolicy, QTableWidget,
                               QTableWidgetItem)

from poe_view.api.models import Item

# Zeilenhöhe und Schrift bewusst kleiner als in der Haupttabelle: Die
# Tabelle teilt sich den Streifen über dem Graphen mit den Gem-Balken
# (60 px hoch, §4.42) und darf ihn nicht sprengen.
ROW_HEIGHT = 18
FONT_SIZE = 8

# Ab hier wird die Liste scrollbar statt höher. Vier Zeilen passen neben
# die Gem-Balken, ohne dass der Graph darunter schrumpft.
MAX_VISIBLE_ROWS = 4

INCOMPLETE_MARK = "≥"


class FavouriteRow(NamedTuple):
    name: str
    total: int
    complete: bool = True

    @property
    def total_text(self) -> str:
        """Tausender mit schmalem Leerzeichen, wie in der Statuszeile."""
        zahl = f"{self.total:,}".replace(",", " ")
        return zahl if self.complete else f"{INCOMPLETE_MARK} {zahl}"


def favourite_rows(items: Iterable[Item], names: Sequence[str],
                   complete: bool = True) -> list[FavouriteRow]:
    """Eine Zeile je beobachtetem Namen, in der gespeicherten Reihenfolge.

    Gezählt wird die Stapelgröße; ``stackSize`` fehlt bei allem, was sich
    nicht stapeln lässt (Waffen, Rüstung, Gems — an Peters Bestand 94 %
    der Items). Ein solches Item zählt als eines: Wer eine Karte oder ein
    Unique beobachtet, will wissen, wie viele davon herumliegen, nicht ob
    GGG ein Stapelfeld mitgeschickt hat.

    Die Reihenfolge stammt vom Nutzer und wird nicht nach Menge sortiert:
    Eine Zeile, die je nach Bestand die Position wechselt, kann man nicht
    "auf einen Blick" ablesen — man müsste sie jedes Mal suchen.

    **Ein Durchlauf für alle Namen, nicht einer je Name.** An Peters
    echtem Bestand (58.621 Items) gemessen: zwölf Beobachtungen über
    ``stack_total`` einzeln kosteten 81 ms, in einem Durchlauf 20 ms —
    und das Zählen läuft nach JEDEM eintreffenden Fach, bei "Load All
    Tabs" also über tausendmal hintereinander. Dieselbe Falle wie beim
    Modellaufbau der Großsuche (FALLSTRICKE #47): Was einzeln billig
    aussieht, wird durch die Wiederholung teuer."""
    gesucht = set(names)
    summen = dict.fromkeys(names, 0)
    for item in items:
        name = item.display_name
        if name in gesucht:
            summen[name] += item.stackSize if item.stackSize is not None else 1
    return [FavouriteRow(name, summen[name], complete) for name in names]


class FavouritesTable(QTableWidget):
    """Zwei Spalten ohne Kopfzeile: Name links, Menge rechts."""

    # Rechtsklick in der Tabelle selbst. Ohne diesen Weg hätte die
    # Funktion eine Sackgasse: Ein beobachtetes Item, von dem gerade
    # nichts mehr da ist, steht in keiner Item-Tabelle mehr — und wäre
    # über den Rechtsklick dort nie wieder zu entfernen.
    remove_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__(0, 2)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.horizontalScrollBarPolicy = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        font = QFont()
        font.setPointSize(FONT_SIZE)
        self.setFont(font)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self._rows: list[FavouriteRow] = []
        self.set_rows([])

    def rows(self) -> list[FavouriteRow]:
        return list(self._rows)

    def set_rows(self, rows: Sequence[FavouriteRow]) -> None:
        self._rows = list(rows)
        self.setRowCount(len(self._rows))
        for zeile, row in enumerate(self._rows):
            self.setRowHeight(zeile, ROW_HEIGHT)
            name = QTableWidgetItem(row.name)
            # Der volle Name im Tooltip: Die Spalte ist schmal, und
            # "Wild Crystallised Lifeforce" steht dort selten ganz.
            name.setToolTip(row.name)
            menge = QTableWidgetItem(row.total_text)
            menge.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter)
            if not row.complete:
                menge.setToolTip("Not every stash tab of this league is "
                                 "loaded — there may be more.")
            self.setItem(zeile, 0, name)
            self.setItem(zeile, 1, menge)
        self.setVisible(bool(self._rows))
        self.setFixedHeight(self._wanted_height())

    def _wanted_height(self) -> int:
        sichtbar = min(len(self._rows), MAX_VISIBLE_ROWS)
        return sichtbar * ROW_HEIGHT + 2 if sichtbar else 0

    def name_at(self, row: int) -> str:
        """Für das Kontextmenü: Welcher Favorit steht in dieser Zeile?"""
        return self._rows[row].name if 0 <= row < len(self._rows) else ""

    def build_context_menu(self, row: int) -> QMenu | None:
        """Als eigene Methode, damit sich der Menüinhalt prüfen lässt,
        ohne ``QMenu.exec()`` auszulösen (dasselbe Vorgehen wie beim
        Item-Kontextmenü im Hauptfenster)."""
        name = self.name_at(row)
        if not name:
            return None
        menu = QMenu(self)
        action = menu.addAction(f"★ Stop watching \"{name}\"")
        action.triggered.connect(
            lambda _=False, n=name: self.remove_requested.emit(n))
        return menu

    def _on_context_menu(self, pos) -> None:
        menu = self.build_context_menu(self.rowAt(pos.y()))
        if menu is not None:
            menu.exec(self.viewport().mapToGlobal(pos))

    def minimumSizeHint(self):  # noqa: N802 — Qt-Namensschema
        """Genug Platz für die Mengenspalte plus ein paar Zeichen Name.

        Ohne diese Untergrenze drückt der Splitter die Tabelle bei engem
        Fenster auf null, und die Zahl — der einzige Grund für die
        Tabelle — verschwindet als Erstes."""
        hint = super().minimumSizeHint()
        breite = QFontMetrics(self.font()).horizontalAdvance("≥ 000 000") + 40
        hint.setWidth(breite)
        return hint
