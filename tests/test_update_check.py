"""Tests für den Update-Hinweis (§4.57, ``services/update_check.py``).

Peter, 2026-09-28: "Haben wir eigentlich eine
Aktualisierungsbenachrichtigung bei neuen Versionen?" — jetzt ja, als
Link in der Statusleiste, ohne Auto-Update. Kein Test hier spricht mit
GitHub: Alle Antworten kommen aus einem ``httpx.MockTransport``.
"""

import json

import httpx
import pytest

from poe_view import config
from poe_view.services import update_check
from poe_view.services.api_worker import ApiWorker, CheckUpdateJob
from poe_view.ui.main_window import MainWindow
from poe_view.ui.settings_dialog import SettingsDialog

_URL = "https://github.com/peterm2024/PoE-VIEW2/releases/tag/v0.18.0"


def _client(tag="v0.18.0", status=200, calls=None, body=None):
    def antwort(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if body is not None:
            return httpx.Response(status, content=body)
        return httpx.Response(status, json={"tag_name": tag, "html_url": _URL})
    return httpx.Client(transport=httpx.MockTransport(antwort))


def _failing_client(calls):
    def antwort(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("kein Netz", request=request)
    return httpx.Client(transport=httpx.MockTransport(antwort))


# --- Versionsvergleich ---------------------------------------------------- #

@pytest.mark.parametrize("text, erwartet", [
    ("v0.17.0", (0, 17, 0)),
    ("0.17.0", (0, 17, 0)),
    ("0.17.0+dev", (0, 17, 0)),
    ("  v1.2.3\n", (1, 2, 3)),
    ("v0.17", None),
    ("latest", None),
    ("", None),
])
def test_parse_version(text, erwartet) -> None:
    assert update_check.parse_version(text) == erwartet


def test_a_dev_build_is_not_older_than_the_release_it_came_from() -> None:
    """Zwischen zwei Releases trägt das Programm ``X.Y.Z+dev`` (RELEASING
    §4). Hielte der Vergleich das für älter als ``X.Y.Z``, meldete jeder
    Entwicklerstand das Release, aus dem er gerade entstanden ist."""
    assert not update_check.is_newer("v0.17.0", "0.17.0+dev")


def test_numbers_are_compared_as_numbers_not_as_text() -> None:
    """Als Text wäre "0.9.0" größer als "0.17.0"."""
    assert update_check.is_newer("v0.17.0", "0.9.0")
    assert not update_check.is_newer("v0.9.0", "0.17.0")


def test_an_unreadable_version_never_reports_an_update() -> None:
    assert not update_check.is_newer("nightly", "0.17.0")
    assert not update_check.is_newer("v0.18.0", "unbekannt")


# --- Abruf und Vorrat ---------------------------------------------------- #

def test_a_newer_release_is_reported_with_its_page() -> None:
    release = update_check.check(_client(), current="0.17.0", now=1000.0)
    assert release == update_check.Release("v0.18.0", _URL)


def test_the_same_or_an_older_release_is_not_reported() -> None:
    assert update_check.check(_client("v0.17.0"), current="0.17.0", now=1000.0) is None
    update_check._cache_path().unlink()
    assert update_check.check(_client("v0.16.0"), current="0.17.0", now=1000.0) is None


def test_the_answer_is_kept_for_six_hours() -> None:
    """Ein Start innerhalb der sechs Stunden fragt GitHub nicht erneut —
    ohne Anmeldung sind es 60 Anfragen pro Stunde und IP."""
    calls = []
    update_check.check(_client(calls=calls), current="0.17.0", now=1000.0)
    update_check.check(_client(calls=calls), current="0.17.0",
                       now=1000.0 + update_check.TTL_SECONDS - 1)
    assert len(calls) == 1


def test_after_six_hours_github_is_asked_again() -> None:
    calls = []
    update_check.check(_client("v0.18.0", calls=calls), current="0.17.0", now=1000.0)
    release = update_check.check(_client("v0.19.0", calls=calls), current="0.17.0",
                                 now=1000.0 + update_check.TTL_SECONDS + 1)
    assert len(calls) == 2
    assert release.version == "v0.19.0"


def test_a_failed_request_is_silent_and_not_kept() -> None:
    """Ohne Netz erscheint nichts — und der nächste Start fragt erneut,
    statt sechs Stunden lang ein "nichts" vorzuhalten."""
    calls = []
    assert update_check.check(_failing_client(calls), current="0.17.0", now=1000.0) is None
    assert not update_check._cache_path().exists()
    assert update_check.check(_client(calls=calls), current="0.17.0",
                              now=1001.0) is not None
    assert len(calls) == 2


@pytest.mark.parametrize("status, body", [
    (404, None),                 # Repo ohne Release
    (403, None),                 # Anfragen-Grenze erschöpft
    (200, b"<html>nope</html>"), # kein JSON
    (200, b'{"name": "x"}'),     # JSON ohne tag_name
])
def test_unusable_answers_are_silent(status, body) -> None:
    assert update_check.check(_client(status=status, body=body),
                              current="0.17.0", now=1000.0) is None


def test_a_broken_cache_file_is_simply_asked_again() -> None:
    update_check._cache_path().parent.mkdir(parents=True, exist_ok=True)
    update_check._cache_path().write_text("{kaputt", encoding="utf-8")
    calls = []
    assert update_check.check(_client(calls=calls), current="0.17.0",
                              now=1000.0) is not None
    assert len(calls) == 1


def test_the_cache_lives_in_the_redirected_data_folder() -> None:
    """Die Autouse-Fixture biegt ``APP_DATA_DIR`` um; der Pfad muss das
    sehen, sonst schriebe dieser Test in Peters echten Datenordner."""
    update_check.check(_client(), current="0.17.0", now=1000.0)
    pfad = config.APP_DATA_DIR / "update-check.json"
    assert pfad.exists()
    assert json.loads(pfad.read_text(encoding="utf-8"))["version"] == "v0.18.0"


# --- Worker --------------------------------------------------------------- #

def test_the_worker_emits_only_for_a_newer_release(qapp) -> None:
    """Verglichen wird mit der laufenden Version — deshalb Tags weit
    davon weg, damit der Test das nächste Release überlebt."""
    worker = ApiWorker()
    gemeldet = []
    worker.update_available.connect(gemeldet.append)

    worker._github_http = _client("v0.0.1")
    worker._dispatch(CheckUpdateJob())
    assert gemeldet == []

    update_check._cache_path().unlink()
    worker._github_http = _client("v999.0.0")
    worker._dispatch(CheckUpdateJob())
    assert gemeldet == [update_check.Release("v999.0.0", _URL)]


# --- Hauptfenster --------------------------------------------------------- #

def _queued_jobs(win):
    jobs = []
    while not win.worker._jobs.empty():
        jobs.append(win.worker._jobs.get_nowait())
    return jobs


@pytest.fixture
def unstarted_worker(monkeypatch):
    monkeypatch.setattr(ApiWorker, "start", lambda self: None)


def test_the_exe_checks_at_startup_by_default(qapp, monkeypatch, unstarted_worker) -> None:
    """Standardmäßig AN (Peter, 2026-09-28)."""
    monkeypatch.setattr(config, "RUNNING_AS_EXE", True)
    win = MainWindow()
    assert any(isinstance(j, CheckUpdateJob) for j in _queued_jobs(win))


def test_running_from_source_never_checks(qapp, monkeypatch, unstarted_worker) -> None:
    monkeypatch.setattr(config, "RUNNING_AS_EXE", False)
    win = MainWindow()
    assert not any(isinstance(j, CheckUpdateJob) for j in _queued_jobs(win))


def test_the_setting_switches_the_check_off(qapp, monkeypatch, unstarted_worker) -> None:
    monkeypatch.setattr(config, "RUNNING_AS_EXE", True)
    win = MainWindow()
    win._save_update_check_enabled(False)
    _queued_jobs(win)
    zweites = MainWindow()
    assert not any(isinstance(j, CheckUpdateJob) for j in _queued_jobs(zweites))


def test_the_status_bar_stays_empty_until_a_release_is_reported(
        qapp, unstarted_worker) -> None:
    win = MainWindow()
    assert win._update_label.text() == ""
    win._on_update_available(update_check.Release("v0.18.0", _URL))
    assert f'href="{_URL}"' in win._update_label.text()
    assert "v0.18.0 available" in win._update_label.text()
    assert win._update_label.openExternalLinks()


def test_the_link_is_escaped(qapp, unstarted_worker) -> None:
    """Tag und Adresse kommen von außen — ein Anführungszeichen darin darf
    das HTML der Statusleiste nicht aufbrechen."""
    win = MainWindow()
    win._on_update_available(update_check.Release('v1<b>"', 'https://x.test/"><b>'))
    text = win._update_label.text()
    assert "<b>" not in text
    assert "&quot;" in text


# --- Einstellungen -------------------------------------------------------- #

def test_the_settings_dialog_shows_and_returns_the_switch(qapp) -> None:
    an = SettingsDialog([], [], False, "")
    assert an.result_update_check_enabled() is True
    aus = SettingsDialog([], [], False, "", update_check_enabled=False)
    assert aus.result_update_check_enabled() is False
    aus._update_check_box.setChecked(True)
    assert aus.result_update_check_enabled() is True


def test_the_setting_survives_a_restart(qapp, unstarted_worker) -> None:
    win = MainWindow()
    assert win._load_update_check_enabled() is True
    win._save_update_check_enabled(False)
    assert MainWindow()._load_update_check_enabled() is False
