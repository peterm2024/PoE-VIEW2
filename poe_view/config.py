"""Zentrale Konfiguration: OAuth-Parameter, URLs, Pfade.

Intention: Alles Installations-Spezifische (v. a. die Kontakt-E-Mail) kommt
aus der lokalen `.env` und steht damit garantiert nicht im Repository.
Alle konstanten OAuth-Werte stammen aus dem erprobten LabVIEW-Test-VI
(docs/api-notes/labview-test-vi.md).

LabVIEW-Äquivalent: Konfigurations-Cluster, beim Start aus externer Datei gelesen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from poe_view import __version__

if sys.platform == "win32":
    import winreg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- OAuth2 (PKCE, public client — kein Secret) ---
CLIENT_ID = os.getenv("POE_CLIENT_ID", "poeview")
CONTACT_EMAIL = os.getenv("POE_CONTACT_EMAIL", "").strip()
REDIRECT_PORT = 64338  # fest in der GGG-Client-Registrierung hinterlegt
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPES = "account:profile account:stashes account:characters account:leagues"
AUTHORIZE_URL = "https://www.pathofexile.com/oauth/authorize"
TOKEN_URL = "https://www.pathofexile.com/oauth/token"

# --- API ---
API_BASE = "https://api.pathofexile.com"

# --- Pfade (Caches/Logs liegen im Profil, nicht im Projekt) ---
APP_DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "PoE-VIEW2"
ICON_CACHE_DIR = APP_DATA_DIR / "icon-cache"
LOG_DIR = APP_DATA_DIR / "logs"

DISCLAIMER = "This product isn't affiliated with or endorsed by Grinding Gear Games in any way."


def user_agent() -> str:
    """User-Agent nach GGG-Vorgabe: 'OAuth {client_id}/{version} (contact: …)'.

    Die E-Mail ist Pflicht laut GGG-API-Regeln; ohne sie liefern wir einen
    Platzhalter, damit die App startet — der Login-Flow warnt dann sichtbar.
    """
    contact = CONTACT_EMAIL or "no-contact-configured"
    return f"OAuth {CLIENT_ID}/{__version__} (contact: {contact})"


def is_configured() -> bool:
    """True, wenn die lokale .env vollständig ist (Kontakt-E-Mail gesetzt)."""
    return bool(CONTACT_EMAIL) and "@" in CONTACT_EMAIL


def ensure_dirs() -> None:
    for d in (APP_DATA_DIR, ICON_CACHE_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


_DOWNLOADS_FOLDER_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"


def downloads_dir() -> Path:
    """Windows-'Downloads'-Ordner als Vorschlag für den CSV-Export.

    Liest den echten Speicherort aus der Registry, statt fest ``~/Downloads``
    anzunehmen — der User kann den Ordner unter Eigenschaften > Speicherort
    verschoben haben (z. B. auf ein anderes Laufwerk).
    """
    if sys.platform == "win32":
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                raw, _ = winreg.QueryValueEx(key, _DOWNLOADS_FOLDER_GUID)
            return Path(os.path.expandvars(raw))
        except OSError:
            pass
    return Path.home() / "Downloads"
