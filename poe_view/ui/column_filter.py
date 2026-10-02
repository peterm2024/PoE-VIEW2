"""Der Excel-artige Spalten-Filter — für jede Tabelle, die einen will.

Peter, 2026-08-02, für die Item-Liste: "eine Art Autovervollständigen
mit Combobox über die Items in der Spalte". Und 2026-09-27 für die
Zonen-Tabelle: "Bitte auch hier nochmal so eine Art Excel-Filter
einbauen, falls ohne größeren Aufwand, sowas haben wir ja schon in der
Item-List."

**Warum eine eigene Datei und nicht weiter in ``item_table``:** Der
Rechtsklick auf einen Spaltenkopf braucht zwei Dinge — das Prüfen eines
Mini-Ausdrucks (``expression_matches``) und das Eingabefeld mit
Vervollständigung (``InlineCompleteLineEdit``). Das erste lag in
``item_table``, das zweite in ``main_window``. Und ``main_window``
importiert ``zone_table``: Ein Rückimport von dort wäre ein Kreis
gewesen. Herausgezogen wird hier also erst, nachdem der zweite Nutzer
tatsächlich da ist — genau die Regel, auf die wir uns am 2026-08-15
geeinigt haben (nicht auf Vorrat umbauen).
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtWidgets import QCompleter, QHeaderView, QLineEdit, QWidget

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Vergleichsoperator am Anfang eines Spalten-Filter-Ausdrucks
_OP_RE = re.compile(r"^\s*(<=|>=|!=|<>|<|>|=)\s*(.+)$")

# Was im leeren Eingabefeld steht — an beiden Tabellen dasselbe, damit
# niemand zweimal lernen muss, was das Feld kann.
PLACEHOLDER = "e.g. >=20, <45, =text, substring"


def first_number(text: str) -> float | None:
    """Erste Zahl im Anzeigetext ("+20%" → 20.0, "–" → None)."""
    m = _NUM_RE.search(text)
    return float(m.group().replace(",", ".")) if m else None


def expression_matches(expr: str, cell_text: str) -> bool:
    """Excel-artige Mini-Ausdrücke: ">=20", "<45", "=Beach Map", sonst
    Teilstring. Numerisch wird verglichen, sobald Operand und Zelle eine
    Zahl hergeben ("+20%" zählt als 20) — sonst Textvergleich; Zellen ohne
    Zahl ("–") fallen bei <,>,<=,>= bewusst raus (wie in Excel)."""
    m = _OP_RE.match(expr)
    if not m:
        return expr.lower() in cell_text.lower()
    op, operand = m.group(1), m.group(2).strip()
    operand_num = first_number(operand)
    cell_num = first_number(cell_text)
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


class InlineCompleteLineEdit(QLineEdit):
    """Eingabefeld, das den passenden Rest gleich hinter dem Cursor
    stehen lässt — markiert, sodass Weitertippen ihn ersetzt und Return
    oder Tab ihn übernimmt.

    Peter, 2026-08-06: "Es gibt Programme, da tippe ich Text in ein Feld
    und direkt hinter dem Cursor erscheint schon der passende Text, den
    ich nur noch durch Tab oder return bestätigen muss." Das Feld hatte
    seit 2026-08-02 bereits eine Vervollständigung, aber als Popup-Liste
    unter dem Feld — offenbar nicht das, was gemeint war, und Peter hat
    sie beim Arbeiten nicht als solche wahrgenommen.

    **Beides bleibt nebeneinander**, weil beide etwas anderes können: Die
    Inline-Ergänzung braucht einen PRÄFIX ("Main" → "MainInventory"), die
    Popup-Liste sucht per Teilstring und findet "MainInventory" auch bei
    der Eingabe "inv". Letzteres passt zum Filter selbst, der ohne
    Operator ebenfalls eine reine Teilstring-Suche ist.

    Ergänzt wird nur beim WACHSEN der Eingabe. Sonst käme man mit der
    Rücktaste nicht mehr aus einem Vorschlag heraus: Sie löscht die
    Markierung, und der Vorschlag stünde sofort wieder da."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._suggestions: list[str] = []
        # Der zuletzt vom NUTZER getippte Text — nicht der um den
        # Vorschlag ergänzte. Sonst sähe das nächste Zeichen wie eine
        # Verkürzung aus (es ersetzt ja die Markierung) und die Ergänzung
        # bliebe aus.
        self._typed = text
        self.textEdited.connect(self._suggest)

    def set_suggestions(self, values: list[str]) -> None:
        self._suggestions = values

    def _suggest(self, typed: str) -> None:
        grew = len(typed) > len(self._typed)
        self._typed = typed
        if not grew or not typed:
            return
        lowered = typed.lower()
        match = next((v for v in self._suggestions
                      if len(v) > len(typed) and v.lower().startswith(lowered)), None)
        if match is None:
            return
        # Der ganze Treffer, nicht getippter Text + Rest: Die
        # Groß-/Kleinschreibung soll die des echten Werts sein, damit im
        # Feld am Ende genau das steht, was in der Spalte vorkommt.
        self.setText(match)  # löst textEdited NICHT aus, keine Rekursion
        self.setSelection(len(typed), len(match) - len(typed))


def build_filter_edit(current: str, values: list[str],
                      parent: QWidget | None = None) -> InlineCompleteLineEdit:
    """Das fertige Eingabefeld für ein Spaltenkopf-Menü: Inline-Ergänzung
    über den Präfix UND Popup-Liste über Teilstrings.

    Zwei Wege zum selben Wert, siehe ``InlineCompleteLineEdit`` — deshalb
    beides nebeneinander. Als eigene Funktion, damit sie ohne den
    blockierenden ``QMenu.exec()`` testbar bleibt."""
    edit = InlineCompleteLineEdit(current, parent)
    edit.setPlaceholderText(PLACEHOLDER)
    if values:
        edit.set_suggestions(values)
        completer = QCompleter(values, edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        # Contains statt StartsWith: passt zum Filter selbst, der auch
        # ohne Operator eine reine Teilstring-Suche ist.
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        edit.setCompleter(completer)
    return edit


class FilterHeader(QHeaderView):
    """Ein Spaltenkopf mit einer Zeile Filterfelder unter den Namen.

    Peter, 2026-10-01, für die Zonen-Tabelle: "Schön wäre es auch, wenn
    man die Filter direkt in eine Zeile eintragen könnte, evtl eine
    kleine beschreibbare extra Tabelle oberhalb mit den Headern und
    unterhalb die Header ausblenden, so dass das nicht auffällt."

    **Warum im Kopf selbst statt als zweite Tabelle darüber:** Optisch
    ist es dasselbe — eine Zeile Felder unter den Spaltennamen. Eine
    zweite Tabelle müsste aber alles, was der Kopf von sich aus kann,
    von Hand nachziehen: jede Spaltenbreite beim Ziehen, das seitliche
    Scrollen, den Sortier-Klick, ein Ein- und Ausblenden von Spalten.
    Jede vergessene Stelle wäre eine Spalte, deren Filterfeld neben der
    falschen Spalte steht. Hier sitzen die Felder im Ansichtsbereich des
    Kopfes und werden mit ihm verschoben; ihre Lage kommt aus denselben
    Abschnittsmaßen, nach denen der Kopf sich selbst zeichnet.

    Die Spaltennamen bleiben oben in ihrer gewohnten Höhe
    (``paintSection`` bekommt nur diesen Streifen), darunter liegt die
    Feldzeile. Ein Klick in die Feldzeile sortiert nicht — er gehört dem
    Feld, auch dort, wo zwischen zwei Feldern ein Pixel frei ist."""

    filter_changed = Signal(int, str)
    # Ein Feld bekommt den Fokus — der Moment, die Vorschläge zu holen.
    # In der Item-Liste stehen bis zu 20.000 Zeilen hinter einer Spalte;
    # die Werte aller Spalten nach jedem Abruf vorab zu sammeln, kostete
    # bei jedem Takt, wofür nur das Feld zahlen soll, in das jemand tippt.
    field_focused = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._edits: list[InlineCompleteLineEdit] = []
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.sectionResized.connect(self._place_edits)
        self.sectionMoved.connect(self._place_edits)

    # --- Felder ---------------------------------------------------------- #

    def set_column_count(self, count: int, tooltip: str = "") -> None:
        """Ein Feld je Spalte anlegen (einmal, beim Aufbau)."""
        for edit in self._edits:
            edit.deleteLater()
        self._edits = []
        for col in range(count):
            edit = InlineCompleteLineEdit("", self.viewport())
            edit.setPlaceholderText("filter")
            edit.setClearButtonEnabled(True)
            if tooltip:
                edit.setToolTip(tooltip)
            edit.textChanged.connect(
                lambda text, c=col: self.filter_changed.emit(c, text))
            edit.installEventFilter(self)
            self._edits.append(edit)
        self.updateGeometries()

    def filter_edit(self, col: int) -> InlineCompleteLineEdit | None:
        return self._edits[col] if 0 <= col < len(self._edits) else None

    def filter_text(self, col: int) -> str:
        edit = self.filter_edit(col)
        return edit.text().strip() if edit is not None else ""

    def set_filter_text(self, col: int, text: str) -> None:
        edit = self.filter_edit(col)
        if edit is not None:
            edit.setText(text)

    def set_filter_text_silently(self, col: int, text: str) -> None:
        """Das Feld zeigt einen Filter, den jemand anderes schon gesetzt
        hat (ein Pin, ein gespeicherter Stand) — ohne ``filter_changed``,
        sonst liefe derselbe Filter ein zweites Mal durch."""
        edit = self.filter_edit(col)
        if edit is not None and edit.text() != text:
            edit.blockSignals(True)
            edit.setText(text)
            edit.blockSignals(False)

    def clear_filters(self) -> None:
        for edit in self._edits:
            edit.clear()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt-API)
        if event.type() == QEvent.Type.FocusIn and watched in self._edits:
            self.field_focused.emit(self._edits.index(watched))
        return super().eventFilter(watched, event)

    def set_suggestions(self, col: int, values: list[str]) -> None:
        """Vervollständigung wie im Kopfmenü der Item-Liste: inline über
        den Präfix UND als Popup über Teilstrings (§build_filter_edit)."""
        edit = self.filter_edit(col)
        if edit is None:
            return
        edit.set_suggestions(values)
        if not values:
            # Kein leerer Completer, der bei jedem Tastendruck nichts findet.
            edit.setCompleter(None)
            return
        completer = QCompleter(values, edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        edit.setCompleter(completer)

    # --- Maße und Zeichnen ----------------------------------------------- #

    def label_height(self) -> int:
        """Die Höhe, die der Kopf OHNE Feldzeile hätte."""
        return super().sizeHint().height()

    def _edit_height(self) -> int:
        return self._edits[0].sizeHint().height() if self._edits else 0

    def sizeHint(self):  # noqa: N802 (Qt-API)
        groesse = super().sizeHint()
        groesse.setHeight(groesse.height() + self._edit_height())
        return groesse

    def updateGeometries(self) -> None:  # noqa: N802 (Qt-API)
        super().updateGeometries()
        self._place_edits()

    def paintSection(self, painter, rect, logical_index) -> None:  # noqa: N802
        super().paintSection(painter, QRect(rect.x(), rect.y(), rect.width(),
                                            self.label_height()), logical_index)

    def _place_edits(self, *_args) -> None:
        oben, hoehe = self.label_height(), self._edit_height()
        for col, edit in enumerate(self._edits):
            if col >= self.count() or self.isSectionHidden(col):
                edit.hide()
                continue
            edit.setGeometry(self.sectionViewportPosition(col) + 1, oben,
                             max(self.sectionSize(col) - 2, 0), hoehe)
            edit.show()

    # --- Klicks in der Feldzeile gehören nicht dem Kopf ------------------ #

    def _in_field_row(self, event) -> bool:
        return event.position().y() >= self.label_height()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        if self._in_field_row(event):
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        if self._in_field_row(event):
            event.ignore()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        if self._in_field_row(event):
            event.ignore()
            return
        super().mouseDoubleClickEvent(event)
