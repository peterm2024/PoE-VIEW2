"""Tests für den RateLimitManager — das Kernsystem.

Abgedeckt ist vor allem FALLSTRICKE #1: Regel und State müssen über
die FENSTERGRÖSSE gematcht werden, nicht über die Array-Position.
Die Uhr ist injizierbar (kein echtes Schlafen in den Tests).
"""

import pytest

from poe_view.api.rate_limiter import SAFETY_MARGIN, RateLimitManager


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


def test_headroom_fraction_recovers_after_window_elapses_without_a_new_request() -> None:
    """Regression: ohne diesen Selbst-Zerfall würde eine Auto-Refresh-Pause
    sich für immer selbst aufrechterhalten — pausiert heißt kein Request
    mehr, kein Request heißt kein neuer Header, der den Zähler auffrischt."""
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account-State"] = "14:15:0,7:300:0"  # 15s-Fenster fast voll
    mgr.update_from_headers(headers)
    assert mgr.headroom_fraction() < 0.1

    clock.t += 20.0  # 15s-Fenster komplett abgelaufen, aber kein Request in der Zwischenzeit
    # jetzt bestimmt das noch laufende 300s-Fenster (7/90 belegt) das Minimum
    assert mgr.headroom_fraction() == pytest.approx((90 - 7) / 90)


def test_snapshot_reflects_last_known_state_without_a_request() -> None:
    clock = FakeClock()
    mgr = make_manager(clock)
    mgr.update_from_headers(HEADERS)
    policy, rules, wait = mgr.snapshot()
    assert policy == "stash-request-limit"
    assert {r["window_s"] for r in rules} == {15, 300}
    assert wait == 0.0


def test_snapshot_decays_expired_window_like_headroom_fraction() -> None:
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account-State"] = "14:15:0,7:300:0"
    mgr.update_from_headers(headers)

    clock.t += 20.0  # 15s-Fenster abgelaufen
    _policy, rules, _wait = mgr.snapshot()
    rule_15 = next(r for r in rules if r["window_s"] == 15)
    assert rule_15["current"] == 0


STEADY_HEADERS = {
    "X-Rate-Limit-Policy": "stash-request-limit",
    "X-Rate-Limit-Rules": "Account",
    "X-Rate-Limit-Account": "30:300:1800",       # Peters real beobachtete Policy
    "X-Rate-Limit-Account-State": "23:300:0",
}


def test_snapshot_ages_out_our_own_requests_one_per_tick() -> None:
    """Peter, 2026-07-30: "die Anzeige sollte doch genauso schnell wieder
    runterticken wie rauf, also alle ca. 11s ein Tick down?" — genau so.
    Unsere eigenen Requests kennen wir mit Zeitstempel, sie fallen einzeln
    aus dem gleitenden Fenster, im selben Takt, in dem sie entstanden sind."""
    clock = FakeClock()
    mgr = make_manager(clock)
    # Fünf eigene Requests im 11s-Takt, wie der Stash-Modus sie erzeugt.
    for i in range(1, 6):
        headers = dict(STEADY_HEADERS)
        headers["X-Rate-Limit-Account-State"] = f"{i}:300:0"
        mgr.update_from_headers(headers)
        if i < 5:
            clock.t += 11.0
    assert mgr.snapshot()[1][0]["current"] == 5  # t=1044, Treffer bei 1000…1044

    # Der älteste Treffer (t=1000) fällt bei t=1300 aus dem 300s-Fenster.
    clock.t = 1300.0
    assert mgr.snapshot()[1][0]["current"] == 4
    clock.t += 11.0  # …und dann einer je Takt, exakt wie beim Hochzählen
    assert mgr.snapshot()[1][0]["current"] == 3
    clock.t += 11.0
    assert mgr.snapshot()[1][0]["current"] == 2


def test_snapshot_estimates_hits_we_did_not_make_ourselves() -> None:
    """Treffer aus einer anderen Instanz/einem anderen Tool (oder von vor
    dem App-Start) kennt nur die Header-Summe. Für sie bleibt die
    gleichmäßige Verteilung übers Fenster die einzig mögliche Annahme —
    die Anzeige klingt dann linear ab statt einzeln zu ticken."""
    clock = FakeClock()
    mgr = make_manager(clock)
    mgr.update_from_headers(STEADY_HEADERS)  # meldet 23, davon 1 von uns

    clock.t += 150.0  # halbes 300s-Fenster verstrichen, kein neuer Request
    # 1 eigener Treffer (noch im Fenster) + round(22 * 0.5) geschätzte
    assert mgr.snapshot()[1][0]["current"] == 12

    clock.t += 120.0  # insgesamt 270s von 300s
    assert mgr.snapshot()[1][0]["current"] == 3  # 1 eigener + round(22 * 0.1)


def test_snapshot_decay_does_not_affect_the_real_wait_decision(monkeypatch) -> None:
    """Die lineare Anzeige-Schätzung darf die tatsächliche Bremse nicht
    aufweichen — die bleibt bewusst konservativ (FALLSTRICKE #34): erst nach
    dem VOLLEN Fenster darf wieder gesendet werden, nicht schon, sobald die
    Anzeige rechnerisch unter die Schwelle gesunken wäre."""
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(STEADY_HEADERS)
    headers["X-Rate-Limit-Account-State"] = "29:300:0"  # an der Bremsschwelle (30 - SAFETY_MARGIN)
    mgr.update_from_headers(headers)

    clock.t += 150.0  # Anzeige würde schon deutlich niedriger schätzen
    _policy, rules, _wait = mgr.snapshot()
    assert rules[0]["current"] < 29  # Anzeige bewegt sich sichtbar

    monkeypatch.setattr("poe_view.api.rate_limiter.time.sleep",
                        lambda s: setattr(clock, "t", clock.t + s))
    assert mgr.check_and_wait("stash-request-limit") > 0.0  # real weiterhin gebremst


def test_snapshot_reports_when_the_next_slot_frees_up() -> None:
    """Peter, 2026-07-30: nach einem frischen Start standen 12/30 über zwei
    Minuten still — völlig korrekt (nichts KANN vor 300s frei werden), sah
    aber aus wie ein Hänger. Die Anzeige nennt deshalb die Restzeit bis zum
    nächsten frei werdenden Platz: ältester eigener Treffer + 300s."""
    clock = FakeClock()
    mgr = make_manager(clock)
    for i in range(1, 4):  # drei Requests im 11s-Takt
        headers = dict(STEADY_HEADERS)
        headers["X-Rate-Limit-Account-State"] = f"{i}:300:0"
        mgr.update_from_headers(headers)
        if i < 3:
            clock.t += 11.0
    # t=1022, ältester Treffer bei t=1000 → frei bei t=1300
    assert mgr.snapshot()[1][0]["next_free_s"] == pytest.approx(278.0)

    clock.t += 278.0  # der älteste fällt heraus, jetzt zählt der zweite (t=1011)
    assert mgr.snapshot()[1][0]["next_free_s"] == pytest.approx(11.0)


def test_next_free_is_unknown_without_own_requests_in_the_window() -> None:
    """Stammen alle gemeldeten Treffer aus einer früheren Sitzung, kennen
    wir keinen einzigen Zeitpunkt — dann bleibt die Angabe leer, statt eine
    Zahl zu erfinden."""
    clock = FakeClock()
    mgr = make_manager(clock)
    mgr.update_from_headers(STEADY_HEADERS)   # ein eigener Request bei t=1000
    clock.t += 301.0                          # der ist längst herausgefallen
    assert mgr.snapshot()[1][0]["next_free_s"] is None


def test_window_coverage_grows_to_full_over_one_window() -> None:
    """Der Synchronisierungsbalken (Peter, 2026-07-30): erst wenn diese
    Instanz ein volles Fenster lang läuft, kann kein Treffer im Fenster mehr
    aus der Zeit VOR dem App-Start stammen — ab da ist die Verbrauchsanzeige
    exakt statt teils geschätzt. Maßgeblich ist das LÄNGSTE Fenster (300s)."""
    clock = FakeClock()
    mgr = make_manager(clock)
    assert mgr.window_coverage() == (0.0, 0.0)  # noch keine Policy bekannt

    mgr.update_from_headers(HEADERS)  # Fenster 15s und 300s
    fraction, remaining = mgr.window_coverage()
    assert fraction == 0.0 and remaining == pytest.approx(300.0)

    clock.t += 150.0
    fraction, remaining = mgr.window_coverage()
    assert fraction == pytest.approx(0.5) and remaining == pytest.approx(150.0)

    clock.t += 150.0
    assert mgr.window_coverage() == (1.0, 0.0)

    clock.t += 1000.0  # bleibt voll — unser Wissen verfällt nicht wieder
    assert mgr.window_coverage() == (1.0, 0.0)


def test_snapshot_before_any_policy_is_known() -> None:
    mgr = make_manager(FakeClock())
    assert mgr.snapshot() == ("", [], 0.0)


def test_last_policy_reflects_the_most_recent_update() -> None:
    mgr = make_manager(FakeClock())
    assert mgr.last_policy == ""
    mgr.update_from_headers(HEADERS)
    assert mgr.last_policy == "stash-request-limit"


def test_steady_pace_interval_uses_default_before_any_policy_is_known() -> None:
    from poe_view.api.rate_limiter import DEFAULT_PACING_INTERVAL_S
    mgr = make_manager(FakeClock())
    assert mgr.steady_pace_interval_s() == DEFAULT_PACING_INTERVAL_S


def test_steady_pace_interval_reflects_the_tightest_known_rule() -> None:
    """15:15 → 15/13 ≈ 1.15s, 90:300 → 300/88 ≈ 3.41s — die 300s-Regel ist
    hier die knappere und bestimmt den Takt (Maximum, nicht Minimum:
    "wie eng darf getaktet werden" muss die strengste Regel respektieren)."""
    mgr = make_manager(FakeClock())
    mgr.update_from_headers(HEADERS)
    assert mgr.steady_pace_interval_s() == pytest.approx(300 / 88, abs=0.01)


def test_steady_pace_interval_stays_strictly_below_the_throttle_threshold() -> None:
    """30 Treffer pro 300s → 300/28 ≈ 10.7s, NICHT 300/29 ≈ 10.3s.

    Regression (FALLSTRICKE #34): der Takt muss strikt unter der Schwelle
    bleiben, ab der ``_required_wait`` bremst (``current >= max_hits -
    SAFETY_MARGIN`` = 29). Ein Takt von 300/29 erzeugt im Dauerbetrieb exakt
    29 Treffer je Fenster und löst damit genau die 300s-Sperre aus, die er
    verhindern soll — real beobachtet, zweimal in Folge."""
    mgr = make_manager(FakeClock())
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account"] = "30:300:1800"
    headers["X-Rate-Limit-Account-State"] = "0:300:0"
    mgr.update_from_headers(headers)

    interval = mgr.steady_pace_interval_s()

    assert interval == pytest.approx(300 / 28, abs=0.01)
    # Kernaussage, unabhängig von der konkreten Formel: die Anzahl Requests,
    # die dieser Takt in ein volles Fenster legt, bleibt unter der Schwelle.
    assert 300 / interval < 30 - SAFETY_MARGIN


def test_steady_pace_interval_ignores_unrelated_older_policies() -> None:
    """Regression: real beobachtet 75s statt der erwarteten ~10s bei "30
    Treffer/300s" — Ursache war eine strengere, aber für den AKTUELLEN Job
    gar nicht zutreffende Policy aus einer früheren Anfrage-Art (Stash-
    Browsing kurz vor dem Umschalten auf Single-Modus für einen
    Charakter), die das Maximum über ALLE Policies dominierte. Nur die
    ZULETZT benutzte Policy darf zählen, wie ``check_and_wait`` es auch
    tatsächlich tut (kein Aufrufer übergibt je einen expliziten
    Policy-Namen, siehe ``client.py._get``)."""
    mgr = make_manager(FakeClock())
    # Zuerst eine Stash-Anfrage mit einer STRENGEREN Policy (5/300s → 75s) …
    mgr.update_from_headers({
        "X-Rate-Limit-Policy": "stash-request-limit",
        "X-Rate-Limit-Rules": "Account",
        "X-Rate-Limit-Account": "5:300:1800",
        "X-Rate-Limit-Account-State": "0:300:0",
    })
    # … dann eine Charakter-Anfrage mit einer LOCKEREREN Policy (30/300s → 10.7s).
    mgr.update_from_headers({
        "X-Rate-Limit-Policy": "account-character-limit",
        "X-Rate-Limit-Rules": "Account",
        "X-Rate-Limit-Account": "30:300:1800",
        "X-Rate-Limit-Account-State": "0:300:0",
    })
    assert mgr.steady_pace_interval_s() == pytest.approx(300 / 28, abs=0.01)
