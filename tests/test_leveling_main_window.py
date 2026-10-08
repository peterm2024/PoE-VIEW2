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
    """Hauptfenster mit "WitchOfPeter" (Juggernaut, Level 3) und dem Ziel
    "Build" = 10, 11, 12, 14, 15, 20, 21 — Reihenfolge vom Start: 10, 11,
    12 (Iron Heart), 14, 15 (Far Away), 20, 21."""
    baum = pt.parse_tree(_ROH, ruthless=True)
    monkeypatch.setattr("poe_view.services.passive_tree.load", lambda ruthless: baum)
    win = MainWindow()
    win._all_characters = [Character.model_validate(
        {"name": "WitchOfPeter", "class": "Juggernaut", "level": 3, "league": "Standard"}),
        Character.model_validate(
        {"name": "PeterM", "class": "Juggernaut", "level": 50, "league": "Standard"})]
    baeume: dict = {}
    th.record(baeume, "WitchOfPeter", {"hashes": [10]}, level=3, ruthless=True)
    th.save_config(baeume, "WitchOfPeter", "Build", {"hashes": [10, 11, 12, 14, 15, 20, 21]},
                   level=3, ruthless=True, source="pob")
    th.set_leveling(baeume, "WitchOfPeter", "Build")
    gespeichert = []
    monkeypatch.setattr(win, "_trees", lambda: baeume)
    monkeypatch.setattr(win, "_save_trees", lambda: gespeichert.append(1))
    yield win, baeume, gespeichert
    # Gründlich abräumen: Ein übrig gebliebenes (offscreen weiter
    # "aktives") Fenster schluckte sonst die Tastenkürzel späterer Tests.
    from PySide6.QtWidgets import QApplication
    for w in (getattr(win, "_tree_dialog", None), win._leveling_window, win):
        if w is not None:
            w.close()
            w.deleteLater()
    QApplication.processEvents()


def test_a_level_up_names_the_next_passive(fenster) -> None:
    """Peter: "Mit jedem Level kommt … ein Skillpunkt dazu" — Level 4 = 3
    Punkte: Iron Heart. Statusleiste (fest) und Meldung beim Aufstieg."""
    win, _, _ = fenster
    win._on_level_up("WitchOfPeter", 4)
    assert win._plan_status.isVisibleTo(win)
    assert win._plan_status.text() == "Leveling: Point 3/7: Iron Heart"
    assert win._status_msg.text() == "WitchOfPeter reached level 4 — Point 3/7: Iron Heart"
    # Der echte Baum ändert nichts: Es zählen nur die Punkte.
    win._on_character_tree("WitchOfPeter", {"hashes": [10, 20]}, True)
    assert win._plan_status.text() == "Leveling: Point 3/7: Iron Heart"
    # Ein Abruf mit niedrigerem Level (älter als das Log) auch nicht.
    win._on_character_snapshot("WitchOfPeter", 3, 1_000)
    assert win._plan_status.text() == "Leveling: Point 3/7: Iron Heart"
    win._on_character_snapshot("WitchOfPeter", 5, 2_000)
    assert win._plan_status.text() == "Leveling: Point 4/7: Life (towards Far Away)"


def test_characters_without_a_plan_change_nothing(fenster) -> None:
    win, _, _ = fenster
    win._on_status("before")
    win._on_level_up("PeterM", 51)
    assert not win._plan_status.isVisibleTo(win) and win._status_msg.text() == "before"
    assert win._live_levels["PeterM"] == 51


def test_the_mini_window_shows_the_next_points_and_counts_quests(fenster) -> None:
    win, baeume, gespeichert = fenster
    win._show_leveling_window("WitchOfPeter")
    w = win._leveling_window
    assert w.isVisible() and w.character == "WitchOfPeter"
    assert "level 3 = 2 points" in w.head.text() and "towards “Build”" in w.head.text()
    zeilen = w.body.text().split("<br>")
    assert zeilen[0] == "<b>▶ 2. Strength (towards Iron Heart)</b>"
    assert zeilen[1] == "3. Iron Heart"
    # Quest-Punkt von Hand: gespeichert, alles rückt weiter.
    assert not w.quest_minus.isEnabled()
    w.quest_plus.click()
    assert th.quest_points(baeume, "WitchOfPeter") == 1 and gespeichert == [1]
    assert w.body.text().split("<br>")[0] == "<b>▶ 3. Iron Heart</b>"
    assert "level 3 + 1 quest = 3 points" in w.head.text()
    assert win._plan_status.text() == "Leveling: Point 3/7: Iron Heart"
    w.quest_minus.click()
    assert th.quest_points(baeume, "WitchOfPeter") == 0
    win._change_quest("WitchOfPeter", -1)                         # nie unter null
    th.set_quest_points(baeume, "WitchOfPeter", 24)
    win._change_quest("WitchOfPeter", 1)                          # nie über alle 24
    assert th.quest_points(baeume, "WitchOfPeter") == 24 and gespeichert == [1, 1]
    th.set_quest_points(baeume, "WitchOfPeter", 0)
    win._on_level_up("WitchOfPeter", 4)
    assert w.body.text().split("<br>")[0] == "<b>▶ 3. Iron Heart</b>"
    # Plan gestoppt: das Fenster sagt es, die Statusleiste schweigt.
    th.clear_leveling(baeume, "WitchOfPeter")
    win._update_leveling("WitchOfPeter")
    assert w.head.text() == "WitchOfPeter: no leveling plan"
    assert not win._plan_status.isVisibleTo(win) and not w.quest_plus.isEnabled()


def test_an_open_tree_window_follows_level_and_quests(fenster) -> None:
    win, baeume, _ = fenster
    win._on_character_tree_requested(win._all_characters[0])
    dialog = win._tree_dialog
    assert dialog._level == 3
    win._on_level_up("WitchOfPeter", 5)
    assert dialog._level == 5 and dialog.graph.marker_now == 14
    win._change_quest("WitchOfPeter", 1)                          # aus dem Mini-Fenster
    assert dialog.graph.marker_now == 15
    dialog.quest_plus.click()                                     # aus dem Baum-Fenster
    assert th.quest_points(baeume, "WitchOfPeter") == 2
    assert win._plan_status.text() == "Leveling: Point 6/7: Life (towards Basic Jewel Socket)"
    assert not dialog.mini_button.isHidden()
    dialog.mini_button.click()
    assert win._leveling_window is not None and win._leveling_window.isVisible()
    dialog.close()


def test_a_character_without_a_plan_does_not_take_over(fenster) -> None:
    win, _, _ = fenster
    win._on_level_up("WitchOfPeter", 4)
    win._on_level_up("PeterM", 51)
    assert win._leveling_char == "WitchOfPeter" and win._plan_status.isVisibleTo(win)
    assert win._plan_status.text() == "Leveling: Point 3/7: Iron Heart"
