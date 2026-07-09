"""Tests für den Stash-Baum: keine Wurzelknoten mehr, Tabs sind Top-Level-Items.

Die Charakterliste lebt separat, siehe test_character_list.py.
"""

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from poe_view.api.models import StashTab
from poe_view.ui import stash_tree as stash_tree_module
from poe_view.ui.stash_tree import StashTree, format_age


def test_set_stashes_builds_recursive_tree_without_wrapper_root(qapp) -> None:
    data = [
        {"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}},
        {"id": "folder1", "name": "Folder", "type": "Folder", "metadata": {"folder": True},
         "children": [{"id": "child1", "name": "Sub", "type": "CurrencyStash", "metadata": {}}]},
    ]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    assert tree.topLevelItemCount() == 2  # Tabs SIND die Top-Level-Items, kein Wrapper
    folder_node = tree.topLevelItem(1)
    assert folder_node.childCount() == 1
    assert folder_node.child(0).text(0) == "Sub"


def test_set_stashes_marks_unloaded_tabs_with_download_marker_only(qapp) -> None:
    """Unloaded Tab: nur der ⬇-Text, KEIN Refresh-Button (Nutzer-Feedback: nur eine Spalte)."""
    data = [{"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    node = tree._stash_nodes["root1"]
    assert node.text(1) == "⬇"
    assert tree.itemWidget(node, 1) is None


def test_set_stashes_shows_refresh_button_with_age_for_loaded_tabs(qapp) -> None:
    data = [{"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    tree.set_stashes(stashes, last_loaded={"root1": three_days_ago})
    node = tree._stash_nodes["root1"]
    assert node.text(1) == ""
    button = tree.itemWidget(node, 1)
    assert button is not None
    assert button.text() == "⟳ vor 3d"


def test_mark_loaded_replaces_download_marker_with_refresh_button(qapp) -> None:
    data = [{"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    assert tree._stash_nodes["root1"].text(1) == "⬇"

    tree.mark_loaded("root1", datetime.now(timezone.utc).isoformat())

    node = tree._stash_nodes["root1"]
    assert node.text(1) == ""
    assert tree.itemWidget(node, 1).text() == "⟳ heute"


def test_refresh_button_click_emits_signal(qapp) -> None:
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes, last_loaded={"root1": datetime.now(timezone.utc).isoformat()})
    node = tree._stash_nodes["root1"]
    button = tree.itemWidget(node, 1)

    received = []
    tree.stash_refresh_requested.connect(lambda sid, name: received.append((sid, name)))
    button.click()
    assert received == [("root1", "Currency 1")]


def test_format_age() -> None:
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    assert format_age(now.isoformat(), now=now) == "heute"
    assert format_age((now - timedelta(hours=5)).isoformat(), now=now) == "heute"
    assert format_age((now - timedelta(days=1)).isoformat(), now=now) == "vor 1d"
    assert format_age((now - timedelta(days=12)).isoformat(), now=now) == "vor 12d"


def test_header_is_visible(qapp) -> None:
    """Kopfzeile sichtbar — sonst keine manuelle Spaltenbreite (Nutzer-Feedback)."""
    tree = StashTree()
    assert not tree.isHeaderHidden()
    assert tree.headerItem().text(0) == "Name"


def test_name_column_is_interactive_not_stretch(qapp) -> None:
    """Stretch-Spalten lassen sich in Qt nicht per Maus verbreitern (Nutzer-Feedback)."""
    from PySide6.QtWidgets import QHeaderView
    tree = StashTree()
    assert tree.header().sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive


class _FakeMenu:
    """Ersatz für QMenu in Tests: QMenu.exec() öffnet einen modalen Event-Loop,
    der in einer Offscreen-Testumgebung ewig auf einen (nie kommenden) Klick
    wartet. Statt (unzuverlässig) QMenu.exec zu monkeypatchen, ersetzen wir
    den kompletten Namen ``QMenu`` im Modul unter Test — echte QAction-Objekte
    darunter, damit .triggered/.trigger() sich exakt wie im echten Code verhalten."""

    def __init__(self, *args, **kwargs) -> None:
        self._actions: list[QAction] = []

    def addAction(self, text: str) -> QAction:
        action = QAction(text)
        self._actions.append(action)
        return action

    def exec(self, *args, **kwargs) -> None:
        for action in self._actions:
            action.trigger()


def test_context_menu_emits_raw_data_requested_for_leaf(qapp, monkeypatch) -> None:
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    node = tree._stash_nodes["root1"]
    pos = tree.visualItemRect(node).center()

    monkeypatch.setattr(stash_tree_module, "QMenu", _FakeMenu)
    received = []
    tree.raw_data_requested.connect(lambda sid, name: received.append((sid, name)))

    tree._on_context_menu(pos)

    assert received == [("root1", "Currency 1")]


def test_context_menu_does_nothing_for_folder_node(qapp, monkeypatch) -> None:
    """Ordner haben keine eigenen Rohdaten — kein Menü, kein Signal."""
    data = [{"id": "folder1", "name": "Folder", "type": "Folder", "metadata": {"folder": True},
             "children": []}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    pos = tree.visualItemRect(tree.topLevelItem(0)).center()

    def _exploding_menu(*args, **kwargs):
        raise AssertionError("QMenu darf für Ordner-Knoten nie erzeugt werden")
    monkeypatch.setattr(stash_tree_module, "QMenu", _exploding_menu)

    tree._on_context_menu(pos)  # darf NICHT auf _exploding_menu treffen


def test_set_children_inserts_subtabs_without_rebuilding_tree(qapp) -> None:
    """Spezial-Tab (MapStash): entdeckte Kinder unter dem Knoten einhängen —
    Aufklapp-Zustand des restlichen Baums bleibt erhalten."""
    data = [
        {"id": "m1", "name": "Maps", "type": "MapStash", "metadata": {}},
        {"id": "other", "name": "Other", "type": "QuadStash", "metadata": {}},
    ]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])

    child = StashTab.model_validate({"id": "c1", "parent": "m1", "type": "MapStash",
                                     "metadata": {"map": {"name": "Beach Map", "tier": 16}}})
    tree.set_children("m1", [child])

    parent_node = tree._stash_nodes["m1"]
    assert parent_node.childCount() == 1
    assert parent_node.child(0).text(0) == "Beach Map (T16)"  # display_name, kein leerer Name
    assert parent_node.isExpanded()
    assert tree._stash_nodes["c1"].text(1) == "⬇"  # Kind noch nicht geladen
    assert tree.topLevelItemCount() == 2  # Rest des Baums unangetastet


def test_set_children_replaces_previous_children_and_index_entries(qapp) -> None:
    data = [{"id": "m1", "name": "Maps", "type": "MapStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])

    old_child = StashTab.model_validate({"id": "old", "parent": "m1", "name": "Old",
                                         "type": "MapStash", "metadata": {}})
    new_child = StashTab.model_validate({"id": "new", "parent": "m1", "name": "New",
                                         "type": "MapStash", "metadata": {}})
    tree.set_children("m1", [old_child])
    tree.set_children("m1", [new_child])

    assert "old" not in tree._stash_nodes  # kein toter Eintrag im Index
    assert tree._stash_nodes["m1"].childCount() == 1
    assert tree._stash_nodes["new"].text(0) == "New"


def test_tab_colour_is_icon_not_text_colour(qapp) -> None:
    """Farbe als Icon-Swatch statt Textfarbe — dunkle API-Farben bleiben lesbar."""
    data = [{"id": "root1", "name": "Dark Tab", "type": "QuadStash",
             "metadata": {"colour": "000000"}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    node = tree._stash_nodes["root1"]
    # NoBrush == nie per setForeground() überschrieben, Text bleibt Theme-Farbe
    assert node.foreground(0).style() == Qt.BrushStyle.NoBrush
    assert not node.icon(0).isNull()
