"""Tests für den Stash-Baum: keine Wurzelknoten mehr, Tabs sind Top-Level-Items.

Die Charakterliste lebt separat, siehe test_character_list.py.
"""

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt

from poe_view.api.models import StashTab
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
