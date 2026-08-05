"""Tests zum Zweitstart (Peter, 2026-08-05: "Zweitstart theoretisch ja,
aber nur im Offline-Modus bzw. anderer Account. Ich will nicht, dass
beide gleichzeitig Daten refreshen und dann beide versuchen den neuen
Inhalt zu schreiben.").

Der Anspruch gilt PRO KONTO — das ist die eigentliche Anforderung, nicht
"nur ein Fenster". Zwei Fenster mit verschiedenen Konten schreiben in
getrennte Dateien und verbrauchen getrennte Rate-Limit-Budgets.
"""

from poe_view.services import data_cache
from poe_view.services.api_worker import (ApiWorker, BootstrapJob,
                                          FetchCharacterItemsJob, FetchIconJob,
                                          FetchPricesJob, FetchStashItemsJob,
                                          LogoutJob)
from poe_view.services.instance_lock import InstanceLock


def test_the_second_claim_on_the_same_account_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(data_cache.config, "APP_DATA_DIR", tmp_path)

    first = InstanceLock("Gandol#4338")
    second = InstanceLock("Gandol#4338")

    assert first.acquire() is True
    assert second.acquire() is False
    assert first.held and not second.held

    first.release()


def test_releasing_hands_the_account_over(tmp_path, monkeypatch) -> None:
    """Fenster zu, anderes Fenster darf sofort weiterarbeiten — ohne dass
    jemand eine liegengebliebene Datei aufraeumen muesste."""
    monkeypatch.setattr(data_cache.config, "APP_DATA_DIR", tmp_path)

    first = InstanceLock("Gandol#4338")
    first.acquire()
    first.release()

    second = InstanceLock("Gandol#4338")
    assert second.acquire() is True
    second.release()


def test_two_different_accounts_do_not_block_each_other(tmp_path, monkeypatch) -> None:
    """Peters Bedingung "bzw. anderer Account" — genau dieser Fall soll
    weiterhin voll funktionieren."""
    monkeypatch.setattr(data_cache.config, "APP_DATA_DIR", tmp_path)

    one = InstanceLock("Gandol#4338")
    two = InstanceLock("Zweitkonto#1")

    assert one.acquire() is True
    assert two.acquire() is True

    one.release()
    two.release()


def test_release_is_safe_to_call_twice(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(data_cache.config, "APP_DATA_DIR", tmp_path)
    lock = InstanceLock("Gandol#4338")
    lock.acquire()
    lock.release()
    lock.release()  # darf nicht knallen
    assert not lock.held


# --- Der eigentliche Schutz sitzt im Worker ----------------------------- #

def test_read_only_worker_drops_every_data_job(qapp) -> None:
    """Alle GGG-Datenabrufe, egal aus welchem UI-Pfad sie stammen. Genau
    deshalb sitzt die Pruefung hier und nicht an einem Dutzend
    Klick-Handlern."""
    worker = ApiWorker()
    worker.read_only = True

    for job in (FetchStashItemsJob("Standard", "t1", "Currency"),
                FetchCharacterItemsJob("WitchOfPeter")):
        assert worker._skip_read_only(job) is True


def test_read_only_worker_still_allows_bootstrap_icons_and_prices(qapp) -> None:
    """Bootstrap MUSS laufen: Ohne den Kontonamen wuesste die Instanz nie,
    ob sie das Konto vielleicht doch beanspruchen darf. Icons kommen vom
    CDN, poe.ninja ist ein anderer Dienst — beide laufen nicht ueber GGGs
    Rate-Limit-Budget fuer dieses Konto."""
    worker = ApiWorker()
    worker.read_only = True

    for job in (BootstrapJob(), LogoutJob(), FetchIconJob("http://x/i.png"),
                FetchPricesJob("Standard")):
        assert worker._skip_read_only(job) is False


def test_a_normal_worker_drops_nothing(qapp) -> None:
    worker = ApiWorker()

    assert worker._skip_read_only(FetchStashItemsJob("Standard", "t1", "C")) is False


# --- Verdrahtung im Fenster --------------------------------------------- #

def _window_with_taken_account(monkeypatch, tmp_path, account="Gandol#4338"):
    """Ein Fenster, dessen Konto bereits von einer 'anderen Instanz'
    gehalten wird."""
    from poe_view.ui.main_window import MainWindow

    monkeypatch.setattr(data_cache.config, "APP_DATA_DIR", tmp_path)
    other = InstanceLock(account)
    assert other.acquire()
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._account_name = account
    win._claim_account(account)
    return win, other


def test_a_taken_account_puts_the_window_into_read_only(qapp, monkeypatch, tmp_path) -> None:
    win, other = _window_with_taken_account(monkeypatch, tmp_path)

    assert win._read_only is True
    assert win.worker.read_only is True          # der eigentliche Schutz
    assert "Read-only" in win._read_only_label.text()
    assert not win._refresh_action.isEnabled()
    assert not win._load_all_action.isEnabled()

    other.release()
    win.worker.stop()
    win.worker.wait(5000)


def test_a_read_only_window_never_writes_the_cache(qapp, monkeypatch, tmp_path) -> None:
    """Peters Kernanforderung: "nicht beide versuchen den neuen Inhalt zu
    schreiben"."""
    win, other = _window_with_taken_account(monkeypatch, tmp_path)
    written = []
    monkeypatch.setattr(data_cache, "save", lambda data, path=None: written.append(path))

    win._persist_cache()

    assert written == []

    other.release()
    win.worker.stop()
    win.worker.wait(5000)


def test_logging_in_with_another_account_makes_the_window_live_again(
        qapp, monkeypatch, tmp_path) -> None:
    """Peters Bedingung "bzw. anderer Account": Das zweite Fenster ist
    nicht dauerhaft entwertet, es braucht nur ein eigenes Konto."""
    win, other = _window_with_taken_account(monkeypatch, tmp_path)
    assert win._read_only is True

    win._on_logged_in("Zweitkonto#1")

    assert win._read_only is False
    assert win.worker.read_only is False
    assert win._read_only_label.text() == ""
    assert win._account_lock is not None and win._account_lock.account_name == "Zweitkonto#1"

    other.release()
    win.worker.stop()
    win.worker.wait(5000)


def test_closing_the_window_hands_the_account_back(qapp, monkeypatch, tmp_path) -> None:
    """Sonst müsste man das ganze Programm beenden, damit ein zweites
    Fenster das Konto übernehmen kann."""
    from poe_view.ui.main_window import MainWindow

    monkeypatch.setattr(data_cache.config, "APP_DATA_DIR", tmp_path)
    win = MainWindow()
    monkeypatch.setattr(win.worker, "submit", lambda job: None)
    win._claim_account("Gandol#4338")
    assert win._account_lock is not None

    win.close()

    assert win._account_lock is None
    assert InstanceLock("Gandol#4338").acquire() is True
