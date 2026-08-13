"""XP/h-Verlauf im Leveling-Feld: ein Balken je abgeschlossenem Abschnitt.

Peter, 2026-08-13: "Wir zeichnen einen Graph über die letzten 3 Stunden,
das sollte eigentlich reichen. Die meisten Gamer schließen eine Map
innerhalb von 5 Minuten ab. Die berechnete XP/h des letzten Abschnitts
schreiben wir einfach in den Graph."

Damit ist die Frage beantwortet, an der der Graph seit dem 2026-08-12
hing (ToDo: "Was kommt auf die x-Achse?"). GGG veröffentlicht die
Erfahrung nur beim Zonenwechsel, rund achtmal pro Stunde (gemessen,
`poe-verhalten.md` §3) — eine Kurve über Momentanwerte gibt es also gar
nicht zu zeichnen. Was es gibt, ist **pro Abschnitt eine fertig
gemessene Rate**, und die hat neben ihrem Wert auch eine Dauer.

Deshalb Balken statt Linie, und zwar über die tatsächlich gemessene
Zeitspanne: Ein Balken beginnt beim Betreten der Zone und endet bei der
Veröffentlichung. Das hat zwei Vorteile gegenüber einem Punkt je
Veröffentlichung:

- Die Breite zeigt, wie lange der Abschnitt gedauert hat. Eine
  Zehn-Minuten-Map und ein Zwei-Minuten-Trial sehen verschieden aus,
  obwohl beide einen Wert liefern.
- **Die Lücken sind echt.** Wo nichts gezeichnet ist, wurde keine
  Erfahrung gemacht — Pause, Stadt, Truhen sortieren. Eine durchgezogene
  Linie müsste dort etwas behaupten.

Die Rechnung (`graph_layout`) steht bewusst als reine Funktion neben dem
Widget: Sie lässt sich ohne Fenster und ohne Bildvergleich prüfen, und
Fehler in einer Zeichenroutine findet man sonst nur mit dem Auge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from poe_view.ui.theme import DASH_BAD, DASH_OK, dimmed_text

# Peters Vorgabe: drei Stunden. Ein Spielabend passt damit größtenteils
# ins Bild, und ein Balken einer Fünf-Minuten-Map ist bei üblichen
# Panelbreiten noch ein paar Pixel breit (bei 300 px Panelbreite rund
# acht Pixel für fünf Minuten).
GRAPH_SPAN_S = 3 * 3600.0

# Mindestmaße, damit ein sehr kurzer Abschnitt oder eine sehr kleine Rate
# nicht auf null Pixel zusammenfällt und dadurch unsichtbar wird.
_MIN_BAR_W = 2.0
_MIN_BAR_H = 1.0

# Untergrenze für die Höhe des Graphen. Darunter lohnt die Zeichnung
# nicht mehr — das Leveling-Feld gibt bei der festen Panelhöhe aus §4.39
# rund 180 px her, der Text darüber nimmt vier Zeilen.
_MIN_HEIGHT = 60


class XpPoint(NamedTuple):
    """Ein abgeschlossener Abschnitt: ``at`` ist der Zeitpunkt der
    Veröffentlichung (``time.monotonic()``), ``seconds`` die Dauer, auf
    die sich die Rate bezieht (in der Regel die Verweildauer in der
    verlassenen Zone, siehe ``_XpWatch``), ``rate`` die daraus errechnete
    XP/h — genau die Zahl, die auch im Leveling-Feld steht."""

    at: float
    seconds: float
    rate: float


@dataclass(frozen=True)
class Layout:
    """Fertige Geometrie für ``paintEvent``. ``bars`` sind
    ``(x, y, w, h, rate)`` in Widget-Koordinaten, ``zero_y`` die Höhe der
    Null-Linie (bei ausschließlich positiven Raten der untere Rand)."""

    bars: list[tuple[float, float, float, float, float]]
    zero_y: float
    peak: float
    trough: float


def visible_points(points: Sequence[XpPoint], now: float,
                   span_s: float = GRAPH_SPAN_S) -> list[XpPoint]:
    """Die Abschnitte, die noch ins Fenster fallen. Maßgeblich ist das
    ENDE eines Abschnitts: Ein Balken, der links aus dem Bild
    hinauswandert, wird beschnitten statt verworfen — sonst verschwände
    eine lange Map schlagartig, statt langsam hinauszulaufen."""
    return [p for p in points if p.at > now - span_s]


def graph_layout(points: Sequence[XpPoint], now: float, width: float, height: float,
                 span_s: float = GRAPH_SPAN_S) -> Layout:
    """Balken für das Zeitfenster ``span_s``, rechts endend beim Jetzt.

    Die y-Achse skaliert auf die höchste sichtbare Rate — eine feste
    Obergrenze gibt es nicht, weil die sinnvolle Größenordnung zwischen
    einem Charakter in Akt 2 und einem in den Maps um Zehnerpotenzen
    auseinanderliegt. Negative Raten (ab Akt 5 kostet der Tod Erfahrung)
    hängen unter der Null-Linie, statt herausgefiltert zu werden."""
    shown = visible_points(points, now, span_s)
    if not shown or width <= 0 or height <= 0:
        return Layout([], height, 0.0, 0.0)

    peak = max(0.0, max(p.rate for p in shown))
    trough = min(0.0, min(p.rate for p in shown))
    spread = (peak - trough) or 1.0
    zero_y = height * peak / spread

    bars: list[tuple[float, float, float, float, float]] = []
    for point in shown:
        end = min(width, width - (now - point.at) / span_s * width)
        start = min(end - max(point.seconds, 0.0) / span_s * width, end - _MIN_BAR_W)
        x = max(0.0, start)
        w = max(end - x, _MIN_BAR_W)
        h = max(abs(point.rate) / spread * height, _MIN_BAR_H)
        bars.append((x, zero_y - h if point.rate >= 0 else zero_y, w, h, point.rate))
    return Layout(bars, zero_y, peak, trough)


def axis_label(rate: float) -> str:
    """Beschriftung der Spitze — bewusst gröber als
    ``MainWindow._format_xp_rate``: An einer Achse steht die
    Größenordnung, die genaue Zahl steht als Text daneben im selben
    Feld. Zwei verschieden genaue Angaben derselben Zahl nebeneinander
    lesen sich sonst wie ein Widerspruch."""
    sign = "-" if rate < 0 else ""
    magnitude = abs(rate)
    if magnitude >= 1_000_000_000:
        return f"{sign}{magnitude / 1_000_000_000:.1f}B"
    if magnitude >= 1_000_000:
        return f"{sign}{magnitude / 1_000_000:.0f}M"
    if magnitude >= 1_000:
        return f"{sign}{magnitude / 1_000:.0f}K"
    return f"{sign}{magnitude:.0f}"


class XpGraph(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._points: list[XpPoint] = []
        self._now = 0.0
        self.setMinimumHeight(_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_points(self, points: Sequence[XpPoint], now: float) -> None:
        """``now`` kommt von außen mit, statt hier ``time.monotonic()`` zu
        rufen: Der Aufrufer hat es ohnehin gerade gelesen, und ein Widget,
        das seine eigene Uhr befragt, lässt sich nicht ohne Warten
        prüfen."""
        self._points = list(points)
        self._now = now
        self.update()

    def clear(self) -> None:
        self.set_points([], 0.0)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt-Namensschema)
        painter = QPainter(self)
        try:
            font = painter.font()
            font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
            painter.setFont(font)
            metrics = painter.fontMetrics()
            caption_h = metrics.height()
            width = self.width()
            plot_h = max(0.0, self.height() - caption_h)
            layout = graph_layout(self._points, self._now, width, plot_h)

            faint = dimmed_text(self.palette())
            painter.setPen(faint)
            painter.drawLine(0, round(layout.zero_y), width, round(layout.zero_y))

            for x, y, w, h, rate in layout.bars:
                # Grün nach oben, Rot nach unten: Ein Abschnitt, in dem
                # unterm Strich Erfahrung verloren ging (Tod ab Akt 5),
                # soll nicht wie ein magerer Gewinn aussehen.
                painter.fillRect(QRectF(x, y, w, h),
                                 QColor(DASH_OK if rate >= 0 else DASH_BAD))

            painter.setPen(faint)
            if layout.peak > 0:
                painter.drawText(2, metrics.ascent(), axis_label(layout.peak))
            # Die x-Achse braucht keine Skala, nur ihre beiden Enden —
            # dazwischen liegt gleichmäßige Zeit.
            strip = QRectF(2, plot_h, width - 4, caption_h)
            painter.drawText(strip, Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter, "3 h ago")
            painter.drawText(strip, Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter, "now")
        finally:
            painter.end()
