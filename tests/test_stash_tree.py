"""Tests für den Stash-Baum: keine Wurzelknoten mehr, Tabs sind Top-Level-Items.

Die Charakterliste lebt separat, siehe test_character_list.py.
"""

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QPalette

from poe_view.api.models import StashTab
from poe_view.ui import stash_tree as stash_tree_module
from poe_view.ui.stash_tree import StashTree, format_age

# Spaltenindizes wie in stash_tree.py: Name, # (Item-Anzahl), Status, Pos.
_COL_NAME, _COL_COUNT, _COL_STATUS, _COL_POSITION = 0, 1, 2, 3


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
    assert folder_node.child(0).text(_COL_NAME) == "Sub"


def test_set_stashes_marks_unloaded_tabs_with_download_marker_only(qapp) -> None:
    """Unloaded Tab: nur der ⬇-Text, kein Refresh-Button (nur eine Spalte)."""
    data = [{"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    node = tree._stash_nodes["root1"]
    assert node.text(_COL_STATUS) == "⬇"
    assert tree.itemWidget(node, _COL_STATUS) is None


def test_set_stashes_shows_refresh_button_with_age_for_loaded_tabs(qapp) -> None:
    data = [{"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    tree.set_stashes(stashes, last_loaded={"root1": three_days_ago})
    node = tree._stash_nodes["root1"]
    assert node.text(_COL_STATUS) == ""
    button = tree.itemWidget(node, _COL_STATUS)
    assert button is not None
    assert button.text() == "⟳ 3d ago"


def test_mark_loaded_replaces_download_marker_with_refresh_button(qapp) -> None:
    data = [{"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    assert tree._stash_nodes["root1"].text(_COL_STATUS) == "⬇"

    now = datetime.now(timezone.utc)
    tree.mark_loaded("root1", now.isoformat())

    node = tree._stash_nodes["root1"]
    assert node.text(_COL_STATUS) == ""
    # Exakte Uhrzeit statt "heute" (sonst unsichtbar, ob der
    # Auto-Refresh innerhalb desselben Tages tatsächlich gegriffen hat).
    assert tree.itemWidget(node, _COL_STATUS).text() == f"⟳ {now.astimezone().strftime('%H:%M:%S')}"


def test_mark_loaded_updates_item_count_column(qapp) -> None:
    """Item-Anzahl in eigene Spalte statt "(N Items)" im Namen."""
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    assert tree._stash_nodes["root1"].text(_COL_COUNT) == ""  # unbekannt vor dem Laden

    tree.mark_loaded("root1", datetime.now(timezone.utc).isoformat(), count=45)

    assert tree._stash_nodes["root1"].text(_COL_COUNT) == "45"
    assert tree._stash_nodes["root1"].text(_COL_NAME) == "Currency 1"  # kein Suffix im Namen


def test_refresh_button_click_emits_signal(qapp) -> None:
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes, last_loaded={"root1": datetime.now(timezone.utc).isoformat()})
    node = tree._stash_nodes["root1"]
    button = tree.itemWidget(node, _COL_STATUS)

    received = []
    tree.stash_refresh_requested.connect(lambda sid, name: received.append((sid, name)))
    button.click()
    assert received == [("root1", "Currency 1")]


def test_format_age() -> None:
    """Regression: "heute" allein verschleierte, ob ein
    Fach innerhalb desselben Tages tatsächlich neu geladen wurde — jetzt
    die exakte (lokale) Uhrzeit statt eines pauschalen "heute"."""
    now = datetime(2026, 7, 9, 15, 30, 0, tzinfo=timezone.utc)
    five_hours_ago = now - timedelta(hours=5)
    assert format_age(now.isoformat(), now=now) == now.astimezone().strftime("%H:%M:%S")
    assert format_age(five_hours_ago.isoformat(), now=now) == five_hours_ago.astimezone().strftime("%H:%M:%S")
    assert format_age((now - timedelta(days=1)).isoformat(), now=now) == "1d ago"
    assert format_age((now - timedelta(days=12)).isoformat(), now=now) == "12d ago"


def test_header_is_visible(qapp) -> None:
    """Kopfzeile sichtbar — sonst keine manuelle Spaltenbreite."""
    tree = StashTree()
    assert not tree.isHeaderHidden()
    assert tree.headerItem().text(_COL_NAME) == "Name"
    assert tree.headerItem().text(_COL_COUNT) == "#"
    assert tree.headerItem().text(_COL_POSITION) == "Pos."


def test_name_column_stretches_count_and_status_stay_fixed(qapp) -> None:
    """Name füllt automatisch die verbleibende Breite (391-Tab-Cache mit
    langen Namen machte manuelles Nachziehen unpraktikabel) — #, Status und
    Pos. bleiben dabei fest und damit immer sichtbar."""
    from PySide6.QtWidgets import QHeaderView
    tree = StashTree()
    header = tree.header()
    assert header.sectionResizeMode(_COL_NAME) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(_COL_COUNT) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(_COL_STATUS) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(_COL_POSITION) == QHeaderView.ResizeMode.Fixed


# --- Positions-Spalte (echte Truhen-Reihenfolge) ---------- #

def test_set_stashes_fills_position_column_for_real_tabs_only(qapp) -> None:
    """Peter fehlte ein Zeilenheader zum Durchzählen der echten Fächer —
    Qt kennt das nur bei Tabellen, hier die Positions-Spalte als
    Äquivalent. Nur echte Fächer bekommen eine Zahl, Ordner bleiben leer."""
    data = [
        {"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}},
        {"id": "folder1", "name": "Folder", "type": "Folder", "metadata": {"folder": True},
         "children": [{"id": "child1", "name": "Sub", "type": "CurrencyStash", "metadata": {}}]},
    ]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes, positions={"root1": 1, "child1": 2})

    assert tree._stash_nodes["root1"].text(_COL_POSITION) == "1"
    assert tree._stash_nodes["child1"].text(_COL_POSITION) == "2"
    folder_node = tree.topLevelItem(1)
    assert folder_node.text(_COL_POSITION) == ""  # Ordner hat keinen eigenen Truhenplatz


def test_set_stashes_without_positions_leaves_column_blank(qapp) -> None:
    """Kein Absturz, wenn (noch) keine Positionsdaten vorliegen."""
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])

    assert tree._stash_nodes["root1"].text(_COL_POSITION) == ""


def test_set_children_fills_position_for_newly_discovered_children(qapp) -> None:
    data = [{"id": "m1", "name": "Maps", "type": "MapStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data], positions={"m1": 1})

    tree.set_children("m1", [_map_leaf("c1", "tier6", "Map (Tier 6)", items=8)],
                      positions={"m1": 1, "c1": 2})

    assert tree._stash_nodes["c1"].text(_COL_POSITION) == "2"
    group_node = tree._stash_nodes["c1"].parent()
    assert group_node.text(_COL_POSITION) == ""  # Gruppenknoten "Tier 6" hat keinen eigenen Platz


class _FakeMenu:
    """Ersatz für QMenu in Tests: QMenu.exec() öffnet einen modalen Event-Loop,
    der in einer Offscreen-Testumgebung ewig auf einen (nie kommenden) Klick
    wartet. Statt (unzuverlässig) QMenu.exec zu monkeypatchen, ersetzen wir
    den kompletten Namen ``QMenu`` im Modul unter Test — echte QAction-Objekte
    darunter, damit .triggered/.trigger() sich exakt wie im echten Code verhalten.

    ``exec()`` löst bewusst NICHTS automatisch aus (anders als eine frühere
    Fassung): der Baum hat inzwischen mehrere Aktionen im selben Menü
    (Rohdaten, Alle öffnen, Alle schließen) — ein pauschales "alle auslösen"
    würde sie gegeneinander ausspielen (öffnen gefolgt von schließen landet
    immer beim letzten). Tests triggern die gewünschte Aktion gezielt über
    ``_FakeMenu.last.trigger(text)``, wie ein echter Klick auf GENAU einen
    Menüpunkt."""

    last: "_FakeMenu | None" = None

    def __init__(self, *args, **kwargs) -> None:
        self._actions: list[QAction] = []
        _FakeMenu.last = self

    def addAction(self, text: str) -> QAction:
        action = QAction(text)
        self._actions.append(action)
        return action

    def addSeparator(self) -> None:
        pass

    def exec(self, *args, **kwargs) -> None:
        pass

    def texts(self) -> list[str]:
        return [a.text() for a in self._actions]

    def trigger(self, text: str) -> None:
        for action in self._actions:
            if action.text() == text:
                action.trigger()
                return
        raise AssertionError(f"Keine Aktion mit Text {text!r} im Menü ({self.texts()})")


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
    _FakeMenu.last.trigger("🔍 View Raw Data")

    assert received == [("root1", "Currency 1")]


def test_context_menu_omits_raw_data_for_folder_node(qapp, monkeypatch) -> None:
    """Ordner haben keine eigenen Rohdaten — kein "Rohdaten anzeigen", aber
    Alle öffnen/schließen gilt für den ganzen Baum und bleibt verfügbar."""
    data = [{"id": "folder1", "name": "Folder", "type": "Folder", "metadata": {"folder": True},
             "children": [{"id": "child1", "name": "Sub", "type": "CurrencyStash", "metadata": {}}]}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    pos = tree.visualItemRect(tree.topLevelItem(0)).center()

    monkeypatch.setattr(stash_tree_module, "QMenu", _FakeMenu)
    received = []
    tree.raw_data_requested.connect(lambda sid, name: received.append((sid, name)))

    tree._on_context_menu(pos)

    assert "🔍 View Raw Data" not in _FakeMenu.last.texts()
    _FakeMenu.last.trigger("▸ Expand All")
    assert received == []  # kein Rohdaten-Signal für den Ordner
    assert tree.topLevelItem(0).isExpanded()  # "Alle öffnen" hat trotzdem gegriffen


def test_context_menu_expand_and_collapse_all_available_everywhere(qapp, monkeypatch) -> None:
    """"Alle öffnen"/"Alle schließen" steht auch im leeren Bereich zur
    Verfügung (kein Fach unter dem Cursor) — es betrifft den ganzen Baum,
    nicht eine einzelne Zeile."""
    data = [{"id": "folder1", "name": "Folder", "type": "Folder", "metadata": {"folder": True},
             "children": [{"id": "child1", "name": "Sub", "type": "CurrencyStash", "metadata": {}}]}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])
    assert not tree.topLevelItem(0).isExpanded()

    monkeypatch.setattr(stash_tree_module, "QMenu", _FakeMenu)
    empty_pos = tree.viewport().rect().bottomLeft()  # unterhalb der letzten Zeile

    tree._on_context_menu(empty_pos)
    assert "🔍 View Raw Data" not in _FakeMenu.last.texts()
    _FakeMenu.last.trigger("▸ Expand All")
    assert tree.topLevelItem(0).isExpanded()

    tree._on_context_menu(empty_pos)
    _FakeMenu.last.trigger("▾ Collapse All")
    assert not tree.topLevelItem(0).isExpanded()


def _map_leaf(child_id: str, section: str, name: str, index: int = 0,
              items: int = 1) -> StashTab:
    """Kind-Fach in der echten Struktur (Nutzer-Rohdaten 2026-07-09)."""
    return StashTab.model_validate({
        "id": child_id, "name": "1", "parent": "m1", "type": "MapStash",
        "metadata": {"items": items,
                     "map": {"section": section, "name": name, "index": index}},
    })


def test_set_children_inserts_subtabs_without_rebuilding_tree(qapp) -> None:
    """Spezial-Tab (MapStash): entdeckte Kinder unter dem Knoten einhängen —
    Aufklapp-Zustand des restlichen Baums bleibt erhalten."""
    data = [
        {"id": "m1", "name": "Maps", "type": "MapStash", "metadata": {}},
        {"id": "other", "name": "Other", "type": "QuadStash", "metadata": {}},
    ]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])

    tree.set_children("m1", [_map_leaf("c1", "tier6", "Map (Tier 6)", items=8)])

    parent_node = tree._stash_nodes["m1"]
    assert parent_node.childCount() == 1  # der Gruppenknoten "Tier 6"
    group = parent_node.child(0)
    assert group.text(_COL_NAME) == "🗂 Tier 6"
    assert group.text(_COL_COUNT) == "8"
    assert group.child(0).text(_COL_NAME) == "Tab 1"
    assert group.child(0).text(_COL_COUNT) == "8"
    assert parent_node.isExpanded()
    assert tree._stash_nodes["c1"].text(_COL_STATUS) == "⬇"  # Kind noch nicht geladen
    assert tree.topLevelItemCount() == 2  # Rest des Baums unangetastet


def test_map_children_are_grouped_by_section_in_order(qapp) -> None:
    """100+ flache Map-Fächer waren "uferlos" — Gruppierung
    nach Tier (numerisch!), dann Unique Maps, dann Special Maps."""
    data = [{"id": "m1", "name": "Maps", "type": "MapStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])

    children = [
        _map_leaf("c_t16a", "tier16", "Map (Tier 16)", index=0, items=14),
        _map_leaf("c_uniq", "unique", "Death and Taxes", items=2),
        _map_leaf("c_t2", "tier2", "Map (Tier 2)", items=8),
        _map_leaf("c_spec", "special", "Shaper Guardian Map", items=1),
        _map_leaf("c_t16b", "tier16", "Map (Tier 16)", index=1, items=5),
    ]
    tree.set_children("m1", children)

    parent_node = tree._stash_nodes["m1"]
    labels = [parent_node.child(i).text(_COL_NAME) for i in range(parent_node.childCount())]
    counts = [parent_node.child(i).text(_COL_COUNT) for i in range(parent_node.childCount())]
    # tier2 vor tier16 (numerisch, nicht lexikographisch!), unique und special hinten
    assert labels == ["🗂 Tier 2", "🗂 Tier 16", "🗂 Unique Maps", "🗂 Special Maps"]
    assert counts == ["8", "19", "2", "1"]

    tier16 = parent_node.child(1)
    assert [tier16.child(i).text(_COL_NAME) for i in range(tier16.childCount())] == \
        ["Tab 1", "Tab 2"]
    assert [tier16.child(i).text(_COL_COUNT) for i in range(tier16.childCount())] == \
        ["14", "5"]
    unique = parent_node.child(2)
    assert unique.child(0).text(_COL_NAME) == "Death and Taxes"
    assert unique.child(0).text(_COL_COUNT) == "2"
    # Gruppenknoten sind reine Anzeige: kein Klick-Ziel, kein ⬇/⟳
    assert parent_node.child(0).data(0, Qt.ItemDataRole.UserRole) is None
    # Fächer bleiben normal klick-/refreshbar (im Index)
    assert "c_t16b" in tree._stash_nodes


def test_grouped_children_survive_full_rerender(qapp) -> None:
    """set_stashes (Liga-Wechsel/Neustart) rendert persistierte Kinder ebenfalls
    gruppiert — nicht nur der set_children-Pfad."""
    map_stash = StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                          "metadata": {}})
    map_stash.children = [_map_leaf("c1", "tier6", "Map (Tier 6)", items=8)]
    tree = StashTree()
    tree.set_stashes([map_stash])

    parent_node = tree._stash_nodes["m1"]
    assert parent_node.child(0).text(_COL_NAME) == "🗂 Tier 6"
    assert parent_node.child(0).text(_COL_COUNT) == "8"
    assert "c1" in tree._stash_nodes


def test_mark_loaded_propagates_count_to_ancestor_group(qapp) -> None:
    """Lädt man ein Fach neu und die echte Item-Anzahl weicht vom API-Hinweis
    ab, muss die Gruppensumme ("Tier 6") mitziehen."""
    data = [{"id": "m1", "name": "Maps", "type": "MapStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])
    tree.set_children("m1", [
        _map_leaf("c1", "tier6", "Map (Tier 6)", index=0, items=8),
        _map_leaf("c2", "tier6", "Map (Tier 6)", index=1, items=3),
    ])
    group = tree._stash_nodes["c1"].parent()
    assert group.text(_COL_COUNT) == "11"

    tree.mark_loaded("c1", datetime.now(timezone.utc).isoformat(), count=20)  # echte Zahl weicht ab

    assert tree._stash_nodes["c1"].text(_COL_COUNT) == "20"
    assert group.text(_COL_COUNT) == "23"  # 20 + 3, nicht mehr 8 + 3


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
    assert tree._stash_nodes["new"].text(_COL_NAME) == "New"


def test_tab_colour_is_icon_not_text_colour(qapp) -> None:
    """Farbe als Icon-Swatch statt Textfarbe — dunkle API-Farben bleiben lesbar."""
    data = [{"id": "root1", "name": "Dark Tab", "type": "QuadStash",
             "metadata": {"colour": "000000"}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    node = tree._stash_nodes["root1"]
    # NoBrush == nie per setForeground() überschrieben, Text bleibt Theme-Farbe
    assert node.foreground(_COL_NAME).style() == Qt.BrushStyle.NoBrush
    assert not node.icon(_COL_NAME).isNull()


# --- Offline-Markierung (GGG-Wartung am Patchday) --------- #

def test_set_offline_marks_loaded_tabs_leaves_unloaded_alone(qapp) -> None:
    data = [{"id": "loaded", "name": "Currency 1", "type": "CurrencyStash", "metadata": {}},
            {"id": "never", "name": "Currency 2", "type": "CurrencyStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    tree.set_stashes(stashes, last_loaded={"loaded": three_days_ago})

    tree.set_offline(True)

    loaded_button = tree.itemWidget(tree._stash_nodes["loaded"], _COL_STATUS)
    assert loaded_button.text() == "📴 3d ago"
    assert "offline cache" in loaded_button.toolTip()
    # Nie geladener Tab bleibt unverändert — für ihn gibt es online wie
    # offline nichts anzuzeigen.
    never_node = tree._stash_nodes["never"]
    assert never_node.text(_COL_STATUS) == "⬇"
    assert tree.itemWidget(never_node, _COL_STATUS) is None


def test_set_offline_false_restores_refresh_button(qapp) -> None:
    data = [{"id": "loaded", "name": "Currency 1", "type": "CurrencyStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    tree.set_stashes(stashes, last_loaded={"loaded": three_days_ago})

    tree.set_offline(True)
    tree.set_offline(False)

    button = tree.itemWidget(tree._stash_nodes["loaded"], _COL_STATUS)
    assert button.text() == "⟳ 3d ago"


def test_set_offline_idempotent_noop_when_unchanged(qapp) -> None:
    """Kein unnötiges Neu-Rendern, wenn sich der Zustand gar nicht ändert."""
    data = [{"id": "loaded", "name": "Currency 1", "type": "CurrencyStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes, last_loaded={"loaded": datetime.now(timezone.utc).isoformat()})

    tree.set_offline(False)  # war schon False

    button = tree.itemWidget(tree._stash_nodes["loaded"], _COL_STATUS)
    assert button.text().startswith("⟳")


# --- Baum-Hervorhebung bei Item-Auswahl ------------------ #

def test_highlight_stash_selects_and_expands_ancestors(qapp) -> None:
    """Klick auf ein Item in einer Aggregat-/Suchansicht soll das
    Herkunfts-Fach im Baum zeigen — auch wenn es in einem zugeklappten
    Ordner liegt."""
    data = [
        {"id": "folder1", "name": "Folder", "type": "Folder", "metadata": {"folder": True},
         "children": [{"id": "child1", "name": "Sub", "type": "CurrencyStash", "metadata": {}}]},
    ]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    folder_node = tree.topLevelItem(0)
    assert not folder_node.isExpanded()  # startet zugeklappt

    tree.highlight_stash("child1")

    assert folder_node.isExpanded()
    assert tree.currentItem() is tree._stash_nodes["child1"]


def test_highlight_stash_does_not_emit_stash_selected(qapp) -> None:
    """Kritisch: die Hervorhebung darf nicht wie ein
    echter Klick wirken — sonst würde sie die aktuelle Such-/Aggregat-
    Ansicht in der Item-Tabelle überschreiben."""
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    stashes = [StashTab.model_validate(d) for d in data]
    tree = StashTree()
    tree.set_stashes(stashes)
    received = []
    tree.stash_selected.connect(lambda sid, name: received.append((sid, name)))

    tree.highlight_stash("root1")

    assert received == []


def test_highlight_stash_unknown_id_is_noop(qapp) -> None:
    tree = StashTree()
    tree.set_stashes([])
    tree.highlight_stash("does-not-exist")  # darf nicht crashen


# --- Einfärbung nach Datenalter -------------------------- #

def _text_and_base(tree: StashTree) -> tuple:
    return (tree.palette().color(QPalette.ColorRole.Text),
            tree.palette().color(QPalette.ColorRole.Base))


def _distance(a, b) -> int:
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())


def test_freshly_loaded_tab_keeps_normal_text_colour(qapp) -> None:
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data],
                     last_loaded={"root1": datetime.now(timezone.utc).isoformat()})
    node = tree._stash_nodes["root1"]
    text, _base = _text_and_base(tree)
    assert node.foreground(_COL_NAME).color() == text


def test_data_older_than_three_hours_is_dimmed_more_than_one_hour_old(qapp) -> None:
    data = [{"id": "recent", "name": "Recent", "type": "CurrencyStash", "metadata": {}},
            {"id": "old", "name": "Old", "type": "CurrencyStash", "metadata": {}}]
    tree = StashTree()
    now = datetime.now(timezone.utc)
    tree.set_stashes([StashTab.model_validate(d) for d in data], last_loaded={
        "recent": (now - timedelta(hours=2)).isoformat(),
        "old": (now - timedelta(hours=5)).isoformat(),
    })
    text, base = _text_and_base(tree)
    recent_colour = tree._stash_nodes["recent"].foreground(_COL_NAME).color()
    old_colour = tree._stash_nodes["old"].foreground(_COL_NAME).color()
    assert recent_colour != text  # sichtbar abgeblendet gegenüber "aktuell"
    assert _distance(old_colour, base) < _distance(recent_colour, base)  # älter = näher am Hintergrund


def test_never_loaded_and_group_nodes_keep_default_colour(qapp) -> None:
    """Ordner-/Gruppenknoten und nie geladene Fächer bleiben unangetastet
    (kein Alter, das man einfärben könnte)."""
    data = [{"id": "m1", "name": "Maps", "type": "MapStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])
    tree.set_children("m1", [_map_leaf("c1", "tier6", "Map (Tier 6)", items=8)])

    group_node = tree._stash_nodes["m1"].child(0)
    assert group_node.foreground(_COL_NAME).style() == Qt.BrushStyle.NoBrush
    never_loaded = tree._stash_nodes["c1"]
    assert never_loaded.foreground(_COL_NAME).style() == Qt.BrushStyle.NoBrush


def test_refresh_age_colors_advances_dimming_over_time(qapp) -> None:
    """Hook für den Sekunden-Tick in MainWindow: ein Fach muss auch ohne
    neue Daten von 'aktuell' auf 'älter' umgefärbt werden."""
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data],
                     last_loaded={"root1": datetime.now(timezone.utc).isoformat()})
    node = tree._stash_nodes["root1"]
    text, _base = _text_and_base(tree)
    assert node.foreground(_COL_NAME).color() == text

    stale = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    node.setData(_COL_STATUS, stash_tree_module._LAST_LOADED_ROLE, stale)
    tree.refresh_age_colors()

    assert node.foreground(_COL_NAME).color() != text


# --- Türkis-Markierung des zuletzt aktualisierten Fachs --- #

def test_mark_loaded_highlights_the_tab_turquoise(qapp) -> None:
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])

    tree.mark_loaded("root1", datetime.now(timezone.utc).isoformat())

    node = tree._stash_nodes["root1"]
    assert node.foreground(_COL_NAME).color() == QColor("turquoise")


def test_mark_loaded_moves_the_highlight_and_reverts_the_previous_tab(qapp) -> None:
    """Peter: 'die zuletzt aktualisierte Zeile' — nur eine Türkis-Markierung
    gleichzeitig, sie wandert zum jeweils neuesten Refresh."""
    data = [{"id": "a", "name": "A", "type": "CurrencyStash", "metadata": {}},
            {"id": "b", "name": "B", "type": "CurrencyStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])

    tree.mark_loaded("a", datetime.now(timezone.utc).isoformat())
    tree.mark_loaded("b", datetime.now(timezone.utc).isoformat())

    node_a = tree._stash_nodes["a"]
    node_b = tree._stash_nodes["b"]
    text, _base = _text_and_base(tree)
    assert node_b.foreground(_COL_NAME).color() == QColor("turquoise")
    assert node_a.foreground(_COL_NAME).color() == text  # zurück auf normale Alters-Farbe


def test_refresh_age_colors_does_not_overwrite_the_turquoise_highlight(qapp) -> None:
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])
    tree.mark_loaded("root1", datetime.now(timezone.utc).isoformat())

    tree.refresh_age_colors()

    assert tree._stash_nodes["root1"].foreground(_COL_NAME).color() == QColor("turquoise")


def test_set_offline_preserves_the_turquoise_highlight(qapp) -> None:
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])
    tree.mark_loaded("root1", datetime.now(timezone.utc).isoformat())

    tree.set_offline(True)

    assert tree._stash_nodes["root1"].foreground(_COL_NAME).color() == QColor("turquoise")


def test_set_stashes_clears_a_stale_highlight_from_a_previous_tree(qapp) -> None:
    """Liga-Wechsel/Neustart baut den Baum neu auf — eine alte
    Türkis-Markierung aus der vorherigen Liga wäre irreführend."""
    data = [{"id": "root1", "name": "Currency 1", "type": "QuadStash", "metadata": {}}]
    tree = StashTree()
    tree.set_stashes([StashTab.model_validate(d) for d in data])
    tree.mark_loaded("root1", datetime.now(timezone.utc).isoformat())

    tree.set_stashes([StashTab.model_validate(d) for d in data],
                     last_loaded={"root1": datetime.now(timezone.utc).isoformat()})

    text, _base = _text_and_base(tree)
    assert tree._stash_nodes["root1"].foreground(_COL_NAME).color() == text
