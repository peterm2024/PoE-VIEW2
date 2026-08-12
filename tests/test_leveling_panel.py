"""Tests fuer das Leveling-Panel rechts neben dem Item-Detail (Peter,
2026-08-12: "Ich haette den rechten (freien) Bereich hier gerne fuer
unsere Leveling-Infos (XP/h-Graph) benutzt") — ARCHITEKTUR.md §4.39."""

from poe_view.api.models import Item
from poe_view.ui.leveling_panel import LevelingPanel
from poe_view.ui.main_window import MainWindow


def test_the_panel_shows_level_experience_and_rate(qapp) -> None:
    panel = LevelingPanel()
    panel.show_character("WitchOfPeter", level=90, experience=1935625585,
                         rate_text="119.2M XP/h", age_note=" (3m ago)")

    assert "WitchOfPeter" in panel._title.text()
    body = panel._body.text()
    assert "Level 90" in body
    assert "119.2M XP/h" in body
    assert "(3m ago)" in body


def test_a_missing_rate_says_why_instead_of_staying_blank(qapp) -> None:
    """GGG veroeffentlicht Erfahrung erst beim Verlassen einer Zone. Ein
    leeres Feld saehe nach einem Fehler aus, obwohl alles in Ordnung
    ist — genau diese Verwechslung hat beim Bau der Rate schon einmal
    Zeit gekostet."""
    panel = LevelingPanel()
    panel.show_character("WitchOfPeter", level=90, experience=1, rate_text=None,
                         age_note="")

    assert "zone change" in panel._body.text()


def test_switching_to_a_stash_tab_clears_the_leveling_panel(qapp, monkeypatch) -> None:
    """Die Anzeige gehoert zu EINEM Charakter. Bliebe sie neben einem
    Truhenfach stehen, behauptete sie einen Zusammenhang, den es nicht
    gibt."""
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "ring-1", "typeLine": "Amethyst Ring",
                             "inventoryId": "Ring"})], False)
    assert "WitchOfPeter" in win.leveling._title.text()

    win._show_items("tab-1", [], "Currency")

    assert win.leveling._title.text() == "Leveling"
    assert "No character selected" in win.leveling._body.text()

    win.worker.stop()
    win.worker.wait(5000)
