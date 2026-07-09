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
    data_cache.save(data)

    restored = data_cache.load()
    assert restored is not None
    assert restored.account_name == "PeterM"
    assert restored.characters[0].name == "A"
    assert restored.stash_trees["Standard"][0].children[0].id == "t1"
    assert restored.items_by_league["Standard"]["t1"][0].typeLine == "Chaos Orb"


def test_save_ignores_write_errors(tmp_path, monkeypatch) -> None:
    """Schreibfehler (z. B. Verzeichnis nicht erstellbar) dürfen nie crashen."""
    monkeypatch.setattr(data_cache, "_CACHE_FILE", tmp_path / "no" / "such" / "dir" / "cache.json")
    monkeypatch.setattr(data_cache.config, "ensure_dirs", lambda: None)  # verhindert Auto-Erstellung
    data_cache.save(data_cache.CachedData())  # darf nicht raisen
