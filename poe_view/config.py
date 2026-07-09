"""Zentrale Konfiguration: OAuth-Parameter, URLs, Pfade.

Intention: Alles Installations-Spezifische (v. a. die Kontakt-E-Mail) kommt
aus der lokalen `.env` und steht damit garantiert nicht im Repository.
Alle konstanten OAuth-Werte stammen aus dem erprobten LabVIEW-Test-VI
(docs/api-notes/labview-test-vi.md).

LabVIEW-Äquivalent: Konfigurations-Cluster, beim Start aus externer Datei gelesen.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from poe_view import __version__

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
