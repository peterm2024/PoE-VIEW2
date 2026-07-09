"""Tests für den Navigationsbaum: flache, liga-gefilterte Charakterliste
(die Liga-Filterung selbst passiert in MainWindow, siehe test_main_window_helpers.py)
und den rekursiven Stash-Baum.
"""

from poe_view.api.models import Character, StashTab
from poe_view.ui.stash_tree import StashTree


def make_char(name: str, level: int) -> Character:
    return Character.model_validate({"name": name, "class": "Witch", "level": level,
                                      "league": "Settlers"})


def test_set_characters_is_flat_and_sorted_by_level_desc(qapp) -> None:
    tree = StashTree()
    tree.set_characters([make_char("Low", 12), make_char("High", 91), make_char("Mid", 50)])
    root = tree._char_root
    assert root.childCount() == 3
    assert [root.child(i).text(0) for i in range(3)] == [
        "High (Witch 91)", "Mid (Witch 50)", "Low (Witch 12)"]


def test_set_characters_no_league_subnodes(qapp) -> None:
    """Kein Zwischenknoten mehr — der Charakter hängt direkt unter 'Charaktere'."""
    tree = StashTree()
    tree.set_characters([make_char("Solo", 91)])
    root = tree._char_root
    assert root.childCount() == 1
    char_node = root.child(0)
    assert char_node.text(0) == "Solo (Witch 91)"
    assert char_node.childCount() == 0  # Blatt, kein Liga-Gruppenknoten


def test_set_stashes_builds_recursive_tree(qapp) -> None:
    data = [
        {"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}},
        {"id": "folder1", "name": "Folder", "type": "Folder", "metadata": {"folder": True},
         "children": [{"id": "child1", "name": "Sub", "type": "CurrencyStash", "metadata": {}}]},
    ]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    root = tree._stash_root
    assert root.childCount() == 2
    folder_node = root.child(1)
    assert folder_node.childCount() == 1
    assert folder_node.child(0).text(0) == "Sub"
