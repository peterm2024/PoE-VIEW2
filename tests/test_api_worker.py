"""Tests für ApiWorker._dispatch — v. a. die Regel, wann "Bereit" emittiert wird.

Ruft _dispatch() direkt und synchron auf (kein echter Thread, kein echtes
Netzwerk) — der Client wird per Monkeypatch durch eine Fake-Methode ersetzt.
"""

from poe_view.api.models import Item, StashTab
from poe_view.services.api_worker import (ApiWorker, FetchLeaguesJob,
                                          FetchStashItemsJob)


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
