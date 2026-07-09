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
    assert win.tree._stash_nodes["t1"].text(1) == ""  # bereits als geladen markiert (Refresh-Button)
    assert win.tree.itemWidget(win.tree._stash_nodes["t1"], 1) is not None
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


def test_pick_auto_refresh_candidate_ignores_recent_and_never_loaded(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("fresh", "Fresh"), _make_leaf("never", "Never")]
    win._last_loaded["Standard"] = {"fresh": datetime.now(timezone.utc).isoformat()}

    assert win._pick_auto_refresh_candidate() is None

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
