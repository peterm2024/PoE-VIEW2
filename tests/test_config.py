"""Test für config.downloads_dir() — Standardpfad für den CSV-Export."""

import importlib
import sys
from pathlib import Path

from poe_view import config


def test_downloads_dir_returns_existing_path() -> None:
    path = config.downloads_dir()
    assert isinstance(path, Path)
    assert path.is_dir()


def test_project_root_uses_executable_dir_when_frozen(monkeypatch, tmp_path) -> None:
    """Regression: In einer PyInstaller-.exe zeigt __file__ in den temporären
    Entpackungsordner (sys._MEIPASS), nicht dorthin, wo die .exe liegt und
    der Nutzer seine .env hinlegen würde — sonst würde eine gepackte .exe
    ihre eigene Konfiguration nie finden."""
    fake_exe = tmp_path / "PoE-VIEW2.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    importlib.reload(config)
    try:
        assert config.PROJECT_ROOT == tmp_path
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)
        importlib.reload(config)  # Modul-Zustand für nachfolgende Tests zurücksetzen
