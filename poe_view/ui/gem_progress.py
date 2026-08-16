"""Sockel-Gems als Balken über dem XP-Graphen.

**Die Balkenhöhe ist die Stufe, nicht der Fortschritt.** Peter,
2026-08-16: "Die aktuelle Stufe des Gems ist wichtiger als die aktuelle
Erfahrung." Die erste Fassung füllte den Balken mit dem Fortschritt zur
nächsten Stufe — damit standen 26 Balken auf zufälligen Prozentwerten
und sahen alle gleich wichtig aus. Mit der Stufe als Höhe wird der
Streifen zu einem Profil des Charakters: Welches Gem hängt zurück, sieht
man, ohne einen einzigen Tooltip zu lesen.

Der Fortschritt ist damit nicht verloren, nur nachgeordnet: eine 1 px
hohe Linie in intensivem Gelb, deren Höhe im Balken den Fortschritt zur
nächsten Stufe angibt. Sie hängt bewusst NICHT an der Stufenfüllung,
sondern läuft über die ganze Balkenhöhe. Innerhalb der Stufe wäre ihr
Spielraum eine Zwanzigstel-Höhe, bei 60 px also 3 px — eine Linie, die
sich nicht bewegt, ist Zierde.

**Die schwierigste Frage beantwortet GGG selbst.** "Ist das Gem fertig?"
müsste man eigentlich aus Stufe, Gem-Art und Erfahrung herleiten — ein
Awakened-Gem ist bei 5 fertig, ein normales bei 20, ein korrumpiertes
kann bei 21 stehen. Nichts davon ist nötig: Über Peters 448 Sockel-Gems
(16 Charaktere, gezählt 2026-08-16) steht die Stufe im Klartext als
``"20 (Max)"``, ``"5 (Max)"``, ``"1 (Max)"``, und genau diesen Gems
fehlt zugleich das ``Experience``-Feld. Beide Merkmale zeigen dasselbe
an, und keines muss geraten werden.

Damit drei Zustände, alle drei aus den Daten belegt:

- **Fertig** (227 von 448): Stufe trägt "(Max)", kein Erfahrungsfeld.
  Voller Balken in der gesättigten Gem-Farbe (`GEM_COLORS_DONE`), ohne
  Erfahrungslinie. Diese Markierung löst zugleich das Problem, an dem
  ein gelber Rahmen am selben Tag gescheitert war: Auf 5 px Breite
  trägt eine Farbfläche, keine Kontur.
- **Wartet auf einen Klick** (65): Balken voll, aber nicht Max. Gems
  steigen in PoE nicht von selbst auf (`poe-verhalten.md` §4) — das ist
  Charakterstärke, die nur auf einen Mausklick wartet. Bekommt deshalb
  eine eigene Markierung; ohne sie sähe es aus wie "fertig".
- **Am Leveln** (156): Höhe = Stufe, Linie = Fortschritt.

**Die Höhe rechnet stur mit Stufe/20**, auch bei Gems, deren Höchststufe
darunter liegt. Über Peters Bestand gezählt gibt es solche zuhauf
(Portal/Quickstep/Convocation = 1, Empower/Enhance/Enlighten = 3, Brand
Recall = 6), und ihre Höchststufe steht in keinem API-Feld — sie wäre
nur über eine gepflegte Namensliste zu erraten. Nötig ist das nicht:
Sobald so ein Gem fertig ist, trägt es "(Max)" und wird voll gezeichnet.
Nur ein *unfertiges* Enlighten steht zu tief im Balken, und das ist der
Zustand, in dem die Aussage "hier fehlt noch etwas" ohnehin stimmt.

**Nicht jedes ``socketedItems`` ist ein Gem.** Ein Abyss-Jewel im
Gürtel oder Ring sitzt in derselben Liste, levelt aber nicht. Peter
2026-08-16: "Belt gibts glaube ich nicht für Gems, nur für Jewels."
Genau ein solches Jewel steckte in seinem Bestand, bekam einen eigenen,
ewig leeren Balken — und war jenes vermeintliche "Gem, dessen Stufe die
API nicht mitliefert", das hier früher als Sonderfall vermerkt war. Seit
der Filter auf ``frameType == 4`` steht, bleibt kein Balken ohne Beleg.

Die Aufbereitung (`gem_progress_of`) ist eine reine Funktion über
``Item``-Objekte: ohne Qt prüfbar, und die Zeichenroutine bekommt nur
noch fertige Werte.
"""

from __future__ import annotations

from typing import NamedTuple, Sequence

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from poe_view.api.models import Item
from poe_view.ui.theme import (DASH_WARN, GEM_COLOR_DONE_OTHER,
                               GEM_COLOR_OTHER, GEM_COLORS, GEM_COLORS_DONE,
                               GEM_XP_LINE, blend, dimmed_text)

# Maße eines Balkens. Peters Vorgabe waren 3-5 px Breite; 5 plus 2 Lücke
# trägt auch den vollsten Charakter in Peters Bestand (33 Gems → 231 px)
# und bleibt einzeln anklickbar breit genug für einen Tooltip.
_BAR_W = 5
_BAR_GAP = 2

# GGGs ``frameType`` für ein Gem. Jewels (1 = Magic, 2 = Rare) stecken in
# derselben ``socketedItems``-Liste, leveln aber nicht.
_GEM_FRAME = 4

# Bezugsgröße der Balkenhöhe: Stufe/20 (Peter, 2026-08-16: "Die Höhe
# machen wir mittels Stufe/20"). Warum das auch für Gems mit kleinerer
# Höchststufe reicht, steht oben im Modulkopf.
_LEVEL_SCALE = 20

# Die Erfahrungslinie. 1 px, damit sie den Balken liest statt ihn zu
# überschreiben — die Stufe ist die Hauptaussage, der Fortschritt der
# Zusatz.
_XP_LINE_H = 1

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
# helle Teil klar heraussticht, hell genug, dass der Balken überhaupt
# noch als Balken zu sehen ist.
#
# Der Wert stand bis 2026-08-16 auf 0,68 und war damit zu dunkel:
# Gegen den Hintergrund der dunklen Windows-Oberfläche kam der leere
# Teil auf 1,02–1,21:1 Kontrast, war also praktisch unsichtbar. In
# Peters Bildschirmfoto sahen kaum gefüllte Balken deshalb aus
# wie LÜCKEN im Streifen — man konnte "hier steckt kein Gem" nicht von
# "Gem bei 5 %" unterscheiden, ausgerechnet den Zustand, den man sehen
# will. Mit 0,45 sind es 1,44–2,29:1: noch klar dunkler als der volle
# Teil, aber als Balken erkennbar.
_EMPTY_DIM = 0.45


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

    @property
    def level_number(self) -> int:
        """Die führenden Ziffern der Klartext-Stufe: "20 (Max)" → 20.

        Aus dem Text gelesen statt als eigenes Feld geführt, weil GGG
        genau diesen Text liefert und "(Max)" daran hängt — zwei Felder
        aus einer Quelle könnten auseinanderlaufen. Steht dort etwas
        Unerwartetes (``"?"``), ist die Stufe 0 und der Balken leer:
        lieber "wir wissen es nicht" als eine geratene Höhe."""
        ziffern = ""
        for zeichen in self.level:
            if not zeichen.isdigit():
                break
            ziffern += zeichen
        return int(ziffern) if ziffern else 0

    @property
    def level_fill(self) -> float:
        """Anteil der Balkenhöhe, den die Stufe füllt (0…1). Korrumpierte
        Gems stehen bei 21 und würden über 1 hinauslaufen."""
        return min(self.level_number / _LEVEL_SCALE, 1.0)


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
            if not isinstance(gem, dict) or gem.get("frameType") != _GEM_FRAME:
                # In ``socketedItems`` steckt nicht nur, was levelt: Ein
                # Abyss-Jewel im Gürtel oder Ring sitzt in derselben
                # Liste (Peter, 2026-08-16: "Belt gibts glaube ich nicht
                # für Gems, nur für Jewels"). Ohne diese Prüfung bekam
                # es einen eigenen, ewig leeren Balken — und war genau
                # jenes "eine Gem, dessen Stufe die API nicht
                # mitliefert", das früher hier im Kommentar stand.
                continue
            level = _level_text(gem)
            experience = _experience(gem)
            maxed = "(max)" in level.lower()
            # Ohne Erfahrungsfeld UND ohne "(Max)" wissen wir nichts —
            # dann ein leerer Balken statt eines vollen: Ein voller
            # hieße "fertig", und das wäre eine Behauptung ohne
            # Grundlage. Seit dem Jewel-Filter oben tritt der Fall in
            # Peters Bestand nicht mehr auf (448 Gems, keiner ohne
            # Beleg) — der frühere Einzelfall WAR das Jewel.
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


def gem_colour_done(colour: str) -> str:
    """Dieselbe Farbe in ihrer gesättigten Fassung — für fertige Gems.

    Alles, was nicht S/D/I ist, wird weiß: die vier grauen ``"G"``-Gems
    in Peters Bestand (Convocation & Co.) und die gelben, die es seit
    kurzem gibt (Peter, 2026-08-16: "die nehmen wir vorerst zu den
    weißen Gems dazu"). Für die gelben liegt uns kein einziger Datensatz
    vor — sie fallen über denselben Weg hier hinein wie jedes andere
    unbekannte Kürzel, ohne dass wir ihr Kürzel kennen müssten."""
    return GEM_COLORS_DONE.get(colour, GEM_COLOR_DONE_OTHER)


class GemProgressBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._gems: list[GemProgress] = []
        self.setFixedHeight(BAR_HEIGHT)
        # Waagerecht ``Fixed``: Die Breite ergibt sich aus der Zahl der
        # Gems, mehr Platz nützt nichts. Solange die Balken allein in
        # einer Zeile standen, war das gleichgültig — seit die
        # Favoriten-Tabelle daneben sitzt (§4.45), nicht mehr: Ohne
        # eigenen Breitenwunsch fiel das Widget auf 0 px zusammen und die
        # Balken verschwanden vollständig (2026-08-16, an Peters
        # Bildschirmfotos aufgefallen).
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt-Namensschema
        return QSize(self._wanted_width(), BAR_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 — Qt-Namensschema
        return self.sizeHint()

    def _wanted_width(self) -> int:
        """Alle Balken samt Zwischenraum, ohne den Abstand hinter dem
        letzten."""
        if not self._gems:
            return 0
        return len(self._gems) * (_BAR_W + _BAR_GAP) - _BAR_GAP

    def set_gems(self, gems: Sequence[GemProgress]) -> None:
        self._gems = list(gems)
        self.setVisible(bool(self._gems))
        self.updateGeometry()  # neue Breite anmelden, sonst bleibt die alte
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
                if gem.maxed:
                    # Fertig: voller Balken in der gesättigten Farbe,
                    # sonst nichts. Keine Erfahrungslinie — ein fertiges
                    # Gem hat kein Erfahrungsfeld mehr, eine Linie wäre
                    # eine erfundene Angabe.
                    painter.fillRect(QRectF(x, 0, _BAR_W, height),
                                     QColor(gem_colour_done(gem.colour)))
                    continue
                hell = QColor(gem_colour(gem.colour))
                dunkel = blend(hell, QColor("#000000"), _EMPTY_DIM)
                stufe = round(height * gem.level_fill)
                painter.fillRect(QRectF(x, 0, _BAR_W, height - stufe), dunkel)
                painter.fillRect(QRectF(x, height - stufe, _BAR_W, stufe), hell)
                # Die Erfahrung als Linie über die GANZE Balkenhöhe, nicht
                # innerhalb der Stufe: dort hätte sie bei 60 px nur 3 px
                # Spielraum. Der Anschlag hält sie auch bei 0 % und 100 %
                # im Balken, statt sie unten heraus- oder oben
                # wegfallen zu lassen.
                linie = min(max(height - round(height * gem.progress), 0),
                            height - _XP_LINE_H)
                painter.fillRect(QRectF(x, linie, _BAR_W, _XP_LINE_H),
                                 QColor(GEM_XP_LINE))
                if gem.ready:
                    painter.fillRect(QRectF(x, 0, _BAR_W, _READY_CAP_H),
                                     QColor(DASH_WARN))
            if not self._gems:
                painter.setPen(dimmed_text(self.palette()))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                                 "No socketed gems")
        finally:
            painter.end()
