"""Der Passiv-Baum als Bild (§4.60.4) — schematisch, nicht im Look des
Originals.

Peter, 2026-10-05: "Wieviel Aufwand ist es, den Skilltree analog zum
Original in einem weiteren Tab graphisch darzustellen?" — entschieden:
Stufe 1 (Kreise und Linien in der echten Lage, mit dem, was der Planer
nicht kann: Reichweite, Respec farbig, Ruthless-Werte im Tooltip), die
Original-Grafiken "benötigen wir vorerst nicht".

Knoten: nicht vergeben hohl und gedämpft, vergeben gefüllt in der Farbe
ihres Themas (§4.60.2) — der Unterschied hängt damit nicht an der Farbe
allein. Beim Vergleich zweier Bäume (Konfiguration gegen den aktuellen,
Verlaufseintrag gegen den davor): neu zu nehmen grün, zurückzunehmen rot.
Ringe: in Reichweite (§within_reach) und Suchtreffer.

Im Hintergrund die Bereiche der Klassen nach Attribut, Hybride gestreift,
außen am Rand Klasse und Aszendenzen (§4.60.5).

Die Aszendenzen der Klassen (§4.60.8): In GGGs Daten liegen sie als
kleine Inseln mitten über dem Hauptbaum; jede wird nach außen vor den
Bereich ihrer Klasse verschoben, die eigene golden umrandet. Nicht
gezeichnet: Bloodline-Aszendenzen ohne Klasse und Platzhalter für
Cluster-Jewels. Linien und Ränder
sind "kosmetisch": gleich dick, egal wie weit hineingezoomt ist.
"""

from __future__ import annotations

import dataclasses
import functools
import html
import math
import textwrap

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QGuiApplication, QImage, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap, QTransform)
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsScene,
                               QGraphicsTextItem, QGraphicsView, QToolTip)

from poe_view.services import passive_tree
from poe_view.services.passive_tree import (JEWEL, KEYSTONE, MASTERY, NOTABLE, START,
                                            ClassInfo, Node, Tree)
from poe_view.ui import tree_report

# Halbmesser in Baum-Einheiten (der Baum ist rund 25.000 breit, eine
# Kreisbahn 82 bis 846).
_RADIUS = {KEYSTONE: 56.0, NOTABLE: 40.0, JEWEL: 36.0, MASTERY: 28.0, START: 60.0}
_KLEIN = 26.0

# Zustände eines Knotens.
DIM, ALLOCATED, ALLOCATE, REFUND = "dim", "allocated", "allocate", "refund"

# Gerechnet gegen den Grund (Base #2d2d2d / #ffffff), Ziel 3:1 für
# Grafik: gedämpft dunkel 3,2:1, hell 4,1:1; Ring "Reichweite" 7,5 / 4,5;
# Suchtreffer 9,8 / 4,5. Hell waren Grau und Gelb zuerst #8a8a8a und
# #b8860b — auf den getönten Bereichen (§4.60.5) unter 3:1.
_FARBEN = {
    True: {"dim": "#7a7a7a", "edge": "#4f4f4f", "edge_on": "#d8d8d8",
           "reach": "#4dd0e1", "search": "#ffd54f", "hover": "#ffffff"},
    False: {"dim": "#7e7e7e", "edge": "#d0d0d0", "edge_on": "#3a3a3a",
            "reach": "#00838f", "search": "#9a7000", "hover": "#000000"},
}

# Bereiche der Klassen (§4.60.5, Peters Idee): Stärke dunkelrot,
# Intelligenz blau, Geschick grün; Hybride gestreift aus beiden.
# Gerechnet: Jeder Knoten hält darauf seine 3:1 (gedämpft dunkel ab
# 3,06:1, hell ab 3,40:1, alles Farbige ab 5,3 bzw. 3,75), und die Tönung
# hebt sich ab (ΔE2000 zum Grund 14–16 dunkel, 9–12 hell).
_TOENUNG = {
    True: {"str": "#401f1f", "int": "#1d2945", "dex": "#1c3622"},
    False: {"str": "#fce6e6", "int": "#e4ebfc", "dex": "#e1f5e5"},
}
# Streifen in Bildschirmpixeln (je Farbe), unabhängig vom Zoom.
STREIFEN_PX = 8
# Zeichen je Tooltip-Zeile, danach Umbruch.
TOOLTIP_BREITE = 70
# Wie lange ein Knoten-Tooltip stehen bleibt: so lange, wie die Maus auf
# dem Knoten ruht (Peter, 2026-10-07: "Können wir die Anzeigedauer des
# Tooltips bei den Nodes auf unendlich stellen?"). Qt blendet sonst nach
# rund 10 s plus einem Aufschlag je Zeichen aus. Der größte Wert, den Qt
# annimmt (int, ~24 Tage); weg ist der Tooltip, sobald die Maus den Knoten
# verlässt (mouseMoveEvent → hideText).
TOOLTIP_MS = 2**31 - 1
# Die Aszendenzen (§4.60.8): Abstand der Inseln vom äußeren Rand der
# Klassenbereiche, Winkel zwischen den Inseln einer Klasse, und die
# Richtung für den Scion (er sitzt in der Mitte und hat keinen Bereich —
# zwischen Witch und Shadow ist Platz).
ASC_ABSTAND = 250.0
ASC_SPREIZUNG = 10.0
ASC_WINKEL_OHNE_BEREICH = 30.0
# Dort steht die Beschriftung schräg, ihr Kasten ragte in der
# Gesamtansicht über die Nachbarinsel (nativ gesehen) — weiter hinaus.
ASC_ABSTAND_SCHRAEG = 900.0


@dataclasses.dataclass
class AscIsland:
    """Eine Aszendenz im Bild: Richtung ihrer Mitte, äußerster Halbmesser,
    Scheibe dahinter und die Attribute der Klasse (Tönung)."""
    angle: float
    outer: float
    disc: QPainterPath
    attributes: tuple[str, ...]
# Beschriftung am Rand: Klasse, Aszendenzen, die eigene hervorgehoben.
_SCHRIFT = {True: {"class": "#e0e0e0", "asc": "#b0b0b0"},
            False: {"class": "#202020", "asc": "#5f5f5f"}}


def _drawn(n: Node) -> bool:
    # Gezeichnet wird, was einer Gruppe angehört — nicht "was nicht bei 0/0
    # liegt": ein Knoten genau im Ursprung fiele sonst weg (im Test gesehen).
    return not n.ascendancy and not n.proxy and n.group >= 0


def _cosmetic(farbe: str, breite: float) -> QPen:
    stift = QPen(QColor(farbe), breite)
    stift.setCosmetic(True)
    return stift


def _winkel(x: float, y: float) -> float:
    """Im Uhrzeigersinn von oben, 0..360 — wie die Kreisbahnen."""
    return math.degrees(math.atan2(x, -y)) % 360.0


@functools.lru_cache(maxsize=8)
def _streifen(farben: tuple[str, ...]) -> QBrush:
    """Diagonale Streifen; die Kachel wiederholt sich nahtlos."""
    periode = STREIFEN_PX * len(farben)
    bild = QImage(periode, periode, QImage.Format.Format_RGB32)
    werte = [QColor(f).rgb() for f in farben]
    for y in range(periode):
        for x in range(periode):
            bild.setPixel(x, y, werte[((x + y) % periode) // STREIFEN_PX])
    return QBrush(QPixmap.fromImage(bild))


def class_areas(tree: Tree) -> tuple[list[tuple[ClassInfo, float, float, float]], float, float]:
    """Je Klasse am Rand ihr Bereich: (Klasse, Winkel des Starts, von, bis),
    dazu innerer und äußerer Halbmesser. Die Grenzen liegen mittig
    zwischen benachbarten Starts — im echten Baum genau ±30°. Der Scion
    sitzt in der Mitte und hat keinen Bereich."""
    starts = []
    for c in tree.classes:
        n = tree.nodes.get(c.start) if c.start is not None else None
        if n is not None and math.hypot(n.x, n.y) > 500:
            starts.append((_winkel(n.x, n.y), math.hypot(n.x, n.y), c))
    if not starts:
        return [], 0.0, 0.0
    starts.sort(key=lambda s: s[0])
    bereiche = []
    for i, (w, _d, c) in enumerate(starts):
        if len(starts) == 1:
            von, bis = w - 180.0, w + 180.0
        else:
            vor, nach = starts[i - 1][0], starts[(i + 1) % len(starts)][0]
            von = w - ((w - vor) % 360.0) / 2
            bis = w + ((nach - w) % 360.0) / 2
        bereiche.append((c, w, von, bis))
    innen = 0.5 * sum(d for _w, d, _c in starts) / len(starts)
    aussen = max(math.hypot(n.x, n.y) for n in tree.nodes.values() if _drawn(n)) + 300.0
    return bereiche, innen, aussen


class TreeGraph(QGraphicsView):
    # Klick auf einen Knoten ohne zu ziehen (§4.60.6): Kennung, rechte Taste.
    node_clicked = Signal(int, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        # Verschoben wird mit der Maus — Rollbalken nähmen nur Platz.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._mastery_theme: dict[int, str] = {}
        self.comparing = False
        self._tree: Tree | None = None
        self._items: dict[int, QGraphicsEllipseItem] = {}
        self._edges: list[tuple[int, int, QPainterPath]] = []
        self._edge_items: list = []
        self._rings: list = []
        self.states: dict[int, str] = {}
        self.reach_ids: set[int] = set()
        self.search_ids: set[int] = set()
        self._shown: set[int] = set()
        # Klassenbereiche (§4.60.5): Pfad in Baum-Koordinaten je Bereich,
        # gemalt im Hintergrund; Beschriftung am Rand.
        self.areas: list[tuple[QPainterPath, tuple[str, ...]]] = []
        self.labels: list[tuple[QGraphicsTextItem, ClassInfo, float]] = []
        self.own_class: tuple[int, int] | None = None
        self._dark = True
        # Zusatzzeile im Tooltip ("Click: allocate (3 points)") — setzt der
        # Dialog, das Bild weiß nicht, was ein Klick bewirkt.
        self.click_hint = None
        self._press: QPoint | None = None
        # Knoten unter der Maus (Ring, Zeiger) und seine Klick-Info.
        self.hovered: int | None = None
        # Gewählte Mastery-Effekte des gezeigten Baums (für den Tooltip).
        self.choices: dict[int, int] = {}
        self._hover_ring = None
        self._hover_info: tuple | None = None
        # Die Aszendenzen (§4.60.8): verschobene Knoten (Lage im Bild), ihre
        # Linien, die Inseln je Name; ``ascendancy`` ist die eigene.
        self.ascendancy = ""
        self._moved: dict[int, Node] = {}
        self._asc_edges: list[tuple[int, int, QPainterPath]] = []
        self._aussen = 0.0
        self.islands: dict[str, AscIsland] = {}

    # --- Aufbau --------------------------------------------------------- #

    def set_tree(self, tree: Tree | None) -> None:
        """Szene einmal je Baum bauen; Zustände setzt ``show_tree``."""
        if tree is self._tree:
            return
        self._tree = tree
        szene = self.scene()
        szene.clear()
        self._items.clear()
        self._edges.clear()
        self._edge_items.clear()
        self._rings.clear()
        self._hover_ring, self.hovered, self._hover_info = None, None, None
        self.areas = []
        self.labels = []
        self.ascendancy, self._moved, self._asc_edges, self.islands = "", {}, [], {}
        if tree is None:
            return
        for n in tree.nodes.values():
            if not _drawn(n):
                continue
            r = _RADIUS.get(n.kind, _KLEIN)
            item = QGraphicsEllipseItem(QRectF(n.x - r, n.y - r, 2 * r, 2 * r))
            item.setZValue(2)
            # Kein Qt-Tooltip: der käme erst nach rund 0,7 s (Peter: "Der
            # Tooltip erscheint im Skilltree zu langsam") — ``mouseMoveEvent``
            # zeigt ihn sofort.
            item.setData(0, n.id)
            szene.addItem(item)
            self._items[n.id] = item
        for a, knoten in tree.nodes.items():
            if a not in self._items or knoten.kind == MASTERY:
                continue
            for b in knoten.neighbours:
                if b > a and b in self._items and tree.nodes[b].kind != MASTERY:
                    self._edges.append((a, b, self._edge_path(knoten, tree.nodes[b])))
        rand = 600.0
        rechteck = szene.itemsBoundingRect().adjusted(-rand, -rand, rand, rand)
        bereiche, innen, aussen = class_areas(tree)
        self._aussen = aussen
        ring_o = QRectF(-aussen, -aussen, 2 * aussen, 2 * aussen)
        ring_i = QRectF(-innen, -innen, 2 * innen, 2 * innen)
        for klasse, w, von, bis in bereiche:
            # Qt misst gegen den Uhrzeigersinn ab 3 Uhr.
            weg = QPainterPath()
            weg.arcMoveTo(ring_o, 90.0 - von)
            weg.arcTo(ring_o, 90.0 - von, -(bis - von))
            weg.arcTo(ring_i, 90.0 - bis, bis - von)
            weg.closeSubpath()
            self.areas.append((weg, klasse.attributes))
            self._add_label(klasse, w)
        if bereiche:
            # Platz für die Insel der Aszendenz (§4.60.8, höchstens rund
            # 1300 breit) und die Beschriftung außen herum.
            weit = aussen + 4000.0
            rechteck = rechteck.united(QRectF(-weit, -weit, 2 * weit, 2 * weit))
        szene.setSceneRect(rechteck)
        self._build_ascendancies()

    @staticmethod
    def _tooltip(n: Node, choices: dict[int, int] | None = None) -> str:
        art = {KEYSTONE: "Keystone", NOTABLE: "Notable", JEWEL: "Jewel socket",
               MASTERY: "Mastery",
               START: "Ascendancy start" if n.ascendancy else "Class start"}.get(n.kind, "")
        if n.ascendancy and n.kind != START:
            art = ", ".join(filter(None, (n.ascendancy, art)))     # "Necromancer, Notable"
        kopf = f"{n.name} ({art})" if art else n.name
        # Umbrechen (Peter, 2026-10-05: "Einige sind zu lang") — ein
        # Qt-Tooltip in reinem Text bricht nicht selbst um; Wind Dancer
        # stand in einer Zeile über die halbe Bildschirmbreite.
        zeilen = [textwrap.fill(z, TOOLTIP_BREITE) for z in n.stats]
        return "\n".join([kopf, f"ID {n.id}"] + zeilen + TreeGraph._effect_lines(n, choices))

    @staticmethod
    def _effect_lines(n: Node, choices: dict[int, int] | None,
                      wrap: bool = True) -> list[str]:
        """Die Effekte einer Mastery, zum Planen (Peter, 2026-10-07: "Bei
        den Masterys sollten wir zumindest hinschreiben was möglich ist
        zum Planen"). ✓ der gewählte; ein Effekt, der schon in einer
        anderen Mastery steckt, ist vergeben — jeder nur einmal je Baum
        (gleichnamige Masteries teilen sich die Kennungen)."""
        if n.kind != MASTERY or not n.effects:
            return []
        choices = choices or {}
        anderswo = {e for k, e in choices.items() if k != n.id}
        zeilen = ["Choose one:" if n.id not in choices else "Effects:"]
        for effekt, werte in n.effects.items():
            zeichen = "✓" if choices.get(n.id) == effekt else "•"
            text = " / ".join(werte) or str(effekt)
            if effekt in anderswo:
                text += " (taken in another mastery)"
            zeile = f"{zeichen} {text}"
            zeilen.append(textwrap.fill(zeile, TOOLTIP_BREITE) if wrap else zeile)
        return zeilen

    def copy_text(self, h: int, full: bool = False) -> str:
        """Was Strg+C kopiert: Name und ID; mit Umschalt alles mit Werten
        (zum Weitergeben, etwa für eine Einschätzung)."""
        n = self._tree.nodes[h]
        if not full:
            return f"{n.name} (ID {n.id})"
        return "\n".join([f"{n.name} (ID {n.id})"] + list(n.stats)
                         + self._effect_lines(n, self.choices, wrap=False))

    @staticmethod
    def _edge_path(a: Node, b: Node) -> QPainterPath:
        """Gerade — oder ein Bogen, wenn beide auf derselben Kreisbahn
        derselben Gruppe liegen (so zeichnet es auch das Spiel)."""
        weg = QPainterPath()
        weg.moveTo(a.x, a.y)
        if a.group == b.group and a.orbit == b.orbit and a.radius > 0:
            ta = math.degrees(math.atan2(a.x - a.gx, -(a.y - a.gy)))
            tb = math.degrees(math.atan2(b.x - b.gx, -(b.y - b.gy)))
            d = (tb - ta + 540.0) % 360.0 - 180.0     # kürzerer Weg, -180..180
            rect = QRectF(a.gx - a.radius, a.gy - a.radius, 2 * a.radius, 2 * a.radius)
            # Qt misst gegen den Uhrzeigersinn ab 3 Uhr, der Baum im
            # Uhrzeigersinn ab 12 Uhr.
            weg.arcTo(rect, 90.0 - ta, -d)
            return weg
        weg.lineTo(b.x, b.y)
        return weg

    def _lage(self, h: int) -> Node:
        """Der Knoten, wie er im Bild liegt — bei der Aszendenz verschoben."""
        return self._moved.get(h) or self._tree.nodes[h]

    def _own_ascendancy(self, class_name: str) -> str:
        k, a = self._tree.class_ids.get(class_name, (-1, 0))
        klasse = next((c for c in self._tree.classes if c.index == k), None)
        if klasse is None or not 0 < a <= len(klasse.ascendancies):
            return ""
        return klasse.ascendancies[a - 1]

    def _build_ascendancies(self) -> None:
        """Die Inseln aller Aszendenzen der Klassen (§4.60.8; Peter,
        2026-10-08: "die anderen Ascendancys auch der anderen Klassen
        analog dazu einbauen? lediglich als Information"). Jede liegt in
        den Daten über dem Hauptbaum und wandert als Ganzes nach außen vor
        den Bereich ihrer Klasse, die drei einer Klasse nebeneinander — in
        der Lesereihenfolge der Beschriftung, die dahinter rückt."""
        tree = self._tree
        je_name: dict[str, list[Node]] = {}
        for n in tree.nodes.values():
            if n.ascendancy and not n.proxy and n.group >= 0:
                je_name.setdefault(n.ascendancy, []).append(n)
        szene = self.scene()
        weit_je_klasse: dict[int, float] = {}
        ohne_bereich: set[int] = set()
        for klasse in tree.classes:
            w = next((w for _t, c, w in self.labels if c is klasse), None)
            namen = [a for a in klasse.ascendancies if a in je_name]
            if w is None:
                # Ohne Bereich (Scion): eigene Richtung, und eine
                # Beschriftung, damit die Inseln einen Namen haben.
                if not namen or not self.labels:
                    continue
                w = ASC_WINKEL_OHNE_BEREICH
                self._add_label(klasse, w)
                ohne_bereich.add(klasse.index)
            # Unten im Bild läuft der Winkel von rechts nach links — dann
            # andersherum, damit die Inseln wie die Namen von links lesen.
            if math.cos(math.radians(w)) < 0:
                namen.reverse()
            for i, name in enumerate(namen):
                winkel = w + (i - (len(namen) - 1) / 2) * ASC_SPREIZUNG
                insel = self._place_island(je_name[name], winkel, klasse.attributes)
                self.islands[name] = insel
                weit_je_klasse[klasse.index] = max(weit_je_klasse.get(klasse.index, 0.0),
                                                   insel.outer)
        for a, lage in self._moved.items():
            for b in lage.neighbours:
                if b > a and b in self._moved:
                    self._asc_edges.append((a, b, self._edge_path(lage, self._moved[b])))
        for h, lage in self._moved.items():
            r = _RADIUS.get(lage.kind, _KLEIN)
            item = QGraphicsEllipseItem(QRectF(lage.x - r, lage.y - r, 2 * r, 2 * r))
            item.setZValue(2)
            item.setData(0, h)
            szene.addItem(item)
            self._items[h] = item
        # Beschriftung hinter die Inseln ihrer Klasse.
        for text, klasse, w in self.labels:
            weit = weit_je_klasse.get(klasse.index, self._aussen - ASC_ABSTAND) + (
                ASC_ABSTAND_SCHRAEG if klasse.index in ohne_bereich else ASC_ABSTAND)
            text.setPos(math.sin(math.radians(w)) * weit, -math.cos(math.radians(w)) * weit)

    def _add_label(self, klasse: ClassInfo, w: float) -> None:
        """Beschriftung am Rand. Die Schrift bleibt bei jedem Zoom gleich
        groß; ihre Lage richten ``_build_ascendancies`` (Abstand) und
        ``_paint_labels`` (Kasten nach außen) aus."""
        text = QGraphicsTextItem()
        text.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        text.setPos(math.sin(math.radians(w)) * self._aussen,
                    -math.cos(math.radians(w)) * self._aussen)
        text.setZValue(4)
        text.setAcceptHoverEvents(False)
        self.scene().addItem(text)
        self.labels.append((text, klasse, w))

    def _place_island(self, knoten: list[Node], winkel: float,
                      attribute: tuple[str, ...]) -> AscIsland:
        """Eine Insel als Ganzes (Form unverändert) nach außen schieben."""
        xs, ys = [n.x for n in knoten], [n.y for n in knoten]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        halb = max(math.hypot(n.x - cx, n.y - cy) + _RADIUS.get(n.kind, _KLEIN)
                   for n in knoten)
        mitte = self._aussen + ASC_ABSTAND + halb
        zx = math.sin(math.radians(winkel)) * mitte
        zy = -math.cos(math.radians(winkel)) * mitte
        dx, dy = zx - cx, zy - cy
        for n in knoten:
            self._moved[n.id] = dataclasses.replace(n, x=n.x + dx, y=n.y + dy,
                                                    gx=n.gx + dx, gy=n.gy + dy)
        scheibe = QPainterPath()
        scheibe.addEllipse(QPointF(zx, zy), halb + 120.0, halb + 120.0)
        return AscIsland(winkel, mitte + halb, scheibe, attribute)

    # --- Zustand -------------------------------------------------------- #

    def show_tree(self, passives: dict, class_name: str, *, compare_to: dict | None = None,
                  show_reach: bool = True, dark: bool = True) -> None:
        """``passives`` zeigen; mit ``compare_to`` als Umbau von dort aus."""
        if self._tree is None:
            return
        tree = self._tree
        self.ascendancy = self._own_ascendancy(class_name)
        # Startknoten sind nie in "hashes" — die der Klasse und der eigenen
        # Aszendenz gelten als vergeben, sonst hinge der Baum in der Luft.
        starts = {h for h, n in self._moved.items()
                  if n.kind == START and n.ascendancy == self.ascendancy}
        start = tree.class_starts.get(class_name)
        if start is not None:
            starts.add(start)
        ziel = passive_tree.allocated(passives) | starts
        basis = None
        if compare_to is not None:
            basis = passive_tree.allocated(compare_to) | starts
        self.states = {}
        for h in self._items:
            if basis is None:
                self.states[h] = ALLOCATED if h in ziel else DIM
            elif h in ziel and h in basis:
                self.states[h] = ALLOCATED
            elif h in ziel:
                self.states[h] = ALLOCATE
            elif h in basis:
                self.states[h] = REFUND
            else:
                self.states[h] = DIM
        # Gewählte Masteries leuchten wie vergebene Knoten — in der Farbe
        # des gewählten Effekts (die Mastery selbst hat keine Werte).
        self._mastery_theme = {}
        self.choices = passive_tree.mastery_choices(passives)
        for knoten_id, effekt in passive_tree.mastery_choices(passives).items():
            if knoten_id in self.states and self.states[knoten_id] == DIM:
                self.states[knoten_id] = ALLOCATED
                werte = tree.nodes[knoten_id].effects.get(effekt, ())
                self._mastery_theme[knoten_id] = passive_tree.theme(
                    Node(0, "", MASTERY, werte))
        self.reach_ids = ({r.node.id for r in passive_tree.within_reach(
            tree, passive_tree.allocated(passives), class_name=class_name)}
            if show_reach and basis is None else set())
        self._shown = ziel
        self._dark = dark
        self.comparing = basis is not None
        self._hover_info = None                   # Kosten eines Klicks neu rechnen
        self.own_class = tree.class_ids.get(class_name)
        self._paint()

    def highlight(self, text: str, center: bool = False) -> None:
        """Suchtreffer: jedes Wort in Name oder Werten (wie die Tabelle) —
        oder genau die Knoten-ID (Peter, 2026-10-05: "Wir könnten noch die
        ID in die Suche integrieren"). ``center``: beim Tippen einer ID
        dorthin springen; nicht beim Neuzeichnen nach einem Klick."""
        woerter = text.lower().split()
        self.search_ids = set()
        if woerter and self._tree is not None:
            for h in self._items:
                n = self._tree.nodes[h]
                heu = f"{n.name} {' '.join(n.stats)}".lower()
                if all(w == str(h) or w in heu for w in woerter):
                    self.search_ids.add(h)
        self._paint_rings()
        if center and len(woerter) == 1 and woerter[0].isdigit():
            h = int(woerter[0])
            if h in self._items:
                self.centerOn(self._items[h].sceneBoundingRect().center())

    def _paint(self) -> None:
        tree, farben = self._tree, _FARBEN[getattr(self, "_dark", True)]
        dunkel = getattr(self, "_dark", True)
        self.setBackgroundBrush(QBrush(self.palette().color(QPalette.ColorRole.Base)))
        for h, item in self._items.items():
            zustand = self.states.get(h, DIM)
            n = tree.nodes[h]
            if zustand == DIM:
                item.setBrush(Qt.BrushStyle.NoBrush)
                item.setPen(_cosmetic(farben["dim"], 1.5))
                continue
            if zustand == ALLOCATE:
                farbe = tree_report.colour("gain", dunkel)
            elif zustand == REFUND:
                farbe = tree_report.colour("loss", dunkel)
            elif self.comparing:
                # Beim Vergleich heißen Grün und Rot "nehmen" und
                # "zurücknehmen" — Unverändertes neutral, sonst läse sich
                # ein grüner Schutz-Knoten wie ein neuer (nativ gesehen).
                farbe = farben["edge_on"]
            elif n.kind in (KEYSTONE, START):
                farbe = tree_report.colour("keystone", dunkel)
            else:
                thema = self._mastery_theme.get(h) or passive_tree.theme(n)
                farbe = tree_report.colour(thema, dunkel) or farben["edge_on"]
            item.setBrush(QBrush(QColor(farbe)))
            item.setPen(_cosmetic(farbe, 1.5))
        # Linien in vier Pfaden statt tausender Einzelstücke.
        for alt in self._edge_items:
            self.scene().removeItem(alt)
        self._edge_items = []
        pfade = {k: QPainterPath() for k in ("edge", "edge_on", "gain", "loss")}
        for a, b, weg in self._edges + self._asc_edges:
            za, zb = self.states.get(a, DIM), self.states.get(b, DIM)
            an = {ALLOCATED, ALLOCATE}
            if za in an and zb in an:
                art = "edge_on" if za == zb == ALLOCATED else "gain"
            elif {za, zb} <= {ALLOCATED, REFUND} and REFUND in (za, zb):
                art = "loss"
            else:
                art = "edge"
            pfade[art].addPath(weg)
        for art, breite, z in (("edge", 1.0, 0), ("edge_on", 2.5, 1), ("gain", 3.0, 1),
                               ("loss", 3.0, 1)):
            if pfade[art].isEmpty():
                continue
            farbe = (tree_report.colour(art == "gain" and "gain" or "loss", dunkel)
                     if art in ("gain", "loss") else farben[art])
            item = self.scene().addPath(pfade[art], _cosmetic(farbe, breite))
            item.setZValue(z)
            self._edge_items.append(item)
        self._paint_labels()
        self._paint_rings()
        self.resetCachedContent()
        self.viewport().update()

    def _paint_labels(self) -> None:
        dunkel = self._dark
        schrift = _SCHRIFT[dunkel]
        gold = tree_report.colour("keystone", dunkel)
        eigen_k, eigen_a = self.own_class if self.own_class else (-1, -1)
        for text, klasse, w in self.labels:
            kopf = gold if klasse.index == eigen_k else schrift["class"]
            namen = []
            for nummer, name in enumerate(klasse.ascendancies, start=1):
                if klasse.index == eigen_k and nummer == eigen_a:
                    namen.append(f'<b style="color:{gold}">{html.escape(name)}</b>')
                else:
                    namen.append(html.escape(name))
            text.setHtml(
                f'<div align="center"><span style="font-size:13pt; font-weight:600; '
                f'color:{kopf}">{html.escape(klasse.name)}</span><br>'
                f'<span style="color:{schrift["asc"]}">{" · ".join(namen)}</span></div>')
            text.setTextWidth(-1)
            text.setTextWidth(text.document().idealWidth())
            # Den Kasten außen an den Randpunkt legen (in Pixeln, weil die
            # Schrift nicht mitzoomt): Mitte des Kastens um seine halbe
            # Ausdehnung in Richtung des Bereichs nach außen.
            b = text.boundingRect()
            dx, dy = math.sin(math.radians(w)), -math.cos(math.radians(w))
            hw, hh = b.width() / 2, b.height() / 2
            weg = min(hw / abs(dx) if abs(dx) > 1e-6 else math.inf,
                      hh / abs(dy) if abs(dy) > 1e-6 else math.inf) + 8.0
            text.setTransform(QTransform.fromTranslate(dx * weg - hw, dy * weg - hh))

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802 (Qt-API)
        super().drawBackground(painter, rect)
        if not self.areas and not self.islands:
            return
        toenung = _TOENUNG[self._dark]
        welt = painter.worldTransform()
        painter.save()
        # In Bildschirmpixeln malen: Streifen gleich breit bei jedem Zoom,
        # aber mit dem Baum verschoben (Ursprung des Musters = Baummitte).
        painter.resetTransform()
        painter.setBrushOrigin(welt.map(QPointF(0.0, 0.0)))
        painter.setPen(Qt.PenStyle.NoPen)
        scheiben = [(i.disc, i.attributes) for i in self.islands.values()]
        for weg, attribute in self.areas + scheiben:
            farben = tuple(toenung[a] for a in attribute if a in toenung)
            if not farben:
                continue
            painter.setBrush(QBrush(QColor(farben[0])) if len(farben) == 1
                             else _streifen(farben))
            painter.drawPath(welt.map(weg))
        # Die eigene Aszendenz golden umrandet — wie ihr Name am Rand.
        eigene = self.islands.get(self.ascendancy)
        if eigene is not None:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tree_report.colour("keystone", self._dark)), 2.0))
            painter.drawPath(welt.map(eigene.disc))
        painter.restore()

    def _paint_rings(self) -> None:
        if self._tree is None:
            return
        farben = _FARBEN[getattr(self, "_dark", True)]
        for ring in self._rings:
            self.scene().removeItem(ring)
        self._rings = []
        for ids, art, abstand, breite in ((self.reach_ids, "reach", 14.0, 1.5),
                                          (self.search_ids, "search", 30.0, 3.0)):
            for h in ids:
                if h not in self._items:          # nicht gezeichnet (Aszendenz, ohne Lage)
                    continue
                n = self._lage(h)
                r = _RADIUS.get(n.kind, _KLEIN) + abstand
                ring = self.scene().addEllipse(QRectF(n.x - r, n.y - r, 2 * r, 2 * r),
                                               _cosmetic(farben[art], breite))
                ring.setZValue(3)
                ring.setAcceptHoverEvents(False)
                self._rings.append(ring)

    # --- Ansicht -------------------------------------------------------- #

    def fit_allocated(self) -> None:
        """Auf den vergebenen Teil zoomen (beim ersten Zeigen)."""
        rechteck = QRectF()
        for h in self._shown:
            if h in self._items:
                rechteck = rechteck.united(self._items[h].sceneBoundingRect())
        if rechteck.isEmpty():
            rechteck = self.scene().sceneRect()
        rand = max(rechteck.width(), rechteck.height()) * 0.15 + 400
        self.fitInView(rechteck.adjusted(-rand, -rand, rand, rand),
                       Qt.AspectRatioMode.KeepAspectRatio)

    def _click_info(self, h: int) -> tuple[str | None, bool]:
        """(Zusatzzeile, klickbar) — einmal je Knoten unter der Maus
        gerechnet, nicht bei jeder Bewegung (die Wegsuche kostet)."""
        if self.click_hint is None:
            return None, False
        if self._hover_info is not None and self._hover_info[0] == h:
            return self._hover_info[1]
        roh = self.click_hint(h)
        info = roh if isinstance(roh, tuple) else (roh, roh is not None)
        self._hover_info = (h, info)
        return info

    def tooltip_at(self, punkt: QPoint) -> str | None:
        """Der Text zum Knoten unter ``punkt`` (Viewport-Koordinaten)."""
        h = self.node_at(punkt)
        if h is None:
            return None
        text = self._tooltip(self._tree.nodes[h], self.choices)
        zusatz = self._click_info(h)[0]
        unten = [zusatz] if zusatz else []
        unten.append("Ctrl+C: copy name and ID · Ctrl+Shift+C: with stats")
        return f"{text}\n\n" + "\n".join(unten)

    def hover(self, h: int | None) -> None:
        """Knoten unter der Maus: Ring drumherum und Zeiger "Hand", wenn ein
        Klick etwas tut, "verboten", wenn nicht (Peter, 2026-10-05: "den
        Cursor ändern wenn der Mauscursor über der Node ist und evtl auch
        die Node hovern"). Ohne ``click_hint`` (nur ansehen) kein Ring."""
        if h == self.hovered:
            return
        self.hovered = h
        if self._hover_ring is not None:
            self.scene().removeItem(self._hover_ring)
            self._hover_ring = None
        if h is None or self.click_hint is None or self._tree is None:
            # Zurück auf den Zeiger fürs Verschieben (nicht den Pfeil).
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            return
        _text, klickbar = self._click_info(h)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if klickbar
                                  else Qt.CursorShape.ForbiddenCursor)
        n = self._lage(h)
        # Außerhalb von Reichweiten- (+14) und Suchring (+30).
        r = _RADIUS.get(n.kind, _KLEIN) + 44.0
        self._hover_ring = self.scene().addEllipse(
            QRectF(n.x - r, n.y - r, 2 * r, 2 * r), _cosmetic(_FARBEN[self._dark]["hover"], 3.0))
        self._hover_ring.setZValue(5)
        self._hover_ring.setAcceptHoverEvents(False)

    def viewportEvent(self, event) -> bool:  # noqa: N802 (Qt-API)
        # Qts eigenes Tooltip-Ereignis schlucken. Es kommt nur im AKTIVEN
        # Fenster, nach ~0,7 s Ruhe; die Szene sucht dann einen Item-
        # Tooltip, findet keinen (wir zeigen ihn selbst, mouseMoveEvent)
        # und blendet mit leerem Text "den" Tooltip aus — unseren, 0,3 s
        # später. Peter, 2026-10-07: "Wenn es aktiv ist und ich geh drüber
        # verschwindet der Tooltip nach 1s", im inaktiven Fenster nicht.
        if event.type() == QEvent.Type.ToolTip:
            return True
        return super().viewportEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        self.hover(None)
        super().leaveEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        # Fokus, damit Strg+C hier ankommt und nicht im Suchfeld.
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().enterEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        kopieren = (event.key() == Qt.Key.Key_C
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if kopieren and self.hovered is not None and self._tree is not None:
            voll = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            text = self.copy_text(self.hovered, full=voll)
            QGuiApplication.clipboard().setText(text)
            QToolTip.showText(QCursor.pos(), f"Copied: {text.splitlines()[0]}",
                              self.viewport())
            event.accept()
            return
        super().keyPressEvent(event)

    def node_at(self, punkt: QPoint) -> int | None:
        for item in self.items(punkt):
            h = item.data(0)
            if isinstance(h, int) and self._tree is not None and h in self._tree.nodes:
                return h
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        super().mouseReleaseEvent(event)
        start, self._press = self._press, None
        punkt = event.position().toPoint()
        # Ein Klick, kein Verschieben: höchstens ein paar Pixel bewegt.
        if start is None or (punkt - start).manhattanLength() > 4:
            return
        h = self.node_at(punkt)
        if h is not None and event.button() in (Qt.MouseButton.LeftButton,
                                                Qt.MouseButton.RightButton):
            self.node_clicked.emit(h, event.button() == Qt.MouseButton.RightButton)
        # Das Verschieben setzt den Zeiger auf "Hand offen" zurück; der
        # Knoten unter der Maus bekommt seinen wieder (Kosten neu gerechnet).
        self.hovered = None
        self.hover(self.node_at(punkt))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        super().mouseMoveEvent(event)
        if event.buttons():                       # beim Verschieben kein Tooltip
            return
        self.hover(self.node_at(event.position().toPoint()))
        text = self.tooltip_at(event.position().toPoint())
        if text:
            QToolTip.showText(event.globalPosition().toPoint(), text, self.viewport(),
                              QRect(), TOOLTIP_MS)
        else:
            QToolTip.hideText()

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        faktor = 1.2 ** (event.angleDelta().y() / 120)
        skala = self.transform().m11() * faktor
        if 0.01 <= skala <= 3.0:
            self.scale(faktor, faktor)
        event.accept()
