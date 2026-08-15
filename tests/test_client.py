"""Tests für den PoeApiClient — v. a. die URL-Bildung (Encoding, Substash-Pfad)."""

import pytest

from poe_view.api.client import ApiError, PoeApiClient
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
    level, experience, items = client.get_character_items("WitchOfPeter")
    assert calls == ["/character/WitchOfPeter"]
    assert [i.typeLine for i in items] == ["Sword", "Chaos Orb", "Crimson Jewel", "Cluster Jewel"]
    assert (level, experience) == (0, 0)
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
    assert client.get_character_items("Empty") == (0, 0, [])
    client.close()


def test_get_character_items_returns_level_and_experience(monkeypatch) -> None:
    """Peter, 2026-08-10: Grundlage für die XP/h-Anzeige. GGGs Antwort
    trägt ``level``/``experience`` direkt neben den Item-Listen — bisher
    stillschweigend verworfen, obwohl kein zusätzlicher Request nötig ist."""
    client = PoeApiClient(RateLimitManager())
    monkeypatch.setattr(client, "_get", lambda path, policy_hint=None: {
        "character": {"level": 87, "experience": 1631274653}})
    level, experience, items = client.get_character_items("WitchOfPeter")
    assert (level, experience, items) == (87, 1631274653, [])
    client.close()


def test_an_error_response_keeps_gggs_own_reason_separate(monkeypatch) -> None:
    """Peters Wartungs-Log vom 2026-08-13: GGGs Umschlag ``{"error":
    {"code": 2, "message": "Invalid query; League not found"}}`` steckte
    bisher nur als Text in der Meldung. Er entscheidet aber darueber, ob
    ein HTTP 400 ein Anwendungsfehler oder eine laufende Wartung ist
    (api_worker._is_maintenance_bad_request), und muss dafuer als Feld
    danebenliegen."""
    import httpx

    client = PoeApiClient(RateLimitManager())
    monkeypatch.setattr(client._http, "get", lambda path, params=None: httpx.Response(
        400, json={"error": {"code": 2, "message": "Invalid query; League not found"}},
        request=httpx.Request("GET", "https://api.pathofexile.com/stash/Allflame/x")))

    with pytest.raises(ApiError) as fehler:
        client._get("/stash/Allflame/152a892ed5")

    assert fehler.value.status_code == 400
    assert fehler.value.error_code == 2
    assert fehler.value.error_message == "Invalid query; League not found"
    client.close()


def test_an_error_page_without_json_does_not_break_the_error_itself(monkeypatch) -> None:
    """Bei Wartung kommt auch mal HTML statt JSON. Eine Fehlerbehandlung,
    die selbst scheitert, verdeckt genau den Fehler, den sie beschreiben
    soll."""
    import httpx

    client = PoeApiClient(RateLimitManager())
    monkeypatch.setattr(client._http, "get", lambda path, params=None: httpx.Response(
        503, text="<html>maintenance</html>",
        request=httpx.Request("GET", "https://api.pathofexile.com/profile")))

    with pytest.raises(ApiError) as fehler:
        client._get("/profile")

    assert fehler.value.status_code == 503
    assert fehler.value.error_code is None
    assert fehler.value.error_message == ""
    client.close()


# --- Realm-Parameter (PoE2-Abzug, §4.43) ------------------------------- #

def _record_params(monkeypatch, client, status=200):
    """Merkt sich Pfad und Query jedes Aufrufs statt zu senden."""
    import httpx

    gesehen: list[tuple] = []

    def fake_get(path, params=None):
        gesehen.append((path, params))
        return httpx.Response(
            status, json={},
            request=httpx.Request("GET", f"https://api.pathofexile.com{path}"))

    monkeypatch.setattr(client._http, "get", fake_get)
    return gesehen


def test_raw_endpoints_pass_the_realm_as_query(monkeypatch) -> None:
    """``realm`` ist ein Query-Parameter, kein eigener Pfad und kein
    eigener OAuth-Scope (GGG-Referenz, gelesen am 2026-08-15)."""
    client = PoeApiClient(RateLimitManager())
    gesehen = _record_params(monkeypatch, client)

    client.get_leagues_raw("poe2")
    client.get_characters_raw("poe2")
    client.get_character_raw("WitchOfPeter", "poe2")

    assert gesehen == [("/account/leagues", {"realm": "poe2"}),
                       ("/character", {"realm": "poe2"}),
                       ("/character/WitchOfPeter", {"realm": "poe2"})]
    client.close()


def test_raw_endpoints_without_realm_send_no_query(monkeypatch) -> None:
    """Ohne Realm ist es der gewoehnliche PoE1-PC-Aufruf — dann darf auch
    kein leerer Parameter mitgehen."""
    client = PoeApiClient(RateLimitManager())
    gesehen = _record_params(monkeypatch, client)

    client.get_characters_raw()

    assert gesehen == [("/character", None)]
    client.close()


def test_raw_character_endpoint_encodes_the_name(monkeypatch) -> None:
    client = PoeApiClient(RateLimitManager())
    gesehen = _record_params(monkeypatch, client)

    client.get_character_raw("Witch Of Peter", "poe2")

    assert gesehen[0][0] == "/character/Witch%20Of%20Peter"
    client.close()


def test_error_message_names_the_realm(monkeypatch) -> None:
    """Ohne die Query stuende in der Meldung nur ``/character`` — und ein
    PoE2-Fehlschlag waere nicht von einem gewoehnlichen PoE1-Fehler zu
    unterscheiden. Genau diese Meldung landet im Abzug."""
    client = PoeApiClient(RateLimitManager())
    _record_params(monkeypatch, client, status=403)

    with pytest.raises(ApiError) as fehler:
        client.get_characters_raw("poe2")

    assert "/character?realm=poe2" in str(fehler.value)
    client.close()


def test_the_429_retry_keeps_the_query(monkeypatch) -> None:
    """Der eine Wiederholungsversuch nach 429 darf den Realm nicht
    verlieren — sonst fragte er still den falschen Realm ab."""
    import httpx

    client = PoeApiClient(RateLimitManager())
    gesehen: list[tuple] = []
    antworten = [429, 200]

    def fake_get(path, params=None):
        gesehen.append((path, params))
        return httpx.Response(
            antworten.pop(0), json={},
            request=httpx.Request("GET", f"https://api.pathofexile.com{path}"))

    monkeypatch.setattr(client._http, "get", fake_get)
    monkeypatch.setattr("poe_view.api.client.time.sleep", lambda s: None)

    client.get_characters_raw("poe2")

    assert gesehen == [("/character", {"realm": "poe2"}),
                       ("/character", {"realm": "poe2"})]
    client.close()
