"""Persistenter Preis-Cache mit TTL (docs/ARCHITEKTUR.md §4.14).

Ein voller poe.ninja-Abruf kostet ~30 Requests und ~1 MB — das lohnt sich
nicht bei jedem App-Start neu, zumal sich Preise nicht minütlich ändern.
Eine JSON-Datei pro Liga-Cache-Datei (wie ``data_cache.py``), keine
Datenbank: der Datenumfang (ein paar tausend Preis-Einträge) rechtfertigt
keine.
"""

from __future__ import annotations

import json
import logging
import time

from poe_view import config
from poe_view.api.ninja import PriceIndex

log = logging.getLogger(__name__)

_CACHE_FILE = config.APP_DATA_DIR / "price-cache.json"

# Preise bewegen sich über Stunden, nicht Minuten — 6h hält die Anzeige
# aktuell genug, ohne bei jedem Start unnötig ~1 MB nachzuladen.
TTL_SECONDS = 6 * 3600


def _index_to_payload(index: PriceIndex) -> dict:
    return {
        "simple": index._simple,
        "gems": {name: [list(variant) for variant in variants]
                for name, variants in index._gems.items()},
        "links": {name: {("base" if bucket is None else str(bucket)): chaos
                         for bucket, chaos in buckets.items()}
                 for name, buckets in index._links.items()},
    }


def _payload_to_index(payload: dict) -> PriceIndex:
    index = PriceIndex()
    index._simple.update(payload.get("simple", {}))
    index._gems = {
        name: [tuple(variant) for variant in variants]
        for name, variants in payload.get("gems", {}).items()
    }
    index._links = {
        name: {(None if bucket == "base" else int(bucket)): chaos
               for bucket, chaos in buckets.items()}
        for name, buckets in payload.get("links", {}).items()
    }
    return index


def save(league: str, index: PriceIndex) -> None:
    """Schreibt EINEN Liga-Eintrag; andere Ligen im Cache bleiben erhalten."""
    all_leagues = _read_raw()
    all_leagues[league] = {"fetched_at": time.time(), "prices": _index_to_payload(index)}
    try:
        config.ensure_dirs()
        _CACHE_FILE.write_text(json.dumps(all_leagues), encoding="utf-8")
    except OSError:
        log.exception("Preis-Cache: Schreiben fehlgeschlagen")


def load(league: str, ttl_seconds: float = TTL_SECONDS) -> PriceIndex | None:
    """None, wenn nichts gecacht ist ODER der Eintrag älter als die TTL —
    beide Fälle bedeuten für den Aufrufer dasselbe: neu abrufen."""
    entry = _read_raw().get(league)
    if entry is None:
        return None
    age = time.time() - entry.get("fetched_at", 0)
    if age > ttl_seconds:
        return None
    try:
        return _payload_to_index(entry["prices"])
    except (KeyError, TypeError, ValueError):
        log.exception("Preis-Cache: Eintrag für %s beschädigt — ignoriere ihn", league)
        return None


def _read_raw() -> dict:
    if not _CACHE_FILE.is_file():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("Preis-Cache: Lesen fehlgeschlagen — ignoriere Cache-Datei")
        return {}
