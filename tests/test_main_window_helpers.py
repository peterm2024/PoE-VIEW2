"""Tests für MainWindow-Hilfsmethoden: rekursives Einsammeln der Nicht-Ordner-Tabs
('Alle Tabs laden'/Aggregat), Liga-Filterung der Charaktere und den
CSV-Dateiname-Vorschlag (Filtertext bzw. Tab-/Aggregat-Name).
"""

from datetime import datetime, timedelta, timezone

import pytest

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
    """Kein Liga-Level mehr in der Liste — das Dropdown filtert stattdessen."""
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


def test_bootstrap_job_is_submitted_before_cached_league_restore_jobs(
        qapp, monkeypatch, tmp_path) -> None:
    """Regression (Rückfrage "warum wird mein Token zwischendurch
    invalid, sollte doch Stunden gültig sein"): Ursache war eine falsche
    Job-Reihenfolge, keine echte Ablauf. `_populate_cached_leagues()`
    (Teil von `_build_ui()`) restauriert beim Start die zuletzt aktive
    Liga aus dem Cache und submitted dafür sofort einen FetchStashListJob
    — lief der vor BootstrapJob, hätte der HTTP-Client noch keinen Token
    gesetzt, GGG hätte mit 401 geantwortet, und der AuthError-Handler
    hätte den eigentlich noch stundenlang gültigen, gespeicherten Token
    gelöscht (echtes Log-Muster: 401 direkt nach "Daten-Cache geladen").
    BootstrapJob muss deshalb immer der erste Job in der Queue sein."""
    from poe_view.services import data_cache
    from poe_view.services.api_worker import ApiWorker, BootstrapJob

    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(data_cache, "_CACHE_FILE", cache_path)
    data = data_cache.CachedData()
    data.stash_trees = {"Standard": [_make_leaf("t1", "Tab 1")]}
    data_cache.save(data)

    monkeypatch.setattr(ApiWorker, "start", lambda self: None)  # Worker-Thread nie starten

    win = MainWindow()

    jobs = []
    while not win.worker._jobs.empty():
        jobs.append(win.worker._jobs.get_nowait())

    assert isinstance(jobs[0], BootstrapJob)
    assert any(type(j).__name__ == "FetchStashListJob" for j in jobs[1:])

    win.worker.stop()
    win.worker.wait(5000)


def test_on_stash_items_ignores_result_for_stale_league(qapp) -> None:
    """Regression: ein Hintergrund-Job für Liga X darf nicht in die Anzeige der
    inzwischen aktiven Liga Y einsickern — nur in den Cache."""
    win = MainWindow()
    win._current_league = "Standard"

    win._on_stash_items("Hardcore", "t1", "Tab", [], silent=False)

    assert win._items["Hardcore"]["t1"] == []  # landet trotzdem im Cache …
    assert "t1" not in win.tree._stash_nodes  # … aber nicht in der aktiven Baum-Anzeige

    win.worker.stop()
    win.worker.wait(5000)


def test_on_stash_items_silent_updates_cache_but_not_table(qapp) -> None:
    """Kein Fach ist gerade geöffnet (_current_stash_id ist None) — ein
    stiller Sweep-Treffer für irgendein Fach darf die (leere) Tabelle
    nicht anfassen."""
    win = MainWindow()
    win._current_league = "Standard"
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})

    win._on_stash_items("Standard", "t1", "Tab", [item], silent=True)

    assert win._items["Standard"]["t1"] == [item]
    assert win.table_model.rowCount() == 0  # Anzeige unangetastet

    win.worker.stop()
    win.worker.wait(5000)


def test_on_stash_items_silent_refresh_of_currently_open_tab_updates_table(qapp) -> None:
    """Regression: Das Live-Halten des gerade geöffneten Fachs durch den
    Auto-Refresh aktualisierte zunächst nur den Cache, nicht die sichtbare
    Tabelle. Ein stiller Refresh mit stash_id == _current_stash_id muss die
    Tabelle deshalb neu zeichnen."""
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"  # "t1" ist gerade als Einzelfach geöffnet
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})

    win._on_stash_items("Standard", "t1", "Tab", [item], silent=True)

    assert win.table_model.rowCount() == 1  # jetzt sichtbar aktualisiert

    win.worker.stop()
    win.worker.wait(5000)


def test_on_stash_items_silent_refresh_of_other_tab_does_not_replace_open_view(qapp) -> None:
    """Gegenprobe: während Fach "t1" offen ist, darf ein stiller Sweep-Treffer
    für ein ANDERES Fach ("t2") die Ansicht nicht wegreißen."""
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"
    win.table_model.set_items(
        [Item.model_validate({"typeLine": "Existing"})], ["Tab"], [None], ["t1"])

    win._on_stash_items("Standard", "t2", "Other Tab",
                       [Item.model_validate({"typeLine": "Chaos Orb"})], silent=True)

    assert win.table_model.rowCount() == 1
    assert win.table_model.item_at(0).typeLine == "Existing"  # unverändert

    win.worker.stop()
    win.worker.wait(5000)


def test_character_selected_fetches_items_when_not_cached(qapp, monkeypatch) -> None:
    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_character_selected(char)

    assert len(submitted) == 1
    assert submitted[0].name == "WitchOfPeter"
    assert win.table_model.rowCount() == 0  # noch nichts geladen

    win.worker.stop()
    win.worker.wait(5000)


def test_character_selected_shows_cached_items_without_fetching(qapp, monkeypatch) -> None:
    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5, "inventoryId": "MainInventory"})
    win._character_items["WitchOfPeter"] = [item]

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_character_selected(char)

    assert submitted == []  # Cache-Treffer: kein erneuter API-Call
    assert win.table_model.rowCount() == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_on_character_items_caches_and_shows_slot_as_source(qapp) -> None:
    from poe_view.ui.item_table import TAB_COL

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    weapon = Item.model_validate({"typeLine": "Sword", "frameType": 2, "inventoryId": "Weapon"})

    win._on_character_items("WitchOfPeter", [weapon], False)

    assert win._character_items["WitchOfPeter"] == [weapon]
    assert win.table_model.rowCount() == 1
    assert win.table_model.source_at(0) == "Weapon"     # Slot statt Tab-Name
    assert not win.table.isColumnHidden(TAB_COL)

    win.worker.stop()
    win.worker.wait(5000)


def test_on_character_items_ignores_late_result_for_deselected_character(qapp) -> None:
    """Analog _on_stash_items: ein spät eintreffender Job für einen inzwischen
    abgewählten Charakter darf die aktuelle Ansicht nicht überschreiben,
    soll das Ergebnis aber trotzdem cachen."""
    win = MainWindow()
    win._current_character_name = "OtherCharacter"
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})

    win._on_character_items("WitchOfPeter", [item], False)

    assert win._character_items["WitchOfPeter"] == [item]  # gecacht …
    assert win.table_model.rowCount() == 0  # … aber nicht angezeigt

    win.worker.stop()
    win.worker.wait(5000)


def test_character_refresh_bypasses_cache_and_switches_view(qapp, monkeypatch) -> None:
    """Rechtsklick "Aktualisieren" — bewusst AM Cache vorbei, analog
    _on_stash_refresh, und schaltet die Ansicht auf diesen Charakter um."""
    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")
    win._character_items["WitchOfPeter"] = [Item.model_validate({"typeLine": "Old Item"})]

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_character_refresh(char)

    assert len(submitted) == 1
    assert submitted[0].name == "WitchOfPeter"
    assert submitted[0].silent is False
    assert win._current_character_name == "WitchOfPeter"

    win.worker.stop()
    win.worker.wait(5000)


def test_maybe_auto_refresh_keeps_currently_displayed_character_live(qapp, monkeypatch) -> None:
    """der gerade angezeigte Charakter soll wie das gerade
    angezeigte Truhenfach bei jedem Tick live gehalten werden — der normale
    Stash-Sweep läuft daneben unverändert weiter."""
    win = MainWindow()
    win._current_league = "Standard"
    now = datetime.now(timezone.utc)
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    win._last_loaded["Standard"] = {"t1": (now - timedelta(days=5)).isoformat()}
    win._current_character_name = "WitchOfPeter"  # kein Fach offen (_current_stash_id bleibt None)

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    win._maybe_auto_refresh()

    character_jobs = [j for j in submitted if hasattr(j, "name")]
    stash_jobs = [j for j in submitted if hasattr(j, "stash_id")]
    assert len(character_jobs) == 1
    assert character_jobs[0].name == "WitchOfPeter"
    assert character_jobs[0].silent is True
    assert len(stash_jobs) == 1  # normaler Sweep läuft unabhängig weiter
    assert stash_jobs[0].stash_id == "t1"

    win.worker.stop()
    win.worker.wait(5000)


def test_maybe_auto_refresh_prefers_open_tab_over_character_when_both_set(qapp, monkeypatch) -> None:
    """_current_stash_id und _current_character_name schließen sich beim
    normalen Ablauf gegenseitig aus (siehe _show_items/_show_character_items) —
    sollten sie doch beide gesetzt sein, gewinnt das offene Fach, damit pro
    Tick höchstens EIN "aktuelle Ansicht"-Job rausgeht."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = []
    win._current_stash_id = "t1"
    win._current_character_name = "WitchOfPeter"

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    win._maybe_auto_refresh()

    assert len(submitted) == 1
    assert submitted[0].stash_id == "t1"

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
    """Regression: bei 391 Tabs bleibt der Zähler sonst für immer
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
    """Tabs mit 'Remove-only' im Namen nur nehmen, wenn es
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
    """sichtbarer Nachweis „X von Y Stash-Tabs aktualisiert“."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    win._update_auto_refresh_label()
    assert win._auto_refresh_label.text() == "Auto-refresh: 0 of 2 stash tabs updated"

    win._on_stash_items("Standard", "t1", "Tab 1", [], silent=True)
    assert win._auto_refresh_label.text() == "Auto-refresh: 1 of 2 stash tabs updated"

    # Manuelle (nicht-silente) Ladevorgänge zählen nicht als Auto-Refresh.
    win._on_stash_items("Standard", "t2", "Tab 2", [], silent=False)
    assert win._auto_refresh_label.text() == "Auto-refresh: 1 of 2 stash tabs updated"

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_counter_counts_tabs_already_loaded_from_a_previous_session(qapp) -> None:
    """Regression: "0 von 94" blieb dauerhaft stehen, obwohl der Sweep im
    Hintergrund longst die ältesten Tabs auffrischte — weil eine bereits
    komplett heruntergeladene Liga für JEDEN Tab schon vor dem ersten
    Silent-Refresh dieser Session ``already_loaded=True`` hatte (Datei-Cache
    einer früheren Session). Der Zähler muss trotzdem pro Session hochlaufen."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    # Simuliert einen zuvor aus dem Datei-Cache geladenen Stand: t1 ist
    # bereits Wochen alt bekannt, ohne dass diese Session je selbst geladen hätte.
    win._last_loaded["Standard"] = {"t1": "2026-01-01T00:00:00+00:00"}

    win._on_stash_items("Standard", "t1", "Tab 1", [], silent=True)

    assert win._auto_refresh_label.text() == "Auto-refresh: 1 of 2 stash tabs updated"

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
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 0.05)
    win._maybe_auto_refresh()
    assert submitted == []

    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)
    win._maybe_auto_refresh()
    assert len(submitted) == 1
    assert submitted[0].stash_id == "t1"
    assert submitted[0].silent is True

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_countdown_shows_seconds_when_not_blocked(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    win._update_auto_refresh_countdown()

    assert win._auto_refresh_blocked_reason() is None
    assert "Next auto-refresh in" in win._auto_refresh_countdown_label.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_countdown_shows_reason_when_blocked(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 0.05)

    win._update_auto_refresh_countdown()

    assert win._auto_refresh_blocked_reason() == "rate limit budget reserved for manual requests"
    assert "Auto-refresh paused" in win._auto_refresh_countdown_label.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_countdown_tick_refreshes_dashboard_from_snapshot(qapp, monkeypatch) -> None:
    """Regression: ohne dieses Polling friert das Dashboard während einer
    Auto-Refresh-Pause ein, weil ohne Request kein neuer Header mehr
    reinkommt (Rückfrage 'Policy-Statusleiste aktualisiert sich nicht')."""
    win = MainWindow()
    monkeypatch.setattr(
        win.worker.rate_limiter, "snapshot",
        lambda: ("stash-request-limit",
                 [{"current": 3, "max": 15, "window_s": 10, "locked": False}], 0.0))

    win._update_auto_refresh_countdown()

    assert "stash-request-limit" in win.dashboard._policy.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_countdown_blank_without_league(qapp) -> None:
    win = MainWindow()
    win._current_league = ""

    win._update_auto_refresh_countdown()

    assert win._auto_refresh_countdown_label.text() == ""

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_single_targets_currently_selected_stash_tab(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"
    win._current_tab_name = "Tab 1"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_refresh_mode_changed("Single")

    assert len(submitted) == 1
    assert submitted[0].stash_id == "t1"
    assert submitted[0].silent is True

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_single_targets_currently_selected_character(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._current_character_name = "WitchOfPeter"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_refresh_mode_changed("Single")

    assert len(submitted) == 1
    assert submitted[0].name == "WitchOfPeter"
    assert submitted[0].silent is True

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_single_does_not_resubmit_while_a_job_is_pending(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"
    win._current_tab_name = "Tab 1"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_refresh_mode_changed("Single")
    win._drive_refresh_mode()  # zweiter Versuch, solange der erste noch "läuft"

    assert len(submitted) == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_single_waits_for_the_steady_pace_interval(qapp, monkeypatch) -> None:
    """Nach Abschluss eines Jobs wird NICHT sofort der nächste nachgeschoben
    (das war die ursprüngliche Fehleinschätzung) — Single taktet gleichmäßig
    im Rhythmus von ``steady_pace_interval_s()``, kein Burst."""
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"
    win._current_tab_name = "Tab 1"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 20.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Single")
    assert len(submitted) == 1

    win._on_stash_items("Standard", "t1", "Tab 1", [], silent=True)
    assert len(submitted) == 1  # noch nicht fällig

    fake_now[0] += 19.0
    win._drive_refresh_mode()
    assert len(submitted) == 1  # immer noch nicht

    fake_now[0] += 1.5  # jetzt sind die vollen 20s um
    win._drive_refresh_mode()
    assert len(submitted) == 2
    assert submitted[1].stash_id == "t1"

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_pace_is_immune_to_an_interleaved_unrelated_policy(qapp) -> None:
    """Regression: real beobachtet 35s statt der erwarteten ~10s, weil ein
    dazwischengefunkter Request an einen ANDEREN Endpunkt (hier simuliert:
    die Charakterliste, ausgelöst z. B. durch den normalen Refresh-Button)
    den globalen ``rate_limiter._last_policy`` kurzzeitig überschrieb.
    Der Single-Modus muss sich stattdessen die Policy SEINES EIGENEN
    letzten Requests merken (``_refresh_mode_policy``)."""
    win = MainWindow()
    win._current_league = "Standard"
    win._current_character_name = "WitchOfPeter"

    # Eigener Request des Single-Modus: lockere Policy, ~10.3s Takt.
    win.worker.rate_limiter.update_from_headers({
        "X-Rate-Limit-Policy": "character-request-limit",
        "X-Rate-Limit-Rules": "Account",
        "X-Rate-Limit-Account": "30:300:1800",
        "X-Rate-Limit-Account-State": "0:300:0",
    })
    win._on_character_items("WitchOfPeter", [], silent=True)
    assert win._refresh_mode_policy == "character-request-limit"

    # Dazwischengefunkter, unabhängiger Request an einen anderen Endpunkt
    # (z. B. der normale "Refresh"-Button, der die Charakterliste lädt) —
    # überschreibt den GLOBALEN _last_policy mit einer viel strengeren Policy.
    win.worker.rate_limiter.update_from_headers({
        "X-Rate-Limit-Policy": "character-list-request-limit",
        "X-Rate-Limit-Rules": "Account",
        "X-Rate-Limit-Account": "5:300:1800",
        "X-Rate-Limit-Account-State": "0:300:0",
    })
    assert win.worker.rate_limiter.last_policy == "character-list-request-limit"

    # Der Single-Modus-Takt darf sich davon nicht beirren lassen.
    interval = win.worker.rate_limiter.steady_pace_interval_s(win._refresh_mode_policy)
    assert interval == pytest.approx(300 / 29, abs=0.01)

    win.worker.stop()
    win.worker.wait(5000)


def _single_mode_win_midtick(qapp, monkeypatch, headroom: float):
    """MainWindow im Single-Modus, mitten in einem laufenden 75s-Takt, mit
    einem bereits gecachten Fach "t1" — der Aufbau, bei dem ein
    Auswahlwechsel bisher bis zu einen vollen Takt lang alte Daten zeigte."""
    win = MainWindow()
    win._current_league = "Standard"
    win._items["Standard"] = {"t1": []}  # Cache-Treffer → kein regulärer Fetch
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 75.0)
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: headroom)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])
    win._refresh_mode = "single"
    win._refresh_mode_next_due = fake_now[0] + 75.0  # mitten im Takt
    return win, submitted


def test_selection_change_kicks_refresh_mode_when_headroom_allows(qapp, monkeypatch) -> None:
    """Ein bewusster Auswahlwechsel soll sofort laden statt den Rest des
    Takts (hier 75s) alte Cache-Daten zu zeigen."""
    win, submitted = _single_mode_win_midtick(qapp, monkeypatch, headroom=1.0)

    win._on_stash_selected("t1", "Tab 1")

    assert len(submitted) == 1
    assert submitted[0].stash_id == "t1"
    assert submitted[0].silent is True

    win.worker.stop()
    win.worker.wait(5000)


def test_selection_change_respects_the_pace_when_headroom_is_low(qapp, monkeypatch) -> None:
    """Gegenprobe: bei knappem Budget bleibt es beim regulären Takt — sonst
    würde schnelles Durchklicken je Klick einen Request auslösen."""
    win, submitted = _single_mode_win_midtick(qapp, monkeypatch, headroom=0.2)

    win._on_stash_selected("t1", "Tab 1")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_selection_change_is_a_no_op_in_auto_mode(qapp, monkeypatch) -> None:
    win, submitted = _single_mode_win_midtick(qapp, monkeypatch, headroom=1.0)
    win._refresh_mode = "auto"

    win._on_stash_selected("t1", "Tab 1")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_selection_change_on_cache_miss_does_not_double_fetch(qapp, monkeypatch) -> None:
    """Bei einem Cache-Miss ist über den normalen Auswahl-Pfad ohnehin schon
    ein (nicht-stiller) Fetch unterwegs — der Kick darf keinen zweiten
    Request obendrauf setzen."""
    win, submitted = _single_mode_win_midtick(qapp, monkeypatch, headroom=1.0)

    win._on_stash_selected("uncached", "Tab X")

    assert len(submitted) == 1
    assert submitted[0].silent is False

    win.worker.stop()
    win.worker.wait(5000)


def test_selection_change_kicks_refresh_mode_for_characters_too(qapp, monkeypatch) -> None:
    win, submitted = _single_mode_win_midtick(qapp, monkeypatch, headroom=1.0)
    win._character_items["WitchOfPeter"] = []  # Cache-Treffer

    win._on_character_selected(
        Character.model_validate({"name": "WitchOfPeter", "class": "Occultist",
                                  "level": 90, "league": "Standard"}))

    assert len(submitted) == 1
    assert submitted[0].name == "WitchOfPeter"
    assert submitted[0].silent is True

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_single_ignores_rate_limit_headroom(qapp, monkeypatch) -> None:
    """Single/Stash nutzen bewusst den vollen Rate-Limit-Pool — anders als
    Auto reservieren sie nichts für manuelle Klicks."""
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"
    win._current_tab_name = "Tab 1"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 0.0)

    win._on_refresh_mode_changed("Single")

    assert len(submitted) == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_stash_prefers_non_empty_and_oldest_tab(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("empty", "Empty"), _make_leaf("full", "Full")]
    now = datetime.now(timezone.utc)
    win._last_loaded["Standard"] = {
        "empty": (now - timedelta(days=10)).isoformat(),  # älter, aber leer
        "full": (now - timedelta(days=1)).isoformat(),
    }
    win._items["Standard"] = {"full": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})]}
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_refresh_mode_changed("Stash")

    assert len(submitted) == 1
    assert submitted[0].stash_id == "full"  # gefüllt schlägt älter-aber-leer

    win.worker.stop()
    win.worker.wait(5000)


def _drive_stash_mode_pick(win: MainWindow, fake_now: list[float], submitted: list) -> str:
    """Einen Pick auslösen und den realen Ladevorgang simulieren
    (``_on_stash_items``), damit Alter/Füllstand für den nächsten Pick
    korrekt fortgeschrieben werden — wie es der echte Worker täte."""
    fake_now[0] += 10.0
    win._refresh_mode_pending = False
    win._drive_refresh_mode()
    picked = submitted[-1].stash_id
    win._on_stash_items("Standard", picked, "x", win._items["Standard"].get(picked, []), silent=True)
    return picked


def test_refresh_mode_stash_covers_the_next_empty_tab_after_a_full_round(qapp, monkeypatch) -> None:
    """Peter: statt eines festen Pick-Verhältnisses (z. B. 'jeder 10.')
    soll die Häufigkeit automatisch mit der Truhengröße skalieren — nach
    einer vollständigen Runde durch alle aktuell GEFÜLLTEN Fächer hängt
    sich genau ein Check für das nächste noch leere Fach an, danach
    beginnt die Runde neu."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("full_a", "Full A"), _make_leaf("full_b", "Full B"),
                         _make_leaf("empty_c", "Empty C")]
    win._items["Standard"] = {
        "full_a": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})],
        "full_b": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})],
    }
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 10.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Stash")  # Pick #1
    first = submitted[-1].stash_id
    win._on_stash_items("Standard", first, "x", win._items["Standard"][first], silent=True)
    second = _drive_stash_mode_pick(win, fake_now, submitted)  # Pick #2

    assert {first, second} == {"full_a", "full_b"}  # Runde: beide gefüllten zuerst, Reihenfolge egal

    third = _drive_stash_mode_pick(win, fake_now, submitted)  # Pick #3: Runde fertig -> Coverage-Pick
    assert third == "empty_c"

    fourth = _drive_stash_mode_pick(win, fake_now, submitted)  # Pick #4: neue Runde beginnt normal
    assert fourth in {"full_a", "full_b"}

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_coverage_pick_walks_empty_tabs_in_order_not_by_age(qapp, monkeypatch) -> None:
    """Peter: der Coverage-Pick soll der Fächerreihenfolge nach gehen, nicht
    nach Alter — sonst würde ein weiter vorne verschobenes Fach den Effekt
    einer Neu-Sortierung im Spiel nicht spüren. Drei leere Fächer, alle
    gleich alt (nie geladen): reines Alter könnte hier nicht entscheiden,
    die Reihenfolge schon — der Rundlauf besucht alle drei nacheinander
    (verschachtelt mit dem einen gefüllten Fach, da dessen Runde nur einen
    Pick lang ist)."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("full", "Full"),
                         _make_leaf("empty_a", "Empty A"),
                         _make_leaf("empty_b", "Empty B"),
                         _make_leaf("empty_c", "Empty C")]
    win._items["Standard"] = {"full": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})]}
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 10.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Stash")  # Pick #1: "full"
    win._on_stash_items("Standard", "full", "x", win._items["Standard"]["full"], silent=True)
    picked = [_drive_stash_mode_pick(win, fake_now, submitted) for _ in range(5)]

    covered = [p for p in picked if p != "full"]
    assert covered == ["empty_a", "empty_b", "empty_c"]

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_coverage_pick_follows_a_tab_moved_forward_in_game(qapp, monkeypatch) -> None:
    """Verschiebt der Nutzer im Spiel ein Fach weiter nach vorne, ändert
    sich seine Position in ``_leaf_stashes`` beim nächsten Stash-Listen-
    Refresh entsprechend — der Rundlauf-Cursor (ein reiner Listen-Index in
    die aktuell leeren Fächer) folgt dieser neuen Reihenfolge und erreicht
    das Fach dadurch früher, als es an seiner alten (hinteren) Position
    dran gewesen wäre."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("full", "Full"),
                         _make_leaf("empty_a", "Empty A"),
                         _make_leaf("empty_b", "Empty B"),
                         _make_leaf("moved", "Moved Tab")]  # "moved" ganz hinten
    win._items["Standard"] = {"full": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})]}
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 10.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Stash")  # Pick #1: "full"
    win._on_stash_items("Standard", "full", "x", win._items["Standard"]["full"], silent=True)

    assert _drive_stash_mode_pick(win, fake_now, submitted) == "empty_a"  # 1. Coverage-Pick

    # Nutzer verschiebt "moved" im Spiel an die zweite leere Position — ohne
    # das würde es erst beim 3. statt beim 2. Coverage-Pick drankommen.
    win._leaf_stashes = [_make_leaf("full", "Full"),
                         _make_leaf("empty_a", "Empty A"),
                         _make_leaf("moved", "Moved Tab"),
                         _make_leaf("empty_b", "Empty B")]

    assert _drive_stash_mode_pick(win, fake_now, submitted) == "full"   # Runde: erst wieder das gefüllte Fach
    assert _drive_stash_mode_pick(win, fake_now, submitted) == "moved"  # früher dran dank neuer Position

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_round_state_resets_on_league_change(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_refresh_mode_changed("Stash")
    assert win._stash_mode_round_picks == 1  # t1 ist leer -> normaler Pick, hochgezählt

    win._on_league_changed("Standard SSF")

    assert win._stash_mode_round_picks == 0
    assert win._stash_mode_coverage_cursor == 0

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_stash_cycles_through_the_league_on_the_steady_pace(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 10.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Stash")
    assert len(submitted) == 1
    first = submitted[0].stash_id

    win._on_stash_items("Standard", first, "x", [], silent=True)
    assert len(submitted) == 1  # noch nicht fällig, kein Burst

    fake_now[0] += 10.0
    win._drive_refresh_mode()

    assert len(submitted) == 2
    assert submitted[1].stash_id != first  # der andere, noch ältere Tab kommt jetzt dran

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_auto_is_a_no_op_for_drive_refresh_mode(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._drive_refresh_mode()  # Modus ist per Default "auto"

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_maybe_auto_refresh_skips_entirely_while_single_mode_active(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    win._last_loaded["Standard"] = {"t1": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()}
    win._refresh_mode = "single"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    win._maybe_auto_refresh()

    assert submitted == []  # der 40s-Takt darf im Single-Modus nichts eigenes tun

    win.worker.stop()
    win.worker.wait(5000)


def test_error_resumes_refresh_mode_chain_on_the_next_due_tick(qapp, monkeypatch) -> None:
    """Ein gescheiterter Job darf die Single-/Stash-Kette nicht stillschweigend
    für den Rest der Session stoppen (der Erfolgs-Signal-Pfad wird ja
    übersprungen) — sie muss aber trotzdem den Takt einhalten, nicht sofort
    erneut versuchen."""
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"
    win._current_tab_name = "Tab 1"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 20.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])
    win._on_refresh_mode_changed("Single")
    assert len(submitted) == 1

    win._on_error("FetchStashItemsJob: boom")
    assert len(submitted) == 1  # kein sofortiger Retry

    fake_now[0] += 20.0
    win._drive_refresh_mode()
    assert len(submitted) == 2

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_countdown_label_shows_active_mode(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._refresh_mode_combo.setCurrentText("Single")

    win._update_auto_refresh_countdown()

    assert "Single" in win._auto_refresh_countdown_label.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_maybe_auto_refresh_stops_after_token_expires_mid_session(qapp, monkeypatch) -> None:
    """Regression (Rückfrage 'Automatik hat nicht hingehauen'):
    real im Log beobachtet — nach einem abgelaufenen Token lief der
    Auto-Refresh alle 40s stur mit demselben, bereits ungültigen Token
    weiter gegen die API (mehrere Minuten lang HTTP 401 in Folge), bis der
    Nutzer den Login-Button von Hand bemerkte. `login_required` muss den
    Auto-Refresh sofort stoppen; `logged_in` ihn wieder erlauben."""
    win = MainWindow()
    win._current_league = "Standard"
    now = datetime.now(timezone.utc)
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    win._last_loaded["Standard"] = {"t1": (now - timedelta(days=5)).isoformat()}

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    win._on_login_required("Token abgelaufen")
    win._maybe_auto_refresh()
    assert submitted == []  # nicht stur mit dem toten Token weiterversuchen

    win._on_logged_in("PeterM")  # submitted FetchLeaguesJob/FetchCharactersJob — nicht relevant hier
    submitted.clear()
    win._maybe_auto_refresh()
    assert len(submitted) == 1  # nach erneutem Login läuft der Auto-Refresh wieder

    win.worker.stop()
    win.worker.wait(5000)


def test_maybe_auto_refresh_also_refreshes_currently_displayed_tab(qapp, monkeypatch) -> None:
    """das gerade angezeigte Fach soll bei jedem Auto-Refresh-
    Tick ZUSÄTZLICH zum normalen Sweep-Kandidaten aktualisiert werden — auch
    wenn es frisch geladen ist (die 1-Tag-Schonfrist gilt nur für den Sweep)."""
    win = MainWindow()
    win._current_league = "Standard"
    now = datetime.now(timezone.utc)
    win._leaf_stashes = [_make_leaf("current", "Current Tab"), _make_leaf("stale", "Stale Tab")]
    win._last_loaded["Standard"] = {
        "current": now.isoformat(),  # gerade erst geladen — würde den Sweep nicht triggern
        "stale": (now - timedelta(days=5)).isoformat(),
    }
    win._current_stash_id = "current"

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    win._maybe_auto_refresh()

    assert {job.stash_id for job in submitted} == {"current", "stale"}
    assert all(job.silent is True for job in submitted)

    win.worker.stop()
    win.worker.wait(5000)


def test_maybe_auto_refresh_dedupes_when_current_tab_is_also_the_sweep_candidate(
        qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    now = datetime.now(timezone.utc)
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    win._last_loaded["Standard"] = {"t1": (now - timedelta(days=5)).isoformat()}
    win._current_stash_id = "t1"

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    win._maybe_auto_refresh()

    assert len(submitted) == 1  # nicht doppelt anfragen, wenn beide dasselbe Fach meinen
    assert submitted[0].stash_id == "t1"

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_counter_does_not_inflate_from_repeated_current_tab_refresh(qapp) -> None:
    """Regression: das wiederholte Live-Halten des angezeigten Fachs (jeder
    Tick) darf den "X von Y"-Zähler nicht über die Gesamtzahl der Fächer
    hinaustreiben — nur der ERSTE Ladevorgang eines Fachs zählt."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]

    win._on_stash_items("Standard", "t1", "Tab 1", [], silent=True)
    win._on_stash_items("Standard", "t1", "Tab 1", [], silent=True)
    win._on_stash_items("Standard", "t1", "Tab 1", [], silent=True)

    assert win._auto_refresh_counts["Standard"] == 1

    win.worker.stop()
    win.worker.wait(5000)


# --- Rohdaten-Mini-Viewer ------------------------------ #

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
    """Rechtsklick 'Rohdaten anzeigen' öffnet den Viewer und lädt (bei Cache-Treffer
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
    """Der Viewer aktualisiert sich beim Durchklicken
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


# --- Spezial-Tabs: MapStash/UniqueStash ----------------- #

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
    """Item-Anzahl in eigener Spalte — der Spezial-Tab-Eltern-
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

    # Frische Liste von der API: MapStash ohne children (wie die API sie liefert)
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
    """MapStash 'funktionierte nicht', bis manuell aktualisiert
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
    assert "0 of 1" in win._status_msg.text()

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
    """Typ default aus (Rarity steckt in der Namensfarbe),
    Mods-Spalte (Map-Modifikatoren) sichtbar."""
    from poe_view.ui.item_table import COLUMNS
    win = MainWindow()
    assert win.table.isColumnHidden(COLUMNS.index("Type"))
    assert not win.table.isColumnHidden(COLUMNS.index("Mods"))
    assert not win.table.isColumnHidden(COLUMNS.index("Name"))

    win.worker.stop()
    win.worker.wait(5000)


def test_column_toggle_persists_across_restart(qapp) -> None:
    from poe_view.ui.item_table import COLUMNS
    win = MainWindow()
    win._toggle_column("Type")   # einblenden
    win._toggle_column("Mods")  # ausblenden
    assert not win.table.isColumnHidden(COLUMNS.index("Type"))
    assert win.table.isColumnHidden(COLUMNS.index("Mods"))
    win.worker.stop()
    win.worker.wait(5000)

    win2 = MainWindow()  # "Neustart": liest ui-settings.ini (im Test: tmp_path)
    assert not win2.table.isColumnHidden(COLUMNS.index("Type"))
    assert win2.table.isColumnHidden(COLUMNS.index("Mods"))

    win2.worker.stop()
    win2.worker.wait(5000)


def test_tab_column_auto_hidden_for_single_tab_shown_for_aggregate(qapp) -> None:
    """Im Einzelfach ist die Herkunft redundant, im Aggregat
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
    assert "1 items from 1 of 2" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def _unique_child(child_id: str, parent_id: str = "u1") -> StashTab:
    """Namenloses Unique-Fach in der echten Struktur (nur metadata.items)."""
    return StashTab.model_validate({"id": child_id, "name": "", "parent": parent_id,
                                    "type": "UniqueStash", "metadata": {"items": 2}})


def test_unique_child_gets_category_name_after_item_load(qapp) -> None:
    """"über die Kategorie gehen, z. B. Two Handed Axe, Ring, Flask"."""
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

# --- Fächerübergreifende Suche + Spalten-Filter ---------- #

def test_typing_in_search_switches_to_league_wide_view(qapp, monkeypatch) -> None:
    """Tippen sucht über alle geladenen Fächer der Liga; Leeren des Felds
    führt zurück zum vorher gewählten Fach — alles ohne API-Call."""
    from PySide6.QtCore import Qt
    from poe_view.ui.item_table import TAB_COL
    win = MainWindow()
    win._current_league = "Standard"
    t1, t2 = _make_leaf("t1", "Currency 1"), _make_leaf("t2", "Essence")
    win._stash_trees["Standard"] = [t1, t2]
    win._leaf_stashes = [t1, t2]
    win._items["Standard"] = {
        "t1": [Item.model_validate({"typeLine": "Chaos Orb"})],
        "t2": [Item.model_validate({"typeLine": "Deafening Essence of Greed"})],
    }
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    win._show_items("t1", win._items["Standard"]["t1"], "Currency 1")
    assert win.table_model.rowCount() == 1

    win._filter_edit.setText("essence")          # tippen → liga-weite Ansicht
    assert win.table_model.rowCount() == 2       # Model hält alle Items der Liga
    assert win.proxy.rowCount() == 1             # Filter zeigt nur den Treffer
    assert win.proxy.data(win.proxy.index(0, 3),
                          Qt.ItemDataRole.DisplayRole) == "Deafening Essence of Greed"
    assert not win.table.isColumnHidden(TAB_COL)  # Herkunfts-Fach ist Teil der Antwort

    win._filter_edit.setText("")                 # leeren → zurück zum Fach
    assert win.table_model.rowCount() == 1
    assert win.table_model.source_at(0) == "Currency 1"
    assert win.table.isColumnHidden(TAB_COL)
    assert submitted == []                       # alles aus dem Cache

    win.worker.stop()
    win.worker.wait(5000)


def test_wildcard_search_also_includes_character_inventory_items(qapp) -> None:
    """"Bei der '*'-Suche sollte auch über sämtliche
    Inventar-Items gesucht werden" — Charaktere DIESER Liga zählen mit."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Currency 1")]
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb"})]}
    win._all_characters = [
        make_char("WitchOfPeter", "Standard"),
        make_char("OtherLeagueChar", "Hardcore"),  # andere Liga — darf nicht mitzählen
    ]
    win._character_items = {
        "WitchOfPeter": [Item.model_validate(
            {"typeLine": "Kaom's Heart", "frameType": 3, "inventoryId": "BodyArmour"})],
        "OtherLeagueChar": [Item.model_validate({"typeLine": "Should Not Appear"})],
    }

    win._filter_edit.setText("*")

    assert win.table_model.rowCount() == 2  # Stash-Item + Charakter-Item, nicht das der anderen Liga
    type_lines = {win.table_model.item_at(i).typeLine for i in range(2)}
    assert type_lines == {"Chaos Orb", "Kaom's Heart"}
    sources = {win.table_model.source_at(i) for i in range(2)}
    assert sources == {"Currency 1", "WitchOfPeter: BodyArmour"}

    win.worker.stop()
    win.worker.wait(5000)


def test_tree_click_during_search_shows_single_tab(qapp, monkeypatch) -> None:
    """Baum-Klick während aktiver Suche beendet die liga-weite Ansicht."""
    win = MainWindow()
    win._current_league = "Standard"
    t1 = _make_leaf("t1", "Currency 1")
    win._stash_trees["Standard"] = [t1]
    win._leaf_stashes = [t1]
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb"})]}
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._filter_edit.setText("chaos")
    assert win._search_all_active

    win._on_stash_selected("t1", "Currency 1")
    assert not win._search_all_active
    assert win.table.isColumnHidden(1)  # TAB_COL: Einzelfach-Ansicht

    win.worker.stop()
    win.worker.wait(5000)


def _weapon(name: str, req_level: str) -> Item:
    return Item.model_validate({"typeLine": name, "requirements": [
        {"name": "Level", "values": [[req_level, 0]]}]})


def test_apply_column_filter_updates_status_and_header(qapp) -> None:
    """Excel-artiger Spalten-Filter ("iLvl <45", "20% Quality"): Statuszeile
    nennt Treffer, Header trägt 🔍, Entfernen räumt beides wieder auf."""
    from PySide6.QtCore import Qt
    from poe_view.ui.item_table import COLUMNS
    win = MainWindow()
    win.table_model.set_items([_weapon("A", "56"), _weapon("B", "70")])
    req_col = COLUMNS.index("Req.Lvl")

    win._apply_column_filter(req_col, "<60")
    assert win.proxy.rowCount() == 1
    assert "1 of 2" in win._status_msg.text()
    assert "Req.Lvl <60" in win._status_msg.text()
    assert win.proxy.headerData(req_col, Qt.Orientation.Horizontal,
                                Qt.ItemDataRole.DisplayRole) == "Req.Lvl 🔍"

    win._apply_column_filter(req_col, "")
    assert win.proxy.rowCount() == 2
    assert "removed" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_clear_column_filters_resets_all(qapp) -> None:
    from poe_view.ui.item_table import COLUMNS
    win = MainWindow()
    win.table_model.set_items([_weapon("A", "56"), _weapon("B", "70")])
    win._apply_column_filter(COLUMNS.index("Req.Lvl"), ">=60")
    win._apply_column_filter(COLUMNS.index("Name"), "A")
    assert win.proxy.rowCount() == 0

    win._clear_column_filters()
    assert win.proxy.rowCount() == 2
    assert win.proxy.filtered_columns() == set()

    win.worker.stop()
    win.worker.wait(5000)


def test_search_field_has_clear_button(qapp) -> None:
    """kleines "x" am rechten Rand zum Leeren des Suchfelds
    — Qt bringt das nativ mit (QLineEdit.setClearButtonEnabled)."""
    win = MainWindow()
    assert win._filter_edit.isClearButtonEnabled()

    win.worker.stop()
    win.worker.wait(5000)


def test_asterisk_search_shows_and_exports_entire_league(qapp, monkeypatch) -> None:
    """"*" im Suchfeld zeigt den gesamten (bereits geladenen) Liga-Inhalt —
    "damit ich den gesamten Inhalt exportieren kann"."""
    win = MainWindow()
    win._current_league = "Standard"
    t1, t2 = _make_leaf("t1", "Currency 1"), _make_leaf("t2", "Essence")
    win._stash_trees["Standard"] = [t1, t2]
    win._leaf_stashes = [t1, t2]
    win._items["Standard"] = {
        "t1": [Item.model_validate({"typeLine": "Chaos Orb"})],
        "t2": [Item.model_validate({"typeLine": "Deafening Essence of Greed"})],
    }
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._show_items("t1", win._items["Standard"]["t1"], "Currency 1")

    win._filter_edit.setText("*")

    assert win.proxy.rowCount() == 2  # alles, nicht nur der zuvor gewählte Tab
    rows = win._visible_rows()  # das nutzt der CSV-Export
    assert {name for _, item in rows for name in [item.display_name]} == \
        {"Chaos Orb", "Deafening Essence of Greed"}

    win.worker.stop()
    win.worker.wait(5000)


# --- Offline-Modus (GGG-Wartung am Patchday) -------------- #

def test_populate_cached_leagues_works_without_network(qapp, monkeypatch) -> None:
    """Ligen-Dropdown aus dem Cache befüllen, unabhängig vom Netzwerk — sonst
    wäre die App bei GGG-Wartung komplett leer, obwohl der Cache alles hat."""
    win = MainWindow()
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    t1 = _make_leaf("t1", "Currency 1")
    win._stash_trees = {"Standard": [t1]}
    win._items = {"Standard": {"t1": [Item.model_validate({"typeLine": "Chaos Orb"})]}}

    win._populate_cached_leagues()

    assert [win._league_combo.itemText(i) for i in range(win._league_combo.count())] == ["Standard"]
    assert win._current_league == "Standard"
    assert [s.id for s in win._leaf_stashes] == ["t1"]

    win.worker.stop()
    win.worker.wait(5000)


def test_populate_cached_leagues_noop_without_cache(qapp) -> None:
    win = MainWindow()  # isolierter, leerer Cache (conftest)
    assert win._league_combo.count() == 0
    assert win._current_league == ""

    win.worker.stop()
    win.worker.wait(5000)


def test_offline_changed_shows_banner_and_marks_tree(qapp) -> None:
    from poe_view.ui.stash_tree import _COL_STATUS
    win = MainWindow()
    win._current_league = "Standard"
    t1 = _make_leaf("t1", "Currency 1")
    win._stash_trees["Standard"] = [t1]
    win._last_loaded["Standard"] = {"t1": datetime.now(timezone.utc).isoformat()}
    win._activate_stash_tree([t1])

    win._on_offline_changed(True)
    assert "Offline" in win._offline_label.text()
    button = win.tree.itemWidget(win.tree._stash_nodes["t1"], _COL_STATUS)
    assert button.text().startswith("📴")

    win._on_offline_changed(False)
    assert win._offline_label.text() == ""
    button = win.tree.itemWidget(win.tree._stash_nodes["t1"], _COL_STATUS)
    assert button.text().startswith("⟳")

    win.worker.stop()
    win.worker.wait(5000)


# --- Typ-Filter-Checkboxen ------------------------------- #

def test_type_checkboxes_exist_checked_by_default(qapp) -> None:
    from poe_view.ui.theme import OTHER_TYPE
    win = MainWindow()
    assert set(win._type_checks) == {0, 1, 2, 3, 4, 5, 6, OTHER_TYPE}
    assert all(box.isChecked() for box in win._type_checks.values())

    win.worker.stop()
    win.worker.wait(5000)


def test_toggling_type_checkbox_filters_table(qapp) -> None:
    win = MainWindow()
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "frameType": 0}),
        Item.model_validate({"typeLine": "Headhunter", "frameType": 3}),
    ])
    assert win.proxy.rowCount() == 2

    win._type_checks[3].setChecked(False)
    assert win.proxy.rowCount() == 1

    win._type_checks[3].setChecked(True)
    assert win.proxy.rowCount() == 2

    win.worker.stop()
    win.worker.wait(5000)


def test_other_type_checkbox_hides_relic_and_unknown(qapp) -> None:
    from poe_view.ui.theme import OTHER_TYPE
    win = MainWindow()
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5}),
        Item.model_validate({"typeLine": "Relic-Item", "frameType": 9}),
    ])
    assert win.proxy.rowCount() == 2

    win._type_checks[OTHER_TYPE].setChecked(False)
    assert win.proxy.rowCount() == 1
    assert win.proxy.data(win.proxy.index(0, 3)) == "Chaos Orb"

    win.worker.stop()
    win.worker.wait(5000)


# --- Liga-Dropdown: gültige zuerst, abgelaufene abgetrennt #

def test_league_with_content_sorted_before_empty_league(qapp, monkeypatch) -> None:
    """"Hardcore wird zuerst angezeigt, obwohl ich dort
    keinen Spielstand habe — alle Felder leer." Ligen mit Charakteren/Items
    sollen vor leeren Ligen stehen, unabhängig von der API-Reihenfolge."""
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._stash_trees = {
        "Hardcore": [_make_leaf("h1", "Currency 1")],
        "Standard": [_make_leaf("s1", "Currency 1")],
    }
    win._all_characters = [make_char("Held", "Standard")]
    win._items = {"Standard": {"s1": [Item.model_validate({"typeLine": "Chaos Orb"})]}}

    win._on_leagues(["Hardcore", "Standard"])  # API liefert Hardcore zuerst

    order = [win._league_combo.itemText(i) for i in range(win._league_combo.count())]
    assert order == ["Standard", "Hardcore"]
    assert win._league_combo.currentText() == "Standard"

    win.worker.stop()
    win.worker.wait(5000)


def test_expired_cache_only_league_appended_below_separator(qapp, monkeypatch) -> None:
    """Ligen, die nicht mehr in der Live-Liste stehen, aber noch im Cache
    sind (abgelaufen/rotiert), kommen unten, getrennt durch einen Strich."""
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._stash_trees = {
        "Standard": [_make_leaf("s1", "Currency 1")],
        "Legacy League": [_make_leaf("l1", "Currency 1")],
    }

    win._on_leagues(["Standard"])  # "Legacy League" ist nicht mehr live

    order = [win._league_combo.itemText(i) for i in range(win._league_combo.count())]
    sep = order.index(MainWindow._ARCHIVED_HEADER)
    assert order[:sep] == ["Standard"]
    assert order[sep + 1:] == ["Legacy League"]
    assert win._league_combo.currentText() == "Standard"
    # Header ist eine reine Überschrift, nicht anwählbar (
    # explizit als "Offline-Liga" erkennbar, nicht nur positionell getrennt).
    header_item = win._league_combo.model().item(sep)
    assert not header_item.isEnabled()

    win.worker.stop()
    win.worker.wait(5000)


def test_no_separator_when_no_expired_leagues(qapp, monkeypatch) -> None:
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._stash_trees = {"Standard": [_make_leaf("s1", "Currency 1")]}

    win._on_leagues(["Standard"])

    order = [win._league_combo.itemText(i) for i in range(win._league_combo.count())]
    assert order == ["Standard"]  # kein "" (Trennstrich) ohne abgelaufene Ligen

    win.worker.stop()
    win.worker.wait(5000)


def test_live_update_preserves_current_selection(qapp, monkeypatch) -> None:
    """Ein Liga-Listen-Refresh darf den Nutzer nicht aus der gerade
    betrachteten Liga werfen, auch wenn sich die Sortierung ändert."""
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._stash_trees = {
        "Hardcore": [_make_leaf("h1", "Currency 1")],
        "Standard": [_make_leaf("s1", "Currency 1")],
    }
    win._on_leagues(["Hardcore", "Standard"])
    win._league_combo.setCurrentText("Hardcore")
    assert win._current_league == "Hardcore"

    win._all_characters = [make_char("Held", "Standard")]  # jetzt hat Standard Inhalt
    win._on_leagues(["Hardcore", "Standard"])  # erneuter Refresh

    assert win._league_combo.currentText() == "Hardcore"  # Auswahl bleibt erhalten
    assert win._current_league == "Hardcore"

    win.worker.stop()
    win.worker.wait(5000)


# --- Position-Spalte: Tab-Index + Koordinaten ------------ #

def test_position_column_uses_list_order_not_stash_index(qapp, monkeypatch) -> None:
    """"der Index der Truhenfächer bezieht sich auf die
    Position der jeweiligen (vergangenen) Liga" — Fächer wandern beim
    Liga-Ende nach Standard und BEHALTEN ihren alten Index, mehrere Fächer
    tragen dort also denselben ``index``. Die Position-Spalte muss daher
    aus der tatsächlichen Reihenfolge der aktuellen API-Antwort kommen
    (``_leaf_stashes``), nicht aus ``StashTab.index``. Test simuliert genau
    das: beide "Heist"-Tabs tragen index=1 (aus zwei toten Ligen migriert)."""
    from poe_view.ui.item_table import POSITION_COL
    win = MainWindow()
    win._current_league = "Standard"
    heist1 = StashTab.model_validate({"id": "h1", "name": "Heist", "type": "NormalStash",
                                      "index": 1, "metadata": {}})
    heist2 = StashTab.model_validate({"id": "h2", "name": "Heist", "type": "NormalStash",
                                      "index": 1, "metadata": {}})  # gleicher index wie h1!
    win._stash_trees["Standard"] = [heist1, heist2]
    win._leaf_stashes = [heist1, heist2]  # Reihenfolge der aktuellen API-Antwort
    win._items["Standard"] = {
        "h1": [Item.model_validate({"typeLine": "Gold Locket", "x": 1, "y": 1})],
        "h2": [Item.model_validate({"typeLine": "Gold Locket", "x": 5, "y": 3})],
    }
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._show_aggregate()

    positions = {win.table_model.display_text(r, POSITION_COL)
                for r in range(win.table_model.rowCount())}
    assert positions == {"#1 (1, 1)", "#2 (5, 3)"}  # eindeutig trotz identischem index

    win.worker.stop()
    win.worker.wait(5000)


def test_single_tab_view_shows_position_column(qapp) -> None:
    """Auch im Einzelfach kommt die Tab-Nr. aus der Listen-Position
    (``_leaf_stashes``), nicht aus ``StashTab.index`` (hier bewusst auf
    einen irreführenden Wert gesetzt, um das zu beweisen)."""
    win = MainWindow()
    win._current_league = "Standard"
    other = StashTab.model_validate({"id": "other", "name": "Currency", "type": "CurrencyStash",
                                     "index": 0, "metadata": {}})
    tab = StashTab.model_validate({"id": "t1", "name": "Heist", "type": "NormalStash",
                                   "index": 99, "metadata": {}})  # irreführender index
    win._stash_trees["Standard"] = [other, tab]
    win._leaf_stashes = [other, tab]  # tab ist der ZWEITE Eintrag -> Position 2

    win._show_items("t1", [Item.model_validate({"typeLine": "Chaos Orb", "x": 2, "y": 9})],
                    "Heist")

    from poe_view.ui.item_table import POSITION_COL
    assert win.table_model.display_text(0, POSITION_COL) == "#2 (2, 9)"

    win.worker.stop()
    win.worker.wait(5000)


# --- Toolbar darf nicht versehentlich ausblendbar sein --- #

def test_toolbar_context_menu_disabled(qapp) -> None:
    """Qt bietet per Default ein Rechtsklick-Menü über der Toolbar an, mit
    dem sie sich komplett ausblenden lässt — ohne Menüleiste gäbe es dann
    keinen Weg zurück (Login, Refresh, Liga-Wahl, Suche wären weg)."""
    from PySide6.QtCore import Qt
    win = MainWindow()
    assert win.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu

    win.worker.stop()
    win.worker.wait(5000)


# --- Baum-Hervorhebung bei Item-Auswahl ------------------ #

def test_row_selection_highlights_tab_without_changing_search(qapp, monkeypatch) -> None:
    """bei "*" (alles anzeigen) soll ein Klick auf ein Item
    das Herkunfts-Fach im Baum zeigen, DARF ABER die Suche nicht verändern."""
    win = MainWindow()
    win._current_league = "Standard"
    t1, t2 = _make_leaf("t1", "Currency 1"), _make_leaf("t2", "Essence")
    win._stash_trees["Standard"] = [t1, t2]
    win._leaf_stashes = [t1, t2]
    win._items["Standard"] = {
        "t1": [Item.model_validate({"typeLine": "Chaos Orb"})],
        "t2": [Item.model_validate({"typeLine": "Deafening Essence of Greed"})],
    }
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    monkeypatch.setattr(win.tree, "highlight_stash", lambda sid: highlighted.append(sid))
    highlighted = []

    win._filter_edit.setText("*")
    assert win.proxy.rowCount() == 2

    # Zeile für "t2" (Essence) auswählen — _on_row_selected direkt aufgerufen,
    # genau wie es sonst currentRowChanged täte (spart Selection-Flag-Kram).
    row = next(r for r in range(win.proxy.rowCount())
              if win.table_model.stash_id_at(win.proxy.mapToSource(win.proxy.index(r, 0)).row())
              == "t2")
    win._on_row_selected(win.proxy.index(row, 0), win.proxy.index(0, 0))

    assert highlighted == ["t2"]
    assert win.proxy.rowCount() == 2          # Suche unverändert
    assert win._filter_edit.text() == "*"     # Suchfeld unverändert
    assert win._search_all_active             # weiterhin in der Suchansicht

    win.worker.stop()
    win.worker.wait(5000)


def test_single_tab_selection_highlights_its_own_tab(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    tab = _make_leaf("t1", "Currency 1")
    win._stash_trees["Standard"] = [tab]
    win._leaf_stashes = [tab]
    win._activate_stash_tree([tab])

    highlighted = []
    win.tree.highlight_stash = lambda sid: highlighted.append(sid)
    win._show_items("t1", [Item.model_validate({"typeLine": "Chaos Orb"})], "Currency 1")
    win._on_row_selected(win.proxy.index(0, 0), win.proxy.index(0, 0))

    assert highlighted == ["t1"]

    win.worker.stop()
    win.worker.wait(5000)


# --- Archivierte (beendete) Ligen: kein Online-Zugriff mehr #

def test_current_league_is_archived_unknown_before_first_live_response(qapp) -> None:
    """Vor der ersten /account/leagues-Antwort (Offline-Start, §4.12) gilt
    NICHTS als archiviert — sonst würde ein reiner Cache-Start jede Liga
    fälschlich als "beendet" markieren."""
    win = MainWindow()
    win._current_league = "Standard"
    assert win._live_leagues is None
    assert win._current_league_is_archived() is False

    win.worker.stop()
    win.worker.wait(5000)


def test_current_league_is_archived_after_league_rotation(qapp) -> None:
    win = MainWindow()
    win._current_league = "Legacy League"
    win._live_leagues = {"Standard", "Hardcore", "NewLeague"}

    assert win._current_league_is_archived() is True

    win._current_league = "Standard"
    assert win._current_league_is_archived() is False

    win.worker.stop()
    win.worker.wait(5000)


def test_league_changed_skips_network_for_archived_league(qapp, monkeypatch) -> None:
    """Liga-Rotation — für eine beendete Liga darf kein
    FetchStashListJob mehr abgeschickt werden (kein Online-Zugriff mehr)."""
    win = MainWindow()
    win._live_leagues = {"NewLeague"}  # "Legacy League" ist raus
    win._stash_trees["Legacy League"] = [_make_leaf("l1", "Currency 1")]
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_league_changed("Legacy League")

    assert submitted == []
    assert "ended" in win._status_msg.text()
    assert win._current_league == "Legacy League"  # trotzdem aktiviert (zeigt Cache)

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_selected_archived_league_cache_hit_still_works(qapp, monkeypatch) -> None:
    """Bereits geladene Items einer beendeten Liga bleiben normal nutzbar —
    nur ein erneuter Netzwerk-Zugriff ist ausgeschlossen."""
    win = MainWindow()
    win._current_league = "Legacy League"
    win._live_leagues = {"Standard"}
    tab = _make_leaf("t1", "Currency 1")
    win._stash_trees["Legacy League"] = [tab]
    win._items["Legacy League"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb"})]}
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_stash_selected("t1", "Currency 1")

    assert submitted == []
    assert win.table_model.rowCount() == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_selected_archived_league_cache_miss_shows_message_no_fetch(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Legacy League"
    win._live_leagues = {"Standard"}
    win._stash_trees["Legacy League"] = [_make_leaf("t1", "Currency 1")]
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_stash_selected("t1", "Currency 1")

    assert submitted == []
    assert "ended" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_refresh_archived_league_no_fetch(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Legacy League"
    win._live_leagues = {"Standard"}
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_stash_refresh("t1", "Currency 1")

    assert submitted == []
    assert "ended" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_special_tab_undiscovered_children_archived_league_no_fetch(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Legacy League"
    win._live_leagues = {"Standard"}
    map_stash = StashTab.model_validate({"id": "m1", "name": "M", "type": "MapStash",
                                         "metadata": {}})
    win._stash_trees["Legacy League"] = [map_stash]
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_stash_selected("m1", "M")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_load_all_items_archived_league_shows_aggregate_without_fetch(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Legacy League"
    win._live_leagues = {"Standard"}
    t1 = _make_leaf("t1", "Currency 1")
    win._stash_trees["Legacy League"] = [t1]
    win._leaf_stashes = [t1]
    win._items["Legacy League"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb"})]}
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._load_all_items()

    assert submitted == []
    assert win.table_model.rowCount() == 1  # Aggregat trotzdem gezeigt
    assert "ended" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_skips_archived_league(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Legacy League"
    win._live_leagues = {"Standard"}
    win._leaf_stashes = [_make_leaf("t1", "Currency 1")]  # wäre sonst ein Kandidat
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._maybe_auto_refresh()

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_update_tree_offline_display_combines_global_and_archived(qapp) -> None:
    """📴 erscheint auch dann, wenn GGG global erreichbar ist, aber die
    GERADE angezeigte Liga archiviert ist — und umgekehrt auch bei
    globalem Offline-Zustand für eine ganz normale, gültige Liga."""
    win = MainWindow()
    win._current_league = "Legacy League"
    win._live_leagues = {"Standard"}
    tab = _make_leaf("t1", "Currency 1")
    win._stash_trees["Legacy League"] = [tab]
    win._last_loaded["Legacy League"] = {"t1": datetime.now(timezone.utc).isoformat()}
    win._activate_stash_tree([tab])

    assert win._offline is False  # GGG selbst ist erreichbar
    win._update_tree_offline_display()

    assert win.tree._offline is True  # trotzdem 📴, weil die Liga archiviert ist

    win.worker.stop()
    win.worker.wait(5000)


def test_manual_refresh_skips_stash_list_for_archived_league(qapp, monkeypatch) -> None:
    """"⟳ Aktualisieren"-Button: Charaktere bleiben liga-unabhängig sinnvoll,
    ein Stash-Listen-Refresh für eine beendete Liga würde nur scheitern."""
    win = MainWindow()
    win._current_league = "Legacy League"
    win._live_leagues = {"Standard"}
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._refresh()

    from poe_view.services.api_worker import FetchCharactersJob, FetchStashListJob
    assert not any(isinstance(j, FetchStashListJob) for j in submitted)
    assert any(isinstance(j, FetchCharactersJob) for j in submitted)

    win.worker.stop()
    win.worker.wait(5000)
