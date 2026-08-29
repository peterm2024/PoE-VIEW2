"""Item-Detail-Panel: großes Icon, Name in Rarity-Farbe, Eigenschaften
und Mods — nach Blöcken getrennt wie PoEs eigener Tooltip.

Peter, 2026-08-12: "Wir sollten unsere Item-Darstellung etwas
überarbeiten... Zumindest etwas übersichtlicher, den grafischen
Schnickschnack brauchen wir vorerst nicht." Vorher lief alles als eine
flache Liste untereinander — Eigenschaften, Anforderungen, impliziter und
explizite Mods ohne jede Trennung. Am auffälligsten daran: **welcher Mod
der implizite ist, war überhaupt nicht zu erkennen.** Im Spiel trennt
eine Linie ihn ab, hier stand er einfach als erste Zeile zwischen den
übrigen.

Deshalb dieselbe Gliederung wie im Spiel, aber ohne dessen Rahmen,
Schriftbild und Verzierung: dünne Linien (``<hr>``) zwischen den
Blöcken, sonst nichts. Der Preis dafür sind ein paar Pixel Höhe pro
Linie, und die gehen dem Tabellenbereich darüber verloren — deshalb das
Zeilenbudget unten.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from poe_view.api.models import (ENCHANT_MOD_FIELD, Item, all_extra_mod_pairs,
                                 extra_mod_lines, item_category, req_attribute,
                                 req_level)
from poe_view.services.mod_collection import BASE_STAT_KIND, base_stat_line
from poe_view.ui import mod_bar
from poe_view.ui.theme import RARITY_COLORS


def _no_mark(kind: str, line: str) -> str:
    """Die Vorgabe: keine Marke. Steht hier oben, weil sie als
    Vorgabewert zweier Signaturen beim Definieren gebraucht wird — nicht
    erst beim Aufruf."""
    return ""


@dataclass(frozen=True)
class Line:
    """Eine Zeile des Panels, in ihren zwei sehr verschiedenen Hälften.

    ``text`` ist roher Text und wird beim Zusammensetzen **escaped** —
    Item- und Mod-Texte kommen von GGGs Server, nicht von uns.

    ``mark`` ist dagegen **fertiges HTML und wird NICHT escaped**. Genau
    deshalb steht es in einem eigenen Feld und nicht vorne im Text: Die
    Balkenspalte der Mod-Sammlung (``ui/mod_bar.py``) besteht aus
    gefärbten ``<span>``-Elementen, und wären Marke und Text ein String,
    müsste hier jemand entscheiden, welcher Teil escaped wird. Diese
    Entscheidung ist der Weg, auf dem fremder Text irgendwann als Markup
    durchrutscht."""

    text: str
    mark: str = ""
    # Ebenfalls fertiges HTML, HINTER dem Text: das Tier-Etikett der
    # Mod-Datenbank (``mod_bar.tail_for``, §4.53.4). Kurz genug, dass es
    # die Umbruch-Warnung von ``_item_blocks`` praktisch nicht trifft —
    # gemessen sind 0,4 % der Tier-faehigen Zeilen laenger als 66 Zeichen.
    tail: str = ""


def _as_line(zeile: "Line | str") -> Line:
    """Ein blanker String ist eine Zeile ohne Marke. Das halten die Tests
    des Höhenbudgets lesbar, die mit ``[["Mod 1", "Mod 2"]]`` arbeiten."""
    return zeile if isinstance(zeile, Line) else Line(zeile)


# Das Höhenbudget des Panels, gezählt in ZEILENHÖHEN — und zwar für
# Textzeilen UND Trennlinien gemeinsam. Der gemeinsame Zähler ist der
# Kern der Sache: Eine ``<hr>`` kostet gemessene 16 px, also **exakt eine
# volle Zeilenhöhe**, keinen Bruchteil davon.
#
# Peter, 2026-08-13, mit einem Screenshot einer Karte: "und eine
# abgeschnittene Info...." — die letzte Mod-Zeile stand auf dem
# Rahmenrand. Die Fassung davor zählte nur Textzeilen (14) und schlug für
# die fünf möglichen Linien plus die Namenszeile pauschal drei Zeilen
# drauf. Für ein Item mit sechs Blöcken fehlten damit drei Zeilenhöhen,
# und weil die Kürzung ebenfalls nur Textzeilen zählte, MELDETE sie es
# nicht einmal — genau das stille Abschneiden, das dieser Umbau
# abschaffen sollte, nur durch eine andere Tür.
#
# Neu gemessen über 59.043 Items aus Peters Bestand, in der Einheit, auf
# die es ankommt (Textzeilen + Trennlinien):
#
#   Einheiten | Panelhöhe | abgedeckt
#          14 |   268 px  |  84,1 %
#          16 |   300 px  |  91,8 %   ← die bisherige Höhe
#          17 |   316 px  |  95,5 %   ← jetzt
#          18 |   332 px  |  97,6 %
#          20 |   364 px  |  99,3 %
#
# 17 kostet die Tabelle 16 Pixel gegenüber vorher und holt die Abdeckung
# auf den Stand, der die ganze Zeit behauptet war. Die nächsten zwei
# Prozent kosten nochmal so viel; das längste Item braucht 29 Einheiten,
# dafür Platz vorzuhalten wäre absurd.
_MAX_UNITS = 17

# Was eine Trennlinie kostet, in Zeilenhöhen. Gemessen (Qt rendert
# ``<hr>`` mit eigenem Abstand), nicht geschätzt — die Schätzung war der
# Fehler oben.
_SEPARATOR_UNITS = 1

# Breite in Zeichen, auf die das Panel ausgelegt ist. Gemessen, nicht
# gegriffen: Über alle 201.426 Mod-Zeilen in Peters echtem Bestand liegt
# der Median bei 34 Zeichen, 90 % passen in 58, **95 % in 68**. Die
# restlichen 5 % brechen um (das Label hat Wortumbruch), sie werden nicht
# abgeschnitten — bis hinauf zu einer 381 Zeichen langen Jewel-Zeile,
# für die keine sinnvolle Panelbreite existiert.
#
# Peter, 2026-08-13: "Die Trennlinienposition können wir ja anhand der
# Zeilenbreite berechnen." Genau das passiert hier, statt wie zuvor
# 900/300 Pixel zu raten.
_TYPICAL_LINE_CHARS = 68

# Die Namenszeile über dem Text. Sie steht in einem eigenen Label und
# gehört deshalb nicht ins Budget, wohl aber in die Höhe.
_NAME_LINE_UNITS = 1


class ItemDetail(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._icon = QLabel()
        self._icon.setFixedSize(64, 64)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name = QLabel("No item selected")
        self._name.setStyleSheet("font-weight: 600; font-size: 13px;")
        self._props = QLabel("")
        self._props.setWordWrap(True)
        self._props.setTextFormat(Qt.TextFormat.RichText)

        text_col = QVBoxLayout()
        text_col.addWidget(self._name)
        text_col.addWidget(self._props)
        text_col.addStretch()

        layout = QHBoxLayout(self)
        layout.addWidget(self._icon)
        layout.addLayout(text_col, stretch=1)

        # Feste Höhe statt einer, die am Inhalt hängt (Peter, 2026-08-13:
        # "Können wir den XP-Bereich unten ausrichten/fixieren? Dann
        # wackelt das beim Item-Wechsel nicht so rum"). Ein Ring mit zwei
        # Mods und ein Unique mit acht ließen das Panel sonst bei jedem
        # Klick springen — und mit ihm das Leveling-Feld daneben und den
        # unteren Rand der Tabelle darüber. Bemessen auf den Vollausbau
        # (_MAX_LINES), damit auch das längste Item nichts verschiebt.
        self.setFixedHeight(self._full_height())

    def _full_height(self) -> int:
        """Höhe für den größtmöglichen Inhalt. Mindestens so hoch wie das
        Icon, sonst wäre das Panel bei einem Currency-Item ohne Mods
        kleiner als sein eigenes Bild."""
        line = self._props.fontMetrics().lineSpacing()
        margins = self.layout().contentsMargins()
        rand = margins.top() + margins.bottom() + self.layout().spacing()
        text = (_MAX_UNITS + _NAME_LINE_UNITS) * line
        return max(self._icon.height(), text) + rand

    def preferred_width(self) -> int:
        """Breite, bei der eine typische Mod-Zeile (§_TYPICAL_LINE_CHARS)
        ohne Umbruch hineinpasst — die Grundlage für die Position des
        Splitters darunter. ``averageCharWidth`` statt einer gemessenen
        Beispielzeile: Der Wert hängt sonst daran, welchen Satz man
        zufällig als Vorlage nimmt.

        Die Balkenspalte kommt dazu, statt vom Text abgezogen zu werden:
        Sie steht VOR der Mod-Zeile, also braucht dieselbe Zeile jetzt
        entsprechend mehr Platz. Ohne diesen Summanden würde die Spalte
        die 68 Zeichen anknabbern, für die das Panel bemessen ist."""
        metrics = self._props.fontMetrics()
        margins = self.layout().contentsMargins()
        return (self._icon.width() + self.layout().spacing()
                + _TYPICAL_LINE_CHARS * metrics.averageCharWidth()
                + metrics.horizontalAdvance(mod_bar.CELL * (mod_bar.BAR_CELLS + 2))
                + margins.left() + margins.right())

    def show_item(self, item: Item, pixmap: QPixmap | None,
                  mark: Callable[[str, str], str] = _no_mark,
                  tail: Callable[[str, str], str] = _no_mark) -> None:
        colour = RARITY_COLORS.get(item.frameType, "#e8e6e3")
        tags = [tag for tag, present in
                (("Unidentified", not item.identified), ("Corrupted", item.corrupted))
                if present]
        suffix = f"  [{', '.join(tags)}]" if tags else ""
        self._name.setText(item.display_name + suffix)
        self._name.setStyleSheet(f"font-weight:600; font-size:13px; color:{colour};")
        self._props.setText(_blocks_to_html(_item_blocks(item, mark, tail)))

        if pixmap:
            self._icon.setPixmap(pixmap.scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self._icon.clear()


def _item_blocks(item: Item,
                 mark: Callable[[str, str], str] = _no_mark,
                 tail: Callable[[str, str], str] = _no_mark) -> list[list[Line]]:
    """Die Textblöcke eines Items in der Reihenfolge des Spiels. Reine
    Datenaufbereitung ohne Qt — dadurch ohne Fenster testbar.

    Leere Blöcke bleiben drin und werden erst beim Zusammensetzen
    verworfen; das hält die Reihenfolge hier lesbar.

    ``mark`` liefert zu jeder Mod-Zeile die Balkenspalte der
    Mod-Sammlung (``ui/mod_bar.py``, §4.52.2) als fertiges HTML.
    **Vorangestellt und von fester Breite**, und das ist keine
    Geschmacksfrage: Das Panel bricht lange Zeilen um (``setWordWrap``),
    sein Höhenbudget zählt aber Zeilen, nicht umgebrochene Zeilen. Ein
    angehängter Text wie "deine 41–96" würde genau die längsten
    Mod-Zeilen umbrechen lassen und das Panel still über seine feste Höhe
    schieben — derselbe Fehler, der die Anzeige schon zweimal gekostet
    hat (§_blocks_to_html). Die feste Breite ist der zweite Teil davon:
    Eine Spalte, die je nach Inhalt schmaler wird, verschöbe den
    Textanfang von Zeile zu Zeile.

    ``tail`` liefert das Tier-Etikett HINTER der Zeile (§4.53.4) — die
    eine, bewusst eingegangene Ausnahme von der Regel oben: zwei bis
    fünf Zeichen, und gemessen an Peters Bestand sind nur 0,4 % der
    Tier-faehigen Zeilen ueberhaupt laenger als 66 Zeichen."""
    kind = [item.rarity + (f" · {item.typeLine}" if item.name else "")]

    # Die Hauptwerte (Armour, Physical Damage, …) bekommen dieselbe
    # Balkenspalte wie die Mod-Zeilen (§4.52.8); die übrigen Eigenschaften
    # (Quality, Weapon Range) eine leere Spalte derselben Breite, damit
    # der Block bündig bleibt. Mit ``_no_mark`` bleibt beides leer.
    kategorie = item_category(item) or ""
    properties = [Line(prop.display_text,
                       mark(BASE_STAT_KIND, base_stat_line(kategorie, prop) or ""))
                  for prop in item.properties if prop.display_value]

    requirements = []
    if item.ilvl:
        requirements.append(f"iLvl {item.ilvl}")
    if req_level(item):
        requirements.append(f"Req. Lvl {req_level(item)}")
    for label in ("Str", "Dex", "Int"):
        value = req_attribute(item, label)
        if value:
            requirements.append(f"Req. {label} {value}")

    # Verzauberung über den impliziten Mods, die übrigen Zusatzlisten bei
    # den expliziten — dieselbe Aufteilung wie im Item-Textexport
    # (§4.38), damit Anzeige und Zwischenablage nicht auseinanderlaufen.
    def markiert(feld: str, zeilen) -> list[Line]:
        return [Line(zeile, mark(feld, zeile), tail(feld, zeile)) for zeile in zeilen]

    return [
        [Line(zeile) for zeile in kind],
        properties,
        [Line(" · ".join(requirements))] if requirements else [],
        markiert(ENCHANT_MOD_FIELD, extra_mod_lines(item, ENCHANT_MOD_FIELD)),
        markiert("implicitMods", item.implicit_mods),
        markiert("explicitMods", item.explicit_mods)
        + [Line(zeile, mark(feld, zeile), tail(feld, zeile))
           for feld, zeile in all_extra_mod_pairs(item)],
    ]


def _blocks_to_html(blocks: Sequence[Sequence[Line | str]]) -> str:
    """Blöcke zu HTML, getrennt durch ``<hr>``. Kürzt auf ``_MAX_UNITS``
    und sagt es dann auch — stilles Abschneiden war der eigentliche
    Mangel der Fassung davor, und danach noch einmal der Grund, warum
    Peters Karte über den Rand lief: Gezählt werden muss das, was Platz
    KOSTET, und das sind Textzeilen und Trennlinien zusammen."""
    gefuellt = [block for block in blocks if block]
    noetig = (sum(len(block) for block in gefuellt)
              + max(0, len(gefuellt) - 1) * _SEPARATOR_UNITS)
    # Passt nicht alles, braucht der Hinweis selbst eine Zeile — sonst
    # schiebt ausgerechnet er das Panel über seine feste Höhe. Vorher
    # entschieden, weil es sich hinterher nicht mehr sauber nachrechnen
    # lässt.
    budget = _MAX_UNITS if noetig <= _MAX_UNITS else _MAX_UNITS - 1

    kept: list[list[str]] = []
    weggelassen = 0
    for block in gefuellt:
        trenner = _SEPARATOR_UNITS if kept else 0
        frei = budget - trenner
        if frei <= 0:
            weggelassen += len(block)
            continue
        genommen = block[:frei]
        kept.append([zeile.mark + escape(zeile.text) + zeile.tail
                     for zeile in map(_as_line, genommen)])
        weggelassen += len(block) - len(genommen)
        budget -= trenner + len(genommen)
    html = "<hr>".join("<br>".join(block) for block in kept)
    if weggelassen:
        html += (f"<br><i>… {weggelassen} more "
                 f"(double-click the item for the full view)</i>")
    return html
