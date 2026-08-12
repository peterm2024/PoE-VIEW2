"""Leveling-Panel rechts neben dem Item-Detail.

Peter, 2026-08-12: "Ich hätte den rechten (freien) Bereich hier gerne
für unsere Leveling-Infos (XP/h-Graph) benutzt." Anlass war eigentlich
die Breite: Seit das Detail-Panel seine Blöcke durch Linien trennt
(§4.39), zogen sich die über die ganze Fensterbreite. Ein Splitter
begrenzt sie — und die Fläche daneben bekommt eine Aufgabe.

**Der Graph ist hier NOCH NICHT drin, und das mit Absicht.** Er braucht
einen Zeitreihen-Speicher, den es nicht gibt: `_XpWatch` merkt sich
genau zwei Veröffentlichungen (die letzte und die davor), mehr braucht
die Rate nicht. Ein Graph braucht den ganzen Abend. Das ist ein eigenes
Vorhaben, kein Beiwerk dieses Umbaus — solange zeigt das Panel die
Zahlen, die ohnehin schon berechnet werden, und zwar größer und
dauerhaft statt zusammengedrängt in der Statuszeile.

Bewusst ein eigenes Widget mit einer stumpfen ``show``-Methode: Es
rechnet nichts selbst, sondern bekommt fertige Werte. Damit lässt es
sich ohne Charakterdaten und ohne laufende Uhr prüfen, und der Graph
später kann daneben wachsen, ohne dass ``main_window`` etwas davon
mitbekommt.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


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

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._body)
        layout.addStretch()

    def clear(self) -> None:
        self._title.setText("Leveling")
        self._body.setText("No character selected")

    def show_character(self, name: str, level: int | None, experience: int | None,
                       rate_text: str | None, age_note: str) -> None:
        """``rate_text`` ist die fertig formatierte Rate ("119.2M XP/h")
        oder ``None``, solange erst eine Veröffentlichung beobachtet wurde
        — dann steht dort, WARUM noch nichts da ist. Das ist keine
        Höflichkeit: GGG veröffentlicht Erfahrung erst beim Verlassen
        einer Zone, ein leeres Feld sähe nach einem Fehler aus."""
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
