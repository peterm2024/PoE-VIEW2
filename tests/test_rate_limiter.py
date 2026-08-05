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


def test_header_detail_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Rohe X-Rate-Limit-Werte je Regel müssen im Log landen — erst damit
    ließ sich beweisen, dass GGGs Zähler blockweise statt gleitend sinkt
    (FALLSTRICKE_UND_WORKAROUNDS.md #45, Runde 6)."""
    caplog.set_level("INFO", logger="poe_view.api.rate_limiter")
    mgr = make_manager(FakeClock())
    mgr.update_from_headers(HEADERS)

    detail_lines = [r.message for r in caplog.records if "Rate-Limit-Header" in r.message]
    assert any("stash-request-limit/Account" in line and "current=3/15" in line
                for line in detail_lines)
    assert any("current=7/90" in line and "window=300s" in line
               for line in detail_lines)


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


def test_rule_observe_leaves_current_untouched_on_increase() -> None:
    """Ein steigender Wert ist ein ganz normaler neuer Treffer, keine
    Absenkung — ``last_drop_at``/``drop_interval_s`` dürfen sich dabei
    nicht verändern."""
    from poe_view.api.rate_limiter import RateLimitRule
    rule = RateLimitRule(rule_group="Account", max_hits=30, window_s=300, lock_s=1800)
    rule.observe(5, now=1000.0)
    rule.observe(6, now=1011.0)
    assert rule.current == 6
    assert rule.last_drop_at == 0.0
    assert rule.drop_interval_s is None


def test_rule_learns_drop_interval_from_two_observed_decreases() -> None:
    """Reale Header-Daten (2026-07-30, FALLSTRICKE #45 Runde 6) zeigten:
    GGGs Zähler sinkt nicht gleitend pro Treffer, sondern in Blöcken alle
    ~60s (bei 30 Treffern/300s beobachtet: Sprünge von 4-5 auf einmal, im
    Abstand von durchschnittlich ~60s). ``observe()`` muss diesen Abstand
    aus zwei beliebig großen Absenkungen lernen — die Größe des Sprungs
    ist dabei irrelevant, nur der Zeitpunkt zählt."""
    from poe_view.api.rate_limiter import RateLimitRule
    rule = RateLimitRule(rule_group="Account", max_hits=30, window_s=300, lock_s=1800)
    rule.observe(27, now=1000.0)
    assert rule.drop_interval_s is None  # noch keine Absenkung gesehen

    rule.observe(23, now=1060.0)  # erste Absenkung, -4
    assert rule.drop_interval_s is None  # eine allein reicht nicht

    rule.observe(27, now=1071.0)  # wieder hoch (neue eigene Treffer)
    rule.observe(23, now=1120.0)  # zweite Absenkung, -4, 60s nach der ersten
    assert rule.drop_interval_s == pytest.approx(60.0)


def test_next_free_estimate_uses_the_learned_drop_interval() -> None:
    """Nach zwei beobachteten Absenkungen lässt sich eine grobe Vorhersage
    treffen, wann die nächste fällig ist — keine Zusage für einen
    bestimmten eigenen Treffer, nur der gelernte Rhythmus."""
    from poe_view.api.rate_limiter import RateLimitRule
    rule = RateLimitRule(rule_group="Account", max_hits=30, window_s=300, lock_s=1800)
    assert rule.next_free_estimate_s(now=1000.0) is None  # noch nichts gelernt

    rule.observe(27, now=1000.0)
    rule.observe(23, now=1060.0)
    assert rule.next_free_estimate_s(now=1060.0) is None  # erst eine Absenkung

    rule.observe(19, now=1120.0)  # zweite Absenkung, Abstand 60s gemessen
    assert rule.next_free_estimate_s(now=1120.0) == pytest.approx(60.0)
    assert rule.next_free_estimate_s(now=1150.0) == pytest.approx(30.0)
    assert rule.next_free_estimate_s(now=1200.0) == pytest.approx(0.0)  # überfällig, nicht negativ


def test_snapshot_reports_raw_current_without_inventing_a_smoother_number() -> None:
    """Zentrale Lehre aus FALLSTRICKE #45 Runde 6: GGGs Zähler zwischen zwei
    Requests weiter "gleitend" herunterzurechnen war die ganze Zeit falsch
    (reale Header sinken blockweise, nicht pro Treffer). Die Anzeige zeigt
    deshalb schlicht den zuletzt gemeldeten Rohwert — auch nach Ablauf von
    Zeit, solange kein neuer Header und kein voller Fensterablauf etwas
    anderes belegen."""
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(STEADY_HEADERS)
    headers["X-Rate-Limit-Account-State"] = "23:300:0"
    mgr.update_from_headers(headers)

    clock.t += 150.0  # kein neuer Request, halbes Fenster verstrichen
    assert mgr.snapshot()[1][0]["current"] == 23  # unverändert, nicht "geschätzt"


def test_snapshot_reports_when_the_next_slot_frees_up() -> None:
    """Peter, 2026-07-30: nach einem frischen Start stand der Zähler über
    zwei Minuten still — sah aus wie ein Hänger, war aber die Realität
    (GGGs Zähler sinkt erst nach einer Weile, und dann in einem Block). Die
    Anzeige nennt deshalb eine grobe Restzeit, sobald zwei Absenkungen
    beobachtet wurden."""
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(STEADY_HEADERS)
    headers["X-Rate-Limit-Account-State"] = "23:300:0"
    mgr.update_from_headers(headers)
    assert mgr.snapshot()[1][0]["next_free_s"] is None  # noch keine Absenkung gesehen

    clock.t += 60.0
    headers["X-Rate-Limit-Account-State"] = "19:300:0"  # erste Absenkung
    mgr.update_from_headers(headers)
    assert mgr.snapshot()[1][0]["next_free_s"] is None  # eine allein reicht nicht

    clock.t += 60.0
    headers["X-Rate-Limit-Account-State"] = "15:300:0"  # zweite Absenkung, Takt messbar
    mgr.update_from_headers(headers)
    assert mgr.snapshot()[1][0]["next_free_s"] == pytest.approx(60.0)

    clock.t += 40.0
    assert mgr.snapshot()[1][0]["next_free_s"] == pytest.approx(20.0)


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
    """15:15 → 15/10 = 1.5s, 90:300 → 300/74 ≈ 4.05s — die 300s-Regel ist
    hier die knappere und bestimmt den Takt (Maximum, nicht Minimum:
    "wie eng darf getaktet werden" muss die strengste Regel respektieren).

    Die Zahlen kommen seit 2026-08-06 aus ``_pacing_budget`` statt aus
    ``max_hits - SAFETY_MARGIN - 1`` — siehe den Test unten."""
    mgr = make_manager(FakeClock())
    mgr.update_from_headers(HEADERS)
    assert mgr.steady_pace_interval_s() == pytest.approx(300 / 74, abs=0.01)


def test_steady_pace_interval_stays_strictly_below_the_throttle_threshold() -> None:
    """30 Treffer pro 300s → 300/23 ≈ 13.0s.

    Regression (FALLSTRICKE #34): der Takt muss strikt unter der Schwelle
    bleiben, ab der gebremst wird. Ein Takt, der die Schwelle im
    Dauerbetrieb punktgenau trifft, löst genau die Sperre aus, die er
    verhindern soll — real beobachtet, zweimal in Folge.

    Bis 2026-08-05 war die maßgebliche Schwelle dabei die FALSCHE: Der
    Takt hielt Abstand zu ``_required_wait`` (bremst bei 29), lief aber
    in ``pacing_blocked`` (stoppt schon bei 24,65). Aus 300/28 ≈ 10,7s
    wurde deshalb 300/23 ≈ 13,0s — Peters Entscheidung am 2026-08-06,
    "machen wir 15% langsamer", nachdem eine fünfminütige Zwangspause
    genau darauf zurückging (FALLSTRICKE #64)."""
    mgr = make_manager(FakeClock())
    headers = dict(HEADERS)
    headers["X-Rate-Limit-Account"] = "30:300:1800"
    headers["X-Rate-Limit-Account-State"] = "0:300:0"
    mgr.update_from_headers(headers)

    interval = mgr.steady_pace_interval_s()

    assert interval == pytest.approx(300 / 23, abs=0.01)
    # Kernaussage, unabhängig von der konkreten Formel: die Anzahl Requests,
    # die dieser Takt in ein volles Fenster legt, bleibt unter der Schwelle.
    assert 300 / interval < 30 - SAFETY_MARGIN


def test_pacing_blocked_stops_the_steady_clock_before_the_throttle_hits() -> None:
    """Regression zu FALLSTRICKE #47 (real: 289s Zwangspause am 2026-07-30).

    Der Takt allein schützt nicht — er rechnet, als wäre das Fenster leer
    und als kämen nur seine eigenen Requests darin vor. Ungetaktete
    Requests (Klicks, Liga-Wechsel, Programmstart) füllen dasselbe Fenster
    mit; bei "30 pro 300s" ist die Restmarge von genau einem Treffer dann
    sofort weg. Ab ``PACING_FILL_LIMIT`` der Bremsschwelle (0.85 · 29 ≈
    24.7, also ab 25) muss der Takt deshalb pausieren, deutlich BEVOR
    ``_required_wait`` bei 29 die volle Fenstersperre auslöst."""
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(STEADY_HEADERS)

    headers["X-Rate-Limit-Account-State"] = "24:300:0"
    mgr.update_from_headers(headers)
    assert mgr.pacing_blocked("stash-request-limit") is False

    headers["X-Rate-Limit-Account-State"] = "25:300:0"
    mgr.update_from_headers(headers)
    assert mgr.pacing_blocked("stash-request-limit") is True
    # …und zwar lange bevor die echte Bremse überhaupt greifen würde.
    assert mgr._required_wait("stash-request-limit") == 0.0


def test_pacing_blocked_is_false_without_a_known_policy() -> None:
    """Vor dem ersten Request gibt es nichts zu blockieren — sonst käme der
    Takt nach dem Programmstart nie in Gang."""
    mgr = make_manager(FakeClock())
    assert mgr.pacing_blocked("nie-gesehen") is False


def test_pacing_blocked_recovers_once_the_counter_drops_again() -> None:
    """Die Sperre ist kein Endzustand: sobald GGGs Zähler wieder sinkt
    (blockweise, §RateLimitRule), darf der Takt weiterlaufen. Ohne das
    würde der Modus nach einem vollen Fenster dauerhaft stehen bleiben."""
    clock = FakeClock()
    mgr = make_manager(clock)
    headers = dict(STEADY_HEADERS)
    headers["X-Rate-Limit-Account-State"] = "26:300:0"
    mgr.update_from_headers(headers)
    assert mgr.pacing_blocked("stash-request-limit") is True

    clock.t += 60.0
    headers["X-Rate-Limit-Account-State"] = "21:300:0"  # GGG senkt um 5
    mgr.update_from_headers(headers)
    assert mgr.pacing_blocked("stash-request-limit") is False


def test_pacing_blocked_stays_usable_for_small_quotas() -> None:
    """Als Anteil statt fester Reserve formuliert: bei "5 pro 300s" ergäbe
    ein fester Abzug von 3 eine Obergrenze von 1 — der Takt käme nie zum
    Zug. Mit 0.85 · (5-1) = 3.4 bleiben drei nutzbare Treffer."""
    clock = FakeClock()
    mgr = make_manager(clock)
    small = {
        "X-Rate-Limit-Policy": "character-request-limit",
        "X-Rate-Limit-Rules": "Account",
        "X-Rate-Limit-Account": "5:300:1800",
        "X-Rate-Limit-Account-State": "3:300:0",
    }
    mgr.update_from_headers(small)
    assert mgr.pacing_blocked("character-request-limit") is False

    small["X-Rate-Limit-Account-State"] = "4:300:0"
    mgr.update_from_headers(small)
    assert mgr.pacing_blocked("character-request-limit") is True


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
    # … dann eine Charakter-Anfrage mit einer LOCKEREREN Policy (30/300s → 13.0s).
    mgr.update_from_headers({
        "X-Rate-Limit-Policy": "account-character-limit",
        "X-Rate-Limit-Rules": "Account",
        "X-Rate-Limit-Account": "30:300:1800",
        "X-Rate-Limit-Account-State": "0:300:0",
    })
    assert mgr.steady_pace_interval_s() == pytest.approx(300 / 23, abs=0.01)


def test_the_steady_clock_never_paces_itself_into_its_own_brake() -> None:
    """Die eigentliche Lehre aus FALLSTRICKE #64, als Eigenschaft statt als
    Einzelwert: Takt und Notbremse muessen aus DEMSELBEN Budget kommen.

    Bis 2026-08-05 taten sie das nicht — der Takt rechnete mit
    ``max_hits - SAFETY_MARGIN - 1`` (bei 30/300s: 28), die Bremse stoppte
    bei 24,65. Der Takt zielte also auf ein Budget, das die Bremse gar
    nicht zuliess, und lief im Dauerbetrieb zwangslaeufig hinein. Real
    kostete das eine fuenfminuetige Zwangspause.

    Geprueft ueber eine Reihe von Kontingenten, damit die Eigenschaft
    nicht nur fuer Peters 30/300 gilt."""
    from poe_view.api.rate_limiter import _pacing_budget

    for max_hits, window in ((30, 300), (90, 300), (15, 15), (5, 300),
                             (45, 60), (300, 3600)):
        mgr = make_manager(FakeClock())
        mgr.update_from_headers({
            "X-Rate-Limit-Policy": "p",
            "X-Rate-Limit-Rules": "Account",
            "X-Rate-Limit-Account": f"{max_hits}:{window}:1800",
            "X-Rate-Limit-Account-State": f"0:{window}:0",
        })
        interval = mgr.steady_pace_interval_s()
        rule = next(iter(mgr._policies["p"].rules.values()))

        # Was der Takt allein in ein volles Fenster legt …
        per_window = window / interval
        # … muss unter dem Budget bleiben, ab dem die Bremse greift.
        assert per_window < _pacing_budget(rule), (
            f"{max_hits}/{window}s: Takt legt {per_window:.1f} Abrufe ins "
            f"Fenster, Bremse greift ab {_pacing_budget(rule):.1f}")


def test_a_tiny_quota_still_yields_a_usable_interval() -> None:
    """Bei sehr kleinen Kontingenten ergaebe die Formel rechnerisch null
    oder weniger nutzbare Treffer. Dann gilt EIN Treffer pro Fenster —
    langsam, aber definiert. Vorher fiel so eine Regel stillschweigend aus
    der Betrachtung und der Takt richtete sich nach dem 20s-Default, der
    fuer "2 pro 300s" viel zu schnell waere."""
    mgr = make_manager(FakeClock())
    mgr.update_from_headers({
        "X-Rate-Limit-Policy": "winzig",
        "X-Rate-Limit-Rules": "Account",
        "X-Rate-Limit-Account": "2:300:1800",
        "X-Rate-Limit-Account-State": "0:300:0",
    })

    assert mgr.steady_pace_interval_s() == 300.0
