"""Tests für die flache Charakterliste."""

from PySide6.QtGui import QAction

from poe_view.api.models import Character
from poe_view.ui import character_list as character_list_module
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


class _FakeMenu:
    """Ersatz für QMenu — .exec() öffnet sonst einen modalen Event-Loop, der in
    einer Offscreen-Testumgebung ewig auf einen nie kommenden Klick wartet
    (siehe tests/test_stash_tree.py, dasselbe Muster)."""

    def __init__(self, *args, **kwargs) -> None:
        self._actions: list[QAction] = []

    def addAction(self, text: str) -> QAction:
        action = QAction(text)
        self._actions.append(action)
        return action

    def exec(self, *args, **kwargs) -> None:
        for action in self._actions:
            action.trigger()


def test_context_menu_emits_character_refresh_requested(qapp, monkeypatch) -> None:
    widget = CharacterList()
    char = make_char("Solo", 91)
    widget.set_characters([char])
    pos = widget.visualItemRect(widget.item(0)).center()

    monkeypatch.setattr(character_list_module, "QMenu", _FakeMenu)
    received = []
    widget.character_refresh_requested.connect(received.append)

    widget._on_context_menu(pos)

    assert received == [char]


def test_context_menu_does_nothing_without_an_item_under_cursor(qapp, monkeypatch) -> None:
    widget = CharacterList()
    widget.set_characters([make_char("Solo", 91)])

    def _exploding_menu(*args, **kwargs):
        raise AssertionError("QMenu darf ohne Item unter dem Cursor nie erzeugt werden")
    monkeypatch.setattr(character_list_module, "QMenu", _exploding_menu)

    from PySide6.QtCore import QPoint
    widget._on_context_menu(QPoint(-1, -1))  # darf nicht auf _exploding_menu treffen
