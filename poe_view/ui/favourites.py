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

**Die Reihenfolge gehört dem Nutzer.** Sortiert wird nie automatisch,
weil eine Zeile, die je nach Bestand die Position wechselt, sich nicht
"auf einen Blick" ablesen lässt. Umgekehrt heißt das, dass sie sich von
Hand setzen lassen muss — per Ziehen in der Tabelle (§``move_row``,
Peter 2026-08-16).
"""

from __future__ import annotations

from typing import Iterable, NamedTuple, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (QHeaderView, QMenu, QSizePolicy, QTableWidget,
                               QTableWidgetItem)

from poe_view.api.models import Item

# Zeilenhöhe und Schrift bewusst kleiner als in der Haupttabelle: Die
# Tabelle steht neben dem Textblock des Leveling-Felds und teilt sich
# dessen Höhe — je Zeile weniger Platz heißt hier mehr Zeilen.
ROW_HEIGHT = 18
FONT_SIZE = 8

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
    "auf einen Blick" ablesen — man müsste sie jedes Mal suchen. Geändert
    wird sie durch Ziehen in der Tabelle (§``FavouritesTable.move_row``).

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


def reordered(names: Sequence[str], von: int, ziel: int) -> list[str]:
    """``names`` mit dem Eintrag an Position ``von``, eingefügt VOR
    Position ``ziel``.

    ``ziel`` ist eine Einfügestelle, keine Zeile: Bei ``len(names)`` geht
    der Eintrag ans Ende. Das ist der Grund für die Korrektur ``ziel > von``
    — nach dem Herausnehmen rutscht alles dahinter eine Stelle vor, und
    ohne sie landete ein nach unten gezogener Eintrag immer eine Position
    zu tief.

    Eigene Funktion statt Rechnerei im ``dropEvent``: Die
    Off-by-one-Fälle (an dieselbe Stelle, ans Ende, über sich selbst
    hinweg) lassen sich so ohne echtes Drag&Drop prüfen."""
    if not 0 <= von < len(names):
        return list(names)
    rest = list(names)
    name = rest.pop(von)
    ziel = min(max(ziel, 0), len(names))
    rest.insert(ziel - 1 if ziel > von else ziel, name)
    return rest


class FavouritesTable(QTableWidget):
    """Zwei Spalten ohne Kopfzeile: Name links, Menge rechts."""

    # Rechtsklick in der Tabelle selbst. Ohne diesen Weg hätte die
    # Funktion eine Sackgasse: Ein beobachtetes Item, von dem gerade
    # nichts mehr da ist, steht in keiner Item-Tabelle mehr — und wäre
    # über den Rechtsklick dort nie wieder zu entfernen.
    remove_requested = Signal(str)

    # Die neue Reihenfolge nach dem Ziehen, als Namensliste. Peter,
    # 2026-08-16: "Könnten wir die Fav-Item-Liste per Drag&Drop
    # umsortieren?" Die Reihenfolge stammt vom Nutzer und wird bewusst
    # nicht nach Menge sortiert (§favourite_rows) — dann muss er sie auch
    # ändern können, ohne die halbe Liste neu anzulegen.
    order_changed = Signal(list)

    def __init__(self) -> None:
        super().__init__(0, 2)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # Eine Zeile auf einmal, und die ganze Zeile: Qts ``startDrag``
        # zieht, was ausgewählt IST — mit ``NoSelection`` (dem früheren
        # Wert) käme kein Ziehen zustande, weil die Auswahl leer bliebe.
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # ``NoFocus`` bleibt: Die Auswahl wird dadurch in der gedämpften
        # Inaktiv-Farbe gezeichnet — sichtbar genug beim Ziehen, ohne die
        # kleine Tabelle dauerhaft mit einem blauen Balken zu belegen.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setDropIndicatorShown(True)
        # Setzt von sich aus ``dragEnabled`` und ``acceptDrops`` auf dem
        # Widget UND auf dem Viewport (nachgemessen 2026-08-16) — die
        # drei einzeln nachzuziehen sähe gründlich aus, änderte aber
        # nichts.
        self.setDragDropMode(QTableWidget.DragDropMode.InternalMove)
        # Ohne das ersetzt Qt die Zielzeile, statt davor einzufügen — aus
        # dem Umsortieren würde ein Überschreiben.
        self.setDragDropOverwriteMode(False)
        self._drag_name = ""
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
        # Senkrecht ``Expanding`` und keine feste Höhe (Peter,
        # 2026-08-16: "die volle uns verbliebene Höhe"): Die Tabelle
        # füllt neben dem Textblock aus, was dort da ist. Wie hoch das
        # ist, entscheidet der Textblock — passen nicht alle Zeilen
        # hinein, wird gescrollt, statt dem Graphen darunter Platz
        # wegzunehmen.
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(ROW_HEIGHT + 2)
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
            # Ziehbar, aber selbst kein Ablageziel: Ohne
            # ``ItemIsDropEnabled`` fällt ein Eintrag ZWISCHEN die Zeilen
            # statt auf eine, und nur so zeigt Qt den Einfügestrich.
            for feld in (name, menge):
                feld.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsDragEnabled)
            self.setItem(zeile, 0, name)
            self.setItem(zeile, 1, menge)
        self.setVisible(bool(self._rows))

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

    # --- Umsortieren per Ziehen ---------------------------------------- #

    def move_row(self, von: int, ziel: int) -> bool:
        """Zeile ``von`` vor die Einfügestelle ``ziel`` schieben.

        Gibt zurück, ob sich dabei etwas geändert hat. Als eigene Methode
        herausgezogen, damit sich das Umsortieren prüfen lässt, ohne ein
        echtes Drag&Drop zu erzeugen — dasselbe Vorgehen wie bei
        ``build_context_menu``.

        Die Tabelle ordnet sich selbst sofort um und meldet es erst
        danach. Wer nur meldete, überließe die Anzeige dem Empfänger des
        Signals; die Zeile bliebe bis zur nächsten Zählung dort liegen,
        wo sie war, und das Ziehen sähe aus, als hätte es nicht
        funktioniert."""
        alt = [row.name for row in self._rows]
        neu = reordered(alt, von, ziel)
        if neu == alt:
            return False
        nach_name = {row.name: row for row in self._rows}
        self.set_rows([nach_name[name] for name in neu])
        self.order_changed.emit(neu)
        return True

    def drop_index(self, y: int) -> int:
        """Vor welche Zeile fällt ein Eintrag, der bei ``y`` losgelassen
        wird?

        Unterhalb der letzten Zeile ans Ende: Sonst wäre ausgerechnet die
        letzte Position nur zu erreichen, indem man auf die untere Hälfte
        der letzten Zeile zielt. Innerhalb einer Zeile entscheidet die
        Mitte, damit sich ein Eintrag auch VOR die erste Zeile setzen
        lässt."""
        zeile = self.rowAt(y)
        if zeile < 0:
            return self.rowCount()
        mitte = self.rowViewportPosition(zeile) + self.rowHeight(zeile) / 2
        return zeile if y < mitte else zeile + 1

    def remember_drag_row(self) -> None:
        """Beim Aufnehmen den gezogenen NAMEN merken, nicht die
        Zeilennummer.

        Qts Drag läuft in einer eigenen Ereignisschleife: Zwischen
        Aufnehmen und Ablegen kommt die Mengen-Zählung durch und ruft
        ``set_rows`` auf. Nachgemessen (2026-08-16) überlebt die
        Zeilennummer das zwar — sie zeigt danach aber unter Umständen auf
        einen ANDEREN Eintrag, etwa wenn währenddessen ein Favorit weiter
        oben entlassen wurde. Nur bei leerer Liste wird sie -1. Der Name
        ist die einzige Angabe, die den Vorgang übersteht.

        Eigene Methode, weil ``startDrag`` im Test nicht aufrufbar ist:
        Es öffnet eine modale Schleife und würde den Lauf anhalten."""
        self._drag_name = self.name_at(self.currentRow())

    def _dragged_row(self) -> int:
        """Wo steht der gezogene Eintrag jetzt? ``-1``, wenn er inzwischen
        verschwunden ist — dann wird nichts verschoben."""
        if not self._drag_name:
            return self.currentRow()
        for index, row in enumerate(self._rows):
            if row.name == self._drag_name:
                return index
        return -1

    def startDrag(self, actions) -> None:  # noqa: N802 — Qt-Namensschema
        self.remember_drag_row()
        super().startDrag(actions)

    def _accept_internal(self, event) -> None:
        """Nur die eigenen Zeilen annehmen. Ein Item aus der Haupttabelle
        hierher zu ziehen sähe aus, als würde es aufgenommen — dafür gibt
        es den Rechtsklick, und ein stillschweigend verworfener Ablauf
        wäre schlimmer als gar keiner."""
        if event.source() is self:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 — Qt-Namensschema
        self._accept_internal(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 — Qt-Namensschema
        self._accept_internal(event)

    def dropEvent(self, event) -> None:  # noqa: N802 — Qt-Namensschema
        """Selbst umsortieren statt Qt machen zu lassen.

        Qts ``InternalMove`` schiebt bei einer Tabelle ZELLEN und lässt
        dabei leere Zeilen zurück; gemeint sind hier aber ganze Zeilen.
        Deshalb wird das Ereignis hier abschließend behandelt und
        ``super()`` nicht aufgerufen."""
        if event.source() is not self:
            event.ignore()
            return
        von = self._dragged_row()
        self._drag_name = ""
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.move_row(von, self.drop_index(int(event.position().y())))

    def sizeHint(self):  # noqa: N802 — Qt-Namensschema
        """Senkrecht nur eine Zeile verlangen, obwohl das Widget beliebig
        viele trägt.

        Der Unterschied entscheidet über die Aufteilung des Panels: Qt
        gibt einer Zeile die Höhe ihres größten ``sizeHint``. Mit dem
        Vorgabewert einer ``QTableWidget`` (gemessen 164 px) hätte die
        Tabelle den Graphen darunter auf 60 px zusammengedrückt. Gefragt
        war das Gegenteil — die Tabelle soll die Höhe FÜLLEN, die der
        Textblock daneben ohnehin belegt, und nicht selbst welche
        einfordern. Was dann nicht hineinpasst, wird gescrollt."""
        hint = super().sizeHint()
        hint.setHeight(ROW_HEIGHT + 2)
        return hint

    def minimumSizeHint(self):  # noqa: N802 — Qt-Namensschema
        """Genug Platz für die Mengenspalte plus ein paar Zeichen Name.

        Ohne diese Untergrenze drückt der Splitter die Tabelle bei engem
        Fenster auf null, und die Zahl — der einzige Grund für die
        Tabelle — verschwindet als Erstes."""
        hint = super().minimumSizeHint()
        breite = QFontMetrics(self.font()).horizontalAdvance("≥ 000 000") + 40
        hint.setWidth(breite)
        hint.setHeight(ROW_HEIGHT + 2)
        return hint
