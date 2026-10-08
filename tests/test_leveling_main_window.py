"""Leveling-Plan im Hauptfenster (§4.60.14): Levelaufstieg aus der
Client.txt → Statusleiste, Mini-Fenster, offenes Baum-Fenster."""

from __future__ import annotations

import pytest

from poe_view.api.models import Character
from poe_view.services import passive_tree as pt
from poe_view.services import tree_history as th
from poe_view.ui.main_window import MainWindow
from tests.test_passive_tree import _ROH


@pytest.fixture
def fenster(qapp, monkeypatch):
    """Hauptfenster mit "WitchOfPeter" (Juggernaut, Level 30, Baum 10, 11,
    12) und einem Plan "Build" aus zwei Abschnitten."""
    baum = pt.parse_tree(_ROH, ruthless=True)
    monkeypatch.setattr("poe_view.services.passive_tree.load", lambda ruthless: baum)
    win = MainWindow()
    win._all_characters = [Character.model_validate(
        {"name": "WitchOfPeter", "class": "Juggernaut", "level": 30, "league": "Standard"}),
        Character.model_validate(
        {"name": "PeterM", "class": "Juggernaut", "level": 50, "league": "Standard"})]
    baeume: dict = {}
    th.record(baeume, "WitchOfPeter", {"hashes": [10, 11, 12]}, level=30, ruthless=True)
    th.save_config(baeume, "WitchOfPeter", "S1", {"hashes": [10, 11, 12, 20, 21]}, level=30,
                   ruthless=True, source="pob")
    th.save_config(baeume, "WitchOfPeter", "S2", {"hashes": [10, 11, 12, 13, 14, 15]},
                   level=30, ruthless=True, source="pob")
    th.set_leveling(baeume, "WitchOfPeter", ["S1", "S2"], title="Build")
    monkeypatch.setattr(win, "_trees", lambda: baeume)
    monkeypatch.setattr(win, "_save_trees", lambda: None)
    yield win, baeume
    # Gründlich abräumen: Ein übrig gebliebenes (offscreen weiter
    # "aktives") Fenster schluckte sonst die Tastenkürzel späterer Tests.
    from PySide6.QtWidgets import QApplication
    for w in (getattr(win, "_tree_dialog", None), win._leveling_window, win):
        if w is not None:
            w.close()
            w.deleteLater()
    QApplication.processEvents()


def test_a_level_up_names_the_next_passive(fenster) -> None:
    """Peter: "zeigt dann den zu vergebenden Skill-Punkt" — Statusleiste
    (fest) und Meldung beim Aufstieg."""
    win, _ = fenster
    win._on_level_up("WitchOfPeter", 31)
    assert win._plan_status.isVisibleTo(win)
    assert win._plan_status.text() == "Next passive: Life (towards Basic Jewel Socket)"
    assert win._status_msg.text() == ("WitchOfPeter reached level 31 — next passive: "
                                      "Life (towards Basic Jewel Socket)")
    # Noch ein Aufstieg ohne neuen Abruf: der vorige Punkt gilt als vergeben.
    win._on_level_up("WitchOfPeter", 32)
    assert win._plan_status.text() == "Next passive: Basic Jewel Socket"
    # Der Abruf bringt den echten Baum (mit 20) und Level 32: dasselbe Ergebnis.
    win._on_character_tree("WitchOfPeter", {"hashes": [10, 11, 12, 20]}, True)
    win._note_api_level("WitchOfPeter", 32)
    assert win._plan_status.text() == "Next passive: Basic Jewel Socket"


def test_characters_without_a_plan_change_nothing(fenster) -> None:
    win, _ = fenster
    win._on_status("before")
    win._on_level_up("PeterM", 51)
    assert not win._plan_status.isVisibleTo(win) and win._status_msg.text() == "before"
    assert win._live_levels["PeterM"] == 51


def test_the_mini_window_shows_the_next_points(fenster) -> None:
    win, baeume = fenster
    win._show_leveling_window("WitchOfPeter")
    w = win._leveling_window
    assert w.isVisible() and w.character == "WitchOfPeter"
    assert "stage 1/2: S1" in w.head.text() and "level 30" in w.head.text()
    zeilen = w.body.text().split("<br>")
    assert zeilen[0] == "<b>▶ Life (towards Basic Jewel Socket)</b>"
    assert zeilen[1] == "2. Basic Jewel Socket"
    win._on_level_up("WitchOfPeter", 32)
    assert w.body.text().split("<br>")[0] == "<b>▶ Basic Jewel Socket</b>"
    # Plan gestoppt: das Fenster sagt es, die Statusleiste schweigt.
    th.clear_leveling(baeume, "WitchOfPeter")
    win._update_leveling("WitchOfPeter")
    assert w.head.text() == "WitchOfPeter: no leveling plan"
    assert not win._plan_status.isVisibleTo(win)


def test_an_open_tree_window_gets_the_levels(fenster) -> None:
    win, _ = fenster
    win._on_character_tree_requested(win._all_characters[0])
    dialog = win._tree_dialog
    win._on_level_up("WitchOfPeter", 33)
    assert dialog._levels == (30, 33)
    assert not dialog.mini_button.isHidden()
    dialog.mini_button.click()
    assert win._leveling_window is not None and win._leveling_window.isVisible()
    dialog.close()


def test_an_api_update_resets_the_count(fenster) -> None:
    """Der Abruf bringt Level 32 und den Baum ohne den Punkt: nicht
    vergeben — wieder "Life" statt des vermuteten "Basic Jewel Socket"."""
    win, _ = fenster
    win._on_level_up("WitchOfPeter", 32)
    assert win._plan_status.text() == "Next passive: Basic Jewel Socket"
    win._on_character_snapshot("WitchOfPeter", 32, 1_000_000)
    assert win._api_levels["WitchOfPeter"] == 32
    assert win._plan_status.text() == "Next passive: Life (towards Basic Jewel Socket)"


def test_a_new_tree_from_the_api_moves_the_plan_on(fenster) -> None:
    win, _ = fenster
    win._on_level_up("WitchOfPeter", 32)                          # 1 vermutet vergeben
    win._on_character_tree("WitchOfPeter", {"hashes": [10, 11, 12, 20, 21]}, True)
    # S1 fertig → S2: 13, 14, 15; einer vermutet → jetzt 14.
    assert win._plan_status.text() == "Next passive: Life (towards Far Away)"


def test_a_character_without_a_plan_does_not_take_over(fenster) -> None:
    win, _ = fenster
    win._on_level_up("WitchOfPeter", 31)
    win._on_level_up("PeterM", 51)
    assert win._leveling_char == "WitchOfPeter" and win._plan_status.isVisibleTo(win)
    assert win._plan_status.text() == "Next passive: Life (towards Basic Jewel Socket)"
