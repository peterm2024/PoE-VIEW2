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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCompleter, QLineEdit, QWidget

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
