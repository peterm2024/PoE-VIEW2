"""Sockel-Gems als Fortschrittsbalken über dem XP-Graphen.

Peter, 2026-08-13: "Oberhalb des XP-Graphen machen wir einen Bereich in
dem die XP als vertikale Linie je Gem zur nächsten Stufe prozentual
angegeben sind und einen dunklen Bereich mit hellem Bereich füllen ...
Dadurch sollte man gut erkennen können ob ein Gem fertig auf Stufe 20
gelevelt ist."

**Die schwierigste Frage daran beantwortet GGG selbst.** "Ist das Gem
fertig?" müsste man eigentlich aus Stufe, Gem-Art und Erfahrung
herleiten — ein Awakened-Gem ist bei 5 fertig, ein normales bei 20, ein
korrumpiertes kann bei 21 stehen. Nichts davon ist nötig: Über Peters
449 Sockel-Gems (16 Charaktere, 2026-08-13) steht die Stufe im Klartext
als ``"20 (Max)"``, ``"5 (Max)"``, ``"1 (Max)"``, und genau diesen 226
Gems fehlt zugleich das ``Experience``-Feld. Beide Merkmale zeigen
dasselbe an, und keines muss geraten werden.

Damit drei Zustände, alle drei aus den Daten belegt:

- **Fertig** (226 von 449): Stufe trägt "(Max)", kein Erfahrungsfeld.
  Voller Balken.
- **Wartet auf einen Klick** (65): Balken voll, aber nicht Max. Gems
  steigen in PoE nicht von selbst auf (`poe-verhalten.md` §4) — das ist
  Charakterstärke, die nur auf einen Mausklick wartet. Bekommt deshalb
  eine eigene Markierung; ohne sie sähe es aus wie "fertig".
- **Am Leveln** (157): Der helle Teil ist der Fortschritt zur nächsten
  Stufe.

Die Aufbereitung (`gem_progress_of`) ist eine reine Funktion über
``Item``-Objekte: ohne Qt prüfbar, und die Zeichenroutine bekommt nur
noch fertige Werte.
"""

from __future__ import annotations

from typing import NamedTuple, Sequence

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from poe_view.api.models import Item
from poe_view.ui.theme import (DASH_WARN, GEM_COLOR_OTHER, GEM_COLORS, blend,
                               dimmed_text)

# Maße eines Balkens. Peters Vorgabe waren 3-5 px Breite; 5 plus 2 Lücke
# trägt auch den vollsten Charakter in Peters Bestand (33 Gems → 231 px)
# und bleibt einzeln anklickbar breit genug für einen Tooltip.
_BAR_W = 5
_BAR_GAP = 2

# Höhe des Streifens. Peter schlug 75 px vor; 60 lassen dem Graphen
# darunter mehr Luft, ohne dass ein Drittel-Fortschritt undeutlich wird
# (bei 60 px ist ein Prozent noch 0,6 px, die Auflösung reicht also
# weiter als das Auge).
BAR_HEIGHT = 60

# Die Markierung für "wartet auf einen Klick": ein Streifen quer über den
# Kopf des Balkens, in der Warnfarbe des Dashboards. Dieselbe Bedeutung
# wie dort — hier stimmt etwas nicht von selbst, es braucht dich.
_READY_CAP_H = 3

# Wie dunkel der noch nicht gefüllte Teil ist. Dunkel genug, dass der
# helle Teil klar heraussticht, hell genug, dass die Farbe des Gems noch
# erkennbar bleibt — sonst wäre der leere Balken nur ein grauer Strich.
_EMPTY_DIM = 0.68


class GemProgress(NamedTuple):
    """Ein Sockel-Gem, wie der Balken es braucht."""

    name: str
    colour: str          # GGGs ``colour``: S/D/I, sonst unbekannt
    progress: float      # 0…1 zur nächsten Stufe
    level: str           # Klartext wie "19" oder "20 (Max)"
    maxed: bool
    ready: bool          # voll, aber nicht Max → wartet auf den Klick

    @property
    def tooltip(self) -> str:
        if self.maxed:
            return f"{self.name} — level {self.level}"
        if self.ready:
            return f"{self.name} — level {self.level}, ready to level up"
        return f"{self.name} — level {self.level}, {self.progress:.0%} to next"


def _level_text(gem: dict) -> str:
    for prop in gem.get("properties") or []:
        if isinstance(prop, dict) and prop.get("name") == "Level":
            values = prop.get("values") or []
            if values:
                return str(values[0][0])
    return "?"


def _experience(gem: dict) -> dict | None:
    for prop in gem.get("additionalProperties") or []:
        if isinstance(prop, dict) and prop.get("name") == "Experience":
            return prop
    return None


def gem_progress_of(items: Sequence[Item]) -> list[GemProgress]:
    """Alle Sockel-Gems der übergebenen Items, in der Reihenfolge, in der
    sie stecken — dieselbe wie in der Paperdoll, damit sich ein Balken
    ohne Suchen zuordnen lässt."""
    gems: list[GemProgress] = []
    for item in items:
        for gem in getattr(item, "socketedItems", None) or []:
            if not isinstance(gem, dict):
                continue
            level = _level_text(gem)
            experience = _experience(gem)
            maxed = "(max)" in level.lower()
            # Ohne Erfahrungsfeld UND ohne "(Max)" wissen wir nichts —
            # dann ein leerer Balken statt eines vollen. Betrifft in
            # Peters Bestand genau ein Gem von 449, dessen Stufe die API
            # gar nicht mitliefert; ein voller Balken hieße dort "fertig",
            # und das wäre eine Behauptung ohne Grundlage.
            if maxed:
                progress = 1.0
            elif experience:
                progress = float(experience.get("progress") or 0.0)
            else:
                progress = 0.0
            gems.append(GemProgress(
                name=str(gem.get("typeLine") or gem.get("baseType") or "?"),
                colour=str(gem.get("colour") or ""),
                progress=min(max(progress, 0.0), 1.0),
                level=level,
                maxed=maxed,
                ready=bool(experience) and progress >= 1.0 and not maxed))
    return gems


def gem_colour(colour: str) -> str:
    return GEM_COLORS.get(colour, GEM_COLOR_OTHER)


class GemProgressBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._gems: list[GemProgress] = []
        self.setFixedHeight(BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_gems(self, gems: Sequence[GemProgress]) -> None:
        self._gems = list(gems)
        self.setVisible(bool(self._gems))
        self.update()

    def clear(self) -> None:
        self.set_gems([])

    def _gem_at(self, x: int) -> GemProgress | None:
        index = int(x // (_BAR_W + _BAR_GAP))
        return self._gems[index] if 0 <= index < len(self._gems) else None

    def event(self, event: QEvent) -> bool:
        """Tooltip je Balken. Ohne ihn wäre der Streifen zwar hübsch, aber
        stumm — bei dreißig Balken nebeneinander ist "welches Gem ist
        das?" die erste Frage."""
        if event.type() == QEvent.Type.ToolTip:
            gem = self._gem_at(event.pos().x())
            if gem is not None:
                QToolTip.showText(event.globalPos(), gem.tooltip, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt-Namensschema)
        painter = QPainter(self)
        try:
            height = self.height()
            for index, gem in enumerate(self._gems):
                x = index * (_BAR_W + _BAR_GAP)
                if x + _BAR_W > self.width():
                    break        # lieber abschneiden als stauchen
                hell = QColor(gem_colour(gem.colour))
                dunkel = blend(hell, QColor("#000000"), _EMPTY_DIM)
                gefuellt = round(height * gem.progress)
                painter.fillRect(QRectF(x, 0, _BAR_W, height - gefuellt), dunkel)
                painter.fillRect(QRectF(x, height - gefuellt, _BAR_W, gefuellt), hell)
                if gem.ready:
                    painter.fillRect(QRectF(x, 0, _BAR_W, _READY_CAP_H),
                                     QColor(DASH_WARN))
            if not self._gems:
                painter.setPen(dimmed_text(self.palette()))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                                 "No socketed gems")
        finally:
            painter.end()
