"""Token-Speicherung im Windows Credential Manager (via ``keyring``).

Intention: Das Access-Token (10 h gültig) landet NIE als Klartext-Datei auf
der Platte und NIE im Repository. LabVIEW-Original nutzte eine externe Datei —
das hier ist das sicherere Pendant.
"""

from __future__ import annotations

import json
import logging
import time

import keyring

log = logging.getLogger(__name__)

_SERVICE = "PoE-VIEW2"
_ENTRY = "oauth-token"

# Puffer vor Ablauf: lieber 5 Minuten zu früh neu einloggen als mit
# abgelaufenem Token einen 401 kassieren.
_EXPIRY_MARGIN_S = 300


def save_token(token: dict) -> None:
    keyring.set_password(_SERVICE, _ENTRY, json.dumps(token))


def load_token() -> dict | None:
    try:
        raw = keyring.get_password(_SERVICE, _ENTRY)
    except Exception:
        log.exception("Credential Manager nicht erreichbar")
        return None
    return json.loads(raw) if raw else None


def delete_token() -> None:
    try:
        keyring.delete_password(_SERVICE, _ENTRY)
    except keyring.errors.PasswordDeleteError:
        pass


def is_valid(token: dict | None) -> bool:
    """Lokale Ablaufprüfung über obtained_at + expires_in (keine API-Anfrage)."""
    if not token or "access_token" not in token:
        return False
    obtained = float(token.get("obtained_at", 0))
    expires_in = float(token.get("expires_in", 0))
    return time.time() < obtained + expires_in - _EXPIRY_MARGIN_S
