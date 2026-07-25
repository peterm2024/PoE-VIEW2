"""Datei-Cache für Item-Icons (docs/ARCHITEKTUR.md §4.6).

Dateiname = SHA-1 der URL (URLs enthalten Query-Parameter und Sonderzeichen).
Vor jedem Download wird der Cache geprüft.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from poe_view import config

log = logging.getLogger(__name__)


def _path_for(url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return config.ICON_CACHE_DIR / f"{digest}.png"


def load(url: str) -> bytes | None:
    path = _path_for(url)
    if path.is_file():
        return path.read_bytes()
    return None


def save(url: str, data: bytes) -> None:
    try:
        _path_for(url).write_bytes(data)
    except OSError:
        log.exception("Icon-Cache: Schreiben fehlgeschlagen")
