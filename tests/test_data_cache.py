"""Tests für den persistenten Daten-Cache (überlebt einen Neustart)."""

from poe_view.api.models import Character, Item, StashTab
from poe_view.services import data_cache


def test_load_returns_none_when_no_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(data_cache, "_CACHE_FILE", tmp_path / "missing.json")
    assert data_cache.load() is None


def test_load_ignores_corrupt_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(data_cache, "_CACHE_FILE", path)
    assert data_cache.load() is None


def test_save_and_load_roundtrip_preserves_nested_tree_and_items(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(data_cache, "_CACHE_FILE", tmp_path / "cache.json")

    char = Character.model_validate(
        {"name": "A", "class": "Witch", "level": 90, "league": "Standard"})
    folder = StashTab.model_validate({
        "id": "f1", "name": "Folder", "type": "Folder", "metadata": {"folder": True},
        "children": [{"id": "t1", "name": "Tab", "type": "CurrencyStash", "metadata": {}}],
    })
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5, "stackSize": 3})

    data = data_cache.CachedData()
    data.account_name = "PeterM"
    data.characters = [char]
    data.stash_trees = {"Standard": [folder]}
    data.items_by_league = {"Standard": {"t1": [item]}}
    data.last_loaded = {"Standard": {"t1": "2026-07-08T12:00:00+00:00"}}
    data_cache.save(data)

    restored = data_cache.load()
    assert restored is not None
    assert restored.account_name == "PeterM"
    assert restored.characters[0].name == "A"
    assert restored.stash_trees["Standard"][0].children[0].id == "t1"
    assert restored.items_by_league["Standard"]["t1"][0].typeLine == "Chaos Orb"
    assert restored.last_loaded["Standard"]["t1"] == "2026-07-08T12:00:00+00:00"


def test_save_and_load_roundtrip_preserves_character_items(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(data_cache, "_CACHE_FILE", tmp_path / "cache.json")
    item = Item.model_validate({"typeLine": "Sword", "frameType": 2, "inventoryId": "Weapon"})

    data = data_cache.CachedData()
    data.character_items = {"WitchOfPeter": [item]}
    data.character_items_loaded = {"WitchOfPeter": "2026-07-08T12:00:00+00:00"}
    data_cache.save(data)

    restored = data_cache.load()
    assert restored is not None
    assert restored.character_items["WitchOfPeter"][0].typeLine == "Sword"
    assert restored.character_items_loaded["WitchOfPeter"] == "2026-07-08T12:00:00+00:00"


def test_load_defaults_character_items_to_empty_dict_for_old_cache_files(tmp_path, monkeypatch) -> None:
    """Cache-Dateien von vor diesem Feature kennen 'character_items' noch nicht."""
    path = tmp_path / "old-cache.json"
    path.write_text(
        '{"account_name": "", "characters": [], "stash_trees": {}, "items_by_league": {}}',
        encoding="utf-8")
    monkeypatch.setattr(data_cache, "_CACHE_FILE", path)
    restored = data_cache.load()
    assert restored is not None
    assert restored.character_items == {}
    assert restored.character_items_loaded == {}


def test_load_defaults_last_loaded_to_empty_dict_for_old_cache_files(tmp_path, monkeypatch) -> None:
    """Ältere Cache-Dateien (vor diesem Feature) haben kein 'last_loaded' — darf nicht crashen."""
    path = tmp_path / "old-cache.json"
    path.write_text(
        '{"account_name": "", "characters": [], "stash_trees": {}, "items_by_league": {}}',
        encoding="utf-8")
    monkeypatch.setattr(data_cache, "_CACHE_FILE", path)
    restored = data_cache.load()
    assert restored is not None
    assert restored.last_loaded == {}


def test_load_backfills_last_loaded_from_file_mtime_for_old_caches(tmp_path, monkeypatch) -> None:
    """Migration FALLSTRICKE #12: Tabs mit gecachten Items, aber ohne Zeitstempel
    (Cache-Datei von vor dem Feature) bekommen die mtime der Datei — sonst
    blieben sie für immer als ⬇ markiert und für den Auto-Refresh unsichtbar."""
    from datetime import datetime, timezone

    path = tmp_path / "old-cache.json"
    path.write_text(
        '{"account_name": "", "characters": [], "stash_trees": {},'
        ' "items_by_league": {"Standard": {"t1": [], "t2": []}}}',
        encoding="utf-8")
    monkeypatch.setattr(data_cache, "_CACHE_FILE", path)

    restored = data_cache.load()

    assert restored is not None
    expected = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    assert restored.last_loaded == {"Standard": {"t1": expected, "t2": expected}}


def test_load_backfill_keeps_existing_timestamps(tmp_path, monkeypatch) -> None:
    path = tmp_path / "cache.json"
    path.write_text(
        '{"account_name": "", "characters": [], "stash_trees": {},'
        ' "items_by_league": {"Standard": {"t1": []}},'
        ' "last_loaded": {"Standard": {"t1": "2026-07-01T00:00:00+00:00"}}}',
        encoding="utf-8")
    monkeypatch.setattr(data_cache, "_CACHE_FILE", path)

    restored = data_cache.load()

    assert restored is not None
    assert restored.last_loaded["Standard"]["t1"] == "2026-07-01T00:00:00+00:00"


def test_save_ignores_write_errors(tmp_path, monkeypatch) -> None:
    """Schreibfehler (z. B. Verzeichnis nicht erstellbar) dürfen nie crashen."""
    monkeypatch.setattr(data_cache, "_CACHE_FILE", tmp_path / "no" / "such" / "dir" / "cache.json")
    monkeypatch.setattr(data_cache.config, "ensure_dirs", lambda: None)  # verhindert Auto-Erstellung
    data_cache.save(data_cache.CachedData())  # darf nicht raisen
