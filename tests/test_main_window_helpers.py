"""Tests für MainWindow-Hilfsmethoden: rekursives Einsammeln der Nicht-Ordner-Tabs
('Alle Tabs laden'/Aggregat), Liga-Filterung der Charaktere und den
CSV-Dateiname-Vorschlag (Filtertext bzw. Tab-/Aggregat-Name).
"""

from datetime import datetime, timedelta, timezone

from poe_view.api.models import Character, Item, StashTab
from poe_view.ui.main_window import MainWindow

NESTED = [
    {"id": "root1", "name": "#", "type": "QuadStash", "metadata": {}},
    {"id": "folder1", "name": "Folder", "type": "Folder", "metadata": {"folder": True},
     "children": [
         {"id": "child1", "name": "Sub", "type": "CurrencyStash", "metadata": {}},
         {"id": "subfolder", "name": "SubFolder", "type": "Folder",
          "metadata": {"folder": True},
          "children": [{"id": "deep1", "name": "Deep", "type": "GemStash", "metadata": {}}]},
     ]},
]


def test_flatten_stashes_skips_folders_recursively() -> None:
    stashes = [StashTab.model_validate(d) for d in NESTED]
    flat = MainWindow._flatten_stashes(stashes)
    assert [s.id for s in flat] == ["root1", "child1", "deep1"]
    assert all(not s.is_folder for s in flat)


def make_char(name: str, league: str) -> Character:
    return Character.model_validate({"name": name, "class": "Witch", "level": 50, "league": league})


def test_character_league_filter_only_shows_current_league(qapp) -> None:
    """Kein Liga-Level mehr in der Liste — das Dropdown filtert stattdessen (Nutzer-Feedback)."""
    win = MainWindow()
    win._current_league = "Settlers"
    win._on_characters([make_char("A", "Settlers"), make_char("B", "Standard"),
                        make_char("C", "Settlers")])
    assert win.character_list.count() == 2

    win._current_league = "Standard"
    win._apply_character_league_filter()  # simuliert den Dropdown-Wechsel
    assert win.character_list.count() == 1
    assert win.character_list.item(0).text() == "B (Witch 50)"

    win.worker.stop()
    win.worker.wait(5000)


def test_default_export_filename_prefers_filter_text(qapp) -> None:
    win = MainWindow()
    win._current_tab_name = "Currency 1"
    win._filter_edit.setText("Chaos Orb")
    assert win._default_export_filename() == "poe-view2-Chaos-Orb.csv"

    win.worker.stop()
    win.worker.wait(5000)


def test_default_export_filename_falls_back_to_tab_name(qapp) -> None:
    win = MainWindow()
    win._current_tab_name = "Currency 1"
    assert win._default_export_filename() == "poe-view2-Currency-1.csv"

    win.worker.stop()
    win.worker.wait(5000)


def test_default_export_filename_includes_league(qapp) -> None:
    win = MainWindow()
    win._current_league = "Settlers"
    win._current_tab_name = "Currency 1"
    assert win._default_export_filename() == "poe-view2-Settlers-Currency-1.csv"

    win._filter_edit.setText("Chaos Orb")
    assert win._default_export_filename() == "poe-view2-Settlers-Chaos-Orb.csv"

    win.worker.stop()
    win.worker.wait(5000)


def test_busy_indicator_toggles_with_busy_changed(qapp) -> None:
    # isHidden() statt isVisible(): win.show() läuft hier nicht, isVisible()
    # wäre also unabhängig vom Widget-Zustand immer False (Ancestor-Kette).
    win = MainWindow()
    win._on_busy_changed(True)
    assert not win._busy_indicator.isHidden()
    win._on_busy_changed(False)
    assert win._busy_indicator.isHidden()

    win.worker.stop()
    win.worker.wait(5000)


def test_status_text_is_not_reset_by_on_status(qapp) -> None:
    """Regression FALLSTRICKE #8: _on_status darf den Busy-Indikator nicht mehr umschalten."""
    win = MainWindow()
    win._on_busy_changed(True)
    win._on_status("Currency 1: 45 Items")
    assert win._status_msg.text() == "Currency 1: 45 Items"
    assert not win._busy_indicator.isHidden()  # busy_changed(True) wirkt weiter fort

    win.worker.stop()
    win.worker.wait(5000)


def test_activate_stash_tree_renders_from_cache_without_network(qapp) -> None:
    """Persistenz-Kern: zeigt bereits bekannte Stash-Daten sofort, ohne auf Live-API zu warten."""
    win = MainWindow()
    win._current_league = "Standard"
    stash = StashTab.model_validate({"id": "t1", "name": "Tab", "type": "CurrencyStash",
                                      "metadata": {}})
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})]}
    win._last_loaded["Standard"] = {"t1": "2026-07-08T12:00:00+00:00"}

    win._activate_stash_tree([stash])

    assert set(win.tree._stash_nodes.keys()) == {"t1"}
    assert win.tree._stash_nodes["t1"].text(2) == ""  # bereits als geladen markiert (Refresh-Button)
    assert win.tree.itemWidget(win.tree._stash_nodes["t1"], 2) is not None
    assert win.tree._stash_nodes["t1"].text(1) == "1"  # Item-Anzahl-Spalte
    assert [s.id for s in win._leaf_stashes] == ["t1"]

    win.worker.stop()
    win.worker.wait(5000)


def test_restore_cached_data_populates_state_at_startup(qapp, monkeypatch, tmp_path) -> None:
    from poe_view.services import data_cache

    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(data_cache, "_CACHE_FILE", cache_path)

    char = make_char("A", "Standard")
    data = data_cache.CachedData()
    data.characters = [char]
    data.stash_trees = {"Standard": []}
    data.items_by_league = {}
    data_cache.save(data)

    win = MainWindow()
    assert win._all_characters == [char]
    assert "Standard" in win._stash_trees

    win.worker.stop()
    win.worker.wait(5000)


def test_on_stash_items_ignores_result_for_stale_league(qapp) -> None:
    """Regression: ein Hintergrund-Job für Liga X darf nicht in die Anzeige der
    inzwischen aktiven Liga Y einsickern — nur in den Cache."""
    win = MainWindow()
    win._current_league = "Standard"

    win._on_stash_items("Hardcore", "t1", "Tab", [], silent=False)

    assert win._items["Hardcore"]["t1"] == []  # landet trotzdem im Cache …
    assert "t1" not in win.tree._stash_nodes  # … aber NICHT in der aktiven Baum-Anzeige

    win.worker.stop()
    win.worker.wait(5000)


def test_on_stash_items_silent_updates_cache_but_not_table(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})

    win._on_stash_items("Standard", "t1", "Tab", [item], silent=True)

    assert win._items["Standard"]["t1"] == [item]
    assert win.table_model.rowCount() == 0  # Anzeige unangetastet (Nutzer-Feedback)

    win.worker.stop()
    win.worker.wait(5000)


def _make_leaf(stash_id: str, name: str) -> StashTab:
    return StashTab.model_validate({"id": stash_id, "name": name, "type": "CurrencyStash",
                                     "metadata": {}})


def test_pick_auto_refresh_candidate_ignores_only_recent_tabs(qapp) -> None:
    """Frisch geladene (< 1 Tag) Tabs werden geschont — dafür reicht der manuelle Refresh."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("fresh", "Fresh")]
    win._last_loaded["Standard"] = {"fresh": datetime.now(timezone.utc).isoformat()}

    assert win._pick_auto_refresh_candidate() is None

    win.worker.stop()
    win.worker.wait(5000)


def test_pick_auto_refresh_candidate_includes_never_loaded_tabs(qapp) -> None:
    """Regression: Nutzer-Feedback — bei 391 Tabs bleibt der Zähler sonst für immer
    auf 0 stehen, weil nie geladene Tabs ohne diese Regel gar keine Kandidaten sind."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("never", "Never Loaded")]
    win._last_loaded["Standard"] = {}

    candidate = win._pick_auto_refresh_candidate()
    assert candidate is not None and candidate.id == "never"

    win.worker.stop()
    win.worker.wait(5000)


def test_pick_auto_refresh_candidate_prefers_never_loaded_over_stale(qapp) -> None:
    """Nie geladene Tabs gelten als 'unendlich alt' und gewinnen gegen jeden
    bereits bekannten (auch sehr alten) stale Tab."""
    win = MainWindow()
    win._current_league = "Standard"
    now = datetime.now(timezone.utc)
    win._leaf_stashes = [_make_leaf("old", "Old Tab"), _make_leaf("never", "Never Loaded")]
    win._last_loaded["Standard"] = {"old": (now - timedelta(days=100)).isoformat()}

    candidate = win._pick_auto_refresh_candidate()
    assert candidate is not None and candidate.id == "never"

    win.worker.stop()
    win.worker.wait(5000)


def test_pick_auto_refresh_candidate_prefers_oldest_stale_tab(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    now = datetime.now(timezone.utc)
    win._leaf_stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    win._last_loaded["Standard"] = {
        "t1": (now - timedelta(days=2)).isoformat(),
        "t2": (now - timedelta(days=5)).isoformat(),
    }

    candidate = win._pick_auto_refresh_candidate()
    assert candidate is not None and candidate.id == "t2"  # älteste Daten zuerst

    win.worker.stop()
    win.worker.wait(5000)


def test_pick_auto_refresh_candidate_deprioritises_remove_only_tabs(qapp) -> None:
    """Nutzer-Feedback: Tabs mit 'Remove-only' im Namen nur nehmen, wenn es
    keine andere stale Alternative gibt."""
    win = MainWindow()
    win._current_league = "Standard"
    now = datetime.now(timezone.utc)
    win._leaf_stashes = [_make_leaf("ro", "Guild Tab (Remove-only)"), _make_leaf("t2", "Tab 2")]
    win._last_loaded["Standard"] = {
        "ro": (now - timedelta(days=10)).isoformat(),  # älter, aber Remove-only
        "t2": (now - timedelta(days=2)).isoformat(),
    }

    candidate = win._pick_auto_refresh_candidate()
    assert candidate is not None and candidate.id == "t2"

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_counter_label_counts_silent_loads(qapp) -> None:
    """Nutzer-Feedback: sichtbarer Nachweis „X von Y Stash-Tabs aktualisiert“."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    win._update_auto_refresh_label()
    assert win._auto_refresh_label.text() == "Auto-Refresh: 0 von 2 Stash-Tabs aktualisiert"

    win._on_stash_items("Standard", "t1", "Tab 1", [], silent=True)
    assert win._auto_refresh_label.text() == "Auto-Refresh: 1 von 2 Stash-Tabs aktualisiert"

    # Manuelle (nicht-silente) Ladevorgänge zählen NICHT als Auto-Refresh.
    win._on_stash_items("Standard", "t2", "Tab 2", [], silent=False)
    assert win._auto_refresh_label.text() == "Auto-Refresh: 1 von 2 Stash-Tabs aktualisiert"

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_label_is_empty_without_league(qapp) -> None:
    win = MainWindow()
    win._update_auto_refresh_label()
    assert win._auto_refresh_label.text() == ""

    win.worker.stop()
    win.worker.wait(5000)


def test_maybe_auto_refresh_skips_when_worker_busy_or_low_headroom(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    now = datetime.now(timezone.utc)
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    win._last_loaded["Standard"] = {"t1": (now - timedelta(days=5)).isoformat()}

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._worker_busy = True
    win._maybe_auto_refresh()
    assert submitted == []

    win._worker_busy = False
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 0.1)
    win._maybe_auto_refresh()
    assert submitted == []

    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)
    win._maybe_auto_refresh()
    assert len(submitted) == 1
    assert submitted[0].stash_id == "t1"
    assert submitted[0].silent is True

    win.worker.stop()
    win.worker.wait(5000)


# --- Rohdaten-Mini-Viewer (Nutzer-Feedback) ------------------------------ #

def test_build_raw_stash_payload_merges_tab_metadata_and_items(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    stash = StashTab.model_validate({"id": "t1", "name": "Tab", "type": "CurrencyStash",
                                      "metadata": {"colour": "ff0000"}})
    win._stash_trees["Standard"] = [stash]
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5, "stackSize": 3})
    win._items["Standard"] = {"t1": [item]}

    payload = win._build_raw_stash_payload("t1")

    assert payload is not None
    assert payload["id"] == "t1"
    assert payload["metadata"]["colour"] == "ff0000"
    assert payload["items"][0]["typeLine"] == "Chaos Orb"

    win.worker.stop()
    win.worker.wait(5000)


def test_build_raw_stash_payload_returns_none_for_unknown_tab(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"

    assert win._build_raw_stash_payload("nope") is None

    win.worker.stop()
    win.worker.wait(5000)


def test_update_raw_viewer_only_refreshes_when_visible(qapp) -> None:
    from poe_view.ui.raw_data_viewer import RawDataViewer

    win = MainWindow()
    win._current_league = "Standard"
    stash = StashTab.model_validate({"id": "t1", "name": "Tab", "type": "CurrencyStash",
                                      "metadata": {}})
    win._stash_trees["Standard"] = [stash]
    win._items["Standard"] = {"t1": []}
    win._raw_data_viewer = RawDataViewer(win)

    win._update_raw_viewer("t1", "Tab")
    assert win._raw_data_viewer._text.toPlainText() == ""  # nicht sichtbar -> kein Update

    win._raw_data_viewer.show()
    win._update_raw_viewer("t1", "Tab")
    assert '"id": "t1"' in win._raw_data_viewer._text.toPlainText()

    win.worker.stop()
    win.worker.wait(5000)


def test_on_raw_data_requested_opens_viewer_and_shows_cached_data(qapp) -> None:
    """Rechtsklick 'Rohdaten anzeigen' öffnet den Viewer UND lädt (bei Cache-Treffer
    sofort) die Daten hinein — wie ein normaler Linksklick auf den Tab."""
    win = MainWindow()
    win._current_league = "Standard"
    stash = StashTab.model_validate({"id": "t1", "name": "Tab", "type": "CurrencyStash",
                                      "metadata": {}})
    win._stash_trees["Standard"] = [stash]
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})
    win._items["Standard"] = {"t1": [item]}

    win._on_raw_data_requested("t1", "Tab")

    assert win._raw_data_viewer is not None
    assert win._raw_data_viewer.isVisible()
    assert "Chaos Orb" in win._raw_data_viewer._text.toPlainText()

    win.worker.stop()
    win.worker.wait(5000)


def test_raw_viewer_follows_tab_switches(qapp) -> None:
    """Kern des Nutzer-Wunsches: der Viewer aktualisiert sich beim Durchklicken
    verschiedener Tabs von selbst, ohne dass erneut rechtsgeklickt werden muss."""
    win = MainWindow()
    win._current_league = "Standard"
    win._stash_trees["Standard"] = [
        StashTab.model_validate({"id": "t1", "name": "Tab 1", "type": "CurrencyStash", "metadata": {}}),
        StashTab.model_validate({"id": "t2", "name": "Tab 2", "type": "CurrencyStash", "metadata": {}}),
    ]
    win._items["Standard"] = {
        "t1": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})],
        "t2": [Item.model_validate({"typeLine": "Divine Orb", "frameType": 5})],
    }

    win._on_raw_data_requested("t1", "Tab 1")
    assert "Chaos Orb" in win._raw_data_viewer._text.toPlainText()

    win._on_stash_selected("t2", "Tab 2")  # normaler Klick auf einen anderen Tab
    assert "Divine Orb" in win._raw_data_viewer._text.toPlainText()
    assert "Chaos Orb" not in win._raw_data_viewer._text.toPlainText()

    win.worker.stop()
    win.worker.wait(5000)


# --- Spezial-Tabs: MapStash/UniqueStash (Nutzer-Feedback) ----------------- #

def _map_child(child_id: str, parent_id: str, map_name: str, items: int | None = None) -> StashTab:
    metadata: dict = {"map": {"name": map_name, "tier": 16}}
    if items is not None:
        metadata["items"] = items
    return StashTab.model_validate({
        "id": child_id, "parent": parent_id, "type": "MapStash", "metadata": metadata,
    })


def test_flatten_treats_special_tab_with_children_as_container() -> None:
    map_stash = StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                          "metadata": {}})
    map_stash.children = [_map_child("c1", "m1", "Beach Map")]
    flat = MainWindow._flatten_stashes([map_stash, _make_leaf("t1", "Tab")])
    assert [s.id for s in flat] == ["c1", "t1"]  # Kind statt Spezial-Tab-Eltern


def test_flatten_keeps_undiscovered_special_tab_as_leaf() -> None:
    """Vor der Entdeckung hat der MapStash keine children — er muss Leaf bleiben,
    damit sein erster Abruf (Klick/Auto-Refresh) die Kinder überhaupt entdeckt."""
    map_stash = StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                          "metadata": {}})
    flat = MainWindow._flatten_stashes([map_stash])
    assert [s.id for s in flat] == ["m1"]


def test_on_stash_children_grafts_into_tree_and_updates_leaves(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    map_stash = StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                          "metadata": {}})
    win._stash_trees["Standard"] = [map_stash]
    win._activate_stash_tree(win._stash_trees["Standard"])
    assert [s.id for s in win._leaf_stashes] == ["m1"]

    children = [_map_child("c1", "m1", "Beach Map"), _map_child("c2", "m1", "Dunes Map")]
    win._on_stash_children("Standard", "m1", "Maps", children, silent=False)

    # Struktur: Kinder im Liga-Baum verankert, Leaves umgestellt
    assert win._stash_trees["Standard"][0].children == children
    assert [s.id for s in win._leaf_stashes] == ["c1", "c2"]
    # UI: Kind-Knoten hängen im Baum unter dem (aufgeklappten) Eltern-Knoten
    assert "c1" in win.tree._stash_nodes and "c2" in win.tree._stash_nodes
    assert win.tree._stash_nodes["m1"].isExpanded()
    # Eltern-Tab gilt als geladen (Struktur bekannt), Kinder noch nicht
    assert win._last_loaded["Standard"].get("m1") is not None
    assert win.tree._stash_nodes["c1"].text(2) == "⬇"

    win.worker.stop()
    win.worker.wait(5000)


def test_on_stash_children_shows_aggregate_count_on_parent_node(qapp) -> None:
    """Nutzer-Feedback: Item-Anzahl in eigener Spalte — der Spezial-Tab-Eltern-
    knoten selbst zeigt die Summe der (bekannten) Kind-Anzahlen."""
    win = MainWindow()
    win._current_league = "Standard"
    map_stash = StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                          "metadata": {}})
    win._stash_trees["Standard"] = [map_stash]
    win._activate_stash_tree(win._stash_trees["Standard"])

    children = [_map_child("c1", "m1", "Beach Map", items=8),
                _map_child("c2", "m1", "Dunes Map", items=5)]
    win._on_stash_children("Standard", "m1", "Maps", children, silent=False)

    assert win.tree._stash_nodes["m1"].text(1) == "13"

    win.worker.stop()
    win.worker.wait(5000)


def test_merge_known_children_survives_stash_list_refresh(qapp) -> None:
    """Die Liga-LISTE kennt Spezial-Tab-Kinder nicht — ohne Merge wären sie nach
    jedem Listen-Refresh/Liga-Wechsel wieder weg."""
    win = MainWindow()
    win._current_league = "Standard"
    old_map = StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                        "metadata": {}})
    old_map.children = [_map_child("c1", "m1", "Beach Map")]
    win._stash_trees["Standard"] = [old_map]

    # Frische Liste von der API: MapStash OHNE children (wie die API sie liefert)
    fresh = [StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                       "metadata": {}})]
    win._on_stash_list(fresh)

    assert win._stash_trees["Standard"][0].children[0].id == "c1"
    assert [s.id for s in win._leaf_stashes] == ["c1"]

    win.worker.stop()
    win.worker.wait(5000)


def test_click_on_special_tab_child_submits_job_with_parent_id(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    map_stash = StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                          "metadata": {}})
    map_stash.children = [_map_child("c1", "m1", "Beach Map")]
    win._stash_trees["Standard"] = [map_stash]

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_stash_selected("c1", "Beach Map (T16)")

    assert len(submitted) == 1
    assert submitted[0].stash_id == "c1"
    assert submitted[0].parent_id == "m1"

    win.worker.stop()
    win.worker.wait(5000)


def test_special_tab_click_bypasses_stale_zero_item_cache(qapp, monkeypatch) -> None:
    """Nutzer-Befund: MapStash 'funktionierte nicht', bis manuell aktualisiert
    wurde. Ursache: ein alter '0 Items'-Cache-Eintrag (von vor dem Spezial-Tab-
    Feature) war ein permanenter Cache-Treffer — die Kinder-Entdeckung fand nie
    statt. Spezial-Tabs ohne bekannte Kinder müssen den Item-Cache ignorieren."""
    win = MainWindow()
    win._current_league = "Standard"
    map_stash = StashTab.model_validate({"id": "m1", "name": "M", "type": "MapStash",
                                          "metadata": {}})
    win._stash_trees["Standard"] = [map_stash]
    win._items["Standard"] = {"m1": []}  # der Alt-Eintrag, der alles blockierte

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_stash_selected("m1", "M")

    assert len(submitted) == 1 and submitted[0].stash_id == "m1"

    win.worker.stop()
    win.worker.wait(5000)


def test_special_tab_click_with_known_children_aggregates_without_fetch(qapp, monkeypatch) -> None:
    """Struktur bekannt → kein API-Call; die Anzeige aggregiert die (hier: null)
    geladenen Unter-Fächer (Details: test_special_parent_click_aggregates_…)."""
    win = MainWindow()
    win._current_league = "Standard"
    map_stash = StashTab.model_validate({"id": "m1", "name": "M", "type": "MapStash",
                                          "metadata": {}})
    map_stash.children = [_map_child("c1", "m1", "Map (Tier 6)")]
    win._stash_trees["Standard"] = [map_stash]

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_stash_selected("m1", "M")

    assert submitted == []
    assert "0 von 1" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_on_stash_children_purges_stale_parent_item_entry(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    map_stash = StashTab.model_validate({"id": "m1", "name": "M", "type": "MapStash",
                                          "metadata": {}})
    win._stash_trees["Standard"] = [map_stash]
    win._items["Standard"] = {"m1": []}  # Alt-Eintrag

    win._on_stash_children("Standard", "m1", "M", [_map_child("c1", "m1", "Map (Tier 6)")],
                           silent=False)

    assert "m1" not in win._items["Standard"]

    win.worker.stop()
    win.worker.wait(5000)


def test_load_all_includes_special_tabs_despite_cache_entry(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    map_stash = StashTab.model_validate({"id": "m1", "name": "M", "type": "MapStash",
                                          "metadata": {}})
    win._stash_trees["Standard"] = [map_stash]
    win._leaf_stashes = [map_stash, _make_leaf("t1", "Tab")]
    win._items["Standard"] = {"m1": [], "t1": []}  # beide "im Cache"

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._load_all_items()

    # Normaler Tab t1 bleibt Cache-Treffer, der Spezial-Tab m1 wird trotzdem geholt
    assert len(submitted) == 1
    assert [s.id for s in submitted[0].stashes] == ["m1"]

    win.worker.stop()
    win.worker.wait(5000)


# --- Item-Spalten: Sichtbarkeit + kontextabhängige Tab-Spalte ------------- #

def test_typ_column_hidden_by_default_mods_visible(qapp) -> None:
    """Nutzer-Feedback: Typ default aus (Rarity steckt in der Namensfarbe),
    Mods-Spalte (Map-Modifikatoren) sichtbar."""
    from poe_view.ui.item_table import COLUMNS
    win = MainWindow()
    assert win.table.isColumnHidden(COLUMNS.index("Typ"))
    assert not win.table.isColumnHidden(COLUMNS.index("Mods"))
    assert not win.table.isColumnHidden(COLUMNS.index("Name"))

    win.worker.stop()
    win.worker.wait(5000)


def test_column_toggle_persists_across_restart(qapp) -> None:
    from poe_view.ui.item_table import COLUMNS
    win = MainWindow()
    win._toggle_column("Typ")   # einblenden
    win._toggle_column("Mods")  # ausblenden
    assert not win.table.isColumnHidden(COLUMNS.index("Typ"))
    assert win.table.isColumnHidden(COLUMNS.index("Mods"))
    win.worker.stop()
    win.worker.wait(5000)

    win2 = MainWindow()  # "Neustart": liest ui-settings.ini (im Test: tmp_path)
    assert not win2.table.isColumnHidden(COLUMNS.index("Typ"))
    assert win2.table.isColumnHidden(COLUMNS.index("Mods"))

    win2.worker.stop()
    win2.worker.wait(5000)


def test_tab_column_auto_hidden_for_single_tab_shown_for_aggregate(qapp) -> None:
    """Nutzer-Feedback: Im Einzelfach ist die Herkunft redundant, im Aggregat
    ("Map"-Elternknoten, "Alle Tabs") ist sie die entscheidende Info."""
    from poe_view.ui.item_table import TAB_COL
    win = MainWindow()
    win._current_league = "Standard"

    win._show_items("t1", [], "Currency 1")
    assert win.table.isColumnHidden(TAB_COL)

    win._leaf_stashes = []
    win._show_aggregate()
    assert not win.table.isColumnHidden(TAB_COL)

    win.worker.stop()
    win.worker.wait(5000)


def test_special_parent_click_aggregates_loaded_children(qapp) -> None:
    """Klick auf den "Map"-Elternknoten zeigt die Items aller GELADENEN
    Unter-Fächer, Tab-Spalte trägt den Fach-Namen ("Map (Tier 6)")."""
    from poe_view.ui.item_table import TAB_COL
    win = MainWindow()
    win._current_league = "Standard"
    map_stash = StashTab.model_validate({"id": "m1", "name": "M", "type": "MapStash",
                                          "metadata": {}})
    c1 = StashTab.model_validate({"id": "c1", "name": "1", "parent": "m1", "type": "MapStash",
                                  "metadata": {"map": {"section": "tier6",
                                                       "name": "Map (Tier 6)", "index": 0}}})
    c2 = StashTab.model_validate({"id": "c2", "name": "1", "parent": "m1", "type": "MapStash",
                                  "metadata": {"map": {"section": "tier9",
                                                       "name": "Map (Tier 9)", "index": 0}}})
    map_stash.children = [c1, c2]
    win._stash_trees["Standard"] = [map_stash]
    # nur c1 ist geladen, c2 nicht
    win._items["Standard"] = {"c1": [Item.model_validate({"typeLine": "Beach Map",
                                                          "frameType": 0})]}

    win._on_stash_selected("m1", "M")

    assert win.table_model.rowCount() == 1
    assert win.table_model.source_at(0) == "Map (Tier 6)"
    assert not win.table.isColumnHidden(TAB_COL)
    assert win._showing_aggregate  # einzelne Kind-Loads kapern die Ansicht nicht
    assert "1 Items aus 1 von 2" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def _unique_child(child_id: str, parent_id: str = "u1") -> StashTab:
    """Namenloses Unique-Fach in der ECHTEN Struktur (nur metadata.items)."""
    return StashTab.model_validate({"id": child_id, "name": "", "parent": parent_id,
                                    "type": "UniqueStash", "metadata": {"items": 2}})


def test_unique_child_gets_category_name_after_item_load(qapp) -> None:
    """Nutzer-Feedback: "über die Kategorie gehen, z. B. Two Handed Axe, Ring, Flask"."""
    win = MainWindow()
    win._current_league = "Standard"
    unique = StashTab.model_validate({"id": "u1", "name": "Uniq", "type": "UniqueStash",
                                       "metadata": {}})
    unique.children = [_unique_child("c1")]
    win._stash_trees["Standard"] = [unique]
    win._activate_stash_tree(win._stash_trees["Standard"])
    assert win.tree._stash_nodes["c1"].text(0) == "UniqueStash"
    assert win.tree._stash_nodes["c1"].text(1) == "2"  # metadata.items als Vorab-Hinweis

    rings = [Item.model_validate({"typeLine": "Amethyst Ring", "baseType": "Amethyst Ring",
                                  "frameType": 3})]
    win._on_stash_items("Standard", "c1", "UniqueStash", rings, silent=True)

    tab = win._stash_trees["Standard"][0].children[0]
    assert tab.metadata["poeview_category"] == "Ring"
    assert win.tree._stash_nodes["c1"].text(0) == "Ring"  # Label live aktualisiert
    assert win.tree._stash_nodes["c1"].text(1) == "1"  # echte Anzahl (1 Item geladen)

    win.worker.stop()
    win.worker.wait(5000)


def test_category_stamp_skips_named_tabs_and_map_children(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    named = _make_leaf("t1", "Currency 1")
    map_stash = StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                          "metadata": {}})
    map_stash.children = [_map_child("c_map", "m1", "Map (Tier 6)")]
    win._stash_trees["Standard"] = [named, map_stash]

    ring = Item.model_validate({"typeLine": "Amethyst Ring", "baseType": "Amethyst Ring",
                                "frameType": 3})
    assert win._stamp_category("Standard", "t1", [ring]) is None      # hat echten Namen
    assert win._stamp_category("Standard", "c_map", [ring]) is None   # Map-Fach
    assert "poeview_category" not in named.metadata

    win.worker.stop()
    win.worker.wait(5000)


def test_raw_payload_hides_synthetic_poeview_keys(qapp) -> None:
    """Der Rohdaten-Viewer verspricht API-Realität — unsere gestempelten
    poeview_*-Schlüssel dürfen dort nicht auftauchen."""
    win = MainWindow()
    win._current_league = "Standard"
    tab = StashTab.model_validate({"id": "c1", "name": "", "parent": "u1",
                                   "type": "UniqueStash",
                                   "metadata": {"items": 2, "poeview_category": "Ring"}})
    win._stash_trees["Standard"] = [tab]

    payload = win._build_raw_stash_payload("c1")

    assert payload is not None
    assert "poeview_category" not in payload["metadata"]
    assert payload["metadata"]["items"] == 2  # echte API-Felder bleiben

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_passes_parent_id_for_special_tab_children(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    child = _map_child("c1", "m1", "Beach Map")
    win._leaf_stashes = [child]
    win._last_loaded["Standard"] = {}

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    win._maybe_auto_refresh()

    assert len(submitted) == 1
    assert submitted[0].stash_id == "c1"
    assert submitted[0].parent_id == "m1"
    assert submitted[0].silent is True

    win.worker.stop()
    win.worker.wait(5000)
