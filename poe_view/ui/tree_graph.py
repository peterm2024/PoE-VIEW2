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

Gezeichnet werden weder die Aszendenz (eigener Baum, liegt in den Daten
weit außerhalb) noch Platzhalter für Cluster-Jewels. Linien und Ränder
sind "kosmetisch": gleich dick, egal wie weit hineingezoomt ist.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsScene, QGraphicsView,
                               QToolTip)

from poe_view.services import passive_tree
from poe_view.services.passive_tree import (JEWEL, KEYSTONE, MASTERY, NOTABLE, START, Node,
                                            Tree)
from poe_view.ui import tree_report

# Halbmesser in Baum-Einheiten (der Baum ist rund 25.000 breit, eine
# Kreisbahn 82 bis 846).
_RADIUS = {KEYSTONE: 56.0, NOTABLE: 40.0, JEWEL: 36.0, MASTERY: 28.0, START: 60.0}
_KLEIN = 26.0

# Zustände eines Knotens.
DIM, ALLOCATED, ALLOCATE, REFUND = "dim", "allocated", "allocate", "refund"

# Gerechnet gegen den Grund (Base #2d2d2d / #ffffff), Ziel 3:1 für
# Grafik: gedämpft dunkel 3,2:1, hell 3,5:1; Ring "Reichweite" 7,5 / 4,5;
# Suchtreffer 9,8 / 3,3.
_FARBEN = {
    True: {"dim": "#7a7a7a", "edge": "#4f4f4f", "edge_on": "#d8d8d8",
           "reach": "#4dd0e1", "search": "#ffd54f"},
    False: {"dim": "#8a8a8a", "edge": "#d0d0d0", "edge_on": "#3a3a3a",
            "reach": "#00838f", "search": "#b8860b"},
}


def _drawn(n: Node) -> bool:
    # Gezeichnet wird, was einer Gruppe angehört — nicht "was nicht bei 0/0
    # liegt": ein Knoten genau im Ursprung fiele sonst weg (im Test gesehen).
    return not n.ascendancy and not n.proxy and n.group >= 0


def _cosmetic(farbe: str, breite: float) -> QPen:
    stift = QPen(QColor(farbe), breite)
    stift.setCosmetic(True)
    return stift


class TreeGraph(QGraphicsView):
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
        szene.setSceneRect(szene.itemsBoundingRect().adjusted(-rand, -rand, rand, rand))

    @staticmethod
    def _tooltip(n: Node) -> str:
        art = {KEYSTONE: "Keystone", NOTABLE: "Notable", JEWEL: "Jewel socket",
               MASTERY: "Mastery", START: "Class start"}.get(n.kind, "")
        kopf = f"{n.name} ({art})" if art else n.name
        return "\n".join([kopf] + list(n.stats))

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

    # --- Zustand -------------------------------------------------------- #

    def show_tree(self, passives: dict, class_name: str, *, compare_to: dict | None = None,
                  show_reach: bool = True, dark: bool = True) -> None:
        """``passives`` zeigen; mit ``compare_to`` als Umbau von dort aus."""
        if self._tree is None:
            return
        tree = self._tree
        ziel = passive_tree.allocated(passives)
        start = tree.class_starts.get(class_name)
        if start is not None:
            ziel = ziel | {start}
        basis = None
        if compare_to is not None:
            basis = passive_tree.allocated(compare_to) | ({start} if start is not None else set())
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
        self._paint()

    def highlight(self, text: str) -> None:
        """Suchtreffer: jedes Wort in Name oder Werten (wie die Tabelle)."""
        woerter = text.lower().split()
        self.search_ids = set()
        if woerter and self._tree is not None:
            for h in self._items:
                n = self._tree.nodes[h]
                heu = f"{n.name} {' '.join(n.stats)}".lower()
                if all(w in heu for w in woerter):
                    self.search_ids.add(h)
        self._paint_rings()

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
        for a, b, weg in self._edges:
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
        self._paint_rings()

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
                n = self._tree.nodes[h]
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

    def tooltip_at(self, punkt: QPoint) -> str | None:
        """Der Text zum Knoten unter ``punkt`` (Viewport-Koordinaten)."""
        if self._tree is None:
            return None
        for item in self.items(punkt):
            h = item.data(0)
            if isinstance(h, int) and h in self._tree.nodes:
                return self._tooltip(self._tree.nodes[h])
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        super().mouseMoveEvent(event)
        if event.buttons():                       # beim Verschieben kein Tooltip
            return
        text = self.tooltip_at(event.position().toPoint())
        if text:
            QToolTip.showText(event.globalPosition().toPoint(), text, self.viewport())
        else:
            QToolTip.hideText()

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        faktor = 1.2 ** (event.angleDelta().y() / 120)
        skala = self.transform().m11() * faktor
        if 0.01 <= skala <= 3.0:
            self.scale(faktor, faktor)
        event.accept()
