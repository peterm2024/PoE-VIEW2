"""Pytest-Setup: Qt läuft in Tests headless (kein echtes Display nötig)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_local_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Isoliert MainWindow() von echtem lokalem State: OAuth-Token (FALLSTRICKE #6),
    data-cache.json, ui-settings.ini (Spalten-Sichtbarkeit) und dem
    RePoE-Download (§4.53)."""
    monkeypatch.setattr("poe_view.services.token_store.load_token", lambda: None)
    monkeypatch.setattr("poe_view.services.data_cache._CACHE_FILE",
                        tmp_path / "unused-data-cache.json")
    # _settings() baut den Pfad bei jedem Aufruf aus config.APP_DATA_DIR —
    # deshalb reicht das Patchen des Modul-Globals hier aus.
    monkeypatch.setattr("poe_view.config.APP_DATA_DIR", tmp_path / "appdata")
    # LOG_DIR ist dagegen eine KONSTANTE, einmal beim Import aus dem
    # UNGEPATCHTEN APP_DATA_DIR berechnet (config.py: "LOG_DIR =
    # APP_DATA_DIR / 'logs'") — das Patchen von APP_DATA_DIR oben ändert
    # daran nichts mehr. Ohne diese Zeile hätte jeder Test, der eine
    # Charakter-Aktualisierung simuliert, ``gem_xp_log.append()`` in Peters
    # ECHTEN Log-Ordner schreiben lassen (dieselbe Falle wie bei
    # ``cache_backup``, die dort sechs Fremddateien verursacht hat, siehe
    # ``services/cache_backup.py``).
    monkeypatch.setattr("poe_view.config.LOG_DIR", tmp_path / "appdata" / "logs")
    # Die Gem-XP-Mitschrift lässt sich per Umgebungsvariable ein- und
    # ausschalten (§gem_xp_log.enabled). Steht die auf einem Entwickler-
    # rechner gesetzt, würde sie sonst hineinregieren und Tests je nach
    # Umgebung anders ausgehen lassen — Tests bestimmen ihren Zustand
    # selbst.
    monkeypatch.delenv("POEVIEW_GEM_XP_LOG", raising=False)
    # Dasselbe für die Beute-Mitschrift (§zone_loot_log.enabled).
    monkeypatch.delenv("POEVIEW_ZONE_LOOT_LOG", raising=False)
    # MainWindow() reiht bei jedem Start einen FetchModKnowledgeJob ein
    # (§4.53) — ohne diese Zeile würde JEDER Test, der ein MainWindow()
    # baut, echt gegen repoe-fork.github.io abrufen (der Cache in
    # tmp_path ist immer leer, also nie "fresh"). fetch() als
    # Fehlschlag simulieren reicht: ensure_fresh() greift dann nie zum
    # Netz, build() findet nichts und liefert None — schnell und
    # deterministisch, kein Verhalten der App wird dadurch verändert
    # (ein echter Offline-Start ohne Cache liefert genau dasselbe None).
    monkeypatch.setattr("poe_view.services.mod_knowledge.fetch", lambda http=None: False)
    # Dasselbe für die Baumdaten von GGG (§passive_tree), die im selben Job
    # mitkommen — rund 13 MB, die kein Test laden soll.
    monkeypatch.setattr("poe_view.services.passive_tree.fetch", lambda http=None: False)
    # Kein Abruf bei pobb.in/pastebin (§pob_import): Wer einen Build aus
    # dem Netz braucht, reicht einen eigenen Client mit MockTransport herein.
    def _kein_netz(request):
        raise httpx.ConnectError("Testsuite: kein Netz für pob_import", request=request)
    monkeypatch.setattr("poe_view.services.pob_import._http",
                        lambda: httpx.Client(transport=httpx.MockTransport(_kein_netz)))
    # Kein Gong aus der Testsuite (§kills_reminder): Ein Test, der die
    # Erinnerung einschaltet, soll prüfen, DASS sie klingt, nicht klingen.
    monkeypatch.setattr("poe_view.ui.kills_reminder.play_gong", lambda: None)
    # ... und kein Blick auf ein echtes, gerade laufendes Spielfenster:
    # Ob PoE nebenher offen ist, darf kein Testergebnis ändern.
    monkeypatch.setattr("poe_view.ui.kills_reminder.game_window_rect", lambda: None)
