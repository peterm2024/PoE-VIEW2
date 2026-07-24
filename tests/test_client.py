"""Tests für den PoeApiClient — v. a. die URL-Bildung (Encoding, Substash-Pfad)."""

from poe_view.api.client import PoeApiClient
from poe_view.api.rate_limiter import RateLimitManager


def make_client(monkeypatch, calls: list[str]) -> PoeApiClient:
    client = PoeApiClient(RateLimitManager())
    monkeypatch.setattr(client, "_get",
                        lambda path, policy_hint=None: calls.append(path) or {"stash": {"id": "x"}})
    return client


def test_get_stash_builds_two_segment_path(monkeypatch) -> None:
    calls: list[str] = []
    client = make_client(monkeypatch, calls)
    client.get_stash("Standard", "abc123")
    assert calls == ["/stash/Standard/abc123"]
    client.close()


def test_get_stash_with_parent_builds_substash_path(monkeypatch) -> None:
    """Kinder von Spezial-Tabs (MapStash, …): /stash/<liga>/<eltern>/<kind>."""
    calls: list[str] = []
    client = make_client(monkeypatch, calls)
    client.get_stash("Standard", "child9", parent_id="parent1")
    assert calls == ["/stash/Standard/parent1/child9"]
    client.close()


def test_get_stash_encodes_league_with_spaces(monkeypatch) -> None:
    calls: list[str] = []
    client = make_client(monkeypatch, calls)
    client.get_stash("SSF Ruthless", "abc", parent_id="def")
    assert calls == ["/stash/SSF%20Ruthless/def/abc"]
    client.close()


def test_get_character_items_builds_path_and_combines_all_lists(monkeypatch) -> None:
    calls: list[str] = []
    client = PoeApiClient(RateLimitManager())
    response = {"character": {
        "equipment": [{"typeLine": "Sword", "inventoryId": "Weapon"}],
        "inventory": [{"typeLine": "Chaos Orb", "inventoryId": "MainInventory"}],
        "jewels": [{"typeLine": "Crimson Jewel", "inventoryId": "PassiveJewels"}],
        "rucksack": [{"typeLine": "Cluster Jewel", "inventoryId": "Rucksack"}],
    }}
    monkeypatch.setattr(client, "_get",
                        lambda path, policy_hint=None: calls.append(path) or response)
    items = client.get_character_items("WitchOfPeter")
    assert calls == ["/character/WitchOfPeter"]
    assert [i.typeLine for i in items] == ["Sword", "Chaos Orb", "Crimson Jewel", "Cluster Jewel"]
    client.close()


def test_get_character_items_encodes_name_with_spaces(monkeypatch) -> None:
    calls: list[str] = []
    client = PoeApiClient(RateLimitManager())
    monkeypatch.setattr(client, "_get",
                        lambda path, policy_hint=None: calls.append(path) or {"character": {}})
    client.get_character_items("Witch Of Peter")
    assert calls == ["/character/Witch%20Of%20Peter"]
    client.close()


def test_get_character_items_tolerates_missing_lists(monkeypatch) -> None:
    """Fehlende Item-Listen (z. B. kein 'rucksack' außerhalb bestimmter Ligen)
    sollen leer bleiben statt einen Fehler zu werfen."""
    client = PoeApiClient(RateLimitManager())
    monkeypatch.setattr(client, "_get", lambda path, policy_hint=None: {"character": {}})
    assert client.get_character_items("Empty") == []
    client.close()
