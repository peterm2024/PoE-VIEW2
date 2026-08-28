"""Tests für MainWindow-Hilfsmethoden: rekursives Einsammeln der Nicht-Ordner-Tabs
('Alle Tabs laden'/Aggregat), Liga-Filterung der Charaktere und den
CSV-Dateiname-Vorschlag (Filtertext bzw. Tab-/Aggregat-Name).
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QMenu

from poe_view.api.models import Character, Item, StashTab
from poe_view.api.ninja import PriceIndex
from poe_view.services import mod_knowledge, price_cache
from poe_view.services.api_worker import (FetchModKnowledgeJob, FetchPricesJob,
                                          FetchStashListJob, LOGIN_EXPIRED,
                                          LOGIN_NO_TOKEN)
from poe_view.services.poe2_probe import Probe, ProbeCall
from poe_view.ui import external_tools, mod_bar
from poe_view.ui.item_table import CONFIGURABLE_COLUMNS
from poe_view.ui.main_window import MainWindow, _stable_item_dump, _XpWatch

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


_TIMESTAMP_RE = r"\d{4}-\d{2}-\d{2}_\d{4}"


def test_default_export_filename_prefers_filter_text(qapp) -> None:
    win = MainWindow()
    win._current_tab_name = "Currency 1"
    win._filter_edit.setText("Chaos Orb")
    assert re.fullmatch(rf"poe-view2-Chaos-Orb-7items-{_TIMESTAMP_RE}\.csv",
                        win._default_export_filename(7))

    win.worker.stop()
    win.worker.wait(5000)


def test_default_export_filename_falls_back_to_tab_name(qapp) -> None:
    win = MainWindow()
    win._current_tab_name = "Currency 1"
    assert re.fullmatch(rf"poe-view2-Currency-1-12items-{_TIMESTAMP_RE}\.csv",
                        win._default_export_filename(12))

    win.worker.stop()
    win.worker.wait(5000)


def test_default_export_filename_includes_league(qapp) -> None:
    win = MainWindow()
    win._current_league = "Settlers"
    win._current_tab_name = "Currency 1"
    assert re.fullmatch(rf"poe-view2-Settlers-Currency-1-3items-{_TIMESTAMP_RE}\.csv",
                        win._default_export_filename(3))

    win._filter_edit.setText("Chaos Orb")
    assert re.fullmatch(rf"poe-view2-Settlers-Chaos-Orb-3items-{_TIMESTAMP_RE}\.csv",
                        win._default_export_filename(3))

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


def test_the_cache_is_backed_up_at_startup(qapp, monkeypatch, tmp_path) -> None:
    """Peter, 2026-08-06, nach dem Schaden aus FALLSTRICKE #66. Der
    Zeitpunkt ist der Kern der Sache: Beim Start traegt die Datei noch
    garantiert den Stand der VORIGEN Sitzung — was diese hier anrichtet,
    ist danach nicht mehr zu sichern. Deshalb prueft der Test nicht nur
    DASS gesichert wird, sondern dass es VOR dem ersten Schreibvorgang
    geschieht."""
    from poe_view.services import cache_backup, cache_writer, data_cache

    # Ein Bestand aus einer frueheren Sitzung, damit der Start eine
    # Kontokennung findet — ohne die gaebe es keine Cache-Datei.
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(data_cache, "_CACHE_FILE", cache_path)
    data = data_cache.CachedData()
    data.account_name = "Someone#1234"
    data.characters = [make_char("A", "Standard")]
    data_cache.save(data)

    ereignisse: list[str] = []
    monkeypatch.setattr(cache_backup, "run",
                        lambda path, now=None: ereignisse.append(f"backup:{path.name}"))
    # Beobachtet wird die ANFORDERUNG, nicht der Schreibvorgang selbst:
    # Der laeuft seit 2026-08-12 in einem eigenen Thread, seine Lage in
    # dieser Liste waere also nicht mehr aussagekraeftig. Fuer die Frage
    # des Tests ("wurde vor dem ersten Schreiben gesichert?") ist der
    # Zeitpunkt der Anforderung ohnehin der richtige.
    monkeypatch.setattr(cache_writer.CacheWriter, "request",
                        lambda self, snapshot: ereignisse.append("save"))

    win = MainWindow()
    assert win._account_name == "Someone#1234"
    win._persist_cache()

    assert ereignisse and ereignisse[0] == "backup:data-cache-Someone#1234.json"
    assert "save" in ereignisse
    assert ereignisse.index("save") > 0  # gesichert wurde zuerst

    win.worker.stop()
    win.worker.wait(5000)


def test_the_startup_backup_never_writes_into_the_real_data_folder(
        qapp, monkeypatch, tmp_path) -> None:
    """Regression: ``BACKUP_DIR`` wurde beim Import ausgerechnet und zeigte
    danach fuer immer auf den echten Datenordner. Tests, die
    ``config.APP_DATA_DIR`` umbiegen, legten ihre Cache-Datei brav im
    Wegwerf-Ordner ab — die Sicherung davon landete in Peters echtem
    ``backups``-Verzeichnis (sechs Fremdkoerper, am 2026-08-07 dort
    gefunden)."""
    from poe_view import config
    from poe_view.services import cache_backup, data_cache

    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(data_cache, "_CACHE_FILE", tmp_path / "cache.json")
    data = data_cache.CachedData()
    data.account_name = "Someone#1234"
    data.characters = [make_char("A", "Standard")]
    data_cache.save(data)

    win = MainWindow()
    win._backup_cached_data()

    assert cache_backup.directory().parent == tmp_path
    win.worker.stop()
    win.worker.wait(5000)


def test_no_backup_before_the_first_login(qapp, monkeypatch) -> None:
    """Ohne Kontokennung gibt es keine kontospezifische Cache-Datei — und
    nichts zu sichern."""
    from poe_view.services import cache_backup

    aufrufe = []
    monkeypatch.setattr(cache_backup, "run",
                        lambda path, now=None: aufrufe.append(path))

    win = MainWindow()
    win._account_name = ""
    win._backup_cached_data()

    assert aufrufe == []
    win.worker.stop()
    win.worker.wait(5000)


def test_a_failing_backup_does_not_prevent_the_program_from_starting(
        qapp, monkeypatch) -> None:
    """Ein misslungenes Backup ist aergerlich; ein Programm, das deswegen
    nicht mehr startet, ist ein Totalausfall. ``cache_backup`` faengt
    ``OSError`` selbst ab — hier geht es um alles andere, was aus einem
    Dateizugriff kommen kann (Rechteprobleme, kaputte Pfade, ein
    Programmfehler im Backup selbst)."""
    from poe_view.services import cache_backup

    def boom(*_args, **_kwargs):
        raise RuntimeError("irgendwas ganz anderes")

    monkeypatch.setattr(cache_backup, "run", boom)

    win = MainWindow()          # darf nicht werfen
    win._account_name = "Someone#1234"
    win._backup_cached_data()   # auch direkt aufgerufen nicht

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


# --- Charakter-Refresh-Diff: geändert türkis, verschwunden grau/durchgestrichen
# (Peter 2026-08-01) ------------------------------------------------------- #

def test_diff_returns_nothing_when_there_is_no_previous_state(qapp) -> None:
    """Erstes Anzeigen eines Charakters (kein vorheriger Ladevorgang zum
    Vergleichen) — sonst wäre beim allerersten Öffnen sofort alles "neu"."""
    item = Item.model_validate({"id": "1", "typeLine": "Chaos Orb"})
    added_ids, changed_ids, removed_items = MainWindow._diff_character_items(None, [item])
    assert added_ids == frozenset()
    assert changed_ids == frozenset()
    assert removed_items == []


def test_diff_marks_a_brand_new_item_as_added_not_changed(qapp) -> None:
    """Ein Item mit einer vorher nie gesehenen id ist ein echter Neuzugang
    (``added_ids``), NICHT ``changed_ids`` — die Unterscheidung braucht der
    Charakter-Item-Verlauf (Peter, 2026-08-02), der nur echte Neuzugänge
    protokollieren soll, keine bloßen Werteänderungen."""
    old = Item.model_validate({"id": "1", "typeLine": "Chaos Orb"})
    new = Item.model_validate({"id": "2", "typeLine": "Exalted Orb"})
    added_ids, changed_ids, removed_items = MainWindow._diff_character_items([old], [old, new])
    assert added_ids == frozenset({"2"})
    assert changed_ids == frozenset()
    assert removed_items == []


def test_diff_marks_a_modified_item_as_changed_not_added(qapp) -> None:
    """Gleiche id, aber z. B. Stack-Größe hat sich geändert — das ist
    ``changed_ids``, nicht ``added_ids``."""
    old = Item.model_validate({"id": "1", "typeLine": "Chaos Orb", "stackSize": 5})
    new = Item.model_validate({"id": "1", "typeLine": "Chaos Orb", "stackSize": 9})
    added_ids, changed_ids, removed_items = MainWindow._diff_character_items([old], [new])
    assert added_ids == frozenset()
    assert changed_ids == frozenset({"1"})
    assert removed_items == []


def test_diff_leaves_an_unchanged_item_alone(qapp) -> None:
    item = Item.model_validate({"id": "1", "typeLine": "Chaos Orb", "stackSize": 5})
    added_ids, changed_ids, removed_items = MainWindow._diff_character_items([item], [item])
    assert added_ids == frozenset()
    assert changed_ids == frozenset()
    assert removed_items == []


def test_diff_reports_a_disappeared_item(qapp) -> None:
    gone = Item.model_validate({"id": "1", "typeLine": "Chaos Orb"})
    added_ids, changed_ids, removed_items = MainWindow._diff_character_items([gone], [])
    assert added_ids == frozenset()
    assert changed_ids == frozenset()
    assert removed_items == [gone]


def test_diff_ignores_items_without_an_id(qapp) -> None:
    """Ohne stabile Kennung ist "gleiches Item anders" von "verschwunden +
    neu" nicht unterscheidbar — solche Items bleiben unberücksichtigt."""
    old = Item.model_validate({"typeLine": "Chaos Orb"})
    new = Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 3})
    added_ids, changed_ids, removed_items = MainWindow._diff_character_items([old], [new])
    assert added_ids == frozenset()
    assert changed_ids == frozenset()
    assert removed_items == []


def test_character_refresh_highlights_changed_and_greys_out_removed_rows(qapp) -> None:
    from PySide6.QtCore import Qt
    from poe_view.ui.item_table import _NAME_COL

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    stays = Item.model_validate({"id": "stays", "typeLine": "Sword", "frameType": 2,
                                 "inventoryId": "Weapon"})
    gone = Item.model_validate({"id": "gone", "typeLine": "Old Ring", "frameType": 2,
                                "inventoryId": "Ring"})
    win._on_character_items("WitchOfPeter", [stays, gone], False)

    new_item = Item.model_validate({"id": "new", "typeLine": "Chaos Orb", "frameType": 5,
                                    "inventoryId": "MainInventory"})
    win._on_character_items("WitchOfPeter", [stays, new_item], False)

    # 3 Zeilen: die zwei aktuellen + das (für einen Zyklus) nachgezogene "gone"
    assert win.table_model.rowCount() == 3
    ids_in_view = {win.table_model.item_at(row).id for row in range(3)}
    assert ids_in_view == {"stays", "new", "gone"}

    def role_for(item_id: str, role) -> object:
        row = next(r for r in range(3) if win.table_model.item_at(r).id == item_id)
        return win.table_model.data(win.table_model.index(row, _NAME_COL), role)

    assert role_for("new", Qt.ItemDataRole.BackgroundRole) is not None    # neu -> türkis
    assert role_for("stays", Qt.ItemDataRole.BackgroundRole) is None       # unverändert -> nichts
    assert role_for("gone", Qt.ItemDataRole.FontRole).strikeOut()          # verschwunden -> durchgestrichen

    win.worker.stop()
    win.worker.wait(5000)


def test_disappeared_item_is_only_shown_for_one_refresh_cycle(qapp) -> None:
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    stays = Item.model_validate({"id": "stays", "typeLine": "Sword", "inventoryId": "Weapon"})
    gone = Item.model_validate({"id": "gone", "typeLine": "Old Ring", "inventoryId": "Ring"})

    win._on_character_items("WitchOfPeter", [stays, gone], False)
    win._on_character_items("WitchOfPeter", [stays], False)          # "gone" fehlt jetzt -> 1x nachgezogen
    assert win.table_model.rowCount() == 2

    win._on_character_items("WitchOfPeter", [stays], False)          # zweiter Refresh ohne "gone"
    assert win.table_model.rowCount() == 1
    assert win.table_model.item_at(0).id == "stays"

    win.worker.stop()
    win.worker.wait(5000)


# --- Charakter-Item-Verlauf: "was ist gerade durchs Inventar gewandert"
# (Peter, 2026-08-02) ------------------------------------------------- #

def test_a_new_item_is_logged_as_an_added_history_entry(qapp) -> None:
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    stays = Item.model_validate({"id": "stays", "typeLine": "Sword", "inventoryId": "Weapon"})
    win._on_character_items("WitchOfPeter", [stays], False)
    assert list(win._item_history) == []  # erster Ladevorgang: nichts zu vergleichen

    new_item = Item.model_validate({"id": "new", "typeLine": "Chaos Orb",
                                    "inventoryId": "MainInventory"})
    win._on_character_items("WitchOfPeter", [stays, new_item], False)

    assert len(win._item_history) == 1
    entry = win._item_history[0]
    assert entry.event == "added"
    assert entry.character == "WitchOfPeter"
    assert entry.item.id == "new"
    assert win.history_model.rowCount() == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_a_disappeared_item_is_logged_as_a_removed_history_entry(qapp) -> None:
    """Peter: "was du gerade in die Truhe getan hast oder verkauft hast
    oder gehandelt hast" — all das zeigt sich als verschwundenes Item."""
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    sold = Item.model_validate({"id": "sold", "typeLine": "Headhunter", "inventoryId": "Belt"})
    win._on_character_items("WitchOfPeter", [sold], False)

    win._on_character_items("WitchOfPeter", [], False)

    assert len(win._item_history) == 1
    assert win._item_history[0].event == "removed"
    assert win._item_history[0].item.id == "sold"

    win.worker.stop()
    win.worker.wait(5000)


def test_a_stack_size_change_is_logged_as_a_changed_history_entry_with_the_delta(qapp) -> None:
    """Peter, 2026-08-03: "In unserer Item-History-Liste berücksichtigen
    wir keine Items die sich ändern, wie Currency ... sobald sich Currency
    ändert, wandert diese wieder ganz oben auf die Liste mit Vermerk,
    wieviel sich geändert hat" — "changed", kein "added" (sonst würde jede
    kleine Mengenänderung fälschlich als Neuzugang im Verlauf landen), mit
    der Differenz im ``stack_delta``-Feld."""
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "1", "typeLine": "Chaos Orb", "stackSize": 5})], False)

    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "1", "typeLine": "Chaos Orb", "stackSize": 9})], False)

    assert len(win._item_history) == 1
    entry = win._item_history[0]
    assert entry.event == "changed"
    assert entry.item.id == "1"
    assert entry.stack_delta == 4

    win.worker.stop()
    win.worker.wait(5000)


def test_a_stack_size_decrease_is_logged_with_a_negative_delta(qapp) -> None:
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "1", "typeLine": "Chaos Orb", "stackSize": 9})], False)

    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "1", "typeLine": "Chaos Orb", "stackSize": 5})], False)

    assert len(win._item_history) == 1
    assert win._item_history[0].event == "changed"
    assert win._item_history[0].stack_delta == -4

    win.worker.stop()
    win.worker.wait(5000)


def test_a_non_stack_field_change_is_not_logged_as_changed(qapp) -> None:
    """GETRENNT von ``changed_ids`` in ``_diff_character_items`` — nur eine
    tatsächliche Stack-Größen-Differenz zählt hier, sonst würde z. B. ein
    gerade identifiziertes Item fälschlich als Mengenänderung geloggt."""
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "1", "typeLine": "Ring", "identified": False})], False)

    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "1", "typeLine": "Ring", "identified": True})], False)

    assert list(win._item_history) == []

    win.worker.stop()
    win.worker.wait(5000)


def test_history_logging_does_not_require_the_character_to_be_currently_displayed(qapp) -> None:
    """Der Verlauf ist global (Peter: "Wenn wir das Global machen") — er
    läuft für JEDEN Charakter mit, nicht nur den gerade angezeigten."""
    win = MainWindow()
    win._current_character_name = "SomeoneElse"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "1", "typeLine": "Sword"})], False)

    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "1", "typeLine": "Sword"}),
        Item.model_validate({"id": "2", "typeLine": "Chaos Orb"}),
    ], False)

    assert len(win._item_history) == 1
    assert win._item_history[0].character == "WitchOfPeter"

    win.worker.stop()
    win.worker.wait(5000)


def test_newest_history_entry_appears_first(qapp) -> None:
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [], False)  # Baseline, nichts geloggt

    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "first", "typeLine": "Chaos Orb"})], False)
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "first", "typeLine": "Chaos Orb"}),
        Item.model_validate({"id": "second", "typeLine": "Exalted Orb"})], False)

    assert win._item_history[0].item.id == "second"  # jüngstes zuerst
    assert win._item_history[1].item.id == "first"

    win.worker.stop()
    win.worker.wait(5000)


def test_history_log_is_capped_at_120_entries(qapp) -> None:
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [], False)  # Baseline

    accumulated: list[Item] = []
    for i in range(130):
        accumulated = accumulated + [Item.model_validate({"id": f"item{i}", "typeLine": "Chaos Orb"})]
        win._on_character_items("WitchOfPeter", accumulated, False)  # reines Hinzufügen, kein Entfernen

    assert len(win._item_history) == 120
    assert win._item_history[0].item.id == "item129"  # jüngstes noch drin
    assert all(e.item.id != "item0" for e in win._item_history)  # ältestes verdrängt

    win.worker.stop()
    win.worker.wait(5000)


def test_showing_a_cached_character_has_no_diff_highlighting(qapp) -> None:
    """_on_character_selected zeigt Cache-Treffer direkt an — kein Refresh,
    also auch kein Vergleichswert und keine Hervorhebung."""
    from PySide6.QtCore import Qt
    from poe_view.ui.item_table import _NAME_COL

    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")
    win._character_items["WitchOfPeter"] = [
        Item.model_validate({"id": "1", "typeLine": "Chaos Orb", "frameType": 5})]

    win._on_character_selected(char)

    idx = win.table_model.index(0, _NAME_COL)
    assert win.table_model.data(idx, Qt.ItemDataRole.BackgroundRole) is None
    assert win.table_model.data(idx, Qt.ItemDataRole.FontRole) is None

    win.worker.stop()
    win.worker.wait(5000)


# --- Charakter-Paperdoll: Doppelklick (ToDo.md, Peter 2026-07-31) ---

def test_paperdoll_opens_immediately_for_a_cached_character(qapp) -> None:
    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")
    win._all_characters = [char]
    win._character_items["WitchOfPeter"] = [
        Item.model_validate({"typeLine": "Sword", "frameType": 2, "inventoryId": "Weapon"})]

    win._on_character_paperdoll_requested(char)

    assert win._paperdoll_dialog.windowTitle() == "WitchOfPeter — Witch 50"
    assert win._paperdoll_pending_char is None

    win.worker.stop()
    win.worker.wait(5000)


# --- Mod-Album: Werkzeugleiste (§4.52, Stufe 3) ---

def test_the_toolbar_opens_the_mod_album(qapp) -> None:
    """Das Fenster bekommt die Sammlung des Fensters, nicht eine leere —
    sonst zeigte ein Klick nach dem Erstbefuellen erstmal nichts."""
    win = MainWindow()
    win._mod_collection.observe("explicitMods", "+96 to maximum Life", rarity=2)
    win._mod_collection.clear_new()

    win._open_mod_album()

    assert win._mod_album_dialog.isVisible()
    assert win._mod_album_dialog._model.rowCount() == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_paperdoll_waits_for_the_fetch_when_not_cached(qapp, monkeypatch) -> None:
    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")
    win._all_characters = [char]
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._on_character_paperdoll_requested(char)
    assert win._paperdoll_pending_char == "WitchOfPeter"
    assert not hasattr(win, "_paperdoll_dialog")

    weapon = Item.model_validate({"typeLine": "Sword", "frameType": 2, "inventoryId": "Weapon"})
    win._on_character_items("WitchOfPeter", [weapon], False)

    assert win._paperdoll_pending_char is None
    assert win._paperdoll_dialog.windowTitle() == "WitchOfPeter — Witch 50"

    win.worker.stop()
    win.worker.wait(5000)


def test_paperdoll_pending_fires_even_if_selection_moved_on(qapp) -> None:
    """Der Doppelklick galt WitchOfPeter — auch wenn der Nutzer inzwischen
    einen anderen Charakter angeklickt hat, bevor die Daten eintrafen, soll
    die Paperdoll trotzdem für den ursprünglich angeklickten Charakter
    aufgehen (unabhängig von _current_character_name, das die Tabellen-
    Anzeige steuert)."""
    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")
    win._all_characters = [char]
    win._paperdoll_pending_char = "WitchOfPeter"
    win._current_character_name = "SomeoneElse"

    weapon = Item.model_validate({"typeLine": "Sword", "frameType": 2, "inventoryId": "Weapon"})
    win._on_character_items("WitchOfPeter", [weapon], False)

    assert win._paperdoll_dialog.windowTitle() == "WitchOfPeter — Witch 50"

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
    angezeigte Truhenfach live gehalten werden — der Stash-Sweep kommt im
    nächsten Takt dran, nicht im selben (§_maybe_auto_refresh)."""
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
    assert len(submitted) == 1  # EIN Job je Takt, nicht zwei
    assert submitted[0].name == "WitchOfPeter"
    assert submitted[0].silent is True

    win._refresh_mode_pending = False  # Antwort ist da, nächster Takt
    win._maybe_auto_refresh()
    assert len(submitted) == 2  # jetzt der Sweep
    assert submitted[1].stash_id == "t1"

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


def _price_index(**prices: float) -> PriceIndex:
    index = PriceIndex()
    index._simple.update(prices)
    return index


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


def test_a_tab_that_ggg_does_not_have_leaves_the_sweep(qapp) -> None:
    """Peters Log vom 2026-08-24: neun Abrufe desselben Map-Stash-
    Unterfachs in fuenf Minuten, kein einziger auf ein anderes Fach.

    Der Grund steckt in der Auswahl selbst: Ein nie geladenes Fach gilt als
    unendlich alt und gewinnt damit jeden Vergleich — und weil der Abruf
    404 liefert, wird nie ein Ladezeitpunkt geschrieben, der das aendern
    wuerde. Ohne Merker bleibt es fuer immer der naechste Kandidat."""
    win = MainWindow()
    win._current_league = "Allflame"
    win._leaf_stashes = [_make_leaf("tot", "1"), _make_leaf("echt", "Currency")]
    win._last_loaded["Allflame"] = {}

    assert win._pick_auto_refresh_candidate().id in ("tot", "echt")   # Vorbedingung
    win._on_stash_missing("Allflame", "tot", "")

    for _ in range(3):   # der Rundlauf muss WEITERlaufen, nicht nur einmal
        assert win._pick_auto_refresh_candidate().id == "echt"

    win.worker.stop()
    win.worker.wait(5000)


def test_a_missing_tab_only_leaves_the_sweep_in_its_own_league(qapp) -> None:
    """Fach-Kennungen sind je Liga vergeben. Ein Merker ohne Liga haette
    in einer anderen Liga ein voellig unbeteiligtes Fach ausgesperrt."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("tot", "1")]
    win._last_loaded["Standard"] = {}
    win._on_stash_missing("Allflame", "tot", "")

    kandidat = win._pick_auto_refresh_candidate()
    assert kandidat is not None and kandidat.id == "tot"

    win.worker.stop()
    win.worker.wait(5000)


def test_a_tab_that_works_again_returns_to_the_sweep(qapp) -> None:
    """Legt der Nutzer eine Karte in ein leeres Map-Stash-Unterfach, gibt es
    das Fach ploetzlich. Der Merker darf dann nicht bis zum Programmende
    nachhaengen."""
    win = MainWindow()
    win._current_league = "Allflame"
    win._leaf_stashes = [_make_leaf("tot", "1")]
    win._last_loaded["Allflame"] = {}
    win._on_stash_missing("Allflame", "tot", "")
    assert win._pick_auto_refresh_candidate() is None    # Vorbedingung

    win._on_stash_items("Allflame", "tot", "1", [], True)

    assert win._missing_stashes["Allflame"] == set()

    win.worker.stop()
    win.worker.wait(5000)


def test_a_missing_tab_releases_the_refresh_chain(qapp) -> None:
    """Dieser Weg loest bewusst kein ``job_error`` aus (das wuerde die Kette
    ein zweites Mal freigeben und einen Takt verschlucken). Damit liegt die
    Freigabe hier — ohne sie stuende der taktende Modus fuer den Rest der
    Sitzung, wie schon einmal beim Nur-Lese-Fenster."""
    win = MainWindow()
    win._current_league = "Allflame"
    win._refresh_mode = "auto"
    win._refresh_mode_pending = True

    win._on_stash_missing("Allflame", "tot", "")

    assert win._refresh_mode_pending is False

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
    win._stash_trees["Standard"] = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    win._leaf_stashes = win._stash_trees["Standard"]
    win._update_refresh_status()
    assert win._sweep_counter_text() == "0/2 tabs"

    win._on_stash_items("Standard", "t1", "Tab 1", [], silent=True)
    assert win._sweep_counter_text() == "1/2 tabs"

    # Manuelle (nicht-silente) Ladevorgänge zählen nicht als Auto-Refresh.
    win._on_stash_items("Standard", "t2", "Tab 2", [], silent=False)
    assert win._sweep_counter_text() == "1/2 tabs"

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_counter_counts_real_vault_slots_not_map_sections(qapp) -> None:
    """Peter: "In der Statusanzeige steht noch '939 stash tabs updated'" —
    derselbe Zähl-Fehler wie bei der Positions-Spalte (FALLSTRICKE #36),
    nur an anderer Stelle: ``_leaf_stashes`` zählt jede Map-Sektion einzeln,
    ein Map-Stash mit vielen Sektionen ist in der Truhen-Leiste aber EIN
    Fach. "Y" muss die echte Fächer-Zahl sein, "X" muss dieselbe Einheit
    zählen — zwei Sektionen DESSELBEN Map-Tabs dürfen nur EINMAL zählen."""
    win = MainWindow()
    win._current_league = "Standard"
    map_stash = StashTab.model_validate({"id": "m1", "name": "Maps", "type": "MapStash",
                                         "metadata": {}})
    map_stash.children = [_map_child("c1", "m1", "Beach Map"), _map_child("c2", "m1", "Dune Map")]
    win._stash_trees["Standard"] = [_make_leaf("t1", "Tab 1"), map_stash]
    win._leaf_stashes = win._flatten_stashes(win._stash_trees["Standard"])  # 3 ladbare Einheiten

    win._update_refresh_status()
    assert win._sweep_counter_text() == "0/2 tabs"  # nicht "of 3"

    win._on_stash_items("Standard", "c1", "x", [], silent=True)
    assert win._sweep_counter_text() == "1/2 tabs"

    # Die zweite Sektion DESSELBEN Map-Tabs darf den Zähler nicht weiter
    # hochtreiben — beide gehören zum selben Truhenplatz "m1".
    win._on_stash_items("Standard", "c2", "x", [], silent=True)
    assert win._sweep_counter_text() == "1/2 tabs"

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
    win._stash_trees["Standard"] = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    win._leaf_stashes = win._stash_trees["Standard"]
    # Simuliert einen zuvor aus dem Datei-Cache geladenen Stand: t1 ist
    # bereits Wochen alt bekannt, ohne dass diese Session je selbst geladen hätte.
    win._last_loaded["Standard"] = {"t1": "2026-01-01T00:00:00+00:00"}

    win._on_stash_items("Standard", "t1", "Tab 1", [], silent=True)

    assert win._sweep_counter_text() == "1/2 tabs"

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_label_is_empty_without_league(qapp) -> None:
    win = MainWindow()
    win._update_refresh_status()
    assert win._sweep_counter_text() == ""

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
    assert "Auto — next update in" in win._refresh_status_label.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_refresh_countdown_shows_reason_when_blocked(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 0.05)

    win._update_auto_refresh_countdown()

    assert win._auto_refresh_blocked_reason() == "rate limit budget reserved for manual requests"
    assert "Auto-refresh paused" in win._refresh_status_label.text()

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

    assert win._refresh_status_label.text() == ""

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

    # Eigener Request des Single-Modus: lockere Policy, ~13.0s Takt.
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
    # 300/23 seit 2026-08-06: Takt und Notbremse kommen aus demselben
    # Budget (§rate_limiter._pacing_budget, FALLSTRICKE #64).
    assert interval == pytest.approx(300 / 23, abs=0.01)

    win.worker.stop()
    win.worker.wait(5000)


def _stash_mode_win_midtick(qapp, monkeypatch):
    """MainWindow im Stash-Modus, mitten in einem laufenden 75s-Takt, mit
    bereits gecachten Fächern — der Aufbau, in dem ein Auswahlwechsel früher
    einen Sofort-Request auslöste (und damit das Rate-Limit-Fenster über die
    Schwelle trieb, FALLSTRICKE #34)."""
    win = MainWindow()
    win._current_league = "Standard"
    win._items["Standard"] = {"t1": [], "t2": []}  # Cache-Treffer → kein regulärer Fetch
    win._leaf_stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 75.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])
    win._refresh_mode = "stash"
    win._refresh_mode_next_due = fake_now[0] + 75.0  # mitten im Takt
    return win, submitted, fake_now


def test_selection_change_does_not_fire_an_extra_request(qapp, monkeypatch) -> None:
    """Peter: "wir sollten das wieder konservativer angehen" — ein Klick
    darf den laufenden Takt NICHT überspringen. Früher feuerte er sofort und
    schob damit einen Extra-Request ins 300s-Fenster (FALLSTRICKE #34)."""
    win, submitted, _fake_now = _stash_mode_win_midtick(qapp, monkeypatch)

    win._on_stash_selected("t1", "Tab 1")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_selection_change_makes_the_clicked_tab_the_next_pick(qapp, monkeypatch) -> None:
    """Stattdessen drängelt sich das angeklickte Fach in der
    Abarbeitungsliste nach vorn: beim nächsten regulären Takt ist es dran,
    obwohl "t2" hier als älteres Fach sonst zuerst käme."""
    win, submitted, fake_now = _stash_mode_win_midtick(qapp, monkeypatch)
    now = datetime.now(timezone.utc)
    win._last_loaded["Standard"] = {
        "t1": now.isoformat(),                            # gerade erst geladen
        "t2": (now - timedelta(days=5)).isoformat(),      # viel älter → sonst zuerst
    }

    win._on_stash_selected("t1", "Tab 1")
    assert submitted == []            # noch kein Request, Takt läuft weiter

    fake_now[0] += 75.0               # nächster regulärer Takt
    win._drive_refresh_mode()

    assert len(submitted) == 1
    assert submitted[0].stash_id == "t1"  # vorgedrängelt, trotz jüngeren Alters
    assert submitted[0].silent is True

    win.worker.stop()
    win.worker.wait(5000)


def test_selection_priority_applies_only_once(qapp, monkeypatch) -> None:
    """Die Vormerkung ist einmalig — danach greift wieder die normale
    Reihenfolge, sonst bliebe der Sweep an diesem einen Fach kleben."""
    win, submitted, fake_now = _stash_mode_win_midtick(qapp, monkeypatch)
    now = datetime.now(timezone.utc)
    win._last_loaded["Standard"] = {
        "t1": now.isoformat(),
        "t2": (now - timedelta(days=5)).isoformat(),
    }

    win._on_stash_selected("t1", "Tab 1")
    fake_now[0] += 75.0
    win._drive_refresh_mode()
    assert submitted[-1].stash_id == "t1"

    win._refresh_mode_pending = False
    fake_now[0] += 75.0
    win._drive_refresh_mode()

    assert submitted[-1].stash_id == "t2"  # wieder das älteste Fach

    win.worker.stop()
    win.worker.wait(5000)


def test_selection_change_is_a_no_op_in_auto_mode(qapp, monkeypatch) -> None:
    win, submitted, _fake_now = _stash_mode_win_midtick(qapp, monkeypatch)
    win._refresh_mode = "auto"

    win._on_stash_selected("t1", "Tab 1")

    assert submitted == []
    assert win._refresh_mode_priority_id is None

    win.worker.stop()
    win.worker.wait(5000)


def test_selection_change_on_cache_miss_does_not_prioritise(qapp, monkeypatch) -> None:
    """Bei einem Cache-Miss ist über den normalen Auswahl-Pfad ohnehin schon
    ein (nicht-stiller) Fetch unterwegs — eine Vormerkung würde dasselbe Fach
    gleich noch einmal laden."""
    win, submitted, _fake_now = _stash_mode_win_midtick(qapp, monkeypatch)

    win._on_stash_selected("uncached", "Tab X")

    assert len(submitted) == 1
    assert submitted[0].silent is False
    assert win._refresh_mode_priority_id is None

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


def _drive_stash_mode_pick(win: MainWindow, fake_now: list[float], submitted: list) -> str | None:
    """Einen Pick auslösen und den realen Ladevorgang simulieren
    (``_on_stash_items`` bzw. ``_on_stash_list``), damit Alter/Füllstand
    bzw. die Fach-Liste für den nächsten Pick korrekt fortgeschrieben
    werden — wie es der echte Worker täte. Liefert die Fach-ID, oder
    ``None`` bei einem Listen-Refresh (§_stash_mode_list_refresh_due)."""
    fake_now[0] += 10.0
    win._refresh_mode_pending = False
    win._drive_refresh_mode()
    job = submitted[-1]
    if isinstance(job, FetchStashListJob):
        win._on_stash_list(win._leaf_stashes, silent=True)
        return None
    picked = job.stash_id
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

    fourth = _drive_stash_mode_pick(win, fake_now, submitted)  # Pick #4: zusätzlich die Fach-Liste auffrischen
    assert fourth is None and isinstance(submitted[-1], FetchStashListJob)

    fifth = _drive_stash_mode_pick(win, fake_now, submitted)  # Pick #5: neue Runde beginnt normal
    assert fifth in {"full_a", "full_b"}

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
    # Jede Runde ist hier nur einen Pick lang (ein einziges gefülltes Fach) und
    # erzeugt danach ZWEI Extra-Ticks: den Coverage-Pick und einen Listen-
    # Refresh (§_stash_mode_list_refresh_due) — macht 3 Ticks je Runde,
    # 9 also genug für alle drei leeren Fächer.
    picked = [_drive_stash_mode_pick(win, fake_now, submitted) for _ in range(9)]

    covered = [p for p in picked if p not in ("full", None)]
    assert covered == ["empty_a", "empty_b", "empty_c"]

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_coverage_pick_follows_a_tab_moved_forward_in_game(qapp, monkeypatch) -> None:
    """Verschiebt der Nutzer im Spiel ein Fach weiter nach vorne, liefert
    der automatische Listen-Refresh (§_stash_mode_list_refresh_due) die
    neue Reihenfolge — der Rundlauf-Cursor (ein reiner Listen-Index in die
    aktuell leeren Fächer) folgt ihr und erreicht das Fach dadurch früher,
    als es an seiner alten (hinteren) Position dran gewesen wäre."""
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

    # Die Runde ist jetzt fertig -> der nächste Tick ist der automatische
    # Listen-Refresh. Seine Antwort simuliert die im Spiel geänderte
    # Reihenfolge: "moved" rückt an die zweite leere Position vor.
    fake_now[0] += 10.0
    win._refresh_mode_pending = False
    win._drive_refresh_mode()
    assert isinstance(submitted[-1], FetchStashListJob)
    reordered = [_make_leaf("full", "Full"), _make_leaf("empty_a", "Empty A"),
                _make_leaf("moved", "Moved Tab"), _make_leaf("empty_b", "Empty B")]
    win._on_stash_list(reordered, silent=True)

    assert _drive_stash_mode_pick(win, fake_now, submitted) == "full"   # Runde: erst wieder das gefüllte Fach
    assert _drive_stash_mode_pick(win, fake_now, submitted) == "moved"  # früher dran dank neuer Position

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_schedules_a_silent_list_refresh_after_a_full_round(qapp, monkeypatch) -> None:
    """Peter: "Bekommen wir das mit, wenn ich ein Truhenfach im Spiel
    verschiebe?" — bisher nein, Auto-/Single-/Stash-Modus aktualisierten
    nur Items, nie die Fach-LISTE selbst. Jetzt hängt sich nach jeder
    vollständigen Runde zusätzlich ein stiller `FetchStashListJob` an."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})]}
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 10.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Stash")  # Pick #1: "t1"
    win._on_stash_items("Standard", "t1", "x", win._items["Standard"]["t1"], silent=True)

    # Pick #2: die Runde (nur 1 Fach) ist damit schon nach Pick #1 voll —
    # dieser Tick merkt sich "Liste beim nächsten Mal auffrischen" und pickt
    # mangels leerer Fächer normal weiter (wieder "t1", das einzige Fach).
    fake_now[0] += 10.0
    win._refresh_mode_pending = False
    win._drive_refresh_mode()
    assert submitted[-1].stash_id == "t1"
    win._on_stash_items("Standard", "t1", "x", win._items["Standard"]["t1"], silent=True)

    # Pick #3: jetzt der geplante Listen-Refresh, VOR jedem weiteren Item-Pick.
    fake_now[0] += 10.0
    win._refresh_mode_pending = False
    win._drive_refresh_mode()

    assert submitted[-1] == FetchStashListJob("Standard", silent=True)
    assert win._refresh_mode_pending is True  # Kette wartet auf die Antwort, kein Sofort-Retry

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_schedules_a_list_refresh_even_without_any_empty_tabs(qapp, monkeypatch) -> None:
    """Auch eine Truhe ohne ein einziges leeres Fach braucht den Listen-
    Refresh — sonst bliebe eine komplett bekannte, aber im Spiel
    umsortierte Truhe für immer unentdeckt."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    win._items["Standard"] = {
        "t1": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})],
        "t2": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})],
    }
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 10.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Stash")  # Pick #1
    first = submitted[-1].stash_id
    win._on_stash_items("Standard", first, "x", win._items["Standard"][first], silent=True)

    second = _drive_stash_mode_pick(win, fake_now, submitted)  # Pick #2: Runde (2 Fächer) fertig
    assert second is not None and second != first

    # Pick #3: mangels leerer Fächer fällt die Runden-Grenze auf einen ganz
    # normalen Pick zurück — merkt sich aber "Liste beim nächsten Mal auffrischen".
    third = _drive_stash_mode_pick(win, fake_now, submitted)
    assert third in {"t1", "t2"}

    # Pick #4: jetzt der geplante Listen-Refresh, obwohl nichts leer ist.
    fake_now[0] += 10.0
    win._refresh_mode_pending = False
    win._drive_refresh_mode()

    assert isinstance(submitted[-1], FetchStashListJob)

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_never_repicks_a_loaded_remove_only_tab_while_others_are_filled(
        qapp, monkeypatch) -> None:
    """Peter, 2026-08-02: Remove-only-Fächer können nur schrumpfen, nie
    wachsen — sobald einmal geladen, sollen sie beim Stash-Modus-Rundlauf
    nicht mehr regulär mitlaufen. Trotz eines viel älteren Ladezeitpunkts
    bleibt "ro" hier über mehrere Runden hinweg unberührt, solange "regular"
    noch existiert."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("ro", "Guild Tab (Remove-only)"),
                         _make_leaf("regular", "Tab 2")]
    now = datetime.now(timezone.utc)
    win._items["Standard"] = {
        "ro": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})],
        "regular": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})],
    }
    win._last_loaded["Standard"] = {
        "ro": (now - timedelta(days=30)).isoformat(),   # viel älter, aber Remove-only
        "regular": (now - timedelta(days=1)).isoformat(),
    }
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 10.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Stash")  # Pick #1
    picks = [submitted[-1].stash_id]
    for _ in range(5):
        pick = _drive_stash_mode_pick(win, fake_now, submitted)
        if pick is not None:
            picks.append(pick)

    assert set(picks) == {"regular"}

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_falls_back_to_a_remove_only_tab_when_nothing_else_is_filled(
        qapp, monkeypatch) -> None:
    """Ist ein bereits geladenes Remove-only-Fach das EINZIGE gefüllte Fach,
    muss es trotzdem irgendwann drankommen — "nachrangig" heißt nicht "nie"."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("ro", "Guild Tab (Remove-only)")]
    win._items["Standard"] = {
        "ro": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})],
    }
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_refresh_mode_changed("Stash")

    assert len(submitted) == 1
    assert submitted[0].stash_id == "ro"

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_still_loads_a_never_loaded_remove_only_tab_once(qapp, monkeypatch) -> None:
    """Vor dem ersten Laden ist das Fach für den Refresh-Modus nicht von
    einem normalen leeren Fach zu unterscheiden (item_counts kennt es noch
    nicht) — es nimmt ganz normal am Leer-Fach-Rundlauf teil und bekommt so
    trotzdem einmal seine Erstladung."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("full", "Full"), _make_leaf("ro", "Guild Tab (Remove-only)")]
    win._items["Standard"] = {"full": [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})]}
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 10.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Stash")  # Pick #1: "full"
    win._on_stash_items("Standard", "full", "x", win._items["Standard"]["full"], silent=True)
    second = _drive_stash_mode_pick(win, fake_now, submitted)  # Pick #2: Runde fertig -> Coverage-Pick

    assert second == "ro"

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_mode_round_state_resets_on_league_change(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_refresh_mode_changed("Stash")
    assert win._stash_mode_round_picks == 1  # t1 ist leer -> normaler Pick, hochgezählt

    win._stash_mode_list_refresh_due = True  # simuliert: Runde war gerade fertig
    win._on_league_changed("Standard SSF")

    assert win._stash_mode_round_picks == 0
    assert win._stash_mode_coverage_cursor == 0
    assert win._stash_mode_list_refresh_due is False  # sonst würde die neue Liga sofort erneut abgefragt

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


def test_auto_haengt_am_gerechneten_takt_statt_an_40_sekunden(qapp, monkeypatch) -> None:
    """Kern der Änderung vom 2026-08-21: Auto war der einzige Modus mit
    einer FESTEN Zahl (40s) und lief damit an GGGs echtem Budget vorbei —
    in Peters Log stand das 300s-Fenster im Median bei 8 von 30 Treffern.
    Jetzt taktet Auto über dieselbe ``_drive_refresh_mode``-Kette wie
    Single/Stash, also aus ``steady_pace_interval_s``."""
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s",
                        lambda policy_name=None: 12.5)

    win._drive_refresh_mode()  # Modus ist per Default "auto"
    assert len(submitted) == 1  # kein No-Op mehr

    win._note_refresh_mode_job_done()  # Antwort da → nächster Takt steht
    ahead = win._refresh_mode_next_due - time.monotonic()
    assert 11.5 < ahead <= 12.5, "Takt kommt aus dem Rate-Limiter, nicht aus einer Konstante"

    win._drive_refresh_mode()  # noch nicht fällig
    assert len(submitted) == 1

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


def test_refresh_mode_paces_from_the_response_not_from_the_submit(qapp, monkeypatch) -> None:
    """Regression (FALLSTRICKE #34): Blockiert der Rate-Limiter einen Job
    minutenlang (``check_and_wait``), war eine beim ABSENDEN gesetzte
    Fälligkeit beim Eintreffen der Antwort längst abgelaufen — der nächste
    Pick feuerte sofort hinterher. Real beobachtet: nach einer 289s-Sperre
    kamen zwei Requests im Abstand von 1.3s statt der ~11s Takt, die
    dadurch erreichten 29 Treffer im 300s-Fenster lösten prompt die
    nächste Sperre aus, und das wiederholte sich endlos."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 11.0)
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win._on_refresh_mode_changed("Stash")
    assert len(submitted) == 1
    first = submitted[0].stash_id

    # Der Worker hängt 289s im Rate-Limit-Wait, DANN erst kommt die Antwort.
    fake_now[0] += 289.0
    win._on_stash_items("Standard", first, "x", [], silent=True)

    assert len(submitted) == 1, "kein Sofort-Nachschlag direkt nach der Sperre"

    # Erst ein voller Takt NACH der Antwort darf der nächste Request raus.
    fake_now[0] += 10.0
    win._drive_refresh_mode()
    assert len(submitted) == 1

    fake_now[0] += 1.0
    win._drive_refresh_mode()
    assert len(submitted) == 2

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_countdown_label_shows_active_mode(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win._refresh_mode_combo.setCurrentText("Single")

    win._update_auto_refresh_countdown()

    assert "Single" in win._refresh_status_label.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_stepping_mode_stops_while_the_rate_limit_window_is_too_full(qapp, monkeypatch) -> None:
    """Regression zu FALLSTRICKE #47 (real: 289s Zwangspause am 2026-07-30).

    Der gleichmäßige Takt rechnet, als wäre das Fenster leer und als kämen
    nur seine eigenen Requests darin vor. Real füllen ungetaktete Requests
    (Klicks, Liga-Wechsel, Programmstart) dasselbe Fenster mit — der Takt
    lief stur weiter bis zur Bremsschwelle. Ist das Fenster schon zu voll,
    muss er pausieren, und das Label muss den Grund nennen statt einen
    Countdown zu zeigen, der bei 0s stehen bleibt."""
    win = MainWindow()
    win._current_league = "Standard"
    win._refresh_mode_combo.setCurrentText("Stash")
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    win._items["Standard"] = {"t1": [object()]}

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    blocked = [True]
    monkeypatch.setattr(win.worker.rate_limiter, "pacing_blocked",
                        lambda policy=None: blocked[0])

    win._refresh_mode_next_due = 0.0
    win._drive_refresh_mode()
    assert submitted == []  # kein Request, solange das Fenster zu voll ist

    win._update_auto_refresh_countdown()
    assert "headroom" in win._refresh_status_label.text()

    # Sobald GGGs Zähler wieder sinkt, läuft der Takt weiter.
    blocked[0] = False
    win._refresh_mode_next_due = 0.0
    win._drive_refresh_mode()
    assert len(submitted) == 1

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
    # Ein Token-Ablauf MITTEN in der Sitzung setzt einen vorherigen Login
    # voraus — `_on_login_required` lässt `_account_name` bewusst stehen
    # (siehe dort). Ohne dieses Feld wäre die Ausgangslage unmöglich: Liga
    # und Fächer gefüllt, aber nie ein Konto aktiv gewesen. Seit
    # FALLSTRICKE #62 macht das einen Unterschied, weil `_on_logged_in`
    # bei leerem `_account_name` den Kontostand von der Platte nachlädt.
    win._account_name = "PeterM"
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


def test_online_actions_disabled_while_not_logged_in(qapp) -> None:
    """Ohne gültigen Login blieb 'Load All Tabs' anklickbar, solange ein
    Daten-Cache aus einer früheren Sitzung vorlag (bleibt auch ohne Login
    sichtbar) — der Fortschrittsdialog öffnete sich, der Job wurde vom
    Worker aber lautlos verworfen und der Dialog hing für immer bei 0 %.
    Refresh/Load-All-Tabs/Refresh-Modus müssen bei fehlendem Login gesperrt
    sein und nach erneutem Login wieder freigegeben werden."""
    win = MainWindow()

    win._on_login_required("No valid token — please log in.")
    assert not win._refresh_action.isEnabled()
    assert not win._load_all_action.isEnabled()
    assert not win._refresh_mode_combo.isEnabled()

    win._on_logged_in("PeterM")
    assert win._refresh_action.isEnabled()
    assert win._load_all_action.isEnabled()
    assert win._refresh_mode_combo.isEnabled()

    win.worker.stop()
    win.worker.wait(5000)


# --- Logout + Konto-Trennung (Peter, 2026-08-02/03) ----------------------- #

def test_login_button_shows_account_name_and_gains_a_logout_menu(qapp) -> None:
    from PySide6.QtWidgets import QToolButton

    win = MainWindow()
    assert win._login_button.text() == "🔑 Log in"
    assert win._login_button.menu() is None

    win._on_logged_in("PeterM")

    assert win._login_button.text() == "⚷ PeterM"
    assert win._login_button.menu() is win._account_menu
    # Auf "enthaelt" statt auf Gleichheit geprueft: Das Menue traegt seit
    # dem PoE2-Abzug (§4.43) einen zweiten Eintrag, und dieser Test geht
    # ueber den Login-Knopf, nicht ueber den Menueinhalt.
    assert "🚪 Log out" in [a.text() for a in win._account_menu.actions()]
    assert win._login_button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup

    win.worker.stop()
    win.worker.wait(5000)


def test_login_button_reverts_after_logout(qapp) -> None:
    win = MainWindow()
    win._on_logged_in("PeterM")

    win._on_login_required("Logged out.")

    assert win._login_button.text() == "🔑 Log in"
    assert win._login_button.menu() is None

    win.worker.stop()
    win.worker.wait(5000)


def test_logout_clears_in_memory_session_data(qapp, monkeypatch) -> None:
    """Peter, 2026-08-02: fehlender Logout war "für ein öffentliches
    Werkzeug eine Sackgasse". Ein Logout muss die im Speicher gehaltenen
    Fach-/Item-/Charakterdaten leeren, damit nach einem Login mit einem
    ANDEREN Konto nichts vom alten sichtbar bleibt oder sich vermischt."""
    win = MainWindow()
    win._on_logged_in("PeterM")
    win._current_league = "Standard"
    t1 = _make_leaf("t1", "Currency 1")
    win._stash_trees["Standard"] = [t1]
    win._leaf_stashes = [t1]
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb"})]}
    win._all_characters = [make_char("WitchOfPeter", "Standard")]
    win._character_items["WitchOfPeter"] = [Item.model_validate({"typeLine": "Chaos Orb"})]
    win._filter_edit.setText("chaos")
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._on_logout_clicked()

    assert win._stash_trees == {}
    assert win._items == {}
    assert win._all_characters == []
    assert win._character_items == {}
    assert win._leaf_stashes == []
    assert win._current_league == ""
    assert win._account_name == ""
    assert win._filter_edit.text() == ""
    assert win.tree.topLevelItemCount() == 0
    assert win.character_list.count() == 0
    assert win.table_model.rowCount() == 0

    win.worker.stop()
    win.worker.wait(5000)


def test_logout_submits_a_logout_job(qapp, monkeypatch) -> None:
    from poe_view.services.api_worker import LogoutJob

    win = MainWindow()
    win._on_logged_in("PeterM")
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_logout_clicked()

    assert any(isinstance(j, LogoutJob) for j in submitted)

    win.worker.stop()
    win.worker.wait(5000)


def test_persist_cache_is_a_noop_without_an_active_account(qapp, monkeypatch) -> None:
    """Verhindert, dass ein spät eintreffender Job kurz nach einem Logout
    eine leere Datei über einen bestehenden Kontostand schreibt."""
    from poe_view.services import cache_writer

    win = MainWindow()
    saved = []
    monkeypatch.setattr(cache_writer.CacheWriter, "request",
                        lambda self, snapshot: saved.append(snapshot.path))

    win._persist_cache()

    assert saved == []

    win.worker.stop()
    win.worker.wait(5000)


def test_persist_cache_writes_to_the_accounts_own_file(qapp, monkeypatch) -> None:
    from poe_view.services import cache_writer, data_cache

    win = MainWindow()
    win._on_logged_in("PeterM")
    saved = []
    monkeypatch.setattr(cache_writer.CacheWriter, "request",
                        lambda self, snapshot: saved.append(snapshot))

    win._persist_cache()

    assert len(saved) == 1
    snapshot = saved[0]
    assert snapshot.payload["account_name"] == "PeterM"
    assert snapshot.path == data_cache.path_for("PeterM")

    win.worker.stop()
    win.worker.wait(5000)


def test_logging_in_with_a_different_account_discards_the_old_data(qapp, monkeypatch) -> None:
    """Kern der Konto-Trennung: ein kalter Start laedt spekulativ das
    zuletzt bekannte Konto, ein Login mit einem ANDEREN Konto darf dessen
    Daten nicht mit dem alten Stand vermischen."""
    win = MainWindow()
    win._account_name = "Alice"  # spekulativ geladen, wie beim kalten Start
    win._stash_trees["Standard"] = [_make_leaf("t1", "Alice's Tab")]
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb"})]}
    win._all_characters = [make_char("AliceChar", "Standard")]
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._on_logged_in("Bob")

    assert win._account_name == "Bob"
    assert win._stash_trees == {}
    assert win._items == {}
    assert win._all_characters == []

    win.worker.stop()
    win.worker.wait(5000)


def test_logging_in_with_a_different_account_loads_its_own_cache(qapp, monkeypatch) -> None:
    from poe_view.services import data_cache

    win = MainWindow()
    win._account_name = "Alice"
    bob_data = data_cache.CachedData()
    bob_data.account_name = "Bob"
    bob_data.characters = [make_char("BobChar", "Standard")]
    data_cache.save(bob_data, data_cache.path_for("Bob"))
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._on_logged_in("Bob")

    assert [c.name for c in win._all_characters] == ["BobChar"]

    win.worker.stop()
    win.worker.wait(5000)


def test_logging_in_with_the_same_account_keeps_the_data(qapp, monkeypatch) -> None:
    """Der Normalfall (Neustart oder erneuter Login mit demselben Konto)
    darf NICHT wie ein Kontowechsel behandelt werden."""
    win = MainWindow()
    win._account_name = "PeterM"
    t1 = _make_leaf("t1", "Currency 1")
    win._stash_trees["Standard"] = [t1]
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb"})]}
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._on_logged_in("PeterM")

    assert "Standard" in win._stash_trees
    assert win._items["Standard"]["t1"][0].display_name == "Chaos Orb"

    win.worker.stop()
    win.worker.wait(5000)


def test_restore_cached_data_uses_the_last_active_account_hint(qapp) -> None:
    """`config.APP_DATA_DIR` ist über die autouse-Fixture in conftest.py
    schon pro Test isoliert — `_settings()` baut ihren Pfad daraus, ein
    Schreiben unter demselben Pfad genügt, kein Monkeypatch von `_settings`
    nötig."""
    from poe_view import config
    from poe_view.services import data_cache
    from PySide6.QtCore import QSettings

    peter_data = data_cache.CachedData()
    peter_data.account_name = "PeterM"
    peter_data.characters = [make_char("WitchOfPeter", "Standard")]
    data_cache.save(peter_data, data_cache.path_for("PeterM"))
    QSettings(str(config.APP_DATA_DIR / "ui-settings.ini"),
             QSettings.Format.IniFormat).setValue("account/last_active", "PeterM")

    win = MainWindow()

    assert win._account_name == "PeterM"
    assert [c.name for c in win._all_characters] == ["WitchOfPeter"]

    win.worker.stop()
    win.worker.wait(5000)


def test_restore_cached_data_falls_back_to_legacy_file_without_a_hint(
        qapp, monkeypatch, tmp_path) -> None:
    """Migration: erster Start nach dieser Funktion kennt noch kein
    'last_active'-Setting, findet aber evtl. die alte gemeinsame
    data-cache.json -- deren eigener account_name wird uebernommen."""
    from poe_view.services import data_cache

    legacy_path = tmp_path / "legacy.json"
    monkeypatch.setattr(data_cache, "_CACHE_FILE", legacy_path)
    legacy_data = data_cache.CachedData()
    legacy_data.account_name = "OldAccount"
    legacy_data.characters = [make_char("LegacyChar", "Standard")]
    data_cache.save(legacy_data)  # kein path -> alter, gemeinsamer Pfad

    win = MainWindow()

    assert win._account_name == "OldAccount"
    assert [c.name for c in win._all_characters] == ["LegacyChar"]

    win.worker.stop()
    win.worker.wait(5000)


def test_restore_cached_data_falls_back_to_legacy_when_account_file_is_missing(
        qapp, monkeypatch) -> None:
    """Real bei Peter beobachtet, 2026-08-02: eine kurze erste Sitzung
    schrieb den 'last_active'-Hinweis bereits (jeder Login tut das), ohne
    dass je ein vollständiger `_persist_cache()` gelaufen wäre. Jeder
    weitere Start versuchte danach NUR NOCH die fehlende kontospezifische
    Datei und gab auf — die reiche alte `data-cache.json` blieb
    unangetastet daneben liegen, aber unsichtbar ("alles muss neu
    heruntergeladen werden"). Existiert die kontospezifische Datei nicht,
    muss die alte übernommen werden, SOFERN ihr eigener account_name zum
    Hinweis passt."""
    from poe_view import config
    from poe_view.services import data_cache
    from PySide6.QtCore import QSettings

    legacy_data = data_cache.CachedData()
    legacy_data.account_name = "TestAccount#1234"
    legacy_data.characters = [make_char("RichChar", "Standard")]
    legacy_data.stash_trees = {"Standard": [_make_leaf("t1", "Currency 1")]}
    data_cache.save(legacy_data)  # alter, gemeinsamer Pfad
    QSettings(str(config.APP_DATA_DIR / "ui-settings.ini"),
             QSettings.Format.IniFormat).setValue("account/last_active", "TestAccount#1234")
    assert not data_cache.path_for("TestAccount#1234").exists()  # genau der beobachtete Zustand

    win = MainWindow()

    assert win._account_name == "TestAccount#1234"
    assert [c.name for c in win._all_characters] == ["RichChar"]
    assert "Standard" in win._stash_trees

    win.worker.stop()
    win.worker.wait(5000)


def test_logging_in_again_after_a_logout_reloads_the_account_cache(qapp, monkeypatch) -> None:
    """Realer Datenverlust bei Peter, 2026-08-03 (FALLSTRICKE #62): nach
    einem Logout ist der Speicher absichtlich leer UND ``_account_name``
    zurückgesetzt. Meldet man sich danach mit DEMSELBEN Konto wieder an,
    muss der Stand von der Platte zurückkommen — sonst bleibt der
    Speicher leer und der nächste ``_persist_cache()`` überschreibt die
    gefüllte Cache-Datei mit dem Nichts."""
    from poe_view.services import data_cache

    stored = data_cache.CachedData()
    stored.account_name = "TestAccount#1234"
    stored.characters = [make_char("RichChar", "Standard")]
    stored.stash_trees = {"Standard": [_make_leaf("t1", "Currency 1")]}
    data_cache.save(stored, data_cache.path_for("TestAccount#1234"))

    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_logged_in("TestAccount#1234")
    win._on_logout_clicked()
    assert win._stash_trees == {} and win._account_name == ""  # Logout wirkt

    win._on_logged_in("TestAccount#1234")  # dieselbe Person meldet sich neu an

    assert [c.name for c in win._all_characters] == ["RichChar"]
    assert "Standard" in win._stash_trees

    win.worker.stop()
    win.worker.wait(5000)


def _window_with_stored_cache(monkeypatch, tabs: int = 40):
    """Fenster, dessen Konto einen nennenswerten Bestand auf der Platte
    hat — Ausgangslage für die Tests des Überschreibschutzes."""
    from poe_view.services import data_cache

    stored = data_cache.CachedData()
    stored.account_name = "TestAccount#1234"
    stored.characters = [make_char("RichChar", "Standard")]
    stored.stash_trees = {"Standard": [_make_leaf(f"t{i}", f"Tab {i}") for i in range(tabs)]}
    stored.items_by_league = {"Standard": {f"t{i}": [] for i in range(tabs)}}
    data_cache.save(stored, data_cache.path_for("TestAccount#1234"))

    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_logged_in("TestAccount#1234")  # laedt den Stand und merkt sich den Umfang
    return win


def test_persist_refuses_to_shrink_the_stored_cache_drastically(qapp, monkeypatch) -> None:
    """Praeventiver Schutz nach zwei echten Datenverlusten (FALLSTRICKE
    #62): Beide entstanden dadurch, dass ein magerer Speicherstand einen
    reichen Dateistand ueberschrieb. Der Waechter arbeitet bewusst
    pfad-unabhaengig — hier wird der Speicher direkt geleert, ohne dass
    einer der bekannten Fehlerpfade beteiligt waere."""
    from poe_view.services import data_cache

    win = _window_with_stored_cache(monkeypatch)
    assert win._persisted_scale >= win._CACHE_GUARD_MIN

    win._items = {}          # Einbruch, egal aus welchem Grund
    win._all_characters = []
    win._character_items = {}
    win._persist_cache()
    win._cache_writer.flush()

    on_disk = data_cache.load(data_cache.path_for("TestAccount#1234"))
    assert on_disk is not None
    assert len(on_disk.items_by_league["Standard"]) == 40  # unveraendert
    assert [c.name for c in on_disk.characters] == ["RichChar"]

    win.worker.stop()
    win.worker.wait(5000)


def test_persist_still_writes_normal_growth_and_moderate_shrinking(qapp, monkeypatch) -> None:
    """Der Waechter darf den Normalbetrieb nicht behindern: Wachstum immer,
    und massvolles Schrumpfen (hier auf die Haelfte, z. B. weil Faecher im
    Spiel entfernt wurden) ebenfalls."""
    from poe_view.services import data_cache

    win = _window_with_stored_cache(monkeypatch)

    win._items = {"Standard": {f"t{i}": [] for i in range(60)}}  # gewachsen
    win._persist_cache()
    win._cache_writer.flush()
    assert len(data_cache.load(data_cache.path_for("TestAccount#1234"))
               .items_by_league["Standard"]) == 60

    win._items = {"Standard": {f"t{i}": [] for i in range(30)}}  # halbiert
    win._persist_cache()
    win._cache_writer.flush()
    assert len(data_cache.load(data_cache.path_for("TestAccount#1234"))
               .items_by_league["Standard"]) == 30

    win.worker.stop()
    win.worker.wait(5000)


def test_persist_guard_does_not_block_a_fresh_account(qapp, monkeypatch) -> None:
    """Ein Konto ohne gespeicherten Bestand muss ganz normal anwachsen
    koennen — der Schutz greift erst ab einem nennenswerten Stand."""
    from poe_view.services import data_cache

    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_logged_in("FreshAccount#9999")
    assert win._persisted_scale == 0

    win._all_characters = [make_char("FirstChar", "Standard")]
    win._persist_cache()
    win._cache_writer.flush()

    on_disk = data_cache.load(data_cache.path_for("FreshAccount#9999"))
    assert on_disk is not None and [c.name for c in on_disk.characters] == ["FirstChar"]

    win.worker.stop()
    win.worker.wait(5000)


def test_persist_after_a_logout_login_cycle_keeps_the_stored_data(qapp, monkeypatch) -> None:
    """Der eigentliche Schaden entstand erst beim Zurückschreiben: solange
    der Speicher nach dem Wieder-Anmelden leer blieb, machte der nächste
    ``_persist_cache()`` aus 2295 Fächern eine leere Datei. Prüft das
    Ergebnis auf der Platte, nicht nur den Speicher."""
    from poe_view.services import data_cache

    stored = data_cache.CachedData()
    stored.account_name = "TestAccount#1234"
    stored.characters = [make_char("RichChar", "Standard")]
    stored.stash_trees = {"Standard": [_make_leaf("t1", "Currency 1")]}
    data_cache.save(stored, data_cache.path_for("TestAccount#1234"))

    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_logged_in("TestAccount#1234")
    win._on_logout_clicked()
    win._on_logged_in("TestAccount#1234")
    win._persist_cache()
    win._cache_writer.flush()

    on_disk = data_cache.load(data_cache.path_for("TestAccount#1234"))
    assert on_disk is not None
    assert [c.name for c in on_disk.characters] == ["RichChar"]
    assert "Standard" in on_disk.stash_trees

    win.worker.stop()
    win.worker.wait(5000)


def test_restore_cached_data_does_not_leak_a_different_accounts_legacy_file(
        qapp, monkeypatch) -> None:
    """Gegenstück zum Fallback: gehört die alte gemeinsame Datei einem
    ANDEREN Konto als dem Hinweis, darf sie NICHT übernommen werden —
    sonst würde ein echter Kontowechsel, dessen neue Datei aus einer
    kurzen Sitzung noch fehlt, fälschlich die Daten des VORHERIGEN
    Kontos zeigen."""
    from poe_view import config
    from poe_view.services import data_cache
    from PySide6.QtCore import QSettings

    legacy_data = data_cache.CachedData()
    legacy_data.account_name = "Alice"
    legacy_data.characters = [make_char("AliceChar", "Standard")]
    data_cache.save(legacy_data)
    QSettings(str(config.APP_DATA_DIR / "ui-settings.ini"),
             QSettings.Format.IniFormat).setValue("account/last_active", "Bob")

    win = MainWindow()

    assert win._account_name == ""
    assert win._all_characters == []

    win.worker.stop()
    win.worker.wait(5000)


def test_maybe_auto_refresh_also_refreshes_currently_displayed_tab(qapp, monkeypatch) -> None:
    """das gerade angezeigte Fach soll live gehalten werden — auch wenn es
    frisch geladen ist (die 1-Tag-Schonfrist gilt nur für den Sweep). Der
    Sweep-Kandidat folgt im NÄCHSTEN Takt, nicht im selben."""
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
    win._refresh_mode_pending = False
    win._maybe_auto_refresh()

    assert [job.stash_id for job in submitted] == ["current", "stale"]
    assert all(job.silent is True for job in submitted)

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_wechselt_zwischen_offener_ansicht_und_sweep_ab(qapp, monkeypatch) -> None:
    """Über mehrere Takte hinweg müssen sich beide Pflichten sauber
    abwechseln — sonst verhungert eine von beiden. Genau das war der
    Befund vom 2026-08-21: 49 Abrufe desselben offenen Fachs in Folge, kein
    einziger Sweep dazwischen."""
    win = MainWindow()
    win._current_league = "Standard"
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    win._leaf_stashes = [_make_leaf("current", "Current"), _make_leaf("a", "A"), _make_leaf("b", "B")]
    win._last_loaded["Standard"] = {"current": old, "a": old, "b": old}
    win._current_stash_id = "current"

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    for _ in range(4):
        win._maybe_auto_refresh()
        # Der jeweils frisch geladene Kandidat wird "jung" — sonst bliebe
        # er ewig der älteste und der Sweep träte auf der Stelle.
        win._last_loaded["Standard"][submitted[-1].stash_id] = \
            datetime.now(timezone.utc).isoformat()
        win._refresh_mode_pending = False

    ids = [job.stash_id for job in submitted]
    assert ids[0] == "current" and ids[2] == "current"  # jeder zweite Takt: offene Ansicht
    assert set(ids[1::2]) == {"a", "b"}                 # dazwischen wandert der Sweep weiter

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_sweep_faellt_auf_den_stash_rundlauf_zurueck(qapp, monkeypatch) -> None:
    """Der eigentliche Befund vom 2026-08-21: Ist jedes Fach jünger als
    einen Tag (durchgeladene Liga = Normalfall), liefert
    ``_pick_auto_refresh_candidate`` NICHTS mehr und der Sweep stand 76
    Minuten still. Jetzt übernimmt der Rundlauf des Stash-Modus."""
    win = MainWindow()
    win._current_league = "Standard"
    fresh = datetime.now(timezone.utc).isoformat()
    win._leaf_stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    win._last_loaded["Standard"] = {"t1": fresh, "t2": fresh}
    win._current_character_name = "WitchOfPeter"  # offene Ansicht ist ein Charakter

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    assert win._pick_auto_refresh_candidate() is None  # 1-Tag-Regel hat nichts mehr
    assert win._drive_auto_sweep() is True             # der Rundlauf schon
    assert submitted[-1].stash_id in {"t1", "t2"}

    win.worker.stop()
    win.worker.wait(5000)


@pytest.mark.parametrize("mode", ["auto", "single", "stash"])
def test_taktende_modi_schicken_in_der_zweitinstanz_nichts_los(qapp, monkeypatch, mode) -> None:
    """Zweitinstanz auf demselben Konto: Der Worker verwirft jeden Job
    lautlos (§_skip_read_only) und meldet nichts zurück. Ohne Guard setzte
    der Takt ``_refresh_mode_pending`` und wartete für den Rest der
    Sitzung auf eine Antwort, die nie kommt — die Kette wäre tot."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    win._last_loaded["Standard"] = {
        "t1": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()}
    win._current_stash_id = "t1"
    win._refresh_mode = mode
    win._read_only = True

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "headroom_fraction", lambda: 1.0)

    win._drive_refresh_mode()

    assert submitted == []
    assert win._refresh_mode_pending is False  # Kette bleibt lauffähig

    win.worker.stop()
    win.worker.wait(5000)


def test_auto_sweep_zieht_die_fachliste_am_rundenende_nach(qapp, monkeypatch) -> None:
    """Mit dem Rückfall auf den Stash-Rundlauf erbt der Auto-Modus auch
    dessen Rundenabschluss: ``_stash_mode_list_refresh_due``. Würde Auto
    das Flag ignorieren, bliebe eine im Spiel umsortierte oder erweiterte
    Truhe unentdeckt — und das Flag stünde für immer, weil nur der
    Stash-Modus es je zurücksetzt."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    win._last_loaded["Standard"] = {"t1": datetime.now(timezone.utc).isoformat()}
    win._stash_mode_list_refresh_due = True

    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    assert win._drive_auto_sweep() is True
    assert isinstance(submitted[-1], FetchStashListJob)
    assert submitted[-1].silent is True
    assert win._stash_mode_list_refresh_due is False  # nur einmal, nicht in Endlosschleife

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


# --- Ordner: flache API-Liste in echte Verschachtelung bringen (#38) ----- #

def _folder(folder_id: str, name: str, index: int) -> StashTab:
    return StashTab.model_validate({"id": folder_id, "name": name, "type": "Folder",
                                     "index": index, "metadata": {"folder": True}})


def _in_folder(stash_id: str, name: str, folder_id: str, index: int) -> StashTab:
    return StashTab.model_validate({"id": stash_id, "name": name, "type": "CurrencyStash",
                                     "index": index, "folder": folder_id, "metadata": {}})


def test_folder_members_are_nested_under_their_folder(qapp) -> None:
    """GGG liefert die Fächer flach; ein Fach im Ordner trägt nur ``folder``.

    Die Mitglieder-Indizes setzen die Zählung ihres Ordners fort und
    überschneiden sich zwischen Ordnern (echte Standard-Liga: Ordner "Special"
    idx=11 mit Mitgliedern 12–24, Ordner "M*" idx=12 mit 13–17). In der nach
    index sortierten API-Liste schiebt sich der zweite Ordner deshalb mitten
    zwischen die Mitglieder des ersten — genau die Abweichung zur Reihenfolge
    im Spiel (FALLSTRICKE #38)."""
    flat = [
        StashTab.model_validate({"id": "a", "name": "Erstes Fach", "index": 0,
                                 "type": "CurrencyStash", "metadata": {}}),
        _folder("dir1", "Ordner 1", 1),
        _in_folder("f1", "Drin 1", "dir1", 2),
        _folder("dir2", "Ordner 2", 2),        # gleicher index wie f1
        _in_folder("f2", "Drin 2", "dir1", 3),
        _in_folder("g1", "Drin A", "dir2", 3),
        _in_folder("g2", "Drin B", "dir2", 4),
    ]

    top = MainWindow._nest_folder_members(flat)

    assert [s.id for s in top] == ["a", "dir1", "dir2"]
    assert [c.id for c in top[1].children] == ["f1", "f2"]
    assert [c.id for c in top[2].children] == ["g1", "g2"]


def test_folder_member_known_from_an_earlier_fetch_is_not_duplicated(qapp) -> None:
    """In SSF Ruthless standen 47 Fächer doppelt im Baum: einmal flach oben,
    einmal im Ordner, nachdem dieser abgerufen worden war. Der frische Eintrag
    ersetzt den bekannten, entdeckte Unter-Tabs bleiben erhalten."""
    folder = _folder("dir", "Ordner", 0)
    known = _in_folder("f1", "Alter Name", "dir", 0)
    known.children = [_map_child("c1", "f1", "Beach Map")]
    folder.children = [known]
    fresh = _in_folder("f1", "Neuer Name", "dir", 0)

    top = MainWindow._nest_folder_members([folder, fresh])

    assert [s.id for s in top] == ["dir"]
    assert len(top[0].children) == 1, "kein zweiter Eintrag für dasselbe Fach"
    assert top[0].children[0].name == "Neuer Name"
    assert [c.id for c in top[0].children[0].children] == ["c1"]


def test_folder_member_with_unknown_folder_id_stays_visible(qapp) -> None:
    """Zeigt ``folder`` ins Leere, bleibt das Fach oben stehen — an der
    falschen Stelle sichtbar ist besser als unsichtbar."""
    orphan = _in_folder("f1", "Waise", "gibt-es-nicht", 0)

    top = MainWindow._nest_folder_members([_folder("dir", "Ordner", 0), orphan])

    assert [s.id for s in top] == ["dir", "f1"]


def test_stash_list_refresh_does_not_resurrect_removed_folder_members(qapp) -> None:
    """Ein Ordner wird jetzt aus der Liste selbst gefüllt — ein LEERER Ordner
    ist damit echt leer. Ohne die is_folder-Ausnahme im Merge holte er sich
    seine alten Mitglieder zurück, im Spiel gelöschte Fächer tauchten wieder auf."""
    win = MainWindow()
    win._current_league = "Standard"
    old_folder = _folder("dir", "Ordner", 0)
    old_folder.children = [_in_folder("f1", "Rausgezogen", "dir", 0)]
    win._stash_trees["Standard"] = [old_folder]

    # Frische Liste: Ordner noch da, aber ohne Mitglieder
    win._on_stash_list([_folder("dir", "Ordner", 0)], silent=False)

    assert win._stash_trees["Standard"][0].children == []

    win.worker.stop()
    win.worker.wait(5000)


def test_stash_list_nests_folders_end_to_end(qapp) -> None:
    """Der ganze Weg: flache API-Liste rein, verschachtelter Baum raus —
    inklusive Pos.-Spalte, die weiter jedes echte Fach zählt (Ordner selbst
    bekommen keine Nummer)."""
    win = MainWindow()
    win._current_league = "Standard"
    flat = [
        StashTab.model_validate({"id": "a", "name": "Fach A", "index": 0,
                                 "type": "CurrencyStash", "metadata": {}}),
        _folder("dir", "Ordner", 1),
        _in_folder("f1", "Drin 1", "dir", 0),
        _in_folder("f2", "Drin 2", "dir", 1),
    ]

    win._on_stash_list(flat, silent=False)

    tree = win._stash_trees["Standard"]
    assert [s.id for s in tree] == ["a", "dir"]
    assert [c.id for c in tree[1].children] == ["f1", "f2"]
    assert win._tab_positions() == {"a": 1, "f1": 2, "f2": 3}
    assert win.tree.topLevelItemCount() == 2

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
    win._on_stash_list(fresh, silent=False)

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


def test_load_all_items_starts_with_the_oldest_or_never_loaded_tab(qapp, monkeypatch) -> None:
    """Peter: "sollte mit den ältesten bzw. noch nie geholten Stash-Tabs
    loslegen" — bricht er über "Abbrechen" vorzeitig ab, sollen die
    dringendsten Fächer schon durch sein, nicht die per Zufall der
    Truhen-Reihenfolge nach vorne gerutschten."""
    win = MainWindow()
    win._current_league = "Standard"
    stale_map = StashTab.model_validate({"id": "stale_map", "name": "M", "type": "MapStash",
                                         "metadata": {}})
    never_loaded = StashTab.model_validate({"id": "never", "name": "N",
                                            "type": "CurrencyStash", "metadata": {}})
    fresh_map = StashTab.model_validate({"id": "fresh_map", "name": "M2", "type": "MapStash",
                                         "metadata": {}})
    # Truhen-Reihenfolge bewusst NICHT nach Alter — die Sortierung muss sie umstellen.
    win._stash_trees["Standard"] = [stale_map, never_loaded, fresh_map]
    win._leaf_stashes = [stale_map, never_loaded, fresh_map]
    win._items["Standard"] = {"stale_map": [], "fresh_map": []}  # beide Spezial-Tabs "im Cache"
    now = datetime.now(timezone.utc)
    win._last_loaded["Standard"] = {
        "stale_map": (now - timedelta(days=10)).isoformat(),
        "fresh_map": (now - timedelta(minutes=5)).isoformat(),
        # "never" hat keinen last_loaded-Eintrag
    }
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._load_all_items()

    assert len(submitted) == 1
    assert [s.id for s in submitted[0].stashes] == ["never", "stale_map", "fresh_map"]

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


# --- Spalten-Reihenfolge über den Settings-Dialog (Peter, 2026-08-01) ---

def test_default_column_config_has_every_configurable_column_visible_except_type(qapp) -> None:
    win = MainWindow()
    config = win._default_column_config()
    assert [name for name, _ in config] == list(CONFIGURABLE_COLUMNS)
    assert dict(config)["Type"] is False
    assert all(visible for name, visible in config if name != "Type")

    win.worker.stop()
    win.worker.wait(5000)


def test_applying_a_column_config_reorders_the_header(qapp) -> None:
    """Reihenfolge wird über die VISUELLE Header-Position umgesetzt, nicht
    über die (fixen) logischen Spalten-Indizes — Sortierung/Filter greifen
    weiter über den logischen Index."""
    from poe_view.ui.item_table import COLUMNS

    win = MainWindow()
    reordered = [("Value", True), ("Name", True)] + [
        (name, True) for name in CONFIGURABLE_COLUMNS if name not in ("Value", "Name")]
    win._apply_column_config(reordered)

    header = win.table.horizontalHeader()
    value_visual = header.visualIndex(COLUMNS.index("Value"))
    name_visual = header.visualIndex(COLUMNS.index("Name"))
    assert value_visual == 1  # direkt nach der fix ersten Tab-Spalte (Index 0)
    assert name_visual == 2

    win.worker.stop()
    win.worker.wait(5000)


def test_column_order_persists_across_restart(qapp) -> None:
    from poe_view.ui.item_table import COLUMNS

    win = MainWindow()
    reordered = [("Value", True)] + [
        (name, True) for name in CONFIGURABLE_COLUMNS if name != "Value"]
    win._save_column_config(reordered)
    win._apply_column_config(reordered)
    win.worker.stop()
    win.worker.wait(5000)

    win2 = MainWindow()  # "Neustart": liest ui-settings.ini (im Test: tmp_path)
    assert win2._load_column_config() == reordered
    header = win2.table.horizontalHeader()
    assert header.visualIndex(COLUMNS.index("Value")) == 1

    win2.worker.stop()
    win2.worker.wait(5000)


def test_column_config_migrates_the_old_hidden_columns_setting(qapp) -> None:
    """Vor der Reihenfolge-Funktion (Peter, 2026-08-01) gab es nur eine
    reine Sichtbarkeits-Menge ("item_table/hidden_columns"). Bestehende
    Installationen sollen diese Auswahl behalten, nur eben jetzt als
    vollständige, geordnete Liste."""
    win = MainWindow()
    win._settings().setValue("item_table/hidden_columns", "Mods;Value")
    config = win._load_column_config()
    assert dict(config)["Mods"] is False
    assert dict(config)["Value"] is False
    assert dict(config)["Name"] is True

    win.worker.stop()
    win.worker.wait(5000)


def test_column_config_appends_columns_missing_from_a_stored_config(qapp) -> None:
    """Falls künftig eine neue Spalte hinzukommt, die im gespeicherten
    JSON-Stand noch nicht vorkommt, soll sie sichtbar auftauchen statt
    stillschweigend zu verschwinden."""
    win = MainWindow()
    partial = [{"name": "Name", "visible": True}, {"name": "Value", "visible": False}]
    win._settings().setValue("item_table/column_config", json.dumps(partial))
    config = win._load_column_config()
    names = [name for name, _ in config]
    assert names[:2] == ["Name", "Value"]
    assert set(names) == set(CONFIGURABLE_COLUMNS)
    assert dict(config)["Type"] is True  # neu angehängt, sichtbar

    win.worker.stop()
    win.worker.wait(5000)


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


def test_reloading_a_unique_stash_keeps_the_names_of_its_children(qapp) -> None:
    """Regression (Peter, 2026-07-30, Screenshot): nach einem "Load All
    Tabs"-Lauf hießen fast alle Unique-Fächer wieder "UniqueStash" — nur das
    eine, dessen Items NACH dem Eltern-Abruf durchkamen, hieß noch
    "Sceptre". Ein erneuter Abruf des Eltern-Fachs liefert die Kinder neu
    und in der API sind sie namenlos; unsere Kategorie-Stempel müssen
    mitwandern."""
    win = MainWindow()
    win._current_league = "Standard"
    unique = StashTab.model_validate({"id": "u1", "name": "Uniq", "type": "UniqueStash",
                                      "metadata": {}})
    win._stash_trees["Standard"] = [unique]
    win._activate_stash_tree(win._stash_trees["Standard"])
    win._on_stash_children("Standard", "u1", "Uniq", [_unique_child("c1")], silent=False)
    # Waffenklasse steht bei GGG als erste, wertlose Property (§item_category).
    sceptres = [Item.model_validate({"typeLine": "Void Sceptre", "baseType": "Void Sceptre",
                                     "frameType": 3,
                                     "properties": [{"name": "Sceptre", "values": []}]})]
    win._on_stash_items("Standard", "c1", "UniqueStash", sceptres, silent=True)
    assert win.tree._stash_nodes["c1"].text(0) == "Sceptre"

    # Eltern-Fach nochmal abrufen — die API liefert das Kind wieder namenlos.
    win._on_stash_children("Standard", "u1", "Uniq", [_unique_child("c1")], silent=False)

    assert win._stash_trees["Standard"][0].children[0].metadata["poeview_category"] == "Sceptre"
    assert win.tree._stash_nodes["c1"].text(0) == "Sceptre"

    win.worker.stop()
    win.worker.wait(5000)


def test_reloading_a_unique_stash_restamps_from_cached_items(qapp) -> None:
    """Heilt bereits beschädigte Caches: liegen die Items eines namenlosen
    Fachs noch im Cache, wird die Kategorie beim nächsten Eltern-Abruf neu
    vergeben — ohne einen zusätzlichen Request."""
    win = MainWindow()
    win._current_league = "Standard"
    unique = StashTab.model_validate({"id": "u1", "name": "Uniq", "type": "UniqueStash",
                                      "metadata": {}})
    win._stash_trees["Standard"] = [unique]
    win._activate_stash_tree(win._stash_trees["Standard"])
    # Kaputter Cache-Zustand: Items da, Stempel weg.
    win._items["Standard"] = {"c1": [Item.model_validate(
        {"typeLine": "Amethyst Ring", "baseType": "Amethyst Ring", "frameType": 3})]}

    win._on_stash_children("Standard", "u1", "Uniq", [_unique_child("c1")], silent=False)

    assert win.tree._stash_nodes["c1"].text(0) == "Ring"

    win.worker.stop()
    win.worker.wait(5000)


def test_reloading_a_special_tab_keeps_fresh_api_metadata(qapp) -> None:
    """Nur die selbst gestempelten ``poeview_``-Schlüssel wandern mit —
    echte API-Felder muss die frische Antwort gewinnen, sonst klebte z. B.
    eine im Spiel geleerte Item-Anzahl am alten Stand."""
    win = MainWindow()
    win._current_league = "Standard"
    unique = StashTab.model_validate({"id": "u1", "name": "Uniq", "type": "UniqueStash",
                                      "metadata": {}})
    old = _unique_child("c1")            # metadata.items == 2
    old.metadata["poeview_category"] = "Ring"
    unique.children = [old]
    win._stash_trees["Standard"] = [unique]
    win._activate_stash_tree(win._stash_trees["Standard"])
    fresh = StashTab.model_validate({"id": "c1", "name": "", "parent": "u1",
                                     "type": "UniqueStash", "metadata": {"items": 7}})

    win._on_stash_children("Standard", "u1", "Uniq", [fresh], silent=False)

    child = win._stash_trees["Standard"][0].children[0]
    assert child.metadata["poeview_category"] == "Ring"
    assert child.metadata["items"] == 7

    win.worker.stop()
    win.worker.wait(5000)


def test_unique_child_with_remove_only_suffix_still_gets_stamped(qapp) -> None:
    """Regression (Peter, 2026-07-30, Screenshot): ein Unique-Stash-Kind mit
    name=" (Remove-only)" (führendes Leerzeichen — GGG-Suffix, kein echter
    Name) galt für ``tab.name.strip()`` fälschlich als "schon benannt" und
    wurde nie gestempelt — jedes Kind eines Remove-only-Uniq-Tabs zeigte
    dadurch nur noch "(Remove-only)" statt z. B. "Ring (Remove-only)"."""
    win = MainWindow()
    win._current_league = "Standard"
    unique = StashTab.model_validate({"id": "u1", "name": "Uniq (Remove-only)",
                                      "type": "UniqueStash", "metadata": {}})
    ro_child = StashTab.model_validate({"id": "c1", "name": " (Remove-only)", "parent": "u1",
                                        "type": "UniqueStash", "metadata": {"items": 2}})
    unique.children = [ro_child]
    win._stash_trees["Standard"] = [unique]
    win._activate_stash_tree(win._stash_trees["Standard"])
    assert win.tree._stash_nodes["c1"].text(0) == "UniqueStash (Remove-only)"

    ring = Item.model_validate({"typeLine": "Amethyst Ring", "baseType": "Amethyst Ring",
                                "frameType": 3})
    win._on_stash_items("Standard", "c1", "UniqueStash (Remove-only)", [ring], silent=True)

    tab = win._stash_trees["Standard"][0].children[0]
    assert tab.metadata["poeview_category"] == "Ring"
    assert win.tree._stash_nodes["c1"].text(0) == "Ring (Remove-only)"

    win.worker.stop()
    win.worker.wait(5000)


def test_restamp_from_cache_handles_remove_only_suffix_children(qapp) -> None:
    """Dieselbe Suffix-Falle in der Cache-Heilung (§_restamp_from_cached_items):
    ohne die Unterscheidung hätte ein namenloses Remove-only-Kind mit
    bereits gecachten Items nie eine Kategorie bekommen."""
    win = MainWindow()
    win._current_league = "Standard"
    unique = StashTab.model_validate({"id": "u1", "name": "Uniq", "type": "UniqueStash",
                                      "metadata": {}})
    win._stash_trees["Standard"] = [unique]
    win._activate_stash_tree(win._stash_trees["Standard"])
    win._items["Standard"] = {"c1": [Item.model_validate(
        {"typeLine": "Amethyst Ring", "baseType": "Amethyst Ring", "frameType": 3})]}
    ro_child = StashTab.model_validate({"id": "c1", "name": " (Remove-only)", "parent": "u1",
                                        "type": "UniqueStash", "metadata": {"items": 2}})

    win._on_stash_children("Standard", "u1", "Uniq", [ro_child], silent=False)

    assert win.tree._stash_nodes["c1"].text(0) == "Ring (Remove-only)"

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

def test_search_filter_is_debounced_not_applied_immediately(qapp) -> None:
    """Peter: bei ~20000 Items in "All Tabs" machte sofortiges Filtern bei
    jedem Tastendruck die Suche langwierig. Der eigentliche Zeilen-Filter
    läuft deshalb gedämpft (SEARCH_DEBOUNCE_MS) statt synchron mit jedem
    textChanged. ``_search_all_active`` wird hier schon vorab gesetzt, damit
    der Tastendruck nicht zusätzlich ``_enter_search_all()`` auslöst (das
    würde die manuell gesetzten Items mit dem — hier leeren — Liga-Aggregat
    überschreiben und ist nicht Gegenstand dieses Tests)."""
    win = MainWindow()
    win._search_all_active = True
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb"}),
        Item.model_validate({"typeLine": "Exalted Orb"}),
    ])
    assert win.proxy.rowCount() == 2

    win._filter_edit.setText("chaos")

    assert win.proxy.rowCount() == 2  # noch nicht angewendet
    assert win._search_debounce.isActive()
    win._apply_debounced_search_filter()
    assert win.proxy.rowCount() == 1  # jetzt schon

    win.worker.stop()
    win.worker.wait(5000)


def test_search_debounce_uses_the_configured_interval(qapp) -> None:
    win = MainWindow()

    assert win._search_debounce.interval() == MainWindow.SEARCH_DEBOUNCE_MS
    assert win._search_debounce.isSingleShot()

    win.worker.stop()
    win.worker.wait(5000)


# --- "On demand"-Suche fuer sehr grosse Ligen (FALLSTRICKE #40) ---------- #

def _setup_large_league(win, item_count: int) -> None:
    win._current_league = "Standard"
    t1 = _make_leaf("t1", "Currency 1")
    win._stash_trees["Standard"] = [t1]
    win._leaf_stashes = [t1]
    win._items["Standard"] = {
        "t1": [Item.model_validate({"typeLine": f"Item {i}"}) for i in range(item_count)]}


def test_enter_search_all_switches_to_on_demand_above_the_limit(qapp, monkeypatch) -> None:
    """Oberhalb LIVE_SEARCH_ITEM_LIMIT baut die Suche das komplette
    ungefilterte Aggregat NICHT als Qt-Modell auf (kostet bei sehr großen
    Ligen mehrere Sekunden, Peter 2026-07-28: "andere haben noch viel
    größere Truhen") — nur zwischenspeichern und auf den Dämpfer warten."""
    monkeypatch.setattr(MainWindow, "LIVE_SEARCH_ITEM_LIMIT", 3)
    win = MainWindow()
    _setup_large_league(win, 5)

    win._filter_edit.setText("item")

    assert win._large_search_items is not None
    assert win.table_model.rowCount() == 0  # noch nicht befüllt
    assert "5 items in this league" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_below_the_limit_stays_in_live_mode(qapp, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "LIVE_SEARCH_ITEM_LIMIT", 10)
    win = MainWindow()
    _setup_large_league(win, 5)

    win._filter_edit.setText("item")

    assert win._large_search_items is None
    assert win.table_model.rowCount() == 5  # sofort komplett befüllt, wie bisher

    win.worker.stop()
    win.worker.wait(5000)


def test_large_search_populates_only_matches_after_the_debounce(qapp, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "LIVE_SEARCH_ITEM_LIMIT", 3)
    win = MainWindow()
    win._current_league = "Standard"
    t1 = _make_leaf("t1", "Currency 1")
    win._stash_trees["Standard"] = [t1]
    win._leaf_stashes = [t1]
    win._items["Standard"] = {"t1": [
        Item.model_validate({"typeLine": "Chaos Orb"}),
        Item.model_validate({"typeLine": "Exalted Orb"}),
        Item.model_validate({"typeLine": "Divine Orb"}),
        Item.model_validate({"typeLine": "Regal Orb"}),
    ]}

    win._filter_edit.setText("chaos")
    assert win.table_model.rowCount() == 0  # Dämpfer: noch nicht angewendet

    win._apply_debounced_search_filter()

    assert win.table_model.rowCount() == 1
    assert win.table_model.item_at(0).typeLine == "Chaos Orb"
    assert "1 of 4 items match" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_large_search_wildcard_shows_everything(qapp, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "LIVE_SEARCH_ITEM_LIMIT", 3)
    win = MainWindow()
    _setup_large_league(win, 5)

    win._filter_edit.setText("*")
    win._apply_debounced_search_filter()

    assert win.table_model.rowCount() == 5

    win.worker.stop()
    win.worker.wait(5000)


def test_large_search_shows_a_wait_cursor_while_filtering(qapp, monkeypatch) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(MainWindow, "LIVE_SEARCH_ITEM_LIMIT", 3)
    win = MainWindow()
    _setup_large_league(win, 5)

    calls: list[tuple] = []
    monkeypatch.setattr(QApplication, "setOverrideCursor",
                        lambda shape: calls.append(("set", shape)))
    monkeypatch.setattr(QApplication, "restoreOverrideCursor",
                        lambda: calls.append(("restore",)))

    win._filter_edit.setText("item")
    win._apply_debounced_search_filter()

    assert calls[0] == ("set", Qt.CursorShape.WaitCursor)
    assert calls[-1] == ("restore",)

    win.worker.stop()
    win.worker.wait(5000)


def test_clearing_the_search_field_leaves_on_demand_mode(qapp, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "LIVE_SEARCH_ITEM_LIMIT", 3)
    win = MainWindow()
    _setup_large_league(win, 5)
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._filter_edit.setText("item")
    assert win._large_search_items is not None

    win._filter_edit.setText("")

    assert win._large_search_items is None
    assert not win._search_all_active

    win.worker.stop()
    win.worker.wait(5000)


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
    win._apply_debounced_search_filter()         # Zeilen-Filter läuft gedämpft, hier erzwungen
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


def test_column_filter_edit_offers_the_columns_distinct_values(qapp) -> None:
    """Peter, 2026-08-02: "eine Art Autovervollständigen mit Combobox über
    die Items in der Spalte" — das Eingabefeld im Header-Rechtsklick-Menü
    bekommt einen QCompleter über die tatsächlich vorkommenden Werte."""
    from PySide6.QtCore import Qt
    from poe_view.ui.item_table import BASE_COL
    win = MainWindow()
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "baseType": "Chaos Orb"}),
        Item.model_validate({"typeLine": "Exalted Orb", "baseType": "Exalted Orb"}),
    ])

    edit = win._build_column_filter_edit(BASE_COL)

    completer = edit.completer()
    assert completer is not None
    model = completer.model()
    values = {model.index(r, 0).data() for r in range(model.rowCount())}
    assert values == {"Chaos Orb", "Exalted Orb"}
    assert completer.caseSensitivity() == Qt.CaseSensitivity.CaseInsensitive
    assert completer.filterMode() == Qt.MatchFlag.MatchContains

    win.worker.stop()
    win.worker.wait(5000)


def test_column_filter_edit_has_no_completer_for_an_empty_table(qapp) -> None:
    """Keine Werte -> kein leerer/nutzloser Completer am Feld."""
    from poe_view.ui.item_table import BASE_COL
    win = MainWindow()

    edit = win._build_column_filter_edit(BASE_COL)

    assert edit.completer() is None

    win.worker.stop()
    win.worker.wait(5000)


def test_column_filter_edit_keeps_the_currently_active_filter_text(qapp) -> None:
    from poe_view.ui.item_table import BASE_COL
    win = MainWindow()
    win.table_model.set_items([Item.model_validate({"typeLine": "Chaos Orb", "baseType": "Chaos Orb"})])
    win._apply_column_filter(BASE_COL, "Chaos")

    edit = win._build_column_filter_edit(BASE_COL)

    assert edit.text() == "Chaos"

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


# --- View-relative Spalten-Filter (Tab/Position) beim View-Wechsel löschen
# (Peter, 2026-08-02: "Tab->MainInventory gibt es im Stash nicht und es
# werden deshalb keine Items angezeigt") ------------------------------- #

def test_switching_from_character_to_stash_clears_a_stale_tab_filter(qapp, monkeypatch) -> None:
    """Der genaue von Peter gemeldete Fall: ein Tab-Spalten-Filter auf
    einen Charakter-Slot-Namen ("MainInventory") überlebte bisher den
    Wechsel zu einer Truhe, in der kein Fach je so heißt — alle Items
    verschwanden lautlos."""
    from poe_view.ui.item_table import TAB_COL
    win = MainWindow()
    win._current_league = "Standard"
    win._character_items["WitchOfPeter"] = [
        Item.model_validate({"typeLine": "Chaos Orb", "inventoryId": "MainInventory"})]
    win._on_character_selected(make_char("WitchOfPeter", "Standard"))
    win._apply_column_filter(TAB_COL, "MainInventory")
    assert win.proxy.rowCount() == 1  # Filter passt hier noch

    t1 = _make_leaf("t1", "Currency 1")
    win._leaf_stashes = [t1]
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Exalted Orb"})]}
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._on_stash_selected("t1", "Currency 1")

    assert win.proxy.filtered_columns() == set()
    assert win.proxy.rowCount() == 1  # Item ist wieder sichtbar

    win.worker.stop()
    win.worker.wait(5000)


def test_switching_between_stash_tabs_also_clears_a_stale_tab_filter(qapp, monkeypatch) -> None:
    """Dieselbe Falle tritt auch zwischen zwei Truhenfächern auf, nicht nur
    Charakter->Stash: ein Tab-Filter auf den Namen von Fach A passt bei
    Fach B im Zweifel nicht."""
    from poe_view.ui.item_table import TAB_COL
    win = MainWindow()
    win._current_league = "Standard"
    t1 = _make_leaf("t1", "Currency 1")
    t2 = _make_leaf("t2", "Currency 2")
    win._leaf_stashes = [t1, t2]
    win._items["Standard"] = {
        "t1": [Item.model_validate({"typeLine": "Chaos Orb"})],
        "t2": [Item.model_validate({"typeLine": "Exalted Orb"})],
    }
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_stash_selected("t1", "Currency 1")
    win._apply_column_filter(TAB_COL, "Currency 1")

    win._on_stash_selected("t2", "Currency 2")

    assert win.proxy.filtered_columns() == set()
    assert win.proxy.rowCount() == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_view_switch_does_not_clear_item_intrinsic_filters(qapp, monkeypatch) -> None:
    """Ein Filter auf einer item-eigenen Spalte (Name, Base, Value, …) ist
    NICHT view-relativ und soll beim Fach-/Charakter-Wechsel absichtlich
    bestehen bleiben — sonst verliert man ihn beim Vergleichen mehrerer
    Fächer nach jedem Klick."""
    from poe_view.ui.item_table import COLUMNS
    win = MainWindow()
    win._current_league = "Standard"
    t1 = _make_leaf("t1", "Currency 1")
    t2 = _make_leaf("t2", "Currency 2")
    win._leaf_stashes = [t1, t2]
    win._items["Standard"] = {
        "t1": [Item.model_validate({"typeLine": "Chaos Orb"})],
        "t2": [Item.model_validate({"typeLine": "Exalted Orb"})],
    }
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_stash_selected("t1", "Currency 1")
    win._apply_column_filter(COLUMNS.index("Name"), "Chaos")

    win._on_stash_selected("t2", "Currency 2")

    assert win.proxy.filtered_columns() == {COLUMNS.index("Name")}
    assert win.proxy.rowCount() == 0  # "Exalted Orb" passt nicht zu "Chaos" — Filter wirkt weiter

    win.worker.stop()
    win.worker.wait(5000)


def test_entering_the_aggregate_view_clears_a_stale_tab_filter(qapp, monkeypatch) -> None:
    from poe_view.ui.item_table import TAB_COL
    win = MainWindow()
    win._current_league = "Standard"
    win._all_characters = [make_char("WitchOfPeter", "Standard")]
    win._character_items["WitchOfPeter"] = [
        Item.model_validate({"typeLine": "Chaos Orb", "inventoryId": "MainInventory"})]
    win._on_character_selected(make_char("WitchOfPeter", "Standard"))
    win._apply_column_filter(TAB_COL, "MainInventory")

    win._leaf_stashes = [_make_leaf("t1", "Currency 1")]
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Exalted Orb"})]}

    win._show_aggregate()

    assert win.proxy.filtered_columns() == set()
    assert win.proxy.rowCount() == 2

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
    win._apply_debounced_search_filter()  # Zeilen-Filter läuft gedämpft, hier erzwungen

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


# --- Stack-Summe in der Statuszeile ------------------------------- #

def test_stack_sum_label_shows_total_of_same_named_stackable_items(qapp) -> None:
    """Peters Wunsch: die Stack-Größe soll nicht mehr von Hand
    zusammengezählt werden müssen. Ausrüstung ohne Stack-Größe (Headhunter)
    zählt nicht als "Stack von 1" mit."""
    win = MainWindow()
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 14}),
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 3}),
        Item.model_validate({"typeLine": "Headhunter"}),
    ])

    assert win._stack_sum_label.text() == "Stack total: 17"

    win.worker.stop()
    win.worker.wait(5000)


def test_stack_sum_label_hidden_when_nothing_stackable_is_visible(qapp) -> None:
    """Kein "Stack total: 0" für reine Ausrüstungsansichten — die Zeile
    verschwindet stattdessen ganz."""
    win = MainWindow()
    win.table_model.set_items([Item.model_validate({"typeLine": "Headhunter"})])

    assert win._stack_sum_label.text() == ""

    win.worker.stop()
    win.worker.wait(5000)


def test_stack_sum_label_hidden_when_visible_items_have_different_names(qapp) -> None:
    """Regression: "*" (zeig alles) lieferte "Stack total: 604.911" quer
    über die ganze Liga — Chaos Orbs, Portal Scrolls, Divine Orbs usw. alle
    in einer Zahl zusammengezählt, was nichts aussagt (Peter, 2026-07-28).
    Die Summe ist nur sinnvoll, wenn genau EIN Item-Name sichtbar ist."""
    win = MainWindow()
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 14}),
        Item.model_validate({"typeLine": "Exalted Orb", "stackSize": 3}),
    ])

    assert win._stack_sum_label.text() == ""

    win.worker.stop()
    win.worker.wait(5000)


def test_stack_sum_label_follows_the_search_filter(qapp) -> None:
    """_update_stack_sum() hängt bewusst NICHT an rowsInserted/rowsRemoved
    (FALLSTRICKE #39, zweiter Teil — das war O(n²)), sondern wird explizit
    aus _apply_debounced_search_filter() aufgerufen. Der Weg über
    _filter_edit + _apply_debounced_search_filter() statt eines direkten
    proxy.setFilterFixedString()-Aufrufs prüft genau das."""
    win = MainWindow()
    win._search_all_active = True  # kein _enter_search_all()-Seiteneffekt hier
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 14}),
        Item.model_validate({"typeLine": "Exalted Orb", "stackSize": 3}),
    ])
    assert win._stack_sum_label.text() == ""  # gemischt, keine sinnvolle Summe

    win._filter_edit.setText("chaos")
    win._apply_debounced_search_filter()

    assert win._stack_sum_label.text() == "Stack total: 14"

    win.worker.stop()
    win.worker.wait(5000)


def test_stack_sum_label_follows_the_type_filter(qapp) -> None:
    win = MainWindow()
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 14, "frameType": 5}),
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 3, "frameType": 5}),
    ])
    assert win._stack_sum_label.text() == "Stack total: 17"

    win._type_checks[5].setChecked(False)  # Currency aus

    assert win._stack_sum_label.text() == ""

    win.worker.stop()
    win.worker.wait(5000)


def test_stack_sum_label_uses_a_thousands_separator(qapp) -> None:
    win = MainWindow()
    win.table_model.set_items([Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 12345})])

    assert win._stack_sum_label.text() == "Stack total: 12,345"

    win.worker.stop()
    win.worker.wait(5000)


def test_search_filter_recomputes_stack_sum_exactly_once(qapp, monkeypatch) -> None:
    """Regression FALLSTRICKE #39 (zweiter Teil): _update_stack_sum() hing
    früher an rowsInserted/rowsRemoved des Proxys. Bei einer Textsuche über
    ein Aggregat mit verstreuten Treffern feuert QSortFilterProxyModel
    (sobald eine QTableView angehängt ist, wie hier immer) pro
    zusammenhängendem Block versteckter/wieder sichtbarer Zeilen ein
    EIGENES Signal — bei stark verstreuten Treffern waren das hunderte
    Aufrufe, jeder mit einer erneuten O(sichtbare Zeilen)-Schleife:
    zusammen O(n²), gemessen 9,5 Sekunden für 19704 Items bei nur EINEM
    Tastendruck. _update_stack_sum() darf pro Suchänderung nur noch GENAU
    EINMAL laufen — deshalb jetzt nur an modelReset gehängt und zusätzlich
    explizit aus _apply_debounced_search_filter() aufgerufen."""
    win = MainWindow()
    win._search_all_active = True
    # Jedes 7. Item passt — verstreut über die ganze Liste, erzeugt beim
    # echten (ungepatchten) Proxy viele einzelne rowsRemoved-Blöcke.
    items = [Item.model_validate({"typeLine": "Chaos Orb" if i % 7 == 0 else f"Item {i}"})
            for i in range(500)]
    win.table_model.set_items(items)

    calls: list[None] = []
    monkeypatch.setattr(win, "_update_stack_sum", lambda *a: calls.append(None))

    win._filter_edit.setText("chaos")
    win._apply_debounced_search_filter()

    assert calls == [None]  # genau ein Aufruf, nicht einer pro versteckter Zeile

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


def test_solo_type_filter_shows_only_the_chosen_type(qapp) -> None:
    """Peters Wunsch: normaler Klick zeigt nur diesen einen Typ, ohne die
    restlichen sieben einzeln abzuwählen."""
    win = MainWindow()

    win._solo_type_filter(3)  # Unique

    assert [tk for tk, box in win._type_checks.items() if box.isChecked()] == [3]

    win.worker.stop()
    win.worker.wait(5000)


def test_reset_type_filters_checks_everything_again(qapp) -> None:
    win = MainWindow()
    win._solo_type_filter(3)

    win._reset_type_filters()

    assert all(box.isChecked() for box in win._type_checks.values())

    win.worker.stop()
    win.worker.wait(5000)


def test_click_on_type_checkbox_solos_it(qapp) -> None:
    """Die eigentliche Maus-Geste, nicht nur der Handler direkt — stellt
    sicher, dass _TypeFilterCheckBox einen modifierlosen Klick abfängt,
    BEVOR QCheckBox ihn als normales Einzel-Umschalten verarbeitet."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win = MainWindow()

    QTest.mouseClick(win._type_checks[3], Qt.MouseButton.LeftButton)

    assert [tk for tk, box in win._type_checks.items() if box.isChecked()] == [3]

    win.worker.stop()
    win.worker.wait(5000)


def test_ctrl_click_on_type_checkbox_does_not_solo_or_reset(qapp) -> None:
    """Strg+Klick (ohne Umschalt) muss an QCheckBox durchgereicht werden,
    NICHT solo/reset auslösen — das native Einzel-Umschalten bleibt so
    Peters Weg, zu einer eingeschränkten Ansicht einen weiteren Typ
    hinzuzufügen oder wieder herauszunehmen. Ein echter End-to-End-Klick
    per QTest.mouseClick ist hier absichtlich vermieden: selbst eine
    nackte QCheckBox togglet im Offscreen-Testmodus nur nach explizitem
    show()+Exposure zuverlässig — das ist Qt-Rendering-Infrastruktur, kein
    Verhalten unseres Codes. Was unser Code leisten muss, ist nur das
    korrekte DURCHREICHEN, und das prüft dieser Test direkt."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    win = MainWindow()
    box = win._type_checks[5]
    solo_calls: list[bool] = []
    reset_calls: list[bool] = []
    box.solo_requested.connect(lambda: solo_calls.append(True))
    box.reset_requested.connect(lambda: reset_calls.append(True))

    event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.ControlModifier)
    box.mousePressEvent(event)

    assert solo_calls == []
    assert reset_calls == []

    win.worker.stop()
    win.worker.wait(5000)


def test_ctrl_shift_click_on_type_checkbox_shows_all(qapp) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win = MainWindow()
    win._solo_type_filter(3)

    QTest.mouseClick(win._type_checks[3], Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)

    assert all(box.isChecked() for box in win._type_checks.values())

    win.worker.stop()
    win.worker.wait(5000)


def test_double_click_on_type_checkbox_resets_all(qapp) -> None:
    """Ohne die eigene mouseDoubleClickEvent-Behandlung würde Qt den
    Doppelklick als zwei normale Klicks werten (Haken am Ende unverändert)
    statt alle Typen zurückzusetzen."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win = MainWindow()
    win._solo_type_filter(3)

    QTest.mouseDClick(win._type_checks[5], Qt.MouseButton.LeftButton)

    assert all(box.isChecked() for box in win._type_checks.values())

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


def test_the_league_from_the_last_session_comes_back(qapp, monkeypatch) -> None:
    """Peter, 2026-08-24: "Wir sollten uns merken, welche Liga zuletzt
    ausgewaehlt war, und die nach dem Neustart anzeigen." Ohne den Merker
    landet man wieder auf der inhaltsreichsten Liga (§_sort_by_content) —
    die eigene Ligen-Wahl ueberlebte den Neustart nicht."""
    erste = MainWindow()
    monkeypatch.setattr(erste.worker, "submit", lambda job: None)
    erste._stash_trees = {"Hardcore": [_make_leaf("h1", "Currency 1")],
                          "Standard": [_make_leaf("s1", "Currency 1")]}
    erste._all_characters = [make_char("Held", "Standard")]   # Standard waere die Vorgabe
    erste._on_leagues(["Standard", "Hardcore"])
    erste._league_combo.setCurrentText("Hardcore")
    erste.worker.stop()
    erste.worker.wait(5000)

    zweite = MainWindow()
    monkeypatch.setattr(zweite.worker, "submit", lambda job: None)
    zweite._stash_trees = {"Hardcore": [_make_leaf("h1", "Currency 1")],
                           "Standard": [_make_leaf("s1", "Currency 1")]}
    zweite._all_characters = [make_char("Held", "Standard")]
    zweite._on_leagues(["Standard", "Hardcore"])

    assert zweite._league_combo.currentText() == "Hardcore"
    assert zweite._current_league == "Hardcore"

    zweite.worker.stop()
    zweite.worker.wait(5000)


def test_a_league_that_is_gone_falls_back_to_the_first_entry(qapp, monkeypatch) -> None:
    """Temporaere Ligen enden. Der gemerkte Name darf dann nicht dazu
    fuehren, dass gar nichts ausgewaehlt ist — es bleibt beim bisherigen
    Verhalten, also dem ersten Eintrag."""
    erste = MainWindow()
    monkeypatch.setattr(erste.worker, "submit", lambda job: None)
    erste._stash_trees = {"Allflame": [_make_leaf("a1", "Currency 1")],
                          "Standard": [_make_leaf("s1", "Currency 1")]}
    erste._on_leagues(["Standard", "Allflame"])
    erste._league_combo.setCurrentText("Allflame")
    erste.worker.stop()
    erste.worker.wait(5000)

    zweite = MainWindow()
    monkeypatch.setattr(zweite.worker, "submit", lambda job: None)
    zweite._stash_trees = {"Standard": [_make_leaf("s1", "Currency 1")]}
    zweite._on_leagues(["Standard"])          # Allflame gibt es nicht mehr

    assert zweite._league_combo.currentText() == "Standard"

    zweite.worker.stop()
    zweite.worker.wait(5000)


def test_the_remembered_league_does_not_override_a_running_session(qapp, monkeypatch) -> None:
    """Der gemerkte Wert gilt nur, solange nichts gewaehlt IST. Sonst risse
    jeder Rebuild mitten in der Sitzung (neue Liga-Antwort, Kontowechsel)
    die Auswahl auf den Startwert zurueck.

    Dass beides auseinanderlaufen kann, ist kein konstruierter Fall: Ein
    zweites Fenster (Nur-Lese-Instanz, §instance_lock) schreibt in
    DIESELBE ui-settings.ini. Wechselt man dort die Liga, steht im Merker
    etwas anderes als hier auf dem Bildschirm."""
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._stash_trees = {"Hardcore": [_make_leaf("h1", "Currency 1")],
                        "Standard": [_make_leaf("s1", "Currency 1")]}
    win._on_leagues(["Standard", "Hardcore"])
    win._league_combo.setCurrentText("Hardcore")
    # Das zweite Fenster steht auf Standard und hat das gerade abgelegt.
    win._settings().setValue(win._LAST_LEAGUE_SETTING_KEY, "Standard")

    win._on_leagues(["Standard", "Hardcore"])   # Rebuild mitten in der Sitzung

    assert win._league_combo.currentText() == "Hardcore"

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
    (``_tab_positions``), nicht aus ``StashTab.index``. Test simuliert genau
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
    (``_tab_positions``), nicht aus ``StashTab.index`` (hier bewusst auf
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


def _map_stash_with_sections(stash_id: str, name: str, n: int) -> StashTab:
    """Map-Stash mit n Sektions-Unterfächern — in der Truhen-Leiste
    trotzdem EIN einziges Fach."""
    parent = StashTab.model_validate({"id": stash_id, "name": name, "type": "MapStash",
                                      "metadata": {}})
    parent.children = [
        StashTab.model_validate({
            "id": f"{stash_id}_c{i}", "name": "1", "parent": stash_id, "type": "MapStash",
            "metadata": {"items": 1, "map": {"section": f"tier{i + 1}",
                                             "name": f"Map (Tier {i + 1})", "index": i}}})
        for i in range(n)
    ]
    return parent


def test_tab_positions_count_special_tabs_as_a_single_vault_slot(qapp) -> None:
    """Peter: "Unique und Map Stash-Tabs werden nicht mitgezählt".

    Grundlage war ``_leaf_stashes``, das die ladbaren EINHEITEN beschreibt:
    dort fällt der Map-/Unique-Eltern-Tab heraus und seine Sektionen sind
    die Einträge. Daraus nummeriert bekam der eigentliche Truhen-Tab gar
    keine Position, während jede Sektion eine verbrauchte und alles
    Folgende verschob (real beobachtet: ein einzelner Map-Stash belegte die
    Positionen 28–38). Gezählt werden muss, was in der Leiste einen Platz
    belegt."""
    win = MainWindow()
    win._current_league = "Standard"
    first = StashTab.model_validate({"id": "first", "name": "Currency",
                                     "type": "CurrencyStash", "metadata": {}})
    maps = _map_stash_with_sections("maps", "M", 11)
    after = StashTab.model_validate({"id": "after", "name": "Essence",
                                     "type": "EssenceStash", "metadata": {}})
    win._stash_trees["Standard"] = [first, maps, after]
    win._leaf_stashes = win._flatten_stashes(win._stash_trees["Standard"])

    positions = win._tab_positions()

    assert positions["maps"] == 2, "der Map-Stash selbst muss eine Position haben"
    assert positions["after"] == 3, "die 11 Sektionen dürfen nichts verschieben"
    # Items aus einer Sektion liegen im Truhenplatz des Eltern-Tabs.
    assert positions["maps_c0"] == 2
    assert positions["maps_c10"] == 2

    win.worker.stop()
    win.worker.wait(5000)


def test_tab_positions_number_special_tabs_inside_folders_too(qapp) -> None:
    """Ordner belegen selbst keinen Platz (unverändert), die Fächer darin
    schon — auch ein Spezial-Tab."""
    win = MainWindow()
    win._current_league = "Standard"
    folder = StashTab.model_validate({"id": "f1", "name": "Map", "type": "Folder",
                                      "metadata": {"folder": True}})
    folder.children = [_map_stash_with_sections("maps", "M", 3)]
    tail = StashTab.model_validate({"id": "tail", "name": "Currency",
                                    "type": "CurrencyStash", "metadata": {}})
    win._stash_trees["Standard"] = [folder, tail]
    win._leaf_stashes = win._flatten_stashes(win._stash_trees["Standard"])

    positions = win._tab_positions()

    assert "f1" not in positions   # Ordner: kein eigener Truhenplatz
    assert positions["maps"] == 1
    assert positions["tail"] == 2

    win.worker.stop()
    win.worker.wait(5000)


def test_undiscovered_special_tab_keeps_its_position(qapp) -> None:
    """Ein Spezial-Tab VOR dem ersten Abruf hat noch keine Kinder — er darf
    dadurch weder seine Position verlieren noch eine zusätzliche belegen,
    wenn die Kinder später eintreffen."""
    win = MainWindow()
    win._current_league = "Standard"
    first = StashTab.model_validate({"id": "first", "name": "Currency",
                                     "type": "CurrencyStash", "metadata": {}})
    maps = StashTab.model_validate({"id": "maps", "name": "M", "type": "MapStash",
                                    "metadata": {}})  # noch keine Kinder entdeckt
    after = StashTab.model_validate({"id": "after", "name": "Essence",
                                     "type": "EssenceStash", "metadata": {}})
    win._stash_trees["Standard"] = [first, maps, after]

    before = win._tab_positions()
    maps.children = _map_stash_with_sections("maps", "M", 5).children  # Abruf liefert Kinder
    after_discovery = win._tab_positions()

    assert before["maps"] == 2 and before["after"] == 3
    assert after_discovery["maps"] == 2 and after_discovery["after"] == 3

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
    win._apply_debounced_search_filter()  # Zeilen-Filter läuft gedämpft, hier erzwungen
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


def test_league_changed_skips_stash_list_when_that_window_is_too_full(qapp, monkeypatch) -> None:
    """Regression zu FALLSTRICKE #48: mehrere schnelle Liga-Wechsel feuerten
    bisher ungebremst je einen FetchStashListJob — das trug real dazu bei,
    das Rate-Limit-Fenster Richtung Zwangspause zu treiben. Ist das Fenster
    für Fach-Listen-Abrufe schon zu voll, bleibt der gecachte Baum stehen
    und der Job entfällt für diesen Wechsel."""
    win = MainWindow()
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    monkeypatch.setattr(win.worker.rate_limiter, "pacing_blocked",
                        lambda policy=None: policy == "stash-list-request-limit")

    win._on_league_changed("Standard")

    assert not any(isinstance(j, FetchStashListJob) for j in submitted)

    win.worker.stop()
    win.worker.wait(5000)


def test_league_change_does_not_reset_the_remembered_refresh_mode_policy(qapp) -> None:
    """Regression zu FALLSTRICKE #48: `_refresh_mode_policy` wurde bei jedem
    Liga-Wechsel auf None zurückgesetzt. Bis zum ersten Job der neuen Liga
    fiel `pacing_blocked()`/`steady_pace_interval_s()` dadurch auf den
    globalen, von JEDEM Request überschreibbaren `_last_policy` zurück —
    exakt die Kontamination, die FALLSTRICKE #33 schon einmal behoben hat.
    Da die Policy einer Fach-Anfrage liga-unabhängig ist, darf der Wert den
    Wechsel unverändert überstehen."""
    win = MainWindow()
    win._refresh_mode_policy = "stash-request-limit"

    win._on_league_changed("Standard")
    assert win._refresh_mode_policy == "stash-request-limit"

    win._refresh_mode_combo.setCurrentText("Single")
    assert win._refresh_mode_policy == "stash-request-limit"

    win.worker.stop()
    win.worker.wait(5000)


def test_league_changed_submits_fetch_prices_job_when_not_cached(qapp, monkeypatch) -> None:
    win = MainWindow()
    monkeypatch.setattr(price_cache, "load", lambda league, ttl_seconds=None: None)
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_league_changed("Standard")

    assert FetchPricesJob("Standard") in submitted
    win.worker.stop()
    win.worker.wait(5000)


def test_league_changed_uses_disk_cache_instead_of_a_network_job(qapp, monkeypatch) -> None:
    fake_index = PriceIndex()
    monkeypatch.setattr(price_cache, "load", lambda league, ttl_seconds=None: fake_index)
    win = MainWindow()
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_league_changed("Standard")

    assert not any(isinstance(j, FetchPricesJob) for j in submitted)
    assert win._price_indexes["Standard"] is fake_index
    win.worker.stop()
    win.worker.wait(5000)


def test_ensure_prices_loaded_is_a_noop_once_already_known(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._price_indexes["Standard"] = PriceIndex()
    load_calls = []
    monkeypatch.setattr(price_cache, "load", lambda league, ttl_seconds=None: load_calls.append(league))
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._ensure_prices_loaded("Standard")

    assert load_calls == []
    assert submitted == []
    win.worker.stop()
    win.worker.wait(5000)


def test_on_prices_loaded_stores_index_and_writes_through_to_disk_cache(qapp, monkeypatch) -> None:
    win = MainWindow()
    fake_index = PriceIndex()
    saved = []
    monkeypatch.setattr(price_cache, "save", lambda league, index: saved.append((league, index)))

    win._on_prices_loaded("Standard", fake_index)

    assert win._price_indexes["Standard"] is fake_index
    assert saved == [("Standard", fake_index)]
    win.worker.stop()
    win.worker.wait(5000)


def test_constructor_submits_a_mod_knowledge_job_right_after_bootstrap(qapp, monkeypatch) -> None:
    """§4.53: laeuft unabhaengig vom Login, deshalb reicht irgendein Platz
    in der Queue - Hauptsache einmal pro Start, wie bei BootstrapJob
    daneben dokumentiert."""
    from poe_view.services.api_worker import ApiWorker, BootstrapJob

    monkeypatch.setattr(ApiWorker, "start", lambda self: None)  # Worker-Thread nie starten

    win = MainWindow()

    jobs = []
    while not win.worker._jobs.empty():
        jobs.append(win.worker._jobs.get_nowait())

    assert isinstance(jobs[0], BootstrapJob)
    assert any(isinstance(j, FetchModKnowledgeJob) for j in jobs[1:])
    win.worker.stop()
    win.worker.wait(5000)


def test_on_mod_knowledge_loaded_stores_the_result(qapp) -> None:
    win = MainWindow()
    fake_knowledge = mod_knowledge.Knowledge({})

    win._on_mod_knowledge_loaded(fake_knowledge)

    assert win._mod_knowledge is fake_knowledge
    win.worker.stop()
    win.worker.wait(5000)


def test_on_mod_knowledge_loaded_accepts_none_without_crashing(qapp) -> None:
    """Kein Cache, kein Netz beim ersten Start - der haeufigste Fall,
    solange RePoE noch nicht heruntergeladen wurde."""
    win = MainWindow()

    win._on_mod_knowledge_loaded(None)

    assert win._mod_knowledge is None
    win.worker.stop()
    win.worker.wait(5000)



def _wertsumme(win) -> str:
    """Nur der Wertsummen-Teil des Statuszeilen-Labels, ohne die
    poe.ninja-Altersangabe dahinter (§4.49).

    Die Altersangabe hat eigene Tests; ohne diese Trennung muesste jede
    Zusicherung ueber die Summe sie mitschleppen und wuerde bei der
    naechsten Formulierungsaenderung dort mit umfallen."""
    text = win._value_sum_label.text()
    kopf = text.split("  ·  ")[0]
    return "" if kopf.startswith("poe.ninja ") else kopf


def test_on_prices_loaded_updates_table_and_value_sum_for_the_current_league(qapp) -> None:
    win = MainWindow()
    win._current_league = "Standard"
    win.table_model.set_items([Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 10})])
    assert _wertsumme(win) == ""  # noch kein Preis-Index

    index = PriceIndex()
    index._simple["Chaos Orb"] = 1.0
    # Zweiter Preis, damit der Index nicht als LEER gilt: "Chaos Orb"
    # allein ueberschreibt nur die fest eingebaute Referenz und ist nach
    # PriceIndex.is_empty kein einziger echter Preis (FALLSTRICKE #49).
    index._simple["Exalted Orb"] = 50.0
    win._on_prices_loaded("Standard", index)

    assert _wertsumme(win) == "Value: 10c"
    win.worker.stop()
    win.worker.wait(5000)


def test_on_prices_loaded_ignores_a_league_that_is_not_currently_shown(qapp) -> None:
    """Preise für eine im Hintergrund geladene, aber nicht angezeigte Liga
    dürfen die aktuell sichtbare Tabelle nicht verändern."""
    win = MainWindow()
    win._current_league = "Standard"
    win.table_model.set_items([Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 10})])

    other_index = PriceIndex()
    other_index._simple["Chaos Orb"] = 1.0
    other_index._simple["Exalted Orb"] = 50.0  # siehe oben: sonst gilt der Index als leer
    win._on_prices_loaded("Hardcore", other_index)

    assert _wertsumme(win) == ""
    win.worker.stop()
    win.worker.wait(5000)


def test_league_changed_applies_the_cached_price_index_to_the_table(qapp, monkeypatch) -> None:
    index = PriceIndex()
    index._simple["Chaos Orb"] = 1.0
    index._simple["Exalted Orb"] = 50.0  # siehe oben: sonst gilt der Index als leer
    monkeypatch.setattr(price_cache, "load", lambda league, ttl_seconds=None: index)
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    win._on_league_changed("Standard")
    win.table_model.set_items([Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 10})])

    assert _wertsumme(win) == "Value: 10c"
    win.worker.stop()
    win.worker.wait(5000)


def test_value_sum_label_shows_total_across_different_item_names(qapp) -> None:
    """Anders als die Stack-Summe (nur bei EINHEITLICHEM Namen sinnvoll)
    ist eine Chaos-Summe über verschiedene Item-Typen hinweg sinnvoll —
    genau das will Peter mit "wie viel ist meine Truhe wert" beantworten."""
    win = MainWindow()
    win.table_model.set_price_index(_price_index(**{"Chaos Orb": 1.0, "Exalted Orb": 50.0}))
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 10}),
        Item.model_validate({"typeLine": "Exalted Orb", "stackSize": 2}),
    ])

    assert _wertsumme(win) == "Value: 110c"
    win.worker.stop()
    win.worker.wait(5000)


def test_a_league_without_prices_says_so_instead_of_staying_blank(qapp) -> None:
    """Spielertest 2026-08-03: Die dauerhaft leere Wertspalte in SSF-Ligen
    sieht aus wie ein Defekt. poe.ninja leitet Preise aus Handelsaktivitaet
    ab, und die gibt es in Solo Self-Found nicht — die Liga wird dort gar
    nicht gefuehrt (FALLSTRICKE #49)."""
    win = MainWindow()
    win._current_league = "Solo Self-Found"
    win._price_indexes["Solo Self-Found"] = PriceIndex()  # nur die Chaos-Orb-Referenz
    win.table_model.set_items([Item.model_validate({"typeLine": "Some Rare"})])

    assert _wertsumme(win) == "No prices for this league"
    assert "Solo Self-Found" in win._value_sum_label.toolTip()

    win.worker.stop()
    win.worker.wait(5000)


def test_the_hint_replaces_the_sum_even_when_chaos_orbs_would_add_up(qapp) -> None:
    """Ein leerer Index bepreist trotzdem eine Sache: die fest eingebaute
    Chaos-Orb-Referenz. "Value: 20c" neben lauter wertlos aussehenden
    Zeilen waere irrefuehrender als der Hinweis."""
    win = MainWindow()
    win._current_league = "Solo Self-Found"
    index = PriceIndex()
    win._price_indexes["Solo Self-Found"] = index
    win.table_model.set_price_index(index)
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5, "stackSize": 20})])

    assert _wertsumme(win) == "No prices for this league"

    win.worker.stop()
    win.worker.wait(5000)


def test_a_league_with_prices_shows_no_hint_and_no_stale_tooltip(qapp) -> None:
    """Gegenprobe: Der Hinweis darf nicht haengenbleiben, wenn die naechste
    Liga Preise hat — sonst behauptet der Tooltip etwas Falsches."""
    win = MainWindow()
    win._current_league = "Standard"
    win._price_indexes["Standard"] = _price_index(**{"Exalted Orb": 50.0})
    win.table_model.set_price_index(win._price_indexes["Standard"])
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Exalted Orb", "frameType": 5, "stackSize": 2})])

    assert _wertsumme(win) == "Value: 100c"
    # Nicht auf einen LEEREN Tooltip pruefen: Dort steht seit §4.49 der
    # poe.ninja-Datenstand. Gemeint war immer, dass der SSF-Hinweis nicht
    # haengenbleibt — genau das wird hier geprueft.
    assert "poe.ninja derives prices" not in win._value_sum_label.toolTip()

    win.worker.stop()
    win.worker.wait(5000)


def test_value_sum_label_hidden_when_nothing_visible_has_a_known_price(qapp) -> None:
    win = MainWindow()
    win.table_model.set_price_index(_price_index(**{"Chaos Orb": 1.0}))
    win.table_model.set_items([Item.model_validate({"typeLine": "Some Unpriced Rare"})])

    assert _wertsumme(win) == ""
    win.worker.stop()
    win.worker.wait(5000)


def test_value_sum_label_skips_unpriced_items_but_sums_the_rest(qapp) -> None:
    win = MainWindow()
    win.table_model.set_price_index(_price_index(**{"Chaos Orb": 1.0}))
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 5}),
        Item.model_validate({"typeLine": "Some Unpriced Rare"}),
    ])

    assert _wertsumme(win) == "Value: 5.0c"
    win.worker.stop()
    win.worker.wait(5000)


def test_value_sum_label_follows_the_type_filter(qapp) -> None:
    win = MainWindow()
    win.table_model.set_price_index(_price_index(**{"Chaos Orb": 1.0}))
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 10, "frameType": 5}),
    ])
    assert _wertsumme(win) == "Value: 10c"

    win._type_checks[5].setChecked(False)  # Currency aus

    assert _wertsumme(win) == ""
    win.worker.stop()
    win.worker.wait(5000)


def test_table_defaults_to_sorting_by_value_ascending(qapp) -> None:
    """ToDo.md "Schrott-Items finden": statt roher API-Reihenfolge soll die
    Tabelle von Anfang an nach Wert aufsteigend sortiert sein, damit
    unbekannte/geringe Preise ("wahrscheinlich Schrott") von selbst oben
    gruppiert sind — kein manueller Klick auf den Value-Header nötig. Ein
    Klick auf einen anderen Header überschreibt das wie jede normale
    Sortierung; das ist nur der Startzustand."""
    from poe_view.ui.item_table import COLUMNS

    win = MainWindow()
    win.table_model.set_price_index(_price_index(**{"Chaos Orb": 1.0, "Exalted Orb": 50.0}))
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Exalted Orb", "stackSize": 1}),   # 50c
        Item.model_validate({"typeLine": "Some Unpriced Rare"}),            # unbekannt
        Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 1}),     # 1c
    ])

    names = [win.proxy.index(row, COLUMNS.index("Name")).data()
             for row in range(win.proxy.rowCount())]
    assert names == ["Some Unpriced Rare", "Chaos Orb", "Exalted Orb"]

    win.worker.stop()
    win.worker.wait(5000)


def test_value_sum_recomputes_exactly_once_per_search_like_the_stack_sum(qapp, monkeypatch) -> None:
    """Dieselbe O(n²)-Gefahr wie FALLSTRICKE #39: _update_value_sum() darf
    nur über _update_summaries() an modelReset hängen bzw. explizit nach
    Filteränderungen laufen, nie an rowsInserted/rowsRemoved."""
    win = MainWindow()
    win._search_all_active = True
    win.table_model.set_price_index(_price_index(**{"Chaos Orb": 1.0}))
    items = [Item.model_validate({"typeLine": "Chaos Orb" if i % 7 == 0 else "Filler",
                                  "stackSize": 1})
             for i in range(500)]
    win.table_model.set_items(items)

    calls: list[None] = []
    monkeypatch.setattr(win, "_update_value_sum", lambda: calls.append(None))
    win._filter_edit.setText("chaos")
    win._apply_debounced_search_filter()

    assert calls == [None]
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


def test_refresh_mode_pauses_while_load_all_tabs_runs(qapp, monkeypatch) -> None:
    """"Load All Tabs" taktet sich selbst durch die ganze Truhe. Liefe der
    Stash-Modus daneben weiter, verdoppelte sich die Anfragerate und beide
    zusammen liefen in die 300s-Sperre, die jeder für sich vermeidet."""
    win = MainWindow()
    win._current_league = "Standard"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    win._bulk_dialog = object()  # Bulk-Ladevorgang läuft

    win._on_refresh_mode_changed("Stash")

    assert submitted == []

    win._bulk_dialog = None  # Bulk fertig -> Modus läuft wieder
    win._drive_refresh_mode()
    assert len(submitted) == 1

    win.worker.stop()
    win.worker.wait(5000)


# --- Refresh-Modus "Pause" (Peter, 2026-07-30) ------------------------- #


def test_refresh_mode_pause_submits_nothing(qapp, monkeypatch) -> None:
    """"Pause" ist der einzige Modus ganz ohne Hintergrund-Requests — weder
    über die Takt-Kette (Single/Stash) noch über den 40s-Timer (Auto).
    Manuelle Klicks und "Load All Tabs" bleiben unberührt."""
    win = MainWindow()
    win._current_league = "Standard"
    win._current_stash_id = "t1"
    win._leaf_stashes = [_make_leaf("t1", "Tab 1")]
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_refresh_mode_changed("Pause")
    win._drive_refresh_mode()
    win._maybe_auto_refresh()

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_rule_label_shows_when_the_next_slot_frees_up(qapp) -> None:
    """Peter, 2026-07-30: "12/30" stand nach einem frischen Start zwei
    Minuten still — sah aus wie ein Hänger, war aber die Realität (GGGs
    Zähler sinkt blockweise statt gleitend, FALLSTRICKE #45 Runde 6). Die
    Restzeit ist deshalb immer eine grobe Schätzung ("~"), nie eine Zusage;
    fehlt sie (noch keine zwei Absenkungen beobachtet), bleibt das Label
    unverändert kurz."""
    win = MainWindow()

    win.dashboard.update_state(
        "stash-request-limit",
        [{"current": 12, "max": 30, "window_s": 300, "locked": False,
          "next_free_s": 139.0}], 0.0)
    assert win.dashboard._bars[0][1].text() == "12/30 · 300 s · next in ~2:19"

    win.dashboard.update_state(
        "stash-request-limit",
        [{"current": 12, "max": 30, "window_s": 300, "locked": False,
          "next_free_s": None}], 0.0)
    assert win.dashboard._bars[0][1].text() == "12/30 · 300 s"

    win.worker.stop()
    win.worker.wait(5000)


def test_rule_bars_are_inserted_after_the_policy_label(qapp) -> None:
    """Regel-Balken landen direkt nach dem Policy-Namen im Layout."""
    win = MainWindow()

    win.dashboard.update_state(
        "stash-request-limit",
        [{"current": 3, "max": 15, "window_s": 15, "locked": False},
         {"current": 7, "max": 30, "window_s": 300, "locked": False}], 0.0)

    layout = win.dashboard._layout
    order = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert order[0] is win.dashboard._policy
    assert order[1] is win.dashboard._bars[0][0]
    assert order[3] is win.dashboard._bars[1][0]

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_pause_marks_the_rate_limit_dashboard(qapp) -> None:
    """Peter, 2026-07-30: 'Wenn ich den Pause-Mode aktiviere verbleibt der
    Policy-Status unverändert.' Das Dashboard bekommt beim Umschalten sofort
    ein sichtbares "(Paused)", nicht erst wenn ein neuer Request die Zahlen
    ändert — und verliert es wieder, sobald ein anderer Modus aktiv wird."""
    win = MainWindow()

    win._on_refresh_mode_changed("Pause")
    assert "(Paused)" in win.dashboard._policy.text()

    win._on_refresh_mode_changed("Auto")
    assert "(Paused)" not in win.dashboard._policy.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_pause_mark_survives_the_second_tick(qapp, monkeypatch) -> None:
    """Der Sekunden-Tick ruft ``update_state`` unabhängig vom Refresh-Modus
    auf (§_update_auto_refresh_countdown) — ein einmaliges ``setText`` beim
    Umschalten würde vom nächsten Tick sofort wieder überschrieben."""
    win = MainWindow()
    monkeypatch.setattr(
        win.worker.rate_limiter, "snapshot",
        lambda: ("stash-request-limit",
                 [{"current": 3, "max": 15, "window_s": 10, "locked": False}], 0.0))
    win._on_refresh_mode_changed("Pause")

    win._update_auto_refresh_countdown()

    assert "(Paused)" in win.dashboard._policy.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_refresh_mode_pause_says_so_in_the_countdown_label(qapp) -> None:
    """Ohne Text stünde da der Auto-Countdown weiter — genau die
    Verwechslung, gegen die die Anzeige überhaupt eingeführt wurde."""
    win = MainWindow()
    win._current_league = "Standard"
    win._refresh_mode_combo.setCurrentText("Pause")

    win._update_auto_refresh_countdown()

    assert "Pause" in win._refresh_status_label.text()

    win.worker.stop()
    win.worker.wait(5000)


# --- Bulk-Fortschritt: Countdown und Baum-Fokus ------------------------ #


def _bulk_window(monkeypatch) -> MainWindow:
    """Fenster mit offenem Bulk-Dialog und einem Baum aus zwei Fächern."""
    from PySide6.QtWidgets import QProgressDialog
    win = MainWindow()
    win._current_league = "Standard"
    stashes = [_make_leaf("t1", "Tab 1"), _make_leaf("t2", "Tab 2")]
    win._leaf_stashes = stashes
    win.tree.set_stashes(stashes)
    win._bulk_dialog = QProgressDialog("", "Cancel", 0, 4, win)
    win._bulk_dialog.setMinimumDuration(100000)  # nie wirklich zeigen
    # Sonst setzt Qt den Balken beim Erreichen des Maximums selbst zurück
    # (value() == -1) — der echte Dialog wird stattdessen von
    # _on_bulk_finished geschlossen.
    win._bulk_dialog.setAutoReset(False)
    return win


def _progress(**overrides):
    from poe_view.services.api_worker import BulkProgress
    fields = dict(done_requests=1, total_requests=4, done_slots=1, total_slots=2,
                  name="Tab 1", stash_id="t1", remaining_s=33.0, next_wait_s=11.0)
    fields.update(overrides)
    return BulkProgress(**fields)


def test_bulk_progress_counts_down_to_the_next_fetch(qapp, monkeypatch) -> None:
    """Zwischen zwei Abrufen liegen ~11s Takt. Ohne Countdown ist von außen
    nicht zu unterscheiden, ob noch etwas läuft (dieselbe Rückfrage wie beim
    Auto-Refresh: "ca. 5 Minuten gewartet ohne dass irgendwas passiert
    ist"). Der Sekunden-Tick zählt ihn herunter, ohne auf den nächsten
    Fortschritts-Tick zu warten."""
    win = _bulk_window(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: clock[0])

    win._on_bulk_progress(_progress())
    assert "Next tab in 11s" in win._bulk_dialog.labelText()

    clock[0] += 7.0
    win._update_bulk_label()  # das macht sonst der 1s-Tick
    assert "Next tab in 4s" in win._bulk_dialog.labelText()

    clock[0] += 5.0
    win._update_bulk_label()
    assert "Fetching…" in win._bulk_dialog.labelText()

    win.worker.stop()
    win.worker.wait(5000)


def test_bulk_progress_shows_a_rate_limit_lock_instead_of_the_pace(qapp, monkeypatch) -> None:
    """Die 300s-Zwangspause steckt in keinem Header (kein HTTP 429, der
    Limiter bremst selbst) — sie kommt nur über den Sekunden-Countdown des
    RateLimitManagers herein. Sie hat Vorrang vor dem 11s-Takt, sonst stünde
    "Fetching…" fünf Minuten lang da."""
    win = _bulk_window(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: clock[0])

    win._on_bulk_progress(_progress())
    win._on_rate_limit_changed("stash-limit", [], 287.0)
    win._update_bulk_label()

    assert "Rate limit — resuming in 287s" in win._bulk_dialog.labelText()

    win._on_rate_limit_changed("stash-limit", [], 0.0)  # Sperre vorbei
    win._update_bulk_label()
    assert "Rate limit" not in win._bulk_dialog.labelText()

    win.worker.stop()
    win.worker.wait(5000)


def test_bulk_progress_focuses_the_current_tab_in_the_tree(qapp, monkeypatch) -> None:
    """Peter, 2026-07-30: "den aktuell behandelten Stash im Stash-Tree
    fokussieren und dort öffnen". Bewusst über highlight_stash — das löst
    kein stash_selected aus, die Item-Tabelle bleibt also stehen."""
    win = _bulk_window(monkeypatch)
    selected = []
    win.tree.stash_selected.connect(lambda sid, name: selected.append(sid))

    win._on_bulk_progress(_progress(stash_id="t2", name="Tab 2"))

    current = win.tree.currentItem()
    assert current is not None and current.text(0) == "Tab 2"
    assert selected == [], "Fokus darf keinen Fach-Wechsel in der Tabelle auslösen"

    win.worker.stop()
    win.worker.wait(5000)


def test_bulk_progress_keeps_both_counts_and_the_eta_in_the_label(qapp, monkeypatch) -> None:
    """Regression FALLSTRICKE #37/#42: der Balken zählt Abrufe, das Label
    nennt zusätzlich den Truhenplatz-Stand — die neue Countdown-Zeile darf
    weder das eine noch das andere verdrängen."""
    win = _bulk_window(monkeypatch)

    win._on_bulk_progress(_progress(done_requests=3, total_requests=4,
                                    done_slots=2, total_slots=2,
                                    remaining_s=4000.0))

    text = win._bulk_dialog.labelText()
    # Seit 2026-08-06 steht der Fach-Zaehler VORN und die Abrufe heissen
    # "requests" statt "Section" — ein Wort, das es in PoEs Truhen-
    # Oberflaeche gar nicht gibt (Spielertest 2026-08-03).
    assert "3 of 4 requests" in text
    assert "tab 2 of 2" in text
    assert "about 1 h 6 min remaining" in text
    assert win._bulk_dialog.value() == 3

    win.worker.stop()
    win.worker.wait(5000)


# --- Rechtsklick-Menü: externe Tools (ToDo.md, Peter 2026-07-30) ---

def test_row_context_menu_returns_early_for_an_empty_click(qapp) -> None:
    """Rechtsklick unterhalb der letzten Zeile (leere Tabelle) darf kein
    Menü öffnen bzw. bei fehlendem Item nicht abstürzen — das ist der
    einzige Teil von _on_table_row_menu, der ohne QMenu.exec() (blockiert
    ohne echte Nutzerinteraktion) direkt testbar ist."""
    win = MainWindow()
    win._on_table_row_menu(win.table.rect().center())  # keine Items geladen
    win.worker.stop()
    win.worker.wait(5000)


def test_item_tools_menu_is_empty_out_of_the_box_and_points_to_settings(qapp) -> None:
    """Peter, 2026-08-02: ab Werk ist keine Seite vorbelegt. Statt eines
    leeren Popups (sieht wie ein Fehler aus) steht dann ein deaktivierter
    Hinweis auf den Settings-Dialog im Menü."""
    win = MainWindow()
    rare = Item.model_validate({"typeLine": "Vaal Regalia", "baseType": "Vaal Regalia", "frameType": 2})
    # Der Kopieren-Eintrag steht fest im Menü und gehört nicht zu den
    # konfigurierbaren Nachschlagewerken — er öffnet keine fremde Seite.
    actions = [a for a in win._build_item_tools_menu(rare).actions()
               if a.text() and "Copy item text" not in a.text()]
    assert len(actions) == 1
    assert not actions[0].isEnabled()
    assert "Settings" in actions[0].text()

    win.worker.stop()
    win.worker.wait(5000)


def test_item_tools_menu_skips_disabled_entries(qapp) -> None:
    """Konfigurierbares Menü — abgeschaltete Einträge dürfen nicht
    auftauchen, ohne dass man sie gleich löschen muss."""
    win = MainWindow()
    win._save_tool_entries([
        external_tools.ToolEntry("Wiki A", "https://a.example.test/{slug}", enabled=True),
        external_tools.ToolEntry("Wiki B", "https://b.example.test/{slug}", enabled=False),
    ])
    rare = Item.model_validate({"typeLine": "Vaal Regalia", "baseType": "Vaal Regalia", "frameType": 2})
    labels = [a.text() for a in win._build_item_tools_menu(rare).actions()]
    assert any("Wiki A" in l for l in labels)
    assert not any("Wiki B" in l for l in labels)

    win.worker.stop()
    win.worker.wait(5000)


def test_item_tools_menu_uses_a_custom_configured_entry(qapp) -> None:
    """Der eigentliche Sinn der Konfigurierbarkeit: ein eigenes Wiki o.ä.
    eintragen, ohne Code zu ändern."""
    win = MainWindow()
    win._save_tool_entries([
        external_tools.ToolEntry("Mein Wiki", "https://example.test/{slug}", enabled=True),
    ])
    item = Item.model_validate({"typeLine": "Chaos Orb", "baseType": "Chaos Orb", "frameType": 5})
    actions = [a for a in win._build_item_tools_menu(item).actions()
               if a.text() and "Copy item text" not in a.text()]
    assert len(actions) == 1
    assert actions[0].text() == "Mein Wiki öffnen"

    win.worker.stop()
    win.worker.wait(5000)


def test_the_context_menu_copies_the_item_text_to_the_clipboard(qapp) -> None:
    """Wunsch von Peters Betatester, 2026-08-12: "Kann man eigentlich von
    da in den Path of Building rein copypasten?" Der Eintrag steht fest im
    Menü, unabhaengig von den konfigurierbaren Nachschlagewerken — er
    oeffnet keine fremde Seite, sondern schreibt nur in die
    Zwischenablage."""
    from PySide6.QtGui import QGuiApplication

    win = MainWindow()
    # Mit der wertlosen ersten Property: Bei WAFFEN ist das die einzige
    # Stelle, an der die API ihre Klasse nennt (die baseType-Endung reicht
    # nur bei Ruestung und Schmuck).
    item = Item.model_validate({"name": "Soul Bane", "typeLine": "Opal Sceptre",
                                "baseType": "Opal Sceptre", "frameType": 2, "ilvl": 70,
                                "properties": [{"name": "Sceptre", "values": []}]})
    copy_action = next(a for a in win._build_item_tools_menu(item).actions()
                       if "Copy item text" in a.text())

    copy_action.trigger()

    text = QGuiApplication.clipboard().text()
    assert text.startswith("Item Class: Sceptres\nRarity: Rare\n"
                           "Soul Bane\nOpal Sceptre")
    assert "Item Level: 70" in text

    win.worker.stop()
    win.worker.wait(5000)


def test_settings_entries_round_trip_through_qsettings(qapp) -> None:
    win = MainWindow()
    entries = [external_tools.ToolEntry("Test Tool", "https://example.test/{slug}", enabled=False)]
    win._save_tool_entries(entries)
    assert win._load_tool_entries() == entries

    win.worker.stop()
    win.worker.wait(5000)


def test_settings_dialog_saves_entries_when_accepted(qapp, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog

    win = MainWindow()
    new_entries = [external_tools.ToolEntry("Accepted Tool", "https://example.test/{slug}")]
    # Voller Satz wie ihn der echte Dialog liefert (alle konfigurierbaren
    # Spalten, "Name" hier probeweise ausgeblendet) — kein Teil-Update.
    new_column_config = [(name, name != "Name") for name in CONFIGURABLE_COLUMNS]
    new_zone_config = (True, r"C:\PoE")

    class _FakeDialog:
        def __init__(self, entries, column_config, zone_watcher_enabled, zone_watcher_path, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def result_entries(self):
            return new_entries

        def result_column_config(self):
            return new_column_config

        def result_zone_watcher_config(self):
            return new_zone_config

    monkeypatch.setattr("poe_view.ui.main_window.SettingsDialog", _FakeDialog)
    win._open_settings_dialog()
    assert win._load_tool_entries() == new_entries
    assert win._load_column_config() == new_column_config
    assert win._load_zone_watcher_config() == new_zone_config

    win.worker.stop()
    win.worker.wait(5000)


def test_settings_dialog_does_not_save_when_cancelled(qapp, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog

    win = MainWindow()
    original = win._load_tool_entries()
    original_columns = win._load_column_config()
    original_zone_config = win._load_zone_watcher_config()

    class _FakeDialog:
        def __init__(self, entries, column_config, zone_watcher_enabled, zone_watcher_path, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Rejected

        def result_entries(self):
            raise AssertionError("result_entries darf bei Abbruch nicht abgefragt werden")

        def result_column_config(self):
            raise AssertionError("result_column_config darf bei Abbruch nicht abgefragt werden")

        def result_zone_watcher_config(self):
            raise AssertionError("result_zone_watcher_config darf bei Abbruch nicht abgefragt werden")

    monkeypatch.setattr("poe_view.ui.main_window.SettingsDialog", _FakeDialog)
    win._open_settings_dialog()
    assert win._load_tool_entries() == original
    assert win._load_column_config() == original_columns
    assert win._load_zone_watcher_config() == original_zone_config

    win.worker.stop()
    win.worker.wait(5000)


# --- Item-Doppelklick: vergrößerte Ansicht (ToDo.md, Peter 2026-07-31) ---

def test_double_click_on_a_row_opens_the_zoom_dialog(qapp) -> None:
    win = MainWindow()
    win.table_model.set_items([Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})])
    index = win.proxy.index(0, 0)

    win._on_table_row_double_clicked(index)

    assert win._item_zoom_dialog.windowTitle() == "Chaos Orb"

    win.worker.stop()
    win.worker.wait(5000)


def test_double_click_with_no_item_at_the_index_does_nothing(qapp) -> None:
    win = MainWindow()  # leere Tabelle
    win._on_table_row_double_clicked(win.proxy.index(0, 0))  # ungültiger Index
    assert not hasattr(win, "_item_zoom_dialog")

    win.worker.stop()
    win.worker.wait(5000)


def _fake_png_bytes() -> bytes:
    """Echte, minimale PNG-Bytes für QPixmap.loadFromData() — kein Mocken
    von Qt-internem Bildparsing nötig."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap(2, 2)
    pixmap.fill()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def test_double_click_on_a_divination_card_fetches_its_real_artwork(qapp, monkeypatch) -> None:
    """GGGs API liefert für jede Div-Card dasselbe generische Icon
    (FALLSTRICKE #52) — der Doppelklick muss deshalb zusätzlich das echte
    Artwork über den Worker anfordern."""
    win = MainWindow()
    monkeypatch.setattr("poe_view.ui.main_window.icon_cache.load", lambda url: None)
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    win.table_model.set_items([Item.model_validate({"typeLine": "The Doctor", "frameType": 6})])

    win._on_table_row_double_clicked(win.proxy.index(0, 0))

    assert len(submitted) == 1
    assert submitted[0].url == "https://web.poecdn.com/image/divination-card/TheDoctor.png"
    assert win._pending_card_art == (submitted[0].url, win._item_zoom_dialog)

    win.worker.stop()
    win.worker.wait(5000)


def test_double_click_on_a_divination_card_uses_a_cached_artwork_immediately(qapp, monkeypatch) -> None:
    win = MainWindow()
    monkeypatch.setattr("poe_view.ui.main_window.icon_cache.load", lambda url: _fake_png_bytes())
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    win.table_model.set_items([Item.model_validate({"typeLine": "The Doctor", "frameType": 6})])

    win._on_table_row_double_clicked(win.proxy.index(0, 0))

    assert submitted == []  # Cache-Treffer: kein Download nötig
    assert not win._item_zoom_dialog._icon.pixmap().isNull()
    assert win._pending_card_art is None

    win.worker.stop()
    win.worker.wait(5000)


def test_double_click_on_a_non_card_item_does_not_fetch_art(qapp, monkeypatch) -> None:
    win = MainWindow()
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    win.table_model.set_items([Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})])

    win._on_table_row_double_clicked(win.proxy.index(0, 0))

    assert submitted == []
    assert win._pending_card_art is None

    win.worker.stop()
    win.worker.wait(5000)


def test_on_icon_updates_a_pending_card_art_dialog(qapp) -> None:
    from poe_view.ui.item_zoom import ItemZoomDialog

    win = MainWindow()
    card = Item.model_validate({"typeLine": "The Doctor", "frameType": 6})
    dialog = ItemZoomDialog(card, None, parent=win)
    url = "https://web.poecdn.com/image/divination-card/TheDoctor.png"
    win._pending_card_art = (url, dialog)

    win._on_icon(url, _fake_png_bytes())

    assert win._pending_card_art is None
    assert not dialog._icon.pixmap().isNull()

    win.worker.stop()
    win.worker.wait(5000)


def test_on_icon_ignores_unrelated_urls_for_pending_card_art(qapp) -> None:
    from poe_view.ui.item_zoom import ItemZoomDialog

    win = MainWindow()
    card = Item.model_validate({"typeLine": "The Doctor", "frameType": 6})
    dialog = ItemZoomDialog(card, None, parent=win)
    url = "https://web.poecdn.com/image/divination-card/TheDoctor.png"
    win._pending_card_art = (url, dialog)

    win._on_icon("https://web.poecdn.com/some/other/icon.png", _fake_png_bytes())

    assert win._pending_card_art == (url, dialog)  # unverändert
    assert dialog._icon.pixmap().isNull()  # noch nicht aktualisiert

    win.worker.stop()
    win.worker.wait(5000)


# --- Mindestfenstergröße: Suche darf nie hinter "…" verschwinden ---
# --- (Peter, 2026-08-01) ---

def test_window_has_a_minimum_size_that_keeps_the_search_field_visible(qapp) -> None:
    """800x600 (Peter, 2026-08-01: "pragmatisch auf die bekannte Größe")
    liegt mit Puffer über der real am Fenster gemessenen Breiten-Schwelle
    (~740px), unterhalb der die zweite Toolbar-Zeile (Liga/Typ-Filter/
    Suche) das Suchfeld hinter "…" versteckt."""
    win = MainWindow()
    assert win.minimumWidth() == 800
    assert win.minimumHeight() == 600

    win.worker.stop()
    win.worker.wait(5000)


# --- Zonenwechsel-Trigger: gezielter Refresh statt Polling -------------- #
# --- (Peter, 2026-08-01: "Erst nach Zonenwechsel gibt es einen Refresh") #

def test_zone_watcher_config_persists_across_restart(qapp) -> None:
    win = MainWindow()
    win._save_zone_watcher_config(True, r"C:\PoE")
    win.worker.stop()
    win.worker.wait(5000)

    win2 = MainWindow()  # "Neustart": liest ui-settings.ini (im Test: tmp_path)
    assert win2._load_zone_watcher_config() == (True, r"C:\PoE")

    win2.worker.stop()
    win2.worker.wait(5000)


def test_zone_watcher_config_defaults_to_disabled_with_no_stored_value(qapp) -> None:
    win = MainWindow()
    assert win._load_zone_watcher_config() == (False, "")

    win.worker.stop()
    win.worker.wait(5000)


def test_apply_zone_watcher_config_does_nothing_when_disabled(qapp) -> None:
    win = MainWindow()
    win._apply_zone_watcher_config(False, "irrelevant")
    assert win._zone_watcher is None

    win.worker.stop()
    win.worker.wait(5000)


def test_apply_zone_watcher_config_does_nothing_for_an_unresolvable_path(qapp) -> None:
    win = MainWindow()
    win._apply_zone_watcher_config(True, r"Z:\does\not\exist")
    assert win._zone_watcher is None

    win.worker.stop()
    win.worker.wait(5000)


def test_apply_zone_watcher_config_starts_a_watcher_for_a_valid_path(qapp, tmp_path) -> None:
    log = tmp_path / "Client.txt"
    log.write_text("", encoding="utf-8")
    win = MainWindow()
    win._apply_zone_watcher_config(True, str(tmp_path))
    assert win._zone_watcher is not None

    win.worker.stop()
    win.worker.wait(5000)


def test_reapplying_zone_watcher_config_replaces_the_old_watcher(qapp, tmp_path) -> None:
    log = tmp_path / "Client.txt"
    log.write_text("", encoding="utf-8")
    win = MainWindow()
    win._apply_zone_watcher_config(True, str(tmp_path))
    first = win._zone_watcher
    win._apply_zone_watcher_config(True, str(tmp_path))
    assert win._zone_watcher is not None
    assert win._zone_watcher is not first

    win.worker.stop()
    win.worker.wait(5000)


def _ready_for_zone_refresh(win) -> None:
    win._current_league = "Standard"
    win._live_leagues = {"Standard"}
    win._logged_in = True
    win._current_stash_id = "t1"
    win._current_tab_name = "Tab 1"


def test_zone_changed_refreshes_the_currently_open_tab(qapp, monkeypatch) -> None:
    win = MainWindow()
    _ready_for_zone_refresh(win)
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_zone_changed("The Coast")

    stash_jobs = [j for j in submitted if hasattr(j, "stash_id")]
    assert len(stash_jobs) == 1
    assert stash_jobs[0].stash_id == "t1"
    assert stash_jobs[0].silent is True
    assert "The Coast" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_changed_does_nothing_while_paused(qapp, monkeypatch) -> None:
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._refresh_mode = "pause"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_zone_changed("The Coast")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_changed_updates_the_zone_label_even_while_paused(qapp, monkeypatch) -> None:
    """Peter, 2026-08-03: "Momentan bin ich mir nicht sicher ob wir das
    überhaupt machen" — die Anzeige bestätigt, dass die Client.txt-Änderung
    erkannt wurde, unabhängig davon, ob ein Refresh danach tatsächlich
    ausgelöst wird (Pause-Modus blockiert hier bewusst nur den Refresh)."""
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._refresh_mode = "pause"
    assert win._zone_label.text() == "–"

    win._on_zone_changed("The Coast")

    assert win._zone_label.text() == "The Coast"

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_changed_does_nothing_without_a_login(qapp, monkeypatch) -> None:
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._logged_in = False
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_zone_changed("The Coast")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_changed_does_nothing_without_a_selected_league(qapp, monkeypatch) -> None:
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._current_league = ""
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_zone_changed("The Coast")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_changed_does_nothing_for_an_archived_league(qapp, monkeypatch) -> None:
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._live_leagues = {"SomeOtherLeague"}  # Standard nicht mehr live -> archiviert
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_zone_changed("The Coast")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_changed_does_nothing_while_load_all_tabs_is_running(qapp, monkeypatch) -> None:
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._bulk_dialog = object()
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_zone_changed("The Coast")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_changed_does_nothing_when_the_rate_limit_window_is_too_full(qapp, monkeypatch) -> None:
    win = MainWindow()
    _ready_for_zone_refresh(win)
    monkeypatch.setattr(win.worker.rate_limiter, "pacing_blocked", lambda *a, **kw: True)
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_zone_changed("The Coast")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_changed_shows_no_status_when_nothing_is_currently_open(qapp, monkeypatch) -> None:
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._current_stash_id = None
    win._current_character_name = None
    win._status_msg.setText("previous status")
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_zone_changed("The Coast")

    assert submitted == []
    assert win._status_msg.text() == "previous status"

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_watcher_end_to_end_triggers_a_refresh(qapp, tmp_path, monkeypatch) -> None:
    """Volle Kette: Zeile an die beobachtete Datei anhängen, ``check_now()``
    (statt auf ein echtes Datei-Ereignis zu warten) -> Signal -> Refresh."""
    log = tmp_path / "Client.txt"
    log.write_text("", encoding="utf-8")
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._apply_zone_watcher_config(True, str(tmp_path))
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    with log.open("a", encoding="utf-8") as f:
        f.write("2026/08/01 21:44:37 15181671 cffb0658 [INFO Client 18604] "
               ": You have entered The Coast.\n")
    win._zone_watcher.check_now()

    stash_jobs = [j for j in submitted if hasattr(j, "stash_id")]
    assert len(stash_jobs) == 1

    win.worker.stop()
    win.worker.wait(5000)


# --- Händler-Trigger und Burst-Budget (Peter, 2026-08-10) ----------------- #
#
# "Ich denke, wir können den Händler-Trigger einbauen, und die dadurch
# gesparte Zeit auf den Timer zum nächsten Trigger addieren. Dann haben
# wir meinetwegen 4 Trigger kurz hintereinander, aber der 5. Trigger
# kommt dann trotzdem erst nach 60 Sekunden und ab dann wieder alle 15
# Sekunden oder so."

def test_an_inventory_event_refreshes_the_currently_open_view(qapp, monkeypatch) -> None:
    """Derselbe gezielte Einzel-Refresh wie beim Zonenwechsel, nur ein
    anderer Anlass — ein Verkauf beim Händler."""
    win = MainWindow()
    _ready_for_zone_refresh(win)
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_inventory_event("Trade accepted")

    stash_jobs = [j for j in submitted if hasattr(j, "stash_id")]
    assert len(stash_jobs) == 1
    assert stash_jobs[0].silent is True
    assert "Trade accepted" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_an_inventory_event_does_nothing_while_paused(qapp, monkeypatch) -> None:
    """Pause heisst "keine Hintergrund-Anfragen" — eine ausdrueckliche
    Nutzerwahl, an der auch ein Haendler-Ereignis nichts aendert."""
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._refresh_mode = "pause"
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._on_inventory_event("Trade accepted")

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_an_early_trigger_pushes_the_next_beat_instead_of_resetting_it(
        qapp, monkeypatch) -> None:
    """Peters Kern-Idee: "die dadurch gesparte Zeit auf den Timer zum
    naechsten Trigger addieren". Ein vorgezogener Abruf stellt die Uhr
    nicht auf null, sondern zahlt seine Ersparnis zurueck — der naechste
    regulaere Takt liegt danach ein volles Intervall hinter dem BISHERIGEN
    Termin, nicht hinter dem Jetzt."""
    win = MainWindow()
    _ready_for_zone_refresh(win)
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s",
                        lambda *_: 15.0)
    now = time.monotonic()
    win._refresh_mode_next_due = now + 12.0  # noch 12s bis zum regulaeren Takt

    win._note_refresh_mode_job_done()  # Antwort auf den vorgezogenen Abruf

    assert win._refresh_mode_next_due - now == pytest.approx(27.0, abs=0.5)

    win.worker.stop()
    win.worker.wait(5000)


def test_a_regular_beat_still_counts_from_now(qapp, monkeypatch) -> None:
    """Gegenprobe: Im gewoehnlichen Fall aendert die Schuldenrechnung
    nichts. Der Job lief ja, WEIL er faellig war — dann liegt der alte
    Termin bereits in der Vergangenheit und der naechste Takt zaehlt wie
    bisher ab jetzt."""
    win = MainWindow()
    _ready_for_zone_refresh(win)
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s",
                        lambda *_: 15.0)
    now = time.monotonic()
    win._refresh_mode_next_due = now - 3.0  # war faellig, Job lief daraufhin

    win._note_refresh_mode_job_done()

    assert win._refresh_mode_next_due - now == pytest.approx(15.0, abs=0.5)

    win.worker.stop()
    win.worker.wait(5000)


def test_a_burst_of_triggers_is_cut_off_once_the_schedule_is_far_enough_ahead(
        qapp, monkeypatch) -> None:
    """Peters Zahlenbeispiel nachgestellt: Bei 15s Takt duerfen vier
    Trigger dicht hintereinander durch, der fuenfte nicht mehr — bis dahin
    liegt der naechste regulaere Takt rund eine Minute voraus."""
    win = MainWindow()
    _ready_for_zone_refresh(win)
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s",
                        lambda *_: 15.0)
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    win._refresh_mode_next_due = time.monotonic()  # gerade eben getaktet

    for _ in range(6):
        before = len(submitted)
        win._on_inventory_event("Trade accepted")
        if len(submitted) > before:
            win._note_refresh_mode_job_done()  # Antwort trifft ein, Schuld waechst

    assert len(submitted) == 4
    assert win._refresh_mode_next_due - time.monotonic() == pytest.approx(60.0, abs=1.0)

    win.worker.stop()
    win.worker.wait(5000)


def test_the_burst_budget_recovers_once_the_schedule_has_caught_up(
        qapp, monkeypatch) -> None:
    """"und ab dann wieder alle 15 Sekunden oder so" — sobald die Zeit die
    aufgelaufene Schuld eingeholt hat, greifen Trigger wieder normal."""
    win = MainWindow()
    _ready_for_zone_refresh(win)
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s",
                        lambda *_: 15.0)
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._refresh_mode_next_due = time.monotonic() + 60.0  # Budget aufgebraucht
    win._on_inventory_event("Trade accepted")
    assert submitted == []

    win._refresh_mode_next_due = time.monotonic() + 30.0  # Zeit hat aufgeholt
    win._on_inventory_event("Trade accepted")
    assert len(submitted) == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_zone_changes_share_the_same_burst_budget(qapp, monkeypatch) -> None:
    """Eine Ausnahme fuer den Zonenwechsel waere ein Loch in genau der
    Grenze, die das Budget zieht: Wer zwischen Hideout und Map hin- und
    herportet, loeste sonst beliebig viele Abrufe aus."""
    win = MainWindow()
    _ready_for_zone_refresh(win)
    monkeypatch.setattr(win.worker.rate_limiter, "steady_pace_interval_s",
                        lambda *_: 15.0)
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))
    win._refresh_mode_next_due = time.monotonic() + 60.0

    win._on_zone_changed("The Coast")

    assert submitted == []
    assert win._zone_label.text() == "The Coast"  # erkannt wurde er trotzdem

    win.worker.stop()
    win.worker.wait(5000)


def test_the_vendor_trigger_reaches_the_window_through_the_watcher(
        qapp, tmp_path, monkeypatch) -> None:
    """Volle Kette wie beim Zonenwechsel: Zeile an die beobachtete Datei
    anhaengen -> Signal -> Refresh."""
    log = tmp_path / "Client.txt"
    log.write_text("", encoding="utf-8")
    win = MainWindow()
    _ready_for_zone_refresh(win)
    win._apply_zone_watcher_config(True, str(tmp_path))
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    with log.open("a", encoding="utf-8") as f:
        f.write("2026/08/10 21:06:08 15181674 cffb0658 [INFO Client 18604] "
               ": 2 Items identified\n")
    win._zone_watcher.check_now()

    stash_jobs = [j for j in submitted if hasattr(j, "stash_id")]
    assert len(stash_jobs) == 1
    assert "2 Items identified" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


# --- CSV-Export aus dem Kontextmenü (Peter, 2026-08-02) ------------------- #

class _NoExecMenu(QMenu):
    """``QMenu.exec()`` blockiert ohne echte Nutzerinteraktion — im Test wird
    nur das Verhalten DAVOR geprüft (welche Zeilen markiert bleiben)."""

    def exec(self, *args, **kwargs):  # noqa: A003 (Qt-API)
        return None


def _window_with_two_items(monkeypatch) -> MainWindow:
    win = MainWindow()
    win._current_league = "Standard"
    tab = _make_leaf("t1", "Currency 1")
    win._stash_trees["Standard"] = [tab]
    win._leaf_stashes = [tab]
    items = [Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5, "stackSize": 4}),
             Item.model_validate({"typeLine": "Divine Orb", "frameType": 5, "stackSize": 1})]
    win._items["Standard"] = {"t1": items}
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._show_items("t1", items, "Currency 1")
    return win


def test_selected_rows_export_only_the_marked_items(qapp, monkeypatch) -> None:
    win = _window_with_two_items(monkeypatch)

    win.table.selectRow(0)
    rows = win._selected_rows()
    assert [item.display_name for _, item in rows] == \
        [win.table_model.item_at(win.proxy.mapToSource(win.proxy.index(0, 0)).row()).display_name]
    assert len(rows) == 1
    # Ohne Auswahl exportiert der Toolbar-Weg weiterhin alles Sichtbare.
    assert len(win._visible_rows()) == 2

    win.worker.stop()
    win.worker.wait(5000)


def test_selected_rows_follow_display_order_not_click_order(qapp, monkeypatch) -> None:
    """Erst Zeile 1, dann Zeile 0 anklicken — die Datei soll trotzdem in der
    Reihenfolge stehen, die auf dem Bildschirm zu sehen ist."""
    win = _window_with_two_items(monkeypatch)
    selection = win.table.selectionModel()
    flags = (QItemSelectionModel.SelectionFlag.Select
             | QItemSelectionModel.SelectionFlag.Rows)
    selection.select(win.proxy.index(1, 0), flags)
    selection.select(win.proxy.index(0, 0), flags)

    names = [item.display_name for _, item in win._selected_rows()]
    visible = [item.display_name for _, item in win._visible_rows()]
    assert names == visible

    win.worker.stop()
    win.worker.wait(5000)


def test_context_menu_offers_both_export_scopes_with_counts(qapp, monkeypatch) -> None:
    win = _window_with_two_items(monkeypatch)
    win.table.selectRow(0)

    menu = win._build_item_tools_menu(win.table_model.item_at(0))
    win._add_export_actions(menu)
    labels = [a.text() for a in menu.actions() if a.text()]
    assert "💾 Export selected items (1)…" in labels
    assert "💾 Export visible items (2)…" in labels

    win.worker.stop()
    win.worker.wait(5000)


def test_right_click_inside_a_multi_selection_keeps_it(qapp, monkeypatch) -> None:
    """Sonst könnte man mehrere markierte Zeilen nie exportieren: das
    Kontextmenü hätte die Auswahl beim Öffnen auf eine Zeile reduziert."""
    win = _window_with_two_items(monkeypatch)
    win.table.selectAll()
    assert len(win.table.selectionModel().selectedRows()) == 2

    # Rechtsklick auf die zweite Zeile — sie ist Teil der Auswahl.
    pos = win.table.visualRect(win.proxy.index(1, 0)).center()
    monkeypatch.setattr(win, "_build_item_tools_menu", lambda item: _NoExecMenu(win.table))
    win._on_table_row_menu(pos)
    assert len(win.table.selectionModel().selectedRows()) == 2

    win.worker.stop()
    win.worker.wait(5000)


def test_right_click_outside_the_selection_selects_that_row(qapp, monkeypatch) -> None:
    win = _window_with_two_items(monkeypatch)
    win.table.selectRow(0)

    pos = win.table.visualRect(win.proxy.index(1, 0)).center()
    monkeypatch.setattr(win, "_build_item_tools_menu", lambda item: _NoExecMenu(win.table))
    win._on_table_row_menu(pos)
    selected = [idx.row() for idx in win.table.selectionModel().selectedRows()]
    assert selected == [1]

    win.worker.stop()
    win.worker.wait(5000)


def test_export_passes_the_leagues_price_index(qapp, monkeypatch, tmp_path) -> None:
    """Ohne den Index bliebe die ValueChaos-Spalte leer, obwohl die
    Value-Spalte im Fenster Preise zeigt."""
    win = _window_with_two_items(monkeypatch)
    win._price_indexes["Standard"] = _price_index(**{"Chaos Orb": 1.0, "Divine Orb": 200.0})
    target = tmp_path / "out.csv"
    monkeypatch.setattr("poe_view.ui.main_window.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "CSV files (*.csv)")))

    win._export_csv()

    import csv as _csv
    with open(target, encoding="utf-8-sig", newline="") as f:
        rows = list(_csv.DictReader(f, delimiter=";"))
    assert {r["Name"]: r["ValueChaos"] for r in rows} == \
        {"Chaos Orb": "4.00", "Divine Orb": "200.00"}

    win.worker.stop()
    win.worker.wait(5000)


def test_raw_json_filter_adds_the_raw_column(qapp, monkeypatch, tmp_path) -> None:
    """Der zweite Dateityp im Speichern-Dialog steuert die Roh-Spalte."""
    win = _window_with_two_items(monkeypatch)
    target = tmp_path / "raw.csv"
    monkeypatch.setattr("poe_view.ui.main_window.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target),
                                                      "CSV with raw JSON column (*.csv)")))

    win._export_csv()

    assert "RawJSON" in target.read_text(encoding="utf-8-sig").splitlines()[0]

    win.worker.stop()
    win.worker.wait(5000)


# --- Suchfeld wird bei Auswahl geleert (Peter, 2026-08-02) ---------------- #

def test_selecting_a_stash_tab_clears_the_search_field(qapp, monkeypatch) -> None:
    """"Die Suche sollte ... beim Auswählen eines Stash-Tabs ... evtl. sogar
    gelöscht werden" — ein stehen gebliebener Suchtext filterte bisher
    unsichtbar weiter, sobald man in ein anderes Fach wechselte."""
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
    win._filter_edit.setText("chaos")

    win._on_stash_selected("t2", "Essence")

    assert win._filter_edit.text() == ""
    assert not win._search_all_active

    win.worker.stop()
    win.worker.wait(5000)


def test_selecting_a_character_clears_the_search_field(qapp, monkeypatch) -> None:
    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")
    win._character_items["WitchOfPeter"] = [
        Item.model_validate({"id": "1", "typeLine": "Chaos Orb", "frameType": 5})]
    win._filter_edit.setText("*")
    win._search_all_active = True  # Zustand einer laufenden globalen Suche

    win._on_character_selected(char)

    assert win._filter_edit.text() == ""
    assert not win._search_all_active

    win.worker.stop()
    win.worker.wait(5000)


def test_search_field_untouched_without_prior_text(qapp, monkeypatch) -> None:
    """Ohne Text im Feld darf die Auswahl keinen unnötigen
    textChanged/Debounce-Zyklus auslösen."""
    win = MainWindow()
    t1 = _make_leaf("t1", "Currency 1")
    win._current_league = "Standard"
    win._stash_trees["Standard"] = [t1]
    win._leaf_stashes = [t1]
    win._items["Standard"] = {"t1": [Item.model_validate({"typeLine": "Chaos Orb"})]}
    monkeypatch.setattr(win.worker, "submit", lambda job: None)

    fired = []
    win._filter_edit.textChanged.connect(lambda text: fired.append(text))
    win._on_stash_selected("t1", "Currency 1")

    assert fired == []

    win.worker.stop()
    win.worker.wait(5000)


def test_typing_a_new_search_after_selection_still_works(qapp, monkeypatch) -> None:
    """Die globale Suche selbst bleibt uneingeschränkt nutzbar — nur die
    vorherige Session wird beim Auswählen beendet, nicht die Fähigkeit,
    danach neu zu suchen."""
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
    win._filter_edit.setText("chaos")
    win._on_stash_selected("t2", "Essence")

    win._filter_edit.setText("*")
    win._apply_debounced_search_filter()

    assert win._search_all_active
    assert win.proxy.rowCount() == 2

    win.worker.stop()
    win.worker.wait(5000)


# --- Stash-Baum-Mehrfachauswahl (Peter, 2026-08-02) ----------------------- #

def _three_tab_window(monkeypatch) -> MainWindow:
    win = MainWindow()
    win._current_league = "Standard"
    t1, t2, t3 = (_make_leaf("t1", "Currency 1"), _make_leaf("t2", "Essence"),
                 _make_leaf("t3", "Rares"))
    win._stash_trees["Standard"] = [t1, t2, t3]
    win._leaf_stashes = [t1, t2, t3]
    win._items["Standard"] = {
        "t1": [Item.model_validate({"typeLine": "Chaos Orb"})],
        "t2": [Item.model_validate({"typeLine": "Deafening Essence of Greed"})],
        # t3 bewusst nie geladen — testet den "never loaded"-Zweig
    }
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    return win


def test_multi_selection_shows_only_cached_items_from_selected_tabs(qapp, monkeypatch) -> None:
    win = _three_tab_window(monkeypatch)

    win._show_stash_selection(["t1", "t2", "t3"])

    names = {item.display_name for _, item in win._visible_rows()}
    assert names == {"Chaos Orb", "Deafening Essence of Greed"}
    assert "3 tabs selected: 2 loaded, 1 never loaded" in win._status_msg.text()
    assert "2 items" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_multi_selection_never_triggers_a_fetch(qapp, monkeypatch) -> None:
    """Kritische Regel: eine Auswahl im Baum darf NIE selbst einen
    API-Abruf auslösen — ein Shift-Klick über viele nie geladene Fächer
    würde sonst das Rate-Limit sprengen."""
    win = _three_tab_window(monkeypatch)
    submitted = []
    monkeypatch.setattr(win.worker, "submit", lambda job: submitted.append(job))

    win._show_stash_selection(["t1", "t2", "t3"])

    assert submitted == []

    win.worker.stop()
    win.worker.wait(5000)


def test_tree_selection_changed_signal_reaches_show_stash_selection(qapp, monkeypatch) -> None:
    """Verdrahtungstest: das neue Baum-Signal ist tatsächlich angeschlossen."""
    win = _three_tab_window(monkeypatch)

    win.tree.selection_changed.emit(["t1", "t2"])

    names = {item.display_name for _, item in win._visible_rows()}
    assert names == {"Chaos Orb", "Deafening Essence of Greed"}

    win.worker.stop()
    win.worker.wait(5000)


def test_multi_selection_clears_the_search_field(qapp, monkeypatch) -> None:
    win = _three_tab_window(monkeypatch)
    win._filter_edit.setText("chaos")

    win._show_stash_selection(["t1", "t2"])

    assert win._filter_edit.text() == ""
    assert not win._search_all_active

    win.worker.stop()
    win.worker.wait(5000)


def test_leaving_search_after_multi_selection_restores_it(qapp, monkeypatch) -> None:
    """"Die Suche sollte ... Global weiter funktionieren" — nach dem Leeren
    des Suchfelds landet man wieder auf der Mehrfachauswahl, nicht auf dem
    zuvor einzeln angeklickten Fach."""
    win = _three_tab_window(monkeypatch)
    win._on_stash_selected("t1", "Currency 1")  # zuletzt einzeln angeklicktes Fach
    win._show_stash_selection(["t2", "t3"])

    win._filter_edit.setText("*")
    win._apply_debounced_search_filter()
    assert win._search_all_active

    win._filter_edit.setText("")
    win._apply_debounced_search_filter()

    names = {item.display_name for _, item in win._visible_rows()}
    assert names == {"Deafening Essence of Greed"}  # t2+t3, t3 ungeladen
    assert win._current_stash_selection == ["t2", "t3"]

    win.worker.stop()
    win.worker.wait(5000)


def test_single_refresh_mode_keeps_the_last_individual_tab_during_multi_selection(
        qapp, monkeypatch) -> None:
    """ToDo.md-Entscheidung: die Refresh-Modi hängen weiterhin am zuletzt
    EINZELN angeklickten Fach — eine Mehrfachauswahl ändert daran nichts."""
    win = _three_tab_window(monkeypatch)
    win._on_stash_selected("t1", "Currency 1")
    assert win._current_stash_id == "t1"

    win._show_stash_selection(["t2", "t3"])

    assert win._current_stash_id == "t1"
    assert win._pick_single_target() == ("stash", "t1", None)

    win.worker.stop()
    win.worker.wait(5000)


def test_csv_export_filename_reflects_multi_selection(qapp, monkeypatch) -> None:
    win = _three_tab_window(monkeypatch)
    win._show_stash_selection(["t1", "t2"])

    filename = win._default_export_filename(2)

    assert re.fullmatch(
        rf"poe-view2-Standard-2-tabs-selected-2items-{_TIMESTAMP_RE}\.csv", filename)

    win.worker.stop()
    win.worker.wait(5000)


def test_selecting_a_single_tab_ends_a_previous_multi_selection(qapp, monkeypatch) -> None:
    win = _three_tab_window(monkeypatch)
    win._show_stash_selection(["t1", "t2"])
    assert win._current_stash_selection == ["t1", "t2"]

    win._on_stash_selected("t1", "Currency 1")

    assert win._current_stash_selection is None

    win.worker.stop()
    win.worker.wait(5000)


def test_selecting_a_character_ends_a_previous_multi_selection(qapp, monkeypatch) -> None:
    win = _three_tab_window(monkeypatch)
    win._show_stash_selection(["t1", "t2"])
    char = make_char("WitchOfPeter", "Standard")

    win._on_character_selected(char)

    assert win._current_stash_selection is None

    win.worker.stop()
    win.worker.wait(5000)


def test_full_aggregate_ends_a_previous_multi_selection(qapp, monkeypatch) -> None:
    win = _three_tab_window(monkeypatch)
    win._show_stash_selection(["t1", "t2"])

    win._show_aggregate()

    assert win._current_stash_selection is None

    win.worker.stop()
    win.worker.wait(5000)


def test_league_change_clears_a_multi_selection(qapp, monkeypatch) -> None:
    win = _three_tab_window(monkeypatch)
    win._show_stash_selection(["t1", "t2"])
    win._live_leagues = {"Standard", "Hardcore"}
    monkeypatch.setattr(win, "_apply_character_league_filter", lambda: None)
    monkeypatch.setattr(win, "_stash_trees", {"Standard": win._stash_trees["Standard"],
                                              "Hardcore": []})

    win._on_league_changed("Hardcore")

    assert win._current_stash_selection is None

    win.worker.stop()
    win.worker.wait(5000)


def test_league_change_clears_the_visible_item_list(qapp, monkeypatch) -> None:
    """Peter, 2026-08-03: "Wenn ich die League wechsle bleibt der aktuelle
    Inhalt der Itemliste erhalten. Das sollte denke ich nicht sein." — vor
    dem Fix leerte ``_on_league_changed`` nur die Auswahl-Variablen, nicht
    aber ``table_model``/``history_model`` selbst."""
    win = _three_tab_window(monkeypatch)
    win._show_stash_selection(["t1"])
    assert win._visible_rows() != []
    win._live_leagues = {"Standard", "Hardcore"}
    monkeypatch.setattr(win, "_apply_character_league_filter", lambda: None)
    monkeypatch.setattr(win, "_stash_trees", {"Standard": win._stash_trees["Standard"],
                                              "Hardcore": []})

    win._on_league_changed("Hardcore")

    assert win._visible_rows() == []

    win.worker.stop()
    win.worker.wait(5000)


def test_multi_selection_with_nothing_cached_shows_zero_items(qapp, monkeypatch) -> None:
    win = _three_tab_window(monkeypatch)

    win._show_stash_selection(["t3"])  # nie geladen

    assert win._visible_rows() == []
    assert "0 loaded, 1 never loaded" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


# --- "Export visible items" auch im Stash-Baum-Kontextmenue -------------- #

def test_tree_export_visible_requested_reaches_export_csv(qapp, monkeypatch, tmp_path) -> None:
    """Peter, 2026-08-03: "im Stash-Tree das 'Export visible Items'-
    Rechtsklick menu auch aufnehmen" — Verdrahtungstest wie beim
    Toolbar-Knopf, nur ueber das neue Baum-Signal ausgeloest."""
    win = _three_tab_window(monkeypatch)
    win._show_items("t1", win._items["Standard"]["t1"], "Currency 1")
    target = tmp_path / "out.csv"
    monkeypatch.setattr("poe_view.ui.main_window.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "CSV files (*.csv)")))

    win.tree.export_visible_requested.emit()

    assert target.exists()
    assert "Chaos Orb" in target.read_text(encoding="utf-8-sig")

    win.worker.stop()
    win.worker.wait(5000)


def test_character_list_export_visible_requested_reaches_export_csv(
        qapp, monkeypatch, tmp_path) -> None:
    """Peter, 2026-08-03: "Sollen wir das in der Character-Liste auch in
    den Rechtsklick mit aufnehmen?" — dieselbe Verdrahtung wie beim
    Stash-Baum, nur ueber CharacterList.export_visible_requested."""
    win = _three_tab_window(monkeypatch)
    win._show_items("t1", win._items["Standard"]["t1"], "Currency 1")
    target = tmp_path / "out.csv"
    monkeypatch.setattr("poe_view.ui.main_window.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "CSV files (*.csv)")))

    win.character_list.export_visible_requested.emit()

    assert target.exists()
    assert "Chaos Orb" in target.read_text(encoding="utf-8-sig")

    win.worker.stop()
    win.worker.wait(5000)


# --- "Updated HH:MM:SS": wann wurde die Tabelle zuletzt neu aufgebaut --- #

def test_the_view_timestamp_updates_on_every_table_rebuild(qapp, monkeypatch) -> None:
    """Peter, 2026-08-04: "Bin im 'Single' Mode und habe die ganze Zeit
    mein Inventar beobachtet ... aber es hat sich nichts getan." Das Log
    zeigte gleichzeitig alle ~13 s erfolgreiche Abrufe. Ohne eine sichtbare
    Marke liess sich nicht unterscheiden, ob die Ansicht nicht neu gesetzt
    oder nur nicht neu gezeichnet wurde."""
    win = _three_tab_window(monkeypatch)
    assert win._view_updated_label.text() == ""

    win._show_items("t1", win._items["Standard"]["t1"], "Currency 1")

    assert win._view_updated_label.text().startswith("Updated ")

    win.worker.stop()
    win.worker.wait(5000)


def test_the_view_timestamp_also_covers_the_character_view(qapp, monkeypatch) -> None:
    """Gerade die Charakter-Ansicht war der Anlass — sie ist das Ziel des
    Single-Modus, wenn ein Charakter ausgewaehlt ist."""
    win = _three_tab_window(monkeypatch)
    win._show_items("t1", win._items["Standard"]["t1"], "Currency 1")
    before = win._view_updated_label.text()
    win._view_updated_label.setText("")  # zuruecksetzen, um den naechsten Aufbau zu sehen

    win._show_character_items("WitchOfPeter",
                              [Item.model_validate({"typeLine": "Chaos Orb"})])

    assert before.startswith("Updated ")
    assert win._view_updated_label.text().startswith("Updated ")

    win.worker.stop()
    win.worker.wait(5000)


def test_unchanged_duration_is_formatted_and_suppressed_when_short(qapp) -> None:
    """Unterhalb einer Minute bleibt der Zusatz weg: Im Single-Modus liegen
    ~13 s zwischen zwei Abrufen, und dass sich dazwischen nichts geaendert
    hat, ist der Normalfall. Der Zusatz soll auffallen, wenn er auftaucht."""
    from datetime import timedelta

    now = datetime(2026, 8, 5, 14, 0, 0)
    text = MainWindow._unchanged_duration_text

    assert text(None, now) == ""
    assert text(now - timedelta(seconds=59), now) == ""
    assert text(now - timedelta(seconds=60), now) == "unchanged for 1m"
    assert text(now - timedelta(minutes=12), now) == "unchanged for 12m"
    assert text(now - timedelta(minutes=59), now) == "unchanged for 59m"
    assert text(now - timedelta(hours=2), now) == "unchanged for 2h"
    assert text(now - timedelta(hours=2, minutes=5), now) == "unchanged for 2h 5m"


def test_a_rate_limit_pause_does_not_count_as_checked_and_unchanged(
        qapp, monkeypatch) -> None:
    """Peter, 2026-08-05: ""unchanged" war jetzt 9 Minuten, aber gerade
    wieder Daten bekommen." Das Log loeste es auf: Von diesen neun Minuten
    waren fuenf eine Rate-Limit-Pause (22:54:44 stand der Zaehler bei
    25/30, danach bis 22:59:45 kein einziger Request). In dieser Zeit hat
    niemand nachgesehen — sie mitzuzaehlen behauptet eine Pruefung, die
    nicht stattgefunden hat."""
    from datetime import timedelta

    win = _three_tab_window(monkeypatch)
    items = win._items["Standard"]["t1"]
    win._show_items("t1", items, "Currency 1")

    # Zehn Minuten seit der letzten inhaltlichen Aenderung, davon fuenf
    # Minuten Rate-Limit-Pause — wie im echten Log.
    win._view_content_since -= timedelta(minutes=10)
    win._unchanged_idle_s = 5 * 60
    win._show_items("t1", items, "Currency 1")

    assert "unchanged for 5m" in win._view_updated_label.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_the_pause_counter_and_the_status_text_cannot_drift_apart(
        qapp, monkeypatch) -> None:
    """Anzeige und Buchfuehrung lesen dieselbe Quelle. Genau ihr
    Auseinanderlaufen war der Fehler: Die Statuszeile sagte korrekt
    "waiting for rate-limit headroom", waehrend "unchanged for" die Pause
    trotzdem als geprueft mitzaehlte."""
    win = _three_tab_window(monkeypatch)
    win._refresh_mode = "pause"

    assert win._refresh_idle_reason() is not None
    assert win._refresh_state_text() == win._refresh_idle_reason()

    before = win._unchanged_idle_s
    win._countdown_timer.timeout.emit()
    assert win._unchanged_idle_s > before  # Pause wird mitgeschrieben

    # Und im Normalbetrieb laeuft der Zaehler NICHT mit.
    win._refresh_mode = "single"
    win._refresh_mode_next_due = time.monotonic() + 10
    assert win._refresh_idle_reason() is None
    steady = win._unchanged_idle_s
    win._countdown_timer.timeout.emit()
    assert win._unchanged_idle_s == steady

    win.worker.stop()
    win.worker.wait(5000)


def test_identical_data_is_reported_as_unchanged_and_a_change_resets_it(
        qapp, monkeypatch) -> None:
    """Peter, 2026-08-04, zur Single-Modus-Frage: Ein weiterlaufender
    Zeitstempel allein sagt nicht, ob GGG tatsaechlich Neues liefert — die
    API veroeffentlicht neue Fach-Inhalte oft erst nach einem Zonenwechsel
    (FALLSTRICKE #58). Erst beide Angaben zusammen trennen "wir holen
    nichts mehr" von "wir holen, GGG liefert Altes"."""
    from datetime import timedelta

    win = _three_tab_window(monkeypatch)
    items = win._items["Standard"]["t1"]

    win._show_items("t1", items, "Currency 1")
    assert "unchanged" not in win._view_updated_label.text()

    # Wie nach fuenf Minuten Abrufen mit stets demselben Ergebnis.
    win._view_content_since -= timedelta(minutes=5)
    win._show_items("t1", items, "Currency 1")
    assert "unchanged for 5m" in win._view_updated_label.text()

    # Sobald sich etwas aendert, faengt die Zaehlung von vorn an.
    win._show_items("t1", items[:-1], "Currency 1")
    assert "unchanged" not in win._view_updated_label.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_every_inventory_change_is_logged_with_all_three_candidate_causes(
        qapp, caplog) -> None:
    """Peter, 2026-08-05: "Evtl. haengt der Refresh auch von irgendwelchen
    anderen Sachen ab, wie aktiv man im Spiel ist oder wieviel Items im
    Inventar sind und nicht, wie wir bisher annehmen, von der Zeit."
    Beantworten laesst sich das nur aus Daten — und Inhaltsaenderungen
    tauchten bis hierher nur in der Oberflaeche auf, nie im Log. Die Zeile
    muss deshalb ALLE drei zur Debatte stehenden Groessen nebeneinander
    tragen, sonst laesst sich hinterher nichts gegeneinander pruefen."""
    import logging

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_zone_changed("Arachnid Nest")

    # Erster Abruf der Sitzung: nur Startpunkt, keine beobachtete Aenderung.
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "a", "typeLine": "Chaos Orb"})], False)

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "a", "typeLine": "Chaos Orb"}),
            Item.model_validate({"id": "b", "typeLine": "Divine Orb"})], False)

    line = next(m for m in caplog.messages if "Inventar-Änderung" in m)
    assert "WitchOfPeter" in line
    assert "+1/-0/~0" in line          # was sich geaendert hat
    assert "2 Items" in line           # Umfang des Inventars
    assert "Abrufe" in line            # verstrichene Zeit + Abrufe
    assert "Arachnid Nest" in line     # Spielaktivitaet, soweit sichtbar

    win.worker.stop()
    win.worker.wait(5000)


def test_the_first_fetch_of_a_session_is_marked_as_such_in_the_measurement(
        qapp, caplog) -> None:
    """Der Abstand zum allerersten Abruf sagt nichts ueber GGG aus — er
    misst, wann das Programm gestartet wurde. Als Messwert getarnt wuerde
    er die Auswertung still verfaelschen."""
    import logging

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._character_items["WitchOfPeter"] = [
        Item.model_validate({"id": "old", "typeLine": "Kishara's Star"})]

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        # Erster Abruf: gecachte Basis, es wird bewusst nichts geloggt.
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "a", "typeLine": "Chaos Orb"})], False)
        assert not [m for m in caplog.messages if "Inventar-Änderung" in m]

        # Zweiter Abruf: erste echte Aenderung, aber gemessen ab Sitzungsbeginn.
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "a", "typeLine": "Chaos Orb"}),
            Item.model_validate({"id": "b", "typeLine": "Divine Orb"})], False)
        first = next(m for m in caplog.messages if "Inventar-Änderung" in m)
        assert "seit Sitzungsbeginn" in first

        # Ab der dritten: echte Abstaende zwischen zwei Veroeffentlichungen.
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "a", "typeLine": "Chaos Orb"})], False)
        last = [m for m in caplog.messages if "Inventar-Änderung" in m][-1]
        assert "seit der letzten Änderung" in last

    win.worker.stop()
    win.worker.wait(5000)


def test_differing_fields_lists_only_the_fields_that_actually_differ() -> None:
    a = Item.model_validate({"id": "x", "typeLine": "Rat's Nest", "inventoryId": "Helm",
                             "corrupted": False, "ilvl": 84})
    b = Item.model_validate({"id": "x", "typeLine": "Rat's Nest", "inventoryId": "Helm",
                             "corrupted": True, "ilvl": 84})
    assert MainWindow._differing_fields(a, b) == ["corrupted"]
    assert MainWindow._differing_fields(a, a) == []


def test_equipped_item_change_shortly_after_a_zone_change_logs_the_field(
        qapp, caplog) -> None:
    """Mechanismus-Test für die Diagnose-Zeile aus ARCHITEKTUR.md §4.33:
    Eine ECHTE Feldänderung an einem Ausrüstungsteil (hier ``corrupted``,
    stellvertretend für jedes Feld außerhalb von
    ``_VOLATILE_LIST_ORDER_FIELDS``) soll weiterhin erkannt und geloggt
    werden. Die ursprünglich vermutete Ursache (vertauschte Reihenfolge
    von ``socketedItems``) ist eigens abgedeckt, siehe die Tests direkt
    darunter."""
    import logging

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                             "inventoryId": "Helm", "corrupted": False})], False)
    win._on_zone_changed("Backstreet Hideout")

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                 "inventoryId": "Helm", "corrupted": True})], False)

    line = next(m for m in caplog.messages if "als GEÄNDERT erkannt" in m)
    assert "Rat's Nest" in line
    assert "Helm" in line
    assert "corrupted" in line

    win.worker.stop()
    win.worker.wait(5000)


def test_reordered_socketed_gems_do_not_count_as_a_changed_item() -> None:
    """Die gefundene Ursache selbst (ARCHITEKTUR.md §4.33): Peters echtes
    Log zeigte am 2026-08-10 acht von acht sockelbaren Ausrüstungsteilen
    gleichzeitig als 'geändert', jedes Mal exakt im Feld
    'socketedItems' — beim selben Zonenwechsel acht Gems auf einmal
    aufsteigen zu lassen wäre kein Zufall gewesen. Reproduziert: dieselben
    zwei Gems, nur in vertauschter Reihenfolge, gelten über Pydantics
    Listenvergleich als 'verschieden', obwohl nichts passiert ist."""
    gem_a = {"id": "gem-a", "typeLine": "Fire Trap", "socket": 0}
    gem_b = {"id": "gem-b", "typeLine": "Swift Affliction Support", "socket": 1}
    previous = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                     "inventoryId": "Helm",
                                     "socketedItems": [gem_a, gem_b]})]
    current = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                    "inventoryId": "Helm",
                                    "socketedItems": [gem_b, gem_a]})]

    added_ids, changed_ids, removed_items = MainWindow._diff_character_items(previous, current)

    assert added_ids == frozenset()
    assert changed_ids == frozenset()
    assert removed_items == []


def test_a_genuine_change_inside_socketed_items_still_counts_as_changed() -> None:
    """Gegenprobe zum Test oben: Die Normalisierung darf eine ECHTE
    Änderung an einem Gem (hier eine Stufenaufstufung) nicht verstecken —
    sie soll nur die Reihenfolge unwichtig machen, nicht den Inhalt."""
    gem_a = {"id": "gem-a", "typeLine": "Fire Trap", "socket": 0}
    gem_b = {"id": "gem-b", "typeLine": "Swift Affliction Support", "socket": 1}
    gem_a_leveled = {"id": "gem-a", "typeLine": "Fire Trap", "socket": 0, "ilvl": 5}
    previous = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                     "inventoryId": "Helm",
                                     "socketedItems": [gem_a, gem_b]})]
    current = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                    "inventoryId": "Helm",
                                    "socketedItems": [gem_b, gem_a_leveled]})]

    added_ids, changed_ids, removed_items = MainWindow._diff_character_items(previous, current)

    assert changed_ids == frozenset({"helm-1"})


def _gem_with_experience(gem_id: str, name: str, experience: int, level: str = "18") -> dict:
    """Sockel-Gem im Aufbau von Peters echten Daten (Feldnamen und
    Verschachtelung 1:1 aus seinem Cache uebernommen, siehe
    ``services/gem_xp_log.py``) — die Erfahrung steckt als
    ``current/max``-Zeichenkette in ``additionalProperties``."""
    return {
        "id": gem_id, "typeLine": name, "socket": 0,
        "properties": [{"name": "Level", "values": [[level, 0]]}],
        "additionalProperties": [
            {"name": "Experience", "values": [[f"{experience}/226180911", 0]],
             "progress": experience / 226180911},
        ],
    }


def test_growing_gem_experience_does_not_count_as_a_changed_item() -> None:
    """DIE Ursache dafuer, dass nach jedem Zonenwechsel praktisch die
    ganze Ausruestung tuerkis aufleuchtete (Peter, 2026-08-10,
    ARCHITEKTUR.md §4.33). Gemessen an seiner echten Spielrunde: Zwischen
    zwei zwoelf Sekunden auseinanderliegenden Abrufen hatten 25 von 29
    Sockel-Gems neue Erfahrungswerte — damit gilt jedes sockelbare
    Ausruestungsteil beim Spielen dauernd als 'geaendert', ohne dass an
    der Ausruestung selbst irgendetwas passiert waere."""
    previous = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                     "inventoryId": "Helm",
                                     "socketedItems": [
                                         _gem_with_experience("gem-a", "Fire Trap", 66921722)]})]
    current = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                    "inventoryId": "Helm",
                                    "socketedItems": [
                                        _gem_with_experience("gem-a", "Fire Trap", 68417244)]})]

    added_ids, changed_ids, removed_items = MainWindow._diff_character_items(previous, current)

    assert added_ids == frozenset()
    assert changed_ids == frozenset()
    assert removed_items == []


def test_a_gem_level_up_still_counts_as_a_changed_item() -> None:
    """Gegenprobe: Nur der Erfahrungsbalken faellt aus dem Vergleich, die
    Gem-STUFE ausdruecklich nicht — ein Gem, das tatsaechlich aufsteigt,
    ist eine echte Aenderung, die Peter sehen soll."""
    previous = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                     "inventoryId": "Helm",
                                     "socketedItems": [
                                         _gem_with_experience("gem-a", "Fire Trap", 66921722,
                                                              level="18")]})]
    current = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                    "inventoryId": "Helm",
                                    "socketedItems": [
                                        _gem_with_experience("gem-a", "Fire Trap", 12,
                                                             level="19")]})]

    _, changed_ids, _ = MainWindow._diff_character_items(previous, current)

    assert changed_ids == frozenset({"helm-1"})


def test_stripping_gem_experience_leaves_the_cached_item_untouched() -> None:
    """``model_dump()`` reicht die ueber ``extra="allow"`` mitgefuehrten
    Rohfelder unkopiert durch — wuerde die Normalisierung die Gem-Dicts an
    Ort und Stelle aendern, verstuemmelte sie den zwischengespeicherten
    Item-Zustand selbst und damit die Grundlage der Gem-XP-Mitschrift."""
    gem = _gem_with_experience("gem-a", "Fire Trap", 66921722)
    item = Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                "inventoryId": "Helm", "socketedItems": [gem]})

    _stable_item_dump(item)

    names = [p["name"] for p in item.socketedItems[0]["additionalProperties"]]
    assert names == ["Experience"]


def _flask(charges: int, maximum: int = 45) -> Item:
    """Flasche im Aufbau von Peters echten Daten: Die aktuelle Ladung
    steht in ``properties`` unter ``Currently has {0} Charges``, die
    maximale in der Verbrauchszeile darueber."""
    return Item.model_validate({
        "id": "flask-1", "typeLine": "Divine Life Flask", "inventoryId": "Flask",
        "properties": [
            {"name": "Consumes {0} of {1} Charges on use",
             "values": [["15", 0], [str(maximum), 0]], "displayMode": 3},
            {"name": "Currently has {0} Charges",
             "values": [[str(charges), 0]], "displayMode": 3},
        ],
    })


def test_changing_flask_charges_do_not_count_as_a_changed_item() -> None:
    """Peter, 2026-08-11: "Flaschen-Ladungen spielen generell keine Rolle,
    da sich die maximale Anzahl nicht aendert und beim Spielen die
    aktuellen Ladungen staendig schwanken." An einem einzigen Spielabend
    hatten seine Flaschen dadurch viermal grundlos aufgeleuchtet —
    dieselbe Sorte Rauschen wie die Gem-Erfahrung, nur eine Ebene
    hoeher."""
    added_ids, changed_ids, removed_items = MainWindow._diff_character_items(
        [_flask(45)], [_flask(30)])

    assert added_ids == frozenset()
    assert changed_ids == frozenset()
    assert removed_items == []


def test_a_flask_change_other_than_its_charges_still_counts() -> None:
    """Gegenprobe: Nur die EINE schwankende Eigenschaft faellt raus, nicht
    ``properties`` als Ganzes. Hier steigt die maximale Ladungszahl (in
    echt: eine andere Flasche oder ein neuer Affix) — das soll sichtbar
    bleiben. Derselbe Grund, aus dem die Stapelgroesse von Waehrung
    weiterhin zaehlt: Sie steht im selben Feld."""
    _, changed_ids, _ = MainWindow._diff_character_items(
        [_flask(45, maximum=45)], [_flask(45, maximum=60)])

    assert changed_ids == frozenset({"flask-1"})


def test_a_gem_level_up_marks_the_item_green() -> None:
    """Peter, 2026-08-11 (§4.33): Waffe und Schildhand leuchteten als
    einzige Ausruestung auf, und das voellig zu Recht — in beiden war ein
    frisch gesockeltes Gem aufgestiegen (Increased Area of Effect Support
    3 -> 5, Minion Life Support 5 -> 8). Genau dieser Fall bekommt seit
    seiner Rueckmeldung eine eigene Farbe, damit man ihn nicht erst im
    Log nachschlagen muss."""
    previous = [Item.model_validate({"id": "wand-1", "typeLine": "Heavy Somatic Wand",
                                     "inventoryId": "Weapon2",
                                     "socketedItems": [
                                         _gem_with_experience("gem-a", "Increased Area of "
                                                              "Effect Support", 697891,
                                                              level="3")]})]
    current = [Item.model_validate({"id": "wand-1", "typeLine": "Heavy Somatic Wand",
                                    "inventoryId": "Weapon2",
                                    "socketedItems": [
                                        _gem_with_experience("gem-a", "Increased Area of "
                                                             "Effect Support", 12,
                                                             level="5")]})]

    assert MainWindow._gem_leveled_ids(previous, current) == frozenset({"wand-1"})


def test_a_freshly_socketed_gem_is_not_a_level_up() -> None:
    """Ein neu eingesetztes Gem bringt seine Stufe mit, ohne aufgestiegen
    zu sein. Peter hat am 2026-08-11 genau das getan (Armageddon Brand
    raus, Increased Area of Effect Support rein) — die Zeile soll dabei
    tuerkis bleiben, denn geaendert hat sich der SOCKEL, nicht die
    Stufe."""
    previous = [Item.model_validate({"id": "wand-1", "typeLine": "Heavy Somatic Wand",
                                     "inventoryId": "Weapon2",
                                     "socketedItems": [
                                         _gem_with_experience("gem-alt", "Armageddon Brand",
                                                              5000, level="19")]})]
    current = [Item.model_validate({"id": "wand-1", "typeLine": "Heavy Somatic Wand",
                                    "inventoryId": "Weapon2",
                                    "socketedItems": [
                                        _gem_with_experience("gem-neu", "Increased Area of "
                                                             "Effect Support", 0, level="1")]})]

    assert MainWindow._gem_leveled_ids(previous, current) == frozenset()


def test_growing_gem_experience_alone_is_not_a_level_up() -> None:
    """Der Normalfall waehrend des Spielens: Die Erfahrung zaehlt hoch,
    die Stufe bleibt. Waere das schon Gruen, leuchtete die halbe
    Ausruestung dauerhaft in der Aufstiegsfarbe — der Fehler von §4.33 in
    neuen Kleidern."""
    previous = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                     "inventoryId": "Helm",
                                     "socketedItems": [
                                         _gem_with_experience("gem-a", "Fire Trap", 66921722)]})]
    current = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                    "inventoryId": "Helm",
                                    "socketedItems": [
                                        _gem_with_experience("gem-a", "Fire Trap", 68417244)]})]

    assert MainWindow._gem_leveled_ids(previous, current) == frozenset()


def test_the_first_refresh_reports_no_gem_level_ups() -> None:
    """Ohne Vorzustand gibt es nichts zu vergleichen. Derselbe Grund, aus
    dem die Tuerkis-Hervorhebung beim ersten Anzeigen schweigt: Ein
    wochenalter oder gar kein Vergleichsstand liesse halbe Inventare
    aufleuchten, als waere das gerade passiert."""
    current = [Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                    "inventoryId": "Helm",
                                    "socketedItems": [
                                        _gem_with_experience("gem-a", "Fire Trap", 12)]})]

    assert MainWindow._gem_leveled_ids(None, current) == frozenset()


def test_socketed_items_reordering_is_not_logged_as_an_equipment_change(
        qapp, caplog) -> None:
    """Ende-zu-Ende-Fassung des Fixes: die Diagnose-Zeile aus §4.33 soll
    für den jetzt behobenen Fall nicht mehr feuern, auch dann nicht, wenn
    der Zonenwechsel gerade erst stattgefunden hat."""
    import logging

    gem_a = {"id": "gem-a", "typeLine": "Fire Trap", "socket": 0}
    gem_b = {"id": "gem-b", "typeLine": "Swift Affliction Support", "socket": 1}

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                             "inventoryId": "Helm", "socketedItems": [gem_a, gem_b]})], False)
    win._on_zone_changed("Backstreet Hideout")

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                 "inventoryId": "Helm",
                                 "socketedItems": [gem_b, gem_a]})], False)

    assert not [m for m in caplog.messages if "als GEÄNDERT erkannt" in m]
    assert not [m for m in caplog.messages if "als NEU erkannt" in m]

    win.worker.stop()
    win.worker.wait(5000)


def test_equipped_item_change_long_after_a_zone_change_is_not_logged(
        qapp, caplog) -> None:
    """Ohne die Zeitgrenze würde jede spätere Änderung (z. B. eine
    Flaschenladung mitten in der nächsten Map) mitgeloggt — das Log soll
    aber nur die Fälle zeigen, die tatsächlich zeitlich an einen
    Zonenwechsel anschließen."""
    import logging

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                             "inventoryId": "Helm", "corrupted": False})], False)
    win._on_zone_changed("Backstreet Hideout")
    win._last_zone_at -= 30  # weit ausserhalb des Zeitfensters

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                 "inventoryId": "Helm", "corrupted": True})], False)

    assert not [m for m in caplog.messages if "als GEÄNDERT erkannt" in m]

    win.worker.stop()
    win.worker.wait(5000)


def test_a_changed_inventory_item_is_logged_but_not_as_equipment(
        qapp, caplog) -> None:
    """Die Diagnose galt zunaechst nur der Ausruestung (Peters Wortlaut:
    'die ANGELEGTEN Items') und deckt seit seiner zweiten Meldung ALLE
    Slots ab: Die Beschraenkung war eine Wette darauf, WO der Fehler
    steckt, und die kostet beim naechsten Mal einen ganzen Spielabend,
    wenn sie danebenliegt. Die Ausruestung bleibt in der Zeile trotzdem
    als solche erkennbar, sonst waere der urspruengliche Fall im Log
    nicht mehr von einem beliebigen Rucksack-Item zu unterscheiden."""
    import logging

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "bag-1", "typeLine": "Chaos Orb",
                             "inventoryId": "MainInventory", "identified": False})], False)
    win._on_zone_changed("Backstreet Hideout")

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "bag-1", "typeLine": "Chaos Orb",
                                 "inventoryId": "MainInventory", "identified": True})], False)

    line = next(m for m in caplog.messages if "als GEÄNDERT erkannt" in m)
    assert line.startswith("Item als GEÄNDERT")
    assert "identified" in line

    win.worker.stop()
    win.worker.wait(5000)


def test_the_highlight_summary_reports_how_many_rows_are_marked(qapp, caplog) -> None:
    """Entstanden aus einem Widerspruch, der sich als Fehldeutung eines
    Screenshots herausstellte (§4.33): Diese Zusammenfassung haelt fest,
    wie viele Zeilen die Anzeige SELBST fuer hervorgehoben haelt — weicht
    das von dem ab, was auf dem Bildschirm zu sehen ist, liegt der Fehler
    in der Darstellung und nicht im Vergleich. Genau diese Frage hat
    damals einen Cache-Vergleich und eine Rueckfrage gekostet. Bewusst
    OHNE Bindung an einen Zonenwechsel, sie soll bei jedem Refresh
    mitlaufen."""
    import logging

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "ring-1", "typeLine": "Amethyst Ring",
                             "inventoryId": "Ring"}),
        Item.model_validate({"id": "bag-1", "typeLine": "Chaos Orb",
                             "inventoryId": "MainInventory", "stackSize": 1})], False)

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "ring-1", "typeLine": "Amethyst Ring",
                                 "inventoryId": "Ring"}),
            Item.model_validate({"id": "bag-1", "typeLine": "Chaos Orb",
                                 "inventoryId": "MainInventory", "stackSize": 2}),
            Item.model_validate({"id": "bag-2", "typeLine": "Portal Scroll",
                                 "inventoryId": "MainInventory"})], False)

    line = next(m for m in caplog.messages if "Hervorhebung" in m)
    assert "2 von 3 angezeigten Zeilen" in line
    assert "1 neu, 1 geändert" in line

    win.worker.stop()
    win.worker.wait(5000)


def test_the_highlight_summary_counts_gem_level_ups_separately(qapp, caplog) -> None:
    """Seit es zwei Farben gibt, muss die Zusammenfassung beide nennen —
    sonst laesst sich der Bildschirm nicht mehr gegen sie pruefen, und
    genau dafuer ist sie da. Die Zahl beantwortet ausserdem im Vorbeigehen
    die Frage, die Peter am 2026-08-11 gestellt hat: War die Markierung
    berechtigt?"""
    import logging

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "wand-1", "typeLine": "Heavy Somatic Wand",
                             "inventoryId": "Weapon2",
                             "socketedItems": [
                                 _gem_with_experience("gem-a", "Fire Trap", 900, level="15")]}),
        Item.model_validate({"id": "bag-1", "typeLine": "Chaos Orb",
                             "inventoryId": "MainInventory", "stackSize": 1})], False)

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "wand-1", "typeLine": "Heavy Somatic Wand",
                                 "inventoryId": "Weapon2",
                                 "socketedItems": [
                                     _gem_with_experience("gem-a", "Fire Trap", 12, level="16")]}),
            Item.model_validate({"id": "bag-1", "typeLine": "Chaos Orb",
                                 "inventoryId": "MainInventory", "stackSize": 2})], False)

    line = next(m for m in caplog.messages if "Hervorhebung" in m)
    assert "2 von 2 angezeigten Zeilen" in line
    assert "0 neu, 2 geändert" in line
    assert "davon 1 mit Gem-Aufstieg" in line

    win.worker.stop()
    win.worker.wait(5000)


def test_an_unchanged_refresh_writes_no_highlight_summary(qapp, caplog) -> None:
    """Gegenprobe: Solange nichts hervorgehoben wird, soll die
    Zusammenfassung schweigen — sonst stuende bei jedem der alle paar
    Sekunden laufenden Hintergrund-Refreshes eine Zeile im Log."""
    import logging

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    item = {"id": "ring-1", "typeLine": "Amethyst Ring", "inventoryId": "Ring"}
    win._on_character_items("WitchOfPeter", [Item.model_validate(item)], False)

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_items("WitchOfPeter", [Item.model_validate(item)], False)

    assert not [m for m in caplog.messages if "Hervorhebung" in m]

    win.worker.stop()
    win.worker.wait(5000)


def test_a_new_id_on_an_equipped_slot_shortly_after_a_zone_change_is_logged_distinctly(
        qapp, caplog) -> None:
    """Deckt die andere mögliche Ursache ab: nicht ein geändertes Feld
    unter derselben ID, sondern eine ganz neue ID auf demselben Slot
    (``added_ids`` statt ``changed_ids``) — falls GGG Ausrüstungs-Items
    bei einem Zonenwechsel neu durchnummeriert, taucht das hier auf,
    nicht als 'GEÄNDERT'."""
    import logging

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "helm-old", "typeLine": "Rat's Nest",
                             "inventoryId": "Helm"})], False)
    win._on_zone_changed("Backstreet Hideout")

    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_items("WitchOfPeter", [
            Item.model_validate({"id": "helm-new", "typeLine": "Rat's Nest",
                                 "inventoryId": "Helm"})], False)

    line = next(m for m in caplog.messages if "als NEU erkannt" in m)
    assert "Rat's Nest" in line
    assert "Helm" in line
    assert not [m for m in caplog.messages if "als GEÄNDERT erkannt" in m]

    win.worker.stop()
    win.worker.wait(5000)


def test_a_cached_inventory_is_not_used_as_a_history_baseline(qapp) -> None:
    """Peter, 2026-08-04: "Hab gerade gesehen, dass in meiner History noch
    Kishara's Star drin war. Ein Item, das ich schon lange nicht mehr
    habe." Der Verlauf ueberlebt keinen Neustart, der Inventarstand schon
    — der erste Abruf nach dem Start verglich deshalb gegen einen
    womoeglich wochenalten Stand und schrieb alles Zwischenzeitliche mit
    der AKTUELLEN Uhrzeit ins Protokoll."""
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    # Stand wie nach _restore_cached_data: liegt im Speicher, stammt aber
    # aus einem frueheren Programmlauf.
    win._character_items["WitchOfPeter"] = [
        Item.model_validate({"id": "old", "typeLine": "Kishara's Star"})]

    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "new", "typeLine": "Chaos Orb"})], False)

    assert list(win._item_history) == []  # kein Ereignis aus der Vergangenheit

    # Ab dem zweiten Abruf dieser Sitzung ist der Vergleich wieder gueltig.
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "new", "typeLine": "Chaos Orb"}),
        Item.model_validate({"id": "fresh", "typeLine": "Divine Orb"})], False)

    assert [e.item.display_name for e in win._item_history] == ["Divine Orb"]

    win.worker.stop()
    win.worker.wait(5000)


def test_a_cached_inventory_does_not_light_up_the_table_either(qapp) -> None:
    """Gegenstueck zum Test darueber, gleiche Ursache eine Ebene weiter
    vorn: Der aus der Datei geladene Stand darf auch die Tuerkis-/Grau-
    Hervorhebung nicht ausloesen. Sonst leuchtet beim ersten Abruf nach dem
    Programmstart ein halbes Inventar auf, als waere das gerade passiert —
    und das verschwundene Item haengt zusaetzlich als graue Zeile darunter.
    """
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._character_items["WitchOfPeter"] = [
        Item.model_validate({"id": "old", "typeLine": "Kishara's Star"})]

    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "new", "typeLine": "Chaos Orb"})], False)

    assert win.table_model._changed_ids == frozenset()
    assert win.table_model._removed_ids == frozenset()
    # Das seit dem letzten Programmlauf verschwundene Item wird gar nicht
    # erst angehaengt — nur das, was jetzt wirklich da ist.
    assert win.table_model.rowCount() == 1

    # Ab dem zweiten Abruf dieser Sitzung ist der Vergleich wieder gueltig.
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "new", "typeLine": "Chaos Orb"}),
        Item.model_validate({"id": "fresh", "typeLine": "Divine Orb"})], False)

    assert win.table_model._changed_ids == frozenset({"fresh"})

    win.worker.stop()
    win.worker.wait(5000)


def test_the_history_baseline_resets_on_logout(qapp, monkeypatch) -> None:
    """Nach einem Logout faengt alles von vorn an — sonst gaelte der Stand
    des abgemeldeten Kontos als Vergleichsbasis fuer das naechste."""
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_logged_in("TestAccount#1234")
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "1", "typeLine": "Sword"})], False)
    assert "WitchOfPeter" in win._session_fetched_chars

    win._on_logout_clicked()

    assert win._session_fetched_chars == set()

    win.worker.stop()
    win.worker.wait(5000)


def test_the_toolbar_clock_shows_date_and_time(qapp) -> None:
    """Peter, 2026-08-04: "dann sieht man im gleichen Screenshot was Sache
    ist." Zweck ist nicht die Uhrzeit an sich, sondern dass ein Screenshot
    allein auswertbar wird — erst im Vergleich mit dieser Uhr sagt das
    "Updated HH:MM:SS" der Statuszeile etwas aus. Mit Datum und in fester
    Schreibweise, damit auch ein Tage spaeter auftauchender Screenshot
    eindeutig bleibt."""
    import re

    win = MainWindow()

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*",
                        win._clock_label.text()), win._clock_label.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_the_clock_reuses_the_existing_one_second_timer(qapp) -> None:
    """Kein zweiter Timer fuer dieselbe Frequenz: die Uhr haengt am
    Countdown-Takt, der ohnehin jede Sekunde laeuft."""
    win = MainWindow()
    win._clock_label.setText("")

    win._countdown_timer.timeout.emit()

    assert win._clock_label.text() != ""

    win.worker.stop()
    win.worker.wait(5000)


def test_a_zone_refresh_does_not_get_a_second_request_on_its_heels(
        qapp, monkeypatch) -> None:
    """Log vom 2026-08-04, dreimal belegt: Nach einem Zonenwechsel-Refresh
    schickte der gleichmaessige Takt eine Sekunde spaeter einen ZWEITEN
    Abruf desselben Ziels hinterher — Sollabstand waeren 13 s. Ursache:
    Der Zonenwechsel-Pfad meldete seinen Abruf nicht beim Takt an, der
    Sekunden-Tick sah seine Faelligkeit abgelaufen und keinen laufenden
    Job. Der zweite Abruf kann nichts liefern, was der erste nicht holt,
    kostet aber Kontingent — und daran fehlte es, als der Takt in die
    fuenfminuetige Zwangspause lief."""
    win = _three_tab_window(monkeypatch)
    win._logged_in = True
    win._refresh_mode = "single"
    win._current_character_name = "WitchOfPeter"
    win._current_stash_id = None
    win._refresh_mode_next_due = 0.0  # Takt ist ueberfaellig, wie im Log

    jobs = []
    monkeypatch.setattr(win.worker, "submit", jobs.append)

    win._on_zone_changed("Arachnid Nest")
    assert len(jobs) == 1                      # der Zonenwechsel-Refresh

    win._countdown_timer.timeout.emit()        # der Takt kommt hinterher
    assert len(jobs) == 1, "zweiter Abruf auf den Fersen des ersten"

    # Erst wenn die Antwort da ist, darf der naechste Takt wieder greifen.
    win._note_refresh_mode_job_done()
    win._refresh_mode_next_due = 0.0
    win._countdown_timer.timeout.emit()
    assert len(jobs) == 2

    win.worker.stop()
    win.worker.wait(5000)


# --- Inline-Vervollstaendigung im Spaltenfilter -------------------------- #

def _filter_edit_with(qapp, *values):
    """Ein Filter-Eingabefeld ueber Items mit den gegebenen baseType-Werten."""
    from poe_view.ui.item_table import BASE_COL
    win = MainWindow()
    win.table_model.set_items([
        Item.model_validate({"typeLine": v, "baseType": v}) for v in values])
    return win, win._build_column_filter_edit(BASE_COL)


def test_typing_a_prefix_completes_it_inline_and_selects_the_rest(qapp) -> None:
    """Peter, 2026-08-06: "direkt hinter dem Cursor erscheint schon der
    passende Text, den ich nur noch durch Tab oder return bestaetigen
    muss." Das Feld hatte zwar seit 2026-08-02 eine Vervollstaendigung,
    aber als Popup-Liste — nicht das Gemeinte."""
    win, edit = _filter_edit_with(qapp, "MainInventory", "Weapon")

    edit.setText("Main")
    edit.textEdited.emit("Main")   # wie beim Tippen

    assert edit.text() == "MainInventory"
    assert edit.selectedText() == "Inventory"   # nur der Rest ist markiert
    # Weitertippen ersetzt die Markierung, Return uebernimmt den ganzen Wert.

    win.worker.stop()
    win.worker.wait(5000)


def test_the_completion_uses_the_real_values_capitalisation(qapp) -> None:
    """Im Feld soll am Ende genau das stehen, was in der Spalte vorkommt —
    sonst passt der Filter zwar (er vergleicht ohne Ruecksicht auf Gross-
    und Kleinschreibung), aber der angezeigte Text weicht ab."""
    win, edit = _filter_edit_with(qapp, "MainInventory")

    edit.setText("main")
    edit.textEdited.emit("main")

    assert edit.text() == "MainInventory"

    win.worker.stop()
    win.worker.wait(5000)


def test_backspace_gets_you_out_of_a_suggestion(qapp) -> None:
    """Der wichtigste Fall: Ergaenzt wird nur beim WACHSEN der Eingabe.
    Sonst loescht die Ruecktaste die Markierung und der Vorschlag stuende
    sofort wieder da — man kaeme nie mehr heraus."""
    win, edit = _filter_edit_with(qapp, "MainInventory")
    edit.setText("Main")
    edit.textEdited.emit("Main")
    assert edit.text() == "MainInventory"

    edit.setText("Main")           # Ruecktaste loescht die Markierung
    edit.textEdited.emit("Main")

    assert edit.text() == "Main"

    win.worker.stop()
    win.worker.wait(5000)


def test_text_without_a_matching_prefix_is_left_alone(qapp) -> None:
    win, edit = _filter_edit_with(qapp, "MainInventory")

    edit.setText(">=20")
    edit.textEdited.emit(">=20")

    assert edit.text() == ">=20"   # Filter-Ausdruecke duerfen nicht ergaenzt werden

    win.worker.stop()
    win.worker.wait(5000)


def test_the_substring_popup_survives_alongside_the_inline_completion(qapp) -> None:
    """Beide nebeneinander, weil sie Verschiedenes koennen: inline braucht
    einen Praefix, das Popup findet "MainInventory" auch bei "inv"."""
    from PySide6.QtCore import Qt
    win, edit = _filter_edit_with(qapp, "MainInventory")

    assert edit.completer() is not None
    assert edit.completer().filterMode() == Qt.MatchFlag.MatchContains

    win.worker.stop()
    win.worker.wait(5000)


# --- "Pin this": Spaltenfilter aus der angeklickten Zelle ---------------- #

def _pinned(win, col: int, source_row: int = 0):
    """Baut das Pin-Menue fuer eine Zelle und loest es aus, ohne
    QMenu.exec() (blockiert ohne echte Nutzerinteraktion)."""
    menu = QMenu(win)
    win._add_pin_action(menu, col, source_row)
    return menu


def test_pin_sets_the_column_filter_to_the_clicked_cells_value(qapp) -> None:
    """Peter, 2026-08-05: "RK auf 'MainInventory' -> Spaltenfilter wird auf
    'MainInventory' gesetzt." Der Wert, nach dem man filtern will, steht
    meistens schon unter dem Mauszeiger — bis dahin musste man ihn im
    Header-Menue abtippen."""
    from poe_view.ui.item_table import BASE_COL
    win = MainWindow()
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "baseType": "Chaos Orb"}),
        Item.model_validate({"typeLine": "Divine Orb", "baseType": "Divine Orb"}),
    ])

    menu = _pinned(win, BASE_COL, 0)
    actions = menu.actions()
    assert len(actions) == 1
    assert actions[0].text() == '📌 Pin Base = "Chaos Orb"'

    actions[0].trigger()

    assert win.proxy.column_filter(BASE_COL) == "=Chaos Orb"
    assert win.proxy.rowCount() == 1  # nur noch die angepinnte Zeile

    win.worker.stop()
    win.worker.wait(5000)


def test_pin_is_exact_so_a_shorter_name_does_not_drag_others_along(qapp) -> None:
    """"=Wert" statt des nackten Werts: Ohne Operator waere es eine
    Teilstring-Suche, bei der "Ring" auch "Ring of Wisdom" mitnaehme —
    "Pin" heisst aber "nur noch diese"."""
    from poe_view.ui.item_table import BASE_COL
    win = MainWindow()
    win.table_model.set_items([
        Item.model_validate({"typeLine": "Ring", "baseType": "Ring"}),
        Item.model_validate({"typeLine": "Ring of Wisdom", "baseType": "Ring of Wisdom"}),
    ])

    _pinned(win, BASE_COL, 0).actions()[0].trigger()

    assert win.proxy.rowCount() == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_pin_is_absent_where_there_is_nothing_to_filter_on(qapp) -> None:
    """Icon-Spalte (kein Text) und der Platzhalter "–" (kein Wert)."""
    from poe_view.ui.item_table import ICON_COL, MODS_COL
    win = MainWindow()
    win.table_model.set_items([Item.model_validate({"typeLine": "Chaos Orb"})])

    assert _pinned(win, ICON_COL, 0).actions() == []
    # Mods sind bei einer Currency leer -> nichts zum Anpinnen
    assert win.table_model.display_text(0, MODS_COL) == ""
    assert _pinned(win, MODS_COL, 0).actions() == []

    win.worker.stop()
    win.worker.wait(5000)


# --- "Load All Tabs": woraus sich die Abrufzahl zusammensetzt ------------ #

def _stash(sid: str, name: str = "", type_: str = "PremiumStash", parent: str | None = None):
    return StashTab(id=sid, name=name or sid, type=type_, parent=parent)


def test_the_breakdown_explains_where_the_request_count_comes_from(qapp) -> None:
    """Peter, 2026-08-03 (Spielertest): "Ich denke, dass die meisten User
    mit den Zahlen nicht klar kommen." Zwei Zaehler mit verschiedenen
    Skalen nebeneinander — "Section 42 of 1456" neben "tab 1 of 362" —
    sehen aus wie ein Widerspruch. Beide stimmen: Ein Map-/Unique-Fach
    belegt EINEN Platz in der Truhenleiste, buendelt darin aber viele
    Sektionen mit je eigenem Abruf. Peter, 2026-08-06: "noch eine Zeile
    fuer die Erklaerung der Berechnung ... oder als mini Tabelle und
    anschliessend als Summe"."""
    win = MainWindow()
    win._current_league = "Standard"
    win._stash_trees["Standard"] = [
        _stash("m1", "Maps", "MapStash"),
        _stash("u1", "Uniques", "UniqueStash"),
    ]
    to_fetch = ([_stash(f"t{i}") for i in range(3)]
                + [_stash(f"ms{i}", parent="m1") for i in range(17)]
                + [_stash(f"us{i}", parent="u1") for i in range(12)])

    rows = win._bulk_breakdown(to_fetch)

    assert rows == [(3, "plain tabs"),
                    (17, "sections in one map tab"),
                    (12, "sections in one unique tab")]
    # Die Summe muss aufgehen — sonst erklaert die Tabelle nichts.
    assert sum(count for count, _ in rows) == len(to_fetch)

    win.worker.stop()
    win.worker.wait(5000)


def test_without_special_tabs_there_is_nothing_to_explain(qapp) -> None:
    """Dann sind beide Zaehler ohnehin gleich — eine Tabelle, die "3 = 3"
    sagt, kostet nur Platz im Dialog."""
    win = MainWindow()
    win._current_league = "Standard"

    assert win._bulk_breakdown([_stash(f"t{i}") for i in range(3)]) == []
    assert win._bulk_breakdown_html([], 3) == ""

    win.worker.stop()
    win.worker.wait(5000)


def test_many_special_tabs_are_summarised_instead_of_listed(qapp) -> None:
    """Sonst waere die Tabelle laenger als der halbe Dialog und erklaerte
    nichts mehr, sondern erschluege."""
    win = MainWindow()
    win._current_league = "Standard"
    win._stash_trees["Standard"] = [
        _stash(f"m{i}", f"Maps {i}", "MapStash") for i in range(10)]
    to_fetch = [_stash(f"s{i}-{j}", parent=f"m{i}")
                for i in range(10) for j in range(i + 1)]

    rows = win._bulk_breakdown(to_fetch)

    assert len(rows) == win._BULK_BREAKDOWN_MAX_ROWS
    # Die Sammelzeile nennt die Art mit, solange es nur eine gibt.
    assert "further map tabs" in rows[-1][1]
    assert sum(count for count, _ in rows) == len(to_fetch)  # Summe geht trotzdem auf

    win.worker.stop()
    win.worker.wait(5000)


def test_the_breakdown_table_ends_in_the_total(qapp) -> None:
    """Peters "anschliessend als Summe": Die Gesamtzahl muss unter ihren
    Summanden stehen, sonst laesst sich die Rechnung nicht nachvollziehen."""
    win = MainWindow()

    html = win._bulk_breakdown_html([(3, "plain tabs"), (17, "sections in one map tab")], 20)

    assert "3" in html and "17" in html
    assert "<b>20</b>" in html and "requests in total" in html
    assert html.index("17") < html.index("<b>20</b>")  # Summe zuletzt

    win.worker.stop()
    win.worker.wait(5000)


def test_the_summary_row_names_the_kind_when_it_is_the_only_one(qapp) -> None:
    """Peter, 2026-08-06, nach dem ersten echten Lauf: "Was sind denn die
    'further Special Tabs'?" — es waren zwoelf Unique-Faecher, und genau
    das haette dastehen koennen. Die Zusammenfassung hatte die einzige
    Information weggelassen, die noch fehlte."""
    win = MainWindow()
    win._current_league = "Standard"
    win._stash_trees["Standard"] = (
        [_stash("m1", "Maps", "MapStash")]
        + [_stash(f"u{i}", f"Uniques {i}", "UniqueStash") for i in range(12)])
    to_fetch = ([_stash(f"ms{j}", parent="m1") for j in range(365)]
                + [_stash(f"s{i}-{j}", parent=f"u{i}")
                   for i in range(12) for j in range(16)])

    rows = win._bulk_breakdown(to_fetch)

    assert "further unique tabs" in rows[-1][1]

    win.worker.stop()
    win.worker.wait(5000)


def test_mixed_kinds_keep_the_neutral_word(qapp) -> None:
    """Sind es verschiedene Arten, stimmt nur noch "special" — dann darf
    die Zeile sich nicht auf eine davon festlegen."""
    win = MainWindow()
    win._current_league = "Standard"
    win._stash_trees["Standard"] = (
        [_stash(f"m{i}", f"Maps {i}", "MapStash") for i in range(6)]
        + [_stash("u1", "Uniques", "UniqueStash")])
    to_fetch = ([_stash(f"ms{i}-{j}", parent=f"m{i}")
                 for i in range(6) for j in range(10 - i)]
                + [_stash(f"us{j}", parent="u1") for j in range(2)])

    rows = win._bulk_breakdown(to_fetch)

    assert "further special tabs" in rows[-1][1]

    win.worker.stop()
    win.worker.wait(5000)


def test_first_character_snapshot_only_sets_the_baseline(qapp, monkeypatch) -> None:
    """Peter, 2026-08-10: Grundlage für die XP/h-Anzeige. Der allererste
    Abruf eines Charakters in dieser Sitzung darf noch keine Rate liefern
    — es gibt noch nichts, wogegen verglichen werden könnte (derselbe
    Grund wie bei ``_PublishWatch``/``stale_baseline``)."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 1_631_274_653)

    assert win._xp_per_hour("WitchOfPeter") is None
    assert win._xp_per_hour("SomeoneElse") is None

    win.worker.stop()
    win.worker.wait(5000)


def test_a_single_experience_change_is_not_enough_for_a_rate(qapp, monkeypatch) -> None:
    """Gemessen wird von Veroeffentlichung zu Veroeffentlichung, also
    braucht es ZWEI Aenderungen. Die erste allein taugt nicht als Basis:
    Was in ihr steckt, wurde teils schon vor dem Start dieser Sitzung
    verdient — sie gegen die Zeit seit Programmstart zu rechnen ergaebe
    eine erfundene Rate."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 1_631_274_653)

    fake_now[0] += 3600.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_631_274_653 + 12_000_000)

    assert win._xp_per_hour("WitchOfPeter") is None

    win.worker.stop()
    win.worker.wait(5000)


def test_the_rate_measures_the_interval_between_two_publications(
        qapp, monkeypatch) -> None:
    """Zwei Veroeffentlichungen im Abstand einer Stunde, dazwischen 12
    Millionen Erfahrung — der einfachste Fall, der den Mechanismus prueft,
    bevor ein Graph darauf aufbaut. Die vielen Abrufe OHNE Aenderung
    dazwischen (real rund 28 von 29, siehe ARCHITEKTUR.md §4.35) duerfen
    das Ergebnis nicht beeinflussen."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)

    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 2_000_000)   # 1. Aenderung
    for _ in range(5):                                          # nichts Neues
        fake_now[0] += 300.0
        win._on_character_snapshot("WitchOfPeter", 87, 2_000_000)
    fake_now[0] += 2100.0
    win._on_character_snapshot("WitchOfPeter", 87, 14_000_000)   # 2. Aenderung, +1h

    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(12_000_000)

    win.worker.stop()
    win.worker.wait(5000)


def test_the_rate_freezes_when_no_more_experience_arrives(qapp, monkeypatch) -> None:
    """Peter, 2026-08-10: "Wir muessen die XP-Berechnung pausieren, sobald
    sie sich nicht mehr aendert." Genau der Fall: Nach zwei
    Veroeffentlichungen steht der Charakter still. Die frueheren Fassung
    teilte durch die verstrichene Uhrzeit und liess die Anzeige dabei
    langsam gegen null sinken, obwohl gar nichts passiert war."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)
    fake_now[0] += 3600.0
    win._on_character_snapshot("WitchOfPeter", 87, 11_000_000)
    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(10_000_000)

    # Drei Stunden Pause, weiter abgefragt, aber nichts Neues.
    for _ in range(3):
        fake_now[0] += 3600.0
        win._on_character_snapshot("WitchOfPeter", 87, 11_000_000)

    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(10_000_000)

    win.worker.stop()
    win.worker.wait(5000)


def test_only_the_last_interval_counts_not_the_whole_session(qapp, monkeypatch) -> None:
    """Peters Befund, 2026-08-11: "Ingame wird mir meine momentane XP/h bei
    182.3M angezeigt, im Tool bei 14.1M." Genau dieser Fall, mit den
    echten Zahlen seiner Sitzung nachgestellt: vier Veroeffentlichungen in
    114 Minuten, dazwischen eine Luecke von 87 Minuten, in der er nicht
    gespielt hat. Ueber die ganze Spanne gemittelt kam Faktor 10 zu wenig
    heraus; das zuletzt abgeschlossene Intervall trifft es."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 0)

    def veroeffentlichung(nach_sekunden: float, zuwachs: int) -> None:
        fake_now[0] += nach_sekunden
        veroeffentlichung.stand += zuwachs
        win._on_character_snapshot("WitchOfPeter", 87, veroeffentlichung.stand)
    veroeffentlichung.stand = 0

    veroeffentlichung(462, 4_470_867)      # 18:24:34
    veroeffentlichung(156, 62_620)         # 18:27:10, 2,6 min spaeter
    veroeffentlichung(5_206, 755_280)      # 19:53:56, 87 min Pause
    veroeffentlichung(432, 2_859_098)      # 20:01:08, 7,2 min

    ueber_alles = (4_470_867 + 62_620 + 755_280 + 2_859_098 - 4_470_867) / ((156 + 5206 + 432) / 3600)
    assert ueber_alles == pytest.approx(2_284_474, rel=0.01)   # die alte Rechnung
    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(2_859_098 / (432 / 3600))
    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(23_825_816, rel=0.01)

    win.worker.stop()
    win.worker.wait(5000)


def test_an_earlier_idle_gap_does_not_drag_the_current_rate_down(
        qapp, monkeypatch) -> None:
    """Zugespitzte Gegenprobe zum Test darueber: Eine Stunde Pause VOR dem
    letzten Intervall darf die Anzeige nicht beruehren. Genau das war der
    Fehler — die vorige Fassung verhinderte nur, dass Zeit NACH der letzten
    Veroeffentlichung verwaessert."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)
    fake_now[0] += 3600.0                      # eine Stunde Pause, fast nichts dazu
    win._on_character_snapshot("WitchOfPeter", 87, 1_100_000)
    fake_now[0] += 360.0                       # sechs Minuten echtes Spielen
    win._on_character_snapshot("WitchOfPeter", 87, 21_100_000)

    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(200_000_000)

    win.worker.stop()
    win.worker.wait(5000)


def test_the_rate_uses_the_time_spent_in_the_zone_just_left(
        qapp, monkeypatch) -> None:
    """Peters echtes Protokoll vom 2026-08-11, der schlimmste Fall darin:
    18:27:09 Hideout (Veroeffentlichung), dann 85 Minuten nichts, dann
    19:52:02 Foundry und 19:53:55 zurueck im Hideout mit +755.280.
    Verdient wurden die in den knapp zwei Minuten in der Foundry — genau
    deren Verweildauer ist der Nenner. Ueber das volle Intervall waeren es
    0,5 Mio./h, eine Zahl, die nach dem Wiedereinstieg wie ein Defekt
    aussaehe."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)   # 18:27:09
    fake_now[0] += 5_093.0                                       # 85 min im Hideout
    win._on_zone_changed("Foundry")                              # 19:52:02
    fake_now[0] += 113.0                                         # Verweildauer in der Map
    win._on_zone_changed("Backstreet Hideout")                   # 19:53:55
    fake_now[0] += 1.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_755_280)    # 19:53:56

    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(755_280 / (113 / 3600))
    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(24_062_336, rel=0.01)

    win.worker.stop()
    win.worker.wait(5000)


def test_a_publication_arriving_inside_the_next_zone_does_not_explode(
        qapp, monkeypatch) -> None:
    """Peter, 2026-08-11: "Hatte gerade 1.53B XP/h. Das kann nicht sein."
    Sein Protokoll, exakt nachgestellt: Die Veroeffentlichung um 22:07:40
    kam, als er laengst in der naechsten Zone war (22:07:37 Trial of
    Lingering Pain). Eine Uhr, die erst beim naechsten Zonenwechsel
    startet, hatte damit nur die drei Sekunden zwischen 22:10:01 und
    22:10:04 — und verteilte 2.192.450 XP darauf. Die Verweildauer in der
    verlassenen Zone sind dagegen die 144 Sekunden im Trial."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 89, 1_802_930_455)
    win._on_zone_changed("Plaza")                                  # 22:04:03
    fake_now[0] += 214.0
    win._on_zone_changed("Trial of Lingering Pain")                # 22:07:37
    fake_now[0] += 3.0
    win._on_character_snapshot("WitchOfPeter", 89, 1_812_607_784)  # 22:07:40
    fake_now[0] += 141.0
    win._on_zone_changed("Plaza")                                  # 22:10:01
    fake_now[0] += 3.0
    win._on_character_snapshot("WitchOfPeter", 89, 1_814_800_234)  # 22:10:04, +2.192.450

    rate = win._xp_per_hour("WitchOfPeter")
    assert rate == pytest.approx(2_192_450 / (144 / 3600))
    assert rate == pytest.approx(54_811_250, rel=0.01)   # nicht 2,99 Mrd.

    win.worker.stop()
    win.worker.wait(5000)


def test_a_publication_without_a_recent_zone_change_uses_the_full_interval(
        qapp, monkeypatch) -> None:
    """Nicht jede Veroeffentlichung folgt auf einen Zonenwechsel — beim
    Haendler kommen sie verspaetet (§4.36). Dann waere die Verweildauer
    einer laengst verlassenen Zone der falsche Nenner; gerechnet wird ueber
    das volle Intervall."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    win._on_zone_changed("Foundry")
    fake_now[0] += 120.0
    win._on_zone_changed("Backstreet Hideout")
    fake_now[0] += 1.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)
    fake_now[0] += 3600.0                       # weit weg von jedem Zonenwechsel
    win._on_character_snapshot("WitchOfPeter", 87, 11_000_000)

    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(10_000_000)

    win.worker.stop()
    win.worker.wait(5000)


def test_without_zone_watching_the_whole_interval_counts(qapp, monkeypatch) -> None:
    """Die Zonen-Beobachtung ist standardmaessig AUS. Ohne sie gibt es
    keinen Startpunkt, dann faellt die Rechnung sauber auf das volle
    Intervall zurueck statt gar keine Rate zu liefern."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)
    fake_now[0] += 3600.0
    win._on_character_snapshot("WitchOfPeter", 87, 11_000_000)

    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(10_000_000)

    win.worker.stop()
    win.worker.wait(5000)


def test_the_very_first_map_of_a_session_already_yields_a_rate(
        qapp, monkeypatch) -> None:
    """Peter, 2026-08-13: "Ich habe eine Anfangs-XP im Tool gehabt und bin
    vom Hideout in eine Map gegangen. Nach der Map (ca. 10 Minuten)
    zurueck ins Hideout und da habe ich eine End-XP bekommen, aber noch
    keine Rate, was theoretisch jetzt moeglich waere."

    Er hatte recht: Der Weg INS Hideout aendert die Erfahrung nicht (dort
    wird nichts verdient), es gab also nur EINE beobachtete Aenderung.
    Der Nenner — die zehn Minuten in der Map — lag laengst gemessen vor,
    nur der Vorgaenger fehlte. Er stand im Sitzungs-Startwert."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)   # Anfangs-XP im Hideout
    fake_now[0] += 300.0
    win._on_zone_changed("Crimson Temple")                      # rein in die Map
    fake_now[0] += 600.0                                        # ca. 10 Minuten
    win._on_zone_changed("Backstreet Hideout")                  # zurueck
    fake_now[0] += 2.0
    win._on_character_snapshot("WitchOfPeter", 87, 21_000_000)  # End-XP

    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(120_000_000)

    win.worker.stop()
    win.worker.wait(5000)


def test_a_baseline_taken_inside_the_measured_zone_yields_no_rate(
        qapp, monkeypatch) -> None:
    """Gegenprobe, damit der Startwert nicht zum Freifahrtschein wird:
    Wurde er erst gelesen, als der Charakter schon IN der Zone stand,
    steckt in der ersten Aenderung auch Erfahrung von davor. Die Rate
    waere dann erfunden — genau der Fehler, den
    ``test_a_single_experience_change_is_not_enough_for_a_rate``
    beschreibt."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_zone_changed("Crimson Temple")                      # Zone schon betreten
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)   # erst jetzt Programmstart
    fake_now[0] += 540.0
    win._on_zone_changed("Backstreet Hideout")
    fake_now[0] += 2.0
    win._on_character_snapshot("WitchOfPeter", 87, 21_000_000)

    assert win._xp_per_hour("WitchOfPeter") is None

    win.worker.stop()
    win.worker.wait(5000)


def test_a_baseline_read_seconds_before_the_zone_change_is_not_trusted(
        qapp, monkeypatch) -> None:
    """Der Sicherheitsabstand: Zwischen einem Zonenwechsel und seiner
    Veroeffentlichung liegen 1-3 Sekunden (§4.34). Faellt der erste Abruf
    in dieses Fenster, ist der Startwert noch der Stand VOR der letzten
    Zone, und ein Teil des Zuwachses gehoert dorthin."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)
    fake_now[0] += 3.0                                          # zu dicht am Wechsel
    win._on_zone_changed("Crimson Temple")
    fake_now[0] += 600.0
    win._on_zone_changed("Backstreet Hideout")
    fake_now[0] += 2.0
    win._on_character_snapshot("WitchOfPeter", 87, 21_000_000)

    assert win._xp_per_hour("WitchOfPeter") is None

    win.worker.stop()
    win.worker.wait(5000)


def test_every_finished_section_becomes_a_point_in_the_graph(
        qapp, monkeypatch) -> None:
    """Der Zeitreihen-Speicher, an dem der Graph bisher hing (§4.40). Er
    haelt genau das, was auch angezeigt wird — Kurve und Zahl duerfen
    nicht auseinanderlaufen."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)    # nur die erste Aenderung
    assert win._xp_watch["WitchOfPeter"].history == []           # noch keine Rate, kein Punkt

    fake_now[0] += 600.0
    win._on_character_snapshot("WitchOfPeter", 87, 21_000_000)
    fake_now[0] += 300.0
    win._on_character_snapshot("WitchOfPeter", 87, 26_000_000)

    verlauf = win._xp_watch["WitchOfPeter"].history
    assert [p.seconds for p in verlauf] == [600.0, 300.0]
    assert [p.rate for p in verlauf] == [pytest.approx(120_000_000),
                                         pytest.approx(60_000_000)]
    assert verlauf[-1].rate == pytest.approx(win._xp_per_hour("WitchOfPeter"))

    win.worker.stop()
    win.worker.wait(5000)


def test_the_graph_history_forgets_everything_older_than_its_window(
        qapp, monkeypatch) -> None:
    """Peters Vorgabe: drei Stunden. Was aelter ist, wird nicht nur nicht
    gezeichnet, sondern gar nicht erst aufgehoben — sonst waechst ueber
    einen langen Abend eine Liste mit, die niemand ansieht."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    stand = 0
    for _ in range(5):                                  # fuenf Stunden Spielabend
        fake_now[0] += 3600.0
        stand += 10_000_000
        win._on_character_snapshot("WitchOfPeter", 87, stand)

    verlauf = win._xp_watch["WitchOfPeter"].history
    assert len(verlauf) == 3                            # nur die letzten drei Stunden
    assert all(p.at > fake_now[0] - 3 * 3600 for p in verlauf)

    win.worker.stop()
    win.worker.wait(5000)


def test_the_leveling_panel_gets_the_history_for_its_graph(qapp, monkeypatch) -> None:
    """Ende-zu-Ende: Der Verlauf muss auch im Widget ankommen, nicht nur
    im Beobachtungsstand liegen."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)
    fake_now[0] += 600.0
    win._on_character_snapshot("WitchOfPeter", 87, 21_000_000)
    win._show_character_items("WitchOfPeter", [])

    assert [p.rate for p in win.leveling._graph._points] == [pytest.approx(120_000_000)]

    win._show_items("tab-1", [], "Currency")
    assert win.leveling._graph._points == []            # Fach-Wechsel raeumt auch den Graphen

    win.worker.stop()
    win.worker.wait(5000)


def test_the_status_bar_marks_how_old_the_rate_is(qapp, monkeypatch) -> None:
    """Die Rate steht zwischen zwei Veroeffentlichungen still — ohne einen
    Hinweis saehe eine zehn Minuten alte Zahl aus wie eine frische. Unter
    einer Minute bleibt der Hinweis weg: GGG veroeffentlicht ohnehin nur
    alle paar Minuten, so frisch wie es geht braucht keine Fussnote."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)
    fake_now[0] += 360.0
    win._on_character_snapshot("WitchOfPeter", 87, 21_000_000)

    win._show_character_items("WitchOfPeter", [])
    assert "200.0M XP/h" in win._status_msg.text()
    assert "ago" not in win._status_msg.text()

    fake_now[0] += 630.0                        # zehneinhalb Minuten spaeter
    win._show_character_items("WitchOfPeter", [])
    assert "200.0M XP/h (10m ago)" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_every_experience_publication_is_logged(qapp, monkeypatch, caplog) -> None:
    """Ueber die Charakter-Erfahrung stand bislang keine einzige Zeile im
    Log — als Peters Anzeige um den Faktor 13 danebenlag, musste die
    Ursache ueber die Gem-Mitschrift erschlossen werden, weil die
    eigentlichen Zahlen nirgends standen."""
    import logging

    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    with caplog.at_level(logging.INFO, logger="poe_view.ui.main_window"):
        win._on_character_snapshot("WitchOfPeter", 87, 1_000_000)   # legt die Basis an
        fake_now[0] += 60.0
        win._on_character_snapshot("WitchOfPeter", 87, 2_000_000)   # 1. Veroeffentlichung
        fake_now[0] += 60.0
        win._on_character_snapshot("WitchOfPeter", 87, 2_000_000)   # nichts Neues
        fake_now[0] += 300.0
        win._on_character_snapshot("WitchOfPeter", 87, 12_000_000)  # 2. Veroeffentlichung

    zeilen = [m for m in caplog.messages if m.startswith("Erfahrung")]
    assert len(zeilen) == 2                      # der unveraenderte Abruf schweigt
    assert "Basis" in zeilen[0]                  # erste Aenderung: noch keine Rate
    assert "+10000000 in 360s" in zeilen[1]
    assert "100.0 Mio. XP/h" in zeilen[1]

    win.worker.stop()
    win.worker.wait(5000)


def test_a_death_lowers_the_rate_instead_of_being_filtered_out(qapp, monkeypatch) -> None:
    """Ab Akt 5 kostet der Tod in PoE Erfahrung. Ein Rueckgang ist damit
    ein echtes Ereignis und zaehlt wie jede andere Aenderung — hier faellt
    die Rate dadurch unter null, statt dass der Wert stillschweigend
    verschluckt wuerde."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 87, 0)
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, 10_000_000)
    fake_now[0] += 3600.0
    win._on_character_snapshot("WitchOfPeter", 87, 8_000_000)

    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(-2_000_000)

    win.worker.stop()
    win.worker.wait(5000)


def test_character_snapshot_signal_is_wired_to_the_xp_tracker(qapp) -> None:
    """Ende-zu-Ende: das neue Worker-Signal muss tatsächlich ankommen,
    nicht nur die Methode für sich isoliert funktionieren."""
    win = MainWindow()
    win.worker.character_snapshot_loaded.emit("WitchOfPeter", 87, 1_631_274_653)

    assert "WitchOfPeter" in win._xp_watch
    assert win._xp_watch["WitchOfPeter"].level == 87

    win.worker.stop()
    win.worker.wait(5000)


def test_format_xp_rate_picks_the_right_unit() -> None:
    assert MainWindow._format_xp_rate(12_400_000) == "12.4M XP/h"
    assert MainWindow._format_xp_rate(340_000) == "340K XP/h"
    assert MainWindow._format_xp_rate(500) == "500 XP/h"
    assert MainWindow._format_xp_rate(2_500_000_000) == "2.50B XP/h"
    assert MainWindow._format_xp_rate(0) == "0 XP/h"
    # Ab Akt 5 kostet der Tod Erfahrung -- eine negative Rate ist ein
    # realer Fall und soll sichtbar bleiben statt verschluckt zu werden.
    assert MainWindow._format_xp_rate(-1_000_000) == "-1.0M XP/h"


def test_character_status_bar_shows_the_xp_rate_once_it_exists(
        qapp, monkeypatch) -> None:
    """Peter, 2026-08-10: Charakter-XP/h in der Statuszeile, als erster
    Schritt vor dem eigentlichen Graphen. Solange noch keine Rate gemessen
    ist, darf die Zeile keine Falschbehauptung machen ("0 XP/h" waere
    falsch, es wurde ja nichts gemessen) -- sie laesst die Angabe dann
    einfach weg."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])
    base = 1_631_274_653

    win = MainWindow()
    win._current_character_name = "WitchOfPeter"

    win._on_character_snapshot("WitchOfPeter", 87, base)
    win._show_character_items("WitchOfPeter", [])
    assert "XP/h" not in win._status_msg.text()

    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 87, base + 1_000_000)
    win._show_character_items("WitchOfPeter", [])
    assert "XP/h" not in win._status_msg.text()  # eine Aenderung reicht nicht

    fake_now[0] += 3600.0
    win._on_character_snapshot("WitchOfPeter", 87, base + 25_000_000)
    win._show_character_items("WitchOfPeter", [])
    assert "24.0M XP/h" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_character_refresh_writes_to_the_gem_xp_log(qapp, monkeypatch, tmp_path) -> None:
    """Ende-zu-Ende: Peter, 2026-08-10, soll beim Spielen automatisch
    mitgeschrieben werden, ohne dass er selbst etwas dafuer tun muss."""
    from poe_view.services import gem_xp_log

    monkeypatch.setattr(gem_xp_log.config, "LOG_DIR", tmp_path)
    win = MainWindow()
    helm = Item.model_validate({
        "id": "helm-1", "typeLine": "Rat's Nest", "inventoryId": "Helm",
        "socketedItems": [{
            "id": "gem-a", "typeLine": "Fire Trap", "support": False,
            "additionalProperties": [
                {"name": "Experience", "values": [["100/200", 0]], "progress": 0.5}],
        }],
    })

    win._on_character_items("WitchOfPeter", [helm], False)

    assert gem_xp_log.log_path().exists()
    assert "Fire Trap" in gem_xp_log.log_path().read_text(encoding="utf-8")

    win.worker.stop()
    win.worker.wait(5000)


# --- Verbindungs-LED in der Statuszeile (§4.41) ------------------------ #

def test_the_connection_led_starts_grey_because_nothing_has_been_asked_yet(
        qapp) -> None:
    """Peter, 2026-08-13: "wir koennten waehrend der Wartungsdauer eine LED
    rot leuchten lassen und wenn die Wartung vorbei ist, diese wieder auf
    gruen setzen." Dazu gehoert ein dritter Zustand, den er nicht genannt
    hat: Vor dem ersten Abruf gibt es keinen erfolgreichen Request, auf den
    sich ein Gruen stuetzen koennte — und PoE-VIEW2 startet
    ausdruecklich auch ohne Login, nur mit dem Cache."""
    win = MainWindow()

    assert win._connection_led_state == "unknown"

    win.worker.stop()
    win.worker.wait(5000)


def test_the_connection_led_follows_the_outage_and_the_recovery(qapp) -> None:
    """Der eigentliche Wunsch: waehrend der Wartung rot, danach wieder
    gruen. Beide Wechsel haengen am vorhandenen ``offline_changed`` — die
    Wartung vom 2026-08-13 hat genau diese zwei Flanken erzeugt."""
    win = MainWindow()

    win._on_offline_changed(True)
    assert win._connection_led_state == "offline"

    win._on_offline_changed(False)
    assert win._connection_led_state == "online"

    win.worker.stop()
    win.worker.wait(5000)


def test_a_successful_login_turns_the_led_green_on_its_own(qapp) -> None:
    """Ohne diesen Anschluss bliebe die LED eine ganze stoerungsfreie
    Sitzung lang grau: ``offline_changed`` meldet nur ZUSTANDSWECHSEL, und
    wer nie offline war, bekommt nie ein Signal. Der Login ist selbst ein
    geglueckter Abruf (``/profile``) und damit der Beleg."""
    win = MainWindow()
    win._on_logged_in("PeterM")

    assert win._connection_led_state == "online"

    win.worker.stop()
    win.worker.wait(5000)


def test_an_expired_token_greys_the_led_instead_of_reddening_it(qapp) -> None:
    """Ohne Token fragen wir gar nicht erst (§_skip_unauthenticated). Ueber
    GGGs Erreichbarkeit sagt das nichts — Rot hiesse "GGG ist weg",
    obwohl der Server einwandfrei laufen kann."""
    win = MainWindow()
    win._on_logged_in("PeterM")
    win._on_login_required("Token expired")

    assert win._connection_led_state == "unknown"

    win.worker.stop()
    win.worker.wait(5000)


def test_a_map_visited_twice_keeps_one_instance_id_in_the_history(
        qapp, monkeypatch) -> None:
    """Peters Ablauf vom 2026-08-13: Map, kurz raus Items verkaufen,
    zurueck in DIESELBE Map, fertig gecleared. Beide Abschnitte muessen
    dieselbe Instanz-Kennung tragen, sonst kann der Graph sie nicht als
    eine Map erkennen (§4.40).

    Die Kennung gehoert dem Gebiet, das VERLASSEN wurde — nicht dem, das
    gerade betreten wird. Genau diese Verschiebung ist die Stelle, an der
    man sich vertut."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()

    class _Watcher:
        last_instance_id = ""
    win._zone_watcher = _Watcher()

    def betreten(instanz: str, zone: str) -> None:
        win._zone_watcher.last_instance_id = instanz
        win._on_zone_changed(zone)

    win._on_character_snapshot("WitchOfPeter", 90, 1_993_000_000)
    fake_now[0] += 60.0
    betreten("2308728564", "Bramble Valley")      # rein in die Map
    fake_now[0] += 362.0
    betreten("3117141110", "Backstreet Hideout")  # raus, verkaufen
    fake_now[0] += 2.0
    win._on_character_snapshot("WitchOfPeter", 90, 1_993_000_000 + 14_643_224)
    fake_now[0] += 56.0
    betreten("2308728564", "Bramble Valley")      # zurueck in DIESELBE Map
    fake_now[0] += 112.0
    betreten("3117141110", "Backstreet Hideout")
    fake_now[0] += 2.0
    win._on_character_snapshot("WitchOfPeter", 90, 1_993_000_000 + 14_643_224 + 686_080)

    verlauf = win._xp_watch["WitchOfPeter"].history
    assert [p.instance for p in verlauf] == ["2308728564", "2308728564"]
    assert [round(p.rate / 1_000_000, 1) for p in verlauf] == [145.6, 22.1]

    win.worker.stop()
    win.worker.wait(5000)


def test_a_history_point_carries_the_level_it_was_earned_at(qapp, monkeypatch) -> None:
    """Ohne die Stufe am Punkt koennte der Graph den Schnitt nicht beim
    letzten Levelaufstieg enden lassen (``xp_graph.average_window``) —
    Peter, 2026-08-23. Der Abschnitt MIT dem Aufstieg traegt bereits die
    neue Stufe: GGG veroeffentlicht sie zusammen mit der Erfahrung."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 33, 0)             # Basis
    fake_now[0] += 600.0
    win._on_character_snapshot("WitchOfPeter", 33, 1_000_000)     # erste Aenderung
    fake_now[0] += 600.0
    win._on_character_snapshot("WitchOfPeter", 33, 3_000_000)     # erster Abschnitt
    fake_now[0] += 600.0
    win._on_character_snapshot("WitchOfPeter", 34, 6_000_000)     # Aufstieg

    assert [p.level for p in win._xp_watch["WitchOfPeter"].history] == [33, 34]

    win.worker.stop()
    win.worker.wait(5000)


def test_a_publication_outside_a_zone_carries_no_instance(qapp, monkeypatch) -> None:
    """Faellt der Nenner auf das volle Intervall zurueck (Haendler, keine
    Zonen-Beobachtung), gehoert der Abschnitt zu keiner Map — und darf
    dann auch mit keiner gruppiert werden."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    win._on_character_snapshot("WitchOfPeter", 90, 0)
    fake_now[0] += 60.0
    win._on_character_snapshot("WitchOfPeter", 90, 1_000_000)
    fake_now[0] += 600.0
    win._on_character_snapshot("WitchOfPeter", 90, 21_000_000)

    assert [p.instance for p in win._xp_watch["WitchOfPeter"].history] == [""]

    win.worker.stop()
    win.worker.wait(5000)


def test_a_section_never_reaches_back_past_the_previous_publication(
        qapp, monkeypatch) -> None:
    """Peters Live-Daten vom 2026-08-13, 18:38:52 — im Log gefunden, nicht
    in einem Test:

        18:29:07  Zone betreten (Burial Chambers)
        18:36:53  +14.550.145 in 485s (volles Intervall)  <- MITTEN in der Map
        18:38:52  +6.167.471 in 582s in der verlassenen Zone -> 38,1 Mio./h

    GGG veroeffentlicht meist beim Zonenwechsel, aber rund 5 % kommen als
    Nachzuegler mittendrin (poe-verhalten.md §1). Dann sind bei der
    naechsten Veroeffentlichung grosse Teile der Verweildauer laengst
    abgerechnet — hier 466 der 582 Sekunden. Die uebrigen 6,17 Mio. wurden
    in 119 Sekunden verdient: 186,6 Mio./h, nicht 38,1.

    Dieselbe Erfahrung laesst sich nicht zweimal verdienen."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    stand = 2_000_000_000
    win._on_character_snapshot("WitchOfPeter", 90, stand)
    fake_now[0] += 60.0
    win._on_zone_changed("Backstreet Hideout")
    fake_now[0] += 22.0
    win._on_zone_changed("Burial Chambers")          # 18:29:07
    fake_now[0] += 466.0
    stand += 14_550_145
    win._on_character_snapshot("WitchOfPeter", 90, stand)   # 18:36:53, mittendrin
    fake_now[0] += 116.0
    win._on_zone_changed("Backstreet Hideout")       # 18:38:49
    fake_now[0] += 3.0
    stand += 6_167_471
    win._on_character_snapshot("WitchOfPeter", 90, stand)   # 18:38:52

    watch = win._xp_watch["WitchOfPeter"]
    assert watch.interval_seconds == pytest.approx(119.0)   # nicht 582
    assert win._xp_per_hour("WitchOfPeter") == pytest.approx(186_600_000, rel=0.01)

    win.worker.stop()
    win.worker.wait(5000)


def test_the_limit_leaves_the_ordinary_case_untouched(qapp, monkeypatch) -> None:
    """Gegenprobe: Im Normalfall faellt die Veroeffentlichung beim
    VERLASSEN der vorigen Zone an, liegt also vor dem Betreten der
    aktuellen. Dann greift die Grenze nicht und es bleibt bei der vollen
    Verweildauer."""
    fake_now = [1000.0]
    monkeypatch.setattr("poe_view.ui.main_window.time.monotonic", lambda: fake_now[0])

    win = MainWindow()
    stand = 2_000_000_000
    win._on_character_snapshot("WitchOfPeter", 90, stand)
    fake_now[0] += 60.0
    win._on_zone_changed("Foundry")
    fake_now[0] += 300.0
    win._on_zone_changed("Backstreet Hideout")
    fake_now[0] += 3.0
    stand += 10_000_000
    win._on_character_snapshot("WitchOfPeter", 90, stand)   # beim Verlassen
    fake_now[0] += 30.0
    win._on_zone_changed("Crimson Temple")
    fake_now[0] += 600.0
    win._on_zone_changed("Backstreet Hideout")
    fake_now[0] += 3.0
    stand += 20_000_000
    win._on_character_snapshot("WitchOfPeter", 90, stand)

    assert win._xp_watch["WitchOfPeter"].interval_seconds == pytest.approx(600.0)

    win.worker.stop()
    win.worker.wait(5000)


def test_the_limit_is_a_pure_function_over_both_candidates() -> None:
    """Die Regel selbst, ohne Fenster: das Kleinere von beidem, und jede
    Seite fuer sich, wenn die andere fehlt."""
    assert MainWindow._interval_seconds(582.0, 119.0) == 119.0
    assert MainWindow._interval_seconds(600.0, 3600.0) == 600.0
    assert MainWindow._interval_seconds(None, 485.0) == 485.0
    assert MainWindow._interval_seconds(144.0, None) == 144.0
    assert MainWindow._interval_seconds(None, None) is None


# --- PoE2-Rohdaten-Abzug (Konto-Menue, §4.43) -------------------------- #

def test_the_account_menu_offers_the_poe2_probe(qapp) -> None:
    """Peters Entscheidung 2026-08-15: der Zugang gehoert ins Konto-Menue,
    nicht als eigener Knopf in die Leiste — das Programm liest PoE1, der
    Abzug ist Diagnose."""
    win = MainWindow()

    beschriftungen = [a.text() for a in win._account_menu.actions()]
    assert any("PoE2" in text for text in beschriftungen)

    win.worker.stop()
    win.worker.wait(5000)


def test_the_probe_opens_the_window_and_queues_the_job(qapp, monkeypatch) -> None:
    """Der Abzug laeuft durch dieselbe Job-Queue und kann hinter einem
    Rate-Limit-Takt warten — ohne sofort sichtbares Fenster saehe der
    Klick nach nichts aus."""
    win = MainWindow()
    eingereiht: list = []
    monkeypatch.setattr(win.worker, "submit", eingereiht.append)

    win._on_poe2_probe_clicked()

    assert win._poe2_viewer is not None
    assert "Querying" in win._poe2_viewer._title.text()
    assert [type(j).__name__ for j in eingereiht] == ["Poe2ProbeJob"]

    win.worker.stop()
    win.worker.wait(5000)


def test_the_probe_is_refused_while_another_window_owns_the_account(qapp, monkeypatch) -> None:
    """Der Worker verwuerfe den Job ohnehin (§_skip_read_only) — dann
    bliebe das Fenster dauerhaft bei "Querying…" stehen."""
    win = MainWindow()
    eingereiht: list = []
    monkeypatch.setattr(win.worker, "submit", eingereiht.append)
    win._set_read_only(True)

    win._on_poe2_probe_clicked()

    assert eingereiht == []
    assert "Not available" in win._poe2_viewer._title.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_the_probe_result_is_shown_and_saved(qapp, tmp_path, monkeypatch) -> None:
    """Ein vollstaendiges Charakter-JSON ist zu lang fuer einen
    Bildschirmfoto-Ausschnitt; weitergeben laesst sich nur die Datei."""
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    win = MainWindow()

    win._on_poe2_probe_loaded(Probe(
        calls=[ProbeCall("GET /character?realm=poe2", True, {"characters": []})],
        fetched_at=1_755_000_000.0))

    text = win._poe2_viewer._text.toPlainText()
    assert "GET /character?realm=poe2" in text
    abzug = tmp_path / "appdata" / "poe2-probe.txt"
    assert abzug.read_text(encoding="utf-8") == text
    assert str(abzug) in win._poe2_viewer._title.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_a_failed_save_still_shows_the_result(qapp, monkeypatch) -> None:
    """Der Abzug ist auch ungespeichert brauchbar."""
    win = MainWindow()

    def explodiere(text):
        raise OSError("kein Platz")

    monkeypatch.setattr("poe_view.services.poe2_probe.save_report", explodiere)
    win._on_poe2_probe_loaded(Probe(
        calls=[ProbeCall("GET /account/leagues?realm=poe2", True, {"leagues": []})],
        fetched_at=1_755_000_000.0))

    assert "not saved" in win._poe2_viewer._title.text()
    assert '"leagues": []' in win._poe2_viewer._text.toPlainText()

    win.worker.stop()
    win.worker.wait(5000)


def test_the_probe_window_survives_a_stash_click(qapp, monkeypatch) -> None:
    """Der Stash-Rohdaten-Betrachter wird bei jedem Tab-Wechsel
    ueberschrieben. Teilten sich beide eine Instanz, waere der Abzug beim
    ersten Klick im Baum weg."""
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    # Ueber den Klick und nicht direkt ueber das Ergebnis: Das Fenster
    # entsteht schon beim Klick, und nur dieser Weg deckt beide Stellen ab,
    # an denen eine Instanz gewaehlt wird.
    win._on_poe2_probe_clicked()
    win._on_poe2_probe_loaded(Probe(
        calls=[ProbeCall("GET /account/leagues?realm=poe2", True, {"leagues": []})],
        fetched_at=1_755_000_000.0))
    win._on_raw_data_requested("t1", "Currency")

    assert win._poe2_viewer is not win._raw_data_viewer
    assert '"leagues": []' in win._poe2_viewer._text.toPlainText()

    win.worker.stop()
    win.worker.wait(5000)


# --- XP-Verlauf ueber den Programmstart hinweg (§4.44) ------------------ #

def _xp_punkt(win, name: str, experience: int, zone_seconds: float = 300.0):
    """Eine Veroeffentlichung simulieren, wie sie aus einem Abruf kommt."""
    win._zone_dwell_seconds = lambda now: zone_seconds
    win._on_character_snapshot(name, 90, experience)


def test_der_xp_verlauf_ueberlebt_einen_neustart(qapp, tmp_path, monkeypatch):
    """Peters Beobachtung 2026-08-15: "Mit jeder neuen Version die ich
    teste beginnen die XP-Daten wieder von vorne.\""""
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")

    erste = MainWindow()
    erste._account_name = "TestAccount#1234"
    _xp_punkt(erste, "WitchOfPeter", 1_000_000)   # setzt nur die Basis
    _xp_punkt(erste, "WitchOfPeter", 1_500_000)   # erster Abschnitt
    _xp_punkt(erste, "WitchOfPeter", 2_000_000)   # zweiter Abschnitt
    gemessen = [p.rate for p in erste._xp_watch["WitchOfPeter"].history]
    assert len(gemessen) >= 1
    erste.worker.stop()
    erste.worker.wait(5000)

    zweite = MainWindow()
    zweite._account_name = "TestAccount#1234"
    _xp_punkt(zweite, "WitchOfPeter", 2_000_000)  # erster Abruf nach Neustart

    assert [p.rate for p in zweite._xp_watch["WitchOfPeter"].history] == gemessen

    zweite.worker.stop()
    zweite.worker.wait(5000)


def test_die_basis_wird_ausdruecklich_nicht_wiederhergestellt(qapp, tmp_path,
                                                              monkeypatch):
    """Ein aus der Datei geladener Beobachtungsstand wuerde einen
    Levelaufstieg waehrend der Programmpause als absurde Rate ausweisen
    (Begruendung im Docstring von ``_XpWatch``)."""
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")

    erste = MainWindow()
    erste._account_name = "TestAccount#1234"
    _xp_punkt(erste, "WitchOfPeter", 1_000_000)
    _xp_punkt(erste, "WitchOfPeter", 1_500_000)
    _xp_punkt(erste, "WitchOfPeter", 2_000_000)
    assert erste._xp_watch["WitchOfPeter"].history, "Vorbedingung: ein Abschnitt"
    erste.worker.stop()
    erste.worker.wait(5000)

    zweite = MainWindow()
    zweite._account_name = "TestAccount#1234"
    _xp_punkt(zweite, "WitchOfPeter", 9_000_000)
    watch = zweite._xp_watch["WitchOfPeter"]

    # Der erste Abruf setzt die Basis, mehr nicht: keine Rate aus dem
    # Sprung von 1,5 auf 9 Millionen ueber die Programmpause hinweg.
    assert watch.since_experience == 9_000_000
    assert watch.last_change_at is None

    zweite.worker.stop()
    zweite.worker.wait(5000)


def test_ohne_kontonamen_wird_kein_verlauf_geschrieben(qapp, tmp_path, monkeypatch):
    """Vor dem Login gibt es keinen Pfad — und es duerfen auch keine
    Dateien mit erratenem Namen entstehen."""
    appdata = tmp_path / "appdata"
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", appdata)

    win = MainWindow()
    win._account_name = ""
    _xp_punkt(win, "WitchOfPeter", 1_000_000)
    _xp_punkt(win, "WitchOfPeter", 1_500_000)
    _xp_punkt(win, "WitchOfPeter", 2_000_000)

    assert win._xp_watch["WitchOfPeter"].history, "Vorbedingung: ein Abschnitt"
    assert not list(appdata.glob("xp-history*.json"))

    win.worker.stop()
    win.worker.wait(5000)


def test_zwei_konten_teilen_sich_keinen_verlauf(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")

    erste = MainWindow()
    erste._account_name = "Konto#1"
    _xp_punkt(erste, "WitchOfPeter", 1_000_000)
    _xp_punkt(erste, "WitchOfPeter", 1_500_000)
    _xp_punkt(erste, "WitchOfPeter", 2_000_000)
    assert erste._xp_watch["WitchOfPeter"].history, "Vorbedingung: ein Abschnitt"
    erste.worker.stop()
    erste.worker.wait(5000)

    zweite = MainWindow()
    zweite._account_name = "Konto#2"
    _xp_punkt(zweite, "WitchOfPeter", 1_000_000)

    assert zweite._xp_watch["WitchOfPeter"].history == []

    zweite.worker.stop()
    zweite.worker.wait(5000)


def test_ein_fehlgeschlagenes_speichern_stoert_die_messung_nicht(qapp, monkeypatch):
    """Der Verlauf ist Komfort — eine volle Platte darf die laufende
    Messung nicht abbrechen."""
    win = MainWindow()
    win._account_name = "TestAccount#1234"

    def explodiere(*args, **kwargs):
        raise OSError("kein Platz")

    monkeypatch.setattr("poe_view.services.xp_history.save", explodiere)
    # Drei Veroeffentlichungen: Basis, erste beobachtete Aenderung, dann
    # der erste Abschnitt mit Rate (siehe ``_XpWatch``).
    _xp_punkt(win, "WitchOfPeter", 1_000_000)
    _xp_punkt(win, "WitchOfPeter", 1_500_000)
    _xp_punkt(win, "WitchOfPeter", 2_000_000)

    assert win._xp_watch["WitchOfPeter"].history

    win.worker.stop()
    win.worker.wait(5000)


# --- Beobachtete Stapelgroessen (§4.45) -------------------------------- #

def _mit_items(win, league="Allflame", stash_items=None, char_items=None):
    """Einen Liga-Bestand einhaengen, wie ihn die Abrufe hinterlassen."""
    win._current_league = league
    win._items[league] = stash_items or {}
    win._character_items = char_items or {}


def test_das_kontextmenue_nimmt_ein_item_in_die_beobachtung(qapp, tmp_path,
                                                            monkeypatch):
    """Peters Wahl 2026-08-15: Rechtsklick beim Item selbst, kein
    Abtippen."""
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    win = MainWindow()
    item = Item(typeLine="Wild Crystallised Lifeforce", stackSize=1200)

    menu = QMenu()
    win._add_favourite_action(menu, item)
    assert "Watch stack size" in menu.actions()[0].text()
    menu.actions()[0].trigger()

    assert win._favourite_names() == ["Wild Crystallised Lifeforce"]

    win.worker.stop()
    win.worker.wait(5000)


def test_derselbe_eintrag_entlaesst_wieder(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    win = MainWindow()
    item = Item(typeLine="Chaos Orb", stackSize=5)
    win._toggle_favourite("Chaos Orb")

    menu = QMenu()
    win._add_favourite_action(menu, item)
    assert "Stop watching" in menu.actions()[0].text()
    menu.actions()[0].trigger()

    assert win._favourite_names() == []

    win.worker.stop()
    win.worker.wait(5000)


def test_die_beobachtung_ueberlebt_einen_neustart(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    erste = MainWindow()
    erste._toggle_favourite("Wild Crystallised Lifeforce")
    erste.worker.stop()
    erste.worker.wait(5000)

    zweite = MainWindow()
    assert zweite._favourite_names() == ["Wild Crystallised Lifeforce"]

    zweite.worker.stop()
    zweite.worker.wait(5000)


def test_die_mengen_kommen_aus_faechern_und_charakteren(qapp, tmp_path,
                                                        monkeypatch):
    """Waehrung liegt oft im Rucksack, nicht nur im Fach."""
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    win = MainWindow()
    tab = StashTab(id="t1", name="Currency", type="CurrencyStash", metadata={})
    win._stash_trees["Allflame"] = [tab]
    win._leaf_stashes = [tab]
    _mit_items(win,
               stash_items={"t1": [Item(typeLine="Chaos Orb", stackSize=1000)]},
               char_items={"WitchOfPeter": [Item(typeLine="Chaos Orb",
                                                 stackSize=204)]})
    win._all_characters = [Character(name="WitchOfPeter", league="Allflame",
                                     level=90, classId=0, ascendancyClass=0,
                                     **{"class": "Witch"})]
    win._toggle_favourite("Chaos Orb")

    zeilen = win.leveling.favourites.rows()
    assert [(z.name, z.total) for z in zeilen] == [("Chaos Orb", 1204)]

    win.worker.stop()
    win.worker.wait(5000)


def test_eine_halb_geladene_liga_kennzeichnet_die_summe(qapp, tmp_path,
                                                        monkeypatch):
    """Sonst saehe ein frisch gestarteter Cache wie ein Bestandsverlust
    aus."""
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    win = MainWindow()
    geladen = StashTab(id="t1", name="Currency", type="CurrencyStash", metadata={})
    offen = StashTab(id="t2", name="Noch nicht", type="PremiumStash", metadata={})
    win._stash_trees["Allflame"] = [geladen, offen]
    win._leaf_stashes = [geladen, offen]
    _mit_items(win, stash_items={"t1": [Item(typeLine="Chaos Orb", stackSize=7)]})
    win._toggle_favourite("Chaos Orb")

    zeile = win.leveling.favourites.rows()[0]
    assert zeile.complete is False
    assert zeile.total == 7

    win.worker.stop()
    win.worker.wait(5000)


def test_eine_vollstaendig_geladene_liga_kennzeichnet_nichts(qapp, tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    win = MainWindow()
    tab = StashTab(id="t1", name="Currency", type="CurrencyStash", metadata={})
    win._stash_trees["Allflame"] = [tab]
    win._leaf_stashes = [tab]
    _mit_items(win, stash_items={"t1": [Item(typeLine="Chaos Orb", stackSize=7)]})
    win._toggle_favourite("Chaos Orb")

    assert win.leveling.favourites.rows()[0].complete is True

    win.worker.stop()
    win.worker.wait(5000)


def test_die_liste_hat_eine_obergrenze(qapp, tmp_path, monkeypatch):
    """Wer mehr beobachten will, fuehrt Inventar — dafuer ist die
    Haupttabelle da."""
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    win = MainWindow()
    for i in range(win._MAX_FAVOURITES + 5):
        win._toggle_favourite(f"Item {i}")

    assert len(win._favourite_names()) == win._MAX_FAVOURITES
    assert "full" in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_ein_item_ohne_brauchbaren_namen_bekommt_keinen_eintrag(qapp):
    """``display_name`` liefert "?" wenn alle Namensfelder leer sind —
    darauf laesst sich nichts beobachten."""
    win = MainWindow()
    menu = QMenu()
    win._add_favourite_action(menu, Item())

    assert menu.actions() == []

    win.worker.stop()
    win.worker.wait(5000)


def test_die_neue_reihenfolge_ueberlebt_den_naechsten_start(qapp, tmp_path,
                                                            monkeypatch):
    """Peter, 2026-08-16: "Koennten wir die Fav-Item-Liste per Drag&Drop
    umsortieren?" Der Sinn der Liste ist, dass sie ueber Sitzungen hinweg
    gleich bleibt — eine Sortierung, die nur bis zum Beenden haelt, waere
    Arbeit, die man zweimal macht. Geprueft wird die ganze Kette: Signal
    der Tabelle, Speichern, Zurueckliest im naechsten Fenster."""
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    erste = MainWindow()
    for name in ("Chaos Orb", "Divine Orb", "Vaal Orb"):
        erste._toggle_favourite(name)

    erste.leveling.favourites.move_row(2, 0)

    assert erste._favourite_names() == ["Vaal Orb", "Chaos Orb", "Divine Orb"]
    erste.worker.stop()
    erste.worker.wait(5000)

    zweite = MainWindow()
    assert zweite._favourite_names() == ["Vaal Orb", "Chaos Orb", "Divine Orb"]
    zweite.worker.stop()
    zweite.worker.wait(5000)


def test_das_entlassen_aus_der_tabelle_ist_verdrahtet(qapp, tmp_path, monkeypatch):
    """Das Signal der Tabelle muss im Hauptfenster ankommen — sonst
    passiert beim Klick auf "Stop watching" nichts."""
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    win = MainWindow()
    win._toggle_favourite("Chaos Orb")
    assert win._favourite_names() == ["Chaos Orb"]

    win.leveling.favourites.remove_requested.emit("Chaos Orb")

    assert win._favourite_names() == []

    win.worker.stop()
    win.worker.wait(5000)


# ----------------------- Charakterbogen-Export --------------------------- #
#
# Peter, 2026-08-21: "eine Hommage ... im Stile der alten Pen&Paper RPGs".
# Der Baustein selbst ist in tests/test_character_sheet.py durchgeprueft;
# hier nur die Verdrahtung: Rechtsklick -> Speichern-Dialog -> Datei.

def test_export_character_sheet_writes_the_expected_file(qapp, monkeypatch, tmp_path):
    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")
    item = Item.model_validate({
        "typeLine": "Darkwood Sceptre", "baseType": "Darkwood Sceptre",
        "inventoryId": "Weapon", "frameType": 0,
        "socketedItems": [{
            "typeLine": "Fireball", "colour": "I", "frameType": 4,
            "properties": [{"name": "Level", "values": [["4", 0]]}]}]})
    win._on_character_items("WitchOfPeter", [item], False)
    win._xp_watch["WitchOfPeter"] = _XpWatch(
        since=0.0, since_experience=0, level=42, current_experience=1_000_000)
    target = tmp_path / "sheet.md"
    monkeypatch.setattr("poe_view.ui.main_window.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "Markdown files (*.md)")))

    win._on_character_sheet_requested(char)

    text = target.read_text(encoding="utf-8")
    assert "# WitchOfPeter" in text
    assert "Level 42" in text
    assert "Darkwood Sceptre" in text
    assert "Fireball" in text
    assert f"Exported character sheet to {target}." in win._status_msg.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_export_character_sheet_needs_the_character_opened_first(qapp, monkeypatch, tmp_path):
    """Ohne geladene Items gaebe es nichts zu exportieren — statt eines
    leeren Blatts ein Hinweis, dieselbe Haltung wie beim CSV-Export
    ("Laden bleibt eine ausdrueckliche Handlung")."""
    win = MainWindow()
    char = make_char("NochNieGeoeffnet", "Standard")
    aufgerufen = []
    monkeypatch.setattr("poe_view.ui.main_window.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: aufgerufen.append(1) or ("", "")))
    monkeypatch.setattr("poe_view.ui.main_window.QMessageBox.information",
                        staticmethod(lambda *a, **k: None))

    win._on_character_sheet_requested(char)

    assert aufgerufen == []  # der Speichern-Dialog wurde gar nicht erst geoeffnet

    win.worker.stop()
    win.worker.wait(5000)


def test_der_charakterbogen_ist_am_kontextmenue_verdrahtet(qapp, monkeypatch, tmp_path):
    """Das Signal der Charakterliste muss im Hauptfenster ankommen."""
    win = MainWindow()
    char = make_char("WitchOfPeter", "Standard")
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5,
                             "inventoryId": "MainInventory"})], False)
    target = tmp_path / "sheet.md"
    monkeypatch.setattr("poe_view.ui.main_window.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "Markdown files (*.md)")))

    win.character_list.character_sheet_requested.emit(char)

    assert target.exists()

    win.worker.stop()
    win.worker.wait(5000)


def _char(name: str, level: int, league: str = "Standard") -> Character:
    return Character.model_validate({"name": name, "class": "Witch",
                                     "level": level, "league": league})


def test_levelaufstieg_kommt_in_der_charakterliste_an(qapp, monkeypatch) -> None:
    """Peter, 2026-08-21: "Die Character-Anzeige haengt bei mir momentan
    auf Stufe 13, obwohl mein Char inzwischen Stufe 24 ist."

    Ursache: Liste und Charakterdaten kommen aus VERSCHIEDENEN Endpunkten.
    Nur ``/character`` fuellt ``_all_characters``, und der laeuft praktisch
    nie — in Peters Log 4 Listenabrufe gegen 1301 Einzelabrufe. Der frische
    Level lag bei jedem einzelnen davon vor, landete aber nur im
    Leveling-Feld."""
    win = MainWindow()
    win._current_league = "Standard"
    win._all_characters = [_char("WitchOfPeter", 13), _char("Demo Ranger", 40)]
    win._apply_character_league_filter()
    monkeypatch.setattr(win, "_persist_cache", lambda: None)
    assert "WitchOfPeter (Witch 13)" in [
        win.character_list.item(i).text() for i in range(win.character_list.count())]

    win._on_character_snapshot("WitchOfPeter", 24, 500_000)

    beschriftungen = [win.character_list.item(i).text()
                      for i in range(win.character_list.count())]
    assert "WitchOfPeter (Witch 24)" in beschriftungen
    assert "WitchOfPeter (Witch 13)" not in beschriftungen
    assert win._all_characters[0].level == 24  # auch die Quelle, nicht nur die Anzeige

    win.worker.stop()
    win.worker.wait(5000)


def test_levelaufstieg_zeichnet_die_liste_nur_bei_echter_aenderung_neu(qapp, monkeypatch) -> None:
    """``_on_character_snapshot`` laeuft bei JEDEM Abruf mit, im Auto-Modus
    also alle paar Sekunden. Ein Neuaufbau der Liste je Takt waere
    Dauerbetrieb fuer nichts — und jeder Neuaufbau muesste die Auswahl
    wiederherstellen."""
    win = MainWindow()
    win._current_league = "Standard"
    win._all_characters = [_char("WitchOfPeter", 24)]
    win._apply_character_league_filter()
    monkeypatch.setattr(win, "_persist_cache", lambda: None)

    aufrufe = []
    monkeypatch.setattr(win.character_list, "set_characters",
                        lambda chars: aufrufe.append(chars))

    win._on_character_snapshot("WitchOfPeter", 24, 500_000)  # unveraenderter Level
    assert aufrufe == []

    win._on_character_snapshot("WitchOfPeter", 25, 600_000)  # jetzt gestiegen
    assert len(aufrufe) == 1

    win.worker.stop()
    win.worker.wait(5000)


def test_levelaufstieg_eines_unbekannten_charakters_stoert_nicht(qapp, monkeypatch) -> None:
    """Ein Snapshot kann einen Charakter betreffen, den die Liste (noch)
    nicht kennt — z. B. weil er nach dem letzten Listenabruf im Spiel neu
    angelegt wurde. Das darf nicht knallen; die Liste holt ihn beim
    naechsten echten Listenabruf nach."""
    win = MainWindow()
    win._current_league = "Standard"
    win._all_characters = [_char("WitchOfPeter", 24)]
    win._apply_character_league_filter()
    monkeypatch.setattr(win, "_persist_cache", lambda: None)

    win._on_character_snapshot("NeuerHeld", 3, 1_000)

    assert [c.name for c in win._all_characters] == ["WitchOfPeter"]
    assert win._all_characters[0].level == 24

    win.worker.stop()
    win.worker.wait(5000)


def test_kein_token_beim_start_oeffnet_den_willkommensdialog(qapp) -> None:
    """Peter, 2026-08-21: "habe gerade schon wieder vergessen mich
    einzuloggen". Vorher sagte das nur die Statuszeile, die die naechste
    Meldung ueberschreiben kann."""
    win = MainWindow()
    win._on_login_required("No valid token — please log in.", LOGIN_NO_TOKEN)

    assert win._welcome_dialog is not None
    assert win._welcome_dialog.isVisible()
    assert win._session_expired_dialog is None

    win._close_login_prompts()
    win.worker.stop()
    win.worker.wait(5000)


def test_ablauf_mitten_in_der_sitzung_oeffnet_das_popup(qapp) -> None:
    win = MainWindow()
    win._on_login_required("HTTP 401", LOGIN_EXPIRED)

    assert win._session_expired_dialog is not None
    assert win._session_expired_dialog.isVisible()
    assert win._welcome_dialog is None

    win._close_login_prompts()
    win.worker.stop()
    win.worker.wait(5000)


def test_selbst_ausgeloester_logout_zeigt_keinen_dialog(qapp) -> None:
    """Nach einem ausdruecklichen Logout waere ein Fenster "Sie sind nicht
    mehr angemeldet" eine Frechheit — der Nutzer hat es gerade selbst
    getan. Alle drei Anlaesse teilen sich dasselbe Signal, nur der Hinweis
    unterscheidet sich."""
    from poe_view.services.api_worker import LOGIN_LOGGED_OUT
    win = MainWindow()
    win._on_login_required("Logged out.", LOGIN_LOGGED_OUT)

    assert win._welcome_dialog is None
    assert win._session_expired_dialog is None
    assert win._logged_in is False  # aufgeraeumt wird trotzdem

    win.worker.stop()
    win.worker.wait(5000)


def test_mehrere_401_stapeln_keine_popups(qapp) -> None:
    """Nach einem 401 laeuft die Reihe bereits eingereihter Jobs weiter
    und meldet jeweils denselben Anlass."""
    win = MainWindow()
    win._on_login_required("HTTP 401", LOGIN_EXPIRED)
    erstes = win._session_expired_dialog
    for _ in range(4):
        win._on_login_required("HTTP 401", LOGIN_EXPIRED)

    assert win._session_expired_dialog is erstes

    win._close_login_prompts()
    win.worker.stop()
    win.worker.wait(5000)


def test_erfolgreicher_login_raeumt_die_dialoge_weg(qapp, monkeypatch) -> None:
    """Ein stehengebliebenes "Your login has expired" neben einem
    angemeldeten Fenster waere schlicht falsch — auch wenn der Login ueber
    den Toolbar-Knopf lief, waehrend das Popup offen stand."""
    win = MainWindow()
    monkeypatch.setattr(win, "_switch_active_account_data", lambda name: None)
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._on_login_required("HTTP 401", LOGIN_EXPIRED)
    assert win._session_expired_dialog is not None

    win._on_logged_in("TestAccount#1234")

    assert win._session_expired_dialog is None
    assert win._welcome_dialog is None

    win.worker.stop()
    win.worker.wait(5000)


def test_willkommensdialog_bleibt_weg_wenn_das_haekchen_aus_ist(qapp) -> None:
    """Das Haekchen wirkt erst NACH dem ersten Start: Beim allerersten Mal
    soll der Dialog in jedem Fall kommen, sonst gaebe es keine Gelegenheit,
    ihn ueberhaupt zu sehen."""
    win = MainWindow()
    settings = win._settings()
    settings.setValue(MainWindow._WELCOME_SEEN_KEY, "true")
    settings.setValue(MainWindow._WELCOME_ON_STARTUP_KEY, "false")

    win._on_login_required("No valid token", LOGIN_NO_TOKEN)

    assert win._welcome_dialog is None

    win.worker.stop()
    win.worker.wait(5000)


def test_erster_start_zeigt_den_dialog_auch_bei_abgeschaltetem_haekchen(qapp) -> None:
    win = MainWindow()
    settings = win._settings()
    settings.remove(MainWindow._WELCOME_SEEN_KEY)
    settings.setValue(MainWindow._WELCOME_ON_STARTUP_KEY, "false")

    win._on_login_required("No valid token", LOGIN_NO_TOKEN)

    assert win._welcome_dialog is not None

    win._close_login_prompts()
    win.worker.stop()
    win.worker.wait(5000)


def test_cache_zusammenfassung_ohne_daten(qapp) -> None:
    win = MainWindow()
    assert "No local data yet" in win._cache_summary_text()
    win.worker.stop()
    win.worker.wait(5000)


def test_cache_zusammenfassung_zaehlt_faecher_mit_daten(qapp) -> None:
    """Nicht die BEKANNTEN Faecher: Ein Baum mit 2295 Eintraegen, von denen
    zwei geladen sind, waere eine irrefuehrende Zahl."""
    win = MainWindow()
    win._stash_trees = {"Standard": [], "Settlers": []}
    win._last_loaded = {"Standard": {"a": "2026-08-21T10:00:00+00:00",
                                     "b": "2026-08-21T11:00:00+00:00"},
                        "Settlers": {"c": "2026-08-20T09:00:00+00:00"}}
    win._all_characters = [_char("WitchOfPeter", 24)]

    text = win._cache_summary_text()

    assert "2 league(s)" in text
    assert "3 stash tab(s) with data" in text
    assert "1 character(s)" in text
    assert "Last updated" in text

    win.worker.stop()
    win.worker.wait(5000)


def test_abgeschaltetes_haekchen_wird_beim_schliessen_gespeichert(qapp) -> None:
    """Sonst waere das Haekchen ein Bedienelement ohne Wirkung: Der Dialog
    kaeme beim naechsten Start wieder."""
    win = MainWindow()
    win._on_login_required("No valid token", LOGIN_NO_TOKEN)
    dialog = win._welcome_dialog
    assert dialog is not None

    dialog.show_again.setChecked(False)
    dialog.reject()  # "Continue offline"

    gespeichert = str(win._settings().value(MainWindow._WELCOME_ON_STARTUP_KEY))
    assert gespeichert.lower() == "false"

    win._close_login_prompts()
    win.worker.stop()
    win.worker.wait(5000)


# --- "Hide empty" und poe.ninja-Datenstand (§4.48/§4.49) -------------- #

def test_hide_empty_haekchen_wirkt_auf_den_baum_und_wird_gemerkt(qapp) -> None:
    win = MainWindow()
    assert win._hide_empty_box.isChecked() is False

    win._hide_empty_box.setChecked(True)

    assert win.tree._hide_empty is True
    assert str(win._settings().value(MainWindow._HIDE_EMPTY_SETTING_KEY)).lower() == "true"
    # Neues Fenster liest den Stand zurueck
    zweites = MainWindow()
    assert zweites._hide_empty_box.isChecked() is True
    assert zweites.tree._hide_empty is True

    for w in (win, zweites):
        w.worker.stop()
        w.worker.wait(5000)


def test_hide_empty_ruehrt_die_ladbaren_faecher_nicht_an(qapp) -> None:
    """Peters Bedingung: reine Anzeige. _leaf_stashes speist Sweep,
    Refresh-Modi und "Load All Tabs" — wuerde das Haekchen dort etwas
    entfernen, blieben ausgeblendete Faecher fuer immer leer, weil sie nie
    wieder abgerufen wuerden."""
    win = MainWindow()
    win._leaf_stashes = [_make_leaf("a", "A"), _make_leaf("b", "B")]
    vorher = list(win._leaf_stashes)

    win._hide_empty_box.setChecked(True)

    assert win._leaf_stashes == vorher

    win.worker.stop()
    win.worker.wait(5000)


def test_preis_datenstand_steht_neben_der_wertsumme(qapp, monkeypatch) -> None:
    """Peter: "Wir brauchen irgendwo die Info, welcher Datenstand von
    PoE.Ninja ist"."""
    win = MainWindow()
    win._current_league = "Settlers"
    monkeypatch.setattr("poe_view.ui.main_window.price_cache.fetched_at",
                        lambda league: time.time() - 2 * 3600)

    win._update_value_sum()

    assert "poe.ninja 2 h ago" in win._value_sum_label.text()
    assert "poe.ninja prices fetched" in win._value_sum_label.toolTip()

    win.worker.stop()
    win.worker.wait(5000)


def test_preis_datenstand_erscheint_auch_ohne_bepreiste_zeile(qapp, monkeypatch) -> None:
    """Dass Preise VORLIEGEN, ist eine andere Aussage als dass eine Summe
    zustande kommt — sonst verschwaende die Altersangabe genau dann, wenn
    man sich fragt, warum nichts bepreist ist."""
    win = MainWindow()
    win._current_league = "Settlers"
    monkeypatch.setattr("poe_view.ui.main_window.price_cache.fetched_at",
                        lambda league: time.time() - 30 * 60)

    win._update_value_sum()  # keine Zeilen sichtbar -> keine Summe

    assert "Value:" not in win._value_sum_label.text()
    assert "poe.ninja 30 min ago" in win._value_sum_label.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_ohne_gecachte_preise_keine_altersangabe(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Settlers"
    monkeypatch.setattr("poe_view.ui.main_window.price_cache.fetched_at",
                        lambda league: None)

    win._update_value_sum()

    assert "poe.ninja" not in win._value_sum_label.text()
    assert win._value_sum_label.toolTip() == ""

    win.worker.stop()
    win.worker.wait(5000)


def test_altersangabe_waehlt_die_einheit_nach_alter(qapp, monkeypatch) -> None:
    win = MainWindow()
    win._current_league = "Settlers"
    for versatz, erwartet in [(5 * 60, "5 min ago"), (3 * 3600, "3 h ago"),
                              (5 * 86400, "5 d ago")]:
        monkeypatch.setattr("poe_view.ui.main_window.price_cache.fetched_at",
                            lambda league, v=versatz: time.time() - v)
        assert win._price_age_text() == f"poe.ninja {erwartet}"

    win.worker.stop()
    win.worker.wait(5000)


def test_login_dialoge_haengen_am_hauptfenster(qapp) -> None:
    """Damit sie nicht dahinter verschwinden koennen (§4.47). Der Test sitzt
    hier und nicht nur bei den Dialogen selbst: Dass die KLASSE ein
    Elternteil annimmt, nuetzt nichts, wenn das Hauptfenster keins
    uebergibt."""
    win = MainWindow()

    win._on_login_required("No valid token", LOGIN_NO_TOKEN)
    assert win._welcome_dialog.parent() is win
    assert win._welcome_dialog.isModal() is False

    win._on_login_required("HTTP 401", LOGIN_EXPIRED)
    assert win._session_expired_dialog.parent() is win
    assert win._session_expired_dialog.isModal() is False

    win._close_login_prompts()
    win.worker.stop()
    win.worker.wait(5000)


# ------------- Die Mod-Sammlung im Fenster (§4.52) --------------------- #
#
# Peter, 2026-08-24: "hat etwas von einer Briefmarkensammlung: Einfach mal
# jedes Objekt in der Hand gehalten zu haben und von PoE-VIEW
# kategorisiert und eingetragen."


def _ring(**felder):
    felder.setdefault("typeLine", "Gold Ring")
    felder.setdefault("frameType", 2)          # Rare
    return Item.model_validate(felder)


def test_a_loaded_tab_lands_in_the_mod_collection(qapp) -> None:
    """Gesammelt wird beilaeufig: Was ohnehin hereinkommt, wird
    eingetragen. Ein eigener Abruf dafuer waere Rate-Limit-Budget fuer
    etwas, das schon da ist."""
    win = MainWindow()
    win._current_league = "Standard"

    win._on_stash_items("Standard", "t1", "Currency",
                        [_ring(explicitMods=["+96 to maximum Life"])], True)

    assert win._mod_collection.get("explicitMods", "+96 to maximum Life") is not None

    win.worker.stop()
    win.worker.wait(5000)


def _lebens_rolls(win, werte, **kwargs) -> None:
    for wert in werte:
        win._mod_collection.observe("explicitMods", f"+{wert} to maximum Life",
                                    rarity=2, **kwargs)
    win._mod_collection.clear_new()


def test_the_best_roll_you_have_seen_fills_the_bar(qapp) -> None:
    """Was vorher der Stern war: ein voller Balken. Und der Schlechteste
    bekommt einen leeren — nicht gar keinen, denn "0 %" ist eine Aussage,
    "kein Vergleich" eine andere."""
    win = MainWindow()
    _lebens_rolls(win, range(41, 97))

    marke = win._mod_mark_for(_ring())
    assert marke("explicitMods", "+96 to maximum Life") == mod_bar.bar_html(1.0)
    assert marke("explicitMods", "+41 to maximum Life") == mod_bar.bar_html(0.0)
    assert marke("explicitMods", "+96 to maximum Life") != mod_bar.blank_html()

    win.worker.stop()
    win.worker.wait(5000)


def test_a_mod_you_have_never_seen_gets_the_find_mark(qapp) -> None:
    win = MainWindow()
    win._mod_collection.observe("explicitMods", "+96 to maximum Life", rarity=2)

    marke = win._mod_mark_for(_ring())
    assert marke("explicitMods", "+96 to maximum Life") == mod_bar.new_html()

    win.worker.stop()
    win.worker.wait(5000)


def test_too_few_sightings_get_no_bar_at_all(qapp) -> None:
    """Zwei Rolls sehen als Skala aus wie zweihundert. Unter
    ``MIN_BAR_OBSERVATIONS`` bleibt die Spalte deshalb leer — die Luecke
    ist genauso breit, damit der Text nicht wandert."""
    win = MainWindow()
    _lebens_rolls(win, (41, 96))

    marke = win._mod_mark_for(_ring())
    assert marke("explicitMods", "+96 to maximum Life") == mod_bar.blank_html()

    _lebens_rolls(win, range(50, 50 + mod_bar.MIN_BAR_OBSERVATIONS))
    marke = win._mod_mark_for(_ring())
    assert marke("explicitMods", "+96 to maximum Life") == mod_bar.bar_html(1.0)

    win.worker.stop()
    win.worker.wait(5000)


def test_the_bar_compares_within_the_rarity_of_the_item(qapp) -> None:
    """Ein Rare gegen die festen Werte eines Uniques zu messen ergaebe
    einen Balken, der nichts bedeutet."""
    win = MainWindow()
    for wert in range(4, 101):
        win._mod_collection.observe("explicitMods", f"{wert}% increased Attack Speed",
                                    rarity=3)      # Unique
    win._mod_collection.clear_new()

    unique = win._mod_mark_for(_ring(frameType=3))
    rare = win._mod_mark_for(_ring(frameType=2))

    assert unique("explicitMods", "100% increased Attack Speed") == mod_bar.bar_html(1.0)
    assert rare("explicitMods", "100% increased Attack Speed") == mod_bar.blank_html()

    win.worker.stop()
    win.worker.wait(5000)


def test_the_starting_stock_is_read_in_slices(qapp) -> None:
    """59.249 Items auf einmal kosten gemessen 1,3 Sekunden, und die
    stuende das Fenster still. Nach der letzten Scheibe ist ausserdem
    nichts mehr "neu" — der Grundstock ist kein Fund."""
    win = MainWindow()
    win._account_name = "TestAccount#1234"
    win._mod_seed_queue = [_ring(explicitMods=[f"+{i} to maximum Life"])
                           for i in range(win._MOD_SEED_SLICE + 5)]

    win._seed_mod_collection_slice()
    assert len(win._mod_seed_queue) == 5, "erste Scheibe abgearbeitet, Rest bleibt liegen"

    win._seed_mod_collection_slice()
    assert win._mod_seed_queue == []
    assert len(win._mod_collection) == 1          # alle Zeilen, eine Identitaet
    assert win._mod_collection.is_new("explicitMods", "+1 to maximum Life") is False

    win.worker.stop()
    win.worker.wait(5000)


def test_a_bar_from_the_old_stock_is_dimmed(qapp) -> None:
    """Der Bestwert steht, aber er stuetzt sich auf den Altbestand: In der
    Liga dieses Items gibt es noch zu wenige Beobachtungen. Die Grundlage
    gehoert zur Aussage, deshalb ein eigener Farbton statt einer
    Fussnote."""
    from poe_view.services.mod_collection import MIN_LEAGUE_OBSERVATIONS

    win = MainWindow()
    _lebens_rolls(win, range(41, 97))

    duenn = win._mod_mark_for(_ring(league="Allflame"))
    assert duenn("explicitMods", "+96 to maximum Life") == mod_bar.bar_html(1.0,
                                                                           own_pot=False)

    _lebens_rolls(win, range(60, 60 + max(MIN_LEAGUE_OBSERVATIONS,
                                          mod_bar.MIN_BAR_OBSERVATIONS)),
                  league="Allflame")
    dicht = win._mod_mark_for(_ring(league="Allflame"))
    hoechster = 60 + max(MIN_LEAGUE_OBSERVATIONS, mod_bar.MIN_BAR_OBSERVATIONS) - 1
    assert dicht("explicitMods", f"+{hoechster} to maximum Life") == mod_bar.bar_html(
        1.0, own_pot=True)

    win.worker.stop()
    win.worker.wait(5000)

