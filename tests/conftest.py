"""Pytest-Setup: Qt läuft in Tests headless (kein echtes Display nötig)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_real_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """MainWindow() löst sonst via BootstrapJob einen echten API-Call aus, falls ein gültiges Token im Credential Manager liegt (siehe FALLSTRICKE #6)."""
    monkeypatch.setattr("poe_view.services.token_store.load_token", lambda: None)
