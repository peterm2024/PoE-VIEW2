"""Pytest-Setup: Qt läuft in Tests headless (kein echtes Display nötig)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_local_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Isoliert MainWindow() von echtem OAuth-Token (FALLSTRICKE #6) und echter data-cache.json."""
    monkeypatch.setattr("poe_view.services.token_store.load_token", lambda: None)
    monkeypatch.setattr("poe_view.services.data_cache._CACHE_FILE",
                        tmp_path / "unused-data-cache.json")
