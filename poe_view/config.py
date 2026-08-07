"""Zentrale Konfiguration: OAuth-Parameter, URLs, Pfade.

Intention: Alles Installations-Spezifische (v. a. die Kontakt-E-Mail) kommt
aus der lokalen `.env` und steht damit garantiert nicht im Repository.
Die konstanten OAuth-Werte sind in docs/api-notes/ggg-api.md dokumentiert.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from poe_view import __version__

if sys.platform == "win32":
    import winreg

# In einer PyInstaller-.exe zeigt __file__ in den temporären Entpackungs-
# ordner (sys._MEIPASS) — nicht dorthin, wo die eigentliche .exe liegt und
# der Nutzer seine .env hinlegen würde. `sys.frozen` (von PyInstaller
# gesetzt) erkennt diesen Fall; dann zählt das Verzeichnis der .exe selbst.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Mitgeliefertes (Icon o. Ä.) entpackt PyInstaller dagegen nach
# ``sys._MEIPASS`` — also gerade NICHT neben die .exe. Beide Pfade werden
# gebraucht und dürfen nicht verwechselt werden: ``PROJECT_ROOT`` für das,
# was der Nutzer selbst danebenlegt (.env), ``BUNDLE_DIR`` für das, was
# wir mitliefern. Ungepackt fallen beide auf dasselbe Verzeichnis zurück.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
APP_ICON = BUNDLE_DIR / "assets" / "PoE-VIEW2.ico"
# Einstufige Fassung fürs Hilfe-Fenster: Qts Rich Text nimmt aus einer
# mehrstufigen .ico nur die erste Stufe (16 px) und zeigt sie verwaschen.
APP_ICON_PNG = BUNDLE_DIR / "assets" / "PoE-VIEW2.png"

# --- OAuth2 (PKCE, public client — kein Secret) ---
CLIENT_ID = os.getenv("POE_CLIENT_ID", "poeview")

# Kontaktadresse für den User-Agent (GGG-Pflicht, siehe user_agent()).
# BEWUSST fest im Code und öffentlich: Laut GGG-Doku identifiziert dieses
# Feld die ANWENDUNG bzw. deren Betreiber, nicht den einzelnen Endnutzer —
# GGGs eigenes Beispiel ist ebenfalls eine feste App-Adresse. Nutzer einer
# fertigen .exe müssen deshalb nichts konfigurieren. Es ist ein eigens für
# dieses Projekt angelegter Alias, keine private Adresse (siehe
# FALLSTRICKE_UND_WORKAROUNDS.md #3). Wer PoE-VIEW2 forkt und selbst
# verteilt, sollte per .env die eigene Adresse setzen — dann landen
# GGG-Rückfragen zur eigenen Distribution auch beim richtigen Empfänger.
DEFAULT_CONTACT_EMAIL = "poeview2@gmx.net"
CONTACT_EMAIL = os.getenv("POE_CONTACT_EMAIL", "").strip() or DEFAULT_CONTACT_EMAIL
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
    """User-Agent im exakt von GGG vorgeschriebenen Format:
    ``OAuth {clientId}/{version} (contact: {contact})``
    (Quelle: https://www.pathofexile.com/developer/docs).

    ``CONTACT_EMAIL`` hat immer einen Wert (Default oben), der Header ist
    also nie unvollständig — auch nicht bei einer frisch ausgepackten .exe
    ohne jede Konfiguration.
    """
    return f"OAuth {CLIENT_ID}/{__version__} (contact: {CONTACT_EMAIL})"


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
