"""Tests für ApiWorker._dispatch — v. a. die Regel, wann "Bereit" emittiert wird.

Ruft _dispatch() direkt und synchron auf (kein echter Thread, kein echtes
Netzwerk) — der Client wird per Monkeypatch durch eine Fake-Methode ersetzt.
"""

from poe_view.api.models import Item, StashTab
from poe_view.api.ninja import PriceIndex
from poe_view.services.api_worker import (ApiWorker, FetchCharacterItemsJob,
                                          FetchLeaguesJob, FetchPricesJob,
                                          FetchStashItemsJob, LogoutJob)


def test_logout_dispatch_deletes_the_token_and_requests_login(qapp, monkeypatch) -> None:
    """Peter, 2026-08-02: fehlender Logout war "für ein öffentliches
    Werkzeug eine Sackgasse". Der Worker-seitige Teil (Token löschen,
    login_required melden) stand als LogoutJob bereits im Code, wurde
    aber nirgends ausgelöst — dieser Test deckte das bisher nicht ab."""
    from poe_view.services import api_worker as api_worker_module
    worker = ApiWorker()
    deleted = []
    monkeypatch.setattr(api_worker_module.token_store, "delete_token",
                        lambda: deleted.append(True))
    required = []
    worker.login_required.connect(required.append)

    worker._dispatch(LogoutJob())

    assert deleted == [True]
    assert required == ["Logged out."]
    worker.client.close()


def test_stash_items_dispatch_does_not_emit_bereit_after_result(qapp, monkeypatch) -> None:
    """Regression FALLSTRICKE #8: 'Bereit' überschrieb sonst die Tab-Name+Anzahl-Meldung."""
    worker = ApiWorker()
    fake_stash = StashTab.model_validate({
        "id": "t1", "name": "Currency 1", "type": "CurrencyStash", "metadata": {},
        "items": [{"typeLine": "Chaos Orb", "frameType": 5}],
    })
    monkeypatch.setattr(worker.client, "get_stash", lambda league, sid, parent_id=None: fake_stash)

    emitted: list[str] = []
    worker.status.connect(emitted.append)

    worker._dispatch(FetchStashItemsJob("Standard", "t1", "Currency 1"))

    assert emitted == ["Loading items: Currency 1…"]  # kein "Bereit" danach
    worker.client.close()


def test_leagues_dispatch_emits_bereit_after_result(qapp, monkeypatch) -> None:
    """Gegenprobe: Jobs ohne eigenen UI-Abschlusstext müssen 'Bereit' emittieren."""
    worker = ApiWorker()
    monkeypatch.setattr(worker.client, "get_leagues", lambda: ["Standard"])

    emitted: list[str] = []
    worker.status.connect(emitted.append)

    worker._dispatch(FetchLeaguesJob())

    assert emitted == ["Loading leagues…", "Ready"]
    worker.client.close()


def test_character_items_dispatch_emits_name_and_items(qapp, monkeypatch) -> None:
    worker = ApiWorker()
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})
    monkeypatch.setattr(worker.client, "get_character_items", lambda name: (87, 123, [item]))

    emitted: list[str] = []
    worker.status.connect(emitted.append)
    results: list[tuple[str, list[Item]]] = []
    worker.character_items_loaded.connect(lambda name, items: results.append((name, items)))

    worker._dispatch(FetchCharacterItemsJob("WitchOfPeter"))

    assert emitted == ["Loading equipment: WitchOfPeter…", "Ready"]
    assert results == [("WitchOfPeter", [item])]
    worker.client.close()


def test_character_items_dispatch_also_emits_level_and_experience(qapp, monkeypatch) -> None:
    """Peter, 2026-08-10: XP/h-Anzeige. Level/Erfahrung stecken in
    derselben Antwort wie die Items — ein eigenes Signal, damit die
    bestehenden Verwerter von ``character_items_loaded`` unangetastet
    bleiben."""
    worker = ApiWorker()
    monkeypatch.setattr(worker.client, "get_character_items", lambda name: (87, 1631274653, []))

    results: list[tuple[str, int, int]] = []
    worker.character_snapshot_loaded.connect(lambda name, level, xp: results.append((name, level, xp)))

    worker._dispatch(FetchCharacterItemsJob("WitchOfPeter"))

    assert results == [("WitchOfPeter", 87, 1631274653)]
    worker.client.close()


def test_run_emits_busy_changed_around_each_job(qapp, monkeypatch) -> None:
    """run() direkt (synchron, kein echter QThread) aufgerufen — deterministisch testbar."""
    worker = ApiWorker()
    worker.client.set_token("test")  # sonst überspringt run() Daten-Jobs (§_skip_unauthenticated)
    fake_stash = StashTab.model_validate({
        "id": "t1", "name": "Tab", "type": "CurrencyStash", "metadata": {}, "items": [],
    })
    monkeypatch.setattr(worker.client, "get_stash", lambda league, sid, parent_id=None: fake_stash)

    busy_events: list[bool] = []
    worker.busy_changed.connect(busy_events.append)

    worker.submit(FetchStashItemsJob("Standard", "t1", "Tab"))
    worker.stop()  # legt _StopJob an, damit run() nach dem einen Job zurückkehrt
    worker.run()

    assert busy_events == [True, False]


def test_stash_items_dispatch_passes_league_and_silent_through_signal(qapp, monkeypatch) -> None:
    """Regression: der Handler in MainWindow braucht die Liga aus dem Signal, nicht
    aus self._current_league — sonst verfälscht ein später Hintergrund-Job die
    Daten der inzwischen aktiven Liga."""
    worker = ApiWorker()
    fake_stash = StashTab.model_validate({
        "id": "t1", "name": "Currency 1", "type": "CurrencyStash", "metadata": {}, "items": [],
    })
    monkeypatch.setattr(worker.client, "get_stash", lambda league, sid, parent_id=None: fake_stash)

    received = []
    worker.stash_items_loaded.connect(
        lambda league, sid, name, items, silent: received.append((league, sid, name, silent)))

    worker._dispatch(FetchStashItemsJob("Standard", "t1", "Currency 1", silent=True))

    assert received == [("Standard", "t1", "Currency 1", True)]
    worker.client.close()


def test_special_tab_response_emits_children_signal_with_backfilled_parent(qapp, monkeypatch) -> None:
    """MapStash/UniqueStash liefern children statt items — eigenes Signal, und
    jedes Kind bekommt parent gesetzt (nötig für den Substash-Endpunkt)."""
    worker = ApiWorker()
    special = StashTab.model_validate({
        "id": "m1", "name": "Maps", "type": "MapStash", "metadata": {},
        "children": [{"id": "c1", "type": "MapStash",
                      "metadata": {"map": {"name": "Beach Map", "tier": 16}}}],
    })
    monkeypatch.setattr(worker.client, "get_stash",
                        lambda league, sid, parent_id=None: special)

    items_events, children_events = [], []
    worker.stash_items_loaded.connect(lambda *args: items_events.append(args))
    worker.stash_children_loaded.connect(lambda *args: children_events.append(args))

    worker._dispatch(FetchStashItemsJob("Standard", "m1", "Maps"))

    assert items_events == []
    assert len(children_events) == 1
    league, sid, name, children, silent = children_events[0]
    assert (league, sid, name, silent) == ("Standard", "m1", "Maps", False)
    assert children[0].parent == "m1"  # backfilled
    worker.client.close()


def test_dispatch_passes_parent_id_to_client_for_substash(qapp, monkeypatch) -> None:
    worker = ApiWorker()
    calls = []

    def fake_get_stash(league, sid, parent_id=None):
        calls.append((league, sid, parent_id))
        return StashTab.model_validate({"id": sid, "name": "Beach", "type": "MapStash",
                                        "metadata": {}, "items": []})

    monkeypatch.setattr(worker.client, "get_stash", fake_get_stash)

    worker._dispatch(FetchStashItemsJob("Standard", "c1", "Beach", parent_id="m1"))

    assert calls == [("Standard", "c1", "m1")]
    worker.client.close()


def test_silent_stash_items_dispatch_emits_no_status(qapp, monkeypatch) -> None:
    """Hintergrund-Auto-Refresh darf den Status-Text nicht mit Ladehinweisen stören."""
    worker = ApiWorker()
    fake_stash = StashTab.model_validate({
        "id": "t1", "name": "Currency 1", "type": "CurrencyStash", "metadata": {}, "items": [],
    })
    monkeypatch.setattr(worker.client, "get_stash", lambda league, sid, parent_id=None: fake_stash)

    emitted: list[str] = []
    worker.status.connect(emitted.append)

    worker._dispatch(FetchStashItemsJob("Standard", "t1", "Currency 1", silent=True))

    assert emitted == []
    worker.client.close()


def test_silent_character_items_dispatch_emits_no_status(qapp, monkeypatch) -> None:
    """Analog zu Stash-Items: der Live-Refresh des gerade angezeigten
    Charakters darf den Status-Text nicht mit Ladehinweisen stören."""
    worker = ApiWorker()
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})
    monkeypatch.setattr(worker.client, "get_character_items", lambda name: (0, 0, [item]))

    emitted: list[str] = []
    worker.status.connect(emitted.append)
    results = []
    worker.character_items_loaded.connect(lambda name, items: results.append((name, items)))

    worker._dispatch(FetchCharacterItemsJob("WitchOfPeter", silent=True))

    assert emitted == []
    assert results == [("WitchOfPeter", [item])]  # Ergebnis kommt trotzdem an
    worker.client.close()


# --- Offline-Erkennung (GGG-Wartung am Patchday) ---------- #

import httpx
import pytest

from poe_view.api.client import ApiError, AuthError
from poe_view.services.api_worker import FetchStashItemsJob, _is_connectivity_issue


@pytest.mark.parametrize("exc", [
    httpx.ConnectError("Verbindung abgelehnt"),
    httpx.ConnectTimeout("Timeout"),
    ApiError(503, "HTTP 503 für /profile: Maintenance"),
    ApiError(502, "HTTP 502 für /profile: Bad Gateway"),
])
def test_is_connectivity_issue_true_for_network_and_5xx(exc) -> None:
    assert _is_connectivity_issue(exc) is True


@pytest.mark.parametrize("exc", [
    ApiError(404, "HTTP 404 für /stash/x: nicht gefunden"),
    ApiError(400, "HTTP 400 für /stash/x: schlechte Anfrage"),
    ValueError("irgendein anderer Fehler"),
])
def test_is_connectivity_issue_false_for_client_errors(exc) -> None:
    """4xx sind echte Anwendungsfehler, kein Offline-Zustand — sonst würde
    z. B. ein falsch zusammengesetzter Substash-Pfad fälschlich "Offline" zeigen."""
    assert _is_connectivity_issue(exc) is False


def test_a_maintenance_400_counts_as_offline_despite_being_a_client_error() -> None:
    """Peters Log vom 2026-08-13, 01:03:41-01:17:41: Waehrend einer
    GGG-Wartung antwortete /character 22x mit 503, /stash im selben
    Augenblick (170 ms spaeter) 19x mit HTTP 400 "Invalid query; League
    not found". Die Liga gab es die ganze Zeit — um 01:18:21 lieferte
    dieselbe URL wieder 200.

    Der Statuscode allein taugt hier also nicht. Ohne diese Ausnahme
    schrieb die Anwendung 19 Tracebacks ins Log und 19 rote Meldungen
    ueber ihr eigenes Offline-Banner, mit einer Begruendung, die dem
    Nutzer faelschlich seine Liga absprach."""
    exc = ApiError(400, "HTTP 400 for /stash/Allflame/152a892ed5: ...",
                   error_code=2, error_message="Invalid query; League not found")

    assert _is_connectivity_issue(exc) is True


def test_a_genuinely_bad_query_stays_a_real_error() -> None:
    """Die Gegenprobe, und der Grund, warum die Ausnahme am TEXT haengt
    und nicht am Fehlercode: Code 2 heisst bei GGG allgemein "Invalid
    query" und traefe auch einen von uns falsch gebauten Substash-Pfad —
    genau den Fall, den die 4xx-Regel schuetzen soll. Der duerfte nicht
    als "GGG ist weg" verschluckt werden."""
    exc = ApiError(400, "HTTP 400 for /stash/Allflame/a/b/c: ...",
                   error_code=2, error_message="Invalid query")

    assert _is_connectivity_issue(exc) is False


def test_a_maintenance_400_stays_quiet_for_a_background_refresh(qapp, monkeypatch) -> None:
    """Der eigentliche Schaden war nicht die falsche Einordnung, sondern
    ihre Folge: Der stille Hintergrund-Refresh laeuft alle paar Sekunden
    weiter und ueberschrieb das Offline-Banner mit einer Fehlermeldung."""
    worker = ApiWorker()
    worker.client.set_token("test")
    monkeypatch.setattr(worker.client, "get_stash",
                        lambda league, sid, parent_id=None: (_ for _ in ()).throw(
                            ApiError(400, "HTTP 400 for /stash/Allflame/152a892ed5: ...",
                                     error_code=2,
                                     error_message="Invalid query; League not found")))
    offline_events, errors = [], []
    worker.offline_changed.connect(offline_events.append)
    worker.job_error.connect(errors.append)

    worker.submit(FetchStashItemsJob("Allflame", "152a892ed5", "Tab", silent=True))
    worker.stop()
    worker.run()

    assert offline_events == [True]
    assert errors == []
    worker.client.close()


def test_connectivity_error_sets_offline_and_suppresses_status_for_silent_job(qapp, monkeypatch) -> None:
    """Silent (Hintergrund-Auto-Refresh) darf bei anhaltender Wartung nicht
    alle paar Sekunden das Offline-Banner mit Fehlertext überschreiben."""
    worker = ApiWorker()
    worker.client.set_token("test")  # sonst überspringt run() Daten-Jobs (§_skip_unauthenticated)
    monkeypatch.setattr(worker.client, "get_stash",
                        lambda league, sid, parent_id=None: (_ for _ in ()).throw(
                            httpx.ConnectError("kein Netz")))
    offline_events, errors = [], []
    worker.offline_changed.connect(offline_events.append)
    worker.job_error.connect(errors.append)

    worker.submit(FetchStashItemsJob("Standard", "t1", "Tab", silent=True))
    worker.stop()
    worker.run()

    assert offline_events == [True]
    assert errors == []
    worker.client.close()


def test_connectivity_error_emits_friendly_message_for_manual_job(qapp, monkeypatch) -> None:
    worker = ApiWorker()
    worker.client.set_token("test")  # sonst überspringt run() Daten-Jobs (§_skip_unauthenticated)
    monkeypatch.setattr(worker.client, "get_stash",
                        lambda league, sid, parent_id=None: (_ for _ in ()).throw(
                            httpx.ConnectError("kein Netz")))
    offline_events, errors = [], []
    worker.offline_changed.connect(offline_events.append)
    worker.job_error.connect(errors.append)

    worker.submit(FetchStashItemsJob("Standard", "t1", "Tab", silent=False))
    worker.stop()
    worker.run()

    assert offline_events == [True]
    assert len(errors) == 1 and "unreachable" in errors[0]
    worker.client.close()


def test_offline_clears_after_a_successful_job(qapp, monkeypatch) -> None:
    """Selbstheilend: der nächste erfolgreiche Job (z. B. Retry per ⟳-Klick)
    beendet den Offline-Zustand wieder — kein manuelles Zurücksetzen nötig."""
    worker = ApiWorker()
    worker.client.set_token("test")  # sonst überspringt run() Daten-Jobs (§_skip_unauthenticated)
    fake_stash = StashTab.model_validate({
        "id": "t1", "name": "Tab", "type": "CurrencyStash", "metadata": {}, "items": [],
    })
    calls = {"n": 0}

    def flaky_get_stash(league, sid, parent_id=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("kein Netz")
        return fake_stash

    monkeypatch.setattr(worker.client, "get_stash", flaky_get_stash)
    offline_events = []
    worker.offline_changed.connect(offline_events.append)

    worker.submit(FetchStashItemsJob("Standard", "t1", "Tab"))
    worker.submit(FetchStashItemsJob("Standard", "t1", "Tab"))
    worker.stop()
    worker.run()

    assert offline_events == [True, False]
    worker.client.close()


def test_offline_state_change_not_re_emitted_for_repeated_failures(qapp, monkeypatch) -> None:
    worker = ApiWorker()
    worker.client.set_token("test")  # sonst überspringt run() Daten-Jobs (§_skip_unauthenticated)
    monkeypatch.setattr(worker.client, "get_stash",
                        lambda league, sid, parent_id=None: (_ for _ in ()).throw(
                            httpx.ConnectError("kein Netz")))
    offline_events = []
    worker.offline_changed.connect(offline_events.append)

    worker.submit(FetchStashItemsJob("Standard", "t1", "Tab", silent=True))
    worker.submit(FetchStashItemsJob("Standard", "t1", "Tab", silent=True))
    worker.stop()
    worker.run()

    assert offline_events == [True]  # nur EIN Signal, nicht pro fehlgeschlagenem Job
    worker.client.close()


# --- Startup-401: Daten-Jobs ohne Token ------------------- #

def test_data_jobs_are_skipped_while_no_token_is_set(qapp, monkeypatch) -> None:
    """Regression (FALLSTRICKE #35): Beim Programmstart reiht `_build_ui()`
    einen FetchStashListJob mit ein, noch bevor feststeht, ob überhaupt ein
    gültiges Token existiert. Fand Bootstrap keines, ging dieser Job ohne
    Authorization-Header raus und kassierte einen sicheren 401 — real bei 42
    von 58 Programmstarts, jeweils 0,7s nach dem Laden des Daten-Caches."""
    from poe_view.services.api_worker import FetchStashListJob
    worker = ApiWorker()
    assert not worker.client.has_token
    calls = []
    monkeypatch.setattr(worker.client, "get_stashes", lambda league: calls.append(league) or [])

    worker.submit(FetchStashListJob("Allflame"))
    worker.stop()
    worker.run()

    assert calls == [], "ohne Token darf gar kein Request rausgehen"
    worker.client.close()


def test_data_jobs_run_normally_once_a_token_is_set(qapp, monkeypatch) -> None:
    """Gegenprobe: der Guard darf den Normalbetrieb nicht blockieren."""
    from poe_view.services.api_worker import FetchStashListJob
    worker = ApiWorker()
    worker.client.set_token("test")
    calls = []
    monkeypatch.setattr(worker.client, "get_stashes", lambda league: calls.append(league) or [])

    worker.submit(FetchStashListJob("Allflame"))
    worker.stop()
    worker.run()

    assert calls == ["Allflame"]
    worker.client.close()


def test_fetch_prices_dispatch_emits_league_and_index(qapp, monkeypatch) -> None:
    worker = ApiWorker()
    fake_index = PriceIndex()
    calls = []
    monkeypatch.setattr("poe_view.services.api_worker.ninja.fetch_price_index",
                        lambda league, http: calls.append((league, http)) or fake_index)

    received = []
    worker.prices_loaded.connect(lambda league, index: received.append((league, index)))

    worker._dispatch(FetchPricesJob("Standard"))

    assert calls == [("Standard", worker._ninja_http)]
    assert received == [("Standard", fake_index)]
    worker.client.close()
    worker._ninja_http.close()


def test_fetch_prices_dispatch_emits_no_status_text(qapp, monkeypatch) -> None:
    """Läuft meist unauffällig bei einem Liga-Wechsel — soll keine
    relevantere Meldung (z. B. 'Loading stash list…') überschreiben."""
    worker = ApiWorker()
    monkeypatch.setattr("poe_view.services.api_worker.ninja.fetch_price_index",
                        lambda league, http: PriceIndex())
    emitted: list[str] = []
    worker.status.connect(emitted.append)

    worker._dispatch(FetchPricesJob("Standard"))

    assert emitted == []
    worker.client.close()
    worker._ninja_http.close()


def test_fetch_prices_job_runs_without_a_token() -> None:
    """poe.ninja ist unabhängig von der GGG-Anmeldung — anders als die
    GGG-Daten-Jobs darf dieser auch ohne Token laufen (kein Eintrag in
    ``ApiWorker._NEEDS_AUTH``)."""
    worker = ApiWorker()
    assert not worker.client.has_token
    assert not worker._skip_unauthenticated(FetchPricesJob("Standard"))
    worker.client.close()
    worker._ninja_http.close()


def test_a_401_without_a_token_does_not_delete_the_stored_token(qapp, monkeypatch) -> None:
    """Ein 401 ohne gesetztes Token ist selbstverschuldet und sagt nichts
    über das GESPEICHERTE Token aus — es darf dabei nicht gelöscht werden
    (sonst zerstört ein Startup-401 ein völlig intaktes Token)."""
    from poe_view.services import api_worker as api_worker_module
    from poe_view.services.api_worker import FetchStashListJob
    worker = ApiWorker()
    deleted = []
    monkeypatch.setattr(api_worker_module.token_store, "delete_token",
                        lambda: deleted.append(True))
    # Guard umgehen, um den reinen AuthError-Pfad zu prüfen:
    monkeypatch.setattr(worker, "_skip_unauthenticated", lambda job: False)
    monkeypatch.setattr(worker.client, "get_stashes",
                        lambda league: (_ for _ in ()).throw(AuthError("401")))
    required = []
    worker.login_required.connect(required.append)

    worker.submit(FetchStashListJob("Allflame"))
    worker.stop()
    worker.run()

    assert deleted == [], "kein Token gesetzt -> nichts zu verwerfen"
    assert len(required) == 1  # Login wird trotzdem angefordert
    worker.client.close()


def test_a_401_with_a_token_still_discards_it(qapp, monkeypatch) -> None:
    """Gegenprobe: Wurde ein Token mitgeschickt und GGG lehnt es ab, ist es
    tatsächlich unbrauchbar und muss weg (bisheriges Verhalten)."""
    from poe_view.services import api_worker as api_worker_module
    from poe_view.services.api_worker import FetchStashListJob
    worker = ApiWorker()
    worker.client.set_token("abgelaufen")
    deleted = []
    monkeypatch.setattr(api_worker_module.token_store, "delete_token",
                        lambda: deleted.append(True))
    monkeypatch.setattr(worker.client, "get_stashes",
                        lambda league: (_ for _ in ()).throw(AuthError("401")))

    worker.submit(FetchStashListJob("Allflame"))
    worker.stop()
    worker.run()

    assert deleted == [True]
    worker.client.close()


# --- "Load All Tabs": gleichmäßiger Takt statt Burst ------ #

def _bulk_worker(monkeypatch, n_tabs: int):
    """Worker mit n gefakten Tabs; zeichnet die Wartezeiten zwischen den
    Abrufen auf, ohne real zu schlafen."""
    from poe_view.services.api_worker import FetchAllItemsJob
    worker = ApiWorker()
    worker.client.set_token("test")
    stashes = [StashTab.model_validate(
        {"id": f"t{i}", "name": f"Tab {i}", "type": "CurrencyStash", "metadata": {}})
        for i in range(n_tabs)]
    fetched = StashTab.model_validate(
        {"id": "t", "name": "T", "type": "CurrencyStash", "metadata": {}, "items": []})
    monkeypatch.setattr(worker.client, "get_stash",
                        lambda league, sid, parent_id=None: fetched)
    monkeypatch.setattr(worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 11.0)
    waits: list[float] = []
    monkeypatch.setattr(worker._cancel_bulk, "wait",
                        lambda timeout=None: waits.append(timeout) or False)
    return worker, FetchAllItemsJob("Standard", stashes), waits


def test_load_all_tabs_paces_every_tab_after_the_first(qapp, monkeypatch) -> None:
    """Peter: "einfach dafür sorgen, dass alle Tabs einmal so schnell wie es
    eben geht (ca. 11s pro Tab) geladen werden". Ohne Takt feuerte die
    Schleife los, füllte binnen ~29 Tabs das Rate-Limit-Fenster und lief in
    die 300s-Zwangspause (FALLSTRICKE #34)."""
    worker, job, waits = _bulk_worker(monkeypatch, n_tabs=4)
    done = []
    worker.bulk_finished.connect(lambda ok, total: done.append((ok, total)))

    worker._dispatch(job)

    assert waits == [11.0, 11.0, 11.0]  # vor Tab 2,3,4 — nicht vor dem ersten
    assert done == [(4, 4)]
    worker.client.close()


def test_load_all_tabs_cancel_takes_effect_during_the_pause(qapp, monkeypatch) -> None:
    """Abbrechen darf nicht erst nach dem laufenden Takt greifen — deshalb
    ``Event.wait(timeout)`` statt ``time.sleep``."""
    from poe_view.services.api_worker import FetchAllItemsJob
    worker = ApiWorker()
    worker.client.set_token("test")
    stashes = [StashTab.model_validate(
        {"id": f"t{i}", "name": f"Tab {i}", "type": "CurrencyStash", "metadata": {}})
        for i in range(5)]
    fetched = StashTab.model_validate(
        {"id": "t", "name": "T", "type": "CurrencyStash", "metadata": {}, "items": []})
    monkeypatch.setattr(worker.client, "get_stash",
                        lambda league, sid, parent_id=None: fetched)
    monkeypatch.setattr(worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 11.0)
    # Erste Wartephase meldet sofort "abgebrochen" (wie ein Klick währenddessen).
    monkeypatch.setattr(worker._cancel_bulk, "wait", lambda timeout=None: True)
    done = []
    worker.bulk_finished.connect(lambda ok, total: done.append((ok, total)))

    worker._dispatch(FetchAllItemsJob("Standard", stashes))

    assert done == [(1, 5)], "nur der erste Tab lief, dann sofortiger Abbruch"
    worker.client.close()


def _progress_worker(monkeypatch):
    """Worker mit gemocktem Netz/Takt für die Bulk-Fortschritts-Tests."""
    worker = ApiWorker()
    worker.client.set_token("test")
    fetched = StashTab.model_validate(
        {"id": "t", "name": "T", "type": "CurrencyStash", "metadata": {}, "items": []})
    monkeypatch.setattr(worker.client, "get_stash",
                        lambda league, sid, parent_id=None: fetched)
    monkeypatch.setattr(worker.rate_limiter, "steady_pace_interval_s", lambda *a, **k: 11.0)
    monkeypatch.setattr(worker._cancel_bulk, "wait", lambda timeout=None: False)
    return worker


_MAP_SECTIONS = [
    {"id": "map-a", "name": "Map A", "parent": "map", "type": "Standard", "metadata": {}},
    {"id": "map-b", "name": "Map B", "parent": "map", "type": "Standard", "metadata": {}},
    {"id": "map-c", "name": "Map C", "parent": "map", "type": "Standard", "metadata": {}},
    {"id": "t1", "name": "Tab 1", "type": "CurrencyStash", "metadata": {}},
]
_MAP_POSITIONS = {"map-a": 5, "map-b": 5, "map-c": 5, "t1": 9}


def test_load_all_tabs_counts_map_stash_sections_as_one_slot(qapp, monkeypatch) -> None:
    """Regression FALLSTRICKE #36/#37: Peters echte Standard-Liga zeigte
    "58/561" statt "58/391" — 561 war die Anzahl ladbarer Einheiten (jede
    Map-/Unique-Sektion ein eigener Abruf), nicht echter Truhenplätze. Die
    TRUHENPLATZ-Zahl muss diese drei Sektionen weiterhin als EINEN Platz (5)
    zählen; sie steht als Text im Dialog-Label."""
    from poe_view.services.api_worker import FetchAllItemsJob
    worker = _progress_worker(monkeypatch)
    stashes = [StashTab.model_validate(s) for s in _MAP_SECTIONS]
    slots: list[tuple[int, int]] = []
    worker.bulk_progress.connect(
        lambda p: slots.append((p.done_slots, p.total_slots)))
    done = []
    worker.bulk_finished.connect(lambda ok, total: done.append((ok, total)))

    worker._dispatch(FetchAllItemsJob("Standard", stashes, _MAP_POSITIONS))

    # 4 Abrufe, aber nur 2 echte Plätze (5 und 9).
    assert slots == [(1, 2), (1, 2), (1, 2), (2, 2)]
    assert done == [(2, 2)]
    worker.client.close()


def test_load_all_tabs_request_count_advances_on_every_fetch(qapp, monkeypatch) -> None:
    """Regression FALLSTRICKE #42: Der Balken darf NICHT an Truhenplätzen
    hängen — bei Peters MapStash mit 365 Sektionen auf einem Platz stünde
    er sonst 67 Minuten still. Die Abruf-Zahl wächst bei jedem Schritt."""
    from poe_view.services.api_worker import FetchAllItemsJob
    worker = _progress_worker(monkeypatch)
    stashes = [StashTab.model_validate(s) for s in _MAP_SECTIONS]
    requests: list[tuple[int, int]] = []
    worker.bulk_progress.connect(
        lambda p: requests.append((p.done_requests, p.total_requests)))

    worker._dispatch(FetchAllItemsJob("Standard", stashes, _MAP_POSITIONS))

    assert requests == [(1, 4), (2, 4), (3, 4), (4, 4)]
    worker.client.close()


def test_load_all_tabs_reports_a_remaining_time_estimate(qapp, monkeypatch) -> None:
    """Restzeit kommt aus der gemessenen Rate, nicht aus dem Soll-Takt —
    sonst blieben Rate-Limit-Zwangspausen unsichtbar. Sie sinkt monoton
    und ist beim letzten Abruf null."""
    from poe_view.services.api_worker import FetchAllItemsJob
    worker = _progress_worker(monkeypatch)
    stashes = [StashTab.model_validate(s) for s in _MAP_SECTIONS]
    etas: list[float] = []
    worker.bulk_progress.connect(lambda p: etas.append(p.remaining_s))

    worker._dispatch(FetchAllItemsJob("Standard", stashes, _MAP_POSITIONS))

    assert all(e >= 0 for e in etas)
    assert etas == sorted(etas, reverse=True)  # monoton fallend
    assert etas[-1] == 0.0                     # nach dem letzten Abruf nichts mehr offen
    worker.client.close()


def test_load_all_tabs_reports_the_pause_until_the_next_fetch(qapp, monkeypatch) -> None:
    """Der Bulk-Dialog zeigt einen Sekunden-Countdown bis zum nächsten Abruf
    — dafür muss der Worker die Taktpause melden, die seine Schleife gleich
    selbst abwartet. Nach dem LETZTEN Abruf wartet niemand mehr (0)."""
    from poe_view.services.api_worker import FetchAllItemsJob
    worker = _progress_worker(monkeypatch)
    stashes = [StashTab.model_validate(s) for s in _MAP_SECTIONS]
    waits: list[float] = []
    worker.bulk_progress.connect(lambda p: waits.append(p.next_wait_s))

    worker._dispatch(FetchAllItemsJob("Standard", stashes, _MAP_POSITIONS))

    assert waits == [11.0, 11.0, 11.0, 0.0]
    worker.client.close()


def test_load_all_tabs_reports_the_stash_id_of_each_fetched_tab(qapp, monkeypatch) -> None:
    """Für die Hervorhebung im Stash-Baum (MainWindow._on_bulk_progress →
    StashTree.highlight_stash) braucht die UI die Fach-ID, nicht nur den
    Namen: Namen sind in Map-/Unique-Sektionen nicht eindeutig."""
    from poe_view.services.api_worker import FetchAllItemsJob
    worker = _progress_worker(monkeypatch)
    stashes = [StashTab.model_validate(s) for s in _MAP_SECTIONS]
    ids: list[str] = []
    worker.bulk_progress.connect(lambda p: ids.append(p.stash_id))

    worker._dispatch(FetchAllItemsJob("Standard", stashes, _MAP_POSITIONS))

    assert ids == ["map-a", "map-b", "map-c", "t1"]
    worker.client.close()


# --- Erfahrung jenseits von 32 Bit (Peters Log, 2026-08-16) ------------- #

def test_experience_above_two_billion_still_reaches_the_ui(qapp):
    """Qts ``int`` ist 32-bittig und endet bei 2.147.483.647. PoE
    ueberschreitet das mitten in Stufe 91; Stufe 100 sind 4.250.334.444.
    Mit ``Signal(..., int)`` warf ``emit`` dort einen OverflowError, das
    Signal kam nie an, und die XP-Anzeige stand still, waehrend im
    Terminal alle paar Sekunden eine Shiboken-Warnung auflief.

    Peters echter Wert aus dem Log: 2.151.302.311."""
    worker = ApiWorker()
    angekommen = []
    worker.character_snapshot_loaded.connect(
        lambda name, level, xp: angekommen.append((name, level, xp)))
    try:
        worker.character_snapshot_loaded.emit("WitchOfPeter", 91, 2_151_302_311)
        worker.character_snapshot_loaded.emit("WitchOfPeter", 100, 4_250_334_444)
    finally:
        worker.client.close()
        worker._ninja_http.close()

    assert angekommen == [("WitchOfPeter", 91, 2_151_302_311),
                          ("WitchOfPeter", 100, 4_250_334_444)]
