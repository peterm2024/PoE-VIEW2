"""Tests für den Preis-Cache — v. a. TTL-Ablauf und den Roundtrip der
drei PriceIndex-Strukturen (einfach/Gems/Links) durch JSON."""

import json

from poe_view.api.models import Item
from poe_view.api.ninja import PriceIndex
from poe_view.services import price_cache


def _index_with_all_kinds() -> PriceIndex:
    index = PriceIndex()
    index._simple["Divine Orb"] = 220.0
    index._gems["Melee Support"] = [(20, 20, False, 5.0), (21, 23, True, 500.0)]
    index._links["Oni-Goroshi"] = {None: 3_617_276.0, 5: 40_000.0, 6: 29_808.0}
    return index


def test_load_returns_none_when_no_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(price_cache, "_CACHE_FILE", tmp_path / "missing.json")
    assert price_cache.load("Standard") is None


def test_load_ignores_corrupt_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "corrupt.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(price_cache, "_CACHE_FILE", path)
    assert price_cache.load("Standard") is None


def test_save_and_load_roundtrip_preserves_all_three_price_kinds(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(price_cache, "_CACHE_FILE", tmp_path / "prices.json")
    price_cache.save("Standard", _index_with_all_kinds())

    loaded = price_cache.load("Standard")
    assert loaded.price_for(Item.model_validate({"typeLine": "Divine Orb", "frameType": 5})) == 220.0
    assert loaded.price_for(Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})) == 1.0

    gem = Item.model_validate({
        "typeLine": "Melee Support", "frameType": 4, "corrupted": False,
        "properties": [{"name": "Level", "values": [["20", 0]]},
                       {"name": "Quality", "values": [["+20%", 1]]}],
    })
    assert loaded.price_for(gem) == 5.0

    weapon = Item.model_validate({
        "name": "Oni-Goroshi", "typeLine": "Oni-Goroshi", "frameType": 3,
        "sockets": [{"group": 0} for _ in range(6)],
    })
    assert loaded.price_for(weapon) == 29_808.0


def test_load_returns_none_when_older_than_ttl(tmp_path, monkeypatch) -> None:
    path = tmp_path / "prices.json"
    monkeypatch.setattr(price_cache, "_CACHE_FILE", path)
    price_cache.save("Standard", _index_with_all_kinds())

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["Standard"]["fetched_at"] -= 7 * 3600  # 7h alt, TTL ist 6h
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert price_cache.load("Standard") is None


def test_load_accepts_a_custom_ttl(tmp_path, monkeypatch) -> None:
    path = tmp_path / "prices.json"
    monkeypatch.setattr(price_cache, "_CACHE_FILE", path)
    price_cache.save("Standard", _index_with_all_kinds())

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["Standard"]["fetched_at"] -= 3600  # 1h alt
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert price_cache.load("Standard", ttl_seconds=1800) is None
    assert price_cache.load("Standard", ttl_seconds=7200) is not None


def test_save_keeps_other_leagues_intact(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(price_cache, "_CACHE_FILE", tmp_path / "prices.json")
    price_cache.save("Standard", _index_with_all_kinds())

    other = PriceIndex()
    other._simple["Chaos Orb"] = 1.0
    price_cache.save("Hardcore", other)

    assert price_cache.load("Standard") is not None
    assert price_cache.load("Hardcore") is not None


def test_load_ignores_a_league_missing_from_the_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(price_cache, "_CACHE_FILE", tmp_path / "prices.json")
    price_cache.save("Standard", _index_with_all_kinds())
    assert price_cache.load("Hardcore") is None
