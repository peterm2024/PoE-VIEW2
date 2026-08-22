"""Zwei Dialoge, die denselben Zweck haben: den Login sichtbar machen.

Peter, 2026-08-21: "habe gerade schon wieder vergessen mich einzuloggen".
Bis dahin sagte ein fehlender oder abgelaufener Login nur zweierlei: die
Beschriftung des Toolbar-Knopfes wechselte auf "🔑 Log in", und in der
Statuszeile stand ein Satz, den die nächste Meldung überschreiben kann.
Beides ist leicht zu übersehen — und weil der Datei-Cache Baum,
Charakterliste und Items ohne Login weiter anzeigt (§4.7/§4.12), sieht
ein nicht angemeldetes PoE-VIEW2 aus wie ein angemeldetes, das gerade
nichts Neues findet.

- ``WelcomeDialog`` beim Programmstart ohne gültiges Token.
- ``SessionExpiredDialog``, wenn das Token MITTEN in der Sitzung abläuft.

**Beide bewusst nicht-modal** (Peters Entscheidung): Der Cache soll ohne
Login durchsuchbar bleiben — das ist eine ausdrückliche Design-
Entscheidung (§4.8, FALLSTRICKE #46), und ein modaler Dialog würde
ausgerechnet das blockieren.

**Texte auf Englisch**, wie die gesamte Oberfläche (siehe
``help_dialog``); Kommentare und Doku bleiben deutsch.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

# Anteil der Textfarbe in einer "gedämpften" Nebenzeile; der Rest ist
# Hintergrund. 0.65 ist keine geschmackliche Zahl, sondern nachgerechnet:
# Sie hält den WCAG-Kontrast in Peters dunklem Windows-Design (#1e1e1e)
# UND im hellen Systemdesign über 4.5:1, siehe test_login_prompts.
_MUTED_TEXT_RATIO = 0.65


def muted_colour(palette: QPalette) -> QColor:
    """Gedämpfte Textfarbe, aus der Palette gerechnet statt eingetippt.

    Der naheliegende Weg — ``color: palette(mid)`` im Stylesheet — war
    nachweislich falsch: In Peters dunklem Design ergibt ``mid`` #282828
    auf #1e1e1e, also **1.13:1**. Das ist keine Dämpfung mehr, das ist
    Unsichtbarkeit; wer die Fehlermeldung braucht, kommt nicht an sie
    heran. Auch die übrigen "grauen" Rollen taugen nicht (``light``
    3.78:1, ``midlight`` 2.42:1) — sie sind für 3D-Rahmen gedacht, nicht
    für Text.

    Ein fest eingetipptes Grau wäre der zweite Fehler: Im hellen
    Systemdesign wäre es ein Fleck (dieselbe Lehre wie beim
    Gem-Balken-Hintergrund, §4.42). Deshalb Textfarbe in Richtung
    Hintergrund mischen — das dreht sich in einem hellen Design von
    selbst um."""
    vorne = palette.color(QPalette.ColorRole.WindowText)
    hinten = palette.color(QPalette.ColorRole.Window)
    misch = _MUTED_TEXT_RATIO
    return QColor(
        round(hinten.red() + misch * (vorne.red() - hinten.red())),
        round(hinten.green() + misch * (vorne.green() - hinten.green())),
        round(hinten.blue() + misch * (vorne.blue() - hinten.blue())),
    )


class _LoginPromptBase(QDialog):
    """Gemeinsames Gerüst: nicht-modal, kein Kontexthilfe-Knopf, und ein
    ``login_requested``-Signal statt eines direkten Zugriffs auf den
    Worker — die Dialoge kennen weder Jobs noch Token."""

    login_requested = Signal()

    # Ohne Mindestbreite schrumpft Qt den Dialog auf die Breite des
    # laengsten Knopfes — nativ gemessen 262 px, worin die umbrechenden
    # Absaetze zu sechs- und siebenzeiligen Tuermen werden (der
    # Erststart-Dialog kam so auf 401 px Hoehe). Mit 430 px stehen die
    # Absaetze in drei bis vier Zeilen. Bewusst MINIMUM, keine feste
    # Groesse: Wer eine groessere Schrift eingestellt hat, braucht mehr.
    _MIN_WIDTH = 430

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        # **Elternteil = das Hauptfenster, und das ist die ganze Technik
        # hinter "bleibt oben"** (Peter, 2026-08-22: "Können wir den
        # Login-Dialog auf Top-Layer legen, so dass er sich nicht vom
        # Hauptfenster verdecken lässt? Nicht modal, aber Top-Layer").
        # Ein Kind-Dialog liegt beim Fenstermanager dauerhaft über seinem
        # Elternfenster; ohne Elternteil sind es zwei gleichrangige
        # Fenster, und ein Klick ins Hauptfenster schiebt den Dialog
        # dahinter.
        #
        # BEWUSST NICHT ``WindowStaysOnTopHint``: Das hielte den Dialog
        # über ALLEM, auch über Path of Exile im Fenstermodus und über
        # dem Browser, in dem man sich gerade anmelden soll. Peters Satz
        # nennt ausdrücklich das Hauptfenster, und genau so weit reicht
        # ein Elternteil.
        #
        # Und es macht den Dialog NICHT modal — das entscheidet allein
        # ``setModal``/``windowModality``, nicht die Elternschaft. (In
        # einer früheren Fassung stand hier das Gegenteil als Begründung
        # dafür, keinen Elternteil zu setzen. Das war schlicht falsch.)
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setMinimumWidth(self._MIN_WIDTH)
        # Der Fragezeichen-Knopf in der Titelleiste öffnet nichts (wir
        # liefern keine Kontexthilfe) und sähe nach einem toten Bedienelement aus.
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line


class WelcomeDialog(_LoginPromptBase):
    """Startdialog, wenn kein gültiges Token vorliegt.

    ``first_run`` blendet zusätzlich einen "Getting started"-Abschnitt
    ein. Peters Wunsch war "beim ersten Start zum Konfigurieren und
    Login" — und beim allerersten Start gibt es nie ein Token, "erster
    Start" und "nicht angemeldet" fallen also zusammen. Unterschiedlich
    ist nur der INHALT, nicht die Bedingung.

    Der Abschnitt führt bewusst in den echten Settings-Dialog, statt
    dessen Bedienelemente hier ein zweites Mal aufzubauen: Eine Kopie des
    Zone-Refresh-Feldes samt seiner Pfad-Prüfung wäre beim nächsten
    Umbau die Stelle, die stehen bleibt.
    """

    settings_requested = Signal()

    def __init__(self, cache_summary: str, *, first_run: bool = False,
                 show_on_startup: bool = True, parent: QWidget | None = None) -> None:
        super().__init__("Welcome to PoE-VIEW2", parent)
        layout = QVBoxLayout(self)

        headline = QLabel("<b>You are not logged in.</b>")
        headline.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(headline)

        explanation = QLabel(
            "Logging in with your Path of Exile account lets PoE-VIEW2 read "
            "your stash and characters from GGG's official API. Without it "
            "you can still browse everything already stored on this PC.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        layout.addWidget(self._separator())
        summary = QLabel(cache_summary)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        if first_run:
            layout.addWidget(self._separator())
            hint = QLabel(
                "<b>Getting started.</b> Two things are worth setting up once: "
                "pick your league in the toolbar, and — if you want the stash "
                "to refresh the moment you change zones in game — point "
                "PoE-VIEW2 at your <i>Client.txt</i> under Settings → Zone Refresh.")
            hint.setWordWrap(True)
            hint.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(hint)
            settings_button = QPushButton("⚙ Open settings…")
            settings_button.clicked.connect(self.settings_requested.emit)
            layout.addWidget(settings_button)

        layout.addWidget(self._separator())
        self.show_again = QCheckBox("Show this when I am not logged in")
        self.show_again.setChecked(show_on_startup)
        self.show_again.setToolTip(
            "Unchecked, PoE-VIEW2 starts straight into the local data and only "
            "mentions the missing login in the status bar.")
        layout.addWidget(self.show_again)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        offline = QPushButton("Continue offline")
        offline.clicked.connect(self.reject)
        buttons.addWidget(offline)
        login = QPushButton("🔑 Log in")
        login.setDefault(True)
        login.clicked.connect(self._on_login)
        buttons.addWidget(login)
        layout.addLayout(buttons)

    def _on_login(self) -> None:
        self.login_requested.emit()
        self.accept()


class SessionExpiredDialog(_LoginPromptBase):
    """Meldung, wenn das Token mitten in der Sitzung abläuft.

    Bewusst eine eigene Klasse statt einer ``QMessageBox``: Die soll
    modal sein, und ein nicht-modales Exemplar davon verhält sich je nach
    Plattform unterschiedlich. Hier ist die Nicht-Modalität die
    eigentliche Anforderung.

    Der Text sagt ausdrücklich, dass die lokalen Daten weiter benutzbar
    sind — sonst liest sich die Meldung wie ein Abbruch, obwohl fast
    alles weiterläuft."""

    def __init__(self, reason: str = "", parent: QWidget | None = None) -> None:
        super().__init__("Login expired", parent)
        layout = QVBoxLayout(self)

        headline = QLabel("<b>Your Path of Exile login has expired.</b>")
        headline.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(headline)

        text = QLabel(
            "Background refreshing has stopped. Everything already stored on "
            "this PC stays browsable — log in again to resume live updates.")
        text.setWordWrap(True)
        layout.addWidget(text)

        if reason:
            detail = QLabel(reason)
            detail.setWordWrap(True)
            detail.setStyleSheet(f"color: {muted_colour(self.palette()).name()};")
            layout.addWidget(detail)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = QPushButton("Later")
        later.clicked.connect(self.reject)
        buttons.addWidget(later)
        login = QPushButton("🔑 Log in")
        login.setDefault(True)
        login.clicked.connect(self._on_login)
        buttons.addWidget(login)
        layout.addLayout(buttons)

    def _on_login(self) -> None:
        self.login_requested.emit()
        self.accept()
