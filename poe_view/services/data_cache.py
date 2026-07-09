"""Persistenter Datei-Cache: Charaktere/Stash/Items überleben einen Neustart.

Eine JSON-Datei statt einer Datenbank: Der Datenumfang (ein paar hundert
Items, ein paar Dutzend Charaktere) rechtfertigt keine Datenbank, und JSON
ist 1:1 nach LabVIEW portierbar (Flatten/Unflatten to JSON gibt es dort
nativ). Struktur und Items werden getrennt gehalten (``stash_trees`` /
``items_by_league``), weil die Stash-LISTE der API items grundsätzlich
leer liefert — items kommen ausschließlich aus dem Einzel-Tab-Endpunkt.

LabVIEW-Äquivalent: JSON-String via "Flatten to JSON" in eine Datei
schreiben (bei jeder relevanten Änderung) und beim Start mit
"Unflatten from JSON" wieder einlesen.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from poe_view import config
from poe_view.api.models import Character, Item, StashTab

log = logging.getLogger(__name__)

_CACHE_FILE = config.APP_DATA_DIR / "data-cache.json"


class CachedData:
    """Alles, was über einen Neustart hinweg erhalten bleiben soll."""

    def __init__(self) -> None:
        self.account_name: str = ""
        self.characters: list[Character] = []
        self.stash_trees: dict[str, list[StashTab]] = {}         # Liga → Baumstruktur
        self.items_by_league: dict[str, dict[str, list[Item]]] = {}  # Liga → {stash_id: Items}
        self.last_loaded: dict[str, dict[str, str]] = {}         # Liga → {stash_id: ISO-Zeitstempel}


def save(data: CachedData) -> None:
    """Schreibt einen vollständigen Snapshot; Fehler werden nur geloggt (kein Crash)."""
    payload = {
        "account_name": data.account_name,
        "characters": [c.model_dump(mode="json") for c in data.characters],
        "stash_trees": {
            league: [s.model_dump(mode="json") for s in tree]
            for league, tree in data.stash_trees.items()
        },
        "items_by_league": {
            league: {sid: [i.model_dump(mode="json") for i in items]
                     for sid, items in stashes.items()}
            for league, stashes in data.items_by_league.items()
        },
        "last_loaded": data.last_loaded,
    }
    try:
        config.ensure_dirs()
        _CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        log.exception("Daten-Cache: Schreiben fehlgeschlagen")


def load() -> CachedData | None:
    """None bei fehlender/kaputter Datei (z. B. allererster Start) — kein Fehler."""
    if not _CACHE_FILE.is_file():
        return None
    try:
        payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        data = CachedData()
        data.account_name = payload.get("account_name", "")
        data.characters = [Character.model_validate(c) for c in payload["characters"]]
        data.stash_trees = {
            league: [StashTab.model_validate(s) for s in tree]
            for league, tree in payload["stash_trees"].items()
        }
        data.items_by_league = {
            league: {sid: [Item.model_validate(i) for i in items]
                     for sid, items in stashes.items()}
            for league, stashes in payload["items_by_league"].items()
        }
        data.last_loaded = payload.get("last_loaded", {})
        _backfill_last_loaded(data)
        return data
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        log.exception("Daten-Cache: Lesen fehlgeschlagen — ignoriere Cache-Datei")
        return None


def _backfill_last_loaded(data: CachedData) -> None:
    """Migration für Cache-Dateien von VOR dem last_loaded-Feature (FALLSTRICKE #12).

    Tabs, deren Items im Cache liegen, aber keinen Zeitstempel haben, bekommen
    die mtime der Cache-Datei — die Daten sind höchstens so alt wie deren
    letzter Schreibvorgang. Ohne Backfill blieben solche Tabs für immer als
    "nie geladen" (⬇) markiert und für den Auto-Refresh unsichtbar.
    """
    mtime_iso = datetime.fromtimestamp(_CACHE_FILE.stat().st_mtime,
                                       tz=timezone.utc).isoformat()
    for league, stashes in data.items_by_league.items():
        league_loaded = data.last_loaded.setdefault(league, {})
        for stash_id in stashes:
            league_loaded.setdefault(stash_id, mtime_iso)
