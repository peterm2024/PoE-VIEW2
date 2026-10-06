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


# --- Cache pro Konto (Peter, 2026-08-02) ---------------------------------- #

def test_path_for_builds_an_account_specific_filename() -> None:
    path = data_cache.path_for("PeterM")
    assert path.name == "data-cache-PeterM.json"


def test_path_for_sanitizes_unsafe_characters() -> None:
    """GGG-Kontonamen können ein '#1234'-Suffix tragen, aber theoretisch
    auch andere Sonderzeichen -- der Dateiname muss trotzdem gueltig sein."""
    path = data_cache.path_for("Weird:Name*?")
    assert path.name == "data-cache-Weird_Name__.json"


def test_path_for_empty_account_falls_back_to_a_fixed_name() -> None:
    path = data_cache.path_for("")
    assert path.name == "data-cache-account.json"


def test_two_accounts_get_independent_cache_files(tmp_path, monkeypatch) -> None:
    """Kern der Konto-Trennung: Konto A darf Konto Bs Datei nicht anfassen."""
    monkeypatch.setattr(data_cache.config, "APP_DATA_DIR", tmp_path)
    path_a, path_b = data_cache.path_for("Alice"), data_cache.path_for("Bob")
    assert path_a != path_b

    data_a = data_cache.CachedData()
    data_a.account_name = "Alice"
    data_a.characters = [Character.model_validate(
        {"name": "AliceChar", "class": "Witch", "level": 90, "league": "Standard"})]
    data_cache.save(data_a, path_a)

    data_b = data_cache.CachedData()
    data_b.account_name = "Bob"
    data_cache.save(data_b, path_b)

    restored_a = data_cache.load(path_a)
    restored_b = data_cache.load(path_b)
    assert restored_a.characters[0].name == "AliceChar"
    assert restored_b.characters == []


def test_save_and_load_with_explicit_path_ignore_the_legacy_cache_file(
        tmp_path, monkeypatch) -> None:
    """Ein expliziter ``path`` wird verwendet, ohne die alte gemeinsame
    ``_CACHE_FILE`` zu beruehren -- die bleibt unangetastet auf der Platte."""
    monkeypatch.setattr(data_cache, "_CACHE_FILE", tmp_path / "legacy.json")
    account_path = tmp_path / "data-cache-PeterM.json"

    data_cache.save(data_cache.CachedData(), account_path)

    assert account_path.exists()
    assert not (tmp_path / "legacy.json").exists()  # nicht angelegt/veraendert


# --- Fach für Fach mit Gedächtnis (Peter, 2026-10-06: Hänger beim Abruf) ---

def _bestand():
    data = data_cache.CachedData()
    data.account_name = "PeterM"
    data.characters = [Character.model_validate(
        {"name": "A", "class": "Witch", "level": 90, "league": "Standard"})]
    data.items_by_league = {
        "Standard": {"t1": [Item.model_validate({"typeLine": "Chaos Orb", "stackSize": 3})],
                     "t2": [Item.model_validate({"typeLine": "Exalted Orb"})]},
        "Allflame": {"t9": []}}
    return data


def _alt_ganz(data, path):
    """So entstand der Text bis 2026-10-06: json.dumps über alles."""
    import json
    payload = dict(data_cache.Snapshot(data, path).payload)
    payload["items_by_league"] = {
        league: {sid: [i.model_dump(mode="json") for i in items]
                 for sid, items in stashes.items()}
        for league, stashes in data.items_by_league.items()}
    return json.dumps(payload)


def test_the_piecewise_text_equals_one_big_dumps(tmp_path) -> None:
    """Zeichengenau dasselbe wie vorher — nicht nur gleich geladen."""
    data, path = _bestand(), tmp_path / "c.json"
    assert data_cache.Snapshot(data, path)._text() == _alt_ganz(data, path)
    leer = data_cache.CachedData()
    leer.items_by_league = {}
    assert data_cache.Snapshot(leer, path)._text() == _alt_ganz(leer, path)


def test_unchanged_tabs_are_not_converted_again(tmp_path, monkeypatch) -> None:
    """Der Kern: Je Abruf ändert sich EIN Fach — nur das wird neu in Text
    verwandelt. Gemessen an Peters Cache: 1,5 s → 0,06 s je Speichern."""
    data, path = _bestand(), tmp_path / "c.json"
    data_cache.Snapshot(data, path).write()
    umgewandelt = []
    echt = Item.model_dump

    def zaehlen(self, *args, **kwargs):
        umgewandelt.append(self.typeLine)
        return echt(self, *args, **kwargs)
    monkeypatch.setattr(Item, "model_dump", zaehlen)
    data_cache.Snapshot(data, path).write()
    assert umgewandelt == []                                    # nichts geändert
    # Ein Fach neu abgerufen: die Liste wird als Ganzes ersetzt.
    data.items_by_league["Standard"]["t2"] = [Item.model_validate({"typeLine": "Divine Orb"})]
    data_cache.Snapshot(data, path).write()
    assert len(umgewandelt) == 1
    geladen = data_cache.load(path)
    assert [i.typeLine for i in geladen.items_by_league["Standard"]["t2"]] == ["Divine Orb"]
    assert [i.typeLine for i in geladen.items_by_league["Standard"]["t1"]] == ["Chaos Orb"]


def test_the_memory_forgets_removed_tabs(tmp_path) -> None:
    """Sonst hielte das Gedächtnis gelöschte Fächer samt Items am Leben."""
    data, path = _bestand(), tmp_path / "c.json"
    data_cache.Snapshot(data, path).write()
    del data.items_by_league["Standard"]["t2"]
    data_cache.Snapshot(data, path).write()
    assert set(data_cache._FRAGMENTE[path]) == {("Standard", "t1"), ("Allflame", "t9")}
