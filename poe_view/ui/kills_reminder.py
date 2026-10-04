"""Die Erinnerung an ``/kills``: ein kurzer Gong und ein kleines Fenster.

Peter, 2026-10-02: "Ich benötige aber eine Erinnerung von dir wenn ich
eine Killzone betrete, einen kurzen Gong und ein kleines aufpoppendes
Fenster mit der Aufforderung den Befehl einzugeben."

**Das Fenster darf dem Spiel den Fokus nicht nehmen.** Wer gerade in eine
Map läuft, tippt oder klickt dort weiter; ein Fenster, das die Tastatur an
sich zieht, schluckte den nächsten Tastendruck. Deshalb ein Werkzeugfenster
ohne Rahmen, immer oben, das sich ohne Aktivierung zeigt
(``WA_ShowWithoutActivating``). Es verschwindet von selbst, sobald die
Zeile ``You have killed …`` in der Client.txt steht, nach
``AUTO_HIDE_MS`` oder bei einem Klick darauf. Über dem Spiel liegt es nur
im Modus "Windowed Fullscreen" oder im Fenster — echtes Vollbild
überdeckt jedes andere Fenster.

**Der Gong wird gerechnet, nicht mitgeliefert:** ein paar Sinustöne im
Verhältnis einer Glocke, jeder mit eigenem Ausklingen. Das spart eine
Audiodatei im Repo samt Lizenzfrage und Qts Multimedia-Modul in der .exe;
abgespielt wird über ``winsound`` aus der Standardbibliothek. Außerhalb von
Windows bleibt es beim Systemton.
"""

from __future__ import annotations

import logging
import math
import struct
import sys
import wave
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPalette, QScreen
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from poe_view import config

log = logging.getLogger(__name__)

AUTO_HIDE_MS = 30_000
# Auffällig soll es sein (§KillsReminder): Schrift und Abstände doppelt so
# groß wie im übrigen Programm, ein dicker roter Rahmen.
GROESSE = 2
RAHMEN_PX = 5
RAHMEN_FARBE = "#e53935"
# Schon in der Map, als PoE-VIEW2 startete (§KillsReminder.pop, ``late``):
# gelb statt rot und nach drei Sekunden wieder weg. Peter, 2026-10-04:
# "...so dass es am Spieler hängt, ob er für diese Runde die Kills zählen
# will." Zwei Gelbs, je nach Grund gerechnet: #fbc02d auf dem dunklen
# Fenstergrund 10,1:1, auf dem hellen nur 1,45:1 — dort #b8860b mit
# 2,86:1, das hellste Gelb, das dem Rot (3,71:1) nahekommt.
SPAET_MS = 3_000
SPAET_FARBE_DUNKEL = "#fbc02d"
SPAET_FARBE_HELL = "#b8860b"
# Abstand vom oberen Bildschirmrand als Anteil der Höhe (§KillsReminder.pop).
_OBEN_ANTEIL = 0.12

_RATE = 44_100
_DAUER_S = 1.1
# Grundton und die Teiltöne einer Glocke (Verhältnisse 1 : 2 : 2,76 :
# 5,4), höhere klingen schneller aus. Lautstärke bewusst zurückhaltend:
# Der Ton soll über dem Spiel zu hören sein, nicht erschrecken.
_GRUNDTON_HZ = 523.25
_TEILTOENE = ((1.0, 1.0, 2.8), (2.0, 0.45, 4.0), (2.76, 0.35, 5.5), (5.4, 0.15, 9.0))
_SPITZE = 0.32


def gong_path() -> Path:
    """Funktion statt Konstante (CLAUDE.md, "Tests")."""
    return config.APP_DATA_DIR / "kills-gong.wav"


def write_gong(path: Path) -> None:
    """Den Gong als 16-Bit-Mono-WAV schreiben."""
    gesamt = sum(amp for _ratio, amp, _abkling in _TEILTOENE)
    proben = bytearray()
    for n in range(int(_RATE * _DAUER_S)):
        t = n / _RATE
        anschlag = min(t / 0.004, 1.0)  # 4 ms Anstieg, sonst knackt es
        wert = sum(amp * math.exp(-abkling * t)
                   * math.sin(2 * math.pi * _GRUNDTON_HZ * ratio * t)
                   for ratio, amp, abkling in _TEILTOENE)
        proben += struct.pack("<h", int(32767 * _SPITZE * anschlag * wert / gesamt))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(_RATE)
        datei.writeframes(bytes(proben))


def play_gong() -> None:
    """Asynchron abspielen — der Zonenwechsel wartet nicht auf den Ton.
    Ein Fehler hier darf nichts weiter aufhalten; es bleibt beim
    Systemton."""
    try:
        if sys.platform != "win32":
            QApplication.beep()
            return
        import winsound
        pfad = gong_path()
        if not pfad.exists():
            write_gong(pfad)
        winsound.PlaySound(str(pfad), winsound.SND_FILENAME | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)
    except Exception:  # noqa: BLE001 — siehe Docstring
        log.exception("Kill-Erinnerung: Gong nicht abgespielt")
        QApplication.beep()


def game_window_rect() -> QRect | None:
    """Wo das Spielfenster liegt — oder ``None``, wenn keins offen ist.

    Peter, 2026-10-03: "Gong ist gekommen und passt. Das Fenster sehe ich
    nicht." Es stand unten rechts auf dem Hauptmonitor; PoE lief auf dem
    Monitor links davon (Fenster bei x=-2560, nativ ausgelesen). Gelesen
    wird nur die Lage des Fensters über seinen Klassennamen, nichts
    sonst — PoE-VIEW2 schreibt weiterhin nie ins Spiel."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW("POEWindowClass", None)
        if not hwnd or not user32.IsWindowVisible(hwnd):
            return None
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:  # noqa: BLE001 — dann eben der Ausweich-Bildschirm
        log.exception("Kill-Erinnerung: Spielfenster nicht gefunden")
        return None


def target_screen(fallback: QScreen | None) -> QScreen | None:
    """Der Bildschirm, auf dem das Spiel liegt; sonst ``fallback`` (der
    von PoE-VIEW2), sonst der Hauptbildschirm."""
    spiel = game_window_rect()
    if spiel is not None:
        bildschirm = QGuiApplication.screenAt(spiel.center())
        if bildschirm is not None:
            return bildschirm
    return fallback or QGuiApplication.primaryScreen()


class KillsReminder(QWidget):
    """Das kleine Fenster oben mittig auf dem Bildschirm des Spiels."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("killsReminder")
        # Ohne das malt eine eigene QWidget-Unterklasse Hintergrund und
        # Rahmen aus dem Stylesheet nicht (nativ gesehen: kein Rahmen).
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        # Eigene Fläche mit Rahmen: Ohne Fensterrahmen ginge das Fenster
        # sonst auf einem dunklen Spielbild unter. Peter, 2026-10-03: "Mach
        # den Rahmen rot und dicker und das Fenster doppelt so groß. Es muss
        # ins Auge stechen." Das Rot ist gerechnet: gegen den dunklen Grund
        # 3,94:1, gegen den hellen 3,71:1 — beide über 3:1 für Bedien-
        # elemente; grellere Töne (#ff3b30) fielen hell auf 3,1.
        self._rahmen(RAHMEN_FARBE)
        # Die Schrift an jede Beschriftung einzeln: Mit einem Stylesheet am
        # Fenster gibt Qt ein setFont() des Fensters nicht an die Kinder
        # weiter (nativ gemessen: Fenster 18 pt, Beschriftungen 9 pt).
        schrift = self.font()
        schrift.setPointSizeF(schrift.pointSizeF() * GROESSE)
        fett = self.font()
        fett.setPointSizeF(schrift.pointSizeF())
        fett.setBold(True)
        self._titel = QLabel()
        self._titel.setFont(fett)
        self._text = QLabel("Type <b>/kills</b> in chat")
        self._text.setFont(schrift)
        aufbau = QVBoxLayout(self)
        aufbau.setContentsMargins(14 * GROESSE, 10 * GROESSE, 14 * GROESSE, 10 * GROESSE)
        aufbau.addWidget(self._titel)
        aufbau.addWidget(self._text)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTO_HIDE_MS)
        self._timer.timeout.connect(self.hide)

    def _rahmen(self, farbe: str) -> None:
        self.border_color = farbe
        self.setStyleSheet(
            f"#killsReminder {{ background: palette(window); "
            f"border: {RAHMEN_PX}px solid {farbe}; border-radius: 10px; }}")
        # Ohne neues Polieren malt Qt nach einem ZWEITEN setStyleSheet
        # weiter den alten Rahmen (nativ gemessen: Stylesheet gelb, Pixel
        # rot; FALLSTRICKE #95).
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def pop(self, zone_name: str, screen: QScreen | None = None,
            late: bool = False) -> None:
        """Oben mittig, etwas unter dem oberen Rand: Unten rechts liegen im
        Spiel Skill-Leiste und Mana-Kugel, ganz oben die Lebensleiste eines
        Bosses — knapp darunter verdeckt das Fenster am wenigsten.

        ``late``: Die Map lief schon, als das Programm startete. Eine
        Ablesung jetzt zählt trotzdem richtig (die Zuordnung rechnet ein
        Tempo über die Zeit ab der Ablesung, §zone_catalog.attribute_kills),
        aber der Spieler steckt womöglich mitten im Kampf — also nur ein
        kurzer, gelber Hinweis statt der roten Aufforderung."""
        if late:
            dunkel = self.palette().color(QPalette.ColorRole.Window).lightnessF() < 0.5
            self._rahmen(SPAET_FARBE_DUNKEL if dunkel else SPAET_FARBE_HELL)
        else:
            self._rahmen(RAHMEN_FARBE)
        self._timer.setInterval(SPAET_MS if late else AUTO_HIDE_MS)
        self._titel.setText(f"⚔ {zone_name}")
        self.adjustSize()
        bildschirm = screen or QGuiApplication.primaryScreen()
        if bildschirm is not None:
            self.move(self.position_on(bildschirm.geometry()))
        self.show()
        self.raise_()
        self._timer.start()

    def position_on(self, flaeche: QRect) -> QPoint:
        return QPoint(flaeche.x() + (flaeche.width() - self.width()) // 2,
                      flaeche.y() + int(flaeche.height() * _OBEN_ANTEIL))

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        self.hide()
        super().mousePressEvent(event)
