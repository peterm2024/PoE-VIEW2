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


def test_an_entry_from_an_older_calculation_is_ignored(tmp_path, monkeypatch) -> None:
    """Die TTL misst das Alter der DATEN, nicht das der Rechenvorschrift.
    Als am 2026-08-05 der 1:1-Boden der poe.ninja-receive-Seite korrigiert
    wurde, haette der Cache sonst bis zu sechs Stunden weiter die alten,
    um Faktor 246 zu hohen Werte ausgeliefert — der Fix haette wie ein
    fehlgeschlagener Fix ausgesehen."""
    path = tmp_path / "prices.json"
    monkeypatch.setattr(price_cache, "_CACHE_FILE", path)
    price_cache.save("Standard", _index_with_all_kinds())
    assert price_cache.load("Standard") is not None  # frisch geschrieben: gueltig

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["Standard"]["version"] = price_cache.CACHE_VERSION - 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert price_cache.load("Standard") is None
    # Nur ignoriert, nicht geloescht — der naechste Abruf ueberschreibt ihn.
    assert "Standard" in json.loads(path.read_text(encoding="utf-8"))


def test_an_entry_without_a_version_is_ignored(tmp_path, monkeypatch) -> None:
    """Der Zustand vor Einfuehrung der Nummer: Genau diese Eintraege lagen
    auf der Platte, als die Preisberechnung sich aenderte."""
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"Standard": {
        "fetched_at": 9_999_999_999, "empty": False, "prices": {"simple": {"Divine Orb": 220.0}},
    }}), encoding="utf-8")
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


def test_empty_result_expires_sooner_than_a_real_one(tmp_path, monkeypatch) -> None:
    """Regression zu FALLSTRICKE #49: real beobachtet bekam "Standard"
    einmal eine leere Antwort von poe.ninja (kein einziger Preis, nur die
    eingebaute Chaos-Orb-Referenz) und blieb dadurch mit der vollen 6h-TTL
    stundenlang ohne jeden Preis, obwohl poe.ninja Sekunden später wieder
    normal antwortete. Ein leeres Ergebnis muss deutlich früher als die
    volle TTL wieder als "abgelaufen" gelten."""
    path = tmp_path / "prices.json"
    monkeypatch.setattr(price_cache, "_CACHE_FILE", path)
    price_cache.save("Standard", PriceIndex())  # nur der Chaos-Orb-Seed

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["Standard"]["fetched_at"] -= price_cache.EMPTY_TTL_SECONDS + 60
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert price_cache.load("Standard") is None


def test_empty_result_is_still_usable_shortly_after_saving(tmp_path, monkeypatch) -> None:
    """Die kürzere TTL darf ein frisches leeres Ergebnis nicht sofort
    verwerfen — sonst würde JEDE Anzeige direkt nach dem Speichern erneut
    einen vollen poe.ninja-Abruf auslösen."""
    path = tmp_path / "prices.json"
    monkeypatch.setattr(price_cache, "_CACHE_FILE", path)
    price_cache.save("Standard", PriceIndex())

    loaded = price_cache.load("Standard")
    assert loaded is not None
    assert loaded.is_empty


def test_a_real_result_keeps_the_normal_ttl_even_though_empty_flag_exists(tmp_path, monkeypatch) -> None:
    """Ein Ergebnis MIT echten Preisen darf nicht von der kürzeren
    Empty-TTL betroffen sein, nur weil das Feature jetzt existiert."""
    path = tmp_path / "prices.json"
    monkeypatch.setattr(price_cache, "_CACHE_FILE", path)
    price_cache.save("Standard", _index_with_all_kinds())

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["Standard"]["fetched_at"] -= price_cache.EMPTY_TTL_SECONDS + 60
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert price_cache.load("Standard") is not None
