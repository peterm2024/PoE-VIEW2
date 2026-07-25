"""Tests für den RateLimitManager — das Kernsystem.

Abgedeckt ist vor allem FALLSTRICKE #1: Regel und State müssen über
die FENSTERGRÖSSE gematcht werden, nicht über die Array-Position.
Die Uhr ist injizierbar (kein echtes Schlafen in den Tests).
"""

import pytest

from poe_view.api.rate_limiter import RateLimitManager


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make_manager(clock: FakeClock) -> RateLimitManager:
    return RateLimitManager(now=clock)


HEADERS = {
    "X-Rate-Limit-Policy": "stash-request-limit",
    "X-Rate-Limit-Rules": "Account",
    "X-Rate-Limit-Account": "15:15:60,90:300:1800",
    "X-Rate-Limit-Account-State": "3:15:0,7:300:0",
}


def test_parse_matches_state_by_window() -> None:
    """Regel 15:15:60 muss den State 3:15:0 bekommen — auch wenn die
    Reihenfolge der State-Einträge vertauscht ist (FALLSTRICKE #1)."""
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account-State"] = "7:300:0,3:15:0"  # vertauscht!
    mgr.update_from_headers(headers)

    state = mgr._policies["stash-request-limit"]
    rule_15 = state.rules[("Account", 15)]
    rule_300 = state.rules[("Account", 300)]
    assert (rule_15.current, rule_15.max_hits) == (3, 15)
    assert (rule_300.current, rule_300.max_hits) == (7, 90)


def test_no_wait_when_under_limit() -> None:
    clock = FakeClock()
    mgr = make_manager(clock)
    mgr.update_from_headers(HEADERS)
    assert mgr.check_and_wait("stash-request-limit") == 0.0


def test_wait_when_limit_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    """14/15 im 15-s-Fenster (Marge 1) → warten bis Fensterende."""
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account-State"] = "14:15:0,7:300:0"
    mgr.update_from_headers(headers)

    slept: list[float] = []

    def fake_sleep(s: float) -> None:
        slept.append(s)
        clock.t += s  # Uhr weiterdrehen, sonst Endlosschleife

    monkeypatch.setattr("poe_view.api.rate_limiter.time.sleep", fake_sleep)
    clock.t += 5.0  # 5 s seit dem Update vergangen
    waited = mgr.check_and_wait("stash-request-limit")
    assert waited == pytest.approx(10.0, abs=0.1)  # 15-s-Fenster minus 5 s


def test_active_lock_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    """State meldet eine aktive Sperre (drittes Feld) → mindestens so lange warten."""
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account-State"] = "15:15:42,7:300:0"
    mgr.update_from_headers(headers)

    def fake_sleep(s: float) -> None:
        clock.t += s

    monkeypatch.setattr("poe_view.api.rate_limiter.time.sleep", fake_sleep)
    waited = mgr.check_and_wait("stash-request-limit")
    assert waited >= 42.0


def test_counter_resets_after_window() -> None:
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account-State"] = "14:15:0,7:300:0"
    mgr.update_from_headers(headers)

    clock.t += 20.0  # 15-s-Fenster ist komplett abgelaufen
    assert mgr.check_and_wait("stash-request-limit") == 0.0


def test_callback_reports_snapshot() -> None:
    events: list[tuple] = []
    clock = FakeClock()
    mgr = RateLimitManager(status_callback=lambda p, r, w: events.append((p, r, w)),
                           now=clock)
    mgr.update_from_headers(HEADERS)
    assert events
    policy, rules, _wait = events[-1]
    assert policy == "stash-request-limit"
    assert {r["window_s"] for r in rules} == {15, 300}


def test_unknown_policy_never_blocks() -> None:
    mgr = make_manager(FakeClock())
    assert mgr.check_and_wait("nie-gesehen") == 0.0


def test_headroom_fraction_is_1_when_no_policy_known() -> None:
    mgr = make_manager(FakeClock())
    assert mgr.headroom_fraction() == 1.0


def test_headroom_fraction_reflects_worst_rule() -> None:
    mgr = make_manager(FakeClock())
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account-State"] = "3:15:0,81:300:0"  # 20% frei im 300s-Fenster
    mgr.update_from_headers(headers)
    assert mgr.headroom_fraction() == pytest.approx(0.1, abs=0.01)


def test_headroom_fraction_is_0_when_locked() -> None:
    mgr = make_manager(FakeClock())
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account-State"] = "15:15:42,7:300:0"  # aktive Sperre
    mgr.update_from_headers(headers)
    assert mgr.headroom_fraction() == 0.0
