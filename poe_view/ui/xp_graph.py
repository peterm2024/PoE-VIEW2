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

from dataclasses import dataclass, field
from typing import NamedTuple, Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from poe_view.ui.theme import DASH_BAD, DASH_OK, blend, dimmed_text

# Die Fläche hinter den Balken einer zusammengehörenden Map: dasselbe
# Grün, nur dunkel (Peter, 2026-08-13: "muss nicht unbedingt schraffiert
# sein, kann auch nur dunkelgrün sein"). Dunkel genug, dass die Balken
# darauf lesbar bleiben, hell genug, um vom Hintergrund abzustechen.
_GROUP_COLOR = blend(QColor(DASH_OK), QColor("#000000"), 0.55)

# Die gestrichelte Gesamtrate. Bewusst nicht grün: Sie ist eine
# Bezugslinie, kein weiterer Messwert.
_AVERAGE_COLOR = "#c9c9c9"

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
    XP/h — genau die Zahl, die auch im Leveling-Feld steht.

    ``instance`` ist die Kennung der Gebiets-Instanz aus der Client.txt.
    Gleiche Kennung = derselbe Map-Durchgang, auch wenn man
    zwischendurch draußen war."""

    at: float
    seconds: float
    rate: float
    instance: str = ""

    @property
    def gain(self) -> float:
        """Die Erfahrung dieses Abschnitts. Der Graph rechnet in Raten,
        zum Zusammenfassen mehrerer Abschnitte braucht es aber die
        Summanden — ein Mittel ÜBER Raten wäre falsch, sobald die
        Abschnitte verschieden lang sind."""
        return self.rate * self.seconds / 3600


@dataclass(frozen=True)
class Layout:
    """Fertige Geometrie für ``paintEvent``. ``bars`` sind
    ``(x, y, w, h, rate)`` in Widget-Koordinaten, ``zero_y`` die Höhe der
    Null-Linie (bei ausschließlich positiven Raten der untere Rand).

    ``groups`` sind die Flächen hinter den Balken: je ein Rechteck über
    alle Abschnitte EINER Map, auf Höhe ihrer gemeinsamen Rate.
    ``average_y`` ist die Höhe der gestrichelten Linie über allem."""

    bars: list[tuple[float, float, float, float, float]]
    zero_y: float
    peak: float
    trough: float
    groups: list[tuple[float, float, float, float]] = field(default_factory=list)
    average_y: float | None = None
    average: float = 0.0


def combined_rate(points: Sequence[XpPoint]) -> float:
    """Gemeinsame Rate mehrerer Abschnitte: Summe der Erfahrung geteilt
    durch die Summe der GESPIELTEN Zeit. Die Pause dazwischen zählt
    bewusst nicht mit — sie hat keine Erfahrung gekostet, sie hat nur
    keine gebracht."""
    sekunden = sum(p.seconds for p in points)
    return sum(p.gain for p in points) / (sekunden / 3600) if sekunden > 0 else 0.0


def group_by_instance(points: Sequence[XpPoint]) -> list[list[XpPoint]]:
    """Aufeinanderfolgende Abschnitte derselben Gebiets-Instanz
    zusammenfassen.

    Peter, 2026-08-13, nach einer Map mit Verkaufspause: "Zusammenfassen
    will ich die beiden Balken nicht, weil hier sieht man wirklich schön
    wann man raus und wieder rein ist und was das gekostet hat." Die
    Balken bleiben deshalb einzeln — gruppiert wird nur für die Fläche
    dahinter.

    Ohne Kennung (leerer String) steht jeder Abschnitt für sich: Zwei
    Maps gleichen Namens hintereinander sind zwei Maps, und ohne die
    Instanz-Zeile in der Client.txt lässt sich das nicht unterscheiden.
    Lieber nicht gruppieren als falsch gruppieren."""
    gruppen: list[list[XpPoint]] = []
    for point in points:
        if point.instance and gruppen and gruppen[-1][-1].instance == point.instance:
            gruppen[-1].append(point)
        else:
            gruppen.append([point])
    return gruppen


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

    def spanne(point: XpPoint) -> tuple[float, float]:
        """Anfang und Ende eines Abschnitts in Widget-Koordinaten."""
        ende = min(width, width - (now - point.at) / span_s * width)
        anfang = min(ende - max(point.seconds, 0.0) / span_s * width, ende - _MIN_BAR_W)
        return max(0.0, anfang), ende

    bars: list[tuple[float, float, float, float, float]] = []
    for point in shown:
        x, end = spanne(point)
        w = max(end - x, _MIN_BAR_W)
        h = max(abs(point.rate) / spread * height, _MIN_BAR_H)
        bars.append((x, zero_y - h if point.rate >= 0 else zero_y, w, h, point.rate))

    # Flächen hinter den Balken: nur, wo wirklich mehrere Abschnitte zu
    # EINER Map gehören. Bei einem einzelnen Abschnitt läge das Rechteck
    # deckungsgleich hinter seinem Balken und wäre reine Verdopplung.
    groups: list[tuple[float, float, float, float]] = []
    for gruppe in group_by_instance(shown):
        if len(gruppe) < 2:
            continue
        rate = combined_rate(gruppe)
        x, _ = spanne(gruppe[0])
        _, end = spanne(gruppe[-1])
        h = max(abs(rate) / spread * height, _MIN_BAR_H)
        groups.append((x, zero_y - h if rate >= 0 else zero_y, max(end - x, _MIN_BAR_W), h))

    average = combined_rate(shown)
    return Layout(bars, zero_y, peak, trough, groups,
                  zero_y - average / spread * height, average)


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

            # ZUERST die Flächen, damit die Balken darauf liegen: Eine Map
            # mit Unterbrechung bekommt ihre gemeinsame Rate als
            # dunkelgrünen Grund, über den die einzelnen Aufenthalte
            # hinaus- oder in den sie hineinragen. Die Lücke bleibt dabei
            # sichtbar — Peter, 2026-08-13: "hier sieht man wirklich schön
            # wann man raus und wieder rein ist und was das gekostet hat."
            for x, y, w, h in layout.groups:
                painter.fillRect(QRectF(x, y, w, h), QColor(_GROUP_COLOR))

            for x, y, w, h, rate in layout.bars:
                # Grün nach oben, Rot nach unten: Ein Abschnitt, in dem
                # unterm Strich Erfahrung verloren ging (Tod ab Akt 5),
                # soll nicht wie ein magerer Gewinn aussehen.
                painter.fillRect(QRectF(x, y, w, h),
                                 QColor(DASH_OK if rate >= 0 else DASH_BAD))

            # Die Gesamtrate über alles Sichtbare als gestrichelte Linie.
            # Sie steht ruhig, während die einzelnen Abschnitte springen,
            # und beantwortet damit die Frage, die ein einzelner Balken
            # nicht kann: liege ich über oder unter meinem Schnitt?
            if layout.average_y is not None and layout.average > 0:
                stift = QPen(QColor(_AVERAGE_COLOR))
                stift.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(stift)
                painter.drawLine(0, round(layout.average_y),
                                 width, round(layout.average_y))
                # Beschriftung AN der Linie, nicht in der Ecke: Dort
                # stand sie zuerst und verschwand prompt auf einem hohen
                # Balken, weil ein gedämpftes Grau auf Grün nichts mehr
                # hergibt. An der Linie ist sie ohnehin besser aufgehoben
                # — sie erklärt genau diese eine Linie.
                painter.drawText(QRectF(2, layout.average_y - metrics.height(),
                                        width - 4, metrics.height()),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 f"⌀ {axis_label(layout.average)}")

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
