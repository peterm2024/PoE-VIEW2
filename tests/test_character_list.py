"""Tests für die flache Charakterliste (kein Tree mehr, siehe Nutzer-Feedback)."""

from poe_view.api.models import Character
from poe_view.ui.character_list import CharacterList


def make_char(name: str, level: int) -> Character:
    return Character.model_validate({"name": name, "class": "Witch", "level": level,
                                      "league": "Settlers"})


def test_set_characters_is_flat_and_sorted_by_level_desc(qapp) -> None:
    widget = CharacterList()
    widget.set_characters([make_char("Low", 12), make_char("High", 91), make_char("Mid", 50)])
    assert widget.count() == 3
    assert [widget.item(i).text() for i in range(3)] == [
        "High (Witch 91)", "Mid (Witch 50)", "Low (Witch 12)"]


def test_click_emits_character_selected(qapp) -> None:
    widget = CharacterList()
    char = make_char("Solo", 91)
    widget.set_characters([char])

    received = []
    widget.character_selected.connect(received.append)
    widget.itemClicked.emit(widget.item(0))
    assert received == [char]
