"""/kills ablesen und mitschreiben (§kills_log), Gong und Fenster
(§kills_reminder)."""

import csv
import wave
from datetime import datetime

import pytest

from poe_view.services import kills_log
from poe_view.ui import kills_reminder

_ZEILE = ("2026/10/02 21:32:08 36346140 cffb065b [INFO Client 21176] : "
          "You have killed 131.404 monsters.")


@pytest.mark.parametrize("zeile, erwartet", [
    (_ZEILE, 131404),                                       # deutsches Windows
    (_ZEILE.replace("131.404", "131,404"), 131404),         # englisches
    (_ZEILE.replace("131.404", "1.131.404"), 1131404),
    (_ZEILE.replace("131.404", "87"), 87),
    (_ZEILE.replace("131.404 monsters", "1 monster"), 1),
])
def test_the_counter_is_read_whatever_the_thousands_separator(zeile, erwartet) -> None:
    assert kills_log.parse_kills(zeile) == erwartet


@pytest.mark.parametrize("zeile", [
    "2026/10/02 21:32:08 1 c [INFO Client 1] : You have entered The Blood Aqueduct.",
    "2026/10/02 21:32:08 1 c [INFO Client 1] : WitchOfPeter has been slain.",
    # Chat eines Mitspielers, der den Satz nur zitiert: Er endet nicht so.
    "2026/10/02 21:32:08 1 c [INFO Client 1] #PeterM: You have killed 5 monsters. lol",
])
def test_other_lines_are_no_reading(zeile) -> None:
    assert kills_log.parse_kills(zeile) is None


def test_the_log_writes_a_header_once_and_one_row_per_reading(tmp_path) -> None:
    pfad = tmp_path / "kills-log.csv"
    erste = kills_log.Reading(datetime(2026, 10, 2, 21, 32, 8), "WitchOfPeter", 131404,
                              None, None, [], "The Blood Aqueduct", 61)
    zweite = kills_log.Reading(datetime(2026, 10, 2, 21, 40, 0), "WitchOfPeter", 131950,
                               546, 472.4, ["The Blood Aqueduct", "Atoll"], "Cells", 77)
    kills_log.append(erste, pfad)
    kills_log.append(zweite, pfad)

    zeilen = list(csv.reader(pfad.open(encoding="utf-8")))
    assert zeilen[0] == list(kills_log.FIELDS)
    assert zeilen[1] == ["2026-10-02T21:32:08", "WitchOfPeter", "131404", "", "", "",
                         "The Blood Aqueduct", "61"]
    assert zeilen[2] == ["2026-10-02T21:40:00", "WitchOfPeter", "131950", "546", "472",
                         "The Blood Aqueduct | Atoll", "Cells", "77"]


def test_the_log_lives_in_the_redirected_log_folder() -> None:
    from poe_view import config
    assert kills_log.log_path().parent == config.LOG_DIR


def test_a_write_error_does_not_raise(tmp_path) -> None:
    ordner = tmp_path / "ist-ein-ordner.csv"
    ordner.mkdir()
    kills_log.append(kills_log.Reading(datetime(2026, 10, 2), "X", 1, None, None, [], "", 0),
                     ordner)


def test_the_gong_is_a_short_mono_wave(tmp_path) -> None:
    pfad = tmp_path / "gong.wav"
    kills_reminder.write_gong(pfad)
    with wave.open(str(pfad)) as datei:
        assert datei.getnchannels() == 1
        assert datei.getsampwidth() == 2
        dauer = datei.getnframes() / datei.getframerate()
        roh = datei.readframes(datei.getnframes())
    assert 0.5 < dauer < 1.5
    import struct
    werte = struct.unpack(f"<{len(roh) // 2}h", roh)
    spitze = max(abs(v) for v in werte)
    # Hörbar, aber nicht auf Anschlag — und am Ende ausgeklungen.
    assert 0.15 * 32767 < spitze < 0.5 * 32767
    assert max(abs(v) for v in werte[-500:]) < 0.1 * spitze


def test_the_gong_file_lives_in_the_redirected_data_folder() -> None:
    from poe_view import config
    assert kills_reminder.gong_path().parent == config.APP_DATA_DIR


def test_the_reminder_shows_without_taking_the_focus(qapp) -> None:
    from PySide6.QtCore import Qt
    fenster = kills_reminder.KillsReminder()
    try:
        assert fenster.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Ohne das kein Rahmen (nativ gesehen) — auf dunklem Spielbild ginge
        # das Fenster unter.
        assert fenster.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        assert fenster.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert fenster.windowFlags() & Qt.WindowType.Tool
        fenster.pop("The Blood Aqueduct")
        assert fenster.isVisible()
        assert "The Blood Aqueduct" in fenster._titel.text()
        assert fenster._timer.isActive()
    finally:
        fenster.close()


def test_a_click_closes_the_reminder(qapp) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    fenster = kills_reminder.KillsReminder()
    fenster.pop("Atoll")
    QTest.mouseClick(fenster, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(5, 5))
    assert not fenster.isVisible()
    fenster.close()


def test_the_reminder_goes_to_the_screen_of_the_game(qapp, monkeypatch) -> None:
    """Peter, 2026-10-03: "Das Fenster sehe ich nicht" — es stand auf dem
    Hauptmonitor, PoE lief auf dem links daneben."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QGuiApplication
    haupt = QGuiApplication.primaryScreen()
    monkeypatch.setattr(kills_reminder, "game_window_rect",
                        lambda: QRect(haupt.geometry().center(), haupt.geometry().center()))
    ausweich = object()   # nicht der Hauptbildschirm — sonst sähe der Test nichts
    assert kills_reminder.target_screen(ausweich) is haupt


def test_without_a_game_window_the_fallback_screen_is_used(qapp, monkeypatch) -> None:
    from PySide6.QtGui import QGuiApplication
    monkeypatch.setattr(kills_reminder, "game_window_rect", lambda: None)
    ausweich = QGuiApplication.primaryScreen()
    assert kills_reminder.target_screen(ausweich) is ausweich


def test_the_reminder_sits_top_centre_below_the_boss_bar(qapp) -> None:
    from PySide6.QtCore import QRect
    fenster = kills_reminder.KillsReminder()
    try:
        fenster.adjustSize()
        punkt = fenster.position_on(QRect(-2560, 75, 2560, 1440))
        assert punkt.x() + fenster.width() // 2 in range(-1281, -1278)
        assert 75 + 100 < punkt.y() < 75 + 300
    finally:
        fenster.close()


def test_the_reminder_is_twice_the_size_with_a_thick_red_frame(qapp) -> None:
    """Peter, 2026-10-03: "Mach den Rahmen rot und dicker und das Fenster
    doppelt so groß. Es muss ins Auge stechen." Die Schrift muss an den
    Beschriftungen selbst ankommen — mit Stylesheet am Fenster erbten sie
    ein setFont() des Fensters nicht (nativ gemessen)."""
    from PySide6.QtWidgets import QApplication
    fenster = kills_reminder.KillsReminder()
    try:
        grund = QApplication.font().pointSizeF()
        assert fenster._titel.font().pointSizeF() == 2 * grund
        assert fenster._text.font().pointSizeF() == 2 * grund
        assert fenster._titel.font().bold()
        assert "5px solid #e53935" in fenster.styleSheet()
    finally:
        fenster.close()
