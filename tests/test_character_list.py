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
    (siehe tests/test_stash_tree.py, dasselbe Muster). Anders als dort
    triggert .exec() hier bewusst ALLE Aktionen auf einmal — es gibt in
    dieser Liste nie zwei Aktionen, die sich gegenseitig widersprechen
    könnten (Refresh und Export schließen sich nicht aus)."""

    def __init__(self, *args, **kwargs) -> None:
        self._actions: list[QAction] = []

    def addAction(self, text: str) -> QAction:
        action = QAction(text)
        self._actions.append(action)
        return action

    def addSeparator(self) -> None:
        pass

    def texts(self) -> list[str]:
        return [a.text() for a in self._actions]

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


def test_context_menu_offers_export_visible_items_on_a_character(qapp, monkeypatch) -> None:
    """Peter, 2026-08-03: "Sollen wir das in der Character-Liste auch in
    den Rechtsklick mit aufnehmen?" — steht neben "Refresh" zusätzlich
    zur Verfügung, exakt wie im Stash-Baum."""
    widget = CharacterList()
    widget.set_characters([make_char("Solo", 91)])
    pos = widget.visualItemRect(widget.item(0)).center()

    monkeypatch.setattr(character_list_module, "QMenu", _FakeMenu)
    received = []
    widget.export_visible_requested.connect(lambda: received.append(True))

    widget._on_context_menu(pos)

    assert received == [True]


def test_context_menu_offers_export_visible_items_without_a_character(qapp, monkeypatch) -> None:
    """Der leere Bereich bot bisher gar kein Menü — jetzt genau wie beim
    Stash-Baum: "Export visible items" bezieht sich auf die Item-Tabelle,
    nicht auf eine bestimmte Zeile in dieser Liste, und ist deshalb auch
    ohne Charakter unter dem Cursor sinnvoll."""
    widget = CharacterList()
    widget.set_characters([make_char("Solo", 91)])

    monkeypatch.setattr(character_list_module, "QMenu", _FakeMenu)
    refresh_received = []
    export_received = []
    widget.character_refresh_requested.connect(refresh_received.append)
    widget.export_visible_requested.connect(lambda: export_received.append(True))

    from PySide6.QtCore import QPoint
    widget._on_context_menu(QPoint(-1, -1))

    assert export_received == [True]
    assert refresh_received == []  # kein Charakter unter dem Cursor


def test_auswahl_ueberlebt_den_neuaufbau(qapp) -> None:
    """Seit die Liste bei jedem Levelaufstieg neu gezeichnet wird
    (§MainWindow._apply_level_to_character_list), darf der Neuaufbau die
    Auswahl nicht wegwerfen — sonst wäre der beobachtete Charakter
    mitten im Spielen plötzlich abgewählt."""
    widget = CharacterList()
    widget.set_characters([make_char("Beobachtet", 13), make_char("Andere", 40)])
    widget.setCurrentItem(widget.item(1))  # nach Level sortiert steht "Andere" oben
    assert widget.currentItem().text() == "Beobachtet (Witch 13)"

    widget.set_characters([make_char("Beobachtet", 24), make_char("Andere", 40)])

    assert widget.currentItem() is not None
    assert widget.currentItem().text() == "Beobachtet (Witch 24)"


def test_auswahl_wandert_mit_wenn_der_levelaufstieg_umsortiert(qapp) -> None:
    """Gemerkt wird der NAME, nicht die Zeilennummer: Ein Levelaufstieg
    kann den Charakter in der nach Level sortierten Liste nach oben
    schieben — an der alten Zeilennummer säße dann ein anderer."""
    widget = CharacterList()
    widget.set_characters([make_char("Steiger", 13), make_char("Andere", 40)])
    widget.setCurrentItem(widget.item(1))  # "Steiger" steht unten
    assert widget.currentItem().text() == "Steiger (Witch 13)"

    widget.set_characters([make_char("Steiger", 55), make_char("Andere", 40)])

    assert widget.currentRow() == 0  # jetzt oben
    assert widget.currentItem().text() == "Steiger (Witch 55)"


def test_neuaufbau_loest_keinen_abruf_aus(qapp) -> None:
    """Die wiederhergestellte Auswahl darf kein ``character_selected``
    nach sich ziehen — sonst feuerte jeder Levelaufstieg einen Abruf."""
    widget = CharacterList()
    widget.set_characters([make_char("Beobachtet", 13)])
    widget.setCurrentItem(widget.item(0))

    received = []
    widget.character_selected.connect(received.append)
    widget.set_characters([make_char("Beobachtet", 14)])

    assert received == []
