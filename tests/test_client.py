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
