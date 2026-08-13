"""Leveling-Panel rechts neben dem Item-Detail.

Peter, 2026-08-12: "Ich hätte den rechten (freien) Bereich hier gerne
für unsere Leveling-Infos (XP/h-Graph) benutzt." Anlass war eigentlich
die Breite: Seit das Detail-Panel seine Blöcke durch Linien trennt
(§4.39), zogen sich die über die ganze Fensterbreite. Ein Splitter
begrenzt sie — und die Fläche daneben bekommt eine Aufgabe.

Der Graph darunter kam am 2026-08-13 dazu (`ui/xp_graph.py`), nachdem
Peter die offene Frage beantwortet hatte, was auf die x-Achse gehört:
drei Stunden Zeit, ein Balken je abgeschlossenem Abschnitt.

Bewusst ein eigenes Widget mit einer stumpfen ``show``-Methode: Es
rechnet nichts selbst, sondern bekommt fertige Werte. Damit lässt es
sich ohne Charakterdaten und ohne laufende Uhr prüfen.
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from poe_view.ui.xp_graph import XpGraph, XpPoint


class LevelingPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._title = QLabel("Leveling")
        self._title.setStyleSheet("font-weight: 600; font-size: 13px;")
        self._body = QLabel("No character selected")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._graph = XpGraph()

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._body)
        layout.addWidget(self._graph, stretch=1)

    def clear(self) -> None:
        """Ohne Charakter verschwindet auch die Achse. Eine leere Achse
        neben "No character selected" behauptete, es gäbe hier einen
        Verlauf zu sehen — bei einem Charakter OHNE Abschnitte ist genau
        das dagegen die richtige Aussage, deshalb bleibt sie dort."""
        self._title.setText("Leveling")
        self._body.setText("No character selected")
        self._graph.clear()
        self._graph.hide()

    def show_character(self, name: str, level: int | None, experience: int | None,
                       rate_text: str | None, age_note: str,
                       points: Sequence[XpPoint] = (), now: float = 0.0) -> None:
        """``rate_text`` ist die fertig formatierte Rate ("119.2M XP/h")
        oder ``None``, solange erst eine Veröffentlichung beobachtet wurde
        — dann steht dort, WARUM noch nichts da ist. Das ist keine
        Höflichkeit: GGG veröffentlicht Erfahrung erst beim Verlassen
        einer Zone, ein leeres Feld sähe nach einem Fehler aus.

        ``points``/``now`` speisen den Graphen darunter; ohne sie zeigt er
        eine leere Achse, was für einen Charakter ohne beobachteten
        Abschnitt genau richtig ist."""
        self._title.setText(name)
        lines = []
        if level:
            lines.append(f"Level {level}")
        if experience:
            lines.append(f"{experience:,} XP total".replace(",", " "))
        if rate_text:
            lines.append(f"<b>{rate_text}</b>{age_note}")
        else:
            lines.append("<i>Rate follows after the next zone change</i>")
        self._body.setText("<br>".join(lines))
        self._graph.set_points(points, now)
        self._graph.show()
