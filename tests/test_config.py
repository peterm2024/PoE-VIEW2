"""Tests für die Konfiguration: CSV-Export-Pfad, .env-Auflösung in der
gepackten .exe und der User-Agent-Header (GGG-Pflichtformat)."""

import importlib
import re
import sys
from pathlib import Path

import dotenv

from poe_view import __version__, config


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


def test_user_agent_matches_ggg_required_format() -> None:
    """GGG schreibt exakt vor: 'OAuth {clientId}/{version} (contact: {contact})'
    (https://www.pathofexile.com/developer/docs)."""
    assert re.fullmatch(r"OAuth \S+/\S+ \(contact: [^@\s]+@[^@\s]+\)",
                        config.user_agent()), config.user_agent()
    assert f"/{__version__} " in config.user_agent()


def _reload_without_local_dotenv(monkeypatch) -> None:
    """config neu laden, ohne die .env des Entwicklers einzulesen.

    Ohne das würde der Test davon abhängen, was zufällig in der lokalen,
    gitignorten .env steht (``load_dotenv`` setzt Variablen, die noch nicht
    in der Umgebung stehen) — auf einem Rechner mit .env käme etwas anderes
    heraus als in der CI. ``config`` bindet ``load_dotenv`` beim (Neu-)Import
    frisch aus ``dotenv``, deshalb reicht es, dort zu patchen."""
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    importlib.reload(config)


def test_contact_email_falls_back_to_project_address_without_env(monkeypatch) -> None:
    """Nutzer einer fertigen .exe sollen NICHTS konfigurieren müssen — der
    Kontakt identifiziert laut GGG-Doku die Anwendung, nicht den Nutzer."""
    monkeypatch.delenv("POE_CONTACT_EMAIL", raising=False)
    _reload_without_local_dotenv(monkeypatch)
    try:
        assert config.CONTACT_EMAIL == config.DEFAULT_CONTACT_EMAIL
        assert "@" in config.DEFAULT_CONTACT_EMAIL
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_contact_email_can_be_overridden_via_env(monkeypatch) -> None:
    """Forks/Eigen-Distributionen sollen ihre eigene Adresse setzen können."""
    monkeypatch.setenv("POE_CONTACT_EMAIL", "fork@example.org")
    _reload_without_local_dotenv(monkeypatch)
    try:
        assert config.CONTACT_EMAIL == "fork@example.org"
        assert "(contact: fork@example.org)" in config.user_agent()
    finally:
        monkeypatch.undo()
        importlib.reload(config)
