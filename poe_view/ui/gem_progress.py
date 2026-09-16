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

**Unter der Linie hängt seit 2026-09-16 ein gelbes Rechteck: der Gewinn
dieser Sitzung.** Peter wollte "gelbe Rechtecke, welche die Erfahrung
seit dem letzten Refresh widerspiegeln; falls es über ein Level
rausgeht, von unten ganz auffüllen". Als Anker dient der SITZUNGSBEGINN
(erstes Sehen des Gems in diesem Programmlauf, `_baseline`), nicht der
letzte Abruf — an Peters Gem-XP-Mitschrift vom 2026-09-13 gemessen ist
der Sprung je Veröffentlichung im Median 1 % (0,6 px), neun von zehn
liegen unter 3,6 px, und 592 von 630 Abrufen ändern gar nichts. Ein
Rechteck je Abruf wäre unsichtbar oder würde flackern. Seit
Sitzungsbeginn wächst es dagegen über den Abend auf lesbare Höhe.
Springt die Stufe, reicht das Rechteck vom Boden bis zur Linie
(`gain_span`) — der alte Stand liegt dann in einer anderen Stufe und
hat als Untergrenze keine Bedeutung mehr.

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

from html import escape

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QApplication, QLabel, QSizePolicy, QStyle,
                               QStyleOptionFrame, QStylePainter, QToolTip,
                               QWidget)

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

# Deckkraft des Gewinn-Rechtecks. Halbdurchsichtig, damit die Stufen-
# füllung darunter lesbar bleibt — die Stufe ist die Hauptaussage, der
# Gewinn die Zugabe. Die Linie darüber bleibt voll gesättigt: Sie
# markiert den aktuellen Stand, das Rechteck nur den Weg dorthin.
_GAIN_ALPHA = 110

# Der Tooltip ist seit 2026-09-16 eine Tabelle ALLER Gems, in der die
# Zeile des Balkens unter der Maus hervorgehoben ist (Peter: "so dass man
# auch den Namen des Gems und den aktuellen Stand lesen kann"). Bei
# dreißig Balken nebeneinander beantwortet ein Einzel-Tooltip die Frage
# "welches Gem ist das?" nur balkenweise; die Tabelle beantwortet sie auf
# einen Blick, und die Hervorhebung wandert mit der Maus. Die Balken in
# der Tabelle sind Blockzeichen — echte Rechtecke zeichnet Qts Rich Text
# im Tooltip unsauber, Zeichen in fester Schrift sitzen zuverlässig.
_TIP_BLOCKS = 10
_TIP_FULL = "█"     # █
_TIP_EMPTY = "░"    # ░
_TIP_EMPTY_COLOR = "#666666"

# Abstand der Tabelle zum Streifen (§_GemTable.place).
_TABLE_GAP = 8

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
    gem_id: str = ""     # GGGs Item-ID des Gems — Schlüssel für den Sitzungs-Anker

    def tooltip(self, gained: float | None = None) -> str:
        """``gained`` ist der Fortschrittsgewinn dieser Sitzung (0…1),
        wie ihn ``gain_span`` liefert — None, wenn es nichts zu sagen
        gibt."""
        if self.maxed:
            return f"{self.name} — level {self.level}"
        if self.ready:
            text = f"{self.name} — level {self.level}, ready to level up"
        else:
            text = f"{self.name} — level {self.level}, {self.progress:.0%} to next"
        if gained:
            text += f" (+{gained:.0%} this session)"
        return text

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
                ready=bool(experience) and progress >= 1.0 and not maxed,
                gem_id=str(gem.get("id") or "")))
    return gems


def gain_span(baseline: tuple[int, float] | None,
              gem: GemProgress) -> tuple[float, float] | None:
    """Untere und obere Kante des Gewinn-Rechtecks als Fortschritt
    (0…1) — oder None, wenn nichts zu zeichnen ist.

    ``baseline`` ist (Stufe, Fortschritt) beim ersten Sehen des Gems in
    dieser Sitzung. Ist die Stufe seither gestiegen, reicht das Rechteck
    vom Boden bis zum aktuellen Stand (Peter: "einfach dann von unten
    ganz auffüllen"); sonst vom alten zum neuen Stand. Fertige Gems
    haben keine Erfahrung mehr, ohne Anker gibt es keinen Vergleich, und
    ein Stand, der nicht gewachsen ist, ergibt kein Rechteck."""
    if baseline is None or gem.maxed:
        return None
    stufe, stand = baseline
    if gem.level_number > stufe:
        return (0.0, gem.progress) if gem.progress > 0 else None
    if gem.progress > stand:
        return (stand, gem.progress)
    return None


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


class _GemTable(QLabel):
    """Die Gem-Tabelle als eigenes Fenster statt als ``QToolTip``.

    Die erste Fassung (2026-09-16, wenige Stunden alt) lief über
    ``QToolTip.showText`` und verschwand bei Peter sofort wieder: Bei
    dreißig Gems ist die Tabelle rund 500 px hoch, passt nicht mehr
    UNTER den Streifen, und Qt schiebt sie darüber — genau unter die
    Maus. Der Streifen bekommt ein Leave, und Qts Tooltip-Mechanik
    blendet den Tipp aus. Mit sechs Gems im Test passte sie darunter,
    deshalb fiel es dort nicht auf.

    Dieses Fenster ist ``WindowTransparentForInput``: Es kann unter der
    Maus liegen, ohne dem Streifen die Maus zu nehmen — Bewegungen gehen
    durch das Fenster hindurch, Enter/Leave des Streifens bleiben
    korrekt. Aussehen wie ein Tooltip (Palette, Schrift und Rahmen aus
    dem Stil), Sichtbarkeit steuert allein der Streifen."""

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setForegroundRole(self.palette().ColorRole.ToolTipText)
        self.setBackgroundRole(self.palette().ColorRole.ToolTipBase)
        self.setPalette(QToolTip.palette())
        self.setFont(QToolTip.font())
        self.setMargin(self.style().pixelMetric(
            QStyle.PixelMetric.PM_ToolTipLabelFrameWidth, None, self) + 2)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt-Namensschema)
        # Derselbe Rahmen, den Qts eigener Tooltip zeichnet.
        painter = QStylePainter(self)
        option = QStyleOptionFrame()
        option.initFrom(self)
        painter.drawPrimitive(QStyle.PrimitiveElement.PE_PanelTipLabel, option)
        painter.end()
        super().paintEvent(event)

    def place(self, owner: QWidget) -> None:
        """Unter den Streifen; passt es dort nicht auf den Bildschirm,
        darüber. Beides bündig mit dem linken Rand des Streifens, damit
        die Tabelle beim Wandern der Hervorhebung nicht springt."""
        self.adjustSize()
        schirm = owner.screen().availableGeometry()
        oben_links = owner.mapToGlobal(QPoint(0, 0))
        unten = oben_links.y() + owner.height() + _TABLE_GAP
        if unten + self.height() > schirm.bottom():
            unten = oben_links.y() - _TABLE_GAP - self.height()
        x = min(max(oben_links.x(), schirm.left()), schirm.right() - self.width())
        self.move(x, max(unten, schirm.top()))


class GemProgressBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._gems: list[GemProgress] = []
        # Sitzungs-Anker je Gem (§Modulkopf): (Stufe, Fortschritt) beim
        # ersten Sehen in diesem Programmlauf. Lebt im Widget, weil es
        # das einzige ist, was alle Charakterwechsel überdauert und die
        # Balken kennt; ein Charakterwechsel löscht nichts — die Gem-ID
        # ist kontoweit eindeutig.
        self._baseline: dict[str, tuple[int, float]] = {}
        self._hovered: int | None = None   # Zeile, die die Tabelle gerade hervorhebt
        self._table: _GemTable | None = None   # erst beim ersten Zeigen gebaut
        self.setMouseTracking(True)
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
        for gem in self._gems:
            if gem.gem_id and not gem.maxed and gem.gem_id not in self._baseline:
                self._baseline[gem.gem_id] = (gem.level_number, gem.progress)
        self.setVisible(bool(self._gems))
        self.updateGeometry()  # neue Breite anmelden, sonst bleibt die alte
        self.update()
        if self.table_visible():
            self._show_table(self._hovered if self._hovered is not None
                             and self._hovered < len(self._gems) else None)

    def clear(self) -> None:
        self.set_gems([])

    def gain_of(self, gem: GemProgress) -> tuple[float, float] | None:
        """Gewinn-Rechteck dieses Gems seit Sitzungsbeginn (§gain_span)."""
        return gain_span(self._baseline.get(gem.gem_id), gem)

    def _gained(self, gem: GemProgress) -> float | None:
        spanne = self.gain_of(gem)
        return spanne[1] - spanne[0] if spanne else None

    def table_html(self, hovered: int | None) -> str:
        """Die Tabelle aller Gems für den Tooltip (§_TIP_BLOCKS): Farbpunkt,
        Name, Stufe, Stufen-Balken (Stufe/20 in der Gem-Farbe), Fortschritt
        zur nächsten Stufe und Sitzungsgewinn. Zeile ``hovered`` fett und
        hinterlegt."""
        hell = self.palette().highlight().color().name()
        zeilen = []
        for index, gem in enumerate(self._gems):
            voll = round(gem.level_fill * _TIP_BLOCKS)
            farbe = gem_colour_done(gem.colour) if gem.maxed else gem_colour(gem.colour)
            balken = (f'<span style="font-family:monospace;color:{farbe}">'
                      f'{_TIP_FULL * voll}</span>'
                      f'<span style="font-family:monospace;color:{_TIP_EMPTY_COLOR}">'
                      f'{_TIP_EMPTY * (_TIP_BLOCKS - voll)}</span>')
            if gem.maxed:
                stand = "max"
            elif gem.ready:
                stand = "ready to level up"
            else:
                stand = f"{gem.progress:.0%} to next"
            gained = self._gained(gem)
            zugabe = f"+{gained:.0%} this session" if gained else ""
            # Geschützte Leerzeichen: Ein Rich-Text-Tooltip bekommt von Qt
            # Zeilenumbruch, und der zerlegte "Raise Zombie" und "34% to
            # next" auf zwei Zeilen (nativ geprüft, 2026-09-16).
            # Ersetzt wird nur im Text — nicht im Farbpunkt-Tag, dessen
            # eigenes Leerzeichen (``<span style``) sonst mit zerfiele
            # und den Punkt grau ließe (im Bild gefunden, 2026-09-16).
            name, stufe, stand, zugabe = (z.replace(" ", "&nbsp;") for z in (
                escape(gem.name), escape(gem.level), stand, zugabe))
            zellen = (f'<span style="color:{farbe}">&#9632;</span>&nbsp;{name}',
                      stufe, balken, stand, zugabe)
            if index == hovered:
                zellen = tuple(f"<b>{z}</b>" for z in zellen)
                attr = f' bgcolor="{hell}"'
            else:
                attr = ""
            zeilen.append("<tr>" + "".join(f"<td{attr}>{z}&nbsp;&nbsp;</td>" for z in zellen)
                          + "</tr>")
        return '<table cellspacing="0" cellpadding="1">' + "".join(zeilen) + "</table>"

    def _show_table(self, hovered: int | None) -> None:
        """Die Tabelle zeigen bzw. ihren Text austauschen. Platziert wird
        nur beim Erscheinen — beim Wandern der Hervorhebung bleibt sie
        stehen, sonst spränge sie mit jeder fett gesetzten Zeile."""
        if self._table is None:
            self._table = _GemTable(self)
        self._table.setText(self.table_html(hovered))
        self._hovered = hovered
        if not self._table.isVisible():
            self._table.place(self)
            self._table.show()
            # Klick irgendwo, Rad, Fensterwechsel: Tabelle weg — dieselben
            # Anlässe, bei denen Qt seine Tooltips schließt. Der Filter
            # hängt NUR, solange die Tabelle steht: Ein dauerhafter Filter
            # je Streifen summierte sich in der Testsuite (hunderte
            # Hauptfenster) zu einem Lauf, der doppelt so lange dauerte.
            QApplication.instance().installEventFilter(self)
        else:
            self._table.adjustSize()

    def _hide_table(self) -> None:
        self._hovered = None
        if self._table is not None and self._table.isVisible():
            self._table.hide()
            QApplication.instance().removeEventFilter(self)

    def table_visible(self) -> bool:
        return self._table is not None and self._table.isVisible()

    def event(self, event: QEvent) -> bool:
        """Beim Verweilen (Qts Tooltip-Anlass, mit dessen Verzögerung) die
        Tabelle aller Gems öffnen, hervorgehoben der Balken unter der
        Maus. Ohne sie wäre der Streifen zwar hübsch, aber stumm — bei
        dreißig Balken nebeneinander ist "welches Gem ist das?" die erste
        Frage."""
        if event.type() == QEvent.Type.ToolTip:
            if self._gems:
                self._show_table(self._index_at(event.pos().x()))
            return True
        return super().event(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if self.table_visible() and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.Wheel,
                QEvent.Type.WindowDeactivate):
            self._hide_table()
        return False

    def _index_at(self, x: int) -> int | None:
        index = int(x // (_BAR_W + _BAR_GAP))
        return index if 0 <= index < len(self._gems) else None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt-Namensschema)
        """Die Hervorhebung wandert mit der Maus, solange die Tabelle
        steht — dafür ``setMouseTracking`` im Konstruktor, sonst kämen
        Bewegungen nur mit gedrückter Taste an."""
        if self.table_visible():
            hovered = self._index_at(event.position().x())
            if hovered != self._hovered:
                self._show_table(hovered)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt-Namensschema)
        self._hide_table()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt-Namensschema)
        self._hide_table()
        super().hideEvent(event)

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
                # Erst das Rechteck des Sitzungsgewinns (halbdurchsichtig,
                # von der alten bis zur aktuellen Höhe), dann die Linie
                # darüber — so bleibt der aktuelle Stand als scharfe
                # Kante lesbar.
                spanne = self.gain_of(gem)
                if spanne:
                    oben = height - round(height * spanne[1])
                    unten = height - round(height * spanne[0])
                    gelb = QColor(GEM_XP_LINE)
                    gelb.setAlpha(_GAIN_ALPHA)
                    painter.fillRect(QRectF(x, oben, _BAR_W, unten - oben), gelb)
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
