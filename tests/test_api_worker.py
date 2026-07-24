"""Tests für ApiWorker._dispatch — v. a. die Regel, wann "Bereit" emittiert wird.

Ruft _dispatch() direkt und synchron auf (kein echter Thread, kein echtes
Netzwerk) — der Client wird per Monkeypatch durch eine Fake-Methode ersetzt.
"""

from poe_view.api.models import Item, StashTab
from poe_view.services.api_worker import (ApiWorker, FetchCharacterItemsJob,
                                          FetchLeaguesJob, FetchStashItemsJob)


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

    assert emitted == ["Lade Items: Currency 1 …"]  # KEIN "Bereit" danach
    worker.client.close()


def test_leagues_dispatch_emits_bereit_after_result(qapp, monkeypatch) -> None:
    """Gegenprobe: Jobs ohne eigenen UI-Abschlusstext müssen 'Bereit' emittieren."""
    worker = ApiWorker()
    monkeypatch.setattr(worker.client, "get_leagues", lambda: ["Standard"])

    emitted: list[str] = []
    worker.status.connect(emitted.append)

    worker._dispatch(FetchLeaguesJob())

    assert emitted == ["Lade Ligen …", "Bereit"]
    worker.client.close()


def test_character_items_dispatch_emits_name_and_items(qapp, monkeypatch) -> None:
    worker = ApiWorker()
    item = Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5})
    monkeypatch.setattr(worker.client, "get_character_items", lambda name: [item])

    emitted: list[str] = []
    worker.status.connect(emitted.append)
    results: list[tuple[str, list[Item]]] = []
    worker.character_items_loaded.connect(lambda name, items: results.append((name, items)))

    worker._dispatch(FetchCharacterItemsJob("WitchOfPeter"))

    assert emitted == ["Lade Ausrüstung: WitchOfPeter …", "Bereit"]
    assert results == [("WitchOfPeter", [item])]
    worker.client.close()


def test_run_emits_busy_changed_around_each_job(qapp, monkeypatch) -> None:
    """run() direkt (synchron, kein echter QThread) aufgerufen — deterministisch testbar."""
    worker = ApiWorker()
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


# --- Offline-Erkennung (Nutzer-Feedback: GGG-Wartung am Patchday) ---------- #

import httpx
import pytest

from poe_view.api.client import ApiError
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


def test_connectivity_error_sets_offline_and_suppresses_status_for_silent_job(qapp, monkeypatch) -> None:
    """Silent (Hintergrund-Auto-Refresh) darf bei anhaltender Wartung nicht
    alle paar Sekunden das Offline-Banner mit Fehlertext überschreiben."""
    worker = ApiWorker()
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
    assert len(errors) == 1 and "nicht erreichbar" in errors[0]
    worker.client.close()


def test_offline_clears_after_a_successful_job(qapp, monkeypatch) -> None:
    """Selbstheilend: der nächste erfolgreiche Job (z. B. Retry per ⟳-Klick)
    beendet den Offline-Zustand wieder — kein manuelles Zurücksetzen nötig."""
    worker = ApiWorker()
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
