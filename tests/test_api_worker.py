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
    monkeypatch.setattr(worker.client, "get_stash", lambda league, sid: fake_stash)

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
    monkeypatch.setattr(worker.client, "get_stash", lambda league, sid: fake_stash)

    busy_events: list[bool] = []
    worker.busy_changed.connect(busy_events.append)

    worker.submit(FetchStashItemsJob("Standard", "t1", "Tab"))
    worker.stop()  # legt _StopJob an, damit run() nach dem einen Job zurückkehrt
    worker.run()

    assert busy_events == [True, False]
