"""Test für config.downloads_dir() — Standardpfad für den CSV-Export."""

from pathlib import Path

from poe_view import config


def test_downloads_dir_returns_existing_path() -> None:
    path = config.downloads_dir()
    assert isinstance(path, Path)
    assert path.is_dir()
