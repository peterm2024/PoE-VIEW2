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

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from poe_view.api.models import (ENCHANT_MOD_FIELD, Item, all_extra_mod_lines,
                                 extra_mod_lines, req_attribute, req_level)
from poe_view.ui.theme import RARITY_COLORS

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
        zufällig als Vorlage nimmt."""
        metrics = self._props.fontMetrics()
        margins = self.layout().contentsMargins()
        return (self._icon.width() + self.layout().spacing()
                + _TYPICAL_LINE_CHARS * metrics.averageCharWidth()
                + margins.left() + margins.right())

    def show_item(self, item: Item, pixmap: QPixmap | None) -> None:
        colour = RARITY_COLORS.get(item.frameType, "#e8e6e3")
        tags = [tag for tag, present in
                (("Unidentified", not item.identified), ("Corrupted", item.corrupted))
                if present]
        suffix = f"  [{', '.join(tags)}]" if tags else ""
        self._name.setText(item.display_name + suffix)
        self._name.setStyleSheet(f"font-weight:600; font-size:13px; color:{colour};")
        self._props.setText(_blocks_to_html(_item_blocks(item)))

        if pixmap:
            self._icon.setPixmap(pixmap.scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self._icon.clear()


def _item_blocks(item: Item) -> list[list[str]]:
    """Die Textblöcke eines Items in der Reihenfolge des Spiels. Reine
    Datenaufbereitung ohne Qt — dadurch ohne Fenster testbar.

    Leere Blöcke bleiben drin und werden erst beim Zusammensetzen
    verworfen; das hält die Reihenfolge hier lesbar."""
    kind = [item.rarity + (f" · {item.typeLine}" if item.name else "")]

    properties = [prop.display_text for prop in item.properties if prop.display_value]

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
    return [
        kind,
        properties,
        [" · ".join(requirements)] if requirements else [],
        extra_mod_lines(item, ENCHANT_MOD_FIELD),
        list(item.implicit_mods),
        list(item.explicit_mods) + all_extra_mod_lines(item),
    ]


def _blocks_to_html(blocks: list[list[str]]) -> str:
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
        kept.append([escape(line) for line in genommen])
        weggelassen += len(block) - len(genommen)
        budget -= trenner + len(genommen)
    html = "<hr>".join("<br>".join(block) for block in kept)
    if weggelassen:
        html += (f"<br><i>… {weggelassen} more "
                 f"(double-click the item for the full view)</i>")
    return html
